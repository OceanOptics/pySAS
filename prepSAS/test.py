import unittest
import glob, os


PATH_SAT = 'test_data/pySAS002/HyperSAS_20201120_175620.bin'
PATH_GPS = 'test_data/pySAS002/GPS_20201120_175616.csv'
PATH_TWR = 'test_data/pySAS002/IndexingTable_20201120_175616.csv'
PATH_OUT = 'test_data/pySAS002/UMSAS002_20201120_175620.raw'
PATH_DIR = 'test_data/pySAS002/'
# PATH_DIR = '/Users/nils/Documents/Lab/HyperSAS/FieldTests/data/pySAS002_data'  # 1 month office data set

PATH_CFG = 'test_data/pySAS002/pysas_cfg_002.ini'
# PATH_CAL = 'test_data/pySAS002/HyperSAS_Es_20200212.sip'

PATH_TO_CAL = 'test_data/cal'
PATH_TO_DATA = sorted(glob.glob(os.path.join(PATH_DIR, 'pySAS*.raw')))


class TestPrepSASRun(unittest.TestCase):

    def test_run(self):
        import logging
        logging.basicConfig(level=logging.DEBUG)
        from prepSAS import Converter

        e = Converter(PATH_TO_CAL, PATH_CFG)
        e.run(PATH_SAT, PATH_GPS, PATH_TWR, PATH_OUT)

    def test_run_dir(self):
        import logging
        logging.basicConfig(level=logging.DEBUG)
        from prepSAS import Converter

        e = Converter(PATH_TO_CAL, PATH_CFG)
        e.run_dir(PATH_DIR, PATH_DIR, 'all')
        e.run_dir(PATH_DIR, PATH_DIR, 'day', False)
        e.run_dir(PATH_DIR, PATH_DIR, 'hour', False)


class TestPrepSASOutput(unittest.TestCase):

    def test_parse_pysas_raw(self):
        from pySatlantic.instrument import SatViewRawToCSV
        from multiprocessing import Pool

        converter = SatViewRawToCSV(PATH_TO_CAL)
        with Pool() as pool:
            pool.map(converter.run, PATH_TO_DATA)
        # for file in PATH_TO_DATA:
        #     converter.run(file)


if __name__ == "__main__":
    unittest.main()
