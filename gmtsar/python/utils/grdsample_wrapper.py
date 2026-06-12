#!/usr/bin/env python3
"""grdsample_wrapper — drop-in replacement for `gmt grdsample` subprocess calls.

Bridges the existing csh-style pipeline that subprocess-calls
``gmt grdsample <in> [-R<grid>|-R<region>] [-I<inc>] [-r] -G<out>`` over to
the in-process ``utils/gmt_grdsample_py.gmt_grdsample_py`` port (committed
v2.1.7, byte-identical to gmt C, ~1.95× faster).

Public API
----------
``grdsample(in_grd, out_grd, *, ref_grd=None, region=None, x_inc=None,
y_inc=None, interp='bicubic', pixel_reg=None, threshold=0.5)`` —
mirrors the gmt CLI option semantics:

  * If ``ref_grd`` is given (csh ``-R<grdfile>``), the region, increments
    AND registration of the output are taken from that .grd unless an
    explicit ``x_inc``/``y_inc``/``region`` overrides.
  * If only ``region`` is given (csh ``-R<w>/<e>/<s>/<n>``) without ``x_inc``,
    the input's increments are reused (gmt grdsample default).
  * Registration: output inherits the input's registration unless
    ``pixel_reg`` is explicitly set (gmt grdsample CLI default behavior).
  * ``interp`` defaults to ``'bicubic'`` — this is gmt grdsample's CLI
    default (``-nc``), NOT bilinear. Existing csh callers do not pass
    ``-n`` so they get bicubic; the wire-in must match.

Env-gate
--------
``GMTSAR_GRDSAMPLE_PY`` controls which path is used.

* ``GMTSAR_GRDSAMPLE_PY=1`` (DEFAULT — in-process port). The port is
  byte-identical to gmt grdsample on real production data (verified on
  ALOS_haiti landmask_ra.grd, 9.77M cells, 38% NaN: max|py-gmt| = 0)
  AND faster than gmt C single-thread on both shape families:

    - ALOS_haiti landmask (9.77M cells, 38% NaN, 4×4 bicubic):
        py 452 ms vs gmt 1018 ms  → 2.25× faster (Mira #65)
    - iono-shaped (200k → 800k, no NaN, 4×4 bicubic):
        py 21 ms vs gmt 189 ms    → 9.2× faster

  Mira #65 replaced the per-block NaN slow-path
  (np.isnan().any() + np.where rebuild on every (jj,ii) corner × tile)
  with a single fused @njit single-thread kernel
  (`gmt_grdsample_py._gather_accumulate`) — same per-pixel accumulation
  order, byte-id output, no allocations in the hot loop.

* ``GMTSAR_GRDSAMPLE_PY=0``: use the gmt subprocess fallback. Same
  output bytes; useful for A/B parity debugging or on hosts where Numba
  is unavailable (the port itself falls back to pure-numpy gather there,
  which is slower than gmt C on NaN-heavy bicubic — set the env var to 0
  in that case).

Per project_rules.md Rule 10 carve-out: byte-identical AND faster than
gmt C on real data → port qualifies for the carve-out (Mira #65 audit).

The subprocess fallback (env=0) rebuilds the exact gmt CLI the wrapper
would have replaced — same flags, same argument order — so the env-gate
is a clean A/B switch.
"""
from __future__ import annotations

import os
import subprocess
from typing import Optional, Tuple

# These imports must succeed even when the env-gate is OFF — the module
# may be imported at module-load time and the gate read per-call.
from gmt_grdsample_py import gmt_grdsample_py
from gmt_grd_io import read_gmt_grd, write_gmt_grd


def _py_enabled() -> bool:
    """In-process port is ON by default — see module docstring.

    Mira #65: the @njit per-pixel gather kernel made the port
    byte-id AND faster than gmt C on both real workloads
    (ALOS_haiti landmask 2.25× faster, iono 9.2× faster). The carve-out
    in project_rules.md Rule 10 now applies. Default flipped to "1".

    Set ``GMTSAR_GRDSAMPLE_PY=0`` to force the subprocess fallback
    (A/B parity debugging, or on hosts without Numba where the pure-
    numpy gather is slower than gmt C on NaN-heavy 4×4 bicubic).
    """
    return os.environ.get("GMTSAR_GRDSAMPLE_PY", "1") == "1"


def _grd_region(grd_path: str) -> Tuple[float, float, float, float]:
    """Read (xmin, xmax, ymin, ymax) from a .grd file via read_gmt_grd.

    For a pixel-registered grid, the returned region matches gmt's
    convention: x_min = x[0] - dx/2, x_max = x[-1] + dx/2.
    """
    _data, x, y, info = read_gmt_grd(grd_path)
    dx = float(x[1] - x[0]) if len(x) > 1 else 0.0
    dy = float(y[1] - y[0]) if len(y) > 1 else 0.0
    off = 0.5 if info.get("node_offset", 0) == 1 else 0.0
    return (float(x[0]) - off * dx,
            float(x[-1]) + off * dx,
            float(y[0]) - off * dy,
            float(y[-1]) + off * dy)


def _grd_inc_reg(grd_path: str) -> Tuple[float, float, int]:
    """Return (x_inc, y_inc, node_offset) of an existing .grd."""
    _data, x, y, info = read_gmt_grd(grd_path)
    dx = float(x[1] - x[0]) if len(x) > 1 else 0.0
    dy = float(y[1] - y[0]) if len(y) > 1 else 0.0
    return dx, dy, int(info.get("node_offset", 0))


def grdsample(
    in_grd: str,
    out_grd: str,
    *,
    ref_grd: Optional[str] = None,
    region: Optional[Tuple[float, float, float, float]] = None,
    x_inc: Optional[float] = None,
    y_inc: Optional[float] = None,
    interp: str = "bicubic",
    pixel_reg: Optional[bool] = None,
    threshold: float = 0.5,
) -> None:
    """Resample ``in_grd`` and write the result to ``out_grd``.

    Mirrors the csh ``gmt grdsample`` CLI; see module docstring for argument
    semantics. Env-gate ``GMTSAR_GRDSAMPLE_PY=0`` falls back to the
    subprocess for A/B parity debugging.
    """
    if _py_enabled():
        _grdsample_py(
            in_grd, out_grd,
            ref_grd=ref_grd, region=region,
            x_inc=x_inc, y_inc=y_inc,
            interp=interp, pixel_reg=pixel_reg, threshold=threshold,
        )
    else:
        _grdsample_subprocess(
            in_grd, out_grd,
            ref_grd=ref_grd, region=region,
            x_inc=x_inc, y_inc=y_inc,
            interp=interp, pixel_reg=pixel_reg,
        )


def _grdsample_py(in_grd, out_grd, *, ref_grd, region, x_inc, y_inc,
                  interp, pixel_reg, threshold):
    # 1. Load input grid + metadata.
    data, x_in, y_in, info_in = read_gmt_grd(in_grd)
    in_off = int(info_in.get("node_offset", 0))

    # 2. Derive region/inc/registration: explicit args win over ref_grd,
    #    ref_grd wins over input defaults. (gmt CLI semantics.)
    new_region = region
    new_dx = x_inc
    new_dy = y_inc
    out_reg = pixel_reg

    if ref_grd is not None:
        # `-R<grdfile>`: take region+inc+registration from this grid.
        ref_region = _grd_region(ref_grd)
        ref_dx, ref_dy, ref_off = _grd_inc_reg(ref_grd)
        if new_region is None:
            new_region = ref_region
        if new_dx is None:
            new_dx = ref_dx
        if new_dy is None:
            new_dy = ref_dy
        if out_reg is None:
            out_reg = (ref_off == 1)

    # Final registration default: inherit input's (gmt grdsample CLI default).
    if out_reg is None:
        out_reg = (in_off == 1)

    # Geographic? Inherit from input.
    geographic = bool(info_in.get("geographic", False))

    # 3. Run the in-process port.
    z_out, x_out, y_out, info_out = gmt_grdsample_py(
        data, x_in, y_in,
        new_x_inc=new_dx, new_y_inc=new_dy,
        new_region=new_region,
        interp=interp,
        pixel_reg=bool(out_reg),
        in_pixel_reg=(in_off == 1),
        threshold=threshold,
    )

    # 4. Write the result. Preserve registration; tag history so
    #    downstream `grdinfo` shows which path produced the file.
    write_gmt_grd(
        out_grd, z_out, x_out, y_out,
        node_offset=1 if out_reg else 0,
        geographic=geographic,
        title="",
        history=f"gmt_grdsample_py {os.path.basename(in_grd)} "
                f"-> {os.path.basename(out_grd)} (interp={interp})",
        description="",
    )


def _grdsample_subprocess(in_grd, out_grd, *, ref_grd, region,
                          x_inc, y_inc, interp, pixel_reg):
    """Rebuild the gmt grdsample CLI exactly (A/B fallback path)."""
    cmd = ["gmt", "grdsample", in_grd]
    if ref_grd is not None:
        cmd.append(f"-R{ref_grd}")
    elif region is not None:
        cmd.append(f"-R{region[0]}/{region[1]}/{region[2]}/{region[3]}")
    if x_inc is not None:
        dy = y_inc if y_inc is not None else x_inc
        cmd.append(f"-I{x_inc}/{dy}")
    interp_flag = {"bicubic": "-nc", "bilinear": "-nl",
                   "bspline": "-nb", "nearest": "-nn"}.get(interp, "-nc")
    cmd.append(interp_flag)
    if pixel_reg is True:
        cmd.append("-rp")
    elif pixel_reg is False:
        cmd.append("-rg")
    cmd.append(f"-G{out_grd}")
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode != 0:
        raise RuntimeError(
            f"gmt grdsample subprocess failed (rc={res.returncode})\n"
            f"  cmd: {' '.join(cmd)}\n  stderr: {res.stderr}"
        )


__all__ = ["grdsample"]
