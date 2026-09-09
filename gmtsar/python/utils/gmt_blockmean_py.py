#!/usr/bin/env python3
"""gmt_blockmean_py — Numba port of `gmt blockmean -bi3d -bo3d -r`.

Sibling of `gmt_blockmedian_py.py` (same grid/bin geometry), targeting
the two `dem2topo_ra` `topo_interp_mode=1` call sites:

    gmt blockmean temp.rat -R<region> -I<rng2>/16 -bi3d -bo3d -r > mean.rat
    gmt blockmean temp.rat -R<region> -I<rng2>/32 -bi3d -bo3d -r > mean.rat

(utils/dem2topo_ra:773, utils/dem2topo_ra:841 — `mode == 1` branches).

Key parity facts established empirically against `gmt blockmean`
(GMT 6.4.0), verified directly against the C binary (see
`gmt_blockmedian_py.py`'s header for the shared framework rationale;
GMT's blockmean/blockmedian/blockmode share the same `block_subs.c`
binning/index/region-adjust code — only the per-bin *reduction* differs):

* With no `-C` (bin centre), `-W` (weighting) or `-S` (extra columns)
  flags — exactly the flags dem2topo_ra passes — output is the plain
  **unweighted arithmetic mean of x, mean of y, mean of z per bin**.
  This was confirmed against the live `gmt blockmean` binary: e.g. for
  region `0/4/0/4 -I2/2 -r`, `gmt blockmean` output equals
  `x[bin].mean(), y[bin].mean(), z[bin].mean()` to full float64
  precision, matching the bin partition below.
* Bin index / region-adjust / row-order rules are IDENTICAL to
  `gmt_blockmedian_py.blockmedian` (banker rounding via `np.rint`,
  inclusive region filter, top-down raster row order). See that
  module's docstring for the derivation; not re-derived here.

Because the reduction is a mean (not an order statistic), no Numba
per-bin kernel is required: `np.add.reduceat` on the sorted arrays
computes all per-bin sums in one vectorised pass, which is both
simpler and faster than a median kernel.
"""
from __future__ import annotations

from typing import Tuple

import numpy as np


def blockmean(xyz: np.ndarray,
              region: Tuple[float, float, float, float],
              inc: Tuple[float, float],
              pixel_reg: bool = True) -> np.ndarray:
    """Bin (x, y, z) points to a grid and return the mean per non-empty bin.

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
        `gmt blockmean -r` and is what `dem2topo_ra` uses.

    Returns
    -------
    out : ndarray (M, 3) float64
        For each non-empty bin: (mean(x), mean(y), mean(z)). Rows are
        in top-down raster order (`j` descending, then `i` ascending),
        matching `gmt blockmean -bi3d -bo3d -r` byte layout.
    """
    if xyz.ndim != 2 or xyz.shape[1] != 3:
        raise ValueError(f"xyz must be (N, 3), got {xyz.shape}")
    xyz = np.ascontiguousarray(xyz, dtype=np.float64)

    x_min, x_max, y_min, y_max = (float(v) for v in region)
    x_inc, y_inc = (float(v) for v in inc)

    # GMT chooses nx = irint((x_max - x_min) / x_inc) (banker rounding),
    # then adjusts x_inc to (x_max - x_min) / nx. Byte-identical to
    # gmt_blockmedian_py's region-adjust logic.
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

    # GMT pixel-reg index formula: irint((p - p_min) / p_inc - 0.5)
    if pixel_reg:
        i = np.rint((x - x_min) / x_inc - 0.5).astype(np.int64)
        j = np.rint((y - y_min) / y_inc - 0.5).astype(np.int64)
    else:
        i = np.rint((x - x_min) / x_inc).astype(np.int64)
        j = np.rint((y - y_min) / y_inc).astype(np.int64)

    np.clip(i, 0, nx - 1, out=i)
    np.clip(j, 0, ny - 1, out=j)

    # Flat bin id in TOP-DOWN raster order: j descends, i ascends.
    bin_id = (ny - 1 - j) * nx + i

    order = np.argsort(bin_id, kind="stable")
    sorted_bins = bin_id[order]
    sorted_x = x[order]
    sorted_y = y[order]
    sorted_z = z[order]

    unique_bins, starts, counts = np.unique(
        sorted_bins, return_index=True, return_counts=True)
    starts = starts.astype(np.int64)
    counts = counts.astype(np.float64)

    # np.add.reduceat computes the per-bin sum in one vectorised pass;
    # dividing by the per-bin count gives the mean. This matches GMT's
    # unweighted-mean reduction (no -W/-C/-S flags at the call sites).
    sum_x = np.add.reduceat(sorted_x, starts)
    sum_y = np.add.reduceat(sorted_y, starts)
    sum_z = np.add.reduceat(sorted_z, starts)

    out_x = sum_x / counts
    out_y = sum_y / counts
    out_z = sum_z / counts

    return np.column_stack([out_x, out_y, out_z])


__all__ = ["blockmean"]
