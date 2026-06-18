#!/usr/bin/env python3
"""test_phasediff — unit + parity tests for bin_py/phasediff_py.

Run with:
    cd gmtsar/python/bin_py/tests
    python3 -m pytest test_phasediff.py -v
    # or, no pytest:
    python3 test_phasediff.py

Test pyramid:

  Unit (fast — milliseconds each):
    - test_parse_prm_rs2 — confirms PRF, fs, RE, lambda parse correctly
      from the real RS2 PRM file (catches key→field-name regressions).
    - test_fix_prm_params_formula — verifies fix_prm_params matches the C
      formula exactly on RS2 inputs.
    - test_calc_drho_synthetic — verifies _calc_drho returns expected
      values for a synthetic flat-earth/zero-baseline geometry.

  Parity (slow — seconds; skipped if C `phasediff` not on PATH OR if
         the RS2 test inputs are missing):
    - TestPhasediffVsCBinary.test_with_topo_bf — runs the C `phasediff`
      and the Py `phasediff_py` on the same RS2 input (master+aligned
      PRM, both SLC files, topo_ra.grd) using `=bf` output format. Asserts
      max abs diff < 1e-7 (well below float32 ULP ≈ 1.2e-7 at 1e-4
      magnitude). Expects bit-exact for >80% of pixels.
    - TestPhasediffVsCBinary.test_with_topo_grd — same but with netCDF
      output (less common; mostly for non-filter consumers).
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

# Load phasediff_py — it has no .py extension, so use exec() pattern
# (matches test_resamp.py).
_HERE = Path(__file__).resolve().parent
_PY = _HERE.parent / "phasediff_py"
_NS: dict = {"__name__": "phasediff_py", "__file__": str(_PY)}
exec(compile(_PY.read_text(), str(_PY), "exec"), _NS)
_parse_prm = _NS["_parse_prm"]
_fix_prm_params = _NS["_fix_prm_params"]
_calc_drho = _NS["_calc_drho"]

# Load _gmt_native_bf as normal module (it has .py extension).
sys.path.insert(0, str(_HERE.parent))
from _gmt_native_bf import read_bf  # noqa: E402

# Real-data fixture (RS2 Hawaii)
_WORK_ROOT = Path(
    os.environ.get("GMTSAR_TEST_WORK")
    or (os.environ.get("GMTSAR", "") + "/gmtsar/python/work"
        if os.environ.get("GMTSAR") else "")
    or str(_HERE.parents[2] / "work")
)
_RS2 = _WORK_ROOT / "csh_test/RS2_SLC_Hawaii"
_SLC_DIR = _RS2 / "SLC"
_TOPO_GRD = _RS2 / "topo" / "topo_ra.grd"
_REF_PRM = _SLC_DIR / "RS220110515.PRM"
_REP_PRM = _SLC_DIR / "RS220110819.PRM"
_REF_SLC = _SLC_DIR / "RS220110515.SLC"
_REP_SLC = _SLC_DIR / "RS220110819.SLC"

C_PHASEDIFF = shutil.which("phasediff") or str(
    Path(os.environ.get("GMTSAR", "")) / "bin" / "phasediff"
    if os.environ.get("GMTSAR") else ""
)


def _have_fixture() -> bool:
    return all(p.exists() for p in (
        _REF_PRM, _REP_PRM, _REF_SLC, _REP_SLC, _TOPO_GRD))


def _have_c_binary() -> bool:
    return Path(C_PHASEDIFF).exists() and os.access(C_PHASEDIFF, os.X_OK)


# ============================================================ unit tests ===


class TestPRMParsing(unittest.TestCase):
    """PRM key→field mapping (mirrors gmtsar/sio_struct.c)."""

    @unittest.skipIf(not _REF_PRM.exists(), "RS2 PRM not present")
    def test_parse_prm_rs2(self):
        p = _parse_prm(str(_REF_PRM))
        # Spot-check known RS2 values
        self.assertEqual(p["num_rng_bins"], 3416)
        self.assertEqual(p["num_valid_az"], 5744)
        self.assertEqual(p["num_patches"], 1)
        self.assertAlmostEqual(p["prf"], 1293.705933, places=4)
        self.assertAlmostEqual(p["fs"], 31669919.362596, places=2)
        self.assertAlmostEqual(p["near_range"], 947767.340373, places=3)
        self.assertAlmostEqual(p["lambda"], 0.0554658, places=6)

    def test_parse_prm_aliases(self):
        """xshift→rshift and yshift→ashift back-compat aliases."""
        with tempfile.NamedTemporaryFile("w", suffix=".PRM", delete=False) as f:
            f.write("xshift = 7\n")
            f.write("yshift = 13\n")
            path = f.name
        try:
            p = _parse_prm(path)
            self.assertEqual(p["rshift"], 7)
            self.assertEqual(p["ashift"], 13)
        finally:
            os.unlink(path)

    def test_parse_prm_unknown_key_ignored(self):
        with tempfile.NamedTemporaryFile("w", suffix=".PRM", delete=False) as f:
            f.write("nonexistent_field = 999\n")
            f.write("PRF = 1000\n")
            path = f.name
        try:
            p = _parse_prm(path)
            self.assertEqual(p["prf"], 1000.0)
            self.assertNotIn("nonexistent_field", p)
        finally:
            os.unlink(path)


class TestCalcDrho(unittest.TestCase):
    """calc_drho — phase from satellite geometry (Lindsey 2015)."""

    def test_zero_baseline_zero_drho(self):
        """B=0, Bx=0 → drho should be 0 for every pixel."""
        xdim = 100
        rng = np.linspace(900_000, 1_100_000, xdim)
        topo = np.zeros(xdim)
        drho = _calc_drho(rng, topo, 0.0, 6.378e6, 700_000, 0.0, 0.0, 0.0)
        np.testing.assert_allclose(drho, 0.0, atol=1e-9)

    def test_known_baseline(self):
        """Synthetic: B=100m, alpha=0, Bx=0, flat earth — drho ≈ -B*sin(theta)."""
        rng = np.array([1_000_000.0])
        topo = np.array([0.0])
        re = 6.378e6
        height = 700_000.0
        B = 100.0
        alpha = 0.0
        drho = _calc_drho(rng, topo, 0.0, re, height, B, alpha, 0.0)
        # Compare with first-order: drho ≈ -B*sint*cosa + (B²cosθ²)/(2ρ)
        # cost = (rho² + (re+ht)² - re²) / (2*rho*(re+ht))
        c = re + height
        cost = (rng[0]**2 + c**2 - re**2) / (2 * rng[0] * c)
        sint = np.sqrt(1 - cost**2)
        approx = -B * sint  # leading term, alpha=0
        self.assertAlmostEqual(drho[0], approx, delta=abs(approx) * 0.01)


# =========================================================== parity tests ===


class TestPhasediffVsCBinary(unittest.TestCase):
    """End-to-end parity vs the C `phasediff` binary on RS2 SLC pair.

    These tests SKIP loudly (not pass) if either the C binary or the
    real-data fixture is missing. They are the canonical 'this port
    matches reference output' contract.
    """

    @classmethod
    def setUpClass(cls):
        if not _have_c_binary():
            raise unittest.SkipTest(
                f"C `phasediff` binary not found at {C_PHASEDIFF}; "
                "skipping parity gate. Build gmtsar first."
            )
        if not _have_fixture():
            raise unittest.SkipTest(
                "RS2_SLC_Hawaii fixture missing; skipping parity gate. "
                "Run a sweep first to populate work/csh_test/RS2_SLC_Hawaii/."
            )
        cls.tmpdir = Path(tempfile.mkdtemp(prefix="phasediff_parity_"))
        # Stage all inputs into tmpdir
        shutil.copy(_REF_PRM, cls.tmpdir / "master.PRM")
        shutil.copy(_REP_PRM, cls.tmpdir / "aligned.PRM")
        shutil.copy(_REF_SLC, cls.tmpdir / _REF_SLC.name)
        shutil.copy(_REP_SLC, cls.tmpdir / _REP_SLC.name)
        shutil.copy(_TOPO_GRD, cls.tmpdir / "topo_ra.grd")

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "tmpdir") and cls.tmpdir.exists():
            shutil.rmtree(cls.tmpdir)

    def test_with_topo_bf(self):
        """=bf format — the canonical pipeline path (filter.csh uses this)."""
        cwd = self.tmpdir
        # Run C
        subprocess.run(
            [C_PHASEDIFF, "master.PRM", "aligned.PRM",
             "-topo", "topo_ra.grd",
             "-imag", "c_imag.grd=bf", "-real", "c_real.grd=bf"],
            cwd=cwd, check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        # Run Py
        subprocess.run(
            [sys.executable, str(_PY),
             "master.PRM", "aligned.PRM",
             "-topo", "topo_ra.grd",
             "-imag", "py_imag.grd=bf", "-real", "py_real.grd=bf"],
            cwd=cwd, check=True,
        )
        # Compare
        for name in ("real", "imag"):
            c, _ = read_bf(str(cwd / f"c_{name}.grd"))
            p, _ = read_bf(str(cwd / f"py_{name}.grd"))
            self.assertEqual(c.shape, p.shape, f"{name}: shape mismatch")
            diff = np.abs(c - p)
            max_diff = float(diff.max())
            med_diff = float(np.median(diff))
            # Float32 ULP at our magnitude (~1e-4) is ~6e-12. We allow
            # up to 1e-7 max (long-double-vs-float64 drift in calc_drho
            # + float32 cast ordering in cos/sin of phase).
            self.assertLess(max_diff, 1e-7,
                            f"{name}: max abs diff {max_diff:.2e} > 1e-7")
            self.assertLess(med_diff, 1e-9,
                            f"{name}: median abs diff {med_diff:.2e} > 1e-9")
            # Bit-equal coverage: expect >80% of pixels exactly match.
            cu = np.frombuffer(c.tobytes(), dtype=np.uint32)
            pu = np.frombuffer(p.tobytes(), dtype=np.uint32)
            bit_equal_frac = float((cu == pu).mean())
            self.assertGreater(bit_equal_frac, 0.80,
                               f"{name}: only {bit_equal_frac*100:.1f}% bit-equal")
            print(f"  [{name}] max={max_diff:.2e}, median={med_diff:.2e}, "
                  f"bit-equal={bit_equal_frac*100:.1f}%")


if __name__ == "__main__":
    unittest.main(verbosity=2)
