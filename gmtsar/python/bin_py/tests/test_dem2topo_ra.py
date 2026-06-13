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


# ---------------------------------------------------------------------------
# Mira #30 — wire-in parity tests for utils/dem2topo_ra
#
# These tests exercise the LIVE production script `utils/dem2topo_ra`
# (not the bin_py exploratory port above), specifically the
# `_grdmath_flipud` function that was wired in to replace the
# `gmt grdmath pixel.grd FLIPUD = topo_ra.grd` subprocess.
#
# The pattern follows /home/staff/dliu/.claude memory rule:
#   "bin_py tests need C-parity, not self-consistency".
# We invoke real `gmt grdmath ... FLIPUD = ...` on the same input
# grid and assert the in-process output is bit-identical (data-array
# byte-equal); grid metadata (Command, history, chunking) is allowed
# to differ — that's documented behavior of the writer-flavor netCDF.
# ---------------------------------------------------------------------------

import shutil
import subprocess


_UTILS_DEM2TOPO_RA = _HERE.parent.parent / "utils" / "dem2topo_ra"
_UTILS_NS: dict = {"__file__": str(_UTILS_DEM2TOPO_RA),
                   "__name__": "utils_dem2topo_ra_module"}
# Need utils/ on sys.path so the script's `from gmtsar_lib import *` works.
sys.path.insert(0, str(_UTILS_DEM2TOPO_RA.parent))
try:
    exec(compile(_UTILS_DEM2TOPO_RA.read_text(), str(_UTILS_DEM2TOPO_RA), "exec"),
         _UTILS_NS)
    _UTILS_IMPORT_OK = True
    _UTILS_IMPORT_ERR = None
except Exception as _exc:
    _UTILS_IMPORT_OK = False
    _UTILS_IMPORT_ERR = repr(_exc)


_GMT_CANDIDATES = [
    "/home/staff/dliu/anaconda3/envs/gmtsar/bin/gmt",
    shutil.which("gmt") or "",
]
_GMT = next((g for g in _GMT_CANDIDATES if g and os.path.exists(g)), "")


@unittest.skipUnless(_UTILS_IMPORT_OK,
                     f"utils/dem2topo_ra import failed: {_UTILS_IMPORT_ERR}")
@unittest.skipUnless(_GMT,
                     "gmt binary not found — parity test cannot run")
class TestWiredFlipudParity(unittest.TestCase):
    """In-process FLIPUD produces bit-identical data to `gmt grdmath`.

    Mira #30 (2026-05-21): the wire-in in `utils/dem2topo_ra`'s
    `_grdmath_flipud` replaces `gmt grdmath pixel.grd FLIPUD =
    topo_ra.grd` with a pure-Python read → np.flipud → write_gmt_grd
    chain. This test asserts the replacement is byte-identical at the
    data-array level on a pixel-registered grid (matching what
    `gmt surface ... -r -G pixel.grd` produces in the pipeline).
    """

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="test_wired_flipud_")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_pixel_reg_grid(self, path: str, nx: int = 64, ny: int = 48):
        """Build a pixel-registered .grd file using gmt's own xyz2grd —
        guarantees the registration metadata mirrors what `gmt surface`
        would write into pixel.grd in the dem2topo_ra pipeline."""
        # Generate xyz triplets at cell centres of a (nx x ny) pixel grid
        # spanning [0..2*nx] x [0..2*ny] with z = j*nx + i.
        rng = np.random.default_rng(42)
        x_centres = 0.5 * 2.0 + 2.0 * np.arange(nx)  # 1, 3, 5, ...
        y_centres = 0.5 * 2.0 + 2.0 * np.arange(ny)
        xx, yy = np.meshgrid(x_centres, y_centres)
        zz = (yy * nx + xx + 100.0 * rng.standard_normal(xx.shape)).astype(np.float64)
        xyz_path = os.path.join(self.tmp, "src.xyz")
        np.column_stack([xx.ravel(), yy.ravel(), zz.ravel()]).tofile(xyz_path)
        rg = f"0/{2*nx}/0/{2*ny}"
        cp = subprocess.run(
            [_GMT, "xyz2grd", xyz_path, f"-R{rg}", "-I2/2", "-bi3d", "-r",
             f"-G{path}"],
            stderr=subprocess.PIPE, check=False)
        if cp.returncode != 0:
            raise RuntimeError(
                f"gmt xyz2grd failed: {cp.stderr.decode(errors='replace')}")

    def test_data_byte_identical_on_pixel_reg_grid(self):
        src = os.path.join(self.tmp, "src.grd")
        out_gmt = os.path.join(self.tmp, "gmt.grd")
        out_py = os.path.join(self.tmp, "py.grd")
        self._make_pixel_reg_grid(src, nx=64, ny=48)

        # Path A: gmt grdmath subprocess
        cp = subprocess.run(
            [_GMT, "grdmath", src, "FLIPUD", "=", out_gmt],
            stderr=subprocess.PIPE, check=False)
        self.assertEqual(cp.returncode, 0,
                         msg=cp.stderr.decode(errors='replace'))

        # Path B: in-process wire (the production fast path)
        _UTILS_NS["_grdmath_flipud"](src, out_py)

        # Compare the z data arrays byte-by-byte
        import netCDF4
        with netCDF4.Dataset(out_gmt) as da, netCDF4.Dataset(out_py) as db:
            za = da.variables["z"][:]
            zb = db.variables["z"][:]
        if hasattr(za, "mask"):
            za = np.ma.filled(za, np.nan).astype(np.float32)
        if hasattr(zb, "mask"):
            zb = np.ma.filled(zb, np.nan).astype(np.float32)
        self.assertEqual(za.shape, zb.shape,
                         msg=f"shape mismatch: {za.shape} vs {zb.shape}")
        self.assertTrue(
            np.array_equal(za, zb, equal_nan=True),
            msg=f"FLIPUD data not byte-identical; max|d|={np.nanmax(np.abs(za-zb))}",
        )

    def test_pixel_registration_preserved(self):
        """The in-process path must propagate node_offset=1 so that
        downstream grdcut/grdsample don't half-cell-shift."""
        src = os.path.join(self.tmp, "src.grd")
        out_py = os.path.join(self.tmp, "py.grd")
        self._make_pixel_reg_grid(src, nx=32, ny=24)
        _UTILS_NS["_grdmath_flipud"](src, out_py)
        # grdinfo should report "Pixel node registration"
        cp = subprocess.run([_GMT, "grdinfo", out_py],
                            stdout=subprocess.PIPE, check=True)
        out = cp.stdout.decode()
        self.assertIn("Pixel node registration", out,
                      msg=f"node_offset not preserved; grdinfo:\n{out}")

    def test_fallback_when_inproc_disabled(self):
        """GMTSAR_GMT_INPROC=0 must fall through to the gmt subprocess
        path (debug A/B switch)."""
        src = os.path.join(self.tmp, "src.grd")
        out = os.path.join(self.tmp, "fallback.grd")
        self._make_pixel_reg_grid(src, nx=16, ny=12)
        old = os.environ.get("GMTSAR_GMT_INPROC")
        os.environ["GMTSAR_GMT_INPROC"] = "0"
        try:
            _UTILS_NS["_grdmath_flipud"](src, out)
        finally:
            if old is None:
                del os.environ["GMTSAR_GMT_INPROC"]
            else:
                os.environ["GMTSAR_GMT_INPROC"] = old
        # The fallback writes a canonical gmt grdmath output — Command
        # field should match exactly
        cp = subprocess.run([_GMT, "grdinfo", out], stdout=subprocess.PIPE,
                            check=True)
        info = cp.stdout.decode()
        self.assertIn("gmt grdmath", info,
                      msg=f"fallback didn't run gmt grdmath; grdinfo:\n{info}")
        self.assertNotIn("[gmt_grd_io in-process]", info,
                         msg=f"in-process marker leaked into fallback")


# ---------------------------------------------------------------------------
# In-memory chain wire-in parity tests (Mira, 2026-05-22).
#
# Exercises the surface → FLIPUD chain when
# GMTSAR_DEM2TOPO_INMEM_CHAIN=1 is set. The chain stashes the
# surface'd grid in a process-global dict instead of writing
# pixel.grd to disk; _grdmath_flipud consumes the stash directly
# and writes only topo_ra.grd.
#
# Byte-identity check: chain vs no-chain (with GMTSAR_SURFACE_INPROC=1
# in both, so the upstream is identical Python).
# ---------------------------------------------------------------------------


@unittest.skipUnless(_UTILS_IMPORT_OK,
                     f"utils/dem2topo_ra import failed: {_UTILS_IMPORT_ERR}")
class TestInmemChainParity(unittest.TestCase):
    """Chain path (GMTSAR_DEM2TOPO_INMEM_CHAIN=1) produces a topo_ra.grd
    byte-identical at the data-array level to the no-chain in-process
    path (env unset). Both use GMTSAR_SURFACE_INPROC=1.

    The chain only fires on the safe surface → FLIPUD path (mode=0,
    RR empty). We unit-test the wire by directly invoking
    `_surface_inproc(chainable=True)` followed by `_grdmath_flipud`.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="test_inmem_chain_")
        # Save and clear chain env to start each test from a known state
        self._old_chain = os.environ.get("GMTSAR_DEM2TOPO_INMEM_CHAIN")
        self._old_inproc = os.environ.get("GMTSAR_GMT_INPROC")
        if self._old_chain is not None:
            del os.environ["GMTSAR_DEM2TOPO_INMEM_CHAIN"]
        # Make sure the FLIPUD step uses the in-proc reader (default)
        if self._old_inproc is not None:
            del os.environ["GMTSAR_GMT_INPROC"]
        # Clear the carrier dict between tests
        _UTILS_NS["_PENDING_INMEM_GRID"].clear()

    def tearDown(self) -> None:
        if self._old_chain is None:
            os.environ.pop("GMTSAR_DEM2TOPO_INMEM_CHAIN", None)
        else:
            os.environ["GMTSAR_DEM2TOPO_INMEM_CHAIN"] = self._old_chain
        if self._old_inproc is None:
            os.environ.pop("GMTSAR_GMT_INPROC", None)
        else:
            os.environ["GMTSAR_GMT_INPROC"] = self._old_inproc
        _UTILS_NS["_PENDING_INMEM_GRID"].clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_temp_rat(self, path: str, region, inc, n_per_dim=12) -> None:
        """Write a synthetic temp.rat (binary 3-double) covering the
        region with a smooth z = sin(x/100)*cos(y/100)*1000 surface.
        This mimics what `gmt blockmedian -bo3d` would emit."""
        x0, x1, y0, y1 = region
        dx, dy = inc
        # Sample on a coarse grid of n_per_dim points per dim
        xs = np.linspace(x0 + dx, x1 - dx, n_per_dim)
        ys = np.linspace(y0 + dy, y1 - dy, n_per_dim)
        xx, yy = np.meshgrid(xs, ys)
        zz = np.sin(xx / 100.0) * np.cos(yy / 100.0) * 1000.0
        rows = np.column_stack([xx.ravel(), yy.ravel(), zz.ravel()])
        rows.astype(np.float64).tofile(path)

    def test_chain_byte_identical_to_no_chain(self):
        """topo_ra.grd from chained path == topo_ra.grd from un-chained
        path (data array byte-equal)."""
        region = (0, 480, 0, 800)
        inc = (1, 2)
        temp_rat = os.path.join(self.tmp, "temp.rat")
        self._make_temp_rat(temp_rat, region, inc)

        region_str = "0/480/0/800"

        # --- Path A: no chain (write pixel.grd, then in-proc FLIPUD reads it)
        pixel_a = os.path.join(self.tmp, "pixel_a.grd")
        out_a = os.path.join(self.tmp, "topo_a.grd")
        _UTILS_NS["_surface_inproc"](
            temp_rat, region_str, 1, 2, 0.1, pixel_a, chainable=False)
        self.assertTrue(os.path.exists(pixel_a),
                        msg="no-chain path must write pixel.grd to disk")
        _UTILS_NS["_grdmath_flipud"](pixel_a, out_a)

        # --- Path B: chain (skip pixel.grd write; FLIPUD consumes stash)
        os.environ["GMTSAR_DEM2TOPO_INMEM_CHAIN"] = "1"
        pixel_b = os.path.join(self.tmp, "pixel_b.grd")
        out_b = os.path.join(self.tmp, "topo_b.grd")
        _UTILS_NS["_surface_inproc"](
            temp_rat, region_str, 1, 2, 0.1, pixel_b, chainable=True)
        # In chained mode, pixel.grd must NOT have been written
        self.assertFalse(
            os.path.exists(pixel_b),
            msg="chained path must NOT write pixel.grd to disk")
        # And the stash must contain it
        self.assertIn(
            pixel_b, _UTILS_NS["_PENDING_INMEM_GRID"],
            msg="chained path must stash the grid for the next FLIPUD")
        _UTILS_NS["_grdmath_flipud"](pixel_b, out_b)
        # After consumption, the stash must be drained
        self.assertNotIn(
            pixel_b, _UTILS_NS["_PENDING_INMEM_GRID"],
            msg="FLIPUD must drain the stash on consume")

        # Compare data arrays
        import netCDF4
        with netCDF4.Dataset(out_a) as da, netCDF4.Dataset(out_b) as db:
            za = da.variables["z"][:]
            zb = db.variables["z"][:]
        if hasattr(za, "mask"):
            za = np.ma.filled(za, np.nan).astype(np.float32)
        if hasattr(zb, "mask"):
            zb = np.ma.filled(zb, np.nan).astype(np.float32)
        self.assertEqual(
            za.shape, zb.shape,
            msg=f"shape mismatch: {za.shape} vs {zb.shape}")
        self.assertTrue(
            np.array_equal(za, zb, equal_nan=True),
            msg=f"chain output diverged from no-chain; "
                f"max|d|={float(np.nanmax(np.abs(za - zb)))}")

    def test_chain_default_on_means_stash_not_disk(self):
        """With GMTSAR_DEM2TOPO_INMEM_CHAIN unset (default ON since
        v2.1.28), _surface_inproc(chainable=True) stashes the grid and
        does NOT write pixel.grd to disk."""
        region = (0, 240, 0, 400)
        inc = (1, 2)
        temp_rat = os.path.join(self.tmp, "temp.rat")
        self._make_temp_rat(temp_rat, region, inc)
        pixel = os.path.join(self.tmp, "pixel.grd")
        # chainable=True, env unset → default-ON chain → stash, no disk write
        _UTILS_NS["_surface_inproc"](
            temp_rat, "0/240/0/400", 1, 2, 0.1, pixel, chainable=True)
        self.assertFalse(
            os.path.exists(pixel),
            msg="chain default-ON must not write pixel.grd to disk")
        self.assertIn(pixel, _UTILS_NS["_PENDING_INMEM_GRID"],
                      msg="chain default-ON must stash the grid")

    def test_chain_explicitly_disabled_means_disk_writes_pixel_grd(self):
        """With GMTSAR_DEM2TOPO_INMEM_CHAIN=0, _surface_inproc
        writes pixel.grd to disk even when called with chainable=True."""
        region = (0, 240, 0, 400)
        inc = (1, 2)
        temp_rat = os.path.join(self.tmp, "temp.rat")
        self._make_temp_rat(temp_rat, region, inc)
        pixel = os.path.join(self.tmp, "pixel.grd")
        os.environ["GMTSAR_DEM2TOPO_INMEM_CHAIN"] = "0"
        # chainable=True but chain explicitly disabled → should write to disk
        _UTILS_NS["_surface_inproc"](
            temp_rat, "0/240/0/400", 1, 2, 0.1, pixel, chainable=True)
        self.assertTrue(
            os.path.exists(pixel),
            msg="chain explicitly disabled must fall back to disk write")
        self.assertNotIn(pixel, _UTILS_NS["_PENDING_INMEM_GRID"],
                         msg="chain explicitly disabled must not stash")

    def test_chainable_false_means_disk_writes_pixel_grd(self):
        """Even with GMTSAR_DEM2TOPO_INMEM_CHAIN=1, chainable=False
        forces disk write (used by the RR != [] and mode=1 branches)."""
        region = (0, 240, 0, 400)
        inc = (1, 2)
        temp_rat = os.path.join(self.tmp, "temp.rat")
        self._make_temp_rat(temp_rat, region, inc)
        pixel = os.path.join(self.tmp, "pixel.grd")
        os.environ["GMTSAR_DEM2TOPO_INMEM_CHAIN"] = "1"
        _UTILS_NS["_surface_inproc"](
            temp_rat, "0/240/0/400", 1, 2, 0.1, pixel, chainable=False)
        self.assertTrue(
            os.path.exists(pixel),
            msg="chainable=False must always write to disk")
        self.assertNotIn(pixel, _UTILS_NS["_PENDING_INMEM_GRID"],
                         msg="chainable=False must not stash")


if __name__ == "__main__":
    unittest.main(verbosity=2)
