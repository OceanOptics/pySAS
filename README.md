pySAS
=====
[![License: AGPL v3](https://img.shields.io/badge/License-AGPLv3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Python 3.8](https://img.shields.io/badge/Python-3.8-blue.svg)](https://www.python.org/downloads/)

_Autonomous above water radiometric measurements_

pySAS is a software orienting a set of radiometers at an angle phi_v from the sun azimuth, controlling their power, and logging their data. It takes advantage of a dual GPS RTK to know the heading and location of the system. The latter is used to estimate the sun position (Reda and Andreas 2005), which allows to calculate the orientation of the sensors during daytime or turn off the sensors during night time. The measurements from the radiometers can be visualized in real-time through a web interface. The system is composed of a tower supporting the radiometers (custom made, see docs folder), a computer box (custom made, see docs folder), a dual GPS RTK (ArduSimple simpleRTK2B and simpleRTK2Blite), and a set of radiometers (Satlantic HyperSAS).

The HyperSAS is composed of the following sensors:
  + THS: Tilt Heading Sensor (SatNet Master)
  + Li: Hyperspectral indirect radiance sensor (point up)
  + Lt: Hyperspectral sea-surface radiance sensor (point down)
  + Es: Hyperspectral irradiance sensor (could be logged independently)
  
 Recommended HyperSAS setup:
  + the zenith and nadir angle from the Li and Lt sensors must be the same, comprise between 30 and 50 degrees, ideally 40 degrees (HyperSAS Manual and Mobley 1999)
  + the azimuth angle should be between 90 and 180 degrees away from the solar plane, with an optimal angle of 90 degrees according to the HyperSAS documentation and 135 degrees according to Mobley (1999)

## Hardware Configuration
The bill of material (BOM) to build the system is available at `docs/pySAS.BOM.xlsx`.
Drawings of the custom-made tower are available at `docs/pySAS.Tower.R2.pdf`.
Illustrations to make the controller box are available at `docs/pySAS.ControllerBoxAssembly.pdf`
A user guide is shared at `docs/pySAS.UserGuide.pdf`.

## Software Configuration
The installation process requires to configure the host computer (e..g RaspberryPi 3B+) and installing pySAS software as a service on the computer. Scripts and explanations are provided in the folder `sbc_setup`.

The RTK GPS modules (simpleRTK2B+heading kit) should be configured in MovingBase and ROver at 1Hz. See the tutorial from the manufacturer for instructions [ArduSimple](https://www.ardusimple.com/configuration-files/).

## Raspberry Pi Configuration
##### Hardware configuration
GPIO pins:
  + Indexing Table: 23
  + GPS: 6
  + HyperSAS: 24
  + Es: 5
  + UPS: 27: UPS alive, 17: power failure, 18: Pi alive (according to documentation)
  + UPS: 27: UPS alive, 22: power failure, 18: Pi alive (according to pin connected)
  
Serial Ports:
  + 0: Indexing Table
  + 1: HyperSAS
  + 2: Es
  + 3: GPS
