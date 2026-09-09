#!/usr/bin/env python3
"""gmt_xyz2grd_py - in-process replacement for the binary -ZTL* mode of
``gmt xyz2grd``, as used by ``utils/snaphu.py``.

Scope (Rule 10 verbatim-first, scoped to the actual call sites)
-----------------------------------------------------------------

The ONLY mode ported is::

    gmt xyz2grd <file> -ZTL<type> -r -R<w>/<e>/<s>/<n> -I<xinc>/<yinc> -G<out>

i.e. a dense 1-column binary z-table in **scanline order, Top row first,
Left-to-right within each row** (the ``-ZTL`` flag combo), with **pixel
registration** (``-r``).  This is the snaphu unwrap/conncomp path:

    utils/snaphu.py:225  gmt xyz2grd unwrap.out   -ZTLf -r {par1} {par2} -Gtmp.grd
    utils/snaphu.py:226  gmt xyz2grd conncomp.out -ZTLu -r {par1} {par2} -Gconncomp.grd

NOT ported (out of scope -- no caller in this fork uses these with -Z):

* ``-A`` (multi-hit aggregation: mean/min/max/etc) -- ``-Z`` mode in GMT
  assumes **all nodes are present exactly once** (xyz2grd.c: the -Z reader
  fills the grid byte-for-byte from the table, no binning).  -A is
  documented as "ignored if -Z is given" (xyz2grd.rst -A).
* Gridline registration (no ``-r``) -- both call sites always pass ``-r``.
* ``-Z`` flags other than ``TL`` (e.g. ``BL``, ``TR``, ``BR``, periodic
  ``x``/``y`` modifiers, byte-swap ``w``, header-skip ``s<n>``) -- not used
  by any caller.
* Non-``-Z`` (3-column xyz) mode -- a genuinely different code path in
  xyz2grd.c (``GMT_xyz2grd`` table-reading + bin-averaging loop); out of
  scope for this mission (call sites #2/#3 in the mission brief).

Algorithm (xyz2grd.c, ``-Z`` branch, verified against gmt 6.4.0 by
round-tripping ``gmt grd2xyz -ZTLf`` -> ``gmt xyz2grd -ZTLf -r`` on a real
ALOS_haiti ``phase_patch.grd`` subset, byte-identical, 2026-06-12):

1. Read the raw binary file as a flat array of ``n_columns * n_rows``
   values of the requested ``-Z`` type (``f`` = float32, ``u`` = uint8_t
   per xyz2grd.rst -Z table).  GMT errors loudly
   ("Found N records, but M was expected (aborting)!") if the byte count
   does not divide evenly into ``nx*ny`` -- we mirror this with a hard
   ``ValueError``, never truncating or padding (Rule 1, no fallback).
2. Reshape to ``(ny, nx)``.  Because the data is **Top**-row-first, this
   reshape gives row 0 = y_max (top); flip vertically (``[::-1, :]``) to
   get the "y ascending" orientation that ``gmt_grd_io.write_gmt_grd``
   expects (row 0 = y_min), matching what ``gmt grdinfo``/``ncdump``
   report for the resulting ``.grd``.
3. GMT always stores grid data internally (and on disk, ``nf`` format) as
   ``float32`` regardless of the ``-Z`` input type -- so ``-ZTLu`` (uint8)
   data is upcast to float32 with no rescaling (verified: round-tripping a
   uint8 grdmath-derived grid through ``grd2xyz -ZTLu`` ->
   ``xyz2grd -ZTLu -r`` reproduces the truncated-to-integer float32 values
   bit-for-bit).
4. ``-R<w>/<e>/<s>/<n>`` + ``-I<xinc>/<yinc>`` + ``-r`` (pixel reg) define
   the output grid header.  For pixel registration,
   ``nx = round((e - w) / xinc)``, ``ny = round((n - s) / yinc)`` (NO +1 --
   that's only for gridline registration / gmt_M_get_n with
   ``registration=0``).  Coordinate arrays are cell centers:
   ``x[i] = w + (i + 0.5) * xinc``, ``y[j] = s + (j + 0.5) * yinc`` --
   exactly ``gmt_grd_io.write_gmt_grd_from_increments(..., node_offset=1)``.
5. No ``-A`` aggregation, no NaN-fill (``-Z`` mode requires every node be
   present in the input table; we do not silently fill missing nodes).

Public API
----------

gmt_xyz2grd_py(raw_bytes, *, region, x_inc, y_inc, dtype)
    Returns ``(data, x, y)`` -- ``data`` is float32 ``(ny, nx)`` in
    y-ascending orientation, ``x``/``y`` are pixel-center coordinate
    arrays.  Pure-array entry point, no file I/O.

gmt_xyz2grd_py_file(in_path, out_path, *, par1, par2, ztype, ...)
    Reads the raw ``-ZTL<ztype>`` binary file at ``in_path``, parses GMT
    ``-R``/``-I`` strings ``par1``/``par2`` (as produced by
    ``gmt grdinfo -I-``/``-I``), and writes ``out_path`` via
    ``gmt_grd_io.write_gmt_grd_from_increments``.  Drop-in replacement for::

        gmt xyz2grd <in_path> -ZTL<ztype> -r {par1} {par2} -G<out_path>

History
-------
* 2026-06-12 -- initial port, mira-volkov, Mission #71.  Byte-identical to
  gmt 6.4.0 on a real ALOS_haiti ``phase_patch.grd`` subset (-ZTLf
  round-trip rms=0, -ZTLu round-trip exact after float32 upcast).
"""
from __future__ import annotations

import re
from typing import Tuple

import numpy as np

# ---------------------------------------------------------------------------
# -Z type code -> numpy dtype (xyz2grd.rst -Z table, binary types only)
# ---------------------------------------------------------------------------

_Z_DTYPE = {
    "c": np.dtype("i1"),   # int8_t
    "u": np.dtype("u1"),   # uint8_t
    "h": np.dtype("i2"),   # int16_t
    "H": np.dtype("u2"),   # uint16_t
    "i": np.dtype("i4"),   # int32_t
    "I": np.dtype("u4"),   # uint32_t
    "l": np.dtype("i8"),   # int64_t
    "L": np.dtype("u8"),   # uint64_t
    "f": np.dtype("f4"),   # float32
    "d": np.dtype("f8"),   # float64
}

_REGION_RE = re.compile(
    r"^-R([-+0-9.eE]+)/([-+0-9.eE]+)/([-+0-9.eE]+)/([-+0-9.eE]+)$"
)
_INC_RE = re.compile(r"^-I([-+0-9.eE]+)/([-+0-9.eE]+)$")


# ---------------------------------------------------------------------------
# Parsing helpers for the catch_output_cmd-style "-R.../..." / "-I.../..."
# strings produced by ``gmt grdinfo -I-`` / ``gmt grdinfo -I``.
# ---------------------------------------------------------------------------

def _parse_region(par1: str) -> Tuple[float, float, float, float]:
    """Parse ``-Rw/e/s/n`` -> ``(w, e, s, n)``."""
    m = _REGION_RE.match(par1.strip())
    if m is None:
        raise ValueError(
            f"par1 does not match -R<w>/<e>/<s>/<n>: {par1!r}"
        )
    w, e, s, n = (float(v) for v in m.groups())
    return w, e, s, n


def _parse_inc(par2: str) -> Tuple[float, float]:
    """Parse ``-Ixinc/yinc`` -> ``(x_inc, y_inc)``."""
    m = _INC_RE.match(par2.strip())
    if m is None:
        raise ValueError(
            f"par2 does not match -I<xinc>/<yinc>: {par2!r}"
        )
    x_inc, y_inc = (float(v) for v in m.groups())
    return x_inc, y_inc


# ---------------------------------------------------------------------------
# Core array API
# ---------------------------------------------------------------------------

def gmt_xyz2grd_py(
    raw: bytes,
    *,
    region: Tuple[float, float, float, float],
    x_inc: float,
    y_inc: float,
    dtype: str = "f",
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Reshape a ``-ZTL<dtype> -r`` binary blob into a y-ascending grid.

    Parameters
    ----------
    raw : bytes-like
        Raw binary contents of the ``-ZTL<dtype>`` file (scanline order,
        top row first, left-to-right).
    region : (w, e, s, n)
        ``-R`` region.
    x_inc, y_inc : float
        ``-I`` increments.
    dtype : str
        GMT ``-Z`` type code (one of ``_Z_DTYPE`` keys).  Default ``"f"``
        (float32), matching ``-ZTLf``.

    Returns
    -------
    data : float32 ndarray, shape (ny, nx)
        y-ascending (row 0 = y_min), matching gmt_grd_io conventions.
    x, y : float64 ndarray
        Pixel-center coordinate arrays (node_offset=1 / ``-r``).

    Raises
    ------
    ValueError
        If the byte count of ``raw`` does not exactly equal
        ``nx * ny * itemsize`` (mirrors xyz2grd.c's
        "Found N records, but M was expected (aborting)!" hard error --
        no truncation, no padding).
    """
    if dtype not in _Z_DTYPE:
        raise ValueError(
            f"unsupported -Z type code {dtype!r}; "
            f"supported: {sorted(_Z_DTYPE)}"
        )
    np_dtype = _Z_DTYPE[dtype]

    w, e, s, n = (float(v) for v in region)
    if e <= w or n <= s:
        raise ValueError(
            f"region must have e>w and n>s, got w={w} e={e} s={s} n={n}"
        )
    x_inc = float(x_inc)
    y_inc = float(y_inc)
    if x_inc <= 0 or y_inc <= 0:
        raise ValueError(f"x_inc/y_inc must be positive, got {x_inc}/{y_inc}")

    # Pixel registration: nx = (e-w)/x_inc, ny = (n-s)/y_inc (NO +1).
    nx_f = (e - w) / x_inc
    ny_f = (n - s) / y_inc
    nx = int(round(nx_f))
    ny = int(round(ny_f))
    # xyz2grd.c / gmt_minmaxinc_verify tolerance: GMT_CONV4_LIMIT = 1e-4
    # of one increment.
    if abs(nx_f - nx) > 1.0e-4 or abs(ny_f - ny) > 1.0e-4:
        raise ValueError(
            f"region/increment mismatch: (e-w)/x_inc={nx_f!r}, "
            f"(n-s)/y_inc={ny_f!r} -- not integral within GMT_CONV4_LIMIT"
        )
    if nx < 1 or ny < 1:
        raise ValueError(f"computed non-positive grid dims: nx={nx} ny={ny}")

    raw = np.frombuffer(raw, dtype=np_dtype)
    n_expected = nx * ny
    if raw.size != n_expected:
        raise ValueError(
            f"Found {raw.size} records, but {n_expected} was expected "
            f"(aborting)! (nx={nx}, ny={ny}, dtype={np_dtype})"
        )

    # raw is Top-row-first, Left-to-right -> reshape gives row 0 = y_max.
    # Flip vertically to get y-ascending (row 0 = y_min), matching
    # gmt_grd_io / write_gmt_grd conventions.  GMT always stores grid data
    # as float32 internally regardless of -Z input type.
    grid_top_first = raw.reshape(ny, nx)
    data = np.ascontiguousarray(grid_top_first[::-1, :]).astype(np.float32)

    # Pixel-center coordinate arrays (node_offset=1).
    x = w + (np.arange(nx, dtype=np.float64) + 0.5) * x_inc
    y = s + (np.arange(ny, dtype=np.float64) + 0.5) * y_inc

    return data, x, y


# ---------------------------------------------------------------------------
# File-level convenience wrapper
# ---------------------------------------------------------------------------

def gmt_xyz2grd_py_file(
    in_path: str,
    out_path: str,
    *,
    par1: str,
    par2: str,
    ztype: str = "f",
    geographic: bool = False,
    title: str = "",
    history: str = "",
    description: str = "",
) -> None:
    """Read the raw ``-ZTL<ztype>`` binary file at ``in_path``, reshape per
    ``par1``/``par2`` (``-R``/``-I`` strings from ``gmt grdinfo -I-``/``-I``),
    and write ``out_path`` via ``gmt_grd_io.write_gmt_grd_from_increments``.

    Drop-in replacement for::

        gmt xyz2grd <in_path> -ZTL<ztype> -r <par1> <par2> -G<out_path>

    Parameters
    ----------
    in_path : str
        Path to the raw binary ``-ZTL<ztype>`` file (e.g. snaphu's
        ``unwrap.out`` / ``conncomp.out``).
    out_path : str
        Output ``.grd`` path.
    par1 : str
        ``-R<w>/<e>/<s>/<n>`` string (output of ``gmt grdinfo -I-``).
    par2 : str
        ``-I<xinc>/<yinc>`` string (output of ``gmt grdinfo -I``).
    ztype : str
        GMT ``-Z`` type code.  ``"f"`` for ``-ZTLf`` (unwrap.out, float32),
        ``"u"`` for ``-ZTLu`` (conncomp.out, uint8).
    geographic, title, history, description :
        Passed through to ``write_gmt_grd``.
    """
    # Local import -- keep the array API free of netCDF4 hard dependency.
    from gmt_grd_io import write_gmt_grd_from_increments

    region = _parse_region(par1)
    x_inc, y_inc = _parse_inc(par2)

    with open(in_path, "rb") as fh:
        raw = fh.read()

    data, x, y = gmt_xyz2grd_py(
        raw, region=region, x_inc=x_inc, y_inc=y_inc, dtype=ztype,
    )

    w = region[0]
    s = region[2]
    if not history:
        history = (
            f"gmt xyz2grd {in_path} -ZTL{ztype} -r {par1} {par2} -G{out_path}"
        )

    write_gmt_grd_from_increments(
        out_path, data,
        x_min=w, y_min=s, x_inc=x_inc, y_inc=y_inc,
        node_offset=1, geographic=geographic,
        title=title, history=history, description=description,
    )
