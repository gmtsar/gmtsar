# ALOS-2 ScanSAR (WBD) test recipe over the southern San Andreas Fault.
# Translated from the bundled README.txt; the csh uses p2p_ALOS2_SCAN_Frame.csh,
# which corresponds to `p2p_processing ALOS2_SCAN ...`. Last arg (0) means
# sequential subswath processing (vs parallel=1).
#
# Note: P2P2FocusAlign's _xcorr_and_fitoffset SKIPS fitoffset for ALOS2_SCAN
# (legacy csh has the median-filter step commented out). If this case fails,
# revisit the ALOS2_SCAN branch in p2p_stages.py.

p2p_processing ALOS2_SCAN IMG-HH-ALOS2022872950-141025-WBDR1.1__D IMG-HH-ALOS2029082950-141206-WBDR1.1__D config.py
