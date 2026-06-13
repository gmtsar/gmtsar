#!/usr/bin/env python3
"""test_m2s_py — C-parity test for utils/m2s_py.m2s_py vs gmtsar/csh/m2s.csh.

Runs the real ``m2s.csh`` (via ``csh -f <path> pix llp``, requires
``csh`` + ``gmt`` on PATH) and ``m2s_py`` on the SAME input llp file
bytes, and asserts the two output STRING tokens (fine_inc, crude_inc)
are EXACTLY equal — not "close". These strings become ``-I`` arguments
to ``gmt surface`` / ``gmt blockmedian`` / ``gmt xyz2grd`` downstream
(proj_ra2ll_lib.py), so any formatting drift ("2" vs "2.0", "0.5" vs
"5e-1") breaks those calls.

Real-data llp construction
---------------------------
``llp`` is a binary float32 (lon, lat, phase) triplet file. We build a
REAL one from the RS2_SLC_Hawaii raln.grd/ralt.grd (lon/lat lookup
grids already on disk under work/csh_test/, READ-ONLY per Rule 9) via
``gmt grd2xyz -Z``, paired with a synthetic phase column (phase plays
no role in m2s.csh — only lon/lat ranges matter, and only lat is used).

Skips loudly (does NOT silently pass) if ``gmt`` or ``csh`` is not on
PATH, or if the real RS2_SLC_Hawaii raln/ralt grids are unavailable.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
_UTILS = _HERE.parent.parent / "utils"          # gmtsar/python/utils/
sys.path.insert(0, str(_UTILS))

from m2s_py import m2s_py  # noqa: E402

_M2S_CSH = (Path(__file__).resolve().parents[3] / "csh" / "m2s.csh")

_GMT = shutil.which("gmt")
if _GMT is None:
    _alt = "/home/staff/dliu/anaconda3/envs/gmtsar/bin/gmt"
    if os.path.exists(_alt):
        _GMT = _alt
_HAVE_GMT = _GMT is not None and os.access(_GMT, os.X_OK)

_CSH = shutil.which("csh")
_HAVE_CSH = _CSH is not None

_RALN = (Path("/home/staff/dliu/gmtsar/gmtsar/python/work/csh_test/"
              "RS2_SLC_Hawaii/intf/2011134_2011230/raln.grd"))
_RALT = (Path("/home/staff/dliu/gmtsar/gmtsar/python/work/csh_test/"
              "RS2_SLC_Hawaii/intf/2011134_2011230/ralt.grd"))
_HAVE_REAL_GRIDS = _RALN.exists() and _RALT.exists()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_m2s_csh(pix, llp_path: str) -> tuple[str, str]:
    """Invoke the real m2s.csh via `csh -f <path> pix llp`.

    Raises (does not silently pass) if csh/gmt are missing or the
    script fails.
    """
    if not _HAVE_CSH:
        raise RuntimeError("csh not on PATH — cannot run m2s.csh")
    if not _HAVE_GMT:
        raise RuntimeError("gmt not on PATH — cannot run m2s.csh")
    if not _M2S_CSH.exists():
        raise RuntimeError(f"m2s.csh not found at {_M2S_CSH}")

    env = dict(os.environ)
    gmt_dir = os.path.dirname(_GMT)
    env["PATH"] = gmt_dir + os.pathsep + env.get("PATH", "")

    res = subprocess.run(
        ["csh", "-f", str(_M2S_CSH), str(pix), llp_path],
        capture_output=True, text=True, check=False, env=env,
    )
    if res.returncode != 0:
        raise RuntimeError(
            f"m2s.csh failed (rc={res.returncode})\n"
            f"  stdout: {res.stdout!r}\n  stderr: {res.stderr!r}"
        )
    tokens = res.stdout.strip().split()
    if len(tokens) != 2:
        raise RuntimeError(
            f"m2s.csh produced unexpected output: {res.stdout!r}"
        )
    return tokens[0], tokens[1]


def _build_real_llp(tmp_path: Path) -> Path:
    """Build a real-data llp (lon, lat, phase float32 triplets) from
    the RS2_SLC_Hawaii raln/ralt lookup grids via `gmt grd2xyz -Z`.
    """
    lon_xyz = subprocess.run(
        [_GMT, "grd2xyz", str(_RALN), "-Z"],
        capture_output=True, text=True, check=True,
    ).stdout
    lat_xyz = subprocess.run(
        [_GMT, "grd2xyz", str(_RALT), "-Z"],
        capture_output=True, text=True, check=True,
    ).stdout
    lon = np.array(lon_xyz.split(), dtype=np.float32)
    lat = np.array(lat_xyz.split(), dtype=np.float32)
    assert lon.size == lat.size and lon.size > 0
    rng = np.random.RandomState(7)
    phase = rng.uniform(-3.14, 3.14, lon.size).astype(np.float32)
    arr = np.empty((lon.size, 3), dtype=np.float32)
    arr[:, 0] = lon
    arr[:, 1] = lat
    arr[:, 2] = phase
    llp = tmp_path / "llp"
    arr.tofile(llp)
    return llp


# ---------------------------------------------------------------------------
# C-parity test
# ---------------------------------------------------------------------------

@unittest.skipUnless(_HAVE_GMT, "gmt not on PATH — cannot run m2s.csh oracle")
@unittest.skipUnless(_HAVE_CSH, "csh not on PATH — cannot run m2s.csh oracle")
@unittest.skipUnless(_HAVE_REAL_GRIDS,
                      f"real RS2_SLC_Hawaii raln/ralt grids not found "
                      f"under {_RALN.parent}")
class TestM2sPyVsCsh(unittest.TestCase):
    """m2s_py(pix, llp) must produce EXACTLY the same (fine_inc,
    crude_inc) strings as `csh -f m2s.csh pix llp` on the SAME llp
    file bytes."""

    @classmethod
    def setUpClass(cls):
        import tempfile
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls.llp = _build_real_llp(Path(cls._tmpdir.name))

    @classmethod
    def tearDownClass(cls):
        cls._tmpdir.cleanup()

    def _check(self, pix):
        c_fine, c_crude = _run_m2s_csh(pix, str(self.llp))
        py_fine, py_crude = m2s_py(pix, str(self.llp))
        self.assertEqual(
            (py_fine, py_crude), (c_fine, c_crude),
            f"pix={pix}: csh m2s.csh -> ({c_fine!r}, {c_crude!r}) "
            f"but m2s_py -> ({py_fine!r}, {py_crude!r})"
        )
        return c_fine, c_crude

    def test_pix_60_default_filter(self):
        """Default filter wavelength 60m / 4 = 15... but also test 60
        directly (proj_ra2ll_lib's no-filter fallback pix_m=60)."""
        fine, crude = self._check(60)
        # Sanity: not empty, has the s/.../s pattern.
        self.assertRegex(fine, r"^[0-9.]+s/[0-9.]+s$")
        self.assertRegex(crude, r"^[0-9.]+s/[0-9.]+s$")

    def test_pix_15_quarter_of_60(self):
        """filter_wavelength=60 -> pix_m = 60/4 = 15."""
        self._check(15)

    def test_pix_7_5(self):
        """filter_wavelength=30 -> pix_m = 30/4 = 7.5 (sub-arcsec dx/dy)."""
        self._check(7.5)

    def test_pix_100_asymmetric(self):
        """pix=100 produces dx != dy (asymmetric inc) — exercises the
        cosd(mlat) longitude-stretch branch distinctly from latitude."""
        fine, crude = self._check(100)
        dx_s, dy_s = fine.split("/")
        self.assertNotEqual(dx_s, dy_s,
                             "pix=100 expected dx != dy at this latitude")

    def test_pix_1_minimum_clamp(self):
        """Very small pix forces the MAX(1, RINT(...)) clamp to 1,
        i.e. dx=dy=0.5s (the minimum 1 arcsec / 2)."""
        fine, crude = self._check(1)
        self.assertEqual(fine, "0.5s/0.5s")
        self.assertEqual(crude, "5s/5s")

    def test_pix_0_01_minimum_clamp(self):
        """Pathologically small pix — still clamps to the minimum."""
        fine, crude = self._check(0.01)
        self.assertEqual(fine, "0.5s/0.5s")
        self.assertEqual(crude, "5s/5s")


# ---------------------------------------------------------------------------
# Error-handling (Py-only, no C side)
# ---------------------------------------------------------------------------

class TestM2sPyErrorHandling(unittest.TestCase):
    """m2s_py raises on malformed input — no silent fallback."""

    def test_empty_llp_raises(self, tmp_path=None):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            llp = Path(d) / "llp_empty"
            llp.write_bytes(b"")
            with self.assertRaises(ValueError):
                m2s_py(60.0, str(llp))

    def test_non_multiple_of_3_raises(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            llp = Path(d) / "llp_bad"
            # 4 float32s -> not a multiple of 3
            np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float32).tofile(llp)
            with self.assertRaises(ValueError):
                m2s_py(60.0, str(llp))

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            m2s_py(60.0, "/nonexistent/path/to/llp")


if __name__ == "__main__":
    unittest.main()
