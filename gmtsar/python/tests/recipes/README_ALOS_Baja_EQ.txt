#February 17, 2011
#David T. Sandwell

#This is an example set of ALOS PALSAR data to make an interferogram of T212, F0640 spanning the M7.2 Easter Sunday Earthquake in Northern Baja California.  The raw data consist of an FBS image before the earthquake and an FBD image after the earthquake.  The file config.ALOS.txt contains reasonable processing parameters.

#The /raw directory should contain 4 files.
#IMG-HH-ALPSRP207600640-H1.0__A	LED-ALPSRP207600640-H1.0__A
#IMG-HH-ALPSRP227730640-H1.0__A	LED-ALPSRP227730640-H1.0__A

#These are the names provided by JAXA AUIG and it is important to have this name format.  If you have ERSDAC data, the simplest approach is to rename the files using this format.  The number 207600640 must simply have the correct number of digits and the IMG and LED numbers should match for each scene.

#Note the /topo directory already contains a file dem.grd that is needed for removal of the topographic phase.  There is a web site http://topex.ucsd.edu/gmtsar that will generate a dem.grd file for a selected area based on the best available data (SRTM or ASTER).

############## Command for GMTSAR ##################
p2p_processing ALOS IMG-HH-ALPSRP207600640-H1.0__A IMG-HH-ALPSRP227730640-H1.0__A
