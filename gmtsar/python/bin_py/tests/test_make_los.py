#!/usr/bin/env python3
"""test_make_los — parity tests for bin_py/make_los_py.

The C-side oracle is the `gmt grdmath` invocation from geocode.csh:
    gmt grdmath unwrap_mask.grd $wavel MUL -79.58 MUL = los.grd

We compare:
  1. Direct numpy formula vs hand-computed reference  (unit-only).
  2. End-to-end .grd I/O: pipe a synthetic phase.grd through both
     `gmt grdmath` and `make_los_py`, then assert byte-equal outputs
     (within float32 roundoff).
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
_BIN = _HERE.parent / "make_los_py"
_UTILS = _HERE.parents[1] / "utils"
sys.path.insert(0, str(_UTILS))

_NS: dict = {"__file__": str(_BIN), "__name__": "make_los_module"}
exec(compile(_BIN.read_text(), str(_BIN), "exec"), _NS)
phase_to_los = _NS["phase_to_los"]
GEOCODE_FACTOR = _NS["GEOCODE_FACTOR"]

from gmt_grd_io import read_gmt_grd, write_gmt_grd  # noqa: E402

def _find_gmt() -> Path | None:
    gmt = shutil.which("gmt")
    if gmt:
        p = Path(gmt)
        if p.exists() and os.access(p, os.X_OK):
            return p
    return None


class TestPhaseToLos(unittest.TestCase):

    def test_truncated_constant_used_by_default(self):
        """GEOCODE_FACTOR is -79.58 (truncated), NOT -1000/(4*pi)."""
        self.assertEqual(GEOCODE_FACTOR, -79.58)
        exact = -1000.0 / (4.0 * np.pi)
        # The truncation matters at the 5th significant figure
        self.assertAlmostEqual(GEOCODE_FACTOR, exact, places=2)
        self.assertNotEqual(GEOCODE_FACTOR, exact)

    def test_formula_basic(self):
        # wavelength = 0.236 m (typical ALOS L-band)
        # phase = 2*pi rad → los = -79.58 * 0.236 * 2*pi
        phase = np.array([2 * np.pi])
        los = phase_to_los(phase, 0.236)
        expected = -79.58 * 0.236 * 2 * np.pi
        np.testing.assert_allclose(los, expected, atol=1e-12)

    def test_zero_phase_zero_los(self):
        phase = np.zeros(100)
        los = phase_to_los(phase, 0.056)
        np.testing.assert_array_equal(los, 0.0)

    def test_negative_phase_positive_los(self):
        """phase < 0 (range increase) → los > 0 (range decrease convention)."""
        phase = np.array([-1.0])
        los = phase_to_los(phase, 0.236)
        self.assertGreater(los[0], 0)

    def test_vectorised_2d(self):
        phase = np.array([[1.0, 2.0], [3.0, 4.0]])
        los = phase_to_los(phase, 0.056)
        np.testing.assert_allclose(los, -79.58 * 0.056 * phase, atol=1e-12)


class TestMakeLosVsGmtGrdmath(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.gmt = _find_gmt()
        if cls.gmt is None:
            raise unittest.SkipTest(
                "`gmt` CLI not found; cannot run grdmath parity test"
            )

    def test_parity_synthetic_phase_grd(self):
        """Same formula via grdmath and make_los_py → byte-equal outputs."""
        with tempfile.TemporaryDirectory() as td:
            # Build a synthetic phase .grd
            ny, nx = 17, 23
            x = np.arange(nx, dtype=np.float64)
            y = np.arange(ny, dtype=np.float64)
            phase = (np.sin(0.3 * x[None, :]) * np.cos(0.2 * y[:, None])
                     ).astype(np.float32)
            phase_grd = os.path.join(td, "phase.grd")
            write_gmt_grd(phase_grd, phase, x, y, node_offset=0)

            wavel = 0.0556
            # Reference: gmt grdmath phase wavel MUL -79.58 MUL = ref.grd
            ref_grd = os.path.join(td, "ref.grd")
            cmd_ref = [str(self.gmt), "grdmath", phase_grd,
                       str(wavel), "MUL", "-79.58", "MUL",
                       "=", ref_grd]
            r = subprocess.run(cmd_ref, capture_output=True, text=True,
                               timeout=60)
            self.assertEqual(r.returncode, 0,
                             f"gmt grdmath failed: {r.stderr}")

            # make_los_py
            py_grd = os.path.join(td, "py.grd")
            cmd_py = [sys.executable, str(_BIN), phase_grd,
                      str(wavel), py_grd]
            r = subprocess.run(cmd_py, capture_output=True, text=True,
                               timeout=60)
            self.assertEqual(r.returncode, 0,
                             f"make_los_py failed: {r.stderr}")

            z_ref, *_ = read_gmt_grd(ref_grd)
            z_py, *_ = read_gmt_grd(py_grd)

            self.assertEqual(z_ref.shape, z_py.shape)
            # Both are float32; float-precision parity expected.
            np.testing.assert_allclose(
                z_ref, z_py, atol=1e-6, rtol=1e-6,
                err_msg="make_los_py output diverges from gmt grdmath"
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
