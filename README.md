pySAS
=====
[![License: AGPL v3](https://img.shields.io/badge/License-AGPLv3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Python 3.8](https://img.shields.io/badge/Python-3.8-blue.svg)](https://www.python.org/downloads/)

_Autonomous above water radiometric measurements_

pySAS is a software orienting a set of radiometers at an angle phi_v from the sun azimuth, controlling their power, and logging their data. It takes advantage of a dual GPS RTK to know the heading and location of the system. The latter is used to estimate the sun position (Reda and Andreas 2005), which combined with the former allow to calculate the aimed heading of the sensor during daytime or turn off the sensors during night time. The data collected can be visualized in real-time through a web interface. This user interface can also be used to adjust settings (e.g. the minimum sun elevation to rake measurements, the valid range of heading for the sensors). The system is composed of an indexing table (custom made), a dual GPS RTK (ArduSimple simpleRTK2B and simpleRTK2Blite), a set of radiometers (Satlantic HyperSAS).

The HyperSAS is composed of the following sensors:
  + THS: Tilt Heading Sensor (SatNet Master)
  + Li: Hyperspectral sea-surface radiance sensor (point down)
  + Lt: Hyperspectral indirect radiance sensor (point up)
  + Es: Hyperspectral irradiance sensor (could be logged independently)
  
 Recommended HyperSAS setup:
  + the zenith and nadir angle from the Li and Lt sensors must be the same, comprise between 30 and 50 degrees, ideally 40 degrees (HyperSAS Manual and Mobley 1999)
  + the azimuth angle should be between 90 and 180 degrees away from the solar plane, with an optimal angle of 90 degrees according to the HyperSAS documentation and 135 degrees according to Mobley (1999)
  
### Note on version of packages used
dash-1.6.1 to 1.9.1
dash-bootstrap-components-0.7.2 to 0.9.1
pyserial 3.4
pySatlantic is not yet shared pip so it has to be installed manually