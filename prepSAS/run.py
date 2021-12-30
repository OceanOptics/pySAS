"""
Simple script to run prepSAS from python
Nils Haentjens
Aug 18, 2021
"""
from prepSAS import Converter
import os
import logging


logging.basicConfig(level=logging.INFO)

PATH_DATA = '/Users/nils/Data/EXPORTS2/pySAS_Scotts'
PATH_CFG = os.path.join(PATH_DATA,'cals','pysas_cfg.ini')
PATH_CAL = os.path.join(PATH_DATA,'cals','SAS045_2021.sip')
PATH_IN = os.path.join(PATH_DATA,'L0A_end')
PATH_OUT = os.path.join(PATH_DATA,'L0B_hourly')
experiment='EXPORTS'
cruise='EXPORTSNA'

## Build object using cals and config
c = Converter(PATH_CAL, PATH_CFG)

c.run_dir(PATH_IN, PATH_OUT, mode='hour', parallel=False, file_out_prefix=f'{experiment}_{cruise}_')