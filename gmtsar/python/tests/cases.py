#! /usr/bin/env python3
import os

# Default: <repo>/gmtsar/python/work/   (i.e. a sibling of tests/ inside the Python folder)
# Override by setting $SCRATCH (the workdir becomes $SCRATCH/py.test/).
_pythonDir = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if os.environ.get('SCRATCH'):
    workAbsoluteDir = os.path.join(os.environ['SCRATCH'], 'py.test') + os.sep
else:
    workAbsoluteDir = os.path.join(_pythonDir, 'work') + os.sep

# Per-case output trees inside workAbsoluteDir
pythonRunRoot = workAbsoluteDir + 'python_test/'   # Python-framework run outputs:   <workdir>/python_test/<caseName>/...
cshRefRoot    = workAbsoluteDir + 'csh_test/'      # legacy csh reference results:   <workdir>/csh_test/<caseName>/...
datasetRoot   = workAbsoluteDir + 'dataset/'       # downloaded raw tarballs:        <workdir>/dataset/<caseName>.tar.gz

recipesDir = workAbsoluteDir + 'recipes/'

# Frozen csh reference: committed-in copies of csh outputs, kept under tests/.
# When present, compare.py runs THREE pairs per file:
#   python_test vs csh_test      (today's python vs today's csh)
#   csh_test    vs reference     (today's csh vs frozen — detects csh drift)
#   python_test vs reference     (today's python vs frozen — stable baseline)
referenceRoot = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reference')

rawDir = 'raw'
SLCDir = 'SLC'

intfDirList = {
                'S1_Ridgecrest_EQ': ['F1/intf/2019184_2019196', 'F2/intf/2019184_2019196', 
                                    'F3/intf/2019184_2019196', 'merge', 'H_res'],
                'TSX_SLC_Hawaii' : ['intf/2012166_2012342'],
                'ALOS_Baja_EQ' : ['intf/2009351_2010124'],
                'ALOS_ERSDAC_L1.0' : ['intf/2010141_2010187'],
                'S1A_SLC_TOPS_LA' : ['F1/intf/2015145_2015157', 'F2/intf/2015145_2015157', 
                                      'F3/intf/2015145_2015157', 'merge'],
                'S1A_SLC_TOPS_Greece' : ['F1/intf/2015308_2015320', 'F2/intf/2015308_2015320',
                                        'F3/intf/2015308_2015320','merge'],
                'ALOS_SLC_L1.1' : ['intf/2010095_2010141'], 
                'ERS_Hector_EQ' : ['intf/1999258_1999293'], 
                'RS2_SLC_Hawaii' : ['intf/2011134_2011230'],
                'ENVI_Baja_EQ' : ['intf/2010087_2010122'],
                'ENVI_Baja_EQ_SLC' : ['intf/2010087_2010122'],
                'CSK_RAW_Hawaii' : ['intf/2014004_2014020'],
                'CSK_SLC_Italy' : ['intf/2009101_2009133'],
                # NISAR_SIM_ALOS: ALOS-family simulated NISAR data. The topex
                # download (NISAR_SIM_ALOS.tgz) currently returns HTTP 403; place
                # the tarball into work/dataset/ manually until that is resolved.
                # Intf path uses the standard ALOS pattern; update after first run.
                'NISAR_SIM_ALOS' : ['intf/2009351_2010124'],
               }

caseNameList = [
        'S1_Ridgecrest_EQ',
        'TSX_SLC_Hawaii',
        'ALOS_Baja_EQ',
        'ALOS_ERSDAC_L1.0',
        'S1A_SLC_TOPS_LA', 'S1A_SLC_TOPS_Greece', 'ALOS_SLC_L1.1', 'ERS_Hector_EQ', 'RS2_SLC_Hawaii',
                'ENVI_Baja_EQ', 'ENVI_Baja_EQ_SLC','CSK_RAW_Hawaii',
                'CSK_SLC_Italy',
                'NISAR_SIM_ALOS',  # tarball not auto-downloadable (403); runs if present
                ]

# Test tiers — curated subsets for different time budgets. Full sweep takes
# ~8 h on this shared NFS host; smaller tiers let a contributor validate
# "did I break the pipeline?" without that.
#   SMOKE: one tiny case  (~3 min)  — pipeline alive?
#   FAST:  diverse small  (~30 min) — covers ALOS / RS2 / ERS / CSK paths
#   FULL:  everything     (~8 h)    — use before a release
SMOKE_CASES = ['RS2_SLC_Hawaii']
FAST_CASES  = ['RS2_SLC_Hawaii', 'ERS_Hector_EQ', 'ALOS_Baja_EQ', 'CSK_RAW_Hawaii']

# caseNameList overrides (highest priority first):
#   1. TEST_CASES=case1,case2     — explicit subset
#   2. TEST_TIER=smoke|fast|full  — named tier
#   3. (default)                  — full caseNameList
_tier = os.environ.get('TEST_TIER', '').lower()
if os.environ.get('TEST_CASES'):
    caseNameList = [c.strip() for c in os.environ['TEST_CASES'].split(',') if c.strip()]
elif _tier == 'smoke':
    caseNameList = list(SMOKE_CASES)
elif _tier == 'fast':
    caseNameList = list(FAST_CASES)



