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


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
