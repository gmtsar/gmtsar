#!/usr/bin/env python3
"""test_make_slc_nsr_py — checkpoint + C-parity tests for make_slc_nsr_py.

Two layers, per Mira's discipline:
 1. Checkpoint unit tests for the C2/C3 numeric helpers (cat_nums,
    str_date2JD/date2MJD, f32_to_i16_batch, get_range) — scalar
    correctness against hand-computed / boundary values.
 2. TestXVsCBinary — runs the REAL C `make_slc_nsr` binary and the Py
    port on the SAME real NISAR .h5 input (both A and B frequency
    paths), asserts byte-identical .SLC, .LED, and .PRM (modulo the
    output-stem substring baked into led_file/SLC_file lines). Skips
    LOUDLY (not silently) if the C binary, the real fixture, or h5py
    are unavailable.

Also covers the one Py-only feature this port adds beyond a literal
C translation: reading only the [yl:yh, xl:xh] HDF5 sub-region instead
of the C's malloc-the-whole-dataset-then-crop. That is proven
equivalent to a full-read-then-crop on a small synthetic HDF5 file
(TestSlicedReadEquivalence), independent of the real 14GB fixture.
"""
from __future__ import annotations

import importlib.machinery as _ilm
import importlib.util as _ilu
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
_MOD_PATH = _HERE.parent.parent / "utils" / "make_slc_nsr_py.py"

try:
    import h5py  # noqa: F401
    _HAVE_H5PY = True
except ImportError:
    _HAVE_H5PY = False


def _load_module():
    spec = _ilu.spec_from_loader(
        "make_slc_nsr_py_mod",
        _ilm.SourceFileLoader("make_slc_nsr_py_mod", str(_MOD_PATH)),
    )
    mod = _ilu.module_from_spec(spec)
    sys.modules["make_slc_nsr_py_mod"] = mod
    spec.loader.exec_module(mod)
    return mod


_MOD = _load_module() if _HAVE_H5PY else None


# ---------------------------------------------------------------------------
# B1: get_range() checkpoint
# ---------------------------------------------------------------------------
@unittest.skipUnless(_HAVE_H5PY, "h5py not installed")
class TestGetRange(unittest.TestCase):
    def test_normal(self):
        self.assertEqual(_MOD.get_range("18000/23000/47000/53000"),
                          (18000, 23000, 47000, 53000))

    def test_negative_not_present_real_data(self):
        # region_cut values in practice are always non-negative; atoi-like
        # parser still must handle a leading sign correctly.
        self.assertEqual(_MOD.get_range("-1/2/3/4"), (-1, 2, 3, 4))

    def test_wrong_token_count_raises(self):
        with self.assertRaises(ValueError):
            _MOD.get_range("1/2/3")


# ---------------------------------------------------------------------------
# B2/C2: cat_nums / str_date2JD / date2MJD checkpoint
# ---------------------------------------------------------------------------
@unittest.skipUnless(_HAVE_H5PY, "h5py not installed")
class TestDateHelpers(unittest.TestCase):
    def test_cat_nums_iso_no_fraction(self):
        # Real NISAR units string format (verified against the actual
        # NISAR_Ethiopia fixture): no fractional seconds.
        self.assertEqual(
            _MOD.cat_nums("seconds since 2025-11-22T00:00:00"),
            "20251122000000",
        )

    def test_cat_nums_single_digit_padding(self):
        # cat_nums's correction path only fires on 'T'/':'/'.' separators
        # (NOT '-'), and only pads the digit immediately preceding that
        # separator (xml.c:429-455) -- hand-traced against the C algorithm:
        # "2025-11-22T3:4:5" -> hour "3" IS padded (colon after single
        # digit); this is the C's actual (quirky, bug-compatible) behavior,
        # not an idealized "always 2-digit" formatter.
        self.assertEqual(_MOD.cat_nums("2025-11-22T3:4:5"), "2025112203045")
        # Month/day/hour/min/sec already 2-digit (the real NISAR format)
        # -> untouched, no correction fires.
        self.assertEqual(_MOD.cat_nums("2025-11-22T03:04:05"), "20251122030405")

    def test_str_date2JD_matches_known_c_output(self):
        # This exact digit string (from the real fixture) produced
        # SC_clock_start = 2025325.1158439936 via the C binary (see
        # TestXVsCBinary) => t0 for day-of-year 325 in 2025 must be
        # exactly 325.0 (whole-day units-string reference, no fraction).
        digits = _MOD.cat_nums("seconds since 2025-11-22T00:00:00")
        t0 = _MOD.str_date2JD(digits)
        self.assertEqual(t0, 325.0)

    def test_str_date2JD_empty_fraction_is_zero(self):
        # C2 audited behavior: a units string with no fractional-seconds
        # field must not inject nonzero fractional seconds (verified
        # against the real C binary's stack-zero-fill behavior).
        digits14 = "20251122024618"  # 14 chars, no frac field present
        t0 = _MOD.str_date2JD(digits14)
        # 2025-11-22 02:46:18 -> day 325, frac = (2*3600+46*60+18)/86400
        expected_frac = (2 * 3600 + 46 * 60 + 18) / 86400.0
        self.assertAlmostEqual(t0 - 325.0, expected_frac, places=9)


# ---------------------------------------------------------------------------
# C3: f32_to_i16_batch checkpoint (boundary + NaN/Inf behavior)
# ---------------------------------------------------------------------------
@unittest.skipUnless(_HAVE_H5PY, "h5py not installed")
class TestF32ToI16(unittest.TestCase):
    def test_truncation_toward_zero(self):
        x = np.array([1.9, -1.9, 0.4, -0.4], dtype=np.float32)
        out, sh, sl, zc = _MOD.f32_to_i16_batch(x)
        np.testing.assert_array_equal(out, [1, -1, 0, 0])
        self.assertEqual(zc, 2)  # 0.4 and -0.4 truncate to 0 but aren't 0

    def test_saturation_hi_lo(self):
        x = np.array([40000.0, -40000.0, 32767.0, -32768.0], dtype=np.float32)
        out, sh, sl, zc = _MOD.f32_to_i16_batch(x)
        np.testing.assert_array_equal(out, [32767, -32768, 32767, -32768])
        self.assertEqual(sh, 1)
        self.assertEqual(sl, 1)

    def test_nan_inf_map_to_zero_not_saturated(self):
        x = np.array([np.nan, np.inf, -np.inf], dtype=np.float32)
        out, sh, sl, zc = _MOD.f32_to_i16_batch(x)
        np.testing.assert_array_equal(out, [0, 0, 0])
        # isfinite guard fires BEFORE the saturation compare (make_slc_nsr.c
        # :498-500 precede :501-508) -- infinities must NOT count as
        # saturated.
        self.assertEqual(sh, 0)
        self.assertEqual(sl, 0)

    def test_rejects_non_float32(self):
        x = np.array([1.0, 2.0], dtype=np.float64)
        with self.assertRaises(TypeError):
            _MOD.f32_to_i16_batch(x)


# ---------------------------------------------------------------------------
# Py-only feature: sliced HDF5 read vs full-read-then-crop equivalence
# ---------------------------------------------------------------------------
@unittest.skipUnless(_HAVE_H5PY, "h5py not installed")
class TestSlicedReadEquivalence(unittest.TestCase):
    """write_slc_hdf5 reads ds[yl:yh, xl:xh] directly; the C reads the
    WHOLE dataset then crops. Prove these are numerically identical on a
    small synthetic file (the real 14GB fixture makes this prohibitively
    slow to double-check inline)."""

    def test_sliced_equals_full_then_crop(self):
        import h5py
        import tempfile

        rng = np.random.default_rng(0)
        height, width = 40, 30
        data = (rng.standard_normal((height, width)) +
                1j * rng.standard_normal((height, width))).astype(np.complex64)

        with tempfile.TemporaryDirectory() as td:
            h5path = os.path.join(td, "synthetic.h5")
            with h5py.File(h5path, "w") as f:
                g = f.create_group("/science/LSAR/RSLC/swaths/frequencyA")
                g.create_dataset("HH", data=data)
                g.create_dataset("slantRangeSpacing", data=6.0)
                gb = f.create_group("/science/LSAR/RSLC/swaths/frequencyB")
                gb.create_dataset("slantRangeSpacing", data=24.0)

            with h5py.File(h5path, "r") as f:
                ds = f["/science/LSAR/RSLC/swaths/frequencyA/HH"]
                xl, xh, yl, yh = 3, 27, 5, 37  # both already multiples of 4 wide
                sliced = ds[yl:yh, xl:xh]
                full = ds[()]
                cropped = full[yl:yh, xl:xh]

            np.testing.assert_array_equal(sliced.real, cropped.real)
            np.testing.assert_array_equal(sliced.imag, cropped.imag)


# ---------------------------------------------------------------------------
# TestXVsCBinary — real-data byte parity gate
# ---------------------------------------------------------------------------
def _find_real_h5():
    work_root = Path(
        os.environ.get("GMTSAR_TEST_WORK")
        or str(_HERE.parents[1] / "work")
    )
    root = work_root / "csh_test" / "NISAR_Ethiopia" / "raw"
    if not root.exists():
        return None
    candidates = sorted(root.glob("NISAR_L1_PR_RSLC_*.h5"))
    return candidates[0] if candidates else None


class TestXVsCBinary(unittest.TestCase):
    """Runs the real C make_slc_nsr binary AND make_slc_nsr_py on the SAME
    real NISAR .h5 file, asserts byte-identical .SLC/.LED and PRM content
    (modulo the output-stem substring). Skips loudly (never silently) if
    the C binary, h5py, or the real fixture are unavailable."""

    REGION_CUT = "18000/23000/47000/53000"
    SLC_FACTOR = "30000.0"

    @classmethod
    def setUpClass(cls):
        if not _HAVE_H5PY:
            raise unittest.SkipTest("h5py not installed — required by make_slc_nsr_py")

        repo_root = _HERE.parents[3]
        c_bin = shutil.which("make_slc_nsr") or str(
            repo_root / "preproc" / "NSR_preproc" / "src_slc" / "make_slc_nsr"
        )
        if not Path(c_bin).exists():
            raise unittest.SkipTest(f"C make_slc_nsr binary not present at {c_bin}")
        cls.C_BIN = c_bin

        h5 = _find_real_h5()
        if h5 is None:
            raise unittest.SkipTest(
                "real NISAR .h5 fixture not present under work/csh_test/NISAR_Ethiopia/raw/"
            )
        cls.H5_FILE = str(h5)

    def _run_case(self, mode: str, tmp_path: Path) -> None:
        c_dir = tmp_path / "c"
        py_dir = tmp_path / "py"
        c_dir.mkdir()
        py_dir.mkdir()
        stem = f"NSR_{mode}"

        c_run = subprocess.run(
            [self.C_BIN, self.H5_FILE, stem, mode, self.SLC_FACTOR, self.REGION_CUT],
            cwd=str(c_dir), capture_output=True, check=False,
        )
        self.assertEqual(c_run.returncode, 0,
                          f"C make_slc_nsr failed ({mode}): {c_run.stderr!r}")

        py_run = subprocess.run(
            [sys.executable, str(_MOD_PATH), self.H5_FILE, stem, mode,
             self.SLC_FACTOR, self.REGION_CUT],
            cwd=str(py_dir), capture_output=True, check=False,
        )
        self.assertEqual(py_run.returncode, 0,
                          f"Py make_slc_nsr_py failed ({mode}): {py_run.stderr!r}")

        c_slc = (c_dir / f"{stem}.SLC").read_bytes()
        py_slc = (py_dir / f"{stem}.SLC").read_bytes()
        self.assertEqual(c_slc, py_slc, f"{mode}: .SLC bytes diverge")

        c_led = (c_dir / f"{stem}.LED").read_text()
        py_led = (py_dir / f"{stem}.LED").read_text()
        self.assertEqual(c_led, py_led, f"{mode}: .LED content diverges")

        c_prm = (c_dir / f"{stem}.PRM").read_text()
        py_prm = (py_dir / f"{stem}.PRM").read_text()
        # led_file/SLC_file lines embed the stem, which is identical between
        # the two runs here (same `stem` used for both) -- no substitution
        # needed, PRM text must be byte-identical too.
        if c_prm != py_prm:
            c_lines = c_prm.splitlines()
            p_lines = py_prm.splitlines()
            for i, (a, b) in enumerate(zip(c_lines, p_lines)):
                if a != b:
                    self.fail(f"{mode}: PRM diverges at line {i+1}:\n  C:  {a!r}\n  Py: {b!r}")
            self.fail(f"{mode}: PRM line-count diverges: C={len(c_lines)} Py={len(p_lines)}")

    def test_frequency_a(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            self._run_case("AHH", Path(td))

    def test_frequency_b(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            self._run_case("BHH", Path(td))


if __name__ == "__main__":
    unittest.main()
