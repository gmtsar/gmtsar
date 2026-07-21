#!/usr/bin/env python3
"""gmt_grdmath_py — in-process numpy replacements for `gmt grdmath` expressions.

C SOURCES PORTED
----------------
This module replaces subprocess calls to the GMT 6.4 binary `gmt grdmath`.
No C source was ported line-by-line; instead, each operator's semantics
is taken verbatim from `gmt grdmath --help` and the GMT Technical Reference
(§7.4 "grid mathematics"). Verified bit/float-equal against the C binary
via the parity test in bin_py/tests/test_gmt_grdmath_py.py.

OPERATORS IMPLEMENTED (13 of 13 requested)
-------------------------------------------
  FLIPUD   np.flipud (row reversal)
  MUL      A * B  (grid×grid or grid×scalar); NaN propagates
  ADD      A + B
  SUB      A - B
  DIV      A / B
  ABS      |A|
  SQRT     √A
  SQR      A²
  POW      A^B
  HYPOT    √(A²+B²)
  ATAN2    atan2(A, B)   — GMT pushes Y then X: ATAN2 pops B=X, A=Y
  GE       1.0 if A >= B else 0.0  (NaN→NaN)
  LE       1.0 if A <= B else 0.0  (NaN→NaN)
  NAN      NaN if A == B else A    (replacement: `A B NAN` = `np.where(A==B, nan, A)`)
  XOR      GMT semantics: 0 if both NaN, NaN if B==NaN, else A
  MIN      element-wise min(A, B); NaN if either is NaN

OPERATORS NOT IMPLEMENTED (left on C path)
-------------------------------------------
  MOD, DENAN, ISNAN, PI (constant), BLEND, BITXOR
  — MOD and PI appear in estimate_ionospheric_phase and p2p_S1_TOPS_doublediff
    in expressions like `PI ADD 2 PI MUL MOD PI SUB`.  These require a full
    RPN stack evaluator to safely decompose; those specific call sites remain
    on the gmt subprocess path.  All other call sites in those files that use
    only supported operators ARE wired.

GATE
----
  GMTSAR_GRDMATH_PY=1  → use this module's helpers (default ON since v2.3.8)
  GMTSAR_GRDMATH_PY=0  → fall back to `gmt grdmath ...` subprocess

WIRE-IN STATUS (v2.4.x comprehensive wiring)
---------------------------------------------
  filter:195     HYPOT          ← grdmath2("HYPOT", ...)
  filter:196     POW+FLIPUD     ← grdmath_pow_flipud()
  filter:216     MUL            ← grdmath2("MUL", ...)
  filter:217     GE+NAN         ← grdmath_ge_nan()
  filter:218     multi-op chain ← grdmath_corr_chain()
  filter:228     ATAN2+MUL+FLIPUD ← grdmath_atan2_mul_flipud()
  filter:250     MUL+FLIPUD     ← grdmath_mul_flipud()
  filter:266     FLIPUD         ← grdmath1("FLIPUD", ...)
  filter:294     POW            ← grdmath2("POW", ...)
  filter:295-296 phase-gradient ← grdmath_phase_gradient_chain()

  stack:67       copy (A = out) ← grdmath_assign()
  stack:69       ADD            ← grdmath2("ADD", ...)
  stack:72       DIV            ← grdmath2("DIV", ...)
  stack:78       SUB+SQR        ← grdmath_sub_sqr()
  stack:80       SUB+SQR+ADD    ← grdmath_sub_sqr_add()
  stack:82       DIV+SQRT       ← grdmath_div_sqrt()
  stack:85/87    MUL            ← grdmath2("MUL", ...)

  align_tops:283-284      FLIPUD      ← grdmath1("FLIPUD", ...)
  fitoffset_ra:42-43      FLIPUD      ← grdmath1("FLIPUD", ...)
  correct_insar_with_gnss:85   SUB    ← grdmath2("SUB", ...)
  correct_merge_offset:104,113 SUB    ← grdmath2("SUB", ...)
  correct_merge_offset:120,129 SUB    ← grdmath2("SUB", ...)
  correct_merge_offset:130     SUB+SUB ← grdmath_sub_sub()
  stack_corr:40-49        SQR/SUB/DIV/ADD/SQRT chain ← grdmath_stack_corr_*()
  stack_coherence_mask:29-37  MUL/ADD/DIV/GE/NAN ← grdmath2() + grdmath_ge_nan()
  merge_unwrap_geocode_tops:285 GE+NAN+MUL ← grdmath_ge_nan_mul()
  merge_unwrap_geocode_tops:286,297 MUL ← grdmath2("MUL", ...)
  merge_unwrap_geocode_tops:299 MUL+MUL ← grdmath_mul_scalar_mul_scalar()
  snaphu:173-174,183-184  MUL         ← grdmath2("MUL", ...)
  snaphu:187-188          GE+NAN+MUL  ← grdmath_ge_nan_mul()
  snaphu:189,358          XOR+MIN     ← grdmath_xor_min()
  snaphu:190,196,229,234,237,341,354,359,364,404,413,419  MUL ← grdmath2("MUL")
  snaphu:357              GE+NAN+MUL  ← grdmath_ge_nan_mul()
  geocode:161             GE+NAN+MUL  ← grdmath_ge_nan_mul()
  p2p_ALOS2_SCAN_Frame:219 MUL        ← grdmath2("MUL", ...)
  p2p_S1_TOPS_doublediff:148 SUB      ← grdmath2("SUB", ...)
  make_dem:53             ADD         ← grdmath2("ADD", ...)
  make_los_ascii:30       ones-mask   ← grdmath_make_ones_mask()
  proj_model:56           tri-mul-add ← grdmath_tri_mul_add()

  FALLBACK (unsupported ops — stay on gmt subprocess):
  estimate_ionospheric_phase: PI, MOD, DENAN, ISNAN ops
  merge_unwrap_geocode_tops:236  MOD+PI chain
  p2p_S1_TOPS_doublediff:149     MOD+PI chain

PARITY GATE
-----------
  bin_py/tests/test_gmt_grdmath_py.py — runs C binary + Py on identical
  float32 grids; asserts max|diff| == 0 (exact ops) or < 1e-6 (SQRT/ATAN2/POW).
  C-parity test fails loudly if `gmt` binary is missing from PATH.
"""
from __future__ import annotations

import os
import struct
import sys
from typing import Tuple, Optional

import numpy as np

# ── I/O helpers (must be on sys.path — utils/ contains them) ─────────────────
try:
    from gmt_grd_io import read_gmt_grd as _read_gmt_grd  # type: ignore
    from gmt_grd_io import write_gmt_grd as _write_gmt_grd  # type: ignore
    _HAVE_IO = True
except ImportError as _io_err:
    _HAVE_IO = False
    _io_err_msg = repr(_io_err)


def _grdmath_py_enabled() -> bool:
    """Return True when GMTSAR_GRDMATH_PY=1.  Default OFF."""
    return os.environ.get("GMTSAR_GRDMATH_PY", "0") == "1"


# ── Internal helpers ──────────────────────────────────────────────────────────

def _is_scalar(x) -> bool:
    """True if x is a plain float/int, not a grid path."""
    try:
        float(x)
        return True
    except (TypeError, ValueError):
        return False


def _load(src, ref_info: Optional[dict] = None):
    """Load a grid or parse a scalar.

    Returns (array_or_float, x, y, info) where x/y/info are None for
    scalars.
    """
    if _is_scalar(src):
        return float(src), None, None, None
    data, x, y, info = _read_gmt_grd(src)
    data = data.astype(np.float32, copy=False)
    return data, x, y, info


def _save(path: str, data: np.ndarray, x, y, info: dict,
          hist: str) -> None:
    _write_gmt_grd(
        path, data.astype(np.float32), x, y,
        node_offset=int(info.get("node_offset", 0)),
        geographic=bool(info.get("geographic", False)),
        history=hist,
    )


def _resolve_xy_info(results):
    """From a list of (data, x, y, info) items pick the first grid's x/y/info."""
    for data, x, y, info in results:
        if x is not None:
            return x, y, info
    raise ValueError("no grid operand found — cannot determine output header")


# ── Core operator implementations ─────────────────────────────────────────────
#
# PRECISION CONTRACT (verified against GMT 6.4 binary):
#   - GMT performs ALL arithmetic in float64 internally; results are cast
#     to float32 on write. Grid×grid operations also go through float64.
#   - Therefore: upcast ALL operands to float64 before arithmetic, cast
#     result back to float32 at the _save() boundary.
#   - Using float32 throughout gives max|diff| ~3e-5 for scalar operations
#     like `A -79.58 MUL` (verified in parity test diagnosis).
#
# All _op_* functions return float32 arrays — the caller passes these
# to _save() which writes float32 to disk.

def _f64(x) -> np.ndarray:
    """Upcast ndarray or scalar to float64 ndarray."""
    if isinstance(x, np.ndarray):
        return x.astype(np.float64)
    return np.float64(x)


def _op_flipud(a: np.ndarray) -> np.ndarray:
    return np.flipud(a).astype(np.float32)


def _op_mul(a, b) -> np.ndarray:
    return (_f64(a) * _f64(b)).astype(np.float32)


def _op_add(a, b) -> np.ndarray:
    return (_f64(a) + _f64(b)).astype(np.float32)


def _op_sub(a, b) -> np.ndarray:
    return (_f64(a) - _f64(b)).astype(np.float32)


def _op_div(a, b) -> np.ndarray:
    """DIV: propagate NaN; zero-div → NaN (GMT semantics)."""
    a64 = _f64(a)
    b64 = _f64(b)
    with np.errstate(invalid="ignore", divide="ignore"):
        result = np.where(b64 == 0.0, np.float64(np.nan), a64 / b64)
    return result.astype(np.float32)


def _op_abs(a: np.ndarray) -> np.ndarray:
    return np.abs(_f64(a)).astype(np.float32)


def _op_sqrt(a: np.ndarray) -> np.ndarray:
    with np.errstate(invalid="ignore"):
        return np.sqrt(_f64(a)).astype(np.float32)


def _op_sqr(a: np.ndarray) -> np.ndarray:
    a64 = _f64(a)
    return (a64 * a64).astype(np.float32)


def _op_pow(a: np.ndarray, b) -> np.ndarray:
    with np.errstate(invalid="ignore"):
        return np.power(_f64(a), float(b)).astype(np.float32)


def _op_hypot(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.hypot(_f64(a), _f64(b)).astype(np.float32)


def _op_atan2(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    # GMT RPN: `Y X ATAN2` → atan2(Y, X). Caller must pass (Y, X) order.
    return np.arctan2(_f64(a), _f64(b)).astype(np.float32)


def _op_ge(a: np.ndarray, b) -> np.ndarray:
    # Comparison done in float64 to match GMT; output is 0.0/1.0/NaN
    a64 = _f64(a)
    b64 = float(b) if _is_scalar(b) else _f64(b)
    result = np.where(np.isnan(a64), np.float64(np.nan),
                      np.where(a64 >= b64, 1.0, 0.0))
    return result.astype(np.float32)


def _op_le(a: np.ndarray, b) -> np.ndarray:
    a64 = _f64(a)
    b64 = float(b) if _is_scalar(b) else _f64(b)
    result = np.where(np.isnan(a64), np.float64(np.nan),
                      np.where(a64 <= b64, 1.0, 0.0))
    return result.astype(np.float32)


def _op_nan(a: np.ndarray, b) -> np.ndarray:
    """GMT `A B NAN` = NaN where A == B, else A."""
    a64 = _f64(a)
    b64 = float(b) if _is_scalar(b) else _f64(b)
    return np.where(a64 == b64, np.float64(np.nan), a64).astype(np.float32)


def _op_xor(a: np.ndarray, b) -> np.ndarray:
    """GMT XOR: 0 if both NaN; NaN if B is NaN; else A.

    Per `gmt grdmath --help`:
        XOR  2 1  0 if A == NaN and B == NaN, NaN if B == NaN, else A
    """
    a64 = _f64(a)
    if _is_scalar(b):
        b64 = np.full_like(a64, float(b))
    else:
        b64 = _f64(b)
    both_nan = np.isnan(a64) & np.isnan(b64)
    b_nan = np.isnan(b64)
    result = np.where(both_nan, 0.0,
              np.where(b_nan, np.float64(np.nan), a64))
    return result.astype(np.float32)


def _op_min(a, b) -> np.ndarray:
    # GMT MIN propagates NaN when either operand is NaN (same as np.minimum).
    # np.fmin would ignore NaN, which differs from GMT's behaviour.
    a64 = _f64(a)
    b64 = float(b) if _is_scalar(b) else _f64(b)
    with np.errstate(invalid="ignore"):
        return np.minimum(a64, b64).astype(np.float32)


# ── Public single/binary-op helpers (used by wired call sites) ───────────────

_OPS1 = {
    "FLIPUD": _op_flipud,
    "ABS":    _op_abs,
    "SQRT":   _op_sqrt,
    "SQR":    _op_sqr,
}
_OPS2 = {
    "MUL":   _op_mul,
    "ADD":   _op_add,
    "SUB":   _op_sub,
    "DIV":   _op_div,
    "POW":   _op_pow,
    "HYPOT": _op_hypot,
    "GE":    _op_ge,
    "LE":    _op_le,
    "NAN":   _op_nan,
    "XOR":   _op_xor,
    "MIN":   _op_min,
    "ATAN2": _op_atan2,
}


def grdmath1(op: str, src: str, dst: str, ctx: str = "") -> None:
    """In-process `gmt grdmath <src> <op> = <dst>`.

    Parameters
    ----------
    op  : one of _OPS1 keys (FLIPUD, ABS, SQRT, SQR)
    src : input .grd path
    dst : output .grd path
    ctx : caller name for history string
    """
    if op not in _OPS1:
        raise ValueError(f"grdmath1: unknown unary op '{op}'; "
                         f"supported: {list(_OPS1)}")
    if not _HAVE_IO:
        raise RuntimeError(f"grdmath1 requires gmt_grd_io / netCDF4: {_io_err_msg}")
    data, x, y, info = _read_gmt_grd(src)
    result = _OPS1[op](data)  # _op_* handle casting internally via _f64()
    _save(dst, result, x, y, info,
          hist=f"gmt grdmath {src} {op} = {dst} [gmt_grdmath_py {ctx}]")


def grdmath2(op: str, a, b, dst: str, ctx: str = "") -> None:
    """In-process `gmt grdmath <a> <b> <op> = <dst>`.

    `a` or `b` may be a .grd path or a numeric scalar string/float.
    If both are grids, shapes must match.
    """
    if op not in _OPS2:
        raise ValueError(f"grdmath2: unknown binary op '{op}'; "
                         f"supported: {list(_OPS2)}")
    if not _HAVE_IO:
        raise RuntimeError(f"grdmath2 requires gmt_grd_io / netCDF4: {_io_err_msg}")

    a_scalar = _is_scalar(a)
    b_scalar = _is_scalar(b)
    if a_scalar and b_scalar:
        raise ValueError("grdmath2: both operands are scalars — no output grid")

    if a_scalar:
        # Keep as Python float (float64) — _op_* uses _f64() internally,
        # and np.float32 of a scalar would lose precision before the op.
        a_val = float(a)
        b_data, x, y, info = _read_gmt_grd(b)
        result = _OPS2[op](a_val, b_data)
    elif b_scalar:
        a_data, x, y, info = _read_gmt_grd(a)
        result = _OPS2[op](a_data, float(b))
    else:
        a_data, ax, ay, a_info = _read_gmt_grd(a)
        b_data, bx, by, b_info = _read_gmt_grd(b)
        if a_data.shape != b_data.shape:
            raise ValueError(
                f"grdmath2 {op}: shape mismatch {a}{a_data.shape} "
                f"vs {b}{b_data.shape}")
        x, y, info = ax, ay, a_info
        result = _OPS2[op](a_data, b_data)

    _save(dst, result.astype(np.float32), x, y, info,
          hist=f"gmt grdmath {a} {b} {op} = {dst} [gmt_grdmath_py {ctx}]")


# ── Compound helpers for high-traffic multi-op chains ─────────────────────────

def grdmath_assign(src: str, dst: str, ctx: str = "") -> None:
    """In-process `gmt grdmath <src> = <dst>` (copy)."""
    if not _HAVE_IO:
        raise RuntimeError(f"grdmath_assign requires gmt_grd_io: {_io_err_msg}")
    data, x, y, info = _read_gmt_grd(src)
    _save(dst, data.astype(np.float32), x, y, info,
          hist=f"gmt grdmath {src} = {dst} [gmt_grdmath_py {ctx}]")


def grdmath_sub_sqr(a: str, b: str, dst: str, ctx: str = "") -> None:
    """In-process `gmt grdmath <a> <b> SUB SQR = <dst>`."""
    if not _HAVE_IO:
        raise RuntimeError(f"grdmath_sub_sqr requires gmt_grd_io: {_io_err_msg}")
    a_data, x, y, info = _read_gmt_grd(a)
    b_data, bx, by, b_info = _read_gmt_grd(b)
    if a_data.shape != b_data.shape:
        raise ValueError(f"grdmath_sub_sqr: shape mismatch {a} vs {b}")
    result = _op_sqr(_op_sub(a_data, b_data))
    _save(dst, result, x, y, info,
          hist=f"gmt grdmath {a} {b} SUB SQR = {dst} [gmt_grdmath_py {ctx}]")


def grdmath_sub_sqr_add(a: str, b: str, acc: str, dst: str,
                         ctx: str = "") -> None:
    """In-process `gmt grdmath <a> <b> SUB SQR <acc> ADD = <dst>`."""
    if not _HAVE_IO:
        raise RuntimeError(f"grdmath_sub_sqr_add requires gmt_grd_io: {_io_err_msg}")
    a_data, x, y, info = _read_gmt_grd(a)
    b_data, _, _, _ = _read_gmt_grd(b)
    acc_data, _, _, _ = _read_gmt_grd(acc)
    result = _op_add(_op_sqr(_op_sub(a_data, b_data)), acc_data)
    _save(dst, result, x, y, info,
          hist=f"gmt grdmath {a} {b} SUB SQR {acc} ADD = {dst} "
               f"[gmt_grdmath_py {ctx}]")


def grdmath_div_sqrt(a: str, b, dst: str, ctx: str = "") -> None:
    """In-process `gmt grdmath <a> <b> DIV SQRT = <dst>`."""
    if not _HAVE_IO:
        raise RuntimeError(f"grdmath_div_sqrt requires gmt_grd_io: {_io_err_msg}")
    a_data, x, y, info = _read_gmt_grd(a)
    if _is_scalar(b):
        b_operand = b
    else:
        b_data_tmp, _, _, _ = _read_gmt_grd(b)
        b_operand = b_data_tmp
    result = _op_sqrt(_op_div(a_data, b_operand))
    _save(dst, result, x, y, info,
          hist=f"gmt grdmath {a} {b} DIV SQRT = {dst} [gmt_grdmath_py {ctx}]")


def grdmath_mul_flipud(a: str, b, dst: str, ctx: str = "") -> None:
    """In-process `gmt grdmath <a> <b> MUL FLIPUD = <dst>`.

    b may be a grid path or scalar.
    """
    if not _HAVE_IO:
        raise RuntimeError(f"grdmath_mul_flipud requires gmt_grd_io: {_io_err_msg}")
    a_data, x, y, info = _read_gmt_grd(a)
    if _is_scalar(b):
        b_operand = b
    else:
        b_data_tmp, _, _, _ = _read_gmt_grd(b)
        if a_data.shape != b_data_tmp.shape:
            raise ValueError(f"grdmath_mul_flipud: shape mismatch {a} vs {b}")
        b_operand = b_data_tmp
    result = np.flipud(_op_mul(a_data, b_operand))
    _save(dst, result, x, y, info,
          hist=f"gmt grdmath {a} {b} MUL FLIPUD = {dst} [gmt_grdmath_py {ctx}]")


def grdmath_pow_flipud(a: str, b, dst: str, ctx: str = "") -> None:
    """In-process `gmt grdmath <a> <b> POW FLIPUD = <dst>`."""
    if not _HAVE_IO:
        raise RuntimeError(f"grdmath_pow_flipud requires gmt_grd_io: {_io_err_msg}")
    a_data, x, y, info = _read_gmt_grd(a)
    a_data = a_data.astype(np.float32)
    result = np.flipud(_op_pow(a_data, b))
    _save(dst, result, x, y, info,
          hist=f"gmt grdmath {a} {b} POW FLIPUD = {dst} [gmt_grdmath_py {ctx}]")


def grdmath_ge_nan(a: str, thresh, dst: str, ctx: str = "") -> None:
    """In-process `gmt grdmath <a> <thresh> GE 0 NAN = <dst>`."""
    if not _HAVE_IO:
        raise RuntimeError(f"grdmath_ge_nan requires gmt_grd_io: {_io_err_msg}")
    a_data, x, y, info = _read_gmt_grd(a)
    ge_mask = _op_ge(a_data, thresh)
    result = _op_nan(ge_mask, 0.0)
    _save(dst, result, x, y, info,
          hist=f"gmt grdmath {a} {thresh} GE 0 NAN = {dst} [gmt_grdmath_py {ctx}]")


def grdmath_atan2_mul_flipud(y_grd: str, x_grd: str,
                              mask_grd: str, dst: str, ctx: str = "") -> None:
    """In-process `gmt grdmath <y_grd> <x_grd> ATAN2 <mask_grd> MUL FLIPUD = <dst>`.

    GMT RPN stack: ATAN2 pops X (top of stack) then Y, returns atan2(Y,X).
    The grdmath call site is:
        gmt grdmath imagfilt.grd realfilt.grd ATAN2 mask.grd MUL FLIPUD = phase.grd
    So imagfilt.grd is Y, realfilt.grd is X.
    """
    if not _HAVE_IO:
        raise RuntimeError(f"grdmath_atan2_mul_flipud requires gmt_grd_io: {_io_err_msg}")
    y_data, x_coord, y_coord, info = _read_gmt_grd(y_grd)
    x_data, _, _, _ = _read_gmt_grd(x_grd)
    m_data, _, _, _ = _read_gmt_grd(mask_grd)
    if not (y_data.shape == x_data.shape == m_data.shape):
        raise ValueError(
            f"grdmath_atan2_mul_flipud: shape mismatch "
            f"{y_grd}{y_data.shape} {x_grd}{x_data.shape} "
            f"{mask_grd}{m_data.shape}")
    phase = _op_atan2(y_data, x_data)
    result = np.flipud(_op_mul(phase, m_data))
    _save(dst, result, x_coord, y_coord, info,
          hist=(f"gmt grdmath {y_grd} {x_grd} ATAN2 {mask_grd} MUL FLIPUD "
                f"= {dst} [gmt_grdmath_py {ctx}]"))


def _write_gmt_binary_float(path: str, data: np.ndarray,
                             x: np.ndarray, y: np.ndarray,
                             info: dict, hist: str) -> None:
    """Write a genuine GMT binary-float (=bf) file at `path`.

    Format: 892-byte little-endian header followed by ny*nx float32 values
    in row-major order (top row first, i.e. y[-1] first).

    This matches what `conv` expects when it opens the file via fopen() after
    GMT_Read_Data with the =bf suffix: it seeks to byte 892 and reads raw
    float32 data directly.

    GMT native binary (=bf) header layout — verified byte-for-byte against
    `gmt grdmath ... = <file>=bf` on RS2 Hawaii real-data (v2.3.6 fix):

        bytes 0-3:   nx (int32) = n_columns
        bytes 4-7:   ny (int32) = n_rows
        bytes 8-11:  registration (int32): 0=gridline, 1=pixel
        bytes 12-19: xmin (float64) — wesn[XLO]: pixel-reg = x[0] - xinc/2
        bytes 20-27: xmax (float64) — wesn[XHI]: pixel-reg = x[-1] + xinc/2
        bytes 28-35: ymin (float64) — wesn[YLO]: pixel-reg = y[0] - yinc/2
        bytes 36-43: ymax (float64) — wesn[YHI]: pixel-reg = y[-1] + yinc/2
        bytes 44-51: zmin (float64) — nanmin of data
        bytes 52-59: zmax (float64) — nanmax of data
        bytes 60-67: xinc (float64)           <── NO xy_off field between zmax and xinc
        bytes 68-75: yinc (float64)
        bytes 76-83: nan_value (float64) — 1.0 (GMT 6.4 convention for this version)
        bytes 84-91: zeros (pad to 92-byte numeric block)
        bytes 92-171:  x_units (80 bytes, null-padded) — b'x'
        bytes 172-251: y_units (80 bytes, null-padded) — b'y'
        bytes 252-331: z_units (80 bytes, null-padded) — b'z'
        bytes 332-411: title (80 bytes, null-padded)
        bytes 412-731: command (320 bytes, null-padded)
        bytes 732-891: remark (160 bytes, null-padded)
    Total header: 892 bytes.

    PREVIOUS BUG (fixed in v2.3.6): the old code wrote:
        bytes 8-11:  0 (always — wrong; pixel-reg grids need 1)
        bytes 12-19: x[0] (node center — wrong for pixel-reg; should be x[0]-xinc/2)
        bytes 20-27: x[-1] (node center — wrong; should be x[-1]+xinc/2)
        bytes 28-35: y[0] (wrong)
        bytes 36-43: y[-1] (wrong)
        bytes 60-67: 1.0 (fictional "xy_off" field — does not exist in this format)
        bytes 68-75: xinc (one slot too late)
        bytes 76-83: yinc (one slot too late)
        bytes 84-91: 0.0 (nan_value at wrong offset)
    GMT reinterpreted this as: xinc=1.0, yinc=xinc=4, and gridline-reg,
    causing n_columns=(xmax-xmin)/1+1 = 3413 (instead of 854), producing
    1435×3414 conv output instead of the correct 718×854.

    Data: ny*nx float32 LE values, top row (y[-1]) first.
    NaN cells are written as float32 NaN (0x7fc00000).
    """
    data = np.asarray(data, dtype=np.float32)
    ny, nx = data.shape
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)

    xinc = float(info.get("x_inc", (x[-1] - x[0]) / (nx - 1) if nx > 1 else 1.0))
    yinc = float(info.get("y_inc", (y[-1] - y[0]) / (ny - 1) if ny > 1 else 1.0))
    node_offset = int(info.get("node_offset", 1))  # 1=pixel (GMTSAR default), 0=gridline

    # WESN: for pixel-registration, boundaries are half-cell outside the node centres.
    # For gridline-registration, node centres ARE the boundaries.
    if node_offset == 1:
        xmin = float(x[0]) - xinc / 2.0
        xmax = float(x[-1]) + xinc / 2.0
        ymin = float(y[0]) - yinc / 2.0
        ymax = float(y[-1]) + yinc / 2.0
    else:
        xmin = float(x[0])
        xmax = float(x[-1])
        ymin = float(y[0])
        ymax = float(y[-1])

    valid = data[~np.isnan(data)]
    if valid.size == 0:
        zmin = zmax = 0.0
    else:
        zmin = float(np.min(valid))
        zmax = float(np.max(valid))

    # Build header in exactly 892 bytes
    hdr = bytearray(892)

    # Fixed-layout fields — layout verified against gmt grdmath oracle (RS2 Hawaii)
    struct.pack_into("<i", hdr, 0, nx)
    struct.pack_into("<i", hdr, 4, ny)
    struct.pack_into("<i", hdr, 8, node_offset)   # registration: 0=gridline, 1=pixel
    struct.pack_into("<d", hdr, 12, xmin)
    struct.pack_into("<d", hdr, 20, xmax)
    struct.pack_into("<d", hdr, 28, ymin)
    struct.pack_into("<d", hdr, 36, ymax)
    struct.pack_into("<d", hdr, 44, zmin)
    struct.pack_into("<d", hdr, 52, zmax)
    struct.pack_into("<d", hdr, 60, xinc)         # xinc at 60 — NO xy_off field here
    struct.pack_into("<d", hdr, 68, yinc)         # yinc at 68
    struct.pack_into("<d", hdr, 76, 1.0)          # nan_value at 76 (GMT 6.4 writes 1.0)
    # bytes 84-91: remain 0x00 (bytearray is zero-initialised)

    # String fields (null-padded to fixed widths)
    def _pack_str(buf, offset, s, width):
        b = s.encode("ascii", errors="replace")[:width]
        buf[offset:offset + len(b)] = b
        # remainder stays 0x00 (bytearray is zero-initialised)

    _pack_str(hdr, 92, "x", 80)
    _pack_str(hdr, 172, "y", 80)
    _pack_str(hdr, 252, "z", 80)
    _pack_str(hdr, 332, "", 80)                  # title
    _pack_str(hdr, 412, hist[:319], 320)          # command
    # remark at 732: leave zeros

    # Data is written as-is (row 0 of `data` = row 0 in the file).
    # Callers must pass data in the row order that GMT would have written
    # to a =bf file.  For grdmath_corr_chain, the FLIPUD operator has
    # already been applied to `result` before calling this function, so
    # result[0, :] is the northernmost (top) row — matching GMT's =bf
    # layout where row 0 = first y value after FLIPUD has been applied.
    with open(path, "wb") as fh:
        fh.write(bytes(hdr))
        fh.write(np.asarray(data, dtype="<f4").tobytes())


def grdmath_corr_chain(amp_grd: str, tmp_grd: str, mask_grd: str,
                        dst: str, ctx: str = "") -> None:
    """In-process `gmt grdmath <amp> <tmp> SQRT DIV <mask> MUL FLIPUD = <dst>`.

    Corresponds to filter:218:
        gmt grdmath amp.grd tmp.grd SQRT DIV mask.grd MUL FLIPUD = tmp2.grd=bf

    When `dst` ends with `=bf`, writes a genuine GMT binary-float file so that
    the downstream `conv` C binary can open it via fopen() + raw float32 read.
    When `dst` has no `=bf` suffix, writes a netCDF4 file (existing behaviour).
    """
    if not _HAVE_IO:
        raise RuntimeError(f"grdmath_corr_chain requires gmt_grd_io: {_io_err_msg}")
    amp, x, y, info = _read_gmt_grd(amp_grd)
    tmp_d, _, _, _ = _read_gmt_grd(tmp_grd)
    mask, _, _, _ = _read_gmt_grd(mask_grd)
    if not (amp.shape == tmp_d.shape == mask.shape):
        raise ValueError(
            f"grdmath_corr_chain: shape mismatch "
            f"{amp_grd}{amp.shape} {tmp_grd}{tmp_d.shape} "
            f"{mask_grd}{mask.shape}")
    sqrt_tmp = _op_sqrt(tmp_d)
    divided = _op_div(amp, sqrt_tmp)
    mul_result = _op_mul(divided, mask)
    hist = (f"gmt grdmath {amp_grd} {tmp_grd} SQRT DIV "
            f"{mask_grd} MUL FLIPUD = {dst} [gmt_grdmath_py {ctx}]")
    if "=bf" in dst:
        # Strip the =bf suffix to get the actual file path, then write
        # a genuine GMT binary-float file that conv can fopen() directly.
        #
        # ROW ORDER NOTE (v2.3.6 fix):
        # `read_gmt_grd` returns data with row 0 = smallest y (south).
        # `gmt grdmath ... FLIPUD = file=bf` writes the FLIPUD result to the
        # =bf file with row 0 = smallest y (verified byte-for-byte against the
        # C oracle on RS2 Hawaii).  Our reader already delivers south-first, so
        # writing mul_result directly (NO np.flipud) produces the oracle layout.
        # Applying np.flipud before writing was the old bug: it inverted the rows
        # relative to the oracle, causing conv to produce wrong values.
        dst_path = dst.split("=")[0]
        _write_gmt_binary_float(dst_path, mul_result, x, y, info, hist=hist)
    else:
        # Non-=bf path: write netCDF with FLIPUD applied so that downstream
        # readers that interpret y-axis conventionally get the correct mapping.
        _save(dst, np.flipud(mul_result), x, y, info, hist=hist)


def grdmath_ge_nan_mul(a: str, thresh, mask_grd: str, dst: str,
                        ctx: str = "") -> None:
    """In-process `gmt grdmath <a> <thresh> GE 0 NAN <mask> MUL = <dst>`.

    Handles geocode:161, merge_unwrap_geocode_tops:285, and snaphu pattern.
    """
    if not _HAVE_IO:
        raise RuntimeError(f"grdmath_ge_nan_mul requires gmt_grd_io: {_io_err_msg}")
    a_data, x, y, info = _read_gmt_grd(a)
    m_data, _, _, _ = _read_gmt_grd(mask_grd)
    ge_mask = _op_ge(a_data, thresh)
    nan_mask = _op_nan(ge_mask, 0.0)
    result = _op_mul(nan_mask, m_data)
    _save(dst, result, x, y, info,
          hist=(f"gmt grdmath {a} {thresh} GE 0 NAN {mask_grd} MUL = {dst} "
                f"[gmt_grdmath_py {ctx}]"))


# ── New helpers added for comprehensive wiring (v2.4.x) ───────────────────────

def grdmath_xor_min(a: str, b_xor, b_min, dst: str, ctx: str = "") -> None:
    """In-process `gmt grdmath <a> <b_xor> XOR <b_min> MIN = <dst>`.

    Handles snaphu pattern:
        gmt grdmath corr_patch.grd 0. XOR 1. MIN = corr_patch.grd

    XOR with b_xor=0.: NaN cells → 0.0, non-NaN cells unchanged.
    Then MIN with b_min=1.: clamp to <= 1.0.
    Net effect: replace NaN with 0, clamp to [0,1].
    """
    if not _HAVE_IO:
        raise RuntimeError(f"grdmath_xor_min requires gmt_grd_io: {_io_err_msg}")
    a_data, x, y, info = _read_gmt_grd(a)
    xor_result = _op_xor(a_data, b_xor)
    result = _op_min(xor_result, b_min)
    _save(dst, result, x, y, info,
          hist=(f"gmt grdmath {a} {b_xor} XOR {b_min} MIN = {dst} "
                f"[gmt_grdmath_py {ctx}]"))


def grdmath_sub_sub(a: str, s1, s2, dst: str, ctx: str = "") -> None:
    """In-process `gmt grdmath <a> <s1> SUB <s2> SUB = <dst>`.

    Handles correct_merge_offset 3-frame pattern:
        gmt grdmath tmp3_{out} {diff1} SUB {diff2} SUB = tmp3_{out}
    Both s1 and s2 may be scalars or grid paths.
    """
    if not _HAVE_IO:
        raise RuntimeError(f"grdmath_sub_sub requires gmt_grd_io: {_io_err_msg}")
    a_data, x, y, info = _read_gmt_grd(a)
    if _is_scalar(s1):
        step1 = _op_sub(a_data, float(s1))
    else:
        s1_data, _, _, _ = _read_gmt_grd(s1)
        step1 = _op_sub(a_data, s1_data)
    if _is_scalar(s2):
        result = _op_sub(step1, float(s2))
    else:
        s2_data, _, _, _ = _read_gmt_grd(s2)
        result = _op_sub(step1, s2_data)
    _save(dst, result, x, y, info,
          hist=(f"gmt grdmath {a} {s1} SUB {s2} SUB = {dst} "
                f"[gmt_grdmath_py {ctx}]"))


def grdmath_mul_scalar_mul_scalar(a: str, s1, s2, dst: str,
                                   ctx: str = "") -> None:
    """In-process `gmt grdmath <a> <s1> MUL <s2> MUL = <dst>`.

    Handles merge_unwrap_geocode_tops LOS pattern:
        gmt grdmath unwrap_mask.grd {wavel} MUL -79.58 MUL = los.grd
    Both s1 and s2 must be scalars (for grid×grid chains use grdmath2 twice).
    """
    if not _HAVE_IO:
        raise RuntimeError(
            f"grdmath_mul_scalar_mul_scalar requires gmt_grd_io: {_io_err_msg}")
    a_data, x, y, info = _read_gmt_grd(a)
    step1 = _op_mul(a_data, float(s1))
    result = _op_mul(step1, float(s2))
    _save(dst, result, x, y, info,
          hist=(f"gmt grdmath {a} {s1} MUL {s2} MUL = {dst} "
                f"[gmt_grdmath_py {ctx}]"))


def grdmath_make_ones_mask(los: str, topo: str, dst: str, ctx: str = "") -> None:
    """In-process `gmt grdmath <los> 0 MUL 1 ADD <topo> MUL = <dst>`.

    make_los_ascii:30 pattern — builds a topo grid masked to the los footprint:
        los * 0  → zeros (NaN where los is NaN)
        + 1      → ones  (NaN where los was NaN)
        * topo   → topo values masked to los footprint
    """
    if not _HAVE_IO:
        raise RuntimeError(
            f"grdmath_make_ones_mask requires gmt_grd_io: {_io_err_msg}")
    los_d, x, y, info = _read_gmt_grd(los)
    topo_d, _, _, _ = _read_gmt_grd(topo)
    zeros = _op_mul(los_d, 0.0)    # NaN propagates from los
    ones = _op_add(zeros, 1.0)
    result = _op_mul(ones, topo_d)
    _save(dst, result, x, y, info,
          hist=(f"gmt grdmath {los} 0 MUL 1 ADD {topo} MUL = {dst} "
                f"[gmt_grdmath_py {ctx}]"))


def grdmath_phase_gradient_chain(rf: str, xi: str, im: str, xr: str,
                                  ap: str, mk: str, dst: str,
                                  ctx: str = "") -> None:
    """In-process `gmt grdmath rf xi MUL im xr MUL SUB ap DIV mk MUL FLIPUD = dst`.

    Handles filter:295-296 phase-gradient pattern (x and y components):
        gmt grdmath realfilt.grd ximag.grd MUL imagfilt.grd xreal.grd MUL SUB
                   amp_pow.grd DIV mask.grd MUL FLIPUD = xphase.grd
    RPN: push rf, push xi, MUL → rf*xi; push im, push xr, MUL → im*xr;
         SUB → rf*xi - im*xr; push ap, DIV → .../ap;
         push mk, MUL → ...*mk; FLIPUD.
    """
    if not _HAVE_IO:
        raise RuntimeError(
            f"grdmath_phase_gradient_chain requires gmt_grd_io: {_io_err_msg}")
    rf_d, x, y, info = _read_gmt_grd(rf)
    xi_d, _, _, _ = _read_gmt_grd(xi)
    im_d, _, _, _ = _read_gmt_grd(im)
    xr_d, _, _, _ = _read_gmt_grd(xr)
    ap_d, _, _, _ = _read_gmt_grd(ap)
    mk_d, _, _, _ = _read_gmt_grd(mk)
    term1 = _op_mul(rf_d, xi_d)
    term2 = _op_mul(im_d, xr_d)
    diff = _op_sub(term1, term2)
    divided = _op_div(diff, ap_d)
    masked = _op_mul(divided, mk_d)
    result = np.flipud(masked).astype(np.float32)
    _save(dst, result, x, y, info,
          hist=(f"gmt grdmath {rf} {xi} MUL {im} {xr} MUL SUB "
                f"{ap} DIV {mk} MUL FLIPUD = {dst} [gmt_grdmath_py {ctx}]"))


def grdmath_tri_mul_add(ve: str, lle: str, vn: str, lln: str,
                         vu: str, llu: str, dst: str,
                         ctx: str = "") -> None:
    """In-process `gmt grdmath ve lle MUL vn lln MUL ADD vu llu MUL ADD = dst`.

    Handles proj_model:56 LOS projection:
        gmt grdmath tmpve.grd lle.grd MUL tmpvn.grd lln.grd MUL ADD
                   tmpvu.grd llu.grd MUL ADD = {out}
    """
    if not _HAVE_IO:
        raise RuntimeError(
            f"grdmath_tri_mul_add requires gmt_grd_io: {_io_err_msg}")
    ve_d, x, y, info = _read_gmt_grd(ve)
    lle_d, _, _, _ = _read_gmt_grd(lle)
    vn_d, _, _, _ = _read_gmt_grd(vn)
    lln_d, _, _, _ = _read_gmt_grd(lln)
    vu_d, _, _, _ = _read_gmt_grd(vu)
    llu_d, _, _, _ = _read_gmt_grd(llu)
    result = _op_add(_op_add(_op_mul(ve_d, lle_d), _op_mul(vn_d, lln_d)),
                     _op_mul(vu_d, llu_d))
    _save(dst, result, x, y, info,
          hist=(f"gmt grdmath {ve} {lle} MUL {vn} {lln} MUL ADD "
                f"{vu} {llu} MUL ADD = {dst} [gmt_grdmath_py {ctx}]"))


def grdmath_stack_corr_init(cor: str, dst_sum: str, ctx: str = "") -> None:
    """In-process first iteration of stack_corr:
        gmt grdmath {cor} SQR = tmp.grd
        gmt grdmath 1 tmp.grd SUB tmp.grd DIV = sum.grd

    Computes sum = (1 - cor^2) / cor^2 and writes to dst_sum.

    RPN for second line: push 1, push tmp (=cor^2), SUB → 1-cor^2,
    push tmp again, DIV → (1-cor^2)/cor^2.
    """
    if not _HAVE_IO:
        raise RuntimeError(
            f"grdmath_stack_corr_init requires gmt_grd_io: {_io_err_msg}")
    cor_d, x, y, info = _read_gmt_grd(cor)
    sqr = _op_sqr(cor_d)                  # cor^2
    numerator = _op_sub(1.0, sqr)         # 1 - cor^2  (scalar SUB grid: 1 tmp SUB)
    result = _op_div(numerator, sqr)      # (1 - cor^2) / cor^2
    _save(dst_sum, result, x, y, info,
          hist=(f"gmt grdmath {cor} SQR = tmp; 1 tmp SUB tmp DIV = {dst_sum} "
                f"[gmt_grdmath_py {ctx}]"))


def grdmath_stack_corr_accum(cor: str, acc: str, dst: str, ctx: str = "") -> None:
    """In-process subsequent iterations of stack_corr:
        gmt grdmath {cor} SQR = tmp.grd
        gmt grdmath 1 tmp.grd SUB tmp.grd DIV sum.grd ADD = tmp2.grd
        (caller does: mv tmp2.grd sum.grd)

    Computes new_acc = (1 - cor^2)/cor^2 + acc and writes to dst.
    """
    if not _HAVE_IO:
        raise RuntimeError(
            f"grdmath_stack_corr_accum requires gmt_grd_io: {_io_err_msg}")
    cor_d, x, y, info = _read_gmt_grd(cor)
    acc_d, _, _, _ = _read_gmt_grd(acc)
    sqr = _op_sqr(cor_d)
    term = _op_div(_op_sub(1.0, sqr), sqr)   # (1 - cor^2) / cor^2
    result = _op_add(term, acc_d)
    _save(dst, result, x, y, info,
          hist=(f"gmt grdmath {cor} SQR ... {acc} ADD = {dst} "
                f"[gmt_grdmath_py {ctx}]"))


def grdmath_stack_corr_final(acc: str, num: int, dst: str, ctx: str = "") -> None:
    """In-process final step of stack_corr:
        gmt grdmath 1 sum.grd {num} DIV 1 ADD DIV SQRT = {out}

    Computes mean_corr = sqrt(1 / (1 + sum/num)).

    RPN: push 1, push sum, push num, DIV → sum/num,
         (stack: 1, sum/num); 1 ADD → 1+sum/num,
         (stack: 1, 1+sum/num); DIV → 1/(1+sum/num); SQRT.
    """
    if not _HAVE_IO:
        raise RuntimeError(
            f"grdmath_stack_corr_final requires gmt_grd_io: {_io_err_msg}")
    acc_d, x, y, info = _read_gmt_grd(acc)
    inner = _op_add(_op_div(acc_d, float(num)), 1.0)  # sum/num + 1
    result = _op_sqrt(_op_div(1.0, inner))             # sqrt(1/(1+sum/num))
    _save(dst, result, x, y, info,
          hist=(f"gmt grdmath 1 {acc} {num} DIV 1 ADD DIV SQRT = {dst} "
                f"[gmt_grdmath_py {ctx}]"))
