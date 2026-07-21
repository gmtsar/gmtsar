#!/usr/bin/env python3
"""test_make_slc_tsx -- C-parity test for make_slc_tsx_py.py.

Per Mira's discipline: this is NOT a self-consistency test. It runs the
REAL C `make_slc_tsx` binary and the Python port on the SAME real TerraSAR-X
scene (TSX_SLC_Hawaii dataset, TSX20120615) and asserts byte-identical
.PRM / .LED / .SLC output. If the C binary or the real dataset tarball
cannot be found, the test SKIPS LOUDLY (visible skip reason), it never
silently passes.

Two layers:
  1. TestStr2DoubleParity -- fast, no real data needed. Verifies the
     ported str2double_c/cat_nums_c/str_date2JD_c match a standalone C
     harness linking the real xml.c on real numeric/date strings pulled
     from the canonical XML. This is the layer that would have caught the
     "Python float() is 1 ULP off from C's str2double" trap.
  2. TestMakeSlcTsxVsCBinary -- full end-to-end parity on real data.
     Skips loudly if the C binary or dataset tarball is not found.
"""
from __future__ import annotations

import os
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PY_TREE = _HERE.parents[1]          # .../gmtsar/python
_UTILS = _PY_TREE / "utils"
sys.path.insert(0, str(_UTILS))

import make_slc_tsx_py as tsx_py  # noqa: E402


# --------------------------------------------------------------------------
# Path resolution: worktree-safe. The TSX C source/binary and the dataset
# tarball may live in a sibling "main" checkout rather than this worktree
# (worktrees don't get the built C binaries or work/dataset/ scratch).
# --------------------------------------------------------------------------

def _repo_root_candidates():
    cands = []
    # This worktree's own repo root: .../gmtsar/python/bin_py/tests -> up 4
    cands.append(_PY_TREE.parents[1])
    # Strip a ".claude/worktrees/<name>" suffix to find the main checkout.
    parts = _PY_TREE.parts
    if ".claude" in parts:
        idx = parts.index(".claude")
        cands.append(Path(*parts[:idx]))
    gmtsar_env = os.environ.get("GMTSAR")
    if gmtsar_env:
        cands.append(Path(gmtsar_env))
    # De-dup, preserve order.
    seen = set()
    out = []
    for c in cands:
        if c not in seen and c.exists():
            seen.add(c)
            out.append(c)
    return out


def _find_c_binary():
    which = shutil.which("make_slc_tsx")
    if which:
        return Path(which)
    for root in _repo_root_candidates():
        for cand in (root / "bin" / "make_slc_tsx",
                     root / "preproc" / "TSX_preproc" / "src" / "make_slc_tsx"):
            if cand.exists() and os.access(cand, os.X_OK):
                return cand
    return None


def _find_dataset_tarball():
    override = os.environ.get("GMTSAR_TSX_DATASET_TARBALL")
    if override and Path(override).exists():
        return Path(override)
    for root in _repo_root_candidates():
        cand = root / "gmtsar" / "python" / "work" / "dataset" / "TSX_SLC_Hawaii.tar.gz"
        if cand.exists():
            return cand
    return None


_C_BIN = _find_c_binary()
_TARBALL = _find_dataset_tarball()


# --------------------------------------------------------------------------
# Layer 1: numeric-parsing parity vs a standalone C harness linking the
# real xml.c str2double/cat_nums/str_date2JD. This directly guards against
# the "library substitution" trap (Python float() disagreeing with C's
# hand-rolled decimal parser by 1 ULP).
# --------------------------------------------------------------------------

_XML_C_SRC_CANDIDATES = []
for root in _repo_root_candidates():
    cand = root / "preproc" / "S1A_preproc" / "lib" / "xml.c"
    if cand.exists():
        _XML_C_SRC_CANDIDATES.append(cand)
_XML_C_SRC = _XML_C_SRC_CANDIDATES[0] if _XML_C_SRC_CANDIDATES else None
_XML_C_INCLUDE = _XML_C_SRC.parents[1] / "include" if _XML_C_SRC else None


@unittest.skipUnless(_XML_C_SRC and shutil.which("gcc"),
                      "xml.c source or gcc not found -- cannot build C str2double harness")
class TestStr2DoubleParity(unittest.TestCase):
    """Verify str2double_c against a compiled copy of the REAL C str2double
    (xml.c), on real numeric strings pulled from the canonical TSX XML."""

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.mkdtemp(prefix="str2double_harness_")
        harness_c = os.path.join(cls._tmpdir, "harness.c")
        with open(harness_c, "w") as f:
            f.write(
                "#include <stdio.h>\n#include <string.h>\n"
                "double str2double(char *str);\n"
                "int main(){char line[1000];"
                "while(fgets(line,sizeof(line),stdin)){"
                "int n=strlen(line);"
                "while(n>0&&(line[n-1]=='\\n'||line[n-1]=='\\r'))line[--n]=0;"
                "double v=str2double(line);"
                "unsigned long long b;memcpy(&b,&v,8);"
                "printf(\"%016llx\\n\",b);}"
                "return 0;}\n"
            )
        exe = os.path.join(cls._tmpdir, "harness")
        cmd = ["gcc", "-O0", "-o", exe, harness_c, str(_XML_C_SRC),
               "-I", str(_XML_C_INCLUDE), "-lm"]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"Failed to build str2double C harness: {r.stderr}")
        cls._exe = exe

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    def _c_bits(self, values):
        inp = "\n".join(values) + "\n"
        r = subprocess.run([self._exe], input=inp, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return [int(x, 16) for x in r.stdout.split()]

    def test_real_xml_numeric_strings(self):
        # Pulled directly from TSX20120615.xml (the canonical Hawaii scene).
        values = [
            "6.06688650151242618E-09", "3.29999995231628418E+00",
            "1.00000000000000000E+00", "3.86392847637630557E-03",
            "3.46862777777777774E+03", "5.34000000000000000E+02",
            "1.20000000000000000E+02", "9.65000000000000000E+09",
            "-5.64500007629394531E+01", "27750", "18880", "27748",
            "2012", "166",
        ]
        c_bits = self._c_bits(values)
        for v, expect_bits in zip(values, c_bits):
            got = tsx_py.str2double_c(v)
            got_bits = struct.unpack('<Q', struct.pack('<d', got))[0]
            self.assertEqual(got_bits, expect_bits,
                              f"str2double_c({v!r}) = {got!r} (0x{got_bits:016x}) "
                              f"!= C str2double (0x{expect_bits:016x})")

    def test_python_float_would_have_diverged(self):
        """Documents WHY str2double_c can't be float(): on these exact real
        values, Python's correctly-rounded float() is 1 ULP off from C's
        hand-rolled parser. If this test ever starts failing (i.e. float()
        now agrees), that's fine -- but str2double_c must still match C."""
        divergent = ["6.06688650151242618E-09", "3.86392847637630557E-03",
                     "-5.64500007629394531E+01"]
        c_bits = self._c_bits(divergent)
        mismatches = 0
        for v, cb in zip(divergent, c_bits):
            py_bits = struct.unpack('<Q', struct.pack('<d', float(v)))[0]
            if py_bits != cb:
                mismatches += 1
        self.assertGreater(mismatches, 0,
                            "expected float() to diverge from C str2double on at least "
                            "one real value (regression in the justification for "
                            "porting str2double verbatim)")

    def test_date_jd_matches_c_reference_prm(self):
        """2012-06-15T16:20:57.425000Z -> clock_start=166.681220196759 in
        the real C-produced PRM (ground truth captured from a live run)."""
        digits = tsx_py.cat_nums_c("2012-06-15T16:20:57.425000Z")
        jd_str = tsx_py.str_date2JD_c(digits)
        self.assertEqual(jd_str, "166.681220196759")


# --------------------------------------------------------------------------
# Layer 2: full end-to-end parity vs the real C binary on real data.
# --------------------------------------------------------------------------

@unittest.skipUnless(_C_BIN, "make_slc_tsx C binary not found on PATH, $GMTSAR/bin, "
                              "or preproc/TSX_preproc/src -- parity test cannot run "
                              "(this is a loud skip, not a silent pass)")
@unittest.skipUnless(_TARBALL, "TSX_SLC_Hawaii.tar.gz dataset not found under "
                                "gmtsar/python/work/dataset/ in any known repo root "
                                "-- parity test cannot run (loud skip, not silent pass)")
class TestMakeSlcTsxVsCBinary(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.mkdtemp(prefix="make_slc_tsx_parity_")
        raw_dir = Path(cls._tmpdir) / "extracted"
        raw_dir.mkdir()
        with tarfile.open(_TARBALL) as tf:
            if hasattr(tarfile, "data_filter"):
                tf.extractall(raw_dir, filter="data")
            else:
                tf.extractall(raw_dir)
        cls._raw = raw_dir / "raw"
        assert (cls._raw / "TSX20120615.xml").exists(), \
            f"unexpected tarball layout under {cls._raw}"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    def _run_c(self, scene, outdir):
        outdir.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(
            [str(_C_BIN), f"{scene}.xml", f"{scene}.cos", str(outdir / scene)],
            cwd=self._raw, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, f"C binary failed: {r.stderr}\n{r.stdout}")

    def _run_py(self, scene, outdir):
        outdir.mkdir(parents=True, exist_ok=True)
        xml_path = self._raw / f"{scene}.xml"
        img_path = self._raw / f"{scene}.cos"
        tsx_py.make_slc_tsx(str(xml_path), str(img_path), str(outdir / scene))

    def _compare_prm(self, c_path, py_path):
        """PRM files embed the absolute output-dir path in input_file/
        led_file/SLC_file fields. C and Python write to separate
        directories (c_out_*/ vs py_out_*/) so those directory names
        legitimately differ in the text; normalize them out before
        comparing everything else byte-for-byte."""
        c_text = c_path.read_text().replace(str(c_path.parent), "OUTDIR")
        py_text = py_path.read_text().replace(str(py_path.parent), "OUTDIR")
        self.assertEqual(c_text, py_text,
                          "PRM text differs between C and Python ports "
                          "(after normalizing the output-directory path)")

    def test_scene_20120615_full_parity(self):
        c_dir = Path(self._tmpdir) / "c_out_a"
        py_dir = Path(self._tmpdir) / "py_out_a"
        self._run_c("TSX20120615", c_dir)
        self._run_py("TSX20120615", py_dir)

        self._compare_prm(c_dir / "TSX20120615.PRM", py_dir / "TSX20120615.PRM")

        c_led = (c_dir / "TSX20120615.LED").read_bytes()
        py_led = (py_dir / "TSX20120615.LED").read_bytes()
        self.assertEqual(c_led, py_led, "LED bytes differ between C and Python ports")

        c_slc = c_dir / "TSX20120615.SLC"
        py_slc = py_dir / "TSX20120615.SLC"
        self.assertEqual(c_slc.stat().st_size, py_slc.stat().st_size,
                          "SLC file size differs between C and Python ports")
        # Byte-for-byte compare via filecmp (memory-mapped, avoids loading
        # the ~2GB file into a Python bytes object twice).
        import filecmp
        self.assertTrue(filecmp.cmp(c_slc, py_slc, shallow=False),
                         "SLC bytes differ between C and Python ports "
                         "(first diverging checkpoint: run `cmp` locally for the offset)")

    def test_scene_20121208_full_parity(self):
        """Second real scene (different cols/rows: 18878 x 27750) -- guards
        against off-by-a-few-columns bugs that a single fixture could hide."""
        c_dir = Path(self._tmpdir) / "c_out_b"
        py_dir = Path(self._tmpdir) / "py_out_b"
        self._run_c("TSX20121208", c_dir)
        self._run_py("TSX20121208", py_dir)

        self._compare_prm(c_dir / "TSX20121208.PRM", py_dir / "TSX20121208.PRM")

        c_led = (c_dir / "TSX20121208.LED").read_bytes()
        py_led = (py_dir / "TSX20121208.LED").read_bytes()
        self.assertEqual(c_led, py_led, "LED bytes differ between C and Python ports")

        import filecmp
        self.assertTrue(filecmp.cmp(c_dir / "TSX20121208.SLC",
                                     py_dir / "TSX20121208.SLC", shallow=False),
                         "SLC bytes differ between C and Python ports (scene B)")


if __name__ == "__main__":
    unittest.main()
