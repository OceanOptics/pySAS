import configparser
import os
from pySAS.interfaces import IndexingTable, GPS, HyperSAS


class TestingProcedure:
    def __init__(self, cfg_filename=None):
        self.cfg = configparser.ConfigParser()
        self.cfg.read(cfg_filename)

        # Controllers & Sensors
        self.gps = GPS(self.cfg)
        self.indexing_table = IndexingTable(self.cfg)
        self.hypersas = HyperSAS(self.cfg)

    def start_sensors(self):
        self.gps.start()
        self.gps.start_logging()
        self.indexing_table.start()
        self.hypersas.start()

    def run(self):
        self.start_sensors()
        for i in range(10):
            for j in range(-180, 181):
                self.indexing_table.set_position(j, check_stall_flag=True)


if __name__ == "__main__":
    cfg_path = os.path.join(os.path.dirname(__file__), '..', 'pysas_cfg.ini')
    tp = TestingProcedure(cfg_path)
    tp.run()

