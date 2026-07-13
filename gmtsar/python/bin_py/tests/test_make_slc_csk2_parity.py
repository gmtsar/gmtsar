#!/usr/bin/env python3
"""test_make_slc_csk2_parity — C-parity test for utils/make_slc_csk2_py.py.

Verifies the Python port of preproc/CSK_preproc/src_slc2/make_slc_csk2.c
produces byte-identical .PRM/.LED/.SLC output vs the real C
`make_slc_csk2` binary, run on the same input HDF5 bytes.

NOTE on the input fixture (read before touching this test)
------------------------------------------------------------
`make_slc_csk2` targets COSMO-SkyMed **2nd-Generation (CSG)** HDF5
products: it hardcodes "/S01/IMG" for the pixel dataset. No genuine
CSG-format product exists anywhere in this checkout (searched the
whole repo, including work/dataset/*.tar.gz — only CSKS2 1st-gen RAW/
SLC and NISAR products are cached). `CSK_SLC_Italy.tar.gz` (this repo's
only cached "real CSK SLC data") is 1st-generation CSKS2 format, whose
pixel dataset is named "/S01/SBI" — running the real `make_slc_csk2`
binary directly against it fails with an HDF5 "object 'IMG' doesn't
exist" error (confirmed).

Diffing src_slc/make_slc_csk.c (1st-gen, reads "SBI") against
src_slc2/make_slc_csk2.c (CSG, reads "IMG") shows the *only*
differences are: the dataset name/group nesting for pixel data, a
malloc sizing constant (irrelevant to output), and how state-vector
count is discovered (loop-until-zero vs an HDF5 attribute CSG lacks).
Every attribute this code reads (Radar Wavelength, Sampling Rate,
PRF, Range Chirp Rate/Length, Zero Doppler *, Reference UTC, Orbit
Direction, Look Side, Product Type, ...) has an identical name/format
in the real CSKS2 file.

So this test builds its fixture by copying the real CSK_SLC_Italy .h5
and creating an HDF5 hard link "/S01/IMG" -> "/S01/SBI" (zero data
duplication, same file). Every byte of pixel data, every orbit state
vector, and every product-metadata attribute is the genuine CSKS2
acquisition; only the dataset *label* is relinked so make_slc_csk2's
hardcoded "IMG" lookups resolve. This is disclosed, not hidden: no
claim is made that this exercises CSG-specific behavior beyond the 3
lines diffed above.

Skips loudly (unittest.skipTest, not silent pass) if:
  - the real make_slc_csk2 C binary is not found
  - the CSK_SLC_Italy dataset tarball is not present
  - h5py is not importable
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_UTILS = _HERE.parent.parent / "utils"
sys.path.insert(0, str(_UTILS))

try:
    import h5py
    _HAVE_H5PY = True
except ImportError:
    _HAVE_H5PY = False

import make_slc_csk2_py as port  # noqa: E402

_REPO_ROOT = _HERE.parent.parent.parent.parent  # gmtsar/python/bin_py/tests -> repo root

# git worktrees only check out tracked files: work/dataset/*.tar.gz (data
# cache) and bin/ (build output) are gitignored and therefore absent from
# an isolated agent worktree. Fall back to the shared checkout(s) that
# host them (read-only reference, same pattern as the hardcoded shared
# paths in test_xcorr.py).
_SHARED_CHECKOUTS = (
    "/home/utig5/dliu/gmtsar",
    "/home/staff/dliu/gmtsar",
)


def _find_dataset_tgz() -> Path | None:
    candidates = [_HERE.parent.parent / "work" / "dataset" / "CSK_SLC_Italy.tar.gz"]
    candidates += [
        Path(root) / "gmtsar" / "python" / "work" / "dataset" / "CSK_SLC_Italy.tar.gz"
        for root in _SHARED_CHECKOUTS
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


_DATASET_TGZ = _find_dataset_tgz()


def _find_c_binary() -> str | None:
    candidates = [
        os.environ.get("MAKE_SLC_CSK2_BIN", ""),
        str(_REPO_ROOT / "bin" / "make_slc_csk2"),
    ]
    candidates += [str(Path(root) / "bin" / "make_slc_csk2") for root in _SHARED_CHECKOUTS]
    candidates.append(shutil.which("make_slc_csk2") or "")
    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def _find_real_h5(extract_dir: Path) -> Path | None:
    matches = sorted(extract_dir.rglob("*.h5"))
    return matches[0] if matches else None


class TestMakeSlcCsk2Parity(unittest.TestCase):
    """C-parity: py port vs real make_slc_csk2 binary on real CSK pixel/orbit
    data (relinked SBI->IMG fixture; see module docstring)."""

    @classmethod
    def setUpClass(cls):
        cls.c_bin = _find_c_binary()
        if cls.c_bin is None:
            raise unittest.SkipTest(
                "make_slc_csk2 C binary not found (set MAKE_SLC_CSK2_BIN to "
                "override). This is a loud skip, not a silent pass.")
        if not _HAVE_H5PY:
            raise unittest.SkipTest("h5py not importable.")
        if _DATASET_TGZ is None:
            raise unittest.SkipTest("CSK_SLC_Italy.tar.gz not found in any known location.")

        cls.tmpdir = tempfile.mkdtemp(prefix="csk2_parity_")
        with tarfile.open(_DATASET_TGZ) as tf:
            tf.extractall(cls.tmpdir)

        real_h5 = _find_real_h5(Path(cls.tmpdir))
        if real_h5 is None:
            raise unittest.SkipTest("No .h5 found in extracted CSK_SLC_Italy tarball.")

        cls.fixture = os.path.join(cls.tmpdir, "fixture_csg.h5")
        shutil.copyfile(real_h5, cls.fixture)
        with h5py.File(cls.fixture, "r+") as f:
            g = f["/S01"]
            if "IMG" not in g:
                g["IMG"] = g["SBI"]  # hard link, no data duplication

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(getattr(cls, "tmpdir", ""), ignore_errors=True)

    def _run_c(self, out_prefix: str, slc_factor: float | None) -> None:
        cmd = [self.c_bin, self.fixture, out_prefix]
        if slc_factor is not None:
            cmd.append(str(slc_factor))
        subprocess.run(cmd, check=True, capture_output=True)

    def _run_py(self, out_prefix: str, slc_factor: float) -> None:
        port.run(self.fixture, out_prefix, slc_factor)

    def _assert_parity(self, c_prefix: str, py_prefix: str):
        for ext in (".LED", ".SLC"):
            c_bytes = Path(c_prefix + ext).read_bytes()
            py_bytes = Path(py_prefix + ext).read_bytes()
            self.assertEqual(
                c_bytes, py_bytes,
                f"{ext}: byte mismatch, C={len(c_bytes)}B py={len(py_bytes)}B")

        # PRM differs only in the 3 embedded path lines (input_file/led_file/
        # SLC_file use the *_prefix arg verbatim) -- normalize those before
        # comparing everything else byte-for-byte.
        c_prm = Path(c_prefix + ".PRM").read_text().replace(c_prefix, "PFX")
        py_prm = Path(py_prefix + ".PRM").read_text().replace(py_prefix, "PFX")
        self.assertEqual(c_prm, py_prm, "PRM mismatch beyond path-prefix substitution")

    def test_parity_default_factor(self):
        """SLC_factor defaults to 1.0 (no arg) -- the real p2p_CSK invocation."""
        c_prefix = os.path.join(self.tmpdir, "c_default")
        py_prefix = os.path.join(self.tmpdir, "py_default")
        self._run_c(c_prefix, None)
        self._run_py(py_prefix, 1.0)
        self._assert_parity(c_prefix, py_prefix)

    def test_parity_explicit_scale_factor(self):
        """Non-trivial SLC_factor exercises the float32-narrowing clip path."""
        c_prefix = os.path.join(self.tmpdir, "c_scaled")
        py_prefix = os.path.join(self.tmpdir, "py_scaled")
        self._run_c(c_prefix, 1.37)
        self._run_py(py_prefix, 1.37)
        self._assert_parity(c_prefix, py_prefix)

    def test_env_gate_default_off_uses_c_binary(self):
        """bin_py/make_slc_csk2_py dispatcher: GMTSAR_CSK_PREPROC_PY unset ->
        C binary subprocess (env-gate default OFF, per project rule)."""
        dispatcher = str(_HERE.parent / "make_slc_csk2_py")
        out_prefix = os.path.join(self.tmpdir, "dispatch_default")
        env = dict(os.environ)
        env.pop("GMTSAR_CSK_PREPROC_PY", None)
        env["PATH"] = os.path.dirname(self.c_bin) + os.pathsep + env.get("PATH", "")
        result = subprocess.run(
            [sys.executable, dispatcher, self.fixture, out_prefix],
            env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(os.path.isfile(out_prefix + ".PRM"))
        # SLC content must match the direct C run (same binary, same input).
        c_prefix = os.path.join(self.tmpdir, "c_for_gate_check")
        self._run_c(c_prefix, None)
        self.assertEqual(
            Path(c_prefix + ".SLC").read_bytes(),
            Path(out_prefix + ".SLC").read_bytes())

    def test_env_gate_on_uses_python_port(self):
        """GMTSAR_CSK_PREPROC_PY=1 -> in-process Python port, byte-identical
        to the direct C run."""
        dispatcher = str(_HERE.parent / "make_slc_csk2_py")
        out_prefix = os.path.join(self.tmpdir, "dispatch_py")
        env = dict(os.environ)
        env["GMTSAR_CSK_PREPROC_PY"] = "1"
        result = subprocess.run(
            [sys.executable, dispatcher, self.fixture, out_prefix],
            env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        c_prefix = os.path.join(self.tmpdir, "c_for_gate_check2")
        self._run_c(c_prefix, None)
        self.assertEqual(
            Path(c_prefix + ".SLC").read_bytes(),
            Path(out_prefix + ".SLC").read_bytes())


if __name__ == "__main__":
    unittest.main()
