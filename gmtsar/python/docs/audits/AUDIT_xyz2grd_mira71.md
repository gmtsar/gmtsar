# AUDIT — gmt_xyz2grd_py port (Mission #71)

**Status: GREEN.** Call site #1 (snaphu.py `-ZTLf`/`-ZTLu` binary reshape)
landed, byte-identical to gmt 6.4.0 on real ALOS_haiti data, ~10x faster
than the subprocess on a real 2826x3456 grid. Wired into `utils/snaphu.py`
behind `GMTSAR_XYZ2GRD_PY` (default OFF).

## What landed

- `utils/gmt_xyz2grd_py.py` — verbatim port of the `-ZTL<type> -r` mode of
  `gmt xyz2grd` (the only mode the production pipeline uses, per
  `xyz2grd.rst -Z`: "-A is ignored if -Z is given" — no aggregation, no
  NaN-fill, all nodes assumed present).
  - `gmt_xyz2grd_py(raw, region, x_inc, y_inc, dtype)` — pure array API:
    reshape `(ny*nx,)` -> `(ny, nx)` top-row-first, flip vertically to
    y-ascending, upcast to float32, build pixel-center coord arrays.
  - `gmt_xyz2grd_py_file(in_path, out_path, par1, par2, ztype)` — file
    wrapper, parses `-R`/`-I` strings from `gmt grdinfo -I-`/`-I` and
    writes via `gmt_grd_io.write_gmt_grd_from_increments(node_offset=1)`.
- `utils/xyz2grd_wrapper.py` — env-gated (`GMTSAR_XYZ2GRD_PY`, default
  `0`/OFF) drop-in for the subprocess call, following the
  `grdcut_wrapper.py` pattern. OFF path calls `gmtsar_lib.run()` exactly as
  before (non-fatal WARN on rc!=0 — Rule 0, no change to legacy error
  semantics on the default path).
- `utils/snaphu.py` — both call sites (`snaphu_unwrap` ~line 226 and the
  legacy `snaphu()` CLI ~line 397/400) now go through `_xyz2grd_file(...)`.
- `bin_py/tests/data/xyz2grd_phase_small.grd` — committed 100x400
  (pixel-reg) fixture, a `gmt grdcut -R0/400/0/400` of the real ALOS_haiti
  `phase_patch.grd` csh oracle (read-only source, never written).
- `bin_py/tests/test_gmt_xyz2grd_py.py` — 14 tests:
  - 2 C-parity tests (`-ZTLf` and `-ZTLu`) against `gmt xyz2grd` subprocess
    on the real fixture, skip loudly if `gmt` not on PATH.
  - 4 parsing tests (`-R`/`-I` string parsing, including error cases).
  - 2 synthetic core-array tests (reshape/flip orientation, uint8 upcast).
  - 5 error-handling tests (wrong byte count, unsupported dtype,
    non-integral grid dims, degenerate region, non-positive increment —
    all hard `ValueError`, no silent fallback).
  - 1 file-wrapper round-trip test.

## Algorithm (verified against gmt 6.4.0, 2026-06-12)

Round-tripped `gmt grd2xyz phase_small.grd -ZTLf -do0` ->
`gmt xyz2grd unwrap.out -ZTLf -r -R... -I... -Gtmp.grd` on a real
2826x3456 ALOS_haiti `phase_patch.grd` (csh oracle):

1. `-ZTLf` = scanline order, **T**op row first, **L**eft-to-right,
   4-byte **f**loat32 (`-ZTLu` = same order, 1-byte unsigned int =
   `uint8_t`, confirmed by byte-count: 100x50 grid -> 5000-byte
   `conncomp.out`).
2. No `-A` aggregation in `-Z` mode — the table is a dense, pre-ordered
   1-column blob; xyz2grd just reshapes it. Confirmed: feeding one element
   short raises `xyz2grd [ERROR]: Found 4999 records, but 5000 was expected
   (aborting)!` (rc=79) — we mirror this with a hard `ValueError`.
3. Reshape `(ny*nx,)` -> `(ny, nx)` gives row 0 = y_max (top); flip
   vertically for y-ascending storage (matches `gmt_grd_io` convention and
   what `ncdump`/`read_gmt_grd` report).
4. `-r` (pixel reg): `nx = (e-w)/x_inc`, `ny = (n-s)/y_inc` — **no +1**
   (that's only for gridline reg). Coord arrays are cell centers:
   `x[i] = w + (i+0.5)*x_inc`. `node_offset=1`.
5. GMT always stores grid data as float32 regardless of `-Z` input type —
   `-ZTLu` (uint8) data is upcast with no rescaling. Verified: a
   grdmath-derived grid with values in `[1, 4.x)` round-tripped through
   `grd2xyz -ZTLu` -> `xyz2grd -ZTLu -r` truncates to integer float32
   values bit-for-bit identically in both C and the Python port.

## Parity results

Real ALOS_haiti `phase_patch.grd` (2826x3456, pixel-reg, x_inc=4 y_inc=8):

| Path | -ZTLf round trip | -ZTLu round trip | wall time (subprocess vs py) | speedup |
|---|---|---|---|---|
| `gmt xyz2grd` subprocess | byte-id to source (mod. `-do0` NaN->0, an upstream property) | byte-id (after uint8 truncation) | 1.005 s | — |
| `gmt_xyz2grd_py` | byte-id (`np.array_equal(..., equal_nan=True)` True) | byte-id | 0.098 s | **10.2x** |

`x`/`y` coordinate arrays (`node_offset=1`, pixel centers) byte-identical
via `np.testing.assert_array_equal`.

100x400 fixture (`bin_py/tests/data/xyz2grd_phase_small.grd`): both
`-ZTLf` and `-ZTLu` parity tests pass in `bin_py/tests/test_gmt_xyz2grd_py.py`.

End-to-end wrapper smoke (gate OFF vs gate ON, same `unwrap.out`/
`conncomp.out` derived from the fixture): both paths produce
`np.array_equal(..., equal_nan=True) == True` grids with identical
coordinate arrays.

## What's NOT done (deliberately out of scope per mission brief)

- Call site #2 (`proj_ll2ra`/`proj_ra2ll`/`proj_ra2ll_lib.py`, binary
  3-column xyz `-fg -bi3f`, true gridding/binning via `-A` mean-merge) —
  algorithmically different code path in `xyz2grd.c` (the non-`-Z` table
  reader + per-node averaging loop). Not started.
- Call site #3 (`landmask`, `calc_look_vector`, text-mode `-Gout.grd` from
  awk/pipe output) — lower priority, smaller grids. Not started.
- `-Z` flags other than `TL` (e.g. `BL`/`TR`/`BR`, periodic `x`/`y`
  modifiers, byte-swap `w`, header-skip `s<n>`) — no caller uses these.
- Gridline registration (no `-r`) — both wired call sites always pass
  `-r`.

## Wire-in status

`GMTSAR_XYZ2GRD_PY` default **OFF** (subprocess fallback, byte-identical to
pre-mission behaviour including `gmtsar_lib.run()`'s non-fatal
WARN-on-nonzero-rc). A follow-up smoke-test mission should run a case that
exercises the snaphu unwrap path (e.g. `ALOS_haiti`) with
`GMTSAR_XYZ2GRD_PY=1` end-to-end through the full sweep, confirm no
regression, then flip the default ON per the standing pattern (grdsample,
grdcut precedent).

## Files touched

- `gmtsar/python/utils/gmt_xyz2grd_py.py` (new)
- `gmtsar/python/utils/xyz2grd_wrapper.py` (new)
- `gmtsar/python/utils/snaphu.py` (2 call sites wired, +1 import)
- `gmtsar/python/bin_py/tests/test_gmt_xyz2grd_py.py` (new, 14 tests)
- `gmtsar/python/bin_py/tests/data/xyz2grd_phase_small.grd` (new fixture)
- `gmtsar/python/AUDIT_xyz2grd_mira71.md` (this file)
