#!/usr/bin/env bash

if [[ $EUID -ne 0 ]]; then
	echo "Please switch to root user (sudo su)."
	exit
fi

echo
echo "Install pySAS"
echo "============="

echo "Install python3 package with apt"
# apt's version of plotly is not up to date hence install directly in venv
apt install -y python3-pip python3-numpy python3-serial python3-rpi.gpio python3-gpiozero

echo "Install pySAS"
cp -r pySAS /usr/local/bin/
python3 -m venv --system-site-packages /usr/local/bin/pySAS/venv
source /usr/local/bin/pySAS/venv/bin/activate
pip3 install -r requirements.txt
deactivate

echo "Copy configuration files and update settings"
rm /usr/local/bin/pySAS/pysas_cfg.ini  # Remove to prevent confusion as not used
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
	ExecStart=/usr/local/bin/pySAS/venv/bin/python3 -u -m pySAS /mnt/data_disk/pysas_cfg.ini
	WorkingDirectory=/mnt/data_disk
	StandardOutput=inherit
	StandardError=inherit
	Restart=on-failure
	User=misclab

	[Install]
	WantedBy=multi-user.target
EOM
echo "$CFG" >> /etc/systemd/system/pysas.service
systemctl daemon-reload
systemctl enable pysas.service

# Grant permission to all users to shutdown command
echo "Authorize shutdown"
chmod 4755 /sbin/shutdown

# Grant permission to all users to date command
echo "Authorize date"
chmod 4755 /bin/date

# Open firewall (already done in 1_secure.sh)
# echo "Open firewall port 8050"
# ufw allow 8050
