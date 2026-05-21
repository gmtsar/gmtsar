#!/usr/bin/env python3
"""test_resamp — unit + parity tests for bin_py/resamp_py.

Run with:
    cd gmtsar/python/bin_py/tests
    python3 -m pytest test_resamp.py -v
    # or, no pytest:
    python3 test_resamp.py

Test pyramid:

  Unit (fast — milliseconds each):
    - c_round_clip_int16_truncates_toward_zero
        Verifies the (short)clipi2(x+0.5) C convention.
    - cubic_kernel_a_neg_0_3_at_anchors
        Verifies Keys-cubic with a=-0.3 (not -0.5) reproduces the C
        kernel at characteristic points: f(0)=1, f(1)=0, f(2)=0.
    - sinc_kernel_at_anchors
        Verifies sinc(0)=1, sinc(integer)=0 with the C PI constant.
    - ram2ras_matches_scalar
        Vectorized ram2ras matches a hand-coded scalar reference.

  Parity (slow — seconds; skipped if C `resamp` not on PATH OR if
         test inputs missing):
    - TestResampVsCBinary.test_intrp_1_nearest
    - TestResampVsCBinary.test_intrp_2_bilinear
    - TestResampVsCBinary.test_intrp_3_bicubic
    - TestResampVsCBinary.test_intrp_4_bisinc
        For each: runs the C `resamp` binary and the Py `resamp_py`
        port on the same RS2 SLC pair (RS220110515 master,
        RS220110819 aligned, post-PRMresamp) and asserts byte-identical
        output SLC files. Skips gracefully (loudly) if either the C
        binary or the real-data inputs aren't present.

  Parity intrp=5 (uses NISAR_Ethiopia inputs; uses fitoffset_ra.csh to
  generate r.grd/a.grd; requires GMT on PATH):
    - TestResampVsCBinaryMode5.test_intrp_5_bisinc_grid
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

# Load resamp_py as a module despite the lack of .py extension.
_HERE = Path(__file__).resolve().parent
_RESAMP = _HERE.parent / "resamp_py"
_NS: dict = {}
exec(compile(_RESAMP.read_text(), str(_RESAMP), "exec"), _NS)
_c_round_clip_int16 = _NS["_c_round_clip_int16"]
_cubic_kernel = _NS["_cubic_kernel"]
_sinc_kernel = _NS["_sinc_kernel"]
ram2ras_vec = _NS["ram2ras_vec"]
resamp = _NS["resamp"]
I2MAX = _NS["I2MAX"]
PI = _NS["PI"]


# -------------------------------------------------------------------- unit ---
class TestCRoundClip(unittest.TestCase):
    """`(short)clipi2(x + 0.5)` — C-style cast truncates toward zero."""

    def test_positive_rounds_half_up(self):
        # x=0.4 -> 0.9 -> trunc -> 0; x=0.5 -> 1.0 -> 1; x=0.6 -> 1.1 -> 1
        x = np.array([0.4, 0.5, 0.6, 1.4, 1.5, 1.6, 32766.5, 32767.5])
        got = _c_round_clip_int16(x)
        # 32767.5 -> 32768.0 -> CLIPPED to 32767.0 -> cast -> 32767
        want = np.array([0, 1, 1, 1, 2, 2, 32767, 32767], dtype=np.int16)
        np.testing.assert_array_equal(got, want)

    def test_negative_truncates_toward_zero(self):
        # For NEGATIVE x, (int)(x+0.5) truncates toward zero, NOT floors.
        # x=-0.4 -> 0.1  -> trunc -> 0
        # x=-0.5 -> 0.0  -> trunc -> 0
        # x=-0.6 -> -0.1 -> trunc (toward 0) -> 0
        # x=-1.4 -> -0.9 -> trunc -> 0
        # x=-1.5 -> -1.0 -> -1
        # x=-1.6 -> -1.1 -> -1
        x = np.array([-0.4, -0.5, -0.6, -1.4, -1.5, -1.6, -32767.5])
        got = _c_round_clip_int16(x)
        # -32767.5 -> -32767.0 -> CLIPPED to -32767.0 -> -32767
        want = np.array([0, 0, 0, 0, -1, -1, -32767], dtype=np.int16)
        np.testing.assert_array_equal(got, want)

    def test_clips_at_i2max(self):
        # 50000 -> 50000.5 -> clipped to +I2MAX -> 32767
        # -50000 -> -49999.5 -> clipped to -I2MAX=-32767.0 -> trunc -> -32767
        # +I2MAX -> 32767.5 -> clipped to +I2MAX=32767.0 -> 32767
        # -I2MAX -> -32766.5 -> in range -> trunc-toward-zero -> -32766
        # (NOT -32767! C `(short)(-32766.5)` truncates toward zero.)
        x = np.array([50000.0, -50000.0, I2MAX, -I2MAX])
        got = _c_round_clip_int16(x)
        want = np.array([32767, -32767, 32767, -32766], dtype=np.int16)
        np.testing.assert_array_equal(got, want)


class TestCubicKernel(unittest.TestCase):
    """Keys-cubic with a=-0.3 — C `cubic_kernel` resamp.c:369."""

    def test_anchors(self):
        # By definition: f(0) = 1, f(1) = 0, f(2) = 0, f(>2) = 0
        a = -0.3
        # f(0) = 0 - 0 + 1 = 1
        # f(1) = (a+2) - (a+3) + 1 = 0
        # f(2) = a*8 - 5a*4 + 8a*2 - 4a = 8a - 20a + 16a - 4a = 0
        x = np.array([0.0, 1.0, 2.0, 2.0001, 3.0])
        got = _cubic_kernel(x, a=a)
        np.testing.assert_allclose(got, [1.0, 0.0, 0.0, 0.0, 0.0], atol=1e-12)

    def test_at_half(self):
        # f(0.5) for a=-0.3: arg=0.5, arg2=0.25, arg3=0.125
        # f = 1.7*0.125 - 2.7*0.25 + 1 = 0.2125 - 0.675 + 1 = 0.5375
        got = _cubic_kernel(np.array([0.5]), a=-0.3)
        np.testing.assert_allclose(got, [0.5375], atol=1e-12)

    def test_at_one_and_a_half(self):
        # f(1.5) for a=-0.3: arg=1.5, arg2=2.25, arg3=3.375
        # f = -0.3*3.375 - 5*(-0.3)*2.25 + 8*(-0.3)*1.5 - 4*(-0.3)
        #   = -1.0125 + 3.375 - 3.6 + 1.2
        #   = -0.0375
        got = _cubic_kernel(np.array([1.5]), a=-0.3)
        np.testing.assert_allclose(got, [-0.0375], atol=1e-12)


class TestSincKernel(unittest.TestCase):
    """C `sinc_kernel` resamp.c:676. Uses truncated PI."""

    def test_at_zero(self):
        got = _sinc_kernel(np.array([0.0]))
        np.testing.assert_allclose(got, [1.0])

    def test_at_integers(self):
        # sin(k*PI) for nonzero int k ~= 0 (modulo float roundoff)
        x = np.array([1.0, 2.0, 3.0, -1.0, -2.0])
        got = _sinc_kernel(x)
        np.testing.assert_allclose(got, np.zeros_like(x), atol=1e-15)

    def test_at_half(self):
        # sinc(0.5) = sin(pi/2)/(pi/2) = 2/pi
        got = _sinc_kernel(np.array([0.5]))
        np.testing.assert_allclose(got, [2.0 / PI], atol=1e-12)


class TestRam2RasVec(unittest.TestCase):
    """Vectorized ram2ras vs scalar reference (resamp.c:660-664)."""

    def test_matches_scalar(self):
        ps = {
            "rshift": "8",
            "sub_int_r": "0.96468",
            "stretch_r": "5.13018e-05",
            "a_stretch_r": "0",
            "ashift": "1",
            "sub_int_a": "0.68752",
            "stretch_a": "9.83968e-05",
            "a_stretch_a": "0",
        }
        rng = np.random.default_rng(0)
        jj = rng.uniform(0, 3416, size=100)
        ii = rng.uniform(0, 5744, size=100)
        ras0, ras1 = ram2ras_vec(jj, ii, ps)

        # scalar reference
        rshift = 8.0; sub_int_r = 0.96468; stretch_r = 5.13018e-05; a_stretch_r = 0.0
        ashift = 1.0; sub_int_a = 0.68752; stretch_a = 9.83968e-05; a_stretch_a = 0.0
        ref0 = jj + ((rshift + sub_int_r) + jj * stretch_r + ii * a_stretch_r)
        ref1 = ii + ((ashift + sub_int_a) + jj * stretch_a + ii * a_stretch_a)
        np.testing.assert_array_equal(ras0, ref0)
        np.testing.assert_array_equal(ras1, ref1)


# ------------------------------------------------------------------ parity ---
# Real-data parity gate. Runs the C resamp binary and the Py port on the
# same RS2 SLC pair and asserts byte-identical output. Skips with a
# LOUD message (not a silent pass) if prerequisites are missing.

# Search several places for the C binary (mira-volkov rule: skip loudly,
# don't silently pass).
def _find_c_resamp() -> str | None:
    for cand in (
        os.environ.get("GMTSAR_RESAMP_BIN"),
        shutil.which("resamp"),
        "/home/utig5/dliu/gmtsar/bin/resamp",
        "/home/staff/dliu/gmtsar/bin/resamp",
    ):
        if cand and os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


# Default real-data inputs (RS2 Hawaii, the standard csh test case).
_RS2_DIR = Path(
    "/home/utig5/dliu/gmtsar/gmtsar/python/work/csh_test/RS2_SLC_Hawaii"
)
_MASTER_PRM = _RS2_DIR / "SLC" / "RS220110515.PRM"
_ALIGNED_PRM = _RS2_DIR / "SLC" / "RS220110819.PRM"
# The SLC files are symlinks; resolve to the real ones for cross-tool input.
_MASTER_SLC = _RS2_DIR / "raw" / "RS220110515.SLC"
_ALIGNED_SLC = _RS2_DIR / "raw" / "RS220110819.SLC"


def _have_real_inputs() -> bool:
    return all(p.exists() for p in (_MASTER_PRM, _ALIGNED_PRM,
                                    _MASTER_SLC, _ALIGNED_SLC))


def _stage_inputs(tmpdir: Path) -> tuple[Path, Path]:
    """Copy PRMs + symlink SLCs into a clean temp dir.

    Returns (master_prm, aligned_prm) paths in tmpdir.
    """
    mprm = tmpdir / "master.PRM"
    aprm = tmpdir / "aligned.PRM"
    shutil.copy(_MASTER_PRM, mprm)
    shutil.copy(_ALIGNED_PRM, aprm)
    # Symlink the SLCs by the names the PRMs reference.
    # Master PRM SLC_file is typically RS220110515.SLC; aligned is RS220110819.SLC.
    (tmpdir / "RS220110515.SLC").symlink_to(_MASTER_SLC.resolve())
    (tmpdir / "RS220110819.SLC").symlink_to(_ALIGNED_SLC.resolve())
    return mprm, aprm


class TestResampVsCBinary(unittest.TestCase):
    """End-to-end parity vs C `resamp` on the RS2 Hawaii pair.

    Generates the C reference IN THE SAME INVOCATION as the Py run, so
    we can't pick up a stale reference file. Asserts byte-identical SLC.
    (PRM output is not byte-compared — see AUDIT_resamp_py.md.)
    """

    @classmethod
    def setUpClass(cls):
        cls._c_resamp = _find_c_resamp()
        if cls._c_resamp is None:
            raise unittest.SkipTest(
                "C `resamp` binary not on PATH; cannot run parity test. "
                "Set GMTSAR_RESAMP_BIN=/path/to/resamp to enable."
            )
        if not _have_real_inputs():
            raise unittest.SkipTest(
                f"Real RS2 SLC inputs not found under {_RS2_DIR}. "
                "Run the RS2_SLC_Hawaii test case through align (PRMresamp) "
                "before running this parity test."
            )

    def _run_parity(self, intrp: int):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            mprm, aprm = _stage_inputs(tmp)

            # Run C reference IN THIS INVOCATION (don't trust disk copies).
            c_prm = tmp / f"c_intrp{intrp}.PRM"
            c_slc = tmp / f"c_intrp{intrp}.SLC"
            r = subprocess.run(
                [self._c_resamp, str(mprm), str(aprm),
                 str(c_prm), str(c_slc), str(intrp)],
                capture_output=True, text=True, cwd=str(tmp), timeout=120,
            )
            self.assertEqual(r.returncode, 0,
                             msg=f"C resamp failed: {r.stderr}")

            # Run Py port on identical inputs.
            py_prm = tmp / f"py_intrp{intrp}.PRM"
            py_slc = tmp / f"py_intrp{intrp}.SLC"
            r = subprocess.run(
                [sys.executable, str(_RESAMP), str(mprm), str(aprm),
                 str(py_prm), str(py_slc), str(intrp)],
                capture_output=True, text=True, cwd=str(tmp), timeout=300,
            )
            self.assertEqual(r.returncode, 0,
                             msg=f"resamp_py failed: {r.stderr}")

            # Byte-compare the SLC files.
            c_bytes = c_slc.read_bytes()
            py_bytes = py_slc.read_bytes()
            self.assertEqual(len(c_bytes), len(py_bytes),
                             msg=f"SLC size mismatch: C={len(c_bytes)} "
                                 f"Py={len(py_bytes)}")
            if c_bytes != py_bytes:
                # diagnose
                c_arr = np.frombuffer(c_bytes, dtype=np.int16)
                p_arr = np.frombuffer(py_bytes, dtype=np.int16)
                diff = (c_arr.astype(np.int32) - p_arr.astype(np.int32))
                ndiff = int(np.count_nonzero(diff))
                maxd = int(np.abs(diff).max())
                self.fail(
                    f"intrp={intrp} SLC NOT bit-identical: "
                    f"{ndiff}/{c_arr.size} int16 samples differ "
                    f"(max |delta|={maxd}). "
                    f"C md5={hashlib.md5(c_bytes).hexdigest()[:12]} "
                    f"Py md5={hashlib.md5(py_bytes).hexdigest()[:12]}"
                )

    def test_intrp_1_nearest(self):
        self._run_parity(1)

    def test_intrp_2_bilinear(self):
        self._run_parity(2)

    def test_intrp_3_bicubic(self):
        self._run_parity(3)

    def test_intrp_4_bisinc(self):
        self._run_parity(4)


# Mode-5 fixture: NISAR_Ethiopia case + GMT-derived shift grids.
_NISAR_DIR = Path(
    "/home/utig5/dliu/gmtsar/gmtsar/python/work/csh_test/NISAR_Ethiopia"
)
_NISAR_MASTER_PRM = _NISAR_DIR / "SLC" / "NSR_20251122A.PRM"
_NISAR_ALIGNED_PRM = _NISAR_DIR / "SLC" / "NSR_20251204A.PRM"
_NISAR_MASTER_SLC = _NISAR_DIR / "raw" / "NSR_20251122A.SLC"
_NISAR_ALIGNED_SLC = _NISAR_DIR / "raw" / "NSR_20251204A.SLC"
_NISAR_FREQ_XCORR = _NISAR_DIR / "SLC" / "freq_xcorr.dat"
_NISAR_AMP = _NISAR_DIR / "SLC" / "amp-NSR_20251122A.grd"


def _have_nisar_inputs() -> bool:
    return all(p.exists() for p in (_NISAR_MASTER_PRM, _NISAR_ALIGNED_PRM,
                                    _NISAR_MASTER_SLC, _NISAR_ALIGNED_SLC,
                                    _NISAR_FREQ_XCORR, _NISAR_AMP))


def _find_fitoffset_ra() -> str | None:
    for cand in (
        os.environ.get("GMTSAR_FITOFFSET_RA"),
        shutil.which("fitoffset_ra.csh"),
        "/home/utig5/dliu/gmtsar/bin/fitoffset_ra.csh",
    ):
        if cand and os.path.isfile(cand):
            return cand
    return None


def _find_gmt() -> str | None:
    for cand in (
        os.environ.get("GMT"),
        shutil.which("gmt"),
        "/home/staff/dliu/anaconda3/envs/gmtsar/bin/gmt",
    ):
        if cand and os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


class TestResampVsCBinaryMode5(unittest.TestCase):
    """End-to-end parity for intrp=5 (GMT-grid shift) on NISAR_Ethiopia.

    Setup:
      1. fitoffset_ra.csh consumes freq_xcorr.dat + amp-*.grd → r.grd, a.grd.
      2. C `resamp ... 5 r.grd a.grd` produces the oracle SLC.
      3. resamp_py runs on the SAME inputs.
      4. Byte-compare the SLC output.

    Skipped if any of: C resamp / GMT / fitoffset_ra.csh / NISAR data missing.
    """

    @classmethod
    def setUpClass(cls):
        cls._c_resamp = _find_c_resamp()
        cls._fitoffset_ra = _find_fitoffset_ra()
        cls._gmt = _find_gmt()
        if cls._c_resamp is None:
            raise unittest.SkipTest("C `resamp` not on PATH")
        if cls._fitoffset_ra is None:
            raise unittest.SkipTest("fitoffset_ra.csh not found")
        if cls._gmt is None:
            raise unittest.SkipTest("GMT binary not on PATH (needed by fitoffset_ra.csh)")
        if not _have_nisar_inputs():
            raise unittest.SkipTest(
                f"NISAR_Ethiopia inputs not found under {_NISAR_DIR}"
            )

    def test_intrp_5_bisinc_grid(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            mprm = tmp / "master.PRM"
            aprm = tmp / "aligned.PRM"
            shutil.copy(_NISAR_MASTER_PRM, mprm)
            shutil.copy(_NISAR_ALIGNED_PRM, aprm)
            shutil.copy(_NISAR_FREQ_XCORR, tmp / "freq_xcorr.dat")
            shutil.copy(_NISAR_AMP, tmp / "amp-master.grd")
            (tmp / "NSR_20251122A.SLC").symlink_to(_NISAR_MASTER_SLC.resolve())
            (tmp / "NSR_20251204A.SLC").symlink_to(_NISAR_ALIGNED_SLC.resolve())

            # 1. Build r.grd / a.grd in the same invocation. fitoffset_ra.csh
            #    needs `gmt` on PATH; prepend the discovered GMT dir.
            env = os.environ.copy()
            gmt_dir = os.path.dirname(self._gmt)
            env["PATH"] = gmt_dir + os.pathsep + env.get("PATH", "")
            r = subprocess.run(
                [self._fitoffset_ra, "10", "10", "freq_xcorr.dat", "20"],
                capture_output=True, text=True, cwd=str(tmp), env=env,
                timeout=120,
            )
            self.assertEqual(r.returncode, 0,
                             msg=f"fitoffset_ra.csh failed: {r.stderr}")
            self.assertTrue((tmp / "r.grd").exists(),
                            msg="r.grd not produced by fitoffset_ra.csh")
            self.assertTrue((tmp / "a.grd").exists(),
                            msg="a.grd not produced by fitoffset_ra.csh")

            # 2. C oracle.
            c_prm = tmp / "c_intrp5.PRM"
            c_slc = tmp / "c_intrp5.SLC"
            r = subprocess.run(
                [self._c_resamp, "master.PRM", "aligned.PRM",
                 str(c_prm), str(c_slc), "5", "r.grd", "a.grd"],
                capture_output=True, text=True, cwd=str(tmp), env=env,
                timeout=600,
            )
            self.assertEqual(r.returncode, 0,
                             msg=f"C resamp mode 5 failed: {r.stderr}")

            # 3. Py port.
            py_prm = tmp / "py_intrp5.PRM"
            py_slc = tmp / "py_intrp5.SLC"
            r = subprocess.run(
                [sys.executable, str(_RESAMP), "master.PRM", "aligned.PRM",
                 str(py_prm), str(py_slc), "5", "r.grd", "a.grd"],
                capture_output=True, text=True, cwd=str(tmp), env=env,
                timeout=900,
            )
            self.assertEqual(r.returncode, 0,
                             msg=f"resamp_py mode 5 failed: {r.stderr}")

            # 4. Byte-compare.
            c_bytes = c_slc.read_bytes()
            py_bytes = py_slc.read_bytes()
            self.assertEqual(len(c_bytes), len(py_bytes))
            if c_bytes != py_bytes:
                c_arr = np.frombuffer(c_bytes, dtype=np.int16)
                p_arr = np.frombuffer(py_bytes, dtype=np.int16)
                diff = (c_arr.astype(np.int32) - p_arr.astype(np.int32))
                ndiff = int(np.count_nonzero(diff))
                maxd = int(np.abs(diff).max())
                self.fail(
                    f"intrp=5 SLC NOT bit-identical: "
                    f"{ndiff}/{c_arr.size} int16 samples differ "
                    f"(max |delta|={maxd}). "
                    f"C md5={hashlib.md5(c_bytes).hexdigest()[:12]} "
                    f"Py md5={hashlib.md5(py_bytes).hexdigest()[:12]}"
                )


# -------------------------------------------------------------- entrypoint ---
if __name__ == "__main__":
    unittest.main(verbosity=2)
