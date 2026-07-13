# Release notes — v2.5.0 (2026-06-18)

## grdmath wired pipeline-wide (bit-exact), default ON

`gmt_grdmath_py` is now wired into **16 pipeline files** (previously only
`filter` + `stack`), so the verified numpy port handles `gmt grdmath`
operations at their call sites throughout the pipeline, behind the
`GMTSAR_GRDMATH_PY` gate (default ON), with a `gmt grdmath` subprocess
fallback for any expression using an unsupported operator.

### Wired (route through the port)
align_tops, fitoffset_ra, correct_insar_with_gnss, correct_merge_offset,
stack_corr, stack_coherence_mask, merge_unwrap_geocode_tops, snaphu.py
(masking), geocode, p2p_ALOS2_SCAN_Frame, p2p_S1_TOPS_doublediff, make_dem,
make_los_ascii, proj_model, plus the existing filter + stack.

### Supported operators (bit/float-parity vs `gmt grdmath`)
FLIPUD MUL ADD SUB DIV ABS SQRT SQR POW HYPOT ATAN2 GE LE NAN XOR MIN.
**Kept on gmt** (unsupported / not bit-safe): MOD, DENAN, ISNAN, PI, BLEND,
BITXOR — so `estimate_ionospheric_phase`, `slc2amp`, and a couple of MOD+PI
chains intentionally retain the gmt subprocess.

### Verification
- **Bit-exactness proven**: an independent A/B (`GMTSAR_GRDMATH_PY=0` gmt vs
  `=1` py) on identical real inputs gave `NaN_mismatch=0, max|diff|=0.0`
  across all four GE/NAN masking chains (geocode, merge, stack_coherence_mask,
  snaphu).
- A latent bug was found and fixed en route: `_op_min` used `np.fmin`
  (ignores NaN) instead of `np.minimum` (propagates NaN, matching GMT's MIN).
- 58 grdmath C-parity tests pass (42 prior + new threshold/NaN/real-data
  locks).
- **Full 21-case all-Python-defaults sweep: 19/21 py-vs-csh clean.**

### The 2 non-clean cases are wiring-INDEPENDENT (documented)
1. **ALOS_haiti** `phasefilt_mask_ll.png` ssim=None — py-corr vs csh-corr
   differ by float-roundoff straddling the hard `GE 0.14` mask threshold,
   shifting the proj_ra2ll bounding box → geocoded PNG dims differ → SSIM
   uncomputable. The wired masking is **bit-exact** to gmt (proven); this is
   a pre-existing threshold-edge sensitivity, not a regression.
2. **S1_Ridgecrest_EQ** (5 fails) — the known no-DEM-corner artifact
   (`phasefilt.grd` complex-rms 0.3516) plus `corr_ll.grd`/`display_amp_ll`/
   `corr_ll.png`/`phasefilt_mask_ll` divergence. `corr_ll`/`display_amp` are
   produced by `_project()` (proj_ra2ll), a path **unchanged by this
   release**; their divergence is against a **freshly-regenerated csh
   reference** (Ridgecrest had no cached reference this sweep) in the
   unstable no-DEM zone — again not a grdmath regression. Test-reference
   management for the no-DEM case is a separate follow-up.

## Process rules added
- **Rule 14** — per-case sweep tripwire: verify each case's scorecard as it
  completes; on a structural break (missing-on-py) or unexpected regression,
  stop the sweep and examine (don't waste hours). Enforced via an event
  Monitor on `work/results/`.
- **Rule 15** — edge-case A/B before wiring a port at a new site: A/B on the
  grid that stresses the edge (not a benign smoke) before wiring + sweeping;
  wire only bit-exact sites, keep gmt for divergent ones.

## Performance note
grdmath wiring is ~parity on per-case wall time. The per-op win (in-process
avoids the gmt fork + netCDF `.grd` round-trip — ~3.7× on a 9.77M-cell MUL)
is real but a small slice of each case; surface (GS-SOR) compute dominates
end-to-end. The larger parity-safe speedup is the planned in-memory pipeline
(Phase B), scoped at a bounded ~5–15% per case (capped because surface
compute and un-ported gmt/viz I/O are not eliminable without a fuller port).
(The sweep's perf-snapshot wall was mis-recorded on this 3rd-reuse run; no
clean per-case delta is quoted here.)
