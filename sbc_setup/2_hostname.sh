#!/usr/bin/env bash

if [[ $EUID -ne 0 ]]; then 
	echo "Please switch to root user (sudo su)."
	exit
fi

echo
echo "Set hostname"
echo "============"
echo "Please enter serial number of pySAS hardware (e.g. 001):"
read SN

# Edit hostname in etc files
sed -i "s/raspberrypi/pysas$SN/" /etc/hostname
sed -i "s/raspberrypi/pysas$SN/" /etc/hosts

# Update system's hostname (without reboot)
hostnamectl set-hostname "pysas$SN"
systemctl restart avahi-daemon