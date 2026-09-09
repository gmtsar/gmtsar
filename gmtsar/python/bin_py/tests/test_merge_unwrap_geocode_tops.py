#!/usr/bin/env python3
"""test_merge_unwrap_geocode_tops — env-gating + unit-level sanity.

Mira-discipline tests for the Python port of merge_unwrap_geocode_tops.csh
(the final stage of the S1 TOPS pipeline that merges F1+F2+F3 subswaths,
unwraps via snaphu, then geocodes).

Three layers:
  1. TestEnvGate — GMTSAR_MERGE_TOPS_PY=0 dispatches to the csh fallback;
     unset / "1" dispatches to the Python port. Distinguishes by Usage
     banner text. Cheap, runs in CI.
  2. TestAwkInt — verifies `_awk_int` mirrors awk's `printf("%d", x)` —
     truncate-toward-zero, NOT Python `//` floor. Guards against future
     refactor breaking parity with the csh's pixel-offset arithmetic
     used in det_stitch (lines 84, 112, 124 of the csh).
  3. TestSnaphuImport — confirms the Python port imports `snaphu_unwrap`
     and `snaphu_interp_unwrap` from utils/snaphu (Mira #43). The
     previous version called the bare `snaphu` shell binary, which on
     PATH resolves to the C unwrapper (Chen & Zebker) — a silent
     wire-in defect not exercised by any TOPS test case (all S1A_*
     configs have threshold_snaphu=0).

The heavy C-parity end-to-end smoke (full Greece F1+F2+F3 merge +
unwrap + geocode) is a 55-min wall job — gated behind the
GMTSAR_RUN_TOPS_E2E env var and skipped by default in CI.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path


_PY_TREE = Path(__file__).resolve().parents[2]  # .../gmtsar/python
_PY_UTIL = _PY_TREE / "utils" / "merge_unwrap_geocode_tops"
_PY_UTILS_DIR = _PY_TREE / "utils"
def _csh_candidates():
    found = shutil.which("merge_unwrap_geocode_tops.csh")
    cands = [Path(found)] if found else []
    gmtsar = os.environ.get("GMTSAR", "")
    if gmtsar:
        cands.append(Path(gmtsar) / "bin" / "merge_unwrap_geocode_tops.csh")
    return cands

_CSH_BIN_CANDIDATES = _csh_candidates()


def _find_csh() -> Path | None:
    for cand in _CSH_BIN_CANDIDATES:
        if cand.exists() and os.access(cand, os.X_OK):
            return cand
    return None


def _load_module():
    """Load the Python port as a module (it has no .py extension)."""
    loader = importlib.machinery.SourceFileLoader(
        "merge_unwrap_geocode_tops_mod", str(_PY_UTIL))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    # The port imports `from gmtsar_lib import ...` and `from snaphu import ...`
    # — needs utils/ on sys.path.
    if str(_PY_UTILS_DIR) not in sys.path:
        sys.path.insert(0, str(_PY_UTILS_DIR))
    spec.loader.exec_module(mod)
    return mod


# ----------------------------------------------------------------------------
# Layer 1 — env-gating sanity
# ----------------------------------------------------------------------------
class TestMergeUnwrapGeocodeTopsEnvGate(unittest.TestCase):
    """GMTSAR_MERGE_TOPS_PY={unset,1,0} dispatch verification."""

    @classmethod
    def setUpClass(cls):
        if not _PY_UTIL.exists():
            raise unittest.SkipTest(f"Python port not found at {_PY_UTIL}")

    def _run_usage(self, env_value: str | None) -> str:
        env = os.environ.copy()
        csh_bin = _find_csh()
        bin_dir = str(csh_bin.parent) if csh_bin else ""
        env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
        if env_value is None:
            env.pop("GMTSAR_MERGE_TOPS_PY", None)
        else:
            env["GMTSAR_MERGE_TOPS_PY"] = env_value
        # No-arg invocation → Usage banner. Both paths print a banner.
        proc = subprocess.run(
            [str(_PY_UTIL)],
            env=env,
            capture_output=True,
            text=True,
            cwd="/tmp",
        )
        return (proc.stdout + proc.stderr).lower()

    def test_default_is_python(self):
        """Unset GMTSAR_MERGE_TOPS_PY → Python path.

        Python banner: "Usage: merge_unwrap_geocode_tops inputfile ..."
        csh banner:    "Usage: merge_unwrap_geocode_tops.csh inputfile ..."
        """
        out = self._run_usage(None)
        self.assertIn("usage: merge_unwrap_geocode_tops inputfile", out)
        self.assertNotIn("usage: merge_unwrap_geocode_tops.csh", out)

    def test_py_one_is_python(self):
        """GMTSAR_MERGE_TOPS_PY=1 → Python path."""
        out = self._run_usage("1")
        self.assertIn("usage: merge_unwrap_geocode_tops inputfile", out)
        self.assertNotIn("usage: merge_unwrap_geocode_tops.csh", out)

    def test_py_zero_is_csh(self):
        """GMTSAR_MERGE_TOPS_PY=0 → exec the csh fallback."""
        if _find_csh() is None:
            self.skipTest("merge_unwrap_geocode_tops.csh not on PATH")
        out = self._run_usage("0")
        self.assertIn("usage: merge_unwrap_geocode_tops.csh", out,
                      "GMTSAR_MERGE_TOPS_PY=0 should exec the csh")


# ----------------------------------------------------------------------------
# Layer 2 — awk-truncation arithmetic parity
# ----------------------------------------------------------------------------
class TestAwkIntParity(unittest.TestCase):
    """`_awk_int(x)` must match awk's `printf("%d", x)` — truncate toward 0.

    The csh has `awk '{printf("%d", ($3-$1-$2)/2+$2)}'` patterns at
    lines 84, 112, 124, 130, 142 of merge_unwrap_geocode_tops.csh.
    Python's `int()` of a float truncates toward zero (good); Python's
    `//` floors toward -inf (bad for negative operands). The helper
    exists to make that choice explicit and parity-correct.
    """

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_module()

    def test_positive_truncate(self):
        # awk: printf("%d", 7.7) -> 7
        self.assertEqual(self.mod._awk_int(7.7), 7)
        self.assertEqual(self.mod._awk_int(7.0), 7)
        self.assertEqual(self.mod._awk_int(0.999), 0)

    def test_negative_truncate_toward_zero(self):
        # awk: printf("%d", -3.7) -> -3 (NOT -4 as Python's `//` gives)
        self.assertEqual(self.mod._awk_int(-3.7), -3)
        self.assertEqual(self.mod._awk_int(-0.5), 0)
        # Sanity: floor would give -4 / -1 here; we explicitly do NOT use //.
        self.assertNotEqual(self.mod._awk_int(-3.7), -3.7 // 1)

    def test_pixel_offset_typical(self):
        """Sanity-check the n1 formula from the 2-swath stitch path.

        csh: n1 = printf("%d", ($3-$1-$2)/2+$2) with ($1,$2,$3)=(n12,n21,ovl12).
        With typical values (n12=900, n21=100, ovl12=2000): (2000-900-100)/2+100 = 600.
        """
        n12, n21, ovl12 = 900, 100, 2000
        n1 = self.mod._awk_int((ovl12 - n12 - n21) / 2.0 + n21)
        self.assertEqual(n1, 600)

    def test_pixel_offset_odd_numerator(self):
        """When the numerator is odd, awk truncates the .5 portion.

        ($3-$1-$2)/2+$2 with ($1,$2,$3)=(101, 50, 200): (200-101-50)/2+50 = 24.5+50 = 74.5
        awk %d → 74. Python `(49)//2 + 50` = 24+50 = 74 (matches here);
        but `_awk_int(74.5) == 74` is the spec-correct interpretation.
        """
        n1 = self.mod._awk_int((200 - 101 - 50) / 2.0 + 50)
        self.assertEqual(n1, 74)


# ----------------------------------------------------------------------------
# Layer 3 — snaphu wrapper import (Mira #43 wire-in)
# ----------------------------------------------------------------------------
class TestSnaphuWrapperImport(unittest.TestCase):
    """The port must import `snaphu_unwrap` / `snaphu_interp_unwrap`.

    Regression guard for the previous defect at line 229: the port used
    to call `run(f"snaphu {threshold} {defomax} {interp} {region}")`,
    which on PATH resolved to the C unwrapper binary (snaphu/src/snaphu)
    — NOT the Python wrapper. The C binary doesn't accept those 4 args;
    the call would silently mis-invoke. No TOPS test case caught it
    because every S1A_SLC_TOPS_* config has threshold_snaphu=0.
    """

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_module()

    def test_snaphu_unwrap_imported(self):
        self.assertTrue(hasattr(self.mod, "snaphu_unwrap"))
        self.assertTrue(callable(self.mod.snaphu_unwrap))

    def test_snaphu_interp_unwrap_imported(self):
        self.assertTrue(hasattr(self.mod, "snaphu_interp_unwrap"))
        self.assertTrue(callable(self.mod.snaphu_interp_unwrap))

    def test_no_bare_snaphu_shellout(self):
        """The source must not call `snaphu ...` via run() — that's the bug.

        We grep the source. Caveat: `from snaphu import ...` is fine
        (Python import); only a run()/subprocess shell-out to bare
        `snaphu` would re-introduce the C-binary defect.
        """
        src = _PY_UTIL.read_text()
        # Forbidden: any run("snaphu ...") or run(f"snaphu ...") call.
        forbidden = [
            'run("snaphu ',
            "run('snaphu ",
            'run(f"snaphu ',
            "run(f'snaphu ",
        ]
        for pat in forbidden:
            self.assertNotIn(pat, src,
                f"merge_unwrap_geocode_tops source must not contain {pat!r} "
                f"— bare `snaphu` on PATH is the C unwrapper, not the "
                f"Python wrapper. Use snaphu_unwrap()/snaphu_interp_unwrap() "
                f"from utils/snaphu instead (Mira #43).")


if __name__ == "__main__":
    unittest.main()
