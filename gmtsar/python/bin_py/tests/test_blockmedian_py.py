#!/usr/bin/env python3
"""test_blockmedian_py — parity tests for the bin_py/blockmedian_py CLI
wrapper against the real `gmt blockmedian` binary.

The wrapper delegates all numerical work to
`utils/gmt_blockmedian_py.blockmedian` (Mira #53, 2026-05-22). These
tests exercise the CLI surface end-to-end:
  1. Build a synthetic xyz binary input.
  2. Run the wrapper CLI: `blockmedian_py in.bin -R... -I... -bi3d -bo3d -r -G out.bin`.
  3. Run `gmt blockmedian` on the same input bytes.
  4. Byte-diff the two output binaries.

Per /home/utig5/dliu/CLAUDE.md memory: "bin_py tests need C-parity, not
self-consistency". When the `gmt` binary is unavailable these tests
**skip loudly** — they do NOT silently pass.
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


# Locate gmt — prefer the conda env on this host.
_GMT_CANDIDATES = [
    "/home/staff/dliu/anaconda3/envs/gmtsar/bin/gmt",
    shutil.which("gmt") or "",
]
GMT = next((g for g in _GMT_CANDIDATES if g and os.path.exists(g)), "")

# Locate the wrapper CLI.
_HERE = Path(__file__).resolve().parent
_WRAPPER = _HERE.parent / "blockmedian_py"
assert _WRAPPER.exists(), f"wrapper not found: {_WRAPPER}"


def _run_gmt_blockmedian(in_bin: Path, region, inc, out_bin: Path) -> None:
    """Run `gmt blockmedian -bi3d -bo3d -r` and write its bytes to out_bin."""
    if not GMT:
        raise RuntimeError("gmt binary not found")
    cmd = [
        GMT, "blockmedian", str(in_bin),
        f"-R{region[0]}/{region[1]}/{region[2]}/{region[3]}",
        f"-I{inc[0]}/{inc[1]}",
        "-bi3d", "-bo3d", "-r",
    ]
    with open(out_bin, "wb") as fout:
        res = subprocess.run(cmd, stdout=fout, stderr=subprocess.PIPE,
                             check=False)
    if res.returncode != 0:
        raise RuntimeError(
            f"gmt blockmedian failed (rc={res.returncode}): "
            f"{res.stderr.decode(errors='replace')}")


def _run_wrapper(in_bin: Path, region, inc, out_bin: Path,
                 input_mode: str = "-bi3d") -> None:
    """Run the blockmedian_py CLI wrapper with -G out_bin."""
    cmd = [
        sys.executable, str(_WRAPPER), str(in_bin),
        f"-R{region[0]}/{region[1]}/{region[2]}/{region[3]}",
        f"-I{inc[0]}/{inc[1]}",
        input_mode, "-bo3d", "-r",
        "-G", str(out_bin),
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, check=False)
    if res.returncode != 0:
        raise RuntimeError(
            f"blockmedian_py wrapper failed (rc={res.returncode}): "
            f"{res.stderr.decode(errors='replace')}")


def _assert_byte_identical(self, py_path: Path, gmt_path: Path) -> None:
    py_raw = np.fromfile(py_path, dtype=np.float64)
    gmt_raw = np.fromfile(gmt_path, dtype=np.float64)
    self.assertEqual(
        py_raw.size, gmt_raw.size,
        f"size mismatch: wrapper {py_raw.size} doubles, gmt {gmt_raw.size}")
    self.assertTrue(
        np.array_equal(py_raw, gmt_raw),
        msg=("wrapper bytes diverge from gmt; "
             f"max diff = {np.abs(py_raw - gmt_raw).max() if py_raw.size else 0}"))


@unittest.skipUnless(GMT, "gmt binary not found on this host (parity gate)")
class TestWrapperParityBi3d(unittest.TestCase):
    """CLI wrapper -bi3d input must byte-match `gmt blockmedian`."""

    def test_random_uniform_1000(self):
        rng = np.random.default_rng(13)
        N = 1000
        xyz = np.column_stack([
            rng.uniform(0, 10, N),
            rng.uniform(0, 10, N),
            rng.standard_normal(N) * 5,
        ])
        region = (0.0, 10.0, 0.0, 10.0)
        inc = (1.0, 1.0)
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            in_bin = tdp / "in.bin"
            np.ascontiguousarray(xyz, dtype=np.float64).tofile(in_bin)
            py_out = tdp / "py_out.bin"
            gmt_out = tdp / "gmt_out.bin"
            _run_wrapper(in_bin, region, inc, py_out, "-bi3d")
            _run_gmt_blockmedian(in_bin, region, inc, gmt_out)
            _assert_byte_identical(self, py_out, gmt_out)

    def test_region_inc_auto_adjust(self):
        """Region not a clean multiple of inc → GMT auto-adjusts inc."""
        rng = np.random.default_rng(101)
        N = 20_000
        region = (-10.0, 11314.0, -20.0, 27668.0)
        inc = (8.0, 8.0)
        xyz = np.column_stack([
            rng.uniform(region[0], region[1], N),
            rng.uniform(region[2], region[3], N),
            rng.standard_normal(N),
        ])
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            in_bin = tdp / "in.bin"
            np.ascontiguousarray(xyz, dtype=np.float64).tofile(in_bin)
            py_out = tdp / "py_out.bin"
            gmt_out = tdp / "gmt_out.bin"
            _run_wrapper(in_bin, region, inc, py_out, "-bi3d")
            _run_gmt_blockmedian(in_bin, region, inc, gmt_out)
            _assert_byte_identical(self, py_out, gmt_out)


@unittest.skipUnless(GMT, "gmt binary not found on this host (parity gate)")
class TestWrapperParityBi5d(unittest.TestCase):
    """-bi5d mode (5-double rows, keep cols 0..2) — the dem2topo_ra path."""

    def test_5col_trans_dat_shape(self):
        rng = np.random.default_rng(42)
        N = 5000
        # Simulate trans.dat layout: 5 doubles per row (lon, lat, h, r, a)
        # We blockmedian on cols 0..2.
        cols = [
            rng.uniform(0, 100, N),     # x  (col 0)
            rng.uniform(0, 100, N),     # y  (col 1)
            rng.standard_normal(N),     # z  (col 2)
            rng.uniform(0, 1, N),       # extra col 3
            rng.uniform(0, 1, N),       # extra col 4
        ]
        five_col = np.column_stack(cols)
        three_col = np.ascontiguousarray(five_col[:, :3])
        region = (0.0, 100.0, 0.0, 100.0)
        inc = (5.0, 5.0)
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            in_5col = tdp / "in5.bin"
            in_3col = tdp / "in3.bin"
            np.ascontiguousarray(five_col, dtype=np.float64).tofile(in_5col)
            three_col.astype(np.float64, copy=False).tofile(in_3col)
            py_out = tdp / "py_out.bin"
            gmt_out = tdp / "gmt_out.bin"
            # wrapper reads 5-double and slices cols 0..2 internally
            _run_wrapper(in_5col, region, inc, py_out, "-bi5d")
            # gmt reads the 3-double equivalent
            _run_gmt_blockmedian(in_3col, region, inc, gmt_out)
            _assert_byte_identical(self, py_out, gmt_out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
