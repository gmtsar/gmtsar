#!/usr/bin/env python3
"""test_gmt_inproc — byte-parity tests for utils/gmt_inproc helpers.

Per the project rule "bin_py tests need C-parity, not self-consistency":
every helper is exercised against `gmt …` running on the SAME input file,
and the output bytes are compared with `==`. No tolerances, no
self-consistency, no synthetic-only tests.

Skip rules
----------
- If `gmt` is not on PATH → skip (loudly, not silently — the test name
  includes the reason in the skip message).
- If `netCDF4` import fails → skip (the inproc helper requires it).

Run:
    python3 -m pytest gmtsar/python/bin_py/tests/test_gmt_inproc.py -v
    # or:
    python3 gmtsar/python/bin_py/tests/test_gmt_inproc.py
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

# Put utils/ on sys.path so we can import gmt_inproc.
_REPO_PY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_PY / "utils"))

try:
    from gmt_inproc import (  # type: ignore
        grd2xyz_skip_nan,
        grd2xyz_skip_nan_to_file,
        gmtconvert_select_cols_bin,
    )
    _IMPORTED = True
    _IMPORT_ERR: str | None = None
except Exception as e:  # noqa: BLE001
    _IMPORTED = False
    _IMPORT_ERR = repr(e)


_HAS_GMT = shutil.which("gmt") is not None


def _gmt(*argv: str, **kwargs) -> subprocess.CompletedProcess:
    """Run `gmt <argv>` and return CompletedProcess. Raises on non-zero."""
    return subprocess.run(["gmt", *argv], check=True,
                          capture_output=True, **kwargs)


# Real RS2 oracle paths — the smallest fast oracle per the user's brief.
_RS2 = Path("/home/utig5/dliu/gmtsar/gmtsar/python/work/python_test/RS2_SLC_Hawaii")
_RS2_DEM = _RS2 / "topo" / "dem.grd"
_RS2_CORR = _RS2 / "intf" / "2011134_2011230" / "corr.grd"
_RS2_TRANS = _RS2 / "topo" / "trans.dat"


@unittest.skipUnless(_IMPORTED, f"gmt_inproc import failed: {_IMPORT_ERR}")
@unittest.skipUnless(_HAS_GMT, "gmt not on PATH (set up conda env or install)")
class TestGrd2xyzSkipNan(unittest.TestCase):
    """Parity vs `gmt grd2xyz <grd> -s -bo3d`.

    Tested oracles:
    - DEM grid (geographic, lat/lon coords, no NaN)
    - corr.grd (Cartesian, x/y coords, ~30% NaN to exercise -s mask)
    """

    @unittest.skipUnless(_RS2_DEM.exists(), f"oracle missing: {_RS2_DEM}")
    def test_geographic_dem_no_nan(self):
        """dem.grd: lat/lon coords, dense. No NaN ⇒ -s strips nothing."""
        with tempfile.TemporaryDirectory() as d:
            ref = os.path.join(d, "ref.bin")
            py = os.path.join(d, "py.bin")
            with open(ref, "wb") as f:
                subprocess.run(
                    ["gmt", "grd2xyz", str(_RS2_DEM), "-s", "-bo3d"],
                    stdout=f, check=True,
                )
            grd2xyz_skip_nan_to_file(str(_RS2_DEM), py)
            with open(ref, "rb") as f:
                ref_bytes = f.read()
            with open(py, "rb") as f:
                py_bytes = f.read()
            self.assertEqual(len(py_bytes), len(ref_bytes),
                             "byte-count mismatch")
            self.assertEqual(py_bytes, ref_bytes,
                             "byte stream not bit-identical to gmt grd2xyz")

    @unittest.skipUnless(_RS2_CORR.exists(), f"oracle missing: {_RS2_CORR}")
    def test_cartesian_corr_with_nan(self):
        """corr.grd: x/y coords, ~30% NaN ⇒ exercises -s skip mask."""
        with tempfile.TemporaryDirectory() as d:
            ref = os.path.join(d, "ref.bin")
            py = os.path.join(d, "py.bin")
            with open(ref, "wb") as f:
                subprocess.run(
                    ["gmt", "grd2xyz", str(_RS2_CORR), "-s", "-bo3d"],
                    stdout=f, check=True,
                )
            grd2xyz_skip_nan_to_file(str(_RS2_CORR), py)
            with open(ref, "rb") as f:
                ref_bytes = f.read()
            with open(py, "rb") as f:
                py_bytes = f.read()
            self.assertEqual(py_bytes, ref_bytes,
                             "byte stream not bit-identical to gmt grd2xyz "
                             "(NaN-skip case)")

    @unittest.skipUnless(_RS2_DEM.exists(), f"oracle missing: {_RS2_DEM}")
    def test_array_form_matches_file_form(self):
        """`grd2xyz_skip_nan` array.tobytes() == grd2xyz_skip_nan_to_file()
        on the same grid (sanity check on the in-memory path)."""
        with tempfile.TemporaryDirectory() as d:
            py_file = os.path.join(d, "py.bin")
            grd2xyz_skip_nan_to_file(str(_RS2_DEM), py_file)
            with open(py_file, "rb") as f:
                from_file = f.read()
            arr = grd2xyz_skip_nan(str(_RS2_DEM))
            self.assertEqual(arr.tobytes(), from_file)
            # And re-verify against gmt
            ref = os.path.join(d, "ref.bin")
            with open(ref, "wb") as f:
                subprocess.run(
                    ["gmt", "grd2xyz", str(_RS2_DEM), "-s", "-bo3d"],
                    stdout=f, check=True,
                )
            with open(ref, "rb") as f:
                ref_bytes = f.read()
            self.assertEqual(arr.tobytes(), ref_bytes)


@unittest.skipUnless(_IMPORTED, f"gmt_inproc import failed: {_IMPORT_ERR}")
@unittest.skipUnless(_HAS_GMT, "gmt not on PATH")
class TestGmtconvertSelectCols(unittest.TestCase):
    """Parity vs `gmt gmtconvert <in> -o<cols> -bi<n>d -bo<m>d`."""

    @unittest.skipUnless(_RS2_TRANS.exists(), f"oracle missing: {_RS2_TRANS}")
    def test_o012_bi5d_bo3d(self):
        """The exact invocation used in utils/dem2topo_ra (lines 123, 169):
            gmt gmtconvert trans.dat -o0,1,2 -bi5d -bo3d
        """
        with tempfile.TemporaryDirectory() as d:
            ref = os.path.join(d, "ref.bin")
            py = os.path.join(d, "py.bin")
            with open(ref, "wb") as f:
                subprocess.run(
                    ["gmt", "gmtconvert", str(_RS2_TRANS),
                     "-o0,1,2", "-bi5d", "-bo3d"],
                    stdout=f, check=True,
                )
            n = gmtconvert_select_cols_bin(str(_RS2_TRANS), 5, [0, 1, 2], py)
            self.assertEqual(n, os.path.getsize(ref))
            with open(ref, "rb") as f:
                ref_bytes = f.read()
            with open(py, "rb") as f:
                py_bytes = f.read()
            self.assertEqual(py_bytes, ref_bytes,
                             "gmtconvert column-select not bit-identical")

    def test_size_error_on_misaligned_input(self):
        """A truncated/mis-aligned input should raise, not silently
        produce garbage."""
        with tempfile.TemporaryDirectory() as d:
            # 5 doubles * 8 = 40 B per record. Write 41 bytes — misaligned.
            bad = os.path.join(d, "bad.bin")
            with open(bad, "wb") as f:
                f.write(np.zeros(5, dtype=np.float64).tobytes() + b"\x00")
            with self.assertRaises(ValueError):
                gmtconvert_select_cols_bin(bad, 5, [0, 1, 2],
                                            os.path.join(d, "out.bin"))

    def test_col_out_of_range_error(self):
        """Asking for col 7 of a 5-col record should raise."""
        with tempfile.TemporaryDirectory() as d:
            inp = os.path.join(d, "in.bin")
            np.zeros((10, 5), dtype=np.float64).tofile(inp)
            with self.assertRaises(ValueError):
                gmtconvert_select_cols_bin(inp, 5, [0, 1, 7],
                                            os.path.join(d, "out.bin"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
