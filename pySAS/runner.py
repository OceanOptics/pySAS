import logging
import configparser
from time import gmtime, time, sleep, strftime
from math import isnan
from datetime import timedelta
import socket
import atexit
from subprocess import run
from threading import Thread
from pySAS.interfaces import IndexingTable, GPS, HyperSAS, Es
from pySAS import WORLD_MAGNETIC_MODEL

# pySolar
from datetime import datetime
import pytz
# from pysolar.time import leap_seconds_adjustments   # v0.7
from pysolar.solartime import leap_seconds_adjustments  # v0.8
from pysolar.solar import get_azimuth, get_altitude


class Runner:
    DATA_EXPIRED_DELAY = 20  # seconds
    ASLEEP_DELAY = 120  # seconds
    ASLEEP_INTERRUPT = 120  # seconds
    HEADING_TOLERANCE = 0.2  # degrees ~ 111 motor steps

    def __init__(self, cfg_filename=None):
        # Setup Logging
        self.__logger = logging.getLogger(self.__class__.__name__)

        self.cfg = configparser.ConfigParser()
        self._cfg_filename = cfg_filename
        self.cfg_last_update = None
        try:
            if self.cfg.read(cfg_filename):
                self.cfg_last_update = gmtime()
            else:
                self.__logger.critical('Configuration file not found')
        except configparser.Error as e:
            self.__logger.critical('Unable to parse configuration file')

        # Runner states
        tmp = self.cfg.get('Runner', 'operation_mode', fallback='auto')
        if tmp not in ['auto', 'manual']:
            self.__logger.warning('Invalid operation mode, fallback to auto')
            tmp = 'auto'
        self.operation_mode = tmp
        self.heading_source = self.cfg.get(self.__class__.__name__, 'heading_source', fallback='gps_relative_position')
        self.min_sun_elevation = self.cfg.getfloat(self.__class__.__name__, 'min_sun_elevation', fallback=20)
        self.start_sleep_timestamp = None
        self.stop_sleep_timestamp = None
        self.asleep = True
        self.sun_elevation = float('nan')
        self.sun_azimuth = float('nan')
        self.sun_position_timestamp = float('nan')
        self.ship_heading = float('nan')
        self.ship_heading_timestamp = float('nan')
        self.interrupt_from_ui = False
        self.reboot_from_ui = False
        self.time_synced = None
        self.internet = check_internet()

        # Pilot
        self.pilot = AutoPilot(self.cfg)

        # Thread
        self.alive = False
        self._thread = None
        self.refresh_delay = self.cfg.getint(self.__class__.__name__, 'refresh', fallback=5)

        # Register methods to execute at exit as cannot use __del__ as logging is already off-loaded
        # Register before interfaces to make sure it's called last in case use shutdown
        atexit.register(self.stop)

        # Controllers & Sensors
        self.indexing_table = IndexingTable(self.cfg)
        self.gps = GPS(self.cfg)
        self.hypersas = HyperSAS(self.cfg)
        self.es = None
        if 'Es' in self.cfg.sections():
            self.es = Es(self.cfg, data_logger=self.hypersas._data_logger, parser=self.hypersas._parser)

        # Start if in auto_mode
        if self.operation_mode == 'auto':
            self.start_auto()

    def start_auto(self):
        if not self.alive:
            self.__logger.debug('start auto')
            self.gps.start()  # GPS is continuously running, could optimize to turn off at night and turn on every hour
            self.alive = True
            self._thread = Thread(name=self.__class__.__name__, target=self.run_auto)
            self._thread.daemon = True
            self._thread.start()

    def stop_auto(self):
        if self.alive:
            self.__logger.debug('stop auto')
            self.alive = False
            self._thread.join(2)
            if self._thread.is_alive():
                self.__logger.error('Thread of ' + self.__class__.__name__ + ' did not join.')
            # self.gps.stop()

    def run_auto(self):
        flag_no_position = False
        flag_stalled = False
        first_iteration = True
        # Reset sleep mode if need to restart instruments
        if self.indexing_table.alive and self.hypersas.alive:
            self.asleep = False
        else:
            self.asleep = True
        while self.alive:
            # Timer
            iteration_timestamp = time()

            try:
                # Get Sun Position
                if not self.get_sun_position():
                    self._wait(iteration_timestamp)
                    continue

                # Toggle Sleep Mode
                if self.sun_elevation < self.min_sun_elevation:  # TODO Implement sleep when no position or stalled
                    if not self.asleep:
                        if not self.start_sleep_timestamp:
                            self.start_sleep_timestamp = time()
                        if time() - self.start_sleep_timestamp > self.ASLEEP_DELAY or first_iteration:
                            self.__logger.info('fall asleep')
                            self.indexing_table.stop()
                            self.hypersas.stop()
                            self.gps.stop_logging()
                            self.asleep = True
                        self.stop_sleep_timestamp = None
                else:
                    if self.asleep:
                        if not self.stop_sleep_timestamp:
                            self.stop_sleep_timestamp = time()
                        if time() - self.stop_sleep_timestamp > self.ASLEEP_DELAY or first_iteration:
                            self.__logger.info('waking up')
                            if not self.internet and not self.hypersas.alive:
                                self.get_time_sync()
                            self.indexing_table.start()
                            self.gps.start_logging()
                            self.hypersas.start()
                            self.asleep = False
                    self.start_sleep_timestamp = None
                if first_iteration:
                    first_iteration = False
                if self.asleep:
                    sleep(self.ASLEEP_INTERRUPT)
                    continue

                # Get Heading
                if not self.get_ship_heading():
                    self._wait(iteration_timestamp)
                    continue

                if not isnan(self.sun_azimuth):
                    # Compute aimed indexing table orientation
                    aimed_indexing_table_orientation = self.pilot.steer(self.sun_azimuth, self.ship_heading)
                    if isnan(aimed_indexing_table_orientation):
                        if not flag_no_position:
                            self.__logger.info('No orientation available.')
                            flag_no_position = True
                    else:
                        # Update Tower
                        if abs(self.indexing_table.get_position() - aimed_indexing_table_orientation) \
                                > self.HEADING_TOLERANCE:
                            if self.indexing_table.get_stall_flag():
                                if not flag_stalled:
                                    self.__logger.warning('Indexing table stalled')
                                    flag_stalled = True
                            else:
                                self.indexing_table.set_position(aimed_indexing_table_orientation)
                                if flag_stalled:
                                    flag_stalled = False
                                if flag_no_position:
                                    flag_no_position = False

            except Exception as e:
                self.__logger.critical(e)

            # Wait before next iteration
            if self.alive:
                self._wait(iteration_timestamp)

    def _wait(self, start_iter):
        delta = self.refresh_delay - (time() - start_iter)
        if delta > 0:
            if delta > 0.5:
                start_sleep = time()
                while time() - start_sleep < delta and self.alive:
                    sleep(0.1)
            else:
                sleep(delta)
        else:
            self.__logger.warning('cannot keep up with refresh rate, slowing down')
            sleep(1 + abs(self.refresh_delay))

    def get_time_sync(self):
        """
        Sync system time to GPS, override used if time has already been synced
        """
        if self.gps.fix_ok and self.gps.datetime_valid and \
                time() - self.gps.packet_pvt_received < self.DATA_EXPIRED_DELAY:
            pre_sync = time()
            delta = timedelta(seconds=(pre_sync - self.gps.packet_pvt_received))
            run(("date", "-s", str((self.gps.datetime+delta).isoformat())))
            self.time_synced = time()
            self.__logger.info("Time synchronized. From %s to %s" % (strftime('%Y/%m/%d %H:%M:%S', gmtime(pre_sync)),
                               strftime('%Y/%m/%d %H:%M:%S', gmtime(self.time_synced))))
        else:
            self.__logger.warning("Unable to synchronize time.")

    def get_sun_position(self):
        """
        Compute sun position after checking that gps fix and datetime valid are ok
        :return: True: if succeeded and False otherwise
        """
        if self.gps.fix_ok and self.gps.datetime_valid and \
                time() - self.gps.packet_pvt_received < self.DATA_EXPIRED_DELAY:
            self.sun_elevation, self.sun_azimuth = get_sun_position(self.gps.latitude, self.gps.longitude,
                                                                    self.gps.datetime, self.gps.altitude)
            self.sun_position_timestamp = time()
            return True
        else:
            return False

    def get_ship_heading(self):
        """
        Get heading of ship according to the source selected
        :return: True if succeeded and False otherwise
        """
        if self.heading_source == 'gps_relative_position':
            if self.gps.heading_valid and time() - self.gps.packet_relposned_received < self.DATA_EXPIRED_DELAY:
                self.ship_heading = self.pilot.get_ship_heading(self.gps.heading)
                self.ship_heading_timestamp = self.gps.packet_relposned_received
                return True
        elif self.heading_source == 'gps_motion':
            if self.gps.fix_ok and time() - self.gps.packet_pvt_received < self.DATA_EXPIRED_DELAY:
                self.ship_heading = self.pilot.get_ship_heading(self.gps.heading_motion)
                self.ship_heading_timestamp = self.gps.packet_pvt_received
                return True
        elif self.heading_source == 'gps_vehicle':
            if self.gps.fix_ok and time() - self.gps.packet_pvt_received < self.DATA_EXPIRED_DELAY:
                self.ship_heading = self.pilot.get_ship_heading(self.gps.heading_vehicle)
                self.ship_heading_timestamp = self.gps.packet_pvt_received
                return True
        elif self.heading_source == 'ths_heading':
            if self.gps.fix_ok and time() - self.gps.packet_pvt_received < self.DATA_EXPIRED_DELAY:
                self.hypersas.compass_adj = get_true_north_heading(self.hypersas.compass,
                                                                   self.gps.latitude, self.gps.longitude,
                                                                   self.gps.datetime, self.gps.altitude)
                self.ship_heading = self.pilot.get_ship_heading(self.hypersas.compass_adj, self.indexing_table.get_position())
                self.ship_heading_timestamp = self.hypersas.packet_THS_parsed
                return True
        else:
            raise ValueError('Invalid heading source')
        return False

    def set_cfg_variable(self, section, variable, value):
        if self.cfg.has_option(section, variable) and self.cfg[section][variable] == str(value):
            self.__logger.debug('set_cfg_variable(' + section + ', ' + variable + ', ' + str(value) + ') already up to date')
            return
        self.__logger.debug('set_cfg_variable(' + section + ', ' + variable + ', ' + str(value) + ')')
        self.cfg[section][variable] = str(value)
        self.cfg_last_update = gmtime()
        if self.cfg.getboolean(self.__class__.__name__, 'ui_update_cfg', fallback=False):
            self.write_cfg()

    def write_cfg(self):
        self.__logger.debug('write_cfg')
        # Save updated configuration
        with open(self._cfg_filename, 'w') as cfg_file:
            self.cfg.write(cfg_file)

    def stop(self):
        self.stop_auto()
        if self.reboot_from_ui and self.cfg.getboolean('Runner', 'halt_host_on_exit', fallback=True):
            run(("shutdown", "-r", "now"))
        if self.interrupt_from_ui and self.cfg.getboolean('Runner', 'halt_host_on_exit', fallback=False):
            run(("shutdown", "-h", "now"))  # Must be authorized to run command


# # Update leap_seconds_adjustments table from pysolar
# pysolar_end_year = 2015  # v0.7
pysolar_end_year = 2018  # v0.8
for y in range(pysolar_end_year, datetime.now().year + 2):
    leap_seconds_adjustments.append((0, 0))  # Not exact but fine for our application


def get_sun_position(lat, lon, dt_utc=None, elevation=0):
    # Compute sun's zenith and azimuth angles using pysolar module
    # input the datetime in utc format (if none are providing computing sun position for now)
    #   timezone must be set or it will be automatically set to utc if naive
    #   azimuth angle is computed if altitude > 0
    # pySolar module is based on:
    #    Reda and A. Andreas, “Solar Position Algorithm for Solar Radiation Applications,”
    #       National Renewable Energy Laboratory, NREL/TP-560-34302, revised November 2005.
    # pySolar module was validated against United States Naval Observatory (USNO) codes and observations at 6000 sites
    #   average accuracy < .1 degrees for both altitude and azimuth
    #   azimuth max error: 0.176 degrees; altitude max error: 0.604 degrees
    # pySolar reference frame:
    #   altitude: 0 is horizon, positive is above the horizon
    #   azimuth: 0 is north, positive east, negative is west (or >180)

    if dt_utc is None:
        dt_utc = datetime.utcnow()

    # Set timezone to utc if datetime object (dt_utc) timezone is naive
    if dt_utc.tzinfo is None or dt_utc.tzinfo.utcoffset(dt_utc) is None:
        dt_utc = dt_utc.replace(tzinfo=pytz.utc)

    altitude = get_altitude(lat, lon, dt_utc, elevation)
    if altitude > 0:
        azimuth = get_azimuth(lat, lon, dt_utc, elevation)
        return altitude, azimuth
    else:
        return altitude, float('nan')


def get_true_north_heading(heading, latitude, longitude, datetime_utc=None, altitude=0):
    """
    Correct compass heading for magnetic field declination/variation
        precision is limited to the day
    :param heading: measured compass heading
    :param latitude: latitude in decimal degrees North
    :param longitude: longitude in decimal degrees East
    :param datetime_utc: date and time
    :param altitude: altitude above mean sea level in meters
    :return: compass heading corrected for magnetic field declination
    """

    if datetime_utc is None:
        datetime_utc = datetime.utcnow()

    # Set timezone to utc if datetime object (dt_utc) timezone is naive
    if datetime_utc.tzinfo is None or datetime_utc.tzinfo.utcoffset(datetime_utc) is None:
        datetime_utc = datetime_utc.replace(tzinfo=pytz.utc)

    return (heading + WORLD_MAGNETIC_MODEL.GeoMag(latitude, longitude, altitude * 3.2808399, datetime_utc.date()).dec) % 360


def normalize_angle(angle):
    new_angle = angle
    while new_angle <= -180:
        new_angle += 360
    while new_angle > 180:
        new_angle -= 360
    return new_angle


def check_internet(host="8.8.8.8", port=53, timeout=3):
    """
    Check internet connection by pinging google
    :return: True if google ping successful, False if fails
    """
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        return True
    except socket.error as ex:
        return False


class AutoPilot:
    """
    The AutoPilot class steers the indexing table as a function of the sun elevation
        The ship is used as the reference for orienting the compass and the indexing table.
        If multiple positions are available for the indexing table the furthest away from the valid range is preferred.
        The indexing table is referred as tower for brevity

    Configuration variable names:
        compass_on_tower: <boolean> compass mounted on indexing table (true) or mounted on the ship (false) DEPRECATED
        compass_zero: <float between -180 and 180> compass orientation with respect to the ship
        tower_zero: <float between -180 and 180> indexing table orientation with respect to the ship
        tower_limits: <2x floats between -180 and 180> indexing table valid orientation limits
        target: <float between -180 and 180> optimal angle away from sun azimuth

    """
    def __init__(self, cfg):
        self.compass_zero = normalize_angle(cfg.getfloat(self.__class__.__name__, 'gps_orientation_on_ship', fallback=0))
        self.tower_zero = normalize_angle(cfg.getfloat(self.__class__.__name__, 'indexing_table_orientation_on_ship', fallback=0))
        self.tower_limits = [float('nan'), float('nan')]
        self.set_tower_limits(cfg.get(self.__class__.__name__, 'valid_indexing_table_orientation_limits').replace('[', '').replace(']', '').split(','))
        self.target = cfg.getfloat(self.__class__.__name__, 'optimal_angle_away_from_sun', fallback=135)

        self.min_dist_delta = cfg.getfloat(self.__class__.__name__, 'minimum_distance_delta', fallback=3)  # degrees
        self.selected_option = None

    def set_tower_limits(self, limits):
        self.tower_limits = [normalize_angle(float(v)) for v in limits]

    def steer(self, sun_azimuth, ship_heading):
        # Get both aimed heading options
        aimed_heading_options = [sun_azimuth + self.target, sun_azimuth - self.target]
        # Get headings
        tower_zero_heading = ship_heading - self.tower_zero
        # Change from magnetic north referential (heading) to tower referential (orientation)
        tower_orientation_options = [normalize_angle(aimed_heading_options[0] - tower_zero_heading),
                                     normalize_angle(aimed_heading_options[1] - tower_zero_heading)]

        # Check if options are in tower limits
        valid_options = 0
        if self.tower_limits[0] == self.tower_limits[1]:
            # Special case: no tower limits => all options are valid prefer first options (arbitrary choice)
            return tower_orientation_options[0]
        elif self.tower_limits[0] < self.tower_limits[1]:
            if self.tower_limits[0] <= tower_orientation_options[0] <= self.tower_limits[1]:
                valid_options += 1
            if self.tower_limits[0] <= tower_orientation_options[1] <= self.tower_limits[1]:
                valid_options += 2
        elif self.tower_limits[0] > self.tower_limits[1]:
            if tower_orientation_options[0] >= self.tower_limits[0] or \
                    self.tower_limits[1] >= tower_orientation_options[0]:
                valid_options += 1
            if tower_orientation_options[1] >= self.tower_limits[0] or \
                    self.tower_limits[1] >= tower_orientation_options[1]:
                valid_options += 2

        if not valid_options:
            # No option
            self.selected_option = None
            return float('nan')
        elif valid_options < 3:
            # One option
            self.selected_option = valid_options - 1
            return tower_orientation_options[self.selected_option]
        else:
            # Two option: find the furthest away from the tower limits
            # Get distance between tower limits and each aimed orientation option
            dist_options = [min(abs(normalize_angle(self.tower_limits[0] - tower_orientation_options[0])),
                                abs(normalize_angle(self.tower_limits[1] - tower_orientation_options[0]))),
                            min(abs(normalize_angle(self.tower_limits[0] - tower_orientation_options[1])),
                                abs(normalize_angle(self.tower_limits[1] - tower_orientation_options[1])))]
            max_dist_option = dist_options.index(max(dist_options))
            # Prevent switch between positions back and forth
            # Only switch if the delta between the two options is greater than MIN_DIST_DELTA
            if self.selected_option is None or \
                    (max_dist_option != self.selected_option and
                     self.min_dist_delta < abs(dist_options[0] - dist_options[1])):
                self.selected_option = max_dist_option
            return tower_orientation_options[self.selected_option]

    def get_ship_heading(self, compass_heading, tower_orientation_correction=None):
        if tower_orientation_correction is None:
            # Assume compass heading is mounted on ship
            return normalize_angle(compass_heading - self.compass_zero)
        else:
            # Assume compass is mounted on tower so need to take that into account
            return normalize_angle(compass_heading + tower_orientation_correction - self.tower_zero - self.compass_zero)
