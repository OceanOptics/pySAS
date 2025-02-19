#!/usr/bin/env bash

if [[ $EUID -ne 0 ]]; then
	echo "Please switch to root user (sudo su)."
	exit
fi

echo
echo "Mount External Drive"
echo "===================="
echo "source: source: https://www.raspberrypi.org/documentation/configuration/external-storage.md"

echo 
echo "Automatically mount external disk on boot (drive must be formatted in ext4)"
# source: https://www.raspberrypi.org/documentation/configuration/external-storage.md
blkid
echo "Enter UUID (e.g. 5C24-1453): "
read UUID
mkdir /mnt/data_disk
# Automatically mount on next boot
echo "UUID=$UUID /mnt/data_disk ext4 defaults,auto,users,rw,nofail,x-systemd.device-timeout=15 0 0" >> /etc/fstab

echo "Mounting disk and setting permissions"
mount /mnt/data_disk
chown root:misclab -R /mnt/data_disk
chmod 775 -R /mnt/data_disk
chmod 700 -R /mnt/data_disk/lost+found
