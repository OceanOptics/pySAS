pySAS
=====
[![License: AGPL v3](https://img.shields.io/badge/License-AGPLv3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Python >3.7](https://img.shields.io/badge/Python->3.7-blue.svg)](https://www.python.org/downloads/)

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
The installation process requires to configure the host computer (e.g. RaspberryPi 3B) and installing pySAS software as a service on the computer. Scripts and explanations are provided in the folder `sbc_setup`.

The RTK GPS modules (simpleRTK2B+heading kit) should be configured in MovingBase and Rover at 1Hz. See the [tutorial](https://www.ardusimple.com/configuration-files/) from the manufacturer for instructions to upload [configuration files](https://www.ardusimple.com/simplertk2heading-hookup-guide/).

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

### Heading Source
By default, pySAS computes the ship's heading from its own dual RTK-GPS (moving base + rover, `heading_source = gps_relative_position` in `pysas_cfg.ini`). This requires no external input, but its accuracy depends on the RTK fix quality of the two onboard antennas.

If the vessel has its own integrated GPS+IMU navigation system (e.g. Applanix POS MV) that broadcasts heading over the ship's network, pySAS can use it instead -- and become fully independent of its own two GPS antennas (heading, sun position, clock sync, and the position logged in the raw files all switch to POS MV; the onboard GPS keeps running but stops logging its own position, so a hardware failure on either antenna no longer affects operation):
  1. Add a `[POSMV]` section to `pysas_cfg.ini` with the UDP `host`/`port` the ship's system broadcasts NMEA-like sentences on (`INGGA`/`INZDA`/`INHDT`/`PASHR`/`INVTG`), and restart pySAS.
  2. In the web interface, open Settings and set Heading Source to "POS MV from ship navigation".

POS MV reports the ship's true heading directly (already calibrated to the vessel), so the GPS Orientation setting -- which corrects for the RTK antennas' mounting offset -- does not apply when this source is selected.

Two additional sources (`gps_motion`, `gps_vehicle`) and a legacy `ths_heading` option (HyperSAS' own compass) exist but are only selectable by editing `heading_source` directly in `pysas_cfg.ini`, not from the Settings menu.
