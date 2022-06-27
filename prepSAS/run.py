"""
Simple script to run prepSAS from python
Nils Haentjens
Aug 18, 2021
"""
from prepSAS import Converter
import os
import logging
from time import time


logging.basicConfig(level=logging.DEBUG)

PATH_DATA = '/Users/nils/Data/EXPORTS2/pySAS_Scotts'
PATH_CFG = os.path.join(PATH_DATA,'cals','pysas_cfg.ini')
PATH_CAL = os.path.join(PATH_DATA,'cals','SAS045_2021.sip')
PATH_IN = os.path.join(PATH_DATA,'L0A')
PATH_OUT = os.path.join(PATH_DATA,'L0B_hourly.v1')
experiment='EXPORTS'
cruise='EXPORTSNA'

if __name__ == '__main__':
    tic = time()
    c = Converter(PATH_CAL, PATH_CFG)
    c.run(PATH_IN, PATH_OUT, mode='hour', file_out_prefix=f'{experiment}_{cruise}_', parallel=True)
    print(f'Run Time: {time() - tic} seconds')
