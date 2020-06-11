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
  
## Installation
Requirements: python 3.8
Download pySAS and install pySAS  

    git clone https://github.com/doizuc/pySAS
    pip3.8 install dash>=1.9.1 dash-bootstrap-components geomag gpiozero numpy pyserial>=3.4 pysolar==0.8 pytz ubxtranslator pySatlantic

When installing on Raspberry Pi the package rpi.gpio is required to control the GPIO port

    sudo pip3.8 install rpi.gpio

## Deployment Environment
Using the flask built-in server for now by setting `host=0.0.0.0`. As typically one user is expected at a time, this is an ok solution.

The application was not deployed successfully with uwsgi and nginx (steps below and following tutorial: https://www.raspberrypi-spy.co.uk/2018/12/running-flask-under-nginx-raspberry-pi/). The global variable `runner` was instantiated multiple times and the page could not be rendered.

    cd ~/pySAS
    sudo vim uwsgi_runner.py
    
        from pySAS.ui import app as application

        if __name__ == "__main__":
            application.run()
            
    uwsgi --socket 0.0.0.0:8000 --protocol=http --enable-threads --file uwsgi_runner.py 
    
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
  
##### Software configuration
  + Follow tutorial to secure a raspberry pi
  + Follow tutorial to automatically switch between access point and client
  + Install python3.8
  + Give permission to shutdown so that any user can turn off the pi with no root privilege

        sudo chmod 4755 /sbin/shutdown
