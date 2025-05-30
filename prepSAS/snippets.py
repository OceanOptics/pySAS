"""
Script to merge multiple Satlantic raw files together
Nils Haentjens
Nov 7, 2024
"""
import os
import glob
import logging
import warnings
from datetime import datetime, timezone, timedelta

from tqdm import tqdm
import pandas as pd

from prepSAS import Converter

logger = logging.getLogger(__name__)

# Define Paths
PATH_DATA = 'PATH_TO_DATA'  # PATH TO WORKING DIRECTORY
PATH_CFG = os.path.join(PATH_DATA, 'cals', 'pysas_cfg.ini')  # pySAS configuration file
PATH_CAL = os.path.join(PATH_DATA, 'cals', 'SAS+Es+IMU.Core+GPS+UMTWR.20230203.sip')  # pySAS calibration files (with THS, UMTWR, GPS)
PATH_IN = os.path.join(PATH_DATA,'L0A')
PATH_OUT = os.path.join(PATH_DATA,'L0B')
experiment='EXPERIMENT_NAME'  # Follow SeaBASS Convention
cruise='CRUISE_NAME'  # Follow SeaBASS Convention

# %% Function to adjust SAS angle in case of poor alignment during data acquisition
def correct_sas_angle(d, offset=+16, end_dt=datetime(2024, 10, 30, 22, 50, 00, tzinfo=timezone.utc)):
    sel = (d.header == b'UMTWR') & (d.timestamp < end_dt)
    if sum(sel) == 0:
        return
    def fun(x):
        try:
            s = x.decode(errors='ignore').split(',', 2)
            s[1] = f'{(float(s[1]) + offset) % 360:.2f}'
            return ','.join(s).encode()
        except ValueError:
            return x
    d.loc[sel, 'frame'] = d[sel].frame.apply(fun)

# %% Group raw files per day
groups = {}
for f in sorted(glob.glob(os.path.join(PATH_IN, '*.raw'))):
    ref = os.path.splitext(os.path.basename(f))[0]
    foo = ref.split('_')
    d = foo[1]
    if d in groups:
        groups[d].append(f)
    else:
        groups[d] = [f]

# %% Merge files
c = Converter(PATH_CAL, PATH_CFG)
with warnings.catch_warnings():
    warnings.filterwarnings('ignore', 'Downcasting behavior in `replace`')
    for date, group in groups.items():
        d = []
        logger.info(date)
        for f in group:
            d.append(c.read_sat(f))
        d = pd.concat(d).sort_values(by=['timestamp'], ignore_index=True)
        # Correct SAS angle if needed
        # correct_sas_angle(d)
        # Hourly File Output (preferred for HyperCP processing due to statistics computation within HyperCP)
        dt_start = d.timestamp.min().replace(minute=0, second=0, microsecond=0)
        dt_end = d.timestamp.max() + timedelta(seconds=1)
        window = timedelta(hours=1)
        dt_format = '%Y%m%d_%H%M%S'
        dt = dt_start
        while dt < dt_end:
            sel = (dt <= d.timestamp) & (d.timestamp < dt + window)
            if sel.any():
                c.write(d[sel], os.path.join(PATH_OUT, f'{experiment}_{cruise}_{dt.strftime(dt_format)}.raw'))
            dt += window
        # Daily File Output (avoid for HyperCP processing)
        # c.write(d, os.path.join(PATH_OUT, f'{experiment}_{cruise}_{date}.raw'))

# %% Inspect files for missing data
c = Converter(PATH_CAL, PATH_CFG)
for filename in sorted(glob.glob('*.raw', root_dir=PATH_IN)):
    df = c.read_sat(os.path.join(PATH_IN, filename))
    print(filename)
    print(df.groupby(df.header)['timestamp'].nunique())
    break

# %% Replace double commas in SATTHS1500 header (bug in pySAS 1.0.0 with BNO085)
for filename in sorted(glob.glob('*.raw', root_dir=PATH_IN)):
    df = c.read_sat(os.path.join(PATH_IN, filename))
    for i, row in df.iterrows():
        if row.header == b'SATTHS1500':
            df.frame[i] = row.frame.replace(b',,', b',')
    c.write(df, os.path.join(PATH_OUT, filename))

# %% Parse frames with pySatlantic (beyond splitting frames)
import pySatlantic.instrument as pySat

parser = pySat.Instrument(PATH_CAL)
# parser.parse_frame(df.loc[20, 'frame'])
print(f'Timestamp is monotonic: {df.timestamp.sort_values().index.is_monotonic_increasing}')
for i, row in tqdm(df.iterrows(), total=len(df)):
    frame = c.parser.parse_frame(row.frame, row.header.decode(), flag_get_auxiliary_variables=True, flag_get_unusable_variables=True)

