#!/usr/bin/env python3
"""gmt_triangulate_py — in-process replacement for ``gmt triangulate -G``.

Verbatim-algorithm port (per project_rules.md Rule 7) of the ONLY mode
`dem2topo_ra` uses:

    gmt triangulate <xyz> -R<region> -I<xinc>/<yinc> -bi3d -G<outgrid> -r [-V]

i.e. Delaunay triangulation of scattered ``(x, y, z)`` points followed by
**linear** (planar, per-triangle) interpolation onto a regular grid,
NaN outside the convex hull (GMT's ``-E`` default). No ``-Q`` (Renka's
C1-continuous scheme), no ``-D`` (derivative grids), no ``-C`` (CURVE
propagated-uncertainty mode) — none of those flags appear at the call
sites (``utils/dem2topo_ra:772,840``), so they are NOT ported here; using
this module with any of those semantics would silently produce the wrong
answer (Rule 1 — no fallback).

Algorithm
---------
GMT is compiled against **Jonathan Shewchuk's Triangle** library
(confirmed via ``strings libgmt.so`` — see AUDIT note below), a
purpose-built incremental 2-D Delaunay triangulator. This port uses
``scipy.spatial.Delaunay`` (Qhull's ``qdelaunay``, lifting points to a
paraboloid in 3-D and computing the convex hull) — a different
ALGORITHM, but for points in general position (no exact co-circular
ties) the Delaunay triangulation of a point set is **unique**, so the
two implementations must produce the same triangle set and therefore
the same linear-interpolation surface. This is verified empirically
below, not assumed (Pattern 3 in the charter — never trust a
library-name match without a real-data check).

Grid interpolation within a triangle is barycentric-linear, computed
from Qhull's precomputed affine transform per simplex — this is exactly
GMT's own linear interpolation (``triangulate.c``: each output node's z
is barycentric-interpolated from its containing triangle's 3 vertices).
Points outside the convex hull get the GMT default empty-node value
(NaN, ``-E`` not used at either call site).

Parity evidence (Mira, 2026-07-12)
-----------------------------------
Real data: ``work/python_test/RS2_SLC_Hawaii/topo/temp.rat`` (964,812
points, the actual ``dem2topo_ra`` mode=1 PRF>=1000 input for that
case), region ``0/3416/0/5744``, ``-I2/4 -r`` (the exact params
`dem2topo_ra` line 840 uses for that case):

    gmt triangulate temp.rat -R0/3416/0/5744 -I2/4 -bi3d -Gref.grd -r

vs this module on the SAME input bytes: **max |diff| = 0.0 over
2,452,676 valid (non-NaN) nodes; 0 NaN-mask mismatches out of
2,452,688 total nodes.** Bit-identical (float32 ULP) on real full-scale
data. See ``bin_py/tests/test_gmt_triangulate_py.py::TestRealRS2Hawaii``.

Performance verdict — DOES NOT PASS Rule 7's speed gate
---------------------------------------------------------
Single-threaded (``taskset -c 0``), same real 964,812-point input:

    gmt triangulate (C, Shewchuk's Triangle):   ~2.1-2.3 s  (build+grid+write)
    this module, scipy.spatial.Delaunay build:  ~9.4-9.9 s  (build alone)
    this module, find_simplex (query) + interp: ~5.0 s
    this module TOTAL:                          ~14.9-15.0 s

Python is **~6.5x SLOWER**, not faster. Root cause: Qhull's Delaunay
(``qdelaunay``, general-dimension convex-hull-in-lifted-space algorithm)
has a much larger constant factor than Shewchuk's Triangle, which is a
purpose-built, cache-friendly incremental 2-D Delaunay algorithm — this
is a genuine algorithmic-implementation gap, not a vectorization
opportunity. Two independent optimization attempts confirmed this is not
fixable in pure Python/numpy:

    1. ``scipy.spatial.Delaunay`` qhull_options tuning (``Qz``/``Qx``/
       bare ``Qbb Qc``): 9.4-12.2 s, no meaningful improvement — the
       triangulation call is a single opaque C invocation, nothing to
       vectorize.
    2. ``matplotlib.tri.Triangulation`` (different C++ Delaunay impl):
       6.9 s — faster than scipy but STILL ~3x slower than the full gmt
       triangulate C pipeline.

Per the "when Py can't catch C" playbook: this is a directly-linked,
purpose-built C library (Shewchuk's Triangle) that Python has no numpy
vectorization answer for. The only remaining lever is a C-extension
(cffi/ctypes binding to Shewchuk's Triangle, or GMT's own Delaunay
routine) — introducing a build-system dependency, which per the
stop-and-ask triggers requires explicit user sign-off before attempting.

**Consequence per Rule 7 (both gates required to wire ON by default):**
bit-identical ✔, equal-or-faster ✘ (6.5x SLOWER). This module is wired
in ONLY behind ``GMTSAR_TRIANGULATE_PY=1``, default **OFF**. Do not
flip the default without either (a) a C-extension speedup, or (b) an
explicit user decision to trade wall-clock for a pure-Python dependency
chain (removes the GMT `triangulate` binary as a runtime dependency at
this one call site) despite being slower.
"""
from __future__ import annotations

from typing import Optional, Tuple

import numpy as np
from scipy.spatial import Delaunay


def gmt_triangulate_grid(
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
    *,
    region: Tuple[float, float, float, float],
    xinc: float,
    yinc: float,
    pixel_reg: bool = True,
    empty_value: float = np.nan,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Delaunay-triangulate ``(x, y, z)`` and linearly interpolate onto a grid.

    Mirrors ``gmt triangulate <xyz> -R<region> -I<xinc>/<yinc> -G<out> [-r]``
    with no other flags (the only invocation dem2topo_ra uses).

    Parameters
    ----------
    x, y, z : 1-D arrays, same length
        Scattered input points (range, azimuth, elevation for the
        dem2topo_ra caller).
    region : (west, east, south, north)
        Same semantics as GMT's ``-R``.
    xinc, yinc : float
        Grid spacing, same semantics as GMT's ``-I``.
    pixel_reg : bool
        True (default; matches ``-r`` at both call sites) → node
        centers offset by half a cell from the region edges.
        False → gridline registration (nodes ON the region edges).
    empty_value : float
        Value for grid nodes outside the convex hull. GMT default is
        NaN (``-E`` not used at either call site) — do NOT change this
        silently; a caller that needs ``-E<val>`` must pass it
        explicitly (Rule 1: no silent fallback).

    Returns
    -------
    (z_grid, qx, qy) : z_grid shape (ny, nx) float32, qx/qy 1-D float64
        coordinate arrays. ``z_grid[0, :]`` corresponds to ``qy[0]``
        (south-most row), matching ``gmt_grd_io.write_gmt_grd``'s
        "y ascending" convention.

    Raises
    ------
    ValueError
        Non-finite input coordinates, mismatched array lengths, or a
        degenerate (< 3 point / collinear) input that Qhull cannot
        triangulate — these must be hard failures (Rule 3), not
        silently-empty output.
    """
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    z = np.asarray(z, dtype=np.float64)
    if not (x.shape == y.shape == z.shape) or x.ndim != 1:
        raise ValueError(
            f"x/y/z must be 1-D arrays of equal length; got "
            f"{x.shape}, {y.shape}, {z.shape}"
        )
    if x.size < 3:
        raise ValueError(f"need >= 3 points for a Delaunay triangulation, got {x.size}")
    if not (np.isfinite(x).all() and np.isfinite(y).all()):
        raise ValueError("x/y contain non-finite values")

    west, east, south, north = region
    if not (east > west and north > south):
        raise ValueError(f"invalid region {region}: need east>west and north>south")
    if xinc <= 0 or yinc <= 0:
        raise ValueError(f"xinc/yinc must be > 0, got {xinc}/{yinc}")

    nx = int(round((east - west) / xinc))
    ny = int(round((north - south) / yinc))
    if nx <= 0 or ny <= 0:
        raise ValueError(
            f"region {region} with I{xinc}/{yinc} yields non-positive "
            f"grid dims nx={nx} ny={ny}"
        )

    if pixel_reg:
        qx = west + (np.arange(nx) + 0.5) * xinc
        qy = south + (np.arange(ny) + 0.5) * yinc
    else:
        qx = west + np.arange(nx + 1) * xinc
        qy = south + np.arange(ny + 1) * yinc
        nx, ny = qx.size, qy.size

    # Delaunay triangulation of the scattered points (Qhull qdelaunay).
    # This is the ONE call that cannot be vectorized further in Python —
    # see module docstring "Performance verdict".
    tri = Delaunay(np.column_stack([x, y]))

    QX, QY = np.meshgrid(qx, qy)
    qpts = np.column_stack([QX.ravel(), QY.ravel()])

    simp = tri.find_simplex(qpts)

    # Barycentric-linear interpolation via Qhull's precomputed affine
    # transform per simplex (same math as GMT's own linear interpolant).
    T = tri.transform[np.where(simp >= 0, simp, 0)]
    Tinv = T[:, :2, :]
    r = qpts - T[:, 2, :]
    b0 = np.einsum("ijk,ik->ij", Tinv, r)
    bary = np.c_[b0, 1.0 - b0.sum(axis=1)]

    verts = tri.simplices[np.where(simp >= 0, simp, 0)]
    zval = np.einsum("ij,ij->i", bary, z[verts])
    zval = np.where(simp >= 0, zval, empty_value)

    z_grid = zval.reshape(ny, nx).astype(np.float32)
    return z_grid, qx, qy


def gmt_triangulate_py_file(
    xyz_path: str,
    out_grd_path: str,
    *,
    region: Tuple[float, float, float, float],
    xinc: float,
    yinc: float,
    pixel_reg: bool = True,
) -> None:
    """File-to-file wrapper mirroring
    ``gmt triangulate <xyz_path> -R<region> -I<xinc>/<yinc> -bi3d -G<out_grd_path> -r``.

    ``xyz_path`` must be raw little-endian binary triples of float64
    (``-bi3d``, GMTSAR's native ``temp.rat``/``mean.rat`` layout) — NOT
    ASCII. A file whose byte count is not a multiple of 24 raises
    (Rule 3/4: hard, loud failure on malformed input, never a silent
    truncated read).
    """
    from gmt_grd_io import write_gmt_grd

    raw = np.fromfile(xyz_path, dtype="<f8")
    if raw.size % 3 != 0:
        raise ValueError(
            f"{xyz_path}: {raw.size} float64 values is not a multiple of 3 "
            f"(expected -bi3d x,y,z triples)"
        )
    pts = raw.reshape(-1, 3)
    z_grid, qx, qy = gmt_triangulate_grid(
        pts[:, 0], pts[:, 1], pts[:, 2],
        region=region, xinc=xinc, yinc=yinc, pixel_reg=pixel_reg,
    )
    write_gmt_grd(
        out_grd_path, z_grid, qx, qy,
        node_offset=1 if pixel_reg else 0,
        history=(
            f"gmt_triangulate_py -R{region[0]}/{region[1]}/{region[2]}/{region[3]} "
            f"-I{xinc}/{yinc}" + (" -r" if pixel_reg else "")
        ),
    )
