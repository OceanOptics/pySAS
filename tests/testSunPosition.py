import unittest
from datetime import datetime
import pytz
from pySAS.runner import get_sun_position
from collections import namedtuple


DataContainer = namedtuple('Data', ['latitude', 'longitude', 'datetime', 'azimuth', 'elevation'])

# Stillwater data set
# Computed from NOAA website: https://www.esrl.noaa.gov/gmd/grad/solcalc/
STILLWATER = DataContainer(latitude=44.9112099, longitude = -68.6872212,
                           datetime=[datetime(2020, 6, 11, 3, 23, 11).astimezone(pytz.timezone('US/Eastern')),
                                  datetime(2020, 6, 11, 4, 23, 11).astimezone(pytz.timezone('US/Eastern')),
                                  datetime(2020, 6, 11, 8, 23, 11).astimezone(pytz.timezone('US/Eastern')),
                                  datetime(2020, 6, 11, 10, 23, 11).astimezone(pytz.timezone('US/Eastern')),
                                  datetime(2020, 6, 11, 12, 23, 11).astimezone(pytz.timezone('US/Eastern')),
                                  datetime(2020, 6, 11, 13, 23, 11).astimezone(pytz.timezone('US/Eastern')),
                                  datetime(2020, 6, 11, 14, 23, 11).astimezone(pytz.timezone('US/Eastern')),
                                  datetime(2020, 6, 11, 16, 23, 11).astimezone(pytz.timezone('US/Eastern')),
                                  datetime(2020, 6, 11, 18, 23, 11).astimezone(pytz.timezone('US/Eastern')),
                                  datetime(2020, 6, 11, 20, 23, 11).astimezone(pytz.timezone('US/Eastern')),
                                  datetime(2020, 6, 11, 21, 23, 11).astimezone(pytz.timezone('US/Eastern'))],
                           azimuth=[39.12, 50.81, 91.27, 118.18, 172.98, 208.52, 234.51, 264.55, 285.01, 305.09, 316.33],
                           elevation=[-11.83, -4.27, 35.1, 55.56, 68.12, 66.09, 58.99, 39.13, 18.11, -0.81, -9.12])

# Station Papa data set
# Computed from NOAA website: https://www.esrl.noaa.gov/gmd/grad/solcalc/
STATION_PAPA = DataContainer(latitude = 50.1, longitude = -144.9,
                             datetime=[datetime(2020, 6, 11, 3, 23, 11, tzinfo=pytz.utc),
                                  datetime(2020, 6, 11, 9, 23, 11, tzinfo=pytz.utc),
                                  datetime(2020, 6, 11, 12, 23, 11, tzinfo=pytz.utc),
                                  datetime(2020, 6, 11, 15, 23, 11, tzinfo=pytz.utc),
                                  datetime(2020, 6, 11, 18, 23, 11, tzinfo=pytz.utc),
                                  datetime(2020, 6, 11, 21, 23, 11, tzinfo=pytz.utc),
                                  datetime(2020, 6, 11, 0, 23, 11, tzinfo=pytz.utc)],
                             azimuth=[282.43, 356.12, 37.52, 71.78, 106.83, 171.78, 245.02],
                             elevation=[20.08, -16.67, -8.25, 15.12, 43.5, 62.88, 48.3])

NOAA_DATASETS = [STATION_PAPA, STILLWATER]


class TestAutoPilot(unittest.TestCase):

    def test_noaa_datasets(self):
        for dataset in NOAA_DATASETS:
            for dt, a, z in zip(dataset.datetime, dataset.azimuth, dataset.elevation):
                computed_elevation, computed_azimuth = get_sun_position(dataset.latitude, dataset.longitude, dt)
                # print(dt, computed_elevation, z)
                self.assertAlmostEqual(computed_elevation, z, delta=0.4)
                if computed_elevation > 0:
                    # print(dt, computed_azimuth, a)
                    self.assertAlmostEqual(computed_azimuth, a, delta=0.1)
