import logging
import configparser
from time import gmtime, time, sleep
from math import isnan
import atexit
from subprocess import call
from threading import Thread
from pySAS.interfaces import IndexingTable, GPS, HyperSAS #, #Es
from pySAS import WORLD_MAGNETIC_MODEL

# pySolar
from datetime import datetime
import pytz
# from pysolar.time import leap_seconds_adjustments   # v0.7
from pysolar.solartime import leap_seconds_adjustments # v0.8
from pysolar.solar import get_azimuth, get_altitude


class Runner:

    DATA_EXPIRED_DELAY = 20     # seconds
    ASLEEP_DELAY = 120     # seconds
    ASLEEP_INTERRUPT = 120  # seconds
    HEADING_TOLERANCE = 1  # degrees

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
        self.asleep = False
        self.sun_elevation = float('nan')
        self.sun_azimuth = float('nan')
        self.sun_position_timestamp = float('nan')
        self.ship_heading = float('nan')
        self.ship_heading_timestamp = float('nan')

        # Controllers & Sensors
        self.indexing_table = IndexingTable(self.cfg)
        self.gps = GPS(self.cfg)
        self.hypersas = HyperSAS(self.cfg)
        self.es = None
        # if 'Es' in self.cfg.sections():
        #     self.es = Es(self.cfg, parser=self.hypersas.parser, data_logger=self.hypersas.parser)

        # Pilot
        self.pilot = AutoPilot(self.cfg)
        self.filter = None

        # Thread
        self.alive = False
        self._thread = None
        self.refresh_delay = self.cfg.getint(self.__class__.__name__, 'refresh', fallback=5)

        # Register methods to execute at exit as cannot use __del__ as logging is already off-loaded
        atexit.register(self.stop)

        # Start if in auto_mode
        if self.operation_mode == 'auto':
            self.start_auto()

    def start_auto(self):
        if not self.alive:
            self.__logger.debug('start')
            self.gps.start()  # GPS is continuously running, could optimize to turn off at night and turn on every hour
            self.alive = True
            self._thread = Thread(name=self.__class__.__name__, target=self.run_auto)
            self._thread.daemon = True
            self._thread.start()

    def stop_auto(self):
        if self.alive:
            self.__logger.debug('stop')
            self.alive = False
            self._thread.join(2)
            if self._thread.is_alive():
                self.__logger.error('Thread of ' + self.__class__.__name__ + ' did not join.')
            self.gps.stop()

    def run_auto(self):
        flag_invalid_heading = False
        flag_no_position = False
        flag_stalled = False
        first_iteration = True
        while self.alive:
            # Timer
            iteration_timestamp = time()

            # try:
            # Check GPS
            if not self.gps.fix_ok:
                self.__logger.info('No GPS fix, fix_type = ' + str(self.gps.fix_type))
                self._wait(iteration_timestamp)
                continue
            if not self.gps.datetime_valid:
                self._wait(iteration_timestamp)
                self.__logger.info('Invalid date and/or time')
                continue
            if not self.gps.heading_valid:
                if not flag_invalid_heading:
                    self.__logger.info('Invalid heading')
                    flag_invalid_heading = True
                self._wait(iteration_timestamp)
                continue
            if time() - self.gps.packet_pvt_received > self.DATA_EXPIRED_DELAY or\
                    isnan(self.gps.packet_pvt_received):
                self.__logger.info('gps packet PVT expired')
                self._wait(iteration_timestamp)
                continue
            if time() - self.gps.packet_relposned_received > self.DATA_EXPIRED_DELAY or\
                    isnan(self.gps.packet_relposned_received):
                self.__logger.info('gps packet RELPOSNED expired')
                self._wait(iteration_timestamp)
                continue

            # Reset GPS flags
            if flag_invalid_heading:
                flag_invalid_heading = False

            # Get Sun Position
            self.sun_elevation, self.sun_azimuth = get_sun_position(self.gps.latitude, self.gps.longitude,
                                                                    self.gps.datetime, self.gps.altitude)
            self.sun_position_timestamp = time()

            # Toggle Sleep Mode
            if self.sun_elevation < self.min_sun_elevation:
                if not self.start_sleep_timestamp:
                    self.start_sleep_timestamp = time()
                if (time() - self.start_sleep_timestamp > self.ASLEEP_DELAY and not self.asleep) or \
                        first_iteration:
                    self.__logger.info('fall asleep')
                    self.indexing_table.stop()
                    self.hypersas.stop()
                    self.gps.stop_logging()
                    self.asleep = True
                self.stop_sleep_timestamp = None
            else:
                if not self.stop_sleep_timestamp:
                    self.stop_sleep_timestamp = time()
                if (time() - self.stop_sleep_timestamp > self.ASLEEP_DELAY and self.asleep) or \
                        first_iteration:
                    self.__logger.info('waking up')
                    self.indexing_table.start()
                    self.gps.start_logging()
                    self.hypersas.start()
                    self.asleep = False
                self.start_sleep_timestamp = None
            if self.asleep:
                sleep(self.ASLEEP_INTERRUPT)
                continue

            # Correct HyperSAS THS Compass
            self.hypersas.compass_adj = get_true_north_heading(self.hypersas.compass,
                                                               self.gps.latitude, self.gps.longitude,
                                                               self.gps.datetime, self.gps.altitude)

            # Get Heading
            ship_heading_tmp = self.get_ship_heading()

            # Smooth Heading
            if self.filter:
                ship_heading_tmp = self.filter.update(ship_heading_tmp)
            self.ship_heading = ship_heading_tmp

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

            if first_iteration:
                first_iteration = False
            # except Exception as e:
            #     self.__logger.critical(e)

            # Wait before next iteration
            if self.alive:
                self._wait(iteration_timestamp)

    def _wait(self, start_iter):
        delta = self.refresh_delay - (time() - start_iter)
        if delta > 0:
            sleep(delta)
        else:
            self.__logger.warning('cannot keep up with refresh rate, slowing down')
            sleep(1 + abs(self.refresh_delay))

    def get_ship_heading(self):
        """
        Get heading of ship according to the source selected
        :return: heading of ship from the requested source
        """
        if self.heading_source == 'gps_relative_position':
            self.ship_heading_timestamp = self.gps.packet_relposned_received
            return self.pilot.get_ship_heading(self.gps.heading)
        elif self.heading_source == 'gps_motion':
            self.ship_heading_timestamp = self.gps.packet_pvt_received
            return self.pilot.get_ship_heading(self.gps.heading_motion)
        elif self.heading_source == 'gps_vehicle':
            self.ship_heading_timestamp = self.gps.packet_pvt_received
            return self.pilot.get_ship_heading(self.gps.heading_vehicle)
        elif self.heading_source == 'ths_heading':
            # Take hypersas compass heading freshly corrected for magnetic declination
            self.ship_heading_timestamp = self.hypersas.packet_THS_parsed
            return self.pilot.get_ship_heading(self.hypersas.compass_adj, self.indexing_table.get_position())
        else:
            raise ValueError('Invalid heading source')

    def set_cfg_variable(self, section, variable, value):
        self.__logger.debug('set_cfg_variable(' + section + ', ' + variable + ', ' + value + ')')
        self.cfg[section][variable] = value
        self.cfg_last_update = gmtime()

    def write_cfg(self):
        self.__logger.debug('write_cfg')
        # Save updated configuration
        with open(self._cfg_filename) as cfg_file:
            self.cfg.write(cfg_file)

    def halt(self):
        if self.cfg.getboolean('Runner', 'halt_on_exit', fallback=False):
            call("sudo shutdown -h now", shell=True)
        # sys.exit()  # UI stop the application itself

    def stop(self):
        self.__logger.debug('stop')
        # self.write_cfg()  # TODO Activate write for production


# # Update leap_seconds_adjustments table from pysolar
# pysolar_end_year = 2015  # v0.7
pysolar_end_year = 2018  # v0.8
for y in range(pysolar_end_year, datetime.now().year+2):
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
    #   azimuth: 0 is south, positive correspond to east of south

    if dt_utc is None:
        dt_utc = datetime.utcnow()

    # Set timezone to utc if datetime object (dt_utc) timezone is naive
    if dt_utc.tzinfo is None or dt_utc.tzinfo.utcoffset(dt_utc) is None:
        dt_utc = dt_utc.replace(tzinfo=pytz.utc)

    altitude = get_altitude(lat, lon, dt_utc, elevation)
    if altitude > 0:
        # azimuth = get_azimuth(lat, lon, dt_utc, elevation) % 360  # bug here has assume North as zero
        azimuth = (180 - get_azimuth(lat, lon, dt_utc, elevation)) % 360 # Translate back to North = 0, clockwise referential
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

    return (heading + WORLD_MAGNETIC_MODEL.GeoMag(latitude, longitude, altitude * 3.2808399, datetime_utc.date()).dec) \
        % 360


def normalize_angle(angle):
    new_angle = angle
    while new_angle <= -180:
        new_angle += 360
    while new_angle > 180:
        new_angle -= 360
    return new_angle


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
        # self.compass_on_tower = cfg.getboolean(self.__class__.__name__, 'compass_mounted_on_indexing_table', fallback=False)
        self.compass_zero = normalize_angle(cfg.getfloat(self.__class__.__name__, 'gps_orientation_on_ship', fallback=0))
        self.tower_zero = normalize_angle(cfg.getfloat(self.__class__.__name__, 'indexing_table_orientation_on_ship', fallback=0))
        self.tower_limits = [float('nan'), float('nan')]
        self.set_tower_limits(cfg.get(self.__class__.__name__, 'valid_indexing_table_orientation_limits').split(':'))
        self.target = cfg.getfloat(self.__class__.__name__, 'optimal_angle_away_from_sun', fallback=135)

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
            return float('nan')
        elif valid_options < 3:
            # One option
            return tower_orientation_options[valid_options - 1]
        else:
            # Two option: find the furthest away from the tower limits
            # Get distance between tower limits and each aimed orientation option
            dist_options = [min(abs(normalize_angle(self.tower_limits[0] - tower_orientation_options[0])),
                                abs(normalize_angle(self.tower_limits[1] - tower_orientation_options[0]))),
                            min(abs(normalize_angle(self.tower_limits[0] - tower_orientation_options[1])),
                                abs(normalize_angle(self.tower_limits[1] - tower_orientation_options[1])))]
            return tower_orientation_options[dist_options.index(max(dist_options))]

    def get_ship_heading(self, compass_heading, tower_orientation_correction=None):
        if tower_orientation_correction is None:
            # Assume compass heading is mounted on ship
            return normalize_angle(compass_heading - self.compass_zero)
        else:
            # Assume compass is mounted on tower so need to take that into account
            return normalize_angle(compass_heading + tower_orientation_correction - self.tower_zero - self.compass_zero)

