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
Install python3.8 from source as not available as default package on Raspberry Pi.


Download and install pySatlantic, this module is not yet on pip and is required to parse frames from Satlantic instruments. It is installed in editable mode in order to be able to update it through a simple `git pull`.

    git clone https://github.com/doizuc/pySatlantic
    sudo pip3.8 install -e ~/pySatlantic

Download pySAS and install its requirements    

    git clone https://github.com/doizuc/pySAS
    sudo pip3.8 install -r requirements.txt

When installing on Raspberry Pi the package rpi.gpio is required to control the GPIO port

    sudo pip3.8 install rpi.gpio

Must run sudo pip3.8 to install packages otherwise packages are not found when execute pySAS with sudo.
sudo is likely required to control the gpio of the RPi.

need to do the assembly

Notes on libraries used to date
dash-1.6.1 to 1.9.1
dash-bootstrap-components-0.7.2 to 0.9.1
pyserial>=3.4
pysolar==0.8
geomag
    
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

GPIO pins:
  + Indexing Table: 23
  + GPS: 24
  + HyperSAS: 5
  + Es: 6
  + UPS: 27: UPS alive, 17: power failure, 18: Pi alive (according to documentation)
  + UPS: 27: UPS alive, 22: power failure, 18: Pi alive (according to pin connected)


## TODO
  + inspect low power detected by UPS hat
      /opt/vc/bin/vcgencmd get_throttled
      https://raspberrypi.stackexchange.com/questions/60593/how-raspbian-detects-under-voltage
  + check GPS error:
      ERROR:GPS:A stream read returned 1786 bytes, expected 46385 bytes
      ERROR:GPS:device disconnected or multiple access on port?
  + add option to turn on and off gps in manual mode
  
  https://www.arrow.com/en/research-and-events/articles/the-best-power-supplies-for-your-dev-board


