#!/usr/bin/env python3
"""test_make_slc_csk_parity — parity tests for utils/make_slc_csk_py.py.

Ports preproc/CSK_preproc/src_slc/make_slc_csk.c (Rule 7 / Phase C gate).

Test pyramid:

  Unit (fast — milliseconds each):
    - TestStringDateHelpers — str2double/cat_nums/str_date2JD transliterated
      helpers vs hand-computed values (catches digit-accumulation drift
      from Python's float()).
    - TestPutSioStruct — put_sio_struct field-order/format vs a hand-built
      dict, mirrors gmtsar/sio_struct.c literally (including the
      stretch_r-gated-on-stretch_a C quirk).

  Parity (slow — ~3-6 minutes; the real CSK SCS_B products are ~1GB HDF5
         each with ~1.9GB pixel payload; both C and Py must read the whole
         thing). Opt-in via CSK_MAKE_SLC_SLOW_TEST=1, matching the
         SNAPHU_SLOW_TEST precedent (test_snaphu_py.py). Skipped LOUDLY
         (not silently) if the C binary or real dataset are missing —
         this is a SKIP, not a PASS.
    - TestMakeSlcCskVsCBinary.test_prm_led_slc_byte_identical — runs the
      real C `make_slc_csk` and the Py port on the SAME real CSKS2 SCS_B
      HDF5 acquisition (CSK_SLC_Italy dataset) and asserts the .PRM
      (modulo the output-prefix-derived filename fields), .LED, and .SLC
      outputs are byte-for-byte identical.

Set CSK_MAKE_SLC_SLOW_TEST=1 to run the parity test:
    CSK_MAKE_SLC_SLOW_TEST=1 python3 -m pytest test_make_slc_csk_parity.py -v
"""
from __future__ import annotations

import filecmp
import importlib.util as _ilu
import importlib.machinery as _ilm
import os
import shutil
import subprocess
import sys
import tarfile
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PY_MOD_PATH = _HERE.parent.parent / "utils" / "make_slc_csk_py.py"

_spec = _ilu.spec_from_loader(
    "make_slc_csk_py_mod",
    _ilm.SourceFileLoader("make_slc_csk_py_mod", str(_PY_MOD_PATH)),
)
_MOD = _ilu.module_from_spec(_spec)
sys.modules["make_slc_csk_py_mod"] = _MOD
_spec.loader.exec_module(_MOD)

strasign = _MOD.strasign
cat_nums = _MOD.cat_nums
str2double = _MOD.str2double
str_date2JD = _MOD.str_date2JD
put_sio_struct = _MOD.put_sio_struct


# ---------------------------------------------------------------------------
# Locate the real dataset + C binary (search worktree-local work/, then the
# outer shared checkout if this test is running inside a .claude/worktrees
# checkout, then GMTSAR_TEST_WORK override).
# ---------------------------------------------------------------------------

def _candidate_work_roots():
    roots = []
    env = os.environ.get("GMTSAR_TEST_WORK")
    if env:
        roots.append(Path(env))
    roots.append(_HERE.parents[1] / "work")  # <repo>/gmtsar/python/work
    # If we're inside .../<outer_repo>/.claude/worktrees/<name>/gmtsar/python,
    # also check the outer (shared) checkout's work dir.
    parts = _HERE.parts
    if ".claude" in parts and "worktrees" in parts:
        idx = parts.index(".claude")
        outer = Path(*parts[:idx])
        roots.append(outer / "gmtsar" / "python" / "work")
    return roots


def _find_dataset_tarball():
    for root in _candidate_work_roots():
        cand = root / "dataset" / "CSK_SLC_Italy.tar.gz"
        if cand.exists():
            return cand
    return None


def _extraction_dir():
    # Prefer a writable worktree-local work dir for the extracted fixture.
    return _HERE.parents[1] / "work" / "csh_test" / "CSK_SLC_Italy_makeslc_fixture"


def _extract_one_h5(tarball: Path, dest_dir: Path) -> Path | None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball, "r:gz") as tf:
        members = [m for m in tf.getmembers()
                   if m.name.endswith(".h5") and "raw/" in m.name]
        members.sort(key=lambda m: m.name)
        if not members:
            return None
        m = members[0]
        target = dest_dir / Path(m.name).name
        if not target.exists():
            with tf.extractfile(m) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out, length=64 * 1024 * 1024)
        return target


def _find_c_binary() -> str:
    found = shutil.which("make_slc_csk")
    if found:
        return found
    gmtsar_env = os.environ.get("GMTSAR", "")
    for root in [gmtsar_env] + [str(p) for p in _candidate_work_roots()]:
        if not root:
            continue
        cand = Path(root) / "bin" / "make_slc_csk"
        if cand.exists() and os.access(cand, os.X_OK):
            return str(cand)
    # Outer shared checkout fallback (bin/ next to gmtsar/python/work's outer root)
    parts = _HERE.parts
    if ".claude" in parts and "worktrees" in parts:
        idx = parts.index(".claude")
        outer = Path(*parts[:idx])
        cand = outer / "bin" / "make_slc_csk"
        if cand.exists() and os.access(cand, os.X_OK):
            return str(cand)
    return ""


C_MAKE_SLC_CSK = _find_c_binary()
_TARBALL = _find_dataset_tarball()


def _have_c_binary() -> bool:
    return bool(C_MAKE_SLC_CSK) and Path(C_MAKE_SLC_CSK).exists() and os.access(C_MAKE_SLC_CSK, os.X_OK)


def _have_dataset() -> bool:
    return _TARBALL is not None


# ============================================================ unit tests ===


class TestStringDateHelpers(unittest.TestCase):
    """xml.c string/date helpers, transliterated (not Python float()/datetime)."""

    def test_str2double_integer(self):
        self.assertEqual(str2double("2009"), 2009.0)

    def test_str2double_decimal(self):
        self.assertAlmostEqual(str2double("123.456"), 123.456, places=9)

    def test_str2double_negative(self):
        self.assertAlmostEqual(str2double("-42.5"), -42.5, places=9)

    def test_str2double_exponent(self):
        self.assertAlmostEqual(str2double("1.5e2"), 150.0, places=6)

    def test_cat_nums_utc_string(self):
        # A typical CSK "Reference UTC" string, e.g. "2009-04-12T05:06:38.123456Z"
        out = cat_nums("2009-04-12T05:06:38.123456Z")
        self.assertTrue(out.startswith("20090412050638123456"))

    def test_str_date2JD_known_value(self):
        date = cat_nums("2009-04-12T05:06:38.123456Z")
        jd = str_date2JD(date)
        # date2MJD(yr,1,1,...) is the yr-anchor, so day-of-year is 0-based:
        # 2009-04-12 -> Jan(31)+Feb(28)+Mar(31)+day(12)-1 = 101 (matches the
        # real C reference PRM clock_start=101.21293929... for the sibling
        # 2009-04-12T05:06:38 acquisition in CSK_SLC_Italy).
        self.assertTrue(jd.startswith("101."))


class TestPutSioStruct(unittest.TestCase):
    """put_sio_struct field order/format, mirrors gmtsar/sio_struct.c literally."""

    def test_stretch_r_gated_on_stretch_a(self):
        """C literal quirk (sio_struct.c:366-369): stretch_r's print line is
        gated on `prm.stretch_a != NULL_DOUBLE`, not `prm.stretch_r`."""
        import io
        prm = {"stretch_a": 0.0, "stretch_r": 5.0}
        fp = io.StringIO()
        put_sio_struct(prm, fp)
        out = fp.getvalue()
        self.assertIn("stretch_r   \t\t= 5 \n", out)
        self.assertIn("stretch_a   \t\t= 0 \n", out)

    def test_missing_key_skipped(self):
        import io
        prm = {"num_lines": 100}
        fp = io.StringIO()
        put_sio_struct(prm, fp)
        out = fp.getvalue()
        self.assertIn("num_lines\t\t= 100 \n", out)
        self.assertNotIn("nrows", out)


# ============================================================ parity gate ==


_RUN_SLOW = os.environ.get("CSK_MAKE_SLC_SLOW_TEST") == "1"


@unittest.skipUnless(_RUN_SLOW, "Set CSK_MAKE_SLC_SLOW_TEST=1 to run "
                                  "(real ~1GB HDF5 read x2, ~3-6 minutes).")
class TestMakeSlcCskVsCBinary(unittest.TestCase):
    """C1-C8 end-to-end parity: real C `make_slc_csk` vs Py port on the
    SAME real CSKS2 SCS_B HDF5 acquisition (CSK_SLC_Italy dataset)."""

    @classmethod
    def setUpClass(cls):
        if not _have_c_binary():
            raise unittest.SkipTest(
                f"make_slc_csk C binary not found (tried PATH, $GMTSAR/bin, "
                f"worktree bin/; searched={C_MAKE_SLC_CSK!r}) -- parity "
                f"cannot be verified, SKIPPING (not silently passing).")
        if not _have_dataset():
            raise unittest.SkipTest(
                "CSK_SLC_Italy.tar.gz not found under any candidate "
                "gmtsar/python/work/dataset/ -- real-data parity oracle "
                "unavailable, SKIPPING (not silently passing).")
        cls.h5_path = _extract_one_h5(_TARBALL, _extraction_dir())
        if cls.h5_path is None:
            raise unittest.SkipTest("No .h5 member found in CSK_SLC_Italy.tar.gz raw/")

    def test_prm_led_slc_byte_identical(self):
        work = _extraction_dir() / "run_out"
        work.mkdir(parents=True, exist_ok=True)
        c_prefix = "C_OUT"
        py_prefix = "PY_OUT"

        # Run the REAL C binary.
        c_res = subprocess.run(
            [C_MAKE_SLC_CSK, str(self.h5_path), c_prefix],
            cwd=work, capture_output=True, text=True, timeout=900)
        self.assertEqual(c_res.returncode, 0,
                          f"C make_slc_csk failed:\nSTDOUT={c_res.stdout}\nSTDERR={c_res.stderr}")

        # Run the Py port (same input bytes, same cwd).
        py_res = subprocess.run(
            [sys.executable, str(_PY_MOD_PATH), str(self.h5_path), py_prefix],
            cwd=work, capture_output=True, text=True, timeout=900)
        self.assertEqual(py_res.returncode, 0,
                          f"Py make_slc_csk_py failed:\nSTDOUT={py_res.stdout}\nSTDERR={py_res.stderr}")

        c_prm = work / f"{c_prefix}.PRM"
        py_prm = work / f"{py_prefix}.PRM"
        c_led = work / f"{c_prefix}.LED"
        py_led = work / f"{py_prefix}.LED"
        c_slc = work / f"{c_prefix}.SLC"
        py_slc = work / f"{py_prefix}.SLC"
        for p in (c_prm, py_prm, c_led, py_led, c_slc, py_slc):
            self.assertTrue(p.exists(), f"missing output {p}")

        # LED and SLC have no prefix-derived content -> byte-identical.
        self.assertTrue(filecmp.cmp(c_led, py_led, shallow=False),
                         "LED files differ -- first diverging orbit line is "
                         "the parity break; dump both files to compare.")
        self.assertTrue(filecmp.cmp(c_slc, py_slc, shallow=False),
                         "SLC files differ -- first diverging byte is the "
                         "parity break (radiometry/clip logic drift).")

        # PRM differs only in the 3 filename fields (which embed the output
        # prefix argv[2]); normalize those before comparing.
        c_prm_text = c_prm.read_text().replace(c_prefix, "OUT")
        py_prm_text = py_prm.read_text().replace(py_prefix, "OUT")
        self.assertEqual(c_prm_text, py_prm_text,
                          "PRM files differ (after filename normalization) "
                          "-- first diverging field is the parity break.")


if __name__ == "__main__":
    unittest.main()
