#!/usr/bin/env python3
"""touched_to_cases.py — map changed file paths to a set of test cases.

Usage (reads changed-file paths from stdin, one per line):
    git diff HEAD~1..HEAD --name-only | python3 touched_to_cases.py

Exits 0; prints a comma-separated case list on stdout (empty if no cases
matched). sweep.sh --smart_fast reads stdout and exports it as TEST_CASES.

Rules are evaluated in order; a path matches the FIRST rule whose pattern
appears as a substring in the path. 'all_21' expands to every enabled full-
tier case from cases.py at call time.

This file is the canonical rules table — update it when a new bin_py module
is ported or when an existing module gains new test-case coverage.
"""
from __future__ import annotations
import re
import sys

# ── Rules table ──────────────────────────────────────────────────────────────
# Each entry: (pattern, cases).
#   pattern : substring match (re.search) against the changed file path.
#   cases   : list of case names OR the sentinel string 'all_21'.
#
# A changed path that matches NO rule is treated as infrastructure-only and
# produces zero cases (e.g. docs/, .gitignore, README changes).
#
# Order matters: first match wins.

RULES: list[tuple[str, str | list[str]]] = [
    # Core geometry / orbit maths — touches every InSAR pair.
    (r'bin_py/xcorr_py',            'all_21'),
    (r'bin_py/SAT_llt2rat',         'all_21'),
    (r'utils/geocode',              'all_21'),
    (r'utils/dem2topo_ra',          'all_21'),
    (r'utils/gmt_inproc',           'all_21'),
    (r'utils/proj_ra2ll',           'all_21'),
    (r'utils/vector\.py',           'all_21'),
    # Resampling — only affects SATs that use the Python resamp_py path.
    (r'bin_py/resamp_py',           ['RS2_SLC_Hawaii', 'NISAR_Ethiopia',
                                     'CSK_RAW_Hawaii', 'TSX_SLC_Hawaii']),
    # Snaphu unwrapping — only cases with threshold_snaphu > 0.
    (r'utils/snaphu\.py',           ['ALOS_haiti']),
    # Sentinel-1 TOPS alignment utilities.
    (r'utils/align_tops',           ['S1A_SLC_TOPS_COVE', 'S1A_SLC_TOPS_Greece',
                                     'S1A_SLC_TOPS_LA', 'S1_Larsen_C',
                                     'S1_Ridgecrest_EQ']),
    # Sentinel-1 TOPS final-stage merge/unwrap/geocode. Same case set as
    # align_tops since both are S1-TOPS-only. (Note: threshold_snaphu=0
    # for every TOPS case in tests/configs/, so the unwrap branch is NOT
    # exercised — keep an eye on that gap.)
    (r'utils/merge_unwrap_geocode_tops', ['S1A_SLC_TOPS_COVE',
                                          'S1A_SLC_TOPS_Greece',
                                          'S1A_SLC_TOPS_LA', 'S1_Larsen_C',
                                          'S1_Ridgecrest_EQ']),
    # conv_py — used in older ALOS raw-mode pipeline. ALOS_haiti is the only
    # case that exercises the filter with a high threshold (Mira #50 audit).
    (r'bin_py/conv_py',             ['ALOS_haiti']),
    # GMT surface Python port — currently exercised only by CSK RAW (only case
    # in --fast with square cells).
    (r'utils/gmt_surface_py',       ['CSK_RAW_Hawaii']),
    # GMT grid I/O helpers — any case with grdmath wire-in.
    (r'utils/gmt_grd_io',           ['RS2_SLC_Hawaii', 'NISAR_Ethiopia']),
    # p2p_processing — the main orchestrator: any change affects every case.
    (r'utils/p2p_processing',       'all_21'),
    # p2p_stages — stage decomposition library; touches every pipeline.
    (r'utils/p2p_stages\.py',       'all_21'),
    # p2p_S1_TOPS_Frame — Sentinel-1 TOPS frame driver; same scope as align_tops.
    (r'utils/p2p_S1_TOPS_Frame',    ['S1A_SLC_TOPS_COVE', 'S1A_SLC_TOPS_Greece',
                                     'S1A_SLC_TOPS_LA', 'S1_Larsen_C',
                                     'S1_Ridgecrest_EQ']),
    # gmtsar_lib — shared library functions called by most processors.
    (r'utils/gmtsar_lib',           'all_21'),
    # Pre-processing utilities.
    (r'utils/pre_proc',             'all_21'),
    # SAT_baseline_py — baseline computation, byte-id verified on 5 SAT
    # families (Mira #29). Other cases hit it via baseline_table only on
    # multi-pair workflows that aren't in the single-pair test pool.
    (r'bin_py/SAT_baseline_py',     ['RS2_SLC_Hawaii', 'ALOS_haiti',
                                     'TSX_SLC_Hawaii', 'ENVI_Baja_EQ',
                                     'ALOS_SLC_L1.1']),
    # phasediff_py — wired into intf. Short-baseline single-pair cases hit
    # the inner loops hardest (RS2, CSK_RAW, ALOS_SLC, Mira #39).
    (r'bin_py/phasediff_py',        ['RS2_SLC_Hawaii', 'CSK_RAW_Hawaii',
                                     'ALOS_SLC_L1.1']),
    # make_los_py — wired into geocode (Mira #39); geocode runs on every case.
    (r'bin_py/make_los_py',         'all_21'),
    # JIT kernel modules (resamp / SAT) — referenced via @njit imports inside
    # the corresponding ports; any kernel change can shift float-rounding
    # across every pipeline. all_21 is the conservative choice.
    (r'bin_py/_jit_kernels_',       'all_21'),
    # estimate_ionospheric_phase — env-gated, no test config has correct_iono=1
    # (Mira #48). Audited 2026-05-22: zero cases exercise this path; touching
    # it requires a manual ALOS2_Brazil + correct_iono=1 run, not a sweep slot.
    (r'utils/estimate_ionospheric_phase', []),
    # Test infrastructure changes — run the fast tier for basic sanity.
    (r'tests/configs/',             ['RS2_SLC_Hawaii', 'ERS_Hector_EQ',
                                     'ALOS_Baja_EQ', 'CSK_RAW_Hawaii']),
    (r'tests/recipes/',             ['RS2_SLC_Hawaii', 'ERS_Hector_EQ',
                                     'ALOS_Baja_EQ', 'CSK_RAW_Hawaii']),
    (r'tests/cases\.py',            ['RS2_SLC_Hawaii', 'ERS_Hector_EQ',
                                     'ALOS_Baja_EQ', 'CSK_RAW_Hawaii']),
    # Test-infrastructure files that require NO pipeline run.
    # Changes here are exercised by --unit, not by the case-based sweep.
    (r'tests/sweep\.sh',            []),
    (r'tests/touched_to_cases\.py', []),
    (r'tests/blessed_diff\.py',     []),
    (r'tests/compare\.py',          []),
    (r'tests/runner\.py',           []),
    (r'tests/report\.py',           []),
    (r'tests/case_runner\.sh',      []),
    (r'bin_py/tests/',              []),    # unit-test changes only
    # Paths that require NO pipeline run — map to empty list.
    (r'docs/',                      []),
    (r'\.gitignore',                []),
    (r'README',                     []),
    (r'PLAN\.md',                   []),
    (r'AUDIT',                      []),
    (r'SESSION_LOG',                []),
    (r'release_notes',              []),
]

# ── Expand 'all_21' ──────────────────────────────────────────────────────────

def _all_full_cases() -> list[str]:
    """Return every enabled case in the 'full' tier from cases.py."""
    import os, sys
    # cases.py is a sibling of this file.
    _here = os.path.dirname(os.path.abspath(__file__))
    if _here not in sys.path:
        sys.path.insert(0, _here)
    # Force TEST_TIER=full so we get the complete pool.
    os.environ['TEST_TIER'] = 'full'
    # Re-import fresh (or use importlib to avoid stale cache).
    import importlib
    import cases as _cases_mod
    importlib.reload(_cases_mod)
    return list(_cases_mod.caseNameList)


def map_paths_to_cases(changed_paths: list[str]) -> list[str]:
    """Return deduplicated, ordered list of case names for the changed paths."""
    _all: list[str] | None = None  # lazy-load

    selected: dict[str, None] = {}   # ordered set via dict

    for path in changed_paths:
        path = path.strip()
        if not path:
            continue
        matched = False
        for pattern, cases in RULES:
            if re.search(pattern, path):
                matched = True
                if isinstance(cases, str) and cases == 'all_21':
                    if _all is None:
                        _all = _all_full_cases()
                    for c in _all:
                        selected[c] = None
                else:
                    for c in cases:
                        selected[c] = None
                break
        if not matched:
            # Unrecognised path: default-safe — run smoke tier instead of
            # silently dropping coverage.
            if _all is None:
                _all = _all_full_cases()
            # Add the smoke case (first in the full list is RS2_SLC_Hawaii).
            smoke = next(iter(_all), None)
            if smoke:
                selected[smoke] = None
            print(f"[touched_to_cases] WARN: unrecognised path '{path}' "
                  f"— defaulting to smoke case {smoke!r}", file=sys.stderr)

    return list(selected.keys())


def main() -> None:
    changed = sys.stdin.read().splitlines()
    cases = map_paths_to_cases(changed)
    # Output comma-separated so sweep.sh can export TEST_CASES directly.
    print(','.join(cases))


if __name__ == '__main__':
    main()
