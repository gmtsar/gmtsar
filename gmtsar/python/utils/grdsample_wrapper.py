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

  * If ``ref_grd`` is given (csh ``-R<grdfile>``), the increments AND
    registration of the output are taken from that .grd; the output REGION
    is the ref grid's region CLIPPED to the input grid's data extent and
    SNAPPED to the ref grid's node lattice — exactly what
    ``gmt grdsample -R<grdfile>`` does. (Earlier versions reconstructed
    the region from read_gmt_grd x/y vectors and re-derived the dims by
    rounding ``(xmax-xmin)/inc``, which produced an output one row/col off
    when the ref grid overhung the input or registrations differed. Fixed
    by reading the authoritative geometry via ``gmt grdinfo -C`` and
    replicating gmt's clip-snap region logic; see ``_clip_snap_region`` /
    ``_ref_geometry``.)
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


class _RefGeom:
    """Authoritative geometry of a reference grid, read from ``gmt grdinfo -C``.

    ``gmt grdsample -R<grdfile>`` takes the OUTPUT region, increments, AND
    registration directly from that grid's header — it does NOT re-derive
    dims by rounding ``(xmax-xmin)/inc``. Reconstructing those values from
    the read_gmt_grd x/y vectors (``dx = x[1]-x[0]``, region = node-extent)
    is lossy: float drift in the reconstructed inc, or a registration
    mismatch between the in-grid and the ref-grid, can make the port's
    ``round((xhi-xlo)/inc)+1-reg`` land one row/col off → output shape
    differs from ``gmt grdsample -R<grdfile>`` by 1. (Diagnosed bug.)

    So we read the EXACT n_columns/n_rows/registration from grdinfo and
    pin the port's output dims to them — guaranteeing the same shape and
    registration gmt would produce.
    """

    __slots__ = ("xmin", "xmax", "ymin", "ymax", "x_inc", "y_inc",
                 "n_columns", "n_rows", "node_offset")

    def __init__(self, xmin, xmax, ymin, ymax, x_inc, y_inc,
                 n_columns, n_rows, node_offset):
        self.xmin = xmin
        self.xmax = xmax
        self.ymin = ymin
        self.ymax = ymax
        self.x_inc = x_inc
        self.y_inc = y_inc
        self.n_columns = n_columns
        self.n_rows = n_rows
        self.node_offset = node_offset

    @property
    def region(self) -> Tuple[float, float, float, float]:
        return (self.xmin, self.xmax, self.ymin, self.ymax)


def _ref_geometry(grd_path: str) -> _RefGeom:
    """Read the ref grid's authoritative geometry via ``gmt grdinfo -C``.

    grdinfo ``-C`` is whitespace-delimited:
      1=name 2=x_min 3=x_max 4=y_min 5=y_max 6=z_min 7=z_max
      8=x_inc 9=y_inc 10=n_columns 11=n_rows 12=registration[ 13=...]

    For a PIXEL-registered grid, grdinfo's x_min/x_max ARE the cell-edge
    (boundary) extent — exactly the region gmt grdsample uses. So we can
    feed these straight to the port.
    """
    res = subprocess.run(["gmt", "grdinfo", "-C", grd_path],
                         capture_output=True, text=True, check=False)
    if res.returncode != 0:
        raise RuntimeError(
            f"gmt grdinfo -C failed on {grd_path} (rc={res.returncode})\n"
            f"  stderr: {res.stderr}"
        )
    f = res.stdout.split()
    if len(f) < 12:
        raise RuntimeError(
            f"gmt grdinfo -C produced too few fields for {grd_path}: "
            f"{res.stdout!r}"
        )
    return _RefGeom(
        xmin=float(f[1]), xmax=float(f[2]),
        ymin=float(f[3]), ymax=float(f[4]),
        x_inc=float(f[7]), y_inc=float(f[8]),
        n_columns=int(round(float(f[9]))),
        n_rows=int(round(float(f[10]))),
        node_offset=int(round(float(f[11]))),
    )


def _clip_snap_region(ref: "_RefGeom", inp: "_RefGeom",
                      x_inc: float, y_inc: float
                      ) -> Tuple[float, float, float, float]:
    """Replicate gmt grdsample's `-R<grdfile>` output-region computation.

    gmt takes the ref grid's region and increment, CLIPS it to the input
    grid's data extent, and SNAPS the clipped bounds onto the ref grid's
    node lattice (origin = ref_min, step = inc). The result is the largest
    sub-region of the ref lattice that fits entirely inside the input.

    Verified against gmt 6.4:
      * ref overhangs input by part of a cell → that row/col is dropped
        (raln -R corr: 18573 → 18572 rows).
      * input bound not aligned to ref lattice → bound snapped inward
        (in x:103/403, ref inc 5 origin 50 → out 105/400).
    """
    import math
    eps = 1e-3  # cell fraction tolerance — absorb float round-off in span/inc

    def _snap(lo_ref, hi_ref, n_ref, lo_in, hi_in, inc):
        # Work in INTEGER ref-lattice cell indices [0 .. n_ref], anchored at
        # lo_ref. n_ref is the ref grid's authoritative node/cell count, so
        # index n_ref maps exactly to hi_ref — no float span/inc ratio.
        # i_lo = first lattice index >= in_lo (clip the left/bottom overhang)
        # i_hi = last lattice index <= in_hi (clip the right/top overhang)
        if lo_in <= lo_ref + eps * inc:
            i_lo = 0
        else:
            i_lo = math.ceil((lo_in - lo_ref) / inc - eps)
        if hi_in >= hi_ref - eps * inc:
            i_hi = n_ref
        else:
            i_hi = math.floor((hi_in - lo_ref) / inc + eps)
        i_lo = max(0, min(i_lo, n_ref))
        i_hi = max(0, min(i_hi, n_ref))
        out_lo = hi_ref if i_lo == n_ref else lo_ref + i_lo * inc
        out_hi = hi_ref if i_hi == n_ref else lo_ref + i_hi * inc
        return out_lo, out_hi

    # For pixel registration the lattice has n_columns cells (index 0..n);
    # for gridline it has n_columns-1 intervals (index 0..n-1). Either way
    # the index that maps to the upper bound is "number of inc steps from
    # the lower bound" = round((hi-lo)/inc).
    nref_x = int(round((ref.xmax - ref.xmin) / x_inc))
    nref_y = int(round((ref.ymax - ref.ymin) / y_inc))
    out_xmin, out_xmax = _snap(ref.xmin, ref.xmax, nref_x,
                               inp.xmin, inp.xmax, x_inc)
    out_ymin, out_ymax = _snap(ref.ymin, ref.ymax, nref_y,
                               inp.ymin, inp.ymax, y_inc)
    return (out_xmin, out_xmax, out_ymin, out_ymax)


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

    ref_geom = None
    expect_geom = None  # (n_columns, n_rows, registration) gmt would emit
    if ref_grd is not None:
        # `-R<grdfile>`: take inc + registration from the ref grid's header,
        # but the OUTPUT REGION is the ref region CLIPPED to the input grid's
        # data extent and SNAPPED to the ref grid's node lattice — this is
        # exactly what `gmt grdsample -R<grdfile>` does (verified against
        # gmt 6.4 on real merge-stage grids: ref region that overhangs the
        # input by part of a cell drops that row/col). The naive "use the
        # ref grid's region/dims verbatim" produced an off-by-one when the
        # ref overhangs the input (e.g. raln -R corr: ref nrow 18573 but
        # gmt emits 18572). See _ref_geometry docstring.
        ref_geom = _ref_geometry(ref_grd)
        in_geom = _ref_geometry(in_grd)
        if new_dx is None:
            new_dx = ref_geom.x_inc
        if new_dy is None:
            new_dy = ref_geom.y_inc
        if out_reg is None:
            out_reg = (ref_geom.node_offset == 1)
        if new_region is None:
            new_region = _clip_snap_region(ref_geom, in_geom, new_dx, new_dy)
        # Predict gmt's output dims from the snapped region (Rule 1 guard).
        _reg = 1 if out_reg else 0
        _ncol = int(round((new_region[1] - new_region[0]) / new_dx)) + 1 - _reg
        _nrow = int(round((new_region[3] - new_region[2]) / new_dy)) + 1 - _reg
        expect_geom = (_ncol, _nrow, _reg)

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

    # 3a. When the region came from a `-R<grdfile>` ref grid, the output
    #     MUST have the SAME shape/registration gmt grdsample would emit
    #     (the ref grid's exact n_columns/n_rows/registration). If the
    #     port's region+inc rounding lands off-by-one, fail loudly
    #     (Rule 1: no silent off-by-one shape divergence downstream).
    if expect_geom is not None:
        got = (z_out.shape[1], z_out.shape[0], 1 if out_reg else 0)
        if got != expect_geom:
            raise RuntimeError(
                "grdsample_wrapper: in-process output geometry "
                f"(n_columns,n_rows,reg)={got} does not match the "
                f"gmt grdsample -R<refgrid> geometry {expect_geom} for "
                f"ref_grd={ref_grd!r}. This is the registration/off-by-one "
                "bug the clip-snap fix targets — set GMTSAR_GRDSAMPLE_PY=0 "
                "to fall back."
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
