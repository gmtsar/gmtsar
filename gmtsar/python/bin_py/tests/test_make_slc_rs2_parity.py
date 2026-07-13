#!/usr/bin/env python3
"""test_make_slc_rs2_parity — C-parity test for make_slc_rs2_py.

Runs the REAL C binary `make_slc_rs2` and the Python port
(``utils/make_slc_rs2_py.py``) on the SAME real RADARSAT-2 product
(RS2_SLC_Hawaii, both the 2011-05-15 master and 2011-08-19 aligned
scenes) and asserts byte-identical `.PRM`, `.LED`, `.SLC` output.

This is the Mira-discipline parity oracle (project_rules.md Rule 7 /
MEMORY.md "bin_py tests need C-parity, not self-consistency"): it is
NOT a self-consistency test. If the C binary or the cached dataset
tarball is missing, the test SKIPS LOUDLY with a stated reason -- it
never silently passes.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_UTILS = _HERE.parents[1] / "utils"
_REPO_ROOT = _HERE.parents[3]  # tests -> bin_py -> python -> gmtsar -> repo root
sys.path.insert(0, str(_UTILS))

_DATASET = _HERE.parents[1] / "work" / "dataset" / "RS2_SLC_Hawaii.tar.gz"


def _find_c_binary():
    """Locate the make_slc_rs2 C reference oracle. Priority:
    1. GMTSAR_RS2_C_BIN env override (explicit path -- useful for dev
       worktrees that don't build the C tree in-place).
    2. `make_slc_rs2` on PATH (normal installed environment).
    3. preproc/RS2_preproc/src/make_slc_rs2 relative to this checkout's
       repo root (in-tree build, e.g. after `make` in preproc/).
    """
    env_override = os.environ.get("GMTSAR_RS2_C_BIN")
    if env_override and os.path.exists(env_override) and os.access(env_override, os.X_OK):
        return env_override
    found = shutil.which("make_slc_rs2")
    if found:
        return found
    candidate = _REPO_ROOT / "preproc" / "RS2_preproc" / "src" / "make_slc_rs2"
    if candidate.exists() and os.access(candidate, os.X_OK):
        return str(candidate)
    return None


_C_BIN = _find_c_binary()
_HAVE_C_BIN = _C_BIN is not None
_HAVE_DATASET = _DATASET.exists()

_SKIP_REASON = None
if not _HAVE_C_BIN:
    _SKIP_REASON = (
        "make_slc_rs2 C binary not found (not on PATH and not built at "
        "preproc/RS2_preproc/src/make_slc_rs2) -- refusing to silently pass"
    )
elif not _HAVE_DATASET:
    _SKIP_REASON = (
        f"real dataset tarball missing: {_DATASET} -- refusing to silently pass"
    )


def _extract_scenes(dest: Path):
    """Extract RS2_SLC_Hawaii.tar.gz and return the two raw SLC scene
    directories (each containing product.xml + imagery_HH.tif)."""
    with tarfile.open(_DATASET, "r:gz") as tf:
        if hasattr(tarfile, "data_filter"):
            tf.extractall(dest, filter="data")
        else:
            tf.extractall(dest)
    scene_dirs = sorted(
        p.parent for p in dest.rglob("product.xml")
    )
    if len(scene_dirs) < 2:
        raise RuntimeError(
            f"test_make_slc_rs2_parity: expected >=2 product.xml scenes in "
            f"{_DATASET}, found {len(scene_dirs)}"
        )
    return scene_dirs


@unittest.skipUnless(_HAVE_C_BIN and _HAVE_DATASET, _SKIP_REASON or "")
class TestMakeSlcRs2Parity(unittest.TestCase):
    """Byte-for-byte parity: C make_slc_rs2 vs make_slc_rs2_py, on the
    real RS2_SLC_Hawaii product (2 scenes: master + aligned)."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp(prefix="rs2_parity_")
        cls.scene_dirs = _extract_scenes(Path(cls._tmp) / "extract")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def _run_c(self, scene_dir: Path, outdir: Path, prefix: str):
        outdir.mkdir(parents=True, exist_ok=True)
        rc = subprocess.run(
            [_C_BIN, str(scene_dir / "product.xml"), str(scene_dir / "imagery_HH.tif"), prefix],
            cwd=outdir, capture_output=True, text=True,
        )
        self.assertEqual(
            rc.returncode, 0,
            f"C make_slc_rs2 failed (rc={rc.returncode}):\n{rc.stdout}\n{rc.stderr}",
        )
        for ext in (".PRM", ".LED", ".SLC"):
            self.assertTrue((outdir / (prefix + ext)).exists(), f"C did not produce {prefix}{ext}")

    def _run_py(self, scene_dir: Path, outdir: Path, prefix: str):
        outdir.mkdir(parents=True, exist_ok=True)
        from make_slc_rs2_py import make_slc_rs2
        cwd = os.getcwd()
        os.chdir(outdir)
        try:
            make_slc_rs2(str(scene_dir / "product.xml"), str(scene_dir / "imagery_HH.tif"), prefix)
        finally:
            os.chdir(cwd)
        for ext in (".PRM", ".LED", ".SLC"):
            self.assertTrue((outdir / (prefix + ext)).exists(), f"py did not produce {prefix}{ext}")

    def _assert_byte_identical(self, scene_dir: Path, prefix: str):
        c_dir = Path(self._tmp) / "c_out"
        py_dir = Path(self._tmp) / "py_out"
        self._run_c(scene_dir, c_dir, prefix)
        self._run_py(scene_dir, py_dir, prefix)
        for ext in (".PRM", ".LED", ".SLC"):
            c_bytes = (c_dir / (prefix + ext)).read_bytes()
            py_bytes = (py_dir / (prefix + ext)).read_bytes()
            if c_bytes != py_bytes:
                # Report first diverging byte offset -- Mira discipline:
                # first checkpoint, not just "they differ".
                n = min(len(c_bytes), len(py_bytes))
                first_diff = next((i for i in range(n) if c_bytes[i] != py_bytes[i]), n)
                self.fail(
                    f"{prefix}{ext}: byte mismatch at offset {first_diff} "
                    f"(C len={len(c_bytes)}, py len={len(py_bytes)}); "
                    f"C[{first_diff}:{first_diff+16}]={c_bytes[first_diff:first_diff+16]!r} "
                    f"py[{first_diff}:{first_diff+16}]={py_bytes[first_diff:first_diff+16]!r}"
                )

    def test_master_scene_byte_identical(self):
        self._assert_byte_identical(self.scene_dirs[0], "RS2MASTER")

    def test_aligned_scene_byte_identical(self):
        self._assert_byte_identical(self.scene_dirs[1], "RS2ALIGNED")


@unittest.skipUnless(_HAVE_C_BIN and _HAVE_DATASET, _SKIP_REASON or "")
class TestMakeSlcRs2Timing(unittest.TestCase):
    """Honest timing record (not a hard perf gate -- I/O noise on
    shared/NFS hosts is too high for a strict pass/fail threshold).
    See make_slc_rs2_py.py module docstring / AUDIT for the measured
    numbers: py is ~1.2-1.4x SLOWER than C on local disk, warm cache,
    steady state (I/O-bound: both read ~79MB TIFF + write ~78MB SLC).
    This test just prints the ratio for visibility in CI logs."""

    def test_timing_report(self):
        import time
        with tempfile.TemporaryDirectory() as td:
            scene_dirs = _extract_scenes(Path(td) / "extract")
            scene = scene_dirs[0]
            xml = str(scene / "product.xml")
            tif = str(scene / "imagery_HH.tif")

            c_dir = Path(td) / "c_time"
            c_dir.mkdir()
            subprocess.run([_C_BIN, xml, tif, "WARM"], cwd=c_dir,
                            capture_output=True)
            t0 = time.time()
            subprocess.run([_C_BIN, xml, tif, "OUT"], cwd=c_dir,
                            capture_output=True)
            t_c = time.time() - t0

            py_dir = Path(td) / "py_time"
            py_dir.mkdir()
            from make_slc_rs2_py import make_slc_rs2
            cwd = os.getcwd()
            os.chdir(py_dir)
            try:
                make_slc_rs2(xml, tif, "WARM")
                t0 = time.time()
                make_slc_rs2(xml, tif, "OUT")
                t_py = time.time() - t0
            finally:
                os.chdir(cwd)

            print(f"\n[test_make_slc_rs2_parity] timing: C={t_c:.3f}s py={t_py:.3f}s "
                  f"ratio(py/C)={t_py / t_c:.2f}x")
            # Not a hard gate -- documents honest perf, doesn't fail CI on
            # noisy shared/NFS hosts.


if __name__ == "__main__":
    unittest.main()
