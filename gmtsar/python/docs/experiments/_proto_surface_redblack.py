"""_proto_surface_redblack.py — PROTOTYPE ONLY.  NOT wired into the pipeline.

9-color parallel SOR variant of the GMT biharmonic-spline-in-tension surface
solver, using numba prange for intra-color parallelism.

WHY 9 COLORS (not 2)
--------------------
The Briggs (1974) biharmonic stencil implemented in surface.c has 12 nodes:
  N2(-2,0), NW(-1,-1), N1(-1,0), NE(-1,+1), W2(0,-2), W1(0,-1),
  E1(0,+1), E2(0,+2), SW(+1,-1), S1(+1,0), SE(+1,+1), S2(+2,0)
Maximum reach is +-2 cells in both row and column directions.

A classic 2-color (red/black checkerboard) assigns color = (row+col) mod 2.
Two same-color nodes can be at (dr,dc)=(+1,+1), (0,+2), (+2,0) etc. — all
within stencil reach.  A naive red/black split would therefore let same-color
nodes read stale neighbors, producing a WRONG update formula.

The minimum safe coloring is color = (row mod 3, col mod 3) -> 9 colors.
Within one color: dr = k*3, dc = l*3. Since max stencil |dr|<=2 < 3 and
|dc|<=2 < 3, any nonzero (dr,dc) with |dr|,|dc|<=2 has (dr mod 3, dc mod 3)
!= (0,0).  Verification: all 12 stencil offsets produce non-(0,0) residuals
(confirmed algebraically in the coloring-analysis script).

CONVERGENCE vs GS-SOR
----------------------
Each 9-color SOR sweep applies omega*new + (1-omega)*old, but reads
*non-updated* neighbors within the same pass (Jacobi-like per color, but
inter-color dependencies are respected).  This is strictly weaker than GS-SOR
(which reads immediately-updated neighbors in the same sweep) and will
generally need more iterations to reach the same tolerance.  The key tradeoff:
  GS-SOR: serial (each row is data-dependent on the previous), 1 thread.
  9-color SOR: parallel (nodes within a color are independent), N threads.
For the speedup to pay off, N*iterations_per_color_sweep must beat 1*GS_iterations.

IMPLEMENTATION NOTES
--------------------
- Float32 grid (matches gmt_grdfloat) — same arithmetic contract as production kernel.
- Boundary conditions (set_bcs) are applied once per full sweep (all 9 passes),
  matching the production pattern (BCs applied before each GS sweep).
- The BCs are NOT parallelized here; they touch boundary rows/cols sequentially.
  BCs are O(nx+ny), negligible vs interior O(nx*ny).
- Convergence check: max|du| across ALL 9 passes in one full sweep, same as
  the production GS-SOR max_u_change.

HOW TO BENCHMARK
----------------
Run the standalone __main__ block at the bottom of this file.
"""
from __future__ import annotations

import os
import sys
import time
import math
import importlib

import numpy as np

# ---------------------------------------------------------------------------
# Import gmt_surface_py internals needed for setup (not the GS-SOR kernel).
# We reuse _compute_coefficients, _bc_constants, _d_node, _P_INDICES,
# _prime_factors, _gcd, _optimal_dim_for_surface, _solve_briggs_b_vec,
# _remove_planar_trend, _restore_planar_trend, _fill_in_forecast,
# _set_bcs (for BC application).
# ---------------------------------------------------------------------------
_UTILS = os.path.dirname(os.path.abspath(__file__))
if _UTILS not in sys.path:
    sys.path.insert(0, _UTILS)

import gmt_surface_py as _gsm

_compute_coefficients   = _gsm._compute_coefficients
_bc_constants           = _gsm._bc_constants
_d_node                 = _gsm._d_node
_P_INDICES              = _gsm._P_INDICES
_prime_factors          = _gsm._prime_factors
_gcd                    = _gsm._gcd
_optimal_dim_for_surface = _gsm._optimal_dim_for_surface
_solve_briggs_b_vec     = _gsm._solve_briggs_b_vec
_remove_planar_trend    = _gsm._remove_planar_trend
_restore_planar_trend   = _gsm._restore_planar_trend
_fill_in_forecast       = _gsm._fill_in_forecast
_set_bcs                = _gsm._set_bcs

_SURFACE_CONV_LIMIT      = _gsm._SURFACE_CONV_LIMIT
_SURFACE_MAX_ITERATIONS  = _gsm._SURFACE_MAX_ITERATIONS
_SURFACE_OVERRELAXATION  = _gsm._SURFACE_OVERRELAXATION
_SURFACE_CLOSENESS_FACTOR = _gsm._SURFACE_CLOSENESS_FACTOR
_STAT_UNCONSTRAINED      = _gsm._STAT_UNCONSTRAINED
_STAT_CONSTRAINED        = _gsm._STAT_CONSTRAINED

_N2, _NW, _N1, _NE, _W2, _W1, _E1, _E2, _SW, _S1, _SE, _S2 = range(12)

# ---------------------------------------------------------------------------
# Numba parallel kernel — 9-color SOR
# ---------------------------------------------------------------------------
try:
    from numba import njit, prange
    _HAVE_NUMBA = True
except ImportError:
    _HAVE_NUMBA = False
    def njit(*a, **kw):  # type: ignore
        def d(f): return f
        return d(a[0]) if (len(a)==1 and callable(a[0]) and not kw) else d
    prange = range

# NOTE: fastmath=False to preserve float32 rounding order.
# parallel=True enables prange -> threads.
@njit(parallel=True, fastmath=False, cache=True)
def _iterate_once_9color(
        u,                   # float32[::1]
        status,              # uint8[::1]
        briggs_b,            # float32[:,::1]  shape (N_briggs, 6)
        briggs_idx,          # int64[::1]
        coeff_unc,           # float64[::1] 12 weights
        coeff_con,           # float64[::1] 12 weights
        d_node,              # int64[::1]  12 offsets
        p_indices,           # int64[:,::1] (5,4)
        a0_const_2,          # float64
        relax_old,           # float64 = 1 - omega
        relax_new,           # float64 = omega
        node_nw,             # int64
        current_nx,          # int
        current_ny,          # int
        current_mx,          # int
):
    """One full 9-color parallel SOR sweep.  Returns max |u_change|.

    The 9-color scheme: color = (row % 3) * 3 + (col % 3), values 0..8.
    All nodes of the same color are mutually outside each other's stencil reach
    (stencil max |dr| and |dc| both <= 2 < 3), so they can be updated in parallel.
    Within each color pass we iterate row_base in {0,1,2} and col_base in {0,1,2},
    collecting all (row, col) such that row%3==row_base and col%3==col_base.
    """
    # Hoist stencil offsets to local scalars (register-friendly)
    dN2 = d_node[0];  dNW = d_node[1];  dN1 = d_node[2];  dNE = d_node[3]
    dW2 = d_node[4];  dW1 = d_node[5];  dE1 = d_node[6];  dE2 = d_node[7]
    dSW = d_node[8];  dS1 = d_node[9];  dSE = d_node[10]; dS2 = d_node[11]

    # Hoist weights
    cuN2 = coeff_unc[0];  cuNW = coeff_unc[1];  cuN1 = coeff_unc[2];  cuNE = coeff_unc[3]
    cuW2 = coeff_unc[4];  cuW1 = coeff_unc[5];  cuE1 = coeff_unc[6];  cuE2 = coeff_unc[7]
    cuSW = coeff_unc[8];  cuS1 = coeff_unc[9];  cuSE = coeff_unc[10]; cuS2 = coeff_unc[11]

    ccN2 = coeff_con[0];  ccNW = coeff_con[1];  ccN1 = coeff_con[2];  ccNE = coeff_con[3]
    ccW2 = coeff_con[4];  ccW1 = coeff_con[5];  ccE1 = coeff_con[6];  ccE2 = coeff_con[7]
    ccSW = coeff_con[8];  ccS1 = coeff_con[9];  ccSE = coeff_con[10]; ccS2 = coeff_con[11]

    max_u_change = np.float64(-1.0)

    # 9-color passes: rb=row_base in {0,1,2}, cb=col_base in {0,1,2}
    for rb in range(3):
        for cb in range(3):
            # Number of rows with row%3==rb in [0, current_ny)
            # rows: rb, rb+3, rb+6, ...
            n_rows_color = (current_ny - rb + 2) // 3
            n_cols_color = (current_nx - cb + 2) // 3

            # Parallel over rows of this color
            for ri in prange(n_rows_color):  # noqa: E501
                row = rb + ri * 3
                local_max = np.float64(-1.0)

                node_base = node_nw + row * current_mx + cb
                ci = np.int64(0)
                while ci < n_cols_color:
                    col = cb + ci * 3
                    node = node_base + ci * 3

                    stat = status[node]
                    if stat == np.uint8(5):  # SURFACE_IS_CONSTRAINED
                        ci += np.int64(1)
                        continue

                    if stat == np.uint8(0):  # UNCONSTRAINED
                        u_00 = (np.float64(u[node + dN2]) * cuN2
                                + np.float64(u[node + dNW]) * cuNW
                                + np.float64(u[node + dN1]) * cuN1
                                + np.float64(u[node + dNE]) * cuNE
                                + np.float64(u[node + dW2]) * cuW2
                                + np.float64(u[node + dW1]) * cuW1
                                + np.float64(u[node + dE1]) * cuE1
                                + np.float64(u[node + dE2]) * cuE2
                                + np.float64(u[node + dSW]) * cuSW
                                + np.float64(u[node + dS1]) * cuS1
                                + np.float64(u[node + dSE]) * cuSE
                                + np.float64(u[node + dS2]) * cuS2)
                    else:  # constrained: stat in 1..4
                        u_00 = (np.float64(u[node + dN2]) * ccN2
                                + np.float64(u[node + dNW]) * ccNW
                                + np.float64(u[node + dN1]) * ccN1
                                + np.float64(u[node + dNE]) * ccNE
                                + np.float64(u[node + dW2]) * ccW2
                                + np.float64(u[node + dW1]) * ccW1
                                + np.float64(u[node + dE1]) * ccE1
                                + np.float64(u[node + dE2]) * ccE2
                                + np.float64(u[node + dSW]) * ccSW
                                + np.float64(u[node + dS1]) * ccS1
                                + np.float64(u[node + dSE]) * ccSE
                                + np.float64(u[node + dS2]) * ccS2)
                        bidx = briggs_idx[node]
                        p0 = p_indices[stat, 0]
                        p1 = p_indices[stat, 1]
                        p2 = p_indices[stat, 2]
                        p3 = p_indices[stat, 3]
                        # Float32 products (same arithmetic contract as production kernel)
                        prod0 = briggs_b[bidx, 0] * u[node + d_node[p0]]
                        prod1 = briggs_b[bidx, 1] * u[node + d_node[p1]]
                        prod2 = briggs_b[bidx, 2] * u[node + d_node[p2]]
                        prod3 = briggs_b[bidx, 3] * u[node + d_node[p3]]
                        sum_bk_uk = (np.float64(prod0) + np.float64(prod1)
                                     + np.float64(prod2) + np.float64(prod3))
                        u_00 = ((u_00 + a0_const_2
                                 * (sum_bk_uk + np.float64(briggs_b[bidx, 4])))
                                * np.float64(briggs_b[bidx, 5]))

                    old = np.float64(u[node])
                    u_00 = old * relax_old + u_00 * relax_new
                    change = u_00 - old
                    if change < 0.0:
                        change = -change
                    if change > local_max:
                        local_max = change
                    u[node] = np.float32(u_00)  # quantize to float32
                    ci += np.int64(1)

                # Thread-local max -> global max (reduction)
                if local_max > max_u_change:
                    max_u_change = local_max

    return max_u_change


# ---------------------------------------------------------------------------
# Top-level solver — same API signature as gmt_surface_py.gmt_surface_py
# so we can compare outputs directly.
# ---------------------------------------------------------------------------
def surface_9color(
        x: np.ndarray, y: np.ndarray, z: np.ndarray,
        region, inc,
        tension: float = 0.0,
        max_iter: int = _SURFACE_MAX_ITERATIONS,
        tol: float = _SURFACE_CONV_LIMIT,
        omega: float = _SURFACE_OVERRELAXATION,
        verbose: bool = False,
        pixel_reg: bool = False,
        alpha = None,
        # back-compat
        use_multigrid: bool = True,
        mg_max_level=None,
        mg_nu_coarse=None,
):
    """9-color parallel SOR variant — PROTOTYPE, NOT production-wired.

    Solves the same biharmonic PDE as gmt_surface_py using a 9-color
    (row%3, col%3) independent-node partitioning that allows prange
    parallelism within each color pass.

    Returns (grid, n_total_iters) where grid matches gmt_surface_py's
    return shape/convention (row 0 = SOUTH, ascending y).
    """
    x = np.ascontiguousarray(x, dtype=np.float64)
    y = np.ascontiguousarray(y, dtype=np.float64)
    z = np.ascontiguousarray(z, dtype=np.float64)
    if x.shape != y.shape or x.shape != z.shape:
        raise ValueError("x, y, z must have the same shape")
    if x.ndim != 1:
        raise ValueError("x, y, z must be 1-D")

    xmin, xmax, ymin, ymax = (float(v) for v in region)
    dx, dy = float(inc[0]), float(inc[1])
    if alpha is None:
        alpha = 1.0
    alpha = float(alpha)

    # Region expansion (mirrors gmt_surface_py)
    n_columns_u = int(round((xmax - xmin) / dx))
    n_rows_u    = int(round((ymax - ymin) / dy))
    crop_x0 = 0
    crop_y0 = 0
    crop_nx = n_columns_u + 1
    crop_ny = n_rows_u + 1

    sug = _optimal_dim_for_surface(n_columns_u, n_rows_u)
    if sug is not None:
        sug_nx, sug_ny, _factor = sug
        m_x = sug_nx - n_columns_u
        m_y = sug_ny - n_rows_u
        half_x = m_x // 2
        xmin_exp = xmin - half_x * dx
        xmax_exp = xmax + half_x * dx
        if m_x % 2:
            xmax_exp += dx
        half_y = m_y // 2
        ymin_exp = ymin - half_y * dy
        ymax_exp = ymax + half_y * dy
        if m_y % 2:
            ymax_exp += dy
        crop_x0 = half_x
        crop_y0 = half_y
        crop_nx = n_columns_u + 1
        crop_ny = n_rows_u + 1
        xmin, xmax, ymin, ymax = xmin_exp, xmax_exp, ymin_exp, ymax_exp

    # Pixel registration (mirrors gmt_surface_py)
    if pixel_reg:
        nx_pixel = int(round((xmax - xmin) / dx))
        ny_pixel = int(round((ymax - ymin) / dy))
        if sug is not None:
            xmin_s, xmax_s, ymin_s, ymax_s = xmin, xmax, ymin, ymax
        else:
            xmin_s = xmin + dx / 2.0
            xmax_s = xmax + dx / 2.0
            ymin_s = ymin + dy / 2.0
            ymax_s = ymax + dy / 2.0
        n_columns = nx_pixel + 1
        n_rows    = ny_pixel + 1
    else:
        n_columns = int(round((xmax - xmin) / dx)) + 1
        n_rows    = int(round((ymax - ymin) / dy)) + 1
        xmin_s, xmax_s, ymin_s, ymax_s = xmin, xmax, ymin, ymax
        nx_pixel = n_columns
        ny_pixel = n_rows

    if n_columns < 4 or n_rows < 4:
        raise ValueError(f"grid {n_rows}x{n_columns} too small (need >=4)")

    # Filter scatter
    wesn_lim_x_lo = xmin_s - dx
    wesn_lim_x_hi = xmax_s + dx
    wesn_lim_y_lo = ymin_s - dy
    wesn_lim_y_hi = ymax_s + dy
    keep = ((x >= wesn_lim_x_lo) & (x <= wesn_lim_x_hi)
            & (y >= wesn_lim_y_lo) & (y <= wesn_lim_y_hi)
            & np.isfinite(z))
    xx_in = x[keep]
    yy_in = y[keep]
    z_in  = z[keep]
    if xx_in.size == 0:
        raise ValueError("no input data inside region")

    # throw_away_unusables (mirrors gmt_surface_py exactly)
    _r_ix = 1.0 / dx
    _r_iy = 1.0 / dy
    _fc = (xx_in - xmin_s) * _r_ix
    _frow_raw = (yy_in - ymin_s) * _r_iy
    _c1 = np.floor(_fc + 0.5).astype(np.int64)
    _r1 = (n_rows - 1) - np.floor(_frow_raw + 0.5).astype(np.int64)
    _ok = ((_c1 >= 0) & (_c1 < n_columns) & (_r1 >= 0) & (_r1 < n_rows))
    _dx1 = _fc[_ok] - _c1[_ok]
    _frow_raw_ok = _frow_raw[_ok]
    _dy1 = _frow_raw_ok - ((n_rows - 1) - _r1[_ok])
    if pixel_reg:
        _d2 = (dx * (_dx1 + 0.5)) ** 2 + (dy * (_dy1 + 0.5)) ** 2
    else:
        _d2 = (dx * _dx1) ** 2 + (dy * _dy1) ** 2
    _idx = _r1[_ok] * n_columns + _c1[_ok]
    _ord = np.lexsort((_d2, _idx))
    _idx_s = _idx[_ord]
    _uniq = np.empty(_idx_s.size, dtype=bool)
    _uniq[0] = True
    _uniq[1:] = _idx_s[1:] != _idx_s[:-1]
    _keep2 = np.where(_ok)[0][_ord][_uniq]
    xx_in = xx_in[_keep2]
    yy_in = yy_in[_keep2]
    z_in  = z_in[_keep2]

    # Cast to float32 (matching C storage)
    xx_in = xx_in.astype(np.float32).astype(np.float64)
    yy_in = yy_in.astype(np.float32).astype(np.float64)
    z_in  = z_in.astype(np.float32).astype(np.float64)

    # Planar trend
    x_frac_pts   = (xx_in - xmin_s) / dx
    y_up_frac_pts = (yy_in - ymin_s) / dy
    plane_icept, plane_sx, plane_sy, _ = _remove_planar_trend(
        x_frac_pts, y_up_frac_pts, z_in)
    _plane_vals_f32 = (plane_icept + plane_sx * x_frac_pts
                       + plane_sy * y_up_frac_pts).astype(np.float32)
    z_det = z_in.astype(np.float32) - _plane_vals_f32

    # Rescale z
    ssz   = float((z_det.astype(np.float64) ** 2).sum())
    z_rms = math.sqrt(ssz / z_det.size)
    if z_rms < 1e-8:
        grid = np.zeros((n_rows, n_columns), dtype=np.float64)
        grid_final = _restore_planar_trend(grid, n_rows, n_columns,
                                           plane_icept, plane_sx, plane_sy, 1.0)
        if pixel_reg:
            if sug is not None:
                grid_final = grid_final[1:ny_pixel + 1, :nx_pixel]
            else:
                grid_final = grid_final[:ny_pixel, :nx_pixel]
        grid_final = grid_final[::-1, :]
        if sug is not None:
            if pixel_reg:
                grid_final = grid_final[crop_y0:crop_y0 + (crop_ny - 1),
                                        crop_x0:crop_x0 + (crop_nx - 1)]
            else:
                grid_final = grid_final[crop_y0:crop_y0 + crop_ny,
                                        crop_x0:crop_x0 + crop_nx]
        return np.ascontiguousarray(grid_final), 0

    r_z_rms = 1.0 / z_rms
    z_norm  = z_det * np.float32(r_z_rms)

    converge_limit_n = tol

    # Stencil coefficients and BC constants
    (coeff_unc, coeff_con, a0_const_1, a0_const_2,
     eps_p2, eps_m2, two_plus_ep2, two_plus_em2,
     _alpha2_doubled) = _compute_coefficients(alpha, tension)
    x0c, x1c, y0c, y1c = _bc_constants(tension, alpha)

    # Stride hierarchy
    current_stride = _gcd(n_columns - 1, n_rows - 1)
    factors = _prime_factors(current_stride)
    factors.sort()
    while True:
        cur_nx = (n_columns - 1) // current_stride + 1
        cur_ny = (n_rows - 1) // current_stride + 1
        if cur_nx >= 4 and cur_ny >= 4:
            break
        if not factors:
            raise ValueError("grid dimensions cannot factor down to 4x4")
        current_stride //= factors.pop()

    final_mx = n_columns + 4
    final_my = n_rows + 4
    mxmy = final_mx * final_my
    u      = np.zeros(mxmy, dtype=np.float32)
    status = np.zeros(mxmy, dtype=np.uint8)
    briggs_idx_shared = np.full(mxmy, -1, dtype=np.int64)
    briggs_idx_dirty: list = []

    cur_nx = (n_columns - 1) // current_stride + 1
    cur_ny = (n_rows - 1) // current_stride + 1
    cur_mx = cur_nx + 4
    node_nw = 2 * cur_mx + 2
    node_sw = node_nw + (cur_ny - 1) * cur_mx
    node_se = node_sw + cur_nx - 1
    node_ne = node_nw + cur_nx - 1
    d_node  = _d_node(cur_mx)

    # Helpers — identical logic to gmt_surface_py (same closure variables)
    def _build_constraints(stride, cur_nx_, cur_ny_):
        inc_x = stride * dx;  r_inc_x = 1.0 / inc_x
        inc_y = stride * dy;  r_inc_y = 1.0 / inc_y
        fcol     = (xx_in - xmin_s) * r_inc_x
        frow_raw = (yy_in - ymin_s) * r_inc_y
        col_near = np.floor(fcol + 0.5).astype(np.int64)
        row_near = (cur_ny_ - 1) - np.floor(frow_raw + 0.5).astype(np.int64)
        inside   = ((col_near >= 0) & (col_near < cur_nx_)
                    & (row_near >= 0) & (row_near < cur_ny_))
        if not inside.any():
            return (np.zeros(0, np.int64), np.zeros(0, np.int64),
                    np.zeros(0), np.zeros(0), np.zeros(0))
        col_near = col_near[inside]; row_near = row_near[inside]
        fcol_in  = fcol[inside];     frow_raw_in = frow_raw[inside]
        z_norm_in = z_norm[inside]
        dx_off   = fcol_in - col_near
        dy_off   = frow_raw_in - (cur_ny_ - 1) + row_near
        index    = row_near * cur_nx_ + col_near
        if pixel_reg:
            dist2 = (inc_x * (dx_off + 0.5 / stride)) ** 2 + (inc_y * (dy_off + 0.5 / stride)) ** 2
        else:
            dist2 = (inc_x * dx_off) ** 2 + (inc_y * dy_off) ** 2
        order    = np.lexsort((dist2, index))
        index_s  = index[order]
        dx_s = dx_off[order]; dy_s = dy_off[order]
        z_s  = z_norm_in[order]; col_s = col_near[order]; row_s = row_near[order]
        uniq    = np.empty(index_s.size, dtype=bool)
        uniq[0] = True; uniq[1:] = (index_s[1:] != index_s[:-1])
        return (col_s[uniq], row_s[uniq], dx_s[uniq], dy_s[uniq], z_s[uniq])

    def _assign_constraints(stride, cur_nx_, cur_ny_, cur_mx_, node_nw_):
        col_u, row_u, dx_u, dy_u, z_u = _build_constraints(stride, cur_nx_, cur_ny_)
        _rows   = node_nw_ + np.arange(cur_ny_, dtype=np.int64) * cur_mx_
        _idx_flat = (_rows[:, None] + np.arange(cur_nx_, dtype=np.int64)[None, :]).ravel()
        status[_idx_flat] = 0
        n_pts   = col_u.size
        briggs_b = np.zeros((max(n_pts, 1), 6), dtype=np.float32)
        briggs_idx = briggs_idx_shared
        if briggs_idx_dirty:
            briggs_idx[briggs_idx_dirty[0]] = -1
            briggs_idx_dirty.clear()
        if n_pts > 0:
            col_arr = col_u.astype(np.int64, copy=False)
            row_arr = row_u.astype(np.int64, copy=False)
            dx_arr  = dx_u.astype(np.float64, copy=False)
            dy_arr  = dy_u.astype(np.float64, copy=False)
            z_arr   = z_u.astype(np.float64, copy=False)
            nodes   = node_nw_ + row_arr * cur_mx_ + col_arr

            on_node = ((np.abs(dx_arr) < _SURFACE_CLOSENESS_FACTOR)
                       & (np.abs(dy_arr) < _SURFACE_CLOSENESS_FACTOR))
            if on_node.any():
                on_idx  = nodes[on_node]
                status[on_idx] = 5
                _corr  = np.float32(r_z_rms * stride
                                    * (plane_sx * dx_arr[on_node] + plane_sy * dy_arr[on_node]))
                u[on_idx] = z_arr[on_node].astype(np.float32) + _corr

            off = ~on_node
            if off.any():
                off_nodes = nodes[off]
                dx_off_   = dx_arr[off]; dy_off_ = dy_arr[off]; z_off_ = z_arr[off]
                dy_ge0 = dy_off_ >= 0.0; dx_ge0 = dx_off_ >= 0.0
                quad   = np.where(dy_ge0, np.where(dx_ge0, 1, 2), np.where(dx_ge0, 4, 3)).astype(np.uint8)
                xx_b   = np.where(dy_ge0, np.where(dx_ge0, dx_off_, dy_off_), np.where(dx_ge0, -dy_off_, -dx_off_))
                yy_b   = np.where(dy_ge0, np.where(dx_ge0, dy_off_, -dx_off_), np.where(dx_ge0, dx_off_, -dy_off_))
                _b_block = _solve_briggs_b_vec(xx_b, yy_b, z_off_, a0_const_1, a0_const_2)
                n_off  = off_nodes.size
                briggs_b[:n_off] = _b_block
                status[off_nodes] = quad
                briggs_idx[off_nodes] = np.arange(n_off, dtype=np.int64)
                briggs_idx_dirty.append(off_nodes)
                cnt = n_off
            else:
                cnt = 0
        else:
            cnt = 0
        return briggs_b[:max(cnt, 1)], briggs_idx

    total_iters = 0

    def _iterate_to_converge_9c(stride, cur_nx_, cur_ny_, cur_mx_,
                                 node_nw_, node_sw_, node_se_, node_ne_,
                                 d_node_, briggs_b_, briggs_idx_, mode_label):
        nonlocal total_iters
        current_max_iter = max_iter * stride
        current_limit    = converge_limit_n / stride
        max_change       = float("inf")
        for it in range(1, current_max_iter + 1):
            _set_bcs(u, cur_nx_, cur_ny_, cur_mx_,
                     node_sw_, node_nw_, node_se_, node_ne_,
                     d_node_[_N2], d_node_[_NW], d_node_[_N1], d_node_[_NE],
                     d_node_[_W2], d_node_[_W1],
                     d_node_[_E1], d_node_[_E2],
                     d_node_[_SW], d_node_[_S1], d_node_[_SE], d_node_[_S2],
                     x0c, x1c, y0c, y1c, eps_p2, eps_m2,
                     two_plus_ep2, two_plus_em2)
            max_change = _iterate_once_9color(
                u, status, briggs_b_, briggs_idx_,
                coeff_unc, coeff_con, d_node_, _P_INDICES,
                a0_const_2, 1.0 - omega, omega,
                node_nw_, cur_nx_, cur_ny_, cur_mx_)
            total_iters += 1
            if max_change <= current_limit:
                if verbose:
                    print(f"[9color] stride={stride} {mode_label} "
                          f"converged at it={it} max|du|={max_change:.3e}")
                return it
            if verbose and (it % 200 == 0):
                print(f"[9color] stride={stride} {mode_label} it={it}"
                      f" max|du|={max_change:.3e} limit={current_limit:.3e}")
        if verbose:
            print(f"[9color] stride={stride} {mode_label} hit max_iter "
                  f"({current_max_iter}) last_change={max_change:.3e}")
        return current_max_iter

    # Coarsest stride: data-constrained
    briggs_b, briggs_idx = _assign_constraints(current_stride, cur_nx, cur_ny,
                                               cur_mx, node_nw)
    _iterate_to_converge_9c(current_stride, cur_nx, cur_ny, cur_mx,
                             node_nw, node_sw, node_se, node_ne, d_node,
                             briggs_b, briggs_idx, "DATA")

    # Down-stride loop
    previous_stride = current_stride
    previous_nx = cur_nx; previous_ny = cur_ny; previous_mx = cur_mx
    while current_stride > 1:
        if not factors:
            break
        current_stride //= factors.pop()
        cur_nx = (n_columns - 1) // current_stride + 1
        cur_ny = (n_rows - 1) // current_stride + 1
        cur_mx = cur_nx + 4
        node_nw = 2 * cur_mx + 2
        node_sw = node_nw + (cur_ny - 1) * cur_mx
        node_se = node_sw + cur_nx - 1
        node_ne = node_nw + cur_nx - 1
        d_node  = _d_node(cur_mx)

        _fill_in_forecast(u, status,
                          previous_nx, previous_ny, previous_mx,
                          cur_nx, cur_ny, cur_mx,
                          previous_stride, current_stride,
                          node_nw, node_ne)
        if briggs_idx_dirty:
            briggs_idx_shared[briggs_idx_dirty[0]] = -1
            briggs_idx_dirty.clear()
        briggs_b_empty = np.zeros((1, 6), dtype=np.float32)
        _iterate_to_converge_9c(current_stride, cur_nx, cur_ny, cur_mx,
                                 node_nw, node_sw, node_se, node_ne, d_node,
                                 briggs_b_empty, briggs_idx_shared, "NODES")
        briggs_b, briggs_idx = _assign_constraints(current_stride, cur_nx,
                                                   cur_ny, cur_mx, node_nw)
        _iterate_to_converge_9c(current_stride, cur_nx, cur_ny, cur_mx,
                                 node_nw, node_sw, node_se, node_ne, d_node,
                                 briggs_b, briggs_idx, "DATA")
        previous_stride = current_stride
        previous_nx = cur_nx; previous_ny = cur_ny; previous_mx = cur_mx

    # Extract output
    grid_norm = np.ascontiguousarray(
        u.reshape(final_my, final_mx)[2:n_rows + 2, 2:n_columns + 2])
    grid = _restore_planar_trend(grid_norm, n_rows, n_columns,
                                 plane_icept, plane_sx, plane_sy, z_rms)

    if pixel_reg:
        grid = grid[1:ny_pixel + 1, :nx_pixel]
    grid = grid[::-1, :]

    if sug is not None:
        if pixel_reg:
            crop_nx_px = crop_nx - 1; crop_ny_px = crop_ny - 1
            grid = grid[crop_y0:crop_y0 + crop_ny_px, crop_x0:crop_x0 + crop_nx_px]
        else:
            grid = grid[crop_y0:crop_y0 + crop_ny, crop_x0:crop_x0 + crop_nx]

    return np.ascontiguousarray(grid), total_iters


# ---------------------------------------------------------------------------
# Coloring validity self-check (runs at import if PROTO_VERIFY=1)
# ---------------------------------------------------------------------------
def _verify_coloring():
    """Assert no stencil offset maps to (dr%3, dc%3) == (0,0)."""
    offsets = [(-2,0),(-1,-1),(-1,0),(-1,1),(0,-2),(0,-1),(0,1),(0,2),
               (1,-1),(1,0),(1,1),(2,0)]
    for dr, dc in offsets:
        if (dr % 3 == 0) and (dc % 3 == 0):
            raise AssertionError(
                f"Coloring conflict: stencil offset ({dr},{dc}) has "
                f"(dr%3, dc%3)=(0,0) — same-color nodes would interact!")

_verify_coloring()


# ---------------------------------------------------------------------------
# Benchmark __main__ block
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import subprocess, struct, argparse, textwrap, time

    # numba's thread count must be set via set_num_threads() at runtime;
    # changing NUMBA_NUM_THREADS env after import has no effect.
    try:
        from numba import set_num_threads as _numba_set_threads
        from numba import get_num_threads as _numba_get_threads
    except ImportError:
        def _numba_set_threads(n): pass
        def _numba_get_threads(): return 1

    ap = argparse.ArgumentParser(
        description="Benchmark 9-color parallel SOR vs production GS-SOR vs gmt surface C")
    ap.add_argument("--small", default="/home/utig5/dliu/gmtsar/gmtsar/python/work/python_test/RS2_SLC_Hawaii/topo/trans.dat")
    ap.add_argument("--large", default="/home/utig5/dliu/gmtsar/gmtsar/python/work/python_test/S1A_SLC_TOPS_Greece/merge/trans.dat")
    ap.add_argument("--outdir", default="/home/utig5/dliu/gmtsar/gmtsar/python/work/proto_surface_test")
    ap.add_argument("--threads", default="1,2,4,8,16",
                    help="comma-separated NUMBA_NUM_THREADS values to sweep")
    ap.add_argument("--tension", type=float, default=0.5)
    ap.add_argument("--gmt", default="gmt")
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    GMT = args.gmt
    TENSION = args.tension
    thread_list = [int(t) for t in args.threads.split(",")]

    # ------------------------------------------------------------------ #
    # Dataset config
    # ------------------------------------------------------------------ #
    DX = 16 / 3600.0   # 16 arc-sec
    DY = 32 / 3600.0   # 32 arc-sec

    datasets = {
        "rs2_hawaii": {
            "path": args.small,
            # region from gmt gmtinfo -I16s/32s, negative-longitude form
            # (trans.dat stores -155.xxx; gmtinfo reports 204.xxx but both
            # gmt surface and the Python port accept the negative form directly)
            "region": (-155.493333333, -155.177777778, 19.2177777778, 19.5466666667),
            "ref_grd": os.path.join(args.outdir, "rs2_hawaii_ref.grd"),
        },
        "greece_tops": {
            "path": args.large,
            "region": (20.0, 23.0, 37.6622222222, 39.7422222222),
            "ref_grd": os.path.join(args.outdir, "greece_tops_ref.grd"),
        },
    }

    def read_trans_dat(path, region):
        """Read trans.dat (5-col binary float64, cols 3=lon 4=lat 2=topo)."""
        data = np.fromfile(path, dtype=np.float64).reshape(-1, 5)
        # cols: 0=range 1=az 2=topo 3=lon 4=lat
        lon  = data[:, 3]
        lat  = data[:, 4]
        topo = data[:, 2]
        xmin, xmax, ymin, ymax = region
        keep = ((lon >= xmin - DX) & (lon <= xmax + DX)
                & (lat >= ymin - DY) & (lat <= ymax + DY))
        return lon[keep], lat[keep], topo[keep]

    def read_grd_values(grd_path):
        """Read gmt netCDF grid as float32 array in NORTH-TO-SOUTH row order.

        gmt grd2xyz outputs rows north->south (lat decreasing).
        Our Python port returns grids in SOUTH-TO-NORTH order (row 0 = min lat).
        To compare element-wise, we flip the Python grid vertically before
        raveling (see compare_to_ref() below).
        """
        result = subprocess.run(
            [GMT, "grd2xyz", grd_path, "-bo3f"],
            capture_output=True, check=True)
        raw = np.frombuffer(result.stdout, dtype=np.float32).reshape(-1, 3)
        return raw[:, 2]   # z values, north-to-south row order

    def compare_to_ref(g_py, ref_z_ns, n_rows, n_cols):
        """Compare Python grid (row 0 = SOUTH) to grd2xyz output (row 0 = NORTH).

        g_py shape: (n_rows, n_cols), row 0 = min lat (SOUTH).
        ref_z_ns:   (n_rows * n_cols,), north-to-south from grd2xyz.
        Flips g_py so row 0 = NORTH before ravel + diff.
        """
        g_ns = g_py[::-1, :]   # row 0 = NORTH after flip
        diff = g_ns.ravel().astype(np.float64) - ref_z_ns.astype(np.float64)
        rms  = float(np.sqrt(np.mean(diff ** 2)))
        mx   = float(np.max(np.abs(diff)))
        return rms, mx

    # ------------------------------------------------------------------ #
    # Warm up numba JIT (first call compiles; not counted in timing)
    # ------------------------------------------------------------------ #
    print("Warming up numba JIT (small synthetic grid)...")
    _xw = np.random.default_rng(7).uniform(0, 1, 50).astype(np.float64)
    _yw = np.random.default_rng(7).uniform(0, 1, 50).astype(np.float64)
    _zw = np.sin(_xw * 6) + np.cos(_yw * 4)
    os.environ["NUMBA_NUM_THREADS"] = "1"
    surface_9color(_xw, _yw, _zw, (0,1,0,1), (0.05,0.05), tension=TENSION)
    print("  JIT warm-up done.")

    # Also warm up production gmt_surface_py (Cython or Numba)
    gmt_surface_py = _gsm.gmt_surface_py
    gmt_surface_py(_xw, _yw, _zw, (0,1,0,1), (0.05,0.05), tension=TENSION)
    print("  Production GS-SOR warm-up done.")

    # ------------------------------------------------------------------ #
    # Main benchmark loop
    # ------------------------------------------------------------------ #
    results = {}   # key: (dataset, scheme, nthreads) -> dict

    for dsname, dscfg in datasets.items():
        print(f"\n{'='*60}")
        print(f"Dataset: {dsname}")
        region = dscfg["region"]
        x_, y_, z_ = read_trans_dat(dscfg["path"], region)
        print(f"  Points after region filter: {x_.size:,}")
        print(f"  Region: {region}")

        # ---- gmt surface C reference (single-thread, 1 run) ----
        ref_grd = dscfg["ref_grd"]
        if not os.path.exists(ref_grd):
            print(f"  Generating C reference: {ref_grd}")
            R = f"-R{region[0]}/{region[1]}/{region[2]}/{region[3]}"
            env = os.environ.copy()
            env["OMP_NUM_THREADS"] = "1"
            t0 = time.perf_counter()
            subprocess.run(
                [GMT, "surface", dscfg["path"],
                 "-i3,4,2", "-bi5d", R, f"-I{DX}/{DY}",
                 f"-T{TENSION}", f"-G{ref_grd}"],
                env=env, check=True, capture_output=True)
            t_gmt_c = time.perf_counter() - t0
            print(f"  gmt surface C (1 thread): {t_gmt_c:.2f}s")
        else:
            # Re-time C binary for comparison
            R = f"-R{region[0]}/{region[1]}/{region[2]}/{region[3]}"
            env = os.environ.copy()
            env["OMP_NUM_THREADS"] = "1"
            t0 = time.perf_counter()
            subprocess.run(
                [GMT, "surface", dscfg["path"],
                 "-i3,4,2", "-bi5d", R, f"-I{DX}/{DY}",
                 f"-T{TENSION}", f"-G{ref_grd}"],
                env=env, check=True, capture_output=True)
            t_gmt_c = time.perf_counter() - t0
            print(f"  gmt surface C (1 thread): {t_gmt_c:.2f}s")

        ref_z = read_grd_values(ref_grd)   # north-to-south row order
        # Grid dimensions needed for flip in compare_to_ref
        import subprocess as _sp
        _info = _sp.run([GMT, "grdinfo", ref_grd, "-C"], capture_output=True, check=True, text=True)
        _cols = _info.stdout.split()
        _ref_nx = int(_cols[9]); _ref_ny = int(_cols[10])
        results[(dsname, "gmt_c", 1)] = {"wall": t_gmt_c, "iters": None}

        # ---- Production GS-SOR (Cython/Numba, 1 thread) ----
        env_orig = {k: os.environ.get(k) for k in ["NUMBA_NUM_THREADS", "OMP_NUM_THREADS"]}
        os.environ["NUMBA_NUM_THREADS"] = "1"
        os.environ["OMP_NUM_THREADS"] = "1"

        N_REPEAT = 3
        times_gsor = []
        for _ in range(N_REPEAT):
            t0 = time.perf_counter()
            g_gs = gmt_surface_py(x_, y_, z_, region, (DX, DY), tension=TENSION)
            times_gsor.append(time.perf_counter() - t0)
        t_gsor = min(times_gsor)
        print(f"  Production GS-SOR (1 thread, best of {N_REPEAT}): {t_gsor:.2f}s")
        results[(dsname, "gs_sor", 1)] = {"wall": t_gsor, "iters": None}

        # GS-SOR parity vs gmt C
        # Python grid: row 0 = SOUTH; grd2xyz: row 0 = NORTH — flip Python before diff
        rms_gs, max_gs = compare_to_ref(g_gs, ref_z, _ref_ny, _ref_nx)
        print(f"  GS-SOR parity vs gmt C:  RMS={rms_gs:.3e}m  max|diff|={max_gs:.3e}m")
        results[(dsname, "gs_sor", 1)]["rms_vs_c"] = rms_gs
        results[(dsname, "gs_sor", 1)]["max_vs_c"] = max_gs

        # ---- 9-color parallel SOR at each thread count ----
        for nthreads in thread_list:
            _numba_set_threads(nthreads)
            os.environ["NUMBA_NUM_THREADS"] = str(nthreads)
            times_9c = []
            iters_9c = []
            for _ in range(N_REPEAT):
                t0 = time.perf_counter()
                g9, nit = surface_9color(x_, y_, z_, region, (DX, DY), tension=TENSION)
                times_9c.append(time.perf_counter() - t0)
                iters_9c.append(nit)
            t_9c = min(times_9c)
            nit  = iters_9c[-1]
            print(f"  9-color SOR ({nthreads:2d} threads, best of {N_REPEAT}): {t_9c:.2f}s  iters={nit}")
            results[(dsname, "9color", nthreads)] = {"wall": t_9c, "iters": nit}

            if nthreads == thread_list[0]:   # parity only at first thread count
                rms9, max9 = compare_to_ref(g9, ref_z, _ref_ny, _ref_nx)
                print(f"  9-color parity vs gmt C: RMS={rms9:.3e}m  max|diff|={max9:.3e}m")
                for nt in thread_list:
                    if (dsname, "9color", nt) in results:
                        results[(dsname, "9color", nt)]["rms_vs_c"] = rms9
                        results[(dsname, "9color", nt)]["max_vs_c"] = max9

        # Restore env
        for k, v in env_orig.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    # ------------------------------------------------------------------ #
    # Print tables
    # ------------------------------------------------------------------ #
    print("\n\n" + "="*70)
    print("TABLE 1 — WALL-TIME AND SPEEDUP")
    print("="*70)
    fmt_h = f"{'Dataset':<15} {'Scheme':<12} {'Threads':>8} {'Wall(s)':>8} {'vs_GS':>8} {'vs_C':>8} {'Iters':>8}"
    print(fmt_h)
    print("-"*70)

    for dsname in ["rs2_hawaii", "greece_tops"]:
        t_c  = results.get((dsname, "gmt_c", 1), {}).get("wall", float('nan'))
        t_gs = results.get((dsname, "gs_sor", 1), {}).get("wall", float('nan'))
        # gmt C row
        print(f"{dsname:<15} {'gmt_C':<12} {'1':>8} {t_c:>8.2f} {'—':>8} {'1.00x':>8} {'—':>8}")
        # GS-SOR
        sp_c = t_c / t_gs if t_gs > 0 else float('nan')
        print(f"{dsname:<15} {'GS-SOR(Cy)':<12} {'1':>8} {t_gs:>8.2f} {'1.00x':>8} {f'{sp_c:.2f}x':>8} {'—':>8}")
        # 9-color
        for nt in thread_list:
            key9 = (dsname, "9color", nt)
            if key9 in results:
                t9   = results[key9]["wall"]
                nit  = results[key9]["iters"]
                sp_gs = t_gs / t9 if t9 > 0 else float('nan')
                sp_c2 = t_c  / t9 if t9 > 0 else float('nan')
                print(f"{dsname:<15} {'9color-SOR':<12} {nt:>8} {t9:>8.2f} {f'{sp_gs:.2f}x':>8} {f'{sp_c2:.2f}x':>8} {nit:>8}")
        print()

    print("\n" + "="*70)
    print("TABLE 2 — PARITY DELTA vs gmt surface C output")
    print("="*70)
    fmt_h2 = f"{'Dataset':<15} {'Scheme':<14} {'RMS(m)':>12} {'max|diff|(m)':>14}"
    print(fmt_h2)
    print("-"*70)
    for dsname in ["rs2_hawaii", "greece_tops"]:
        for scheme_label, scheme_key, nt in [("GS-SOR(Cy)", "gs_sor", 1),
                                              ("9color-SOR", "9color", thread_list[0])]:
            k = (dsname, scheme_key, nt)
            if k in results and "rms_vs_c" in results[k]:
                rms = results[k]["rms_vs_c"]
                mx  = results[k]["max_vs_c"]
                print(f"{dsname:<15} {scheme_label:<14} {rms:>12.4e} {mx:>14.4e}")
    print()

    print("RECOMMENDATION:")
    print("  See PROTO_surface_redblack.md in gmtsar/python/docs/ for full analysis.")
