# v2.5.6 — dem2topo_ra mode=1: fix phasediff segfault on masked cells

## Bug

`topo_interp_mode=1` (the triangulation fast-path in `dem2topo_ra`, opt-in,
not exercised by the 21-case regression suite — every current test config
uses mode=0) could leave a small number of masked/NaN cells in
`topo_ra.grd` / `topo_shift.grd`, causing the C `phasediff` binary to
segfault (exit 139) whenever a case's baseline forces the long-baseline
C fallback path (baseline > 1000 m). The crash cascaded into `filter`
(FileNotFoundError on `real.grd`) and `geocode` (FileNotFoundError on
`corr.grd`), so mode=1 produced no final interferogram product at all
for affected cases.

Root cause: a domain corner can fall outside *both* the triangulation's
convex hull and the coarse donor grid's convex hull (the donor's own
blockmean-binned points can fall just short of the same corner), so the
existing `-Ag<donor>` grdfill pass has nothing to donate there. Found on
a real ALOS_Baja_EQ run: 6 masked pixels in one grid corner, deterministic
and reproducible.

## Fix

Added `_fill_remaining_holes()` in `gmtsar/python/utils/dem2topo_ra`,
wired into `_grdfill_dispatch()` so it runs after every donor-grid fill
in both mode=1 call sites (PRF<1000 and PRF>=1000 branches). It runs a
nearest-neighbor `gmt grdfill -An` pass and asserts the output file was
actually produced before accepting it — no silent fallback: if the
safety-net fill itself fails, the pipeline exits with a clear FATAL
message rather than silently shipping a grid that may still contain
masked cells.

Verified end-to-end on real data (ALOS_Baja_EQ, full case, mode=1):
`topo_shift.grd` masked-cell count 6 -> 0, `phasediff`/`filter`/`geocode`
all complete, `phasefilt_mask_ll.grd/.png` produced. Final-product diff
vs. the mode=0 baseline: RMS 0.47 cm (LOS-displacement equivalent),
99th-percentile |diff| 1.27 cm — numerically inconsequential, confirming
the pre-existing accuracy characterization of mode=1 still holds once the
crash is fixed. mode=1 is now also faster end-to-end where it applies:
~2x on this case's topo->intf->filter->geocode stages (638s -> 323s).

Scope: mode=1 only (opt-in, unexercised by the regression suite) — mode=0
(the default, used by every current test config) is untouched. Existing
unit tests (`test_dem2topo_ra.py`, `test_gmt_grdfill_py.py`, 31 cases)
pass unchanged.

## Files changed

- `gmtsar/python/utils/dem2topo_ra` (+27 lines)
