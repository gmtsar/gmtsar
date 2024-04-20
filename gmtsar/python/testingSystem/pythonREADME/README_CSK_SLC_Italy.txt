# January 20, 2016
# Revised January 29, 2019
#
# This is an example set of COSMOS-SkyMed SLC images for an example interferogram.  The region is in Central Italy and the Pair spans the L'Aquela Earthquake.  Unfortunately the baseline is rather long
#
# The file configure.csk.txt contains reasonable processing parammeters.  Note the /topo directory already contains a file dem.grd that is needed for removal of the topographic phase.  There is a  web site http://topex.ucsd.edu/gmtsar that will generate a dem.grd file for a selected area based on the best available data (SRTM or ASTER).
#
############### GMTSAR commands ########################
#
p2p_processing CSK_SLC CSKS2_SCS_B_HI_09_HH_RA_SF_20090412050638_20090412050645 CSKS2_SCS_B_HI_09_HH_RA_SF_20090514050618_20090514050626 config.py
