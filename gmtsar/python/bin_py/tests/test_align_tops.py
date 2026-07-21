#!/usr/bin/env python3
"""test_align_tops — env-gating sanity + (optional) csh-vs-py parity test.

Two layers:
  1. TestAlignTopsEnvGate — verifies GMTSAR_ALIGN_TOPS_PY=0 dispatches to
     align_tops.csh and =1 (or unset) dispatches to the Python port.
     Cheap: only checks the usage banners, no heavy SAR run required.
  2. TestAlignTopsCshParity — heavy end-to-end parity. Stages the
     S1A_SLC_TOPS_Greece F2 subswath, runs csh align_tops.csh and Python
     align_tops back-to-back into separate dirs, then diffs r.grd, a.grd,
     offset.dat, and key PRM fields. Skips loudly if real inputs absent.

Per Mira's discipline: env-gated wire-ins need a smoke that exercises BOTH
paths. The cheap layer-1 test runs in CI; the layer-2 test runs on demand
(20+ min wall time on the Greece subswath).
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


# Resolve paths from THIS file's location so worktrees and main checkouts
# both Just Work. test file lives at <pyroot>/bin_py/tests/test_align_tops.py
# and the port lives at <pyroot>/utils/align_tops.
_PY_TREE = Path(__file__).resolve().parents[2]  # .../gmtsar/python
_PY_UTIL = _PY_TREE / "utils" / "align_tops"
def _find_csh_align_tops_in_path() -> Path | None:
    found = shutil.which("align_tops.csh")
    if found:
        return Path(found)
    # Also probe $GMTSAR/bin directly (the env is set by sweep.sh).
    gmtsar = os.environ.get("GMTSAR")
    if gmtsar:
        cand = Path(gmtsar) / "bin" / "align_tops.csh"
        if cand.exists() and os.access(cand, os.X_OK):
            return cand
    return None

_CSH_BIN_CANDIDATES = [p for p in [_find_csh_align_tops_in_path()] if p]

# Greece F2 raw dir.  Set GMTSAR_GREECE_F2_RAW to override.
# Default: try the local work/csh_test/ then $GMTSAR/gmtsar/python/work/.
def _resolve_greece_dir() -> Path:
    override = os.environ.get("GMTSAR_GREECE_F2_RAW")
    if override:
        return Path(override)
    work_root = Path(
        os.environ.get("GMTSAR_TEST_WORK")
        or (os.environ.get("GMTSAR", "") + "/gmtsar/python/work"
            if os.environ.get("GMTSAR") else "")
        or str(_PY_TREE / "work")
    )
    cand = work_root / "csh_test/S1A_SLC_TOPS_Greece/F2/raw"
    if cand.is_dir():
        return cand
    return cand  # report this path in skip msg

_GREECE_F2_RAW = _resolve_greece_dir()
_TOPS_PREFIXES = (
    "s1a-iw2-slc-vv-20151105t163134-20151105t163159-008472-00bfa6-005",
    "s1a-iw2-slc-vv-20151117t163128-20151117t163154-008647-00c499-005",
)


def _find_csh_align_tops() -> Path | None:
    for cand in _CSH_BIN_CANDIDATES:
        if cand.exists() and os.access(cand, os.X_OK):
            return cand
    return None


def _have_greece_inputs() -> bool:
    """All four TIFFs/XMLs/EOFs + dem.grd present?"""
    if not _GREECE_F2_RAW.is_dir():
        return False
    needed: list[Path] = [_GREECE_F2_RAW / "dem.grd"]
    for pre in _TOPS_PREFIXES:
        needed.append(_GREECE_F2_RAW / f"{pre}.tiff")
        needed.append(_GREECE_F2_RAW / f"{pre}.xml")
        needed.append(_GREECE_F2_RAW / f"{pre}.EOF")
    return all(p.exists() for p in needed)


# ----------------------------------------------------------------------------
# Layer 1 — env-gating sanity (cheap)
# ----------------------------------------------------------------------------
class TestAlignTopsEnvGate(unittest.TestCase):
    """Verify the GMTSAR_ALIGN_TOPS_PY env switch dispatches correctly.

    Both modes hit Usage on no-arg invocation; we distinguish the path by
    the banner text. Python path: "Usage: align_tops master_prefix ...".
    csh path: "Usage: align_tops.csh master_prefix master_orb_file ...".
    """

    @classmethod
    def setUpClass(cls):
        if not _PY_UTIL.exists():
            raise unittest.SkipTest(f"Python align_tops not found at {_PY_UTIL}")

    def _run_usage(self, env_value: str | None) -> str:
        env = os.environ.copy()
        # Ensure align_tops.csh is reachable for the fallback path.
        csh_bin = _find_csh_align_tops()
        bin_dir = str(csh_bin.parent) if csh_bin else ""
        env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
        if env_value is None:
            env.pop("GMTSAR_ALIGN_TOPS_PY", None)
        else:
            env["GMTSAR_ALIGN_TOPS_PY"] = env_value
        # No-arg invocation → Usage banner. Exit code is 1 in both paths,
        # but stderr differs by header.
        proc = subprocess.run(
            [str(_PY_UTIL)],
            env=env,
            capture_output=True,
            text=True,
            cwd="/tmp",
        )
        return (proc.stdout + proc.stderr).lower()

    def test_default_is_python(self):
        """Unset GMTSAR_ALIGN_TOPS_PY → Python path."""
        out = self._run_usage(None)
        self.assertIn("usage: align_tops master_prefix", out,
                      "Default path should hit the Python usage banner")
        self.assertNotIn("usage: align_tops.csh", out)

    def test_py_one_is_python(self):
        """GMTSAR_ALIGN_TOPS_PY=1 → Python path."""
        out = self._run_usage("1")
        self.assertIn("usage: align_tops master_prefix", out)
        self.assertNotIn("usage: align_tops.csh", out)

    def test_py_zero_is_csh(self):
        """GMTSAR_ALIGN_TOPS_PY=0 → exec align_tops.csh."""
        if _find_csh_align_tops() is None:
            self.skipTest("align_tops.csh not on PATH; cannot test csh fallback")
        out = self._run_usage("0")
        self.assertIn("usage: align_tops.csh", out,
                      "GMTSAR_ALIGN_TOPS_PY=0 should exec align_tops.csh")


# ----------------------------------------------------------------------------
# Helpers for layer 2 (heavy parity)
# ----------------------------------------------------------------------------
def _stage_greece_inputs(dst: Path) -> None:
    """Symlink TIFF/XML/EOF/dem.grd from the Greece F2 raw dir into `dst`."""
    dst.mkdir(parents=True, exist_ok=True)
    # dem.grd — symlink at top level (csh expects ./dem.grd)
    (dst / "dem.grd").symlink_to((_GREECE_F2_RAW / "dem.grd").resolve())
    for pre in _TOPS_PREFIXES:
        for ext in ("tiff", "xml", "EOF"):
            src = (_GREECE_F2_RAW / f"{pre}.{ext}").resolve()
            (dst / f"{pre}.{ext}").symlink_to(src)


def _grd_data(path: Path) -> bytes:
    """Return the data section of a netCDF .grd — strips the header so a
    timestamp / history difference doesn't trip parity. Falls back to full
    file bytes if netCDF4 isn't available."""
    try:
        import netCDF4  # type: ignore
        ds = netCDF4.Dataset(str(path), "r")
        try:
            var = ds.variables.get("z") or ds.variables.get("Band1")
            if var is None:
                # Pick the first 2-D numeric variable.
                for v in ds.variables.values():
                    if v.ndim == 2:
                        var = v
                        break
            if var is None:
                return path.read_bytes()
            arr = var[:].filled() if hasattr(var[:], "filled") else var[:]
            return arr.tobytes()
        finally:
            ds.close()
    except Exception:
        return path.read_bytes()


def _file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _prm_dict(path: Path) -> dict[str, str]:
    """Parse a PRM file into {key: value} (last write wins, matching csh's
    grep behavior of taking the last match for re-assigned keys)."""
    out: dict[str, str] = {}
    with open(path) as f:
        for line in f:
            if "=" not in line:
                continue
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


# ----------------------------------------------------------------------------
# Layer 2 — heavy csh-vs-py end-to-end parity
# ----------------------------------------------------------------------------
class TestAlignTopsCshParity(unittest.TestCase):
    """Run csh align_tops.csh and Py align_tops on the SAME staged Greece F2
    inputs; diff r.grd, a.grd, offset.dat, and key PRM fields.

    Skipped unless real TOPS inputs exist under work/csh_test/. The test
    takes ~20 min on a single subswath. Set GMTSAR_RUN_HEAVY_PARITY=1 to
    actually execute (otherwise skip-loud to avoid blowing up CI).
    """

    @classmethod
    def setUpClass(cls):
        if os.environ.get("GMTSAR_RUN_HEAVY_PARITY") != "1":
            raise unittest.SkipTest(
                "Heavy align_tops csh-vs-py parity gated behind "
                "GMTSAR_RUN_HEAVY_PARITY=1. Wall time ~20 min on Greece F2."
            )
        if _find_csh_align_tops() is None:
            raise unittest.SkipTest("align_tops.csh not found on PATH")
        if not _PY_UTIL.exists():
            raise unittest.SkipTest(f"Python align_tops not found at {_PY_UTIL}")
        if not _have_greece_inputs():
            raise unittest.SkipTest(
                f"Greece F2 inputs not staged at {_GREECE_F2_RAW}; "
                "run the S1A_SLC_TOPS_Greece test case once to populate."
            )

    def _run_one_side(self, work: Path, env_extra: dict[str, str]) -> None:
        """Stage inputs into `work`, run align_tops with the given env
        (csh or py), check return code."""
        _stage_greece_inputs(work)
        env = os.environ.copy()
        env.update(env_extra)
        # Ensure align_tops and its dependencies are on PATH.
        # Prepend $GMTSAR/bin if set; the rest comes from the caller's env.
        gmtsar_bin = os.environ.get("GMTSAR", "")
        gmtsar_bin = (gmtsar_bin + "/bin:") if gmtsar_bin else ""
        env["PATH"] = gmtsar_bin + env.get("PATH", "")
        # Invoke the worktree's align_tops by absolute path so the env-gate
        # under test is the one in THIS commit, not the system bin symlink.
        cmd = [
            str(_PY_UTIL),
            _TOPS_PREFIXES[0],
            f"{_TOPS_PREFIXES[0]}.EOF",
            _TOPS_PREFIXES[1],
            f"{_TOPS_PREFIXES[1]}.EOF",
            "dem.grd",
        ]
        proc = subprocess.run(cmd, cwd=work, env=env, capture_output=True,
                              text=True, timeout=1800)
        if proc.returncode != 0:
            self.fail(
                f"align_tops failed in {work} (rc={proc.returncode}):\n"
                f"--- stdout ---\n{proc.stdout}\n"
                f"--- stderr ---\n{proc.stderr}\n"
            )

    def test_parity_greece_f2(self):
        # Use mkdtemp + manual cleanup so a failed run leaves artifacts behind
        # for inspection. The dir is rooted at $TMPDIR / parity_align_tops/.
        tdname = tempfile.mkdtemp(prefix="align_tops_parity_")
        td = Path(tdname)
        self.addCleanup(self._maybe_cleanup, td)
        csh_dir = td / "csh"
        py_dir = td / "py"
        self._run_one_side(csh_dir, {"GMTSAR_ALIGN_TOPS_PY": "0"})
        self._run_one_side(py_dir, {"GMTSAR_ALIGN_TOPS_PY": "1"})

        # Verify both sides actually produced the expected outputs.
        for side, sdir in (("csh", csh_dir), ("py", py_dir)):
            for grd in ("r.grd", "a.grd"):
                self.assertTrue(
                    (sdir / grd).is_file(),
                    f"{side} did not produce {grd} in {sdir}",
                )

        # Compare the alignment grids — the principal scientific output.
        for grd in ("r.grd", "a.grd"):
            c_data = _grd_data(csh_dir / grd)
            p_data = _grd_data(py_dir / grd)
            self.assertEqual(
                hashlib.sha256(c_data).hexdigest(),
                hashlib.sha256(p_data).hexdigest(),
                f"{grd} data section differs csh vs py",
            )

        # offset.dat is plain ASCII — byte-id required.
        self.assertEqual(
            (csh_dir / "offset.dat").read_bytes(),
            (py_dir / "offset.dat").read_bytes(),
            "offset.dat differs csh vs py",
        )

        # PRM scientific fields — compare numerics, not timestamps.
        # The aligned-side PRM is the heavy one (includes ashift,
        # rshift, sub_int_*, stretch_*, a_stretch_*).
        aligned_prm_name = next(
            p.name for p in csh_dir.iterdir()
            if p.name.startswith("S1_") and p.name.endswith(".PRM")
               and "20151117" in p.name
        )
        c_prm = _prm_dict(csh_dir / aligned_prm_name)
        p_prm = _prm_dict(py_dir / aligned_prm_name)
        critical_fields = (
            "ashift", "rshift",
            "sub_int_r", "sub_int_a",
            "stretch_r", "stretch_a",
            "a_stretch_r", "a_stretch_a",
            "num_lines", "num_rng_bins",
            "earth_radius", "PRF",
        )
        for k in critical_fields:
            self.assertEqual(c_prm.get(k), p_prm.get(k),
                             f"PRM field {k} differs: csh={c_prm.get(k)} "
                             f"py={p_prm.get(k)}")

    @staticmethod
    def _maybe_cleanup(td: Path) -> None:
        """Remove the tempdir unless GMTSAR_KEEP_PARITY_DIR=1 is set."""
        if os.environ.get("GMTSAR_KEEP_PARITY_DIR") == "1":
            return
        try:
            shutil.rmtree(td)
        except OSError:
            pass


if __name__ == "__main__":
    unittest.main()
