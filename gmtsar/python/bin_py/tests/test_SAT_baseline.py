#!/usr/bin/env python3
"""test_SAT_baseline — parity + checkpoint tests for SAT_baseline_py.

Two layers:
 1. Checkpoint unit tests for the Py-only helpers (cross3, find_dist,
    find_alpha_degrees, get_sign, xyz2plh round-trips).
 2. TestXVsCBinary — runs the C `SAT_baseline` and the Py port on the
    SAME canonical PRM pair, asserts BYTE-IDENTICAL stdout. Skipped
    gracefully if C binary or fixtures absent.

Per Mira's discipline: every port commit must include a parity test
that runs C on real data and asserts roundoff-identical output. For
this binary, "roundoff" is byte-identical — every value goes through
printf with fixed format, so any ULP-level disagreement in the floats
would shift the last printed digit. See PYGMT_ROADMAP.md / the Mira #2
ancestor's audit for the bug ladder we inherit.
"""
from __future__ import annotations

import math
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
_MOD = _HERE.parent / "SAT_baseline_py"

# Load SAT_baseline_py as a module (it has no .py extension).
import importlib.util as _ilu
import importlib.machinery as _ilm
_spec = _ilu.spec_from_loader(
    "sat_baseline_py_mod",
    _ilm.SourceFileLoader("sat_baseline_py_mod", str(_MOD)),
)
_NS_MOD = _ilu.module_from_spec(_spec)
sys.modules["sat_baseline_py_mod"] = _NS_MOD
_spec.loader.exec_module(_NS_MOD)
_NS: dict = _NS_MOD.__dict__

cross3 = _NS["cross3"]
find_dist = _NS["find_dist"]
find_alpha_degrees = _NS["find_alpha_degrees"]
find_unit_vectors = _NS["find_unit_vectors"]
get_sign = _NS["get_sign"]
xyz2plh = _NS["xyz2plh"]
goldop_sub = _NS["goldop_sub"]


# ---------- B2: small vector geometry --------------------------------------
class TestVectorGeometry(unittest.TestCase):
    """Verify cross3 / find_dist / find_alpha_degrees / find_unit_vectors
    against synthetic inputs."""

    def test_cross3_xy(self):
        """x × y = z."""
        a = np.array([1.0, 0.0, 0.0])
        b = np.array([0.0, 1.0, 0.0])
        np.testing.assert_array_equal(cross3(a, b), [0.0, 0.0, 1.0])

    def test_cross3_yz(self):
        """y × z = x."""
        a = np.array([0.0, 1.0, 0.0])
        b = np.array([0.0, 0.0, 1.0])
        np.testing.assert_array_equal(cross3(a, b), [1.0, 0.0, 0.0])

    def test_cross3_anti_symmetry(self):
        """a × b = -(b × a)."""
        a = np.array([0.1, -0.7, 0.42])
        b = np.array([-0.3, 0.2, 0.9])
        np.testing.assert_array_almost_equal(cross3(a, b), -cross3(b, a))

    def test_find_dist_zero(self):
        self.assertEqual(find_dist(1, 2, 3, 1, 2, 3), 0.0)

    def test_find_dist_axis(self):
        self.assertAlmostEqual(find_dist(3, 0, 0, 0, 0, 0), 3.0)

    def test_find_dist_3_4_5(self):
        """3-4-5 right triangle in 2D."""
        self.assertAlmostEqual(find_dist(3, 4, 0, 0, 0, 0), 5.0)

    def test_find_unit_vectors_axis(self):
        ru, xu, yu, zu = find_unit_vectors(10.0, 0.0, 0.0)
        self.assertAlmostEqual(ru, 10.0)
        self.assertAlmostEqual(xu, 1.0)
        self.assertAlmostEqual(yu, 0.0)
        self.assertAlmostEqual(zu, 0.0)

    def test_find_alpha_degrees_pure_h(self):
        """bv=0, bh>0 → atan2(0, bh) = 0 → 0 degrees."""
        self.assertAlmostEqual(find_alpha_degrees(0.0, 10.0), 0.0)

    def test_find_alpha_degrees_pure_v(self):
        """bv=10, bh=0 → atan2(10, 0) = π/2 → 90 degrees."""
        self.assertAlmostEqual(find_alpha_degrees(10.0, 0.0), 90.0)

    def test_find_alpha_degrees_45(self):
        """45° line."""
        self.assertAlmostEqual(find_alpha_degrees(1.0, 1.0), 45.0)


# ---------- B2: get_sign branching ---------------------------------------
class TestGetSign(unittest.TestCase):
    """Verify get_sign's 8 branch combinations (orbdir × lookdir × longitude
    comparison). Mirrors the 3 if's in SAT_baseline.c L532-538."""

    def test_default_signs_positive(self):
        """orbdir != 'D', lookdir != 'L', rlnrep >= rlnref → +1."""
        # Pick coordinates with x>0 so atan2 stays small; ref at (1, 0),
        # rep at (1, 0.1) → rlnrep > rlnref → no third negation.
        self.assertEqual(get_sign("A", "R", 1.0, 0.0, 1.0, 0.1), 1)

    def test_descending_negates(self):
        self.assertEqual(get_sign("D", "R", 1.0, 0.0, 1.0, 0.1), -1)

    def test_left_look_negates(self):
        self.assertEqual(get_sign("A", "L", 1.0, 0.0, 1.0, 0.1), -1)

    def test_descending_and_left_cancel(self):
        self.assertEqual(get_sign("D", "L", 1.0, 0.0, 1.0, 0.1), 1)

    def test_rln_less_negates(self):
        """rlnrep < rlnref → flip."""
        self.assertEqual(get_sign("A", "R", 1.0, 0.1, 1.0, 0.0), -1)

    def test_empty_orbdir_keeps_positive(self):
        """ENVI / NISAR PRMs may omit orbdir. C null_sio_struct leaves
        it as "XXXXXXXX" so strncmp("XXXX...", "D", 1) != 0 → no flip.
        Our Py code reads orbdir as "" via _prm_s default."""
        self.assertEqual(get_sign("", "R", 1.0, 0.0, 1.0, 0.1), 1)


# ---------- B2: xyz2plh round-trips with plh2xyz ----------------------------
class TestXyz2Plh(unittest.TestCase):
    """xyz2plh ↔ plh2xyz inverse pair on WGS84 ellipsoid."""

    WGS84_A = 6378137.0
    WGS84_F = 1.0 / 298.257223563

    def test_origin_equator(self):
        """xyz=(a, 0, 0) → lat=0, lon=0, h=0."""
        out = xyz2plh(np.array([self.WGS84_A, 0.0, 0.0]),
                      self.WGS84_A, self.WGS84_F)
        self.assertAlmostEqual(out[0], 0.0, places=5)  # lat
        # lon should be 0 (atan2(0, A) = 0)
        self.assertAlmostEqual(out[1], 0.0, places=5)
        self.assertAlmostEqual(out[2], 0.0, places=1)  # h

    def test_near_north_pole(self):
        """xyz near pole → lat near 90. (C plxyz.c notes: 'This routine
        will fail for points on the Z axis, i.e. if X = Y = 0' — both
        C and Py raise/diverge there; we test near-pole instead.)"""
        b = self.WGS84_A * (1.0 - self.WGS84_F)
        out = xyz2plh(np.array([1.0, 1.0, b - 0.5]),
                      self.WGS84_A, self.WGS84_F)
        self.assertGreater(out[0], 89.9)
        self.assertLess(out[0], 90.0)

    def test_real_target_in_sar_range(self):
        """Real-world ECEF point used by SAT_baseline target shoot
        (RS2 Hawaii test fixture). xyz2plh should produce sensible
        (lat, lon, h) in WGS84 degrees / metres."""
        # ECEF for ~(19.4 deg N, 204.7 deg E) altitude ~215 m
        target = np.array([-5468893.4420498842, -2512592.576389336,
                           2105136.0727659292])
        ra = 6378137.0
        rc = 6356752.31
        fll = (ra - rc) / ra
        out = xyz2plh(target, ra, fll)
        self.assertAlmostEqual(out[0], 19.399044, places=5)
        self.assertAlmostEqual(out[1], 204.675633, places=5)
        self.assertAlmostEqual(out[2], 215.495, places=1)


# ---------- B5: goldop_sub mirrors SAT_llt2rat_sub.c (TOL=3) ------------
class TestGoldopSub(unittest.TestCase):
    """Verify our goldop_sub picks closest-approach on a synthetic orbit.
    Note: TOL=3 means the converged window may be ±3 grid points instead
    of ±2 — wider than SAT_llt2rat.c's main goldop. Required for parity
    with C SAT_llt2rat_sub.c llt2rat_sub callers (Mira #11)."""

    def test_recovers_closest_approach(self):
        """Straight orbit in +x at y=1000, z=0; target at (500, 0, 0).
        Closest approach is at t=10, range=1000."""
        ts = np.arange(0, 20.01, 0.1)
        n = ts.size
        op = np.column_stack([ts, 50.0 * ts, np.full(n, 1000.0), np.zeros(n)])
        rng, tm = goldop_sub(op, 500.0, 0.0, 0.0)
        # TOL=3 → tm within ±3 grid samples → ±0.3 s
        self.assertAlmostEqual(tm, 10.0, delta=0.3)
        self.assertAlmostEqual(rng, 1000.0, delta=2.0)


# ---------- C-parity end-to-end (the Mira guardrail) -----------------------
class TestSATBaselineCParity(unittest.TestCase):
    """End-to-end byte-level parity vs C `SAT_baseline`.

    Per Mira's discipline: every port commit must include a parity test
    that runs C on the canonical real-data input and asserts BYTE-equal
    output. We diff stdout + stderr to catch both the PRM-key value
    drift and any banner-line regression.

    The C SAT_baseline.c always writes 22 stdout lines (3 banner lines +
    19 PRM key=value lines). Each %.12f value is sensitive to ULP-level
    differences in the underlying double, so a regression in plh2xyz /
    Hermite / goldop_sub will shift the last printed digit and fail this
    test.

    Skips gracefully if C binary or fixture PRMs are absent. Does NOT
    silently pass on missing data — per failure-avoidance checklist.
    """

    C_BIN = "/home/staff/dliu/gmtsar/bin/SAT_baseline"

    # (case-name, dir, master.PRM, aligned.PRM)
    CASES = [
        ("RS2",
         "/home/utig5/dliu/gmtsar/gmtsar/python/work/csh_test/RS2_SLC_Hawaii/SLC",
         "RS220110515.PRM", "RS220110819.PRM"),
        ("ALOS_haiti",
         "/home/utig5/dliu/gmtsar/gmtsar/python/work/csh_test/ALOS_haiti/SLC",
         "IMG-HH-ALPSRP166373240-H1.0__D.PRM",
         "IMG-HH-ALPSRP213343240-H1.0__D.PRM"),
        ("TSX_Hawaii",
         "/home/utig5/dliu/gmtsar/gmtsar/python/work/csh_test/TSX_SLC_Hawaii/SLC",
         "TSX20120615.PRM", "TSX20121208.PRM"),
        ("ENVI_Baja",
         "/home/utig5/dliu/gmtsar/gmtsar/python/work/csh_test/ENVI_Baja_EQ/SLC",
         "ENV1_2_084_2943_2961_42222.PRM",
         "ENV1_2_084_2943_2961_42723.PRM"),
        ("ALOS_SLC",
         "/home/utig5/dliu/gmtsar/gmtsar/python/work/csh_test/ALOS_SLC_L1.1/SLC",
         "IMG-HH-ALPSRP223500660-H1.1__A.PRM",
         "IMG-HH-ALPSRP230210660-H1.1__A.PRM"),
    ]

    @classmethod
    def setUpClass(cls):
        if not Path(cls.C_BIN).exists():
            raise unittest.SkipTest(
                f"C SAT_baseline binary not present at {cls.C_BIN}")

    def _run_case(self, name: str, dir_path: str,
                  master: str, aligned: str) -> None:
        d = Path(dir_path)
        if not d.exists():
            self.skipTest(f"{name}: fixture dir missing: {d}")
        for f in (master, aligned):
            if not (d / f).exists():
                self.skipTest(f"{name}: fixture file missing: {d/f}")
            led = d / (f[:-4] + ".LED")
            if not led.exists():
                self.skipTest(f"{name}: LED missing: {led}")

        c_run = subprocess.run(
            [self.C_BIN, master, aligned],
            cwd=str(d), capture_output=True, check=False)
        py_run = subprocess.run(
            [sys.executable, str(_MOD), master, aligned],
            cwd=str(d), capture_output=True, check=False)

        self.assertEqual(c_run.returncode, 0,
                         f"{name}: C SAT_baseline failed: {c_run.stderr!r}")
        self.assertEqual(py_run.returncode, 0,
                         f"{name}: Py SAT_baseline_py failed: {py_run.stderr!r}")

        # stdout must be byte-identical.
        if c_run.stdout != py_run.stdout:
            # Show first diverging line for the failure message.
            c_lines = c_run.stdout.decode().splitlines()
            p_lines = py_run.stdout.decode().splitlines()
            for i, (a, b) in enumerate(zip(c_lines, p_lines)):
                if a != b:
                    self.fail(
                        f"{name}: stdout diverges at line {i+1}:\n"
                        f"  C : {a!r}\n  Py: {b!r}")
            self.fail(
                f"{name}: stdout length differs "
                f"(C={len(c_lines)} Py={len(p_lines)})")

        # stderr must also match (banner + LED file messages).
        self.assertEqual(
            c_run.stderr, py_run.stderr,
            f"{name}: stderr diverges:\n  C : {c_run.stderr!r}\n  Py: {py_run.stderr!r}")

    def test_RS2_byte_identical(self):
        self._run_case(*self.CASES[0])

    def test_ALOS_haiti_byte_identical(self):
        self._run_case(*self.CASES[1])

    def test_TSX_Hawaii_byte_identical(self):
        self._run_case(*self.CASES[2])

    def test_ENVI_Baja_byte_identical(self):
        """Regression test for Mira #12 (this port): ENVI PRMs omit
        `orbdir`, so the rep PRM's orbdir must come from
        calc_height_velocity (vz>0 → A else D), NOT the master PRM."""
        self._run_case(*self.CASES[3])

    def test_ALOS_SLC_byte_identical(self):
        self._run_case(*self.CASES[4])


if __name__ == "__main__":
    unittest.main()
