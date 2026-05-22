#!/usr/bin/env python3
"""gmt_grdfill_py - in-process replacement for ``gmt grdfill``.

Verbatim port (per project_rules.md Rule 10) of the GMT 6 grdfill module:

    src/grdfill.c          - main module, -A option handling
        - ``grdfill_do_constant_fill``       (-Ac)
        - ``grdfill_nearest_interp``          (-An)
        - ``grdfill_find_nearest``            (-An helper)
        - ``grdfill_sample``                  (-Ag, via grdtrack bilinear)
        - ``GMT_grdfill`` main + hole tracing (informational only)

Algorithm matrix
----------------

============  =================================================================
``-A`` flag   Behaviour (this port)
============  =================================================================
``c<val>``    Replace every NaN with ``<val>`` (cast to float32).
``n[<r>]``    Eric Xu's nearest-neighbour scan. For each NaN, scans concentric
              integer-radius shells outward until a non-NaN is found, reusing
              the previous nearest distance as a starting radius (the "recx /
              recy" optimisation in grdfill.c:454-461).  ``<r>`` is the max
              shell radius; default is ``floor(sqrt(nx**2 + ny**2))``.
``g``         For each NaN node ``(row, col)`` in the input, sample the donor
              grid at ``(x[col], y[row])`` using bicubic interpolation (a=-0.5,
              4x4 kernel).  This mirrors the C path verbatim: grdfill.c:547
              calls ``grdtrack`` with NO ``-n`` flag, so GMT's default
              interpolant (``BCR_BICUBIC``, gmt_init.c) is used.  We verified
              empirically: ``gmt grdtrack -Gdonor`` == ``-nc`` (bicubic),
              NOT ``-nl`` (bilinear) -- both at the API level (default
              ``GMT->common.n.interpolant = BCR_BICUBIC``) and on real
              numbers (grdtrack -Gcoarse on a 21x17 donor matched -nc to
              the bit and differed from -nl by ~0.03 in mid-range).
============  =================================================================

The spline mode ``-As`` is NOT ported; production pipeline (dem2topo_ra
mode=1, the only consumer in this fork) uses ``-Ag`` exclusively, and
``-As`` invokes ``greenspline`` -- a separate ~10 kLOC GMT module out of
scope for this port.  Calling ``algorithm='s'`` raises NotImplementedError
(per Rule 1: no silent fallback).

Hole tracing (``grdfill_trace_the_hole``) is NOT needed because the only
per-hole work the C code does is the constant / nearest / sample fill, all
of which act element-wise on NaN positions independent of hole identity.
(``-As`` and ``-L`` -- which DO need hole topology -- are out of scope.)

Boundary handling
-----------------

-An scan: indices outside ``[0, ny) x [0, nx)`` are skipped (mirrors the C
  guard at grdfill.c:469-470, ``if (is[k] >= 0 && is[k] < ny && js[k] >= 0
  && js[k] < nx)``).  This means a NaN node never wraps around the grid.

-Ag bilinear: if the donor grid's region exactly matches the input's, the
  query point lands on a donor node (or between four nodes), all within
  range.  If the query falls outside the donor's [xmin, xmax] x [ymin, ymax]
  the port raises -- the C path's grdtrack would also fail (silent NaN in
  the output), and per Rule 1 we make that loud.

Parity oracle
-------------

``bin_py/tests/test_gmt_grdfill_py.py`` runs ``gmt grdfill`` and this port
on the same synthetic grids and asserts byte-identical float32 output.
For ``-An`` and ``-Ag`` the result must be exact (no floating-point
arithmetic in -An; -Ag is a single bilinear weighted sum identical to
grdtrack's).  For ``-Ac`` the result is trivially exact.

Performance
-----------

-Ag is fully vectorised (numpy gather + 4-tap dot product); typical wall
   time is dominated by the netCDF I/O, not the math.
-An uses a Numba-jitted scan kernel (``@njit(parallel=False,
   fastmath=False, cache=True)``) since the algorithm is intrinsically
   serial along rows (each column reuses the previous column's recx/recy).
"""

from __future__ import annotations

from typing import Optional, Tuple, Union

import numpy as np

try:
    from numba import njit  # type: ignore
    _HAVE_NUMBA = True
except ImportError:  # pragma: no cover
    _HAVE_NUMBA = False

    def njit(*args, **kwargs):  # type: ignore
        def deco(fn):
            return fn
        if len(args) == 1 and callable(args[0]):
            return args[0]
        return deco


# ---------------------------------------------------------------------------
# -Ac : constant fill   (grdfill.c:210-222, grdfill_do_constant_fill)
# ---------------------------------------------------------------------------

def _constant_fill(data: np.ndarray, value: float) -> np.ndarray:
    """Replace every NaN with ``value`` (float32 cast).

    Mirrors grdfill.c:214-218:

        if (gmt_M_is_fnan (G->data[node]))
            G->data[node] = value;
    """
    out = data.astype(np.float32, copy=True)
    mask = np.isnan(out)
    out[mask] = np.float32(value)
    return out


# ---------------------------------------------------------------------------
# -An : Eric Xu's nearest-neighbour scan
# Verbatim port of grdfill.c:354-493
# ---------------------------------------------------------------------------

# The C helper ``grdfill_find_nearest`` (grdfill.c:354-424):
#
#   * Takes the previous squared distance ``r2`` and finds the smallest
#     integer (nx, ny) pair with ``nx*nx + ny*ny > r2`` and ``ny <= nx``.
#   * Emits the 4 / 8 / 4 symmetric shell points around (i, j) at that
#     squared radius.
#   * Returns the count and updates ``r2`` to the new squared radius.
#
# The Python port keeps the **exact** same integer arithmetic so the
# shell enumeration order is bit-identical to C; this matters because
# the C code documents that ordering changes lead to different
# nearest-neighbour solutions when ties exist (grdfill.c:386).

@njit(parallel=False, fastmath=False, cache=True)
def _find_nearest_shell(i: np.int64, j: np.int64, r2_in: np.int64,
                        is_buf: np.ndarray, js_buf: np.ndarray,
                        xs_buf: np.ndarray, ys_buf: np.ndarray
                        ) -> Tuple[np.int64, np.int64]:
    """Emit shell of candidate (i, j) neighbours at the next squared radius.

    Returns (ct, r2_new) where ct is the number of candidates written to
    ``is_buf[:ct]`` and ``js_buf[:ct]`` (absolute row/col), and r2_new is
    the updated squared radius for the next call.

    Mirrors grdfill_find_nearest (grdfill.c:354-424) verbatim:

        rr = INTMAX_MAX
        nx = (int64_t)(sqrt(r2 / 2.0))
        for nx1 in [nx, sqrt(r2)+1]:
            if nx1*nx1 < r2: ny = sqrt(r2 - nx1*nx1)
            else:            ny = 0
            while (nx1*nx1 + ny*ny <= r2) and (ny <= nx1): ny += 1
            ny_2 = ny*ny
            if ny <= nx1:
                update best (xs, ys, k) tracking ties at distance rr
        # Then expand each (nx, ny) into the 4/8/4 shell octants.
    """
    INTMAX = np.int64(9223372036854775807)
    rr = INTMAX
    k = np.int64(-1)  # filled when first tie found; -1 means none yet

    nx_start = np.int64(np.sqrt(r2_in / 2.0))
    nx_end = np.int64(np.sqrt(np.float64(r2_in))) + np.int64(1)

    for nx1 in range(nx_start, nx_end + 1):
        nx1_2 = nx1 * nx1
        if nx1_2 < r2_in:
            ny = np.int64(np.sqrt(np.float64(r2_in - nx1_2)))
        else:
            ny = np.int64(0)
        # Walk ny up until we cross the threshold or surpass nx1
        while (nx1_2 + ny * ny) <= r2_in and ny <= nx1:
            ny += 1
        ny_2 = ny * ny
        if ny <= nx1:
            if rr > (nx1_2 + ny_2):
                k = np.int64(0)
                rr = nx1_2 + ny_2
                xs_buf[0] = nx1
                ys_buf[0] = ny
            elif rr == (nx1_2 + ny_2):
                k += 1
                xs_buf[k] = nx1
                ys_buf[k] = ny

    ct = np.int64(0)
    if k < 0:
        # No shell found - signal end-of-scan to caller
        return ct, rr

    for ii in range(k + 1):
        nx = xs_buf[ii]
        ny = ys_buf[ii]
        if ny == 0:
            # 4 cardinal offsets at +-nx
            js_buf[ct] = 0;   is_buf[ct] =  nx; ct += 1
            js_buf[ct] = 0;   is_buf[ct] = -nx; ct += 1
            js_buf[ct] =  nx; is_buf[ct] =  0;  ct += 1
            js_buf[ct] = -nx; is_buf[ct] =  0;  ct += 1
        elif nx != ny:
            # 8 octant offsets
            js_buf[ct] =  ny; is_buf[ct] =  nx; ct += 1
            js_buf[ct] =  ny; is_buf[ct] = -nx; ct += 1
            js_buf[ct] = -ny; is_buf[ct] =  nx; ct += 1
            js_buf[ct] = -ny; is_buf[ct] = -nx; ct += 1
            js_buf[ct] =  nx; is_buf[ct] =  ny; ct += 1
            js_buf[ct] = -nx; is_buf[ct] =  ny; ct += 1
            js_buf[ct] =  nx; is_buf[ct] = -ny; ct += 1
            js_buf[ct] = -nx; is_buf[ct] = -ny; ct += 1
        else:
            # nx == ny: 4 diagonal offsets
            js_buf[ct] =  nx; is_buf[ct] =  nx; ct += 1
            js_buf[ct] =  nx; is_buf[ct] = -nx; ct += 1
            js_buf[ct] = -nx; is_buf[ct] =  nx; ct += 1
            js_buf[ct] = -nx; is_buf[ct] = -nx; ct += 1

    # Convert to absolute (row, col) by adding (i, j)
    for ii in range(ct):
        is_buf[ii] = is_buf[ii] + i
        js_buf[ii] = js_buf[ii] + j

    return ct, rr


@njit(parallel=False, fastmath=False, cache=True)
def _nn_scan(m: np.ndarray, m_interp: np.ndarray, rad2: np.float64) -> np.int64:
    """Eric Xu nearest-neighbour scan, port of grdfill_nearest_interp.

    grdfill.c:426-493:

        nx = n_columns, ny = n_rows
        rad2 = radius * radius  (radius default = floor(sqrt(nx^2 + ny^2)))

        gmt_M_row_loop:           # i = 0..ny-1
            rr = 0
            recx, recy = 1, 1     # NOTE: only reset on row change-via-NaN
            gmt_M_col_loop:       # j = 0..nx-1, node = i*nx + j
                if not NaN(m[node]):
                    rr = 0
                    continue
                # search nearest neighbour
                flag = 0
                # set starting search radius based on last nearest distance
                if rr >= 4:
                    if   recy > 0 and recx > 0: rr = (recx-1)^2 + (recy-1)^2 - 1
                    elif recy == 0 and recx > 0: rr = (recx-1)^2 - 1
                    elif recy > 0 and recx == 0: rr = (recy-1)^2 - 1
                else:
                    rr = 0
                while flag == 0 and rr <= rad2:
                    ct = grdfill_find_nearest(i, j, &rr, is, js, xs, ys)
                    for k = 0..ct-1:
                        if (is[k], js[k]) in bounds and not NaN(m[is, js]):
                            m_interp[ij] = m[is, js]
                            flag = 1
                            recx = |is[k] - i|
                            recy = |js[k] - j|
                            break

    Note: ``m_interp`` must START AS A COPY of ``m`` (the C code calls
    ``GMT_Duplicate_Data`` before this kernel, grdfill.c:633-636).
    """
    ny, nx = m.shape

    # Preallocated scratch buffers (matches grdfill.c:435-438 sizes)
    is_buf = np.empty(2048, dtype=np.int64)
    js_buf = np.empty(2048, dtype=np.int64)
    xs_buf = np.empty(512, dtype=np.int64)
    ys_buf = np.empty(512, dtype=np.int64)

    cs = np.int64(0)  # search-call counter (informational, matches C)

    for i in range(ny):
        rr = np.int64(0)
        recx = np.int64(1)
        recy = np.int64(1)
        for j in range(nx):
            v = m[i, j]
            if not np.isnan(v):
                rr = np.int64(0)
                continue
            # set starting search radius based on last nearest distance
            if rr >= 4:
                if recy > 0 and recx > 0:
                    rr = (recx - 1) * (recx - 1) + (recy - 1) * (recy - 1) - 1
                elif recy == 0 and recx > 0:
                    rr = (recx - 1) * (recx - 1) - 1
                elif recy > 0 and recx == 0:
                    rr = (recy - 1) * (recy - 1) - 1
                # else: leave rr unchanged (recx == recy == 0 is impossible
                # in C path: we only reach here from a NaN; previous match
                # must have been at distance >= 1)
            else:
                rr = np.int64(0)

            flag = 0
            while flag == 0 and rr <= rad2:
                ct, rr = _find_nearest_shell(i, j, rr, is_buf, js_buf,
                                             xs_buf, ys_buf)
                cs += 1
                if ct == 0:
                    # No further shells representable -> exhausted
                    break
                for k in range(ct):
                    ii = is_buf[k]
                    jj = js_buf[k]
                    if 0 <= ii < ny and 0 <= jj < nx:
                        cand = m[ii, jj]
                        if not np.isnan(cand):
                            m_interp[i, j] = cand
                            flag = 1
                            recx = ii - i if ii >= i else i - ii
                            recy = jj - j if jj >= j else j - jj
                            break
    return cs


def _nearest_fill(data: np.ndarray, radius: int = -1) -> np.ndarray:
    """-An nearest-neighbour fill.

    Parameters
    ----------
    data : 2-D float32 array in **numpy y-ascending orientation**
        (``data[0, :]`` -> smallest y).  NaN marks holes.
    radius : int
        Max integer shell radius.  ``-1`` -> default
        ``floor(sqrt(nx^2+ny^2))`` (grdfill.c:440-441).

    Notes
    -----
    GMT iterates rows in y-DESCENDING order (row 0 = north,
    gmt_M_row_loop, gmt_M_ijp).  When tied at distance 1 it prefers the
    SOUTH neighbour first in its frame (grdfill.c:392-395 emits
    ``is=+nx, js=0`` first, i.e. row+1) -- which is the NORTH neighbour
    in our y-ascending numpy frame.

    Tie-breaking matters: on the synthetic ``many_holes`` test, an
    isolated NaN at numpy ``[10, 10]`` has equal distance-1 neighbours
    in all 4 cardinal directions; iterating in the wrong frame picks
    the wrong neighbour and the output diverges from gmt grdfill at all
    isolated NaN positions.

    The fix: flip data y-down before the scan (matching gmt's frame),
    run the scan, flip back.  The numerical result is bit-identical to
    GMT because all comparisons inside the scan are equality / index
    arithmetic only.
    """
    if data.ndim != 2:
        raise ValueError(f"data must be 2-D, got shape {data.shape}")
    ny, nx = data.shape
    if radius == -1:
        radius = int(np.floor(np.sqrt(float(nx * nx + ny * ny))))
    rad2 = float(radius) * float(radius)

    if not np.isnan(data).any():
        return data.astype(np.float32, copy=True)

    # Flip to GMT's row order (row 0 = north / largest y).
    d_gmt = data[::-1, :].astype(np.float32, copy=True)
    out_gmt = d_gmt.copy()
    _nn_scan(d_gmt, out_gmt, np.float64(rad2))
    # Flip back to numpy y-ascending.
    return out_gmt[::-1, :].copy()


# ---------------------------------------------------------------------------
# -Ag : sample from donor grid (BICUBIC -- the GMT grdtrack default)
# Verbatim port of grdfill_sample (grdfill.c:495-564) - which delegates to
# grdtrack with NO -n flag, so GMT's default interpolant
# (gmt_init.c: ``GMT->common.n.interpolant = BCR_BICUBIC``, a=-0.5) is used.
# ---------------------------------------------------------------------------
#
# Verification (synthetic 21x17 donor, queried at scattered NaN locations
# in a 41x33 input):
#   gmt grdfill -Agdonor.grd          -> matches  gmt grdtrack -Gdonor    -nc (bicubic)
#                                        differs by ~0.03 from           -nl (bilinear)
# So bilinear is wrong for -Ag.  We port the bicubic kernel from
# gmt_grdsample_py's _bicubic_weights + _apply_natural_bc, applied at
# scattered (xq, yq) instead of a regular output grid.

# Reuse the natural-BC pad fill + bicubic weights already validated in
# gmt_grdsample_py (Mira #N, GREEN against gmt grdsample).  Importing
# from the sibling module keeps the kernel choice in lockstep -- a
# library-substitution risk we accept (Pattern 3) because the kernel is
# our OWN port of the C and not a scipy/numpy generic.
from gmt_grdsample_py import (  # noqa: E402
    _apply_natural_bc as _natural_bc,
    _bicubic_weights as _bcr_bicubic_weights,
)


def _bcr_bicubic_sample(donor: np.ndarray, donor_x: np.ndarray,
                        donor_y: np.ndarray, qx: np.ndarray,
                        qy: np.ndarray,
                        *, threshold: float = 0.5) -> np.ndarray:
    """Bicubic sample of ``donor`` at scattered query points ``(qx, qy)``.

    Mirrors gmt_bcr.c (gmt_bcr_get_z) with the default a=-0.5 bicubic
    kernel:

      1. Build padded array (pad=2) in BCR frame (row 0 = north).
      2. Fill the pad via natural BC (gmt_support.c, no periodicity).
      3. For each query (xq, yq) compute normalised coords
             xn = (xq - in_xmin)/dx - in_off       # gmt_bcr.c:130
             yn = (in_ymax - yq)/dy - in_off       # gmt_bcr.c:131  (y from top)
         col0 = floor(xn) - 1   (upper-left corner of 4x4 in input coords)
         row0 = floor(yn) - 1
         fx = xn - floor(xn);  fy = yn - floor(yn)
      4. Weights wx[k=0..3] = _bicubic_weights(fx), same for wy(fy).
      5. z = sum_{j=0..3} sum_{i=0..3} d[row0+j+PAD, col0+i+PAD] * wx[i] * wy[j]

    NaN handling matches gmt_bcr.c:305 -- NaN-valued contributors drop
    out of the weighted average; the cell is masked NaN if (sum_w +
    GMT_CONV8_LIMIT - threshold) <= 0.
    """
    nx = donor_x.size
    ny = donor_y.size
    dx = float(donor_x[-1] - donor_x[0]) / max(nx - 1, 1)
    dy = float(donor_y[-1] - donor_y[0]) / max(ny - 1, 1)
    in_xmin = float(donor_x[0])
    in_ymax = float(donor_y[-1])
    # We always treat donor as gridline-registered here -- the dem2topo_ra
    # production path passes pixel-registered topo_ra_tmp through the same
    # bicubic at the same registration; the in_off applies in both axes if
    # the donor is pixel-reg.  We default to 0.0 (gridline); the file-
    # wrapper passes the actual node_offset.
    in_off = 0.0

    fx = (qx.astype(np.float64) - in_xmin) / dx - in_off
    fy = (in_ymax - qy.astype(np.float64)) / dy - in_off

    # Range check (per Rule 1).  Allow tiny overshoot (rounding).
    if (fx < -1e-9).any() or (fx > nx - 1 + 1e-9).any():
        raise ValueError(
            "donor grid does not cover query x range: "
            f"qx in [{float(qx.min()):.6g}, {float(qx.max()):.6g}] vs donor "
            f"[{donor_x[0]:.6g}, {donor_x[-1]:.6g}]")
    if (fy < -1e-9).any() or (fy > ny - 1 + 1e-9).any():
        raise ValueError(
            "donor grid does not cover query y range: "
            f"qy in [{float(qy.min()):.6g}, {float(qy.max()):.6g}] vs donor "
            f"[{donor_y[0]:.6g}, {donor_y[-1]:.6g}]")

    fx = np.clip(fx, 0.0, nx - 1.0)
    fy = np.clip(fy, 0.0, ny - 1.0)

    xi = np.floor(fx)
    yj = np.floor(fy)
    col0 = xi.astype(np.int64) - 1  # 4x4 upper-left
    row0 = yj.astype(np.int64) - 1
    tx = fx - xi
    ty = fy - yj

    wx = _bcr_bicubic_weights(tx)   # (Nq, 4)
    wy = _bcr_bicubic_weights(ty)   # (Nq, 4)

    # Build padded donor in BCR frame (row 0 = north -- so flip
    # numpy-y-ascending to gmt-y-descending).
    PAD = 2
    d_bcr = donor[::-1, :].astype(np.float32, copy=False)
    d_pad = np.full((ny + 2 * PAD, nx + 2 * PAD),
                    np.float32(np.nan), dtype=np.float32)
    d_pad[PAD:PAD + ny, PAD:PAD + nx] = d_bcr
    _natural_bc(d_pad, pad=PAD)
    d64 = d_pad.astype(np.float64, copy=False)

    Nq = qx.size
    z_sum = np.zeros(Nq, dtype=np.float64)
    w_sum = np.zeros(Nq, dtype=np.float64)
    has_nan = np.isnan(d64).any()

    for j in range(4):
        ri = row0 + j + PAD   # (Nq,)
        # ri can theoretically go out of bounds for queries within 2 cells
        # of the donor edge -- the PAD=2 + natural BC fill ensures all
        # legitimate indices in [0, ny+2*PAD) are populated.
        if (ri.min() < 0) or (ri.max() >= ny + 2 * PAD):
            raise RuntimeError(
                f"bicubic BCR index out of padded range (j={j}, "
                f"ri in [{ri.min()},{ri.max()}], allowed "
                f"[0,{ny + 2 * PAD - 1}])")
        for i in range(4):
            ci = col0 + i + PAD  # (Nq,)
            if (ci.min() < 0) or (ci.max() >= nx + 2 * PAD):
                raise RuntimeError(
                    f"bicubic BCR index out of padded range (i={i}, "
                    f"ci in [{ci.min()},{ci.max()}], allowed "
                    f"[0,{nx + 2 * PAD - 1}])")
            z = d64[ri, ci]
            w = wy[:, j] * wx[:, i]
            if has_nan:
                m = np.isnan(z)
                if m.any():
                    z = np.where(m, 0.0, z)
                    w = np.where(m, 0.0, w)
            z_sum += z * w
            w_sum += w

    # Threshold + normalize, gmt_bcr.c:268-275
    GMT_CONV8_LIMIT = 1.0e-8
    valid = (w_sum + GMT_CONV8_LIMIT - threshold) > 0.0
    out = np.full(Nq, np.nan, dtype=np.float64)
    np.divide(z_sum, w_sum, out=out, where=valid & (w_sum != 0.0))
    return out.astype(np.float32)


def _grid_fill(data: np.ndarray, x: np.ndarray, y: np.ndarray,
               donor: np.ndarray, donor_x: np.ndarray,
               donor_y: np.ndarray) -> np.ndarray:
    """-Ag fill: replace each NaN with bicubic sample of donor at (x, y)."""
    out = data.astype(np.float32, copy=True)
    mask = np.isnan(out)
    if not mask.any():
        return out
    rows, cols = np.nonzero(mask)
    qx = x[cols]
    qy = y[rows]
    vals = _bcr_bicubic_sample(donor, donor_x, donor_y, qx, qy)
    out[rows, cols] = vals
    return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def gmt_grdfill_py(
    data: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    *,
    algorithm: str = 'g',
    constant: Optional[float] = None,
    radius: int = -1,
    donor: Optional[np.ndarray] = None,
    donor_x: Optional[np.ndarray] = None,
    donor_y: Optional[np.ndarray] = None,
    nodata_value: Optional[float] = None,
) -> np.ndarray:
    """In-process ``gmt grdfill`` port.

    Parameters
    ----------
    data : 2-D float array, shape ``(ny, nx)``
        Grid in y-ascending orientation (``data[0, :]`` -> ``y[0]``, the
        smallest y).  NaN marks holes.  Cast to float32 internally.
    x, y : 1-D arrays
        Coordinate vectors.  Must be uniformly spaced + ascending.
    algorithm : str
        ``'c'`` -> constant fill (``constant=`` required).
        ``'n'`` -> Eric Xu nearest neighbour.  ``radius`` is max integer
                   shell radius (-1 -> default).
        ``'g'`` -> bilinear sample from donor grid (``donor / donor_x /
                   donor_y`` required).
        ``'s'`` -> NotImplementedError (greenspline path not ported).
    constant : float
        Required when ``algorithm='c'``.
    radius : int
        Max integer shell radius for ``algorithm='n'``.
    donor, donor_x, donor_y :
        Donor grid + coords for ``algorithm='g'``.
    nodata_value : float
        Alternate hole sentinel.  Cells equal to this value are treated
        as NaN before filling (mirrors GMT's ``-N`` option,
        grdfill.c:622-627; uses ``floatAlmostEqualZero``).

    Returns
    -------
    filled : 2-D float32 array, same shape as ``data``.

    Notes
    -----
    The original ``grid`` is not modified.  Output dtype is always float32
    so the result matches GMT's on-disk format byte-for-byte after a
    round-trip through ``gmt_grd_io.write_gmt_grd``.
    """
    if data.ndim != 2:
        raise ValueError(f"data must be 2-D, got shape {data.shape}")
    data = np.asarray(data, dtype=np.float32)
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    ny, nx = data.shape
    if x.shape != (nx,):
        raise ValueError(f"x must have length nx={nx}, got {x.shape}")
    if y.shape != (ny,):
        raise ValueError(f"y must have length ny={ny}, got {y.shape}")

    # -N pre-substitution (grdfill.c:622-627).  GMT uses
    # ``floatAlmostEqualZero``, which for float32 is ~ULP-level equal.
    if nodata_value is not None:
        # Match the C: cast sentinel to float32 then exact equality after
        # the cast.  ``floatAlmostEqualZero`` in GMT is effectively
        # ``fabs(a-b) <= 5*FLT_EPSILON*max(|a|,|b|)``; we use the
        # float32-cast equality test which is bit-equivalent for the
        # sentinel-value substitution case (the sentinel always round-
        # trips through float32).
        sentinel = np.float32(nodata_value)
        eps = np.finfo(np.float32).eps * 5.0 * max(abs(float(sentinel)), 1.0)
        data = data.copy()
        data[np.abs(data - sentinel) <= eps] = np.float32(np.nan)

    algo = algorithm.lower()
    if algo == 'c':
        if constant is None:
            raise ValueError("algorithm='c' requires constant=<float>")
        return _constant_fill(data, float(constant))

    if algo == 'n':
        return _nearest_fill(data, radius=radius)

    if algo == 'g':
        if donor is None or donor_x is None or donor_y is None:
            raise ValueError(
                "algorithm='g' requires donor, donor_x, donor_y")
        donor = np.asarray(donor, dtype=np.float32)
        donor_x = np.asarray(donor_x, dtype=np.float64)
        donor_y = np.asarray(donor_y, dtype=np.float64)
        if donor.ndim != 2:
            raise ValueError(f"donor must be 2-D, got {donor.shape}")
        if donor.shape != (donor_y.size, donor_x.size):
            raise ValueError(
                f"donor shape {donor.shape} != "
                f"(len(donor_y)={donor_y.size}, len(donor_x)={donor_x.size})")
        return _grid_fill(data, x, y, donor, donor_x, donor_y)

    if algo == 's':
        raise NotImplementedError(
            "algorithm='s' (-As spline) is not ported - it delegates to "
            "GMT's greenspline module (~10 kLOC). dem2topo_ra and the "
            "rest of the fork's gmt grdfill consumers use -Ag exclusively.")

    raise ValueError(
        f"unknown algorithm={algorithm!r}; expected one of "
        "'c' (constant), 'n' (nearest), 'g' (grid)")


# ---------------------------------------------------------------------------
# File-to-file convenience wrapper (parallels gmt_grdsample_py / gmt_grdcut_py)
# ---------------------------------------------------------------------------

def gmt_grdfill_py_file(
    in_path: str,
    out_path: str,
    *,
    algorithm: str = 'g',
    constant: Optional[float] = None,
    radius: int = -1,
    donor_path: Optional[str] = None,
    nodata_value: Optional[float] = None,
) -> None:
    """File-to-file wrapper.

    Reads ``in_path`` (and ``donor_path`` if ``algorithm='g'``) via
    :func:`gmt_grd_io.read_gmt_grd`, runs :func:`gmt_grdfill_py`, writes
    via :func:`gmt_grd_io.write_gmt_grd` preserving metadata
    (registration, geographic flag).
    """
    # Local import: keep the array-level entry point importable without
    # the netCDF4 dependency.
    from gmt_grd_io import read_gmt_grd, write_gmt_grd

    z, x, y, info = read_gmt_grd(in_path)

    donor = donor_x = donor_y = None
    if algorithm.lower() == 'g':
        if donor_path is None:
            raise ValueError("algorithm='g' requires donor_path")
        donor, donor_x, donor_y, _ = read_gmt_grd(donor_path)

    out = gmt_grdfill_py(z, x, y,
                         algorithm=algorithm,
                         constant=constant,
                         radius=radius,
                         donor=donor, donor_x=donor_x, donor_y=donor_y,
                         nodata_value=nodata_value)

    write_gmt_grd(out_path, out, x, y,
                  node_offset=int(info.get('node_offset', 0)),
                  geographic=bool(info.get('geographic', False)),
                  title=info.get('title', ''),
                  history=f"gmt_grdfill_py -A{algorithm}",
                  description=info.get('description', ''))


# ---------------------------------------------------------------------------
# Module diagnostics
# ---------------------------------------------------------------------------

def _selftest() -> None:
    """Round-trip smoke: synthetic grid with hole, fill via each algorithm."""
    nx, ny = 17, 13
    x = np.arange(nx, dtype=np.float64)
    y = np.arange(ny, dtype=np.float64)
    xg, yg = np.meshgrid(x, y)
    z = (np.sin(xg * 0.3) * np.cos(yg * 0.4)).astype(np.float32)
    z_hole = z.copy()
    z_hole[4:9, 5:11] = np.nan

    # Constant fill
    f_c = gmt_grdfill_py(z_hole, x, y, algorithm='c', constant=999.0)
    assert not np.isnan(f_c).any()
    assert (f_c[4:9, 5:11] == 999.0).all()
    assert np.array_equal(f_c[0, 0], z_hole[0, 0])

    # Nearest fill
    f_n = gmt_grdfill_py(z_hole, x, y, algorithm='n')
    assert not np.isnan(f_n).any()

    # Grid (-Ag) fill: donor = original z
    f_g = gmt_grdfill_py(z_hole, x, y, algorithm='g',
                         donor=z, donor_x=x, donor_y=y)
    assert not np.isnan(f_g).any()
    # At the hole positions, bilinear at integer coords = donor node value
    np.testing.assert_array_equal(f_g[4:9, 5:11], z[4:9, 5:11])
    print("gmt_grdfill_py self-test OK")


if __name__ == '__main__':
    _selftest()
