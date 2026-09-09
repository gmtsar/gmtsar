"""_jit_kernels_sat — Numba JIT'd inner-loop kernels for SAT_llt2rat_py.

These kernels are factored OUT of SAT_llt2rat_py (the executable
script, which has no .py extension) into this top-level module so
that Numba's `@njit(cache=True)` can write IR sidecars to
`__pycache__/_jit_kernels_sat.cpython-3X.*.nbi/.nbc` and reload them
on subsequent invocations — saving ~5-6 s of cold JIT per process.

The script SAT_llt2rat_py is invoked as a script (no .py extension)
from sweep harnesses, so its module __name__ is "__main__", which
Numba CAN cache under — but only as long as that invocation context
is consistent. When the test harness loads the same file under a
DIFFERENT name (via importlib.SourceFileLoader → "sat_llt2rat_py_mod")
Numba sees a different module-of-record and can't share the cache.
Splitting kernels into this proper .py module sidesteps both issues:
the kernels' __name__ is always "_jit_kernels_sat" regardless of how
SAT_llt2rat_py itself is loaded.

Each kernel is a line-by-line scalar mirror of the C reference
(SAT_llt2rat.c, hermite_c.c). Constants are baked as Numba module
literals (R_LIT, C_LIT, the truncated golden-ratio C #defines) so
they propagate into the LLVM IR as immediates.

fastmath=False is REQUIRED for bit-parity with C — LLVM reordering
silently breaks reproducibility against the C oracle. cache=True
persists compiled IR to disk.
"""
from __future__ import annotations

import numpy as np
from numba import njit


# ---------- _hermite_c_1d_uniform_jit ----------------------------------------
# Horner fast-path for hermite_c interpolation on a uniform-grid orbit.
# Mirrors the pure-numpy `hermite_c_1d_uniform` op-for-op:
#   - same Horner reduction order over coefs (descending k)
#   - same per-query u, idx, f0, f1, hj_sq layout
#   - sum over i (in the inner loop here) accumulates in the SAME order
#     as numpy's (y_loc*f0 + z_loc*f1)*hj_sq sum-over-axis=0:
#       for i in 0..nval-1: yp += (y[i0+i]*f0_i + z[i0+i]*f1_i) * hj_sq_i
#     numpy `(...).sum(axis=0)` also reduces in ascending-i order at this
#     small N (nval=6, BLAS doesn't kick in), so the order matches.
# Used by polyfit_refine_batch (via hermite_orbit) where the AUDIT documents
# a known 1e-6 m residual vs C — that residual is from Horner basis vs C's
# direct Lagrange, NOT from numpy-vs-numba differences. This kernel preserves
# the numpy result bit-for-bit so the precise=1 azi_pix max|d|=2.4e-6 doesn't
# get worse.
@njit(cache=True, fastmath=False)
def _hermite_c_1d_uniform_jit(x0, dsec, y, z, xp, nval,
                              HJ, S_VALS, yp_out):
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
            # Horner ascending (Mira's basis): v = 0; for k = nval-1..0: v = v*u + HJ[i_idx,k]
            v = 0.0
            for k in range(nval - 1, -1, -1):
                v = v * u + HJ[i_idx, k]
            hj_sq = v * v
            u_minus_i = u - float(i_idx)
            f0 = 1.0 - 2.0 * u_minus_i * S_VALS[i_idx]
            f1 = u_minus_i * dsec
            yp = yp + (y[i0 + i_idx] * f0 + z[i0 + i_idx] * f1) * hj_sq
        yp_out[m] = yp


# ---------- _hermite_c_1d_jit ------------------------------------------------
# Line-by-line mirror of the pure-numpy hermite_c_1d above, which itself
# line-by-line mirrors C hermite_c.c (file:gmtsar/hermite_c.c). Inner loops
# preserve C's left-associative arithmetic:
#   hj = (hj * (xp - x[j+i0])) / (x[i+i0] - x[j+i0])   (Mira bug #5)
#   yp = yp + (y*f0 + z*f1) * hj * hj                  (left-assoc * hj * hj)
# Single-thread, fastmath=False, plain `range`. nval is treated as runtime int
# so the same compiled body handles nval=6 (the only one gmtsar uses) without
# specialisation.
@njit(cache=True, fastmath=False)
def _hermite_c_1d_jit(x, y, z, xp, nval, yp_out):  # noqa: D401
    nmax = x.shape[0]
    n = nval - 1
    M = xp.shape[0]
    x0v = x[0]
    xLv = x[nmax - 1]
    # i0_clip_max = nmax - n - 1
    clip_max = nmax - n - 1
    for m in range(M):
        xpm = xp[m]
        # C: error if outside [x[0], x[nmax-1]]
        if xpm < x0v or xpm > xLv:
            # Match numpy raise: produce NaN; parity-test would catch it.
            yp_out[m] = np.nan
            continue
        # C: find first i with x[i] >= xpm  (searchsorted, side='left')
        # Linear search is O(nmax) but nmax<=64 in gmtsar orbit context;
        # binary search to be safe.
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


# ---------- _goldop_jit ------------------------------------------------------
# Line-by-line scalar mirror of C `goldop` in SAT_llt2rat.c (lines 332-393),
# applied per-target. This is actually CLEANER for parity than the np.where
# vectorisation in SAT_llt2rat_py because it mirrors the scalar C function
# 1:1 — same SHFT3/SHFT2 cascade with OLD-value capture, same per-iter
# sqrt (Mira bug #9), same int truncation via Numba float64-to-int64 cast.
#
# Constants captured: R_LIT=0.61803399, C_LIT=0.382 (Mira bug "truncated
# golden ratio in C #define R, C"). We hard-bake these inside the kernel
# (Numba constants) so they propagate as literals, NOT module-level lookups.
@njit(cache=True, fastmath=False)
def _goldop_jit(op_t, px, py, pz, tx, ty, tz, R_out, T_out):
    R_LIT = 0.61803399
    C_LIT = 0.382
    nrec = px.shape[0]
    N = tx.shape[0]
    ax_init = 0
    bx_init = nrec - 1
    cx_init = int(ax_init + (bx_init - ax_init) * C_LIT)
    # Per-target initial bracket (all identical at start). Per-C:
    #   if abs(bx-cx) > abs(cx-ax): x1=cx, x2=cx+int(abs(C*(bx-cx)))
    #   else:                       x2=cx, x1=cx-int(abs(C*(cx-ax)))
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
        # while (x3 - x0) > 2 and x2 != x1
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
                # clip to valid range (defensive; matches numpy version)
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
