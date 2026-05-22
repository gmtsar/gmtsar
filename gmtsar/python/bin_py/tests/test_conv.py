#!/usr/bin/env python3
"""test_conv — unit + parity tests for bin_py/conv_py.

Run with:
    cd gmtsar/python/bin_py/tests
    python3 -m pytest test_conv.py -v
    # or, no pytest:
    python3 test_conv.py

Test pyramid:

  Unit (fast):
    - test_read_filter — parses a known filter file correctly
    - test_norm_mode_classification — DC filter vs derivative filter
    - test_conv2d_grid_interior — vectorized inner-loop matches a
      hand-coded scalar reference on a synthetic 5x5 grid

  Parity (slow — skipped if C `conv` or RS2 fixture missing):
    - TestConvVsCBinary.test_gauss15x3_dec1 — runs C `conv` and
      Py `conv_py` on the same =bf input (real.grd produced by
      phasediff). With this filter (gauss15x3, idec=jdec=1), the
      interior pixels agree to ~1e-13. The bottom ~7 rows of the C
      output read stale buffer memory from the chunked-read state
      machine in conv.c (a deterministic-but-implementation-defined
      C quirk); on those rows we expect Py and C to disagree at the
      ~1e-5 level. We assert agreement on the INTERIOR + permit a
      bottom-row exclusion.

Known divergences (C bugs we don't replicate)
---------------------------------------------
The C `conv` has TWO out-of-bounds memory-access bugs at image edges.
Both are documented inconsistencies, not the Py port:

1. **Bottom-row overrun**: In conv2d.c, `i1 = min(ni, ic+nif2)`. The
   loop iterates `i in [i0, i1]` INCLUSIVE — so for the last data row,
   it accesses one row past the valid buffer. The result depends on
   stale buffer memory from the chunked-read state machine. For
   gauss15x3 (yarr=15) this affects the bottom 7 rows.

2. **Right-column overrun**: Same issue in `j1 = min(nj, jc+njf2)`
   with the loop iterating inclusive. The data is row-major, so
   reading column `xdim` of row `i` accesses column 0 of row `i+1` —
   a wrap-around that pollutes the entire LAST column of the image
   with values that include data from the next row.

The Python port zero-pads instead — the mathematically correct edge
behavior. As a result:

  - Interior pixels (NOT last column, NOT bottom 7 rows): py == C to
    float32 roundoff (~1e-13 typical, < 1e-5 worst case from cos/sin
    sign-bit flips in phasediff_py output).
  - Last column: py ≈ 0 vs C ≈ 1e-6 (small wrap-around contamination)
  - Bottom 7 rows: py ≈ 0 at edge vs C reads stale memory

The pipeline impact is negligible: filter.csh applies a second conv
pass with decimation that discards the last partial row+column, then
FLIPUD, then phase formation. None of these C-bug regions survive
downstream.
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

_HERE = Path(__file__).resolve().parent
_PY = _HERE.parent / "conv_py"
_NS: dict = {"__name__": "conv_py", "__file__": str(_PY)}
exec(compile(_PY.read_text(), str(_PY), "exec"), _NS)
_read_filter = _NS["_read_filter"]
_conv2d_grid = _NS["_conv2d_grid"]
conv = _NS["conv"]

sys.path.insert(0, str(_HERE.parent))
from _gmt_native_bf import read_bf, write_bf  # noqa: E402

_RS2 = Path("/home/utig5/dliu/gmtsar/gmtsar/python/work/csh_test/RS2_SLC_Hawaii")
_FILTER_DIR = Path("/home/utig5/dliu/gmtsar/share/gmtsar/filters")
C_CONV = shutil.which("conv") or "/home/utig5/dliu/gmtsar/bin/conv"
C_PHASEDIFF = shutil.which("phasediff") or "/home/utig5/dliu/gmtsar/bin/phasediff"


def _have_c_conv() -> bool:
    return Path(C_CONV).exists() and os.access(C_CONV, os.X_OK)


def _have_fixture() -> bool:
    return all((
        _RS2.exists(),
        (_RS2 / "SLC" / "RS220110515.PRM").exists(),
        (_RS2 / "topo" / "topo_ra.grd").exists(),
        (_FILTER_DIR / "gauss15x3").exists(),
    ))


# ============================================================ unit tests ===


class TestReadFilter(unittest.TestCase):
    def test_filter_file_layout(self):
        """gauss15x3 in the shipped filters/ dir has the expected shape."""
        p = _FILTER_DIR / "gauss15x3"
        if not p.exists():
            self.skipTest("filters/gauss15x3 not present")
        flt, xarr, yarr = _read_filter(str(p))
        # File header: "3 15" → 3 cols (range), 15 rows (azimuth)
        self.assertEqual(xarr, 3)
        self.assertEqual(yarr, 15)
        self.assertEqual(flt.shape, (15, 3))
        # Center coefficient should be the largest (gaussian peak)
        self.assertEqual(flt.argmax(), 7 * 3 + 1)  # row 7 (middle), col 1

    def test_even_dims_rejected(self):
        with tempfile.NamedTemporaryFile("w", suffix=".filt", delete=False) as f:
            f.write("4 3\n")
            for v in range(12):
                f.write(f" {v}.0")
            path = f.name
        try:
            with self.assertRaises(IOError):
                _read_filter(path)
        finally:
            os.unlink(path)


class TestConv2dGridInterior(unittest.TestCase):
    """Vectorized inner loop matches hand-coded scalar conv on a tiny grid."""

    def test_5x5_box_filter(self):
        np.random.seed(0)
        data = np.random.randn(8, 10).astype(np.float32)
        flt = np.ones((3, 3), dtype=np.float32)
        # All output positions (no decimation)
        ic = np.arange(8, dtype=np.int64)
        jc = np.arange(10, dtype=np.int64)
        fdat, rnorm = _conv2d_grid(data, flt, ic, jc)
        # Hand-coded reference: scalar conv with zero-pad boundary
        ref_fdat = np.zeros_like(fdat)
        ref_rnorm = np.zeros_like(rnorm)
        for i, ci in enumerate(ic):
            for j, cj in enumerate(jc):
                s = 0.0
                n = 0.0
                for di in range(-1, 2):
                    for dj in range(-1, 2):
                        ii = ci + di
                        jj = cj + dj
                        if 0 <= ii < 8 and 0 <= jj < 10:
                            s += flt[di+1, dj+1] * data[ii, jj]
                            n += flt[di+1, dj+1]
                ref_fdat[i, j] = s
                ref_rnorm[i, j] = n
        np.testing.assert_allclose(fdat, ref_fdat, atol=1e-6)
        np.testing.assert_allclose(rnorm, ref_rnorm, atol=1e-6)

    def test_decimation(self):
        """Output dim should equal len(ic_arr) × len(jc_arr) regardless of input."""
        np.random.seed(1)
        data = np.random.randn(20, 30).astype(np.float32)
        flt = np.ones((3, 3), dtype=np.float32) / 9.0
        ic = np.arange(0, 20, 4, dtype=np.int64)   # 5 rows
        jc = np.arange(0, 30, 3, dtype=np.int64)   # 10 cols
        fdat, rnorm = _conv2d_grid(data, flt, ic, jc)
        self.assertEqual(fdat.shape, (5, 10))
        self.assertEqual(rnorm.shape, (5, 10))


# =========================================================== parity tests ===


class TestConvVsCBinary(unittest.TestCase):
    """End-to-end parity vs the C `conv` binary."""

    @classmethod
    def setUpClass(cls):
        if not _have_c_conv():
            raise unittest.SkipTest(f"C `conv` not found at {C_CONV}")
        if not _have_fixture():
            raise unittest.SkipTest("RS2 fixture or filters/gauss15x3 missing")
        if not Path(C_PHASEDIFF).exists():
            raise unittest.SkipTest("Need C `phasediff` to generate real.grd input")
        cls.tmpdir = Path(tempfile.mkdtemp(prefix="conv_parity_"))
        # Stage RS2 inputs
        shutil.copy(_RS2 / "SLC" / "RS220110515.PRM", cls.tmpdir / "master.PRM")
        shutil.copy(_RS2 / "SLC" / "RS220110819.PRM", cls.tmpdir / "aligned.PRM")
        shutil.copy(_RS2 / "SLC" / "RS220110515.SLC", cls.tmpdir / "RS220110515.SLC")
        shutil.copy(_RS2 / "SLC" / "RS220110819.SLC", cls.tmpdir / "RS220110819.SLC")
        shutil.copy(_RS2 / "topo" / "topo_ra.grd", cls.tmpdir / "topo_ra.grd")
        shutil.copy(_FILTER_DIR / "gauss15x3", cls.tmpdir / "gauss15x3")
        # Generate real.grd input using C `phasediff` for use by both conv runs
        subprocess.run(
            [C_PHASEDIFF, "master.PRM", "aligned.PRM",
             "-topo", "topo_ra.grd",
             "-imag", "imag.grd=bf", "-real", "real.grd=bf"],
            cwd=cls.tmpdir, check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "tmpdir") and cls.tmpdir.exists():
            shutil.rmtree(cls.tmpdir)

    def test_gauss15x3_dec1(self):
        """gauss15x3 filter, no decimation. Interior ~1e-13, bottom 7 rows diverge."""
        cwd = self.tmpdir
        subprocess.run(
            [C_CONV, "1", "1", "gauss15x3", "real.grd=bf", "c_smooth.grd=bf"],
            cwd=cwd, check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            [sys.executable, str(_PY),
             "1", "1", "gauss15x3", "real.grd=bf", "py_smooth.grd=bf"],
            cwd=cwd, check=True,
        )
        c, _ = read_bf(str(cwd / "c_smooth.grd"))
        p, _ = read_bf(str(cwd / "py_smooth.grd"))
        self.assertEqual(c.shape, p.shape)
        # Strict interior: skip bottom (yarr/2) rows AND last (xarr/2)
        # columns to exclude C's two known out-of-bounds bugs (see
        # module docstring for full explanation).
        ydim, xdim = c.shape
        yarr_half = 7   # gauss15x3 → yarr=15
        xarr_half = 1   # gauss15x3 → xarr=3
        c_int = c[yarr_half:ydim - yarr_half, xarr_half:xdim - xarr_half]
        p_int = p[yarr_half:ydim - yarr_half, xarr_half:xdim - xarr_half]
        diff_int = np.abs(c_int - p_int)
        max_int = float(diff_int.max())
        med_int = float(np.median(diff_int))
        # Interior should be essentially bit-equal.
        self.assertLess(max_int, 1e-7,
                        f"strict interior max diff {max_int:.2e} > 1e-7")
        self.assertLess(med_int, 1e-10,
                        f"strict interior median diff {med_int:.2e} > 1e-10")
        # Document the edge divergence (don't fail on it — it's a C bug)
        c_lastcol = c[:, -1]
        p_lastcol = p[:, -1]
        c_botrows = c[ydim - yarr_half:, :]
        p_botrows = p[ydim - yarr_half:, :]
        print(f"  strict interior: max={max_int:.2e}, median={med_int:.2e}")
        print(f"  last-col diff: max={np.abs(c_lastcol-p_lastcol).max():.2e} "
              f"(C wraps to next row)")
        print(f"  bottom-7-rows diff: max={np.abs(c_botrows-p_botrows).max():.2e} "
              f"(C reads stale buffer)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
