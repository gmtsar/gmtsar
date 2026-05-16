#! /usr/bin/env python3
"""Case manifest and workdir layout for the regression-test framework.

The single source of truth for every test case is `CASES` below — a dict of
dicts keyed by case name. All consumers (runner.py, compare.py, sweep.sh,
freeze_reference.py) derive what they need from it.
"""
import os

# ---------------------------------------------------------------- workdir ---

# Default: <repo>/gmtsar/python/work/   (i.e. a sibling of tests/ inside the
# Python folder). Override by setting $SCRATCH (workdir becomes $SCRATCH/py.test/).
_pythonDir = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if os.environ.get('SCRATCH'):
    workAbsoluteDir = os.path.join(os.environ['SCRATCH'], 'py.test') + os.sep
else:
    workAbsoluteDir = os.path.join(_pythonDir, 'work') + os.sep

# Per-case output trees inside workAbsoluteDir.
pythonRunRoot = workAbsoluteDir + 'python_test/'   # Python-framework outputs
cshRefRoot    = workAbsoluteDir + 'csh_test/'      # legacy csh reference outputs
datasetRoot   = workAbsoluteDir + 'dataset/'       # downloaded raw tarballs
recipesDir    = workAbsoluteDir + 'recipes/'

# Frozen csh reference (gitignored, ~5.8 GB). When present, compare.py runs
# three pairs per file: py-vs-csh, csh-vs-frozen, py-vs-frozen.
referenceRoot = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reference')

rawDir = 'raw'
SLCDir = 'SLC'

# ------------------------------------------------------- case manifest ---

# Single source of truth for every supported test case. Schema:
#   satellite : SAT type passed to p2p_processing (one of ALOS, ERS, ENVI, ...)
#   ext       : archive filename extension as published on topex (tar.gz or tgz)
#   tiers     : which test tiers this case belongs to (smoke / fast / full)
#   enabled   : False marks a case as known-broken or temporarily skipped
#               (e.g. NISAR_SIM_ALOS: download 403'd by topex)
#
# Archive URL is always http://topex.ucsd.edu/gmtsar/tar/<case>.<ext>.
# Pythonization of intfDirList was removed in v1.1.1; intf paths are now
# auto-discovered from the filesystem by compare.py / freeze_reference.py.
# Tiers:
#   smoke : 1 case, ~4 min — pipeline-alive check
#   fast  : 4 cases, ~25 min — covers ALOS/RS2/ERS/CSK SAT families
#   full  : 14 single-pair cases, ~3 h cached — every SAT family + flagship S1s
#   sbas  : multi-pair time-series stacks for Phase 4 SBAS validation
#           (not invoked by sweep.sh by default; use TEST_TIER=sbas explicitly)
#
# Order matters: sweep.sh iterates the dict and starts MAX_PARALLEL (default 12)
# cases at a time, FIFO from the order below. We use a hybrid LPT schedule
# (longest-processing-time-first) with a few fast cases at the head to give
# early-feedback signal that the pipeline is alive:
#   - 3 smallest cases first (RS2, ALOS_SLC, NISAR — all under 10 min)
#   - then the heaviest cases (Ridgecrest, S1A_TOPS_LA, Larsen, ALOS2_SCAN_SSAF,
#     S1A_Greece) so they start at t=0 and don't bottleneck the tail
#   - then mediums in roughly descending order
# With MAX_PARALLEL=12 + 19 enabled cases, only 7 cases queue; they fill slots
# as fast cases finish.
CASES = {
    # ---- head: fastest cases first (early-feedback) ----
    'RS2_SLC_Hawaii':           {'satellite': 'RS2',        'ext': 'tar.gz', 'tiers': {'full', 'fast', 'smoke'}, 'enabled': True},   # ~3 min
    'NISAR_Ethiopia':           {'satellite': 'NSR_A',      'ext': 'tar.gz', 'tiers': {'full'},                'enabled': True},     # ~6 min (region_cut)
    'ALOS_SLC_L1.1':            {'satellite': 'ALOS_SLC',   'ext': 'tar.gz', 'tiers': {'full'},                'enabled': True},     # ~8 min

    # ---- heaviest cases — start at t=0 so they don't extend total makespan ----
    'S1_Ridgecrest_EQ':         {'satellite': 'S1_TOPS',    'ext': 'tar.gz', 'tiers': {'full'},                'enabled': True},     # ~3 h
    'S1A_SLC_TOPS_LA':          {'satellite': 'S1_TOPS',    'ext': 'tar.gz', 'tiers': {'full'},                'enabled': True},     # ~2 h
    'S1_Larsen_C':              {'satellite': 'S1_TOPS',    'ext': 'tar.gz', 'tiers': {'full'},                'enabled': True},     # ~1.5 h
    'ALOS2_SCAN_SSAF':          {'satellite': 'ALOS2_SCAN', 'ext': 'tar.gz', 'tiers': {'full'},                'enabled': True},     # ScanSAR heavier
    'S1A_SLC_TOPS_Greece':      {'satellite': 'S1_TOPS',    'ext': 'tar.gz', 'tiers': {'full'},                'enabled': True},     # ~1 h
    'ALOS2_Brazil':             {'satellite': 'ALOS2',      'ext': 'tar.gz', 'tiers': {'full'},                'enabled': True},     # ~50 min

    # ---- mediums (~15-30 min) ----
    'ENVI_Baja_EQ':             {'satellite': 'ENVI',       'ext': 'tar.gz', 'tiers': {'full'},                'enabled': True},     # ~27 min
    'ALOS_haiti':               {'satellite': 'ALOS',       'ext': 'tar.gz', 'tiers': {'full'},                'enabled': True},     # ~25 min
    'ALOS4_Pinon':              {'satellite': 'ALOS4',      'ext': 'tar.gz', 'tiers': {'full'},                'enabled': True},     # ~25 min
    'TSX_SLC_Hawaii':           {'satellite': 'TSX',        'ext': 'tar.gz', 'tiers': {'full'},                'enabled': True},     # ~24 min
    'ENVI_Baja_EQ_SLC':         {'satellite': 'ENVI_SLC',   'ext': 'tar.gz', 'tiers': {'full'},                'enabled': True},     # ~18 min
    'ERS_Hector_EQ':            {'satellite': 'ERS',        'ext': 'tar.gz', 'tiers': {'full', 'fast'},        'enabled': True},     # ~18 min
    'ALOS_Baja_EQ':             {'satellite': 'ALOS',       'ext': 'tar.gz', 'tiers': {'full', 'fast'},        'enabled': True},     # ~17 min
    'ALOS_ERSDAC_L1.0':         {'satellite': 'ALOS',       'ext': 'tar.gz', 'tiers': {'full'},                'enabled': True},     # ~14 min
    'CSK_SLC_Italy':            {'satellite': 'CSK_SLC',    'ext': 'tar.gz', 'tiers': {'full'},                'enabled': True},     # ~13 min
    'CSK_RAW_Hawaii':           {'satellite': 'CSK_RAW',    'ext': 'tar.gz', 'tiers': {'full', 'fast'},        'enabled': True},     # ~13 min

    # ---- previously disabled: re-enabled to retest with macOS dotfile filter + bundled-config flow ----
    # ALOS2_Japan_Fugi_left: previously failed with "couldn't open LED file" on both sides.
    'ALOS2_Japan_Fugi_left':    {'satellite': 'ALOS2',      'ext': 'tar.gz', 'tiers': {'full'},                'enabled': True},
    # S1A_SLC_TOPS_COVE: previously failed with empty annotation/; macOS ._ filter may help.
    'S1A_SLC_TOPS_COVE':        {'satellite': 'S1_TOPS',    'ext': 'tar.gz', 'tiers': {'full'},                'enabled': True},
    # S1A_SLC_Napa uses manual make_slc_s1a + extend_orbit prep — no single-script equivalent.
    'S1A_SLC_Napa_EQ':          {'satellite': 'S1_TOPS',    'ext': 'tar.gz', 'tiers': {'full'},                'enabled': False},
    # S1_SLC_TOPS_Ross — 3-scene double-difference (pair1: SAFE1→SAFE2, pair2:
    # SAFE2→SAFE3, then phase_diff). Python port: p2p_S1_TOPS_doublediff.
    # Disabled: bundled csh `p2p_S1_TOPS_doublediff.csh` calls legacy
    # `p2p_S1_TOPS.csh` which was removed from upstream in 2018, so csh-side
    # reference cannot run. Py side runs end-to-end. To re-enable, restore the
    # historical p2p_S1_TOPS.csh from git history (commit c0933d9).
    'S1_SLC_TOPS_Ross_doubledifference': {'satellite': 'S1_TOPS', 'ext': 'tar.gz', 'tiers': {'full'},          'enabled': False},

    # ---- multi-pair stacks (Phase 4 SBAS / time-series testing) ----
    'ALOS_Hawaii_stack':        {'satellite': 'ALOS',       'ext': 'tar.gz', 'tiers': {'sbas'},                'enabled': True},
    'ALOS_Indio_SBAS':          {'satellite': 'ALOS',       'ext': 'tar.gz', 'tiers': {'sbas'},                'enabled': True},
    'ENVI_2907_stack':          {'satellite': 'ENVI',       'ext': 'tar.gz', 'tiers': {'sbas'},                'enabled': True},
    'S1A_Stack_CPGF_T173':      {'satellite': 'S1_TOPS',    'ext': 'tar.gz', 'tiers': {'sbas'},                'enabled': True},
    'kilauea_timeseries_sentinel_data':  {'satellite': 'S1_TOPS', 'ext': 'tar.gz', 'tiers': {'sbas'},          'enabled': True},
    'kilauea_timeseries_sentinel_files': {'satellite': 'S1_TOPS', 'ext': 'tar.gz', 'tiers': {'sbas'},          'enabled': False},  # orbit / aux companion to *_data
}

# Helpers for consumers.
ARCHIVE_URL_PREFIX = 'http://topex.ucsd.edu/gmtsar/tar/'

def archive_url(case):    return f'{ARCHIVE_URL_PREFIX}{case}.{CASES[case]["ext"]}'
def archive_path(case):   return f'{datasetRoot}{case}.{CASES[case]["ext"]}'

# ----------------------------------------------------- tier selection ---

# caseNameList is what the framework actually iterates over. By default it's
# every enabled case in CASES; tier env vars filter it down.
#   1. TEST_CASES=case1,case2     — explicit subset (highest priority)
#   2. TEST_TIER=smoke|fast|full  — tier filter
#   3. (default)                  — every enabled case (== TEST_TIER=full)
_tier = os.environ.get('TEST_TIER', '').lower() or 'full'
if os.environ.get('TEST_CASES'):
    caseNameList = [c.strip() for c in os.environ['TEST_CASES'].split(',') if c.strip()]
else:
    caseNameList = [name for name, info in CASES.items()
                    if info['enabled'] and _tier in info['tiers']]
