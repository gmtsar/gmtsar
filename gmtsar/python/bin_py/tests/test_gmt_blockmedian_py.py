#!/usr/bin/env python3
"""test_gmt_blockmedian_py — C-parity tests for the Numba port of
`gmt blockmedian -bi3d -bo3d -r`.

These tests are byte/roundoff-identical comparisons against the real
GMT binary. They are NOT self-consistency tests. If `gmt` is not on
PATH the tests fail LOUDLY (per /home/utig5/dliu/CLAUDE.md memory:
"bin_py tests need C-parity, not self-consistency").

Run:
    python3 -m unittest gmtsar/python/bin_py/tests/test_gmt_blockmedian_py.py
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

# Locate the port
_HERE = Path(__file__).resolve().parent
_UTILS = _HERE.parent.parent / "utils"
sys.path.insert(0, str(_UTILS))
from gmt_blockmedian_py import blockmedian  # noqa: E402


def gmt_blockmedian(xyz: np.ndarray, region, inc) -> np.ndarray:
    """Run `gmt blockmedian -bi3d -bo3d -r` and return its output."""
    if not GMT:
        raise RuntimeError(
            "gmt binary not found — parity test cannot run "
            "(install GMT or set PATH to include it)")
    with tempfile.TemporaryDirectory() as td:
        in_path = Path(td) / "in.bin"
        out_path = Path(td) / "out.bin"
        np.ascontiguousarray(xyz, dtype=np.float64).tofile(in_path)
        cmd = [
            GMT, "blockmedian", str(in_path),
            f"-R{region[0]}/{region[1]}/{region[2]}/{region[3]}",
            f"-I{inc[0]}/{inc[1]}",
            "-bi3d", "-bo3d", "-r",
        ]
        with open(out_path, "wb") as fout:
            res = subprocess.run(cmd, stdout=fout,
                                 stderr=subprocess.PIPE, check=False)
        if res.returncode != 0:
            raise RuntimeError(
                f"gmt blockmedian failed (rc={res.returncode}): "
                f"{res.stderr.decode(errors='replace')}")
        raw = np.fromfile(out_path, dtype=np.float64)
        if raw.size % 3 != 0:
            raise RuntimeError(f"gmt output not multiple of 3 doubles: {raw.size}")
        return raw.reshape(-1, 3)


def _assert_bit_parity(self, py_out, gmt_out, atol=0.0):
    self.assertEqual(py_out.shape, gmt_out.shape,
                     f"shape mismatch: py {py_out.shape} vs gmt {gmt_out.shape}")
    if atol == 0.0:
        self.assertTrue(
            np.array_equal(py_out, gmt_out),
            msg=f"not byte-identical; max diff = {np.abs(py_out - gmt_out).max()}")
    else:
        self.assertTrue(
            np.allclose(py_out, gmt_out, atol=atol, rtol=0.0),
            msg=f"max diff {np.abs(py_out - gmt_out).max()} exceeds atol {atol}")


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
        gmt_out = gmt_blockmedian(xyz, region, inc)
        py_out = blockmedian(xyz, region, inc, pixel_reg=True)
        _assert_bit_parity(self, py_out, gmt_out)

    def test_sparse_grid_empty_cells(self):
        # 1 point per 10x10 cell on average, but with most cells empty
        rng = np.random.default_rng(7)
        N = 50
        xyz = np.column_stack([
            rng.uniform(0, 100, N),
            rng.uniform(0, 100, N),
            rng.standard_normal(N),
        ])
        region = (0.0, 100.0, 0.0, 100.0)
        inc = (10.0, 10.0)
        gmt_out = gmt_blockmedian(xyz, region, inc)
        py_out = blockmedian(xyz, region, inc, pixel_reg=True)
        _assert_bit_parity(self, py_out, gmt_out)

    def test_single_point_bin(self):
        # Each point in its own bin → output equals input (modulo order)
        xyz = np.array([
            [0.5, 0.5, 1.0],
            [1.5, 0.5, 2.0],
            [0.5, 1.5, 3.0],
            [1.5, 1.5, 4.0],
        ])
        region = (0.0, 2.0, 0.0, 2.0)
        inc = (1.0, 1.0)
        gmt_out = gmt_blockmedian(xyz, region, inc)
        py_out = blockmedian(xyz, region, inc, pixel_reg=True)
        _assert_bit_parity(self, py_out, gmt_out)

    def test_points_on_bin_boundary(self):
        # Point at x = xmin + dx (exact boundary). GMT uses banker
        # rounding via irint, so x=1.0 with dx=1 → cell index 0
        # (round_half_to_even of 0.5 = 0). This is the trickiest
        # divergence between a naive floor() port and GMT.
        xyz = np.array([
            [0.5, 0.5, 10.0],
            [1.0, 0.5, 100.0],  # boundary
            [1.5, 0.5, 50.0],
            [2.0, 0.5, 200.0],  # banker round(1.5)=2 -> cell 2 in 4-cell grid
            [2.5, 0.5, 20.0],
            [3.0, 0.5, 300.0],  # banker round(2.5)=2 -> cell 2
        ])
        region = (0.0, 4.0, 0.0, 1.0)
        inc = (1.0, 1.0)
        gmt_out = gmt_blockmedian(xyz, region, inc)
        py_out = blockmedian(xyz, region, inc, pixel_reg=True)
        _assert_bit_parity(self, py_out, gmt_out)

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
        gmt_out = gmt_blockmedian(xyz, region, inc)
        py_out = blockmedian(xyz, region, inc, pixel_reg=True)
        _assert_bit_parity(self, py_out, gmt_out)

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
        gmt_out = gmt_blockmedian(xyz, region, inc)
        py_out = blockmedian(xyz, region, inc, pixel_reg=True)
        _assert_bit_parity(self, py_out, gmt_out)

    def test_even_count_per_bin_median(self):
        # 4 points per bin so median is mean of middle two
        # (numpy default; we verified GMT does the same)
        xyz = np.array([
            [0.1, 0.1, 10.0],
            [0.3, 0.3, 20.0],
            [0.5, 0.5, 30.0],
            [0.7, 0.7, 40.0],
        ])
        region = (0.0, 1.0, 0.0, 1.0)
        inc = (1.0, 1.0)
        gmt_out = gmt_blockmedian(xyz, region, inc)
        py_out = blockmedian(xyz, region, inc, pixel_reg=True)
        _assert_bit_parity(self, py_out, gmt_out)

    def test_region_inc_auto_adjust(self):
        """Region NOT a clean multiple of inc — GMT auto-adjusts inc to
        (xmax-xmin)/nx. The port must match this byte-for-byte (or it
        diverges on every real dem2topo_ra invocation)."""
        rng = np.random.default_rng(101)
        N = 50_000
        # 11324 / 8 = 1415.5 → banker → nx=1416; effective inc = 7.9971751...
        xyz = np.column_stack([
            rng.uniform(-10.0, 11314.0, N),
            rng.uniform(-20.0, 27668.0, N),
            rng.standard_normal(N),
        ])
        region = (-10.0, 11314.0, -20.0, 27668.0)
        inc = (8.0, 8.0)
        gmt_out = gmt_blockmedian(xyz, region, inc)
        py_out = blockmedian(xyz, region, inc, pixel_reg=True)
        _assert_bit_parity(self, py_out, gmt_out)

    def test_large_8M_rows_smoke(self):
        # Realistic NISAR-scale: 8M rows. We don't bit-check every
        # value (the difference *should* still be zero), but if there
        # is roundoff at scale we want to see it.
        rng = np.random.default_rng(2)
        N = 8_000_000
        xyz = np.column_stack([
            rng.uniform(0, 1000, N),
            rng.uniform(0, 1000, N),
            rng.standard_normal(N).astype(np.float64),
        ])
        region = (0.0, 1000.0, 0.0, 1000.0)
        inc = (1.0, 1.0)
        gmt_out = gmt_blockmedian(xyz, region, inc)
        py_out = blockmedian(xyz, region, inc, pixel_reg=True)
        _assert_bit_parity(self, py_out, gmt_out)


_HERE = Path(__file__).resolve().parent
_WORK_ROOT = Path(
    os.environ.get("GMTSAR_TEST_WORK")
    or (os.environ.get("GMTSAR", "") + "/gmtsar/python/work"
        if os.environ.get("GMTSAR") else "")
    or str(_HERE.parents[2] / "work")
)
_REAL_TRANS = _WORK_ROOT / "csh_test/ALOS_Baja_EQ/topo/trans.dat"


@unittest.skipUnless(GMT and _REAL_TRANS.exists(),
                     "real trans.dat fixture not present on this host")
class TestParityRealData(unittest.TestCase):
    """C-parity on a real ALOS_Baja_EQ trans.dat (~9M rows)."""

    def test_real_trans_dat_byte_parity(self):
        raw = np.fromfile(_REAL_TRANS, dtype=np.float64)
        assert raw.size % 5 == 0, "trans.dat not a multiple of 5 doubles"
        xyz = raw.reshape(-1, 5)[:, :3].copy()
        region = (-10.0, 11314.0, -20.0, 27668.0)
        inc = (8.0, 8.0)
        gmt_out = gmt_blockmedian(xyz, region, inc)
        py_out = blockmedian(xyz, region, inc, pixel_reg=True)
        _assert_bit_parity(self, py_out, gmt_out)


@unittest.skipUnless(GMT, "gmt binary not found on this host")
class TestEdgeCases(unittest.TestCase):
    """Edge-case checks for the Python API (no parity gate)."""

    def test_empty_region(self):
        xyz = np.array([[100.0, 100.0, 1.0]])  # outside R
        out = blockmedian(xyz, (0.0, 10.0, 0.0, 10.0), (1.0, 1.0))
        self.assertEqual(out.shape, (0, 3))

    def test_bad_shape_raises(self):
        with self.assertRaises(ValueError):
            blockmedian(np.zeros((10, 4)),
                        (0.0, 1.0, 0.0, 1.0), (0.1, 0.1))

    def test_zero_size_grid_raises(self):
        with self.assertRaises(ValueError):
            # inc bigger than region → nx=0
            blockmedian(np.array([[0.0, 0.0, 1.0]]),
                        (0.0, 0.5, 0.0, 0.5), (1.0, 1.0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
