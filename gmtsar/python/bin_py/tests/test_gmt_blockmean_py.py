#!/usr/bin/env python3
"""test_gmt_blockmean_py — C-parity tests for the numpy port of
`gmt blockmean -bi3d -bo3d -r`.

These tests compare against the real GMT binary on the SAME input
bytes. They are NOT self-consistency tests. If `gmt` is not on PATH
the tests fail LOUDLY (skipUnless reports the skip reason; there is
no silent pass).

Unlike `gmt_blockmedian_py` (median reduction, byte-identical to
GMT), the mean reduction here is float-roundoff-identical only:
GMT's per-bin accumulation order is not guaranteed to match our
np.argsort(kind="stable") order, so float64 summation differs at the
~1 ULP level. Every test below therefore uses atol=1e-9 (the
project's doubles tolerance, see project_rules.md Rule 7 / Phase C),
NOT atol=0. Measured real-data diffs are ~1e-12..1e-14 -- three to
five orders of magnitude inside that gate.

Run:
    python3 -m unittest gmtsar/python/bin_py/tests/test_gmt_blockmean_py.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

GMT = shutil.which("gmt") or ""

_HERE = Path(__file__).resolve().parent
_UTILS = _HERE.parent.parent / "utils"
sys.path.insert(0, str(_UTILS))
from gmt_blockmean_py import blockmean  # noqa: E402

ATOL_DOUBLE = 1e-9  # project_rules.md doubles tolerance


def gmt_blockmean(xyz: np.ndarray, region, inc) -> np.ndarray:
    """Run `gmt blockmean -bi3d -bo3d -r` and return its output."""
    if not GMT:
        raise RuntimeError(
            "gmt binary not found — parity test cannot run "
            "(install GMT or set PATH to include it)")
    with tempfile.TemporaryDirectory() as td:
        in_path = Path(td) / "in.bin"
        out_path = Path(td) / "out.bin"
        np.ascontiguousarray(xyz, dtype=np.float64).tofile(in_path)
        cmd = [
            GMT, "blockmean", str(in_path),
            f"-R{region[0]}/{region[1]}/{region[2]}/{region[3]}",
            f"-I{inc[0]}/{inc[1]}",
            "-bi3d", "-bo3d", "-r",
        ]
        with open(out_path, "wb") as fout:
            res = subprocess.run(cmd, stdout=fout,
                                 stderr=subprocess.PIPE, check=False)
        if res.returncode != 0:
            raise RuntimeError(
                f"gmt blockmean failed (rc={res.returncode}): "
                f"{res.stderr.decode(errors='replace')}")
        raw = np.fromfile(out_path, dtype=np.float64)
        if raw.size % 3 != 0:
            raise RuntimeError(f"gmt output not multiple of 3 doubles: {raw.size}")
        return raw.reshape(-1, 3)


def _assert_roundoff_parity(self, py_out, gmt_out, atol=ATOL_DOUBLE):
    self.assertEqual(py_out.shape, gmt_out.shape,
                     f"shape mismatch: py {py_out.shape} vs gmt {gmt_out.shape}")
    diff = np.abs(py_out - gmt_out)
    self.assertTrue(
        np.allclose(py_out, gmt_out, atol=atol, rtol=0.0),
        msg=f"max diff {diff.max()} exceeds atol {atol}")


@unittest.skipUnless(GMT, "gmt binary not found on this host")
class TestParitySynthetic(unittest.TestCase):
    """C-parity on synthetic inputs of various shapes."""

    def test_1000_random_uniform(self):
        rng = np.random.default_rng(13)
        N = 1000
        xyz = np.column_stack([
            rng.uniform(0, 10, N),
            rng.uniform(0, 10, N),
            rng.standard_normal(N) * 5,
        ])
        region = (0.0, 10.0, 0.0, 10.0)
        inc = (1.0, 1.0)
        gmt_out = gmt_blockmean(xyz, region, inc)
        py_out = blockmean(xyz, region, inc, pixel_reg=True)
        _assert_roundoff_parity(self, py_out, gmt_out)

    def test_sparse_grid_empty_cells(self):
        rng = np.random.default_rng(7)
        N = 50
        xyz = np.column_stack([
            rng.uniform(0, 100, N),
            rng.uniform(0, 100, N),
            rng.standard_normal(N),
        ])
        region = (0.0, 100.0, 0.0, 100.0)
        inc = (10.0, 10.0)
        gmt_out = gmt_blockmean(xyz, region, inc)
        py_out = blockmean(xyz, region, inc, pixel_reg=True)
        _assert_roundoff_parity(self, py_out, gmt_out)

    def test_single_point_bin(self):
        # Each point in its own bin -> mean of 1 point = the point itself.
        xyz = np.array([
            [0.5, 0.5, 1.0],
            [1.5, 0.5, 2.0],
            [0.5, 1.5, 3.0],
            [1.5, 1.5, 4.0],
        ])
        region = (0.0, 2.0, 0.0, 2.0)
        inc = (1.0, 1.0)
        gmt_out = gmt_blockmean(xyz, region, inc)
        py_out = blockmean(xyz, region, inc, pixel_reg=True)
        _assert_roundoff_parity(self, py_out, gmt_out, atol=0.0)

    def test_points_on_bin_boundary(self):
        # Banker rounding (irint / np.rint) must place boundary points
        # in the same bin as GMT -- this is a bin-geometry check, not
        # a mean-reduction check, so it can be byte-exact.
        xyz = np.array([
            [0.5, 0.5, 10.0],
            [1.0, 0.5, 100.0],
            [1.5, 0.5, 50.0],
            [2.0, 0.5, 200.0],
            [2.5, 0.5, 20.0],
            [3.0, 0.5, 300.0],
        ])
        region = (0.0, 4.0, 0.0, 1.0)
        inc = (1.0, 1.0)
        gmt_out = gmt_blockmean(xyz, region, inc)
        py_out = blockmean(xyz, region, inc, pixel_reg=True)
        _assert_roundoff_parity(self, py_out, gmt_out)

    def test_non_integer_inc(self):
        rng = np.random.default_rng(99)
        N = 5000
        xyz = np.column_stack([
            rng.uniform(-3.0, 7.0, N),
            rng.uniform(10.0, 30.0, N),
            rng.standard_normal(N),
        ])
        region = (-3.0, 7.0, 10.0, 30.0)
        inc = (0.25, 0.5)
        gmt_out = gmt_blockmean(xyz, region, inc)
        py_out = blockmean(xyz, region, inc, pixel_reg=True)
        _assert_roundoff_parity(self, py_out, gmt_out)

    def test_anisotropic_inc(self):
        rng = np.random.default_rng(11)
        N = 2000
        xyz = np.column_stack([
            rng.uniform(0, 8, N),
            rng.uniform(0, 4, N),
            rng.standard_normal(N) * 0.1,
        ])
        region = (0.0, 8.0, 0.0, 4.0)
        inc = (2.0, 0.5)
        gmt_out = gmt_blockmean(xyz, region, inc)
        py_out = blockmean(xyz, region, inc, pixel_reg=True)
        _assert_roundoff_parity(self, py_out, gmt_out)

    def test_dense_bins_200k_rows(self):
        # ~20 pts/bin on average -- exercises the summation-order
        # roundoff divergence (the case that motivated atol=1e-9
        # instead of atol=0 for this port).
        rng = np.random.default_rng(42)
        N = 200_000
        xyz = np.column_stack([
            rng.uniform(0, 100, N),
            rng.uniform(0, 100, N),
            rng.standard_normal(N) * 5,
        ])
        region = (0.0, 100.0, 0.0, 100.0)
        inc = (1.0, 1.0)
        gmt_out = gmt_blockmean(xyz, region, inc)
        py_out = blockmean(xyz, region, inc, pixel_reg=True)
        _assert_roundoff_parity(self, py_out, gmt_out)

    def test_region_inc_auto_adjust(self):
        rng = np.random.default_rng(101)
        N = 50_000
        xyz = np.column_stack([
            rng.uniform(-10.0, 11314.0, N),
            rng.uniform(-20.0, 27668.0, N),
            rng.standard_normal(N),
        ])
        region = (-10.0, 11314.0, -20.0, 27668.0)
        inc = (8.0, 8.0)
        gmt_out = gmt_blockmean(xyz, region, inc)
        py_out = blockmean(xyz, region, inc, pixel_reg=True)
        _assert_roundoff_parity(self, py_out, gmt_out)


_HERE = Path(__file__).resolve().parent
_WORK_ROOT = Path(
    os.environ.get("GMTSAR_TEST_WORK")
    or (os.environ.get("GMTSAR", "") + "/gmtsar/python/work"
        if os.environ.get("GMTSAR") else "")
    or str(_HERE.parents[2] / "work")
)
_REAL_TEMP_RAT = _WORK_ROOT / "python_test/RS2_SLC_Hawaii/topo/temp.rat"


@unittest.skipUnless(GMT and _REAL_TEMP_RAT.exists(),
                     "real temp.rat fixture not present on this host")
class TestParityRealData(unittest.TestCase):
    """C-parity on a real RS2_SLC_Hawaii temp.rat (~965k rows), using
    the same -R/-I shape as the topo_interp_mode=1 dem2topo_ra call
    site (rng2/16 spacing on a PRF<1000 scene)."""

    def test_real_temp_rat_roundoff_parity(self):
        xyz = np.fromfile(_REAL_TEMP_RAT, dtype=np.float64).reshape(-1, 3)
        region = (0.0, 3416.0, 0.0, 5744.0)
        inc = (32.0, 16.0)
        gmt_out = gmt_blockmean(xyz, region, inc)
        py_out = blockmean(xyz, region, inc, pixel_reg=True)
        _assert_roundoff_parity(self, py_out, gmt_out)


@unittest.skipUnless(GMT, "gmt binary not found on this host")
class TestEdgeCases(unittest.TestCase):
    """Edge-case checks for the Python API (no parity gate)."""

    def test_empty_region(self):
        xyz = np.array([[100.0, 100.0, 1.0]])  # outside R
        out = blockmean(xyz, (0.0, 10.0, 0.0, 10.0), (1.0, 1.0))
        self.assertEqual(out.shape, (0, 3))

    def test_bad_shape_raises(self):
        with self.assertRaises(ValueError):
            blockmean(np.zeros((10, 4)),
                     (0.0, 1.0, 0.0, 1.0), (0.1, 0.1))

    def test_zero_size_grid_raises(self):
        with self.assertRaises(ValueError):
            blockmean(np.array([[0.0, 0.0, 1.0]]),
                     (0.0, 0.5, 0.0, 0.5), (1.0, 1.0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
