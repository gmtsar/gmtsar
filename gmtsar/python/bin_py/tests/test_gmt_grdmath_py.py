#!/usr/bin/env python3
"""test_gmt_grdmath_py — C-parity tests for utils/gmt_grdmath_py.py.

Per project Rule 10/10a: every test runs BOTH `gmt grdmath` (C binary) AND
gmt_grdmath_py on the SAME input file and asserts float32-roundoff-identical
output grids (max|diff| == 0 for exact-integer ops; < 1e-5 rel for SQRT/ATAN2/POW).

Skip rules
----------
- If `gmt` is not on PATH → skipUnless (loud skip, not silent pass).
- If netCDF4 / gmt_grd_io import fails → skipUnless.
- If gmt_grdmath_py import fails → skipUnless.

Each test class tests one operator or compound helper:

  TestFlipud      — FLIPUD
  TestMul         — MUL (grid×scalar, grid×grid)
  TestAdd         — ADD (grid+scalar, grid+grid)
  TestSub         — SUB
  TestDiv         — DIV (grid/scalar, div-by-zero NaN)
  TestAbs         — ABS
  TestSqrt        — SQRT (atol 1e-6 relative)
  TestSqr         — SQR
  TestPow         — POW (atol 1e-5 relative)
  TestHypot       — HYPOT (atol 1e-6 relative)
  TestAtan2       — ATAN2 (atol 1e-6 relative)
  TestGe          — GE (threshold mask)
  TestLe          — LE (threshold mask)
  TestNan         — NAN (replace-with-NaN)
  TestXor         — XOR (GMT semantics)
  TestMin         — MIN
  TestCompounds   — grdmath_sub_sqr, grdmath_div_sqrt, grdmath_mul_flipud,
                    grdmath_pow_flipud, grdmath_ge_nan, grdmath_atan2_mul_flipud
Run:
    python3 -m pytest gmtsar/python/bin_py/tests/test_gmt_grdmath_py.py -v
    # or standalone:
    python3 gmtsar/python/bin_py/tests/test_gmt_grdmath_py.py
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

# ── sys.path: put utils/ first so imports resolve correctly ──────────────────
_REPO_PY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_PY / "utils"))

# ── Import guards ─────────────────────────────────────────────────────────────

try:
    from gmt_grd_io import read_gmt_grd as _read  # type: ignore
    from gmt_grd_io import write_gmt_grd as _write  # type: ignore
    _HAVE_IO = True
    _IO_ERR = ""
except Exception as _e:
    _HAVE_IO = False
    _IO_ERR = repr(_e)

try:
    import gmt_grdmath_py as _py  # type: ignore
    _HAVE_PY = True
    _PY_ERR = ""
except Exception as _e:
    _HAVE_PY = False
    _PY_ERR = repr(_e)

_GMT = shutil.which("gmt") or "/home/staff/dliu/anaconda3/envs/gmtsar/bin/gmt"
_HAS_GMT = shutil.which("gmt") is not None or os.path.isfile(_GMT)

if not _HAS_GMT:
    # Try the known absolute path as a last resort
    _HAS_GMT = os.path.isfile(_GMT)


# ── Shared test infrastructure ────────────────────────────────────────────────

def _gmt(*args: str, cwd: str | None = None) -> subprocess.CompletedProcess:
    """Run `gmt <args>` via the located binary. Raises on non-zero."""
    bin_ = _GMT if os.path.isfile(_GMT) else "gmt"
    return subprocess.run([bin_, *args], check=True,
                          capture_output=True, cwd=cwd)


def _make_test_grid(tmpdir: str, name: str,
                    ny: int = 20, nx: int = 15,
                    seed: int = 42,
                    with_nan: bool = False) -> str:
    """Write a small float32 .grd to tmpdir and return its path.

    Grid is Cartesian, gridline-registered, x in [0,14], y in [0,19].
    Values are random floats in [0.1, 5.0] to avoid exact zeros (safer
    for DIV / SQRT tests).  When with_nan=True, ~20% of cells are NaN.
    """
    rng = np.random.default_rng(seed)
    data = rng.uniform(0.1, 5.0, (ny, nx)).astype(np.float32)
    if with_nan:
        mask = rng.random((ny, nx)) < 0.2
        data[mask] = np.nan
    x = np.arange(nx, dtype=np.float64)
    y = np.arange(ny, dtype=np.float64)
    path = os.path.join(tmpdir, name)
    _write(path, data, x, y, node_offset=0, geographic=False,
           history=f"test_gmt_grdmath_py {name}")
    return path


def _gmt_grdmath(tmpdir: str, *tokens: str, out_name: str = "c_out.grd") -> str:
    """Run `gmt grdmath <tokens> = <out_name>` in tmpdir. Returns out path."""
    out = os.path.join(tmpdir, out_name)
    _gmt("grdmath", *tokens, "=", out, cwd=tmpdir)
    return out


def _compare(c_path: str, py_path: str, atol: float = 0.0,
             rtol: float = 0.0, label: str = "") -> None:
    """Assert max|diff| <= atol + rtol*|C| between two .grd files.

    NaN positions must match exactly (any NaN in C must be NaN in Py and
    vice versa — a NaN/non-NaN mismatch is always an error regardless of atol).
    """
    c_data, _, _, _ = _read(c_path)
    py_data, _, _, _ = _read(py_path)

    c_nan = np.isnan(c_data)
    py_nan = np.isnan(py_data)
    if not np.array_equal(c_nan, py_nan):
        mismatch = np.sum(c_nan != py_nan)
        raise AssertionError(
            f"{label}: NaN position mismatch in {mismatch} cells "
            f"(C has {c_nan.sum()} NaN, Py has {py_nan.sum()} NaN)"
        )

    valid = ~c_nan
    if valid.any():
        diff = np.abs(c_data[valid].astype(np.float64)
                      - py_data[valid].astype(np.float64))
        scale = np.abs(c_data[valid].astype(np.float64))
        threshold = atol + rtol * scale
        worst = float(np.max(diff - threshold))
        if worst > 0:
            idx = np.unravel_index(
                np.argmax(diff - threshold), c_data.shape)
            raise AssertionError(
                f"{label}: max|diff - threshold| = {worst:.3e} "
                f"at {idx} (C={float(c_data[idx]):.6g}, "
                f"Py={float(py_data[idx]):.6g})"
            )


# ── Decorator shorthands ──────────────────────────────────────────────────────

def _need_all(cls):
    """Apply common skipUnless guards to a test class."""
    return (unittest.skipUnless(_HAS_GMT,
                "gmt not on PATH — set up conda env or install GMT")
            (unittest.skipUnless(_HAVE_IO,
                f"gmt_grd_io / netCDF4 unavailable: {_IO_ERR}")
             (unittest.skipUnless(_HAVE_PY,
                f"gmt_grdmath_py unavailable: {_PY_ERR}")(cls))))


# ═════════════════════════════════════════════════════════════════════════════
# Operator parity tests
# ═════════════════════════════════════════════════════════════════════════════

@_need_all
class TestFlipud(unittest.TestCase):
    """FLIPUD: exact — row reversal, no arithmetic."""

    def test_basic(self):
        with tempfile.TemporaryDirectory() as d:
            a = _make_test_grid(d, "a.grd")
            c_out = _gmt_grdmath(d, a, "FLIPUD", out_name="c.grd")
            py_out = os.path.join(d, "py.grd")
            _py.grdmath1("FLIPUD", a, py_out, ctx="test_flipud")
            _compare(c_out, py_out, atol=0.0, label="FLIPUD")

    def test_with_nan(self):
        with tempfile.TemporaryDirectory() as d:
            a = _make_test_grid(d, "a.grd", with_nan=True)
            c_out = _gmt_grdmath(d, a, "FLIPUD", out_name="c.grd")
            py_out = os.path.join(d, "py.grd")
            _py.grdmath1("FLIPUD", a, py_out, ctx="test_flipud_nan")
            _compare(c_out, py_out, atol=0.0, label="FLIPUD+NaN")


@_need_all
class TestMul(unittest.TestCase):
    """MUL: exact (float32 mul)."""

    def test_grid_scalar(self):
        with tempfile.TemporaryDirectory() as d:
            a = _make_test_grid(d, "a.grd")
            c_out = _gmt_grdmath(d, a, "3.5", "MUL", out_name="c.grd")
            py_out = os.path.join(d, "py.grd")
            _py.grdmath2("MUL", a, 3.5, py_out, ctx="test_mul_scalar")
            _compare(c_out, py_out, atol=0.0, label="MUL grid*scalar")

    def test_grid_grid(self):
        with tempfile.TemporaryDirectory() as d:
            a = _make_test_grid(d, "a.grd", seed=1)
            b = _make_test_grid(d, "b.grd", seed=2)
            c_out = _gmt_grdmath(d, a, b, "MUL", out_name="c.grd")
            py_out = os.path.join(d, "py.grd")
            _py.grdmath2("MUL", a, b, py_out, ctx="test_mul_grid")
            _compare(c_out, py_out, atol=0.0, label="MUL grid*grid")

    def test_mul_nan_propagates(self):
        with tempfile.TemporaryDirectory() as d:
            a = _make_test_grid(d, "a.grd", with_nan=True)
            b = _make_test_grid(d, "b.grd", seed=5)
            c_out = _gmt_grdmath(d, a, b, "MUL", out_name="c.grd")
            py_out = os.path.join(d, "py.grd")
            _py.grdmath2("MUL", a, b, py_out, ctx="test_mul_nan")
            _compare(c_out, py_out, atol=0.0, label="MUL NaN propagation")

    def test_neg_scalar(self):
        with tempfile.TemporaryDirectory() as d:
            a = _make_test_grid(d, "a.grd")
            c_out = _gmt_grdmath(d, a, "-79.58", "MUL", out_name="c.grd")
            py_out = os.path.join(d, "py.grd")
            _py.grdmath2("MUL", a, -79.58, py_out, ctx="test_mul_neg")
            _compare(c_out, py_out, atol=0.0, label="MUL grid*-79.58")


@_need_all
class TestAdd(unittest.TestCase):
    """ADD."""

    def test_grid_scalar(self):
        with tempfile.TemporaryDirectory() as d:
            a = _make_test_grid(d, "a.grd")
            c_out = _gmt_grdmath(d, a, "2.5", "ADD", out_name="c.grd")
            py_out = os.path.join(d, "py.grd")
            _py.grdmath2("ADD", a, 2.5, py_out, ctx="test_add_scalar")
            _compare(c_out, py_out, atol=0.0, label="ADD grid+scalar")

    def test_grid_grid(self):
        with tempfile.TemporaryDirectory() as d:
            a = _make_test_grid(d, "a.grd", seed=10)
            b = _make_test_grid(d, "b.grd", seed=11)
            c_out = _gmt_grdmath(d, a, b, "ADD", out_name="c.grd")
            py_out = os.path.join(d, "py.grd")
            _py.grdmath2("ADD", a, b, py_out, ctx="test_add_grid")
            _compare(c_out, py_out, atol=0.0, label="ADD grid+grid")


@_need_all
class TestSub(unittest.TestCase):
    """SUB."""

    def test_grid_scalar(self):
        with tempfile.TemporaryDirectory() as d:
            a = _make_test_grid(d, "a.grd")
            c_out = _gmt_grdmath(d, a, "1.0", "SUB", out_name="c.grd")
            py_out = os.path.join(d, "py.grd")
            _py.grdmath2("SUB", a, 1.0, py_out, ctx="test_sub_scalar")
            _compare(c_out, py_out, atol=0.0, label="SUB grid-scalar")

    def test_grid_grid(self):
        with tempfile.TemporaryDirectory() as d:
            a = _make_test_grid(d, "a.grd", seed=20)
            b = _make_test_grid(d, "b.grd", seed=21)
            c_out = _gmt_grdmath(d, a, b, "SUB", out_name="c.grd")
            py_out = os.path.join(d, "py.grd")
            _py.grdmath2("SUB", a, b, py_out, ctx="test_sub_grid")
            _compare(c_out, py_out, atol=0.0, label="SUB grid-grid")


@_need_all
class TestDiv(unittest.TestCase):
    """DIV."""

    def test_grid_scalar(self):
        with tempfile.TemporaryDirectory() as d:
            a = _make_test_grid(d, "a.grd")
            c_out = _gmt_grdmath(d, a, "2.0", "DIV", out_name="c.grd")
            py_out = os.path.join(d, "py.grd")
            _py.grdmath2("DIV", a, 2.0, py_out, ctx="test_div_scalar")
            _compare(c_out, py_out, atol=0.0, label="DIV grid/scalar")

    def test_grid_grid(self):
        with tempfile.TemporaryDirectory() as d:
            a = _make_test_grid(d, "a.grd", seed=30)
            b = _make_test_grid(d, "b.grd", seed=31)
            c_out = _gmt_grdmath(d, a, b, "DIV", out_name="c.grd")
            py_out = os.path.join(d, "py.grd")
            _py.grdmath2("DIV", a, b, py_out, ctx="test_div_grid")
            # float32 division: allow atol=0 (same FP operation)
            _compare(c_out, py_out, atol=0.0, label="DIV grid/grid")


@_need_all
class TestAbs(unittest.TestCase):
    """ABS."""

    def test_with_neg(self):
        with tempfile.TemporaryDirectory() as d:
            rng = np.random.default_rng(99)
            # grid with positive and negative values
            data = rng.uniform(-3.0, 3.0, (20, 15)).astype(np.float32)
            x = np.arange(15, dtype=np.float64)
            y = np.arange(20, dtype=np.float64)
            a_path = os.path.join(d, "a.grd")
            _write(a_path, data, x, y, history="ABS test")
            c_out = _gmt_grdmath(d, a_path, "ABS", out_name="c.grd")
            py_out = os.path.join(d, "py.grd")
            _py.grdmath1("ABS", a_path, py_out, ctx="test_abs")
            _compare(c_out, py_out, atol=0.0, label="ABS")


@_need_all
class TestSqrt(unittest.TestCase):
    """SQRT: atol 1e-6 relative (transcendental)."""

    def test_basic(self):
        with tempfile.TemporaryDirectory() as d:
            a = _make_test_grid(d, "a.grd")
            c_out = _gmt_grdmath(d, a, "SQRT", out_name="c.grd")
            py_out = os.path.join(d, "py.grd")
            _py.grdmath1("SQRT", a, py_out, ctx="test_sqrt")
            _compare(c_out, py_out, atol=0.0, rtol=1e-6, label="SQRT")


@_need_all
class TestSqr(unittest.TestCase):
    """SQR (A^2): exact float32."""

    def test_basic(self):
        with tempfile.TemporaryDirectory() as d:
            a = _make_test_grid(d, "a.grd")
            c_out = _gmt_grdmath(d, a, "SQR", out_name="c.grd")
            py_out = os.path.join(d, "py.grd")
            _py.grdmath1("SQR", a, py_out, ctx="test_sqr")
            _compare(c_out, py_out, atol=0.0, label="SQR")


@_need_all
class TestPow(unittest.TestCase):
    """POW: atol rtol=1e-5 relative."""

    def test_pow_0_5(self):
        """A 0.5 POW = sqrt(A): matches grdmath amp.grd 0.5 POW."""
        with tempfile.TemporaryDirectory() as d:
            a = _make_test_grid(d, "a.grd")
            c_out = _gmt_grdmath(d, a, "0.5", "POW", out_name="c.grd")
            py_out = os.path.join(d, "py.grd")
            _py.grdmath2("POW", a, 0.5, py_out, ctx="test_pow_0.5")
            _compare(c_out, py_out, atol=0.0, rtol=1e-5, label="POW 0.5")

    def test_pow_2(self):
        with tempfile.TemporaryDirectory() as d:
            a = _make_test_grid(d, "a.grd")
            c_out = _gmt_grdmath(d, a, "2", "POW", out_name="c.grd")
            py_out = os.path.join(d, "py.grd")
            _py.grdmath2("POW", a, 2, py_out, ctx="test_pow_2")
            _compare(c_out, py_out, atol=0.0, rtol=1e-5, label="POW 2")


@_need_all
class TestHypot(unittest.TestCase):
    """HYPOT = sqrt(A^2+B^2): rtol 1e-6."""

    def test_grid_grid(self):
        with tempfile.TemporaryDirectory() as d:
            a = _make_test_grid(d, "a.grd", seed=40)
            b = _make_test_grid(d, "b.grd", seed=41)
            c_out = _gmt_grdmath(d, a, b, "HYPOT", out_name="c.grd")
            py_out = os.path.join(d, "py.grd")
            _py.grdmath2("HYPOT", a, b, py_out, ctx="test_hypot")
            _compare(c_out, py_out, atol=0.0, rtol=1e-6, label="HYPOT")


@_need_all
class TestAtan2(unittest.TestCase):
    """ATAN2: rtol 1e-6. GMT stack: `Y X ATAN2` → atan2(Y,X)."""

    def test_atan2(self):
        with tempfile.TemporaryDirectory() as d:
            # Use grids with both signs to exercise all quadrants
            rng = np.random.default_rng(50)
            data_y = rng.uniform(-3.0, 3.0, (20, 15)).astype(np.float32)
            data_x = rng.uniform(-3.0, 3.0, (20, 15)).astype(np.float32)
            x_coord = np.arange(15, dtype=np.float64)
            y_coord = np.arange(20, dtype=np.float64)
            y_path = os.path.join(d, "Y.grd")
            x_path = os.path.join(d, "X.grd")
            _write(y_path, data_y, x_coord, y_coord, history="ATAN2 Y")
            _write(x_path, data_x, x_coord, y_coord, history="ATAN2 X")
            # GMT RPN: Y X ATAN2 → atan2(Y, X)
            c_out = _gmt_grdmath(d, y_path, x_path, "ATAN2", out_name="c.grd")
            py_out = os.path.join(d, "py.grd")
            _py.grdmath2("ATAN2", y_path, x_path, py_out, ctx="test_atan2")
            _compare(c_out, py_out, atol=0.0, rtol=1e-6, label="ATAN2")


@_need_all
class TestGe(unittest.TestCase):
    """GE: 1.0 if A>=thresh else 0.0 (NaN→NaN)."""

    def test_ge_scalar(self):
        with tempfile.TemporaryDirectory() as d:
            a = _make_test_grid(d, "a.grd", with_nan=True)
            thresh = "2.0"
            c_out = _gmt_grdmath(d, a, thresh, "GE", out_name="c.grd")
            py_out = os.path.join(d, "py.grd")
            _py.grdmath2("GE", a, float(thresh), py_out, ctx="test_ge")
            _compare(c_out, py_out, atol=0.0, label="GE")


@_need_all
class TestLe(unittest.TestCase):
    """LE: 1.0 if A<=thresh else 0.0 (NaN→NaN)."""

    def test_le_scalar(self):
        with tempfile.TemporaryDirectory() as d:
            a = _make_test_grid(d, "a.grd", with_nan=True)
            thresh = "2.5"
            c_out = _gmt_grdmath(d, a, thresh, "LE", out_name="c.grd")
            py_out = os.path.join(d, "py.grd")
            _py.grdmath2("LE", a, float(thresh), py_out, ctx="test_le")
            _compare(c_out, py_out, atol=0.0, label="LE")


@_need_all
class TestNan(unittest.TestCase):
    """NAN: NaN where A==B else A."""

    def test_nan_zero(self):
        """A 0 NAN = replace zeros with NaN (common mask pattern)."""
        with tempfile.TemporaryDirectory() as d:
            # Build a grid with some exact zeros
            rng = np.random.default_rng(60)
            data = rng.uniform(0.0, 5.0, (20, 15)).astype(np.float32)
            data[::3, ::4] = 0.0   # inject exact zeros
            x = np.arange(15, dtype=np.float64)
            y = np.arange(20, dtype=np.float64)
            a_path = os.path.join(d, "a.grd")
            _write(a_path, data, x, y, history="NAN test")
            c_out = _gmt_grdmath(d, a_path, "0", "NAN", out_name="c.grd")
            py_out = os.path.join(d, "py.grd")
            _py.grdmath2("NAN", a_path, 0.0, py_out, ctx="test_nan_zero")
            _compare(c_out, py_out, atol=0.0, label="NAN(A,0)")


@_need_all
class TestXor(unittest.TestCase):
    """XOR: 0 if both NaN; NaN if B==NaN; else A."""

    def test_xor_semantics(self):
        with tempfile.TemporaryDirectory() as d:
            rng = np.random.default_rng(70)
            data_a = rng.uniform(0.1, 5.0, (20, 15)).astype(np.float32)
            data_b = rng.uniform(0.1, 5.0, (20, 15)).astype(np.float32)
            # Inject NaN in different patterns
            data_a[0, :5] = np.nan
            data_b[1, :5] = np.nan
            data_a[2, :5] = np.nan
            data_b[2, :5] = np.nan
            x = np.arange(15, dtype=np.float64)
            y = np.arange(20, dtype=np.float64)
            a_path = os.path.join(d, "a.grd")
            b_path = os.path.join(d, "b.grd")
            _write(a_path, data_a, x, y, history="XOR A")
            _write(b_path, data_b, x, y, history="XOR B")
            c_out = _gmt_grdmath(d, a_path, b_path, "XOR", out_name="c.grd")
            py_out = os.path.join(d, "py.grd")
            _py.grdmath2("XOR", a_path, b_path, py_out, ctx="test_xor")
            _compare(c_out, py_out, atol=0.0, label="XOR")

    def test_xor_with_scalar_b(self):
        """gmt grdmath corr_patch.grd 0. XOR: B=scalar 0 → result = A everywhere."""
        with tempfile.TemporaryDirectory() as d:
            a = _make_test_grid(d, "a.grd", with_nan=True)
            c_out = _gmt_grdmath(d, a, "0.", "XOR", out_name="c.grd")
            py_out = os.path.join(d, "py.grd")
            # For scalar b=0.0 (not NaN), result = A.
            # We must build a fake grid with constant 0.0 for grdmath2:
            data_a, x, y, info = _read(a)
            b_path = os.path.join(d, "b_zero.grd")
            _write(b_path, np.zeros_like(data_a), x, y, history="XOR B=0")
            _py.grdmath2("XOR", a, b_path, py_out, ctx="test_xor_zero")
            _compare(c_out, py_out, atol=0.0, label="XOR(A,0.)")


@_need_all
class TestMin(unittest.TestCase):
    """MIN."""

    def test_min_scalar(self):
        """gmt grdmath corr_patch.grd 0. XOR 1. MIN = corr_patch.grd pattern."""
        with tempfile.TemporaryDirectory() as d:
            a = _make_test_grid(d, "a.grd")
            c_out = _gmt_grdmath(d, a, "1.", "MIN", out_name="c.grd")
            py_out = os.path.join(d, "py.grd")
            _py.grdmath2("MIN", a, 1.0, py_out, ctx="test_min_scalar")
            _compare(c_out, py_out, atol=0.0, label="MIN(A,1.)")

    def test_min_grid_grid(self):
        with tempfile.TemporaryDirectory() as d:
            a = _make_test_grid(d, "a.grd", seed=80)
            b = _make_test_grid(d, "b.grd", seed=81)
            c_out = _gmt_grdmath(d, a, b, "MIN", out_name="c.grd")
            py_out = os.path.join(d, "py.grd")
            _py.grdmath2("MIN", a, b, py_out, ctx="test_min_grid")
            _compare(c_out, py_out, atol=0.0, label="MIN(A,B)")


# ═════════════════════════════════════════════════════════════════════════════
# Compound-helper parity tests
# ═════════════════════════════════════════════════════════════════════════════

@_need_all
class TestCompounds(unittest.TestCase):
    """Compound helpers — each tested against the equivalent gmt grdmath chain."""

    def test_sub_sqr(self):
        """grdmath_sub_sqr: A B SUB SQR = dst."""
        with tempfile.TemporaryDirectory() as d:
            a = _make_test_grid(d, "a.grd", seed=90)
            b = _make_test_grid(d, "b.grd", seed=91)
            # C: A B SUB SQR
            c_out = _gmt_grdmath(d, a, b, "SUB", "SQR", out_name="c.grd")
            py_out = os.path.join(d, "py.grd")
            _py.grdmath_sub_sqr(a, b, py_out, ctx="test_sub_sqr")
            _compare(c_out, py_out, atol=0.0, label="SUB SQR")

    def test_div_sqrt(self):
        """grdmath_div_sqrt: A n DIV SQRT = dst (stack/stdev pattern)."""
        with tempfile.TemporaryDirectory() as d:
            a = _make_test_grid(d, "a.grd", seed=92)
            n = 5
            c_out = _gmt_grdmath(d, a, str(n), "DIV", "SQRT", out_name="c.grd")
            py_out = os.path.join(d, "py.grd")
            _py.grdmath_div_sqrt(a, n, py_out, ctx="test_div_sqrt")
            _compare(c_out, py_out, atol=0.0, rtol=1e-6, label="DIV SQRT")

    def test_mul_flipud_scalar(self):
        """grdmath_mul_flipud: A scalar MUL FLIPUD = dst."""
        with tempfile.TemporaryDirectory() as d:
            a = _make_test_grid(d, "a.grd", seed=93)
            b = "-79.58"
            c_out = _gmt_grdmath(d, a, b, "MUL", "FLIPUD", out_name="c.grd")
            py_out = os.path.join(d, "py.grd")
            _py.grdmath_mul_flipud(a, float(b), py_out, ctx="test_mul_flipud_s")
            _compare(c_out, py_out, atol=0.0, label="MUL FLIPUD scalar")

    def test_mul_flipud_grid(self):
        """grdmath_mul_flipud: A B MUL FLIPUD = dst."""
        with tempfile.TemporaryDirectory() as d:
            a = _make_test_grid(d, "a.grd", seed=94)
            b = _make_test_grid(d, "b.grd", seed=95, with_nan=True)
            c_out = _gmt_grdmath(d, a, b, "MUL", "FLIPUD", out_name="c.grd")
            py_out = os.path.join(d, "py.grd")
            _py.grdmath_mul_flipud(a, b, py_out, ctx="test_mul_flipud_g")
            _compare(c_out, py_out, atol=0.0, label="MUL FLIPUD grid")

    def test_pow_flipud(self):
        """grdmath_pow_flipud: amp.grd 0.5 POW FLIPUD = display_amp.grd."""
        with tempfile.TemporaryDirectory() as d:
            a = _make_test_grid(d, "a.grd", seed=96)
            c_out = _gmt_grdmath(d, a, "0.5", "POW", "FLIPUD", out_name="c.grd")
            py_out = os.path.join(d, "py.grd")
            _py.grdmath_pow_flipud(a, 0.5, py_out, ctx="test_pow_flipud")
            _compare(c_out, py_out, atol=0.0, rtol=1e-5, label="POW FLIPUD")

    def test_ge_nan(self):
        """grdmath_ge_nan: a thresh GE 0 NAN = dst (mask pattern)."""
        with tempfile.TemporaryDirectory() as d:
            a = _make_test_grid(d, "a.grd", with_nan=True)
            thresh = 2.0
            c_out = _gmt_grdmath(d, a, str(thresh), "GE", "0", "NAN",
                                  out_name="c.grd")
            py_out = os.path.join(d, "py.grd")
            _py.grdmath_ge_nan(a, thresh, py_out, ctx="test_ge_nan")
            _compare(c_out, py_out, atol=0.0, label="GE 0 NAN")

    def test_atan2_mul_flipud(self):
        """grdmath imagfilt.grd realfilt.grd ATAN2 mask.grd MUL FLIPUD = phase.grd"""
        with tempfile.TemporaryDirectory() as d:
            rng = np.random.default_rng(97)
            data_y = rng.uniform(-3.0, 3.0, (20, 15)).astype(np.float32)
            data_x = rng.uniform(-3.0, 3.0, (20, 15)).astype(np.float32)
            data_m = (rng.random((20, 15)) > 0.3).astype(np.float32)
            x_coord = np.arange(15, dtype=np.float64)
            y_coord = np.arange(20, dtype=np.float64)
            imag_path = os.path.join(d, "imag.grd")
            real_path = os.path.join(d, "real.grd")
            mask_path = os.path.join(d, "mask.grd")
            _write(imag_path, data_y, x_coord, y_coord, history="ATAN2 Y")
            _write(real_path, data_x, x_coord, y_coord, history="ATAN2 X")
            _write(mask_path, data_m, x_coord, y_coord, history="ATAN2 mask")
            # C: imagfilt.grd realfilt.grd ATAN2 mask.grd MUL FLIPUD
            c_out = _gmt_grdmath(d, imag_path, real_path, "ATAN2",
                                   mask_path, "MUL", "FLIPUD", out_name="c.grd")
            py_out = os.path.join(d, "py.grd")
            _py.grdmath_atan2_mul_flipud(imag_path, real_path, mask_path,
                                          py_out, ctx="test_atan2_mul_flipud")
            _compare(c_out, py_out, atol=0.0, rtol=1e-6,
                     label="ATAN2 MUL FLIPUD")

    def test_assign(self):
        """grdmath_assign: gmt grdmath A = B (copy)."""
        with tempfile.TemporaryDirectory() as d:
            a = _make_test_grid(d, "a.grd", with_nan=True)
            c_out = _gmt_grdmath(d, a, out_name="c.grd")
            py_out = os.path.join(d, "py.grd")
            _py.grdmath_assign(a, py_out, ctx="test_assign")
            _compare(c_out, py_out, atol=0.0, label="ASSIGN (copy)")

    def test_sub_sqr_add(self):
        """grdmath_sub_sqr_add: A B SUB SQR acc ADD = dst."""
        with tempfile.TemporaryDirectory() as d:
            a = _make_test_grid(d, "a.grd", seed=101)
            b = _make_test_grid(d, "b.grd", seed=102)
            acc = _make_test_grid(d, "acc.grd", seed=103)
            # C:  a b SUB SQR acc ADD
            c_out = _gmt_grdmath(d, a, b, "SUB", "SQR", acc, "ADD",
                                  out_name="c.grd")
            py_out = os.path.join(d, "py.grd")
            _py.grdmath_sub_sqr_add(a, b, acc, py_out, ctx="test_sub_sqr_add")
            _compare(c_out, py_out, atol=0.0, label="SUB SQR ADD")


# ═════════════════════════════════════════════════════════════════════════════
# Error handling / bad-input tests
# ═════════════════════════════════════════════════════════════════════════════

@unittest.skipUnless(_HAVE_PY, f"gmt_grdmath_py unavailable: {_PY_ERR}")
class TestErrorHandling(unittest.TestCase):
    """Bad inputs raise, never silently return wrong output."""

    def test_unknown_op1_raises(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                _py.grdmath1("BADOP", "/dev/null", d + "/out.grd")

    def test_unknown_op2_raises(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                _py.grdmath2("BADOP", "/dev/null", "1.0", d + "/out.grd")

    def test_shape_mismatch_raises(self):
        if not _HAVE_IO:
            self.skipTest(f"gmt_grd_io unavailable: {_IO_ERR}")
        with tempfile.TemporaryDirectory() as d:
            a = _make_test_grid(d, "a.grd", ny=10, nx=10)
            b = _make_test_grid(d, "b.grd", ny=12, nx=8)
            with self.assertRaises(ValueError):
                _py.grdmath2("MUL", a, b, d + "/out.grd")

    def test_both_scalars_raises(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                _py.grdmath2("MUL", "2.0", "3.0", d + "/out.grd")


# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    unittest.main(verbosity=2)
