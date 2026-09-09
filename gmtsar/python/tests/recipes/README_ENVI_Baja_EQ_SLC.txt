#April 14, 2017

#Example of InSAR using the new SLC file format provided for ERS-1/2 and Envisat.

#The directory /raw should contain the following two files.
#Note the suffix .N1 is required for Envisat.
#The suffix .E1 is required for ERS-1
#The suffix .E2 is required for ERS-2

#ASA_IMS_1PNESA20100328_175019_000000152088_00084_42222_0000.N1
#ASA_IMS_1PNESA20100502_175016_000000152089_00084_42723_0000.N1

#The directory /topo should contain one file dem.grd.
#This is most easily created using the following web-based tool.
#http://topex.ucsd.edu/gmtsar/demgen/

#Use the following command to process these ENVISAT SLC data for the El Major-Cupacah earthquake.
#Be sure to have the PRC orbital files for ENVI.

############## Commands for GMTSAR  ##################
p2p_processing ENVI_SLC ASA_IMS_1PNESA20100328_175017_000000182088_00084_42222_0000 ASA_IMS_1PNESA20100502_175015_000000182089_00084_42723_0000

