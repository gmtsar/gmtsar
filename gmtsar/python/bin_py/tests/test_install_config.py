#!/usr/bin/env python3
"""test_install_config.py — cheap, static regression guards for install.py's
config constants. No conda/network/subprocess needed (milliseconds), so
these run on every pytest pass and catch a real bug from silently coming
back if someone edits a version pin or a dependency list without
re-running a full clean-room test_install.py verification.

Each guard here maps to a real bug found by a genuine clean-room run on
2026-07-14 -- see install.py's own comments for the full incident writeup.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_UTILS = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_UTILS))

import install  # noqa: E402


def test_hdf5_pinned_to_1_12_not_1_14_plus():
    """conda-forge's HDF5 1.14.3 h5cc fails this repo's own configure.ac/
    ax_lib_hdf5.m4 compile-test, producing a broken HDF5_LIBS (missing
    the base -lhdf5/-lhdf5_cpp) that fails to LINK make_slc_nsr/
    make_slc_csk entirely. 1.12.x is proven working."""
    hdf5_pins = [p for p in install.CONDA_FORGE_BOOTSTRAP_PACKAGES
                 if p.startswith("hdf5")]
    assert hdf5_pins, "hdf5 must be in CONDA_FORGE_BOOTSTRAP_PACKAGES"
    assert hdf5_pins[0] == "hdf5=1.12.*", (
        f"hdf5 pin changed to {hdf5_pins[0]!r} -- if this wasn't "
        "deliberately re-verified against a real clean-room build "
        "(test_install.py --system conda --full), it will silently "
        "reintroduce the 1.14.x link failure")


def _requirements_txt_lines():
    req = install.REPO_ROOT / "gmtsar" / "python" / "requirements.txt"
    return req.read_text().splitlines()


def test_numpy_pinned_ge2_not_reverted():
    """numpy<2 was pinned with NO documented reason (unlike every other
    pin in requirements.txt) until a real external report (InSARHub,
    a downstream consumer wanting numpy>=2 for its own dependencies)
    prompted actually testing it instead of assuming it was needed.
    Confirmed via a genuine clean-room build: fresh env, numpy 2.4.6,
    full bin_py/tests/ suite (562 passed/59 skipped/0 failed) INCLUDING
    the real C-vs-Python xcorr parity test against real data --
    bit/float-exact, no numerical drift. See release_notes_v2.12.0.md."""
    numpy_lines = [l for l in _requirements_txt_lines() if l.startswith("numpy")]
    assert numpy_lines, "numpy must be pinned in requirements.txt"
    assert numpy_lines[0].split()[0] == "numpy>=2", (
        f"numpy pin changed to {numpy_lines[0]!r} -- if this reverts to "
        "numpy<2 without a real reason, it silently drops a real, "
        "tested compatibility improvement for downstream consumers")


def test_numba_floor_ge_0_60_for_numpy2_abi():
    """numba<0.60 caps numpy well below 2.0 in its own PyPI metadata
    (0.56.4: numpy<1.24; 0.59.x: numpy<1.27) -- numba only gained real
    numpy 2.x ABI support at 0.60.0. Doesn't bite in today's normal
    resolve (nothing else forces an old numba), but a real risk in an
    offline/locked install pinning numba<0.60 alongside numpy>=2."""
    numba_lines = [l for l in _requirements_txt_lines() if l.startswith("numba")]
    assert numba_lines, "numba must be pinned in requirements.txt"
    assert numba_lines[0].split()[0] == "numba>=0.60", (
        f"numba floor changed to {numba_lines[0]!r} -- if this drops "
        "below 0.60 while numpy stays >=2, an offline/locked install "
        "can silently pick a numpy2-incompatible numba")


def test_flex_in_apt_system_deps():
    """preproc/ERS_preproc/ers_line_fixer/ers_line_fixer.l is the only
    .l/.y source in the repo and needs flex/lex to generate its .c file.
    Without it: silent empty .c, compiles fine, fails to LINK with
    'undefined reference to main' -- no obvious connection to "flex is
    missing" from the error text alone."""
    assert "flex" in install.APT_SYSTEM_DEPS


def test_flex_bootstrapped_via_conda_and_lex_overridden():
    """flex is missing from a real host's system PATH even after being
    documented as 'assumed present' -- confirmed live (--system conda,
    ERS_Hector_EQ zero-comparison failure). Since flex has no ABI/
    linkage implications (unlike gfortran/g++, which deliberately stay
    system-provided), it's bootstrapped via conda-forge directly. But
    GNU Make's implicit .l.c rule invokes $(LEX), which defaults to the
    LITERAL name "lex" -- not "flex" -- so conda-forge's flex package
    must ALSO be paired with an explicit LEX=flex override; otherwise
    installing flex alone doesn't guarantee `make`'s lex rule finds it
    (no lex-alias guarantee across conda-forge builds/channels)."""
    assert "flex" in install.CONDA_FORGE_BOOTSTRAP_PACKAGES
    import inspect
    src = inspect.getsource(install.do_conda_setup)
    assert '"LEX": "flex"' in src


def test_conda_setup_extra_env_includes_path():
    """do_conda_setup()'s extra_env must prepend the conda env's own
    bin/ to PATH -- otherwise configure's HDF5 detection (which shells
    out to find h5cc/h5pcc via a plain PATH search, not CPPFLAGS/
    LDFLAGS) can silently resolve an unrelated conda install's h5cc on
    a host with multiple conda installs on PATH, producing a header/
    library version mismatch with no hard error until run time."""
    import inspect
    src = inspect.getsource(install.do_conda_setup)
    assert '"PATH"' in src, (
        "do_conda_setup no longer sets PATH in extra_env -- this will "
        "silently reintroduce the h5cc-resolves-to-the-wrong-conda-"
        "install bug")


def test_gshhg_gmt_not_gshhg_gmt_nc4():
    """gshhg-gmt-nc4 is not a real conda-forge package name -- `conda
    create` fails outright with PackagesNotFoundError on a truly fresh
    env. The correct package is gshhg-gmt."""
    assert "gshhg-gmt" in install.CONDA_FORGE_BOOTSTRAP_PACKAGES
    assert "gshhg-gmt-nc4" not in install.CONDA_FORGE_BOOTSTRAP_PACKAGES


def test_defuse_fake_lex_sources_exists_and_runs_in_do_build():
    """preproc/ERS_preproc/ers_line_fixer/ers_line_fixer.l is a troff man
    page, not lex source, but shares a basename with the real committed
    ers_line_fixer.c. GNU Make's implicit `.l.c:` rule can fire whenever
    it thinks .l is newer than .c (confirmed live twice: once via mtime
    ordering after a fresh git clone, and again even after touching .c
    forward -- most likely NFS attribute-cache staleness defeating the
    touch), destroying the real source and cascading into
    ERS_Hector_EQ failing downstream with zero comparisons. do_build()
    must call the defuse step before running make."""
    import inspect
    assert hasattr(install, "_defuse_fake_lex_sources")
    do_build_src = inspect.getsource(install.do_build)
    assert "_defuse_fake_lex_sources()" in do_build_src


def test_defuse_fake_lex_sources_renames_the_l_file(tmp_path):
    """Functional check (not just a call-site check): given a fixture .l
    file with a real .c sibling, _defuse_fake_lex_sources() must rename
    the .l file so it can never match Make's `%.l` implicit-rule
    pattern again -- mtime-based fixes were tried first and proved
    unreliable (see the function's own docstring), so this test
    specifically checks the rename outcome, not a timestamp."""
    sub = tmp_path / "preproc" / "ERS_preproc" / "ers_line_fixer"
    sub.mkdir(parents=True)
    c_file = sub / "ers_line_fixer.c"
    l_file = sub / "ers_line_fixer.l"
    c_file.write_text("int main(){return 0;}")
    l_file.write_text(".TH fake manpage")

    orig_repo_root = install.REPO_ROOT
    install.REPO_ROOT = tmp_path
    try:
        install._defuse_fake_lex_sources()
    finally:
        install.REPO_ROOT = orig_repo_root

    assert not l_file.exists(), ".l file must no longer exist under its original name"
    renamed = sub / "ers_line_fixer.l.not-lex-source"
    assert renamed.is_file(), "renamed file must exist"
    assert c_file.is_file(), "the real .c source must be untouched"
    assert c_file.read_text() == "int main(){return 0;}"


def test_defuse_fake_lex_sources_works_when_repo_root_under_work_dir(tmp_path):
    """Real bug found live (2026-07-14): the skip-guard used to do a
    substring check ("/work/" in str(l_file)) against the ABSOLUTE
    path, meant to skip files under a repo's own work/ subdirectory.
    But test_install.py's own clean-room clones live under
    gmtsar/python/work/install_test/clone_.../ -- REPO_ROOT itself
    nested under a directory named "work" -- so EVERY file's absolute
    path matched that substring, silently skipping the real fix on
    every single test run while never affecting a normal user's clone
    (which has no "work" in its path). The first functional test above
    used tmp_path, which happens not to contain "/work/", so it never
    caught this. This test deliberately nests the fixture repo under a
    "work" directory to reproduce the exact failure mode."""
    fake_repo = tmp_path / "work" / "install_test" / "clone_fake"
    sub = fake_repo / "preproc" / "ERS_preproc" / "ers_line_fixer"
    sub.mkdir(parents=True)
    c_file = sub / "ers_line_fixer.c"
    l_file = sub / "ers_line_fixer.l"
    c_file.write_text("int main(){return 0;}")
    l_file.write_text(".TH fake manpage")

    orig_repo_root = install.REPO_ROOT
    install.REPO_ROOT = fake_repo
    try:
        install._defuse_fake_lex_sources()
    finally:
        install.REPO_ROOT = orig_repo_root

    assert not l_file.exists(), (
        "still not renamed when REPO_ROOT is nested under a 'work' dir "
        "-- the substring-vs-path-component bug is back")
    assert (sub / "ers_line_fixer.l.not-lex-source").is_file()


def test_phasefilt_py_in_bin_py_names():
    """phasefilt_py was MISSING from BIN_PY_NAMES -- utils/filter:275
    calls `run('phasefilt_py ' + args)` by bare name, so every fresh
    install broke on the filter pipeline stage (rc=127; fails loudly
    since gmtsar_lib.run() raises on rc=127). Invisible on the dev host
    only because its bin/phasefilt_py symlink predated this rewrite."""
    assert "phasefilt_py" in install.BIN_PY_NAMES


def test_bin_py_names_covers_every_bare_name_call_site():
    """General regression guard, not just phasefilt_py specifically:
    grep every bin_py/*_py tool against every bare `run(f"<name> ...")`/
    subprocess `['<name>', ...]` call site in utils/, and assert every
    tool that's actually invoked by bare name is in BIN_PY_NAMES. This
    is the exact audit done by hand on 2026-07-14 that found the
    phasefilt_py gap, now automated so a NEW bare-name call site
    without a matching BIN_PY_NAMES entry fails a test instead of
    silently breaking a fresh install."""
    import re
    utils_dir = _UTILS / "utils"
    bin_py_dir = _UTILS / "bin_py"
    tool_names = sorted(p.name for p in bin_py_dir.glob("*_py") if p.is_file())
    assert tool_names, "no bin_py/*_py tools found -- check test setup"

    missing = []
    for name in tool_names:
        # \b on BOTH sides -- without the leading boundary, "surface_py"
        # would wrongly match inside "gmt_surface_py" (a DIFFERENT,
        # unrelated in-process module referenced only in comments).
        pat = re.compile(r"\b" + re.escape(name) + r"\b")
        invoked_bare = False
        for f in utils_dir.glob("*"):
            if not f.is_file():
                continue
            try:
                text = f.read_text(errors="ignore")
            except Exception:
                continue
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue  # comment-only line, not a real call site
                if pat.search(line) and ("run(" in line or "subprocess" in line):
                    invoked_bare = True
                    break
            if invoked_bare:
                break
        if invoked_bare and name not in install.BIN_PY_NAMES:
            missing.append(name)

    assert not missing, (
        f"{missing} are invoked by bare name in utils/ but missing from "
        "BIN_PY_NAMES -- a fresh install will fail with rc=127 the first "
        "time this pipeline stage runs")


def test_pytest_in_requirements_txt():
    """A fresh --system conda install had no way to run bin_py/tests/ at
    all without a manual `pip install pytest` -- requirements.txt never
    listed it, even though running that suite is part of the documented
    dev workflow (README.md's "Testing for developers")."""
    # encoding pinned: read_text() without one uses the LOCALE codepage
    # (e.g. GBK on a zh-locale Windows host), which chokes on this
    # UTF-8 file's non-ASCII chars -- real failure hit 2026-07-23 on the
    # conda-windows-full clean-room host.
    requirements = (_UTILS / "requirements.txt").read_text(encoding="utf-8")
    assert re.search(r"^pytest\b", requirements, re.MULTILINE), (
        "pytest missing from requirements.txt -- a fresh install can't "
        "run its own test suite")


def test_locate_conda_env_creates_when_missing_at_resolved_base(tmp_path, monkeypatch):
    """locate_conda_env() used to only ever FIND an existing env under
    the fixed CONDA_SEARCH_BASES list and error if missing, assuming a
    pre-populated env. It must now CREATE the env via `conda create`
    when missing, using whatever conda_base locate_conda_base()
    resolves -- which may be OUTSIDE CONDA_SEARCH_BASES (see the next
    test for the specific bug that caused)."""
    fake_conda_base = tmp_path / "fakeconda"
    (fake_conda_base / "bin").mkdir(parents=True)
    conda_bin = fake_conda_base / "bin" / "conda"
    conda_bin.write_text("#!/bin/sh\necho fake\n")
    conda_bin.chmod(0o755)

    monkeypatch.setattr(install, "CONDA_SEARCH_BASES", [str(tmp_path / "unrelated")])
    monkeypatch.setattr(install, "locate_conda_base", lambda: fake_conda_base)
    # Force the classic `conda create` path this test actually exercises --
    # without this, a REAL micromamba on the test host's own PATH (installed
    # separately, unrelated to this test) gets preferred by locate_conda_env's
    # real logic, bypassing fake_run's `cmd[:2] == [conda_bin, "create"]`
    # check entirely since the command becomes ["micromamba", "create", ...].
    # Found as a genuine regression 2026-07-23 when a real clean-room
    # test_install.py --full run hit this on a host that happened to have
    # micromamba installed.
    monkeypatch.setattr(install.shutil, "which", lambda name: None)

    calls = []
    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:2] == [str(conda_bin), "create"]:
            (fake_conda_base / "envs" / "gmtsar_regress_test").mkdir(parents=True)
    monkeypatch.setattr(install, "run", fake_run)

    prefix = install.locate_conda_env("gmtsar_regress_test")
    assert prefix == fake_conda_base / "envs" / "gmtsar_regress_test"
    assert calls, "conda create was never invoked"
    assert "conda-forge" in calls[0]


def test_locate_conda_env_prefers_micromamba_when_present(tmp_path, monkeypatch):
    """Real bug found 2026-07-23 (a genuine clean-room test_install.py
    --full run): classic conda's solver hung 28+ minutes unsolved on
    the real CONDA_FORGE_BOOTSTRAP_PACKAGES set on a host with an old,
    pre-libmamba-solver conda. locate_conda_env() now prefers
    micromamba for the actual create call when present on PATH."""
    fake_conda_base = tmp_path / "fakeconda"
    (fake_conda_base / "bin").mkdir(parents=True)
    conda_bin = fake_conda_base / "bin" / "conda"
    conda_bin.write_text("#!/bin/sh\necho fake\n")
    conda_bin.chmod(0o755)
    fake_micromamba = tmp_path / "fake_micromamba"
    fake_micromamba.write_text("#!/bin/sh\necho fake\n")
    fake_micromamba.chmod(0o755)

    monkeypatch.setattr(install, "CONDA_SEARCH_BASES", [str(tmp_path / "unrelated")])
    monkeypatch.setattr(install, "locate_conda_base", lambda: fake_conda_base)
    monkeypatch.setattr(install.shutil, "which",
                        lambda name: str(fake_micromamba) if name == "micromamba" else None)

    calls = []
    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:1] == [str(fake_micromamba)]:
            (fake_conda_base / "envs" / "gmtsar_mamba_test").mkdir(parents=True)
    monkeypatch.setattr(install, "run", fake_run)

    prefix = install.locate_conda_env("gmtsar_mamba_test")
    assert prefix == fake_conda_base / "envs" / "gmtsar_mamba_test"
    assert calls, "micromamba create was never invoked"
    assert calls[0][0] == str(fake_micromamba)
    assert "create" in calls[0]
    assert "conda-forge" in calls[0]


def test_locate_conda_env_finds_env_outside_conda_search_bases(tmp_path, monkeypatch):
    """Real bug: the post-`conda create` existence check used to
    re-scan the fixed CONDA_SEARCH_BASES list instead of looking under
    the SAME conda_base locate_conda_base() actually resolved -- on a
    host with multiple conda installs (this dev host has 50+), the env
    genuinely got created but the check couldn't find it, incorrectly
    erroring "conda create exited 0 but the env still doesn't exist"
    on a real success. Also covers the case where the env already
    exists under a non-standard base (no create should be attempted)."""
    fake_conda_base = tmp_path / "fakeconda"
    (fake_conda_base / "envs" / "gmtsar_existing").mkdir(parents=True)
    (fake_conda_base / "bin").mkdir()
    (fake_conda_base / "bin" / "conda").write_text("#!/bin/sh\n")

    monkeypatch.setattr(install, "CONDA_SEARCH_BASES", [str(tmp_path / "unrelated")])
    monkeypatch.setattr(install, "locate_conda_base", lambda: fake_conda_base)

    calls = []
    monkeypatch.setattr(install, "run", lambda cmd, **kw: calls.append(cmd))

    prefix = install.locate_conda_env("gmtsar_existing")
    assert prefix == fake_conda_base / "envs" / "gmtsar_existing"
    assert not calls, "should NOT have called conda create -- env already exists"


def test_root_readme_is_pure_ascii():
    """The root README.md must contain no non-ASCII byte.

    Real incident, 2026-08-01: the fork's v2.11.1 GitHub Release body
    rendered as `Native Windows bundle 鈥??? supersedes...`. Em-dashes
    written as UTF-8 (E2 80 94) went through a CP936/GBK-configured pipe
    on the Windows dev host, so E2 80 became a CJK glyph and 94 became an
    unrecoverable replacement char. The repo's own .md files were fine --
    the damage happened in transit to an external system.

    The root README is the highest-risk file for that failure mode: it is
    upstream's, it is read by everyone, and it gets copied into release
    announcements and issue replies where the same mangling can recur. It
    was pure ASCII before this project touched it and must stay that way.

    Deliberately scoped to the root README only. The release notes under
    docs/release_notes/ do use em-dashes and arrows throughout, are read
    via git/GitHub's own UTF-8 rendering, and have never been corrupted --
    guarding them would be churn, not safety."""
    readme = install.REPO_ROOT / "README.md"
    assert readme.is_file(), f"root README.md not found at {readme}"
    raw = readme.read_bytes()
    offenders = [
        (i, b) for i, b in enumerate(raw) if b > 0x7F
    ]
    assert not offenders, (
        f"root README.md has {len(offenders)} non-ASCII byte(s), first at "
        f"offset {offenders[0][0]} (0x{offenders[0][1]:02X}). Use ASCII "
        "punctuation ('--' not an em-dash, '->' not an arrow, straight "
        "quotes) -- non-ASCII here has been mangled to mojibake by "
        "CP936-configured Windows tooling before."
    )


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
