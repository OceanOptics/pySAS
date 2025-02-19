"""
Script to merge multiple Satlantic raw files together
Nils Haentjens
Nov 7, 2024
"""
import os
import glob
import logging
import warnings
from datetime import datetime, timezone

from tqdm import tqdm
import pandas as pd

from prepSAS import Converter

logger = logging.getLogger(__name__)

# Define Paths
PATH_DATA = '/Users/nils/Data/SOPACE/KM24/'
PATH_CFG = '/Users/nils/Data/EXPORTS2/pySAS_Scotts/cals/pysas_cfg.ini'  # Not needed
PATH_CAL = os.path.join(PATH_DATA,'cals','HyperSAS+GPS+TWR.Chase.20240320.sip')
PATH_IN = os.path.join(PATH_DATA,'L0A')
PATH_OUT = os.path.join(PATH_DATA,'L0B_corr')
experiment='PVST-SOPACE'
cruise='KM24'

# %% Correction specific to SOPACE-KM24
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
        correct_sas_angle(d)
        c.write(d, os.path.join(PATH_OUT, f'{experiment}_{cruise}_{date}.raw'))
