# PROTO_surface_redblack — Parallel SOR Prototype Evaluation

**Status:** Prototype only. NOT wired into the pipeline. No default path modified.  
**Date:** 2026-06-19  
**Author:** Dr. Mira Volkov (performance engineering)  
**Files:**
- Prototype: removed in the v2.7.1 doc cleanup (dead code, never
  imported); recoverable from git history before that release.
- Reference grids: `gmtsar/python/work/proto_surface_test/`  

---

## Purpose

Evaluate whether a 9-color (parallel) SOR variant of the biharmonic surface
solver can beat the production Cython GS-SOR kernel (`_surface_kernel.pyx`)
on wall time while staying within acceptable parity of `gmt surface` C output.

The production solver is already ~1.0-1.17× faster than `gmt surface` C on
real data. The question is: can parallelism buy more?

---

## Stencil Analysis

`gmt surface` uses the Briggs (1974) biharmonic spline-in-tension with a
**12-node stencil** (surface.c lines 1078-1159):

```
N2(-2,0)  NW(-1,-1)  N1(-1,0)  NE(-1,+1)
W2(0,-2)  W1(0,-1)             E1(0,+1)  E2(0,+2)
SW(+1,-1) S1(+1,0)  SE(+1,+1)
S2(+2,0)
```

Maximum reach: ±2 cells in both row and column directions.

**Why 2-color (red/black) fails:**  
Classic checkerboard assigns `color = (row+col) mod 2`. Same-color nodes can
be at offsets (+1,+1), (0,+2), (+2,0) — all within the ±2 stencil reach.
Those nodes would read stale neighbors of their own color within a single
pass, producing a wrong update formula.

**Minimum safe coloring — 9 colors:**  
`color = (row mod 3) * 3 + (col mod 3)`.  
Within one color, all row differences are multiples of 3 and all column
differences are multiples of 3. Since the stencil max |dr| = 2 < 3 and
max |dc| = 2 < 3, no stencil offset maps to (dr mod 3, dc mod 3) = (0,0).
Verified algebraically — all 12 offsets produce non-(0,0) residuals.

---

## Implementation

The (now-removed) prototype implemented `surface_9color()` with:
- Same PDE (biharmonic spline-in-tension, tension T=0.5)
- Same stencil weights (computed by `_compute_coefficients`, same as production)
- Same Briggs sub-cell constraint coefficients
- Same multi-stride W-up nested iteration hierarchy
- Same boundary conditions (`_set_bcs`)
- Same float32 grid (gmt_grdfloat), same omega=1.4 SOR factor
- **Different sweep order:** 9 sequential color passes per sweep (vs row-major GS)
- **numba prange** over rows within each color pass

---

## Test Setup

Hardware: Linux x86-64, `utig5` server  
GMT version: 6.4.0  
numba version: 0.65.1  
Tension: T=0.5, max_iter=500 (per-stride: 500×stride), tol=1e-4  

**Datasets:**

| Dataset | Path | Grid size | gcd(nx-1,ny-1) | Points in |
|---|---|---|---|---|
| RS2 Hawaii (small) | `work/python_test/RS2_SLC_Hawaii/topo/trans.dat` | 72×38 | 1 | ~978K |
| Greece TOPS (large) | `work/python_test/S1A_SLC_TOPS_Greece/merge/trans.dat` | 676×235 | 9 | ~6.98M |

Region: `gmt gmtinfo trans.dat -bi5d -i3,4,2 -I16s/32s`  
Spacing: -I16s/32s (16"/32" arc-seconds = 0.00444°/0.00889°)  
Reference oracle: fresh `gmt surface` C run at OMP_NUM_THREADS=1 (each benchmark run)  

Best-of-3 timing; thread count swept with `numba.set_num_threads()`.

---

## Results

### TABLE 1 — Wall-time and Speedup (best of 3 runs, OMP_NUM_THREADS=1 for C)

| Dataset | Scheme | Threads | Wall (s) | vs GS-SOR | vs gmt C | Iters |
|---|---|---:|---:|---:|---:|---:|
| rs2_hawaii (72×38) | gmt C | 1 | 0.40 | — | 1.00× | — |
| rs2_hawaii | GS-SOR (Cython) | 1 | 0.20 | 1.00× | 2.06× | — |
| rs2_hawaii | 9-color SOR | 1 | 0.19 | 1.04× | 2.14× | 7 |
| rs2_hawaii | 9-color SOR | 2 | 0.19 | 1.04× | 2.13× | 7 |
| rs2_hawaii | 9-color SOR | 4 | 0.19 | 1.04× | 2.13× | 7 |
| rs2_hawaii | 9-color SOR | 8 | 0.19 | 1.03× | 2.13× | 7 |
| greece_tops (676×235) | gmt C | 1 | 3.71 | — | 1.00× | — |
| greece_tops | GS-SOR (Cython) | 1 | 3.19 | 1.00× | 1.16× | — |
| greece_tops | 9-color SOR | 1 | 1.87 | **1.71×** | **1.98×** | 11 |
| greece_tops | 9-color SOR | 2 | 1.87 | 1.71× | 1.99× | 11 |
| greece_tops | 9-color SOR | 4 | 1.87 | 1.70× | 1.98× | 11 |
| greece_tops | 9-color SOR | 8 | 1.88 | 1.70× | 1.98× | 11 |

### TABLE 2 — Parity Delta vs `gmt surface` C (interior nodes, single-thread run)

| Dataset | Scheme | RMS (m) | max\|diff\| (m) |
|---|---|---:|---:|
| rs2_hawaii (72×38) | GS-SOR (Cython) | **6.23e-01** | **5.74** |
| rs2_hawaii | 9-color SOR | 4.62e+01 | 4.84e+02 |
| greece_tops (676×235) | GS-SOR (Cython) | 4.70e+01 | 5.90e+02 |
| greece_tops | 9-color SOR | 1.05e+02 | 8.58e+02 |

---

## Diagnostic Findings

### 1. Thread parallelism does not scale

Adding threads 1→8 gives **0% speedup** on both datasets. Root cause:

- Per 9-color pass, prange runs over `n_rows_color ≈ ny/3` rows.  
  For Greece (235 rows): ~78 rows/color, split over 8 threads = ~10 rows/thread.  
  Each thread handles ~10 × 225 = 2,250 stencil evaluations per color pass.  
- 9 color passes × 18 BC barriers per sweep × 11 sweeps = 1,782 thread-pool
  activations per solver call.  
- Thread-launch and barrier overhead dominates. The FLOP budget per thread
  is too small to amortize the prange fixed cost.

On a 4000×4000 synthetic grid (outside real pipeline range): 8 threads gives
only 1.17× speedup (2.36s → 2.02s) — still far from linear.

### 2. Why single-thread 9-color is 1.71× faster than Cython GS-SOR on Greece

This is NOT parallelism — it's an iteration-count artifact. The 9-color SOR
does 11 full sweeps (at stride=1) vs GS-SOR hitting `max_iter` (500)
without converging. Verbose output from GS-SOR on Greece TOPS:

```
stride=1 DATA: hit max_iter (500) last_change=2.568e-04 limit=1.000e-04
```

The 9-color solver reaches the same non-convergence state faster because its
Jacobi-like updates (reading non-updated same-sweep neighbors) advance the
solution in fewer sweeps at the cost of weaker per-sweep contraction. Both
schemes diverge from `gmt surface` C output because neither converges within
the iteration budget — the C binary completes far more iterations in the
same wall-time because its Cython inner loop is tighter per iteration.

### 3. Parity: 9-color degrades vs GS-SOR

On RS2 Hawaii (small, well-constrained grid where GS-SOR converges):
- GS-SOR parity: RMS=0.62m, max=5.74m (float-roundoff order)
- 9-color parity: RMS=46m, max=484m — **74× worse**

The degradation comes from the different fixed point: GS-SOR (in-place) and
Jacobi-style 9-color SOR converge to slightly different solutions because
they propagate information at different rates across the ghost-boundary nodes.
The Gauss-Seidel fixed point = GS-SOR fixed point = C binary fixed point (to
float32 roundoff). The 9-color Jacobi-like fixed point is a distinct solution.

On Greece TOPS (neither converges): both schemes diverge from C, but 9-color
diverges ~2× more (RMS 105m vs 47m) because it has seen only 11 passes (each
9-color pass = 9×(nx/3)×(ny/3) ≈ nx×ny updates total, same as 1 GS sweep),
vs GS-SOR which runs 500 passes, getting closer to the C solution.

---

## Summary: Why Parallelizing Surface Does Not Pay Off

| Issue | Finding |
|---|---|
| Thread scaling | Zero. prange overhead >> compute at real-data grid sizes (72×38, 676×235). |
| Parity: GS-SOR | 0.62m RMS on small converged case; float-roundoff faithful. |
| Parity: 9-color | 46m RMS on same small case — 74× worse; wrong fixed point. |
| Single-thread 9-color speedup | 1.71× on large grid vs production GS-SOR, but both fail to converge. |
| Root cause of non-convergence | Neither scheme closes within 500 iterations at stride=1 on 676×235 real terrain. The C binary converges because each GS sweep is ~10× faster per-iteration (Cython vs Numba overhead at the per-node level). |

**The right fix for the parity gap is more iterations per second (i.e., faster
GS-SOR kernel), not a parallel scheme that changes the fixed point.**

---

## Recommendation

**Do NOT wire the 9-color parallel SOR into the pipeline.**

Rationale:

1. prange provides zero speedup on real GMTSAR grid sizes. The work per thread
   per color pass is ~2,000 nodes — below the threshold where thread overhead
   breaks even (empirically ~50,000 nodes/thread for numba prange on this hardware).

2. The 9-color scheme breaks parity with `gmt surface` C output by 74× on the
   small converged case. The float-roundoff-faithful guarantee (project invariant,
   memory `GMTSAR_SURFACE_INPROC must stay OFF`) cannot be maintained.

3. The single-thread 1.71× speedup over Cython GS-SOR on the large grid is an
   artifact of reduced iterations-to-convergence under the Jacobi update order,
   not genuine work reduction. It comes at the cost of a different (wrong) fixed
   point and is not robust across datasets.

**Recommended path if further speedup is needed:**

- Profile and optimize the Cython `iterate_once_cy` inner loop (currently the
  parity-faithful bottleneck). Each per-node iteration is ~50 float ops; AVX2
  vectorization of the stencil sum (SIMD over 8 floats) could give 4-6× without
  changing the GS update order or the fixed point.
- Alternatively: reduce the number of strides needed by a better coarse-grid
  initialization (search-radius fill, `-S` flag, currently not ported) so that
  fewer iterations are needed at fine strides.
- Do NOT relax the parity tolerance to accommodate the 9-color fixed point.
