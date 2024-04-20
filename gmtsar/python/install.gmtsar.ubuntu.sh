#! /bin/bash

apt install python-is-python3
apt install csh subversion autoconf libtiff5-dev libhdf5-dev wget
apt install liblapack-dev
apt install gfortran
apt install g++
apt install libgmt-dev
apt install gmt-dcw gmt-gshhg
apt install gmt
apt install ghostscript
apt install git make vim

cd /usr/local
rm -rf GMTSAR
#git clone https://github.com/gmtsar/gmtsar GMTSAR
git clone https://github.com/dunyuliu/gmtsar.py.docker GMTSAR
#chmod -R 777 GMTSAR

cd GMTSAR
autoconf 
autoupdate
./configure --with-orbits-dir=/usr/local/orbits

make
# add -z muldefs to CFLAGS and LDFLAGS to config.mk
sed -i 's/-fno-strict-aliasing -std=c99/-fno-strict-aliasing -std=c99 -z muldefs/' config.mk
sed -i 's|,/usr/lib/x86_64-linux-gnu|,/usr/lib/x86_64-linux-gnu -z muldefs|' config.mk

make install 

echo "Finish installing GMTSAR ... ..."
echo "Setting up environments ... ..."

export GMTSAR=/usr/local/GMTSAR
export PATH=$GMTSAR/bin:"$PATH"

cp $GMTSAR/gmtsar/python/utils/* $GMTSAR/bin # move python utilities to GMTSAR's bin

export PATH=/home/pyGMTSAR:"$PATH"
alias  psconvert="gmt psconvert"
alias  ln="ln -f"
cd $HOME

bash

   
