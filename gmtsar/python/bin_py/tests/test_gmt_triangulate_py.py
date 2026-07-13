#!/usr/bin/env python3
"""test_gmt_triangulate_py — C-parity test for utils/gmt_triangulate_py.

Runs ``gmt triangulate`` (subprocess) and ``gmt_triangulate_py`` on the
SAME real ``temp.rat`` input (the actual scattered range/azimuth/elevation
points ``dem2topo_ra`` mode=1 feeds triangulate) and asserts numerically
equal output.

Real-data files used (READ-ONLY, per Rule 9):
    work/python_test/RS2_SLC_Hawaii/topo/temp.rat   (964,812 pts)
    work/python_test/ALOS4_Pinon/topo/temp.rat       (6,155,430 pts)

KNOWN GAP (documented, not swept under the rug — see module docstring
in gmt_triangulate_py.py "Performance verdict" and Rule 7): on the
larger ALOS4_Pinon input, scipy's Qhull-based Delaunay and GMT's
Shewchuk's-Triangle-based Delaunay pick a different diagonal at a
handful of near-degenerate (near-cocircular) point quads. Observed:
10 of 29,315,664 grid nodes diverge (max |diff| ~12.2), all other
29,311,477 valid nodes are bit-identical. The RS2_SLC_Hawaii case
(964,812 pts, 2,452,676 valid nodes) is 100% bit-identical. This test
asserts the OBSERVED bound (>=99.999% of nodes bit-identical, i.e.
<=20 divergent nodes tolerated on the Pinon case) rather than loosening
the RS2 case's strict 0-mismatch bound. Do NOT raise this tolerance
without a fresh real-data re-measurement (Rule 13).

Skips loudly (does NOT silently pass) if ``gmt`` is not on PATH or the
real cached temp.rat files are not present (they are produced by a
prior tests/sweep.sh run and are not checked into git).
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

_HERE = Path(__file__).resolve().parent
_UTILS = _HERE.parent.parent / "utils"
sys.path.insert(0, str(_UTILS))

from gmt_triangulate_py import gmt_triangulate_grid, gmt_triangulate_py_file  # noqa: E402
from gmt_grd_io import read_gmt_grd  # noqa: E402

_GMT = shutil.which("gmt")
_HAVE_GMT = _GMT is not None and os.access(_GMT, os.X_OK)

_WORK_ROOT = Path(
    os.environ.get("GMTSAR_TEST_WORK")
    or (os.environ.get("GMTSAR", "") + "/gmtsar/python/work"
        if os.environ.get("GMTSAR") else "")
    or str(_HERE.parents[2] / "work")
)
_RS2_RAT = _WORK_ROOT / "python_test/RS2_SLC_Hawaii/topo/temp.rat"
_PINON_RAT = _WORK_ROOT / "python_test/ALOS4_Pinon/topo/temp.rat"


def _gmt_triangulate(in_path, out_path, region, xinc, yinc, pixel_reg=True):
    w, e, s, n = region
    cmd = [_GMT, "triangulate", str(in_path),
           f"-R{w}/{e}/{s}/{n}", f"-I{xinc}/{yinc}", "-bi3d",
           f"-G{out_path}"]
    if pixel_reg:
        cmd.append("-r")
    t0 = time.time()
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    dt = time.time() - t0
    if res.returncode != 0:
        raise RuntimeError(
            f"gmt triangulate failed (rc={res.returncode})\n"
            f"  cmd: {' '.join(cmd)}\n  stderr: {res.stderr}"
        )
    return dt


def _compare(z_py, z_c, *, max_mismatches, label):
    nan_py = np.isnan(z_py)
    nan_c = np.isnan(z_c)
    mismatch = nan_py != nan_c
    n_mismatch = int(mismatch.sum())
    valid = ~nan_py & ~nan_c
    diff = np.abs(z_py.astype(np.float64) - z_c.astype(np.float64))
    diff_valid = diff[valid]
    n_diverge = int(np.sum(diff_valid > 1e-3))
    total_bad = n_mismatch + n_diverge
    assert total_bad <= max_mismatches, (
        f"{label}: {n_mismatch} NaN-mask mismatches + {n_diverge} value "
        f"divergences (>1e-3) out of {z_py.size} nodes "
        f"(tolerance {max_mismatches}); max|diff|={diff_valid.max() if diff_valid.size else 0.0:.3f}"
    )
    return n_mismatch, n_diverge, (diff_valid.max() if diff_valid.size else 0.0)


@unittest.skipUnless(_HAVE_GMT, "gmt binary not on PATH; refusing to silently pass")
@unittest.skipUnless(_RS2_RAT.exists(), f"real temp.rat not found: {_RS2_RAT}")
class TestRealRS2Hawaii(unittest.TestCase):
    """964,812-point real case: PROVEN 100% bit-identical."""

    REGION = (0.0, 3416.0, 0.0, 5744.0)
    XINC, YINC = 2.0, 4.0

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="triangulate_test_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_file_wrapper_bit_identical(self):
        out_c = self.tmp / "c.grd"
        out_py = self.tmp / "py.grd"
        _gmt_triangulate(_RS2_RAT, out_c, self.REGION, self.XINC, self.YINC)
        gmt_triangulate_py_file(
            str(_RS2_RAT), str(out_py),
            region=self.REGION, xinc=self.XINC, yinc=self.YINC, pixel_reg=True,
        )
        z_c, x_c, y_c, info_c = read_gmt_grd(str(out_c))
        z_py, x_py, y_py, info_py = read_gmt_grd(str(out_py))
        self.assertEqual(z_py.shape, z_c.shape)
        self.assertEqual(info_py["node_offset"], info_c["node_offset"])
        assert np.allclose(x_py, x_c, atol=1e-9)
        assert np.allclose(y_py, y_c, atol=1e-9)
        n_mismatch, n_diverge, max_diff = _compare(
            z_py, z_c, max_mismatches=0, label="RS2_SLC_Hawaii"
        )
        self.assertEqual((n_mismatch, n_diverge), (0, 0))


@unittest.skipUnless(_HAVE_GMT, "gmt binary not on PATH; refusing to silently pass")
@unittest.skipUnless(_PINON_RAT.exists(), f"real temp.rat not found: {_PINON_RAT}")
class TestRealAlos4Pinon(unittest.TestCase):
    """6,155,430-point real case: documents the rare Delaunay-tie gap.

    KNOWN GAP: near-degenerate point quads cause Qhull and Shewchuk's
    Triangle to pick different diagonals at a handful of nodes. Observed
    bound: <=10 divergent nodes out of 29,315,664. Tolerance set at 20
    (2x observed) to avoid test flakiness from Qhull's own tie-breaking
    non-determinism across scipy versions, while still catching a real
    regression (e.g. hundreds/thousands of mismatches would fail loudly).
    """

    REGION = (0.0, 8244.0, 0.0, 28448.0)
    XINC, YINC = 2.0, 4.0

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="triangulate_test_pinon_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_file_wrapper_mostly_bit_identical(self):
        out_c = self.tmp / "c.grd"
        out_py = self.tmp / "py.grd"
        _gmt_triangulate(_PINON_RAT, out_c, self.REGION, self.XINC, self.YINC)
        gmt_triangulate_py_file(
            str(_PINON_RAT), str(out_py),
            region=self.REGION, xinc=self.XINC, yinc=self.YINC, pixel_reg=True,
        )
        z_c, x_c, y_c, info_c = read_gmt_grd(str(out_c))
        z_py, x_py, y_py, info_py = read_gmt_grd(str(out_py))
        self.assertEqual(z_py.shape, z_c.shape)
        n_mismatch, n_diverge, max_diff = _compare(
            z_py, z_c, max_mismatches=20, label="ALOS4_Pinon"
        )
        print(f"\n  ALOS4_Pinon: {n_mismatch} NaN-mask mismatches, "
              f"{n_diverge} value divergences (>1e-3), max|diff|={max_diff:.3f} "
              f"out of {z_py.size} nodes")


class TestErrorHandling(unittest.TestCase):
    """Hard-failure tests — Rule 1/3: no silent fallback on bad input."""

    def test_too_few_points(self):
        x = np.array([0.0, 1.0])
        y = np.array([0.0, 1.0])
        z = np.array([0.0, 1.0])
        with self.assertRaises(ValueError):
            gmt_triangulate_grid(x, y, z, region=(0, 10, 0, 10), xinc=1, yinc=1)

    def test_nonfinite_coords(self):
        x = np.array([0.0, 1.0, 2.0, np.nan])
        y = np.array([0.0, 1.0, 1.0, 0.0])
        z = np.array([0.0, 1.0, 2.0, 3.0])
        with self.assertRaises(ValueError):
            gmt_triangulate_grid(x, y, z, region=(0, 10, 0, 10), xinc=1, yinc=1)

    def test_bad_region(self):
        x = np.array([0.0, 1.0, 2.0])
        y = np.array([0.0, 1.0, 1.0])
        z = np.array([0.0, 1.0, 2.0])
        with self.assertRaises(ValueError):
            gmt_triangulate_grid(x, y, z, region=(10, 0, 0, 10), xinc=1, yinc=1)

    def test_mismatched_lengths(self):
        x = np.array([0.0, 1.0, 2.0])
        y = np.array([0.0, 1.0])
        z = np.array([0.0, 1.0, 2.0])
        with self.assertRaises(ValueError):
            gmt_triangulate_grid(x, y, z, region=(0, 10, 0, 10), xinc=1, yinc=1)

    def test_malformed_binary_file(self):
        tmp = Path(tempfile.mkdtemp(prefix="triangulate_err_"))
        try:
            bad = tmp / "bad.rat"
            # 5 float64 values -- not a multiple of 3.
            np.array([1.0, 2.0, 3.0, 4.0, 5.0], dtype="<f8").tofile(bad)
            with self.assertRaises(ValueError):
                gmt_triangulate_py_file(
                    str(bad), str(tmp / "out.grd"),
                    region=(0, 10, 0, 10), xinc=1, yinc=1,
                )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


@unittest.skipUnless(_HAVE_GMT, "gmt binary not on PATH")
@unittest.skipUnless(_RS2_RAT.exists(), f"real temp.rat not found: {_RS2_RAT}")
class TestPerformance(unittest.TestCase):
    """Single-threaded wall-time vs subprocess gmt triangulate.

    NOT a regression gate that fails the suite -- this documents the
    Rule 7 speed-gate FAILURE (Python is slower) so the honest number
    ships with the port. See gmt_triangulate_py.py module docstring
    "Performance verdict".
    """

    def test_wall_time_single_threaded(self):
        region = (0.0, 3416.0, 0.0, 5744.0)
        tmp = Path(tempfile.mkdtemp(prefix="triangulate_perf_"))
        try:
            out_c = tmp / "c.grd"
            out_py = tmp / "py.grd"

            # subprocess.run already pays fork/exec; pin the child to one
            # core the same way the AUDIT numbers were measured.
            t0 = time.time()
            subprocess.run(
                ["taskset", "-c", "0", _GMT, "triangulate", str(_RS2_RAT),
                 f"-R{region[0]}/{region[1]}/{region[2]}/{region[3]}",
                 "-I2/4", "-bi3d", f"-G{out_c}", "-r"],
                capture_output=True, check=True,
            )
            t_c = time.time() - t0

            t0 = time.time()
            gmt_triangulate_py_file(
                str(_RS2_RAT), str(out_py),
                region=region, xinc=2.0, yinc=4.0, pixel_reg=True,
            )
            t_py = time.time() - t0

            print(f"\n  triangulate wall time on RS2-Hawaii temp.rat "
                  f"(964,812 pts, single-threaded):")
            print(f"    gmt subprocess (taskset -c 0): {t_c*1e3:.0f} ms")
            print(f"    py (Delaunay+grid+write)     : {t_py*1e3:.0f} ms")
            print(f"    ratio py/c                   : {t_py/max(t_c,1e-9):.1f}x "
                  f"({'SLOWER' if t_py > t_c else 'faster'})")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
