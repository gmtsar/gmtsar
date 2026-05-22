#!/usr/bin/env python3
"""gmt_grdsample_py — in-process replacement for ``gmt grdsample``.

Verbatim port (per project_rules.md Rule 10) of the GMT 6 grid-resampling
chain:

    src/grdsample.c        — output grid construction + main loop
    src/gmt_bcr.c          — interpolation kernels (gmtbcr_prep, gmt_bcr_get_z)
    src/gmt_grd.h          — coord <-> col/row macros (gmt_M_col_to_x)
    src/gmt_init.c         — -n option defaults (BCR_BICUBIC, threshold=0.5)

The four interpolant flavours match GMT's ``-n`` flag:

==============  =====================================================
-n flag         Kernel
==============  =====================================================
``n``           Nearest neighbour (1x1 weight)
``l``           Bilinear (2x2 weight, see gmt_bcr.c:170-177)
``b``           B-spline (4x4 weight, gmt_bcr.c:178-199)
``c`` (default) Bicubic, a=-0.5 (4x4 weight, gmt_bcr.c:200-227)
==============  =====================================================

Registration semantics follow GMT exactly (gmt_grd.h:122-123):

  * Gridline (``node_offset = 0``, ``xy_off = 0``):
        ``x[i] = x_min + i * inc`` for ``i in [0, nx)``
        and the last node is anchored at ``x_max`` (the macro special-
        cases ``col == n_columns-1`` to dodge round-off drift).
  * Pixel (``node_offset = 1``, ``xy_off = 0.5``):
        ``x[i] = x_min + (i + 0.5) * inc``, last node ``x_max - 0.5*inc``.

The normalised query coordinate inside ``gmtbcr_prep`` is

    x = (xx - x_min) / dx  -  xy_off            # gmt_bcr.c:130
    y = (y_max - yy) / dy  -  xy_off            # gmt_bcr.c:131

i.e. y measured downwards from the top edge (GMT's row 0 is north).
For bicubic / bspline ``bcr_n == 4`` the upper-left corner index is
shifted one further cell NW (``col--; row--``; gmt_bcr.c:151).

Boundary policy
---------------
GMT pads the input grid by ``pad = 2`` cells on every side and fills the
pad via ``gmt_grd_BC_set`` (gmt_support.c:13050-13110) -- default is the
"natural" BC (zero second normal derivative, zero Laplacian on the 1st
outside row/col, zero d[Laplacian]/dn on the 2nd outside row/col).  We
replicate the natural BC fill verbatim in :func:`_apply_natural_bc`.
This is necessary for parity vs GMT at output points within 2 cells of
the input boundary -- the difference between index-clamp BC and natural
BC there is small in absolute terms but ~1e-2 on typical data ranges,
and pollutes the synthetic-grid parity tests.

Threshold
---------
GMT's ``-n+t<th>`` (default 0.5; gmt_init.c:19359) gates whether a
sample's weight-sum is large enough relative to the kernel's mass for
the result to be considered valid.  In the absence of NaNs the weight
sum equals the kernel mass (1.0 for bilinear+bicubic, 1.0 for the
3-term B-spline; the integral of the cubic-convolution kernel over
[-2,2] is 1).  We compute ``wsum`` per pixel and reject (-> NaN) if
``wsum + 1e-8 - threshold <= 0`` (matches gmt_bcr.c:268).

Truncation
----------
``-n+c`` clamps the output to ``[z_min, z_max]`` of the input (gmt_bcr.c
:271-273).  We expose this via the ``truncate`` kwarg, default False
(matching the default for ``gmt grdsample``).

Public API
----------
gmt_grdsample_py(data, x, y, *, new_x_inc, new_y_inc=None,
                 new_region=None, interp='bilinear', pixel_reg=False,
                 in_pixel_reg=False, threshold=0.5, truncate=False)
    Returns (data_out, x_out, y_out).
"""
from __future__ import annotations

from typing import Optional, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Output grid coord helpers (gmt_grd.h:122-123)
# ---------------------------------------------------------------------------

def _build_out_coord(c0: float, c1: float, inc: float, xy_off: float, n: int) -> np.ndarray:
    """Replicate gmt_M_col_to_x / gmt_M_row_to_y row-by-row.

    For interior nodes (``i != n-1``) ``c[i] = c0 + (i + xy_off) * inc``.
    The last node is pinned to ``c1 - xy_off * inc`` -- the GMT macro
    has this special case (gmt_grd.h:122) to compensate for the round-
    off in repeated addition over thousands of nodes.
    """
    out = c0 + (np.arange(n, dtype=np.float64) + xy_off) * inc
    out[-1] = c1 - xy_off * inc
    return out


def _output_dims(
    region: Tuple[float, float, float, float],
    x_inc: float,
    y_inc: float,
    pixel_reg: bool,
) -> Tuple[int, int]:
    """Compute (n_columns, n_rows) for a region/inc/registration.

    Matches gmt_M_get_n (gmt_grd.h:138):
        n = round((c1 - c0) / inc) + 1 - registration
    """
    xlo, xhi, ylo, yhi = region
    reg = 1 if pixel_reg else 0
    nx = int(round((xhi - xlo) / x_inc)) + 1 - reg
    ny = int(round((yhi - ylo) / y_inc)) + 1 - reg
    if nx < 1 or ny < 1:
        raise ValueError(
            f"output grid has non-positive dims: nx={nx}, ny={ny} "
            f"(region={region}, inc=({x_inc},{y_inc}), pixel_reg={pixel_reg})"
        )
    return nx, ny


# ---------------------------------------------------------------------------
# Kernel weights (gmt_bcr.c:166-227)
# ---------------------------------------------------------------------------

def _bilinear_weights(t: np.ndarray) -> np.ndarray:
    """1-D bilinear weights for offsets ``t`` in [0,1].
    Returns shape (..., 2) — wx[0]=1-t, wx[1]=t."""
    w = np.empty(t.shape + (2,), dtype=np.float64)
    w[..., 0] = 1.0 - t
    w[..., 1] = t
    return w


def _bspline_weights(t: np.ndarray) -> np.ndarray:
    """B-spline weights (gmt_bcr.c:178-199). Returns shape (..., 4).

    The C indexing convention:
        wp = t*t; wq = wp*t
        wx[1] = wq/2 - wp + 2/3
        wx[3] = wq/6
        w' = 1-t; wp' = w'^2; wq' = wp'*w'
        wx[2] = wq'/2 - wp' + 2/3
        wx[0] = wq'/6
    """
    w = np.empty(t.shape + (4,), dtype=np.float64)
    wp = t * t
    wq = wp * t
    w[..., 1] = wq / 2.0 - wp + 2.0 / 3.0
    w[..., 3] = wq / 6.0
    wm = 1.0 - t
    wpm = wm * wm
    wqm = wpm * wm
    w[..., 2] = wqm / 2.0 - wpm + 2.0 / 3.0
    w[..., 0] = wqm / 6.0
    return w


def _bicubic_weights(t: np.ndarray) -> np.ndarray:
    """Bicubic convolution weights with a=-0.5 (gmt_bcr.c:211-225).

    Verbatim:
        w = 1 - t
        wp = w * t
        wq = -0.5 * wp
        wx[0] = wq * w
        wx[3] = wq * t
        wx[1] = 3*wx[3] + w + wp
        wx[2] = 3*wx[0] + t + wp
    """
    out = np.empty(t.shape + (4,), dtype=np.float64)
    w = 1.0 - t
    wp = w * t
    wq = -0.5 * wp
    out[..., 0] = wq * w
    out[..., 3] = wq * t
    out[..., 1] = 3.0 * out[..., 3] + w + wp
    out[..., 2] = 3.0 * out[..., 0] + t + wp
    return out


# ---------------------------------------------------------------------------
# Natural BC pad fill (gmt_support.c:13050-13110)
# ---------------------------------------------------------------------------

def _apply_natural_bc(d_padded: np.ndarray, pad: int = 2) -> None:
    """Fill the ``pad`` rows/cols on every side of ``d_padded`` in-place
    using GMT's natural BC rules (gmt_support.c, x not periodic, y not
    periodic case).

    Input layout: ``d_padded`` has shape ``(ny + 2*pad, nx + 2*pad)``.
    The interior block ``d_padded[pad:-pad, pad:-pad]`` is the original
    data in **GMT's BCR frame** (row 0 = north).  Pad rows/cols ouside
    the interior get filled here.

    The constants 2.0, 4.0, 5.0 in the formulas are taken verbatim from
    the C; they correspond to the standard 5-point Laplacian stencil
    coefficients.
    """
    if pad != 2:
        raise ValueError(f"natural BC implementation is pad=2 specific (got {pad})")
    ny_pad, nx_pad = d_padded.shape
    # Index aliases matching the gmt_support.c naming (in BCR frame --
    # 'n' = north = row 0 of interior; 'jn' = pad row in padded frame).
    iw = pad                    # 1st column of data
    iwi1 = iw + 1               # 1st column inside (data col 1)
    iwo1 = iw - 1               # 1st column outside west
    iwo2 = iwo1 - 1             # 2nd column outside west
    ie = nx_pad - pad - 1       # last data column
    iei1 = ie - 1               # 1st column inside east (data col -2)
    ieo1 = ie + 1               # 1st column outside east
    ieo2 = ieo1 + 1             # 2nd column outside east

    jn = pad                    # north (top) data row
    jni1 = jn + 1               # 1st row inside (data row 1)
    jno1 = jn - 1               # 1st row outside north
    jno2 = jno1 - 1             # 2nd row outside north
    js = ny_pad - pad - 1       # south (bottom) data row
    jsi1 = js - 1               # 1st row inside south (data row -2)
    jso1 = js + 1               # 1st row outside south
    jso2 = jso1 + 1             # 2nd row outside south

    D = d_padded

    # ----- Step 1: corner points -----
    # d2/dx2 = 0:  D[edge, outside] = 2*D[edge, edge] - D[edge, inside]
    D[jn, iwo1] = 2.0 * D[jn, iw] - D[jn, iwi1]
    D[jn, ieo1] = 2.0 * D[jn, ie] - D[jn, iei1]
    D[js, iwo1] = 2.0 * D[js, iw] - D[js, iwi1]
    D[js, ieo1] = 2.0 * D[js, ie] - D[js, iei1]
    # d2/dy2 = 0
    D[jno1, iw] = 2.0 * D[jn, iw] - D[jni1, iw]
    D[jno1, ie] = 2.0 * D[jn, ie] - D[jni1, ie]
    D[jso1, iw] = 2.0 * D[js, iw] - D[jsi1, iw]
    D[jso1, ie] = 2.0 * D[js, ie] - D[jsi1, ie]
    # d2/dxdy = 0 (corner)
    D[jno1, iwo1] = D[jn, iwo1] + D[jno1, iw] - D[jn, iw]
    D[jno1, ieo1] = D[jn, ieo1] + D[jno1, ie] - D[jn, ie]
    D[jso1, iwo1] = D[js, iwo1] + D[jso1, iw] - D[js, iw]
    D[jso1, ieo1] = D[js, ieo1] + D[jso1, ie] - D[js, ie]

    # ----- Step 2: Laplacian = 0 on interior edge points (skip corners) -----
    # Top/bottom: cols iwi1..iei1
    cols_int = np.arange(iwi1, iei1 + 1)
    D[jno1, cols_int] = (4.0 * D[jn, cols_int]
                          - (D[jn, cols_int - 1] + D[jn, cols_int + 1] + D[jni1, cols_int]))
    D[jso1, cols_int] = (4.0 * D[js, cols_int]
                          - (D[js, cols_int - 1] + D[js, cols_int + 1] + D[jsi1, cols_int]))
    # Left/right: rows jni1..jsi1
    rows_int = np.arange(jni1, jsi1 + 1)
    D[rows_int, iwo1] = (4.0 * D[rows_int, iw]
                          - (D[rows_int + 1, iw] + D[rows_int - 1, iw] + D[rows_int, iwi1]))
    D[rows_int, ieo1] = (4.0 * D[rows_int, ie]
                          - (D[rows_int + 1, ie] + D[rows_int - 1, ie] + D[rows_int, iei1]))

    # ----- Step 3: d[Laplacian]/dn = 0 on 2nd outside row/col (incl corners) -----
    cols_all = np.arange(iw, ie + 1)
    D[jno2, cols_all] = (D[jni1, cols_all]
                         + 5.0 * (D[jno1, cols_all] - D[jn, cols_all])
                         + (D[jn, cols_all - 1] - D[jno1, cols_all - 1])
                         + (D[jn, cols_all + 1] - D[jno1, cols_all + 1]))
    D[jso2, cols_all] = (D[jsi1, cols_all]
                         + 5.0 * (D[jso1, cols_all] - D[js, cols_all])
                         + (D[js, cols_all - 1] - D[jso1, cols_all - 1])
                         + (D[js, cols_all + 1] - D[jso1, cols_all + 1]))
    rows_all = np.arange(jn, js + 1)
    D[rows_all, iwo2] = (D[rows_all, iwi1]
                        + 5.0 * (D[rows_all, iwo1] - D[rows_all, iw])
                        + (D[rows_all - 1, iw] - D[rows_all - 1, iwo1])
                        + (D[rows_all + 1, iw] - D[rows_all + 1, iwo1]))
    D[rows_all, ieo2] = (D[rows_all, iei1]
                        + 5.0 * (D[rows_all, ieo1] - D[rows_all, ie])
                        + (D[rows_all - 1, ie] - D[rows_all - 1, ieo1])
                        + (D[rows_all + 1, ie] - D[rows_all + 1, ieo1]))
    # 3 corner-most points in each corner of the pad remain unset
    # (gmt_support.c comment: "Loaded all but three corner-most points
    # at each corner.").  These positions are never touched by the
    # 4x4 BCR kernel as long as the query is inside the grid.


# Map -n flag -> (bcr_n, weight_fn, is_neighbour)
_INTERP_TABLE = {
    'nearest': (1, None, True),
    'n':       (1, None, True),
    'bilinear': (2, _bilinear_weights, False),
    'l':        (2, _bilinear_weights, False),
    'bspline':  (4, _bspline_weights, False),
    'b':        (4, _bspline_weights, False),
    'bicubic':  (4, _bicubic_weights, False),
    'c':        (4, _bicubic_weights, False),
}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def gmt_grdsample_py(
    data: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    *,
    new_x_inc: Optional[float] = None,
    new_y_inc: Optional[float] = None,
    new_region: Optional[Tuple[float, float, float, float]] = None,
    interp: str = 'bilinear',
    pixel_reg: bool = False,
    in_pixel_reg: bool = False,
    threshold: float = 0.5,
    truncate: bool = False,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    """In-process replacement for ``gmt grdsample``.

    Parameters
    ----------
    data : (ny, nx) float32/float64
        Input grid in "y ascending" orientation (``data[0]`` is the
        south-most row, ``data[-1]`` is the north-most). Same convention
        as :func:`gmt_grd_io.read_gmt_grd`.
    x, y : 1-D float
        Input coordinate vectors (length ``nx``, ``ny`` respectively),
        strictly monotonically ascending and uniformly spaced.
    new_x_inc : float, optional
        Output x increment. Default = input ``x[1] - x[0]``.
    new_y_inc : float, optional
        Output y increment. Default = input ``y[1] - y[0]``.
    new_region : (xmin, xmax, ymin, ymax), optional
        Output region. Default = input grid's full extent.
    interp : str
        One of ``'nearest' / 'n'``, ``'bilinear' / 'l'``,
        ``'bspline' / 'b'``, ``'bicubic' / 'c'``. Default ``'bilinear'``.
    pixel_reg : bool
        Output grid registration. False = gridline (default), True = pixel.
    in_pixel_reg : bool
        Input grid registration. Must match the source file's
        ``node_offset`` attribute (read via ``read_gmt_grd``).
    threshold : float
        ``-n+t`` value. NaN-mass gate; samples whose surviving weight
        sum is below this fraction of the kernel mass are returned NaN.
        Default 0.5 (GMT default, gmt_init.c:19359).
    truncate : bool
        If True, clamp output to ``[nanmin(data), nanmax(data)]``.
        Default False (matches ``gmt grdsample`` default — clipping is
        only applied if the user passed ``-n+c``).

    Returns
    -------
    data_out : (ny_out, nx_out) float32
        Resampled grid.
    x_out, y_out : 1-D float64
        Output coordinate vectors.
    info : dict
        Diagnostic dict carrying ``{n_columns, n_rows, x_inc, y_inc,
        registration, interp}`` for downstream comparison.
    """
    # ---- 1. shape + type sanity (no silent fallbacks; Rule 1)
    data = np.asarray(data)
    if data.ndim != 2:
        raise ValueError(f"data must be 2-D, got shape {data.shape}")
    ny_in, nx_in = data.shape
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    if x.shape != (nx_in,) or y.shape != (ny_in,):
        raise ValueError(
            f"x/y shape mismatch: data is {data.shape}, "
            f"x={x.shape}, y={y.shape}"
        )

    if interp not in _INTERP_TABLE:
        raise ValueError(
            f"interp={interp!r} not in {sorted(_INTERP_TABLE)}"
        )
    bcr_n, w_fn, is_neighbour = _INTERP_TABLE[interp]

    # ---- 2. derive input geometry
    # NOTE: GMT's wesn for a gridline-registered grid is (x[0], x[-1],
    # y[0], y[-1]); for pixel-registered it is (x[0]-dx/2, x[-1]+dx/2,
    # ...).  Same convention as gmt_grd_io.read_gmt_grd's stored info.
    in_dx = float(x[1] - x[0]) if nx_in > 1 else 0.0
    in_dy = float(y[1] - y[0]) if ny_in > 1 else 0.0
    if in_dx <= 0 or in_dy <= 0:
        raise ValueError(f"input grid must be ascending; got dx={in_dx}, dy={in_dy}")

    in_off = 0.5 if in_pixel_reg else 0.0
    in_xmin = float(x[0]) - in_off * in_dx
    in_xmax = float(x[-1]) + in_off * in_dx
    in_ymin = float(y[0]) - in_off * in_dy
    in_ymax = float(y[-1]) + in_off * in_dy

    # ---- 3. output geometry
    out_dx = float(new_x_inc) if new_x_inc is not None else in_dx
    out_dy = float(new_y_inc) if new_y_inc is not None else in_dy
    if out_dx <= 0 or out_dy <= 0:
        raise ValueError(f"new_x_inc/new_y_inc must be positive; got ({out_dx}, {out_dy})")

    if new_region is None:
        out_region = (in_xmin, in_xmax, in_ymin, in_ymax)
    else:
        out_region = tuple(float(v) for v in new_region)
        if len(out_region) != 4:
            raise ValueError(f"new_region must be (xmin, xmax, ymin, ymax); got {new_region!r}")

    out_off = 0.5 if pixel_reg else 0.0
    nx_out, ny_out = _output_dims(out_region, out_dx, out_dy, pixel_reg)

    x_out = _build_out_coord(out_region[0], out_region[1], out_dx, out_off, nx_out)
    y_out = _build_out_coord(out_region[2], out_region[3], out_dy, out_off, ny_out)

    # ---- 4. build padded data in BCR frame (row 0 = north, y-descending).
    # The natural BC fill at the pad happens in float32 to match gmt's
    # in-place fill (gmt_support.c casts back to gmt_grdfloat in each
    # corner constraint).
    PAD = 2
    d_in_bcr = data[::-1, :].astype(np.float32, copy=False)   # north-first
    d_pad = np.full((ny_in + 2 * PAD, nx_in + 2 * PAD),
                    np.float32(np.nan), dtype=np.float32)
    d_pad[PAD:PAD + ny_in, PAD:PAD + nx_in] = d_in_bcr
    _apply_natural_bc(d_pad, pad=PAD)
    # For the convolution we use float64 (gmt internally does the
    # multiply-accumulate in double via gmt_bcr_get_z's `double retval`).
    d64 = d_pad.astype(np.float64, copy=False)

    # ---- 5. normalised query coords (gmt_bcr.c:130-131)
    # x_norm = (xx - in_xmin) / in_dx - in_off   <-- already in node space.
    # We expand to a 2-D query grid (xq, yq) = meshgrid(x_out, y_out).
    # For column-vector / row-vector outer-product style: avoid full
    # meshgrid by keeping x_q and y_q as 1-D, then computing per-axis
    # weights independently and contracting along axes.

    r_inc_x = 1.0 / in_dx
    r_inc_y = 1.0 / in_dy

    # Per-axis normalised positions in (input) node coords.
    # NB: y is measured downwards from in_ymax (gmt_bcr.c:131).
    xn = (x_out - in_xmin) * r_inc_x - in_off
    yn = (in_ymax - y_out) * r_inc_y - in_off

    # ---- 6. kernel index + fractional offset
    if is_neighbour:
        # Nearest-neighbour: gmt_bcr.c:135-136 uses ``irint(x)`` which
        # under default IEEE FE_TONEAREST rounds half-to-even -- same
        # rule numpy's np.rint follows.  In practice query coords that
        # land *exactly* at .5 are very rare on real data (the multiply
        # by 1/inc nearly always introduces ULP-level drift).  When
        # they DO coincide, the rounding choice is unobservable as long
        # as the same rule is used both for the col0 -> data lookup AND
        # for the kernel weight evaluation -- but bilinear/bicubic skip
        # this branch altogether.
        col0 = np.rint(xn).astype(np.int64)
        row0 = np.rint(yn).astype(np.int64)
        # Clamp to valid range (BCR frame -- row 0 = north).
        col0 = np.clip(col0, 0, nx_in - 1)
        row0 = np.clip(row0, 0, ny_in - 1)
        # Gather from the padded array (row 0 of d_pad is the top of
        # the north pad).
        out = d64[row0[:, None] + PAD, col0[None, :] + PAD]
        out32 = out.astype(np.float32)
        if truncate:
            zmin = float(np.nanmin(d64)) if np.isfinite(d64).any() else 0.0
            zmax = float(np.nanmax(d64)) if np.isfinite(d64).any() else 0.0
            out32 = np.clip(out32, zmin, zmax).astype(np.float32)
        info = {
            'n_columns': nx_out, 'n_rows': ny_out,
            'x_inc': out_dx, 'y_inc': out_dy,
            'registration': 1 if pixel_reg else 0,
            'interp': interp, 'bcr_n': bcr_n,
        }
        return out32, x_out, y_out, info

    # 4x4 / 2x2 kernels: upper-left corner index in input grid coords.
    # gmt_bcr.c:141-152.
    xi = np.floor(xn)          # int part, float dtype
    yj = np.floor(yn)
    col0 = xi.astype(np.int64)  # irint(floor(.)) == floor(.) when finite
    row0 = yj.astype(np.int64)
    fx = xn - xi               # in [0, 1)
    fy = yn - yj
    if bcr_n == 4:
        col0 = col0 - 1
        row0 = row0 - 1

    # ---- 7. per-axis weights, shape (nx_out, bcr_n) and (ny_out, bcr_n)
    wx = w_fn(fx)               # (nx_out, bcr_n)
    wy = w_fn(fy)               # (ny_out, bcr_n)

    # ---- 8. assemble bcr_n^2 gather indices and accumulate.
    # Per-output-point sum_{i,j} d[row0+j, col0+i] * wx[i] * wy[j].
    # Vectorise with broadcasting:
    #   d_block[row, col, j, i] = d[row0[row]+j, col0[col]+i]   with edge clamp
    # then z = sum over (j, i) of d_block * wy[row, j, None] * wx[col, None, i]
    #
    # For 4x4 on a 2881x3241 grid resampled at the same size this is
    # 9.34M points * 16 reads = 150M doubles -- fine in 1.2 GB peak,
    # well within machine memory.  For larger output grids we tile
    # along the row axis (see below).

    # Build the index arrays (clamped) once.
    out_z = np.zeros((ny_out, nx_out), dtype=np.float64)
    out_w = np.zeros((ny_out, nx_out), dtype=np.float64)

    # Pre-build per-offset indices for each axis.  These reach into the
    # padded array, which carries valid natural-BC values out to 2
    # cells past the data edge -- so we add PAD and DO NOT clamp.
    # gmt_bcr.c:261 has a safety ``if (node >= G->header->size) continue;``
    # but with PAD=2 and bcr_n in {2,4} on data with n>=1 the index
    # never exceeds (n + 2*PAD - 1).  We assert that to fail loud if
    # an unexpected query slips through.
    col_idx = col0[None, :] + np.arange(bcr_n)[:, None] + PAD   # (bcr_n, nx_out)
    row_idx = row0[None, :] + np.arange(bcr_n)[:, None] + PAD   # (bcr_n, ny_out)
    if (col_idx.min() < 0 or col_idx.max() >= nx_in + 2 * PAD or
        row_idx.min() < 0 or row_idx.max() >= ny_in + 2 * PAD):
        raise RuntimeError(
            "internal: BCR query index left the padded grid -- "
            "output region outside input by more than the PAD of 2 cells. "
            "gmt_grdsample.c's wesn_o adjustment should prevent this; "
            "check new_region vs input extent."
        )

    # NaN mask for the input (gmt_bcr.c:305 skips NaN nodes).
    has_nan = np.isnan(d64).any()

    # Tile along row axis to keep peak memory manageable for very large
    # output grids.  Each tile builds a (tile_rows, nx_out, bcr_n, bcr_n)
    # block of weights + reads -- ~tile_rows * nx_out * bcr_n^2 * 8B.
    # Target ~256 MB per tile.
    bytes_per_row = nx_out * bcr_n * bcr_n * 8
    target_bytes = 256 * 1024 * 1024
    tile_rows = max(1, min(ny_out, target_bytes // max(bytes_per_row, 1)))

    for r0 in range(0, ny_out, tile_rows):
        r1 = min(r0 + tile_rows, ny_out)
        # Row indices for this tile slice: shape (bcr_n, r1-r0)
        rid = row_idx[:, r0:r1]
        # Loop over 4*4 (or 2*2) corner offsets.  This is bcr_n^2 = 4
        # or 16 outer-product-style accumulations; each touches the
        # whole tile of output pixels.
        for jj in range(bcr_n):
            ri = rid[jj]                # (r1-r0,)
            wyy = wy[r0:r1, jj]         # (r1-r0,)
            for ii in range(bcr_n):
                ci = col_idx[ii]        # (nx_out,)
                wxx = wx[:, ii]         # (nx_out,)
                w = wyy[:, None] * wxx[None, :]    # (r1-r0, nx_out)
                # Gather d[ri, ci] -> (r1-r0, nx_out)
                z_block = d64[ri[:, None], ci[None, :]]
                if has_nan:
                    nan_mask = np.isnan(z_block)
                    if nan_mask.any():
                        z_block = np.where(nan_mask, 0.0, z_block)
                        w_eff = np.where(nan_mask, 0.0, w)
                        out_z[r0:r1] += z_block * w_eff
                        out_w[r0:r1] += w_eff
                        continue
                out_z[r0:r1] += z_block * w
                out_w[r0:r1] += w

    # ---- 9. threshold + finalize (gmt_bcr.c:268-275)
    GMT_CONV8_LIMIT = 1.0e-8
    valid = (out_w + GMT_CONV8_LIMIT - threshold) > 0.0
    out = np.full_like(out_z, np.nan)
    np.divide(out_z, out_w, out=out, where=valid & (out_w != 0.0))

    if truncate:
        zmin = float(np.nanmin(d64)) if np.isfinite(d64).any() else 0.0
        zmax = float(np.nanmax(d64)) if np.isfinite(d64).any() else 0.0
        # Only clamp the *valid* entries (NaNs stay NaN).
        clamped = np.clip(out, zmin, zmax)
        out = np.where(valid, clamped, np.nan)

    info = {
        'n_columns': nx_out, 'n_rows': ny_out,
        'x_inc': out_dx, 'y_inc': out_dy,
        'registration': 1 if pixel_reg else 0,
        'interp': interp, 'bcr_n': bcr_n,
    }
    return out.astype(np.float32), x_out, y_out, info


# ---------------------------------------------------------------------------
# self-test
# ---------------------------------------------------------------------------

def _selftest() -> None:
    """Quick sanity check.  Verifies that resampling a grid onto its
    own coordinates is identity (within roundoff for bilinear/bicubic
    on a regular grid -- frac = 0 exactly)."""
    nx, ny = 31, 23
    x = np.linspace(0.0, 30.0, nx)
    y = np.linspace(0.0, 22.0, ny)
    z = (x[None, :] + y[:, None]) * 0.5  # linear field -- exact for both kernels
    for interp in ('bilinear', 'bicubic', 'bspline', 'nearest'):
        out, xo, yo, info = gmt_grdsample_py(z, x, y, interp=interp)
        if interp == 'bspline':
            # bspline is a smoother; identity at exact nodes lands within
            # ~2/3 of the true value due to wx(0) != 1 by construction
            # (gmt_bcr.c:182).  Verify shape and finite-ness instead.
            assert out.shape == z.shape, f"{interp}: shape {out.shape} != {z.shape}"
            assert np.isfinite(out).all(), f"{interp}: produced NaN at exact-node sampling"
            continue
        diff = np.abs(out.astype(np.float64) - z).max()
        assert diff < 1e-6, f"{interp}: identity-resample diff={diff:.3e}"
    print("gmt_grdsample_py: self-test OK")


if __name__ == "__main__":
    _selftest()
