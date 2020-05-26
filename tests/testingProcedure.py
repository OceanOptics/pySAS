import logging
import configparser
import os
from datetime import datetime
from time import gmtime, time, sleep
from math import isnan
import atexit
from subprocess import call
from threading import Thread
from pySAS.interfaces import IndexingTable, GPS, HyperSAS
from pySAS.runner import get_true_north_heading, normalize_angle


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
    tp = TestingProcedure('')
    tp.run()

#     DATA_EXPIRED_DELAY = 20  # seconds
#     ASLEEP_DELAY = 120  # seconds
#     ASLEEP_INTERRUPT = 120  # seconds
#     HEADING_TOLERANCE = 1  # degrees
#
#     def __init__(self, cfg_filename=None):
#         # Setup Logging
#         self.__logger = logging.getLogger(self.__class__.__name__)
#         self.cfg = configparser.ConfigParser()
#         self._cfg_filename = cfg_filename
#         self.cfg_last_update = None
#         self.start_sleep_timestamp = None
#         self.stop_sleep_timestamp = None
#         self.ship_heading = float('nan')
#         self.tower_heading = float('nan')
#
#         # Controllers & Sensors
#         self.indexing_table = IndexingTable(self.cfg)
#         self.gps = GPS(self.cfg)
#         self.hypersas = HyperSAS(self.cfg)
#
#         # Pilot
#         self.pilot = ValidatePilot(self.cfg)
#         self.filter = None
#
#         try:
#             if self.cfg.read(cfg_filename):
#                 self.cfg_last_update = gmtime()
#             else:
#                 self.__logger.critical('Configuration file not found')
#         except configparser.Error as e:
#             self.__logger.critical('Unable to parse configuration file')
#
#         # Thread
#         self.alive = False
#         self._thread = None
#         self.refresh_delay = self.cfg.getint(self.__class__.__name__, 'refresh', fallback=5)
#
#         # Register methods to execute at exit as cannot use __del__ as logging is already off-loaded
#         atexit.register(self.stop)
#
#     def stop(self):
#         self.__logger.debug('stop')
#
#     def run_validation(self):
#         flag_no_gps_fix = False
#         flag_invalid_datetime = False
#         flag_invalid_heading = False
#         flag_pvt_expired = False
#         flag_relposned_expired = False
#         flag_no_position = False
#         flag_stalled = False
#         first_iteration = True
#         while self.alive:
#             # Timer
#             iteration_timestamp = time()
#
#             try:
#                 # Check GPS
#                 if not self.gps.fix_ok:
#                     if not flag_no_gps_fix:
#                         self.__logger.info('No GPS fix, fix_type = ' + str(self.gps.fix_type))
#                         flag_no_gps_fix = True
#                     self._wait(iteration_timestamp)
#                     continue
#                 if not self.gps.datetime_valid:
#                     if not flag_invalid_datetime:
#                         self.__logger.info('Invalid date and/or time')
#                         flag_invalid_datetime = True
#                     self._wait(iteration_timestamp)
#                     continue
#                 if not self.gps.heading_valid:
#                     if not flag_invalid_heading:
#                         self.__logger.info('Invalid heading')
#                         flag_invalid_heading = True
#                     self._wait(iteration_timestamp)
#                     continue
#                 if time() - self.gps.packet_pvt_received > self.DATA_EXPIRED_DELAY or \
#                         isnan(self.gps.packet_pvt_received):
#                     if not flag_pvt_expired:
#                         self.__logger.info('gps packet PVT expired')
#                         flag_pvt_expired = True
#                     self._wait(iteration_timestamp)
#                     continue
#                 if time() - self.gps.packet_relposned_received > self.DATA_EXPIRED_DELAY or \
#                         isnan(self.gps.packet_relposned_received):
#                     if not flag_relposned_expired:
#                         self.__logger.info('gps packet RELPOSNED expired')
#                         flag_relposned_expired = True
#                     self._wait(iteration_timestamp)
#                     continue
#
#                 # Reset GPS flags
#                 if flag_no_gps_fix:
#                     flag_no_gps_fix = False
#                 if flag_invalid_datetime:
#                     flag_invalid_datetime = False
#                 if flag_invalid_heading:
#                     flag_invalid_heading = False
#                 if flag_pvt_expired:
#                     flag_pvt_expired = False
#                 if flag_relposned_expired:
#                     flag_relposned_expired = False
#
#                 # Correct HyperSAS THS Compass
#                 self.hypersas.compass_adj = get_true_north_heading(self.hypersas.compass,
#                                                                    self.gps.latitude, self.gps.longitude,
#                                                                    self.gps.datetime, self.gps.altitude)
#
#                 # Get Heading
#                 self.ship_heading = self.get_ship_heading()
#
#                 # Smooth Heading (not yet implemented)
#                 #if self.filter:
#                 #    ship_heading_tmp = self.filter.update(ship_heading_tmp)
#                 #self.ship_heading = ship_heading_tmp
#
#
#                 # Compute aimed indexing table orientation
#
#                 aimed_indexing_table_orientation = self.pilot.steer(self.sun_azimuth, self.ship_heading)
#                 if isnan(aimed_indexing_table_orientation):
#                     if not flag_no_position:
#                         self.__logger.info('No orientation available.')
#                         flag_no_position = True
#                 else:
#                     # Update Tower
#                     if abs(self.indexing_table.get_position() - aimed_indexing_table_orientation) \
#                             > self.HEADING_TOLERANCE:
#                         if self.indexing_table.get_stall_flag():
#                             if not flag_stalled:
#                                 self.__logger.warning('Indexing table stalled')
#                                 flag_stalled = True
#                         else:
#                             self.indexing_table.set_position(aimed_indexing_table_orientation)
#                             if flag_stalled:
#                                 flag_stalled = False
#                             if flag_no_position:
#                                 flag_no_position = False
#
#                 if first_iteration:
#                     first_iteration = False
#             except Exception as e:
#                 self.__logger.critical(e)
#
#             # Wait before next iteration
#             if self.alive:
#                 self._wait(iteration_timestamp)
#
#     def _wait(self, start_iter):
#         delta = self.refresh_delay - (time() - start_iter)
#         if delta > 0:
#             if delta > 0.5:
#                 start_sleep = time()
#                 while time() - start_sleep < delta and self.alive:
#                     sleep(0.1)
#             else:
#                 sleep(delta)
#         else:
#             self.__logger.warning('cannot keep up with refresh rate, slowing down')
#             sleep(1 + abs(self.refresh_delay))
#
# class ValidatePilot:
#     def __init__(self, cfg):
#         # self.compass_on_tower = cfg.getboolean(self.__class__.__name__, 'compass_mounted_on_indexing_table', fallback=False)
#         self.compass_zero = normalize_angle(cfg.getfloat(self.__class__.__name__, 'gps_orientation_on_ship', fallback=0))
#         self.tower_zero = normalize_angle(cfg.getfloat(self.__class__.__name__, 'indexing_table_orientation_on_ship', fallback=0))
#         self.tower_limits = [float('nan'), float('nan')]
#         self.set_tower_limits(cfg.get(self.__class__.__name__, 'valid_indexing_table_orientation_limits').replace('[', '').replace(']', '').split(','))
#         self.target = float('nan')#cfg.getfloat(self.__class__.__name__, 'optimal_angle_away_from_sun', fallback=135)
#
#     def set_tower_limits(self, limits):
#         # Tower limits with testing? Prevent Wires being crossed?
#         self.tower_limits = [normalize_angle(float(v)) for v in limits]
#
#     def steer(self, sun_azimuth, ship_heading):
#         # Get both aimed heading options
#         #aimed_heading_options = [sun_azimuth + self.target, sun_azimuth - self.target]
#         # Get headings
#         tower_zero_heading = ship_heading - self.tower_zero
#         # Change from magnetic north referential (heading) to tower referential (orientation)
#         #tower_orientation_options = [normalize_angle(aimed_heading_options[0] - tower_zero_heading),
#         #                             normalize_angle(aimed_heading_options[1] - tower_zero_heading)]
#
#         # Check if options are in tower limits
#         valid_options = 0
#         if self.tower_limits[0] == self.tower_limits[1]:
#             # Special case: no tower limits => all options are valid prefer first options (arbitrary choice)
#             return tower_orientation_options[0]
#         elif self.tower_limits[0] < self.tower_limits[1]:
#             if self.tower_limits[0] <= tower_orientation_options[0] <= self.tower_limits[1]:
#                 valid_options += 1
#             if self.tower_limits[0] <= tower_orientation_options[1] <= self.tower_limits[1]:
#                 valid_options += 2
#         elif self.tower_limits[0] > self.tower_limits[1]:
#             if tower_orientation_options[0] >= self.tower_limits[0] or \
#                     self.tower_limits[1] >= tower_orientation_options[0]:
#                 valid_options += 1
#             if tower_orientation_options[1] >= self.tower_limits[0] or \
#                     self.tower_limits[1] >= tower_orientation_options[1]:
#                 valid_options += 2
#
#         if not valid_options:
#             # No option
#             return float('nan')
#         elif valid_options < 3:
#             # One option
#             return tower_orientation_options[valid_options - 1]
#         else:
#             # Two option: find the furthest away from the tower limits
#             # Get distance between tower limits and each aimed orientation option
#             dist_options = [min(abs(normalize_angle(self.tower_limits[0] - tower_orientation_options[0])),
#                                 abs(normalize_angle(self.tower_limits[1] - tower_orientation_options[0]))),
#                             min(abs(normalize_angle(self.tower_limits[0] - tower_orientation_options[1])),
#                                 abs(normalize_angle(self.tower_limits[1] - tower_orientation_options[1])))]
#             return tower_orientation_options[dist_options.index(max(dist_options))]
#
#     def get_ship_heading(self, compass_heading, tower_orientation_correction=None):
#         if tower_orientation_correction is None:
#             # Assume compass heading is mounted on ship
#             return normalize_angle(compass_heading - self.compass_zero)
#         else:
#             # Assume compass is mounted on tower so need to take that into account
#             return normalize_angle(compass_heading + tower_orientation_correction - self.tower_zero - self.compass_zero)