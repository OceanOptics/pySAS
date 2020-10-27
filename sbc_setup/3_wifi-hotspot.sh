#!/usr/bin/env bash

if [[ $EUID -ne 0 ]]; then 
	echo "Please switch to root user (sudo su)."
	exit
fi

echo
echo "Wifi Hotspot (Routed)"
echo "======================"
echo "Source: https://www.raspberrypi.org/documentation/configuration/wireless/access-point-routed.md, https://thepi.io/how-to-use-your-raspberry-pi-as-a-wireless-access-point/, and https://www.raspberryconnect.com/projects/65-raspberrypi-hotspot-accesspoints/157-raspberry-pi-auto-wifi-hotspot-switch-internet"



echo
echo "Install Software"
echo "----------------"
apt install -y hostapd
apt install -y dnsmasq

systemctl unmask hostapd
systemctl enable hostapd

systemctl stop hostapd
systemctl stop dnsmasq


echo
echo "Configure software"
echo "------------------"

echo "Define the wireless interface IP configuration"
read -r -d '' CFG <<- EOM
	

	# Hotspot configuration
	interface wlan0
	static ip_address=192.168.50.5/24
	nohook wpa_supplicant	
EOM
echo "$CFG" >> /etc/dhcpcd.conf


echo "Configure the DHCP and DNS services for the wireless network"
mv /etc/dnsmasq.conf /etc/dnsmasq.conf.orig
read -r -d '' CFG <<- EOM

	interface=wlan0
	dhcp-range=192.168.50.50,192.168.50.200,255.255.255.0,24h
EOM
echo "$CFG" >> /etc/dnsmasq.conf


echo "Enable routing and IP masquerading"
sed -i 's/#net.ipv4.ip_forward=1/net.ipv4.ip_forward=1/' /etc/sysctl.conf
iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
iptables -A FORWARD -i eth0 -o wlan0 -m state --state RELATED,ESTABLISHED -j ACCEPT
iptables -A FORWARD -i wlan0 -o eth0 -j ACCEPT
sh -c "iptables-save > /etc/iptables.ipv4.nat"
sed -i '/^exit 0/i iptables-restore < /etc/iptables.ipv4.nat' /etc/rc.local


echo "Configure the access point software"
read -r -d '' CFG <<- EOM 
	#2.4GHz setup wifi 80211 b,g,n
	country_code=US
	interface=wlan0
	driver=nl80211
	ssid=$(hostname)
	hw_mode=g
	channel=8
	wmm_enabled=0
	macaddr_acl=0
	auth_algs=1
	ignore_broadcast_ssid=0
	wpa=2
	wpa_passphrase=Phyt0plankt0n!
	wpa_key_mgmt=WPA-PSK
	wpa_pairwise=CCMP TKIP
	rsn_pairwise=CCMP

	#80211n
	ieee80211n=1
	ieee80211d=1
EOM
echo "$CFG" >> /etc/hostapd/hostapd.conf
sed -i 's/#DAEMON_CONF=\"\"/DAEMON_CONF=\"\/etc\/hostapd\/hostapd.conf\"/' /etc/default/hostapd


echo "Ensure wireless operation"
rfkill unblock wlan


echo "Please reboot the system, to apply settings."
