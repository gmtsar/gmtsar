#February 17, 2011

#Use the following command to process these ENVISAT data for the El Major-Cupacah earthquake.
#Be sure to have the PRC orbital files for ENVI in the path set in your gmtsar_config file.

#The directory /raw should contain the following two files.  Note the suffix .baq is required.
#ESA have a suffix .N1.  You will need to change this to .baq.  The prefix stem name can ve anything.

#ENV1_2_084_2943_2961_42222.baq	
#ENV1_2_084_2943_2961_42723.baq

#The directory /topo should contain one file dem.grd.
#This is most easily created using the following web-based tool.
#http://topex.ucsd.edu/gmtsar/demgen/

############## Commands for GMTSAR ##################a
#pop_config.csh ENVI > config.txt
p2p_processing ENVI ENV1_2_084_2943_2961_42222 ENV1_2_084_2943_2961_42723

