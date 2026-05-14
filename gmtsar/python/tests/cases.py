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
CASES = {
    'S1_Ridgecrest_EQ':    {'satellite': 'S1_TOPS',  'ext': 'tar.gz', 'tiers': {'full'},                'enabled': True},
    'TSX_SLC_Hawaii':      {'satellite': 'TSX',      'ext': 'tar.gz', 'tiers': {'full'},                'enabled': True},
    'ALOS_Baja_EQ':        {'satellite': 'ALOS',     'ext': 'tar.gz', 'tiers': {'full', 'fast'},        'enabled': True},
    'ALOS_ERSDAC_L1.0':    {'satellite': 'ALOS',     'ext': 'tar.gz', 'tiers': {'full'},                'enabled': True},
    'S1A_SLC_TOPS_LA':     {'satellite': 'S1_TOPS',  'ext': 'tar.gz', 'tiers': {'full'},                'enabled': True},
    'S1A_SLC_TOPS_Greece': {'satellite': 'S1_TOPS',  'ext': 'tar.gz', 'tiers': {'full'},                'enabled': True},
    'ALOS_SLC_L1.1':       {'satellite': 'ALOS_SLC', 'ext': 'tar.gz', 'tiers': {'full'},                'enabled': True},
    'ERS_Hector_EQ':       {'satellite': 'ERS',      'ext': 'tar.gz', 'tiers': {'full', 'fast'},        'enabled': True},
    'RS2_SLC_Hawaii':      {'satellite': 'RS2',      'ext': 'tar.gz', 'tiers': {'full', 'fast', 'smoke'}, 'enabled': True},
    'ENVI_Baja_EQ':        {'satellite': 'ENVI',     'ext': 'tar.gz', 'tiers': {'full'},                'enabled': True},
    'ENVI_Baja_EQ_SLC':    {'satellite': 'ENVI_SLC', 'ext': 'tar.gz', 'tiers': {'full'},                'enabled': True},
    'CSK_RAW_Hawaii':      {'satellite': 'CSK_RAW',  'ext': 'tar.gz', 'tiers': {'full', 'fast'},        'enabled': True},
    'CSK_SLC_Italy':       {'satellite': 'CSK_SLC',  'ext': 'tar.gz', 'tiers': {'full'},                'enabled': True},
    'NISAR_SIM_ALOS':      {'satellite': 'ALOS',     'ext': 'tgz',    'tiers': {'full'},                'enabled': False},  # topex 403
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
