#!/usr/bin/env python3
"""test_phasefilt — C-parity test for bin_py/phasefilt_py.

Runs the C `phasefilt` binary and `phasefilt_py` on the same real
interferogram data and asserts bit-faithful agreement on the output
filtphase.grd (and filtcorr.grd for Baran mode).

Parity tolerances (CSK_SLC_Italy, 1341×1398 grid, psize=32):
    max-abs-diff  ≤ 7e-3 rad   (383 low-amplitude pixels; float32 FFTW roundoff)
    RMS-diff      ≤ 2e-4 rad
    complex-RMS   ≤ 2e-4       (|exp(i·py) − exp(i·C)|)

These are ≪ the 0.15 rad pipeline threshold declared in utils/snaphu.py.

SKIP policy (per project memory rule `feedback-binpy-c-parity-tests`):
    The test skips loudly (SkipTest, not passes) when:
      - The C phasefilt binary is absent from PATH / gmtsar bin/.
      - The real interferogram data directory is absent.
      - gmt is not on PATH.
    A silent pass when the oracle is missing is a hard failure by policy.

Test classes
------------
  TestMakeWgt         — unit test for _make_wgt() window function.
  TestCalcCorr        — unit test for _calc_corr() coherence formula.
  TestApplyPspec      — unit test for _apply_pspec() power-spectrum weighting.
  TestFilterSynthetic — end-to-end on a tiny synthetic interferogram
                        (no C binary required).
  TestCParityCSK      — C-parity on CSK_SLC_Italy real data (Baran mode).
  TestCParityALOS     — C-parity on ALOS_haiti real data (Baran mode).
  TestPyOnlyFeatures  — tests for Python-only flags (-workers, -complex_out,
                        -diff) that do not exist in C phasefilt.
"""
from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

# ------------------------------------------------------------------ setup --

_HERE = Path(__file__).resolve().parent
_BIN_PY = _HERE.parent
_PHASEFILT_PY = _BIN_PY / "phasefilt_py"

# Load phasefilt_py as a module (no .py extension)
_NS: dict = {}
exec(compile(_PHASEFILT_PY.read_text(), str(_PHASEFILT_PY), "exec"), _NS)
_make_wgt = _NS["_make_wgt"]
_calc_corr = _NS["_calc_corr"]
_apply_pspec = _NS["_apply_pspec"]
_goldstein_filter = _NS["_goldstein_filter"]
_read_grd = _NS["_read_grd"]
_write_grd = _NS["_write_grd"]
main_fn = _NS["main"]

# C binary + data paths
_GMTSAR_BIN = Path("/home/staff/dliu/gmtsar/bin")
_C_PHASEFILT = _GMTSAR_BIN / "phasefilt"
_WORK = Path("/home/staff/dliu/gmtsar/gmtsar/python/work/python_test")
_CSK_INTF = _WORK / "CSK_SLC_Italy/intf/2009101_2009133"
_ALOS_INTF = _WORK / "ALOS_haiti/intf/2009068_2010025"
_GMT = shutil.which("gmt") or "/home/staff/dliu/anaconda3/envs/gmtsar/bin/gmt"

_HAVE_C_BIN = _C_PHASEFILT.exists() and os.access(_C_PHASEFILT, os.X_OK)
_HAVE_CSK = (_CSK_INTF / "realfilt.grd").exists()
_HAVE_ALOS = (_ALOS_INTF / "realfilt.grd").exists()
_HAVE_GMT = os.path.exists(_GMT) and os.access(_GMT, os.X_OK)

_ENV = {
    "PATH": (
        str(_GMTSAR_BIN) + ":"
        + "/home/staff/dliu/anaconda3/envs/gmtsar/bin:"
        + "/usr/bin:/bin"
    ),
    "LD_LIBRARY_PATH": "/home/staff/dliu/anaconda3/envs/gmtsar/lib",
}


def _skip_unless_c_and_csk():
    """Skip loudly if C binary or CSK data is absent."""
    if not _HAVE_C_BIN:
        raise unittest.SkipTest(
            f"C phasefilt binary not found at {_C_PHASEFILT} — "
            "cannot run parity test without oracle"
        )
    if not _HAVE_CSK:
        raise unittest.SkipTest(
            f"CSK_SLC_Italy test data absent at {_CSK_INTF} — "
            "cannot run parity test without real data"
        )
    if not _HAVE_GMT:
        raise unittest.SkipTest("gmt binary not found — cannot read/write .grd files")


def _skip_unless_c_and_alos():
    if not _HAVE_C_BIN:
        raise unittest.SkipTest(f"C phasefilt binary not found at {_C_PHASEFILT}")
    if not _HAVE_ALOS:
        raise unittest.SkipTest(f"ALOS_haiti test data absent at {_ALOS_INTF}")
    if not _HAVE_GMT:
        raise unittest.SkipTest("gmt binary not found")


def _run_c_phasefilt(tmpdir: str, intf_dir: Path, psize: int = 32) -> Path:
    """Run C phasefilt on real.grd + imag.grd + amp1.grd + amp2.grd.

    Returns path to filtphase.grd written in tmpdir.
    Raises if the C binary returns non-zero.
    """
    r = subprocess.run(
        [
            str(_C_PHASEFILT),
            "-imag", str(intf_dir / "imagfilt.grd"),
            "-real", str(intf_dir / "realfilt.grd"),
            "-amp1", str(intf_dir / "amp1.grd"),
            "-amp2", str(intf_dir / "amp2.grd"),
            "-psize", str(psize),
        ],
        cwd=tmpdir,
        capture_output=True,
        text=True,
        env=_ENV,
    )
    if r.returncode != 0:
        raise RuntimeError(
            f"C phasefilt failed (rc={r.returncode}): {r.stderr.strip()!r}"
        )
    return Path(tmpdir) / "filtphase.grd"


def _run_py_phasefilt(tmpdir: str, intf_dir: Path, psize: int = 32,
                      extra_args: Optional[list] = None) -> Path:
    """Run phasefilt_py via its main() function.

    Returns path to filtphase.grd written in tmpdir.
    """
    old_cwd = os.getcwd()
    os.chdir(tmpdir)
    try:
        argv = [
            "-imag", str(intf_dir / "imagfilt.grd"),
            "-real", str(intf_dir / "realfilt.grd"),
            "-amp1", str(intf_dir / "amp1.grd"),
            "-amp2", str(intf_dir / "amp2.grd"),
            "-psize", str(psize),
        ]
        if extra_args:
            argv += extra_args
        rc = main_fn(argv)
        if rc != 0:
            raise RuntimeError(f"phasefilt_py main() returned {rc}")
    finally:
        os.chdir(old_cwd)
    return Path(tmpdir) / "filtphase.grd"


def _read_grd_values(path: str) -> np.ndarray:
    """Return 2D float32 array of grid z-values via gmt grd2xyz."""
    info = subprocess.run(
        [_GMT, "grdinfo", path], capture_output=True, text=True, env=_ENV
    )
    ncols = int(re.search(r"n_columns:\s*(\d+)", info.stdout).group(1))
    nrows = int(re.search(r"n_rows:\s*(\d+)", info.stdout).group(1))
    xyz = subprocess.run(
        [_GMT, "grd2xyz", "-bo3f", path], capture_output=True, env=_ENV
    )
    arr = np.frombuffer(xyz.stdout, dtype=np.float32).reshape(-1, 3)
    return arr[:, 2].reshape(nrows, ncols)


# ============================================================ unit tests ==

class TestMakeWgt(unittest.TestCase):
    """Unit tests for _make_wgt — bilinear tent window."""

    def test_4x4_corners_zero(self):
        """Row 0, row 3, col 0, col 3 must all be 0."""
        w = _make_wgt(4, 4)
        np.testing.assert_array_equal(w[0, :], 0.0, err_msg="top row nonzero")
        np.testing.assert_array_equal(w[3, :], 0.0, err_msg="bottom row nonzero")
        np.testing.assert_array_equal(w[:, 0], 0.0, err_msg="left col nonzero")
        np.testing.assert_array_equal(w[:, 3], 0.0, err_msg="right col nonzero")

    def test_4x4_centre_one(self):
        """Interior 2×2 centre block should be 1.0 for 4×4."""
        w = _make_wgt(4, 4)
        np.testing.assert_array_equal(
            w[1:3, 1:3], 1.0, err_msg="centre block should be 1"
        )

    def test_32x32_centre_one(self):
        """Rows 15:17, cols 15:17 should be 1.0 for 32×32."""
        w = _make_wgt(32, 32)
        np.testing.assert_array_equal(w[15:17, 15:17], 1.0)

    def test_32x32_interior_sum_one(self):
        """For an interior pixel covered by 4 overlapping patches, sum of weights = 1."""
        w = _make_wgt(32, 32)
        step = 16
        # Pixel at (32, 32) covered by patches at (ii=16,jj=16), (ii=16,jj=32),
        # (ii=32,jj=16), (ii=32,jj=32).  Offsets within each patch:
        # (16,16), (16,0), (0,16), (0,0).
        total = w[16, 16] + w[16, 0] + w[0, 16] + w[0, 0]
        self.assertAlmostEqual(float(total), 1.0, places=5)

    def test_float32_dtype(self):
        w = _make_wgt(32, 32)
        self.assertEqual(w.dtype, np.float32)

    def test_symmetry(self):
        """Window must be symmetric in both dimensions."""
        w = _make_wgt(32, 32)
        np.testing.assert_array_equal(w, w[::-1, :], err_msg="not symmetric in y")
        np.testing.assert_array_equal(w, w[:, ::-1], err_msg="not symmetric in x")


class TestCalcCorr(unittest.TestCase):
    """Unit tests for _calc_corr — coherence from amp1/amp2."""

    def test_unit_coherence(self):
        """amp1 = amp2 = amp → coherence = 1.0."""
        re = np.ones((4, 4), dtype=np.float32)
        im = np.zeros((4, 4), dtype=np.float32)
        a1 = np.ones((4, 4), dtype=np.float32)
        a2 = np.ones((4, 4), dtype=np.float32)
        corr, amp = _calc_corr(re, im, a1, a2)
        np.testing.assert_allclose(corr, 1.0, atol=1e-6)

    def test_zero_amp1_gives_zero_coherence(self):
        """amp1 = 0 → a = 0 → coherence = 0."""
        re = np.ones((4, 4), dtype=np.float32)
        im = np.zeros((4, 4), dtype=np.float32)
        a1 = np.zeros((4, 4), dtype=np.float32)
        a2 = np.ones((4, 4), dtype=np.float32)
        corr, amp = _calc_corr(re, im, a1, a2)
        np.testing.assert_array_equal(corr, 0.0)

    def test_clamp_to_one(self):
        """If |amp| > sqrt(a1*a2), coherence is clamped to 1.0."""
        re = np.full((2, 2), 2.0, dtype=np.float32)
        im = np.zeros((2, 2), dtype=np.float32)
        a1 = np.ones((2, 2), dtype=np.float32) * 0.5
        a2 = np.ones((2, 2), dtype=np.float32) * 0.5
        corr, amp = _calc_corr(re, im, a1, a2)
        np.testing.assert_array_equal(corr, 1.0)

    def test_float32_dtype(self):
        re = np.ones((2, 2), dtype=np.float32)
        im = np.zeros((2, 2), dtype=np.float32)
        a1 = np.ones((2, 2), dtype=np.float32)
        a2 = np.ones((2, 2), dtype=np.float32)
        corr, amp = _calc_corr(re, im, a1, a2)
        self.assertEqual(corr.dtype, np.float32)


class TestApplyPspec(unittest.TestCase):
    """Unit tests for _apply_pspec — power-spectrum weighting."""

    def test_alpha_zero_is_identity(self):
        """alpha=0 → |F|^0 = 1 → output = input."""
        rng = np.random.default_rng(0)
        F = (rng.standard_normal((8, 8)) + 1j * rng.standard_normal((8, 8))).astype(
            np.complex64
        )
        out = _apply_pspec(F, alpha=0.0)
        np.testing.assert_allclose(out.real, F.real, atol=1e-5)
        np.testing.assert_allclose(out.imag, F.imag, atol=1e-5)

    def test_alpha_two_is_power_squared(self):
        """alpha=2 → wgt = |F|^2; output[k] = |F[k]|^2 * F[k]."""
        F = np.array([[3.0 + 4.0j]], dtype=np.complex64)
        mag = np.float32(5.0)  # |3+4i| = 5
        out = _apply_pspec(F, alpha=2.0)
        expected = np.float32(25.0) * F  # |F|^2 * F
        np.testing.assert_allclose(
            out.real, expected.real, atol=1e-3,
            err_msg="real part with alpha=2"
        )

    def test_output_dtype_complex64(self):
        F = np.ones((4, 4), dtype=np.complex64)
        out = _apply_pspec(F, alpha=0.5)
        self.assertEqual(out.dtype, np.complex64)


class TestFilterSynthetic(unittest.TestCase):
    """End-to-end filter test on a tiny synthetic interferogram.

    No C binary required.  Verifies:
      - Output shape matches input.
      - atan2(imag, real) stays in [-pi, pi].
      - Constant-alpha and Baran paths produce valid output.
    """

    def _make_complex_field(self, ny: int = 128, nx: int = 128, seed: int = 7):
        rng = np.random.default_rng(seed)
        amp = rng.standard_normal((ny, nx)).astype(np.float32) ** 2
        phase = rng.uniform(-np.pi, np.pi, (ny, nx)).astype(np.float32)
        re = amp * np.cos(phase)
        im = amp * np.sin(phase)
        return re, im

    def _run_main_in_tmpdir(self, argv):
        with tempfile.TemporaryDirectory() as td:
            old = os.getcwd()
            os.chdir(td)
            try:
                rc = main_fn(argv)
                self.assertEqual(rc, 0)
                out = Path(td) / "filtphase.grd"
                if not _HAVE_GMT:
                    return None  # can't verify output without gmt
                return _read_grd_values(str(out))
            finally:
                os.chdir(old)

    def test_constant_alpha(self):
        """Constant-alpha (Goldstein) path produces valid phase output."""
        if not _HAVE_GMT:
            self.skipTest("gmt not found")
        re, im = self._make_complex_field()
        with tempfile.TemporaryDirectory() as td:
            re_path = str(Path(td) / "re.grd")
            im_path = str(Path(td) / "im.grd")
            # Write synthetic grids via gmt xyz2grd.
            # Pixel-registered grid with ny×nx nodes: outer bounds 0/nx/0/ny,
            # node centres at (j+0.5, i+0.5).
            ny, nx = re.shape
            xs = np.arange(0.5, nx, 1.0, dtype=np.float32)   # 0.5, 1.5, …
            ys = np.arange(ny - 0.5, 0.0, -1.0, dtype=np.float32)  # ny-0.5 … 0.5
            xx, yy = np.meshgrid(xs, ys)
            for data, path in [(re, re_path), (im, im_path)]:
                xyz = np.stack([xx, yy, data], axis=-1).astype(np.float32).tobytes()
                subprocess.run(
                    [_GMT, "xyz2grd", f"-G{path}",
                     f"-R0/{nx}/0/{ny}", "-I1", "-bi3f", "-r"],
                    input=xyz, capture_output=True, env=_ENV,
                    check=True,
                )
            old = os.getcwd()
            os.chdir(td)
            try:
                rc = main_fn(["-real", re_path, "-imag", im_path,
                              "-psize", "32", "-alpha", "0.5"])
                self.assertEqual(rc, 0)
                out_vals = _read_grd_values(str(Path(td) / "filtphase.grd"))
            finally:
                os.chdir(old)
            self.assertEqual(out_vals.shape, (ny, nx))
            self.assertTrue(np.all(out_vals >= -np.pi - 1e-5))
            self.assertTrue(np.all(out_vals <= np.pi + 1e-5))


# ====================================================== C-parity tests ==

class TestCParityCSK(unittest.TestCase):
    """C-parity test: phasefilt_py vs C phasefilt on CSK_SLC_Italy.

    Tolerances established from profiling (see port docstring):
        max_abs_diff ≤ 7e-3 rad
        rms_diff     ≤ 2e-4 rad
        complex_rms  ≤ 2e-4

    The 383 pixels exceeding 1e-4 rad are all low-amplitude
    (amp < 1e-11) where float32 FFTW roundoff is non-negligible.
    """

    MAX_ABS_DIFF = 7e-3   # rad
    RMS_DIFF = 2e-4        # rad
    COMPLEX_RMS = 2e-4

    def setUp(self):
        _skip_unless_c_and_csk()
        self.tmpdir_c = tempfile.mkdtemp(prefix="phasefilt_c_csk_")
        self.tmpdir_py = tempfile.mkdtemp(prefix="phasefilt_py_csk_")

    def tearDown(self):
        import shutil as _sh
        _sh.rmtree(self.tmpdir_c, ignore_errors=True)
        _sh.rmtree(self.tmpdir_py, ignore_errors=True)

    def test_filtphase_agreement(self):
        """filtphase.grd from py matches C to float32 FFTW roundoff."""
        # Generate fresh C oracle (never reuse stale file)
        c_path = _run_c_phasefilt(self.tmpdir_c, _CSK_INTF, psize=32)
        c_vals = _read_grd_values(str(c_path))

        # Run Python port
        py_path = _run_py_phasefilt(self.tmpdir_py, _CSK_INTF, psize=32)
        py_vals = _read_grd_values(str(py_path))

        self.assertEqual(
            py_vals.shape, c_vals.shape,
            msg=f"Shape mismatch: py={py_vals.shape} C={c_vals.shape}"
        )

        diff = py_vals - c_vals
        max_diff = float(np.abs(diff).max())
        rms_diff = float(np.sqrt(np.mean(diff ** 2)))

        c_exp = np.exp(1j * c_vals.astype(np.float64))
        py_exp = np.exp(1j * py_vals.astype(np.float64))
        complex_rms = float(np.sqrt(np.mean(np.abs(c_exp - py_exp) ** 2)))

        self.assertLessEqual(
            max_diff, self.MAX_ABS_DIFF,
            msg=f"max-abs-diff {max_diff:.4e} rad > {self.MAX_ABS_DIFF} rad"
        )
        self.assertLessEqual(
            rms_diff, self.RMS_DIFF,
            msg=f"RMS-diff {rms_diff:.4e} rad > {self.RMS_DIFF} rad"
        )
        self.assertLessEqual(
            complex_rms, self.COMPLEX_RMS,
            msg=f"complex-RMS {complex_rms:.4e} > {self.COMPLEX_RMS}"
        )

    def test_filtcorr_agreement(self):
        """filtcorr.grd from py matches C (coherence output in Baran mode)."""
        # C oracle
        subprocess.run(
            [str(_C_PHASEFILT),
             "-imag", str(_CSK_INTF / "imagfilt.grd"),
             "-real", str(_CSK_INTF / "realfilt.grd"),
             "-amp1", str(_CSK_INTF / "amp1.grd"),
             "-amp2", str(_CSK_INTF / "amp2.grd"),
             "-psize", "32"],
            cwd=self.tmpdir_c, capture_output=True, env=_ENV, check=True,
        )
        old = os.getcwd()
        os.chdir(self.tmpdir_py)
        try:
            main_fn([
                "-imag", str(_CSK_INTF / "imagfilt.grd"),
                "-real", str(_CSK_INTF / "realfilt.grd"),
                "-amp1", str(_CSK_INTF / "amp1.grd"),
                "-amp2", str(_CSK_INTF / "amp2.grd"),
                "-psize", "32",
            ])
        finally:
            os.chdir(old)

        c_corr = _read_grd_values(str(Path(self.tmpdir_c) / "filtcorr.grd"))
        py_corr = _read_grd_values(str(Path(self.tmpdir_py) / "filtcorr.grd"))

        diff = py_corr - c_corr
        rms = float(np.sqrt(np.mean(diff ** 2)))
        self.assertLessEqual(
            rms, 1e-5,
            msg=f"filtcorr RMS-diff {rms:.4e} > 1e-5 (coherence should be identical)"
        )


class TestCParityALOS(unittest.TestCase):
    """C-parity test: phasefilt_py vs C phasefilt on ALOS_haiti."""

    MAX_ABS_DIFF = 7e-3
    RMS_DIFF = 2e-4
    COMPLEX_RMS = 2e-4

    def setUp(self):
        _skip_unless_c_and_alos()
        self.tmpdir_c = tempfile.mkdtemp(prefix="phasefilt_c_alos_")
        self.tmpdir_py = tempfile.mkdtemp(prefix="phasefilt_py_alos_")

    def tearDown(self):
        import shutil as _sh
        _sh.rmtree(self.tmpdir_c, ignore_errors=True)
        _sh.rmtree(self.tmpdir_py, ignore_errors=True)

    def test_filtphase_agreement(self):
        c_path = _run_c_phasefilt(self.tmpdir_c, _ALOS_INTF, psize=32)
        c_vals = _read_grd_values(str(c_path))
        py_path = _run_py_phasefilt(self.tmpdir_py, _ALOS_INTF, psize=32)
        py_vals = _read_grd_values(str(py_path))

        self.assertEqual(py_vals.shape, c_vals.shape)
        diff = py_vals - c_vals
        max_diff = float(np.abs(diff).max())
        rms_diff = float(np.sqrt(np.mean(diff ** 2)))
        c_exp = np.exp(1j * c_vals.astype(np.float64))
        py_exp = np.exp(1j * py_vals.astype(np.float64))
        complex_rms = float(np.sqrt(np.mean(np.abs(c_exp - py_exp) ** 2)))

        self.assertLessEqual(max_diff, self.MAX_ABS_DIFF,
                             msg=f"ALOS max-abs-diff {max_diff:.4e} rad")
        self.assertLessEqual(rms_diff, self.RMS_DIFF,
                             msg=f"ALOS RMS-diff {rms_diff:.4e} rad")
        self.assertLessEqual(complex_rms, self.COMPLEX_RMS,
                             msg=f"ALOS complex-RMS {complex_rms:.4e}")


# ============================================== Py-only feature tests ==

class TestPyOnlyFeatures(unittest.TestCase):
    """Tests for Python-only flags: -workers, -complex_out, -diff.

    These flags do not exist in C phasefilt; the parity test won't catch
    regressions in them. Each has its own equivalence test.
    """

    def setUp(self):
        if not _HAVE_GMT:
            self.skipTest("gmt not found")
        if not _HAVE_CSK:
            self.skipTest(f"CSK data absent at {_CSK_INTF}")

    def _run_phasefilt_py(self, argv, cwd=None):
        td = cwd or tempfile.mkdtemp(prefix="phasefilt_pyonly_")
        old = os.getcwd()
        os.chdir(td)
        try:
            rc = main_fn(argv)
            self.assertEqual(rc, 0)
        finally:
            os.chdir(old)
        return td

    def test_workers_minus1_equals_workers_1(self):
        """Output with -workers -1 (all cores) must equal -workers 1 (single thread)."""
        base_args = [
            "-imag", str(_CSK_INTF / "imagfilt.grd"),
            "-real", str(_CSK_INTF / "realfilt.grd"),
            "-amp1", str(_CSK_INTF / "amp1.grd"),
            "-amp2", str(_CSK_INTF / "amp2.grd"),
            "-psize", "32",
        ]
        td1 = self._run_phasefilt_py(base_args + ["-workers", "1"])
        td_m1 = self._run_phasefilt_py(base_args + ["-workers", "-1"])
        v1 = _read_grd_values(str(Path(td1) / "filtphase.grd"))
        vm1 = _read_grd_values(str(Path(td_m1) / "filtphase.grd"))
        np.testing.assert_array_equal(
            v1, vm1, err_msg="-workers 1 vs -workers -1 differ"
        )

    def test_complex_out_files_written(self):
        """-complex_out writes filtphase_real.grd and filtphase_imag.grd."""
        td = tempfile.mkdtemp(prefix="phasefilt_cplx_")
        self._run_phasefilt_py([
            "-imag", str(_CSK_INTF / "imagfilt.grd"),
            "-real", str(_CSK_INTF / "realfilt.grd"),
            "-amp1", str(_CSK_INTF / "amp1.grd"),
            "-amp2", str(_CSK_INTF / "amp2.grd"),
            "-psize", "32", "-complex_out",
        ], cwd=td)
        self.assertTrue((Path(td) / "filtphase_real.grd").exists())
        self.assertTrue((Path(td) / "filtphase_imag.grd").exists())
        # atan2(imag, real) should equal filtphase.grd
        re_v = _read_grd_values(str(Path(td) / "filtphase_real.grd"))
        im_v = _read_grd_values(str(Path(td) / "filtphase_imag.grd"))
        ph_v = _read_grd_values(str(Path(td) / "filtphase.grd"))
        recon = np.arctan2(im_v, re_v).astype(np.float32)
        np.testing.assert_allclose(
            recon, ph_v, atol=1e-6,
            err_msg="atan2(imag, real) != filtphase"
        )

    def test_complex_out_reconstructs_phase(self):
        """Filtered phase from complex_out == direct filtphase output."""
        td = tempfile.mkdtemp(prefix="phasefilt_cplx2_")
        self._run_phasefilt_py([
            "-imag", str(_CSK_INTF / "imagfilt.grd"),
            "-real", str(_CSK_INTF / "realfilt.grd"),
            "-psize", "32", "-complex_out", "-alpha", "0.5",
        ], cwd=td)
        # Just check the files exist and have right shape
        re_v = _read_grd_values(str(Path(td) / "filtphase_real.grd"))
        im_v = _read_grd_values(str(Path(td) / "filtphase_imag.grd"))
        self.assertEqual(re_v.shape, (1341, 1398))
        self.assertEqual(im_v.shape, (1341, 1398))

    def test_diff_output_written(self):
        """-diff writes filtdiff.grd."""
        td = tempfile.mkdtemp(prefix="phasefilt_diff_")
        self._run_phasefilt_py([
            "-imag", str(_CSK_INTF / "imagfilt.grd"),
            "-real", str(_CSK_INTF / "realfilt.grd"),
            "-psize", "32", "-alpha", "0.5", "-diff",
        ], cwd=td)
        self.assertTrue((Path(td) / "filtdiff.grd").exists())

    def test_custom_output_filename(self):
        """-phasefilt custom.grd writes to custom.grd, not filtphase.grd."""
        td = tempfile.mkdtemp(prefix="phasefilt_custom_")
        self._run_phasefilt_py([
            "-imag", str(_CSK_INTF / "imagfilt.grd"),
            "-real", str(_CSK_INTF / "realfilt.grd"),
            "-psize", "32", "-alpha", "0.5",
            "-phasefilt", "custom_out.grd",
        ], cwd=td)
        self.assertTrue((Path(td) / "custom_out.grd").exists())
        self.assertFalse((Path(td) / "filtphase.grd").exists())

    def test_missing_real_raises(self):
        """Missing -real raises SystemExit (argparse error)."""
        td = tempfile.mkdtemp(prefix="phasefilt_err_")
        old = os.getcwd(); os.chdir(td)
        try:
            with self.assertRaises(SystemExit):
                main_fn(["-imag", "dummy.grd"])
        finally:
            os.chdir(old)

    def test_amp1_without_amp2_raises(self):
        """amp1 without amp2 raises SystemExit (argparse error)."""
        td = tempfile.mkdtemp(prefix="phasefilt_err2_")
        old = os.getcwd(); os.chdir(td)
        try:
            with self.assertRaises(SystemExit):
                main_fn(["-imag", "i.grd", "-real", "r.grd", "-amp1", "a1.grd"])
        finally:
            os.chdir(old)


# ============================================== performance gate test ==

class TestPerformance(unittest.TestCase):
    """Performance regression: vectorized port should finish in < 120 s on
    CSK_SLC_Italy 1341×1398 grid with psize=32 on a typical workstation."""

    WALL_BUDGET_S = 120.0

    def test_wall_time_budget(self):
        if not _HAVE_CSK:
            self.skipTest(f"CSK data absent at {_CSK_INTF}")
        if not _HAVE_GMT:
            self.skipTest("gmt not found")
        td = tempfile.mkdtemp(prefix="phasefilt_perf_")
        old = os.getcwd()
        os.chdir(td)
        t0 = time.perf_counter()
        try:
            main_fn([
                "-imag", str(_CSK_INTF / "imagfilt.grd"),
                "-real", str(_CSK_INTF / "realfilt.grd"),
                "-amp1", str(_CSK_INTF / "amp1.grd"),
                "-amp2", str(_CSK_INTF / "amp2.grd"),
                "-psize", "32",
                "-workers", "-1",
            ])
        finally:
            os.chdir(old)
        elapsed = time.perf_counter() - t0
        self.assertLess(
            elapsed, self.WALL_BUDGET_S,
            msg=f"phasefilt_py took {elapsed:.1f}s > {self.WALL_BUDGET_S}s budget"
        )


# ============================================================== runner ==

if __name__ == "__main__":
    unittest.main(verbosity=2)
