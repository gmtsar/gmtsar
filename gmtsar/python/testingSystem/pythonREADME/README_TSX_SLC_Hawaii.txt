# February 5, 2014
#Revised January 29, 2019
#
# This is an example set of TerraSAR-X SLC images for an example interferogram.  The region is in Hawaii and is centered on the Kilauea Caldera. The data are part of the Hawaii Supersite.
#
# The file configure.csk.txt contains reasonable processing parameters.  Note the /topo directory already contains a file dem.grd that is needed for removal of the topographic phase.  There is a  web site http://topex.ucsd.edu/gmtsar that will generate a dem.grd file for a selected area based on the best available data (SRTM or ASTER).
#
############### Use these instructions if you are using the GMTSAR trunk: ########################
#
# 1) This code requires the raw data files to be in the same directory.
#Of course, this is not ideal for keeping different data sets organized, but we may fulfill both tasks by linking the requisite files into the raw directory.
#
cd raw
ln -s dims_op_oc_dfd2_370205611_1/TSX-1.SAR.L1B/TSX1_SAR__SSC______SM_S_SRA_20120615T162057_20120615T162105/TSX1_SAR__SSC______SM_S_SRA_20120615T162057_20120615T162105.xml ./TSX20120615.xml
ln -s dims_op_oc_dfd2_370205611_1/TSX-1.SAR.L1B/TSX1_SAR__SSC______SM_S_SRA_20120615T162057_20120615T162105/IMAGEDATA/IMAGE_HH_SRA_strip_007.cos ./TSX20120615.cos
ln -s dims_op_oc_dfd2_370849225_1/TSX-1.SAR.L1B/TSX1_SAR__SSC______SM_S_SRA_20121208T162059_20121208T162107/TSX1_SAR__SSC______SM_S_SRA_20121208T162059_20121208T162107.xml ./TSX20121208.xml
ln -s dims_op_oc_dfd2_370849225_1/TSX-1.SAR.L1B/TSX1_SAR__SSC______SM_S_SRA_20121208T162059_20121208T162107/IMAGEDATA/IMAGE_HH_SRA_strip_007.cos ./TSX20121208.cos
#
#
# 2) Now we may create the interferogram by running the the p2p code:
#
cd ..
p2p_processing TSX TSX20120615 TSX20121208
