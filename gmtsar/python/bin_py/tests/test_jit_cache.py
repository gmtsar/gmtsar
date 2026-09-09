#!/usr/bin/env python3
"""test_jit_cache — verify Numba disk cache works for the resamp/SAT JIT kernels.

Why this test exists
--------------------
Prior to 2026-05-21 the JIT kernels for `resamp_py` lived inside the
closure `_build_numba_kernels()` (a nested-function definition) and the
JIT kernels for `SAT_llt2rat_py` had `cache=False`. Result: every
fresh process re-compiled the kernels (~5-8 s of JIT cost), which the
21-case strict-single-thread sweep paid 21 times — a pure-overhead
budget of 100-200 s.

The fix lifted the JITs into proper top-level .py modules
(`bin_py/_jit_kernels_resamp.py`, `bin_py/_jit_kernels_sat.py`) and
enabled `cache=True`. Numba writes IR sidecars into `__pycache__/`
keyed off the module's stable `__name__`. Subsequent invocations of
the binary in any context (script, subprocess, importlib loader) read
the cached IR and skip compilation.

This test guards against a regression where:
  - someone refactors the kernels back into a closure / inner-fn
  - someone sets `cache=False` (debugging) and forgets to revert
  - the module __name__ becomes unstable for some other reason

For each kernel module:
  1. Wipe `__pycache__/<module>*.nb{i,c}`.
  2. Spawn a fresh `python3 -c "import _jit_kernels_X; <call kernel>"`
     subprocess → time it (cold). Verify cache files appear.
  3. Spawn another fresh subprocess → time it (warm). Verify it's at
     least 1.5x faster than cold AND that the cache files were NOT
     rewritten (mtime unchanged → confirms cache HIT, not a silent
     compile-on-mismatch).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path


_HERE = Path(__file__).resolve().parent
_BIN_PY = _HERE.parent
_PYCACHE = _BIN_PY / "__pycache__"

# Probe scripts. Each one imports the kernel module and calls every kernel
# once with a tiny synthetic input — enough to force-load the IR (either
# from cache or by JIT-compiling). We DON'T import the parent binary
# (resamp_py / SAT_llt2rat_py) because that pulls in tens of MB of
# numpy/scipy/xarray import overhead that swamps the JIT-vs-cache signal.

_PROBE_RESAMP = r"""
import os, sys, time
sys.path.insert(0, __BIN_PY__)
import numpy as np
t0 = time.perf_counter()
import _jit_kernels_resamp as jk
t1 = time.perf_counter()
# Call each kernel once with a tiny input to force IR resolution.
ras0 = np.array([1.5, 2.5, 3.5, 4.5], dtype=np.float64)
ras1 = np.array([1.5, 2.5, 3.5, 4.5], dtype=np.float64)
ydims, xdims = 8, 8
sin_flat = (np.arange(2 * xdims * ydims, dtype=np.int32) % 100).astype(np.int16)
sout = np.zeros(8, dtype=np.int16)
jk._knearest(ras0, ras1, sin_flat, ydims, xdims, sout)
jk._kbilinear(ras0, ras1, sin_flat, ydims, xdims, sout)
jk._kbicubic(ras0, ras1, sin_flat, ydims, xdims, sout)
jk._kbisinc(ras0, ras1, sin_flat, ydims, xdims, sout)
t2 = time.perf_counter()
print("IMPORT_S=" + repr(t1 - t0))
print("ALL_KERNELS_S=" + repr(t2 - t1))
print("TOTAL_S=" + repr(t2 - t0))
"""

_PROBE_SAT = r"""
import os, sys, time
sys.path.insert(0, __BIN_PY__)
import numpy as np
t0 = time.perf_counter()
import _jit_kernels_sat as jk
t1 = time.perf_counter()
# hermite_c_1d_uniform
HJ = np.zeros((6, 6), dtype=np.float64); HJ[0, 0] = 1.0
S_VALS = np.zeros(6, dtype=np.float64); S_VALS[0] = 0.5
x = np.linspace(0.0, 10.0, 20)
y = np.sin(x); z = np.cos(x)
xp = np.array([2.5, 5.0], dtype=np.float64)
yp_out = np.empty(2, dtype=np.float64)
jk._hermite_c_1d_uniform_jit(0.0, 0.5, y, z, xp, 6, HJ, S_VALS, yp_out)
# hermite_c_1d
jk._hermite_c_1d_jit(x, y, z, xp, 6, yp_out)
# goldop
op_t = np.linspace(0.0, 100.0, 50)
px = np.linspace(0.0, 1000.0, 50)
py = np.linspace(0.0, 1000.0, 50)
pz = np.linspace(0.0, 1000.0, 50)
tx = np.array([500.0]); ty = np.array([500.0]); tz = np.array([500.0])
R_out = np.empty(1, dtype=np.float64); T_out = np.empty(1, dtype=np.float64)
jk._goldop_jit(op_t, px, py, pz, tx, ty, tz, R_out, T_out)
t2 = time.perf_counter()
print("IMPORT_S=" + repr(t1 - t0))
print("ALL_KERNELS_S=" + repr(t2 - t1))
print("TOTAL_S=" + repr(t2 - t0))
"""


def _wipe_cache_for(module_name: str) -> int:
    """Delete every Numba cache artefact under __pycache__ that belongs
    to `module_name` (e.g. "_jit_kernels_resamp"). Returns the count
    deleted. The .pyc files are left intact.
    """
    if not _PYCACHE.exists():
        return 0
    n = 0
    for p in _PYCACHE.iterdir():
        if not p.is_file():
            continue
        if not p.name.startswith(module_name + "."):
            continue
        if p.suffix.endswith(".nbi") or p.suffix.endswith(".nbc") \
                or ".py3" in p.name and (".nbi" in p.name or ".nbc" in p.name):
            p.unlink()
            n += 1
    return n


def _cache_files_for(module_name: str) -> list[Path]:
    if not _PYCACHE.exists():
        return []
    return sorted(p for p in _PYCACHE.iterdir()
                  if p.is_file() and p.name.startswith(module_name + ".")
                  and (".nbi" in p.name or ".nbc" in p.name))


def _run_probe(script: str) -> tuple[float, dict[str, float]]:
    """Run the probe script in a fresh interpreter; return (wall_seconds,
    parsed metrics).
    """
    src = script.replace("__BIN_PY__", repr(str(_BIN_PY)))
    t0 = time.perf_counter()
    r = subprocess.run(
        [sys.executable, "-c", src],
        capture_output=True, text=True, timeout=120,
    )
    wall = time.perf_counter() - t0
    if r.returncode != 0:
        raise RuntimeError(
            f"probe failed rc={r.returncode}\nSTDOUT:\n{r.stdout}\n"
            f"STDERR:\n{r.stderr}"
        )
    metrics = {}
    for line in r.stdout.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            try:
                metrics[k.strip()] = float(v)
            except ValueError:
                pass
    return wall, metrics


class _CacheMechanismTestMixin:
    """Common assertions for both modules. Subclasses set:
      MODULE   — name of the kernel module
      PROBE    — the python script to spawn (string, %(bin_py)s substitution)
      MIN_KERNELS — minimum number of cache files (.nbi + .nbc pairs) expected
                    after a cold run.
      MIN_SPEEDUP — minimum ALL_KERNELS speedup factor (warm vs cold) we
                    require to declare the cache "hit". Set conservatively
                    so the test is not flaky on busy CI hosts.
    """

    MODULE: str = ""
    PROBE: str = ""
    MIN_KERNELS: int = 0
    MIN_SPEEDUP: float = 2.0

    def test_cold_then_warm_uses_disk_cache(self):
        """Cold run writes IR; warm run loads from disk and is faster."""
        try:
            import numba  # noqa: F401
        except ImportError:
            self.skipTest("numba not installed")

        # 1. Wipe any prior cache.
        _wipe_cache_for(self.MODULE)
        self.assertEqual(_cache_files_for(self.MODULE), [],
                         msg="cache files unexpectedly remained after wipe")

        # 2. Cold run.
        _, cold_metrics = _run_probe(self.PROBE)
        cold_files = _cache_files_for(self.MODULE)
        self.assertGreaterEqual(
            len(cold_files), self.MIN_KERNELS,
            msg=f"expected >= {self.MIN_KERNELS} cache files after cold "
                f"run, got {len(cold_files)}: {[p.name for p in cold_files]}",
        )

        # Snapshot mtimes — they must NOT change on the warm run, else
        # numba silently re-compiled (cache miss disguised as a hit).
        cold_mtimes = {p.name: p.stat().st_mtime_ns for p in cold_files}

        # 3. Warm run.
        _, warm_metrics = _run_probe(self.PROBE)
        warm_files = _cache_files_for(self.MODULE)
        self.assertEqual(
            sorted(p.name for p in warm_files),
            sorted(cold_files_names := [p.name for p in cold_files]),
            msg="cache file SET changed between runs (new files appeared "
                "or some disappeared)",
        )
        for p in warm_files:
            self.assertEqual(
                p.stat().st_mtime_ns, cold_mtimes[p.name],
                msg=f"cache file {p.name} mtime changed — numba silently "
                    "re-compiled (cache miss). Check that the module has "
                    "stable __name__ and that cache=True is set on every "
                    "@njit.",
            )

        # 4. Warm should be substantially faster than cold on the
        #    kernel-execution segment. We compare ALL_KERNELS_S not
        #    TOTAL_S so that interpreter+numpy import jitter (which
        #    dominates total time at this small workload) doesn't mask
        #    the JIT delta.
        cold_k = cold_metrics["ALL_KERNELS_S"]
        warm_k = warm_metrics["ALL_KERNELS_S"]
        self.assertGreater(
            cold_k / max(warm_k, 1e-9), self.MIN_SPEEDUP,
            msg=f"warm run ALL_KERNELS={warm_k:.3f}s vs cold={cold_k:.3f}s "
                f"— speedup {cold_k/max(warm_k,1e-9):.2f}x is below "
                f"required {self.MIN_SPEEDUP}x. The cache may not be "
                "working; check __pycache__ for .nbc/.nbi files.",
        )


class TestJitCacheResamp(_CacheMechanismTestMixin, unittest.TestCase):
    MODULE = "_jit_kernels_resamp"
    PROBE = _PROBE_RESAMP
    # 4 kernels exercised (1-4), each emits 1 .nbi + 1 .nbc = 8 files.
    # Mode 5 (_kbisinc_grid) is not exercised here — its signature is
    # complex enough that we'd need real inputs.
    MIN_KERNELS = 8
    # On a busy NFS host the cold compile is ~1.5-2 s for the 4 kernels
    # and warm is ~0.05 s — speedup easily 20x. Set the floor low enough
    # that we don't flake.
    MIN_SPEEDUP = 2.0


class TestJitCacheSat(_CacheMechanismTestMixin, unittest.TestCase):
    MODULE = "_jit_kernels_sat"
    PROBE = _PROBE_SAT
    # 3 kernels × (1 .nbi + 1 .nbc) = 6 files.
    MIN_KERNELS = 6
    MIN_SPEEDUP = 2.0


if __name__ == "__main__":
    unittest.main(verbosity=2)
