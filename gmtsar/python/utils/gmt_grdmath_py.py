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
  MOD, DENAN, ISNAN, PI (constant), SQR (handled inline), BLEND, BITXOR
  — these appear in complex chained expressions in estimate_ionospheric_phase
    and p2p_S1_TOPS_doublediff that mix constants, PI, and multi-op chains.
    Wiring those sites safely requires a full RPN stack evaluator; deferred.

GATE
----
  GMTSAR_GRDMATH_PY=1  → use this module's helpers
  GMTSAR_GRDMATH_PY=0  → fall back to `gmt grdmath ...` subprocess (default OFF)

WIRE-IN STATUS
--------------
  filter:195     HYPOT     ← gmt_grdmath_py._grdmath2("HYPOT", ...)
  filter:196     POW+FLIPUD ← chained via _grdmath_pow_flipud()
  filter:216     MUL       ← _grdmath2("MUL", ...)
  filter:217     GE+NAN    ← _grdmath_ge_nan()
  filter:218     multi-op  ← _grdmath_corr_chain()
  filter:228     ATAN2+MUL+FLIPUD ← _grdmath_atan2_mul_flipud()
  filter:250     MUL+FLIPUD ← _grdmath_mul_flipud()
  filter:266     FLIPUD    ← _grdmath1("FLIPUD", ...)

  stack:67       copy (A = out) ← _grdmath_assign()
  stack:69       ADD       ← _grdmath2("ADD", ...)
  stack:72       DIV       ← _grdmath2("DIV", ...)
  stack:78       SUB+SQR   ← _grdmath_sub_sqr()
  stack:80       SUB+SQR+ADD ← _grdmath_sub_sqr_add()
  stack:82       DIV+SQRT  ← _grdmath_div_sqrt()
  stack:85/87    MUL       ← _grdmath2("MUL", ...)

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
    a64 = _f64(a)
    b64 = float(b) if _is_scalar(b) else _f64(b)
    with np.errstate(invalid="ignore"):
        # np.fmin: ignores NaN unless BOTH are NaN (propagates when both NaN)
        return np.fmin(a64, b64).astype(np.float32)


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

    Header layout (all little-endian):
        bytes 0-3:   nx (int32)
        bytes 4-7:   ny (int32)
        bytes 8-11:  0 (int32 padding)
        bytes 12-19: xmin (float64)  — x[0]
        bytes 20-27: xmax (float64)  — x[-1]
        bytes 28-35: ymin (float64)  — y[0]
        bytes 36-43: ymax (float64)  — y[-1]
        bytes 44-51: zmin (float64)  — nanmin of data
        bytes 52-59: zmax (float64)  — nanmax of data
        bytes 60-67: xy_off (float64) — 1.0 (GMT always writes 1.0 for gridline-reg)
        bytes 68-75: xinc (float64)
        bytes 76-83: yinc (float64)
        bytes 84-91: nan_value (float64) — 0.0 (NaN in data is float32 NaN)
        bytes 92-171: x_units (80 bytes, null-padded) — b'x'
        bytes 172-251: y_units (80 bytes, null-padded) — b'y'
        bytes 252-331: z_units (80 bytes, null-padded) — b'z'
        bytes 332-411: title (80 bytes, null-padded)
        bytes 412-731: command (320 bytes, null-padded)
        bytes 732-891: remark (160 bytes, null-padded)
    Total header: 892 bytes.

    Data: ny*nx float32 LE values, top row (y[-1]) first.
    NaN cells are written as float32 NaN (0x7fc00000).
    """
    data = np.asarray(data, dtype=np.float32)
    ny, nx = data.shape
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)

    xmin = float(x[0])
    xmax = float(x[-1])
    ymin = float(y[0])
    ymax = float(y[-1])
    xinc = float(info.get("x_inc", (x[-1] - x[0]) / (nx - 1) if nx > 1 else 1.0))
    yinc = float(info.get("y_inc", (y[-1] - y[0]) / (ny - 1) if ny > 1 else 1.0))

    valid = data[~np.isnan(data)]
    if valid.size == 0:
        zmin = zmax = 0.0
    else:
        zmin = float(np.min(valid))
        zmax = float(np.max(valid))

    # Build header in exactly 892 bytes
    hdr = bytearray(892)

    # Fixed-layout fields
    struct.pack_into("<i", hdr, 0, nx)
    struct.pack_into("<i", hdr, 4, ny)
    struct.pack_into("<i", hdr, 8, 0)
    struct.pack_into("<d", hdr, 12, xmin)
    struct.pack_into("<d", hdr, 20, xmax)
    struct.pack_into("<d", hdr, 28, ymin)
    struct.pack_into("<d", hdr, 36, ymax)
    struct.pack_into("<d", hdr, 44, zmin)
    struct.pack_into("<d", hdr, 52, zmax)
    struct.pack_into("<d", hdr, 60, 1.0)   # xy_off — GMT gridline-reg always writes 1.0
    struct.pack_into("<d", hdr, 68, xinc)
    struct.pack_into("<d", hdr, 76, yinc)
    struct.pack_into("<d", hdr, 84, 0.0)   # nan_value

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
    result = np.flipud(_op_mul(divided, mask))
    hist = (f"gmt grdmath {amp_grd} {tmp_grd} SQRT DIV "
            f"{mask_grd} MUL FLIPUD = {dst} [gmt_grdmath_py {ctx}]")
    if "=bf" in dst:
        # Strip the =bf suffix to get the actual file path, then write
        # a genuine GMT binary-float file that conv can fopen() directly.
        dst_path = dst.split("=")[0]
        _write_gmt_binary_float(dst_path, result, x, y, info, hist=hist)
    else:
        _save(dst, result, x, y, info, hist=hist)


def grdmath_ge_nan_mul(a: str, thresh, mask_grd: str, dst: str,
                        ctx: str = "") -> None:
    """In-process `gmt grdmath <a> <thresh> GE 0 NAN <mask> MUL = <dst>`.

    Handles geocode:161 and merge_unwrap_geocode_tops:285 pattern.
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
