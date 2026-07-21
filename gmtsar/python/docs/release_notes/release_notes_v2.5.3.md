# Release notes — v2.5.3 (2026-06-18)

## grdsample `-R<gridfile>` wrapper fix + completion of bit-exact grdsample/blockmedian wiring

This patch fixes a region-handling bug in `grdsample_wrapper.py` and wires the
verified grdsample/blockmedian ports into the remaining bit-exact call sites,
completing the directed pipeline-wide wiring of every ported+verified operator.

### grdsample_wrapper.py — `-R<gridfile>` bug fixed (byte-exact)

`gmt grdsample <in> -R<refgrid> -G<out>` does **not** resample onto the ref
grid's verbatim dimensions: it **clips the region to the input extent** and
**snaps it to the ref node lattice**. The old wrapper mishandled this
(gridline-vs-pixel registration + verbatim ref dims). The fix adds:
- `_ref_geometry()` — reads ref geometry via `gmt grdinfo -C`.
- `_clip_snap_region()` — replicates gmt's clip-to-input + snap-to-ref-lattice
  in integer cell-index space.
- a loud Rule-1 guard for the unsupported path.

Byte-exact vs `gmt grdsample` on real merge grids (including overhang/clip).
+3 tests (`TestRefGridRegionFix`).

### Wired sites (Rule-15 edge-case A/B before wiring)

Routed to the Python ports (all bit-exact / ≤1 ULP on real data):
- `estimate_ionospheric_phase` — grdsample (max|diff|=0)
- `merge_unwrap_geocode_tops` — grdsample (iono resample, max|diff|=0)
- `make_dem` — grdsample (1 ULP; dem.grd byte-geometry-identical)
- `align_tops` — blockmedian (`-bo3d` cmp=0) + grdsample
- `tide_correction` — blockmedian (ASCII byte-identical) + grdsample
- new `utils/blockmedian_wrapper.py` (+ `test_blockmedian_wrapper.py`)

### Kept on gmt (Rule-15 — divergent, not bit-safe)

- `p2p_S1_TOPS_doublediff`, `calc_look_vector` — `_ll` non-uniform-x lattice
  drift (gmt special-cases near-uniform geo coords; the port treats them as
  exactly uniform).
- `correct_insar_with_gnss` — a **Rule-13 fresh-run catch**: the grdsample
  `-I` path here *crashes* on non-uniform-x input and the call uses unsupported
  `+n` syntax, contradicting an earlier inherited "byte-exact" claim. Left on
  gmt.

## Verification — full 21-case py-vs-csh sweep

**17/21 fully clean; 4 documented-benign; zero ra-domain regressions.**

The (c)-wired tools all operate in the **ra-domain**; a real regression would
corrupt `phasefilt.grd`/`filtcorr.grd`. Every one of those passed across all
21 cases (incl. the TOPS cases that exercise the new `align_tops` blockmedian/
grdsample wiring: `S1_Larsen_C`, `S1A_SLC_TOPS_COVE` fully clean).

The 4 non-clean cases are all **wiring-independent**:
1. **S1_Ridgecrest_EQ** — the long-documented no-DEM-corner artifact
   (`phasefilt.grd` complex-rms **0.3516**, identical to v2.5.0; undefined for
   both C and Python where the DEM does not cover the H_res grid) plus `_ll`
   divergence in the same no-DEM zone.
2. **ALOS_haiti** `phasefilt_mask_ll.png` — pre-existing `GE 0.14` threshold-edge
   sensitivity (documented v2.5.0).
3. **S1A_SLC_TOPS_Greece**, **S1A_SLC_TOPS_LA** — `_ll`-only geocode divergence
   from a **pre-existing py-vs-csh `proj_ra2ll` region-rounding difference**
   (see below), ra-domain clean.

### Finding: py-vs-csh `proj_ra2ll` geocode-region rounding (pre-existing)

Root-caused on Greece during this sweep: py `proj_ra2ll` computes a geocoded
region whose **west edge is 10 cells (= 10 × 2s) east** of what `proj_ra2ll.csh`
computes (5600 vs 5610 columns; same east/north/spacing). Confirmed
**independent of the v2.5.3 work and of the surface port**: a fresh re-run on the
existing `corr.grd`+`trans.dat` reproduced 5600 under both
`GMTSAR_SURFACE_INPROC=0/1` and `GMTSAR_GRDSAMPLE_PY=0/1`, and `dem.grd` +
`trans.dat` are byte-identical py-vs-csh. The whole corr_ll path
(`proj_ra2ll`, `gmt_surface_py`, `gmtsar_lib`) is byte-identical to v2.5.2.
It surfaces only against a **freshly regenerated** csh reference and is
geometry-specific (other TOPS cases — Larsen_C, COVE — are clean). Tracked as a
separate follow-up; **not** a v2.5.3 blocker.

## Process

Executed on the **main checkout** (no isolation worktree), which eliminated the
stale-worktree-base cherry-pick friction seen earlier in the campaign. Rule-14
tripwire refined to abort on structural (missing-on-py) or any **ra-domain**
failure while treating `_ll`-only geocode divergence as a documented NOTE.
