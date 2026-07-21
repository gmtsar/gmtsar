#!/usr/bin/env python3
"""test_blockmedian_wrapper — C-parity test for utils/blockmedian_wrapper.

The wire-in routes the file-based `gmt blockmedian <in> -R -I -r [-bo3d]`
calls in utils/align_tops (binary -bo3d) and utils/tide_correction (ASCII)
through the in-process gmt_blockmedian_py port. This test verifies, for
each csh call pattern the wire-in replaces, the wrapper's output file is
byte-identical to `gmt blockmedian` on real-shaped scattered data.

Patterns covered:
  1. ASCII in, binary -bo3d out  (align_tops r.xyz/a.xyz → rtmp/atmp.xyz)
  2. ASCII in, ASCII out         (tide_correction topo.rad → tmp.rad)
  3. env-gate fallback: GMTSAR_BLOCKMEDIAN_PY=0 → gmt subprocess, bytes
     identical to gmt called directly.

Skips loudly if `gmt` is not on PATH.
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

_HERE = Path(__file__).resolve().parent
_UTILS = _HERE.parent.parent / "utils"
sys.path.insert(0, str(_UTILS))

import blockmedian_wrapper  # noqa: E402

_GMT = shutil.which("gmt")
_HAVE_GMT = _GMT is not None and os.access(_GMT, os.X_OK)


def _scatter(n, rmax, amax, seed):
    rng = np.random.default_rng(seed)
    x = rng.uniform(0.0, rmax, n)
    y = rng.uniform(0.0, amax, n)
    z = rng.uniform(-2.0, 2.0, n)
    return np.c_[x, y, z]


@unittest.skipUnless(_HAVE_GMT, "gmt binary not on PATH; cannot validate parity")
class TestBlockmedianWireIn(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="blockmedian_wrap_")
        cls.rmax, cls.amax = 20000, 8000
        cls.region = f"0/{cls.rmax}/0/{cls.amax}"
        cls.inc = "16/8"
        xyz = _scatter(6000, cls.rmax, cls.amax, seed=7)
        cls.ascii_in = os.path.join(cls.tmp, "r.xyz")
        np.savetxt(cls.ascii_in, xyz, fmt="%.6f")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _gmt(self, out, extra):
        cmd = [_GMT, "blockmedian", self.ascii_in,
               f"-R{self.region}", f"-I{self.inc}", "-r", *extra]
        with open(out, "wb") as f:
            res = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE,
                                 check=False)
        if res.returncode != 0:
            raise RuntimeError(res.stderr.decode(errors="replace"))

    def test_binary_bo3d(self):
        """align_tops pattern: ASCII in → -bo3d binary out, byte-identical."""
        out_gmt = os.path.join(self.tmp, "g.bin")
        out_py = os.path.join(self.tmp, "p.bin")
        self._gmt(out_gmt, ["-bo3d"])
        os.environ["GMTSAR_BLOCKMEDIAN_PY"] = "1"
        try:
            blockmedian_wrapper.blockmedian(
                self.ascii_in, out_py, region=self.region,
                inc=self.inc, out_binary=3)
        finally:
            os.environ.pop("GMTSAR_BLOCKMEDIAN_PY", None)
        with open(out_gmt, "rb") as f:
            bg = f.read()
        with open(out_py, "rb") as f:
            bp = f.read()
        self.assertEqual(bg, bp, "binary -bo3d output not byte-identical to gmt")

    def test_ascii(self):
        """tide_correction pattern: ASCII in → ASCII out, byte-identical."""
        out_gmt = os.path.join(self.tmp, "g.txt")
        out_py = os.path.join(self.tmp, "p.txt")
        self._gmt(out_gmt, [])
        os.environ["GMTSAR_BLOCKMEDIAN_PY"] = "1"
        try:
            blockmedian_wrapper.blockmedian(
                self.ascii_in, out_py, region=self.region, inc=self.inc)
        finally:
            os.environ.pop("GMTSAR_BLOCKMEDIAN_PY", None)
        with open(out_gmt) as f:
            tg = f.read()
        with open(out_py) as f:
            tp = f.read()
        self.assertEqual(tg, tp, "ASCII output not byte-identical to gmt")

    def test_env_gate_fallback(self):
        """GMTSAR_BLOCKMEDIAN_PY=0 → subprocess, bytes match gmt direct."""
        out_direct = os.path.join(self.tmp, "d.bin")
        out_wrap = os.path.join(self.tmp, "w.bin")
        self._gmt(out_direct, ["-bo3d"])
        old = os.environ.get("GMTSAR_BLOCKMEDIAN_PY")
        os.environ["GMTSAR_BLOCKMEDIAN_PY"] = "0"
        try:
            blockmedian_wrapper.blockmedian(
                self.ascii_in, out_wrap, region=self.region,
                inc=self.inc, out_binary=3)
        finally:
            if old is None:
                os.environ.pop("GMTSAR_BLOCKMEDIAN_PY", None)
            else:
                os.environ["GMTSAR_BLOCKMEDIAN_PY"] = old
        with open(out_direct, "rb") as f:
            bd = f.read()
        with open(out_wrap, "rb") as f:
            bw = f.read()
        self.assertEqual(bd, bw, "env=0 fallback bytes differ from gmt direct")


class TestOracleAvailability(unittest.TestCase):
    def test_gmt_present_else_loud_skip(self):
        if not _HAVE_GMT:
            self.skipTest("gmt not on PATH — LOUD skip, not a silent pass.")


if __name__ == "__main__":
    unittest.main(verbosity=2)
