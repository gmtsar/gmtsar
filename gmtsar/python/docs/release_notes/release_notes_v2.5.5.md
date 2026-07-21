# Release notes — v2.5.5 (2026-06-29)

Housekeeping + findings release. **No pipeline code change** since v2.5.4
(`proj_ra2ll` geocode-region parity). This release commits the campaign's
documentation, performance numbers, and the surface-parallelization study, and
tidies scratch out of the source tree.

## State at this release

- **Matrix: 20/21** py-vs-csh clean. The non-clean cases are documented
  numerical-edge artifacts, **not** port regressions:
  - `ALOS_haiti` — `corr = conv(amp/√(amp1·amp2))` divides by ≈0 at a
    low-amplitude patch, amplifying the unavoidable ~1e-9 py-vs-csh upstream
    roundoff into a 0.037 corr diff → flips ~181 px at the `GE 0.14` mask →
    geocoded extent/SSIM differ. Same structural class as Ridgecrest.
  - `S1_Ridgecrest_EQ` — the no-DEM-corner artifact (`phasefilt.grd` undefined
    where the DEM doesn't cover the grid).
- **Upstream invariant = 0** (everything outside `gmtsar/python/` is
  byte-identical to upstream).
- **Hybrid, not pure-Python**: GMT (≥6.4), the C/Fortran SAR preprocessors, and
  snaphu remain required and compiled.

## Performance — per-sensor, py-vs-csh end-to-end (median of 23–142 runs)

`speedup = csh_wall / py_wall` (>1 = the Python framework is faster).

| Sensor | case | py (s) | csh (s) | speedup |
|---|---|---:|---:|---:|
| RS2 | RS2_SLC_Hawaii | 95 | 178 | 1.9× |
| NISAR | NISAR_Ethiopia | 292 | 447 | 1.5× |
| ALOS SLC | ALOS_SLC_L1.1 | 353 | 453 | 1.28× |
| ALOS-2 | ALOS2_SCAN_SSAF | 7774 | 8925 | 1.15× |
| ALOS | ALOS_ERSDAC_L1.0 | 825 | 938 | 1.14× |
| CSK | CSK_RAW_Hawaii | 668 | 748 | 1.12× |
| ENVISAT | ENVI_Baja_EQ | 1616 | 1784 | 1.10× |
| ALOS | ALOS_Baja_EQ | 1009 | 1096 | 1.09× |
| ERS | ERS_Hector_EQ | 1178 | 1269 | 1.08× |
| TSX | TSX_SLC_Hawaii | 752 | 788 | 1.05× |
| ALOS-4 | ALOS4_Pinon | 1147 | 1184 | 1.03× |
| S1 TOPS | S1_Ridgecrest_EQ | 7789 | 9235 | 1.19× |
| S1 TOPS | S1A_SLC_TOPS_LA | 6358 | 6683 | 1.05× |
| S1 TOPS | Greece / COVE / Larsen_C | 3006 / 5486 / 4956 | ≈ | ~1.00× |

Stripmap sensors gain ~5–90% (largest on small/SLC cases where vectorized
kernels dominate). **S1 TOPS is ~parity** — those runs are dominated by surface
(kept on gmt-C), snaphu, and merge, which the Python kernels don't touch. Net:
faster on most cases, never slower. Full per-sweep snapshots in
`docs/perf_snapshots/`.

## Surface parallelization study → NOT pursued (hardware wall)

Surface (Briggs biharmonic SOR) is the single largest per-case cost but is
**memory-bandwidth-bound**, so adding CPU cores does not help. Two independent
prototypes on the real 39M-node `pixel.grd`:

- 9-color (red-black) numba SOR — ~0% scaling 1→8 threads; also drifts to a
  Jacobi fixed point.
- domain-decomposition block-SOR — 0.98–0.99× at 2–16 threads; measured
  effective bandwidth 3.8→4.4 GB/s going 1→2 threads (+16%, not +100%).

`gmt surface` (C, 269s) already beats the numba port (412s) single-threaded and
wouldn't thread-scale either. Reports + prototype code:
`docs/experiments/PROTO_surface_redblack.md`,
`docs/experiments/PROTO_surface_parallel_domain.md`. The only real surface
levers are **fewer iterations** (`-S` search-radius / multigrid; single-core,
parity-safe) or **GPU** (~10× bandwidth).

## In-memory pipeline (Phase B) → shelved

Instrumented profiling showed `.grd` I/O is <0.3% of per-case wall (NFS reads
are page-cached at ~7.6 GB/s; netCDF (de)serialization ~1.34 s per fusible
intermediate, ~3–6 per case). Not worth the refactor; surface/compute dominate.

## Open next steps

1. **ALOS_haiti** — document as a threshold-edge artifact (recommended) or
   attempt bit-exact `phasediff` (large, risky, touches every case).
2. **Parallel compute on the compute-bound islands** (surface is dead, but
   these are not):
   - **FFT steps** (`xcorr`, `phasefilt`) — currently forced single-threaded by
     `fftw_force_serial.so`; un-throttling / batched-parallel FFT could scale.
   - **SAT geometry** (`vector.py`, `SAT_llt2rat`) — per-point trig/sqrt,
     `@njit(parallel=False)` today; `prange` would scale.
   - Profile their share of wall first — they're smaller slices than surface, so
     the upside is bounded.
3. **Publish / contribute upstream** — the fork is clean, tagged, invariant=0.

## Repo tidy in this release

- dev scratch notes → `docs/dev_notes/`
- surface-parallel prototypes + reports → `docs/experiments/`
- removed generated `bin_py/tests/phase_profile_py.json` (now gitignored)
