#!/usr/bin/env python3
"""test_gmt_grdcut_py — C-parity test for utils/gmt_grdcut_py.

Runs ``gmt grdcut`` (subprocess) and ``gmt_grdcut_py`` on the SAME input
grid and asserts byte-identical (rms < float32 ULP) numerical output.

Three test families:

  1. Synthetic gridline-registered grid: cut to inner half, off-by-one
     edges, a single-row strip.  Assert byte-identical.

  2. Synthetic pixel-registered grid: cut to inner half on cell-edge
     boundaries.  Assert byte-identical.

  3. Real DEM (work/csh_test/RS2_SLC_Hawaii/topo/dem.grd, READ-ONLY
     per Rule 9): cut to multiple sub-regions.  Assert byte-identical
     and rms <= 1 ULP.

  4. Error-handling: out-of-bounds + misaligned -R raise.

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
# Locate sources
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent
_UTILS = _HERE.parent.parent / "utils"          # gmtsar/python/utils/
sys.path.insert(0, str(_UTILS))

from gmt_grdcut_py import gmt_grdcut_py, gmt_grdcut_py_file  # noqa: E402
from gmt_grd_io import write_gmt_grd, read_gmt_grd            # noqa: E402

_GMT = shutil.which("gmt")
_HAVE_GMT = _GMT is not None and os.access(_GMT, os.X_OK)

# Real DEM file (READ-ONLY).
_WORK_ROOT = Path(
    os.environ.get("GMTSAR_TEST_WORK")
    or (os.environ.get("GMTSAR", "") + "/gmtsar/python/work"
        if os.environ.get("GMTSAR") else "")
    or str(_HERE.parents[2] / "work")
)
_DEM_PATH = _WORK_ROOT / "csh_test/RS2_SLC_Hawaii/topo/dem.grd"
_HAVE_DEM = _DEM_PATH.exists()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _gmt_grdcut(in_path: str, out_path: str, region) -> float:
    """Invoke ``gmt grdcut <in> -R<w>/<e>/<s>/<n> -G<out>``.

    Returns wall-clock seconds (subprocess fork/exec + work).
    Raises if rc != 0.
    """
    w, e, s, n = region
    cmd = [_GMT, "grdcut", in_path,
           f"-R{w}/{e}/{s}/{n}", f"-G{out_path}"]
    t0 = time.time()
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    dt = time.time() - t0
    if res.returncode != 0:
        raise RuntimeError(
            f"gmt grdcut failed (rc={res.returncode})\n"
            f"  cmd: {' '.join(cmd)}\n  stderr: {res.stderr}"
        )
    return dt


def _make_smooth_grid(nx: int, ny: int, *,
                      xmin=0.0, xmax=10.0, ymin=0.0, ymax=8.0,
                      pixel_reg=False):
    """Build a simple smooth float32 grid.

    For gridline reg: x[0]=xmin, x[-1]=xmax, dx=(xmax-xmin)/(nx-1).
    For pixel    reg: x[0]=xmin+dx/2, x[-1]=xmax-dx/2,
                                          dx=(xmax-xmin)/nx.
    """
    if pixel_reg:
        dx = (xmax - xmin) / nx
        dy = (ymax - ymin) / ny
        x = xmin + (np.arange(nx) + 0.5) * dx
        y = ymin + (np.arange(ny) + 0.5) * dy
    else:
        x = np.linspace(xmin, xmax, nx, dtype=np.float64)
        y = np.linspace(ymin, ymax, ny, dtype=np.float64)
    # Simple smooth pattern, distinct values at every node.
    z = (x[None, :] * 0.31415 + y[:, None] * 0.27182).astype(np.float32)
    return z, x, y


def _assert_grids_equal(z_py, x_py, y_py, z_gmt, x_gmt, y_gmt, *,
                        atol_z=0.0, atol_xy=1e-9, msg=""):
    """Assert the two (data, x, y) triples are equal to within tolerance.

    Default atol_z=0.0 enforces byte-identical float32 values.
    """
    assert z_py.shape == z_gmt.shape, (
        f"{msg}: shape mismatch py={z_py.shape} gmt={z_gmt.shape}"
    )
    assert x_py.shape == x_gmt.shape, (
        f"{msg}: x shape mismatch py={x_py.shape} gmt={x_gmt.shape}"
    )
    assert y_py.shape == y_gmt.shape, (
        f"{msg}: y shape mismatch py={y_py.shape} gmt={y_gmt.shape}"
    )

    # Coord arrays: GMT writes back as float64 with some last-bit shift
    # from the actual_range round-trip; allow a tight numeric tolerance.
    assert np.allclose(x_py, x_gmt, atol=atol_xy, rtol=0), (
        f"{msg}: x mismatch (max |diff|={np.abs(x_py-x_gmt).max():.3e})"
    )
    assert np.allclose(y_py, y_gmt, atol=atol_xy, rtol=0), (
        f"{msg}: y mismatch (max |diff|={np.abs(y_py-y_gmt).max():.3e})"
    )

    # Data: cuts are pure indexing so we expect bit-identical float32.
    if atol_z == 0.0:
        assert np.array_equal(z_py, z_gmt, equal_nan=True), (
            f"{msg}: data not bit-identical "
            f"(max |diff|={np.nanmax(np.abs(z_py.astype(np.float64) - z_gmt.astype(np.float64))):.3e})"
        )
    else:
        diff = np.abs(z_py.astype(np.float64) - z_gmt.astype(np.float64))
        assert np.nanmax(diff) <= atol_z, (
            f"{msg}: data exceeds tol "
            f"(max |diff|={np.nanmax(diff):.3e} > {atol_z:.3e})"
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@unittest.skipUnless(_HAVE_GMT, "gmt binary not on PATH; refusing to silently pass")
class TestSyntheticGridline(unittest.TestCase):
    """Cut a small smooth gridline-registered grid; expect bit-identical."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="grdcut_test_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _round_trip(self, nx, ny, region, label):
        in_path = self.tmp / "in.grd"
        z, x, y = _make_smooth_grid(nx, ny, pixel_reg=False)
        write_gmt_grd(str(in_path), z, x, y, node_offset=0)

        # gmt path
        out_gmt = self.tmp / "out_gmt.grd"
        _gmt_grdcut(str(in_path), str(out_gmt), region)
        z_gmt, x_gmt, y_gmt, info_gmt = read_gmt_grd(str(out_gmt))
        self.assertEqual(info_gmt["node_offset"], 0, f"{label}: gmt changed reg")

        # py path (in-memory)
        z_py, x_py, y_py = gmt_grdcut_py(z, x, y, region=region, pixel_reg=False)

        _assert_grids_equal(z_py, x_py, y_py, z_gmt, x_gmt, y_gmt, msg=label)

    def test_inner_half(self):
        # 11x9 grid spanning [0,10]x[0,8] with dx=1.0 dy=1.0.
        # Cut to inner half: [2,7]x[2,6].
        self._round_trip(11, 9, region=(2.0, 7.0, 2.0, 6.0),
                         label="gridline inner-half")

    def test_off_one_edge(self):
        # Cut to one-cell-shifted boundary: [1,9]x[1,7]
        self._round_trip(11, 9, region=(1.0, 9.0, 1.0, 7.0),
                         label="gridline off-by-one")

    def test_thin_strip(self):
        # Thinnest strip GMT accepts (s < n required): one cell of y.
        self._round_trip(11, 9, region=(2.0, 7.0, 3.0, 4.0),
                         label="gridline thin-strip")

    def test_full_grid(self):
        # No-op subset (full extent).
        self._round_trip(11, 9, region=(0.0, 10.0, 0.0, 8.0),
                         label="gridline full")


@unittest.skipUnless(_HAVE_GMT, "gmt binary not on PATH; refusing to silently pass")
class TestSyntheticPixel(unittest.TestCase):
    """Cut a pixel-registered grid; verify registration semantics + bit-equality."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="grdcut_test_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _round_trip(self, nx, ny, region, label):
        in_path = self.tmp / "in.grd"
        z, x, y = _make_smooth_grid(nx, ny, pixel_reg=True)
        write_gmt_grd(str(in_path), z, x, y, node_offset=1)

        out_gmt = self.tmp / "out_gmt.grd"
        _gmt_grdcut(str(in_path), str(out_gmt), region)
        z_gmt, x_gmt, y_gmt, info_gmt = read_gmt_grd(str(out_gmt))
        self.assertEqual(info_gmt["node_offset"], 1,
                         f"{label}: gmt lost pixel reg")

        z_py, x_py, y_py = gmt_grdcut_py(z, x, y, region=region, pixel_reg=True)

        _assert_grids_equal(z_py, x_py, y_py, z_gmt, x_gmt, y_gmt, msg=label)

    def test_inner_half(self):
        # 10x8 pixel grid spanning [0,10]x[0,8] with dx=dy=1.0.
        # cell centers at 0.5,1.5,...,9.5; cell edges at 0,1,...,10.
        # Cut to inner half on cell edges: [2,8]x[2,6]
        self._round_trip(10, 8, region=(2.0, 8.0, 2.0, 6.0),
                         label="pixel inner-half")

    def test_full_grid(self):
        # No-op subset.
        self._round_trip(10, 8, region=(0.0, 10.0, 0.0, 8.0),
                         label="pixel full")


@unittest.skipUnless(_HAVE_GMT and _HAVE_DEM,
                     "gmt or RS2 Hawaii DEM unavailable")
class TestRealDEM(unittest.TestCase):
    """Cut a real DEM at multiple sub-regions; assert bit-identical.

    Per Rule 9 the DEM at csh_test/.../dem.grd is READ-ONLY.  All outputs
    land in a temp dir.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="grdcut_test_dem_"))
        # Read the real DEM once.
        self.z, self.x, self.y, self.info = read_gmt_grd(str(_DEM_PATH))
        self.assertEqual(self.info["node_offset"], 0, "DEM should be gridline-reg")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _round_trip(self, region, label):
        out_gmt = self.tmp / f"gmt_{label}.grd"
        # Use the real input file directly — guaranteed identical bytes
        # for both pipelines.
        _gmt_grdcut(str(_DEM_PATH), str(out_gmt), region)
        z_gmt, x_gmt, y_gmt, info_gmt = read_gmt_grd(str(out_gmt))

        z_py, x_py, y_py = gmt_grdcut_py(
            self.z, self.x, self.y, region=region, pixel_reg=False,
        )

        _assert_grids_equal(z_py, x_py, y_py, z_gmt, x_gmt, y_gmt, msg=label)

    def test_small_central(self):
        # DEM spans ~[-155.7,-154.9] x [18.9,19.8] @ 1arcsec.
        # Cut a small central window aligned to grid.
        dx = float(self.x[1] - self.x[0])
        # Snap to grid nodes exactly.
        w = float(self.x[500])
        e = float(self.x[800])
        s = float(self.y[400])
        n = float(self.y[700])
        self._round_trip((w, e, s, n), "small-central")

    def test_west_edge(self):
        # Window touching the west edge.
        w = float(self.x[0])
        e = float(self.x[300])
        s = float(self.y[100])
        n = float(self.y[500])
        self._round_trip((w, e, s, n), "west-edge")

    def test_east_edge(self):
        # Window touching the east edge.
        w = float(self.x[-300])
        e = float(self.x[-1])
        s = float(self.y[200])
        n = float(self.y[800])
        self._round_trip((w, e, s, n), "east-edge")

    def test_north_strip(self):
        # Thin strip across the top.
        w = float(self.x[100])
        e = float(self.x[1500])
        s = float(self.y[-50])
        n = float(self.y[-1])
        self._round_trip((w, e, s, n), "north-strip")


@unittest.skipUnless(_HAVE_GMT, "gmt binary not on PATH")
class TestFilePath(unittest.TestCase):
    """Verify the gmt_grdcut_py_file() wrapper produces a GMT-readable .grd."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="grdcut_test_file_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_file_round_trip(self):
        in_path = self.tmp / "in.grd"
        z, x, y = _make_smooth_grid(21, 17, pixel_reg=False)
        write_gmt_grd(str(in_path), z, x, y, node_offset=0)

        out_py = self.tmp / "out_py.grd"
        out_gmt = self.tmp / "out_gmt.grd"
        region = (2.0, 8.0, 1.0, 7.0)

        gmt_grdcut_py_file(str(in_path), str(out_py), region=region)
        _gmt_grdcut(str(in_path), str(out_gmt), region)

        z_py, x_py, y_py, info_py = read_gmt_grd(str(out_py))
        z_gmt, x_gmt, y_gmt, info_gmt = read_gmt_grd(str(out_gmt))

        _assert_grids_equal(z_py, x_py, y_py, z_gmt, x_gmt, y_gmt,
                            msg="file-wrapper round-trip")
        # Confirm our output is still grdcut-able by gmt itself.
        out_chain = self.tmp / "chain.grd"
        _gmt_grdcut(str(out_py), str(out_chain), (3.0, 6.0, 2.0, 5.0))


class TestErrorHandling(unittest.TestCase):
    """Hard-failure tests — these MUST raise (Rule 1: no silent fallbacks)."""

    def test_region_outside_grid(self):
        z, x, y = _make_smooth_grid(11, 9, pixel_reg=False)
        with self.assertRaises(ValueError):
            gmt_grdcut_py(z, x, y, region=(100.0, 200.0, 100.0, 200.0))

    def test_region_partly_outside(self):
        z, x, y = _make_smooth_grid(11, 9, pixel_reg=False)
        # Off the high end by a full dx — no -N supported.
        with self.assertRaises(ValueError):
            gmt_grdcut_py(z, x, y, region=(0.0, 12.0, 0.0, 8.0))

    def test_region_misaligned(self):
        z, x, y = _make_smooth_grid(11, 9, pixel_reg=False)
        # 0.37 is not a multiple of dx=1.0.
        with self.assertRaises(ValueError):
            gmt_grdcut_py(z, x, y, region=(0.37, 5.0, 0.0, 4.0))

    def test_bad_region_order(self):
        z, x, y = _make_smooth_grid(11, 9, pixel_reg=False)
        with self.assertRaises(ValueError):
            gmt_grdcut_py(z, x, y, region=(5.0, 2.0, 1.0, 4.0))

    def test_bad_data_shape(self):
        x = np.arange(11.0)
        y = np.arange(9.0)
        z = np.zeros((5, 5), dtype=np.float32)   # mismatched shape
        with self.assertRaises(ValueError):
            gmt_grdcut_py(z, x, y, region=(1.0, 4.0, 1.0, 4.0))


@unittest.skipUnless(_HAVE_GMT and _HAVE_DEM,
                     "gmt or RS2 Hawaii DEM unavailable")
class TestPerformance(unittest.TestCase):
    """Measure py vs subprocess gmt grdcut wall-time on the real DEM.

    NOT a regression gate — just emits numbers so the wire-in justification
    is data-backed.
    """

    def test_wall_time_vs_subprocess(self):
        tmp = Path(tempfile.mkdtemp(prefix="grdcut_perf_"))
        try:
            z, x, y, info = read_gmt_grd(str(_DEM_PATH))
            # mid-grid window of ~1/4 area
            w = float(x[500])
            e = float(x[2000])
            s = float(y[500])
            n = float(y[2500])
            region = (w, e, s, n)

            # py: include read+cut+write (most realistic swap-in)
            out_py = tmp / "py.grd"
            t0 = time.time()
            gmt_grdcut_py_file(str(_DEM_PATH), str(out_py), region=region)
            t_py = time.time() - t0

            # gmt subprocess: include just the subprocess.run
            out_gmt = tmp / "gmt.grd"
            t_gmt = _gmt_grdcut(str(_DEM_PATH), str(out_gmt), region)

            # py array-only (no file I/O) — useful when caller has arrays
            t0 = time.time()
            gmt_grdcut_py(z, x, y, region=region, pixel_reg=False)
            t_arr = time.time() - t0

            print(f"\n  grdcut wall time on RS2-Hawaii DEM "
                  f"({z.shape[0]}x{z.shape[1]} float32):")
            print(f"    gmt subprocess (read+cut+write): {t_gmt*1e3:.1f} ms")
            print(f"    py_file        (read+cut+write): {t_py*1e3:.1f} ms")
            print(f"    py_array       (cut only)      : {t_arr*1e3:.3f} ms")
            print(f"    speedup (full file path)      : {t_gmt/max(t_py,1e-9):.1f}x")
            print(f"    speedup (array-only vs subproc): "
                  f"{t_gmt/max(t_arr,1e-9):.0f}x")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
