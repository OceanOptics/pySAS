#!/usr/bin/env bash

if [[ $EUID -ne 0 ]]; then
	echo "Please switch to root user (sudo su)."
	exit
fi

echo
echo "Install pySAS"
echo "============="

echo "Install pip3"
sudo apt install -y python3-pip
echo "Install numpy (as version installed with pip3 doesn't work)"
sudo apt install -y python3-numpy

echo "Instal RPi specific python package"
pip3 install rpi.gpio

echo "Download pySAS"
curl -L  https://github.com/OceanOptics/pySAS/archive/refs/heads/master.zip > master.zip
unzip master.zip
cd pySAS-master

echo "Install pySAS"
pip3 install -r requirements.txt
cp -r pySAS /usr/local/bin/
rm /usr/local/bin/pySAS/pysas_cfg.ini
# python3.8 setup.py install
# Copy configuration file and update settings
cp pySAS/pysas_cfg.ini /mnt/data_disk/pysas_cfg.ini
sed -i "s/ui_update_cfg = False/ui_update_cfg = True/" /mnt/data_disk/pysas_cfg.ini
sed -i "/^sip/d" /mnt/data_disk/pysas_cfg.ini
# Make backup of configuration file
cp /mnt/data_disk/pysas_cfg.ini /mnt/data_disk/pysas_cfg_backup.ini
chown misclab:misclab /mnt/data_disk/pysas_cfg*

# Setup service for misclab user
# source: https://www.raspberrypi.org/documentation/linux/usage/systemd.md
echo "Setup pySAS service"
read -r -d '' CFG <<- EOM
	[Unit]
	Description=pySAS Service
	After=network.target

	[Service]
	Environment=PYTHONPATH=/usr/local/bin
	ExecStart=/usr/bin/python3 -u -m pySAS /mnt/data_disk/pysas_cfg.ini
	WorkingDirectory=/mnt/data_disk
	StandardOutput=inherit
	StandardError=inherit
	Restart=on-failure
	User=misclab

	[Install]
	WantedBy=multi-user.target
EOM
echo "$CFG" >> /etc/systemd/system/pysas.service
systemctl enable pysas.service

# Grant permission to all users to shutdown command
echo "Authorize shutdown"
chmod 4755 /sbin/shutdown

# Grant permission to all users to date command
echo "Authorize date"
chmod 4755 /bin/date

# Open firewall
# echo "Open firewall port 8050"
# ufw allow 8050
