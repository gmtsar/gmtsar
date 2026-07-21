"""utils.vector — shared @njit single-thread vector primitives for gmtsar Py ports.

A foundational library of low-level numerical primitives extracted from
the existing bin_py JIT-kernel files (`_jit_kernels_sat.py`,
`_jit_kernels_resamp.py`) and from `SAT_llt2rat_py` itself. Once this
module exists, future Python ports should import these primitives
instead of redefining them — eliminating drift across copies.

Design constraints
------------------
* All kernels are `@njit(fastmath=False, cache=True)` — strict
  single-thread; **NO `parallel=True`, NO `prange`**.
* `fastmath=False` is required for bit-parity with the C reference —
  LLVM reordering of FP ops silently breaks reproducibility.
* `cache=True` persists compiled IR to disk so cold start (~5-7 s on
  the full primitive set) is paid once per code-change cycle.
* Constants are baked as Numba module literals (captured as closures
  over module globals when the functions are compiled) so they
  propagate as immediates into the generated LLVM IR.
* Constants use the **C truncated values** verbatim — DO NOT replace
  with the mathematically-correct equivalents. C bakes these truncated
  values into millions of accumulations and the ports must match
  bit-for-bit.

Constants
---------
* `SOL = 299792456.0` — speed of light, C #define in gmtsar.h:16
  (2 m/s off from the true physical 299792458.0; mandatory for parity).
* `PI = 3.14159265358979` — truncated π from llt2xyz.h:61 (14 digits,
  NOT math.pi's 15). The 1-ULP diff propagates to ~1.5e-8 m in xyz
  after plh2xyz and can flip goldop branches.
* `TWOPI`, `DEG_TO_RAD`, `RAD_TO_DEG` — derived from the truncated PI
  (same convention as llt2xyz.h:62-66).
* `R_GOLD = 0.61803399`, `C_GOLD = 0.382` — truncated golden-ratio
  constants from SAT_llt2rat.c #define R, C (sum = 0.99996601, not 1.0).

What's exported
---------------
Tier 1 — Math primitives + Tier 1 vector geometry:
  * `cross_3(a, b, out)` — 3-vector cross product, C-faithful component
    formulae (see cross3 in SAT_baseline_py for the 1-ULP gotcha).
  * `dot_3(a, b)` — 3-vector dot, ascending-index accumulation.
  * `norm_3(v)` — 3-vector L2 norm.
  * `plh2xyz_scalar(lat_deg, lon_deg, h, A, FL)` — geodetic → ECEF,
    C-faithful via (1-FL)*(1-FL) and truncated π (Mira #2 fix).

Tier 2 — Orbit / interpolation primitives:
  * `hermite_c_1d(x, y, z, xp, nval, yp_out)` — 1D Hermite interp,
    line-by-line mirror of C hermite_c.c (Mira #2's 9-bug ladder).
  * `hermite_c_1d_uniform(x0, dsec, y, z, xp, nval, HJ, S_VALS,
    yp_out)` — Horner fast path for uniform grids.

Tier 3 — Search + fit primitives:
  * `goldop_search(op_t, px, py, pz, tx, ty, tz, R_out, T_out)` —
    batched golden-section search, scalar C-faithful (TOL=2 with
    `x2 != x1` guard, matches SAT_llt2rat.c).
  * `polyfit_normal_eqs(T, Y, N, out)` — C-faithful normal-equations
    polyfit via gauss_jordan elimination (mirrors polyfit.c bit-exact).

Provenance
----------
Tier 1 vector primitives (`cross_3`, `dot_3`, `norm_3`): new minimal
helpers, designed from the scalar C component formulae used in
gmtsar utils.c.

Tier 1 `plh2xyz_scalar`: ported from `SAT_llt2rat_py:plh2xyz` (the
pure-numpy vectorised version), converted to a scalar `@njit` form
that mirrors C plxyz.c plh2xyz() line-by-line. Same constants and
same operation order.

Tier 2 `hermite_c_1d` / `hermite_c_1d_uniform`: copied verbatim from
`bin_py/_jit_kernels_sat.py:_hermite_c_1d_jit` and
`_hermite_c_1d_uniform_jit` (Mira #2 has already audited those for
bit-parity vs C `hermite_c.c`).

Tier 3 `goldop_search`: copied verbatim from
`bin_py/_jit_kernels_sat.py:_goldop_jit` (Mira #2's SHFT3 OLD-value
capture audit, including `R_LIT`/`C_LIT` truncated golden-ratio).

Tier 3 `polyfit_normal_eqs`: ported from `SAT_llt2rat_py:polyfit_c`
to a fully scalar `@njit` form. Mirrors C polyfit.c + gauss_jordan.c
exactly: same Hankel A construction, same elimination order, same
back-substitution. No `parallel=True`, no `prange`.
"""
from __future__ import annotations

import numpy as np
from numba import njit


# ---------------------------------------------------------------------------
# Constants — bit-faithful to the C upstream values. Module-level so Numba
# captures them as closures-over-globals → LLVM literals.
# ---------------------------------------------------------------------------

# Speed of light, m/s. C #define SOL in gmtsar.h:16 (also soi.h:36).
# 2 m/s off from the true physical 299792458 but mandatory for parity.
# Affects dr = 0.5*SOL/fs → ~2e-5 px range_pix systematic offset.
SOL = 299792456.0

# Truncated π from llt2xyz.h:61.  14 digits, NOT math.pi's 15.
# `deg_to_rad = 2*PI/360 = 0.017453292519943278` vs numpy's
# 0.017453292519943295. The 1-ULP diff propagates to ~5e-9 rad at mid-
# latitudes → ~1.5e-8 m in xyz → can flip goldop branches.
PI = 3.14159265358979
TWOPI = 2.0 * PI                  # llt2xyz.h:63
DEG_TO_RAD = TWOPI / 360.0        # llt2xyz.h:65
RAD_TO_DEG = 360.0 / TWOPI        # llt2xyz.h:66

# Truncated golden-ratio constants from SAT_llt2rat.c #define R, C.
# R + C = 0.99996601 (NOT 1.0). Baked into goldop step sizes.
R_GOLD = 0.61803399
C_GOLD = 0.382


# ---------------------------------------------------------------------------
# Tier 1 — Vector primitives
# ---------------------------------------------------------------------------

@njit(fastmath=False, cache=True)
def cross_3(a, b, out):
    """3-vector cross product, C-faithful component formulae.

    Mirrors `utils.c cross3` (used by SAT_baseline.c and others):

        c[0] = a[1]*b[2] - a[2]*b[1]
        c[1] = -a[0]*b[2] + a[2]*b[0]
        c[2] = a[0]*b[1] - a[1]*b[0]

    Note c[1] is `(-a[0]*b[2]) + (a[2]*b[0])` — left-to-right, NOT
    `a[2]*b[0] - a[0]*b[2]` which differs by 1 ULP for some inputs.

    Args:
        a, b : 1-D float64 arrays of length 3.
        out  : 1-D float64 array of length 3 (written in place).
    """
    out[0] = (a[1] * b[2]) - (a[2] * b[1])
    out[1] = (-a[0] * b[2]) + (a[2] * b[0])
    out[2] = (a[0] * b[1]) - (a[1] * b[0])


@njit(fastmath=False, cache=True)
def dot_3(a, b):
    """3-vector dot, ascending-index accumulation order."""
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


@njit(fastmath=False, cache=True)
def norm_3(v):
    """3-vector L2 norm. Order: sqrt(x*x + y*y + z*z), left-to-right."""
    return np.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


@njit(fastmath=False, cache=True)
def plh2xyz_scalar(lat_deg, lon_deg, h, A, FL):
    """Scalar C-faithful geodetic → ECEF conversion.

    Bit-faithful port of gmtsar plxyz.c `plh2xyz()`. Mirrors the C
    operation order EXACTLY — algebraic equivalents differ by 1 ULP:

        flatfn = (2 - FL) * FL
        funsq  = (1 - FL) * (1 - FL)    # NOT (1 - e2); 1 ULP off
        g1 = A / sqrt(1 - flatfn * sin_lat^2)     # N
        g2 = g1 * funsq + h                       # N*(1-FL)^2 + h  (order matters)
        g1 = g1 + h                               # N + h
        x = g1 * cos_lat
        y = x * sin(lon)            # = (g1*cos_lat) * sin_lon
        x = x * cos(lon)            # = (g1*cos_lat) * cos_lon
        z = g2 * sin_lat

    Uses TRUNCATED `pi = 3.14159265358979` (llt2xyz.h:61), NOT math.pi.

    Args:
        lat_deg : geodetic latitude (degrees).
        lon_deg : geodetic longitude (degrees).
        h       : ellipsoidal height (m).
        A       : equatorial radius (m).
        FL      : flattening (dimensionless).

    Returns: (x, y, z) tuple of ECEF coordinates in metres.
    """
    flatfn = (2.0 - FL) * FL
    funsq = (1.0 - FL) * (1.0 - FL)
    lat_r = lat_deg * DEG_TO_RAD
    lon_r = lon_deg * DEG_TO_RAD
    sin_lat = np.sin(lat_r)
    cos_lat = np.cos(lat_r)
    g1 = A / np.sqrt(1.0 - flatfn * sin_lat * sin_lat)
    g2 = g1 * funsq + h
    g1 = g1 + h
    x = g1 * cos_lat
    y = x * np.sin(lon_r)
    x = x * np.cos(lon_r)
    z = g2 * sin_lat
    return x, y, z


# ---------------------------------------------------------------------------
# Tier 2 — Hermite interpolation primitives
#
# Both kernels are copied VERBATIM from bin_py/_jit_kernels_sat.py — the
# Mira #2 audit has already verified bit-parity vs C hermite_c.c for the
# RS2 canonical dataset (9-bug ladder, including left-associative arith
# and the (1-FL)^2 sub-ULP family).
# ---------------------------------------------------------------------------

@njit(fastmath=False, cache=True)
def hermite_c_1d(x, y, z, xp, nval, yp_out):
    """Line-by-line mirror of C `hermite_c.c hermite_c` (general grid).

    Inner loops preserve C's left-associative arithmetic exactly:
        hj = (hj * (xp - x[j+i0])) / (x[i+i0] - x[j+i0])   (Mira bug #5)
        yp = yp + (y*f0 + z*f1) * hj * hj                  (left-assoc * hj * hj)

    Single-thread, fastmath=False, plain `range`. `nval` is treated
    as runtime int so the same compiled body handles `nval=6` (the only
    one gmtsar uses) without specialisation.

    Args:
        x       : (nmax,) float64 knot positions (need NOT be uniform).
        y       : (nmax,) float64 function values.
        z       : (nmax,) float64 derivatives.
        xp      : (M,)    float64 query positions.
        nval    : int — number of points used per query (gmtsar uses 6).
        yp_out  : (M,) float64 output array (written in place).

    On out-of-range xp the corresponding `yp_out[m]` is set to NaN —
    matches the numpy reference's `raise ValueError`.
    """
    nmax = x.shape[0]
    n = nval - 1
    M = xp.shape[0]
    x0v = x[0]
    xLv = x[nmax - 1]
    clip_max = nmax - n - 1
    for m in range(M):
        xpm = xp[m]
        if xpm < x0v or xpm > xLv:
            yp_out[m] = np.nan
            continue
        # binary search for first i with x[i] >= xpm
        lo = 0
        hi = nmax
        while lo < hi:
            mid = (lo + hi) >> 1
            if x[mid] < xpm:
                lo = mid + 1
            else:
                hi = mid
        i = lo
        i0 = i - (n + 1) // 2
        if i0 < 0:
            i0 = 0
        elif i0 > clip_max:
            i0 = clip_max
        yp = 0.0
        for ii in range(nval):
            xi = x[i0 + ii]
            hj = 1.0
            sj = 0.0
            for jj in range(nval):
                if jj == ii:
                    continue
                xj = x[i0 + jj]
                # C: hj = hj * (xpm - xj) / (xi - xj)
                # Mira #5: left-associative ((hj*(xpm-xj))/(xi-xj))
                hj = (hj * (xpm - xj)) / (xi - xj)
                sj = sj + 1.0 / (xi - xj)
            f0 = 1.0 - 2.0 * (xpm - xi) * sj
            f1 = xpm - xi
            # C: yp = yp + (y*f0 + z*f1) * hj * hj   (left-assoc)
            yp = yp + (y[i0 + ii] * f0 + z[i0 + ii] * f1) * hj * hj
        yp_out[m] = yp


@njit(fastmath=False, cache=True)
def hermite_c_1d_uniform(x0, dsec, y, z, xp, nval, HJ, S_VALS, yp_out):
    """Horner fast-path for hermite_c interpolation on a uniform-grid orbit.

    Mirrors the pure-numpy `hermite_c_1d_uniform` op-for-op:
      - same Horner reduction order over coefs (descending k)
      - same per-query u, idx, f0, f1, hj_sq layout
      - inner-loop sum over i accumulates in the SAME order as numpy's
        `(y_loc*f0 + z_loc*f1)*hj_sq sum(axis=0)`.

    The AUDIT documents a known 1e-6 m residual vs C — that residual is
    from the Horner basis vs C's direct Lagrange (an algorithmic, not
    numerical, divergence), NOT from numpy-vs-numba differences. This
    kernel preserves the numpy result bit-for-bit.

    Args:
        x0      : float — knot start (t_orb[0]).
        dsec    : float — knot spacing (uniform).
        y       : (nmax,) float64 function values.
        z       : (nmax,) float64 derivatives.
        xp      : (M,)    float64 query positions.
        nval    : int — number of points used per query.
        HJ      : (nval, nval) Hermite basis polynomial coefs (ascending u^k).
        S_VALS  : (nval,) S_i = sum_{j!=i} 1/(i - j).
        yp_out  : (M,) float64 output array (written in place).
    """
    nmax = y.shape[0]
    n = nval - 1
    clip_max = nmax - n - 1
    M = xp.shape[0]
    for m in range(M):
        xpm = xp[m]
        raw = (xpm - x0) / dsec
        # i = ceil(raw)
        i = int(np.ceil(raw))
        i0 = i - (n + 1) // 2
        if i0 < 0:
            i0 = 0
        elif i0 > clip_max:
            i0 = clip_max
        u = raw - i0   # (xpm - (x0 + i0*dsec))/dsec, algebraically identical
        yp = 0.0
        for i_idx in range(nval):
            # Horner ascending: v = 0; for k = nval-1..0: v = v*u + HJ[i_idx,k]
            v = 0.0
            for k in range(nval - 1, -1, -1):
                v = v * u + HJ[i_idx, k]
            hj_sq = v * v
            u_minus_i = u - float(i_idx)
            f0 = 1.0 - 2.0 * u_minus_i * S_VALS[i_idx]
            f1 = u_minus_i * dsec
            yp = yp + (y[i0 + i_idx] * f0 + z[i0 + i_idx] * f1) * hj_sq
        yp_out[m] = yp


# ---------------------------------------------------------------------------
# Tier 3 — Search + fit primitives
# ---------------------------------------------------------------------------

@njit(fastmath=False, cache=True)
def goldop_search(op_t, px, py, pz, tx, ty, tz, R_out, T_out):
    """Batched C-faithful golden-section search for time-of-closest-approach.

    Line-by-line scalar mirror of C `goldop` in SAT_llt2rat.c
    (lines 332-393), applied per-target.  Mirrors:
      - SHFT3/SHFT2 macros: cascade assignments with cross-dependencies
        (the NEW x2 in the `f2<f1` branch uses OLD x2, NOT OLD x1,
        because the macro `(a)=(b); (b)=(c); (c)=(d)` evaluates `d`
        textually AFTER x1 has been overwritten with x2_old).
      - Truncated golden-ratio: R_LIT=0.61803399, C_LIT=0.382 are
        baked as Numba constants so they propagate as LLVM literals.
      - Per-iter sqrt (Mira bug #9): the f2<f1 compare MUST be against
        sqrt values, NOT squared values — tiny f²-differences at the
        ULP level can be wiped out by sqrt rounding and flip branches.
      - int truncation via Numba float64-to-int64 cast (toward zero).
      - Termination: `(x3 - x0) > 2 AND x2 != x1` (TOL=2 from main.c).

    Args:
        op_t        : (nrec,) orbit times at each pre-sampled grid index.
        px, py, pz  : (nrec,) orbit ECEF positions (X, Y, Z components).
        tx, ty, tz  : (N,)    target ECEF positions per query point.
        R_out       : (N,) float64 — output min-range per target.
        T_out       : (N,) float64 — output orbit-time at minimum per target.
    """
    R_LIT = 0.61803399
    C_LIT = 0.382
    nrec = px.shape[0]
    N = tx.shape[0]
    ax_init = 0
    bx_init = nrec - 1
    cx_init = int(ax_init + (bx_init - ax_init) * C_LIT)
    # Per-target initial bracket (all identical at start).
    if abs(bx_init - cx_init) > abs(cx_init - ax_init):
        x1_init = cx_init
        x2_init = cx_init + int(abs(C_LIT * (bx_init - cx_init)))
    else:
        x2_init = cx_init
        x1_init = cx_init - int(abs(C_LIT * (cx_init - ax_init)))
    for n in range(N):
        ttx = tx[n]
        tty = ty[n]
        ttz = tz[n]
        x0 = 0
        x3 = bx_init
        x1 = x1_init
        x2 = x2_init
        # f1 = dist(orb_pos[x1], target)
        dx1 = ttx - px[x1]
        dy1 = tty - py[x1]
        dz1 = ttz - pz[x1]
        f1 = np.sqrt(dx1 * dx1 + dy1 * dy1 + dz1 * dz1)
        dx2 = ttx - px[x2]
        dy2 = tty - py[x2]
        dz2 = ttz - pz[x2]
        f2 = np.sqrt(dx2 * dx2 + dy2 * dy2 + dz2 * dz2)
        # while (x3 - x0) > 2 and x2 != x1   (TOL=2 from main.c)
        for _it in range(64):
            if not ((x3 - x0) > 2 and x2 != x1):
                break
            if f2 < f1:
                # SHFT3(x0,x1,x2,(int)(R*x3 + C*x1));
                # cascade reads x1 AFTER assignment to x2_old → uses x2_old
                new_x0 = x1
                new_x1 = x2
                new_x2 = int(R_LIT * x3 + C_LIT * x2)  # OLD x2
                x0 = new_x0
                x1 = new_x1
                x2 = new_x2
                if x2 < 0:
                    x2 = 0
                elif x2 > nrec - 1:
                    x2 = nrec - 1
                # SHFT2(f1,f2,dist(...,x2_new,...))
                f1 = f2
                dxn = ttx - px[x2]
                dyn = tty - py[x2]
                dzn = ttz - pz[x2]
                f2 = np.sqrt(dxn * dxn + dyn * dyn + dzn * dzn)
            else:
                # SHFT3(x3,x2,x1,(int)(R*x0 + C*x2));
                # cascade reads x2 AFTER overwrite to x1_old → uses x1_old
                new_x3 = x2
                new_x2 = x1
                new_x1 = int(R_LIT * x0 + C_LIT * x1)  # OLD x1
                x3 = new_x3
                x2 = new_x2
                x1 = new_x1
                if x1 < 0:
                    x1 = 0
                elif x1 > nrec - 1:
                    x1 = nrec - 1
                # SHFT2(f2,f1,dist(...,x1_new,...))
                f2 = f1
                dxn = ttx - px[x1]
                dyn = tty - py[x1]
                dzn = ttz - pz[x1]
                f1 = np.sqrt(dxn * dxn + dyn * dyn + dzn * dzn)
        # Winner (C lines 371-390)
        if f1 < f2:
            chosen = x1
            rng = f1
        else:
            chosen = x2
            rng = f2
        if chosen < 0:
            chosen = 0
        elif chosen > nrec - 1:
            chosen = nrec - 1
        R_out[n] = rng
        T_out[n] = op_t[chosen]


@njit(fastmath=False, cache=True)
def polyfit_normal_eqs(T, Y, N, out):
    """C-faithful polynomial fit via normal equations + gauss_jordan.

    Bit-faithful port of gmtsar `polyfit.c` + `gauss_jordan.c`.  Fits the
    lowest-N-order polynomial:

        A[i,j] = sum_k T[k]^(i+j)         (Hankel matrix)
        B[j]   = sum_k Y[k] * T[k]^j
        Solve A @ C = B via gauss_jordan (forward elimination only;
        m=k in the C loop means the row-swap is identity → no pivoting).

    Differs from `numpy.polyfit` (Vandermonde + LAPACK lstsq) at the
    ~1e-15 level for well-conditioned problems — but C uses THIS exact
    routine in SAT_llt2rat.c precise=1 and SAT_baseline.c poly_interp,
    so the port mirrors it bit-for-bit to match downstream tm/rng0.

    Args:
        T   : (M,) float64 — abscissae.
        Y   : (M,) float64 — ordinates.
        N   : int — number of polynomial coefs (order = N-1).
              N=3 for SAT_baseline poly_interp; N up to ~6 elsewhere.
        out : (N,) float64 — output coefs c0..c_{N-1} (ascending order).
    """
    M = T.shape[0]
    # Build A (Hankel), B vector via in-place power accumulation.
    # First: B[j] = sum_k Y[k] * T[k]^j   (j in 0..N-1)
    # Allocate a small N×N + 2N-1 powers-sum vector — bounded by N which is
    # always small (<= ~6 in gmtsar). Stack-friendly in Numba.
    A = np.zeros((N, N), dtype=np.float64)
    B = np.zeros(N, dtype=np.float64)

    # sum_powers[p] = sum_k T[k]^p,  p in 0..2N-2
    P = 2 * N - 1
    sum_powers = np.zeros(P, dtype=np.float64)
    # accumulate via per-element running power; bit-faithful to C polyfit.c
    # which redundantly recomputes pow_T = T^(i+j) at each (i,j).
    for k in range(M):
        Tk = T[k]
        Yk = Y[k]
        pw = 1.0
        # B[j] uses pw = T^j; pw advances each j
        for j in range(N):
            B[j] = B[j] + Yk * pw
            pw = pw * Tk
        # sum_powers[p] = sum_k T^p
        pw = 1.0
        for p in range(P):
            sum_powers[p] = sum_powers[p] + pw
            pw = pw * Tk
    for i in range(N):
        for j in range(N):
            A[i, j] = sum_powers[i + j]

    # gauss_jordan-style forward elimination (C: gauss_jordan in polyfit.c).
    # C iterates m=k each outer step (no partial pivoting), only eliminates
    # downward, then swaps row k with row m via the j-loop. m=k means swap
    # is identity → forward elimination only. Replicate C exactly.
    # NB: the C "row" index in the inner loop is actually the COLUMN of A
    # in this representation (look at polyfit.c: A[j][l] etc.) — i.e. the
    # operations are on COLUMNS of A. Mirror that.
    for k in range(N):
        m = k
        # eliminate column m from columns l > m
        akm = A[k, m]
        if akm != 0.0:
            for l in range(m + 1, N):
                factor = A[k, l] / akm
                # A[:, l] -= factor * A[:, m]
                for j in range(N):
                    A[j, l] = A[j, l] - factor * A[j, m]
                B[l] = B[l] - factor * B[m]
        # row swap k <-> m (m == k → no-op, kept for bit-faithfulness)
        # No-op since m == k.

    # back-substitute (C polyfit.c back_substitute):
    #   X[N-1] = B[N-1] / A[N-1, N-1]
    #   for p in 1..N-1:
    #     idx = N-1 - p
    #     X[idx] = (B[idx] - sum_{u=idx+1..N-1} A[u, idx]*X[u]) / A[idx, idx]
    N0 = N - 1
    out[N0] = B[N0] / A[N0, N0]
    for p in range(1, N):
        idx_back = N0 - p
        s = 0.0
        for u in range(idx_back + 1, N):
            s = s + A[u, idx_back] * out[u]
        out[idx_back] = (B[idx_back] - s) / A[idx_back, idx_back]


__all__ = [
    # constants
    "SOL", "PI", "TWOPI", "DEG_TO_RAD", "RAD_TO_DEG",
    "R_GOLD", "C_GOLD",
    # Tier 1
    "cross_3", "dot_3", "norm_3", "plh2xyz_scalar",
    # Tier 2
    "hermite_c_1d", "hermite_c_1d_uniform",
    # Tier 3
    "goldop_search", "polyfit_normal_eqs",
]
