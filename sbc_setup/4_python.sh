#!/usr/bin/env bash

if [[ $EUID -ne 0 ]]; then
	echo "Please switch to root user (sudo su)."
	exit
fi

echo
echo "Install Python 3.8.6"
echo "===================="
echo "Source: https://installvirtual.com/how-to-install-python-3-8-on-raspberry-pi-raspbian/"

# Install tools to build python
apt-get install -y build-essential tk-dev libncurses5-dev libncursesw5-dev libreadline6-dev libdb5.3-dev libgdbm-dev libsqlite3-dev libssl-dev libbz2-dev libexpat1-dev liblzma-dev zlib1g-dev libffi-dev tar wget vim

# Download and unzip
cd /var/tmp/
wget https://www.python.org/ftp/python/3.8.6/Python-3.8.6.tgz
tar zxf Python-3.8.6.tgz

# Build and install
cd Python-3.8.6
./configure --enable-optimizations
make -j 4
make install
pip3.8 install --upgrade pip

# Clean install
rm -rf Python-3.8.6.tgz
rm -rf Python-3.8.6

