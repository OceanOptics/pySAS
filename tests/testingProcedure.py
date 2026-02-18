import configparser
from time import sleep, time
from pySAS.interfaces import IndexingTable, GPS, HyperSAS, IMU


class SlowIndexingTable(IndexingTable):

    def set_configuration(self):
        self._serial.write(b'\x03')  # ctrl+c for resetting motor  # TODO Might Loose zero position due to that
        self._log_data.write([float('nan'), 'nan', 'set_cfg'], time())
        sleep(0.5)                   # Reset takes longer than standard COMMAND_EXECUTION_TIME
        # Settings motor configuration
        self._serial.write(bytes('ee=1' + self.TERMINATOR, self.ENCODING))  # First command so no need for registration (backspace)
        sleep(self.COMMAND_EXECUTION_TIME)
        self._serial.write(bytes(self.REGISTRATOR + 'a=20000' + self.TERMINATOR, self.ENCODING))
        sleep(self.COMMAND_EXECUTION_TIME)
        self._serial.write(bytes(self.REGISTRATOR + 'd=20000' + self.TERMINATOR, self.ENCODING))
        sleep(self.COMMAND_EXECUTION_TIME)
        self._serial.write(bytes(self.REGISTRATOR + 'vi=78' + self.TERMINATOR, self.ENCODING))
        sleep(self.COMMAND_EXECUTION_TIME)
        self._serial.write(bytes(self.REGISTRATOR + 'vm=2000' + self.TERMINATOR, self.ENCODING))
        sleep(self.COMMAND_EXECUTION_TIME)
        self._serial.write(bytes(self.REGISTRATOR + 'em=1' + self.TERMINATOR, self.ENCODING))
        sleep(self.COMMAND_EXECUTION_TIME)
        # Log initialization
        msg = self._serial_read()
        if msg:
            self.eng_log.debug(msg.decode(self.ENCODING, self.UNICODE_HANDLING))


class TestingProcedure:
    def __init__(self, cfg_filename=None):
        # Config Loader
        self.cfg = configparser.ConfigParser()
        self.cfg.read(cfg_filename)

        # Controllers & Sensors
        self.indexing_table = SlowIndexingTable(self.cfg)
        self.hypersas = HyperSAS(self.cfg)

        # GPS Starts on initiation to obtain fix
        self.gps = GPS(self.cfg)
        self.gps.start()

        self.imu = IMU(self.cfg)

    def start_sensors(self):
        """Starts sensors & logging, only starts GPS logger"""
        self.gps.start_logging()
        self.imu.start()
        self.indexing_table.start()
        self.hypersas.start()

    def stop_sensors(self, stop_gps=False, stop_IMU=False):
        """Stops sensors, with option to stop GPS & GPS Logger"""
        self.gps.stop_logging()
        if stop_gps:
            self.gps.stop()
        if stop_IMU:
            self.imu.stop()
        self.hypersas.stop()
        self.indexing_table.stop()


    def run(self, rotations=1, stop_gps=False):
        """Positions tower by step_angle degrees for user-set number of trials"""
        self.start_sensors()
        for i in range(rotations):
            self.indexing_table.set_position(-180, check_stall_flag=True)
            self.indexing_table.set_position(180, check_stall_flag=True)
            self.indexing_table.set_position(0, check_stall_flag=True)
        self.stop_sensors(stop_gps)


    def zero_run(self):
        """Used to provide accurate zero for validation"""
        self.gps.start_logging()
        for i in range(180):
            print("Fix Type: " + str(self.gps.fix_type) + "\t Time left: "+str(180-i)+" s")
            sleep(1)
        self.gps.stop_logging()


if __name__ == "__main__":
    # Assumes testingProcedure is being launched from it's directory, otherwise enter path fo cfg_path
    # cfg_path =
    #up_dir = os.path.dirname(os.getcwd())
    cfg_path = 'pySAS/pysas_cfg.ini'
    tp = TestingProcedure(cfg_path)

    #Start Countdown
    for i in range(30):
        print(str(30-i))
        sleep(1)

    # Run configuration: run(step_angle, trials, stop_gps)
    tp.zero_run()
    tp.run(5)
    tp.run(5)
    tp.run(5)
