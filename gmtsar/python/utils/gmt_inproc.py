"""gmt_inproc — Tier-1 in-process replacements for cheap `gmt` subprocesses.

Targets the easy numpy/xarray drop-ins from PLAN.md section 9 (Tier 1):
`gmt grd2xyz -s`, `gmt gmtconvert -bi/-bo -o`. No numba, no GPU; just
numpy + netCDF4 doing what GMT does on the side.

Bit-exactness vs the `gmt` CLI is a non-negotiable contract here. Each
helper has a parity test in `bin_py/tests/test_gmt_inproc.py` that diffs
helper output against `subprocess.run('gmt …')` on a real RS2 grid.

What this module does NOT do
----------------------------
- It does NOT write `.grd` files via xarray. That round-trip produces a
  netCDF flavor downstream `gmt` modules reject ("grid files not of same
  size"), as documented in `utils_pygmt/gmt_compat.py::grdmath`. Helpers
  that consume `.grd` and produce non-grd output (binary streams, numpy
  arrays) are safe; helpers that produce `.grd` are deferred until a
  GMT-compatible netCDF writer lands.
- It does NOT replace `gmt grdmath` operations on `.grd` files for the
  same reason. The Tier-1 list in PLAN.md §9 originally included
  grdmath FLIPUD / MUL / ADD; those have to stay on the `clib.Session`
  fast path (see gmt_compat.grdmath) until the writer is fixed.
- It does NOT replace `gmt grdcut` (produces `.grd`).
- It does NOT replace `gmt xyz2grd` (produces `.grd`).

Wired-in sites
--------------
- `utils/dem2topo_ra`, lines 123 + 169 (the `gmt gmtconvert -o0,1,2 -bi5d
  -bo3d` step in the `trans.dat → temp.rat` pipe). The downstream
  consumer is `gmt blockmedian -bi3d`, which reads a pure binary
  stream — no `.grd` involved.

Behind `GMTSAR_GMT_INPROC=0` every helper falls through to the original
`gmt` subprocess for A/B regression. Default ON.

Mira-discipline notes
---------------------
- `gmt grd2xyz` walks the grid in row-major top-down order: starting from
  `(x_min, y_max)`, sweeping x ascending then row by row down. Within a
  row x is `x_min + j*x_inc`; row y is `y_max - i*y_inc`. The y_inc here
  is `(y_max - y_min) / (n_rows - 1)` for gridline-registered grids,
  NOT the rounded value printed by `grdinfo`. We MUST recompute it
  internally — the file-stored `lat` coordinate variable agrees on the
  endpoints but disagrees with gmt's iteration at 1 ULP for ~1% of rows
  (cumulative roundoff).
- `-s` skips rows where z is NaN (gmtsar's standard "strip no-data" mode).
- z is promoted from float32 (file storage) to float64 (gmt's `-bo3d`
  format) by a direct cast; numpy float32 → float64 is bit-exact in
  the sense that the float32 representable value lands on the unique
  representable float64.
"""
from __future__ import annotations

import mmap
import os
import sys
from typing import Sequence

import numpy as np


def _advise_sequential(arr):
    """Hint the kernel that this memmap will be read sequentially.

    Mira #35 / #37: under NFS, np.memmap default access is per-4 KB-page
    demand-fault, which triggers a separate NFS RPC for each page.
    MADV_SEQUENTIAL tells the kernel to read-ahead in larger chunks.
    Linux-only; falls back silently on macOS/BSD.
    """
    try:
        m = arr.base
        while m is not None and not isinstance(m, mmap.mmap):
            m = getattr(m, "base", None)
        if m is None:
            return
        madvise = getattr(m, "madvise", None)
        advice = getattr(mmap, "MADV_SEQUENTIAL", None)
        if madvise is None or advice is None:
            return
        madvise(advice)
    except (AttributeError, OSError, ValueError):
        pass

try:
    import netCDF4 as _nc4  # type: ignore
    _HAVE_NETCDF4 = True
except ImportError:
    _nc4 = None  # type: ignore
    _HAVE_NETCDF4 = False


def _inproc_enabled() -> bool:
    """Master switch. `GMTSAR_GMT_INPROC=0` disables every helper and
    forces the subprocess fallback. Default ON."""
    return os.environ.get("GMTSAR_GMT_INPROC", "1") != "0"


# ---------------------------------------------------------------------------
# grd2xyz -s -bo3d
# ---------------------------------------------------------------------------

def grd2xyz_skip_nan(grd_path: str, dtype: np.dtype = np.float64) -> np.ndarray:
    """In-process replacement for `gmt grd2xyz <grd_path> -s -bo3d`.

    Returns a contiguous `(N, 3)` float64 numpy array `[x, y, z]` per
    non-NaN pixel, in the exact byte order `gmt grd2xyz` would emit:
    rows from `y_max` down to `y_min`, within each row `x_min → x_max`.
    `.tobytes()` on the returned array is bit-identical to
    `gmt grd2xyz -s -bo3d` stdout (verified on RS2 corr.grd and
    Hawaii dem.grd in test_gmt_inproc.py).

    Why this is safe to call: no .grd file is produced; the caller
    consumes a numpy array (or writes raw binary to a stream that
    `gmt blockmedian -bi3d` will read).
    """
    if not _HAVE_NETCDF4:
        raise RuntimeError(
            "grd2xyz_skip_nan requires netCDF4. Install via "
            "`pip install netCDF4` or fall through to subprocess by "
            "setting GMTSAR_GMT_INPROC=0."
        )
    with _nc4.Dataset(grd_path, "r") as ds:
        z = ds.variables["z"][:]
        # Figure out which coord vars to use. GMT writes either
        # (lat, lon) for geographic grids or (y, x) for Cartesian.
        if "lon" in ds.variables and "lat" in ds.variables:
            xv = ds.variables["lon"][:].data
            yv = ds.variables["lat"][:].data
        elif "x" in ds.variables and "y" in ds.variables:
            xv = ds.variables["x"][:].data
            yv = ds.variables["y"][:].data
        else:
            raise ValueError(
                f"{grd_path}: cannot find (lon,lat) or (x,y) coord vars "
                f"(have {list(ds.variables.keys())})"
            )
    # Convert masked array → plain float array if needed; preserve NaN
    if isinstance(z, np.ma.MaskedArray):
        z = np.ma.filled(z, np.nan)
    z = np.asarray(z, dtype=np.float64)
    ny, nx = z.shape

    # gmt iterates top-down: row 0 at y_max, row ny-1 at y_min.
    # y[i] = y_max - i * y_inc, with y_inc = (y_max - y_min) / (ny - 1).
    # Use the endpoints of the file's stored coord arrays (these match
    # `grdinfo` y_min/y_max exactly; the rounding lives only in the
    # interior of the coord array).
    y_min = float(yv[0])
    y_max = float(yv[-1])
    x_min = float(xv[0])
    x_max = float(xv[-1])
    # Gridline-registered: y_inc = (y_max - y_min) / (ny - 1).
    # (Pixel-registered uses (max-min)/n; we don't see pixel-registered
    # grids in the dem2topo_ra / geocode pipelines — they're all
    # gridline-registered. Document and defer.)
    if ny > 1:
        y_inc = (y_max - y_min) / (ny - 1)
    else:
        y_inc = 0.0
    if nx > 1:
        x_inc = (x_max - x_min) / (nx - 1)
    else:
        x_inc = 0.0

    # Top-down y array, x array unchanged.
    y_td = y_max - np.arange(ny, dtype=np.float64) * y_inc
    x_lr = x_min + np.arange(nx, dtype=np.float64) * x_inc

    # Reverse z rows so row 0 of z_td corresponds to y_max.
    # xarray/netCDF4 store rows with y ascending → z[0] is at y_min.
    # If y is already descending (rare in gmtsar grids), don't flip.
    if yv[0] < yv[-1]:
        z_td = z[::-1, :]
    else:
        z_td = z
        # The y_min/y_max were taken from yv[0]/yv[-1]; if descending
        # those need to be swapped so y_max is at the top of z_td.
        y_min, y_max = y_max, y_min
        y_td = y_max - np.arange(ny, dtype=np.float64) * y_inc

    # Tile coordinates: xx broadcasts a row of x_lr, yy broadcasts y_td col-vec
    xx = np.broadcast_to(x_lr, (ny, nx))
    yy = np.broadcast_to(y_td[:, None], (ny, nx))

    # Stack and reshape: (ny, nx, 3) → (ny*nx, 3). Row-major flattening
    # in numpy walks rows first (axis 0) — same as gmt's top-down row
    # iteration. Within a row, x_lr scans low→high.
    xyz = np.stack([xx, yy, z_td], axis=-1).reshape(-1, 3)

    # -s: drop rows with NaN z. Use a boolean mask so we keep contiguity.
    mask = ~np.isnan(xyz[:, 2])
    out = np.ascontiguousarray(xyz[mask], dtype=dtype)
    return out


def grd2xyz_skip_nan_to_file(grd_path: str, out_path: str) -> int:
    """Same as `grd2xyz_skip_nan` but writes the result to a raw binary
    file, byte-identical to `gmt grd2xyz <grd> -s -bo3d > <out>`. Returns
    the byte count written."""
    xyz = grd2xyz_skip_nan(grd_path, dtype=np.float64)
    xyz.tofile(out_path)
    return xyz.nbytes


# ---------------------------------------------------------------------------
# gmtconvert -bi{n}d -bo{m}d -o{cols}
# ---------------------------------------------------------------------------

def gmtconvert_select_cols_bin(in_path: str, ncol_in: int,
                                cols: Sequence[int], out_path: str) -> int:
    """In-process replacement for the specific `gmt gmtconvert` invocation

        gmt gmtconvert <in_path> -o{c0},{c1},... -bi{ncol_in}d -bo{N}d > out

    where `cols = [c0, c1, ...]` (0-based, same convention as gmtconvert
    `-o`). Reads `ncol_in`-double binary records, slices the requested
    columns in order, writes `len(cols)`-double binary. Returns byte
    count written.

    Used in `utils/dem2topo_ra` for the `trans.dat → blockmedian` pipe:
        gmtconvert_select_cols_bin("trans.dat", 5, [0,1,2], "temp_xyz.bin")
    which previously was `gmt gmtconvert trans.dat -o0,1,2 -bi5d -bo3d`.

    Bit-parity: gmtconvert with `-bi{n}d -bo{m}d -o{cols}` does
    column-select on float64 records. No arithmetic, no precision loss.
    A pure numpy memmap + fancy index produces the exact same bytes
    (verified in test_gmt_inproc.py against RS2 trans.dat).
    """
    if not cols:
        raise ValueError("gmtconvert_select_cols_bin: cols must be non-empty")
    cols_arr = np.asarray(cols, dtype=np.intp)
    if (cols_arr < 0).any() or (cols_arr >= ncol_in).any():
        raise ValueError(
            f"gmtconvert_select_cols_bin: cols={list(cols)} out of range "
            f"[0, {ncol_in})"
        )

    sz = os.path.getsize(in_path)
    if sz % (ncol_in * 8) != 0:
        raise ValueError(
            f"gmtconvert_select_cols_bin: {in_path} size {sz} is not a "
            f"multiple of ncol_in*8 = {ncol_in*8}; check ncol_in / dtype."
        )
    n_rows = sz // (ncol_in * 8)

    # Memmap for big files; sliced via fancy index → contiguous copy
    # we then write out. Doing it column-by-column would scatter reads;
    # the simplest fast path is row-stride mmap → index columns.
    in_mm = np.memmap(in_path, dtype=np.float64, mode="r",
                      shape=(n_rows, ncol_in))
    _advise_sequential(in_mm)  # Mira #37: avoid NFS per-page fault storms
    out = np.ascontiguousarray(in_mm[:, cols_arr])
    out.tofile(out_path)
    return out.nbytes


# ---------------------------------------------------------------------------
# Module diagnostics
# ---------------------------------------------------------------------------

def _selftest() -> None:
    """Smoke test: import + check netCDF4 availability."""
    print(f"gmt_inproc: GMTSAR_GMT_INPROC={'on' if _inproc_enabled() else 'off'}")
    print(f"gmt_inproc: netCDF4 available: {_HAVE_NETCDF4}")
    if not _HAVE_NETCDF4:
        print("gmt_inproc: WARN: netCDF4 missing — grd2xyz_skip_nan will fail",
              file=sys.stderr)


if __name__ == "__main__":
    _selftest()
