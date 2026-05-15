"""phase1_test — byte-identical comparison of Phase 1 Python ports vs csh.

PLAN Phase 1 ports several csh utilities to Python:
    baseline_table, get_baseline_table, gmtsar_sharedir, make_dem,
    select_pairs, proj_ll2ra, proj_ll2ra_ascii, proj_ra2ll_ascii.

For each, this script runs both the csh and Python versions on the same
input fixture and diffs the stdout / output files. The pass criterion is
**byte-equivalence** for text outputs and within-RMS-threshold for GRDs
(reusing the threshold logic from tests/compare.py).

Run:  python3 tests/phase1_test.py [--verbose]

This is a SCAFFOLD — not implemented.

Implementation notes:
- Fixtures live under tests/fixtures/phase1/ (TBD — needs creation).
- Per-utility fixture set:
    baseline_table:    master.PRM + aligned.PRM from a known case
    get_baseline_table: prmlist.txt + master_prm + expected baseline_table.dat
    gmtsar_sharedir:   no input — assert stdout matches `gmtsar_sharedir.csh`
    make_dem:          a small W/E/S/N box (e.g. -118 -117 33 34); compare dem.grd
    select_pairs:      a baseline_table.dat fixture; compare intf.in line-by-line
    proj_*:            a tiny trans.dat + phase grid; compare output grids
- Use existing GRD comparison helpers from compare.py (DEFAULT_GRD_RMS threshold).
- gmtsar_sharedir is the simplest: just assert outputs match.
- For floating-point text outputs, allow a small numerical tolerance per
  column (baseline_table emits Bperp etc. with ~6 significant digits).
"""
import sys

# Phase 1 utilities to test (one suite per utility).
PHASE1_UTILS = [
    'gmtsar_sharedir',
    'baseline_table',
    'get_baseline_table',
    'make_dem',
    'select_pairs',
    'proj_ll2ra',
    'proj_ll2ra_ascii',
    'proj_ra2ll_ascii',
]


def main():
    raise NotImplementedError("phase1_test: PLAN Phase 1 scaffold — not yet implemented")


if __name__ == '__main__':
    main()
