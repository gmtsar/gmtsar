# ALOS-2 ScanSAR (WBD) test recipe over the southern San Andreas Fault.
# Mirrors the bundled README.txt:
#   pop_config.csh ALOS2_SCAN > config.txt
#   p2p_ALOS2_SCAN_Frame.csh IMG-HH-... IMG-HH-... config.txt 0
# Python port: p2p_ALOS2_SCAN_Frame handles the 5-subswath workflow
# (preprocess, samp_slc upsample to PRF 3350, per-subswath p2p, two-stage
# merge of F1-F3 then with F4-F5). config.py is pre-staged from
# tests/configs/ALOS2_SCAN_SSAF.py.

p2p_ALOS2_SCAN_Frame IMG-HH-ALOS2022872950-141025-WBDR1.1__D IMG-HH-ALOS2029082950-141206-WBDR1.1__D config.py 1
