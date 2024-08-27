#!/usr/bin/env bash

if [[ $EUID -ne 0 ]]; then
	echo "Please switch to root user (sudo su)."
	exit
fi

echo
echo "Update pySAS"
echo "============="
echo "Pins 39 (GND) and 40 (GPIO21) should be connected to enable read-write file system."
echo "Python 3.8.6 should be installed and accessed from python3 or pip3"
echo ""

echo "Download pySAS"
curl -L  https://github.com/OceanOptics/pySAS/archive/refs/heads/master.zip > master.zip
unzip master.zip
cd pySAS-master

echo "Stop pySAS software"
systemctl stop pysas.service

echo "Update python3 requirements"
pip3 install --upgrade -r requirements.txt

echo "Replace pySAS software"
cp -r pySAS /usr/local/bin/
rm /usr/local/bin/pySAS/pysas_cfg.ini

# Backup previous configuration file
cp /mnt/data_disk/pysas_cfg.ini /mnt/data_disk/pysas_cfg.ini.previous_backup

# Copy configuration file and update settings
cp pySAS/pysas_cfg.ini /mnt/data_disk/pysas_cfg.ini
sed -i "s/ui_update_cfg = False/ui_update_cfg = True/" /mnt/data_disk/pysas_cfg.ini
sed -i "/^sip/d" /mnt/data_disk/pysas_cfg.ini

# Make backup of configuration file
cp /mnt/data_disk/pysas_cfg.ini /mnt/data_disk/pysas_cfg_backup.ini
chown misclab:misclab /mnt/data_disk/pysas_cfg*

echo "Remove installation files"
cd ..
rm master.zip
rm -r pySAS-master

echo "Update Complete, restarting pySAS"
systemctl start pysas.service
