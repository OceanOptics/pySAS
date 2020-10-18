from serial import Serial, SerialException
from timeit import default_timer
from time import sleep, time
from datetime import datetime
from math import isnan
from threading import Thread, Lock
import logging
from pySAS.log import Log, LogBinary, pack_timestamp_satlantic
from gpiozero import OutputDevice
from gpiozero.pins.mock import MockFactory  # required for virtual hardware
from gpiozero.exc import BadPinFactory
import os
from ubxtranslator.core import Parser as UBXParser
from pySAS.ubxtranslator_messages import NAV_ARDUSIMPLE
from configparser import NoOptionError
import pytz
from pySatlantic.instrument import Instrument as SatlanticParser
from pySatlantic.instrument import FrameError as SatlanticFrameError
from pySatlantic.instrument import CalibrationFileError as SatlanticCalibrationFileError
import atexit


def get_serial_instance(interface, cfg):
    s = Serial()
    s.port = cfg.get(interface, 'port')
    s.baudrate = cfg.getint(interface, 'baudrate')
    s.bytesize = cfg.getint(interface, 'bytesize', fallback=8)
    s.parity = cfg.get(interface, 'parity', fallback='N')
    s.stopbits = cfg.getfloat(interface, 'stopbits', fallback=1)
    s.timeout = cfg.getfloat(interface, 'timeout', fallback=10)
    s.xonxoff = cfg.getboolean(interface, 'xonxoff', fallback=False)
    s.rtscts = cfg.getboolean(interface, 'rtscts', fallback=False)
    s.write_timeout = cfg.getfloat(interface, 'write_timeout', fallback=None)
    s.dsrdtr = cfg.getboolean(interface, 'dsrdtr', fallback=False)
    return s


class IndexingTable:
    """
    Python Interface to custom made indexing table. The indexing table is made of a Lexium MDrive LMD M85 which is
    communicating over RS485. The drive is interprets M-Code and must be set with local echo disabled (em=1).

    """
    GEAR_BOX_RATIO = 200000 / 360
    POSITION_LIMITS = [-180, 180]
    MOTION_TIMEOUT = 10  # seconds

    COMMAND_EXECUTION_TIME = 0.05
    ENCODING = 'latin-1'
    REGISTRATOR = '\x08'  # Backspace
    TERMINATOR = '\r\n'   # CR LF (\x0D\x0A)
    UNICODE_HANDLING = 'replace'

    def __new__(cls, *args, **kwargs):
        """
        Create new instance of IndexingTable for each serial port
            if serial port already used in an instance then return that instance
            otherwise return new instance
        """
        if not hasattr(cls, '_instances'):
            cls._instances = []
        # Capture port argument
        if 'cfg' in kwargs:
            cfg = kwargs['cfg']
        elif len(args) > 0:
            cfg = args[0]
        port = cfg.get(cls.__name__, 'port')
        for i in cls._instances:
            if i._serial_port == port:
                return i
        cls._instances.append(super(IndexingTable, cls).__new__(cls))
        return cls._instances[-1]

    def __init__(self, cfg):
        # Prevent re-init if asking for second instance
        if hasattr(self, '_serial_port'):
            self.__logger.debug(self.__class__.__name__ + ' already initialized for port ' + self._serial_port)
            return
        self._serial_port = cfg.get(self.__class__.__name__, 'port')
        # Loggers
        self.__logger = logging.getLogger(self.__class__.__name__)
        self._log_data = Log({'filename_prefix': self.__class__.__name__,
                              'path': cfg.get(self.__class__.__name__, 'path_to_data',
                                              fallback=os.path.join(os.path.dirname(__file__), 'data')),
                              'length': cfg.getint(self.__class__.__name__, 'file_length', fallback=60),
                              'variable_names': ['position', 'stall_flag', 'type'],
                              'variable_units': ['degrees', '1:stalled | 0:ok', 'get|set|reset'],
                              'variable_precision': ['%.2f', '%s', '%s']})
        # Serial
        self._serial = get_serial_instance(self.__class__.__name__, cfg)
        # GPIO
        try:
            # Try to load physical pin factory (Factory())
            self._relay = OutputDevice(cfg.getint(self.__class__.__name__, 'relay_gpio_pin'),
                                       active_high=False, initial_value=False)
        except BadPinFactory:
            # No physical gpio library installed, likely running on development platform
            self.__logger.warning('Loading GPIO Mock Factory')
            self._relay = OutputDevice(cfg.getint(self.__class__.__name__, 'relay_gpio_pin'),
                                       active_high=False, initial_value=False, pin_factory=MockFactory())
        # Configuration variables specific to motor
        self.rotation_ispeed = 0.02778    # sec / deg
        self.rotation_delay = 0.1331 * 2  # sec (start and stop)
        # Variables for UI
        self.alive = False
        self.stalled = False
        self.position = float('nan')
        # Register methods to execute at exit as cannot use __del__ as logging is already off-loaded
        atexit.register(self.stop)

    def start(self):
        if not self.alive:
            self.__logger.debug('start')
            self._relay.on()
            sleep(self.COMMAND_EXECUTION_TIME)
            try:
                self._serial.open()
            except SerialException as e:
                self.__logger.critical(e)
                self._relay.off()
                return False
            self.set_configuration()
            self.alive = True
            self.get_position()
            return True

    def set_configuration(self):
        self._serial.write(b'\x03')  # ctrl+c for resetting motor  # TODO Might Loose zero position due to that
        self._log_data.write([float('nan'), 'nan', 'set_cfg'], time())
        sleep(0.5)                   # Reset takes longer than standard COMMAND_EXECUTION_TIME
        # Settings motor configuration
        self._serial.write(bytes('ee=1' + self.TERMINATOR, self.ENCODING))  # First command so no need for registration (backspace)
        sleep(self.COMMAND_EXECUTION_TIME)
        self._serial.write(bytes(self.REGISTRATOR + 'a=78125' + self.TERMINATOR, self.ENCODING))
        sleep(self.COMMAND_EXECUTION_TIME)
        self._serial.write(bytes(self.REGISTRATOR + 'd=78125' + self.TERMINATOR, self.ENCODING))
        sleep(self.COMMAND_EXECUTION_TIME)
        self._serial.write(bytes(self.REGISTRATOR + 'vi=78' + self.TERMINATOR, self.ENCODING))
        sleep(self.COMMAND_EXECUTION_TIME)
        self._serial.write(bytes(self.REGISTRATOR + 'vm=20000' + self.TERMINATOR, self.ENCODING))
        sleep(self.COMMAND_EXECUTION_TIME)
        self._serial.write(bytes(self.REGISTRATOR + 'em=1' + self.TERMINATOR, self.ENCODING))
        sleep(self.COMMAND_EXECUTION_TIME)
        # Log initialization
        msg = self._serial_read()
        if msg:
            self.__logger.debug(msg.decode(self.ENCODING, self.UNICODE_HANDLING))

    def set_position(self, position_degrees, check_stall_flag=False):
        # The stall flag must be checked after using the set_position function
        # to make sure the motion was done without issues.
        # This can be done by setting the argument check_stall_flag = True
        if not self.alive:
            self.__logger.error('set_position: unable, not alive')
            return False
        if position_degrees < self.POSITION_LIMITS[0] or self.POSITION_LIMITS[1] < position_degrees:
            self.__logger.error('set_position: unable, position out of range ' + str(position_degrees))
            return False
        self.__logger.debug('set_position(' + str(position_degrees) + ', ' + str(check_stall_flag) + ')')
        pos_steps = int(position_degrees * self.GEAR_BOX_RATIO)
        self._serial.write(bytes(self.REGISTRATOR + 'ma ' + str(pos_steps) + self.TERMINATOR, self.ENCODING))
        if check_stall_flag:
            # Wait till the tower stops moving
            start_time = time()
            pre_pos = self.get_position()
            if isnan(pre_pos):  # Unable to read position
                return False
            sleep(self.COMMAND_EXECUTION_TIME)
            while pre_pos != self.get_position() and time() - start_time < self.MOTION_TIMEOUT:
                pre_pos = self.position
                sleep(self.COMMAND_EXECUTION_TIME)
            if self.get_stall_flag():
                self.__logger.warning('stalled while moving to ' + str(position_degrees))
                return False
        else:
            self.position = position_degrees
        self._log_data.write([position_degrees, 'nan', 'set'], time())
        return True

    def get_position(self):
        if not self.alive:
            self.__logger.error('get_position: unable, not alive')
            self.position = float('nan')
            return self.position
        # self.__logger.debug('get_position()')
        # Flush serial buffer
        self._serial_read()
        # Ask current position of encoder to motor
        self._serial.write(bytes(self.REGISTRATOR + 'pr p' + self.TERMINATOR, self.ENCODING))
        # Wait for answer
        sleep(self.COMMAND_EXECUTION_TIME)
        # Read answer
        msg = self._serial_read()
        if msg is not None:
            try:
                pos_steps = int(msg.decode(self.ENCODING, self.UNICODE_HANDLING).strip())
                self.position = pos_steps / self.GEAR_BOX_RATIO
            except ValueError or UnicodeDecodeError:
                self.__logger.error('unable to parse position')
                self.position = float('nan')
            finally:
                self._log_data.write([self.position, 'nan', 'get'], time())
                return self.position
        else:
            self.__logger.error('unable to get position')
            self.position = float('nan')
            return self.position

    def get_stall_flag(self):
        """
        Read stall flag using the read_flag method

        :return: False: Motor did not stall
                 True:  Motor stalled
        """
        self.stalled = self.get_flag('st')
        if self.stalled:
            self.__logger.debug('STALLED')
        self._log_data.write([float('nan'), self.stalled, 'nan'], time())
        return self.stalled

    def get_flag(self, flag_name):
        """
        Read flag requested

        :param flag_name: name of flag requested
        :return: True (1) or False (0)
        """
        if not self.alive:
            self.__logger.error('get_flag: unable, not alive')
            return
        self.__logger.debug('get_flag(' + str(flag_name) + ')')

        # Flush serial buffer
        self._serial_read()
        # Ask stall flag to motor
        self._serial.write(bytes(self.REGISTRATOR + 'pr ' + flag_name + self.TERMINATOR, self.ENCODING))
        sleep(self.COMMAND_EXECUTION_TIME)
        # Get answer
        msg = self._serial_read()
        if msg is not None:
            try:
                flag = int(msg.decode(self.ENCODING, self.UNICODE_HANDLING).strip())
            except ValueError or UnicodeDecodeError:
                self.__logger.error('unable to parse flag ' + flag_name)
                return None
            return bool(flag)
        else:
            self.__logger.error('unable to get flag ' + flag_name)
            return None

    def print_all_parameters(self):
        if not self.alive:
            self.__logger.error('print_all_parameters: unable, not alive')
            return
        self.__logger.debug('print_all_parameters')
        # Flush serial buffer
        self._serial_read()
        # Ask stall flag to motor
        self._serial.write(bytes(self.REGISTRATOR + 'pr al' + self.TERMINATOR, self.ENCODING))
        sleep(2)  # much longer than the standard COMMAND_EXECUTION_TIME
        # Get answer
        msg = self._serial_read()
        if msg is not None:
            print(msg.decode(self.ENCODING, self.UNICODE_HANDLING).strip())
        else:
            self.__logger.error('unable to read parameters')

    def reset_position_zero(self):
        if not self.alive:
            self.__logger.error('reset_position_zero: unable, not alive')
            return
        self.__logger.info('reset zero')
        self._serial.write(bytes(self.REGISTRATOR + 'p=0' + self.TERMINATOR, self.ENCODING))
        self.position = 0
        self._log_data.write([0, 'nan', 'reset'], time())

    def reset_stall_flag(self):
        if not self.alive:
            self.__logger.error('reset_stall_flag: unable, not alive')
            return
        self.__logger.warning('reset stall flag')
        self._serial.write(bytes(self.REGISTRATOR + 'st=0' + self.TERMINATOR, self.ENCODING))
        self.stalled = False
        self._log_data.write([float('nan'), False, 'reset'], time())

    def measure_motion_speed(self, test_position=360, timeout=20, delta_position=0.01):
        if not self.alive:
            self.__logger.error('measure_motion_speed: unable, not alive')
            return
        self.__logger.debug('measure_motion_speed()')
        start_position = self.get_position()
        start_clock = default_timer()
        self.set_position(test_position)
        cur_clock, pos = [0], [start_position]
        while abs(pos[-1] - test_position) > delta_position and cur_clock[-1] < timeout:
            cur_clock.append(default_timer() - start_clock)
            pos.append(self.get_position())
            # print(cur_clock, pos)
        stop_clock = default_timer()
        return abs(test_position - start_position) / (stop_clock - start_clock), cur_clock, pos

    def estimate_motion_time(self, current_position_degrees, aimed_position_degrees):
        # TODO Updated Model
        #  https://motion.schneider-electric.com/application-note/intro-mcode-basic-motion-commands/
        if not self.alive:
            self.__logger.error('estimate_motion_time: unable, not alive')
            return
        self.__logger.debug('estimate_motion_time()')
        if current_position_degrees is not None and aimed_position_degrees is not None:
            return self.rotation_ispeed * abs(aimed_position_degrees - current_position_degrees) \
                   + self.rotation_delay
        else:
            return None

    def _serial_read(self):
        if self._serial.in_waiting > 0:
            return self._serial.read(self._serial.in_waiting)
        else:
            return None

    def stop(self):
        self.__logger.debug('stop')
        if self.alive:
            # Get stall flag (and reset if necessary)
            self.get_stall_flag()
            if self.stalled is not None: # Can read stall flag and communicate
                if self.stalled:
                    self.reset_stall_flag()
                # Move indexing table back to 0
                self.set_position(0, check_stall_flag=True)
            # Close log
            self._log_data.close()
            # Stop serial connection
            if hasattr(self._serial, 'cancel_read'):
                self._serial.cancel_read()
            if self._serial.is_open:
                self._serial.close()
            # Stop Power
            self._relay.off()
            self.alive = False


class Sensor:

    def __new__(cls, *args, **kwargs):
        """
        Create new instance of Sensor for each serial port
            if serial port already used in an instance then return that instance
            otherwise return new instance
        """
        if not hasattr(cls, '_instances'):
            cls._instances = []
        # Capture port argument
        if 'cfg' in kwargs:
            cfg = kwargs['cfg']
        elif len(args) > 0:
            cfg = args[0]
        port = cfg.get(cls.__name__, 'port')
        for i in cls._instances:
            if i._serial_port == port:
                return i
        cls._instances.append(super(Sensor, cls).__new__(cls))
        return cls._instances[-1]

    def __init__(self, cfg):
        # Prevent re-init if asking for second instance
        if hasattr(self, '_serial_port'):
            self.__logger.debug(self.__class__.__name__ + ' already initialized for port ' + self._serial_port)
            return
        self._serial_port = cfg.get(self.__class__.__name__, 'port')
        # Loggers
        self.__logger = logging.getLogger(self.__class__.__name__)
        self._data_logger = Log({'filename_prefix': self.__class__.__name__,
                                 'path': cfg.get(self.__class__.__name__, 'path_to_data',
                                                 fallback=os.path.join(os.path.dirname(__file__), 'data')),
                                 'length': cfg.getint(self.__class__.__name__, 'file_length', fallback=60)})
        # Serial
        self._serial = get_serial_instance(self.__class__.__name__, cfg)
        # GPIO
        try:
            # Try to load physical pin factory (Factory())
            self._relay = OutputDevice(cfg.getint(self.__class__.__name__, 'relay_gpio_pin'),
                                       active_high=False, initial_value=False)
        except BadPinFactory:
            # No physical gpio library installed, likely running on development platform
            self.__logger.warning('Loading GPIO Mock Factory')
            self._relay = OutputDevice(cfg.getint(self.__class__.__name__, 'relay_gpio_pin'),
                                       active_high=False, initial_value=False, pin_factory=MockFactory())
        # Thread
        self._thread = None
        self.alive = False
        # Register methods to execute at exit as cannot use __del__ as logging is already off-loaded
        atexit.register(self.stop)

    def start(self):
        if not self.alive:
            self.__logger.debug('start')
            self._relay.on()
            sleep(0.5)  # Leave time for sensor to turn on
            try:
                self._serial.open()
            except SerialException as e:
                self.__logger.critical(e)
                self._relay.off()
                return
            self.alive = True
            self._thread = Thread(name=self.__class__.__name__, target=self.run)
            self._thread.daemon = True
            self._thread.start()

    def stop(self, from_thread=False):
        self.__logger.debug('stop')
        if self.alive:
            self.alive = False
            if hasattr(self._serial, 'cancel_read'):
                self._serial.cancel_read()
            # TODO Find elegant way to immediatly stop thread as slow down user interface when switching from auto to manual mode
            if not from_thread:
                self._thread.join(2)
                if self._thread.is_alive():
                    self.__logger.error('Thread did not join.')
            self._serial.close()
            self._relay.off()
            self._data_logger.close()  # Required to start new log_data file when instrument restart


class GPS(Sensor):

    def __init__(self, cfg):
        super().__init__(cfg)
        self.__logger = logging.getLogger(self.__class__.__name__)  # Need to recall logger as it's private

        # Update loggers
        self._data_logger = Log({'filename_prefix': self.__class__.__name__,
                                 'path': cfg.get(self.__class__.__name__, 'path_to_data',
                                                 fallback=os.path.join(os.path.dirname(__file__), 'data')),
                                 'length': cfg.getint(self.__class__.__name__, 'file_length', fallback=60),
                                 'variable_names': ['gps_datetime', 'datetime_accuracy', 'datetime_valid',
                                                     'heading', 'heading_accuracy', 'heading_valid',
                                                     'heading_motion', 'heading_vehicle',
                                                     'heading_vehicle_accuracy', 'heading_vehicle_valid',
                                                     'speed', 'speed_accuracy',
                                                     'latitude', 'longitude', 'horizontal_accuracy',
                                                     'altitude','altitude_accuracy',
                                                     'fix_ok', 'fix_type', 'last_packet'],
                                 'variable_units': ['yyyy-mm-dd HH:MM:SS.us', 'us', 'bool',
                                                    'deg', 'deg', 'bool',
                                                    'deg', 'deg', 'deg', 'bool',
                                                    'm/s ground', 'm/s',
                                                    'deg N', 'deg E', 'm', 'm MSL', 'm',
                                                    'bool',
                                                    '0: no_fix; 1: DR; 2: 2D-fix; 3: 3D-fix; 4: GNSS+DR; 5: time_only',
                                                    'name'],
                                 'variable_precision': ['%s', '%d', '%s',
                                                        '%.5f', '%.5f', '%s',
                                                        '%.5f', '%.5f', '%.5f', '%s',
                                                        '%.3f', '%.3f',
                                                        '%.7f', '%.7f', '%.3f', '%.3f', '%.3f',
                                                        '%s', '%d', '%s']})
        self._data_logger_lock = Lock()
        self._log_data = False
        self._gps_orientation_on_ship = cfg.getint(self.__class__.__name__, 'orientation', fallback=0)
        self._parser = UBXParser([NAV_ARDUSIMPLE])
        self.packet_pvt_received = float('nan')
        self.packet_relposned_received = float('nan')

        # Variables
        self.datetime = None
        self.datetime_accuracy = -1
        self.datetime_valid = False                   # Confirmed Date and Time
        # Heading: relative (default, 2 GPS), motion, vehicle
        self.heading = float('nan')                   # relative heading (based on 2nd GPS antenna)
        self.heading_accuracy = float('nan')          # relative heading accuracy
        self.heading_valid = False                    # relative heading flag
        self.heading_motion = float('nan')
        self.heading_vehicle = float('nan')
        self.heading_vehicle_accuracy = float('nan')  # motion and vehicle heading accuracy
        self.heading_vehicle_valid = False
        # Speed (to know if heading_motion is more likely correct)
        self.speed = float('nan')
        self.speed_accuracy = float('nan')
        # Position
        self.latitude = float('nan')
        self.longitude = float('nan')
        self.horizontal_accuracy = float('nan')
        self.altitude = float('nan')                  # altitude above MSL (m)
        self.altitude_accuracy = float('nan')
        self.fix_ok = False
        self.fix_type = 0
        # 0: no_fix
        # 1: dead_reckoning
        # 2: 2D-fix
        # 3: 3D-fix
        # 4: GNSS + dead reckoning
        # 5: time only

    def start_logging(self):
        if not self._log_data:
            self.__logger.debug('start logging')
            if not self.alive:
                self.__logger.info('not alive')
            self._log_data = True

    def stop_logging(self):
        if self._log_data:
            self.__logger.debug('stop logging')
            self._log_data = False
            if self._data_logger_lock.acquire(timeout=2):
                try:
                    self._data_logger.close()
                finally:
                    self._data_logger_lock.release()
            else:
                self.__logger.warning('Unable to acquire data_logger to close file')

    def run(self):
        while self.alive:
            try:
                packet = self._parser.receive_from(self._serial)
                timestamp = time()
                if packet:
                    self.handle_packet(packet, timestamp)
            except OSError as e:
                self.__logger.error(e)
                self.__logger.error('device disconnected or multiple access on port?')
                # self.stop(from_thread=True)
                sleep(1)
            except ValueError as e:
                self.__logger.error(e)
                self.__logger.error('corrupted message')
                sleep(1)
            except Exception as e:
                self.__logger.error(e)
                sleep(1)

    def handle_packet(self, packet, timestamp):
        if packet[1] == 'PVT':
            # Get date and time
            self.datetime = datetime(packet[2].year, packet[2].month, packet[2].day,
                                     packet[2].hour, packet[2].min, packet[2].sec,
                                     packet[2].nano // 1000 if packet[2].nano > 0 else 0,  # nano to micro seconds
                                     pytz.utc)
            self.datetime_accuracy = packet[2].tAcc // 1000  # convert nano seconds to micro seconds
            self.datetime_valid = bool(packet[2].valid.validDate) and bool(packet[2].valid.validTime)
            # Get Position
            self.latitude = packet[2].lat / 10000000
            self.longitude = packet[2].lon / 10000000
            self.horizontal_accuracy = packet[2].hAcc / 1000  # convert mm to m
            self.altitude = packet[2].hMSL / 1000  # convert mm to m, above mean sea level
            self.altitude_accuracy = packet[2].hAcc / 1000 # convert mm to m
            self.fix_ok = bool(packet[2].flags.gnssFixOK)
            self.fix_type = packet[2].fixType
            # Get Speed
            self.speed = packet[2].gSpeed / 1000  # convert mm/s to m/s
            self.speed_accuracy = packet[2].sAcc / 1000 # covnert mm/s to m/s
            # Get motion and vehicle headings
            self.heading_motion = packet[2].headMot / 100000
            self.heading_vehicle = packet[2].headVeh / 100000
            self.heading_vehicle_accuracy = packet[2].headAcc / 100000
            self.heading_vehicle_valid = bool(packet[2].flags.headVehValid)
            # Timestamp data
            self.packet_pvt_received = timestamp
        elif packet[1] == 'RELPOSNED':
            # Get relative heading
            self.heading = packet[2].relPosHeading / 100000
            self.heading_accuracy = packet[2].accHeading / 100000
            self.heading_valid = bool(packet[2].flags.relPosHeadingValid)
            # Get Flags
            self.fix_ok = bool(packet[2].flags.gnssFixOK)
            # Timestamp data
            self.packet_relposned_received = timestamp
        else:
            self.__logger.warning('packet not supported: ' + packet[1])
            return

        # Write parsed data
        if self._log_data:
            # TODO Optimize logging to only write when received both frames (prevent replicated data)
            if self._data_logger_lock.acquire(timeout=0.5):
                try:
                    self._data_logger.write([self.datetime.strftime('%Y/%m/%d %H:%M:%S.%f'),
                                             self.datetime_accuracy, self.datetime_valid,
                                             self.heading, self.heading_accuracy, self.heading_valid,
                                             self.heading_motion, self.heading_vehicle,
                                             self.heading_vehicle_accuracy, self.heading_vehicle_valid,
                                             self.speed, self.speed_accuracy,
                                             self.latitude, self.longitude, self.horizontal_accuracy,
                                             self.altitude, self.altitude_accuracy, self.fix_ok, self.fix_type, packet[1]], timestamp)
                finally:
                    self._data_logger_lock.release()
            else:
                self.__logger.error('unable to acquire data_logger to write data')


class HyperOCR(Sensor):

    MAX_BUFFER_LENGTH = 16384

    def __init__(self, cfg, data_logger=None, parser=None):
        super().__init__(cfg)
        self.__logger = logging.getLogger(self.__class__.__name__)

        if data_logger is None:
            self._data_logger = LogBinary({'filename_prefix': self.__class__.__name__,
                                           'path': cfg.get(self.__class__.__name__, 'path_to_data',
                                                           fallback=os.path.join(os.path.dirname(__file__), 'data')),
                                           'length': cfg.getint(self.__class__.__name__, 'file_length', fallback=60)})
            self._data_logger.timestamp_packer = pack_timestamp_satlantic
        else:
            self._data_logger = data_logger

        self._buffer = bytearray()

        self._packet_Lt_raw = None
        self._packet_Lt_dark_raw = None
        self._packet_Li_raw = None
        self._packet_Li_dark_raw = None
        self._packet_Es_raw = None
        self._packet_Es_dark_raw = None
        self._packet_THS_raw = None

        self._packet_Lt_received = float('nan')
        self._packet_Lt_dark_received = float('nan')
        self._packet_Li_received = float('nan')
        self._packet_Li_dark_received = float('nan')
        self._packet_Es_received = float('nan')
        self._packet_Es_dark_received = float('nan')
        self._packet_THS_received = float('nan')

        self.Lt = None
        self.Lt_dark = None
        self.Li = None
        self.Li_dark = None
        self.Es = None
        self.Es_dark = None
        self.roll = float('nan')
        self.pitch = float('nan')
        self.compass = float('nan')      # Compass heading measured
        self.compass_adj = float('nan')  # Compass heading corrected for magnetic declination

        self.packet_Lt_parsed = float('nan')
        self.packet_Lt_dark_parsed = float('nan')
        self.packet_Li_parsed = float('nan')
        self.packet_Li_dark_parsed = float('nan')
        self.packet_Es_parsed = float('nan')
        self.packet_Es_dark_parsed = float('nan')
        self.packet_THS_parsed = float('nan')

        # Set device file (which sets dispatcher and wavelengths)
        self._parser = SatlanticParser()
        self._parser_device_file = None
        self.__immersed = cfg.getboolean(self.__class__.__name__, 'immersed', fallback=False)
        self._dispatcher = dict()
        self.Lt_wavelength, self.Li_wavelength, self.Es_wavelength = None, None, None
        if parser is None:
            try:
                self.set_parser(cfg.get(self.__class__.__name__, 'sip'))
            except NoOptionError:
                self.__logger.warning('Calibration file parameter "sip" absent from pysas_cfg.ini.')
            except FileNotFoundError:
                self.__logger.critical('The calibration file specified in the configuration was not found. '
                                    'Please set a calibration file using the button "Select or Upload" under '
                                    'the section "HyperSAS Device File" at the bottom of the sidebar.')
            except SatlanticCalibrationFileError:
                self.__logger.critical('Error while loading the calibration file specified in the configuration. '
                                       'Please set a new calibration file using the button "Select or Upload" under '
                                       'the section "HyperSAS Device File" at the bottom of the sidebar.')
        else:
            self._parser = parser
            self.set_dispatcher()
            self.set_wavelengths()

        self.__missing_packet_header = []
        self.__missing_dispatcher_key = []

    def set_parser(self, device_file):
        if self._parser_device_file == device_file:
            self.__logger.debug('device file already up to date ' + device_file)
            return
        self.__logger.info('update device file with ' + device_file)
        was_alive = False
        if self.alive:
            was_alive = True
            self.stop()
        self._parser.cal = dict()  # Reset calibration files loaded
        self._parser.read_calibration(device_file, self.__immersed)
        self._parser_device_file = device_file
        self.reset_buffers()
        self.set_dispatcher()
        self.set_wavelengths()
        if was_alive:
            self.start()

    def set_dispatcher(self):
        self._dispatcher = dict()
        for packet_header, cal in self._parser.cal.items():
            if 'SATTHS' in packet_header:
                self._dispatcher[packet_header] = 'THS'
            elif 'LT' == cal.core_groupname and 'SATHSL' in packet_header:
                self._dispatcher[packet_header] = 'Lt'
            elif 'LI' == cal.core_groupname and 'SATHSL' in packet_header:
                self._dispatcher[packet_header] = 'Li'
            elif 'ES' == cal.core_groupname and 'SATHSE' in packet_header:
                self._dispatcher[packet_header] = 'Es'
            elif 'LT' == cal.core_groupname and 'SATHLD' in packet_header:
                self._dispatcher[packet_header] = 'Lt_dark'
            elif 'LI' == cal.core_groupname and 'SATHLD' in packet_header:
                self._dispatcher[packet_header] = 'Li_dark'
            elif 'ES' == cal.core_groupname and 'SATHED' in packet_header:
                self._dispatcher[packet_header] = 'Es_dark'
            else:
                raise ValueError('Unable to find type of HyperSAS frame header.')

    def set_wavelengths(self):
        Lt_frame_header, Li_frame_header, Es_frame_header = None, None, None
        for packet_header, cal in self._parser.cal.items():
            if 'LT' == cal.core_groupname and 'SATHSL' in packet_header:
                Lt_frame_header = packet_header
            elif 'LI' == cal.core_groupname and 'SATHSL' in packet_header:
                Li_frame_header = packet_header
            elif 'ES' == cal.core_groupname and 'SATHSE' in packet_header:
                Es_frame_header = packet_header
        if Lt_frame_header:
            self.Lt_wavelength = [float(self._parser.cal[Lt_frame_header].id[i])
                                  for i in self._parser.cal[Lt_frame_header].core_variables]
        else:
            self.Es_wavelength = float('nan')
        if Li_frame_header:
            self.Li_wavelength = [float(self._parser.cal[Li_frame_header].id[i])
                                  for i in self._parser.cal[Li_frame_header].core_variables]
        else:
            self.Es_wavelength = float('nan')
        if Es_frame_header:
            self.Es_wavelength = [float(self._parser.cal[Es_frame_header].id[i])
                                  for i in self._parser.cal[Es_frame_header].core_variables]
        else:
            self.Es_wavelength = float('nan')

    def reset_buffers(self, raw=True, parsed=True):
        if raw:
            self._packet_Lt_raw = None
            self._packet_Lt_dark_raw = None
            self._packet_Li_raw = None
            self._packet_Li_dark_raw = None
            self._packet_Es_raw = None
            self._packet_Es_dark_raw = None
            self._packet_THS_raw = None

            self._packet_Lt_received = float('nan')
            self._packet_Lt_dark_received = float('nan')
            self._packet_Li_received = float('nan')
            self._packet_Li_dark_received = float('nan')
            self._packet_Es_received = float('nan')
            self._packet_Es_dark_received = float('nan')
            self._packet_THS_received = float('nan')
        if parsed:
            self.Lt = None
            self.Lt_dark = None
            self.Li = None
            self.Li_dark = None
            self.Es = None
            self.Es_dark = None
            self.roll = float('nan')
            self.pitch = float('nan')
            self.compass = float('nan')  # Compass heading measured
            self.compass_adj = float('nan')  # Compass heading corrected for magnetic declination

            self.packet_Lt_parsed = float('nan')
            self.packet_Lt_dark_parsed = float('nan')
            self.packet_Li_parsed = float('nan')
            self.packet_Li_dark_parsed = float('nan')
            self.packet_Es_parsed = float('nan')
            self.packet_Es_dark_parsed = float('nan')
            self.packet_THS_parsed = float('nan')

    def start(self):
        if not self._parser.cal:
            self.__logger.critical('A calibration file is required for the system to work. '
                                   'Please set a calibration file using the button "Select or Upload" under '
                                   'the section "HyperSAS Device File" at the bottom of the sidebar.')
        else:
            super().start()

    def run(self):
        while self.alive: # and self._serial.is_open:
            try:
                data = self._serial.read(self._serial.in_waiting or 1)
                timestamp = time()
                if data:
                    try:
                        self.data_received(data, timestamp)
                        if len(self._buffer) > self.MAX_BUFFER_LENGTH:
                            self.__logger.error('Buffer exceeded maximum length. Buffer emptied to prevent overflow')
                            self._buffer = bytearray()
                    except Exception as e:
                        self.__logger.error(e)
                        sleep(1)
            except SerialException as e:
                self.__logger.error(e)
                self.stop(from_thread=True)

    def data_received(self, data, timestamp):
        self._buffer.extend(data)
        packet = True
        while packet:
            packet, packet_header, self._buffer, unknown_bytes = self._parser.find_frame(self._buffer)
            if unknown_bytes:
                self._data_logger.write(unknown_bytes, timestamp)
                unknown_bytes_header = unknown_bytes[0:10].decode(self._parser.ENCODING, self._parser.UNICODE_HANDLING)
                if unknown_bytes_header not in self.__missing_packet_header:
                    if len(self.__missing_dispatcher_key) > 100:
                        self.__missing_packet_header = list()
                    self.__missing_packet_header.append(unknown_bytes_header)
                    self.__logger.info('Data logged not registered: ' + str(unknown_bytes_header) + '...')
            if packet:
                self._data_logger.write(packet, timestamp)
                self.dispatch_packet(packet_header, packet, timestamp)

    def dispatch_packet(self, packet_header, packet, timestamp):
        try:
            if self._dispatcher[packet_header] == 'THS':
                self._packet_THS_raw = packet
                self._packet_THS_received = timestamp
            elif self._dispatcher[packet_header] == 'Lt':
                self._packet_Lt_raw = packet
                self._packet_Lt_received = timestamp
            elif self._dispatcher[packet_header] == 'Lt_dark':
                self._packet_Lt_dark_raw = packet
                self._packet_Lt_dark_received = timestamp
            elif self._dispatcher[packet_header] == 'Li':
                self._packet_Li_raw = packet
                self._packet_Li_received = timestamp
            elif self._dispatcher[packet_header] == 'Li_dark':
                self._packet_Li_dark_raw = packet
                self._packet_Li_dark_received = timestamp
            elif self._dispatcher[packet_header] == 'Es':
                self._packet_Es_raw = packet
                self._packet_Es_received = timestamp
            elif self._dispatcher[packet_header] == 'Es_dark':
                self._packet_Es_dark_raw = packet
                self._packet_Es_dark_received = timestamp
        except KeyError:
            if packet_header not in self.__missing_dispatcher_key:
                if len(self.__missing_dispatcher_key) > 100:
                    self.__missing_dispatcher_key = list()
                self.__missing_dispatcher_key.append(packet_header)
                self.__logger.warning(f'Dispatcher does not support packet {packet_header}.')

    def parse_packets(self):
        """
        Parse packet received since last parsing. Called by UX
        """

        # Parse THS
        if self._packet_THS_received > self.packet_THS_parsed or \
                (isnan(self.packet_THS_parsed) and not isnan(self._packet_THS_received)):
            try:
                THS, _ = self._parser.parse_frame(self._packet_THS_raw)
                self.packet_THS_parsed = time()
                self.roll, self.pitch, self.compass = THS['ROLL'], THS['PITCH'], THS['COMP']
            except SatlanticFrameError as e:
                self.__logger.error('THS:' + e)
                self.roll, self.pitch, self.compass = float('nan'), float('nan'), float('nan')
                self._packet_THS_received = float('nan')
        # Parse Lt Dark
        if self._packet_Lt_dark_received > self.packet_Lt_dark_parsed or \
                (isnan(self.packet_Lt_dark_parsed) and not isnan(self._packet_Lt_dark_received)):
            try:
                Lt_dark, _ = self._parser.parse_frame(self._packet_Lt_dark_raw)
                self.packet_Lt_dark_parsed = time()
                self.Lt_dark = Lt_dark['LT']
            except SatlanticFrameError as e:
                self.__logger.error('Lt_dark:' + e)
                self.Lt_dark = None
                self._packet_Lt_dark_received = float('nan')
        # Parse Lt
        if self._packet_Lt_received > self.packet_Lt_parsed or \
                (isnan(self.packet_Lt_parsed) and not isnan(self._packet_Lt_received)):
            try:
                Lt, _ = self._parser.parse_frame(self._packet_Lt_raw)
                self.packet_Lt_parsed = time()
                if self.Lt_dark is not None:
                    self.Lt = Lt['LT'] - self.Lt_dark
                else:
                    self.Lt = Lt['LT']
            except SatlanticFrameError as e:
                self.__logger.error('Lt:' + e)
                self.Lt = None
                self._packet_Lt_received = float('nan')
        # Parse Li Dark
        if self._packet_Li_dark_received > self.packet_Li_dark_parsed or \
                (isnan(self.packet_Li_dark_parsed) and not isnan(self._packet_Li_dark_received)):
            try:
                Li_dark, _ = self._parser.parse_frame(self._packet_Li_dark_raw)
                self.packet_Li_dark_parsed = time()
                self.Li_dark = Li_dark['LI']
            except SatlanticFrameError as e:
                self.__logger.error('Li_dark:' + e)
                self.Li_dark = None
                self._packet_Li_dark_received = float('nan')
        # Parse Li
        if self._packet_Li_received > self.packet_Li_parsed or \
                (isnan(self.packet_Li_parsed) and not isnan(self._packet_Li_received)):
            try:
                Li, _ = self._parser.parse_frame(self._packet_Li_raw)
                self.packet_Li_parsed = time()
                if self.Li_dark is not None:
                    self.Li = Li['LI'] - self.Li_dark
                else:
                    self.Li = Li['LI']
            except SatlanticFrameError as e:
                self.__logger.error('Li:' + e)
                self.Li = None
                self._packet_Li_received = float('nan')
        # Parse Es Dark
        if self._packet_Es_dark_received > self.packet_Es_dark_parsed or \
                (isnan(self.packet_Es_dark_parsed) and not isnan(self._packet_Es_dark_received)):
            try:
                Es_dark, _ = self._parser.parse_frame(self._packet_Es_dark_raw)
                self.packet_Es_dark_parsed = time()
                self.Es_dark = Es_dark['ES']
            except SatlanticFrameError as e:
                self.__logger.error('Es_dark:' + e)
                self.Es_dark = None
                self._packet_Es_dark_received = float('nan')
        # Parse Es
        if self._packet_Es_received > self.packet_Es_parsed or \
                (isnan(self.packet_Es_parsed) and not isnan(self._packet_Es_received)):
            try:
                Es, _ = self._parser.parse_frame(self._packet_Es_raw)
                self.packet_Es_parsed = time()
                if self.Es_dark is not None:
                    self.Es = Es['ES'] - self.Es_dark
                else:
                    self.Es = Es['ES']
            except SatlanticFrameError as e:
                self.__logger.error('Es:' + e)
                self.Es = None
                self._packet_Es_received = float('nan')


class HyperSAS(HyperOCR):

    def __init__(self, cfg, data_logger=None, parser=None):
        super().__init__(cfg, data_logger, parser)
        self.__logger = logging.getLogger(self.__class__.__name__)


class Es(HyperOCR):

    def __init__(self, cfg, data_logger=None, parser=None):
        super().__init__(cfg, data_logger, parser)
        self.__logger = logging.getLogger(self.__class__.__name__)


if __name__ == '__main__':
    from configparser import ConfigParser
    cfg = ConfigParser()
    cfg.read('pysas_cfg.ini')

    # gps = GPS(cfg)

    # # Test HyperSAS
    sas = HyperSAS(cfg)
    # sas.start()
    # sleep(8)
    # sas.parse_packets()
    # print(sas.Lt)
    # print(sas.Li)
    # print(sas.roll)
    # print(sas.pitch)
    # print(sas.compass)
    # print(sas.Lt_wavelength)
    # print(sas.Li_wavelength)

    # # Test Reset em and set position to zero
    # # Indexing table is encoded with latin-1 (Western Europe, Schneider is German)
    # # b'\xa9'.decode('latin1')
    # it = IndexingTable(cfg)
    # # it.print_all_parameters()
    # it._serial.open()
    # it._serial.write(b'\x03')       # Reset
    # sleep(0.5); print(it._serial.read(it._serial.in_waiting).decode('latin-1'), end='')
    # sleep(0.1); it._serial.write(b'pr vr\r\n')   # Version number LMDCM 6.013, Hw: 2.9
    # sleep(0.1); it._serial.write(b'pr sn\r\n')   # Serial number 012150209
    # sleep(0.1); print(it._serial.read(it._serial.in_waiting).decode('latin-1'), end='')
    # # sleep(0.1); it._serial.write(b'em=1\r\n')   # Echo mode 0: Verbose 1: No echo
    # sleep(0.1); it._serial.write(b'\x08pr em\r\n') # Print Echo mode
    # sleep(0.1); print(it._serial.read(it._serial.in_waiting).decode('latin-1'), end='')
    #
    # sleep(0.1); it._serial.write(b'\x08pr p\r\n')  # Print position
    # sleep(0.1); it._serial.write(b'\x08p=2000\r\n')   # Set position to 0
    # sleep(0.1); it._serial.write(b'\x08pr p\r\n')  # Print position
    # sleep(0.1); print(it._serial.read(it._serial.in_waiting).decode('latin-1'), end='')
    #
    # sleep(0.1); it._serial.write(bytes('\x08p=0\r\n', 'latin-1'))  # Set position to 0
    # sleep(0.1); it._serial.write(b'\x08pr p\r\n')  # Print position
    # sleep(0.1); print(it._serial.read(it._serial.in_waiting).decode('latin-1'), end='')
    #
    # sleep(0.1); it._serial.write(b'\x08ma 56750\r\n')  # Set position to 0
    # sleep(0.5); it._serial.write(b'\x08pr p\r\n')  # Print position
    # sleep(0.1); print(it._serial.read(it._serial.in_waiting).decode('latin-1'), end='')
    # it._serial.close()

#   Test Indexing Table Motion
#
#     print('Stalled flag :' + str(it.read_stall_flag()))
#     print('Current position: ' + str(it.get_position()))
#     it.set_position(45)
#     sleep(5)
#     it.set_position(90, check_stall_flag=True)
#     # for i in range(5):
#     #     print('Current position: ' + str(it.get_position()))
#     #     sleep(0.5)
#
#     # print('===')
#     # avg_speed, time_data, pos_data = it.estimate_speed(0)
#     # print('Average rotation speed (deg/sec):\t' + str(avg_speed))
#     # print('Measured rotation time (sec):\t' + str(time_data[-1]))
#     print('===')
#     print('Estimated rotation time (sec):\t' + str(it.estimate_motion_time(it.get_position(),360)))
#     avg_speed, time_data, pos_data = it.measure_motion_speed(360)
#     print('Average rotation speed (deg/sec):\t' + str(avg_speed))
#     print('Measured rotation time (sec):\t' + str(time_data[-1]))
#     # print('===')
#     # print('Estimated rotation time (sec):\t' + str(it.estimate_motion_time(360, 180)))
#     # avg_speed, time_data, pos_data = it.estimate_speed(180)
#     # print('Average rotation speed (deg/sec):\t' + str(avg_speed))
#     # print('Measured rotation time (sec):\t' + str(time_data[-1]))
#     # print('===')
#     # print('Estimated motion time (sec): ' + str(it.estimate_motion_time(180, 0)))
#     # avg_speed, time_data, pos_data = it.estimate_speed(0)
#     # print('Average rotation speed (deg/sec):\t' + str(avg_speed))
#     # print('Measured rotation time (sec):\t' + str(time_data[-1]))
#     # print('Stalled flag after moving:' + str(it.read_stall_flag()))
#     # it.reset_stall_flag()
#     # sleep(it.DRIVE_COMMAND_DELAY)
#     # print('Stalled flag reset:' + str(it.read_stall_flag()))
#     # it.serial.write(bytes("st=1\r\n", 'utf-8'))
#     # sleep(it.DRIVE_COMMAND_DELAY)
#     # print('Stalled flag set to 1:' + str(it.read_stall_flag()))
#     # it.reset_stall_flag()
#     # sleep(it.DRIVE_COMMAND_DELAY)
#     # print('Stalled flag reset:' + str(it.read_stall_flag()))