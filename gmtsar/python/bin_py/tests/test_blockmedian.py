#!/usr/bin/env python3
"""test_blockmedian — unit tests for bin_py/blockmedian_py."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
_BM = _HERE.parent / "blockmedian_py"
_NS: dict = {"__file__": str(_BM), "__name__": "blockmedian_module"}
exec(compile(_BM.read_text(), str(_BM), "exec"), _NS)
blockmedian_xyz = _NS["blockmedian_xyz"]
_parse_region = _NS["_parse_region"]
_parse_spacing = _NS["_parse_spacing"]


class TestParseHelpers(unittest.TestCase):
    def test_region_four_floats(self):
        self.assertEqual(_parse_region("0/100/200/3800"),
                         (0.0, 100.0, 200.0, 3800.0))

    def test_region_malformed_raises(self):
        with self.assertRaises(ValueError):
            _parse_region("0/100/200")    # only 3 components

    def test_spacing_single_isotropic(self):
        self.assertEqual(_parse_spacing("2"), (2.0, 2.0))

    def test_spacing_anisotropic(self):
        self.assertEqual(_parse_spacing("1/4"), (1.0, 4.0))


class TestBlockmedianCorrectness(unittest.TestCase):

    def test_single_cell_returns_median(self):
        """5 points all inside one cell → output is (centre, median z)."""
        xyz = np.array([
            [10.0, 10.0, 100.0],
            [10.5, 10.5, 110.0],
            [11.0, 11.0, 200.0],
            [11.5, 11.5, 130.0],
            [12.0, 12.0, 150.0],
        ])
        out = blockmedian_xyz(xyz, (10.0, 20.0, 10.0, 20.0),
                              (10.0, 10.0), pixel_reg=True)
        self.assertEqual(out.shape, (1, 3))
        self.assertAlmostEqual(out[0, 0], 15.0)        # cell centre x
        self.assertAlmostEqual(out[0, 1], 15.0)        # cell centre y
        self.assertAlmostEqual(out[0, 2], 130.0)       # median of [100,110,130,150,200]

    def test_two_cells_independent_medians(self):
        """Two cells, each with its own points → 2 rows, each medianed."""
        xyz = np.array([
            [1.0, 1.0, 10.0],
            [1.5, 1.5, 30.0],     # cell 0,0: median = 30
            [1.0, 1.0, 50.0],
            [5.5, 5.5, 100.0],
            [5.0, 5.0, 200.0],    # cell 1,1: median of [100,200] = 150
        ])
        out = blockmedian_xyz(xyz, (0.0, 10.0, 0.0, 10.0),
                              (5.0, 5.0), pixel_reg=True)
        # Expect 2 non-empty cells out of 4
        self.assertEqual(out.shape, (2, 3))
        # Find which row corresponds to which cell
        medians = sorted([(round(r[0], 1), round(r[1], 1), r[2]) for r in out])
        self.assertEqual(medians[0][:2], (2.5, 2.5))   # cell 0,0 centre
        self.assertEqual(medians[1][:2], (7.5, 7.5))   # cell 1,1 centre
        self.assertAlmostEqual(medians[0][2], 30.0)    # median of [10,30,50]
        self.assertAlmostEqual(medians[1][2], 150.0)   # median of [100,200]

    def test_empty_cells_dropped(self):
        """A 3×3 grid with only one cell populated → output 1 row."""
        xyz = np.array([[1.5, 1.5, 42.0]])
        out = blockmedian_xyz(xyz, (0.0, 3.0, 0.0, 3.0),
                              (1.0, 1.0), pixel_reg=True)
        self.assertEqual(out.shape, (1, 3))
        self.assertAlmostEqual(out[0, 2], 42.0)

    def test_out_of_region_filtered(self):
        """Points outside R are silently dropped."""
        xyz = np.array([
            [1.0, 1.0, 10.0],         # inside
            [100.0, 100.0, 99.0],     # outside
            [-5.0, 1.0, 50.0],        # outside
        ])
        out = blockmedian_xyz(xyz, (0.0, 10.0, 0.0, 10.0),
                              (10.0, 10.0), pixel_reg=True)
        self.assertEqual(out.shape, (1, 3))
        self.assertAlmostEqual(out[0, 2], 10.0)

    def test_all_outside_returns_empty(self):
        """No xyz row inside R → output is (0, 3)."""
        xyz = np.array([[100.0, 100.0, 1.0]])
        out = blockmedian_xyz(xyz, (0.0, 10.0, 0.0, 10.0),
                              (10.0, 10.0), pixel_reg=True)
        self.assertEqual(out.shape, (0, 3))

    def test_large_random_smoke(self):
        """1000 random points in a 10x10 grid: output is monotone-bounded."""
        rng = np.random.default_rng(13)
        xyz = np.column_stack([
            rng.uniform(0, 100, 1000),
            rng.uniform(0, 100, 1000),
            rng.uniform(0, 1000, 1000),
        ])
        out = blockmedian_xyz(xyz, (0.0, 100.0, 0.0, 100.0),
                              (10.0, 10.0), pixel_reg=True)
        # All cells should have at least 1 point (1000 pts across 100 cells avg=10)
        self.assertTrue(out.shape[0] >= 95,
                        msg=f"expected ~100 non-empty cells, got {out.shape[0]}")
        # z medians should be inside the original z range
        self.assertTrue((out[:, 2] >= 0).all() and (out[:, 2] <= 1000).all())


if __name__ == "__main__":
    unittest.main(verbosity=2)
