#!/usr/bin/env python3
"""gmt_blockmedian_py — Numba port of `gmt blockmedian -bi3d -bo3d -r`.

Tier-2 entry in the GMT port roadmap. Bins scattered (x, y, z) points
into a regular pixel-registered grid and emits, for each non-empty bin,
the *independent* median of x, median of y, and median of z.

This matches what `gmt blockmedian` writes when invoked the way
`dem2topo_ra` and `geocode` invoke it:

    gmt blockmedian trans.dat -R<x>/<x>/<y>/<y> -I<dx>/<dy> \
                              -bi3d -bo3d -r

Key parity facts established empirically against `gmt blockmedian`
(GMT 6.4.0):

* Output is **median(x), median(y), median(z) per bin**, NOT the bin
  centre. This is the dominant correctness pitfall — `scipy`'s
  `binned_statistic_2d(statistic="median")` returns centres for the
  (x, y) coordinates if you feed it the cell-centre arrays, which is
  why the prior `bin_py/blockmedian_py` differs from GMT.
* Bin index uses **banker rounding** (round half to even):
      i = irint((x - x_min) / x_inc - 0.5)
      j = irint((y - y_min) / y_inc - 0.5)
  via numpy's `rint`, which is round-half-to-even (C99 `irint`).
  Points exactly on an interior bin boundary therefore go to the
  *even-indexed* neighbour, not always left or always right.
* Output rows are in **top-down raster order**: `j` descends from
  `ny - 1` to 0, and within each row `i` ascends from 0 to `nx - 1`.
* Even-count medians use the arithmetic mean of the two middle
  elements (numpy default, matches GMT).
* Region is treated **inclusively**: points with `x_min <= x <= x_max`
  and `y_min <= y <= y_max` are kept. Points outside are silently
  dropped (`gmt blockmedian` does the same).

The Numba kernel only runs the per-bin median, which is the expensive
step. The bin-index computation and the argsort group are pure numpy
and already vectorised.
"""
from __future__ import annotations

from typing import Tuple

import numpy as np

try:
    import numba
    from numba import njit, prange
    _HAVE_NUMBA = True
except ImportError:  # pragma: no cover
    _HAVE_NUMBA = False

    def njit(*args, **kwargs):  # type: ignore
        def deco(f):
            return f
        if args and callable(args[0]):
            return args[0]
        return deco

    def prange(*a, **k):  # type: ignore
        return range(*a, **k)


# ---------------------------------------------------------------------------
# Numba kernel — per-bin median
# ---------------------------------------------------------------------------

@njit(parallel=True, fastmath=False, cache=True)
def _per_bin_median(sorted_x, sorted_y, sorted_z,
                    bin_starts, bin_ends, out_x, out_y, out_z):
    """For each non-empty bin, write median(x), median(y), median(z).

    Inputs:
        sorted_x, sorted_y, sorted_z : 1-D float64 arrays of length N,
            already permuted so all points belonging to the same bin
            occupy a contiguous slice.
        bin_starts, bin_ends : 1-D int64 arrays of length M = number of
            non-empty bins. Slice [start, end) for bin k.
        out_x, out_y, out_z  : 1-D float64 output arrays of length M.

    The median of each slice is computed independently for x, y, z
    using numpy's selection (`np.partition`) — numba supports a sort
    on a local copy and we take the middle (or average of two
    middles for even-length runs).
    """
    M = bin_starts.shape[0]
    for k in prange(M):
        s = bin_starts[k]
        e = bin_ends[k]
        n = e - s
        # Copy each slice to a local buffer and sort in place.
        # This is allocation per bin, which is fine because numba/numpy
        # arenas reuse small buffers and bins are typically small
        # (median size ~9M points / ~5e4 bins = ~180 pts/bin).
        bx = np.empty(n, dtype=np.float64)
        by = np.empty(n, dtype=np.float64)
        bz = np.empty(n, dtype=np.float64)
        for t in range(n):
            bx[t] = sorted_x[s + t]
            by[t] = sorted_y[s + t]
            bz[t] = sorted_z[s + t]
        bx.sort()
        by.sort()
        bz.sort()
        if n & 1:
            mid = n // 2
            out_x[k] = bx[mid]
            out_y[k] = by[mid]
            out_z[k] = bz[mid]
        else:
            lo = (n // 2) - 1
            hi = n // 2
            out_x[k] = 0.5 * (bx[lo] + bx[hi])
            out_y[k] = 0.5 * (by[lo] + by[hi])
            out_z[k] = 0.5 * (bz[lo] + bz[hi])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def blockmedian(xyz: np.ndarray,
                region: Tuple[float, float, float, float],
                inc: Tuple[float, float],
                pixel_reg: bool = True) -> np.ndarray:
    """Bin (x, y, z) points to a grid and return median per non-empty bin.

    Parameters
    ----------
    xyz : ndarray (N, 3) float64
        Scattered points.
    region : (x_min, x_max, y_min, y_max)
        Grid extent. Points outside the closed region are dropped.
    inc : (x_inc, y_inc)
        Grid spacing.
    pixel_reg : bool
        True = pixel registration (`-r` in GMT); False = gridline
        registration. Only pixel registration is byte-faithful with
        `gmt blockmedian -r` and is what `dem2topo_ra` uses.

    Returns
    -------
    out : ndarray (M, 3) float64
        For each non-empty bin: (median(x), median(y), median(z)).
        Rows are in top-down raster order (`j` descending, then `i`
        ascending), matching `gmt blockmedian -bi3d -bo3d -r` byte
        layout.
    """
    if xyz.ndim != 2 or xyz.shape[1] != 3:
        raise ValueError(f"xyz must be (N, 3), got {xyz.shape}")
    xyz = np.ascontiguousarray(xyz, dtype=np.float64)

    x_min, x_max, y_min, y_max = (float(v) for v in region)
    x_inc, y_inc = (float(v) for v in inc)

    # GMT chooses nx = irint((x_max - x_min) / x_inc) (banker rounding),
    # then *adjusts* x_inc to (x_max - x_min) / nx so the grid exactly
    # fills the region. This is the "(x_max-x_min) must equal (NX +
    # eps)*x_inc" rule from gmtapi_init_grdheader. Match it byte-for-byte.
    nx = int(np.rint((x_max - x_min) / x_inc))
    ny = int(np.rint((y_max - y_min) / y_inc))
    if nx <= 0 or ny <= 0:
        raise ValueError(f"derived grid has non-positive size: nx={nx}, ny={ny}")
    x_inc = (x_max - x_min) / nx
    y_inc = (y_max - y_min) / ny

    x = xyz[:, 0]
    y = xyz[:, 1]
    z = xyz[:, 2]

    # Inclusive region filter (matches GMT)
    in_x = (x >= x_min) & (x <= x_max)
    in_y = (y >= y_min) & (y <= y_max)
    keep = in_x & in_y
    if not keep.any():
        return np.zeros((0, 3), dtype=np.float64)

    x = x[keep]
    y = y[keep]
    z = z[keep]

    # GMT pixel-reg index formula:  irint((p - p_min) / p_inc - 0.5)
    # numpy.rint is round-half-to-even (C99 irint).
    if pixel_reg:
        i = np.rint((x - x_min) / x_inc - 0.5).astype(np.int64)
        j = np.rint((y - y_min) / y_inc - 0.5).astype(np.int64)
    else:
        # Gridline registration: nearest node (no -0.5 shift).
        # Kept for completeness; not the dem2topo_ra path.
        i = np.rint((x - x_min) / x_inc).astype(np.int64)
        j = np.rint((y - y_min) / y_inc).astype(np.int64)

    # Clamp indices that fell exactly on the upper boundary after
    # banker rounding (e.g. (x_max - x_min)/x_inc - 0.5 = nx-0.5 → nx).
    # Without this, points at the extreme upper edge could land in a
    # phantom (nx, *) bin. GMT clamps these into the last cell.
    np.clip(i, 0, nx - 1, out=i)
    np.clip(j, 0, ny - 1, out=j)

    # Compose flat bin id in TOP-DOWN raster order so that an argsort
    # yields the exact byte layout GMT writes: j descends, i ascends.
    # bin_id = (ny - 1 - j) * nx + i
    bin_id = (ny - 1 - j) * nx + i

    # Group points by bin via argsort.
    order = np.argsort(bin_id, kind="stable")
    sorted_bins = bin_id[order]
    sorted_x = np.ascontiguousarray(x[order])
    sorted_y = np.ascontiguousarray(y[order])
    sorted_z = np.ascontiguousarray(z[order])

    # Find run boundaries: each non-empty bin is a contiguous slice.
    # `np.unique(return_index=True)` returns the first index of each
    # unique bin. Coupled with the total length we get start/end pairs.
    unique_bins, starts = np.unique(sorted_bins, return_index=True)
    starts = starts.astype(np.int64)
    ends = np.empty_like(starts)
    ends[:-1] = starts[1:]
    ends[-1] = sorted_bins.size

    M = unique_bins.size
    out_x = np.empty(M, dtype=np.float64)
    out_y = np.empty(M, dtype=np.float64)
    out_z = np.empty(M, dtype=np.float64)

    _per_bin_median(sorted_x, sorted_y, sorted_z, starts, ends,
                    out_x, out_y, out_z)

    return np.column_stack([out_x, out_y, out_z])


__all__ = ["blockmedian"]
