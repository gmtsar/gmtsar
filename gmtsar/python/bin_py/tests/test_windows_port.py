#!/usr/bin/env python3
"""test_windows_port.py — regression guards for the v2.10.x native-Windows
port (`--system conda-windows-full`). Each test maps to a REAL bug found
during the 2026-07-23 bring-up and the two clean-room runs that followed
(fresh clone + fresh conda env) — see install.py / utils/gmtsar_lib.py /
tests/case_runner.py comments and release_notes_v2.10.x.md for the full
incident writeups. Per project_rules.md Rule 8, every one of those bugs
gets a guard here so it can't silently ship again.

All tests are static, mock-based, or tiny-fixture — no conda, no network,
no Windows requirement (they run and pass on POSIX CI too; the
Windows-only code paths are exercised via monkeypatched `os.name`).
"""
from __future__ import annotations

import importlib
import inspect
import os
import sys
import threading
from pathlib import Path

import pytest

_PY_ROOT = Path(__file__).resolve().parent.parent.parent  # gmtsar/python
for _p in (str(_PY_ROOT), str(_PY_ROOT / "utils"), str(_PY_ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import install  # noqa: E402
import gmtsar_lib  # noqa: E402


# ── install.py: fresh-env creation bugs (found by the 2026-07-23 clean room) ──

def test_windows_bootstrap_includes_pip():
    """Real bug (2026-07-23, first genuinely-fresh Windows env): python
    arrives transitively (gmt -> gdal -> python bindings) but pip is not
    guaranteed to, and do_python_deps runs `python.exe -m pip install`.
    Same bug class CONDA_FORGE_BOOTSTRAP_PACKAGES fixed in v2.9.0."""
    assert "pip" in install.WINDOWS_CONDA_BOOTSTRAP_PACKAGES


def test_windows_conda_cmd_exe_is_direct_and_preserves_specs():
    """Real bug (2026-07-23, first genuinely-fresh Windows env creation):
    routing `conda create` through `cmd /c conda.bat` let cmd parse the
    spec `libtiff>=4.5,<5` as redirection operators, failing in ms with
    'The system cannot find the file specified'. conda.exe must be
    invoked DIRECTLY (no cmd), with specs passed through untouched."""
    spec = "libtiff>=4.5,<5"
    cmd = install._windows_conda_cmd(Path("C:/fake/Scripts/conda.exe"),
                                      ["create", "-n", "x", spec])
    assert cmd[0] != "cmd", "conda.exe must not be routed through cmd /c"
    assert spec in cmd, "package spec must pass through verbatim"


def test_windows_conda_cmd_bat_fallback_rejects_metachars():
    """The conda.bat fallback CANNOT pass cmd metacharacters reliably
    (list2cmdline escapes embedded quotes as \\" which survive the .bat's
    %* forwarding as literal quote chars) — it must fail loudly up front,
    never let cmd silently misparse a spec into redirections."""
    bat = Path("C:/fake/condabin/conda.bat")
    with pytest.raises(SystemExit):
        install._windows_conda_cmd(bat, ["create", "libtiff>=4.5,<5"])
    # Metachar-free args are still allowed through the fallback:
    cmd = install._windows_conda_cmd(bat, ["env", "list", "--json"])
    assert cmd[:2] == ["cmd", "/c"]


def test_windows_conda_exe_prefers_scripts_exe(tmp_path):
    """Scripts\\conda.exe (real PE, directly CreateProcess-able, no cmd
    parsing) must win over condabin\\conda.bat whenever it exists."""
    (tmp_path / "Scripts").mkdir()
    (tmp_path / "condabin").mkdir()
    exe = tmp_path / "Scripts" / "conda.exe"
    bat = tmp_path / "condabin" / "conda.bat"
    exe.write_text("")
    bat.write_text("")
    assert install._windows_conda_exe(tmp_path) == exe
    exe.unlink()
    assert install._windows_conda_exe(tmp_path) == bat


def test_apply_c_fixes_called_from_windows_build():
    """Real gap (v2.10.0): _apply_c_fixes() was only called from
    do_build(), so the Windows CMake path silently skipped both the
    conv.c and fitoffset.c fixes until wired in explicitly."""
    assert "_apply_c_fixes" in inspect.getsource(install.do_windows_build)


# ── c_fixes/conv.c: binary reads must stay binary-mode ────────────────────────

def test_conv_c_fix_staged_wired_and_binary_mode():
    """Real bug (2026-07-23): conv.c opened the raw SLC and .grd=bf files
    with fopen(..., "r") — text mode. On Windows the CRT translates CRLF
    and treats 0x1A as EOF, silently corrupting the read; correlation
    collapsed to ~0 over 85% of a real RS2 swath. Guard all three layers:
    staged copy uses "rb", the C_FIXES map wires it, and no text-mode
    variant of either call site sneaks back into the staged copy."""
    src = _PY_ROOT / "c_fixes" / "conv.c"
    assert src.is_file(), "c_fixes/conv.c staged copy missing"
    text = src.read_text(encoding="utf-8")
    assert 'fopen(input_file_name, "rb")' in text
    assert 'fopen(input_name, "rb")' in text
    assert 'fopen(input_file_name, "r")' not in text
    assert 'fopen(input_name, "r")' not in text
    assert any(s.name == "conv.c" for s in install.C_FIXES), \
        "c_fixes/conv.c not wired into install.C_FIXES"


# ── gmtsar_lib._win_bash(): resolution + thread-safety ───────────────────────

@pytest.fixture
def _reset_win_bash():
    """Save/restore _win_bash's process-wide memoization around a test."""
    saved = (gmtsar_lib._WIN_BASH, gmtsar_lib._WIN_BASH_RESOLVED)
    gmtsar_lib._WIN_BASH = None
    gmtsar_lib._WIN_BASH_RESOLVED = False
    yield
    gmtsar_lib._WIN_BASH, gmtsar_lib._WIN_BASH_RESOLVED = saved


def test_win_bash_honors_env_override(_reset_win_bash, tmp_path, monkeypatch):
    fake_bash = tmp_path / "bash.exe"
    fake_bash.write_text("")
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setenv("GMTSAR_WIN_BASH", str(fake_bash))
    assert gmtsar_lib._win_bash() == str(fake_bash)


def test_win_bash_rejects_system32_wsl_stub(_reset_win_bash, monkeypatch):
    """Real bug (2026-07-23): Windows 10+ ships a System32\\bash.exe stub
    that launches WSL — a full recipe run silently no-opped against its
    'no installed distributions' prompt while reporting success. When the
    ONLY bash PATH offers is the System32 stub, resolution must refuse it
    (and, with no other candidate existing, exit loudly)."""
    stub = r"C:\Windows\System32\bash.exe"
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.delenv("GMTSAR_WIN_BASH", raising=False)
    monkeypatch.setattr(gmtsar_lib.shutil, "which", lambda _: stub)
    monkeypatch.setattr(gmtsar_lib.os.path, "isfile",
                        lambda p: p == stub)  # ONLY the stub "exists"
    with pytest.raises(SystemExit):
        gmtsar_lib._win_bash()


def test_win_bash_thread_safe_no_caller_sees_none(_reset_win_bash, tmp_path,
                                                   monkeypatch):
    """Real bug (2026-07-23): the memoization set its resolved flag BEFORE
    assigning the value — a concurrent caller (case_runner runs two slot
    threads per case) saw RESOLVED=True with the value still None and
    silently fell through to cmd.exe ('cleanup' is not recognized...).
    Invariant: once any caller gets a value, no concurrent caller may
    ever observe None."""
    fake_bash = tmp_path / "bash.exe"
    fake_bash.write_text("")
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setenv("GMTSAR_WIN_BASH", str(fake_bash))
    results = []
    threads = [threading.Thread(target=lambda: results.append(gmtsar_lib._win_bash()))
               for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results) == 16
    assert all(r == str(fake_bash) for r in results), \
        f"a concurrent caller observed a wrong value: {set(results)}"


def test_resolve_sharedir_returns_forward_slashes(tmp_path, monkeypatch):
    """Real bug (2026-07-23): a backslashed sharedir embedded unquoted in
    a `bash -c` command string had its backslashes eaten by bash escaping
    (D:\\...\\share\\gmtsar -> D:...sharegmtsar), so conv couldn't open
    filter kernels. resolve_sharedir must emit forward slashes only."""
    share = tmp_path / "share" / "gmtsar"
    share.mkdir(parents=True)
    monkeypatch.setenv("GMTSAR", str(tmp_path))
    assert "\\" not in gmtsar_lib.resolve_sharedir()


# ── tests/ harness: path-separator + tree-name bugs ──────────────────────────

def test_case_runner_env_path_uses_os_pathsep():
    """Real bug (2026-07-23): case_runner/sweep built PATH with a
    hardcoded ':' — malformed on Windows (os.pathsep is ';')."""
    import case_runner
    env = case_runner._run_subprocess_env(None, "/fake/gmtsar/bin",
                                           False, "case_x", None)
    assert env["PATH"].split(os.pathsep)[0] == "/fake/gmtsar/bin"


def test_cases_roots_survive_rstrip_basename_on_all_platforms(monkeypatch):
    """Real bug (2026-07-23): tree roots were built as
    `workAbsoluteDir + 'ref_test/'` — a literal '/' after an os.sep path.
    On Windows, `.rstrip(os.sep)` then stripped nothing, basename()
    returned '', and BOTH topo-mode-ab trees silently collapsed into the
    same directory (two threads corrupting each other's outputs while
    reporting success). Guard: for both TOPO_MODE_AB settings, every root
    must end with os.sep and yield its expected non-empty dir name."""
    import cases
    try:
        for ab_mode, expected in (
            ("1", {"ref_test", "new_test", "dataset", "recipes"}),
            (None, {"python_test", "csh_test", "dataset", "recipes"}),
        ):
            if ab_mode is None:
                monkeypatch.delenv("TOPO_MODE_AB", raising=False)
            else:
                monkeypatch.setenv("TOPO_MODE_AB", ab_mode)
            importlib.reload(cases)
            roots = [cases.cshRefRoot, cases.pythonRunRoot,
                     cases.datasetRoot, cases.recipesDir]
            names = {os.path.basename(r.rstrip(os.sep)) for r in roots}
            assert all(r.endswith(os.sep) for r in roots)
            assert names == expected, f"tree-name derivation broke: {names}"
    finally:
        monkeypatch.delenv("TOPO_MODE_AB", raising=False)
        importlib.reload(cases)


def test_run_recipe_resolves_bash_via_win_bash():
    """Real bug (2026-07-23): _run_recipe invoked a bare ["bash", ...],
    trusting PATH order — the System32 WSL stub could (and did) win,
    no-opping entire recipe runs. It must resolve via _win_bash()."""
    import case_runner
    assert "_win_bash" in inspect.getsource(case_runner._run_recipe)


# ── distribute_gmtsar_windows.py: bundle-correctness guards (v2.10.3) ────────

import distribute_gmtsar_windows as dist_mod  # noqa: E402


def test_bootstrap_pins_openblas_blas_variant():
    """Real bug (2026-07-23, isolated-PATH verify): conda-forge's win-64
    default libblas/liblapack are MKL-variant forwarder shims; merely
    co-installing openblas does NOT flip them, and MKL can't be bundled
    (runtime dispatch). The variant pins are load-bearing."""
    for pin in ("libblas=*=*openblas", "liblapack=*=*openblas",
                "libcblas=*=*openblas"):
        assert pin in install.WINDOWS_CONDA_BOOTSTRAP_PACKAGES


def test_is_system_dll_policy():
    """api-set names are virtual on Win10+ (never bundle); MSVC runtime
    is NEVER system (presence in System32 only proves THIS machine has a
    VC redist -- a clean target may not)."""
    assert dist_mod._is_system_dll("api-ms-win-crt-math-l1-1-0.dll")
    assert dist_mod._is_system_dll("ext-ms-win-anything.dll")
    assert not dist_mod._is_system_dll("VCRUNTIME140.dll")
    assert not dist_mod._is_system_dll("msvcp140.dll")


@pytest.mark.skipif(os.name != "nt", reason="needs a real Windows system DLL")
def test_pe_forwarder_targets_on_real_forwarders():
    """kernel32.dll famously forwards a chunk of its exports to ntdll
    (HeapAlloc -> NTDLL.RtlAllocateHeap, ...) -- a real, stable fixture
    for the export-forwarder parser that found the MKL-shim bug."""
    k32 = Path(os.environ["SystemRoot"]) / "System32" / "kernel32.dll"
    targets = {t.lower() for t in dist_mod._pe_forwarder_targets(k32)}
    assert "ntdll.dll" in targets


def test_pe_forwarder_targets_tolerates_non_pe(tmp_path):
    junk = tmp_path / "not_a_pe.dll"
    junk.write_bytes(b"definitely not a PE file")
    assert dist_mod._pe_forwarder_targets(junk) == set()


def test_collect_dlls_walks_forwarders_and_guards_mkl():
    src = inspect.getsource(dist_mod.do_collect_dlls)
    assert "_pe_forwarder_targets" in src, \
        "import-table-only walk misses forwarder deps (the MKL-shim bug)"
    assert "mkl" in src, "MKL fail-loud guard removed"


def test_launcher_template_contract():
    """Each entry maps to a real bundle-smoke failure (2026-07-23):
    gmt.exe lives in pyenv\Library\bin (rc=127 without it); the real
    bash is usr\bin\bash.exe (Git\bin one is a launcher stub); the
    gmt.dll copy in dist\bin has the BUILD env's share path baked in
    (GMT_SHAREDIR must override)."""
    t = dist_mod.LAUNCHER_TEMPLATE
    assert r"pyenv\Library\bin" in t
    assert r"git-bash\usr\bin\bash.exe" in t
    assert "GMT_SHAREDIR" in t


def test_bundle_includes_python_framework_tree():
    """bin_py tools resolve their utils package via
    $GMTSAR/gmtsar/python/utils -- the bundle must carry that tree or
    every one of them ImportErrors (found by the first bundle smoke)."""
    src = inspect.getsource(dist_mod.do_copy_gmtsar)
    assert '"utils"' in src and '"bin_py"' in src


def test_verify_harness_survives_stdin_readers():
    """esarp.exe etc. block on stdin when invoked bare -- the verify must
    close stdin and treat a long-running (started!) exe as pass, not
    crash the whole run with TimeoutExpired."""
    src = inspect.getsource(dist_mod.do_verify)
    assert "DEVNULL" in src
    assert "TimeoutExpired" in src


def test_bundle_writes_license_attribution():
    """Publishing the bundle zip redistributes GMT/LGPL, ghostscript/AGPL,
    Git Bash/GPLv3, GMTSAR/GPL-3 -- the license-collation step is a
    release blocker, not a nicety (flagged in PATHWAY_FORWARD v2.10.2/3,
    closed in v2.11.0)."""
    src = inspect.getsource(dist_mod.do_write_licenses)
    for needle in ("THIRD_PARTY_NOTICES", "conda-meta", "AGPL", "LICENSE.TXT",
                   "importlib.metadata",  # pip dists are NOT in conda-meta
                   "license_texts"):      # verbatim copyleft texts, fail-loud
        assert needle in src
    assert "do_write_licenses" in inspect.getsource(dist_mod.main)
    # The committed texts every copyleft component in the bundle requires
    # (2026-07-23 audit): poppler GPL-2.0-only, gmt LGPL-3, geos LGPL-2.1,
    # ghostscript AGPL-3, spatialite MPL-1.1, certifi MPL-2.0.
    texts = _PY_ROOT / "license_texts"
    for lic in ("GPL-2.0", "LGPL-2.1", "LGPL-3.0", "AGPL-3.0",
                "MPL-1.1", "MPL-2.0"):
        f = texts / f"{lic}.txt"
        assert f.is_file() and f.stat().st_size > 5000, f"missing/stub {f}"


def test_cmake_win32_tiff_coalesce_and_fail_loud():
    """Real clean-machine failure (2026-07-24, another host's fresh conda
    env): find_package(TIFF REQUIRED) left TIFF_LIBRARY empty, TIFF
    silently dropped off GMTSAR_LINK_LIBS, and only split_spectrum.exe
    (the sole direct libtiff consumer) failed at link -- undefined
    TIFFOpen/TIFFReadScanline. gmtsar/CMakeLists.txt must coalesce
    TIFF_LIBRARY from TIFF_LIBRARIES / a direct search, and FATAL_ERROR
    at configure time rather than ever link without TIFF."""
    cml = (_PY_ROOT.parent.parent / "gmtsar" / "CMakeLists.txt").read_text(encoding="utf-8")
    assert "TIFF_LIBRARIES" in cml
    assert "TIFF_LIBRARY_WIN_FALLBACK" in cml
    assert "FATAL_ERROR" in cml and "TIFF import library not found" in cml
