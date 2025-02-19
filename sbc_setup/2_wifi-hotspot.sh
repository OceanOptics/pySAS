#!/usr/bin/env bash

if [[ $EUID -ne 0 ]]; then 
	echo "Please switch to root user (sudo su)."
	exit
fi

echo
echo "Wifi Hotspot"
echo "============"
echo "Source: https://www.raspberrypi.com/documentation/computers/configuration.html#enable-hotspot"

echo "Setting hotspot ... "
nmcli device wifi hotspot ssid $(hostname) password Phyt0plankt0n!
HS_UUID="$(nmcli -t -f NAME,UUID con | grep ^Hotspot: | tr -d 'Hotspot:)')"
nmcli connection modify $HS_UUID connection.autoconnect yes connection.autoconnect-priority 100
sleep 1
echo

# Show hotspot configuration
nmcli dev wifi show-password
