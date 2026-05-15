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
# Order matters: sweep.sh iterates the dict and starts MAX_PARALLEL=4 cases
# at a time, FIFO from the order below. Listed roughly by expected runtime
# (small → large) so quick cases land early and the long-tail S1s don't
# block fast feedback.
CASES = {
    # ---- single-pair, small/fast (≤30 min each) ----
    'RS2_SLC_Hawaii':           {'satellite': 'RS2',        'ext': 'tar.gz', 'tiers': {'full', 'fast', 'smoke'}, 'enabled': True},   # ~3 min
    'ALOS_SLC_L1.1':            {'satellite': 'ALOS_SLC',   'ext': 'tar.gz', 'tiers': {'full'},                'enabled': True},     # ~8 min
    'CSK_RAW_Hawaii':           {'satellite': 'CSK_RAW',    'ext': 'tar.gz', 'tiers': {'full', 'fast'},        'enabled': True},     # ~13 min
    'CSK_SLC_Italy':            {'satellite': 'CSK_SLC',    'ext': 'tar.gz', 'tiers': {'full'},                'enabled': True},     # ~13 min
    'ALOS_ERSDAC_L1.0':         {'satellite': 'ALOS',       'ext': 'tar.gz', 'tiers': {'full'},                'enabled': True},     # ~14 min
    'ALOS_Baja_EQ':             {'satellite': 'ALOS',       'ext': 'tar.gz', 'tiers': {'full', 'fast'},        'enabled': True},     # ~17 min
    'ALOS_haiti':               {'satellite': 'ALOS',       'ext': 'tar.gz', 'tiers': {'full'},                'enabled': True},     # est. ~17 min
    'ENVI_Baja_EQ_SLC':         {'satellite': 'ENVI_SLC',   'ext': 'tar.gz', 'tiers': {'full'},                'enabled': True},     # ~18 min
    'ERS_Hector_EQ':            {'satellite': 'ERS',        'ext': 'tar.gz', 'tiers': {'full', 'fast'},        'enabled': True},     # ~18 min
    'TSX_SLC_Hawaii':           {'satellite': 'TSX',        'ext': 'tar.gz', 'tiers': {'full'},                'enabled': True},     # ~24 min
    'ENVI_Baja_EQ':             {'satellite': 'ENVI',       'ext': 'tar.gz', 'tiers': {'full'},                'enabled': True},     # ~27 min

    # ---- single-pair, medium (ALOS-2 family, ~30-60 min) ----
    'ALOS2_Brazil':             {'satellite': 'ALOS2',      'ext': 'tar.gz', 'tiers': {'full'},                'enabled': True},
    # ALOS2_Japan_Fugi_left: topex tarball is missing LED files (orbit metadata).
    # Both Python and csh pre_proc fail with "couldn't open LED file". Upstream data bug.
    'ALOS2_Japan_Fugi_left':    {'satellite': 'ALOS2',      'ext': 'tar.gz', 'tiers': {'full'},                'enabled': False},
    'ALOS2_SCAN_SSAF':          {'satellite': 'ALOS2_SCAN', 'ext': 'tar.gz', 'tiers': {'full'},                'enabled': True},     # ScanSAR is heavier

    # ---- multi-burst S1 TOPS, slow (≥1 h each) ----
    'S1A_SLC_TOPS_Greece':      {'satellite': 'S1_TOPS',    'ext': 'tar.gz', 'tiers': {'full'},                'enabled': True},     # ~1 h
    # S1A_SLC_TOPS_COVE: master SAFE's annotation/ dir is empty in the topex
    # tarball (broken upload). Python p2p_S1_TOPS_Frame can't find any xml files
    # to build the frame setup. Upstream data bug.
    'S1A_SLC_TOPS_COVE':        {'satellite': 'S1_TOPS',    'ext': 'tar.gz', 'tiers': {'full'},                'enabled': False},
    'S1_Larsen_C':              {'satellite': 'S1_TOPS',    'ext': 'tar.gz', 'tiers': {'full'},                'enabled': True},
    'S1A_SLC_TOPS_LA':          {'satellite': 'S1_TOPS',    'ext': 'tar.gz', 'tiers': {'full'},                'enabled': True},     # ~2 h
    'S1_Ridgecrest_EQ':         {'satellite': 'S1_TOPS',    'ext': 'tar.gz', 'tiers': {'full'},                'enabled': True},     # ~3 h (largest)

    # ---- disabled: need code paths not yet ported to Python ----
    # NISAR_Ethiopia uses NSR_A SAT type via p2p_processing_nsr — neither is
    # supported by the Python p2p_processing dispatch yet.
    'NISAR_Ethiopia':           {'satellite': 'ALOS',       'ext': 'tar.gz', 'tiers': {'full'},                'enabled': False},
    # S1A_SLC_Napa uses manual make_slc_s1a + extend_orbit prep that has no
    # single-script Python equivalent.
    'S1A_SLC_Napa_EQ':          {'satellite': 'S1_TOPS',    'ext': 'tar.gz', 'tiers': {'full'},                'enabled': False},
    # S1_SLC_TOPS_Ross requires a 3-pair double-difference workflow
    # (p2p_S1_TOPS_doublediff.csh) — not yet ported.
    'S1_SLC_TOPS_Ross_doubledifference': {'satellite': 'S1_TOPS', 'ext': 'tar.gz', 'tiers': {'full'},          'enabled': False},

    # ---- not yet supported by p2p_processing SAT dispatch ----
    'ALOS4_Pinon':              {'satellite': 'ALOS4',      'ext': 'tar.gz', 'tiers': {'full'},                'enabled': False},  # ALOS-4 SAT not yet in p2p_processing

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
