#! /bin/bash
mkdir /usr/local/orbits
cd /usr/local/orbits
wget http://topex.ucsd.edu/gmtsar/tar/ORBITS.tar
tar -xvf ORBITS.tar
rm -rf ORBITS.tar
