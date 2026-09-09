#!/usr/bin/env python3
"""blockmedian_wrapper — drop-in for file-based `gmt blockmedian` calls.

Bridges csh-style subprocess calls
``gmt blockmedian <in.xyz> -R<region> -I<inc> -r [-bo3d] > <out>``
to the in-process ``utils/gmt_blockmedian_py.blockmedian`` port
(byte-identical to ``gmt blockmedian -r`` on real data; Mira #25/#67).

Only the pixel-registered (``-r``) path is supported — that is the only
mode the gmtsar pipeline uses and the only mode the port is parity-tested
against.

Input formats
-------------
* ``in_binary=None`` (default): ASCII ``x y z`` (whitespace-separated),
  as produced by the ``awk`` pre-steps in align_tops / tide_correction.
* ``in_binary=3`` : native-endian 3×float64 stream (``-bi3d``).

Output formats
--------------
* ``out_binary=3`` : native-endian 3×float64 stream (``gmt ... -bo3d``).
  Byte-identical to gmt's ``-bo3d`` output (the port returns the same
  (median_x, median_y, median_z) rows in the same raster order).
* ``out_binary=None`` : ASCII, written with ``%.12g`` TAB-separated to
  mirror gmt's default ``FORMAT_FLOAT_OUT=%.12g``.

Env-gate
--------
``GMTSAR_BLOCKMEDIAN_PY`` (default ``"1"`` — in-process port). Set to
``"0"`` to force the ``gmt blockmedian`` subprocess (A/B parity debugging
or hosts without Numba). The subprocess fallback rebuilds the exact gmt
CLI the wrapper replaced.
"""
from __future__ import annotations

import os
import subprocess
from typing import Optional, Tuple

import numpy as np

# Must import at module load so the gate can be read per-call.
from gmt_blockmedian_py import blockmedian as _blockmedian_py


def _py_enabled() -> bool:
    return os.environ.get("GMTSAR_BLOCKMEDIAN_PY", "1") == "1"


def _parse_region(region: str) -> Tuple[float, float, float, float]:
    parts = region.split("/")
    if len(parts) != 4:
        raise ValueError(f"region must be w/e/s/n, got {region!r}")
    return tuple(float(p) for p in parts)  # type: ignore[return-value]


def _parse_inc(inc: str) -> Tuple[float, float]:
    parts = inc.split("/")
    if len(parts) == 1:
        v = float(parts[0])
        return v, v
    if len(parts) == 2:
        return float(parts[0]), float(parts[1])
    raise ValueError(f"inc must be dx or dx/dy, got {inc!r}")


def blockmedian(
    in_path: str,
    out_path: str,
    *,
    region: str,
    inc: str,
    pixel_reg: bool = True,
    in_binary: Optional[int] = None,
    out_binary: Optional[int] = None,
) -> None:
    """Run blockmedian on ``in_path`` and write the result to ``out_path``.

    Mirrors the csh ``gmt blockmedian`` CLI; see module docstring.
    ``GMTSAR_BLOCKMEDIAN_PY=0`` falls back to the gmt subprocess.
    """
    if not pixel_reg:
        # Only -r is parity-tested; refuse silently-wrong gridline output.
        raise NotImplementedError(
            "blockmedian_wrapper supports only pixel registration (-r)")

    if _py_enabled():
        _blockmedian_py_path(
            in_path, out_path, region=region, inc=inc,
            in_binary=in_binary, out_binary=out_binary)
    else:
        _blockmedian_subprocess(
            in_path, out_path, region=region, inc=inc,
            in_binary=in_binary, out_binary=out_binary)


def _read_xyz(in_path: str, in_binary: Optional[int]) -> np.ndarray:
    if in_binary == 3:
        a = np.fromfile(in_path, dtype=np.float64)
        if a.size % 3 != 0:
            raise ValueError(
                f"{in_path}: binary -bi3d stream not a multiple of 3 doubles")
        return a.reshape(-1, 3)
    if in_binary is not None:
        raise NotImplementedError(
            f"blockmedian_wrapper in_binary={in_binary} unsupported (only 3)")
    a = np.loadtxt(in_path, dtype=np.float64, ndmin=2)
    if a.shape[1] < 3:
        raise ValueError(f"{in_path}: need >=3 columns, got {a.shape[1]}")
    return np.ascontiguousarray(a[:, :3])


def _blockmedian_py_path(in_path, out_path, *, region, inc,
                         in_binary, out_binary):
    xyz = _read_xyz(in_path, in_binary)
    out = _blockmedian_py(
        xyz, _parse_region(region), _parse_inc(inc), pixel_reg=True)
    out = np.ascontiguousarray(out, dtype=np.float64)
    if out_binary == 3:
        out.tofile(out_path)
    elif out_binary is None:
        # Mirror gmt's default ASCII: %.12g, TAB-separated, LF-terminated.
        with open(out_path, "w") as f:
            for r in out:
                f.write("%.12g\t%.12g\t%.12g\n" % (r[0], r[1], r[2]))
    else:
        raise NotImplementedError(
            f"blockmedian_wrapper out_binary={out_binary} unsupported (3 or None)")


def _blockmedian_subprocess(in_path, out_path, *, region, inc,
                            in_binary, out_binary):
    """Rebuild the gmt blockmedian CLI exactly (A/B fallback path)."""
    cmd = ["gmt", "blockmedian", in_path, f"-R{region}", f"-I{inc}", "-r"]
    if in_binary == 3:
        cmd.append("-bi3d")
    if out_binary == 3:
        cmd.append("-bo3d")
    with open(out_path, "wb") as fout:
        res = subprocess.run(cmd, stdout=fout, stderr=subprocess.PIPE,
                             check=False)
    if res.returncode != 0:
        raise RuntimeError(
            f"gmt blockmedian subprocess failed (rc={res.returncode})\n"
            f"  cmd: {' '.join(cmd)}\n  stderr: {res.stderr.decode(errors='replace')}"
        )


__all__ = ["blockmedian"]
