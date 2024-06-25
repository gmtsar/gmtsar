#
#  download the SAFE and orbit *.EOF files and out them in the raw directory
#
#
#
# make a topo directory and construct a dem
#
# make_dem.csh -119.1 -115.8 34.4 36.6 2
#
#  process the entire frame
#
p2p_S1_TOPS_Frame S1A_IW_SLC__1SDV_20190704T135158_20190704T135225_027968_032877_1C4D.SAFE S1A_OPER_AUX_RESORB_OPOD_20190704T152016_V20190704T113336_20190704T145106.EOF S1A_IW_SLC__1SDV_20190716T135159_20190716T135226_028143_032DC3_512B.SAFE S1A_OPER_AUX_RESORB_OPOD_20190716T165508_V20190716T113337_20190716T145107.EOF config.py vv 1 
#
#  next make a full resolution interferogram and products using just subswath-2
#  if you want phase gradients you will need to replace your filter.csh with the
#  version in this directory.
# which filter.csh
#  copy that path
# cp filter.csh the_full_path
#
cd H_res
p2p_processing S1_TOPS s1a-iw2-slc-vv-20190704t135158-20190704t135223-027968-032877-005 s1a-iw2-slc-vv-20190716t135159-20190716t135224-028143-032dc3-005 config.py 
