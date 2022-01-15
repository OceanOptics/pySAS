pySAS
=====
[![License: AGPL v3](https://img.shields.io/badge/License-AGPLv3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Python 3.8](https://img.shields.io/badge/Python-3.8-blue.svg)](https://www.python.org/downloads/)

_Autonomous above water radiometric measurements._

pySAS is a user-friendly system for optimal radiometer positioning relative to the sun to measure water leaving reflectance. The system is currently compatible with Sea-Bird Scientific radiometers, though, it is easily adapted to other radiometers. An important advantage of the pySAS is its web-interface that allows simple control of the system and visualization of the measurements (Lt, Li, and Es) in real-time, which ensures that quality data are recorded. In addition, the data recorded with pySAS can be ingested by [HyperInSPACE](https://github.com/nasa/HyperInSPACE) for automatic processing.

## Hardware
pySAS system's main parts:
  + Sea-Brd Scientific HyperSAS:
    + THS: Tilt Heading Sensor (SatNet Master)
    + Li: Hyperspectral indirect radiance sensor (point up)
    + Lt: Hyperspectral sea-surface radiance sensor (point down)
    + Es: Hyperspectral irradiance sensor
  + Tower: supports radiometers and orient them
  + Controller Box:
    + dual RTK-GPS: Get heading and location of system (ArduSimple simpleRTK2B and simpleRTK2Blite)
    + SBC: log the data and compute the radiometers' orientation using the sun position algorithm of Reda and Andreas (2005)

To build your own system the complete bill of material (BOM) is available at [docs/pySAS.BOM.xlsx](https://github.com/OceanOptics/pySAS/blob/master/docs/pySAS.BOM.xlsx). Drawings of the custom-made tower are available at [docs/pySAS.TowerDrawings.R2.pdf](https://github.com/OceanOptics/pySAS/blob/master/docs/pySAS.TowerDrawings.R2.pdf). Illustrations to make the controller box are available at [docs/pySAS.ControllerBoxAssembly.pdf](https://github.com/OceanOptics/pySAS/blob/master/docs/pySAS.ControllerBoxAssembly.pdf). The user guide is shared at [docs/pySAS.UserGuide.pdf](https://github.com/OceanOptics/pySAS/blob/master/docs/pySAS.UserGuide.pdf).

## Software Configuration
The installation process requires to configure the host computer (e.g. RaspberryPi 3B+) and installing pySAS software as a service on the computer. Scripts and explanations are provided in the folder `sbc_setup`.

The RTK GPS modules (simpleRTK2B+heading kit) should be configured in MovingBase and Rover at 1Hz. See the tutorial from the manufacturer for instructions [ArduSimple](https://www.ardusimple.com/configuration-files/).

Recommended pySAS configuration:
  + the zenith and nadir angle from the Li and Lt sensors must be the same, comprise between 30 and 50 degrees, ideally 40 degrees (HyperSAS Manual and Mobley 1999)
  + the azimuth angle should be between 90 and 180 degrees away from the solar plane, with an optimal angle of 90 degrees according to the HyperSAS documentation and 135 degrees according to Mobley (1999)
  + GPIO Pins:
    + Indexing Table: 23
    + GPS: 6
    + HyperSAS: 24
    + Es: 5
  + Serial Ports:
    + 0: Indexing Table
    + 1: HyperSAS
    + 2: Es
    + 3: GPS
