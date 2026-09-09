# ALOS-4 (PALSAR-3) test recipe over Pinon Flat.
# Mirrors the bundled README.txt:
#   pop_config.csh ALOS_SLC > config.txt; p2p_processing.csh ALOS4 IMG-A IMG-B config.txt
# config.py is pre-staged from tests/configs/ALOS4_Pinon.py.

p2p_processing ALOS4 IMG-HH-ALOS40650660250415FWD-RA0105-1.1__A IMG-HH-ALOS40650660250527FWD-RA0105-1.1__A config.py
