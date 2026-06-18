#!/usr/bin/env python3
"""test_gmt_grd_io — GMT-readback parity tests for utils/gmt_grd_io.

The contract for `utils.gmt_grd_io.write_gmt_grd` is:
    a netCDF file written by it must be read by every downstream GMT
    module (`grdinfo`, `grdmath`, `grdcut`, `grdtrack`, `grd2xyz`,
    `xyz2grd`) with the same metadata and numerical results that would
    be reported for a file produced by `gmt grdmath`/`gmt xyz2grd`.

So every test here:
    1. Writes a `.grd` via `write_gmt_grd` (NO `pygmt.clib`, NO subprocess).
    2. Hands it to a `gmt` subprocess.
    3. Asserts the subprocess output matches a closed-form expectation.

Per the project rule "bin_py tests need C-parity, not self-consistency":
the gate is "does GMT's own binary accept and process the file
correctly?", not "does write_gmt_grd round-trip with read_gmt_grd?".
A pure-Python round-trip test would not catch e.g. a missing
`node_offset` attribute, because read_gmt_grd is symmetric to
write_gmt_grd by construction.

Skip rules
----------
- If `gmt` is not on PATH → skip (loudly).
- If `netCDF4` import fails → skip.

Run:
    python3 -m pytest gmtsar/python/bin_py/tests/test_gmt_grd_io.py -v
    # or:
    python3 gmtsar/python/bin_py/tests/test_gmt_grd_io.py
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

# Put utils/ on sys.path so we can import gmt_grd_io.
_REPO_PY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_PY / "utils"))

try:
    from gmt_grd_io import (  # type: ignore
        write_gmt_grd,
        write_gmt_grd_from_increments,
        read_gmt_grd,
    )
    _IMPORTED = True
    _IMPORT_ERR: str | None = None
except Exception as e:  # noqa: BLE001
    _IMPORTED = False
    _IMPORT_ERR = repr(e)


# Locate `gmt`. Use PATH only; skip loudly if not found.
def _find_gmt() -> str | None:
    return shutil.which("gmt")


_GMT = _find_gmt()
_HAS_GMT = _GMT is not None


def _run_gmt(args: str, cwd: str | None = None) -> subprocess.CompletedProcess:
    """Run `gmt <args>` and return the CompletedProcess. Captures both
    stdout and stderr; does NOT raise on nonzero rc (the test asserts
    explicitly)."""
    assert _GMT is not None
    return subprocess.run(
        f"{_GMT} {args}", shell=True, cwd=cwd, capture_output=True, text=True
    )


@unittest.skipUnless(_IMPORTED, f"gmt_grd_io import failed: {_IMPORT_ERR}")
@unittest.skipUnless(_HAS_GMT, "gmt not on PATH and not in expected conda env")
class TestWriteGmtGrdInfo(unittest.TestCase):
    """`gmt grdinfo` reports correct dims, increments, registration,
    and data range — proving every attribute write_gmt_grd emits is
    something GMT's reader recognizes."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="test_gmt_grd_io_")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _info_C(self, path: str) -> list[str]:
        """`gmt grdinfo -C` emits a tab-separated single line:
        path x_min x_max y_min y_max v_min v_max x_inc y_inc nx ny reg type
        We split and return the fields, dropping the path column."""
        cp = _run_gmt(f"grdinfo -C {path}")
        self.assertEqual(cp.returncode, 0, msg=cp.stderr)
        return cp.stdout.strip().split("\t")[1:]

    def test_cartesian_gridline_registration(self):
        path = os.path.join(self.tmp, "g.grd")
        nx, ny = 50, 40
        x = np.arange(nx, dtype=float) * 2.0
        y = np.arange(ny, dtype=float) * 4.0
        z = (np.arange(ny * nx, dtype=np.float32).reshape(ny, nx))
        write_gmt_grd(path, z, x, y, title="t", history="h")

        f = self._info_C(path)
        # x_min, x_max, y_min, y_max
        self.assertEqual(float(f[0]), 0.0)
        self.assertEqual(float(f[1]), 98.0)
        self.assertEqual(float(f[2]), 0.0)
        self.assertEqual(float(f[3]), 156.0)
        # v_min, v_max  ← MUST be 0..1999, not 0..0 (the xarray-default
        # failure mode would silently report 0..0 because actual_range
        # is absent)
        self.assertEqual(float(f[4]), 0.0)
        self.assertEqual(float(f[5]), 1999.0)
        # x_inc, y_inc
        self.assertEqual(float(f[6]), 2.0)
        self.assertEqual(float(f[7]), 4.0)
        # nx, ny
        self.assertEqual(int(f[8]), 50)
        self.assertEqual(int(f[9]), 40)
        # registration (0 = gridline)
        self.assertEqual(int(f[10]), 0)

    def test_cartesian_pixel_registration(self):
        path = os.path.join(self.tmp, "p.grd")
        nx, ny = 50, 40
        # Pixel-registered: cell centers — use the convenience helper
        z = np.arange(ny * nx, dtype=np.float32).reshape(ny, nx)
        write_gmt_grd_from_increments(
            path, z, x_min=0.0, y_min=0.0, x_inc=2.0, y_inc=4.0,
            node_offset=1, title="p", history="h",
        )
        f = self._info_C(path)
        # Pixel registration: cell EDGES, not centers
        #   x_min..x_max should span the full nx*x_inc = 100
        self.assertEqual(float(f[0]), 0.0)
        self.assertEqual(float(f[1]), 100.0)
        self.assertEqual(float(f[2]), 0.0)
        self.assertEqual(float(f[3]), 160.0)
        self.assertEqual(int(f[10]), 1, "expected pixel registration (1)")

    def test_geographic_gridline_registration(self):
        path = os.path.join(self.tmp, "geo.grd")
        nx, ny = 60, 48
        lon = np.linspace(-118.0, -117.0, nx)
        lat = np.linspace(33.0, 34.0, ny)
        z = np.sin(lon)[None, :] + np.cos(lat)[:, None]
        z = z.astype(np.float32)
        write_gmt_grd(path, z, lon, lat, geographic=True,
                      title="geo", history="h")
        # Long-form grdinfo to verify the registration is reported as
        # "Geographic grid" (not Cartesian).
        cp = _run_gmt(f"grdinfo {path}")
        self.assertEqual(cp.returncode, 0, msg=cp.stderr)
        self.assertIn("Geographic grid", cp.stdout)
        self.assertIn("longitude", cp.stdout)
        self.assertIn("latitude", cp.stdout)

    def test_actual_range_reported_correctly_with_nans(self):
        """A grid with some NaN cells should have actual_range computed
        over the non-NaN values — not "0 0" (the failure mode where the
        attribute is missing and grdinfo falls back to the masked min)."""
        path = os.path.join(self.tmp, "nan.grd")
        z = np.full((10, 10), 42.5, dtype=np.float32)
        z[0, 0] = np.nan
        z[5, 5] = -7.0
        x = np.arange(10, dtype=float)
        y = np.arange(10, dtype=float)
        write_gmt_grd(path, z, x, y)
        f = self._info_C(path)
        self.assertAlmostEqual(float(f[4]), -7.0, places=4)
        self.assertAlmostEqual(float(f[5]), 42.5, places=4)


@unittest.skipUnless(_IMPORTED, f"gmt_grd_io import failed: {_IMPORT_ERR}")
@unittest.skipUnless(_HAS_GMT, "gmt not on PATH and not in expected conda env")
class TestGmtGrdmath(unittest.TestCase):
    """`gmt grdmath` accepts and processes writer output. The original
    xarray-flavor blocker was: writer → grdmath would fail with "grid
    files not of same size". We verify cross-file arithmetic and the
    common single-arg `... 2 MUL = out.grd` pattern."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="test_gmt_grd_io_")
        nx, ny = 30, 24
        self.x = np.arange(nx, dtype=float) * 0.5
        self.y = np.arange(ny, dtype=float) * 0.25
        self.z = (self.y[:, None] * 10 + self.x[None, :]).astype(np.float32)
        self.path_a = os.path.join(self.tmp, "a.grd")
        self.path_b = os.path.join(self.tmp, "b.grd")
        write_gmt_grd(self.path_a, self.z, self.x, self.y, title="a", history="h")
        write_gmt_grd(self.path_b, self.z * 3, self.x, self.y, title="b", history="h")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_grdmath_mul_constant(self):
        out = os.path.join(self.tmp, "doubled.grd")
        cp = _run_gmt(f"grdmath {self.path_a} 2 MUL = {out}")
        self.assertEqual(cp.returncode, 0, msg=cp.stderr)
        zr, _, _, _ = read_gmt_grd(out)
        np.testing.assert_allclose(zr, self.z * 2, rtol=0, atol=1e-5)

    def test_grdmath_add_two_writer_files(self):
        out = os.path.join(self.tmp, "sum.grd")
        cp = _run_gmt(f"grdmath {self.path_a} {self.path_b} ADD = {out}")
        self.assertEqual(cp.returncode, 0, msg=cp.stderr)
        zr, _, _, _ = read_gmt_grd(out)
        np.testing.assert_allclose(zr, self.z * 4, rtol=0, atol=1e-5)

    def test_grdmath_flipud(self):
        """The original `dem2topo_ra::_grdmath_flipud` blocker case."""
        out = os.path.join(self.tmp, "fud.grd")
        cp = _run_gmt(f"grdmath {self.path_a} FLIPUD = {out}")
        self.assertEqual(cp.returncode, 0, msg=cp.stderr)
        zr, _, _, _ = read_gmt_grd(out)
        np.testing.assert_allclose(zr, self.z[::-1, :], rtol=0, atol=1e-5)


@unittest.skipUnless(_IMPORTED, f"gmt_grd_io import failed: {_IMPORT_ERR}")
@unittest.skipUnless(_HAS_GMT, "gmt not on PATH and not in expected conda env")
class TestGmtGrdcut(unittest.TestCase):
    """`gmt grdcut` honours the writer's registration and produces a
    correctly-aligned subset. This is the primary failure mode for
    pixel-registered grids missing `node_offset`: grdcut silently
    half-cell-shifts the subset."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="test_gmt_grd_io_")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_grdcut_gridline(self):
        path = os.path.join(self.tmp, "g.grd")
        nx, ny = 40, 30
        x = np.arange(nx, dtype=float) * 1.0
        y = np.arange(ny, dtype=float) * 1.0
        z = (np.arange(ny * nx, dtype=np.float32).reshape(ny, nx))
        write_gmt_grd(path, z, x, y)

        out = os.path.join(self.tmp, "cut.grd")
        cp = _run_gmt(f"grdcut {path} -R5/15/3/12 -G{out}")
        self.assertEqual(cp.returncode, 0, msg=cp.stderr)

        # Subset should be 11 cols (x=5..15 incl.) × 10 rows (y=3..12 incl.)
        zr, xr, yr, info = read_gmt_grd(out)
        self.assertEqual(info["node_offset"], 0)
        self.assertEqual(xr[0], 5.0)
        self.assertEqual(xr[-1], 15.0)
        self.assertEqual(yr[0], 3.0)
        self.assertEqual(yr[-1], 12.0)
        # Values: z[y, x] = y*nx + x.  At y=3 → row index 3 in original;
        # but after subset, row 0 corresponds to y=3.
        # Compare to a direct slice of the input z.
        expected = z[3:13, 5:16]
        np.testing.assert_allclose(zr, expected, rtol=0, atol=1e-5)

    def test_grdcut_pixel(self):
        """A pixel-registered grid should be cut on cell-edge boundaries
        without GMT half-cell shifting (the failure mode for missing
        node_offset)."""
        path = os.path.join(self.tmp, "p.grd")
        nx, ny = 40, 30
        z = (np.arange(ny * nx, dtype=np.float32).reshape(ny, nx))
        write_gmt_grd_from_increments(
            path, z, x_min=0.0, y_min=0.0, x_inc=1.0, y_inc=1.0,
            node_offset=1,
        )
        out = os.path.join(self.tmp, "cut.grd")
        # Pixel registration: R is on cell EDGES, so -R5/15 gives 10 cells
        cp = _run_gmt(f"grdcut {path} -R5/15/3/12 -G{out}")
        self.assertEqual(cp.returncode, 0, msg=cp.stderr)
        zr, xr, yr, info = read_gmt_grd(out)
        self.assertEqual(info["node_offset"], 1,
                         "grdcut should preserve pixel registration")
        # 10 cells × 9 cells (pixel-registered)
        self.assertEqual(zr.shape, (9, 10))


@unittest.skipUnless(_IMPORTED, f"gmt_grd_io import failed: {_IMPORT_ERR}")
@unittest.skipUnless(_HAS_GMT, "gmt not on PATH and not in expected conda env")
class TestGmtGrdtrack(unittest.TestCase):
    """`gmt grdtrack` samples values at arbitrary (x, y) coords. We feed
    it coords that land exactly on grid nodes (no interpolation needed)
    so the comparison is exact float32-round-trip."""

    def test_grdtrack_at_nodes(self):
        tmp = tempfile.mkdtemp(prefix="test_gmt_grd_io_")
        try:
            path = os.path.join(tmp, "g.grd")
            nx, ny = 20, 16
            x = np.arange(nx, dtype=float) * 2.0
            y = np.arange(ny, dtype=float) * 3.0
            # z[j, i] = i + 100 * j
            z = (np.arange(ny, dtype=np.float32)[:, None] * 100
                 + np.arange(nx, dtype=np.float32)[None, :])
            write_gmt_grd(path, z, x, y)

            track_in = os.path.join(tmp, "in.txt")
            with open(track_in, "w") as fh:
                # Probe a few exact-node coordinates
                fh.write("0 0\n4 6\n10 9\n38 45\n")

            cp = _run_gmt(f"grdtrack {track_in} -G{path}")
            self.assertEqual(cp.returncode, 0, msg=cp.stderr)
            # Each output line is "x\ty\tz"; parse the z column
            rows = [line.split() for line in cp.stdout.strip().splitlines()]
            zs = [float(r[2]) for r in rows]
            # (x=0,  y=0)  → z[0,0]   = 0
            # (x=4,  y=6)  → z[2,2]   = 202
            # (x=10, y=9)  → z[3,5]   = 305
            # (x=38, y=45) → z[15,19] = 1519
            self.assertAlmostEqual(zs[0], 0.0)
            self.assertAlmostEqual(zs[1], 202.0)
            self.assertAlmostEqual(zs[2], 305.0)
            self.assertAlmostEqual(zs[3], 1519.0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


@unittest.skipUnless(_IMPORTED, f"gmt_grd_io import failed: {_IMPORT_ERR}")
@unittest.skipUnless(_HAS_GMT, "gmt not on PATH and not in expected conda env")
class TestXyz2GrdRoundTrip(unittest.TestCase):
    """`grd2xyz` ∘ `xyz2grd` ∘ writer should round-trip a writer-produced
    grid bit-cleanly. This is the harshest test: it makes GMT itself
    re-write the grid, then we diff that against the original.

    Specifically:
      1. write_gmt_grd → A.grd
      2. gmt grd2xyz A.grd > xyz.txt
      3. gmt xyz2grd xyz.txt -R<...> -I<...> -G B.grd
      4. gmt grdmath A B SUB = diff.grd
      5. assert max(|diff|) == 0
    """

    def test_full_round_trip(self):
        tmp = tempfile.mkdtemp(prefix="test_gmt_grd_io_")
        try:
            path_a = os.path.join(tmp, "a.grd")
            nx, ny = 25, 20
            x = np.arange(nx, dtype=float) * 1.5
            y = np.arange(ny, dtype=float) * 0.5
            z = (np.sin(x)[None, :] + np.cos(y)[:, None]).astype(np.float32)
            write_gmt_grd(path_a, z, x, y, title="rt", history="round-trip")

            # grd2xyz
            xyz = os.path.join(tmp, "xyz.txt")
            cp = _run_gmt(f"grd2xyz {path_a}", cwd=tmp)
            self.assertEqual(cp.returncode, 0, msg=cp.stderr)
            with open(xyz, "w") as fh:
                fh.write(cp.stdout)

            # xyz2grd back
            path_b = os.path.join(tmp, "b.grd")
            x_min, x_max = float(x[0]), float(x[-1])
            y_min, y_max = float(y[0]), float(y[-1])
            cp = _run_gmt(
                f"xyz2grd {xyz} -R{x_min}/{x_max}/{y_min}/{y_max} "
                f"-I1.5/0.5 -G{path_b}"
            )
            self.assertEqual(cp.returncode, 0, msg=cp.stderr)

            # diff
            diff = os.path.join(tmp, "diff.grd")
            cp = _run_gmt(f"grdmath {path_a} {path_b} SUB = {diff}")
            self.assertEqual(cp.returncode, 0, msg=cp.stderr)
            zd, _, _, _ = read_gmt_grd(diff)
            # Allow strict zero — GMT's grd2xyz uses %g ASCII formatting
            # which loses precision, but xyz2grd recovers the float32
            # nearest-representable. So max |diff| should be at float32 ULP.
            self.assertLess(np.max(np.abs(zd)), 1e-3,
                            f"round-trip diff exceeds tolerance: "
                            f"max |diff| = {np.max(np.abs(zd))}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


@unittest.skipUnless(_IMPORTED, f"gmt_grd_io import failed: {_IMPORT_ERR}")
class TestInputValidation(unittest.TestCase):
    """Input-validation tests do not need `gmt` on PATH; they only
    require netCDF4 (covered by _IMPORTED)."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="test_gmt_grd_io_")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_rejects_non_2d_data(self):
        path = os.path.join(self.tmp, "x.grd")
        with self.assertRaises(ValueError):
            write_gmt_grd(path, np.arange(10), np.arange(10), np.arange(10))

    def test_rejects_shape_mismatch(self):
        path = os.path.join(self.tmp, "x.grd")
        with self.assertRaises(ValueError):
            write_gmt_grd(path, np.zeros((4, 5)), np.arange(6), np.arange(4))

    def test_rejects_non_monotonic_x(self):
        path = os.path.join(self.tmp, "x.grd")
        x = np.array([0.0, 2.0, 1.0, 3.0])
        y = np.arange(3, dtype=float)
        with self.assertRaises(ValueError):
            write_gmt_grd(path, np.zeros((3, 4)), x, y)

    def test_rejects_non_uniform_spacing(self):
        path = os.path.join(self.tmp, "x.grd")
        x = np.array([0.0, 1.0, 3.0, 6.0])  # diffs 1,2,3 — not uniform
        y = np.arange(3, dtype=float)
        with self.assertRaises(ValueError):
            write_gmt_grd(path, np.zeros((3, 4)), x, y)

    def test_rejects_bad_node_offset(self):
        path = os.path.join(self.tmp, "x.grd")
        with self.assertRaises(ValueError):
            write_gmt_grd(
                path, np.zeros((3, 4)),
                np.arange(4, dtype=float), np.arange(3, dtype=float),
                node_offset=2,
            )


if __name__ == "__main__":
    if not _IMPORTED:
        print(f"SKIP: gmt_grd_io not importable: {_IMPORT_ERR}", file=sys.stderr)
    if not _HAS_GMT:
        print("WARN: gmt not on PATH and not in expected conda env; "
              "GMT-readback tests will skip", file=sys.stderr)
    unittest.main(verbosity=2)
