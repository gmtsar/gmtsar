#  March 8, 2019
#
#  This is an example script to process a swath of TOPS mode SAR data collected by the Sentinel 1A satellite.
#  It will process every subswath and merge the resulting interferograms.
#  To process only a single subswath, look at the S1A_SLC_TOPS_Greece example.
#
#  The final results may be found in the merge folder.
#  Interferograms for each individual subswath may be found in the F1, F2, and F3 folders.
#
#   make a merged interferogram
#
p2p_S1_TOPS_Frame S1A_IW_SLC__1SSV_20150526T014935_20150526T015002_006086_007E23_679A.SAFE S1A_OPER_AUX_POEORB_OPOD_20150615T155109_V20150525T225944_20150527T005944.EOF S1A_IW_SLC__1SDV_20150607T014936_20150607T015003_006261_00832E_3626.SAFE S1A_OPER_AUX_POEORB_OPOD_20150627T155155_V20150606T225944_20150608T005944.EOF config.py vv 1
#
#
#  The final argument of the script is a processing factor that governs whether the subswaths will be processed sequentially or in parallel.
#  A processing factor of 1 will have the script process the subswaths in parallel.
#  A processing factor of 0 will have the script process the subswaths sequentially. This is better for computers less memory, but takes longer to executes.
