#!/usr/bin/env python3
"""test_proj_ra2ll_fast — parity tests for the in-process replacement of
the `proj_ra2ll` subprocess chain used inside utils/geocode.

Strategy
--------
The reference oracle is the existing `proj_ra2ll` script (utils/proj_ra2ll),
which itself shells out to `gmt grd2xyz | gmt grdtrack | gmt gmtconvert |
gmt blockmedian | gmt xyz2grd`. We run that pipeline on a real RS2 grid
(corr.grd) and assert that `proj_ra2ll_fast(...)` produces a bit-equal
output `_ll.grd` file. Cache reuse across multiple files is also exercised
to make sure the m2s.csh + gmtinfo cache doesn't corrupt later files.

Skips gracefully (does NOT silently pass) if:
- `gmt` / `proj_ra2ll` / `m2s.csh` aren't on PATH.
- The RS2 work dir
  /home/utig5/dliu/gmtsar/gmtsar/python/work/python_test/RS2_SLC_Hawaii/intf/
  is not present.
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

_UTILS = Path(__file__).resolve().parent.parent.parent / "utils"
sys.path.insert(0, str(_UTILS))

try:
    import xarray as xr  # noqa: F401
except ImportError:
    xr = None

try:
    from proj_ra2ll_lib import (
        proj_ra2ll_fast,
        _bilinear_lookup,
        _read_grd,
        _region_from_corr_extent,
    )
    _HAVE_LIB = True
except ImportError:
    _HAVE_LIB = False


_WORK_ROOT = Path(
    os.environ.get("GMTSAR_TEST_WORK")
    or (os.environ.get("GMTSAR", "") + "/gmtsar/python/work"
        if os.environ.get("GMTSAR") else "")
    or str(Path(__file__).resolve().parents[2] / "work")
)
_RS2_INTF = Path(os.environ.get(
    "PROJ_RA2LL_TEST_INTF",
    str(_WORK_ROOT / "python_test/RS2_SLC_Hawaii/intf/2011134_2011230"),
))


def _have_binary(name: str) -> bool:
    return shutil.which(name) is not None


def _have_real_test_data() -> bool:
    """Return True only if every input grd resolves to a real file
    (resolve() follows symlinks; bare existence isn't enough — sweep.sh
    can leave broken symlinks while it's mid-flight)."""
    needed = ("corr.grd", "phasefilt.grd", "phase_mask.grd",
              "display_amp.grd", "trans.dat")
    if not _RS2_INTF.is_dir():
        return False
    for f in needed:
        p = (_RS2_INTF / f).resolve()
        if not p.is_file():
            return False
    return True


@unittest.skipUnless(_HAVE_LIB and xr is not None,
                     "proj_ra2ll_lib or xarray not importable")
class TestBilinearVsGrdtrack(unittest.TestCase):
    """Verify the numpy bilinear lookup matches `gmt grdtrack -nl`
    bit-for-bit (float32) on a real raln/ralt cache from RS2 data."""

    @classmethod
    def setUpClass(cls):
        if not _have_real_test_data():
            raise unittest.SkipTest("RS2 work dir not present")
        if not (_have_binary("gmt") and _have_binary("proj_ra2ll")):
            raise unittest.SkipTest("gmt / proj_ra2ll not on PATH")

        cls.tmp = tempfile.mkdtemp(prefix="proj_ra2ll_test_")
        # Symlink inputs (use canonicalised abspaths to dodge ../../topo)
        for f in ("corr.grd", "trans.dat", "gauss_100"):
            src = (_RS2_INTF / f).resolve()
            if src.exists():
                os.symlink(src, os.path.join(cls.tmp, f))
        # Seed raln/ralt by running the original proj_ra2ll on corr.grd
        subprocess.run(["proj_ra2ll", "trans.dat", "corr.grd", "_seed.grd"],
                       cwd=cls.tmp, check=False, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_bilinear_matches_grdtrack(self):
        cwd = os.getcwd()
        try:
            os.chdir(self.tmp)
            subprocess.run("gmt grd2xyz corr.grd -s -bo3f > rap",
                           shell=True, check=True)
            subprocess.run(
                "gmt grdtrack rap -nl -bi3f -bo5f -Graln.grd -Gralt.grd | "
                "gmt gmtconvert -bi5f -bo3f -o3,4,2 > llp_ref",
                shell=True, check=True)
            rap = np.fromfile("rap", dtype=np.float32).reshape(-1, 3)
            ref = np.fromfile("llp_ref", dtype=np.float32).reshape(-1, 3)

            raln, rln_x, rln_y = _read_grd("raln.grd")
            ralt, ralt_x, ralt_y = _read_grd("ralt.grd")
            my_lon = _bilinear_lookup(raln, rln_x, rln_y, rap[:, 0], rap[:, 1])
            my_lat = _bilinear_lookup(ralt, ralt_x, ralt_y, rap[:, 0], rap[:, 1])

            # Bit-exact in float32 — bilinear interp done in float64 then
            # cast to float32, matching GMT grdtrack's internal precision.
            self.assertTrue(np.array_equal(my_lon, ref[:, 0]),
                            f"lon mismatch: max diff "
                            f"{np.abs(my_lon - ref[:, 0]).max()}")
            self.assertTrue(np.array_equal(my_lat, ref[:, 1]),
                            f"lat mismatch: max diff "
                            f"{np.abs(my_lat - ref[:, 1]).max()}")
        finally:
            os.chdir(cwd)


@unittest.skipUnless(_HAVE_LIB and xr is not None,
                     "proj_ra2ll_lib or xarray not importable")
class TestProjRa2llFastVsSubprocess(unittest.TestCase):
    """Parity test: proj_ra2ll_fast produces the same *_ll.grd as the
    `proj_ra2ll` subprocess chain, on every file geocode hands it."""

    FILES = [
        ("corr.grd", "corr_ll.grd"),
        ("phasefilt.grd", "phasefilt_ll.grd"),
        ("phase_mask.grd", "phase_mask_ll.grd"),
        ("display_amp.grd", "display_amp_ll.grd"),
        ("phasefilt_mask.grd", "phasefilt_mask_ll.grd"),
    ]

    @classmethod
    def setUpClass(cls):
        if not _have_real_test_data():
            raise unittest.SkipTest("RS2 work dir not present")
        if not (_have_binary("gmt") and _have_binary("proj_ra2ll")
                and _have_binary("m2s.csh")):
            raise unittest.SkipTest("gmt / proj_ra2ll / m2s.csh not on PATH")
        # phasefilt_mask.grd may not exist as an input — geocode creates it
        # from phasefilt × mask2. For the test, fall back to phasefilt.grd
        # as a stand-in if missing.
        cls.tmp = tempfile.mkdtemp(prefix="proj_ra2ll_test_")
        for f, _ in cls.FILES:
            src_candidates = [_RS2_INTF / f, _RS2_INTF / "phasefilt.grd"]
            for c in src_candidates:
                c = c.resolve()
                if c.exists():
                    dst = os.path.join(cls.tmp, f)
                    if not os.path.exists(dst):
                        os.symlink(c, dst)
                    break
        for f in ("trans.dat", "gauss_100"):
            src = (_RS2_INTF / f).resolve()
            if src.exists():
                os.symlink(src, os.path.join(cls.tmp, f))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_all_files_bit_exact(self):
        cwd = os.getcwd()
        try:
            os.chdir(self.tmp)
            # Reference run via subprocess proj_ra2ll
            for inp, out in self.FILES:
                ref_out = out.replace(".grd", "_ref.grd")
                if os.path.exists(ref_out):
                    os.remove(ref_out)
                subprocess.run(["proj_ra2ll", "trans.dat", inp, ref_out],
                               check=False, capture_output=True)
            # Wipe cache to make fast path regenerate from scratch
            for f in ("raln.grd", "ralt.grd", "rap", "llp", "llpb"):
                if os.path.exists(f):
                    os.remove(f)
            cache = {}
            for inp, out in self.FILES:
                if os.path.exists(out):
                    os.remove(out)
                proj_ra2ll_fast("trans.dat", inp, out, cache=cache)

            for _, out in self.FILES:
                ref_out = out.replace(".grd", "_ref.grd")
                if not os.path.exists(ref_out):
                    self.skipTest(f"reference {ref_out} not produced; "
                                  "likely missing input")
                r = xr.open_dataarray(ref_out).values
                g = xr.open_dataarray(out).values
                self.assertEqual(r.shape, g.shape, f"{out}: shape mismatch")
                self.assertTrue(
                    np.array_equal(r, g, equal_nan=True),
                    f"{out}: not bit-exact vs subprocess proj_ra2ll")
        finally:
            os.chdir(cwd)


class TestRegionFromCorrExtent(unittest.TestCase):
    """Pure-math unit test: the region we feed `gmt surface` for raln/ralt
    must match the original `gmt gmtinfo rap -I16/32 -bi3f` rounding on
    the NON-NaN footprint of the data."""

    @staticmethod
    def _make_grid(ny, nx, x_inc, y_inc, fill_value=1.0, nan_mask=None):
        # Pixel-centered coords starting at x_inc/2 (matches GMT convention).
        x_coord = (np.arange(nx) + 0.5) * x_inc
        y_coord = (np.arange(ny) + 0.5) * y_inc
        z = np.full((ny, nx), fill_value, dtype=np.float32)
        if nan_mask is not None:
            z[nan_mask] = np.nan
        return z, x_coord, y_coord

    def test_rs2_full_coverage(self):
        # RS2 test: corr.grd (718, 854), x_inc=4, y_inc=8, no NaN
        # gmt gmtinfo on pixel centers 2..3414, 4..5740, rounded to multiples
        # of 16/32 → -R0/3424/0/5760
        z, xc, yc = self._make_grid(718, 854, 4.0, 8.0)
        r = _region_from_corr_extent(z, xc, yc)
        self.assertEqual(r, "-R0/3424/0/5760")

    def test_nan_edges_trim_region(self):
        # Critical regression test (Mira #9): when corr.grd has NaN at the
        # (r=0, a=0) edge, the region must be trimmed accordingly. csh's
        # `gmt gmtinfo rap -I16/32` rounds the min DOWN to nearest 16/32,
        # so a 20-pixel NaN strip at the start (x_inc=16) gives x_lo=320.
        z, xc, yc = self._make_grid(50, 50, 16.0, 32.0)
        # First 20 columns NaN → first valid x is at col 20, center=20*16+8=328
        z[:, :20] = np.nan
        r = _region_from_corr_extent(z, xc, yc)
        # x_min center=328 → floor(328/16)*16 = 320
        # x_max center=50*16-8=792 → ceil(792/16)*16 = 800
        # y_min center=16 → floor(16/32)*32 = 0
        # y_max center=50*32-16=1584 → ceil(1584/32)*32 = 1600
        self.assertEqual(r, "-R320/800/0/1600")

    def test_all_nan_falls_back_to_full(self):
        # Degenerate input — fall back to full grid extent so surface still
        # runs (and downstream pipeline produces a sensible empty output).
        z, xc, yc = self._make_grid(10, 10, 4.0, 32.0)
        z[:] = np.nan
        r = _region_from_corr_extent(z, xc, yc)
        # nx*x_inc=40 → ceil(40/16)*16=48; ny*y_inc=320 → ceil(320/32)*32=320
        self.assertEqual(r, "-R0/48/0/320")


if __name__ == "__main__":
    unittest.main(verbosity=2)
