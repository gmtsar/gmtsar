#
# January 19, 2016
# Revised January 29, 2019
#
# This is an example set of COSMOS-SkyMed RAW images for an example interferogram. The region is in Hawaii and is centered on the Kilauea Caldera. The data are part of the Hawaii Supersite.
#
# The file configure.csk.txt contains reasonable processing parammeters. Note the /topo directory already contains a file dem.grd that is needed for removal of the topographic phase. There is a  web site http://topex.ucsd.edu/gmtsar that will generate a dem.grd file for a selected area based on the best available data (SRTM or ASTER).
#
#
#Create the interferogram by running the p2p code:
#
#pop_config.csh CSK_RAW > config.txt
p2p_processing CSK_RAW CSKS2_RAW_B_HI_10_HH_RD_SF_20140105040332_20140105040340 CSKS2_RAW_B_HI_10_HH_RD_SF_20140121040327_20140121040334
