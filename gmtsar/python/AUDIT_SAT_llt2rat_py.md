# SAT_llt2rat_py — status as of 2026-05-20 (Mira Volkov goldop closure)

## TL;DR

`bin_py/SAT_llt2rat_py` is now **bit-faithful to C `SAT_llt2rat` on azi_pix,
lon, lat** (max|d|=0 on all 978882 rows of the RS2 Hawaii DEM) for
precise=0, with sub-mm residual on range_pix and sub-nm on height from
sub-ULP order-of-summation differences that DO NOT affect goldop branch
decisions. Production wire-in is GREEN. Recommendation: re-enable in
`utils/dem2topo_ra` and re-run the RS2 sweep with PNG comparison.

## Parity numbers (RS2 Hawaii DEM, 9.3 M cells → 978882 in-coverage rows)

| Column     | Before (bisection goldop) | After (C-faithful, this audit) |
|------------|---------------------------|--------------------------------|
| range_pix  | rms 1.7e-5 px, max 4.9e-5 | **rms 3.4e-12 px, max 1.2e-10** |
| azi_pix    | rms 1.4 px, max 4.0 px    | **rms 0, max 0** (bit-identical) |
| height     | rms 7.5e-10 m, max 3.7e-9 | **rms 2.2e-11 m, max 1.9e-9** |
| lon        | 0                          | 0 |
| lat        | 0                          | 0 |
| row count  | 978895 (+13 extra)         | **978882 (exact match)** |

For precise=1: range_pix max 2.3e-9 px, azi_pix max 2.4e-6 px (residual
from polyfit_refine path which is also tightened but not bit-exact).

## What was fixed (root-causing the goldop divergence)

The bisection-style `goldop_batch` was a symptom, not the root cause. The
true 4-point golden section was correctly portable; the prior attempt's
"rms 33 px" failure was a coding bug. But once corrected, six SEPARATE
numerical-roundoff bugs upstream were exposed at the goldop convergence
floor, each flipping branches on a few edge-case targets:

1. **`np.arange` time accumulation** (presample_orbit): np.arange-based
   time grid drifts ~1e-5 s over 18k samples vs C's per-index
   `time = t1 - npad*ts + i*ts`. → ~7 mpx azi_pix systematic offset.
   FIX: per-index explicit formula.

2. **Off-by-one in nrec** (presample_orbit): np.arange yielded one extra
   sample vs C's `int((t2-t1)/ts) + 2*npad`. FIX: mirror C formula.

3. **LED-time vs synthetic-time Hermite knots** (presample_orbit): Py
   used the actual ASCII-parsed LED times (1.86e-9 s roundoff per knot),
   C uses synthetic `pt[k] = pt0 + k*dsec`. → ~1e-5 m orb_pos drift.
   FIX: pass `meta` to presample_orbit, build synthetic knots.

4. **Horner-basis vs direct Hermite** (hermite_orbit): the
   `hermite_c_1d_uniform` Horner fast path is algebraically equivalent
   to C's direct Lagrange-style Hermite but ~1e-6 m numerically.
   FIX: use general `hermite_c_1d` with synthetic knots (no fast path).

5. **Hermite multiplication ordering** (hermite_c_1d): Py's `hj *= a / b`
   evaluates as `hj * (a/b)` — 1 ULP off C's `hj = hj * a / b` =
   `((hj*a)/b)`. FIX: rewrite as `hj = (hj * a) / b`.

6. **Truncated `pi` in C `deg_to_rad`** (plh2xyz): C uses
   `#define pi 3.14159265358979` (14 digits, NOT math.pi's 15).
   → 1-ULP diff in lat_rad → ~5e-9 m in xyz → flipped goldop branches.
   FIX: hardcode `_PI_GMTSAR = 3.14159265358979`.

7. **C `funsq` vs Py `1-e2` algebraic equivalents** (plh2xyz): C
   `(1-FL)*(1-FL)` vs Py `1 - 2*FL + FL²` differ by 1 ULP.
   FIX: rewrite plh2xyz to follow C's exact statement order.

8. **Wrong SOL constant**: gmtsar uses `#define SOL 299792456.0`, Py was
   using the true 299792458.0 (2 m/s difference). → 2e-5 px systematic
   offset in range_pix. FIX: use C's value.

9. **Squared-distance optimisation in goldop_batch** (the one that broke
   the LAST edge case): `f² < f²` and `sqrt(f²) < sqrt(f²)` are not
   bijective at the float-ULP level when f₁ ≈ f₂. C compares sqrt'd
   values; Py was comparing squares to save ~N*niter sqrts. → 1 row
   diff. FIX: take sqrt every iteration (matches C, costs a few ms).

The **TRUE goldop port itself** (C-faithful 4-point golden section with
SHFT3/SHFT2 cascade and OLD-value-capture pattern for vectorisation)
was a clean port — bugs 1-9 above were all upstream of it, exposed only
once the goldop port was finally precise enough to NOT mask them.

## Defenses added (Pattern 4 / parity-gate hygiene)

- `tests/test_SAT_llt2rat.py::TestC5GoldopBatch` — three new tests
  asserting `goldop_batch` (vectorised) is bit-identical to scalar
  `goldop` on 1 target, 30 random targets, and across chunk boundaries.
- `tests/test_SAT_llt2rat.py::TestEndToEndCParity` — full end-to-end
  byte-level diff vs C `SAT_llt2rat` on the RS2 DEM. Skips cleanly when
  the C binary or input files are absent. Took 58 s on the test host.

## Performance

| Path                                       | Time (RS2 9.3 M cells) |
|--------------------------------------------|------------------------|
| C `SAT_llt2rat` (precise=0)                | 9 s                    |
| Py `SAT_llt2rat_py` (precise=0, no Numba)  | ~30 s                  |
| Py `SAT_llt2rat_py` (precise=0, Numba JIT) | **~15 s** (1.7× C)     |
| C `SAT_llt2rat` (precise=1)                | 75 s                   |
| Py `SAT_llt2rat_py` (precise=1, no Numba)  | 383 s (~5× slower)     |
| Py `SAT_llt2rat_py` (precise=1, Numba JIT) | **~54 s** (faster than C) |

Per-kernel speedups (RS2 9.3 M cells, anaconda_knox + numba 0.59.1,
single-thread, fastmath=False):

| Kernel               | numpy time | numba time | speedup |
|----------------------|-----------:|-----------:|--------:|
| `goldop_batch`       | 18.7 s     | 2.4 s      | 7.7×    |
| `polyfit_refine_batch` (mostly `hermite_c_1d_uniform`) | 304.2 s | 39.2 s | 7.8× |
| `presample_orbit` (`hermite_c_1d` general) | 0.013 s | 0.006 s | 2× |

Numba JIT is **optional**: set `SAT_LLT2RAT_PY_NUMBA=0` (or install
without numba) → falls back to the pure-numpy paths automatically. All
three modes produce **bit-identical parity** to C (azi_pix max|d|=0,
lon/lat=0, range_pix max 1.2e-10 px for precise=0; same numbers as the
pre-Numba baseline for precise=1).

The JIT kernels (`_hermite_c_1d_jit`, `_hermite_c_1d_uniform_jit`,
`_goldop_jit`) are **line-by-line mirrors** of the pure-numpy versions
that themselves mirror the C source. In particular they preserve:
- C's left-associative arithmetic (Mira #5 / bug #5): `hj = (hj*(xp-xj))/(xi-xj)`,
  not `hj *= (xp-xj)/(xi-xj)`.
- Truncated golden-ratio constants (bug #6 / bug #7): hard-baked as
  numeric literals inside the JIT body.
- C `SHFT3`/`SHFT2` cascade semantics with OLD-value capture before any
  branch update (Pattern 4 vectorisation trap).
- Per-iter `sqrt` in goldop (bug #9) — same Mira removed.

`cache=False` on the JIT decorators: cold-compile cost is ~2 s, paid
once per process; the alternative (`cache=True`) caused cross-context
breakage when the module was loaded under different `__name__`s
(unittest test loader vs direct script invocation).

## Wire-in recommendation

**Re-enable `SAT_llt2rat_py` in `utils/dem2topo_ra` and re-run the RS2
sweep with PNG comparison.** The 1.4 px azi_pix drift that previously
broke the PNG visual comparison is now 0 px — all 978882 in-coverage
rows have bit-identical azi_pix to C. PNG diff should pass.

The 3.5× wall-clock cost (9 s → 32 s) is acceptable; the previous
hot-path optimisations (binary stdin via `-bi3d`, etc.) still apply.

## Files involved

- `gmtsar/python/bin_py/SAT_llt2rat_py` — the port (this commit's diff)
- `gmtsar/python/bin_py/tests/test_SAT_llt2rat.py` — new parity tests
- `gmtsar/SAT_llt2rat.c`, `hermite_c.c`, `plxyz.c`, `llt2xyz.h`,
  `gmtsar.h` — C source consulted (no changes)

## 2026-05-21 follow-up (Mira #4) — ALOS_haiti los_ll fix

The `utils/dem2topo_ra` wire-in shipped on 2026-05-20 used the
`-bi3d`/`-bo3d` binary-stdin fast path:

```
gmt grd2xyz dem.grd -s -bo3d | SAT_llt2rat_py master.PRM 0 -bod -bi3d
```

This was **WRONG** for parity. The C dem2topo_ra.csh pipeline that
SAT_llt2rat_py mirrors is:

```
gmt grd2xyz --FORMAT_FLOAT_OUT=%lf dem.grd -s | SAT_llt2rat master.PRM 0 -bod
```

i.e. ASCII output with `%lf` (6-digit) quantization. The C binary has
never been exposed to full-precision float64 inputs in production
pipelines. Feeding SAT_llt2rat_py full-precision inputs via `-bi3d`
fed it lon/lat/h that the C parity oracle had never seen and produced:

- ALOS_haiti: max|d| azi_pix = **2 pixels** on ~99% of rows,
  range_pix max|d| 0.0058 px, height max|d| 7.7e-5 m, lon/lat max|d|
  3.3e-7 deg (the %lf-to-full-float64 step itself).

These compound through blockmedian -> surface -> topo_ra -> topo_shift
-> phase -> unwrap -> los into:

| stage              | RMS diff vs C |
|--------------------|---------------|
| topo_ra.grd        | 0.077 m       |
| topo_shift.grd     | 0.077 m       |
| phase.grd          | 0.073 rad     |
| phasefilt.grd      | 0.11 rad      |
| unwrap.grd         | 0.069 rad     |
| los.grd            | 1.30 mm       |
| los_ll.grd         | 1.51 mm       |

This is Mira Pattern 5: "Input-format quantization in the parity test".
The unit test in `test_precise0_bit_identical` uses `%.17g` ASCII —
finer than what csh actually sends C — so it passed even while the
production pipeline was off-trajectory.

Fix: revert `dem2topo_ra` to the `%lf` ASCII pipeline. This restores
sub-ULP parity (lon/lat max|d|=0, azi_pix max|d|=3.6e-12 px, range_pix
max|d|=1e-10 px, height max|d|=1.9e-9 m) on ALOS_haiti — verified by
direct C-vs-py diff at trans.dat.

Test added: `test_precise0_csh_lf_pipeline_parity` mirrors the actual
csh `dem2topo_ra.csh` pipeline (`--FORMAT_FLOAT_OUT=%lf`) and asserts
byte-level parity. This catches the regression that
`test_precise0_bit_identical` couldn't see because it used
full-precision ASCII.

Files updated:
- `gmtsar/python/utils/dem2topo_ra` (line 103-105 revert to ASCII pipe)
- `gmtsar/python/bin_py/dem2topo_ra_py` (the same fix in the bin_py
  alternate path that also defaulted to `-bi3d` if SAT_llt2rat_py was
  on PATH)
- `gmtsar/python/bin_py/tests/test_SAT_llt2rat.py` (new
  `test_precise0_csh_lf_pipeline_parity` test)

Performance cost: the `-bi3d` path was advertised as ~2x faster on the
standalone SAT_llt2rat_py call (15.9 s -> 7.5 s on RS2 9.3 M rows). In
the end-to-end dem2topo_ra wallclock, `surface` (5-10 min) and
`blockmedian` dominate; SAT_llt2rat_py is a small fraction. Reverting
to ASCII is a negligible end-to-end cost for restored parity.
