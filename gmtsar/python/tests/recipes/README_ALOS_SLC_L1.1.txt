#November 20, 2013
#David T. Sandwell

#This is an example set of ALOS PALSAR data to make an interferogram of T213, F0660 starting with L1.1 (SLC) images. The raw data consist of a L1.1 (SLC) FBS image a L1.1 FBD image. The file configure.txt contains reasonable processing parameters.

#The /raw directory should contain 4 files.
#IMG-HH-ALPSRP223500660-H1.1__A	LED-ALPSRP223500660-H1.1__A
#IMG-HH-ALPSRP230210660-H1.1__A	LED-ALPSRP230210660-H1.1__A

#These are the names provided by JAXA AUIG and it is important to have this name format.  If you have ERSDAC data, the simplest approach is to rename the files using this format.  The number 207600640 must simply have the correct number of digits and the IMG and LED numbers should match for each scene.

#Note we have not tested any of this code for mixing L1.1 and L1.0 data.  Also this code will not work with L1.1 data from ERSDAC.

#Note the /topo directory already contains a file dem.grd that is needed for removal of the topographic phase.  There is a  web site http://topex.ucsd.edu/gmtsar that will generate a dem.grd file for a selected area based on the best available data (SRTM or ASTER).

############## Command for GMTSAR ##################
#pop_config.csh ALOS_SLC > config.txt
p2p_processing ALOS_SLC IMG-HH-ALPSRP223500660-H1.1__A IMG-HH-ALPSRP230210660-H1.1__A
