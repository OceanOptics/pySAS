import configparser
import os
import time
from pySAS.interfaces import IndexingTable, GPS, HyperSAS


class TestingProcedure:
    def __init__(self, cfg_filename=None):
        # Config Loader
        self.cfg = configparser.ConfigParser()
        self.cfg.read(cfg_filename)

        # Controllers & Sensors
        self.indexing_table = IndexingTable(self.cfg)
        self.hypersas = HyperSAS(self.cfg)

        # GPS Starts on initiation to obtain fix
        self.gps = GPS(self.cfg)
        self.gps.start()

    def start_sensors(self):
        """Starts sensors & logging, only starts GPS logger"""
        self.gps.start_logging()
        self.indexing_table.start()
        self.hypersas.start()

    def stop_sensors(self, stop_gps=False):
        """Stops sensors, with option to stop GPS & GPS Logger"""
        self.gps.stop_logging()
        if stop_gps:
            self.gps.stop()
        self.hypersas.stop()
        self.indexing_table.stop()


    def run(self, step_angle, trials=1, stop_gps=False):
        """Positions tower by step_angle degrees for user-set number of trials"""
        self.start_sensors()
        for i in range(trials):
            for j in range(-180, 181, step_angle):
                self.indexing_table.set_position(j, check_stall_flag=True)

                # This piece is to ensure the proper parsing of the HyperSAS data
                self.hypersas.parse_packets()
                print(self.hypersas.packet_THS_parsed)
                print(self.hypersas.packet_Li_dark_parsed)
                print(self.hypersas.packet_Li_parsed)

                time.sleep(3)

        self.stop_sensors(stop_gps)


if __name__ == "__main__":
    # Assumes testingProcedure is being launched from it's directory, otherwise enter path fo cfg_path
    # cfg_path =
    up_dir = os.path.dirname(os.getcwd())
    cfg_path = os.path.join(up_dir, 'pySAS/pysas_cfg.ini')
    tp = TestingProcedure(cfg_path)

    # Obtain GPS fix before running trials
    time.sleep(60)

    # Run configuration: run(step_angle, trials, stop_gps)
    # stop_gps should be True on last run
    tp.run(1)
    tp.run(5)
    tp.run(15, 2, True)


