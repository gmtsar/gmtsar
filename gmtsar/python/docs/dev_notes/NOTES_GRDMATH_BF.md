# NOTES_GRDMATH_BF.md — gmt_grdmath_py =bf fix

## Bug

`grdmath_corr_chain` with `dst='tmp2.grd=bf'` stripped the `=bf` suffix and
wrote a netCDF4 file.  `conv` (conv.c:205-212) opens the file as raw binary
via fopen() after GMT_Read_Data recognises the =bf suffix → netCDF bytes at
offset 892 are not float32 grid data → conv crashes → corr.grd not produced.

## Fix applied (2026-06-17)

File: `gmtsar/python/utils/gmt_grdmath_py.py`

1. Added `import struct` to module imports.

2. Added `_write_gmt_binary_float(path, data, x, y, info, hist)` helper that
   writes the 892-byte GMT native binary-float header + raw float32 data.

   Key finding during verification: the `xy_off` field at bytes 60-67 of the
   GMT =bf header must be **1.0**, not 0.0.  GMT computes
   `n_columns = (xmax - xmin) / xinc + xy_off`, so xy_off=0.0 yields
   n_columns=0 and x_inc≈0 (reported by grdinfo as ERROR).  Real GMT =bf
   files always write 1.0 here for gridline-registered grids.  The bug
   report's "use 0.0" annotation was incorrect.

3. Modified `grdmath_corr_chain`: when `"=bf" in dst`, calls
   `_write_gmt_binary_float(dst_path, result, x, y, info, hist)` instead of
   `_save()`.  The `result` array already has FLIPUD applied (it's
   `np.flipud(_op_mul(divided, mask))`) so `_write_gmt_binary_float` writes
   it as-is without an additional flip.

## Verification

### Test 1 — `gmt grdinfo` + `conv` on synthetic 5×4 grid

```
gmt grdinfo /tmp/test_bf.grd=bf:
  x_min: 0 x_max: 4 x_inc: 1  n_columns: 5
  y_min: 0 y_max: 3 y_inc: 1  n_rows: 4
  v_min: 0 v_max: 19

conv 1 1 .../gauss5x5 /tmp/test_bf.grd=bf /tmp/test_out.grd
  Exit code: 0
  /tmp/test_out.grd: 712 bytes (nonzero)
```

### Test 2 — Existing parity suite

```
pytest gmtsar/python/bin_py/tests/test_gmt_grdmath_py.py -v
  39 passed in 2.68s
```

### Test 3 — Smoke (Hawaii RS2)

Not run (data not confirmed present in worktree env).

## Other =bf sites

Only one `=bf` site exists in `gmt_grdmath_py.py` (line 587, inside
`grdmath_corr_chain`).  No other functions in the file use `=bf`.
