# February 14, 2014
# Revised january 20, 2016
#Revised January 29, 2019
#
# This is an example set of RADARSAT-2 SLC images for an example interferogram.  The region is in Hawaii and is centered on the Kilauea Caldera. The data are part of the Hawaii Supersite.
#
# The file configure.rs2.txt contains reasonable processing parammeters.  Note the /topo directory already contains a file dem.grd that is needed for removal of the topographic phase.  There is a  web site http://topex.ucsd.edu/gmtsar that will generate a dem.grd file for a selected area based on the best available data (SRTM or ASTER).
#
#
#
############### Use these instructions if you are using the GMTSAR trunk: ########################
#
#Trunk users may use the instructions for v5.6 or the following instructions employing a generic p2p code.
#The advantages of the generic p2p code is that it automatically generates the SLCs and other necessary files and generates a default config file if none is given, making it more user friendly.
#
#
#
# 1) This code requires the raw data files to be in the same directory.
#Of course, this is not ideal for keeping different data sets organized, but we may fulfill both tasks by linking the requisite files into the raw directory.
#
cd raw
ln -s RS2_OK43873_PK423873_DK374693_FQ16_20110515_161531_HH_VV_HV_VH_SLC/product.xml ./RS220110515.xml
ln -s RS2_OK43873_PK423873_DK374693_FQ16_20110515_161531_HH_VV_HV_VH_SLC/imagery_HH.tif ./RS220110515.tif
ln -s RS2_OK43874_PK423902_DK375296_FQ16_20110819_161534_HH_VV_HV_VH_SLC/product.xml ./RS220110819.xml
ln -s RS2_OK43874_PK423902_DK375296_FQ16_20110819_161534_HH_VV_HV_VH_SLC/imagery_HH.tif ./RS220110819.tif
#
#
# 2) Now we may create the interferogram by running the the p2p code:
#
cd .. 
p2p_processing RS2 RS220110515 RS220110819 config.py 
