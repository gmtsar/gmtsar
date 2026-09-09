#!/usr/bin/env python3
"""test_vector — unit tests for utils/vector.py.

Verifies the shared @njit single-thread primitives extracted from the
existing bin_py JIT-kernel files. Each tier of primitives gets its own
TestCase:

  * Tier 1 (cross/dot/norm/plh2xyz) — pure unit semantics
    + parity vs the audited SAT_llt2rat_py reference for plh2xyz.
  * Tier 2 (hermite_c_1d, hermite_c_1d_uniform) — synthetic-polynomial
    exactness + parity vs the audited SAT_llt2rat_py reference paths
    on a synthetic orbit.
  * Tier 3 (goldop_search, polyfit_normal_eqs) — convergence and parity
    vs the audited SAT_llt2rat_py reference paths.

The parity targets are the existing implementations in
`bin_py/SAT_llt2rat_py` which Mira #2 already verified against the C
oracle on the RS2 canonical dataset. By matching THAT, we inherit the
C-parity audit for free — no need to spin up a C run here.

cross_3, dot_3, norm_3 don't have a SAT_llt2rat_py counterpart; we
verify them against `numpy.cross / @ / np.linalg.norm` on synthetic
inputs. The C-faithful `cross_3` component formula is the same as
numpy's for clean inputs (the 1-ULP gotcha only fires on extreme
mixed-magnitude vectors that don't appear in our test cases).
"""
from __future__ import annotations

import importlib.machinery as _ilm
import importlib.util as _ilu
import sys
import unittest
from pathlib import Path

import numpy as np


# ---------------------------------------------------------------------------
# Make utils/ importable.
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent
_PY_ROOT = _HERE.parent.parent  # gmtsar/python
sys.path.insert(0, str(_PY_ROOT))

from utils.vector import (                                                  # noqa: E402
    SOL, PI, TWOPI, DEG_TO_RAD, RAD_TO_DEG, R_GOLD, C_GOLD,
    cross_3, dot_3, norm_3, plh2xyz_scalar,
    hermite_c_1d, hermite_c_1d_uniform,
    goldop_search, polyfit_normal_eqs,
)


# ---------------------------------------------------------------------------
# Load the audited SAT_llt2rat_py reference module so we can compare against
# its plh2xyz / hermite_c_1d / goldop_batch / polyfit_c which Mira #2
# already verified bit-parity vs C on the RS2 canonical dataset.
# ---------------------------------------------------------------------------
_LLT_PATH = _HERE.parent / "SAT_llt2rat_py"
_spec = _ilu.spec_from_loader(
    "sat_llt2rat_py_for_vec_tests",
    _ilm.SourceFileLoader("sat_llt2rat_py_for_vec_tests", str(_LLT_PATH)),
)
_LLT = _ilu.module_from_spec(_spec)
sys.modules["sat_llt2rat_py_for_vec_tests"] = _LLT
_spec.loader.exec_module(_LLT)


# ---------------------------------------------------------------------------
# Tier 1 — Constants & basic vector primitives
# ---------------------------------------------------------------------------
class TestConstants(unittest.TestCase):
    """Constants must be C-#define-faithful, not mathematically correct."""

    def test_SOL_is_C_value_not_physical(self):
        # gmtsar.h:16  #define SOL 299792456.0  (2 m/s off from 299792458)
        self.assertEqual(SOL, 299792456.0)
        self.assertNotEqual(SOL, 299792458.0)

    def test_PI_is_truncated_14_digit(self):
        # llt2xyz.h:61  #define pi 3.14159265358979  (14 digits, NOT math.pi)
        import math
        self.assertEqual(PI, 3.14159265358979)
        self.assertNotEqual(PI, math.pi)
        # math.pi = 3.141592653589793  — ~3e-15 larger than PI
        diff = math.pi - PI
        self.assertGreater(diff, 1e-15)
        self.assertLess(diff, 1e-14)

    def test_derived_constants_use_truncated_PI(self):
        # llt2xyz.h:63-66: TWOPI, DEG_TO_RAD, RAD_TO_DEG derived from PI
        self.assertEqual(TWOPI, 2.0 * PI)
        self.assertEqual(DEG_TO_RAD, TWOPI / 360.0)
        self.assertEqual(RAD_TO_DEG, 360.0 / TWOPI)
        # DEG_TO_RAD is 1 ULP off from the "correct" value
        self.assertAlmostEqual(DEG_TO_RAD, 0.017453292519943278, places=18)

    def test_golden_ratio_constants_are_truncated(self):
        # SAT_llt2rat.c #define R 0.61803399; #define C 0.382
        # The TRUE values are R≈0.6180339887, C≈0.3819660113 (1-R).
        # C truncates BOTH, but C=0.382 OVERSHOOTS by ~4e-5 → sum > 1.0.
        # (NB: the SAT_llt2rat_py module comment says "R+C=0.99996601"
        #  but that's an arithmetic typo — actual sum is 1.00003399.)
        self.assertEqual(R_GOLD, 0.61803399)
        self.assertEqual(C_GOLD, 0.382)
        self.assertAlmostEqual(R_GOLD + C_GOLD, 1.00003399, places=10)
        self.assertNotEqual(R_GOLD + C_GOLD, 1.0)


class TestCross3(unittest.TestCase):
    """cross_3 — 3-vector cross product, C-faithful component formulae."""

    def test_unit_basis_vectors(self):
        # x cross y = z
        a = np.array([1.0, 0.0, 0.0])
        b = np.array([0.0, 1.0, 0.0])
        out = np.empty(3)
        cross_3(a, b, out)
        np.testing.assert_array_equal(out, [0.0, 0.0, 1.0])

        # y cross z = x
        cross_3(np.array([0.0, 1.0, 0.0]),
                np.array([0.0, 0.0, 1.0]), out)
        np.testing.assert_array_equal(out, [1.0, 0.0, 0.0])

        # z cross x = y
        cross_3(np.array([0.0, 0.0, 1.0]),
                np.array([1.0, 0.0, 0.0]), out)
        np.testing.assert_array_equal(out, [0.0, 1.0, 0.0])

    def test_anti_commutative(self):
        rng = np.random.default_rng(0)
        a = rng.standard_normal(3)
        b = rng.standard_normal(3)
        ab = np.empty(3)
        ba = np.empty(3)
        cross_3(a, b, ab)
        cross_3(b, a, ba)
        np.testing.assert_allclose(ab, -ba, rtol=0, atol=0)

    def test_self_cross_zero(self):
        rng = np.random.default_rng(1)
        v = rng.standard_normal(3)
        out = np.empty(3)
        cross_3(v, v, out)
        np.testing.assert_array_equal(out, [0.0, 0.0, 0.0])

    def test_against_numpy_cross(self):
        """For typical (similar-magnitude) inputs, cross_3 matches np.cross
        to roundoff. The 1-ULP gotcha in C ordering only fires for extreme
        mixed-magnitude vectors."""
        rng = np.random.default_rng(2)
        for _ in range(20):
            a = rng.standard_normal(3) * 1e6
            b = rng.standard_normal(3) * 1e6
            out = np.empty(3)
            cross_3(a, b, out)
            ref = np.cross(a, b)
            np.testing.assert_allclose(out, ref, rtol=1e-13, atol=1e-9)


class TestDot3(unittest.TestCase):

    def test_orthogonal(self):
        self.assertEqual(
            dot_3(np.array([1.0, 0.0, 0.0]),
                  np.array([0.0, 1.0, 0.0])), 0.0)

    def test_against_numpy(self):
        rng = np.random.default_rng(3)
        for _ in range(20):
            a = rng.standard_normal(3)
            b = rng.standard_normal(3)
            self.assertAlmostEqual(dot_3(a, b), float(a @ b), places=14)


class TestNorm3(unittest.TestCase):

    def test_unit_vectors_have_norm_1(self):
        for v in [[1, 0, 0], [0, 1, 0], [0, 0, 1]]:
            self.assertEqual(norm_3(np.array(v, dtype=np.float64)), 1.0)

    def test_345_triangle(self):
        # 3-4-12 -> 13  (3D Pythagorean)
        self.assertAlmostEqual(norm_3(np.array([3.0, 4.0, 12.0])), 13.0,
                               places=14)

    def test_against_numpy_norm(self):
        rng = np.random.default_rng(4)
        for _ in range(20):
            v = rng.standard_normal(3) * 1e6
            self.assertAlmostEqual(norm_3(v), float(np.linalg.norm(v)),
                                   places=8)


class TestPlh2XyzScalar(unittest.TestCase):
    """plh2xyz_scalar — C-faithful via truncated PI + (1-FL)^2.

    Parity target: SAT_llt2rat_py.plh2xyz (numpy vectorised, Mira #2
    audited bit-parity vs C on RS2 dataset). The two implementations
    use IDENTICAL constants and operation order; differences should be
    pure floating-point noise from numpy's vectorisation vs Numba's
    scalar Horner.
    """
    WGS84_A = 6378137.0
    WGS84_F = 1.0 / 298.257223563

    def test_origin_equator_prime_meridian(self):
        """lat=0, lon=0, h=0 → (A, 0, 0)."""
        x, y, z = plh2xyz_scalar(0.0, 0.0, 0.0, self.WGS84_A, self.WGS84_F)
        self.assertAlmostEqual(x, self.WGS84_A, places=6)
        self.assertAlmostEqual(y, 0.0, places=6)
        self.assertAlmostEqual(z, 0.0, places=6)

    def test_equator_90E(self):
        """lat=0, lon=90, h=0 → (0, A, 0)."""
        x, y, z = plh2xyz_scalar(0.0, 90.0, 0.0, self.WGS84_A, self.WGS84_F)
        self.assertAlmostEqual(x, 0.0, places=6)
        self.assertAlmostEqual(y, self.WGS84_A, places=6)
        self.assertAlmostEqual(z, 0.0, places=6)

    def test_north_pole(self):
        """lat=90 → z = B = A*(1-FL).  x,y ≈ 0 modulo cos(90°) noise."""
        b = self.WGS84_A * (1.0 - self.WGS84_F)
        x, y, z = plh2xyz_scalar(90.0, 0.0, 0.0, self.WGS84_A, self.WGS84_F)
        self.assertAlmostEqual(x, 0.0, places=1)
        self.assertAlmostEqual(y, 0.0, places=1)
        self.assertAlmostEqual(z, b, places=1)

    def test_height_adds_to_radial_at_equator(self):
        x0, y0, z0 = plh2xyz_scalar(0.0, 0.0, 0.0,
                                    self.WGS84_A, self.WGS84_F)
        x1, y1, z1 = plh2xyz_scalar(0.0, 0.0, 1000.0,
                                    self.WGS84_A, self.WGS84_F)
        r0 = np.sqrt(x0 * x0 + y0 * y0 + z0 * z0)
        r1 = np.sqrt(x1 * x1 + y1 * y1 + z1 * z1)
        self.assertAlmostEqual(r1 - r0, 1000.0, places=3)

    def test_parity_vs_SAT_llt2rat_py(self):
        """Compare scalar njit form vs SAT_llt2rat_py.plh2xyz (numpy
        vectorised, Mira #2 audited bit-parity vs C)."""
        rng = np.random.default_rng(42)
        # 100 random (lat, lon, h) points across the WGS84 ellipsoid
        lats = rng.uniform(-80.0, 80.0, 100)
        lons = rng.uniform(-180.0, 180.0, 100)
        hs = rng.uniform(-1000.0, 5000.0, 100)
        ref = _LLT.plh2xyz(lats, lons, hs, self.WGS84_A, self.WGS84_F)
        for i in range(100):
            x, y, z = plh2xyz_scalar(float(lats[i]), float(lons[i]),
                                     float(hs[i]),
                                     self.WGS84_A, self.WGS84_F)
            # Bit-parity expected: same constants, same operation order,
            # just scalar vs broadcast.
            self.assertAlmostEqual(x, ref[i, 0], delta=1e-7)
            self.assertAlmostEqual(y, ref[i, 1], delta=1e-7)
            self.assertAlmostEqual(z, ref[i, 2], delta=1e-7)


# ---------------------------------------------------------------------------
# Tier 2 — Hermite interpolation primitives
# ---------------------------------------------------------------------------
class TestHermiteC1d(unittest.TestCase):
    """hermite_c_1d — general-grid Hermite, line-by-line mirror of C
    hermite_c.c. Same kernel as the audited bin_py/_jit_kernels_sat.py
    `_hermite_c_1d_jit`.
    """

    def test_exact_on_polynomial(self):
        """Hermite with derivatives at 6 nodes exactly reproduces any
        polynomial of degree <= 5."""
        # 5th-degree polynomial. Use a sub-interval well inside the knots
        # so the i0-clip logic isn't hit.
        x = np.linspace(0.0, 10.0, 12)
        # P(t) = 1 + 2t - t^2 + 0.5*t^3 - 0.1*t^4 + 0.01*t^5
        coefs = np.array([1.0, 2.0, -1.0, 0.5, -0.1, 0.01])
        y = sum(c * x**i for i, c in enumerate(coefs))
        # derivatives
        z = sum(i * c * x**(i - 1) for i, c in enumerate(coefs) if i >= 1)

        xp = np.linspace(1.0, 9.0, 30)
        yp_ref = sum(c * xp**i for i, c in enumerate(coefs))
        out = np.empty_like(xp)
        hermite_c_1d(x, y, z, xp, 6, out)
        # Numerical conditioning of 5th-deg Hermite on 12 nodes →
        # ~1e-9 typical residual on this polynomial.
        np.testing.assert_allclose(out, yp_ref, rtol=0, atol=5e-9)

    def test_endpoints_recover_node_values(self):
        x = np.linspace(0.0, 10.0, 12)
        y = np.sin(x)
        z = np.cos(x)
        out = np.empty(2)
        # query at knots well inside the clip range
        xp = np.array([x[4], x[7]])
        hermite_c_1d(x, y, z, xp, 6, out)
        np.testing.assert_allclose(out, [y[4], y[7]], atol=1e-12)

    def test_parity_vs_SAT_llt2rat_py(self):
        """hermite_c_1d (njit) == hermite_c_1d (numpy ref in SAT_llt2rat_py)
        on a synthetic orbit query batch."""
        # Synthetic orbit at uniform 5-s spacing — typical gmtsar layout
        rng = np.random.default_rng(7)
        t = np.linspace(0.0, 100.0, 21)  # 21 nodes
        y = np.cos(0.05 * t) + 1e3 * np.sin(0.01 * t)
        z = -0.05 * np.sin(0.05 * t) + 10.0 * np.cos(0.01 * t)
        # 50 queries inside the valid range
        xp = rng.uniform(t[3], t[-3], 50)
        ref = _LLT.hermite_c_1d(t, y, z, xp, 6)
        out = np.empty(50)
        hermite_c_1d(t, y, z, xp, 6, out)
        np.testing.assert_allclose(out, ref, rtol=0, atol=1e-9)


class TestHermiteC1dUniform(unittest.TestCase):
    """hermite_c_1d_uniform — Horner fast-path. Same kernel as
    bin_py/_jit_kernels_sat.py `_hermite_c_1d_uniform_jit`.
    """

    def test_parity_vs_SAT_llt2rat_py_uniform(self):
        """hermite_c_1d_uniform (njit) == hermite_c_1d_uniform (numpy ref).

        Both use the SAME Horner basis → expect bit-parity to roundoff.
        """
        rng = np.random.default_rng(13)
        dsec = 5.0
        x0 = 0.0
        n = 21
        t = x0 + dsec * np.arange(n)
        y = np.cos(0.05 * t) + 1e3 * np.sin(0.01 * t)
        z = -0.05 * np.sin(0.05 * t) + 10.0 * np.cos(0.01 * t)
        xp = rng.uniform(t[3], t[-3], 50)

        # numpy reference (audited path in SAT_llt2rat_py)
        ref = _LLT.hermite_c_1d_uniform(x0, dsec, y, z, xp, 6)

        # build HJ / S_VALS via the same private helper the ref uses
        HJ, S_VALS = _LLT._hermite_basis(6)

        out = np.empty(50)
        hermite_c_1d_uniform(x0, dsec, y, z, xp, 6, HJ, S_VALS, out)
        # numpy vectorised reduction vs scalar accumulation differ by a few
        # ULP at the ~1e-11 m level on this synthetic orbit (Mira-#2 AUDIT
        # note: Horner reduction is order-stable, but the broadcast path
        # adds across axis=0 in a different micro-op order than the scalar
        # `yp += ...` loop). Both still match C `hermite_c_1d_uniform`
        # within the audited 1e-6 m envelope.
        np.testing.assert_allclose(out, ref, rtol=0, atol=1e-9)

    def test_uniform_close_to_general_on_uniform_grid(self):
        """For a uniform grid, Horner basis and direct Lagrange should
        agree to ~1e-6 m (the AUDIT-known residual). Tests that we're
        within that envelope, not tighter."""
        rng = np.random.default_rng(17)
        dsec = 5.0
        x0 = 0.0
        n = 21
        t = x0 + dsec * np.arange(n)
        y = np.sin(0.07 * t)
        z = 0.07 * np.cos(0.07 * t)
        xp = rng.uniform(t[3], t[-3], 20)

        HJ, S_VALS = _LLT._hermite_basis(6)
        out_u = np.empty(20)
        out_g = np.empty(20)
        hermite_c_1d_uniform(x0, dsec, y, z, xp, 6, HJ, S_VALS, out_u)
        hermite_c_1d(t, y, z, xp, 6, out_g)
        # Audited envelope: 1e-6 m vs direct Lagrange (AUDIT note).
        np.testing.assert_allclose(out_u, out_g, rtol=0, atol=1e-6)


# ---------------------------------------------------------------------------
# Tier 3 — Search + fit primitives
# ---------------------------------------------------------------------------
class TestGoldopSearch(unittest.TestCase):
    """goldop_search — batched golden-section. Same kernel as
    bin_py/_jit_kernels_sat.py `_goldop_jit`.
    """

    def test_single_target_lands_near_minimum(self):
        # Construct a synthetic orbit: straight line through (0, 0, 0) at t=50
        n = 100
        op_t = np.arange(n, dtype=np.float64)
        px = (op_t - 50.0) * 100.0      # passes through 0 at t=50
        py = np.zeros(n)
        pz = np.full(n, 1000.0)         # ~1 km away at closest
        # Target at the origin → closest approach is at index 50
        tx = np.array([0.0])
        ty = np.array([0.0])
        tz = np.array([0.0])
        R_out = np.empty(1)
        T_out = np.empty(1)
        goldop_search(op_t, px, py, pz, tx, ty, tz, R_out, T_out)
        # C goldop with TOL=2 → ±2 grid samples → tm within ±2.0
        self.assertAlmostEqual(T_out[0], 50.0, delta=2.0)
        # min distance is sqrt(0 + 0 + 1000^2) = 1000.  TOL=2 grid samples
        # → px goes off-axis by up to 200 m at neighbours → range up to
        # sqrt(1000^2 + 200^2) ≈ 1019.8.  Allow that envelope.
        self.assertLess(R_out[0], 1020.0)
        self.assertGreater(R_out[0], 999.0)

    def test_parity_vs_SAT_llt2rat_py_goldop_batch(self):
        """goldop_search (njit, this module) == goldop_batch
        (SAT_llt2rat_py — Mira #2 audited C-parity) on a batch of targets."""
        rng = np.random.default_rng(123)
        n = 200
        op_t = np.arange(n, dtype=np.float64)
        # Curved orbit: parabolic in xz, linear in y
        px = (op_t - 100.0) * 50.0
        py = (op_t - 100.0) * 5.0
        pz = 1000.0 + 0.1 * (op_t - 100.0) ** 2
        # 30 random targets within the orbit envelope
        N = 30
        tx = rng.uniform(px.min(), px.max(), N)
        ty = rng.uniform(py.min(), py.max(), N)
        tz = rng.uniform(0.0, 2000.0, N)

        R_out = np.empty(N)
        T_out = np.empty(N)
        goldop_search(op_t, px, py, pz, tx, ty, tz, R_out, T_out)

        # Reference path: SAT_llt2rat_py goldop_batch
        orb_pos = np.column_stack([op_t, px, py, pz])
        targets = np.column_stack([tx, ty, tz])
        R_ref, T_ref = _LLT.goldop_batch(orb_pos, targets)

        # Both kernels mirror the C SHFT3 cascade. Expect bit-parity.
        np.testing.assert_array_equal(T_out, T_ref)
        np.testing.assert_array_equal(R_out, R_ref)

    def test_index_clipping_at_boundaries(self):
        """Targets at the orbit edges should not crash; chosen index
        is clipped into [0, nrec-1]."""
        n = 50
        op_t = np.arange(n, dtype=np.float64)
        px = op_t * 1.0
        py = np.zeros(n)
        pz = np.zeros(n)
        # Targets WAY past the orbit end (would want index > 49)
        tx = np.array([1000.0, -1000.0])
        ty = np.array([0.0, 0.0])
        tz = np.array([0.0, 0.0])
        R_out = np.empty(2)
        T_out = np.empty(2)
        goldop_search(op_t, px, py, pz, tx, ty, tz, R_out, T_out)
        # T_out must be valid orbit times in [0, n-1]
        self.assertTrue((T_out >= 0).all())
        self.assertTrue((T_out <= n - 1).all())


class TestPolyfitNormalEqs(unittest.TestCase):
    """polyfit_normal_eqs — C-faithful normal-equations polyfit.

    Parity target: SAT_llt2rat_py.polyfit_c (numpy reference for the C
    polyfit.c + gauss_jordan.c chain, Mira #2 audited).
    """

    def test_recovers_exact_polynomial(self):
        """On a polynomial fit to its own samples, recovers the coefs
        to ~1e-12."""
        T = np.linspace(-1.0, 1.0, 50)
        true_coefs = np.array([3.0, -0.5, 2.0])  # 3 - 0.5*t + 2*t^2
        Y = true_coefs[0] + true_coefs[1] * T + true_coefs[2] * T * T
        out = np.zeros(3)
        polyfit_normal_eqs(T, Y, 3, out)
        np.testing.assert_allclose(out, true_coefs, rtol=0, atol=1e-9)

    def test_parity_vs_SAT_llt2rat_py_polyfit_c(self):
        """polyfit_normal_eqs (njit) == polyfit_c (numpy ref) on the same
        inputs. Both implement C polyfit.c + gauss_jordan.c bit-exact."""
        rng = np.random.default_rng(99)
        for trial in range(5):
            T = np.sort(rng.uniform(-5.0, 5.0, 30))
            Y = (1.0 + 2.0 * T - 0.3 * T * T
                 + 0.05 * T * T * T + 1e-2 * rng.standard_normal(30))
            for N in (2, 3, 4):
                ref = _LLT.polyfit_c(T, Y, N)
                out = np.zeros(N)
                polyfit_normal_eqs(T, Y, N, out)
                np.testing.assert_allclose(
                    out, ref, rtol=0, atol=1e-10,
                    err_msg=f"trial={trial} N={N}")

    def test_vertex_extraction_for_quadratic(self):
        """For the SAT_baseline poly_interp use case (N=3 quadratic),
        we extract the vertex tm + b from a perfect quadratic."""
        # Vertex at t = 0.123, b² minimum = 25.0
        t_vert = 0.123
        bmin_sq = 25.0
        T = np.linspace(-0.01, 0.01, 100)
        # bs[k] = bmin_sq + 1e6 * (T[k] - t_vert)^2  (quadratic in T)
        Y = bmin_sq + 1.0e6 * (T - t_vert) ** 2
        out = np.zeros(3)
        polyfit_normal_eqs(T, Y, 3, out)
        # vertex at -d1 / (2*d2)
        t_recovered = -out[1] / (2.0 * out[2])
        b_recovered_sq = out[0] - out[1] * out[1] / 4.0 / out[2]
        self.assertAlmostEqual(t_recovered, t_vert, places=10)
        self.assertAlmostEqual(b_recovered_sq, bmin_sq, places=4)


if __name__ == "__main__":
    unittest.main()
