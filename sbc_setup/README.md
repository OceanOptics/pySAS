Setup Raspberry Pi
==================

### Copy image to SD card
Download the latest version of Raspian OS and copy it to the sd card. A reminder of the command for macOS is below. Detailled instructions are available on the Raspberry Pi website. The OS version installed at time of writting was Buster (2020-08-20).

	diskutil list
	diskutil unmountDisk /dev/disk2
	sudo dd bs=1m if=2020-08-20-raspios-buster-armhf-lite.img of=/dev/rdisk2; sync
	diskutil unmountDisk /dev/disk2


### First boot
The first step to configure your Raspbrry Pi (rpi) is to run `sudo raspi-config` and setup the following options:
	+ localisation options:
		+ change local to us_US.UTF-8
		+ change keyboard layout to US
		+ change time zone to UTC
		+ change WLAN Country to US
	+ interface enable ssh
	+ network options set hostname to pysas### with ### the serial number (e.g. pysas003)


### Secure Pi
First update the raspberry pi.

	sudo apt update
	sudo apt full-upgrade
	sudo reboot

Using another computer on the same local network copy the folder sbc_setup to the Raspberry Pi /tmp folder with an ftp client. Swith to root user (`sudo su`). Run the secure script `bash 1_secure.sh`. Logout and re-login as misclab, with the password defined while running the secure script. Now delete the user pi.
	
	sudo pkill -u pi
	sudo deluser -remove-home pi

Note that ufw seems to pose problem with the WiFi hotspot, hence this software was removed from the installation.


### Set Wifi Hotspot
Run the script `3_wifi-hotspot.sh` as root. The pySAS wifi SSID is its hostname (e.g. pysas003) and the password is `Phyt0plankt0n!`.


### Set external drive
An external drive is needed to store the data from pySAS as the SD card is set in read-only mode.

Partition and format the external drive in journaled ext4 following this steps. First find the disk to format:

	sudo fdisk -l

Partition the disk with the fsdisk utility.

	sudo fdisk /dev/sda

Use the formating utility as follow: create a new partiiton table with `g`, create a new partition with `n` leave default parameters, and write partition to disk with `w`.

Format the new partition:

	sudo mkfs -t ext4 /dev/sda1*

Then run the script `5_external-drive.sh` to mount the disk at set permissions.

### Setup pySAS Software
Setup pySAS by running the script `6_pySAS.sh`. At the time of setup Raspbian Buster carried python3.7 which is supported by pySAS and the packaged its based on.


### Set system in read only mode
Set the SD Card in read-only to prevent any software corruption in case of unexpected shutdown. Run the script `7_read-only.sh` and enable boot-time read/write jumper on GPIO port 21. On current versions of pySAS the GPIO-halt utility and kernel panic watchdog were not enabled.

### Alternative is to clone SD Card
To clone the SD card to a new one, use the following command. This will create an image of the SD card on the computer. The image can then be copied to a new SD card.

	diskutil list # find the disk number of the SD card
	sudo dd bs=4M if=/dev/disk2 of=pySAS-v1.0.0-`date +%Y%m%d`.img

Set file system in read-write mode: connect pins 39 (GND) and 40 (GPIO21).
Boot RPi.
Change the hostname with the command `sudo raspi-config` > network options > set hostname to pysas### with ### the serial number (e.g. pysas004).
Use script `5_external-drive.sh` to adjust the UUID of the external drive.
Use part of script `6_pySAS.sh` to download configuration files and copy them to the external drive.
Shutdown the RPi.
Disconnect jumper between pins 39 and 40.
Boot RPi, and enjoy pySAS.
