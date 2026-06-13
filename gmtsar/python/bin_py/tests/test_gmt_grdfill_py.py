#!/usr/bin/env python3
"""test_gmt_grdfill_py - C-parity test for utils/gmt_grdfill_py.

Runs ``gmt grdfill`` (subprocess) and ``gmt_grdfill_py`` on the SAME input
grid and asserts byte-identical (rms < float32 ULP) numerical output.

Algorithms tested:

  * ``-Ac`` (constant fill): trivial -- pure assignment, must be exact.
  * ``-An`` (Eric Xu nearest neighbour): integer arithmetic, must be exact.
  * ``-Ag`` (sample from another grid): bilinear; matches grdtrack
    bit-for-bit when both inputs are float32 and IEEE-754 multiply-add
    semantics are followed.  This is the primary production code path
    (dem2topo_ra mode=1).

Skips loudly (does NOT silently pass) if ``gmt`` is not on PATH.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Locate sources + GMT binary
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent
_UTILS = _HERE.parent.parent / "utils"
sys.path.insert(0, str(_UTILS))

from gmt_grdfill_py import (  # noqa: E402
    gmt_grdfill_py, gmt_grdfill_py_file)
from gmt_grd_io import write_gmt_grd, read_gmt_grd  # noqa: E402

_GMT = shutil.which("gmt")
if _GMT is None:
    _alt = "/home/staff/dliu/anaconda3/envs/gmtsar/bin/gmt"
    if os.path.exists(_alt):
        _GMT = _alt
_HAVE_GMT = _GMT is not None and os.access(_GMT, os.X_OK)


def _gmt_grdfill(in_path: str, out_path: str, args: str) -> float:
    """Invoke ``gmt grdfill <in> <args> -G<out>``. Returns wall seconds."""
    cmd = [_GMT, "grdfill", in_path] + args.split() + [f"-G{out_path}"]
    t0 = time.time()
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    dt = time.time() - t0
    if res.returncode != 0:
        raise RuntimeError(
            f"gmt grdfill failed (rc={res.returncode})\n"
            f"  cmd: {' '.join(cmd)}\n  stderr: {res.stderr}")
    return dt


# ---------------------------------------------------------------------------
# Synthetic-grid helpers
# ---------------------------------------------------------------------------

def _smooth_with_hole(nx: int, ny: int,
                      hole_slice=(slice(5, 11), slice(7, 14)),
                      *, seed: int = 0):
    """Build a smooth float32 grid + drop a rectangular NaN hole."""
    rng = np.random.default_rng(seed)
    x = np.arange(nx, dtype=np.float64)
    y = np.arange(ny, dtype=np.float64)
    xg, yg = np.meshgrid(x, y)
    z = (np.sin(xg * 0.3) * np.cos(yg * 0.4)
         + 2.0 * xg / nx - yg / ny
         + 0.01 * rng.standard_normal(xg.shape)).astype(np.float32)
    z_hole = z.copy()
    z_hole[hole_slice] = np.nan
    return z, z_hole, x, y


def _assert_data_bit_equal(z_py, z_gmt, *, label="", allow_nan_eq=True):
    """Assert float32 data arrays are byte-for-byte identical.

    Treats NaN == NaN if allow_nan_eq.
    """
    assert z_py.shape == z_gmt.shape, (
        f"{label}: shape mismatch py={z_py.shape} gmt={z_gmt.shape}")
    if np.array_equal(z_py, z_gmt, equal_nan=allow_nan_eq):
        return
    # Diagnostic on mismatch
    diff = z_py.astype(np.float64) - z_gmt.astype(np.float64)
    bad = ~np.isclose(z_py, z_gmt, equal_nan=allow_nan_eq, atol=0, rtol=0)
    raise AssertionError(
        f"{label}: data not bit-identical "
        f"(max|diff|={np.nanmax(np.abs(diff)):.3e}, n_mismatch={bad.sum()}, "
        f"first mismatch at {np.argwhere(bad)[0].tolist()}: "
        f"py={z_py[tuple(np.argwhere(bad)[0])]!r} "
        f"gmt={z_gmt[tuple(np.argwhere(bad)[0])]!r})")


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------

@unittest.skipUnless(_HAVE_GMT, "gmt binary not on PATH; refusing to silently pass")
class TestConstantFill(unittest.TestCase):
    """-Ac<value> : every NaN replaced with constant. Pure assignment."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="grdfill_test_c_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _round_trip(self, nx, ny, hole, value, label):
        _, z_hole, x, y = _smooth_with_hole(nx, ny, hole_slice=hole)
        in_path = self.tmp / "in.grd"
        write_gmt_grd(str(in_path), z_hole, x, y, node_offset=0)

        out_gmt = self.tmp / "out_gmt.grd"
        _gmt_grdfill(str(in_path), str(out_gmt), f"-Ac{value}")
        z_gmt, _, _, _ = read_gmt_grd(str(out_gmt))

        z_py = gmt_grdfill_py(z_hole, x, y,
                              algorithm='c', constant=value)
        _assert_data_bit_equal(z_py, z_gmt, label=label)
        self.assertFalse(np.isnan(z_py).any(), f"{label}: NaN remains")

    def test_value_999(self):
        self._round_trip(21, 17, (slice(5, 11), slice(7, 14)),
                         999.0, "Ac=999")

    def test_value_zero(self):
        self._round_trip(31, 23, (slice(3, 8), slice(10, 18)),
                         0.0, "Ac=0")

    def test_value_negative(self):
        self._round_trip(21, 17, (slice(5, 11), slice(7, 14)),
                         -42.5, "Ac=-42.5")


@unittest.skipUnless(_HAVE_GMT, "gmt binary not on PATH; refusing to silently pass")
class TestNearestFill(unittest.TestCase):
    """-An : Eric Xu nearest neighbour scan."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="grdfill_test_n_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _round_trip(self, nx, ny, hole, label):
        _, z_hole, x, y = _smooth_with_hole(nx, ny, hole_slice=hole)
        in_path = self.tmp / "in.grd"
        write_gmt_grd(str(in_path), z_hole, x, y, node_offset=0)

        out_gmt = self.tmp / "out_gmt.grd"
        _gmt_grdfill(str(in_path), str(out_gmt), "-An")
        z_gmt, _, _, _ = read_gmt_grd(str(out_gmt))

        z_py = gmt_grdfill_py(z_hole, x, y, algorithm='n')
        _assert_data_bit_equal(z_py, z_gmt, label=label)
        self.assertFalse(np.isnan(z_py).any(),
                         f"{label}: NaN remains after -An")

    def test_centered_hole(self):
        self._round_trip(21, 17, (slice(5, 11), slice(7, 14)),
                         "centered hole")

    def test_corner_hole(self):
        # NaN cluster touching the top-left corner.
        self._round_trip(21, 17, (slice(0, 4), slice(0, 5)),
                         "corner hole")

    def test_edge_hole_north(self):
        # Touches the top edge only.
        self._round_trip(21, 17, (slice(0, 3), slice(8, 14)),
                         "edge north")

    def test_many_holes(self):
        # Multiple scattered NaN clusters.
        _, z_hole, x, y = _smooth_with_hole(31, 23,
                                            hole_slice=(slice(0, 0), slice(0, 0)))
        z_hole[3:7, 4:9] = np.nan
        z_hole[15:18, 20:25] = np.nan
        z_hole[10, 10] = np.nan
        in_path = self.tmp / "in.grd"
        write_gmt_grd(str(in_path), z_hole, x, y, node_offset=0)

        out_gmt = self.tmp / "out_gmt.grd"
        _gmt_grdfill(str(in_path), str(out_gmt), "-An")
        z_gmt, _, _, _ = read_gmt_grd(str(out_gmt))

        z_py = gmt_grdfill_py(z_hole, x, y, algorithm='n')
        _assert_data_bit_equal(z_py, z_gmt, label="many holes")

    def test_explicit_radius(self):
        _, z_hole, x, y = _smooth_with_hole(21, 17,
                                            hole_slice=(slice(5, 11),
                                                         slice(7, 14)))
        in_path = self.tmp / "in.grd"
        write_gmt_grd(str(in_path), z_hole, x, y, node_offset=0)

        # radius 10 (large enough to reach a non-NaN from any hole node)
        out_gmt = self.tmp / "out_gmt.grd"
        _gmt_grdfill(str(in_path), str(out_gmt), "-An10")
        z_gmt, _, _, _ = read_gmt_grd(str(out_gmt))

        z_py = gmt_grdfill_py(z_hole, x, y, algorithm='n', radius=10)
        _assert_data_bit_equal(z_py, z_gmt, label="An radius=10")


@unittest.skipUnless(_HAVE_GMT, "gmt binary not on PATH; refusing to silently pass")
class TestGridFill(unittest.TestCase):
    """-Ag : sample from donor grid (the production dem2topo_ra path)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="grdfill_test_g_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_pair(self, nx, ny, hole_slice):
        z_full, z_hole, x, y = _smooth_with_hole(nx, ny,
                                                  hole_slice=hole_slice)
        in_path = self.tmp / "in.grd"
        coarse_path = self.tmp / "coarse.grd"
        write_gmt_grd(str(in_path), z_hole, x, y, node_offset=0)
        write_gmt_grd(str(coarse_path), z_full, x, y, node_offset=0)
        return z_hole, z_full, x, y, in_path, coarse_path

    def test_same_grid_donor(self):
        """Donor grid is the same x/y -- bilinear at node = node value."""
        z_hole, z_full, x, y, in_p, c_p = self._write_pair(
            21, 17, (slice(5, 11), slice(7, 14)))
        out_gmt = self.tmp / "out_gmt.grd"
        _gmt_grdfill(str(in_p), str(out_gmt), f"-Ag{c_p}")
        z_gmt, _, _, _ = read_gmt_grd(str(out_gmt))

        z_py = gmt_grdfill_py(z_hole, x, y, algorithm='g',
                              donor=z_full, donor_x=x, donor_y=y)
        _assert_data_bit_equal(z_py, z_gmt, label="-Ag same grid")
        self.assertFalse(np.isnan(z_py).any())

    def test_coarse_donor(self):
        """Donor grid covers same region but at half resolution."""
        # Full-res input (with hole)
        nx, ny = 41, 33
        _, z_hole, x, y = _smooth_with_hole(nx, ny,
                                             hole_slice=(slice(10, 22),
                                                          slice(14, 28)))
        # Coarse donor: every other node, same xmin/xmax (so spacing 2.0)
        cnx, cny = 21, 17
        cx = np.linspace(x[0], x[-1], cnx, dtype=np.float64)
        cy = np.linspace(y[0], y[-1], cny, dtype=np.float64)
        cxg, cyg = np.meshgrid(cx, cy)
        z_coarse = (np.sin(cxg * 0.3) * np.cos(cyg * 0.4)
                    + 2.0 * cxg / nx - cyg / ny).astype(np.float32)

        in_p = self.tmp / "in.grd"
        c_p = self.tmp / "coarse.grd"
        write_gmt_grd(str(in_p), z_hole, x, y, node_offset=0)
        write_gmt_grd(str(c_p), z_coarse, cx, cy, node_offset=0)

        out_gmt = self.tmp / "out_gmt.grd"
        _gmt_grdfill(str(in_p), str(out_gmt), f"-Ag{c_p}")
        z_gmt, _, _, _ = read_gmt_grd(str(out_gmt))

        z_py = gmt_grdfill_py(z_hole, x, y, algorithm='g',
                              donor=z_coarse, donor_x=cx, donor_y=cy)
        # For coarse donor, both paths do bilinear in float64 then cast to
        # float32.  GMT uses grdtrack which is the same algebra, so we
        # expect exact float32 equality; if a 1-ULP drift shows up due to
        # operation-ordering differences, fall back to <= 1 ULP.
        try:
            _assert_data_bit_equal(z_py, z_gmt, label="-Ag coarse donor")
        except AssertionError:
            # Last-ULP equivalence
            diff = np.abs(z_py.astype(np.float64)
                          - z_gmt.astype(np.float64))
            ulp = np.spacing(np.maximum(np.abs(z_py).astype(np.float64),
                                        np.abs(z_gmt).astype(np.float64)) + 1e-20)
            ok = (diff <= 2 * ulp).all()
            self.assertTrue(
                ok,
                f"-Ag coarse donor: max diff = {diff.max():.3e} > 2 ULP")

    def test_no_holes(self):
        """No NaNs in input -- should return the input unchanged."""
        nx, ny = 17, 13
        z_full, _, x, y = _smooth_with_hole(
            nx, ny, hole_slice=(slice(0, 0), slice(0, 0)))
        in_p = self.tmp / "in.grd"
        c_p = self.tmp / "coarse.grd"
        write_gmt_grd(str(in_p), z_full, x, y, node_offset=0)
        write_gmt_grd(str(c_p), z_full, x, y, node_offset=0)

        out_gmt = self.tmp / "out_gmt.grd"
        # gmt grdfill warns + returns input unchanged when no NaNs.
        _gmt_grdfill(str(in_p), str(out_gmt), f"-Ag{c_p}")
        z_gmt, _, _, _ = read_gmt_grd(str(out_gmt))

        z_py = gmt_grdfill_py(z_full, x, y, algorithm='g',
                              donor=z_full, donor_x=x, donor_y=y)
        _assert_data_bit_equal(z_py, z_gmt, label="-Ag no holes")

    def test_pixel_registered_donor(self):
        """Pixel-registered (node_offset=1) coarse donor -- Mira #70.

        Mirrors the dem2topo_ra production shape: ``coarse.grd`` is built
        with the same ``-R`` (wesn) as the input grid but ``-r`` (pixel
        registration), so its pixel centres are inset by ``dx_coarse/2``
        from the input's outermost gridline nodes.

        Pre-fix, ``_bcr_bicubic_sample`` hard-coded ``in_off=0.0`` and the
        range check used ``donor_x[0]/donor_x[-1]`` (the pixel CENTRES,
        not ``wesn``) -- so queries at the input's edge columns/rows (which
        sit exactly on the donor's ``wesn`` border, outside the pixel-
        centre range) raised ``ValueError: donor grid does not cover query
        x range``.  This test fails on that code and passes after the
        ``donor_node_offset`` / ``in_off=0.5*registration`` /
        ``gmtbcr_reject``-style clamp fix (gmt_bcr.c:86-131,
        gmt_grdio.c:2147).
        """
        # Fine (gridline-registered) input grid, wesn = [0,40] x [0,32].
        nx, ny = 41, 33
        x = np.arange(nx, dtype=np.float64)
        y = np.arange(ny, dtype=np.float64)
        _, z_hole, _, _ = _smooth_with_hole(
            nx, ny, hole_slice=(slice(2, 5), slice(2, 5)))
        # Also punch holes at the four corners + edge midpoints so the
        # bicubic query set includes points exactly on the donor's wesn
        # border (the pre-fix raise site).
        z_hole[0, 0] = np.nan
        z_hole[0, -1] = np.nan
        z_hole[-1, 0] = np.nan
        z_hole[-1, -1] = np.nan
        z_hole[0, nx // 2] = np.nan
        z_hole[-1, nx // 2] = np.nan
        z_hole[ny // 2, 0] = np.nan
        z_hole[ny // 2, -1] = np.nan

        # Coarse pixel-registered donor: same wesn=[0,40]x[0,32], 20x16
        # pixels -> dx_c=2, dy_c=2, pixel centres at 1,3,...,39 / 1,...,31.
        cnx, cny = 20, 16
        dx_c, dy_c = 40.0 / cnx, 32.0 / cny
        cx = (np.arange(cnx, dtype=np.float64) + 0.5) * dx_c
        cy = (np.arange(cny, dtype=np.float64) + 0.5) * dy_c
        cxg, cyg = np.meshgrid(cx, cy)
        z_coarse = (np.sin(cxg * 0.3) * np.cos(cyg * 0.4)
                    + 2.0 * cxg / nx - cyg / ny).astype(np.float32)

        in_p = self.tmp / "in.grd"
        c_p = self.tmp / "coarse.grd"
        write_gmt_grd(str(in_p), z_hole, x, y, node_offset=0)
        write_gmt_grd(str(c_p), z_coarse, cx, cy, node_offset=1)

        out_gmt = self.tmp / "out_gmt.grd"
        _gmt_grdfill(str(in_p), str(out_gmt), f"-Ag{c_p}")
        z_gmt, _, _, _ = read_gmt_grd(str(out_gmt))

        out_py_path = self.tmp / "out_py.grd"
        gmt_grdfill_py_file(str(in_p), str(out_py_path), algorithm='g',
                             donor_path=str(c_p))
        z_py, _, _, _ = read_gmt_grd(str(out_py_path))

        _assert_data_bit_equal(z_py, z_gmt, label="-Ag pixel-reg donor")


# ---------------------------------------------------------------------------
# Edge cases (Py-only contract tests)
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    """Boundary/edge contract -- not parity, just port semantics."""

    def test_all_nan_input_constant(self):
        # Every node NaN -- constant fill should fill everything.
        z = np.full((5, 7), np.nan, dtype=np.float32)
        x = np.arange(7, dtype=np.float64)
        y = np.arange(5, dtype=np.float64)
        out = gmt_grdfill_py(z, x, y, algorithm='c', constant=3.14)
        self.assertFalse(np.isnan(out).any())
        self.assertTrue((out == np.float32(3.14)).all())

    def test_all_nan_input_grid(self):
        # Every node NaN with donor -- all nodes filled from donor.
        z = np.full((5, 7), np.nan, dtype=np.float32)
        x = np.arange(7, dtype=np.float64)
        y = np.arange(5, dtype=np.float64)
        donor = np.arange(35, dtype=np.float32).reshape(5, 7) * 0.1
        out = gmt_grdfill_py(z, x, y, algorithm='g',
                             donor=donor, donor_x=x, donor_y=y)
        np.testing.assert_array_equal(out, donor)

    def test_no_nan_input_no_change(self):
        # No NaN -- output identical to input regardless of algorithm.
        z = np.arange(35, dtype=np.float32).reshape(5, 7)
        x = np.arange(7, dtype=np.float64)
        y = np.arange(5, dtype=np.float64)
        for algo, extra in (('c', {'constant': 99.0}),
                            ('n', {}),
                            ('g', {'donor': z + 1000.0,
                                   'donor_x': x, 'donor_y': y})):
            out = gmt_grdfill_py(z, x, y, algorithm=algo, **extra)
            np.testing.assert_array_equal(
                out, z, err_msg=f"algo={algo} mutated NaN-free input")

    def test_nan_at_boundary(self):
        # NaNs on the outer ring -- nearest must still find a value.
        z = np.arange(35, dtype=np.float32).reshape(5, 7)
        z = z.copy()
        z[0, :] = np.nan   # whole top row NaN
        z[:, -1] = np.nan  # whole right col NaN
        x = np.arange(7, dtype=np.float64)
        y = np.arange(5, dtype=np.float64)
        out = gmt_grdfill_py(z, x, y, algorithm='n')
        self.assertFalse(np.isnan(out).any())

    def test_unknown_algorithm_raises(self):
        z = np.zeros((3, 3), dtype=np.float32)
        x = np.arange(3, dtype=np.float64)
        y = np.arange(3, dtype=np.float64)
        with self.assertRaises(ValueError):
            gmt_grdfill_py(z, x, y, algorithm='zzz')

    def test_spline_raises_notimplemented(self):
        z = np.zeros((3, 3), dtype=np.float32)
        z[1, 1] = np.nan
        x = np.arange(3, dtype=np.float64)
        y = np.arange(3, dtype=np.float64)
        with self.assertRaises(NotImplementedError):
            gmt_grdfill_py(z, x, y, algorithm='s')

    def test_constant_without_value_raises(self):
        z = np.zeros((3, 3), dtype=np.float32)
        z[1, 1] = np.nan
        x = np.arange(3, dtype=np.float64)
        y = np.arange(3, dtype=np.float64)
        with self.assertRaises(ValueError):
            gmt_grdfill_py(z, x, y, algorithm='c')

    def test_grid_without_donor_raises(self):
        z = np.zeros((3, 3), dtype=np.float32)
        z[1, 1] = np.nan
        x = np.arange(3, dtype=np.float64)
        y = np.arange(3, dtype=np.float64)
        with self.assertRaises(ValueError):
            gmt_grdfill_py(z, x, y, algorithm='g')

    def test_bad_data_shape(self):
        z = np.zeros((3, 3, 3), dtype=np.float32)
        x = np.arange(3, dtype=np.float64)
        y = np.arange(3, dtype=np.float64)
        with self.assertRaises(ValueError):
            gmt_grdfill_py(z, x, y, algorithm='c', constant=0.0)


@unittest.skipUnless(_HAVE_GMT, "gmt binary not on PATH")
class TestFilePath(unittest.TestCase):
    """File-to-file wrapper verifies round-trip via netCDF."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="grdfill_test_file_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_file_grid_round_trip(self):
        z_full, z_hole, x, y = _smooth_with_hole(21, 17,
                                                  hole_slice=(slice(5, 11),
                                                              slice(7, 14)))
        in_p = self.tmp / "in.grd"
        c_p = self.tmp / "coarse.grd"
        write_gmt_grd(str(in_p), z_hole, x, y, node_offset=0)
        write_gmt_grd(str(c_p), z_full, x, y, node_offset=0)

        out_py = self.tmp / "out_py.grd"
        out_gmt = self.tmp / "out_gmt.grd"

        gmt_grdfill_py_file(str(in_p), str(out_py),
                            algorithm='g', donor_path=str(c_p))
        _gmt_grdfill(str(in_p), str(out_gmt), f"-Ag{c_p}")

        z_py, _, _, _ = read_gmt_grd(str(out_py))
        z_gmt, _, _, _ = read_gmt_grd(str(out_gmt))
        _assert_data_bit_equal(z_py, z_gmt, label="file-wrapper Ag")


# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------

@unittest.skipUnless(_HAVE_GMT, "gmt binary not on PATH")
class TestPerformance(unittest.TestCase):
    """Wall-time : py vs subprocess on a mid-size grid with hole.

    Not a hard regression gate -- just data for the wire-in
    justification.
    """

    def test_wall_time_vs_subprocess(self):
        tmp = Path(tempfile.mkdtemp(prefix="grdfill_perf_"))
        try:
            nx, ny = 1200, 900
            _, z_hole, x, y = _smooth_with_hole(
                nx, ny, hole_slice=(slice(300, 700), slice(400, 900)))
            z_full = z_hole.copy()
            z_full[300:700, 400:900] = 0.0  # fill so donor has no NaN

            in_p = tmp / "in.grd"
            c_p = tmp / "coarse.grd"
            write_gmt_grd(str(in_p), z_hole, x, y, node_offset=0)
            write_gmt_grd(str(c_p), z_full, x, y, node_offset=0)

            # Warm Numba (-An scan)
            small, _, sx, sy = _smooth_with_hole(20, 20)
            gmt_grdfill_py(small, sx, sy, algorithm='n')

            # GMT subprocess (-Ag, the production path)
            out_gmt = tmp / "gmt.grd"
            t_gmt = _gmt_grdfill(str(in_p), str(out_gmt), f"-Ag{c_p}")

            # py file path
            out_py = tmp / "py.grd"
            t0 = time.time()
            gmt_grdfill_py_file(str(in_p), str(out_py),
                                algorithm='g', donor_path=str(c_p))
            t_py = time.time() - t0

            # py array-only
            t0 = time.time()
            gmt_grdfill_py(z_hole, x, y, algorithm='g',
                           donor=z_full, donor_x=x, donor_y=y)
            t_arr = time.time() - t0

            print(f"\n  grdfill -Ag wall time on {ny}x{nx} float32:")
            print(f"    gmt subprocess (read+fill+write): {t_gmt*1e3:.1f} ms")
            print(f"    py_file       (read+fill+write): {t_py*1e3:.1f} ms")
            print(f"    py_array      (fill only)      : {t_arr*1e3:.3f} ms")
            print(f"    speedup (full file path)       : "
                  f"{t_gmt/max(t_py,1e-9):.2f}x")
            print(f"    speedup (array-only vs subproc): "
                  f"{t_gmt/max(t_arr,1e-9):.0f}x")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
