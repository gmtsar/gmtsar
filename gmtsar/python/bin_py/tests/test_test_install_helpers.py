#!/usr/bin/env python3
"""test_test_install_helpers.py — cheap regression guards for
tests/test_install.py's own helper functions.

test_install.py is itself a testing tool (clean-room install.py
verification), but until now its own logic had only ever been checked
via one-off inline scripts during development -- never persisted as
real, repeatable tests. Every guard here maps to a real bug found in
tests/test_install.py during the 2026-07-14 clean-room investigation
(see tests/test_install.py's own comments for the full incident
writeups). No conda/network/subprocess needed -- pure fixture-based,
runs in milliseconds.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent.parent.parent / "tests"
sys.path.insert(0, str(_TESTS_DIR))

import test_install as ti  # noqa: E402


def _reset_paths(monkeypatch, python_dir=None, repo_root=None):
    if python_dir is not None:
        monkeypatch.setattr(ti, "_PYTHON_DIR", python_dir)
    if repo_root is not None:
        monkeypatch.setattr(ti, "_REPO_ROOT", repo_root)
    monkeypatch.setattr(ti, "_LOG_PATH", None)


def test_reuse_tarball_cache_scopes_to_requested_cases(tmp_path, monkeypatch):
    """Real bug: an earlier version copied EVERY cached tarball
    unconditionally (164 GB across all tiers), even for a --cases
    request naming just 1-2 cases. Must only copy tarballs matching
    the requested case list."""
    src_work = tmp_path / "src"
    (src_work / "work" / "dataset").mkdir(parents=True)
    for name in ["NISAR_Ethiopia.tar.gz", "ALOS_haiti.tar.gz",
                 "S1_Ridgecrest_EQ.tar.gz", "ALOS4_Pinon.tar.gz"]:
        (src_work / "work" / "dataset" / name).write_bytes(b"x" * 100)

    _reset_paths(monkeypatch, python_dir=src_work)
    dst_clone = tmp_path / "clone"
    ti._reuse_tarball_cache(dst_clone, ["NISAR_Ethiopia", "ALOS_haiti"])

    got = sorted(p.name for p in (dst_clone / "work" / "dataset").glob("*"))
    assert got == ["ALOS_haiti.tar.gz", "NISAR_Ethiopia.tar.gz"], (
        f"expected only the 2 requested tarballs, got {got}")


def test_reuse_tarball_cache_supports_tgz_extension(tmp_path, monkeypatch):
    """NISAR_SIM_ALOS uses .tgz instead of .tar.gz -- the case-name glob
    (f"{case}.*") must match both."""
    src_work = tmp_path / "src"
    (src_work / "work" / "dataset").mkdir(parents=True)
    (src_work / "work" / "dataset" / "NISAR_SIM_ALOS.tgz").write_bytes(b"x")

    _reset_paths(monkeypatch, python_dir=src_work)
    dst_clone = tmp_path / "clone"
    ti._reuse_tarball_cache(dst_clone, ["NISAR_SIM_ALOS"])

    assert (dst_clone / "work" / "dataset" / "NISAR_SIM_ALOS.tgz").is_file()


def test_reuse_tarball_cache_idempotent_does_not_clobber(tmp_path, monkeypatch):
    src_work = tmp_path / "src"
    (src_work / "work" / "dataset").mkdir(parents=True)
    (src_work / "work" / "dataset" / "RS2_SLC_Hawaii.tar.gz").write_bytes(b"original")

    _reset_paths(monkeypatch, python_dir=src_work)
    dst_clone = tmp_path / "clone"
    ti._reuse_tarball_cache(dst_clone, ["RS2_SLC_Hawaii"])
    (dst_clone / "work" / "dataset" / "RS2_SLC_Hawaii.tar.gz").write_bytes(b"DO NOT OVERWRITE")
    ti._reuse_tarball_cache(dst_clone, ["RS2_SLC_Hawaii"])

    assert (dst_clone / "work" / "dataset" / "RS2_SLC_Hawaii.tar.gz").read_bytes() == b"DO NOT OVERWRITE"


def test_reuse_tarball_cache_no_source_no_crash(tmp_path, monkeypatch):
    _reset_paths(monkeypatch, python_dir=tmp_path / "empty_src")
    dst_clone = tmp_path / "clone"
    ti._reuse_tarball_cache(dst_clone, ["RS2_SLC_Hawaii"])  # must not raise
    assert not (dst_clone / "work" / "dataset").exists()


def test_reuse_orbits_symlinks_and_is_readable(tmp_path, monkeypatch):
    fake_repo = tmp_path / "src_repo"
    (fake_repo / "orbits" / "ENVI").mkdir(parents=True)
    (fake_repo / "orbits" / "ENVI" / "marker.txt").write_text("real orbit data")

    _reset_paths(monkeypatch, repo_root=fake_repo)
    # In real usage clone_dir always already exists (created by
    # _fresh_clone's `git clone` before _reuse_orbits runs).
    dst_clone = tmp_path / "clone"
    dst_clone.mkdir()
    ti._reuse_orbits(dst_clone)

    assert (dst_clone / "orbits").is_symlink()
    assert (dst_clone / "orbits" / "ENVI" / "marker.txt").read_text() == "real orbit data"


def test_reuse_orbits_idempotent(tmp_path, monkeypatch):
    fake_repo = tmp_path / "src_repo"
    (fake_repo / "orbits").mkdir(parents=True)
    _reset_paths(monkeypatch, repo_root=fake_repo)
    dst_clone = tmp_path / "clone"
    dst_clone.mkdir()
    ti._reuse_orbits(dst_clone)
    ti._reuse_orbits(dst_clone)  # must not raise on second call


def test_reuse_orbits_no_source_no_crash(tmp_path, monkeypatch):
    _reset_paths(monkeypatch, repo_root=tmp_path / "empty_src")
    dst_clone = tmp_path / "clone"
    dst_clone.mkdir()
    ti._reuse_orbits(dst_clone)  # must not raise
    assert not (dst_clone / "orbits").exists()


def _write_results(results_dir, case, comparisons):
    import json
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / f"{case}.json").write_text(
        json.dumps({"case": case, "comparisons": comparisons}))


def test_check_sweep_results_detects_real_comparison_failure(tmp_path):
    """Real bug: sweep.py's exit code only reflects orchestration
    health, not per-comparison verdicts. A case with an attempted-and-
    FAILED comparison must be caught."""
    results_dir = tmp_path / "work" / "results"
    _write_results(results_dir, "ALOS_haiti", [
        {"file": "corr_ll.png", "status": "SUCCESS", "pair": "py-vs-csh",
         "metric_name": "ssim", "metric": 0.999, "intf": "intf/x"},
        {"file": "los_ll.grd", "status": "FAIL", "pair": "py-vs-csh",
         "metric_name": "rms", "metric": 1.174, "intf": "intf/x"},
    ])
    ok, summary = ti._check_sweep_results(tmp_path, ["ALOS_haiti"])
    assert ok is False
    assert "los_ll.grd" in summary


def test_check_sweep_results_detects_zero_comparison_case(tmp_path):
    """Real bug found AFTER the first fix landed: a case where BOTH
    python and csh fail to produce any common intf output yields ZERO
    comparisons, not a FAIL one (compare.py's discover_intf_dirs only
    adds a directory when at least one side has files). Zero fails
    trivially satisfies "no fails found" unless explicitly cross-
    checked against the expected case list."""
    results_dir = tmp_path / "work" / "results"
    _write_results(results_dir, "NISAR_Ethiopia", [
        {"file": "corr_ll.png", "status": "SUCCESS", "pair": "py-vs-csh",
         "metric_name": "ssim", "metric": 0.999, "intf": "intf/x"},
    ])
    _write_results(results_dir, "ERS_Hector_EQ", [])  # zero comparisons

    ok, summary = ti._check_sweep_results(tmp_path, ["NISAR_Ethiopia", "ERS_Hector_EQ"])
    assert ok is False, "a case with zero comparisons must not silently pass"
    assert "ERS_Hector_EQ" in summary
    assert "ZERO py-vs-csh" in summary


def test_check_sweep_results_excludes_non_py_vs_csh_pairs(tmp_path):
    results_dir = tmp_path / "work" / "results"
    _write_results(results_dir, "RS2_SLC_Hawaii", [
        {"file": "corr_ll.grd", "status": "SUCCESS", "pair": "py-vs-csh",
         "metric_name": "rms", "metric": 1e-6, "intf": "intf/x"},
        {"file": "corr_ll.grd", "status": "FAIL", "pair": "csh-vs-frozen",
         "metric_name": "rms", "metric": 5.0, "intf": "intf/x"},
    ])
    ok, summary = ti._check_sweep_results(tmp_path, ["RS2_SLC_Hawaii"])
    assert ok is True, f"csh-vs-frozen FAIL must not affect py-vs-csh verdict: {summary}"


def test_check_sweep_results_all_clean_passes(tmp_path):
    results_dir = tmp_path / "work" / "results"
    _write_results(results_dir, "RS2_SLC_Hawaii", [
        {"file": "corr_ll.png", "status": "SUCCESS", "pair": "py-vs-csh",
         "metric_name": "ssim", "metric": 0.999, "intf": "intf/x"},
    ])
    ok, summary = ti._check_sweep_results(tmp_path, ["RS2_SLC_Hawaii"])
    assert ok is True
    assert "1/1" in summary


def test_locate_fresh_conda_prefix_matches_unnamed_column_env(monkeypatch):
    """Real bug: `conda env list` only prints a name column for envs
    registered under the CURRENTLY-RESOLVED conda installation's own
    envs_dirs -- an env belonging to a DIFFERENT conda install on the
    same host (this dev host has 50+) shows up as a bare path with NO
    name column at all. Matching column[0]=='name' silently misses
    those; must match the path's basename instead."""
    fake_output = (
        "# conda environments:\n"
        "#\n"
        "                       /home/staff/dliu/anaconda3\n"
        "                       /home/staff/dliu/anaconda3/envs/gmtsar\n"
        "base                 * /home/staff/dliu/anaconda_knox\n"
        "gmtsar_verify_xyz      /home/staff/dliu/anaconda_knox/envs/gmtsar_verify_xyz\n"
    )
    import subprocess as sp
    monkeypatch.setattr(sp, "run", lambda *a, **k: type(
        "R", (), {"stdout": fake_output})())
    monkeypatch.setenv("CONDA_EXE", "/fake/conda")

    unnamed = ti._locate_fresh_conda_prefix("gmtsar")
    assert unnamed == Path("/home/staff/dliu/anaconda3/envs/gmtsar")

    named = ti._locate_fresh_conda_prefix("gmtsar_verify_xyz")
    assert named == Path("/home/staff/dliu/anaconda_knox/envs/gmtsar_verify_xyz")

    missing = ti._locate_fresh_conda_prefix("definitely_not_present")
    assert missing is None


def test_tier_cases_matches_cases_py_for_fast_and_full():
    """Sanity check that _tier_cases() (used to scope tarball/orbits
    reuse when no --cases override is given) stays in sync with
    tests/cases.py's own CASES dict rather than silently drifting, for
    BOTH the 12-case fast tier and the 21-case full tier. Real naming
    bug found live (2026-07-14): this tool's --full flag used to only
    ever run sweep.py --fast (12 cases), never sweep.py --full (21
    cases) -- so passing --full silently never verified the other 9
    cases at all. Fixed by renaming to match sweep.py's own --fast/
    --full vocabulary directly."""
    import cases as cases_mod
    for tier in ("fast", "full"):
        expected = {name for name, meta in cases_mod.CASES.items()
                    if tier in meta.get("tiers", set()) and meta.get("enabled", True)}
        assert set(ti._tier_cases(tier)) == expected, f"tier={tier}"
    # The full tier must be a strict superset of fast -- if it isn't,
    # something in cases.py's tier tagging has drifted.
    assert set(ti._tier_cases("fast")) <= set(ti._tier_cases("full"))
    assert len(ti._tier_cases("full")) == 21
    assert len(ti._tier_cases("fast")) == 12


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
