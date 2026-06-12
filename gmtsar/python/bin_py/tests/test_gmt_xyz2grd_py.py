#!/usr/bin/env python3
"""test_gmt_xyz2grd_py - C-parity test for utils/gmt_xyz2grd_py.

Runs ``gmt xyz2grd <file> -ZTL<type> -r -R... -I... -G<out>`` (subprocess)
and ``gmt_xyz2grd_py_file`` on the SAME input bytes and asserts
byte-identical output grids -- the snaphu.py call sites:

    gmt xyz2grd unwrap.out   -ZTLf -r {par1} {par2} -Gtmp.grd
    gmt xyz2grd conncomp.out -ZTLu -r {par1} {par2} -Gconncomp.grd

Input data: ``bin_py/tests/data/xyz2grd_phase_small.grd`` is a 100x400 cut of
a real ALOS_haiti ``phase_patch.grd`` (produced once via ``gmt grdcut`` from
the csh oracle, then committed as a fixture -- the oracle itself is never
read or written by this test, per Rule 9). It is round-tripped through
``gmt grd2xyz -ZTL<type> -do0`` to produce genuine GMT-format binary blobs
(the same format snaphu emits for unwrap.out/conncomp.out), then fed to both
xyz2grd paths.

Skips loudly (does NOT silently pass) if ``gmt`` is not on PATH.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
_UTILS = _HERE.parent.parent / "utils"
sys.path.insert(0, str(_UTILS))

from gmt_xyz2grd_py import (  # noqa: E402
    gmt_xyz2grd_py, gmt_xyz2grd_py_file, _parse_region, _parse_inc)
from gmt_grd_io import read_gmt_grd, write_gmt_grd_from_increments  # noqa: E402

_GMT = shutil.which("gmt")
if _GMT is None:
    _alt = "/home/staff/dliu/anaconda3/envs/gmtsar/bin/gmt"
    if os.path.exists(_alt):
        _GMT = _alt
_HAVE_GMT = _GMT is not None and os.access(_GMT, os.X_OK)

# Committed fixture: 100x400 cut of a real ALOS_haiti phase_patch.grd
# (pixel-registered). See bin_py/tests/data/ -- never written to.
_REAL_GRD = _HERE / "data" / "xyz2grd_phase_small.grd"


def _run(cmd):
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode != 0:
        raise RuntimeError(
            f"command failed (rc={res.returncode})\n"
            f"  cmd: {' '.join(cmd)}\n  stderr: {res.stderr}")
    return res.stdout


def _catch_output(cmd):
    return subprocess.run(cmd, stdout=subprocess.PIPE).stdout.decode(
        "utf-8").strip()


# ---------------------------------------------------------------------------
# Synthetic fallback input (used by tests that don't need gmt at all)
# ---------------------------------------------------------------------------

def _synthetic_grid(nx=20, ny=15, seed=0):
    rng = np.random.default_rng(seed)
    z = rng.standard_normal((ny, nx)).astype(np.float32)
    return z


# ---------------------------------------------------------------------------
# C-parity tests (require gmt + real ALOS_haiti oracle grid)
# ---------------------------------------------------------------------------

@unittest.skipUnless(_HAVE_GMT, "gmt binary not found on PATH -- cannot run parity test")
class TestXyz2grdVsGmtBinaryZTLf(unittest.TestCase):
    """-ZTLf path (snaphu.py unwrap.out -> tmp.grd)."""

    @classmethod
    def setUpClass(cls):
        if not _REAL_GRD.exists():
            raise unittest.SkipTest(
                f"fixture grid not found: {_REAL_GRD}")
        cls.tmpdir = tempfile.mkdtemp(prefix="xyz2grd_ztlf_")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def test_ztlf_roundtrip_parity(self):
        d = self.tmpdir
        small = str(_REAL_GRD)
        unwrap_out = os.path.join(d, "unwrap.out")
        out_c = os.path.join(d, "tmp_c.grd")
        out_py = os.path.join(d, "tmp_py.grd")

        # Real binary -ZTLf blob (same format snaphu writes for unwrap.out).
        res = subprocess.run([_GMT, "grd2xyz", small, "-ZTLf", "-do0"],
                              capture_output=True, check=True)
        with open(unwrap_out, "wb") as fh:
            fh.write(res.stdout)

        par1 = _catch_output([_GMT, "grdinfo", "-I-", small])
        par2 = _catch_output([_GMT, "grdinfo", "-I", small])

        # --- C reference
        _run([_GMT, "xyz2grd", unwrap_out, "-ZTLf", "-r", par1, par2,
              f"-G{out_c}"])

        # --- Python port
        gmt_xyz2grd_py_file(unwrap_out, out_py, par1=par1, par2=par2, ztype="f")

        z_c, x_c, y_c, info_c = read_gmt_grd(out_c)
        z_py, x_py, y_py, info_py = read_gmt_grd(out_py)

        z_c = np.array(z_c.filled(np.nan)) if hasattr(z_c, "filled") else np.asarray(z_c)
        z_py = np.array(z_py.filled(np.nan)) if hasattr(z_py, "filled") else np.asarray(z_py)

        self.assertEqual(z_c.shape, z_py.shape)
        np.testing.assert_array_equal(x_c, x_py)
        np.testing.assert_array_equal(y_c, y_py)
        self.assertTrue(np.array_equal(z_c, z_py, equal_nan=True),
                        f"data mismatch: max|diff|="
                        f"{np.nanmax(np.abs(z_c.astype(np.float64) - z_py.astype(np.float64)))}")
        self.assertEqual(info_c["node_offset"], 1)
        self.assertEqual(info_py["node_offset"], 1)

        # Sanity: this is also a true round trip vs the ORIGINAL grid
        # wherever it had no NaN (the -do0 step replaces NaN with 0, which
        # is an upstream-of-xyz2grd property, not a parity gap here).
        z_orig, _, _, _ = read_gmt_grd(small)
        z_orig = np.array(z_orig.filled(np.nan)) if hasattr(z_orig, "filled") else np.asarray(z_orig)
        valid = ~np.isnan(z_orig)
        np.testing.assert_array_equal(z_py[valid], z_orig[valid])


@unittest.skipUnless(_HAVE_GMT, "gmt binary not found on PATH -- cannot run parity test")
class TestXyz2grdVsGmtBinaryZTLu(unittest.TestCase):
    """-ZTLu path (snaphu.py conncomp.out -> conncomp.grd)."""

    @classmethod
    def setUpClass(cls):
        if not _REAL_GRD.exists():
            raise unittest.SkipTest(
                f"fixture grid not found: {_REAL_GRD}")
        cls.tmpdir = tempfile.mkdtemp(prefix="xyz2grd_ztlu_")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def test_ztlu_roundtrip_parity(self):
        d = self.tmpdir
        small = str(_REAL_GRD)
        conn_src = os.path.join(d, "conncomp_src.grd")
        conncomp_out = os.path.join(d, "conncomp.out")
        out_c = os.path.join(d, "conncomp_c.grd")
        out_py = os.path.join(d, "conncomp_py.grd")

        # Build a small-integer-valued grid (like a connected-component
        # label map: 0..N) via grdmath, matching conncomp.out's value range.
        # ABS+ADD gives values in [1,4.x); -ZTLu truncates to uint8 on
        # write (same truncation a real conncomp.out label map exercises).
        _run([_GMT, "grdmath", small, "ABS", "1", "ADD", "=", conn_src])

        res = subprocess.run([_GMT, "grd2xyz", conn_src, "-ZTLu", "-do0"],
                              capture_output=True, check=True)
        with open(conncomp_out, "wb") as fh:
            fh.write(res.stdout)

        par1 = _catch_output([_GMT, "grdinfo", "-I-", small])
        par2 = _catch_output([_GMT, "grdinfo", "-I", small])

        _run([_GMT, "xyz2grd", conncomp_out, "-ZTLu", "-r", par1, par2,
              f"-G{out_c}"])
        gmt_xyz2grd_py_file(conncomp_out, out_py, par1=par1, par2=par2, ztype="u")

        z_c, x_c, y_c, info_c = read_gmt_grd(out_c)
        z_py, x_py, y_py, info_py = read_gmt_grd(out_py)
        z_c = np.array(z_c.filled(np.nan)) if hasattr(z_c, "filled") else np.asarray(z_c)
        z_py = np.array(z_py.filled(np.nan)) if hasattr(z_py, "filled") else np.asarray(z_py)

        self.assertEqual(z_c.shape, z_py.shape)
        np.testing.assert_array_equal(x_c, x_py)
        np.testing.assert_array_equal(y_c, y_py)
        self.assertTrue(np.array_equal(z_c, z_py, equal_nan=True),
                        f"data mismatch: max|diff|="
                        f"{np.nanmax(np.abs(z_c.astype(np.float64) - z_py.astype(np.float64)))}")


# ---------------------------------------------------------------------------
# Synthetic / parsing / error-handling tests (no gmt required)
# ---------------------------------------------------------------------------

class TestParsing(unittest.TestCase):
    def test_parse_region(self):
        self.assertEqual(_parse_region("-R0/400/0/400"), (0.0, 400.0, 0.0, 400.0))
        self.assertEqual(_parse_region("-R-10.5/20.25/-5/100"),
                         (-10.5, 20.25, -5.0, 100.0))

    def test_parse_inc(self):
        self.assertEqual(_parse_inc("-I4/8"), (4.0, 8.0))
        self.assertEqual(_parse_inc("-I0.000277778/0.000277778"),
                         (0.000277778, 0.000277778))

    def test_parse_region_bad(self):
        with self.assertRaises(ValueError):
            _parse_region("-Rgarbage")

    def test_parse_inc_bad(self):
        with self.assertRaises(ValueError):
            _parse_inc("-Igarbage")


class TestCoreArray(unittest.TestCase):
    """Synthetic correctness: reshape + flip + coordinate generation."""

    def test_basic_reshape_and_flip(self):
        nx, ny = 4, 3
        # Top-row-first, left-to-right: row0=[0,1,2,3] is y_max
        z_top_first = np.arange(nx * ny, dtype=np.float32).reshape(ny, nx)
        raw = z_top_first.tobytes()

        data, x, y = gmt_xyz2grd_py(
            raw, region=(0, 4, 0, 3), x_inc=1.0, y_inc=1.0, dtype="f")

        self.assertEqual(data.shape, (3, 4))
        # row 0 of output (y_min) == last row of the top-first input
        np.testing.assert_array_equal(data[0], z_top_first[-1])
        np.testing.assert_array_equal(data[-1], z_top_first[0])
        # pixel-center coords
        np.testing.assert_allclose(x, [0.5, 1.5, 2.5, 3.5])
        np.testing.assert_allclose(y, [0.5, 1.5, 2.5])
        self.assertEqual(data.dtype, np.float32)

    def test_uint8_upcast(self):
        nx, ny = 2, 2
        z = np.array([[0, 1], [254, 255]], dtype=np.uint8)
        raw = z.tobytes()
        data, x, y = gmt_xyz2grd_py(
            raw, region=(0, 2, 0, 2), x_inc=1.0, y_inc=1.0, dtype="u")
        self.assertEqual(data.dtype, np.float32)
        # row0 (y_min) = input row -1 = [254,255]; row1 = input row0 = [0,1]
        np.testing.assert_array_equal(data[0], [254.0, 255.0])
        np.testing.assert_array_equal(data[1], [0.0, 1.0])


class TestErrorHandling(unittest.TestCase):
    """Hard-failure / no-fallback checks (Rule 1)."""

    def test_wrong_byte_count_raises(self):
        nx, ny = 4, 3
        z = np.zeros((ny, nx), dtype=np.float32)
        raw = z.tobytes()[:-4]  # one element short
        with self.assertRaises(ValueError):
            gmt_xyz2grd_py(raw, region=(0, 4, 0, 3), x_inc=1.0, y_inc=1.0,
                           dtype="f")

    def test_unsupported_dtype_raises(self):
        with self.assertRaises(ValueError):
            gmt_xyz2grd_py(b"\x00" * 16, region=(0, 4, 0, 4),
                           x_inc=1.0, y_inc=1.0, dtype="Q")

    def test_non_integral_inc_raises(self):
        nx, ny = 4, 3
        z = np.zeros((ny, nx), dtype=np.float32)
        raw = z.tobytes()
        # (e-w)/x_inc = 4/1.3 = 3.0769... not integral
        with self.assertRaises(ValueError):
            gmt_xyz2grd_py(raw, region=(0, 4, 0, 3), x_inc=1.3, y_inc=1.0,
                           dtype="f")

    def test_zero_region_raises(self):
        with self.assertRaises(ValueError):
            gmt_xyz2grd_py(b"", region=(0, 0, 0, 4), x_inc=1.0, y_inc=1.0,
                           dtype="f")

    def test_nonpositive_inc_raises(self):
        with self.assertRaises(ValueError):
            gmt_xyz2grd_py(b"", region=(0, 4, 0, 4), x_inc=0.0, y_inc=1.0,
                           dtype="f")


class TestFileWrapper(unittest.TestCase):
    """gmt_xyz2grd_py_file equivalence to the array API + grd round trip."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="xyz2grd_filewrap_")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_file_roundtrip(self):
        nx, ny = 5, 4
        z_top_first = np.arange(nx * ny, dtype=np.float32).reshape(ny, nx)
        raw_path = os.path.join(self.tmpdir, "blob.out")
        with open(raw_path, "wb") as fh:
            fh.write(z_top_first.tobytes())

        out_path = os.path.join(self.tmpdir, "out.grd")
        gmt_xyz2grd_py_file(raw_path, out_path, par1="-R0/5/0/4",
                             par2="-I1/1", ztype="f")

        data, x, y, info = read_gmt_grd(out_path)
        data = np.array(data.filled(np.nan)) if hasattr(data, "filled") else np.asarray(data)
        self.assertEqual(data.shape, (4, 5))
        self.assertEqual(info["node_offset"], 1)
        np.testing.assert_array_equal(data[0], z_top_first[-1])
        np.testing.assert_array_equal(data[-1], z_top_first[0])


if __name__ == "__main__":
    unittest.main()
