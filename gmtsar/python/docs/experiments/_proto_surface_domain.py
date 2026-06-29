"""_proto_surface_domain.py — PROTOTYPE ONLY. NOT wired into pipeline.

Coarse-grained domain-decomposition parallel block-SOR for the GMT biharmonic
surface solver. Each thread gets a contiguous horizontal strip of the grid and
runs the EXISTING GS-SOR kernel on its strip; ghost/halo rows are exchanged
every K sweeps (additive-Schwarz / block-GS).

This is specifically designed to amortize the numba prange barrier overhead
that killed the fine-grained 9-color prototype: each parallel work unit is
millions of nodes (not thousands), so the thread-launch fixed cost is negligible.

The tradeoff vs pure GS-SOR:
  - Correct serial GS order within each strip (data propagation fast inside strip).
  - Incorrect inter-strip order: information crosses strip boundaries only every
    K sweeps via the ghost exchange. This is additive-Schwarz, not pure GS.
  - Fixed point of additive-Schwarz != fixed point of GS-SOR for the same omega.
    Convergence is measured to the SAME tolerance as GS-SOR, but the solution
    may differ from gmt surface C output.

PARITY TARGET: RMS vs ref_pixel.grd <= current gmt_surface_py port parity.
SCALING TARGET: >=3-4x at 8 threads on the 39M-node grid.
"""
from __future__ import annotations

import math
import os
import sys
import time
import importlib

import numpy as np

# ---------------------------------------------------------------------------
# Pull production internals from gmt_surface_py without re-running the port
# ---------------------------------------------------------------------------
_UTILS_DIR = os.path.dirname(os.path.abspath(__file__))
if _UTILS_DIR not in sys.path:
    sys.path.insert(0, _UTILS_DIR)

import gmt_surface_py as _gs
from gmt_surface_py import (
    _compute_coefficients,
    _bc_constants,
    _set_bcs,
    _iterate_once,
    _fill_in_forecast,
    _prime_factors,
    _gcd,
    _optimal_dim_for_surface,
    _remove_planar_trend,
    _restore_planar_trend,
    _solve_briggs_b_vec,
    _P_INDICES,
    _d_node,
    _N2, _NW, _N1, _NE, _W2, _W1, _E1, _E2, _SW, _S1, _SE, _S2,
    _SURFACE_CONV_LIMIT,
    _SURFACE_OVERRELAXATION,
    _SURFACE_CLOSENESS_FACTOR,
    _STAT_CONSTRAINED,
)

try:
    import numba
    from numba import njit, prange
    _HAVE_NUMBA = True
except ImportError:
    _HAVE_NUMBA = False
    def njit(*a, **k):
        if len(a) == 1 and callable(a[0]) and not k:
            return a[0]
        def d(f): return f
        return d
    prange = range

@njit(parallel=False, fastmath=False, cache=True)
def _iterate_strip_nx(u, status, briggs_b, briggs_idx_of_node,
                      coeff_unc, coeff_con,
                      d_node, p_indices,
                      a0_const_2, relax_old, relax_new,
                      node_nw_strip, strip_nx, strip_ny, current_mx):
    """GS-SOR sweep over a horizontal strip of strip_ny rows x strip_nx cols.
    Returns max |u_change| in the strip."""
    dN2 = d_node[0]; dNW = d_node[1]; dN1 = d_node[2]; dNE = d_node[3]
    dW2 = d_node[4]; dW1 = d_node[5]; dE1 = d_node[6]; dE2 = d_node[7]
    dSW = d_node[8]; dS1 = d_node[9]; dSE = d_node[10]; dS2 = d_node[11]
    cuN2 = coeff_unc[0]; cuNW = coeff_unc[1]; cuN1 = coeff_unc[2]; cuNE = coeff_unc[3]
    cuW2 = coeff_unc[4]; cuW1 = coeff_unc[5]; cuE1 = coeff_unc[6]; cuE2 = coeff_unc[7]
    cuSW = coeff_unc[8]; cuS1 = coeff_unc[9]; cuSE = coeff_unc[10]; cuS2 = coeff_unc[11]
    ccN2 = coeff_con[0]; ccNW = coeff_con[1]; ccN1 = coeff_con[2]; ccNE = coeff_con[3]
    ccW2 = coeff_con[4]; ccW1 = coeff_con[5]; ccE1 = coeff_con[6]; ccE2 = coeff_con[7]
    ccSW = coeff_con[8]; ccS1 = coeff_con[9]; ccSE = coeff_con[10]; ccS2 = coeff_con[11]

    max_u_change = -1.0
    for row in range(strip_ny):
        node = node_nw_strip + row * current_mx
        for _col in range(strip_nx):
            stat = status[node]
            if stat == 5:
                node += 1
                continue
            if stat == 0:
                u_00 = (u[node + dN2] * cuN2 + u[node + dNW] * cuNW
                        + u[node + dN1] * cuN1 + u[node + dNE] * cuNE
                        + u[node + dW2] * cuW2 + u[node + dW1] * cuW1
                        + u[node + dE1] * cuE1 + u[node + dE2] * cuE2
                        + u[node + dSW] * cuSW + u[node + dS1] * cuS1
                        + u[node + dSE] * cuSE + u[node + dS2] * cuS2)
            else:
                u_00 = (u[node + dN2] * ccN2 + u[node + dNW] * ccNW
                        + u[node + dN1] * ccN1 + u[node + dNE] * ccNE
                        + u[node + dW2] * ccW2 + u[node + dW1] * ccW1
                        + u[node + dE1] * ccE1 + u[node + dE2] * ccE2
                        + u[node + dSW] * ccSW + u[node + dS1] * ccS1
                        + u[node + dSE] * ccSE + u[node + dS2] * ccS2)
                bidx = briggs_idx_of_node[node]
                p0 = p_indices[stat, 0]; p1 = p_indices[stat, 1]
                p2 = p_indices[stat, 2]; p3 = p_indices[stat, 3]
                sum_bk_uk = (np.float64(briggs_b[bidx, 0] * u[node + d_node[p0]])
                             + np.float64(briggs_b[bidx, 1] * u[node + d_node[p1]])
                             + np.float64(briggs_b[bidx, 2] * u[node + d_node[p2]])
                             + np.float64(briggs_b[bidx, 3] * u[node + d_node[p3]]))
                u_00 = (u_00 + a0_const_2 * (sum_bk_uk + briggs_b[bidx, 4])) * briggs_b[bidx, 5]
            old = u[node]
            u_00 = old * relax_old + u_00 * relax_new
            ch = u_00 - old
            if ch < 0.0: ch = -ch
            if ch > max_u_change: max_u_change = ch
            u[node] = u_00
            node += 1
    return max_u_change


# ---------------------------------------------------------------------------
# Domain-decomp parallel sweep via threading.Thread (not prange).
#
# Why threading.Thread instead of prange/concurrent.futures?
# - prange: intra-JIT parallelism, hard to share the SAME u array with
#   Python-level coordination between strips. The GIL is released inside
#   njit anyway, so threading.Thread works correctly with numba njit functions
#   that hold the nogil contract.
# - concurrent.futures.ThreadPoolExecutor: Python overhead per submit, but
#   manageable for K-sweep bursts.
# - Each thread reads/writes only its own strip's rows, PLUS reads the
#   shared ghost rows (2 rows above/below the strip boundary). The ONLY
#   race is at strip boundary rows where two adjacent strips both READ the
#   same ghost rows (no write conflict since each thread writes only its
#   own strip interior). After each K-sweep block, the main thread does
#   the halo exchange (nothing to do — ghosts are already shared memory).
#   The convergence check barrier is also in the main thread.
# ---------------------------------------------------------------------------
import threading
import ctypes


def _domain_decomp_solve(u, status, briggs_b, briggs_idx,
                          coeff_unc, coeff_con, d_node_arr,
                          a0_const_2, relax_old, relax_new,
                          node_nw, current_nx, current_ny, current_mx,
                          max_iter_this_stride, converge_limit,
                          n_strips, halo_k,
                          node_sw_, node_se_, node_ne_,
                          x0c, x1c, y0c, y1c, eps_p2, eps_m2,
                          two_plus_ep2, two_plus_em2,
                          verbose=False):
    """Block-GS domain decomposition solver.

    Splits cur_ny rows into n_strips horizontal strips. Each strip runs
    _iterate_strip_nx in its own thread. Halo (ghost) exchange happens
    automatically since u is shared memory — adjacent strips always see
    each other's latest writes after a threading barrier (thread.join).

    The halo_k parameter controls how many strip-sweeps each thread runs
    before returning to the main thread for the convergence check. With
    halo_k=1 this is identical to sequential GS-SOR except the strip order
    is determined by thread scheduling (non-deterministic).

    With halo_k>1, each thread runs K sweeps privately on its strip before
    the main thread checks convergence and re-launches. This amortizes the
    thread-launch overhead but delays inter-strip information propagation.

    Returns (total_iterations, final_max_change).
    """
    # Partition rows evenly into n_strips.
    # Each strip is [row_start[s], row_end[s]) in interior row coords (0-based).
    rows_per_strip = current_ny // n_strips
    strip_starts = []
    strip_ends = []
    for s in range(n_strips):
        r0 = s * rows_per_strip
        r1 = (s + 1) * rows_per_strip if s < n_strips - 1 else current_ny
        strip_starts.append(r0)
        strip_ends.append(r1)

    # Pre-compute node_nw for each strip (row r in interior -> padded row r+2)
    strip_node_nw = []
    for s in range(n_strips):
        strip_node_nw.append(node_nw + strip_starts[s] * current_mx)

    max_changes = np.zeros(n_strips, dtype=np.float64)

    def worker(s):
        snw = strip_node_nw[s]
        sny = strip_ends[s] - strip_starts[s]
        for _ in range(halo_k):
            mc = _iterate_strip_nx(
                u, status, briggs_b, briggs_idx,
                coeff_unc, coeff_con, d_node_arr, _P_INDICES,
                a0_const_2, relax_old, relax_new,
                snw, current_nx, sny, current_mx)
            max_changes[s] = mc

    total_iters = 0
    max_change = float('inf')

    outer_iters = (max_iter_this_stride + halo_k - 1) // halo_k
    for outer in range(outer_iters):
        # Apply BCs (serial; O(nx+ny), negligible)
        _set_bcs(u, current_nx, current_ny, current_mx,
                 node_sw_, node_nw, node_se_, node_ne_,
                 d_node_arr[_N2], d_node_arr[_NW], d_node_arr[_N1], d_node_arr[_NE],
                 d_node_arr[_W2], d_node_arr[_W1],
                 d_node_arr[_E1], d_node_arr[_E2],
                 d_node_arr[_SW], d_node_arr[_S1], d_node_arr[_SE], d_node_arr[_S2],
                 x0c, x1c, y0c, y1c, eps_p2, eps_m2,
                 two_plus_ep2, two_plus_em2)

        if n_strips == 1:
            # Single-strip: just run the standard kernel directly
            mc = _iterate_strip_nx(
                u, status, briggs_b, briggs_idx,
                coeff_unc, coeff_con, d_node_arr, _P_INDICES,
                a0_const_2, relax_old, relax_new,
                strip_node_nw[0], current_nx, current_ny, current_mx)
            max_changes[0] = mc
        else:
            threads = [threading.Thread(target=worker, args=(s,))
                       for s in range(n_strips)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        total_iters += halo_k
        max_change = float(max_changes.max())

        if max_change <= converge_limit:
            if verbose:
                print(f"    converged at iter={total_iters} "
                      f"max|du|={max_change:.3e} limit={converge_limit:.3e}")
            return total_iters, max_change

        if verbose and (total_iters % 200 == 0):
            print(f"    iter={total_iters} max|du|={max_change:.3e} "
                  f"limit={converge_limit:.3e}")

        if total_iters >= max_iter_this_stride:
            break

    if verbose:
        print(f"    hit max_iter ({max_iter_this_stride}) "
              f"last_change={max_change:.3e} limit={converge_limit:.3e}")
    return total_iters, max_change


# ---------------------------------------------------------------------------
# Main domain-decomp surface solver — same outer structure as gmt_surface_py
# ---------------------------------------------------------------------------
def surface_domain_decomp(x, y, z, region, inc,
                           tension=0.0,
                           max_iter=1000,
                           tol=_SURFACE_CONV_LIMIT,
                           omega=_SURFACE_OVERRELAXATION,
                           pixel_reg=False,
                           alpha=None,
                           n_strips=8,
                           halo_k=1,
                           verbose=False):
    """Coarse-grained domain-decomp parallel biharmonic surface solver.

    Identical setup to gmt_surface_py (same W-up multigrid hierarchy,
    same Briggs constraints, same BCs, same float32 grid). The ONLY
    difference is the solver loop: instead of a single GS-SOR sweep over
    all rows, we split rows into n_strips horizontal strips and run each
    strip's GS-SOR in a separate Python thread. Halo rows are shared
    memory — no explicit copy needed.

    Parameters
    ----------
    n_strips : int
        Number of horizontal strip partitions (= number of threads).
    halo_k : int
        Number of inner sweeps each thread runs per outer iteration before
        the main thread checks convergence. halo_k=1 is safest (minimal
        inter-strip lag). halo_k>1 amortizes thread-launch overhead at
        the cost of slightly delayed information propagation across strip
        boundaries.
    """
    x = np.ascontiguousarray(x, dtype=np.float64)
    y = np.ascontiguousarray(y, dtype=np.float64)
    z = np.ascontiguousarray(z, dtype=np.float64)

    xmin, xmax, ymin, ymax = (float(v) for v in region)
    dx, dy = float(inc[0]), float(inc[1])
    if alpha is None:
        alpha = 1.0

    # --- Dimension suggestion (same as gmt_surface_py) ---
    n_columns_u = int(round((xmax - xmin) / dx))
    n_rows_u = int(round((ymax - ymin) / dy))
    crop_x0 = 0; crop_y0 = 0
    crop_nx = n_columns_u + 1; crop_ny = n_rows_u + 1

    sug = _optimal_dim_for_surface(n_columns_u, n_rows_u)
    if sug is not None:
        sug_nx, sug_ny, _factor = sug
        m_x = sug_nx - n_columns_u; m_y = sug_ny - n_rows_u
        half_x = m_x // 2; half_y = m_y // 2
        xmin_exp = xmin - half_x * dx; xmax_exp = xmax + half_x * dx
        if m_x % 2: xmax_exp += dx
        ymin_exp = ymin - half_y * dy; ymax_exp = ymax + half_y * dy
        if m_y % 2: ymax_exp += dy
        crop_x0 = half_x; crop_y0 = half_y
        xmin, xmax, ymin, ymax = xmin_exp, xmax_exp, ymin_exp, ymax_exp

    # --- Pixel registration ---
    if pixel_reg:
        nx_pixel = int(round((xmax - xmin) / dx))
        ny_pixel = int(round((ymax - ymin) / dy))
        if sug is not None:
            xmin_s, xmax_s, ymin_s, ymax_s = xmin, xmax, ymin, ymax
        else:
            xmin_s = xmin + dx / 2.0; xmax_s = xmax + dx / 2.0
            ymin_s = ymin + dy / 2.0; ymax_s = ymax + dy / 2.0
        n_columns = nx_pixel + 1; n_rows = ny_pixel + 1
    else:
        n_columns = int(round((xmax - xmin) / dx)) + 1
        n_rows = int(round((ymax - ymin) / dy)) + 1
        xmin_s, xmax_s, ymin_s, ymax_s = xmin, xmax, ymin, ymax
        nx_pixel = n_columns; ny_pixel = n_rows

    # --- Filter and throw_away_unusables ---
    _r_ix = 1.0 / dx; _r_iy = 1.0 / dy
    wesn_lim_x_lo = xmin_s - dx; wesn_lim_x_hi = xmax_s + dx
    wesn_lim_y_lo = ymin_s - dy; wesn_lim_y_hi = ymax_s + dy
    keep = ((x >= wesn_lim_x_lo) & (x <= wesn_lim_x_hi)
            & (y >= wesn_lim_y_lo) & (y <= wesn_lim_y_hi)
            & np.isfinite(z))
    xx_in = x[keep]; yy_in = y[keep]; z_in = z[keep]
    if xx_in.size == 0:
        raise ValueError("no input data inside region")

    _fc = (xx_in - xmin_s) * _r_ix
    _frow_raw = (yy_in - ymin_s) * _r_iy
    _c1 = np.floor(_fc + 0.5).astype(np.int64)
    _r1 = (n_rows - 1) - np.floor(_frow_raw + 0.5).astype(np.int64)
    _ok = (_c1 >= 0) & (_c1 < n_columns) & (_r1 >= 0) & (_r1 < n_rows)
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
    _uniq[0] = True; _uniq[1:] = _idx_s[1:] != _idx_s[:-1]
    _keep2 = np.where(_ok)[0][_ord][_uniq]
    xx_in = xx_in[_keep2]; yy_in = yy_in[_keep2]; z_in = z_in[_keep2]

    xx_in = xx_in.astype(np.float32).astype(np.float64)
    yy_in = yy_in.astype(np.float32).astype(np.float64)
    z_in  = z_in.astype(np.float32).astype(np.float64)

    x_frac_pts = (xx_in - xmin_s) / dx
    y_up_frac_pts = (yy_in - ymin_s) / dy

    plane_icept, plane_sx, plane_sy, _ = _remove_planar_trend(
        x_frac_pts, y_up_frac_pts, z_in)

    _plane_vals_f32 = (plane_icept + plane_sx * x_frac_pts
                       + plane_sy * y_up_frac_pts).astype(np.float32)
    z_det = z_in.astype(np.float32) - _plane_vals_f32

    ssz = float((z_det.astype(np.float64) ** 2).sum())
    z_rms = math.sqrt(ssz / z_det.size)
    if z_rms < 1e-8:
        raise RuntimeError("z_rms < 1e-8, degenerate input")
    r_z_rms = 1.0 / z_rms
    z_norm = z_det * np.float32(r_z_rms)

    converge_limit_n = tol

    (coeff_unc, coeff_con, a0_const_1, a0_const_2,
     eps_p2, eps_m2, two_plus_ep2, two_plus_em2,
     _alpha2) = _compute_coefficients(alpha, tension)

    x0c, x1c, y0c, y1c = _bc_constants(tension, alpha)

    # --- Stride hierarchy ---
    current_stride = _gcd(n_columns - 1, n_rows - 1)
    factors = _prime_factors(current_stride); factors.sort()
    while True:
        cur_nx = (n_columns - 1) // current_stride + 1
        cur_ny = (n_rows - 1) // current_stride + 1
        if cur_nx >= 4 and cur_ny >= 4: break
        if not factors: raise ValueError("grid too small to factor")
        current_stride //= factors.pop()

    # --- Allocate ---
    final_mx = n_columns + 4; final_my = n_rows + 4
    mxmy = final_mx * final_my
    u = np.zeros(mxmy, dtype=np.float32)
    status = np.zeros(mxmy, dtype=np.uint8)
    briggs_idx_shared = np.full(mxmy, -1, dtype=np.int64)
    briggs_idx_dirty = []

    # --- Setup ---
    cur_nx = (n_columns - 1) // current_stride + 1
    cur_ny = (n_rows - 1) // current_stride + 1
    cur_mx = cur_nx + 4
    node_nw = 2 * cur_mx + 2
    node_sw = node_nw + (cur_ny - 1) * cur_mx
    node_se = node_sw + cur_nx - 1
    node_ne = node_nw + cur_nx - 1
    d_node = _d_node(cur_mx)

    # --- Constraint helpers (same as production port) ---
    def _build_constraints(stride, cur_nx_, cur_ny_):
        inc_x = stride * dx; inc_y = stride * dy
        r_inc_x = 1.0 / inc_x; r_inc_y = 1.0 / inc_y
        fcol = (xx_in - xmin_s) * r_inc_x
        frow_raw = (yy_in - ymin_s) * r_inc_y
        col_near = np.floor(fcol + 0.5).astype(np.int64)
        row_near = (cur_ny_ - 1) - np.floor(frow_raw + 0.5).astype(np.int64)
        inside = ((col_near >= 0) & (col_near < cur_nx_)
                  & (row_near >= 0) & (row_near < cur_ny_))
        if not inside.any():
            return (np.zeros(0, np.int64), np.zeros(0, np.int64),
                    np.zeros(0), np.zeros(0), np.zeros(0))
        col_near = col_near[inside]; row_near = row_near[inside]
        fcol_in = fcol[inside]; frow_raw_in = frow_raw[inside]
        z_norm_in = z_norm[inside]
        dx_off = fcol_in - col_near
        dy_off = frow_raw_in - (cur_ny_ - 1) + row_near
        index = row_near * cur_nx_ + col_near
        if pixel_reg:
            dist2 = (inc_x * (dx_off + 0.5/stride))**2 + (inc_y * (dy_off + 0.5/stride))**2
        else:
            dist2 = (inc_x * dx_off)**2 + (inc_y * dy_off)**2
        order = np.lexsort((dist2, index))
        index_s = index[order]; dx_s = dx_off[order]; dy_s = dy_off[order]
        z_s = z_norm_in[order]; col_s = col_near[order]; row_s = row_near[order]
        uniq = np.empty(index_s.size, dtype=bool)
        uniq[0] = True; uniq[1:] = (index_s[1:] != index_s[:-1])
        return (col_s[uniq], row_s[uniq], dx_s[uniq], dy_s[uniq], z_s[uniq])

    def _assign_constraints(stride, cur_nx_, cur_ny_, cur_mx_, node_nw_):
        col_u, row_u, dx_u, dy_u, z_u = _build_constraints(stride, cur_nx_, cur_ny_)
        _rows_ = node_nw_ + np.arange(cur_ny_, dtype=np.int64) * cur_mx_
        _idx_flat = (_rows_[:, None] + np.arange(cur_nx_, dtype=np.int64)[None, :]).ravel()
        status[_idx_flat] = 0
        n_pts = col_u.size
        briggs_b = np.zeros((max(n_pts, 1), 6), dtype=np.float32)
        briggs_idx = briggs_idx_shared
        if briggs_idx_dirty:
            briggs_idx[briggs_idx_dirty[0]] = -1; briggs_idx_dirty.clear()
        if n_pts > 0:
            col_arr = col_u.astype(np.int64, copy=False)
            row_arr = row_u.astype(np.int64, copy=False)
            dx_arr = dx_u.astype(np.float64, copy=False)
            dy_arr = dy_u.astype(np.float64, copy=False)
            z_arr = z_u.astype(np.float64, copy=False)
            nodes = node_nw_ + row_arr * cur_mx_ + col_arr
            on_node = ((np.abs(dx_arr) < _SURFACE_CLOSENESS_FACTOR)
                       & (np.abs(dy_arr) < _SURFACE_CLOSENESS_FACTOR))
            if on_node.any():
                on_idx = nodes[on_node]
                status[on_idx] = 5
                _corr = np.float32(r_z_rms * stride
                    * (plane_sx * dx_arr[on_node] + plane_sy * dy_arr[on_node]))
                u[on_idx] = z_arr[on_node].astype(np.float32) + _corr
            off = ~on_node
            if off.any():
                off_nodes = nodes[off]
                dx_off2 = dx_arr[off]; dy_off2 = dy_arr[off]; z_off = z_arr[off]
                dy_ge0 = dy_off2 >= 0.0; dx_ge0 = dx_off2 >= 0.0
                quad = np.where(dy_ge0, np.where(dx_ge0, 1, 2), np.where(dx_ge0, 4, 3)).astype(np.uint8)
                xx_b = np.where(dy_ge0, np.where(dx_ge0, dx_off2, dy_off2),
                                np.where(dx_ge0, -dy_off2, -dx_off2))
                yy_b = np.where(dy_ge0, np.where(dx_ge0, dy_off2, -dx_off2),
                                np.where(dx_ge0, dx_off2, -dy_off2))
                _b_block = _solve_briggs_b_vec(xx_b, yy_b, z_off, a0_const_1, a0_const_2)
                n_off = off_nodes.size
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

    def _solve_stride(stride, cur_nx_, cur_ny_, cur_mx_,
                      node_nw_, node_sw_, node_se_, node_ne_,
                      d_node_, briggs_b, briggs_idx, label):
        n_strips_eff = min(n_strips, cur_ny_)
        current_max_iter = max_iter * stride
        current_limit = converge_limit_n / stride
        iters, mc = _domain_decomp_solve(
            u, status, briggs_b, briggs_idx,
            coeff_unc, coeff_con, d_node_,
            a0_const_2, 1.0 - omega, omega,
            node_nw_, cur_nx_, cur_ny_, cur_mx_,
            current_max_iter, current_limit,
            n_strips_eff, halo_k,
            node_sw_, node_se_, node_ne_,
            x0c, x1c, y0c, y1c, eps_p2, eps_m2,
            two_plus_ep2, two_plus_em2,
            verbose=verbose)
        if verbose:
            print(f"  [{label}] stride={stride} iters={iters} "
                  f"max|du|={mc:.3e} strips={n_strips_eff}")
        return iters

    # --- Coarsest stride ---
    briggs_b, briggs_idx = _assign_constraints(current_stride, cur_nx, cur_ny, cur_mx, node_nw)
    _solve_stride(current_stride, cur_nx, cur_ny, cur_mx,
                  node_nw, node_sw, node_se, node_ne, d_node,
                  briggs_b, briggs_idx, "DATA")

    # --- Down-stride loop ---
    previous_stride = current_stride
    previous_nx = cur_nx; previous_ny = cur_ny; previous_mx = cur_mx
    while current_stride > 1:
        if not factors: break
        current_stride //= factors.pop()
        cur_nx = (n_columns - 1) // current_stride + 1
        cur_ny = (n_rows - 1) // current_stride + 1
        cur_mx = cur_nx + 4
        node_nw = 2 * cur_mx + 2
        node_sw = node_nw + (cur_ny - 1) * cur_mx
        node_se = node_sw + cur_nx - 1
        node_ne = node_nw + cur_nx - 1
        d_node = _d_node(cur_mx)

        _fill_in_forecast(u, status, previous_nx, previous_ny, previous_mx,
                          cur_nx, cur_ny, cur_mx, previous_stride, current_stride,
                          node_nw, node_ne)
        if briggs_idx_dirty:
            briggs_idx_shared[briggs_idx_dirty[0]] = -1; briggs_idx_dirty.clear()
        briggs_b_empty = np.zeros((1, 6), dtype=np.float32)
        _solve_stride(current_stride, cur_nx, cur_ny, cur_mx,
                      node_nw, node_sw, node_se, node_ne, d_node,
                      briggs_b_empty, briggs_idx_shared, "NODES")
        briggs_b, briggs_idx = _assign_constraints(current_stride, cur_nx,
                                                    cur_ny, cur_mx, node_nw)
        _solve_stride(current_stride, cur_nx, cur_ny, cur_mx,
                      node_nw, node_sw, node_se, node_ne, d_node,
                      briggs_b, briggs_idx, "DATA")
        previous_stride = current_stride
        previous_nx = cur_nx; previous_ny = cur_ny; previous_mx = cur_mx

    # --- Extract ---
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
    return np.ascontiguousarray(grid)


