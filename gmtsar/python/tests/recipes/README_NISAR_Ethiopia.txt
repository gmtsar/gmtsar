# NISAR (Ethiopia) test recipe — NSR_A (A-band) repeat-pass.
#
# Translated from bundled README_eruption.txt. Two acquisitions over
# the Ethiopian eruption area; both .h5 files are in raw/.
# Configures via pop_config (NSR_A defaults). Builds DEM via make_dem if topo/dem.grd
# is missing (it isn't shipped in the tarball).
#
# NSR_A path was wired into Python p2p_processing in v1.11.6 (NSR_A in pop_config,
# pre_proc_nsr Python port, NSR-specific xcorr/fitoffset/resamp in p2p_stages).

# Build DEM for the Ethiopia rift region (40.4 to 41.0 lon, 13.3 to 13.8 lat)
mkdir -p topo
cd topo
make_dem 40.4 41.0 13.3 13.8 1
cd ..

# Run NISAR repeat-pass processing
p2p_processing NSR_A NISAR_L1_PR_RSLC_005_172_A_008_2005_DHDH_A_20251122T024618_20251122T024652_X05007_N_F_J_001 NISAR_L1_PR_RSLC_006_172_A_008_2005_DHDH_A_20251204T024618_20251204T024653_X05007_N_F_J_001 config.py
