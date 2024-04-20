#
#  July 27, 2021
#
#  This is an example script to process a swath of TOPS mode SAR data collected by the Sentinel 1 satellite.
#  It will process every subswath and merge the resulting interferograms.
#  To process only a single subswath, look at the S1A_SLC_TOPS_Greece example.
#
#  The final results may be found in the merge folder.
#  Interferograms for each individual subswath may be found in the F1, F2, and F3 folders.
#  Script to process interferogram for Greece area.
#
#   make a merged interferogram
#
p2p_S1_TOPS_Frame S1A_IW_SLC__1SDV_20151105T163133_20151105T163201_008472_00BFA6_D862.SAFE S1A_OPER_AUX_POEORB_OPOD_20151125T122020_V20151104T225943_20151106T005943.EOF.txt S1A_IW_SLC__1SDV_20151117T163127_20151117T163155_008647_00C499_5DC1.SAFE S1A_OPER_AUX_POEORB_OPOD_20151207T122501_V20151116T225943_20151118T005943.EOF.txt config.py vv 1
