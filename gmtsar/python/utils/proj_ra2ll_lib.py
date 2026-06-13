"""proj_ra2ll_lib — fast in-process replacement for the proj_ra2ll subprocess
chain inside geocode.

Bottleneck this targets
-----------------------
The original proj_ra2ll wrapper (utils/proj_ra2ll, mirroring csh/proj_ra2ll.csh)
runs this 5-stage pipeline on EVERY call, once per geocoded *_ll.grd:

    gmt grd2xyz   in.grd  -s -bo3f > rap            # ~0.1-0.5 s
    [gmt surface]  trans.dat -> raln.grd, ralt.grd  # ~1.0 s, one-shot, cached
    gmt grdtrack rap -Graln.grd -Gralt.grd \
        | gmt gmtconvert -o3,4,2 > llp              # ~0.3-0.7 s  <-- per call
    gmt blockmedian llp ... > llpb                  # ~0.06 s
    gmt xyz2grd     llpb -> out.grd                 # ~0.06 s

Inside geocode this gets called 5+ times on grids that all share the same
(range, azimuth) layout. The (lon, lat) lookup is the IDENTICAL math each
time — only the data values change. So we compute (lon, lat) for every
(r, a) pixel ONCE in numpy, then for each output we just glue the data
column in, and let blockmedian+xyz2grd do the heavy lifting they already
do efficiently.

What stays the same (parity-stable)
-----------------------------------
- `gmt surface` for raln.grd / ralt.grd (the (r,a) -> (lon,lat) regressor).
- `gmt blockmedian` + `gmt xyz2grd` to land the final regular grid.
- `m2s.csh` to choose the geographic grid increments.

What's replaced
---------------
- `gmt grd2xyz | -s` (extract non-NaN pixels): pure numpy.
- `gmt grdtrack -nl` (bilinear lookup of raln/ralt at (r,a)): pure numpy
  bilinear, matches GMT's -nl on a regular grid to float32 roundoff
  (verified — see TestProjRa2llBilinearVsGmt).
- `gmt gmtconvert -o3,4,2`: column reordering in numpy.

Mira-discipline notes
---------------------
- Bilinear interp uses (1 - dx)(1 - dy)*a + dx(1 - dy)*b + (1 - dx)dy*c + dx*dy*d
  with float32 throughout (raln.grd is float32 from gmt surface) — matches
  GMT grdtrack -nl on a regular grid.
- We do NOT replace blockmedian or xyz2grd. Reproducing GMT's blockmedian
  binning + median selection bit-faithfully in numpy is a separate ports
  problem; not in scope for this commit.
- The Python proj_ra2ll subprocess CLI (utils/proj_ra2ll) is left unchanged
  for backward compat with any caller that shells out to it directly.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

import numpy as np

try:
    import xarray as xr
except ImportError as e:
    raise ImportError(
        "proj_ra2ll_lib requires xarray. Install via `pip install xarray netCDF4`."
    ) from e


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _read_grd(path: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (z, x, y) for a GMT netCDF grid; x, y as 1-D coord arrays."""
    da = xr.open_dataarray(path, engine="netcdf4")
    z = da.values
    x = da.x.values
    y = da.y.values
    da.close()
    return z, x, y


def _bilinear_lookup(values: np.ndarray, vx: np.ndarray, vy: np.ndarray,
                     qx: np.ndarray, qy: np.ndarray) -> np.ndarray:
    """Vectorised bilinear lookup of `values` (defined on regular grid vx*vy)
    at query points (qx, qy). Points strictly outside the (vx, vy) extent
    are returned as NaN — matching `gmt grdtrack` which DROPS such points
    (caller must filter NaN out before writing llp).

    Mira #9 audit (2026-05-21): previous version clamped out-of-extent
    points to the boundary value, which produced spurious lon/lat output
    when display_amp.grd (no NaN, wider than corr.grd footprint) was
    projected through a raln/ralt grid built from corr.grd's narrower
    non-NaN extent. csh grdtrack drops these points; we now do the same.
    """
    # vx, vy are strictly monotonic increasing (xarray reads sorted).
    x0 = float(vx[0]); dx = float(vx[1] - vx[0])
    y0 = float(vy[0]); dy = float(vy[1] - vy[0])
    nx = vx.size; ny = vy.size
    x_hi = float(vx[-1]); y_hi = float(vy[-1])

    # Do the math in float64 to match GMT grdtrack's internal precision
    # (it stores grid values as float but interpolates in double). Casting
    # only at the end avoids float32 catastrophic cancellation in
    # (1-tx)(1-ty)*v00 + ... when v00 has magnitude ~100 (lon/lat).
    qx64 = qx.astype(np.float64, copy=False)
    qy64 = qy.astype(np.float64, copy=False)

    # Mask out-of-extent queries (gmtrack: drop). Inclusive on both ends.
    in_extent = (qx64 >= x0) & (qx64 <= x_hi) & (qy64 >= y0) & (qy64 <= y_hi)

    # Fractional index into the grid
    fx = (qx64 - x0) / dx
    fy = (qy64 - y0) / dy

    # Clamp to interior; ix, iy are lower-left indices.
    ix = np.clip(np.floor(fx).astype(np.int64), 0, nx - 2)
    iy = np.clip(np.floor(fy).astype(np.int64), 0, ny - 2)
    tx = fx - ix
    ty = fy - iy
    # Clamp t in [0,1] for safety (only matters for borderline within-extent).
    np.clip(tx, 0.0, 1.0, out=tx)
    np.clip(ty, 0.0, 1.0, out=ty)

    # values is shape (ny, nx); promote to float64 for the FMA.
    v = values.astype(np.float64, copy=False)
    v00 = v[iy,     ix    ]
    v10 = v[iy,     ix + 1]
    v01 = v[iy + 1, ix    ]
    v11 = v[iy + 1, ix + 1]

    out = ((1 - tx) * (1 - ty) * v00 +
           tx       * (1 - ty) * v10 +
           (1 - tx) * ty       * v01 +
           tx       * ty       * v11)
    out = np.where(in_extent, out, np.nan)
    return out.astype(np.float32)


def _run_surface_inproc_5col(trans_dat: str, region_str: str, col_z: int,
                              inc_x: float, inc_y: float, tension: float,
                              out_path: str) -> None:
    """In-process replacement for
        gmt surface <trans_dat> -i0,1,<col_z> -bi5d -R... -I -T -G<out>.

    Reads `trans_dat` as 5-column binary float64; uses columns 0 (x),
    1 (y), and `col_z` (z), feeds the scatter into `gmt_surface_py`
    with gridline registration (matches the legacy invocation which
    omits -r), then writes the output via `gmt_grd_io.write_gmt_grd`.
    """
    # Lazy import — pay numba JIT cost only when GMTSAR_SURFACE_INPROC=1.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from gmt_surface_py import gmt_surface_py
    from gmt_grd_io import write_gmt_grd

    # Parse region "-R x0/x1/y0/y1"
    rs = region_str.replace("-R", "").strip()
    parts = rs.split("/")
    if len(parts) != 4:
        raise ValueError(f"bad region '{region_str}' for in-proc surface")
    x0, x1, y0, y1 = (float(p) for p in parts)
    data = np.fromfile(trans_dat, dtype=np.float64)
    if data.size % 5 != 0:
        raise ValueError(f"{trans_dat}: size {data.size} not div by 5 doubles")
    data = data.reshape(-1, 5)
    x = data[:, 0]
    y = data[:, 1]
    z = data[:, col_z]
    grid = gmt_surface_py(
        x, y, z,
        region=(x0, x1, y0, y1),
        inc=(float(inc_x), float(inc_y)),
        tension=float(tension),
        max_iter=2000, tol=1e-4,
        omega=0.5,
        use_multigrid=True,
        pixel_reg=False,
    )
    ny, nx = grid.shape
    x_coord = x0 + np.arange(nx) * float(inc_x)
    y_coord = y0 + np.arange(ny) * float(inc_y)
    write_gmt_grd(out_path, grid, x_coord, y_coord, node_offset=0,
                  history=f"gmt_surface_py (-T{tension}) "
                          f"-I{inc_x}/{inc_y}  (col {col_z})")


def _ensure_raln_ralt(trans_dat: str, region: str, verbose: bool = False) -> None:
    """Run `gmt surface` once to produce raln.grd / ralt.grd if missing.

    In-process gmt_surface_py + write_gmt_grd pair (Mira #41 wire-in),
    DEFAULT ON since v2.1.27.  Both raln (col 3 = lon) and ralt (col 4
    = lat) are computed from the same 5-col trans.dat binary input.
    Set GMTSAR_SURFACE_INPROC=0 to fall back to the `gmt surface`
    subprocess.

    History
    -------
    * Default flipped ON after RS2_SLC_Hawaii path-exercising smoke
      (6/6 py-vs-csh SUCCESS, blessed diff PASS at v2.1.27) confirmed
      the in-proc -I16/32 (anisotropic) call produces parity output.
      Mira #60 (glue vectorization) + Mira #68 (gcd==1 region
      expansion) + Mira #72 (anisotropic benchmark fix, no algorithm
      change needed) closed the remaining gaps.
    """
    Vflag = "-V" if verbose else ""
    inproc = os.environ.get("GMTSAR_SURFACE_INPROC", "1") == "1"
    if not os.path.isfile("raln.grd"):
        if inproc:
            _run_surface_inproc_5col(trans_dat, region, col_z=3,
                                      inc_x=16.0, inc_y=32.0, tension=0.5,
                                      out_path="raln.grd")
        else:
            cmd = f"gmt surface {trans_dat} -i0,1,3 -bi5d {region} -I16/32 -T.50 -Graln.grd {Vflag}"
            subprocess.run(cmd, shell=True, check=False)
    if not os.path.isfile("ralt.grd"):
        if inproc:
            _run_surface_inproc_5col(trans_dat, region, col_z=4,
                                      inc_x=16.0, inc_y=32.0, tension=0.5,
                                      out_path="ralt.grd")
        else:
            cmd = f"gmt surface {trans_dat} -i0,1,4 -bi5d {region} -I16/32 -T.50 -Gralt.grd {Vflag}"
            subprocess.run(cmd, shell=True, check=False)


def _region_from_corr_extent(z, x_coord, y_coord) -> str:
    """Mirror `gmt gmtinfo rap -I16/32 -bi3f` rounding for the data grid.

    rap is the (r, a) coords of NON-NaN data pixels of the current input
    grid (corr.grd, on the first call). `gmt gmtinfo -I16/32` rounds the
    actual min/max DOWN to the nearest multiple of 16 in x (32 in y) for
    the lower bound, and UP for the upper bound.

    Previously we used a synthetic formula `-R0/(nx*x_inc)/0/(ny*y_inc)`
    assuming the grid was fully populated. That broke for any case where
    corr.grd has NaN edges (TSX, ENVI, CSK_SLC, ALOS-1/-2 stripmap, ...):
    csh builds a NARROWER raln/ralt; Python built a WIDER one, so when
    display_amp.grd (no NaN, full coverage) is later projected through
    bilinear lookup it gets ~10-20 extra lon/lat columns that csh drops
    via grdtrack returning NaN outside raln/ralt extent.

    Now we mirror csh exactly: take the actual non-NaN extent of the
    current input grid and apply gmtinfo's -I16/32 rounding.
    Mira #9 audit, 2026-05-21.
    """
    valid = ~np.isnan(z)
    if not valid.any():
        # Degenerate input — fall back to full extent so surface still runs.
        ny, nx = z.shape
        x_inc = float(x_coord[1] - x_coord[0])
        y_inc = float(y_coord[1] - y_coord[0])
        x_min, x_max = 0.0, nx * x_inc
        y_min, y_max = 0.0, ny * y_inc
    else:
        # (R, A) at every non-NaN pixel center
        ys, xs = np.where(valid)
        x_min = float(x_coord[xs.min()])
        x_max = float(x_coord[xs.max()])
        y_min = float(y_coord[ys.min()])
        y_max = float(y_coord[ys.max()])
    # gmt gmtinfo -I16/32: round min DOWN, max UP to nearest 16 / 32.
    x_lo = int(np.floor(x_min / 16.0)) * 16
    x_hi = int(np.ceil(x_max / 16.0)) * 16
    y_lo = int(np.floor(y_min / 32.0)) * 32
    y_hi = int(np.ceil(y_max / 32.0)) * 32
    return f"-R{x_lo}/{x_hi}/{y_lo}/{y_hi}"


def _grid_pixel_centers(x_coord: np.ndarray, y_coord: np.ndarray):
    """Build the per-pixel (r, a) coordinate arrays for a 2-D grid.

    GMT pixel-node registration: x_coord, y_coord ARE the pixel centers
    (gmt grd2xyz emits exactly these). So we just mesh them.
    """
    R, A = np.meshgrid(x_coord, y_coord, indexing="xy")
    return R, A


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def proj_ra2ll_fast(trans_dat: str, in_grd: str, out_grd: str,
                    filter_wavelength: float | None = None,
                    verbose: bool = False,
                    keep_intermediates: bool = False,
                    cache: dict | None = None) -> dict:
    """In-process replacement for `proj_ra2ll trans.dat in.grd out.grd`.

    Pass a `cache` dict (initially `{}`) across multiple calls in the same
    geocoding session to amortise the one-shot setup cost:
      - raln.grd / ralt.grd `gmt surface` build (~1.0 s)
      - reading raln, ralt into numpy (~0.03 s)
      - `m2s.csh` (~0.47 s) + `gmt gmtinfo` (~0.15 s) for the lon/lat
        grid spacing — same for every data file because all data grids
        in a typical geocode pass share the same (r, a) layout, so they
        produce the same (lon, lat) extents within blockmedian-cell
        resolution.

    Returns a dict of per-step wall times for profiling.
    """
    times = {}
    Vflag = "-V" if verbose else ""
    cache = cache if cache is not None else {}

    # ---- 1. read input data grid ----
    t = time.time()
    z, xc, yc = _read_grd(in_grd)
    # nan-mask matches `gmt grd2xyz -s` (skip NaN records)
    valid = ~np.isnan(z)
    R, A = _grid_pixel_centers(xc, yc)
    r_pts = R[valid].astype(np.float32, copy=False)
    a_pts = A[valid].astype(np.float32, copy=False)
    d_pts = z[valid].astype(np.float32, copy=False)
    times["read_grd"] = time.time() - t

    # ---- 2. ensure raln/ralt cache (one-shot per session) ----
    # Region for `gmt surface` must mirror csh's `gmt gmtinfo rap -I16/32 -bi3f`
    # which uses the NON-NaN footprint of the input data grid (corr.grd on the
    # first call). Pass z + coord arrays so the helper can use np.where(~NaN).
    t = time.time()
    region = _region_from_corr_extent(z, xc, yc)
    _ensure_raln_ralt(trans_dat, region, verbose=verbose)
    times["surface_cache"] = time.time() - t

    # ---- 3. bilinear lookup raln/ralt at (r, a) ----
    t = time.time()
    if "raln" not in cache:
        cache["raln"] = _read_grd("raln.grd")
        cache["ralt"] = _read_grd("ralt.grd")
    raln, rln_x, rln_y = cache["raln"]
    ralt, ralt_x, ralt_y = cache["ralt"]
    lon = _bilinear_lookup(raln, rln_x, rln_y, r_pts, a_pts)
    lat = _bilinear_lookup(ralt, ralt_x, ralt_y, r_pts, a_pts)
    times["bilinear_lookup"] = time.time() - t

    # ---- 4. write (lon, lat, data) triplet as binary float32 ----
    # gmt grdtrack drops points outside the raln/ralt extent (returns NaN
    # via _bilinear_lookup, then gmtconvert/blockmedian drop them). Mirror
    # that by filtering NaN lon/lat before writing llp. This matters when
    # the input grid has a wider non-NaN footprint than corr.grd (e.g.,
    # display_amp.grd has zero NaN while corr.grd has NaN at the (r,a)
    # edges for many sensors — Mira #9 audit, 2026-05-21).
    t = time.time()
    finite = np.isfinite(lon) & np.isfinite(lat)
    if not finite.all():
        lon = lon[finite]
        lat = lat[finite]
        d_pts = d_pts[finite]
    llp = np.empty((lon.size, 3), dtype=np.float32)
    llp[:, 0] = lon
    llp[:, 1] = lat
    llp[:, 2] = d_pts
    llp.tofile("llp")
    times["write_llp"] = time.time() - t

    # ---- 5. determine grid pixel spacing (m2s.csh) + bbox ----
    # m2s output (fine_inc, crude_inc) depends only on pix_m and the mean
    # latitude — same for ALL files in a batch, cache & reuse.
    #
    # The bbox R = `gmt gmtinfo -I<crude_inc>` MUST be recomputed per file:
    # different geocoded grids have DIFFERENT non-NaN footprints. corr.grd
    # and phasefilt.grd are full; *_mask.grd are trimmed by the correlation
    # mask; display_amp.grd can be slightly wider. Caching R across files
    # silently produced wrong-bbox PNGs for CSK_RAW / ENVI_SLC / TSX
    # (Mira #8 audit, 2026-05-20) — RS2/NISAR happened to share footprint
    # so the bug stayed hidden. Per-file gmtinfo costs ~0.15 s × 5 files
    # = 0.75 s overhead vs the speedup — well worth correctness.
    t = time.time()
    if "fine_inc" not in cache:
        if filter_wavelength is not None:
            pix_m = filter_wavelength / 4.0
        else:
            import glob as _glob
            filt = _glob.glob("gauss_*")
            if filt:
                pix_m = float(filt[0].split("_")[1]) / 4.0
            else:
                pix_m = 60.0
        incs_line = subprocess.check_output(
            ["m2s.csh", str(pix_m), "llp"], text=True).strip().split()
        cache["fine_inc"], cache["crude_inc"] = incs_line[0], incs_line[1]
    fine_inc = cache["fine_inc"]
    # Per-file bbox — DO NOT cache (see comment above).
    R = subprocess.check_output(
        ["gmt", "gmtinfo", "llp", f"-I{cache['crude_inc']}", "-bi3f"],
        text=True).strip()
    times["m2s_region"] = time.time() - t

    # ---- 6. blockmedian -> xyz2grd (UNCHANGED, parity-stable) ----
    t = time.time()
    subprocess.run(
        f"gmt blockmedian llp {R} -bi3f -bo3f -I{fine_inc} -r {Vflag} > llpb",
        shell=True, check=False)
    subprocess.run(
        f"gmt xyz2grd llpb {R} -I{fine_inc} -r -fg -G{out_grd} -bi3f",
        shell=True, check=False)
    times["blockmedian_xyz2grd"] = time.time() - t

    # ---- 7. cleanup ----
    if not keep_intermediates:
        for f in ("llp", "llpb"):
            try: os.remove(f)
            except FileNotFoundError: pass

    times["total"] = sum(times.values()) - times.get("total", 0)
    return times


__all__ = ["proj_ra2ll_fast"]
