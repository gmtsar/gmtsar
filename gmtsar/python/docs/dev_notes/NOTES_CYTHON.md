# Cython kernel for gmt_surface_py GS-SOR — design & build log

## Goal
Replace the Numba `_iterate_once` and `_set_bcs` kernels in
`gmtsar/python/utils/gmt_surface_py.py` with a Cython extension
`_surface_kernel` that produces **bit-identical** output to the
current Numba path AND runs at ≤1.0× the wall-time of `gmt surface`
(gcc -O2) on the CSK grid (342,752 pts, 5595×5367 pixels).

## Files added
- `gmtsar/python/utils/_surface_kernel.pyx`  — Cython GS-SOR kernel
- `gmtsar/python/utils/build_surface_kernel.py` — standalone build script
- `gmtsar/python/NOTES_CYTHON.md` — this log

## Design decisions

### Arithmetic order preservation (critical for bit-identity)
The Numba kernel has `fastmath=False` precisely to preserve the float32/float64
mixed-precision chain that `gmt surface` uses:
- `u[]` array is float32 (gmt_grdfloat)
- Stencil coefficients (`coeff_unc`, `coeff_con`) are float64
- The 12-term stencil sum `u_00` is a float64 accumulation of float32*float64 products
- Briggs `b[]` coefficients are float32; the 4-term `sum_bk_uk` is
  float32*float32 promoted to float64 (`np.float64(b[k]*u[k])`)
- Final write: `u[node] = (float32)(u_00)` — rounds back to float32

The Cython kernel replicates this exactly using typed memoryviews:
- `float[::1] u` (float32)
- `double[::1] coeff_unc, coeff_con` (float64)
- All intermediate accumulations in `double`
- The 4 Briggs terms: `(float)(b[k]*u[k])` cast to float then promoted to double

### Cython compiler directives
```
@cython.boundscheck(False)
@cython.wraparound(False)
@cython.cdivision(True)
@cython.nonecheck(False)
```
Built with `-O2 -march=native` via `extra_compile_args`.

### `_set_bcs` kernel
Also ported to Cython for completeness; the BCs loop is tiny compared
to the inner GS-SOR sweep but keeping it in C avoids Python call overhead
in the outer `_iterate_to_converge` loop.

## Build command
```bash
cd /path/to/gmtsar/python/utils
/home/staff/dliu/anaconda3/envs/gmtsar/bin/python3.11 build_surface_kernel.py build_ext --inplace
```
Output: `_surface_kernel.cpython-311-x86_64-linux-gnu.so` (or similar)

## Graceful fallback
`gmt_surface_py.py` wraps the import:
```python
try:
    from _surface_kernel import iterate_once_cy, set_bcs_cy
    _HAVE_CYTHON_KERNEL = True
except ImportError:
    _HAVE_CYTHON_KERNEL = False
```
If the .so is absent, the Numba path is used transparently.

## Parity verification plan
1. Run 25-test suite with Cython active → all pass (0 fail)
2. Run CSK parity test → interior RMS ≤ 0.0666 m (unchanged from Numba baseline)
3. Compare Cython vs Numba on a 1001×1001 grid: assert max|diff| == 0.0

## Benchmark results (to be filled after build)
- Numba baseline: ~1.14× C on CSK grid
- Cython target: ≤1.0× C

