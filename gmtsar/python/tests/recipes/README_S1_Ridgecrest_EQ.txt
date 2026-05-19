# S1 TOPS test recipe over Ridgecrest, CA (2019 EQ sequence).
# Mirrors the bundled README.txt:
#   pop_config.csh S1_TOPS > config.txt
#   p2p_S1_TOPS_Frame.csh <m.SAFE> <m.EOF> <a.SAFE> <a.EOF> config.txt vv 1 >& log.txt
#   cd H_res
#   p2p_processing.csh S1_TOPS s1a-iw2-...027968... s1a-iw2-...028143... config.txt
# Tarball ships THREE bundled configs in different dirs:
#   top-level config.txt      (filter=200, dec=2) — used by Frame
#   top-level config.tops.txt (filter=160, dec=2) — variant, not used by Frame
#   H_res/config.txt          (filter=60,  dec=1) — high-res single-subswath
# config.py is pre-staged at top level from tests/configs/S1_Ridgecrest_EQ.py
# (= bundled config.txt, filter=200). H_res/ needs its own staging from its
# bundled config.txt — copying the top-level config.py would run the H_res
# pass at the wrong resolution and produce a shape-mismatched phasefilt.grd.

p2p_S1_TOPS_Frame S1A_IW_SLC__1SDV_20190704T135158_20190704T135225_027968_032877_1C4D.SAFE S1A_OPER_AUX_RESORB_OPOD_20190704T152016_V20190704T113336_20190704T145106.EOF S1A_IW_SLC__1SDV_20190716T135159_20190716T135226_028143_032DC3_512B.SAFE S1A_OPER_AUX_RESORB_OPOD_20190716T165508_V20190716T113337_20190716T145107.EOF config.py vv 1

cd H_res
import_csh_config config.txt config.py
p2p_processing S1_TOPS s1a-iw2-slc-vv-20190704t135158-20190704t135223-027968-032877-005 s1a-iw2-slc-vv-20190716t135159-20190716t135224-028143-032dc3-005 config.py
