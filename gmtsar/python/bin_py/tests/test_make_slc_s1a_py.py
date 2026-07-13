#!/usr/bin/env python3
"""test_make_slc_s1a_py -- C-parity test for the Python port of
preproc/S1A_preproc/src_swath/make_slc_s1a.

Runs the REAL C binary `make_slc_s1a` and the Python port
(utils/s1a_preproc_lib.make_slc_s1a, wrapped by bin_py/make_slc_s1a_py) on
the SAME real Sentinel-1 TOPS annotation-XML + measurement-TIFF input, and
asserts byte-identical PRM/LED/SLC output.

Per /home/utig5/dliu/CLAUDE.md memory ("bin_py tests need C-parity, not
self-consistency"): this test does NOT silently pass when the C binary or
the real dataset tarball is missing -- it SKIPS LOUDLY (visible skip
reason), which is different from a green PASS.

Real data: extracts one IW1 VV annotation.xml + measurement.tiff pair from
the cached S1A_SLC_TOPS_LA.tar.gz canonical dataset
(gmtsar/python/work/dataset/). The extraction is cached on disk (keyed by a
sentinel file) so repeat test runs don't re-scan the ~4.8 GB tarball.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tarfile
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BIN_PY = _HERE.parent
_UTILS = _BIN_PY.parent / "utils"
_WORKDIR = _BIN_PY.parent / "work"


def _find_dataset_tarball() -> Path:
    """Locate S1A_SLC_TOPS_LA.tar.gz. Isolated git-worktree agent checkouts
    (.claude/worktrees/<id>/) don't carry the multi-GB download cache
    (gitignored, local to whichever checkout ran the test sweep) -- fall
    back (read-only) to the shared main checkout's cache if this worktree's
    own work/dataset/ is empty. Never writes outside this worktree."""
    local = _WORKDIR / "dataset" / "S1A_SLC_TOPS_LA.tar.gz"
    if local.exists():
        return local
    here = str(_WORKDIR)
    marker = ".claude/worktrees"
    idx = here.find(marker)
    if idx != -1:
        repo_root = Path(here[:idx])
        shared = repo_root / "gmtsar" / "python" / "work" / "dataset" / "S1A_SLC_TOPS_LA.tar.gz"
        if shared.exists():
            return shared
    return local  # doesn't exist; caller's .exists() check will fail -> skip


_DATASET_TARBALL = _find_dataset_tarball()
_CACHE_DIR = _WORKDIR / "s1a_preproc_py_test_cache" / "iw1"

def _find_c_binary() -> str:
    # 1. Explicit override.
    env_override = os.environ.get("MAKE_SLC_S1A_C_BIN", "")
    if env_override and os.access(env_override, os.X_OK):
        return env_override
    # 2. On PATH (e.g. after `install.sh --build`).
    found = shutil.which("make_slc_s1a")
    if found:
        return found
    # 3. In-tree build location relative to this worktree's repo root.
    candidate = (_BIN_PY.parent.parent.parent /
                 "preproc" / "S1A_preproc" / "src_swath" / "make_slc_s1a")
    if candidate.exists() and os.access(candidate, os.X_OK):
        return str(candidate)
    # 4. Isolated git-worktree dev fallback: agent worktrees under
    # .claude/worktrees/ check out source only (no build artifacts); the
    # C binary lives in whichever checkout ran `make`. Walk up looking for
    # a sibling checkout with a pre-built binary. This is a read-only dev
    # convenience (never writes outside this worktree) -- if none is found
    # the test SKIPS loudly, it does not silently pass.
    here = _BIN_PY.parent.parent.parent
    worktrees_marker = ".claude/worktrees"
    idx = str(here).find(worktrees_marker)
    if idx != -1:
        repo_root = Path(str(here)[:idx])
        candidate2 = (repo_root / "preproc" / "S1A_preproc" / "src_swath" / "make_slc_s1a")
        if candidate2.exists() and os.access(candidate2, os.X_OK):
            return str(candidate2)
    return ""


_C_BINARY = _find_c_binary()

sys.path.insert(0, str(_UTILS))

_XML_IN_TAR = (
    "./raw/S1A_IW_SLC__1SSV_20150526T014935_20150526T015002_006086_007E23_679A.SAFE/"
    "annotation/s1a-iw1-slc-vv-20150526t014935-20150526t015000-006086-007e23-001.xml")
_TIFF_IN_TAR = (
    "./raw/S1A_IW_SLC__1SSV_20150526T014935_20150526T015002_006086_007E23_679A.SAFE/"
    "measurement/s1a-iw1-slc-vv-20150526t014935-20150526t015000-006086-007e23-001.tiff")


def _extract_real_input():
    """Extract (once, cached) the canonical IW1 XML+TIFF pair. Returns
    (xml_path, tiff_path). Raises if the tarball is missing -- callers must
    skip, not swallow."""
    xml_out = _CACHE_DIR / "iw1.xml"
    tiff_out = _CACHE_DIR / "iw1.tiff"
    if xml_out.exists() and tiff_out.exists():
        return str(xml_out), str(tiff_out)

    if not _DATASET_TARBALL.exists():
        raise FileNotFoundError(str(_DATASET_TARBALL))

    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with tarfile.open(_DATASET_TARBALL, "r:gz") as tf:
        for member_name, out_path in (
                (_XML_IN_TAR, xml_out), (_TIFF_IN_TAR, tiff_out)):
            member = tf.getmember(member_name)
            src = tf.extractfile(member)
            if src is None:
                raise RuntimeError(f"tar member not extractable: {member_name}")
            tmp_path = str(out_path) + ".tmp"
            with open(tmp_path, "wb") as fout:
                shutil.copyfileobj(src, fout, length=64 * 1024 * 1024)
            os.rename(tmp_path, out_path)

    return str(xml_out), str(tiff_out)


def _have_real_input():
    try:
        _extract_real_input()
        return True
    except FileNotFoundError:
        return False


@unittest.skipUnless(_C_BINARY, "make_slc_s1a C binary not found on PATH or "
                                 "in preproc/S1A_preproc/src_swath/ -- "
                                 "parity test cannot run (this is a SKIP, not a PASS)")
@unittest.skipUnless(_have_real_input(),
                      f"canonical dataset tarball not found: {_DATASET_TARBALL} "
                      "-- parity test cannot run (this is a SKIP, not a PASS)")
class TestMakeSlcS1aVsCBinary(unittest.TestCase):
    """C-parity: run the real C binary and the Python port on the SAME real
    Sentinel-1 IW1 VV annotation.xml/measurement.tiff and diff outputs."""

    @classmethod
    def setUpClass(cls):
        cls.xml_path, cls.tiff_path = _extract_real_input()

    def _run_c(self, tmp_dir: Path, prefix: str) -> None:
        res = subprocess.run(
            [_C_BINARY, self.xml_path, self.tiff_path, prefix],
            cwd=str(tmp_dir), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if res.returncode != 0:
            raise RuntimeError(
                f"make_slc_s1a (C) failed rc={res.returncode}: "
                f"{res.stderr.decode(errors='replace')}")

    def _run_py(self, tmp_dir: Path, prefix: str) -> None:
        from s1a_preproc_lib import make_slc_s1a
        cwd = os.getcwd()
        os.chdir(str(tmp_dir))
        try:
            make_slc_s1a(self.xml_path, self.tiff_path, prefix)
        finally:
            os.chdir(cwd)

    def test_prm_led_slc_byte_identical(self):
        import tempfile
        with tempfile.TemporaryDirectory() as c_dir, tempfile.TemporaryDirectory() as py_dir:
            c_dir = Path(c_dir)
            py_dir = Path(py_dir)
            prefix = "S1A_test"

            self._run_c(c_dir, prefix)
            self._run_py(py_dir, prefix)

            for ext in (".PRM", ".LED", ".SLC"):
                c_file = c_dir / (prefix + ext)
                py_file = py_dir / (prefix + ext)
                self.assertTrue(c_file.exists(), f"C output missing: {c_file}")
                self.assertTrue(py_file.exists(), f"Py output missing: {py_file}")
                c_bytes = c_file.read_bytes()
                py_bytes = py_file.read_bytes()
                self.assertEqual(
                    len(c_bytes), len(py_bytes),
                    f"{ext}: size mismatch C={len(c_bytes)} Py={len(py_bytes)}")
                self.assertEqual(
                    c_bytes, py_bytes,
                    f"{ext}: byte content differs between C and Python port")

    def test_cli_wrapper_matches_library_call(self):
        """bin_py/make_slc_s1a_py CLI produces the same bytes as calling
        s1a_preproc_lib.make_slc_s1a directly (Py-only-feature equivalence:
        the CLI is new surface the C binary doesn't have an analogue test
        for)."""
        import tempfile
        wrapper = _BIN_PY / "make_slc_s1a_py"
        with tempfile.TemporaryDirectory() as lib_dir, tempfile.TemporaryDirectory() as cli_dir:
            lib_dir = Path(lib_dir)
            cli_dir = Path(cli_dir)
            prefix = "S1A_test"

            self._run_py(lib_dir, prefix)

            res = subprocess.run(
                [sys.executable, str(wrapper), self.xml_path, self.tiff_path, prefix],
                cwd=str(cli_dir), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(
                res.returncode, 0,
                f"make_slc_s1a_py CLI failed: {res.stderr.decode(errors='replace')}")

            for ext in (".PRM", ".LED", ".SLC"):
                self.assertEqual(
                    (lib_dir / (prefix + ext)).read_bytes(),
                    (cli_dir / (prefix + ext)).read_bytes(),
                    f"{ext}: CLI wrapper output differs from direct library call")

    def test_cli_missing_args_fails_cleanly(self):
        """Error-handling test for the Py-only CLI surface: too few args ->
        clean non-zero exit + usage message, not a silent wrong result."""
        wrapper = _BIN_PY / "make_slc_s1a_py"
        res = subprocess.run(
            [sys.executable, str(wrapper), self.xml_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn(b"Usage", res.stderr)

    def test_cli_missing_xml_file_raises(self):
        """Error-handling test: nonexistent xml path must raise, not
        silently produce empty/garbage output."""
        import tempfile
        wrapper = _BIN_PY / "make_slc_s1a_py"
        with tempfile.TemporaryDirectory() as d:
            res = subprocess.run(
                [sys.executable, str(wrapper), "/nonexistent/path.xml",
                 self.tiff_path, "out"],
                cwd=d, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertNotEqual(res.returncode, 0)
            self.assertFalse((Path(d) / "out.PRM").exists())


if __name__ == "__main__":
    unittest.main()
