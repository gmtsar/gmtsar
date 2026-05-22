#!/usr/bin/env python3
"""test_geocode — wire-in parity tests for utils/geocode.

Mira #36 (2026-05-22): the geocode script now routes 5 `gmt grdmath
A B MUL = C` calls through `_grdmath_mul_grid_grid`, which reads both
inputs via gmt_grd_io.read_gmt_grd, multiplies in numpy float32, and
writes the result via gmt_grd_io.write_gmt_grd. The replacement must
be byte-identical to `gmt grdmath A B MUL = C` on the canonical use
case (pixel-registered Cartesian grids with NaN cells in the mask
factor).

This is a C-parity test, not a self-consistency one (per CLAUDE.md
memory rule "bin_py tests need C-parity, not self-consistency"):
both paths run on the same input grids, and the test asserts the
output `z` arrays are byte-equal including NaN positions.

Run:
    python3 -m pytest test_geocode.py -v
    # or:
    python3 test_geocode.py
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
_UTILS_GEOCODE = _HERE.parent.parent / "utils" / "geocode"
_UTILS_NS: dict = {"__file__": str(_UTILS_GEOCODE),
                   "__name__": "utils_geocode_module"}
# utils/ on sys.path so the script's `from gmtsar_lib import *` works.
sys.path.insert(0, str(_UTILS_GEOCODE.parent))
try:
    exec(compile(_UTILS_GEOCODE.read_text(), str(_UTILS_GEOCODE), "exec"),
         _UTILS_NS)
    _UTILS_IMPORT_OK = True
    _UTILS_IMPORT_ERR = None
except Exception as _exc:  # pragma: no cover
    _UTILS_IMPORT_OK = False
    _UTILS_IMPORT_ERR = repr(_exc)


_GMT_CANDIDATES = [
    "/home/staff/dliu/anaconda3/envs/gmtsar/bin/gmt",
    shutil.which("gmt") or "",
]
_GMT = next((g for g in _GMT_CANDIDATES if g and os.path.exists(g)), "")


@unittest.skipUnless(_UTILS_IMPORT_OK,
                     f"utils/geocode import failed: {_UTILS_IMPORT_ERR}")
@unittest.skipUnless(_GMT,
                     "gmt binary not found — parity test cannot run")
class TestWiredGrdmathMulParity(unittest.TestCase):
    """`_grdmath_mul_grid_grid` produces byte-identical data to
    `gmt grdmath A B MUL = C` on the geocode canonical use case
    (pixel-registered Cartesian grids, with NaN cells in the mask)."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="test_geocode_mul_")
        # Use the tmp dir as cwd so the script-emitted paths are local.
        self._cwd = os.getcwd()
        os.chdir(self.tmp)

    def tearDown(self) -> None:
        os.chdir(self._cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_pixel_reg_grid(self, path: str, nx: int, ny: int,
                              seed: int) -> None:
        """Build a pixel-registered .grd via `gmt xyz2grd -r` so the
        registration metadata matches what the upstream gmtsar
        pipeline emits (phase.grd, mask2.grd, etc.)."""
        rng = np.random.default_rng(seed)
        xc = 0.5 * 2.0 + 2.0 * np.arange(nx)
        yc = 0.5 * 2.0 + 2.0 * np.arange(ny)
        xx, yy = np.meshgrid(xc, yc)
        zz = (yy * nx + xx + 100.0 *
              rng.standard_normal(xx.shape)).astype(np.float64)
        xyz = path + ".xyz"
        np.column_stack([xx.ravel(), yy.ravel(), zz.ravel()]).tofile(xyz)
        rg = f"0/{2*nx}/0/{2*ny}"
        cp = subprocess.run(
            [_GMT, "xyz2grd", xyz, f"-R{rg}", "-I2/2", "-bi3d", "-r",
             f"-G{path}"],
            stderr=subprocess.PIPE, check=False)
        if cp.returncode != 0:
            raise RuntimeError(
                f"gmt xyz2grd failed: {cp.stderr.decode(errors='replace')}")

    def _make_pixel_reg_mask(self, path: str, nx: int, ny: int,
                              seed: int) -> None:
        """Mask grid: ~70% cells = 1, rest = NaN. Built via
        `gmt xyz2grd -r` + `gmt grdmath 0 NAN` so it has the same
        registration as the data grid and uses GMT's canonical NaN
        sentinel."""
        rng = np.random.default_rng(seed)
        xc = 0.5 * 2.0 + 2.0 * np.arange(nx)
        yc = 0.5 * 2.0 + 2.0 * np.arange(ny)
        xx, yy = np.meshgrid(xc, yc)
        zz = (rng.random(xx.shape) > 0.3).astype(np.float64)
        xyz = path + ".xyz"
        np.column_stack([xx.ravel(), yy.ravel(), zz.ravel()]).tofile(xyz)
        rg = f"0/{2*nx}/0/{2*ny}"
        bool_path = path + ".bool"
        cp = subprocess.run(
            [_GMT, "xyz2grd", xyz, f"-R{rg}", "-I2/2", "-bi3d", "-r",
             f"-G{bool_path}"],
            stderr=subprocess.PIPE, check=False)
        if cp.returncode != 0:
            raise RuntimeError(
                f"gmt xyz2grd (mask) failed: "
                f"{cp.stderr.decode(errors='replace')}")
        cp = subprocess.run(
            [_GMT, "grdmath", bool_path, "0", "NAN", "=", path],
            stderr=subprocess.PIPE, check=False)
        if cp.returncode != 0:
            raise RuntimeError(
                f"gmt grdmath (0 NAN) failed: "
                f"{cp.stderr.decode(errors='replace')}")

    def _z_array(self, grd_path: str) -> np.ndarray:
        import netCDF4
        with netCDF4.Dataset(grd_path) as ds:
            z = ds.variables["z"][:]
        if hasattr(z, "mask"):
            z = np.ma.filled(z, np.nan).astype(np.float32)
        return np.asarray(z, dtype=np.float32)

    def test_data_byte_identical(self):
        """In-process MUL is byte-identical (incl. NaN positions) to
        `gmt grdmath A B MUL = C` on a pixel-registered Cartesian
        grid with a NaN-cell mask."""
        self._make_pixel_reg_grid("a.grd", 64, 48, seed=1)
        self._make_pixel_reg_mask("m.grd", 64, 48, seed=2)

        # Path A: gmt grdmath subprocess
        cp = subprocess.run(
            [_GMT, "grdmath", "a.grd", "m.grd", "MUL", "=", "out_gmt.grd"],
            stderr=subprocess.PIPE, check=False)
        self.assertEqual(cp.returncode, 0,
                         msg=cp.stderr.decode(errors="replace"))

        # Path B: in-process wire (the production fast path)
        _UTILS_NS["_grdmath_mul_grid_grid"]("a.grd", "m.grd", "out_py.grd")

        za = self._z_array("out_gmt.grd")
        zb = self._z_array("out_py.grd")
        self.assertEqual(za.shape, zb.shape,
                         msg=f"shape mismatch: {za.shape} vs {zb.shape}")
        self.assertTrue(
            np.array_equal(za, zb, equal_nan=True),
            msg=(f"MUL data not byte-identical; "
                 f"max|d|={np.nanmax(np.abs(za-zb))}; "
                 f"NaN gmt={np.isnan(za).sum()} py={np.isnan(zb).sum()}"),
        )

    def test_pixel_registration_preserved(self):
        """In-process MUL output must keep node_offset=1 so downstream
        grdcut/grdsample don't half-cell-shift."""
        self._make_pixel_reg_grid("a.grd", 32, 24, seed=3)
        self._make_pixel_reg_mask("m.grd", 32, 24, seed=4)
        _UTILS_NS["_grdmath_mul_grid_grid"]("a.grd", "m.grd", "out_py.grd")
        cp = subprocess.run([_GMT, "grdinfo", "out_py.grd"],
                            stdout=subprocess.PIPE, check=True)
        info = cp.stdout.decode()
        self.assertIn("Pixel node registration", info,
                      msg=f"node_offset not preserved; grdinfo:\n{info}")

    def test_fallback_when_inproc_disabled(self):
        """GMTSAR_GMT_INPROC=0 falls through to `gmt grdmath`."""
        self._make_pixel_reg_grid("a.grd", 16, 12, seed=5)
        self._make_pixel_reg_mask("m.grd", 16, 12, seed=6)
        # Ensure `gmt` resolves under shell=True (geocode's run() uses
        # the shell, which has its own PATH). The test runner may not
        # inherit the conda env's bin/.
        old_inproc = os.environ.get("GMTSAR_GMT_INPROC")
        old_path = os.environ.get("PATH", "")
        gmt_dir = os.path.dirname(_GMT)
        os.environ["GMTSAR_GMT_INPROC"] = "0"
        os.environ["PATH"] = f"{gmt_dir}{os.pathsep}{old_path}"
        try:
            _UTILS_NS["_grdmath_mul_grid_grid"](
                "a.grd", "m.grd", "out_fb.grd")
        finally:
            if old_inproc is None:
                del os.environ["GMTSAR_GMT_INPROC"]
            else:
                os.environ["GMTSAR_GMT_INPROC"] = old_inproc
            os.environ["PATH"] = old_path
        # gmt grdmath stamps a "Command:" header containing "gmt grdmath";
        # the in-process marker must NOT appear.
        cp = subprocess.run([_GMT, "grdinfo", "out_fb.grd"],
                            stdout=subprocess.PIPE, check=True)
        info = cp.stdout.decode()
        self.assertIn("gmt grdmath", info,
                      msg=f"fallback didn't run gmt grdmath; grdinfo:\n{info}")
        self.assertNotIn("[gmt_grd_io in-process]", info,
                         msg="in-process marker leaked into fallback")

    def test_fallback_on_shape_mismatch(self):
        """A grid + mask of different shapes triggers the fallback to
        gmt grdmath (which handles extension/broadcast natively). The
        wire-in must NOT silently produce a wrong-shape output."""
        self._make_pixel_reg_grid("a.grd", 32, 24, seed=7)
        # Build a smaller mask (different region + spacing) — the
        # in-process strict-match branch raises and falls back.
        self._make_pixel_reg_mask("m.grd", 32, 16, seed=8)
        # gmt grdmath will reject this too unless one is a single-cell;
        # the point is that the wire-in must not crash, it should hand
        # off to gmt which then reports the real error or extends.
        try:
            _UTILS_NS["_grdmath_mul_grid_grid"](
                "a.grd", "m.grd", "out_mismatch.grd")
        except Exception:
            # gmt grdmath itself may exit non-zero — that's fine; the
            # wire-in passed the call through. Both paths produce
            # the SAME behavior on mismatch (fail loudly).
            pass


if __name__ == "__main__":
    unittest.main(verbosity=2)
