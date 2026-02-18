Setup Raspberry Pi
==================

# Installation from Scratch
## Copy image to SD card
Prepare an SD card with Raspberry Pi imager. At the time of writing (2025-02-19) Bookworm was installed.

  - Device: Raspberry Pi 3 (compatible with 3B or 3B+)
  - Choose OS: Raspberry Pi OS (other) > Raspberry Pi OS Lite (64-bit) 
  - Choose storage: SD Card of your choice
  - Next > Edit Settings:
    - Set hostname to pysas### with ### the serial number (e.g. pysas005)
    - Set username (default is misclab for pysas) and password
    - Set Wireless LAN (optional, convenient to connect over ssh after)
    - Set locale settings:
      - Timezone: Etc/UTC
      - Keyboard: us
    - Tab Services: enable SSH
    - -> Save > Yes > Yes

## First boot
Insert SD Card and power RPi. Connect to RPi over ssh or with a keyboard and monitor (requires plugging the monitor and keyboard before powering the RPi). Make sure your RPi is connected to the internet, preferably via an ethernet cable as the RPi WiFi will be configured to a hotspot.

The first step to configure your Raspbrry Pi (rpi) is to run `sudo raspi-config` and set up the following options:
  - Advance Options:
    - Expand Filesystem:
      - Select Yes
  - Localisation Options:
    - change local to en_US.UTF-8
    - change WLAN Country to US
    - change Timezone to Other/UTC
  - Interface Options:
    - Set Serial Port to:
      - Enable login shell: No
      - Enable serial port hardware: Yes


Download the pySAS repository and make configuration scripts executable.

	sudo apt install -y git
	git clone https://github.com/OceanOptics/pySAS.git
	cd pySAS
	chmod 744 sbc_setup/*.sh

Run configuration scripts (answer yes when prompted by scripts).

	sudo su
	./sbc_setup/1_secure.sh
	./sbc_setup/2_wifi-hotspot.sh
	./sbc_setup/3_external-drive.sh  # See section below if external drive is not formated in ext4
	./sbc_setup/4_pysas.sh  # Must be run from the pySAS directory

Check that everything run, then delete temporary pySAS folder in home to avoid confusion in the future,
and set the boot partition in read-only (next section) to prevent any software corruption in case of unexpected shutdown.

    rm -r ~misclab/pySAS

## Set boot partition in read-only
Read-only mode is set through the raspi-config utility. Note that data from pySAS will be stored on an external drive, which stays in read-write mode.

    sudo raspi-config

Navigate down to `Performance Options` > `Overlay File System`. Select `Yes` to both the enable and write-protect questions.
It may take a minute or more while the system works, this is normal. Tab to the “Finish” button and do NOT reboot. 
Edit the cmdline.txt file to prevent boot issues.

    sudo nano /boot/firmware/cmdline.txt

Find the line that contains `overlayroot=tmpfs` and change it to `overlayroot=tmpfs:recurse=0`. 
Save and exit the file (Ctrl+X, Y, Enter). You can now reboot the system.

After rebooting, the system will be in read-only mode.

To temporarily restore Read/Write mode enter command:

    sudo mount -o remount,rw /boot
	
Reboot system to restore read-only state.

If you enable overlayfs without replacing `overlayroot=tmpfs` to `overlayroot=tmpfs:recurse=0` in `/boot/firmware/cmdline.txt`, then you need to switch back to read-write mode with raspi-config:

1. Disable overlayfs in raspi-config
2. Reboot
3. Disable write-only boot partition
4. Reboot
5. Turn on the overlay in raspi-config
6. Edit `/boot/firmware/cmdline.txt` replacing `overlayroot=tmpfs` to `overlayroot=tmpfs:recurse=0`
7. Apply changes `sudo update-initramfs -u` and reboot (note that despite error message system is in read-only mode)

References: [Adafruit](https://learn.adafruit.com/read-only-raspberry-pi), [StackExchange](https://raspberrypi.stackexchange.com/questions/144661/enabling-overlayfs-makes-external-drives-read-only), [GitHub](https://github.com/raspberrypi/bookworm-feedback/issues/137)

## Set external drive
An external drive is needed to store the data from pySAS as the SD card is set in read-only mode.

Partition and format the external drive in journaled ext4 following these steps. First find the disk to format:

	sudo fdisk -l

Partition the disk with the fsdisk utility.

	sudo fdisk /dev/sda

Use the formating utility as follows: create a new partition table with `g`, create a new partition with `n` leave default parameters, and write partition to disk with `w`.

Format the new partition:

	sudo mkfs.ext4 /dev/sda1

Then run the script `3_external-drive.sh` to mount the disk at set permissions.

# Installation from pySAS Image
Image can be obtained from another pySAS (see section Clone SD Card)

### Set SD from Image
Boot RPi and temporarily set the system in read/write mode (it will reset after reboot).

    sudo mount -o remount,rw /boot

Change the hostname with the command `sudo raspi-config` > network options > set hostname to pysas### with ### the serial number (e.g. pysas004).
Use the script `2_wifi-hotspot.sh` to update the Wi-Fi hotspot name.
Use the script `3_external-drive.sh` to adjust the UUID of the external drive.
Download the configuration file from this repository and copy them to the external drive:
    
    cp pySAS/pysas_cfg.ini /mnt/data_disk/pysas_cfg.ini
    sed -i "s/ui_update_cfg = False/ui_update_cfg = True/" /mnt/data_disk/pysas_cfg.ini
    sed -i "/^sip/d" /mnt/data_disk/pysas_cfg.ini
    cp /mnt/data_disk/pysas_cfg.ini /mnt/data_disk/pysas_cfg_backup.ini

Optional expand the file system with `sudo raspi-config` > Advanced Options > Expand Filesystem.
Reboot the RPi.
Enjoy pySAS.

### Clone SD Card to Share Image
To clone the SD card to a new one, use the following command. This will create an image of the SD card on the computer. The image can then be copied to a new SD card.

	diskutil list # find the disk number of the SD card
	sudo dd bs=4M if=/dev/disk2 of=pySAS-v1.0.0-`date +%Y%m%d`.img

### Network Configuration
To show current connection use:

    nmcli connection show

To configure the network (wifi connection, ip settings) use:

    sudo nmtui
 