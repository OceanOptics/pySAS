import unittest
import configparser
from pySAS.runner import AutoPilot
import numpy as np


cfg = configparser.ConfigParser()
cfg.add_section('AutoPilot')
# cfg.set('AutoPilot', 'compass_mounted_on_indexing_table', 'False')
cfg.set('AutoPilot', 'gps_orientation_on_ship', '0')
cfg.set('AutoPilot', 'indexing_table_orientation_on_ship', '0')
cfg.set('AutoPilot', 'valid_indexing_table_orientation_limits', '[-180, 180]')
cfg.set('AutoPilot', 'optimal_angle_away_from_sun', '135')

class TestAutoPilot(unittest.TestCase):

    def setUp(self):
        self.pilot = AutoPilot(cfg)

    def test_steer_1(self):
        """ Test 1: sun_azimuth = 45 deg N, ship_heading = -45 deg N """
        # All positions are available
        self.pilot.set_tower_limits([-180, 180])
        self.assertEqual(self.pilot.steer(sun_azimuth=45, ship_heading=-45), -135.)
        # Only position 1
        self.pilot.set_tower_limits([-90, 0])
        self.assertEqual(self.pilot.steer(sun_azimuth=45, ship_heading=-45), -45.)
        # Only position 2 (test reverse limits)
        self.pilot.set_tower_limits([180, -90])
        self.assertEqual(self.pilot.steer(sun_azimuth=45, ship_heading=-45), -135.)
        # Both position available optimal for options 1
        self.pilot.set_tower_limits([-140, 0])
        self.assertEqual(self.pilot.steer(sun_azimuth=45, ship_heading=-45), -45.)
        # Both position available optimal for options 2
        self.pilot.set_tower_limits([-180, -40])
        self.assertEqual(self.pilot.steer(sun_azimuth=45, ship_heading=-45), -135.)

    def test_steer_2(self):
        """ Test 2: sun_azimuth = -135 deg N, ship_heading = -45 deg N """
        sun_azimuth = 225
        ship_heading = -45
        # All positions are available
        self.pilot.set_tower_limits([-180, 180])
        self.assertEqual(self.pilot.steer(sun_azimuth, ship_heading), 45.)
        # Only position 1
        self.pilot.set_tower_limits([0, 90])
        self.assertEqual(self.pilot.steer(sun_azimuth, ship_heading), 45.)
        # Only position 2
        self.pilot.set_tower_limits([90, 0])
        self.assertEqual(self.pilot.steer(sun_azimuth, ship_heading), 135.)
        # Both position available optimal (equi-distant)
        #   Prefer not moving the system from previous position
        self.pilot.set_tower_limits([0, 180])
        self.assertEqual(self.pilot.steer(sun_azimuth, ship_heading), 135.)
        # Both position available optimal for option 1 but stay in position 2
        #   Not moving as delta between the two options is small, therefore prefer staying to current position
        self.pilot.set_tower_limits([0, 179])
        self.assertEqual(self.pilot.steer(sun_azimuth, ship_heading), 135.)
        # Both position available optimal for option 1
        #   Delta between the two options is large, therefore prefer moving to optimal position
        self.pilot.set_tower_limits([0, 176])
        self.assertEqual(self.pilot.steer(sun_azimuth, ship_heading), 45.)
        # Both position available optimal for option 2
        self.pilot.set_tower_limits([10, 180])
        self.assertEqual(self.pilot.steer(sun_azimuth, ship_heading), 135.)

    def test_steer_3(self):
        """ Test 3: sun_azimuth = -135 deg N, ship_heading = 135 deg N """
        sun_azimuth = 225
        ship_heading = 135
        # All positions are available
        self.pilot.set_tower_limits([-180, 180])
        self.assertEqual(self.pilot.steer(sun_azimuth, ship_heading), -135.)
        # Only position 1
        self.pilot.set_tower_limits([-90, 90])
        self.assertEqual(self.pilot.steer(sun_azimuth, ship_heading), -45.)
        # Only position 2 (test reverse limits)
        self.pilot.set_tower_limits([-180, -90])
        self.assertEqual(self.pilot.steer(sun_azimuth, ship_heading), -135.)
        # Both position available optimal for options 1 (equi-distant, therefore prefer staying to current position)
        self.pilot.set_tower_limits([-180, 0])
        self.assertEqual(self.pilot.steer(sun_azimuth, ship_heading), -135.)
        # Both position available optimal for options 2
        self.pilot.set_tower_limits([-170, 170])
        self.assertEqual(self.pilot.steer(sun_azimuth, ship_heading), -45.)

    def test_steer_4(self):
        """ Test 4: sun_azimuth = 112 deg N, ship_heading = -170 deg N """
        sun_azimuth = 112
        ship_heading = -170
        # All positions are available
        self.pilot.set_tower_limits([-180, 180])
        self.assertEqual(self.pilot.steer(sun_azimuth, ship_heading), 57.)
        # Only position 1
        self.pilot.set_tower_limits([-90, 90])
        self.assertEqual(self.pilot.steer(sun_azimuth, ship_heading), 57.)
        # Only position 2 (test reverse limits)
        self.pilot.set_tower_limits([90, -90])
        self.assertEqual(self.pilot.steer(sun_azimuth, ship_heading), 147.)
        # Both position available optimal for options 1 (equi-distant, no best case)
        self.pilot.set_tower_limits([90, 0])
        self.assertEqual(self.pilot.steer(sun_azimuth, ship_heading), 147.)
        # Both position available optimal for options 2
        self.pilot.set_tower_limits([-170, 170])
        self.assertEqual(self.pilot.steer(sun_azimuth, ship_heading), 57.)

    def test_steer_timeseries(self):
        """ Test timeseries: sun_azimuth = 180 to -45 deg N, ship_heading = -45 +/- 3deg deg N """
        # Generate dataset
        n = 1000
        rs = np.random.RandomState(np.random.MT19937(np.random.SeedSequence(15)))  # Set Random State
        sun_azimuth = np.arange(180, 315, (315-180)/n)
        ship_heading = rs.normal(-45, 1 * 0.341 * self.pilot.min_dist_delta, n)
        tower_orientation = np.empty(n)
        tower_orientation_option = np.empty(n)

        # Test Auto-Pilot when difference between two options needs to be significant before switch
        self.pilot.set_tower_limits([0, 180])
        for i in range(n):
            tower_orientation[i] = self.pilot.steer(sun_azimuth[i], ship_heading[i])
            tower_orientation_option[i] = self.pilot.selected_option
        # Count number of switch
        n_switch_option = sum(np.gradient(tower_orientation_option) != 0) / 2
        self.assertEqual(n_switch_option, 1)

        # Test Auto-Pilot when switch to best option instantly (without taking care of previous option)
        self.pilot.min_dist_delta = 0
        for i in range(n):
            tower_orientation[i] = self.pilot.steer(sun_azimuth[i], ship_heading[i])
            tower_orientation_option[i] = self.pilot.selected_option
        # Count number of switch
        n_switch_option = sum(np.gradient(tower_orientation_option) != 0) / 2
        self.assertGreaterEqual(n_switch_option, 1)

    def test_get_ship_heading(self):
        """ Test 1: retrieve ship heading """
        compass_heading = 15
        self.pilot.compass_zero = 0
        self.assertEqual(self.pilot.get_ship_heading(compass_heading), 15.0)
        self.pilot.compass_zero = 90
        self.assertEqual(self.pilot.get_ship_heading(compass_heading), -75.0)

        self.pilot.tower_zero = 0
        self.pilot.compass_zero = 90
        self.assertEqual(self.pilot.get_ship_heading(compass_heading, tower_orientation_correction=0), -75.0)
        self.assertEqual(self.pilot.get_ship_heading(compass_heading, tower_orientation_correction=90), 15.0)


if __name__ == '__main__':
    unittest.main()