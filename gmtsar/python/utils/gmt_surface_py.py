#!/usr/bin/env python3
"""gmt_surface_py — Numba-accelerated prototype of GMT `surface` (Smith & Wessel 1990).

Continuous-curvature spline interpolator under tension.  The PDE is

    (1 - T) * grad^4 u  +  (T / h^2) * grad^2 u  =  0

with T in [0, 1].  T = 0 gives a pure minimum-curvature (biharmonic) spline;
T = 1 collapses to a harmonic (Laplace) interpolant.  Data constraints at
scatter points are imposed by snapping each input (x_k, y_k, z_k) to the
nearest grid node and pinning u[i, j] = z_k at that node throughout
relaxation (a simplification of GMT's Briggs sub-cell interpolator — see
LIMITATIONS below).

Algorithm reference
-------------------
Upstream C reference (GenericMappingTools/gmt master):
    src/surface.c
      - surface_set_coefficients()  : lines 180-220   (eqs A-4, A-7 weights)
      - surface_iterate()           : lines 1430-1500 (12-pt sweep + relax)
      - surface_set_BCs()           : lines 1140-1220 (natural BC, eqs A-8..10)

This prototype implements the unconstrained 12-point biharmonic stencil
(square cells, alpha = dy/dx = 1) plus a tension-weighted Laplacian, with
natural BCs (zero second derivative at the boundary) and Jacobi-style
relaxation.  No multigrid yet — single-resolution only.  See the matching
test (bin_py/tests/test_gmt_surface_py.py) for parity vs `gmt surface`.

Limitations (vs upstream gmt surface)
-------------------------------------
1. **No multigrid.**  GMT surface coarsens by strides 32->16->...->1.  We
   start at the final stride directly.  Convergence is slower but the
   converged answer is the same to within tol.
2. **Snap-to-node data constraints.**  GMT uses Briggs sub-cell offsets
   (eq A-6, A-7) so the surface honours the data at its exact off-node
   location.  We snap to the nearest grid node.  For tests with input
   points near grid nodes this is roundoff-equivalent; for input points
   mid-cell the local error is O(h * |grad z|).
3. **alpha = 1.**  Only square cells (dx == dy) are supported.  Upstream
   handles anisotropic cells via the alpha2 / alpha4 prefactors in the
   stencil.  TODO for production.
4. **Single thread fallback** when env var GMT_SURFACE_PY_NUMBA=0.

Performance
-----------
The inner Jacobi sweep is `@njit(parallel=True)` with `prange` over rows.
Tension and BC application are kept in Python (cheap, < 1% of runtime on
realistic grids).  Expected 5-10x speedup at 8 threads vs single-thread
gmt surface on grids >= 1000x1000.

Multigrid acceleration (added in Mira #21)
-------------------------------------------
The Jacobi smoother is asymptotically O(N**2) for the biharmonic — high-
frequency error modes are damped quickly but low-frequency modes take ~N
iterations to die out, so a 1001x1001 grid needs hundreds of sweeps for
plain Jacobi to converge.  This module accelerates relaxation with a
**Full Multigrid (FMG) / nested-iteration** scheme that matches GMT
surface's own design:

    s = 2^(K-1)             # coarsest stride (every s'th node)
    solve on stride-s grid via damped Jacobi
    for k in K-2 .. 0:
        s = 2^k
        prolongate the stride-(2s) solution to the stride-s grid (bilinear)
        snap data constraints onto the new (denser) nodes
        relax to per-level tolerance via damped Jacobi

Each level's relaxation converges quickly because the prolongated
solution from the previous (coarser) level is a near-perfect initial
guess for the smooth modes.  The smoother only needs to kill the new
high-frequency content introduced by refinement — Jacobi does this in
O(1) sweeps regardless of grid size.  Total cost is dominated by the
finest level, where we run ~100-300 sweeps; that is still O(N) better
than the O(N^2) cold-start Jacobi.

Why FMG and not classical V-cycles?  A standard V-cycle (smooth /
restrict residual / recursive solve / prolongate correction / smooth)
needs the coarse-grid operator to be a faithful coarsening of the fine
operator.  Our 12-point stencil has h-independent constants but the
underlying PDE has L ~ h^-4 (biharmonic) and L ~ h^-2 (Laplacian) — the
scaling matters for correction.  A naive same-stencil V-cycle on the
biharmonic diverges on grids larger than 251x251 (confirmed empirically:
operator-scaling factors of 1 and 16 both fail, the former by slow
divergence, the latter by immediate amplification).  FMG sidesteps this
because each level's relaxation is a complete solve of the same PDE at
that level's resolution; no cross-level operator consistency is needed.

Public API
----------
gmt_surface_py(x, y, z, region, inc, tension=0.5, max_iter=1000, tol=1e-4,
               use_multigrid=True, mg_max_level=None, mg_nu_coarse=50)
    Scattered -> regular grid.  Returns (ny, nx) ndarray.
"""
from __future__ import annotations

import os
from typing import Optional, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Numba availability + soft fallback
# ---------------------------------------------------------------------------

_USE_NUMBA = os.environ.get("GMT_SURFACE_PY_NUMBA", "1") != "0"

try:
    if _USE_NUMBA:
        from numba import njit, prange
        _HAVE_NUMBA = True
    else:
        raise ImportError("disabled by GMT_SURFACE_PY_NUMBA=0")
except Exception:  # pragma: no cover
    _HAVE_NUMBA = False

    def njit(*args, **kwargs):  # type: ignore
        # accept both @njit and @njit(...) usage
        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]
        def deco(f):
            return f
        return deco

    def prange(*args):  # type: ignore
        # Mirror builtin range() signature so the kernel can be JIT'd OR
        # run as a plain Python loop without changes.
        return range(*args)


# ---------------------------------------------------------------------------
# Multigrid V-cycle constants
# ---------------------------------------------------------------------------
# Smallest grid size we allow as a multigrid level (must be >= 5 for the
# 12-point stencil to have any interior nodes after the 2-wide ghost ring).
_MG_MIN_DIM = 9   # leaves at least 5x5 interior (kept) nodes per axis


# ---------------------------------------------------------------------------
# Inner kernel — one Jacobi sweep of the 12-point biharmonic + tension stencil
# ---------------------------------------------------------------------------
# Stencil layout (square cell, h=dx=dy):
#
#           NN
#       NW  N   NE
#    WW  W  *   E  EE
#       SW  S   SE
#           SS
#
# Update at interior node u[i, j]:
#   numer = (1-T) * [8*(N+S+E+W) - 2*(NE+NW+SE+SW) - (NN+SS+EE+WW)] + T*(N+S+E+W)
#   denom = 20*(1-T) + 4*T  =  20 - 16T
#   u_new[i, j] = numer / denom
#
# Where T in [0, 1] is the interior tension and the data-constrained nodes
# (`fixed[i, j] == True`) are skipped (held at the data value).
#
# Jacobi (not Gauss-Seidel) is used because it parallelises cleanly with
# prange — no row-to-row dependence within one sweep.

@njit(parallel=True, fastmath=False, cache=True)
def _jacobi_sweep(u_old, u_new, fixed, rhs, T, omega, ny_full, nx_full):
    """One Jacobi sweep over interior nodes [2..ny_full-3, 2..nx_full-3].

    Solves the local equation  L[u] = rhs  with the 12-point stencil
    of the (1-T) biharmonic + T Laplacian operator.  On the finest
    multigrid level, `rhs` is zero everywhere and we recover the
    classic homogeneous relaxation.  On coarse levels, `rhs` is the
    restricted residual and the equation being solved is the
    coarse-grid correction equation  L[v] = restrict(residual).

    `u_old`, `u_new`, `fixed`, `rhs` are the FULL padded grid of shape
    (ny+4, nx+4) where the outer 2 rings on each side are ghosts.
    The relaxation domain [2..ny+1] in row index maps to the (ny,nx)
    output grid; the ghosts at rows {0,1,ny+2,ny+3} are set by BC code
    in Python (outside this JIT'd kernel).

    Returns max |u_new - u_old| over the swept domain.
    """
    one_minus_T = 1.0 - T
    denom = 20.0 * one_minus_T + 4.0 * T  # = 20 - 16T

    # per-row max changes, reduced after
    row_max = np.zeros(ny_full, dtype=np.float64)

    for i in prange(2, ny_full - 2):
        local_max = 0.0
        for j in range(2, nx_full - 2):
            if fixed[i, j]:
                u_new[i, j] = u_old[i, j]
                continue

            # First-ring (4) Laplacian-style neighbours
            N_ = u_old[i + 1, j]
            S_ = u_old[i - 1, j]
            E_ = u_old[i, j + 1]
            W_ = u_old[i, j - 1]
            # Diagonal (4)
            NE = u_old[i + 1, j + 1]
            NW = u_old[i + 1, j - 1]
            SE = u_old[i - 1, j + 1]
            SW = u_old[i - 1, j - 1]
            # Second-ring (4) axial
            NN = u_old[i + 2, j]
            SS = u_old[i - 2, j]
            EE = u_old[i, j + 2]
            WW = u_old[i, j - 2]

            sum1 = N_ + S_ + E_ + W_
            sum_diag = NE + NW + SE + SW
            sum2 = NN + SS + EE + WW

            # L[u] center-coeff*u_ij = neighbour_sum + something.
            # Stencil: center_coeff = -(20*(1-T) + 4*T) = -denom (sign chosen so
            # that L[u] = neighbour_terms - denom*u_ij; Jacobi: u_ij_new solves
            #   neighbour_terms - denom*u_ij_new = rhs  =>  u_ij_new = (neighbour_terms - rhs)/denom).
            # neighbour_terms = (1-T)*[8*sum1 - 2*sum_diag - sum2] + T*sum1
            numer = one_minus_T * (8.0 * sum1 - 2.0 * sum_diag - sum2) + T * sum1
            val = (numer - rhs[i, j]) / denom
            # Under-relaxation: u_new = (1-omega)*u_old + omega*val.
            # The biharmonic Jacobi iteration is unstable for omega=1; the
            # damped version converges (slowly) for any T in [0, 1] when
            # omega <= ~0.8.  See README for the formal stability analysis.
            val = (1.0 - omega) * u_old[i, j] + omega * val

            u_new[i, j] = val
            diff = val - u_old[i, j]
            if diff < 0.0:
                diff = -diff
            if diff > local_max:
                local_max = diff

        row_max[i] = local_max

    m = 0.0
    for i in range(ny_full):
        if row_max[i] > m:
            m = row_max[i]
    return m


# ---------------------------------------------------------------------------
# BC application — natural (zero second derivative) at the boundary
# ---------------------------------------------------------------------------
# Mirror the inner 2 rows/cols out so that the second-difference vanishes:
#   u[0, :]   = 2*u[1, :]   - u[2, :]
#   u[-1, :]  = 2*u[-2, :]  - u[-3, :]
#   u[:, 0]   = 2*u[:, 1]   - u[:, 2]
#   u[:, -1]  = 2*u[:, -2]  - u[:, -3]
# (Then the corners are filled by repeating the rule.)
#
# This is a simplification of upstream's surface_set_BCs (eqs A-8..A-10)
# which uses a tension-weighted natural BC.  For the prototype it is good
# enough at interior tension <= 0.5; high T forces u toward harmonic so
# the BC contribution grows.

def _apply_bcs(u: np.ndarray) -> None:
    """In-place natural BC application on a padded grid (ghost ring = 2).

    Convention: the kept domain occupies indices [2 : ny+2, 2 : nx+2] of
    the padded array of shape (ny+4, nx+4).  The natural BC d2u/dn2 = 0
    means each ghost value is the linear extrapolation of the two real
    nodes nearest the boundary:

        u[1, j] = 2*u[2, j]    - u[3, j]
        u[0, j] = 2*u[1, j]    - u[2, j]   = 3*u[2, j] - 2*u[3, j]
        u[-2,j] = 2*u[-3, j]   - u[-4, j]
        u[-1,j] = 2*u[-2, j]   - u[-3, j]

    Order: do rows first (fills row ghosts in column range [2:nx+2]),
    then columns (which now read valid ghost rows at corners).
    """
    # Row ghosts (south / north), columns [2:-2] kept domain
    u[1, 2:-2]  = 2.0 * u[2, 2:-2]   - u[3, 2:-2]
    u[0, 2:-2]  = 2.0 * u[1, 2:-2]   - u[2, 2:-2]
    u[-2, 2:-2] = 2.0 * u[-3, 2:-2]  - u[-4, 2:-2]
    u[-1, 2:-2] = 2.0 * u[-2, 2:-2]  - u[-3, 2:-2]
    # Column ghosts (west / east), ALL rows including corner ghost rows
    u[:, 1]  = 2.0 * u[:, 2]   - u[:, 3]
    u[:, 0]  = 2.0 * u[:, 1]   - u[:, 2]
    u[:, -2] = 2.0 * u[:, -3]  - u[:, -4]
    u[:, -1] = 2.0 * u[:, -2]  - u[:, -3]


# ---------------------------------------------------------------------------
# Multigrid transfer operators (restriction + prolongation).
# ---------------------------------------------------------------------------
# We operate on the KEPT block (no ghost ring) for the transfer; the V-cycle
# driver pads / unpads around each call.  All transfers preserve the
# gridline-registration convention: the coarse grid's i,j corresponds to
# the fine grid's 2*i, 2*j node.
#
# Restriction: full-weighting (1/16 stencil) of residual from fine to coarse.
#   r_c[I, J] = (1/16) * [ 4*r_f[2I, 2J]
#                        + 2*(r_f[2I+1,2J] + r_f[2I-1,2J] + r_f[2I,2J+1] + r_f[2I,2J-1])
#                        + 1*(r_f[2I+1,2J+1] + r_f[2I-1,2J-1] + r_f[2I+1,2J-1] + r_f[2I-1,2J+1]) ]
# At the coarse boundary we fall back to injection (use the single fine value).
#
# Prolongation: bilinear interpolation from coarse to fine.
#   - Coincident nodes (2I, 2J) take the coarse value directly.
#   - Horizontal-midpoint nodes (2I, 2J+1) average two coarse neighbours horiz.
#   - Vertical-midpoint nodes (2I+1, 2J) average two coarse neighbours vert.
#   - Center nodes (2I+1, 2J+1) average four coarse neighbours.
# This is the standard MG operator pair (full-weighting + bilinear) which
# satisfies the variational P = R^T compatibility for nodal-centred grids.


def _coarse_dim(n_fine: int) -> int:
    """Coarse-grid dimension for a fine grid of dimension n_fine (gridline reg).
    Pattern: 5 -> 3, 7 -> 4, 9 -> 5, 17 -> 9, 33 -> 17, ... i.e. (n+1)//2."""
    return (n_fine + 1) // 2


def _restrict_full_weight(r_fine: np.ndarray) -> np.ndarray:
    """Full-weighting restriction of `r_fine` (ny_f, nx_f) -> (ny_c, nx_c).

    Assumes `r_fine` is the KEPT block (no ghost ring) on the fine grid.
    Returns the kept block on the coarse grid.

    Boundary handling: at coarse-grid edges the 9-point stencil would read
    past the fine boundary; we use injection there (r_c = r_f[2I,2J]) since
    the residual is zero at the data-constrained natural-BC boundary anyway.
    """
    ny_f, nx_f = r_fine.shape
    ny_c = _coarse_dim(ny_f)
    nx_c = _coarse_dim(nx_f)
    r_coarse = np.zeros((ny_c, nx_c), dtype=r_fine.dtype)

    # Interior coarse nodes that can use the full 9-point stencil
    # Coarse (I,J) corresponds to fine (2I,2J). Need 2I+/-1 and 2J+/-1 in bounds.
    # That requires 1 <= 2I <= ny_f-2, i.e. 1 <= I and 2I <= ny_f-2 (=> I <= (ny_f-2)//2).
    Ilo, Ihi = 1, (ny_f - 2) // 2 + 1   # exclusive
    Jlo, Jhi = 1, (nx_f - 2) // 2 + 1

    # Vectorised inner block
    II = np.arange(Ilo, Ihi)
    JJ = np.arange(Jlo, Jhi)
    fi = 2 * II[:, None]
    fj = 2 * JJ[None, :]
    r_coarse[Ilo:Ihi, Jlo:Jhi] = (1.0 / 16.0) * (
        4.0 * r_fine[fi, fj]
        + 2.0 * (r_fine[fi + 1, fj] + r_fine[fi - 1, fj]
                 + r_fine[fi, fj + 1] + r_fine[fi, fj - 1])
        + 1.0 * (r_fine[fi + 1, fj + 1] + r_fine[fi - 1, fj - 1]
                 + r_fine[fi + 1, fj - 1] + r_fine[fi - 1, fj + 1])
    )

    # Boundary coarse nodes: injection (no off-grid reads)
    for I in range(ny_c):
        for J in range(nx_c):
            if Ilo <= I < Ihi and Jlo <= J < Jhi:
                continue
            fi_ = min(2 * I, ny_f - 1)
            fj_ = min(2 * J, nx_f - 1)
            r_coarse[I, J] = r_fine[fi_, fj_]
    return r_coarse


def _prolong_bilinear(v_coarse: np.ndarray, ny_f: int, nx_f: int) -> np.ndarray:
    """Bilinear prolongation of `v_coarse` (ny_c, nx_c) -> (ny_f, nx_f).

    Assumes gridline registration with coarse (I,J) coincident with fine
    (2I, 2J).  When ny_f is odd (i.e. ny_c = (ny_f+1)//2), the mapping is
    exact for all fine nodes; for even ny_f the last row uses the last
    coarse row (zero-extension).
    """
    ny_c, nx_c = v_coarse.shape
    out = np.zeros((ny_f, nx_f), dtype=v_coarse.dtype)

    # Coincident fine nodes (2I, 2J)
    II = np.arange(ny_c)
    JJ = np.arange(nx_c)
    fi = 2 * II
    fj = 2 * JJ
    # clip to fine range
    fi_in = fi[fi < ny_f]
    fj_in = fj[fj < nx_f]
    nc_i = fi_in.size
    nc_j = fj_in.size
    out[np.ix_(fi_in, fj_in)] = v_coarse[:nc_i, :nc_j]

    # Horizontal midpoints (2I, 2J+1) — average two horiz neighbours
    if nc_j >= 2:
        fj_mid = 2 * np.arange(nc_j - 1) + 1
        fj_mid = fj_mid[fj_mid < nx_f]
        out[np.ix_(fi_in, fj_mid)] = 0.5 * (
            v_coarse[:nc_i, :fj_mid.size]
            + v_coarse[:nc_i, 1:fj_mid.size + 1]
        )

    # Vertical midpoints (2I+1, 2J) — average two vert neighbours
    if nc_i >= 2:
        fi_mid = 2 * np.arange(nc_i - 1) + 1
        fi_mid = fi_mid[fi_mid < ny_f]
        out[np.ix_(fi_mid, fj_in)] = 0.5 * (
            v_coarse[:fi_mid.size, :nc_j]
            + v_coarse[1:fi_mid.size + 1, :nc_j]
        )

    # Center midpoints (2I+1, 2J+1) — average four coarse neighbours
    if nc_i >= 2 and nc_j >= 2:
        fi_mid = 2 * np.arange(nc_i - 1) + 1
        fj_mid = 2 * np.arange(nc_j - 1) + 1
        fi_mid = fi_mid[fi_mid < ny_f]
        fj_mid = fj_mid[fj_mid < nx_f]
        out[np.ix_(fi_mid, fj_mid)] = 0.25 * (
            v_coarse[:fi_mid.size,     :fj_mid.size]
            + v_coarse[1:fi_mid.size + 1, :fj_mid.size]
            + v_coarse[:fi_mid.size,     1:fj_mid.size + 1]
            + v_coarse[1:fi_mid.size + 1, 1:fj_mid.size + 1]
        )

    # Trailing edge row/col (when ny_f or nx_f is even) — copy from last coarse
    if fi.max() < ny_f - 1:
        out[ny_f - 1, :] = out[ny_f - 2, :]
    if fj.max() < nx_f - 1:
        out[:, nx_f - 1] = out[:, nx_f - 2]
    return out


# ---------------------------------------------------------------------------
# Nested-iteration (Full Multigrid) driver — matches GMT surface's design.
# ---------------------------------------------------------------------------
# GMT surface (see src/surface.c) implements multigrid acceleration via
# PROGRESSIVE GRID REFINEMENT rather than classical V-cycles:
#
#   1. Pick a coarsening stride S = 32 (or as large as the grid allows).
#   2. Solve on every S'th node (a S-coarsened grid) to convergence via
#      cheap relaxation.
#   3. Halve S, prolongate the current solution to the new (denser) grid
#      as a starting guess, re-distribute data constraints, relax.
#   4. Repeat S = 16, 8, 4, 2, 1.
#
# This is mathematically equivalent to a "Full Multigrid" (FMG) cycle.
# Convergence is fast because:
#   - At each level, the previous level's interpolated solution is a
#     near-perfect initial guess for the smooth modes.
#   - The smoother only needs to kill the new high-frequency content
#     introduced by the refinement, which Jacobi does very efficiently.
#
# It also avoids the operator-scaling pitfall of classical V-cycles for
# the biharmonic: the coarse operator only ever acts on coarse data, so
# the h^4 stiffness scaling is built into both sides of the equation.
#
# Implementation:
#   - We build coarsened grids by selecting every (2**k)'th data node
#     from the input scatter.  This sets up consistent constraints
#     at every level.
#   - At each level we run Jacobi sweeps until max |du| < tol or until
#     a per-level iteration cap is hit.
#   - Prolongation to the next finer level is bilinear (using the
#     standard MG prolongation operator).
#
# Convergence comparison: where classical V-cycle on the biharmonic with
# h-independent stencils gets ~0.9 rate per cycle (slow), FMG runs each
# level for ~50-200 Jacobi sweeps once and never revisits.  Total cost
# is dominated by the finest level, which only needs O(50) sweeps to
# kill new high-frequency error rather than O(N) sweeps from a cold
# start.


def _smooth(u: np.ndarray, fixed: np.ndarray, rhs: np.ndarray,
            T: float, omega: float, n_sweeps: int, tol: float = 0.0) -> float:
    """Run up to `n_sweeps` damped-Jacobi sweeps on padded grids.

    If `tol > 0`, stop early when max |du| < tol.  Returns the last delta.
    """
    ny_full, nx_full = u.shape
    u_new = u.copy()
    last_delta = 0.0
    for s in range(n_sweeps):
        _apply_bcs(u)
        u_new[:] = u
        last_delta = float(_jacobi_sweep(u, u_new, fixed, rhs,
                                          float(T), float(omega),
                                          ny_full, nx_full))
        u[:] = u_new
        if tol > 0.0 and last_delta < tol:
            break
    return last_delta


def _unpad2(padded: np.ndarray, ny: int, nx: int) -> np.ndarray:
    return padded[2:2 + ny, 2:2 + nx]


def _max_level_for(ny: int, nx: int) -> int:
    """Number of additional coarsenings allowed below the finest level."""
    n = min(ny, nx)
    lvl = 0
    while _coarse_dim(n) >= _MG_MIN_DIM:
        n = _coarse_dim(n)
        lvl += 1
    return lvl


def _fmg_solve(x: np.ndarray, y: np.ndarray, z: np.ndarray,
               xmin: float, ymin: float, dx: float, dy: float,
               nx: int, ny: int,
               T: float, omega: float,
               n_levels: int,
               sweeps_per_level: int,
               tol: float,
               verbose: bool) -> np.ndarray:
    """Full-multigrid solve: start at coarsest grid (every 2^(n_levels-1)
    node), relax to convergence, prolong to next finer grid, relax again,
    repeat down to the finest (full-resolution) grid.

    Returns the padded grid at the finest level (shape (ny+4, nx+4)),
    same convention as the rest of the module.
    """
    # Levels: 0 = coarsest, n_levels-1 = finest
    # At level k (counting from finest=0), grid step is 2^k in node units.
    # We iterate from coarsest down to finest.
    # Compute level (k counting from finest, 0 = finest).
    # For convenience use stride s = 2^k.

    # Build per-level fine-grid index ranges.  At stride s we keep nodes
    # i = 0, s, 2s, ... that fall within [0, ny-1] x [0, nx-1].  This
    # convention preserves gridline registration at every level.
    u_pad_prev = None    # padded grid at the previous (coarser) level
    nx_prev = ny_prev = 0
    s_max = 1 << (n_levels - 1)   # coarsest stride

    for kk in range(n_levels - 1, -1, -1):
        s = 1 << kk
        # Coarse-grid axis sizes (gridline registration: include endpoints
        # where possible).  We require at least _MG_MIN_DIM nodes per axis;
        # if the requested coarsest is too small, the caller has already
        # capped n_levels via _max_level_for.
        nx_k = (nx - 1) // s + 1
        ny_k = (ny - 1) // s + 1
        # Effective spacings at this level (in physical units, equal to
        # s*dx and s*dy).  Not used directly because our stencil is
        # h-independent — the level-k discrete problem is solved with
        # the same stencil; the relaxation at each level converges to
        # the level-k discrete biharmonic-+ tension fixed point.
        u_pad_k, fixed_k = _init_grid_from_scatter(
            x, y, z, xmin, ymin, dx * s, dy * s, nx_k, ny_k)
        rhs_k = np.zeros_like(u_pad_k)

        if u_pad_prev is not None:
            # Prolong previous (coarser) solution to this level as initial
            # guess.  Strip the ghost ring, bilinear-prolong, then write
            # the result into the kept domain of u_pad_k WITHOUT
            # overwriting nodes that are pinned by snapped data.
            u_prev_inner = _unpad2(u_pad_prev, ny_prev, nx_prev)
            u_guess = _prolong_bilinear(u_prev_inner, ny_k, nx_k)
            # Where fixed, keep the snapped data value; elsewhere, use
            # the prolonged guess.
            inner_view = u_pad_k[2:2 + ny_k, 2:2 + nx_k]
            fixed_inner = fixed_k[2:2 + ny_k, 2:2 + nx_k]
            inner_view[~fixed_inner] = u_guess[~fixed_inner]

        # Relax at this level.  Use a tighter tolerance at coarse levels
        # (they are cheap) and the requested tol at the finest level.
        level_tol = tol if kk == 0 else max(tol, tol * (4 ** kk))
        # Iteration cap scales with the level: coarse grids converge in
        # ~ny_k iterations of damped Jacobi (cost ~ ny_k^3 work / level).
        # Cap finest level at sweeps_per_level; allow more on coarse since
        # cost there is negligible relative to fine.
        cap = max(sweeps_per_level, 4 * ny_k)
        delta = _smooth(u_pad_k, fixed_k, rhs_k, T, omega, cap, tol=level_tol)
        if verbose:
            print(f"  FMG level k={kk} stride={s} grid={ny_k}x{nx_k}  "
                  f"final max|du|={delta:.3e}  (cap={cap}, tol={level_tol:.1e})")

        u_pad_prev = u_pad_k
        ny_prev = ny_k
        nx_prev = nx_k

    return u_pad_prev


# ---------------------------------------------------------------------------
# Initial guess — bilinear from nearest-known data
# ---------------------------------------------------------------------------

def _init_grid_from_scatter(x: np.ndarray, y: np.ndarray, z: np.ndarray,
                            xmin: float, ymin: float, dx: float, dy: float,
                            nx: int, ny: int
                            ) -> Tuple[np.ndarray, np.ndarray]:
    """Snap scatter to nearest grid node on a PADDED grid of shape
    (ny+4, nx+4); pin those nodes; init the rest with the data mean.
    The kept domain is u[2:ny+2, 2:nx+2].  Ghost rings are computed by
    `_apply_bcs` each iteration; they are also initialized here so the
    first JIT sweep does not see uninitialized memory.
    """
    ny_full = ny + 4
    nx_full = nx + 4

    z_mean = float(np.mean(z))
    u = np.full((ny_full, nx_full), z_mean, dtype=np.float64)
    fixed = np.zeros((ny_full, nx_full), dtype=np.bool_)

    # Snap scatter to nearest kept-domain node, offset by +2 for ghost ring
    i_idx = np.rint((y - ymin) / dy).astype(np.int64) + 2
    j_idx = np.rint((x - xmin) / dx).astype(np.int64) + 2
    inside = ((i_idx >= 2) & (i_idx < ny + 2)
              & (j_idx >= 2) & (j_idx < nx + 2))
    i_idx = i_idx[inside]
    j_idx = j_idx[inside]
    z_in = z[inside]

    # Average duplicates on the same node (crude blockmean).
    accum = np.zeros((ny_full, nx_full), dtype=np.float64)
    count = np.zeros((ny_full, nx_full), dtype=np.int64)
    for k in range(z_in.size):
        accum[i_idx[k], j_idx[k]] += z_in[k]
        count[i_idx[k], j_idx[k]] += 1
    has = count > 0
    u[has] = accum[has] / count[has]
    fixed[has] = True

    return u, fixed


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def gmt_surface_py(x: np.ndarray, y: np.ndarray, z: np.ndarray,
                   region: Tuple[float, float, float, float],
                   inc: Tuple[float, float],
                   tension: float = 0.5,
                   max_iter: int = 1000,
                   tol: float = 1e-4,
                   omega: float = 0.7,
                   verbose: bool = False,
                   use_multigrid: bool = True,
                   mg_max_level: Optional[int] = None,
                   mg_nu_coarse: int = 50,
                   ) -> np.ndarray:
    """Continuous-curvature spline matching `gmt surface` (Smith & Wessel 1990).

    Parameters
    ----------
    x, y, z : ndarray
        Scattered point coords and values (1-D, length N).
    region : (x_min, x_max, y_min, y_max)
        Grid extent.
    inc : (x_inc, y_inc)
        Grid spacing.  Currently requires x_inc == y_inc (square cells).
    tension : float, default 0.5
        Surface tension T in [0, 1].  0 = pure spline (biharmonic),
        1 = pure interp (harmonic).  GMT default is 0.
    max_iter : int, default 1000
        Max relaxation iterations (used only when ``use_multigrid=False``).
    tol : float, default 1e-4
        Convergence threshold on max |delta u| per sweep.
    omega : float, default 0.7
        Damping factor for the (under-)relaxed Jacobi update,
        ``u_new = (1 - omega) * u_old + omega * stencil_value``.
        Plain Jacobi (omega=1) is unstable for the discrete biharmonic
        operator; values in (0, 0.8] are safe.  Higher = faster
        convergence but risks divergence at low tension.  Default 0.7 is
        safe for grids up to ~501x501; for 1001x1001 use omega <= 0.65.
    verbose : bool, default False
        Print per-level FMG progress.
    use_multigrid : bool, default True
        If True, accelerate with Full Multigrid (FMG) nested iteration —
        solve on a coarse grid first, prolongate, refine.  Mira #21.
        Set False to fall back to plain single-level damped Jacobi
        (slow on large grids).
    mg_max_level : int or None
        Number of additional coarsenings below the finest level.
        ``None`` picks the deepest level that keeps coarsest >= 9x9.
    mg_nu_coarse : int, default 50
        Lower bound on the per-level sweep cap.  At each FMG level the
        cap is ``max(mg_nu_coarse, 4 * ny_level)``; relaxation stops
        early when max |du| drops below the per-level tolerance.

    Returns
    -------
    grid : ndarray, shape (ny, nx)
        Interpolated surface.  Row 0 is the southernmost row (y = y_min).
    """
    x = np.ascontiguousarray(x, dtype=np.float64)
    y = np.ascontiguousarray(y, dtype=np.float64)
    z = np.ascontiguousarray(z, dtype=np.float64)
    if x.shape != y.shape or x.shape != z.shape:
        raise ValueError("x, y, z must have the same shape")
    if x.ndim != 1:
        raise ValueError("x, y, z must be 1-D")

    xmin, xmax, ymin, ymax = region
    dx, dy = inc
    if abs(dx - dy) > 1e-12 * max(abs(dx), abs(dy)):
        raise NotImplementedError(
            f"gmt_surface_py prototype requires square cells "
            f"(dx={dx}, dy={dy}).  Anisotropic cells: TODO.")
    if not (0.0 <= tension <= 1.0):
        raise ValueError(f"tension must be in [0,1], got {tension}")

    nx = int(round((xmax - xmin) / dx)) + 1
    ny = int(round((ymax - ymin) / dy)) + 1
    if nx < 5 or ny < 5:
        raise ValueError(f"grid too small ({ny}x{nx}); need >=5 in each dim "
                         f"for the 12-point stencil")

    if use_multigrid and ny >= _MG_MIN_DIM and nx >= _MG_MIN_DIM:
        # Full multigrid (FMG) / nested iteration — matches GMT surface.
        # n_levels counts the finest level too, so n_levels=1 => single
        # grid (no multigrid benefit).
        n_levels = ((_max_level_for(ny, nx) + 1) if mg_max_level is None
                    else int(mg_max_level) + 1)
        n_levels = max(1, n_levels)
        if verbose:
            print(f"[gmt_surface_py] grid {ny}x{nx}, T={tension}, "
                  f"numba={_HAVE_NUMBA}, FMG n_levels={n_levels} "
                  f"(coarsest ~ {ny // (1 << (n_levels - 1))}x"
                  f"{nx // (1 << (n_levels - 1))})")
        u = _fmg_solve(x, y, z, xmin, ymin, dx, dy, nx, ny,
                       float(tension), float(omega),
                       n_levels, sweeps_per_level=mg_nu_coarse,
                       tol=tol, verbose=verbose)
        fixed = None  # not needed below; we already converged
    else:
        # Single-level plain damped Jacobi (original prototype path).
        u, fixed = _init_grid_from_scatter(x, y, z, xmin, ymin, dx, dy, nx, ny)
        ny_full, nx_full = u.shape
        rhs = np.zeros_like(u)
        if verbose:
            print(f"[gmt_surface_py] grid {ny}x{nx} (padded {ny_full}x{nx_full}), "
                  f"T={tension}, {int(fixed.sum())} fixed nodes, "
                  f"numba={_HAVE_NUMBA}, multigrid=False")
        u_new = u.copy()
        last_delta = np.inf
        for it in range(max_iter):
            _apply_bcs(u)
            u_new[:] = u
            delta = _jacobi_sweep(u, u_new, fixed, rhs, float(tension), float(omega),
                                  ny_full, nx_full)
            u, u_new = u_new, u
            last_delta = float(delta)
            if verbose and (it % 100 == 0):
                print(f"  iter {it:5d}  max |du| = {last_delta:.3e}")
            if last_delta < tol:
                if verbose:
                    print(f"[gmt_surface_py] converged at iter {it}, "
                          f"max |du| = {last_delta:.3e}")
                break
        else:
            if verbose:
                print(f"[gmt_surface_py] max_iter={max_iter} reached, "
                      f"max |du| = {last_delta:.3e}")

    _apply_bcs(u)
    # Return only the kept (ny, nx) block, stripping the 2-wide ghost ring.
    return np.ascontiguousarray(u[2:2 + ny, 2:2 + nx])


# ---------------------------------------------------------------------------
# Diagnostic helpers (exposed for tests; not for production use)
# ---------------------------------------------------------------------------

def _diag_info() -> dict:
    """Return current runtime configuration (for tests / debug)."""
    return {
        "have_numba": _HAVE_NUMBA,
        "num_threads": int(os.environ.get("NUMBA_NUM_THREADS", "0")) or None,
        "env_disabled": os.environ.get("GMT_SURFACE_PY_NUMBA", "1") == "0",
    }


if __name__ == "__main__":
    # Self-test: smooth Gaussian on 100 random points.
    rng = np.random.default_rng(42)
    N = 200
    x = rng.uniform(0, 10, N)
    y = rng.uniform(0, 10, N)
    z = np.exp(-((x - 5.0) ** 2 + (y - 5.0) ** 2) / 4.0)
    grid = gmt_surface_py(x, y, z,
                          region=(0.0, 10.0, 0.0, 10.0),
                          inc=(0.1, 0.1),
                          tension=0.25,
                          omega=0.5,
                          max_iter=5000,
                          tol=1e-5,
                          verbose=True)
    # Build the analytic surface on the same grid
    nx = ny = 101
    gx, gy = np.meshgrid(np.linspace(0, 10, nx), np.linspace(0, 10, ny))
    z_true = np.exp(-((gx - 5.0) ** 2 + (gy - 5.0) ** 2) / 4.0)
    rms = float(np.sqrt(np.mean((grid - z_true) ** 2)))
    print(f"Self-test RMS vs analytic: {rms:.4e}")
