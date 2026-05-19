# ALOS-2 PALSAR L1.1 (SLC) test recipe over Japan / Mt. Fuji (left-looking).
# Translated from the bundled README.txt; the csh uses p2p_ALOS2_SLC.csh,
# which is equivalent to `p2p_processing ALOS2 ...` since ALOS2 in p2p_processing
# handles SLC inputs directly.

p2p_processing ALOS2 IMG-HH-ALOS2026912870-141122-UBSL1.1__D IMG-HH-ALOS2057962870-150620-UBSL1.1__D config.py
