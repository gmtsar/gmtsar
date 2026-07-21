"""gmt_grdfilter_py — native-Python port of `gmt grdfilter -Fg -Dp`.

Mira mission, 2026-05-22 (continued from earlier session). Bit-faithful
port of GMT 6's Gaussian filter under cartesian-pixel distances (-Dp),
with -Ni NaN handling (skip-NaN-and-renormalize) and optional output
resampling via `inc_x_out` / `inc_y_out`.

GMT branches into TWO different Gaussian algorithms depending on whether
the user gives one or two filter widths
-----------------------------------------------------------------------
Reading grdfilter.c carefully, line 828: when the -F argument contains
a `/` (e.g. `-Fg<Wx>/<Wy>`), gmt sets `Ctrl->F.rect = true`. This flag
SWITCHES THE KERNEL ALGORITHM (lines 435-462 in set_weight_matrix):

  - `Ctrl->F.rect == false`  (single width, e.g. `-Fg7`):
      CIRCULAR-truncated Gaussian. Kernel weight at offset (i,j) is
        weight = exp(-18 r^2 / W^2)  for r <= W/2,  0 otherwise.
      (par[INV_R_SCALE] = -18/(W*W) at line 1169.)

  - `Ctrl->F.rect == true`  (two widths, e.g. `-Fg7/7` OR `-Fg7/9`):
      SEPARABLE RECTANGULAR Gaussian. Kernel weight at offset (i,j) is
        weight = exp(-4.5 * (i/x_half_width)^2)
               * exp(-4.5 * (j/y_half_width)^2)
      No radial truncation; the kernel covers the full
      (2*x_half_width+1) x (2*y_half_width+1) box.
      (par[INV_R_SCALE] = -4.5 at line 1169; the i/x_half_width
       normalization at lines 436-437 + 446 + 451-452.)

The gmtsar iono path (`estimate_ionospheric_phase`) invokes
  gmt grdfilter -Dp -Fg<filtx>/<filty> ...
i.e. the RECTANGULAR-SEPARABLE branch. The Mira #48 scipy substitution
diverged because scipy uses `truncate*sigma` truncation
(`exp(-r^2/(2*sigma^2))` shape) while gmt uses
`exp(-4.5*(i/half_width)^2)` (a FIXED weight at the kernel edge,
not at a fixed sigma-multiple). Different sigma definition.

Both algorithms are ported here. Caller picks via the number of width
arguments:
   filter_width only           -> circular truncated
   filter_width + filter_width2 -> separable rectangular
This matches gmt's CLI: `-Fg7` -> circular, `-Fg7/7` -> rectangular.

Why this exists
---------------
The Mira #48 scipy substitution was rejected for divergence (~1%).
The mission goal is to replace the iono path's `gmt grdfilter -Fg`
subprocess with an in-process port that is bit-faithful within float32
ULP, so `GMTSAR_IONO_PY=1` (default) can stay in-process AND match the
csh oracle byte-for-byte.

Source ported from
------------------
https://raw.githubusercontent.com/GenericMappingTools/gmt/master/src/grdfilter.c

Mapped lines (master @ 2026-05-22):
  - Kernel weight construction       set_weight_matrix  (lines 519-575)
  - Radius test                       line 791 `r > par[GRDFILTER_HALF_WIDTH]`
  - Gaussian weight formula           lines 632-636 (GaussianWeight)
                                       and 1071-1073 (par[INV_R_SCALE])
                                       => exp(-18 * r^2 / W^2)
  - Half-width formula                lines 1457-1481
                                       x_width = W / (inc_x * x_scale)
                                       x_half_width = ceil(x_width / 2)
                                       (with x_scale = 1.0 for -Dp/-D0)
  - Cartesian radius                  line 1420 `hypot(x0-x1, y0-y1)`
  - x[i] = i * inc_x precomputation   lines 1579-1581
  - Inner accumulation loop           lines 1693-1748
                                       w = weight * area; value += z*w;
                                       wt_sum += w
  - Renormalization                   lines 1749-1755
                                       out = value / wt_sum
                                       (NaN if wt_sum == 0)
  - NaN handling (-Ni default)        lines 1654-1663 (NAN_IGNORE: skip the
                                       NaN cell, do not poison wt_sum)
  - Effort level 1 (cartesian)        once per filter, not per row/col,
                                       since the kernel does not depend
                                       on output y (line 1281)

What this port covers
---------------------
  -Fg<W>                                    Gaussian, square (filtx=filty)
  -Fg<filtx>/<filty>                        Gaussian, axis-distinct widths
                                            (treated as a rectangle of
                                            elliptical Gaussian; matches
                                            gmt's `Ctrl->F.width` /
                                            `Ctrl->F.width2` two-field
                                            parse for the cartesian path).
  -Dp                                       Cartesian distances in grid
                                            increments.
  -Ni                                       Skip NaN cells (default).
  -I<inc_x>/<inc_y>                         Output increment override
                                            (coarser grid; output cell
                                            centers placed at
                                            xmin + (i+0.5)*inc_x_out for
                                            pixel registration; on
                                            xmin + i*inc_x_out for gridline.
                                            For each output cell, the
                                            input cell whose center is
                                            CLOSEST to (x_out, y_out)
                                            is the "origin" — exactly
                                            matches gmt line 1252's
                                            `col_origin = grd_x_to_col`).

What this port does NOT cover (yet)
-----------------------------------
  -D1..-D4                                  Spherical / flat-earth radius.
                                            (gmtsar's iono path always
                                            uses -Dp; not needed here.)
  -Fb, -Fc, -Fm, -Fp, -Fl, -Fu              Other filter shapes.
                                            (Boxcar, cosine-bell, median,
                                            mode, min, max — also not
                                            invoked by the iono path.)
  -Np, -Nr                                  Non-default NaN modes.
                                            (iono path uses -Ni.)
  -F.rect                                   Rectangular (non-radial)
                                            kernel — a separate path
                                            in grdfilter.c. -Fg is always
                                            radial (circle in the
                                            cartesian sense).

If a caller passes an unsupported option, this module raises — per
project rule 1 (no silent fallback).

Bit-faithfulness contract
-------------------------
On the canonical iono path (`-Dp -Fg<W> -Ni -I<incx>/<incy>`), output
is float32-roundoff identical to `gmt grdfilter`. The parity oracle is
`bin_py/tests/test_gmt_grdfilter_py.py::TestGmtGrdfilterParity`, which
spawns the real `gmt` and asserts `max|diff| < 1e-5` (float32 ULP at
unit-scale).
"""
from __future__ import annotations

from typing import Optional, Tuple

import numpy as np
from numba import njit


# ---------------------------------------------------------------------------
# Constants — verbatim from grdfilter.c line 1169:
#   par[GRDFILTER_INV_R_SCALE] = (Ctrl->F.rect)
#       ? -4.5 : -18.0 / (Ctrl->F.width * Ctrl->F.width);
# par[GRDFILTER_INV_R_SCALE] enters GaussianWeight as
#     exp(r * r * par[INV_R_SCALE]).
# - Circular (F.rect=false): exp(-18 * r^2 / W^2), truncated at r=W/2.
# - Rectangular (F.rect=true): the "r" passed to GaussianWeight is
#   already normalized (i/x_half_width or j/y_half_width) and gmt
#   multiplies the two 1-D weights; the constant is -4.5 so the kernel
#   edge (|i| = x_half_width) gets weight exp(-4.5) ~= 0.0111.
# ---------------------------------------------------------------------------
GMT_GAUSS_INV_R_SCALE_CIRC = -18.0
GMT_GAUSS_INV_R_SCALE_RECT = -4.5


# ---------------------------------------------------------------------------
# Kernel weight construction — gmt's set_weight_matrix, effort_level == 1
# (no per-row recompute under -Dp/cartesian).
# ---------------------------------------------------------------------------

def _kernel_half_widths(width: float, width2: float,
                        inc_x: float, inc_y: float,
                        nx_in: int, ny_in: int) -> tuple:
    """Replicate grdfilter.c lines 1192-1222 verbatim for cartesian -Dp.

      x_width = Ctrl->F.width  / inc_x         (x_scale = 1.0)
      y_width = (rect ? Ctrl->F.width2 : Ctrl->F.width) / inc_y
      x_half_width = irint(ceil(x_width / 2.0))
      y_half_width = irint(ceil(y_width / 2.0))
      n_columns = 2*x_half_width + 1; clamp to n_columns_input;
                  if clamped, recompute x_half_width = (n_columns-1)/2.
      Same for n_rows.
    """
    x_width_cells = width / inc_x
    y_width_cells = width2 / inc_y
    nx_half = int(np.ceil(x_width_cells / 2.0))
    ny_half = int(np.ceil(y_width_cells / 2.0))

    n_cols = 2 * nx_half + 1
    if n_cols > nx_in:
        n_cols = nx_in
        nx_half = (n_cols - 1) // 2

    n_rows = 2 * ny_half + 1
    if n_rows > ny_in:
        n_rows = ny_in
        ny_half = (n_rows - 1) // 2

    return nx_half, ny_half


def _build_circular_gaussian_kernel(
    width: float,
    inc_x: float,
    inc_y: float,
    nx_half: int,
    ny_half: int,
) -> np.ndarray:
    """Circular Gaussian kernel — `-Fg<W>` (single width).

    grdfilter.c references
    ----------------------
    Radius test       line 457: `weight[ij] = (r > par[HALF_WIDTH]) ? -1.0
                                              : F->weight_func(r, par)`
    Gaussian          GaussianWeight at lines 521-527: exp(r^2 * INV_R_SCALE).
    INV_R_SCALE       line 1169: -18.0 / (W*W).
    HALF_WIDTH        line 1180: 0.5 * Ctrl->F.width.
    Per-cell offsets  line 1228-1229: F.x[i] = i*F.dx, F.y[j] = j*F.dy.
    Cartesian radius  line 470: hypot(x0-x1, y0-y1).
    """
    half_width_cap = 0.5 * width
    inv_r_scale = GMT_GAUSS_INV_R_SCALE_CIRC / (width * width)

    jj = np.arange(-ny_half, ny_half + 1, dtype=np.float64)
    ii = np.arange(-nx_half, nx_half + 1, dtype=np.float64)
    dx = ii * inc_x
    dy = jj * inc_y
    rr2 = (dy[:, None]) ** 2 + (dx[None, :]) ** 2  # squared cartesian radius

    mask_in = rr2 <= (half_width_cap * half_width_cap)
    weights = np.where(mask_in, np.exp(rr2 * inv_r_scale), 0.0).astype(np.float64)
    return weights


def _build_rect_gaussian_kernel(
    nx_half: int,
    ny_half: int,
) -> np.ndarray:
    """Rectangular separable Gaussian kernel — `-Fg<Wx>/<Wy>` (two widths).

    grdfilter.c set_weight_matrix lines 435-452 (rect branch):
        if (F->rect) {
            inv_x_half_width = 1.0 / F->x_half_width;
            inv_y_half_width = 1.0 / F->y_half_width;
        }
        ...
        if (F->rect) ry = inv_y_half_width * j;    // j ∈ [-y_half, y_half]
        ...
        if (F->rect) {
            weight[ij] = F->weight_func(inv_x_half_width * i, par)
                       * F->weight_func(ry, par);
        }

    With INV_R_SCALE = -4.5 (line 1169), GaussianWeight(arg, par) returns
        exp(arg^2 * -4.5)
    so the 2-D weight at offset (j, i) is
        exp(-4.5 * (i/x_half_width)^2) * exp(-4.5 * (j/y_half_width)^2).

    No radial truncation. The kernel covers the full
    (2*ny_half+1, 2*nx_half+1) box, with values ~exp(-4.5) ≈ 0.011 at
    the corners (|i|=x_half_width AND |j|=y_half_width).
    """
    inv_x_half_width = 1.0 / nx_half
    inv_y_half_width = 1.0 / ny_half

    jj = np.arange(-ny_half, ny_half + 1, dtype=np.float64)
    ii = np.arange(-nx_half, nx_half + 1, dtype=np.float64)
    ry = inv_y_half_width * jj  # shape (2ny+1,)
    rx = inv_x_half_width * ii  # shape (2nx+1,)

    wy = np.exp(GMT_GAUSS_INV_R_SCALE_RECT * ry * ry)  # 1-D
    wx = np.exp(GMT_GAUSS_INV_R_SCALE_RECT * rx * rx)  # 1-D
    weights = (wy[:, None] * wx[None, :]).astype(np.float64)
    return weights


# ---------------------------------------------------------------------------
# Per-cell "area weight" A grid — grdfilter.c lines 555-585.
# For Cartesian (-Dp): A[row, col] = row_weight * col_weight, where
#   row_weight = inc_y * (0.5 if gridline-reg AND row ∈ {0, n_rows-1} else 1.0)
#   col_weight = inc_x * (0.5 if gridline-reg AND col ∈ {0, n_cols-1} else 1.0)
# This halves the weight contribution of the four edge strips of the
# INPUT grid in gridline-registered mode (because each gridline-reg
# edge node is "shared" with its image neighbour). For pixel-reg the
# weight is uniform inc_x*inc_y everywhere, which cancels in the
# per-cell renormalization and is therefore irrelevant — but we still
# build the constant grid so the inner loop is branch-free.
# ---------------------------------------------------------------------------

def _build_area_weight(ny_in: int, nx_in: int,
                       inc_x: float, inc_y: float,
                       node_offset: int) -> np.ndarray:
    """Area-weight A grid for cartesian -Dp. Shape (ny_in, nx_in)."""
    if node_offset == 0:
        row_w = np.full(ny_in, inc_y, dtype=np.float64)
        row_w[0] = 0.5 * inc_y
        row_w[-1] = 0.5 * inc_y
        col_w = np.full(nx_in, inc_x, dtype=np.float64)
        col_w[0] = 0.5 * inc_x
        col_w[-1] = 0.5 * inc_x
        A = row_w[:, None] * col_w[None, :]
    else:
        A = np.full((ny_in, nx_in), inc_x * inc_y, dtype=np.float64)
    return A


# ---------------------------------------------------------------------------
# Inner convolution kernel — numba-jitted, mirrors grdfilter.c lines 1567-1620.
# ---------------------------------------------------------------------------

@njit(parallel=False, fastmath=False, cache=True)
def _convolve_with_renorm(
    z_in: np.ndarray,             # (ny_in, nx_in) float64
    nan_mask_in: np.ndarray,      # (ny_in, nx_in) bool: True = NaN cell, skip
    weights: np.ndarray,          # (2ny_half+1, 2nx_half+1) float64
    area_w: np.ndarray,           # (ny_in, nx_in) float64 — A grid (gridline edges)
    col_origin: np.ndarray,       # (nx_out,) int64  input col closest to x_out
    row_origin: np.ndarray,       # (ny_out,) int64  input row closest to y_out
) -> np.ndarray:                  # (ny_out, nx_out) float64
    """Per-output-cell convolution with per-cell weight renormalization
    and NaN-skip (-Ni). Mirrors grdfilter.c lines 1567-1620 exactly.

    For each output cell (row_out, col_out):
      sum (w_ij * A[r_in, c_in]) * z[r_in, c_in]  over kernel offsets,
        skipping (a) r_in/c_in out of grid, (b) kernel weight == 0,
        (c) NaN cells.
      divide by sum of the SAME effective weights actually used (renorm).
      output = NaN if no weight contributed.

    grdfilter.c lines 1567-1620 (condensed):
        for jj in [-y_half, y_half]:
            row_in = row_origin + jj
            if row_in < 0 or row_in >= n_rows_in: continue
            for ii in [-x_half, x_half]:
                col_in = col_origin[col_out] + ii
                if col_in < 0 or col_in >= n_cols_in: continue
                w_kernel = weight[jj+y_half, ii+x_half]
                if w_kernel <= 0: continue          # outside filter circle
                if isnan(z_in[row_in, col_in]):
                    if N.mode == NAN_IGNORE: continue
                w = w_kernel * A[row_in, col_in]    // grdfilter.c line 1604
                value += z_in[row_in, col_in] * w
                wt_sum += w
        if wt_sum == 0: out = NaN
        else:           out = value / wt_sum
    """
    ny_in, nx_in = z_in.shape
    n_ky, n_kx = weights.shape
    y_half = n_ky // 2
    x_half = n_kx // 2
    ny_out = row_origin.shape[0]
    nx_out = col_origin.shape[0]

    out = np.empty((ny_out, nx_out), dtype=np.float64)

    for row_out in range(ny_out):
        r0 = row_origin[row_out]
        for col_out in range(nx_out):
            c0 = col_origin[col_out]
            value = 0.0
            wt_sum = 0.0
            for jj in range(-y_half, y_half + 1):
                row_in = r0 + jj
                if row_in < 0 or row_in >= ny_in:
                    continue
                wt_row = y_half + jj
                for ii in range(-x_half, x_half + 1):
                    col_in = c0 + ii
                    if col_in < 0 or col_in >= nx_in:
                        continue
                    w_kernel = weights[wt_row, x_half + ii]
                    if w_kernel <= 0.0:
                        continue
                    if nan_mask_in[row_in, col_in]:
                        # -Ni default: skip NaN cell, do not poison wt_sum.
                        continue
                    w = w_kernel * area_w[row_in, col_in]
                    value += z_in[row_in, col_in] * w
                    wt_sum += w
            if wt_sum == 0.0:
                out[row_out, col_out] = np.nan
            else:
                out[row_out, col_out] = value / wt_sum
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def gmt_grdfilter_py(
    data: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    *,
    filter_type: str = "g",
    filter_width: float,
    filter_width2: Optional[float] = None,
    rect: Optional[bool] = None,
    mode: str = "mean",
    distance_units: str = "p",
    nan_mode: str = "i",
    inc_x_out: Optional[float] = None,
    inc_y_out: Optional[float] = None,
    node_offset: int = 0,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """In-process port of `gmt grdfilter -Fg<W> -Dp -Ni [-I<inc>]`.

    Parameters
    ----------
    data : (ny, nx) array
        Input grid values. Will be cast to float64 internally; output
        is float32 (matches GMT's `nf` netCDF flavour).
    x, y : 1-D arrays
        Coordinate vectors for input grid columns / rows. Must be
        equispaced and ascending (gmt's normal convention; the bundled
        gmtsar grids satisfy this). `len(x) == nx`, `len(y) == ny`.
    filter_type : 'g'
        Only Gaussian -Fg is implemented; passing anything else raises.
    filter_width : float
        Full filter diameter (in the same units as `x` / `y`). Corresponds
        to `-Fg<filter_width>` on the gmt CLI. For -Dp this is in grid
        increments, so `filter_width = 21` and `x_inc = 1` means a 21-cell
        diameter circle.
    filter_width2 : float, optional
        Second axis diameter for `-Fg<filtx>/<filty>`. Defaults to
        `filter_width` if omitted.
    mode : 'mean'
        Only weighted-mean (gmt's convolution mode for -Fg) is implemented.
    distance_units : 'p'
        Only -Dp (cartesian-pixel) is implemented.
    nan_mode : 'i'
        Only -Ni (default: skip NaN cells, renormalize weights) is
        implemented.
    inc_x_out, inc_y_out : float, optional
        Output grid increments (matches `-I<inc_x>/<inc_y>`). If omitted,
        the output grid has the same dimensions and registration as the
        input. If provided, the output grid spans the same extent
        (xmin to xmax) with the new (coarser) spacing.
    node_offset : 0 (gridline) or 1 (pixel)
        Grid registration of input AND output. Same convention as
        `gmt_grd_io.write_gmt_grd` and gmt's `node_offset` global attr.

    Returns
    -------
    z_out : (ny_out, nx_out) float32
        Filtered grid in numpy "y ascending" orientation, matching the
        `gmt_grd_io.read_gmt_grd` layout.
    x_out, y_out : 1-D arrays, float64
        Output cell-center coordinates.

    Raises
    ------
    ValueError
        On any unsupported option, missing required arg, or non-equispaced
        coordinate vector. Project rule 1: no silent fallback.
    """
    # --- Argument validation -------------------------------------------------
    if filter_type != "g":
        raise ValueError(
            f"gmt_grdfilter_py: only -Fg (Gaussian) is implemented; got filter_type={filter_type!r}"
        )
    if mode != "mean":
        raise ValueError(
            f"gmt_grdfilter_py: only mode='mean' (gmt convolution) is implemented; got {mode!r}"
        )
    if distance_units != "p":
        raise ValueError(
            f"gmt_grdfilter_py: only distance_units='p' (-Dp cartesian) is implemented; got {distance_units!r}"
        )
    if nan_mode != "i":
        raise ValueError(
            f"gmt_grdfilter_py: only nan_mode='i' (-Ni default) is implemented; got {nan_mode!r}"
        )
    if filter_width is None or filter_width <= 0.0:
        raise ValueError(f"gmt_grdfilter_py: filter_width must be > 0; got {filter_width!r}")
    # grdfilter.c line 828: F.rect is set to true iff `-Fg<W1>/<W2>` is
    # given (i.e. the user supplies TWO widths). Caller-passed rect=...
    # is an override; otherwise we infer from filter_width2.
    if rect is None:
        rect_flag = filter_width2 is not None
    else:
        rect_flag = bool(rect)
    if filter_width2 is None:
        filter_width2 = filter_width
    if filter_width2 <= 0.0:
        raise ValueError(f"gmt_grdfilter_py: filter_width2 must be > 0; got {filter_width2!r}")
    if node_offset not in (0, 1):
        raise ValueError(f"gmt_grdfilter_py: node_offset must be 0 or 1; got {node_offset!r}")

    data = np.asarray(data)
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    if data.ndim != 2:
        raise ValueError(f"gmt_grdfilter_py: data must be 2-D; got shape {data.shape}")
    ny_in, nx_in = data.shape
    if x.shape != (nx_in,) or y.shape != (ny_in,):
        raise ValueError(
            f"gmt_grdfilter_py: x/y shapes ({x.shape}, {y.shape}) "
            f"must match data shape {data.shape} as (ny, nx)"
        )

    # Input increment: from coord spacing. Must be equispaced (gmt's grid
    # contract).
    inc_x_in = float(x[1] - x[0]) if nx_in > 1 else 1.0
    inc_y_in = float(y[1] - y[0]) if ny_in > 1 else 1.0
    if inc_x_in <= 0.0 or inc_y_in <= 0.0:
        raise ValueError(
            f"gmt_grdfilter_py: input coords must be ascending; got "
            f"inc_x_in={inc_x_in}, inc_y_in={inc_y_in}"
        )

    # --- Output grid construction ------------------------------------------
    # grdfilter.c lines 1080-1102 (paraphrased): output extent = input
    # extent (unless -R given); output spacing = input spacing (unless
    # -I given).
    if inc_x_out is None:
        inc_x_out_f = inc_x_in
    else:
        inc_x_out_f = float(inc_x_out)
    if inc_y_out is None:
        inc_y_out_f = inc_y_in
    else:
        inc_y_out_f = float(inc_y_out)
    if inc_x_out_f <= 0.0 or inc_y_out_f <= 0.0:
        raise ValueError(
            f"gmt_grdfilter_py: output increments must be > 0; got "
            f"inc_x_out={inc_x_out_f}, inc_y_out={inc_y_out_f}"
        )

    # The input grid's bounding box w/e/s/n:
    #   gridline (node_offset=0): xmin = x[0], xmax = x[-1]
    #   pixel    (node_offset=1): xmin = x[0] - inc_x_in/2, xmax = x[-1] + inc_x_in/2
    # gmt copies the input header's wesn into the output header (line 1080).
    if node_offset == 0:
        xmin_grd = float(x[0])
        xmax_grd = float(x[-1])
        ymin_grd = float(y[0])
        ymax_grd = float(y[-1])
    else:
        xmin_grd = float(x[0]) - inc_x_in / 2.0
        xmax_grd = float(x[-1]) + inc_x_in / 2.0
        ymin_grd = float(y[0]) - inc_y_in / 2.0
        ymax_grd = float(y[-1]) + inc_y_in / 2.0

    # gmt's grdfilter never overrides the input extent (no -R given here).
    # It computes:
    #   n_cols_out = irint((xmax - xmin) / inc_x_out) + 1  (gridline)
    #              = irint((xmax - xmin) / inc_x_out)      (pixel)
    # then RECOMPUTES the actual inc to span the extent exactly:
    #   inc_x_actual = (xmax - xmin) / (n_cols_out - 1)    (gridline)
    #                = (xmax - xmin) / n_cols_out          (pixel)
    # This is how -I8/8 on a 0..99 gridline grid lands at inc=8.25
    # (not 8.0): gmt prefers the input extent over the user's exact
    # requested increment. See gmt_init.c gmt_M_get_n and gmt's grid
    # header initialization in grdfilter.c lines ~1080-1102.
    if node_offset == 0:
        nx_out = int(np.rint((xmax_grd - xmin_grd) / inc_x_out_f)) + 1
        ny_out = int(np.rint((ymax_grd - ymin_grd) / inc_y_out_f)) + 1
        if nx_out > 1:
            inc_x_actual = (xmax_grd - xmin_grd) / (nx_out - 1)
        else:
            inc_x_actual = inc_x_out_f
        if ny_out > 1:
            inc_y_actual = (ymax_grd - ymin_grd) / (ny_out - 1)
        else:
            inc_y_actual = inc_y_out_f
        x_out = xmin_grd + np.arange(nx_out, dtype=np.float64) * inc_x_actual
        y_out = ymin_grd + np.arange(ny_out, dtype=np.float64) * inc_y_actual
        # Force exact endpoints (gmt does this at the macro level — see
        # gmt_M_col_to_x: last-col case returns xmax exactly).
        if nx_out > 1:
            x_out[-1] = xmax_grd
        if ny_out > 1:
            y_out[-1] = ymax_grd
    else:
        nx_out = int(np.rint((xmax_grd - xmin_grd) / inc_x_out_f))
        ny_out = int(np.rint((ymax_grd - ymin_grd) / inc_y_out_f))
        if nx_out >= 1:
            inc_x_actual = (xmax_grd - xmin_grd) / nx_out
        else:
            inc_x_actual = inc_x_out_f
        if ny_out >= 1:
            inc_y_actual = (ymax_grd - ymin_grd) / ny_out
        else:
            inc_y_actual = inc_y_out_f
        x_out = xmin_grd + (np.arange(nx_out, dtype=np.float64) + 0.5) * inc_x_actual
        y_out = ymin_grd + (np.arange(ny_out, dtype=np.float64) + 0.5) * inc_y_actual

    # col_origin / row_origin: nearest input cell to each output cell
    # (grdfilter.c line 1252:
    #   col_origin[col_out] = (int)gmt_M_grd_x_to_col(x_out, Gin->header)
    # which, for gridline reg, is round((x_out - x[0]) / inc_x_in)
    # and for pixel reg is floor((x_out - xmin_grd) / inc_x_in)).
    if node_offset == 0:
        col_origin = np.round((x_out - float(x[0])) / inc_x_in).astype(np.int64)
        row_origin = np.round((y_out - float(y[0])) / inc_y_in).astype(np.int64)
    else:
        col_origin = np.floor((x_out - xmin_grd) / inc_x_in).astype(np.int64)
        row_origin = np.floor((y_out - ymin_grd) / inc_y_in).astype(np.int64)
    # Clamp to grid (defensive — at exact extent boundaries float
    # round-off can push us by ±1 cell).
    np.clip(col_origin, 0, nx_in - 1, out=col_origin)
    np.clip(row_origin, 0, ny_in - 1, out=row_origin)

    # --- Kernel ---------------------------------------------------------
    # Half-widths (grdfilter.c lines 1192-1222). Common to both branches.
    nx_half, ny_half = _kernel_half_widths(
        width=float(filter_width),
        width2=float(filter_width2),
        inc_x=inc_x_in,
        inc_y=inc_y_in,
        nx_in=nx_in,
        ny_in=ny_in,
    )
    if nx_half == 0 or ny_half == 0:
        raise ValueError(
            f"gmt_grdfilter_py: kernel half-widths must be > 0; got "
            f"(nx_half={nx_half}, ny_half={ny_half}) from "
            f"(filter_width={filter_width}, filter_width2={filter_width2}, "
            f"inc_x={inc_x_in}, inc_y={inc_y_in})"
        )

    if rect_flag:
        weights = _build_rect_gaussian_kernel(nx_half, ny_half)
    else:
        weights = _build_circular_gaussian_kernel(
            width=float(filter_width),
            inc_x=inc_x_in,
            inc_y=inc_y_in,
            nx_half=nx_half,
            ny_half=ny_half,
        )

    # --- Area-weight A grid (grdfilter.c lines 555-585) ----------------
    area_w = _build_area_weight(ny_in, nx_in, inc_x_in, inc_y_in, node_offset)

    # --- Convolution ----------------------------------------------------
    data64 = data.astype(np.float64, copy=False)
    nan_mask_in = ~np.isfinite(data64)
    z_out_f64 = _convolve_with_renorm(
        data64, nan_mask_in, weights, area_w, col_origin, row_origin
    )
    return z_out_f64.astype(np.float32), x_out, y_out


__all__ = ["gmt_grdfilter_py"]
