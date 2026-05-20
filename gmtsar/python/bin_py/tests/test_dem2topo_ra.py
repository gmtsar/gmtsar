#!/usr/bin/env python3
"""test_dem2topo_ra — unit tests for bin_py/dem2topo_ra_py.

The hand-portable bits we own (no GMT calls) — bounds derivation from
temp.rat, FLIPUD via clib.Session. Other steps (gmt surface,
SAT_llt2rat) are external and tested at the integration level via
the live RS2 sweep.

Run:
    python3 -m pytest test_dem2topo_ra.py -v
    # or:
    python3 test_dem2topo_ra.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
_DEM = _HERE.parent / "dem2topo_ra_py"
_NS: dict = {"__file__": str(_DEM), "__name__": "dem2topo_ra_module"}
exec(compile(_DEM.read_text(), str(_DEM), "exec"), _NS)
_bounds_of_temp_rat = _NS["_bounds_of_temp_rat"]


class TestBoundsDerivation(unittest.TestCase):
    """Covers `_bounds_of_temp_rat` — the key step in IMPROVEMENT A
    (skipping the gmt surface dry-run hint pass). Bounds derived
    directly from the xyz triplets that blockmedian writes."""

    def _write_temp_rat(self, xyz_rows: list[tuple[float, float, float]],
                        path: str) -> None:
        """Write a `temp.rat`-style binary file: 3 doubles per row."""
        a = np.array(xyz_rows, dtype=np.float64).flatten()
        a.tofile(path)

    def test_simple_rectangle(self):
        """xyz extent 100..900 (x), 200..3800 (y) → bounds match."""
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "temp.rat")
            self._write_temp_rat([
                (100.0, 200.0, 0.0),
                (500.0, 1000.0, 50.0),
                (900.0, 3800.0, 100.0),
                (250.0, 2100.0, 25.0),
            ], p)
            xmin, xmax, ymin, ymax = _bounds_of_temp_rat(p)
            self.assertEqual(xmin, 100)
            self.assertEqual(xmax, 900)
            self.assertEqual(ymin, 200)
            self.assertEqual(ymax, 3800)

    def test_fractional_xy_rounded_to_inclusive_int(self):
        """Bounds returned as inclusive integers (floor for min,
        ceil for max). Matches what gmt surface's -R expects."""
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "temp.rat")
            self._write_temp_rat([
                (100.5, 200.5, 0.0),
                (899.5, 3799.5, 10.0),
            ], p)
            xmin, xmax, ymin, ymax = _bounds_of_temp_rat(p)
            self.assertEqual(xmin, 100)      # floor(100.5)
            self.assertEqual(xmax, 900)      # ceil(899.5)
            self.assertEqual(ymin, 200)      # floor(200.5)
            self.assertEqual(ymax, 3800)     # ceil(3799.5)

    def test_empty_file_returns_zeros(self):
        """No xyz rows → all-zero bounds (caller falls back to nominal R)."""
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "temp.rat")
            open(p, "w").close()             # empty file
            self.assertEqual(_bounds_of_temp_rat(p), (0, 0, 0, 0))

    def test_misaligned_byte_count_returns_zeros(self):
        """File whose size isn't a multiple of (3 × float64) → bail safely."""
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "temp.rat")
            np.array([1.0, 2.0], dtype=np.float64).tofile(p)   # 2 doubles, not 3*N
            self.assertEqual(_bounds_of_temp_rat(p), (0, 0, 0, 0))

    def test_large_dataset_matches_numpy_minmax(self):
        """1000 random xyz rows: derived bounds match np.min / np.max."""
        rng = np.random.default_rng(7)
        xs = rng.uniform(50, 950, 1000)
        ys = rng.uniform(100, 4000, 1000)
        zs = rng.uniform(0, 500, 1000)
        rows = list(zip(xs.tolist(), ys.tolist(), zs.tolist()))
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "temp.rat")
            self._write_temp_rat(rows, p)
            xmin, xmax, ymin, ymax = _bounds_of_temp_rat(p)
            self.assertEqual(xmin, int(np.floor(xs.min())))
            self.assertEqual(xmax, int(np.ceil(xs.max())))
            self.assertEqual(ymin, int(np.floor(ys.min())))
            self.assertEqual(ymax, int(np.ceil(ys.max())))


class TestModuleImportsCleanly(unittest.TestCase):
    """Smoke test: the module loads without raising, and key symbols
    are exported. Catches import-time bugs (today's `shutil` issue
    would have been caught here)."""

    def test_required_symbols_present(self):
        for sym in ("_bounds_of_temp_rat", "_grdmath_flipud",
                    "_piped_grd2xyz_llt2rat", "_gmtconvert_blockmedian",
                    "dem2topo_ra"):
            self.assertIn(sym, _NS,
                          msg=f"dem2topo_ra_py missing symbol: {sym}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
