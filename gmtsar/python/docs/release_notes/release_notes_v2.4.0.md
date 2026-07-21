# Release notes — v2.4.0 (2026-06-17)

## Milestone: the compute kernels have verified, default-on Python implementations

v2.4.0 marks the point where every heavy per-pixel **compute kernel** has a
Python implementation that is default-on **at its primary call site(s)** and
verified bit-faithful to the csh/C pipeline. With those defaults enabled, a
full 21-case sweep against the csh oracle is **20/21 py-vs-csh clean** — the
lone diff being the long-documented `S1_Ridgecrest_EQ` no-DEM-corner surface
artifact (phasefilt complex-rms 0.3516, undefined for both C and Python where
the DEM does not cover the H_res grid; masked/merged products match).

> **Scope — read this before "it's fully Python."** This is **not** a
> GMT-free pipeline, and the framework still requires a GMT install (see
> *Scope & dependencies* below). The Python ports replace the numerically
> expensive *inner loops* at their main call sites; the surrounding
> geospatial toolkit (grid I/O, projection, visualization, ~60 `gmt`
> subcommands), the C/Fortran SAR preprocessors, and snaphu remain C. The
> 20/21 result validates that **the hybrid pipeline** (Python kernels at
> wired sites + GMT everywhere else) matches csh bit-for-bit — not that gmt
> is no longer called.

### Compute kernels — Python implementation, default-on at primary call sites
(Selective wiring: e.g. `gmt_grdmath_py` is wired in `filter` + `stack`; other
`gmt grdmath` call sites — iono, snaphu masking, merge, stack_corr, geocode —
still call the `gmt` C binary. Surface is wired in `dem2topo_ra` + 5 rerouted
calls. So most operator *invocations* across the pipeline still go to gmt.)

| Core | Python module | Default |
|------|---------------|---------|
| Cross-correlation | `xcorr_py` | ON |
| Phase difference | `phasediff_py` | ON |
| Convolution | `conv` (Python) | ON |
| Resampling | `resamp_py` | ON |
| SAT_llt2rat / SAT_look trio | `utils/vector.py` | ON |
| Block median | `gmt_blockmedian_py` | ON |
| Phase filter | `phasefilt_py` | ON |
| Surface (biharmonic spline) | `gmt_surface_py` (+ Cython GS-SOR kernel) | ON (v2.3.0) |
| grdmath operators | `gmt_grdmath_py` | ON (v2.3.8) |
| grdsample | `gmt_grdsample_py` | ON |
| grdfilter / grdfill | `gmt_grdfilter_py` / `gmt_grdfill_py` | available |

### snaphu (phase unwrapping)

snaphu remains the **C binary in production**. The pure-Python/numba port
(`bin_py/snaphu_py/`) is a verified **correctness/audit reference**: the
network-simplex anti-cycling bug was solved in v2.3.7 (30×30 and 64×64 real
ALOS_haiti patches are float32-exact vs the C binary). A Cython kernel
(v2.3.9, experimental, unwired) confirmed the remaining gap is a
**struct-of-arrays vs array-of-structs cache-layout** constant factor
(~125×), not algorithm or interpreter — so full-grid production speed would
require an AoS rewrite or a cffi→C wrap. Since snaphu is ~0.3% of pipeline
wall-time (macro profile), production stays on the C binary.

## Scope & dependencies (what is *not* Python)

The framework is a **hybrid**, not a pure-Python reimplementation. It still
requires a working **GMT (≥6.4) install** — at both runtime and build time:

- **~60 GMT subcommands are called and were never ported** — `grdinfo`,
  `grd2xyz`, `xyz2grd`, `grdcut`, `gmtinfo`, `grdimage`, `gmtconvert`,
  `psconvert`, `grdtrack`, `makecpt`, `psscale`, `grdedit`, `project`,
  `grd2kml`, `trend2d`, … (grid I/O, projection, visualization).
- **Even ported operators are wired selectively** — only the primary call
  sites route to Python. Most `gmt grdmath` / `gmt surface` / `gmt blockmedian`
  *invocations* across the pipeline still call the `gmt` C binary.
- **GMT is a build/link dependency** — gmtsar's own C binaries compile
  against `-lgmt` (libgmt).
- **SAR preprocessing is C/Fortran, unported** — `make_slc_s1a`,
  `make_slc_csk`, `make_raw_csk`, `make_slc_tsx/rs2/gf3/lt1`, `calc_dop_orb`,
  `extend_orbit`, `update_PRM`, etc. (reading/focusing raw SAR data).
- **snaphu** (phase unwrapping) is the C binary in production.
- GMT is also the `.grd` (netCDF) I/O layer the pipeline reads/writes through.

Dropping the GMT dependency would require porting the remaining ~60 GMT
subcommands (incl. projection and all visualization), replacing GMT's grid
I/O wholesale, and relinking/porting the C/Fortran SAR preprocessors off
libgmt — effectively reimplementing GMT. That is far beyond this milestone's
scope and is not planned.

## What got here (v2.3.6 → v2.4.0)

- **v2.3.6** — fixed `grdmath_corr_chain` GMT native `=bf` header (wrong
  registration/offsets) so `conv` reads `corr.grd` at the correct dims.
- **v2.3.7** — solved the snaphu network-simplex anti-cycling remount bug
  (matched C's `snaphu_solver.c` thread-rewire + WrapPhase seed).
- **v2.3.8** — flipped `GMTSAR_GRDMATH_PY` default OFF→ON (20/21 sweep).
- **v2.3.9** — experimental Cython snaphu kernel + SoA-cache diagnosis.
- **v2.4.0** — full all-Python-defaults 21-case capstone sweep, 20/21 clean.

## Performance note (the next chapter)

A macro profile across the matrix shows `dem2topo_ra` / **surface dominates
end-to-end wall-time (36–81% per case)**; snaphu is ~0.3%. Surface is
already at ~1.0–1.14× the `gmt surface` C binary (Cython kernel), so further
speedup requires an algorithmic change (multigrid, red-black SOR) or GPU —
each of which alters update order and therefore **breaks bit-identity** with
`gmt surface`. That parity-vs-speed tradeoff is the central decision for the
optimization phase.
