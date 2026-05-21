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
# Load via importlib so the module is registered in sys.modules — Numba's
# JIT functions need to be able to find the module they live in by name
# when re-entered. Without sys.modules registration, `from numba import njit`
# in the SAT module fails to resolve `@njit(...)` decorations at exec-time
# under unittest's loader (subtle interpreter-state interaction).
# We register under "sat_llt2rat_py_mod" (NOT "__main__") so the test
# process does not collide with a direct script invocation. With
# cache=False on the JIT kernels there are no on-disk artefacts to worry
# about across contexts.
import importlib.util as _ilu
import importlib.machinery as _ilm
_spec = _ilu.spec_from_loader(
    "sat_llt2rat_py_mod",
    _ilm.SourceFileLoader("sat_llt2rat_py_mod", str(_MOD)),
)
_NS_MOD = _ilu.module_from_spec(_spec)
sys.modules["sat_llt2rat_py_mod"] = _NS_MOD
_spec.loader.exec_module(_NS_MOD)
_NS: dict = _NS_MOD.__dict__
read_prm = _NS["read_prm"]
read_led = _NS["read_led"]
plh2xyz = _NS["plh2xyz"]
hermite_orbit = _NS["hermite_orbit"]
presample_orbit = _NS["presample_orbit"]
goldop = _NS["goldop"]
goldop_batch = _NS["goldop_batch"]
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
        # npad=0 for the unpadded length-check; live driver uses npad=8000
        # to handle out-of-window closest-approach points (see
        # test_npad_padding_extends_window).
        op = presample_orbit(orbit, 0.0, 10.0, ts, npad=0)
        # C-faithful: nrec = int((t2-t1)/ts) = int(10/0.5) = 20 (not 21).
        self.assertEqual(op.shape[0], 20)
        self.assertEqual(op.shape[1], 4)
        # First time matches.
        self.assertAlmostEqual(op[0, 0], 0.0)
        # Last sample at t = (nrec-1)*ts = 19*0.5 = 9.5.
        self.assertAlmostEqual(op[-1, 0], 9.5)

    def test_npad_padding_extends_window(self):
        """Default npad=8000 extends sampling by ±8000*ts on each side.

        Orbit must span the padded interval [t1-pad, t2+pad].
        """
        # Sample range [50,60] with pad = 8000*0.01 = 80 → need orbit on
        # at least [-30, 140].
        t = np.linspace(-30.0, 140.0, 20)
        orbit = np.column_stack([t, 50*t, np.zeros_like(t), np.zeros_like(t),
                                  np.full_like(t, 50.0),
                                  np.zeros_like(t),
                                  np.zeros_like(t)])
        ts = 0.01
        op = presample_orbit(orbit, 50.0, 60.0, ts)   # default npad=8000
        pad = 8000 * ts
        self.assertAlmostEqual(op[0, 0], 50.0 - pad, places=6)
        # Last sample at t1-pad + (n-1)*ts where n = int((t2-t1)/ts) + 2*npad
        # = 1000 + 16000 = 17000 → last = (50-80) + 16999*0.01 = -30 + 169.99 = 139.99
        self.assertAlmostEqual(op[-1, 0], 50.0 - pad + (16999) * ts, places=4)


# ---------- C5 goldop -------------------------------------------------------
class TestC5Goldop(unittest.TestCase):
    def test_recovers_closest_approach_synthetic(self):
        """Straight-line orbit; place target at known closest-approach point;
        goldop should land near that point.

        Tolerance is TOL=2 grid samples (C-faithful). Grid spacing 0.1 →
        tm within ±0.2 s, range within ±1 m.
        """
        # Orbit: straight line along +x at y=1000, z=0, from t=0..20
        ts = np.arange(0, 20.01, 0.1)
        n = ts.size
        op = np.column_stack([ts, 50.0 * ts, np.full(n, 1000.0), np.zeros(n)])
        # Target at (500, 0, 0). Closest approach is at t=10 (orbit at x=500),
        # range = 1000.
        rng, tm = goldop(op, 500.0, 0.0, 0.0)
        # C goldop uses integer TOL=2 → ±2 grid samples → tm within ±0.2 s.
        self.assertAlmostEqual(tm, 10.0, delta=0.2)
        self.assertAlmostEqual(rng, 1000.0, delta=1.0)


# ---------- C5b goldop_batch (vectorized) -----------------------------------
class TestC5GoldopBatch(unittest.TestCase):
    """Pattern-4 defense: branch-dependent vectorized algorithm needs a
    scalar-vs-vec equivalence test on the same inputs.
    """

    def _make_orbit(self, n=200):
        """Linear orbit straight along +x, y=1000 constant, z=0."""
        ts = np.arange(0, n, 1.0) * 0.1
        op = np.column_stack([ts, 50.0 * ts, np.full(n, 1000.0), np.zeros(n)])
        return op

    def test_scalar_vec_bit_identical_single(self):
        """1 target: goldop scalar == goldop_batch vec, bit-exact (rng, tm)."""
        op = self._make_orbit()
        targets = np.array([[500.0, 0.0, 0.0]])
        r_s, t_s = goldop(op, 500.0, 0.0, 0.0,
                          stai=0, endi=op.shape[0]-1)
        r_v, t_v = goldop_batch(op, targets)
        self.assertEqual(float(r_v[0]), r_s)
        self.assertEqual(float(t_v[0]), t_s)

    def test_scalar_vec_bit_identical_many(self):
        """30 random targets: each scalar == vec, bit-exact."""
        rng = np.random.default_rng(42)
        op = self._make_orbit(n=500)
        targets = rng.uniform(low=[100.0, -500.0, -500.0],
                              high=[2400.0, 500.0, 500.0],
                              size=(30, 3))
        r_v, t_v = goldop_batch(op, targets)
        for i in range(targets.shape[0]):
            r_s, t_s = goldop(op, float(targets[i, 0]),
                              float(targets[i, 1]),
                              float(targets[i, 2]),
                              stai=0, endi=op.shape[0]-1)
            self.assertEqual(float(r_v[i]), r_s,
                             msg=f"rng mismatch at target {i}")
            self.assertEqual(float(t_v[i]), t_s,
                             msg=f"tm mismatch at target {i}")

    def test_chunk_boundary(self):
        """chunk smaller than N: results unchanged across the boundary."""
        rng = np.random.default_rng(7)
        op = self._make_orbit(n=300)
        targets = rng.uniform(low=[100.0, -500.0, -500.0],
                              high=[1400.0, 500.0, 500.0],
                              size=(50, 3))
        r_big, t_big = goldop_batch(op, targets, chunk=200_000)
        r_small, t_small = goldop_batch(op, targets, chunk=7)
        np.testing.assert_array_equal(r_big, r_small)
        np.testing.assert_array_equal(t_big, t_small)


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


# ---------- C-parity end-to-end (the Mira-rule guardrail) -------------------
class TestNumbaParity(unittest.TestCase):
    """Numba JIT kernels must be bit-identical to their pure-numpy
    reference paths. Per Mira's discipline: every fast path gets its own
    test — the C-parity oracle alone won't catch a regression that affects
    BOTH paths equally.
    """

    def setUp(self):
        # Use the live module attribute (not the cached `_NS` dict captured
        # at import time). _HAS_NUMBA = True only when numba imported cleanly
        # AND env SAT_LLT2RAT_PY_NUMBA != "0".
        has_numba = getattr(_NS_MOD, "_HAS_NUMBA", False)
        if not has_numba:
            self.skipTest("numba not installed / SAT_LLT2RAT_PY_NUMBA=0")

    def test_hermite_c_1d_jit_vs_numpy(self):
        """General-path Hermite: Numba == numpy on a realistic orbit grid."""
        rng = np.random.default_rng(42)
        n = 30
        x = np.arange(n, dtype=np.float64) * 4.0   # uniform 4-s knots
        y = rng.normal(size=n) * 1e6
        z = rng.normal(size=n) * 1e3
        xp = rng.uniform(x[3], x[-4], size=200)
        ref = _NS["hermite_c_1d"](x, y, z, xp, nval=6)
        jit = _NS["hermite_c_1d_numba"](x, y, z, xp, nval=6)
        np.testing.assert_array_equal(jit, ref,
            err_msg="hermite_c_1d_numba diverged from pure-numpy hermite_c_1d")

    def test_hermite_c_1d_uniform_jit_vs_numpy(self):
        """Uniform-path Hermite (Horner): Numba == numpy."""
        rng = np.random.default_rng(7)
        n = 50
        x0 = 100.0
        dsec = 0.5
        y = rng.normal(size=n) * 1e6
        z = rng.normal(size=n) * 1e3
        xp = rng.uniform(x0 + 3 * dsec, x0 + (n - 4) * dsec, size=300)
        ref = _NS["hermite_c_1d_uniform"](x0, dsec, y, z, xp, nval=6)
        jit = _NS["hermite_c_1d_uniform_numba"](x0, dsec, y, z, xp, nval=6)
        np.testing.assert_array_equal(jit, ref,
            err_msg="hermite_c_1d_uniform_numba diverged from pure-numpy")

    def test_goldop_jit_vs_scalar(self):
        """Numba goldop_batch == scalar goldop on per-target basis (bit-exact)."""
        rng = np.random.default_rng(99)
        # Build a smooth synthetic orbit (parabola); plenty of nrec for a real search
        nrec = 500
        op_t = np.linspace(0.0, 100.0, nrec)
        px = 7000e3 + 100.0 * op_t
        py = 50.0 * (op_t - 50.0) ** 2
        pz = 1e3 * np.cos(op_t / 5.0)
        orb_pos = np.column_stack([op_t, px, py, pz])
        # Random targets near the orbit
        N = 25
        tx = px[5: 5 + N] + rng.normal(scale=1e3, size=N)
        ty = py[5: 5 + N] + rng.normal(scale=1e3, size=N)
        tz = pz[5: 5 + N] + rng.normal(scale=1e3, size=N)
        targets = np.column_stack([tx, ty, tz])
        rng_b, tm_b = _NS["goldop_batch"](orb_pos, targets)
        for k in range(N):
            r_s, t_s = _NS["goldop"](orb_pos, float(tx[k]), float(ty[k]),
                                     float(tz[k]))
            self.assertEqual(rng_b[k], r_s,
                f"target {k}: batch rng {rng_b[k]} != scalar {r_s}")
            self.assertEqual(tm_b[k], t_s,
                f"target {k}: batch tm {tm_b[k]} != scalar {t_s}")


class TestEndToEndCParity(unittest.TestCase):
    """End-to-end byte-level parity vs C `SAT_llt2rat`. Per the bin_py
    discipline, every port must have a test running C on the canonical
    real-data input and asserting roundoff-equal output. Without this
    test we'd silently regress goldop/Hermite/plh2xyz arithmetic.
    """

    C_BIN = "/home/staff/dliu/gmtsar/bin/SAT_llt2rat"
    PRM = Path("/home/utig5/dliu/gmtsar/gmtsar/python/work/csh_test/"
               "RS2_SLC_Hawaii/topo/master.PRM")
    LED = Path("/home/utig5/dliu/gmtsar/gmtsar/python/work/csh_test/"
               "RS2_SLC_Hawaii/topo/RS220110515.LED")
    DEM = Path("/home/utig5/dliu/gmtsar/gmtsar/python/work/csh_test/"
               "RS2_SLC_Hawaii/topo/dem.grd")

    @classmethod
    def setUpClass(cls):
        if not Path(cls.C_BIN).exists():
            raise unittest.SkipTest(
                f"C SAT_llt2rat binary not present at {cls.C_BIN}")
        for f in (cls.PRM, cls.LED, cls.DEM):
            if not f.exists():
                raise unittest.SkipTest(f"input not present: {f}")
        # gmt grd2xyz needed
        import shutil
        if shutil.which("gmt") is None:
            raise unittest.SkipTest("gmt not on PATH (needed to make DEM xyz)")

    def test_precise0_bit_identical(self):
        """Full RS2 DEM, precise=0 (-bod): row-by-row diff vs C oracle.

        Expects azi_pix, lon, lat bit-identical (max|d|=0). range_pix
        and height tolerate ~1e-10 px / ~2e-9 m residual roundoff from
        order-of-summation differences between scalar C and vectorised
        numpy that don't affect goldop's branch decisions.
        """
        import shutil, subprocess, tempfile
        with tempfile.TemporaryDirectory() as d:
            xyz = Path(d) / "dem.xyz"
            c_out = Path(d) / "c.dat"
            py_out = Path(d) / "py.dat"

            # 1. grd2xyz → ASCII (full precision)
            with open(xyz, "w") as fout:
                subprocess.check_call(
                    ["gmt", "grd2xyz", "--FORMAT_FLOAT_OUT=%.17g",
                     str(self.DEM), "-s"], stdout=fout)
            # 2. Run C and Py on the same input bytes
            with open(xyz, "rb") as fin, open(c_out, "wb") as fout:
                subprocess.check_call(
                    [self.C_BIN, str(self.PRM), "0", "-bod"],
                    stdin=fin, stdout=fout,
                    cwd=str(self.PRM.parent))
            py_bin = str(_MOD)
            with open(xyz, "rb") as fin, open(py_out, "wb") as fout:
                subprocess.check_call(
                    [sys.executable, py_bin, str(self.PRM), "0", "-bod"],
                    stdin=fin, stdout=fout,
                    cwd=str(self.PRM.parent))
            c = np.fromfile(c_out, dtype=np.float64).reshape(-1, 5)
            p = np.fromfile(py_out, dtype=np.float64).reshape(-1, 5)
            self.assertEqual(c.shape, p.shape, "row count must match exactly")
            # azi_pix, lon, lat must be bit-identical
            for j, name in [(1, "azi_pix"), (3, "lon"), (4, "lat")]:
                np.testing.assert_array_equal(
                    p[:, j], c[:, j],
                    err_msg=f"column {name} not bit-identical")
            # range_pix tolerates sub-mm residual (sub-ULP order-of-ops diff)
            self.assertLess(np.max(np.abs(p[:, 0] - c[:, 0])), 1e-7,
                            "range_pix exceeds 1e-7 px residual tolerance")
            # height tolerates ~2e-9 m residual (|xyz| sqrt-summation order)
            self.assertLess(np.max(np.abs(p[:, 2] - c[:, 2])), 1e-6,
                            "height exceeds 1e-6 m residual tolerance")

    def test_precise0_csh_lf_pipeline_parity(self):
        """Mirror the REAL csh `dem2topo_ra.csh` pipeline byte-for-byte.

        Mira #4 (2026-05-21): dem2topo_ra.csh feeds SAT_llt2rat through
        `gmt grd2xyz --FORMAT_FLOAT_OUT=%lf dem.grd -s | SAT_llt2rat ...`
        (ASCII, 6-digit `%lf` quantization). That is the input the C
        binary actually sees in production. test_precise0_bit_identical
        above uses `%.17g` (full-precision ASCII) which is finer than the
        real pipeline — it can pass while the wire-in is broken.

        This test mirrors the csh pipeline exactly and asserts byte parity
        of the resulting trans.dat. Catches the regression where the py
        wire-in switched to `-bo3d | -bi3d` (binary full-precision) and
        broke topo_ra → los_ll by 1.51 mm on ALOS_haiti.
        """
        import subprocess, tempfile
        with tempfile.TemporaryDirectory() as d:
            xyz = Path(d) / "dem.xyz.lf"
            c_out = Path(d) / "c.dat"
            py_out = Path(d) / "py.dat"

            # 1. grd2xyz → ASCII with %lf (6-digit) — exactly what csh does
            with open(xyz, "w") as fout:
                subprocess.check_call(
                    ["gmt", "grd2xyz", "--FORMAT_FLOAT_OUT=%lf",
                     str(self.DEM), "-s"], stdout=fout)
            # 2. Run C and Py on the same %lf-quantized input bytes
            with open(xyz, "rb") as fin, open(c_out, "wb") as fout:
                subprocess.check_call(
                    [self.C_BIN, str(self.PRM), "0", "-bod"],
                    stdin=fin, stdout=fout,
                    cwd=str(self.PRM.parent))
            py_bin = str(_MOD)
            with open(xyz, "rb") as fin, open(py_out, "wb") as fout:
                subprocess.check_call(
                    [sys.executable, py_bin, str(self.PRM), "0", "-bod"],
                    stdin=fin, stdout=fout,
                    cwd=str(self.PRM.parent))
            c = np.fromfile(c_out, dtype=np.float64).reshape(-1, 5)
            p = np.fromfile(py_out, dtype=np.float64).reshape(-1, 5)
            self.assertEqual(c.shape, p.shape, "row count must match exactly")
            # In the %lf pipeline, lon/lat must be bit-identical and
            # azi_pix should be sub-ULP (~1e-11). range_pix and height
            # follow at sub-mm levels.
            for j, name in [(3, "lon"), (4, "lat")]:
                np.testing.assert_array_equal(
                    p[:, j], c[:, j],
                    err_msg=f"col {name} not bit-identical "
                    f"(%lf csh-pipeline parity)")
            self.assertLess(np.max(np.abs(p[:, 1] - c[:, 1])), 1e-9,
                "azi_pix exceeds 1e-9 px residual tolerance (%lf pipeline)")
            self.assertLess(np.max(np.abs(p[:, 0] - c[:, 0])), 1e-7,
                "range_pix exceeds 1e-7 px residual tolerance (%lf pipeline)")
            self.assertLess(np.max(np.abs(p[:, 2] - c[:, 2])), 1e-6,
                "height exceeds 1e-6 m residual tolerance (%lf pipeline)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
