#!/usr/bin/env python3
"""test_SAT_llt2rat — checkpoint-aligned unit tests for SAT_llt2rat_py."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
_MOD = _HERE.parent / "SAT_llt2rat_py"
_NS: dict = {"__file__": str(_MOD), "__name__": "sat_llt2rat_module"}
exec(compile(_MOD.read_text(), str(_MOD), "exec"), _NS)
read_prm = _NS["read_prm"]
read_led = _NS["read_led"]
plh2xyz = _NS["plh2xyz"]
hermite_orbit = _NS["hermite_orbit"]
presample_orbit = _NS["presample_orbit"]
goldop = _NS["goldop"]
polyfit_refine = _NS["polyfit_refine"]
to_pixel_coords = _NS["to_pixel_coords"]


# ---------- C1 read PRM / LED -----------------------------------------------
class TestC1ReadPrmLed(unittest.TestCase):
    LIVE_DIR = Path("/home/utig5/dliu/gmtsar/gmtsar/python/work/python_test/"
                    "RS2_SLC_Hawaii/raw")

    def test_read_led_rs2(self):
        led = self.LIVE_DIR / "RS220110515.LED"
        if not led.exists():
            self.skipTest("RS2 LED file not present")
        meta, orbit = read_led(str(led))
        self.assertEqual(meta["nd"], 35)
        self.assertEqual(orbit.shape, (35, 7))
        # time monotonically increasing
        self.assertTrue((np.diff(orbit[:, 0]) > 0).all())
        # px magnitudes are ECEF-scale (~6.4e6 m)
        r = np.sqrt(orbit[:, 1] ** 2 + orbit[:, 2] ** 2 + orbit[:, 3] ** 2)
        self.assertTrue(((r > 6e6) & (r < 8e6)).all(),
                        msg="expected RS2 orbit radii in 6-8 Mm range")


# ---------- C2 plh2xyz ------------------------------------------------------
class TestC2Plh2xyz(unittest.TestCase):
    """Sanity checks against well-known WGS84 reference points."""
    WGS84_A = 6378137.0
    WGS84_F = 1.0 / 298.257223563

    def test_origin_equator_prime_meridian(self):
        """lat=0, lon=0, h=0 → (a, 0, 0)."""
        xyz = plh2xyz(np.array([0.0]), np.array([0.0]), np.array([0.0]),
                      self.WGS84_A, self.WGS84_F)[0]
        np.testing.assert_allclose(xyz, [self.WGS84_A, 0.0, 0.0], atol=1e-6)

    def test_equator_90E(self):
        """lat=0, lon=90, h=0 → (0, a, 0)."""
        xyz = plh2xyz(np.array([0.0]), np.array([90.0]), np.array([0.0]),
                      self.WGS84_A, self.WGS84_F)[0]
        np.testing.assert_allclose(xyz, [0.0, self.WGS84_A, 0.0], atol=1e-6)

    def test_north_pole(self):
        """lat=90, lon=any, h=0 → (0, 0, b) where b = a*(1 - f)."""
        b = self.WGS84_A * (1.0 - self.WGS84_F)
        xyz = plh2xyz(np.array([90.0]), np.array([0.0]), np.array([0.0]),
                      self.WGS84_A, self.WGS84_F)[0]
        np.testing.assert_allclose(xyz[:2], [0.0, 0.0], atol=1.0)
        self.assertAlmostEqual(xyz[2], b, places=1)

    def test_height_adds_to_radial(self):
        """For points on the equator, adding height h adds exactly h to the
        radial distance."""
        xyz0 = plh2xyz(np.array([0.0]), np.array([0.0]), np.array([0.0]),
                       self.WGS84_A, self.WGS84_F)[0]
        xyz1 = plh2xyz(np.array([0.0]), np.array([0.0]), np.array([1000.0]),
                       self.WGS84_A, self.WGS84_F)[0]
        r0 = np.linalg.norm(xyz0)
        r1 = np.linalg.norm(xyz1)
        self.assertAlmostEqual(r1 - r0, 1000.0, places=3)


# ---------- C3 Hermite interp -----------------------------------------------
class TestC3HermiteOrbit(unittest.TestCase):
    def test_endpoints_exact(self):
        """At the orbit knot times, Hermite returns the stored positions
        (within float noise)."""
        # Synthetic: linear motion in 3D
        t = np.linspace(0, 10, 5)
        px = 100.0 + 50.0 * t
        py = 200.0 - 30.0 * t
        pz = 0.0 * t
        vx = np.full_like(t, 50.0); vy = np.full_like(t, -30.0); vz = np.zeros_like(t)
        orbit = np.column_stack([t, px, py, pz, vx, vy, vz])
        p_at = hermite_orbit(orbit[:, 0:7], orbit, t)
        np.testing.assert_allclose(p_at[:, 0], px, atol=1e-6)
        np.testing.assert_allclose(p_at[:, 1], py, atol=1e-6)

    def test_linear_motion_midpoint(self):
        """Linear motion → midpoint interpolation hits the line exactly."""
        t = np.linspace(0, 10, 5)
        orbit = np.column_stack([t, 100 + 50*t, 200 - 30*t, np.zeros_like(t),
                                  np.full_like(t, 50.0),
                                  np.full_like(t, -30.0),
                                  np.zeros_like(t)])
        mid = hermite_orbit(orbit[:, 0:7], orbit, np.array([5.0]))[0]
        np.testing.assert_allclose(mid, [350.0, 50.0, 0.0], atol=1e-6)


# ---------- C4 pre-sample ---------------------------------------------------
class TestC4PresampleOrbit(unittest.TestCase):
    def test_length_matches_expected(self):
        t = np.linspace(0, 10, 5)
        orbit = np.column_stack([t, 50*t, np.zeros_like(t), np.zeros_like(t),
                                  np.full_like(t, 50.0),
                                  np.zeros_like(t),
                                  np.zeros_like(t)])
        ts = 0.5
        op = presample_orbit(orbit, 0.0, 10.0, ts)
        self.assertGreaterEqual(op.shape[0], 21)
        self.assertEqual(op.shape[1], 4)
        # First and last time match
        self.assertAlmostEqual(op[0, 0], 0.0)
        self.assertAlmostEqual(op[-1, 0], 10.0)


# ---------- C5 goldop -------------------------------------------------------
class TestC5Goldop(unittest.TestCase):
    def test_recovers_closest_approach_synthetic(self):
        """Straight-line orbit; place target at known closest-approach point;
        goldop should land near that point."""
        # Orbit: straight line along +x at y=1000, z=0, from t=0..20
        ts = np.arange(0, 20.01, 0.1)
        n = ts.size
        op = np.column_stack([ts, 50.0 * ts, np.full(n, 1000.0), np.zeros(n)])
        # Target at (500, 0, 0). Closest approach is at t=10 (orbit at x=500),
        # range = 1000.
        rng, tm = goldop(op, 500.0, 0.0, 0.0)
        self.assertAlmostEqual(tm, 10.0, delta=0.1)
        self.assertAlmostEqual(rng, 1000.0, delta=1.0)


# ---------- C6 polyfit refine -----------------------------------------------
class TestC6PolyfitRefine(unittest.TestCase):
    def test_refines_closest_approach(self):
        """Smooth-orbit synthetic; refine should not move tm by more than ts/2
        and should yield ≤ initial range."""
        # Slow curvature: position with quadratic-in-time deviation
        ts = np.arange(0, 20.01, 1.0)
        n = ts.size
        # Orbit straight line + a small quadratic bump in y
        py = 1000.0 + 0.5 * (ts - 10) ** 2
        vy = 1.0 * (ts - 10)
        orbit = np.column_stack([ts, 50.0 * ts, py, np.zeros(n),
                                  np.full(n, 50.0), vy, np.zeros(n)])
        # Target at (500, 0, 0). Closest approach is near t=10 (orbit at 500
        # in x, but the y-bump means actual minimum is slightly off-grid).
        rng_init = np.sqrt((500 - 50*10)**2 + (1000 - 0)**2)
        rng_ref, tm_ref = polyfit_refine(orbit, 10.0, 500.0, 0.0, 0.0)
        self.assertLessEqual(rng_ref, rng_init + 1e-3)
        self.assertAlmostEqual(tm_ref, 10.0, delta=0.5)


# ---------- C7 pixel coords -------------------------------------------------
class TestC7PixelCoords(unittest.TestCase):
    def test_at_near_range(self):
        """Point at exact near_range, time t1 → range_pix = 0, azi_pix = 0
        (no shifts)."""
        prm = {"near_range": "1000000.0", "rshift": "0", "sub_int_r": "0",
               "chirp_ext": "0", "PRF": "1500.0", "ashift": "0",
               "sub_int_a": "0"}
        dr = 5.0
        t1 = 0.0
        rp, ap = to_pixel_coords(rng0=1000000.0, tm=0.0, prm=prm, dr=dr, t1=t1)
        self.assertAlmostEqual(rp, 0.0)
        self.assertAlmostEqual(ap, 0.0)

    def test_pixel_arithmetic(self):
        """Verify (rng0 - near_range)/dr - shifts + chirp_ext."""
        prm = {"near_range": "1000000.0", "rshift": "10", "sub_int_r": "0.5",
               "chirp_ext": "20", "PRF": "1500.0", "ashift": "5",
               "sub_int_a": "0.25"}
        dr = 5.0; t1 = 100.0
        # 1000050 - 1000000 = 50; /5 = 10; minus (10+0.5) + 20 = 19.5
        rp, ap = to_pixel_coords(rng0=1000050.0, tm=100.5, prm=prm, dr=dr, t1=t1)
        self.assertAlmostEqual(rp, 19.5)
        # 1500*(100.5 - 100) - (5+0.25) = 750 - 5.25 = 744.75
        self.assertAlmostEqual(ap, 744.75)


if __name__ == "__main__":
    unittest.main(verbosity=2)
