import unittest
from pySAS.runner import get_true_north_heading
from datetime import datetime

class TestAutoPilot(unittest.TestCase):

    def test_get_true_north_heading(self):
        """ Tested against NOAA web model
        https://www.ngdc.noaa.gov/geomag/calculators/magcalc.shtml#igrfwmm
        """
        self.assertAlmostEqual(get_true_north_heading(0, 40, -70, datetime(2020,4,2), 1000), 360 - 14.2833, places=0)
        self.assertAlmostEqual(get_true_north_heading(0, 40, -170, datetime(2020, 4, 2), 1000), 7.8588, places=0)


if __name__ == '__main__':
    unittest.main()