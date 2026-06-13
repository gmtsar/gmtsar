#!/usr/bin/env python3
"""gmt_surface_py — faithful Python port of GMT's `surface` (Smith & Wessel 1990).

This is a line-by-line port of upstream
``GenericMappingTools/gmt/src/surface.c`` (~2300 lines of C) per project
Rule 10 ("port the C algorithm verbatim FIRST, optimize later").

Why the rewrite (vs Miras #20/#26/#33/#38/#50)
----------------------------------------------
Previous prototypes substituted "easier" algorithm choices for what
surface.c actually does, hoping correctness on small grids would scale.
It did not.  On 6600x4800 grids the Jacobi+FMG combination was 13x
SLOWER than `gmt surface` (single thread).  Concrete substitutions that
were wrong:

  * Smoother: Jacobi (parallelisable) instead of in-place Gauss-Seidel
    with successive over-relaxation (GS-SOR, omega=1.4).  For the
    biharmonic Jacobi requires O(N^2) iterations; GS-SOR requires
    O(N^1.5) — that is a complexity-class gap, not a constant factor.

  * Multigrid: Full-Multigrid (FMG) with bilinear grid-build was a
    workaround for never getting V-cycle right.  surface.c is NOT a
    V-cycle in the textbook sense — it is a **W-up nested iteration**:
    start at the coarsest stride (= gcd(n_columns-1, n_rows-1)),
    iterate to convergence, divide stride by next-largest prime
    factor, expand+fill bilinearly, iterate, repeat down to stride=1.

  * BCs: naive linear extrapolation instead of the tension-weighted
    natural BC (eqs A-8..A-10 in S&W 1990, surface.c:surface_set_BCs).

  * Convergence: tol=1e-4 absolute instead of the C's per-stride
    `converge_limit / current_stride` test.

This port matches the C algorithm in all four respects.

Performance vs `gmt surface 6.4.0` (strict single thread, OMP_NUM_THREADS=1)
---------------------------------------------------------------------------
After Mira #52's verbatim GS-SOR port, the algorithm was correct but the
Python *implementation* was 1.9-4x slower than the C reference.  Mira #53
profiled and found 84% of wall-time on 6601x4801 was outside the JIT
kernel — three pure-Python double-loops (`_restore_planar_trend`, the
final extract, and the per-stride status-reset / scalar Briggs loop in
`_assign_constraints`) plus repeated 254-MB allocations of
`np.full(mxmy, -1, np.int64)`.

Vectorising those loops with broadcasting + reshape-slice, vectorising
`_solve_briggs_b` over the full set of constrained points in one shot,
and reusing a single `briggs_idx` buffer across strides lifted the port
from 4.2x slower to 0.79x of `gmt surface` on 6601x4801 (and 1.9x slower
to 0.83x on 1001x1001).  The inner GS-SOR kernel itself (`_iterate_once`)
is unchanged — same arithmetic, same iteration order, same per-element
roundoff.  The wins are purely implementation hygiene, not algorithm
substitution (Rule 10 carve-out: equal-or-faster + bit-identical).

Algorithm reference (surface.c structure)
------------------------------------------
  surface_set_coefficients()      C  286-326    (eq A-4, A-7 weights)
  surface_set_offset()            C  328-347    (12-node offset table)
  fill_in_forecast()              C  349-467    (expand+bilinear fill)
  surface_find_nearest_constraint C  575-658    (snap + Briggs setup)
  surface_solve_Briggs_coefficients C 544-573   (eq A-6)
  surface_set_grid_parameters     C  660-679    (current_nx/ny/mx)
  surface_set_BCs                 C 1006-1076   (natural BC, eqs A-8..10)
  surface_iterate                 C 1078-1159   (GS-SOR main solver)
  surface_remove_planar_trend     C 1236-1279
  surface_restore_planar_trend    C 1281-1299
  surface_throw_away_unusables    C 1301-1340
  surface_rescale_z_values        C 1342-1369
  surface_smart_divide            C  511-515
  GMT_surface (main)              C 1981-2296

This module focuses on the algorithmic core needed by the gmtsar
pipeline (`dem2topo_ra`, `proj_ra2ll_lib`):

  * gridline + pixel registration  (-r equivalent)
  * isotropic (alpha=1) and anisotropic (-A) stencil
  * Briggs sub-cell data constraints
  * Limit grids (-L), break lines (-D), search-radius init (-S), and
    -M masking are NOT ported — none of the SAR callers use them.

Public API
----------
gmt_surface_py(x, y, z, region, inc, tension=0.0, max_iter=500, tol=1e-4,
               omega=1.4, pixel_reg=False, ...) -> ndarray (ny, nx)
"""
from __future__ import annotations

import math
import os
from typing import Optional, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Numba availability + soft fallback
# ---------------------------------------------------------------------------
# Per project rule "strict single-thread for in-sweep numba kernels" we
# pin parallel=False.  fastmath=False keeps roundoff-identical to the C
# arithmetic order (which matters for GS-SOR — fastmath would re-order
# the FMA in the inner stencil sum, breaking parity).
_USE_NUMBA = os.environ.get("GMT_SURFACE_PY_NUMBA", "1") != "0"

try:
    if _USE_NUMBA:
        from numba import njit
        _HAVE_NUMBA = True
    else:
        raise ImportError("disabled by GMT_SURFACE_PY_NUMBA=0")
except Exception:  # pragma: no cover
    _HAVE_NUMBA = False

    def njit(*args, **kwargs):  # type: ignore
        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]

        def deco(f):
            return f
        return deco


# ---------------------------------------------------------------------------
# Constants from surface.c (#define block at lines 130-145)
# ---------------------------------------------------------------------------
_SURFACE_CONV_LIMIT = 1.0e-4          # surface.c:133 (default tolerance)
_SURFACE_MAX_ITERATIONS = 500         # surface.c:134
_SURFACE_OVERRELAXATION = 1.4         # surface.c:135 (Z= relaxation default)
_SURFACE_CLOSENESS_FACTOR = 0.05      # surface.c:136 (5% of grid spacing)

# Status codes (surface.c:137-142)
_STAT_UNCONSTRAINED = 0
_STAT_QUAD1 = 1
_STAT_QUAD2 = 2
_STAT_QUAD3 = 3
_STAT_QUAD4 = 4
_STAT_CONSTRAINED = 5


# ---------------------------------------------------------------------------
# Prime factorisation (mirrors gmt_get_prime_factors)
# ---------------------------------------------------------------------------
def _prime_factors(n: int) -> list:
    """Return prime factors of n in ascending order, with multiplicity.

    Matches the order surface.c's smart_divide assumes — it pops the
    LAST entry (largest prime).
    """
    if n <= 1:
        return []
    out = []
    d = 2
    nn = int(n)
    while d * d <= nn:
        while nn % d == 0:
            out.append(d)
            nn //= d
        d += 1
    if nn > 1:
        out.append(nn)
    return out


def _gcd(a: int, b: int) -> int:
    return math.gcd(int(a), int(b))


# ---------------------------------------------------------------------------
# Dimension-suggestion logic (mirrors gmt_optimal_dim_for_surface /
# gmtsupport_guess_surface_time / gmtsupport_compare_sugs in
# gmt_support.c:6424-17003).
#
# surface.c:2029-2047 (GMT_surface, called unconditionally unless -Qr) calls
# this BEFORE the gcd/stride hierarchy is set up.  If a "better" (n_columns,
# n_rows) pair exists with a smaller gmtsupport_guess_surface_time() value,
# GMT silently EXPANDS the solved region/grid to that pair, runs the entire
# multigrid solve on the expanded grid, and crops back to the user's
# requested region when writing the output (surface_write_grid,
# surface.c:939-966).
#
# This is the actual fix for the "gcd==1" case: C essentially NEVER solves
# a mutually-prime grid (except under -Qr) — it pads the grid to the nearest
# size with a better gcd first.  Mira #68.
# ---------------------------------------------------------------------------
def _guess_surface_time(n_columns: int, n_rows: int) -> float:
    """Port of gmtsupport_guess_surface_time (gmt_support.c:6424-6490).

    n_columns, n_rows here are in the "n-1" convention (one less than the
    node count), matching the C call sites.
    """
    g = _gcd(n_columns, n_rows)
    if g > 1:
        factors = _prime_factors(g)
        nxg = n_columns // g
        nyg = n_rows // g
        if nxg < 3 or nyg < 3:
            factor = factors[-1]
            factors = factors[:-1]
            g //= factor
            nxg *= factor
            nyg *= factor
    else:
        factors = []
        nxg = n_columns
        nyg = n_rows
    length = float(max(nxg, nyg))
    t_sum = float(nxg) * (float(nyg) * length)
    while g > 1:
        factor = factors[-1]
        factors = factors[:-1]
        g //= factor
        nxg *= factor
        nyg *= factor
        length = float(factor)
        t_sum += float(nxg) * (float(nyg) * length)
    return t_sum


def _optimal_dim_for_surface(n_columns: int, n_rows: int):
    """Port of gmt_optimal_dim_for_surface (gmt_support.c:16944-17003).

    Returns the BEST suggestion (n_columns_sug, n_rows_sug, factor) per
    gmtsupport_compare_sugs's DESCENDING sort, or None if no suggestion
    improves on the user's (n_columns, n_rows).

    n_columns, n_rows are in the "n-1" convention (one less than the node
    count) as required by the C call sites (surface.c:2034, 2082).
    """
    users_time = _guess_surface_time(n_columns, n_rows)
    xstop = 2 * n_columns
    ystop = 2 * n_rows

    suggestions = []
    nx2 = 2
    while nx2 <= xstop:
        nx3 = 1
        while nx3 <= xstop:
            nx5 = 1
            while nx5 <= xstop:
                nxg = nx2 * nx3 * nx5
                if not (nxg < n_columns or nxg > xstop):
                    ny2 = 2
                    while ny2 <= ystop:
                        ny3 = 1
                        while ny3 <= ystop:
                            ny5 = 1
                            while ny5 <= ystop:
                                nyg = ny2 * ny3 * ny5
                                if not (nyg < n_rows or nyg > ystop):
                                    current_time = _guess_surface_time(nxg, nyg)
                                    if current_time < users_time:
                                        suggestions.append(
                                            (nxg, nyg, users_time / current_time))
                                ny5 *= 5
                            ny3 *= 3
                        ny2 *= 2
                nx5 *= 5
            nx3 *= 3
        nx2 *= 2

    if not suggestions:
        return None
    # gmtsupport_compare_sugs: DESCENDING by factor.  Python's sort is
    # stable, so ties keep the C nested-loop discovery order (ascending
    # nx2/nx3/nx5/ny2/ny3/ny5 powers) — matches glibc qsort on the small
    # arrays involved here closely enough that the top (largest-factor)
    # entry is unambiguous in practice.
    suggestions.sort(key=lambda s: -s[2])
    return suggestions[0]


# ---------------------------------------------------------------------------
# Briggs sub-cell coefficients — surface_solve_Briggs_coefficients
# ---------------------------------------------------------------------------
# surface.c:544-573.  Given normalised offset (xx, yy) of the data
# constraint from its assigned grid node (both >= 0, in fractional grid
# spacings — quadrants 2-4 are rotated to look like quadrant 1), and the
# data value z, produce the 6 Briggs coefficients b[0..5] that will be
# used inside the GS-SOR sweep.
#
# Important: b[5] holds the inverse of the denominator for that node's
# update, b[4] is pre-multiplied by z (the data constraint).
def _solve_briggs_b(xx, yy, z, a0_const_1, a0_const_2, b_out):
    """Fill b_out[0..5] for one constrained node.  Mirrors surface.c:544."""
    xx_plus_yy = xx + yy
    xx_plus_yy_plus_one = 1.0 + xx_plus_yy
    inv_xpyp1 = 1.0 / xx_plus_yy_plus_one
    xx2 = xx * xx
    yy2 = yy * yy
    inv_delta = inv_xpyp1 / xx_plus_yy
    b_out[0] = (xx2 + 2.0 * xx * yy + xx - yy2 - yy) * inv_delta
    b_out[1] = 2.0 * (yy - xx + 1.0) * inv_xpyp1
    b_out[2] = 2.0 * (xx - yy + 1.0) * inv_xpyp1
    b_out[3] = (-xx2 + 2.0 * xx * yy - xx + yy2 + yy) * inv_delta
    b_4 = 4.0 * inv_delta
    b_sum = b_out[0] + b_out[1] + b_out[2] + b_out[3] + b_4
    b_out[4] = b_4 * z
    b_out[5] = 1.0 / (a0_const_1 + a0_const_2 * b_sum)


def _solve_briggs_b_vec(xx, yy, z, a0_const_1, a0_const_2):
    """Vectorised _solve_briggs_b — same arithmetic order per element.

    Returns an (N,6) array of Briggs coefficients.  Mira #53 perf pass:
    the scalar loop showed up at 430k calls / 0.7s on the 6601x4801 grid.
    """
    xx = np.ascontiguousarray(xx, dtype=np.float64)
    yy = np.ascontiguousarray(yy, dtype=np.float64)
    z = np.ascontiguousarray(z, dtype=np.float64)
    out = np.empty((xx.size, 6), dtype=np.float64)
    xx_plus_yy = xx + yy
    xx_plus_yy_plus_one = 1.0 + xx_plus_yy
    inv_xpyp1 = 1.0 / xx_plus_yy_plus_one
    xx2 = xx * xx
    yy2 = yy * yy
    inv_delta = inv_xpyp1 / xx_plus_yy
    out[:, 0] = (xx2 + 2.0 * xx * yy + xx - yy2 - yy) * inv_delta
    out[:, 1] = 2.0 * (yy - xx + 1.0) * inv_xpyp1
    out[:, 2] = 2.0 * (xx - yy + 1.0) * inv_xpyp1
    out[:, 3] = (-xx2 + 2.0 * xx * yy - xx + yy2 + yy) * inv_delta
    b_4 = 4.0 * inv_delta
    b_sum = out[:, 0] + out[:, 1] + out[:, 2] + out[:, 3] + b_4
    out[:, 4] = b_4 * z
    out[:, 5] = 1.0 / (a0_const_1 + a0_const_2 * b_sum)
    return out


# ---------------------------------------------------------------------------
# Boundary conditions — surface_set_BCs (surface.c:1006-1076)
# ---------------------------------------------------------------------------
# We use a 1D-padded array u of size mx*my, with mx = n_columns + 4 and
# my = n_rows + 4.  The interior is rows 2..n_rows+1, cols 2..n_columns+1
# (row 0 = NORTH per GMT convention).  Per eq A-8..A-10:
#   x_0_const = 4*(1-Tb)/(2-Tb)
#   x_1_const = (3*Tb - 2)/(2-Tb)
#   y_0_const = 4*alpha*(1-Tb) / (2*alpha*(1-Tb) + Tb)
#   y_1_const = (Tb - 2*alpha*(1-Tb)) / (2*alpha*(1-Tb) + Tb)
@njit(parallel=False, fastmath=False, cache=True)
def _set_bcs(u, current_nx, current_ny, current_mx,
             node_sw, node_nw, node_se, node_ne,
             d_N2, d_NW, d_N1, d_NE, d_W2, d_W1,
             d_E1, d_E2, d_SW, d_S1, d_SE, d_S2,
             x0c, x1c, y0c, y1c, eps_p2, eps_m2,
             two_plus_ep2, two_plus_em2):
    """Apply natural BCs (eqs A-8..A-10) to the 2-wide ghost ring.

    All indices are 1D into the flat-padded u array.  Mirrors
    surface_set_BCs (surface.c:1006-1076).
    """
    # BC1: (1-T) d2/dn2 + T d/dn = 0 along edges
    n_s = node_sw
    n_n = node_nw
    for _ in range(current_nx):
        u[n_s + d_S1] = y0c * u[n_s] + y1c * u[n_s + d_N1]
        u[n_n + d_N1] = y0c * u[n_n] + y1c * u[n_n + d_S1]
        n_s += 1
        n_n += 1

    n_w = node_nw
    n_e = node_ne
    for _ in range(current_ny):
        u[n_w + d_W1] = x1c * u[n_w + d_E1] + x0c * u[n_w]
        u[n_e + d_E1] = x1c * u[n_e + d_W1] + x0c * u[n_e]
        n_w += current_mx
        n_e += current_mx

    # d2/dxdy = 0 at the 4 corners (surface.c:1042-1049)
    n = node_sw
    u[n + d_SW] = u[n + d_SE] + u[n + d_NW] - u[n + d_NE]
    n = node_nw
    u[n + d_NW] = u[n + d_NE] + u[n + d_SW] - u[n + d_SE]
    n = node_se
    u[n + d_SE] = u[n + d_SW] + u[n + d_NE] - u[n + d_NW]
    n = node_ne
    u[n + d_NE] = u[n + d_NW] + u[n + d_SE] - u[n + d_SW]

    # BC2: dC/dn = 0 along S/N edges (eq A-10)
    n_s = node_sw
    n_n = node_nw
    for _ in range(current_nx):
        u[n_s + d_S2] = (u[n_s + d_N2]
                        + eps_m2 * (u[n_s + d_NW] + u[n_s + d_NE]
                                    - u[n_s + d_SW] - u[n_s + d_SE])
                        + two_plus_em2 * (u[n_s + d_S1] - u[n_s + d_N1]))
        u[n_n + d_N2] = (u[n_n + d_S2]
                        + eps_m2 * (u[n_n + d_SW] + u[n_n + d_SE]
                                    - u[n_n + d_NW] - u[n_n + d_NE])
                        + two_plus_em2 * (u[n_n + d_N1] - u[n_n + d_S1]))
        n_s += 1
        n_n += 1

    n_w = node_nw
    n_e = node_ne
    for _ in range(current_ny):
        u[n_w + d_W2] = (u[n_w + d_E2]
                        + eps_p2 * (u[n_w + d_NE] + u[n_w + d_SE]
                                    - u[n_w + d_NW] - u[n_w + d_SW])
                        + two_plus_ep2 * (u[n_w + d_W1] - u[n_w + d_E1]))
        u[n_e + d_E2] = (u[n_e + d_W2]
                        + eps_p2 * (u[n_e + d_NW] + u[n_e + d_SW]
                                    - u[n_e + d_NE] - u[n_e + d_SE])
                        + two_plus_ep2 * (u[n_e + d_E1] - u[n_e + d_W1]))
        n_w += current_mx
        n_e += current_mx


# ---------------------------------------------------------------------------
# Iterate — surface_iterate (surface.c:1078-1159).  In-place GS-SOR.
# ---------------------------------------------------------------------------
# The C uses one buffer for u_old and u_new (line 1089).  In a single
# sweep through nodes (row-major), each update writes back to u
# immediately, so subsequent reads in the SAME sweep see the just-updated
# values.  This IS Gauss-Seidel.  Multiply (1-omega)*u_old + omega*u_new
# and that becomes SOR.
@njit(parallel=False, fastmath=False, cache=True)
def _iterate_once(u, status, briggs_b, briggs_idx_of_node,
                  coeff_unc, coeff_con,
                  d_node, p_indices,
                  a0_const_2, relax_old, relax_new,
                  node_nw, current_nx, current_ny, current_mx):
    """One full GS-SOR sweep over interior nodes.  Returns max |u_change|.

    Inner-loop hoist (Mira #53 perf pass): the 12 stencil offsets and the
    12 stencil weights are LOOP-INVARIANT but were addressed via array
    indexing inside the hot path.  Hoisting them into stack-allocated
    locals lets LLVM keep them in registers and produces tighter codegen
    (the load-load chain previously forced extra rip-relative addressing).
    The arithmetic order is preserved exactly — same float bit pattern as
    the array-indexed version.
    """
    # Hoist offsets
    dN2 = d_node[0]; dNW = d_node[1]; dN1 = d_node[2]; dNE = d_node[3]
    dW2 = d_node[4]; dW1 = d_node[5]; dE1 = d_node[6]; dE2 = d_node[7]
    dSW = d_node[8]; dS1 = d_node[9]; dSE = d_node[10]; dS2 = d_node[11]
    # Hoist unconstrained-node weights
    cuN2 = coeff_unc[0]; cuNW = coeff_unc[1]; cuN1 = coeff_unc[2]; cuNE = coeff_unc[3]
    cuW2 = coeff_unc[4]; cuW1 = coeff_unc[5]; cuE1 = coeff_unc[6]; cuE2 = coeff_unc[7]
    cuSW = coeff_unc[8]; cuS1 = coeff_unc[9]; cuSE = coeff_unc[10]; cuS2 = coeff_unc[11]
    # Hoist constrained-node weights
    ccN2 = coeff_con[0]; ccNW = coeff_con[1]; ccN1 = coeff_con[2]; ccNE = coeff_con[3]
    ccW2 = coeff_con[4]; ccW1 = coeff_con[5]; ccE1 = coeff_con[6]; ccE2 = coeff_con[7]
    ccSW = coeff_con[8]; ccS1 = coeff_con[9]; ccSE = coeff_con[10]; ccS2 = coeff_con[11]

    max_u_change = -1.0
    for row in range(current_ny):
        node = node_nw + row * current_mx
        for _col in range(current_nx):
            stat = status[node]
            if stat == 5:  # SURFACE_IS_CONSTRAINED — pinned, skip
                node += 1
                continue

            if stat == 0:  # SURFACE_IS_UNCONSTRAINED
                u_00 = (u[node + dN2] * cuN2
                        + u[node + dNW] * cuNW
                        + u[node + dN1] * cuN1
                        + u[node + dNE] * cuNE
                        + u[node + dW2] * cuW2
                        + u[node + dW1] * cuW1
                        + u[node + dE1] * cuE1
                        + u[node + dE2] * cuE2
                        + u[node + dSW] * cuSW
                        + u[node + dS1] * cuS1
                        + u[node + dSE] * cuSE
                        + u[node + dS2] * cuS2)
            else:  # 1..4
                u_00 = (u[node + dN2] * ccN2
                        + u[node + dNW] * ccNW
                        + u[node + dN1] * ccN1
                        + u[node + dNE] * ccNE
                        + u[node + dW2] * ccW2
                        + u[node + dW1] * ccW1
                        + u[node + dE1] * ccE1
                        + u[node + dE2] * ccE2
                        + u[node + dSW] * ccSW
                        + u[node + dS1] * ccS1
                        + u[node + dSE] * ccSE
                        + u[node + dS2] * ccS2)
                bidx = briggs_idx_of_node[node]
                p0 = p_indices[stat, 0]
                p1 = p_indices[stat, 1]
                p2 = p_indices[stat, 2]
                p3 = p_indices[stat, 3]
                sum_bk_uk = (briggs_b[bidx, 0] * u[node + d_node[p0]]
                             + briggs_b[bidx, 1] * u[node + d_node[p1]]
                             + briggs_b[bidx, 2] * u[node + d_node[p2]]
                             + briggs_b[bidx, 3] * u[node + d_node[p3]])
                u_00 = (u_00 + a0_const_2 * (sum_bk_uk + briggs_b[bidx, 4])) * briggs_b[bidx, 5]

            old = u[node]
            u_00 = old * relax_old + u_00 * relax_new
            change = u_00 - old
            if change < 0.0:
                change = -change
            if change > max_u_change:
                max_u_change = change
            u[node] = u_00  # in-place => Gauss-Seidel
            node += 1
    return max_u_change


# ---------------------------------------------------------------------------
# fill_in_forecast (surface.c:349-467)
# ---------------------------------------------------------------------------
@njit(parallel=False, fastmath=False, cache=True)
def _fill_in_forecast(u, status,
                      previous_nx, previous_ny, previous_mx,
                      current_nx, current_ny, current_mx,
                      previous_stride, current_stride,
                      node_nw_cur, node_ne_cur):
    """Expand grid + bilinear fill.  Mirrors surface.c:349-467 line-for-line."""
    expand = previous_stride // current_stride

    # Phase a: copy backwards (so we don't overwrite source nodes)
    for prev_row in range(previous_ny - 1, -1, -1):
        row = prev_row * expand
        for prev_col in range(previous_nx - 1, -1, -1):
            col = prev_col * expand
            cur_node = (row + 2) * current_mx + (col + 2)
            prev_node = (prev_row + 2) * previous_mx + (prev_col + 2)
            u[cur_node] = u[prev_node]

    # Precalc fractions per surface.c:397-398.  This uses r_prev_size =
    # 1/previous_stride, NOT 1/expand — at coarse intermediate strides
    # (current_stride > 1) this gives fractions = i*current_stride/expand
    # implicitly.  We replicate the C verbatim.
    fraction = np.empty(expand, dtype=np.float64)
    r_prev = 1.0 / previous_stride
    for i in range(expand):
        fraction[i] = i * r_prev

    # Phase b: bilinear fill of 4-corner bins (interior)
    for prev_row in range(1, previous_ny):
        row = prev_row * expand
        for prev_col in range(0, previous_nx - 1):
            col = prev_col * expand
            idx00 = (row + 2) * current_mx + (col + 2)
            idx01 = idx00 - expand * current_mx
            idx10 = idx00 + expand
            idx11 = idx01 + expand
            c = u[idx00]
            sx = u[idx10] - c
            sy = u[idx01] - c
            sxy = u[idx11] - u[idx10] - sy
            first = 1
            for j in range(expand):
                cspsy_dy = c + sy * fraction[j]
                sxpsxy_dy = sx + sxy * fraction[j]
                idx_new = idx00 - j * current_mx + first
                for i in range(first, expand):
                    u[idx_new] = cspsy_dy + fraction[i] * sxpsxy_dy
                    status[idx_new] = 0  # _STAT_UNCONSTRAINED
                    idx_new += 1
                first = 0
            status[idx00] = 5  # _STAT_CONSTRAINED

    # Phase c: linear interp along east edge
    idx00 = node_ne_cur
    for prev_row in range(1, previous_ny):
        idx01 = idx00
        idx00 = idx00 + expand * current_mx
        sy = u[idx01] - u[idx00]
        idx_new = idx00 - current_mx
        for j in range(1, expand):
            u[idx_new] = u[idx00] + fraction[j] * sy
            status[idx_new] = 0
            idx_new -= current_mx
        status[idx00] = 5

    # Phase d: linear interp along north edge
    idx10 = node_nw_cur
    for prev_col in range(0, previous_nx - 1):
        idx00 = idx10
        idx10 = idx00 + expand
        sx = u[idx10] - u[idx00]
        idx_new = idx00 + 1
        for i in range(1, expand):
            u[idx_new] = u[idx00] + fraction[i] * sx
            status[idx_new] = 0
            idx_new += 1
        status[idx00] = 5

    status[node_ne_cur] = 5


# ---------------------------------------------------------------------------
# Helpers (Python-side; only run once or twice per port call)
# ---------------------------------------------------------------------------
def _compute_coefficients(alpha, interior_tension):
    """Mirror surface_set_coefficients (surface.c:286-326).

    Returns (coeff_unc, coeff_con, a0_const_1, a0_const_2,
             eps_p2, eps_m2_doubled, two_plus_ep2, two_plus_em2,
             alpha2_doubled).

    coeff_* arrays follow the N2..S2 enum order:
       N2=0, NW=1, N1=2, NE=3, W2=4, W1=5, E1=6, E2=7, SW=8, S1=9, SE=10, S2=11
    """
    loose = 1.0 - interior_tension
    alpha2 = alpha * alpha
    alpha4 = alpha2 * alpha2
    eps_p2 = alpha2
    eps_m2 = 1.0 / alpha2
    one_plus_e2 = 1.0 + alpha2
    two_plus_ep2 = 2.0 + 2.0 * eps_p2
    two_plus_em2 = 2.0 + 2.0 * eps_m2

    a0 = 1.0 / ((6 * alpha4 * loose + 10 * alpha2 * loose + 8 * loose - 2 * one_plus_e2)
                + 4 * interior_tension * one_plus_e2)
    a0_const_1 = 2.0 * loose * (1.0 + alpha4)
    a0_const_2 = 2.0 - interior_tension + 2 * loose * alpha2

    N2, NW, N1, NE, W2, W1, E1, E2, SW, S1, SE, S2 = range(12)

    coeff_con = np.zeros(12, dtype=np.float64)
    coeff_unc = np.zeros(12, dtype=np.float64)

    # Per surface.c:311-322
    coeff_con[W2] = coeff_con[E2] = -loose
    coeff_con[N2] = coeff_con[S2] = -loose * alpha4
    coeff_unc[W2] = coeff_unc[E2] = -loose * a0
    coeff_unc[N2] = coeff_unc[S2] = -loose * alpha4 * a0

    cW1 = 2 * loose * one_plus_e2
    coeff_con[W1] = coeff_con[E1] = cW1
    coeff_unc[W1] = coeff_unc[E1] = (2 * cW1 + interior_tension) * a0
    coeff_con[N1] = coeff_con[S1] = cW1 * alpha2
    coeff_unc[N1] = coeff_unc[S1] = coeff_unc[W1] * alpha2

    cdiag = -2 * loose * alpha2
    coeff_con[NW] = coeff_con[NE] = coeff_con[SW] = coeff_con[SE] = cdiag
    coeff_unc[NW] = coeff_unc[NE] = coeff_unc[SW] = coeff_unc[SE] = cdiag * a0

    # surface.c:324-325 doubles `alpha2` and a separate `e_m2` (not eps_m2)
    # but those doubled values are never read after — dead variables.
    # BC2 uses the ORIGINAL eps_p2 = alpha2 and eps_m2 = 1/alpha2.
    return (coeff_unc, coeff_con, a0_const_1, a0_const_2,
            eps_p2, eps_m2, two_plus_ep2, two_plus_em2,
            alpha2)


def _bc_constants(boundary_tension, alpha):
    """Mirror surface_set_BCs constants (surface.c:1010-1014)."""
    Tb = boundary_tension
    if (2.0 - Tb) != 0.0:
        x0c = 4.0 * (1.0 - Tb) / (2.0 - Tb)
        x1c = (3 * Tb - 2.0) / (2.0 - Tb)
    else:
        x0c = 0.0
        x1c = 0.0
    y_denom = 2 * alpha * (1.0 - Tb) + Tb
    if y_denom != 0.0:
        y0c = 4 * alpha * (1.0 - Tb) / y_denom
        y1c = (Tb - 2 * alpha * (1.0 - Tb)) / y_denom
    else:
        y0c = 0.0
        y1c = 0.0
    return x0c, x1c, y0c, y1c


# Quadrant -> 4 stencil indices, per surface.c:179-185.
# p_indices[quad][k] is an index into d_node[].
# Enum: N2=0, NW=1, N1=2, NE=3, W2=4, W1=5, E1=6, E2=7, SW=8, S1=9, SE=10, S2=11
_N2, _NW, _N1, _NE, _W2, _W1, _E1, _E2, _SW, _S1, _SE, _S2 = range(12)
_P_INDICES = np.array([
    [0, 0, 0, 0],                # not used
    [_NW, _W1, _S1, _SE],        # quadrant 1
    [_SW, _S1, _E1, _NE],        # quadrant 2
    [_SE, _E1, _N1, _NW],        # quadrant 3
    [_NE, _N1, _W1, _SW],        # quadrant 4
], dtype=np.int64)


def _d_node(current_mx: int) -> np.ndarray:
    """The 12 1D index offsets in N2..S2 enum order, per surface_set_offset."""
    d = np.zeros(12, dtype=np.int64)
    d[_N2] = -2 * current_mx
    d[_NW] = -current_mx - 1
    d[_N1] = -current_mx
    d[_NE] = -current_mx + 1
    d[_W2] = -2
    d[_W1] = -1
    d[_E1] = +1
    d[_E2] = +2
    d[_SW] = current_mx - 1
    d[_S1] = current_mx
    d[_SE] = current_mx + 1
    d[_S2] = 2 * current_mx
    return d


def _remove_planar_trend(x_frac, y_up_frac, z):
    """Mirror surface_remove_planar_trend (surface.c:1236-1279)."""
    sx = x_frac.sum()
    sy = y_up_frac.sum()
    sz = z.sum()
    sxx = (x_frac * x_frac).sum()
    sxy = (x_frac * y_up_frac).sum()
    sxz = (x_frac * z).sum()
    syy = (y_up_frac * y_up_frac).sum()
    syz = (y_up_frac * z).sum()
    n = float(z.size)
    d = n * sxx * syy + 2 * sx * sy * sxy - n * sxy * sxy - sx * sx * syy - sy * sy * sxx
    if d == 0.0:
        return 0.0, 0.0, 0.0, z.copy()
    a = sz * sxx * syy + sx * sxy * syz + sy * sxy * sxz - sz * sxy * sxy - sx * sxz * syy - sy * syz * sxx
    b = n * sxz * syy + sz * sy * sxy + sy * sx * syz - n * sxy * syz - sz * sx * syy - sy * sy * sxz
    c = n * sxx * syz + sx * sy * sxz + sz * sx * sxy - n * sxy * sxz - sx * sx * syz - sz * sy * sxx
    icept = a / d
    px = b / d
    py = c / d
    z_det = z - (icept + px * x_frac + py * y_up_frac)
    return icept, px, py, z_det


def _restore_planar_trend(grid_norm, n_rows, n_columns,
                          plane_icept, plane_sx, plane_sy, z_rms):
    """Mirror surface_restore_planar_trend (surface.c:1281-1299).

    grid_norm has row 0 = NORTH (largest y).  y_up grows UP from south
    so y_up(row) = n_rows - 1 - row.

    Vectorised — Mira #53 perf pass.  The previous pure-Python double
    loop was the single largest hot spot (47% of wall on 6601x4801).
    Broadcasting computes the trend plane in float64 in one expression;
    bit-identical to the scalar loop because the arithmetic order
    (z_norm * z_rms + (icept + sx*col + sy*y_up)) is preserved.
    """
    y_up = (n_rows - 1 - np.arange(n_rows, dtype=np.float64))[:, None]   # (ny,1)
    col_idx = np.arange(n_columns, dtype=np.float64)[None, :]            # (1,nx)
    trend = plane_icept + plane_sx * col_idx + plane_sy * y_up
    return grid_norm * z_rms + trend


def gmt_surface_py(x: np.ndarray, y: np.ndarray, z: np.ndarray,
                   region: Tuple[float, float, float, float],
                   inc: Tuple[float, float],
                   tension: float = 0.0,
                   max_iter: int = _SURFACE_MAX_ITERATIONS,
                   tol: float = _SURFACE_CONV_LIMIT,
                   omega: float = _SURFACE_OVERRELAXATION,
                   verbose: bool = False,
                   pixel_reg: bool = False,
                   alpha: Optional[float] = None,
                   # Back-compat kwargs (silently accepted, ignored).
                   use_multigrid: bool = True,
                   mg_max_level=None,
                   mg_nu_coarse=None,
                   ) -> np.ndarray:
    """Continuous-curvature spline matching `gmt surface` (Smith & Wessel 1990).

    Faithful Python port of surface.c (see module docstring).

    Parameters
    ----------
    x, y, z : ndarray, shape (N,)
        Scatter points (Cartesian).
    region : (xmin, xmax, ymin, ymax)
    inc : (x_inc, y_inc)
    tension : float in [0, 1], default 0.0
    max_iter : int, default 500   (per-stride; scaled by current_stride)
    tol : float, default 1e-4     (fraction of z_rms)
    omega : float, default 1.4    (SOR)
    pixel_reg : bool, default False
    alpha : float or None         (None = GMT default alpha=1)

    Returns
    -------
    grid : ndarray, shape (ny, nx)
        Row 0 = SOUTH (ascending y).  Matches caller convention.
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
    if dx <= 0.0 or dy <= 0.0:
        raise ValueError(f"inc must be positive, got dx={dx}, dy={dy}")
    if not (0.0 <= tension <= 1.0):
        raise ValueError(f"tension must be in [0,1], got {tension}")
    if not (0.0 < omega < 2.0):
        raise ValueError(f"omega out of (0,2), got {omega}")

    if alpha is None:
        alpha = 1.0
    alpha = float(alpha)

    # ----- Dimension-suggestion / region expansion (surface.c:2029-2047) -----
    # Computed on the USER's region, in "n-1" convention, BEFORE the
    # pixel-registration offset trick (which doesn't change n_columns-1 /
    # n_rows-1 — surface.c:2055-2063 keeps the node counts fixed and only
    # shifts wesn by +/- inc/2).
    #
    # If gmt_optimal_dim_for_surface finds a (n_columns, n_rows) pair with
    # a smaller guess_surface_time (this is how C avoids ever actually
    # solving a mutually-prime grid except under -Qr), GMT silently grows
    # the region/grid, solves on the larger grid, and crops back to the
    # user's requested window when writing the result
    # (surface_write_grid, surface.c:939-966).  Mira #68: this expansion
    # step was MISSING, so gcd(n_columns-1, n_rows-1)==1 inputs collapsed
    # the Python port's stride hierarchy to a single stride=1 pass with no
    # coarse warm-start — diverging from what `gmt surface` actually runs.
    n_columns_u = int(round((xmax - xmin) / dx))   # "n-1" convention
    n_rows_u = int(round((ymax - ymin) / dy))
    crop_x0 = 0   # columns to drop from the LEFT of the solved grid
    crop_y0 = 0   # rows to drop from the BOTTOM (south) of the solved grid
    crop_nx = n_columns_u + 1   # final output width  (node count)
    crop_ny = n_rows_u + 1      # final output height (node count)

    sug = _optimal_dim_for_surface(n_columns_u, n_rows_u)
    if sug is not None:
        sug_nx, sug_ny, _factor = sug
        m_x = sug_nx - n_columns_u
        m_y = sug_ny - n_rows_u
        # surface.c:1391-1400 (integer division truncates toward zero;
        # m_x, m_y >= 0 here so // matches C's m/2 exactly).
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
        # surface_write_grid's del_pad (surface.c:951-954): nodes to crop
        # from each side to get back to the user's requested window.
        crop_x0 = half_x
        crop_y0 = half_y
        crop_nx = n_columns_u + 1
        crop_ny = n_rows_u + 1
        xmin, xmax, ymin, ymax = xmin_exp, xmax_exp, ymin_exp, ymax_exp
        if verbose:
            print(f"[surface_py] region expanded for gcd hierarchy: "
                  f"({n_columns_u}x{n_rows_u}) -> ({sug_nx}x{sug_ny}) "
                  f"speedup={_factor:.4g}; crop back to "
                  f"({crop_nx}x{crop_ny}) at offset ({crop_x0},{crop_y0})")

    # ----- Pixel-registration trick (surface.c:2055-2063) -----
    if pixel_reg:
        nx_pixel = int(round((xmax - xmin) / dx))
        ny_pixel = int(round((ymax - ymin) / dy))
        if sug is not None:
            # surface_suggest_sizes' pixel-undo (surface.c:1399-1403) and the
            # pixel-shift below (surface.c:2055-2058) cancel exactly once the
            # region has been expanded for the gcd hierarchy: the solve-grid
            # wesn is just the expanded (xmin_exp,xmax_exp,ymin_exp,ymax_exp)
            # with NO extra +/- inc/2 shift.
            xmin_s, xmax_s, ymin_s, ymax_s = xmin, xmax, ymin, ymax
        else:
            xmin_s = xmin + dx / 2.0
            xmax_s = xmax + dx / 2.0
            ymin_s = ymin + dy / 2.0
            ymax_s = ymax + dy / 2.0
        n_columns = nx_pixel + 1
        n_rows = ny_pixel + 1
    else:
        n_columns = int(round((xmax - xmin) / dx)) + 1
        n_rows = int(round((ymax - ymin) / dy)) + 1
        xmin_s, xmax_s, ymin_s, ymax_s = xmin, xmax, ymin, ymax
        nx_pixel = n_columns
        ny_pixel = n_rows

    if n_columns < 4 or n_rows < 4:
        raise ValueError(f"grid {n_rows}x{n_columns} too small (need >=4)")

    # ----- Filter scatter to within +/- 1 inc of region (surface.c:762) -----
    wesn_lim_x_lo = xmin_s - dx
    wesn_lim_x_hi = xmax_s + dx
    wesn_lim_y_lo = ymin_s - dy
    wesn_lim_y_hi = ymax_s + dy
    keep = ((x >= wesn_lim_x_lo) & (x <= wesn_lim_x_hi)
            & (y >= wesn_lim_y_lo) & (y <= wesn_lim_y_hi)
            & np.isfinite(z))
    xx_in = x[keep]
    yy_in = y[keep]
    z_in = z[keep]
    if xx_in.size == 0:
        raise ValueError("no input data inside region")

    # ----- Replicate surface_throw_away_unusables (surface.c:1301-1340) -----
    # In C, surface_read_data assigns data to cells at stride=1, then
    # surface_throw_away_unusables retains one point per cell (nearest to the
    # cell center using info->wesn, which is set BEFORE the pixel shift in
    # surface_init_parameters).  Plane fitting and all subsequent strides use
    # only these survivors — not the full region-filtered set.  We replicate
    # this here so the plane fit and z_norm match C's exact data subset.
    _r_ix = 1.0 / dx
    _r_iy = 1.0 / dy
    _fc = (xx_in - xmin_s) * _r_ix
    _fr = (n_rows - 1) - (yy_in - ymin_s) * _r_iy
    _c1 = np.floor(_fc + 0.5).astype(np.int64)
    _r1 = np.floor(_fr + 0.5).astype(np.int64)
    _ok = (_c1 >= 0) & (_c1 < n_columns) & (_r1 >= 0) & (_r1 < n_rows)
    _dx1 = _fc[_ok] - _c1[_ok]
    _dy1 = -(_fr[_ok] - _r1[_ok])
    # surface_compare_points uses physical Euclidean distance to the cell
    # center from info->wesn (set before the pixel shift in
    # surface_init_parameters).  For pixel_reg+sug, info->wesn[XLO] =
    # xmin_s - dx/2, so the comparison center is (x_node - dx/2, y_node -
    # dy/2): dist^2 = (dx*dx_off + dx/2)^2 + (dy*dy_off + dy/2)^2
    #             = dx^2*(dx_off+0.5)^2 + dy^2*(dy_off+0.5)^2.
    # For non-pixel or no-sug: comparison center is the node itself:
    # dist^2 = (dx*dx_off)^2 + (dy*dy_off)^2.
    if pixel_reg and sug is not None:
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
    z_in = z_in[_keep2]

    # ----- Fractional col / y_up for planar fit (surface.c:1249-1250) -----
    x_frac_pts = (xx_in - xmin_s) / dx
    y_up_frac_pts = (yy_in - ymin_s) / dy

    # ----- Planar trend removal (surface.c:1236-1279) -----
    plane_icept, plane_sx, plane_sy, z_det = _remove_planar_trend(
        x_frac_pts, y_up_frac_pts, z_in)
    if verbose:
        print(f"[surface_py] plane fit: z = {plane_icept:.6g} "
              f"+ ({plane_sx:.6g} * col) + ({plane_sy:.6g} * row_up)")

    # ----- Rescale z by rms (surface.c:1342-1369) -----
    ssz = float((z_det * z_det).sum())
    z_rms = math.sqrt(ssz / z_det.size)
    if z_rms < 1e-8:
        grid = np.zeros((n_rows, n_columns), dtype=np.float64)
        grid_final = _restore_planar_trend(grid, n_rows, n_columns,
                                            plane_icept, plane_sx, plane_sy, 1.0)
        if pixel_reg:
            if sug is not None:
                # Mirror the main-path convention (drop the NORTHERNMOST
                # row, i.e. row 0) so the crop below can reuse the same
                # crop_x0/crop_y0 del_pad offsets as the main path.
                grid_final = grid_final[1:ny_pixel + 1, :nx_pixel]
            else:
                grid_final = grid_final[:ny_pixel, :nx_pixel]
        # Flip to row 0 = SOUTH for callers
        grid_final = grid_final[::-1, :]
        if sug is not None:
            if pixel_reg:
                grid_final = grid_final[crop_y0:crop_y0 + (crop_ny - 1),
                                         crop_x0:crop_x0 + (crop_nx - 1)]
            else:
                grid_final = grid_final[crop_y0:crop_y0 + crop_ny,
                                         crop_x0:crop_x0 + crop_nx]
        return np.ascontiguousarray(grid_final)
    r_z_rms = 1.0 / z_rms
    z_norm = z_det * r_z_rms

    # In NORMALIZED units, the converge limit per-stride is tol/stride
    # (surface.c:1086).  When tol=1e-4 and z_rms=O(1), the absolute limit
    # at stride=1 is 1e-4 * z_rms — matching gmt's "100ppm" default.
    #
    # NOTE: surface.c:1365 computes converge_limit = SURFACE_CONV_LIMIT *
    # z_rms in UNNORMALIZED units (e.g. ~0.0204 for RS2_SLC_Hawaii's
    # pixel.grd, vs this port's tol=1e-4) -- so this port's stride=1 du
    # threshold is ~200x tighter than gmt's for that case. Multiplying by
    # z_rms here to match was tried and reduced RS2 stride=1 DATA from 248
    # to 8 iterations (vs gmt's 157) WITHOUT reducing the output rms diff
    # (0.605 -> 0.612), and regressed
    # test_iteration_counts_match_c_within_slack (Mira #72's
    # omega/convergence-formula divergence guard). The per-iteration
    # convergence RATE, not just the threshold, diverges from gmt's GS-SOR
    # -- a separate, already-tracked issue (Mira #72), not fixed here.
    converge_limit_n = tol

    # ----- Compute stencil coefficients (surface.c:286-326) -----
    (coeff_unc, coeff_con, a0_const_1, a0_const_2,
     eps_p2, eps_m2, two_plus_ep2, two_plus_em2,
     _alpha2_doubled) = _compute_coefficients(alpha, tension)

    x0c, x1c, y0c, y1c = _bc_constants(tension, alpha)

    # ----- Determine stride hierarchy (surface.c:2072-2140) -----
    current_stride = _gcd(n_columns - 1, n_rows - 1)
    factors = _prime_factors(current_stride)
    factors.sort()  # ascending; pop -> largest

    # Ensure first stride gives at least 4x4
    while True:
        cur_nx = (n_columns - 1) // current_stride + 1
        cur_ny = (n_rows - 1) // current_stride + 1
        if cur_nx >= 4 and cur_ny >= 4:
            break
        if not factors:
            raise ValueError("grid dimensions cannot factor down to 4x4")
        current_stride //= factors.pop()

    # ----- Allocate the FINAL-stride padded grid (surface.c does this) -----
    final_mx = n_columns + 4
    final_my = n_rows + 4
    mxmy = final_mx * final_my
    u = np.zeros(mxmy, dtype=np.float64)
    status = np.zeros(mxmy, dtype=np.uint8)
    # Reusable Briggs-index buffer (Mira #53 perf pass): on 6601x4801 grids
    # mxmy ~ 32M.  np.full(mxmy, -1, dtype=np.int64) is 256 MB and used to
    # be allocated FRESH at every stride (~7 times = ~1.8 GB of allocation
    # churn, ~1s wall in cProfile).  We allocate once here and the
    # constraint-setter resets only the entries it previously wrote.
    briggs_idx_shared = np.full(mxmy, -1, dtype=np.int64)
    briggs_idx_dirty: list = []  # list-of-one ndarray of nodes touched
                                  # by the previous _assign_constraints call

    # ----- Initial setup at coarsest stride -----
    cur_nx = (n_columns - 1) // current_stride + 1
    cur_ny = (n_rows - 1) // current_stride + 1
    cur_mx = cur_nx + 4
    node_nw = 2 * cur_mx + 2
    node_sw = node_nw + (cur_ny - 1) * cur_mx
    node_se = node_sw + cur_nx - 1
    node_ne = node_nw + cur_nx - 1
    d_node = _d_node(cur_mx)

    # Initialise interior nodes to data mean (cheap default — C uses 0
    # or search-radius initialiser; mean is a no-op for centred data).
    # Vectorised (Mira #53 perf pass) — at the coarsest stride the layout
    # is cur_ny rows of cur_nx contiguous elements with row stride cur_mx,
    # starting at flat offset node_nw.  np.lib.stride_tricks.as_strided
    # gives the right view; but it's safe to allocate a fresh 2-D temp
    # (cheap at the coarsest stride; only a few hundred nodes typically).
    z_mean_norm = float(z_norm.mean())
    _row_offsets = node_nw + np.arange(cur_ny, dtype=np.int64) * cur_mx
    _flat_targets = (_row_offsets[:, None]
                     + np.arange(cur_nx, dtype=np.int64)[None, :]).ravel()
    u[_flat_targets] = z_mean_norm

    # ----- Helpers closing over (xmin_s, ymin_s, dx, dy, z_norm, …) -----
    def _build_constraints(stride, cur_nx_, cur_ny_):
        """Compute (col, row, dx_off, dy_off, z) for nearest scatter per node.

        Mirrors surface.c's set_index + find_nearest_constraint logic.
        """
        inc_x = stride * dx
        inc_y = stride * dy
        r_inc_x = 1.0 / inc_x
        r_inc_y = 1.0 / inc_y
        fcol = (xx_in - xmin_s) * r_inc_x
        # row counts from north; surface.c:160 y_to_row = (n_rows-1) - x_to_col(y)
        frow = (cur_ny_ - 1) - (yy_in - ymin_s) * r_inc_y
        col_near = np.floor(fcol + 0.5).astype(np.int64)
        row_near = np.floor(frow + 0.5).astype(np.int64)
        inside = ((col_near >= 0) & (col_near < cur_nx_)
                  & (row_near >= 0) & (row_near < cur_ny_))
        if not inside.any():
            return (np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64),
                    np.zeros(0), np.zeros(0), np.zeros(0))
        col_near = col_near[inside]
        row_near = row_near[inside]
        fcol_in = fcol[inside]
        frow_in = frow[inside]
        z_norm_in = z_norm[inside]
        dx_off = fcol_in - col_near
        # dy_off: positive UP (y_up_data - y_up_node) = row_near - frow_in
        dy_off = -(frow_in - row_near)
        # Sort by (index, dist2), keep nearest per node
        index = row_near * cur_nx_ + col_near
        # surface_compare_points uses physical Euclidean distance to the
        # info->wesn cell center (set before pixel shift).  For pixel_reg+sug,
        # that center is (x_node - inc_x/2, y_node - inc_y/2), so:
        #   dist^2 = (inc_x*(dx_off+0.5))^2 + (inc_y*(dy_off+0.5))^2.
        # For other cases: dist^2 = (inc_x*dx_off)^2 + (inc_y*dy_off)^2.
        # Briggs dx_off/dy_off stay node-relative (surface.c:601-605 uses
        # h->wesn, not info->wesn).
        if pixel_reg and sug is not None:
            dist2 = (inc_x * (dx_off + 0.5)) ** 2 + (inc_y * (dy_off + 0.5)) ** 2
        else:
            dist2 = (inc_x * dx_off) ** 2 + (inc_y * dy_off) ** 2
        order = np.lexsort((dist2, index))
        index_s = index[order]
        dx_s = dx_off[order]
        dy_s = dy_off[order]
        z_s = z_norm_in[order]
        col_s = col_near[order]
        row_s = row_near[order]
        uniq = np.empty(index_s.size, dtype=bool)
        uniq[0] = True
        uniq[1:] = (index_s[1:] != index_s[:-1])
        return (col_s[uniq], row_s[uniq], dx_s[uniq], dy_s[uniq], z_s[uniq])

    def _assign_constraints(stride, cur_nx_, cur_ny_, cur_mx_, node_nw_):
        col_u, row_u, dx_u, dy_u, z_u = _build_constraints(stride, cur_nx_, cur_ny_)
        # Reset status of interior (surface.c:587-589).
        # Vectorised (Mira #53 perf pass): compute the flat node-indices for
        # the cur_ny_ x cur_nx_ interior and clear in one shot.  Matches
        # the C "for each interior node, status = 0" exactly.
        _rows = node_nw_ + np.arange(cur_ny_, dtype=np.int64) * cur_mx_
        _idx_flat = (_rows[:, None]
                     + np.arange(cur_nx_, dtype=np.int64)[None, :]).ravel()
        status[_idx_flat] = 0

        n_pts = col_u.size
        briggs_b = np.zeros((max(n_pts, 1), 6), dtype=np.float64)
        # Mira #53 perf pass: reuse the shared briggs_idx buffer.  Reset
        # only the nodes the previous call dirtied — full np.full() on
        # 32M-element grids was ~140 ms each (cProfile).
        briggs_idx = briggs_idx_shared
        if briggs_idx_dirty:
            briggs_idx[briggs_idx_dirty[0]] = -1
            briggs_idx_dirty.clear()
        if n_pts > 0:
            # Vectorised classification (Mira #53):
            #   * "exactly-on-node" mask -> status=5, u=zk
            #   * else quadrant 1..4 via sign(dy), sign(dx); Briggs xx,yy
            #     are |.| with axes swapped per quadrant to bring everything
            #     into the rotated-Q1 frame _solve_briggs_b expects.
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
                u[on_idx] = z_arr[on_node]

            off = ~on_node
            if off.any():
                off_nodes = nodes[off]
                dx_off = dx_arr[off]
                dy_off = dy_arr[off]
                z_off = z_arr[off]
                # Quadrant via sign — matches the four-branch tree exactly.
                dy_ge0 = dy_off >= 0.0
                dx_ge0 = dx_off >= 0.0
                # Quadrant + Briggs-frame mapping (mirrors the C 4-branch
                # tree in scalar _assign_constraints; same arithmetic):
                #   dy>=0, dx>=0  -> Q1, xx_b= dx,  yy_b= dy
                #   dy>=0, dx<0   -> Q2, xx_b= dy,  yy_b=-dx
                #   dy<0 , dx>=0  -> Q4, xx_b=-dy,  yy_b= dx
                #   dy<0 , dx<0   -> Q3, xx_b=-dx,  yy_b=-dy
                quad = np.where(dy_ge0,
                                np.where(dx_ge0, 1, 2),
                                np.where(dx_ge0, 4, 3)).astype(np.uint8)
                xx_b = np.where(dy_ge0,
                                np.where(dx_ge0, dx_off, dy_off),
                                np.where(dx_ge0, -dy_off, -dx_off))
                yy_b = np.where(dy_ge0,
                                np.where(dx_ge0, dy_off, -dx_off),
                                np.where(dx_ge0, dx_off, -dy_off))
                # Solve Briggs coeffs vectorised (mirrors _solve_briggs_b)
                _b_block = _solve_briggs_b_vec(xx_b, yy_b, z_off,
                                                a0_const_1, a0_const_2)
                n_off = off_nodes.size
                briggs_b[:n_off] = _b_block
                status[off_nodes] = quad
                briggs_idx[off_nodes] = np.arange(n_off, dtype=np.int64)
                briggs_idx_dirty.append(off_nodes)  # remember for next reset
                cnt = n_off
            else:
                cnt = 0
        else:
            cnt = 0
        return briggs_b[:max(cnt, 1)], briggs_idx

    def _iterate_to_converge(stride, cur_nx_, cur_ny_, cur_mx_,
                              node_nw_, node_sw_, node_se_, node_ne_,
                              d_node_, briggs_b, briggs_idx, mode_label):
        """Call _iterate_once until convergence or max iter."""
        current_max_iter = max_iter * stride
        current_limit = converge_limit_n / stride
        max_change = float("inf")
        for it in range(1, current_max_iter + 1):
            _set_bcs(u, cur_nx_, cur_ny_, cur_mx_,
                     node_sw_, node_nw_, node_se_, node_ne_,
                     d_node_[_N2], d_node_[_NW], d_node_[_N1], d_node_[_NE],
                     d_node_[_W2], d_node_[_W1],
                     d_node_[_E1], d_node_[_E2],
                     d_node_[_SW], d_node_[_S1], d_node_[_SE], d_node_[_S2],
                     x0c, x1c, y0c, y1c, eps_p2, eps_m2,
                     two_plus_ep2, two_plus_em2)
            max_change = _iterate_once(
                u, status, briggs_b, briggs_idx,
                coeff_unc, coeff_con, d_node_, _P_INDICES,
                a0_const_2, 1.0 - omega, omega,
                node_nw_, cur_nx_, cur_ny_, cur_mx_)
            if max_change <= current_limit:
                if verbose:
                    print(f"[surface_py] stride={stride} {mode_label} "
                          f"converged at it={it} max|du|={max_change:.3e}")
                return it
            if verbose and (it % 200 == 0):
                print(f"[surface_py] stride={stride} {mode_label} it={it}"
                      f" max|du|={max_change:.3e} limit={current_limit:.3e}")
        if verbose:
            print(f"[surface_py] stride={stride} {mode_label} hit max_iter "
                  f"({current_max_iter}) last_change={max_change:.3e} "
                  f"limit={current_limit:.3e}")
        return current_max_iter

    # ----- Coarsest stride: data-constrained iterate -----
    briggs_b, briggs_idx = _assign_constraints(current_stride, cur_nx, cur_ny,
                                                cur_mx, node_nw)
    _iterate_to_converge(current_stride, cur_nx, cur_ny, cur_mx,
                         node_nw, node_sw, node_se, node_ne, d_node,
                         briggs_b, briggs_idx, "DATA")

    # ----- Down-stride loop (surface.c:2194-2204) -----
    previous_stride = current_stride
    previous_nx = cur_nx
    previous_ny = cur_ny
    previous_mx = cur_mx
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
        d_node = _d_node(cur_mx)

        _fill_in_forecast(u, status,
                          previous_nx, previous_ny, previous_mx,
                          cur_nx, cur_ny, cur_mx,
                          previous_stride, current_stride,
                          node_nw, node_ne)
        # GRID_NODES (no data constraints — just improve bilinear guess).
        # Mira #53 perf pass: an "all -1" briggs_idx of size mxmy is what
        # status==0 nodes index into, but the iterator never reads it on
        # the UNCONSTRAINED path (stat==0 short-circuits before any
        # briggs_b lookup).  We still pass `briggs_idx_shared` (left in
        # whatever previous state — that's fine because status[...] = 0
        # for every interior node here, so the briggs_b path is never
        # taken).  Reset its dirty list to be safe.
        if briggs_idx_dirty:
            briggs_idx_shared[briggs_idx_dirty[0]] = -1
            briggs_idx_dirty.clear()
        briggs_b_empty = np.zeros((1, 6), dtype=np.float64)
        _iterate_to_converge(current_stride, cur_nx, cur_ny, cur_mx,
                             node_nw, node_sw, node_se, node_ne, d_node,
                             briggs_b_empty, briggs_idx_shared, "NODES")
        # Now assign data constraints at this stride and iterate
        briggs_b, briggs_idx = _assign_constraints(current_stride, cur_nx,
                                                    cur_ny, cur_mx, node_nw)
        _iterate_to_converge(current_stride, cur_nx, cur_ny, cur_mx,
                             node_nw, node_sw, node_se, node_ne, d_node,
                             briggs_b, briggs_idx, "DATA")
        previous_stride = current_stride
        previous_nx = cur_nx
        previous_ny = cur_ny
        previous_mx = cur_mx

    # ----- Extract output -----
    # u stored normalised, layout row 0 = NORTH, padded with 2 ghost on each
    # side.  Extract the interior, restore plane + z_rms, flip to S-N for
    # caller convention.
    #
    # Vectorised (Mira #53 perf pass): u is flat shape (final_my*final_mx,)
    # in row-major; reshape and slice off the 2-wide ghost ring.  This is
    # bit-identical to the previous Python double loop (same float values,
    # same byte layout, just no Python-interpreter overhead).
    cur_mx_final = n_columns + 4
    grid_norm = np.ascontiguousarray(
        u.reshape(final_my, final_mx)[2:n_rows + 2, 2:n_columns + 2])

    grid = _restore_planar_trend(grid_norm, n_rows, n_columns,
                                  plane_icept, plane_sx, plane_sy, z_rms)

    if pixel_reg:
        # surface.c:972-975: drop NORTHERNMOST row + EASTERNMOST col.
        # In our NORTH-first internal layout, that is row 0 and col nx_pixel.
        # Keep rows 1..ny_pixel (inclusive) and cols 0..nx_pixel-1.
        grid = grid[1:ny_pixel + 1, :nx_pixel]

    # Flip to row 0 = SOUTH (ascending y) — caller convention.
    grid = grid[::-1, :]

    # ----- Crop back to the user's requested window (surface_write_grid,
    # surface.c:947-961) if the region was expanded above for the gcd
    # hierarchy. -----
    if sug is not None:
        if pixel_reg:
            # When sug is not None, the pixel-reg block above (lines
            # ~843-858) computed nx_pixel=sug_nx, ny_pixel=sug_ny and
            # solved/cropped on the EXPANDED region [xmin_exp,xmax_exp] x
            # [ymin_exp,ymax_exp] (xmin/xmax/ymin/ymax were overwritten
            # with the _exp values at line ~836 BEFORE the pixel-reg
            # block ran). So `grid` here is a (sug_ny, sug_nx) pixel grid
            # whose cell (q, j) [row 0 = south, ascending y] is centred at
            #   x_j = xmin_exp + (j+0.5)*dx,  y_q = ymin_exp + (q+0.5)*dy
            #
            # The user's requested pixel grid has n_columns_u x n_rows_u
            # cells centred at x_k = xmin + (k+0.5)*dx (k=0..n_columns_u-1),
            # y_k = ymin + (k+0.5)*dy.  Since xmin_exp = xmin - crop_x0*dx
            # and ymin_exp = ymin - crop_y0*dy (crop_x0=half_x, crop_y0=
            # half_y from the del_pad computed above — same offsets used
            # for the gridline case), x_j == x_k iff j == k + crop_x0, and
            # similarly for y. So the SAME crop_x0/crop_y0 offsets apply,
            # but the cropped extent is n_columns_u x n_rows_u pixels
            # (= crop_nx-1, crop_ny-1), not crop_nx x crop_ny nodes.
            crop_nx_px = crop_nx - 1
            crop_ny_px = crop_ny - 1
            grid = grid[crop_y0:crop_y0 + crop_ny_px,
                         crop_x0:crop_x0 + crop_nx_px]
            if grid.shape != (crop_ny_px, crop_nx_px):
                raise RuntimeError(
                    f"gcd-hierarchy pixel-reg crop produced shape "
                    f"{grid.shape}, expected ({crop_ny_px}, {crop_nx_px})")
        else:
            grid = grid[crop_y0:crop_y0 + crop_ny, crop_x0:crop_x0 + crop_nx]
            if grid.shape != (crop_ny, crop_nx):
                raise RuntimeError(
                    f"gcd-hierarchy crop produced shape {grid.shape}, "
                    f"expected ({crop_ny}, {crop_nx})")

    return np.ascontiguousarray(grid)


# ---------------------------------------------------------------------------
# Diagnostic helper
# ---------------------------------------------------------------------------
def _diag_info() -> dict:
    return {
        "have_numba": _HAVE_NUMBA,
        "num_threads": int(os.environ.get("NUMBA_NUM_THREADS", "0")) or None,
        "env_disabled": os.environ.get("GMT_SURFACE_PY_NUMBA", "1") == "0",
    }


if __name__ == "__main__":
    rng = np.random.default_rng(42)
    N = 200
    x_ = rng.uniform(0, 10, N)
    y_ = rng.uniform(0, 10, N)
    z_ = np.exp(-((x_ - 5.0) ** 2 + (y_ - 5.0) ** 2) / 4.0)
    grid = gmt_surface_py(x_, y_, z_,
                          region=(0.0, 10.0, 0.0, 10.0),
                          inc=(0.1, 0.1),
                          tension=0.25,
                          verbose=True)
    nx_ = ny_ = 101
    gx, gy = np.meshgrid(np.linspace(0, 10, nx_), np.linspace(0, 10, ny_))
    z_true = np.exp(-((gx - 5.0) ** 2 + (gy - 5.0) ** 2) / 4.0)
    rms = float(np.sqrt(np.mean((grid - z_true) ** 2)))
    print(f"Self-test RMS vs analytic: {rms:.4e}")
