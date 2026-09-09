"""_jit_kernels_resamp — Numba JIT'd inner-loop kernels for resamp_py.

These kernels are factored OUT of resamp_py (the executable script,
which has no .py extension) into this top-level module so that:

1. Numba's disk cache (`@njit(cache=True)`) writes IR sidecars to
   `__pycache__/_jit_kernels_resamp.cpython-3X.*.nbi/.nbc` that are
   keyed off this module's STABLE `__name__` (`_jit_kernels_resamp`).
   The cache survives across subprocess invocations of resamp_py.
2. Loading via `exec(compile(...))` (the resamp_py test harness, see
   bin_py/tests/test_resamp.py) does NOT confuse Numba's cache —
   the test loader exec's the SCRIPT, which then `import`s us
   normally, so our `__name__` is always stable regardless of how
   resamp_py itself was launched.

Each kernel mirrors the equivalent block in resamp.c BIT-FOR-BIT:
  - `_round_clip`  : C-style `(short)clipi2(x + 0.5)` (round half-away-
                     from-zero, then clamp to int16, then cast-truncate
                     toward zero).
  - `_knearest`    : intrp=1 (resamp.c:447-475)
  - `_kbilinear`   : intrp=2 (resamp.c:477-495)
  - `_kbicubic`    : intrp=3 (resamp.c:497-553)
  - `_kbisinc`     : intrp=4 (resamp.c:555-608)
  - `_kbisinc_grid`: intrp=5 (resamp.c:98-254 — fuses grid-shift + bisinc)

fastmath=False is REQUIRED — LLVM reordering of FP ops silently breaks
bit-parity with C. cache=True persists compiled IR to disk so cold start
(~7 s on the full 5-kernel build) is paid once per code-change cycle,
not per invocation. inline="always" on the leaf helpers (round_clip,
ckernel, skernel) keeps them inlined despite cache=True.
"""
from __future__ import annotations

import numpy as np
from numba import njit

# C #define constants from gmtsar.h — must be Numba module-level
# literals (captured as closures over the module globals when the
# functions are compiled) so they propagate as constants into the
# generated LLVM IR. Do NOT replace with the mathematically correct
# equivalents — C bakes these truncated values into millions of
# accumulations and the port must match bit-for-bit.
I2MAX = 32767.0
NS = 4
PI = 3.1415926535897932


@njit(fastmath=False, cache=True, inline="always")
def _round_clip(x):
    """Inlined C-style round/clip helper. Matches `(short)clipi2(x+0.5)`
    bit-for-bit: clamp x+0.5 to [-I2MAX, +I2MAX] as DOUBLE, then truncate
    toward zero via int16 cast.
    """
    y = x + 0.5
    if y > I2MAX:
        y = I2MAX
    elif y < -I2MAX:
        y = -I2MAX
    # Truncate-toward-zero: numpy/numba int16 cast on a finite float is
    # round-toward-zero, identical to C's (short) cast.
    return np.int16(y)


@njit(fastmath=False, cache=True)
def _knearest(ras0, ras1, sin_flat, ydims, xdims, sout):
    """intrp=1 nearest-neighbor. resamp.c:447-475."""
    n = ras0.shape[0]
    row_stride = 2 * xdims
    for p in range(n):
        # C: j = (int)(ras[0] + 0.5); for negative ras this TRUNCATES
        # toward zero, NOT floors. np.int64 cast of a float does the
        # same: (-0.3 + 0.5) -> 0.2 -> int -> 0; (-0.7 + 0.5) -> -0.2
        # -> int -> 0.
        j = np.int64(ras0[p] + 0.5)
        i = np.int64(ras1[p] + 0.5)
        if i < 0 or i >= ydims or j < 0 or j >= xdims:
            sout[2 * p] = 0
            sout[2 * p + 1] = 0
        else:
            base = row_stride * i + 2 * j
            sout[2 * p] = sin_flat[base]
            sout[2 * p + 1] = sin_flat[base + 1]


@njit(fastmath=False, cache=True)
def _kbilinear(ras0, ras1, sin_flat, ydims, xdims, sout):
    """intrp=2 bilinear. resamp.c:476-495."""
    n = ras0.shape[0]
    row_stride = 2 * xdims
    for p in range(n):
        r0 = ras0[p]
        r1 = ras1[p]
        j0 = np.int64(np.floor(r0))
        i0 = np.int64(np.floor(r1))
        dr = r0 - np.float64(j0)
        da = r1 - np.float64(i0)
        if i0 < 0 or i0 >= (ydims - 1) or j0 < 0 or j0 >= (xdims - 1):
            sout[2 * p] = 0
            sout[2 * p + 1] = 0
        else:
            base = row_stride * i0 + 2 * j0
            k00 = base
            k01 = base + 2
            k10 = base + row_stride
            k11 = base + row_stride + 2
            # MATCH C ordering exactly (resamp.c:476-477):
            #   real = s_in[k00]*(1-da)*(1-dr)
            #        + s_in[k10]*(da)*(1-dr)
            #        + s_in[k01]*(1-da)*(dr)
            #        + s_in[k11]*(da)*(dr)
            w_1mda_1mdr = (1.0 - da) * (1.0 - dr)
            w_da_1mdr = da * (1.0 - dr)
            w_1mda_dr = (1.0 - da) * dr
            w_da_dr = da * dr
            real = (np.float64(sin_flat[k00]) * w_1mda_1mdr
                    + np.float64(sin_flat[k10]) * w_da_1mdr
                    + np.float64(sin_flat[k01]) * w_1mda_dr
                    + np.float64(sin_flat[k11]) * w_da_dr)
            imag = (np.float64(sin_flat[k00 + 1]) * w_1mda_1mdr
                    + np.float64(sin_flat[k10 + 1]) * w_da_1mdr
                    + np.float64(sin_flat[k01 + 1]) * w_1mda_dr
                    + np.float64(sin_flat[k11 + 1]) * w_da_dr)
            sout[2 * p] = _round_clip(real)
            sout[2 * p + 1] = _round_clip(imag)


@njit(fastmath=False, cache=True, inline="always")
def _ckernel(arg):
    """cubic_kernel from resamp.c:369-388 with a=-0.3 (HARD-CODED;
    do NOT pass a as a parameter — the JIT specializes constants
    better when they're inlined).
    """
    a = -0.3
    arg2 = arg * arg
    arg3 = arg2 * arg
    if arg <= 1.0:
        return (a + 2.0) * arg3 - (a + 3.0) * arg2 + 1.0
    elif arg <= 2.0:
        return a * arg3 - 5.0 * a * arg2 + 8.0 * a * arg - 4.0 * a
    else:
        return 0.0


@njit(fastmath=False, cache=True)
def _kbicubic(ras0, ras1, sin_flat, ydims, xdims, sout):
    """intrp=3 bicubic Keys (a=-0.3). resamp.c:497-553."""
    n = ras0.shape[0]
    row_stride = 2 * xdims
    wx = np.empty(4, dtype=np.float64)
    wy = np.empty(4, dtype=np.float64)
    for p in range(n):
        r0 = ras0[p]
        r1 = ras1[p]
        j0 = np.int64(np.floor(r0))
        i0 = np.int64(np.floor(r1))
        dr = r0 - np.float64(j0)
        da = r1 - np.float64(i0)
        if (i0 - 1) < 0 or (i0 + 2) >= ydims or \
           (j0 - 1) < 0 or (j0 + 2) >= xdims:
            sout[2 * p] = 0
            sout[2 * p + 1] = 0
            continue
        # Compute weights — mirror C bicubic_one (resamp.c:335-340):
        #   wx[i] = cubic_kernel(|x + 1 - i|, a)
        #   wy[i] = cubic_kernel(|y + 1 - i|, a)
        for i in range(4):
            wx[i] = _ckernel(abs(dr + 1.0 - i))
            wy[i] = _ckernel(abs(da + 1.0 - i))
        # Accumulate in C's exact order (resamp.c:344-352):
        #   for j in 0..3: for i in 0..3:
        #     w = wx[i]*wy[j]; rsum += rdata[j*4+i]*w; ...
        # where rdata[j*4+i] = sin_flat[row_stride*(i0-1+j) + 2*(j0-1+i)]
        rsum = 0.0
        isum = 0.0
        wsum = 0.0
        base_row = row_stride * (i0 - 1) + 2 * (j0 - 1)
        for j in range(4):
            row_off = base_row + row_stride * j
            wyj = wy[j]
            for i in range(4):
                w = wx[i] * wyj
                k = row_off + 2 * i
                rsum += np.float64(sin_flat[k]) * w
                isum += np.float64(sin_flat[k + 1]) * w
                wsum += w
        cz_r = rsum / wsum
        cz_i = isum / wsum
        sout[2 * p] = _round_clip(cz_r)
        sout[2 * p + 1] = _round_clip(cz_i)


@njit(fastmath=False, cache=True, inline="always")
def _skernel(x):
    """sinc_kernel from resamp.c:676-687. Uses the C truncated PI
    3.1415926535897932 (hard-coded in C #define), so np.sinc would
    produce slightly different values — we evaluate by hand.
    """
    arg = abs(PI * x)
    if arg > 0.0:
        return np.sin(arg) / arg
    else:
        return 1.0


@njit(fastmath=False, cache=True)
def _kbisinc(ras0, ras1, sin_flat, ydims, xdims, sout):
    """intrp=4 truncated 4-tap sinc. resamp.c:554-608."""
    n = ras0.shape[0]
    row_stride = 2 * xdims
    # ns2 = NS/2 - 1 = 1.0 in C with NS=4 (computed in DOUBLE per
    # resamp.c:555). Both 1.0 (double) and 1 (int) coincide here.
    ns2_d = np.float64(NS // 2 - 1)  # 1.0
    ns2 = NS // 2 - 1  # 1
    wx = np.empty(NS, dtype=np.float64)
    wy = np.empty(NS, dtype=np.float64)
    for p in range(n):
        r0 = ras0[p]
        r1 = ras1[p]
        j0 = np.int64(np.floor(r0))
        i0 = np.int64(np.floor(r1))
        dr = r0 - np.float64(j0)
        da = r1 - np.float64(i0)
        if (i0 - ns2) < 0 or (i0 + ns2 + 1) >= ydims or \
           (j0 - ns2) < 0 or (j0 + ns2 + 1) >= xdims:
            sout[2 * p] = 0
            sout[2 * p + 1] = 0
            continue
        for i in range(NS):
            wx[i] = _skernel(abs(dr + ns2_d - i))
            wy[i] = _skernel(abs(da + ns2_d - i))
        # Accumulate in C order (resamp.c:715-723):
        #   for j in 0..NS-1: for i in 0..NS-1:
        #     w = wx[i]*wy[j]; rsum += rdata[j*NS+i]*w; ...
        rsum = 0.0
        isum = 0.0
        wsum = 0.0
        base_row = row_stride * (i0 - ns2) + 2 * (j0 - ns2)
        for j in range(NS):
            row_off = base_row + row_stride * j
            wyj = wy[j]
            for i in range(NS):
                w = wx[i] * wyj
                k = row_off + 2 * i
                rsum += np.float64(sin_flat[k]) * w
                isum += np.float64(sin_flat[k + 1]) * w
                wsum += w
        cz_r = rsum / wsum
        cz_i = isum / wsum
        sout[2 * p] = _round_clip(cz_r)
        sout[2 * p + 1] = _round_clip(cz_i)


@njit(fastmath=False, cache=True)
def _kbisinc_grid(ii0, ii1, xdimm,
                  R_data, A_data, inc_y,
                  r1_arr, tx_arr, one_mtx_arr,
                  sin_flat, ydims, xdims, sout):
    """intrp=5 fused GMT-grid-shift + bisinc. resamp.c:98-254 + 555-608.

    Fuses grid_shift_vec + _kbisinc into one Numba kernel. Avoids
    materializing the per-chunk (ras0, ras1) and bad_mask arrays in
    numpy and the chain of .astype/np.where calls (profiled at ~2.2s
    on NISAR mode 5). Per-pixel cost is identical to the C inner loop
    at resamp.c:166-253 — bilinear-interpolate two GMT grids, NaN
    guard, then bisinc the result. FP accumulation order matches C
    exactly (ram[0] as the seed, left-to-right adds).

    x-side per-jj arithmetic (r1, tx, one_mtx) depends only on jj and
    inc_x — caller precomputes these into r1_arr / tx_arr / one_mtx_arr
    ONCE for the whole master image and passes them in. Each is shape
    (xdimm,). Saves ~6 ops × xdimm × ydimm scalar work in the inner
    loop. The arithmetic is deterministic so the precomputed values
    are bit-identical to what the inline form would produce.
    """
    ny_R, nx_R = R_data.shape
    nx = nx_R
    ny = ny_R
    row_stride = 2 * xdims
    ns2_d = np.float64(NS // 2 - 1)
    ns2 = NS // 2 - 1
    wx = np.empty(NS, dtype=np.float64)
    wy = np.empty(NS, dtype=np.float64)
    inv_inc_y = 1.0 / inc_y
    p = 0  # output pixel index within sout
    for ii in range(ii0, ii1):
        gy = np.float64(ii) * inv_inc_y
        # gy depends only on ii — precompute the y-side clamp & frac
        a1 = np.int64(np.floor(gy))
        if a1 < 0:
            a1 = 0
        if a1 > ny - 2:
            a1 = ny - 2
        ty_ = gy - np.float64(a1)
        one_mty = 1.0 - ty_
        a2 = a1 + 1
        for jj in range(xdimm):
            r1 = r1_arr[jj]
            r2 = r1 + 1
            tx_ = tx_arr[jj]
            one_mtx = one_mtx_arr[jj]
            # Range grid (R) bilinear shift, exact C accumulation order
            # (resamp.c:203-207): seed = ram[0] = jj
            f11 = np.float64(R_data[a1, r1])
            f12 = np.float64(R_data[a1, r2])
            f21 = np.float64(R_data[a2, r1])
            f22 = np.float64(R_data[a2, r2])
            r0 = np.float64(jj)
            r0 = r0 + one_mtx * one_mty * f11
            r0 = r0 + tx_ * one_mty * f12
            r0 = r0 + one_mtx * ty_ * f21
            r0 = r0 + tx_ * ty_ * f22
            # Azimuth grid (A) — same indices/fracs (C asserts equal incs)
            f11 = np.float64(A_data[a1, r1])
            f12 = np.float64(A_data[a1, r2])
            f21 = np.float64(A_data[a2, r1])
            f22 = np.float64(A_data[a2, r2])
            r1f = np.float64(ii)
            r1f = r1f + one_mtx * one_mty * f11
            r1f = r1f + tx_ * one_mty * f12
            r1f = r1f + one_mtx * ty_ * f21
            r1f = r1f + tx_ * ty_ * f22
            # NaN guard (resamp.c:245-249)
            if not (np.isfinite(r0) and np.isfinite(r1f)):
                sout[2 * p] = 0
                sout[2 * p + 1] = 0
                p += 1
                continue
            # bisinc kernel (mirrors _kbisinc above)
            j0 = np.int64(np.floor(r0))
            i0 = np.int64(np.floor(r1f))
            dr = r0 - np.float64(j0)
            da = r1f - np.float64(i0)
            if (i0 - ns2) < 0 or (i0 + ns2 + 1) >= ydims or \
               (j0 - ns2) < 0 or (j0 + ns2 + 1) >= xdims:
                sout[2 * p] = 0
                sout[2 * p + 1] = 0
                p += 1
                continue
            for i in range(NS):
                wx[i] = _skernel(abs(dr + ns2_d - i))
                wy[i] = _skernel(abs(da + ns2_d - i))
            rsum = 0.0
            isum = 0.0
            wsum = 0.0
            base_row = row_stride * (i0 - ns2) + 2 * (j0 - ns2)
            for j in range(NS):
                row_off = base_row + row_stride * j
                wyj = wy[j]
                for i in range(NS):
                    w = wx[i] * wyj
                    k = row_off + 2 * i
                    rsum += np.float64(sin_flat[k]) * w
                    isum += np.float64(sin_flat[k + 1]) * w
                    wsum += w
            cz_r = rsum / wsum
            cz_i = isum / wsum
            sout[2 * p] = _round_clip(cz_r)
            sout[2 * p + 1] = _round_clip(cz_i)
            p += 1


# Public table consumed by resamp_py._dispatch_kernel.
KERNELS = {
    1: _knearest,
    2: _kbilinear,
    3: _kbicubic,
    4: _kbisinc,
    5: _kbisinc_grid,
}
