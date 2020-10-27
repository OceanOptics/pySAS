#!/usr/bin/env bash

if [[ $EUID -ne 0 ]]; then 
	echo "Please switch to root user (sudo su)."
	echo "Note that pi user will be deleted hence you cannot be connected over ssh with that user."
	exit
fi

echo
echo "Secure"
echo "======"
echo "Source: https://www.raspberrypi.org/documentation/configuration/security.md"

echo
echo "Add User misclab"
echo "----------------"
adduser misclab
usermod -a -G adm,dialout,cdrom,sudo,audio,video,plugdev,games,users,input,netdev,gpio,i2c,spi misclab

echo "Make sudo require password"
sed -i 's/pi/misclab/' /etc/sudoers.d/010_pi-nopasswd
sed -i 's/NOPASSWD/PASSWD/' /etc/sudoers.d/010_pi-nopasswd

# echo "Delete user pi (warning regarding the group pi can be safely ignored)"
# pkill -u pi
# deluser -remove-home pi

echo 
echo "Ensure latest security fix"
echo "---------------------------"
apt update
apt full-upgrade

# echo
# echo "Setup firewall"
# echo "--------------"
# echo "open: 22 (ssh/tcp) and 8050 (pySAS)"
# apt install -y ufw
# ufw limit ssh/tcp
# ufw enable

echo
echo "Setup fail2ban"
echo "--------------"
echo "ban ssh after 5 failed login"
apt install -y fail2ban
cp /etc/fail2ban/jail.conf /etc/fail2ban/jail.local
read -r -d '' CFG <<- EOM 

	[ssh]
	enabled  = true
	port     = ssh
	filter   = sshd
	logpath  = /var/log/auth.log
	maxretry = 5
	bantime = -1

EOM
echo "$CFG" >> /etc/fail2ban/jail.local 
service fail2ban restart


read -r -d '' MSG <<- EOM
	
	Please logout and log back in as user misclab.
	Then delete user pi as follow.

		pkill -u pi
		deluser -remove-home pi

	Warning regarding the group pi can be safely ignored.

EOM
echo "$MSG"
