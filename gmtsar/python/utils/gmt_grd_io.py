"""gmt_grd_io — write GMT-compatible netCDF `.grd` files in pure Python.

The Tier-1 GMT-port roadmap in PLAN.md §9 is blocked on a single thing:
xarray's default `to_netcdf()` writer produces a netCDF file that **GMT 6
can technically open** but with degraded behavior:

    /tmp/xarray.grd: v_min: 0 v_max: 0  name: z

(`grdinfo` reports zeros for the data range because the `actual_range`
attribute is missing — and `grdcut` then emits warnings about misaligned
boundaries because no `node_offset` attribute pins the registration.)
For some downstream chains the missing attributes are tolerated;
for grid arithmetic that propagates `actual_range` and for any module
that distinguishes pixel-vs-gridline registration (`grdcut`, `grdsample`,
`grdpaste`) the missing attributes cause **silent wrong-region cuts**
and "grid files not of same size" failures.

The canonical GMT netCDF flavor (as written by `gmt grdmath`, `gmt
xyz2grd`, `gmt grdcut`, etc., and observed via `ncdump -h` on real GMT
output) is:

    Conventions       = "CF-1.7"            (global)
    title             = string              (global, may be empty)
    history           = string              (global, recommended)
    description       = string              (global, may be empty)
    GMT_version       = "6.4.0 [64-bit]"    (global)
    node_offset       = 1                   (global, **ONLY for pixel reg**)

Coordinate variables (`x`, `y` for Cartesian; `lon`, `lat` for geographic):
    long_name         = "x" / "y" / "longitude" / "latitude"
    units             = "degrees_east" / "degrees_north"  (geographic only)
    axis              = "X" / "Y"           (Cartesian; optional but written
                                             by GMT 6 for geographic too)
    actual_range      = [min, max]          (required for full grdinfo)

Data variable (`z`):
    long_name         = "z"
    _FillValue        = NaNf                (float32 NaN, hex 0x7fc00000)
    actual_range      = [min, max]          (skipping NaNs)

Two registration models:

  - **Gridline** (default): coord values land ON the grid nodes; for an
    N-cell grid you have N coord values, the first at `x_min`, the last
    at `x_max`. Total extent = (N-1) * x_inc.
  - **Pixel** (also "cell-centered"): coord values sit at CELL CENTERS;
    for an N-cell grid the first cell-center is at `x_min + x_inc/2`,
    the last at `x_max - x_inc/2`. Total extent = N * x_inc.
    Pixel-registered files MUST carry the global `node_offset = 1`
    attribute; otherwise GMT treats them as gridline and the half-cell
    edge shift propagates into every downstream module.

This writer:

  - Uses `netCDF4.Dataset` directly (not xarray) for low-level attribute
    control. xarray writes through netCDF4 but adds its own metadata
    cruft (`_FillValue=NaN` on coords, `_Netcdf4Coordinates`,
    `_CoordSysBuilder`) that GMT's nf-reader sometimes mis-categorizes.
  - Produces a NETCDF4_CLASSIC file by default (compatible with the
    NETCDF3 "classic" model GMT 4/5/6 all read).
  - Writes coordinate vars as float64, data var as float32 — this
    matches GMT's `nf` format ("netCDF, 32-bit float"), which is the
    only format `gmt grdmath ... = out.grd` emits.

Verified downstream (see `bin_py/tests/test_gmt_grd_io.py`):

    gmt grdinfo               (full data range + registration reported)
    gmt grdmath A 2 MUL = B   (preserves attributes; B is well-formed)
    gmt grdmath A B ADD = C   (cross-file arithmetic; sizes match)
    gmt grdcut A -R<sub>      (pixel-registered subset has aligned edges)
    gmt xyz2grd ... -G        (round-trip read → xyz → grd is bit-clean)
    gmt grdtrack ... -G       (sampling at coords agrees with numpy index)

Anti-charter (what this writer does NOT try to do):

  - Does NOT emit netCDF-4 chunked/deflated output. GMT 6 writes chunked
    output for grdmath; classic-format output is just as readable, and
    the chunk-level optimization is irrelevant for typical GMTSAR grid
    sizes (1-100 MB).
  - Does NOT preserve byte-identical bytes vs `gmt grdmath A FLIPUD = B`.
    That requires matching GMT's exact internal write order, padding,
    and `actual_range` recomputation precision. The contract is
    "GMT-readable with full attribute support", not "byte-equal to GMT".
"""
from __future__ import annotations

import os
import sys
import time
from typing import Optional, Sequence, Tuple

import numpy as np

try:
    import netCDF4 as _nc4  # type: ignore
    _HAVE_NETCDF4 = True
except ImportError:
    _nc4 = None  # type: ignore
    _HAVE_NETCDF4 = False


# Version-string tagged into every file we write. Downstream `grdinfo`
# reports this verbatim — useful when triaging "is this an xarray-flavor
# grd or a writer-flavor grd?"
_WRITER_VERSION = "gmtsar-py gmt_grd_io 1.0"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def write_gmt_grd(
    grd_path: str,
    data: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    *,
    node_offset: int = 0,
    geographic: bool = False,
    title: str = "",
    history: str = "",
    description: str = "",
    z_name: str = "z",
    fill_value: float = np.nan,
) -> None:
    """Write a netCDF `.grd` file in the canonical GMT flavor.

    Parameters
    ----------
    grd_path :
        Output path. Overwrites if it exists.
    data : 2-D array, shape (ny, nx)
        Grid values, in numpy "y ascending" orientation. Row `data[0, :]`
        corresponds to `y = y[0]` (the smallest y); row `data[-1, :]`
        corresponds to `y[-1]` (the largest y). This is the same layout
        xarray uses and the layout `nc.Dataset.variables["z"][:]` returns
        when reading a GMT-written file.
        Will be cast to `float32` (GMT's `nf` format) on write.
    x, y : 1-D arrays
        Coordinate values along each axis. Must be strictly monotonically
        ascending and uniformly spaced (constant `x_inc`, `y_inc`); the
        writer asserts this. Length must match `data.shape[1]` and
        `data.shape[0]` respectively.
    node_offset :
        0 = gridline-registered (coord values are at grid nodes; default).
        1 = pixel-registered (coord values are at cell centers; sets the
            global `node_offset = 1` attribute required by GMT).
    geographic :
        True if the grid is in lon/lat. Names the coord vars `lon`/`lat`
        and tags them with CF `units = "degrees_east"` / `"degrees_north"`
        so `gmt grdinfo` reports "Geographic grid". False (default) names
        them `x`/`y` and produces a Cartesian grid.
    title, history, description :
        Free-form metadata. Written to the global attrs of the same name.
        `history` should typically describe the command that produced
        the file, GMT-style:  "gmt grdmath A B ADD = out.grd".
    z_name :
        Name of the data variable. Default `"z"` (GMT canonical).
    fill_value :
        Value to mark missing data with. Default `NaN`. GMT writes
        `_FillValue = NaNf` (32-bit NaN, hex `0x7fc00000`) unconditionally;
        we follow suit unless `fill_value` is overridden.

    Notes
    -----
    The writer is a drop-in replacement for what `gmt grdmath ... = out.grd`
    or `gmt xyz2grd ... -Gout.grd` would have produced, in the sense that
    downstream `gmt grdcut`, `gmt grdmath`, `gmt grdtrack`, etc. accept the
    output with the same metadata they accept from native-GMT files.
    """
    if not _HAVE_NETCDF4:
        raise RuntimeError(
            "write_gmt_grd requires netCDF4. Install via `pip install netCDF4`."
        )

    # ----- validate shapes
    data = np.asarray(data)
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    if data.ndim != 2:
        raise ValueError(f"data must be 2-D, got shape {data.shape}")
    ny, nx = data.shape
    if x.shape != (nx,):
        raise ValueError(f"x must have length nx={nx}, got {x.shape}")
    if y.shape != (ny,):
        raise ValueError(f"y must have length ny={ny}, got {y.shape}")
    if node_offset not in (0, 1):
        raise ValueError(f"node_offset must be 0 or 1, got {node_offset}")

    # ----- validate monotonic + uniform spacing
    # (GMT itself tolerates very small non-uniformity, but emits warnings;
    #  catch the most common porter bug — passing pixel-center coords for
    #  a gridline-registered grid — explicitly here.)
    if nx > 1:
        dx = np.diff(x)
        if (dx <= 0).any():
            raise ValueError("x must be strictly monotonically ascending")
        if not np.allclose(dx, dx[0], rtol=1e-6, atol=0):
            raise ValueError(
                f"x is not uniformly spaced (range of diffs: "
                f"{dx.min():.6g} to {dx.max():.6g}); GMT requires "
                f"constant x_inc"
            )
    if ny > 1:
        dy = np.diff(y)
        if (dy <= 0).any():
            raise ValueError("y must be strictly monotonically ascending")
        if not np.allclose(dy, dy[0], rtol=1e-6, atol=0):
            raise ValueError(
                f"y is not uniformly spaced (range of diffs: "
                f"{dy.min():.6g} to {dy.max():.6g}); GMT requires "
                f"constant y_inc"
            )

    # ----- cast data to float32, propagate fill_value to NaN-as-float32
    z32 = np.asarray(data, dtype=np.float32)
    if not np.isnan(fill_value):
        # caller wants a non-NaN sentinel; replace it with NaN in the
        # float32 array (GMT always writes _FillValue=NaNf for the nf format)
        z32 = np.where(z32 == np.float32(fill_value), np.float32(np.nan), z32)

    # ----- compute actual_range over valid (non-NaN) entries
    if np.isnan(z32).all():
        z_min = z_max = 0.0
    else:
        z_min = float(np.nanmin(z32))
        z_max = float(np.nanmax(z32))

    # ----- choose coord var names per CF + GMT convention
    if geographic:
        xname, yname = "lon", "lat"
        x_long, y_long = "longitude", "latitude"
        x_units, y_units = "degrees_east", "degrees_north"
    else:
        xname, yname = "x", "y"
        x_long, y_long = "x", "y"
        x_units = y_units = None

    # ----- write
    # Remove the file first so netCDF4 doesn't try a partial overwrite
    if os.path.exists(grd_path):
        os.remove(grd_path)

    # NETCDF4_CLASSIC: classic data model (no groups, no compound types,
    # no unlimited dims beyond one) on top of HDF5. Readable by every GMT
    # version since GMT 5, and by `ncdump`, `xarray.open_dataset`, etc.
    with _nc4.Dataset(grd_path, "w", format="NETCDF4_CLASSIC") as ds:
        ds.createDimension(xname, nx)
        ds.createDimension(yname, ny)

        # --- x / lon coord var
        xv = ds.createVariable(xname, "f8", (xname,))
        xv.long_name = x_long
        if x_units is not None:
            xv.units = x_units
        xv.actual_range = np.array([float(x[0]), float(x[-1])], dtype=np.float64)
        if not geographic:
            xv.axis = "X"
        xv[:] = x

        # --- y / lat coord var
        yv = ds.createVariable(yname, "f8", (yname,))
        yv.long_name = y_long
        if y_units is not None:
            yv.units = y_units
        yv.actual_range = np.array([float(y[0]), float(y[-1])], dtype=np.float64)
        if not geographic:
            yv.axis = "Y"
        yv[:] = y

        # --- z data var
        # Pass _FillValue at creation time (netCDF4 requires this — it
        # can't be set after the variable exists in classic mode).
        zv = ds.createVariable(
            z_name, "f4", (yname, xname),
            fill_value=np.float32(np.nan),
        )
        zv.long_name = z_name
        zv.actual_range = np.array([z_min, z_max], dtype=np.float64)
        zv[:, :] = z32

        # --- global attrs (order matches GMT 6 output)
        ds.Conventions = "CF-1.7"
        ds.title = title
        ds.history = history
        ds.description = description
        ds.GMT_version = _WRITER_VERSION
        if node_offset == 1:
            # GMT's pixel-registration flag. MUST be a 32-bit int per the
            # CDM spec — use np.int32 explicitly so netCDF4 doesn't
            # promote to int64 (which GMT's reader rejects).
            ds.node_offset = np.int32(1)


# ---------------------------------------------------------------------------
# Convenience helpers (built on top of write_gmt_grd)
# ---------------------------------------------------------------------------

def write_gmt_grd_from_increments(
    grd_path: str,
    data: np.ndarray,
    *,
    x_min: float,
    y_min: float,
    x_inc: float,
    y_inc: float,
    node_offset: int = 0,
    geographic: bool = False,
    **kwargs,
) -> None:
    """Wrapper: build `x`/`y` coord arrays from increments then call
    `write_gmt_grd`.

    For `node_offset = 0` (gridline): x[i] = x_min + i * x_inc, for i in [0, nx).
        The last coord lands exactly at `x_min + (nx-1)*x_inc` = `x_max`.

    For `node_offset = 1` (pixel): the coord array is shifted to cell
        centers: `x[i] = x_min + (i + 0.5) * x_inc`.

    Useful when the caller has `(x_min, y_min, x_inc, y_inc)` from a
    config / PRM file rather than precomputed coord arrays.
    """
    data = np.asarray(data)
    ny, nx = data.shape
    if node_offset == 0:
        x = x_min + np.arange(nx, dtype=np.float64) * x_inc
        y = y_min + np.arange(ny, dtype=np.float64) * y_inc
    else:
        # pixel-centered: first cell center at x_min + inc/2
        x = x_min + (np.arange(nx, dtype=np.float64) + 0.5) * x_inc
        y = y_min + (np.arange(ny, dtype=np.float64) + 0.5) * y_inc
    write_gmt_grd(
        grd_path, data, x, y,
        node_offset=node_offset, geographic=geographic, **kwargs,
    )


def read_gmt_grd(grd_path: str) -> Tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    """Read a `.grd` file and return `(data, x, y, info)`.

    `data` is a float32 2-D array in "y ascending" orientation
    (row 0 → `y_min`, row -1 → `y_max`). Masked values (where
    `_FillValue=NaN`) come back as NaN.

    `info` is a dict with `node_offset`, `geographic`, `title`,
    `history`, `description`, `GMT_version`, `x_inc`, `y_inc`,
    `actual_range_z`. Useful for round-tripping a file you wrote
    via `write_gmt_grd` and re-asserting the metadata.

    NOTE: this is intentionally minimal — it's a peer of
    `write_gmt_grd`, not a general GMT-grd reader. For full reading
    use `xarray.open_dataset` or `netCDF4.Dataset` directly.
    """
    if not _HAVE_NETCDF4:
        raise RuntimeError("read_gmt_grd requires netCDF4.")
    with _nc4.Dataset(grd_path, "r") as ds:
        if "x" in ds.variables and "y" in ds.variables:
            xname, yname = "x", "y"
            geographic = False
        elif "lon" in ds.variables and "lat" in ds.variables:
            xname, yname = "lon", "lat"
            geographic = True
        else:
            raise ValueError(
                f"{grd_path}: no (x,y) or (lon,lat) coord vars found "
                f"(have {list(ds.variables.keys())})"
            )
        x = np.asarray(ds.variables[xname][:], dtype=np.float64)
        y = np.asarray(ds.variables[yname][:], dtype=np.float64)
        z = ds.variables["z"][:]
        if isinstance(z, np.ma.MaskedArray):
            z = np.ma.filled(z, np.nan).astype(np.float32)
        else:
            z = np.asarray(z, dtype=np.float32)

        info = {
            "geographic": geographic,
            "node_offset": int(getattr(ds, "node_offset", 0)),
            "title": getattr(ds, "title", ""),
            "history": getattr(ds, "history", ""),
            "description": getattr(ds, "description", ""),
            "GMT_version": getattr(ds, "GMT_version", ""),
            "x_inc": float(x[1] - x[0]) if len(x) > 1 else 0.0,
            "y_inc": float(y[1] - y[0]) if len(y) > 1 else 0.0,
            "actual_range_z": (
                float(np.nanmin(z)) if not np.isnan(z).all() else 0.0,
                float(np.nanmax(z)) if not np.isnan(z).all() else 0.0,
            ),
        }
        return z, x, y, info


# ---------------------------------------------------------------------------
# Module diagnostics
# ---------------------------------------------------------------------------

def _selftest() -> None:
    print(f"gmt_grd_io: netCDF4 available: {_HAVE_NETCDF4}")
    if not _HAVE_NETCDF4:
        print("gmt_grd_io: WARN: netCDF4 missing — write_gmt_grd will fail",
              file=sys.stderr)
        return
    import tempfile
    tmp = tempfile.NamedTemporaryFile(suffix=".grd", delete=False)
    tmp.close()
    try:
        x = np.arange(10, dtype=np.float64) * 2.0
        y = np.arange(8, dtype=np.float64) * 4.0
        z = (y[:, None] + x[None, :]).astype(np.float32)
        write_gmt_grd(tmp.name, z, x, y, node_offset=1,
                      title="selftest", history="gmt_grd_io._selftest")
        zr, xr, yr, info = read_gmt_grd(tmp.name)
        assert zr.shape == z.shape, f"shape mismatch {zr.shape} != {z.shape}"
        assert np.allclose(zr, z), "data round-trip failed"
        assert np.allclose(xr, x), "x round-trip failed"
        assert np.allclose(yr, y), "y round-trip failed"
        assert info["node_offset"] == 1, "node_offset not preserved"
        print("gmt_grd_io: self-test OK")
    finally:
        os.unlink(tmp.name)


if __name__ == "__main__":
    _selftest()
