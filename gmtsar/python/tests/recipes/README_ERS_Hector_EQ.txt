#February 17, 2011

#Use the following command to process an ERS interferogram for the Hector Mine Earthquake.
#Be sure to have the PRC orbital files for ERS in the path set in your gmtsar_config file.

#The /raw directory should contain 4 files.  
#e2_127_2907_23027.dat	
#e2_127_2907_23027.ldr	
#e2_127_2907_23528.dat	
#e2_127_2907_23528.ldr
#Note the suffixes .dat and .ldr are required.

#The /topo files should contain the file dem.grd.  This is most easily created using the following web-based tool.
#http://topex.ucsd.edu/gmtsar/demgen/

############## Commands for GMTSAR ##################
#pop_config.csh ERS > config.txt
p2p_processing ERS e2_127_2907_23027 e2_127_2907_23528

