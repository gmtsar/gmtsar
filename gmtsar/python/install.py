#!/usr/bin/env python3
"""install.py — Consolidated installer for the GMTSAR Python framework
(fork: gmtsar.py.docker.dev). Installs deps, builds gmtsar IN-PLACE from
this checkout, and stages Python utilities into <repo>/bin. Re-runnable
(idempotent).

Install location: the existing clone. This script never re-clones and
never installs system-wide. `make install` lands in <repo>/bin via
--prefix=<repo>.

Both --system choices work on a brand-new box (nothing pre-installed
beyond the OS package manager, or an already-installed Miniconda/Anaconda):

--system (pick exactly one):
    ubuntu    apt-install system deps (REQUIRES SUDO). Provisions
              everything: gmt, gfortran, g++, make, autoconf, csh,
              ghostscript, libtiff, libhdf5, liblapack, ...
    conda     use a conda env (no sudo). Set CONDA_GMTSAR_ENV (or
              --conda-env) to pick which env (default: 'gmtsar'). If the
              env doesn't exist yet, it's created via `conda create -c
              conda-forge gmt hdf5 libtiff liblapack ...` (network
              required, also bootstraps flex -- see do_conda_setup's
              docstring for why flex specifically is conda-provisioned
              rather than assumed). Still assumes the system already
              has basic build tools (gfortran, g++, make, autoconf,
              csh, ghostscript) -- --system conda deliberately keeps the
              SYSTEM compiler in use rather than conda's (see
              do_conda_setup's docstring), so it is not a fully
              from-scratch bootstrap on a bare OS image the way
              --system ubuntu is.

`--system` alone installs everything for that system: dependencies, Python
packages, and the in-place build. Two optional add-ons:
    --rebuild    skip the dependency steps, just rebuild + re-stage
                 (fast path for "I edited source, rebuild")
    --orbits     also fetch ORBITS.tar (~5-7 GB) into <repo>/orbits
                 (or run alone, with no --system, to fetch orbits only)

Examples:
    python3 gmtsar/python/install.py --system conda           # no-sudo, full install
    python3 gmtsar/python/install.py --system ubuntu          # sudo path, full install
    python3 gmtsar/python/install.py --system conda --rebuild # rebuild only, no deps
    python3 gmtsar/python/install.py --orbits                 # orbits only
"""
from __future__ import annotations

import argparse
import datetime
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = (SCRIPT_DIR / ".." / "..").resolve()

# Set once in main() before any run() calls, so every command this script
# executes -- across every helper function -- gets a timestamped marker in
# a single durable log file, not just scattered stdout a caller may or may
# not have redirected. None until then (e.g. --help exits before this is
# set, and never calls run() anyway).
_LOG_PATH: Path | None = None

APT_SYSTEM_DEPS = [
    "python-is-python3", "csh", "subversion", "autoconf", "libtiff5-dev",
    "libhdf5-dev", "wget", "liblapack-dev", "gfortran", "g++", "libgmt-dev",
    "gmt-dcw", "gmt-gshhg", "gmt", "ghostscript", "git", "make", "vim",
    # flex (2026-07-14, real clean-room build failure): preproc/ERS_preproc/
    # ers_line_fixer/ers_line_fixer.l needs `lex`/`flex` to generate its .c
    # source. Without it, `lex -t ers_line_fixer.l > ers_line_fixer.c` fails
    # with "command not found", silently produces an empty .c file that
    # still COMPILES (0 warnings) but has no main(), and the link step then
    # fails with "undefined reference to `main'" -- no binary, no clear
    # connection back to "flex is missing" unless you read the raw build
    # log. The only .l/.y source in the whole repo, so flex alone suffices.
    "flex",
]
APT_PYTHON_DEPS = [
    "python3-skimage", "python3-matplotlib", "python3-xarray",
    "python3-netcdf4", "python3-tk", "python3-numpy", "python3-scipy",
    "python3-h5py", "python3-pip",
]
# numba and cython aren't reliably available as apt packages across Ubuntu
# releases -- pip install them (see requirements.txt comment on what's NOT
# apt-installable). Required for xcorr_py/resamp_py/SAT_llt2rat_py/
# gmt_surface_py, all wired ON by default.
PIP_PYTHON_DEPS_UBUNTU = ["numba>=0.56", "cython>=3.0"]

# The bin_py/ ports that utils/p2p_stages.py (and utils/filter, utils/
# intf, utils/geocode, utils/dem2topo_ra) invoke by bare name via
# subprocess (resamp_py, xcorr_py, etc.) -- these must be on PATH too. One
# production copy per tool, no version suffixes (project_rules.md Rule 13)
# -- superseded variants (resamp_py_v2, SAT_llt2rat_py's old v1) were kept
# at bin_py/archive/ for reference, removed in the v2.7.1 doc cleanup
# (recoverable from git history if needed), never on PATH.
#
# `phasefilt_py` (2026-07-14, real clean-room test): was MISSING here --
# utils/filter:275 calls `run('phasefilt_py ' + args)`, so every fresh
# install broke on the filter pipeline stage (rc=127; fails loudly since
# gmtsar_lib.run() raises on rc=127 -- see project_rules.md Rule 1).
# Confirmed by grepping every bin_py/*_py tool against every bare
# `run(f"<name> ...")`/`subprocess...['<name>', ...]` call site in
# utils/ -- blockmedian_py/conv_py/make_slc_csk2_py/surface_py have no
# such call site (not invoked by bare name anywhere), so they're
# correctly absent from this list.
BIN_PY_NAMES = [
    "phasediff_py", "make_los_py", "SAT_baseline_py", "xcorr_py",
    "resamp_py", "make_slc_s1a_py", "SAT_llt2rat_py", "phasefilt_py",
]

CONDA_SEARCH_BASES = ["~/anaconda3", "~/miniconda3", "/opt/conda"]


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _log_line(line: str) -> None:
    """Print AND (if a log file is open) append -- so every command this
    script runs, across every helper function, lands in one durable,
    timestamped log, not just whatever a caller happened to redirect."""
    print(line)
    if _LOG_PATH is not None:
        with open(_LOG_PATH, "a") as f:
            f.write(line + "\n")


def _run_impl(cmd: list[str], check: bool, **kwargs) -> int:
    """Shared by run()/run_soft(): tees the subprocess's combined stdout+
    stderr live to the terminal AND the log file (not just a summary
    marker), so a failure's real error text -- not just "exit 1" -- is
    captured for tracing, and prints a timestamped start marker before
    and a done/FAILED summary (elapsed time + exit code) after."""
    cmd_str = " ".join(cmd)
    _log_line(f"[{_utc_now()}] ==> {cmd_str}")
    t0 = time.time()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True,
                             bufsize=1, **kwargs)
    for line in proc.stdout:
        _log_line(line.rstrip("\n"))
    rc = proc.wait()
    dt = time.time() - t0
    if rc == 0:
        _log_line(f"[{_utc_now()}] done in {dt:.3f}s (rc=0): {cmd_str}")
    else:
        _log_line(f"[{_utc_now()}] FAILED after {dt:.3f}s (rc={rc}): {cmd_str}")
        if check:
            raise subprocess.CalledProcessError(rc, cmd)
    return rc


def run(cmd: list[str], **kwargs) -> None:
    """Run a subprocess; any non-zero exit raises loudly and stops the
    script immediately (this script's equivalent of `set -e`). Never
    swallow a non-zero exit (project_rules.md Rule 1). Full output is
    teed live + logged -- see _run_impl."""
    _run_impl(cmd, check=True, **kwargs)


def run_soft(cmd: list[str], **kwargs) -> int:
    """Like run(), but does NOT raise on a non-zero exit -- only for the
    one genuinely-best-effort call in this script (`autoupdate`, whose
    original bash equivalent was `autoupdate || true`). Still fully
    logged, so a soft failure is traceable even though it isn't fatal."""
    return _run_impl(cmd, check=False, **kwargs)


def sudo_prefix() -> list[str]:
    return [] if os.geteuid() == 0 else ["sudo"]


def require_apt() -> None:
    if shutil.which("apt") is None:
        sys.exit("ERROR: apt not found (this script targets Ubuntu/Debian)")


def _find_existing_conda_env(envname: str) -> Path | None:
    for base in CONDA_SEARCH_BASES:
        candidate = Path(os.path.expanduser(base)) / "envs" / envname
        if candidate.is_dir():
            return candidate
    return None


def locate_conda_base() -> Path:
    """Find the conda INSTALLATION (not a specific env) so a missing
    'gmtsar' env can be created. Checks $CONDA_EXE (set by conda's shell
    init in most interactive shells), then `conda` on PATH, then the same
    common locations env-search uses."""
    conda_exe = os.environ.get("CONDA_EXE")
    if conda_exe and Path(conda_exe).is_file():
        return Path(conda_exe).resolve().parent.parent
    found = shutil.which("conda")
    if found:
        return Path(found).resolve().parent.parent
    for base in CONDA_SEARCH_BASES:
        b = Path(os.path.expanduser(base))
        if (b / "bin" / "conda").is_file():
            return b
    sys.exit(
        "ERROR: no conda installation found (checked $CONDA_EXE, PATH, "
        f"{', '.join(CONDA_SEARCH_BASES)}). Install Miniconda/Anaconda "
        "first, or use --system ubuntu instead."
    )


# Minimal conda-forge package set to bootstrap a fresh 'gmtsar' env: GMT
# itself plus its two data companions (official GMT conda-forge install
# guidance), and the C libraries requirements.txt documents as NOT
# pip-installable (libtiff, hdf5, lapack). Deliberately excludes
# compilers/make/autoconf/csh/ghostscript/git -- do_conda_setup() keeps
# system gfortran/gcc in use on purpose (see its docstring), so --system
# conda still assumes those system build tools pre-exist; only --system
# ubuntu provisions them.
#
# Version guards (same floor-pin convention as requirements.txt -- pin
# what affects build/output correctness, leave pure-data packages
# unpinned): gmt is pinned to a minor version since a GMT upgrade can
# shift numerical output and this project's whole premise is bit-parity
# with a known-good GMT. hdf5/libtiff are linked into the C build and
# touch grid I/O -- an unpinned ABI/behavior change discovered months
# later would be hard to trace back to a conda solve. hdf5 specifically
# is pinned to an exact minor version (1.12.x), not just a floor + cap
# -- see the real build-failure note below. liblapack gets a floor pin
# (lower risk, narrow linear-algebra usage, but free to pin). gshhg-gmt/
# dcw-gmt are coastline/boundary DATA, not compute -- left unpinned.
#
# `gshhg-gmt-nc4` (2026-07-13, real clean-room test): NOT a real
# conda-forge package name -- `conda create` fails with
# PackagesNotFoundError. The correct package is `gshhg-gmt`.
#
# hdf5 pinned to 1.12.x, NOT a "floor + cap" range up to 2.x (2026-07-14,
# real clean-room test): this repo's own configure.ac/ax_lib_hdf5.m4
# HDF5 detection macro (outside gmtsar/python/, not something this
# project can patch) fails its compile-test against conda-forge's
# HDF5 1.14.3 h5cc wrapper ("Unable to compile HDF5 test program"),
# falls back to a broken HDF5_LIBS missing the base -lhdf5/-lhdf5_cpp
# (only -lhdf5_hl/-lhdf5_hl_cpp survive), and make_slc_nsr/make_slc_csk
# fail to LINK entirely ("undefined reference to H5Aread" etc) -- not a
# version-mismatch warning, a hard build failure with no binary
# produced. 1.12.2 is what the project's actual working reference conda
# env already has and is confirmed to configure/link cleanly.
#
# `flex` (2026-07-14, real clean-room test): documented as a conda-mode
# "assumed already present" system tool (see do_conda_setup's docstring)
# same as gfortran/g++/make/autoconf/csh/ghostscript -- but unlike a
# compiler, flex has no ABI/linkage implications for anything else in
# the build (it's a standalone code-generator invoked once to turn
# preproc/ERS_preproc/ers_line_fixer/ers_line_fixer.l into a .c file,
# nothing links against "libflex"). So unlike gfortran/g++ (which
# deliberately stay system-provided -- see do_conda_setup's docstring
# on why conda activation would break configure), it's safe AND more
# self-sufficient to bootstrap flex via conda-forge directly rather
# than only assume/document it -- confirmed on a real host where flex
# genuinely wasn't installed system-wide, breaking --system conda's
# "just works from a bare Miniconda install" promise for ERS_Hector_EQ
# and any other .l/.y-derived build.
CONDA_FORGE_BOOTSTRAP_PACKAGES = [
    "gmt=6.4", "gshhg-gmt", "dcw-gmt", "flex",
    "hdf5=1.12.*", "libtiff>=4.5,<5", "liblapack>=3.9",
]


def locate_conda_env(envname: str) -> Path:
    """Find an existing conda env named `envname`; if none exists, create
    it via `conda create -c conda-forge ...` so --system conda works on a
    brand-new host that already has *some* conda install but not yet the
    'gmtsar' env (network required for the create step).

    Real bug fixed 2026-07-13 (found by a genuine clean-room test, not
    a fixture): _find_existing_conda_env() only ever checks the fixed
    CONDA_SEARCH_BASES list (~/anaconda3, ~/miniconda3, /opt/conda).
    locate_conda_base() can resolve a DIFFERENT conda install entirely
    (via $CONDA_EXE or `conda` on PATH) -- e.g. a host whose conda lives
    at ~/anaconda_knox. When that happens, an env this function itself
    just created under conda_base/envs/<name> would NOT be found by
    re-scanning CONDA_SEARCH_BASES, incorrectly erroring "conda create
    exited 0 but the env still doesn't exist" even though it does. The
    post-create check (and a pre-create check) must look under the
    SAME conda_base that locate_conda_base() actually resolved, not a
    separately-guessed list."""
    existing = _find_existing_conda_env(envname)
    if existing is not None:
        return existing
    conda_base = locate_conda_base()
    # conda_base may not be one of CONDA_SEARCH_BASES -- check its own
    # envs/ dir directly before assuming a fresh create is needed.
    candidate = conda_base / "envs" / envname
    if candidate.is_dir():
        return candidate
    print(f"==> conda env '{envname}' not found; creating it via "
          f"{conda_base}/bin/conda create -c conda-forge "
          f"{' '.join(CONDA_FORGE_BOOTSTRAP_PACKAGES)} "
          "(this downloads packages -- needs network, may take a while)...")
    run([str(conda_base / "bin" / "conda"), "create", "-n", envname, "-y",
         "-c", "conda-forge"] + CONDA_FORGE_BOOTSTRAP_PACKAGES)
    if not candidate.is_dir():
        sys.exit(
            f"ERROR: conda create exited 0 but {candidate} still doesn't "
            "exist -- check the conda output above."
        )
    return candidate


def stage_execs(paths: list[Path], bin_dir: Path) -> None:
    """chmod +x each existing regular file, then symlink it into bin_dir
    (not copy, so edits to the source tree are picked up live). Shared by
    every "stage these onto PATH" step in --build.

    Directories in `paths` (e.g. utils/__pycache__, utils/build -- a glob
    over utils/* picks these up too) are skipped, not staged: they were
    never meant to land on PATH, and symlinking a directory then hitting
    a REAL (non-symlink) directory already at the destination on a later
    run would crash trying to unlink() it."""
    for f in paths:
        if not f.is_file():
            continue
        f.chmod(f.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        dst = bin_dir / f.name
        if dst.is_symlink() or dst.is_file():
            dst.unlink()
        elif dst.is_dir():
            print(f"WARN: skipping stage of {f.name} -- {dst} already "
                  "exists as a real directory, not a symlink; remove it "
                  "manually if it shouldn't be there.", file=sys.stderr)
            continue
        dst.symlink_to(f)


def do_ubuntu_deps() -> None:
    require_apt()
    print("==> Installing Ubuntu apt system dependencies...")
    sudo = sudo_prefix()
    run(sudo + ["apt", "update"])
    run(sudo + ["apt", "install", "-y"] + APT_SYSTEM_DEPS)


def do_conda_setup(conda_env: str) -> tuple[Path, dict[str, str]]:
    """Locate (or create, if missing -- see locate_conda_env) the conda
    env, then return its libs/includes as an explicit env-var dict for
    do_build to pass ONLY to the subprocess calls that need them --
    WITHOUT activating the env or mutating this process's own
    os.environ, so system gfortran/gcc stay in use (full conda
    activation pollutes CC/F77 and breaks configure) and so these
    build flags don't silently leak into every other subprocess this
    script runs. This is why --system conda still assumes the system's
    own compiler/build-tool chain (gfortran, g++, make, autoconf, csh,
    ghostscript) is already present, unlike --system ubuntu which
    provisions all of that itself via apt. flex is the one exception --
    bootstrapped via conda-forge instead of assumed present, since
    (unlike a compiler) it has no ABI/linkage implications for the rest
    of the build -- see CONDA_FORGE_BOOTSTRAP_PACKAGES's comment."""
    prefix = locate_conda_env(conda_env)
    print(f"==> Using conda env at {prefix} (no sudo)")
    extra_env = {
        "CPPFLAGS": f"-I{prefix}/include -I{prefix}/include/gmt",
        "LDFLAGS": f"-L{prefix}/lib -Wl,-rpath,{prefix}/lib",
        "PKG_CONFIG_PATH": f"{prefix}/lib/pkgconfig",
        # Real bug found 2026-07-14 (a genuine clean-room run, on a host
        # with 50+ unrelated conda installs on PATH): CPPFLAGS/LDFLAGS
        # alone are NOT enough. configure's HDF5 detection doesn't read
        # them -- it shells out to find `h5cc`/`h5pcc` (a compiler
        # wrapper script with ITS OWN baked-in flags) via a plain PATH
        # search, and without this, it silently picks up whichever
        # unrelated h5cc happens to be first on the ambient PATH. That
        # produced a real, non-obvious failure: build used one HDF5
        # version's headers, linked a DIFFERENT version's shared library
        # at runtime ("Headers are 1.12.1, library is 1.14.3"), and the
        # NISAR preprocessor (the only sensor pipeline that uses HDF5)
        # silently produced garbage/empty output with no hard error --
        # cascading into 6 downstream comparison failures with no
        # obvious root cause in any single error message. Prepending the
        # env's own bin/ to PATH makes `h5cc`/`h5pcc` resolve to the
        # SAME installation CPPFLAGS/LDFLAGS point at.
        "PATH": f"{prefix}/bin:{os.environ.get('PATH', '')}",
        # GNU Make's implicit .l.c rule invokes $(LEX), which defaults to
        # the LITERAL name "lex" -- not "flex". conda-forge's flex
        # package installs a `flex` binary; whether it also provides a
        # `lex` alias/symlink is not guaranteed across channels/versions,
        # so don't gamble on PATH resolution finding one. Overriding LEX
        # as an env var is honored by make's implicit-rule variable
        # substitution regardless of what's actually on PATH.
        "LEX": "flex",
    }
    return prefix, extra_env


def do_python_deps(use_conda: bool, conda_prefix: Path | None) -> None:
    if use_conda:
        requirements_txt = REPO_ROOT / "gmtsar" / "python" / "requirements.txt"
        print(f"==> Installing Python packages into conda env {conda_prefix} "
              "from requirements.txt ...")
        # requirements.txt is the single source of truth (2026-07-13: this
        # used to hardcode a separate, shorter list here that had drifted
        # out of sync -- missing scipy/numba/cython/h5py, which are required
        # for the default-ON compute kernels (xcorr_py, resamp_py,
        # SAT_llt2rat_py, gmt_surface_py) and make_slc_nsr_py. A fresh
        # install via this path left the framework broken out of the box.
        # Read from requirements.txt directly so the two lists can't
        # diverge again.
        run([str(conda_prefix / "bin" / "pip"), "install", "--upgrade",
             "-r", str(requirements_txt)])
    else:
        require_apt()
        print("==> Installing Python packages via apt...")
        sudo = sudo_prefix()
        run(sudo + ["apt", "install", "-y"] + APT_PYTHON_DEPS)
        run(sudo + ["python3", "-m", "pip", "install", "--upgrade"]
            + PIP_PYTHON_DEPS_UBUNTU)


def _patch_config_mk_line(lines: list[str], key: str, value: str) -> list[str]:
    """Replace an existing `key = ...` line's value. Matches `sed -i
    's|^KEY\\s*=.*|...|'`: a no-op if `key` isn't already a line in the
    file (configure always emits GMT_INC/GMT_LIB/TIFF_INC/TIFF_LIB, so
    this only ever fires on a present-but-wrong line)."""
    out = []
    for line in lines:
        if line.split("=", 1)[0].strip() == key:
            out.append(f"{key} = {value}\n")
        else:
            out.append(line)
    return out


def patch_config_mk(config_mk: Path, use_conda: bool,
                     conda_prefix: Path | None) -> None:
    """configure leaves GMT_INC/GMT_LIB/TIFF_*/HDF5_* empty or wrong, and
    the modern-linker muldefs flag must live in LDFLAGS (not CFLAGS)
    because the gmtsar/Makefile link rule uses $(LDFLAGS) only.

    HDF5_CPPFLAGS/HDF5_LDFLAGS (2026-07-14, real bug found by a genuine
    clean-room run): configure's HDF5 detection shells out to whatever
    h5cc/h5pcc is first on PATH at configure time -- on a shared host
    with 50+ unrelated conda installs, that's whichever one happened to
    be first, NOT necessarily the target conda env (do_conda_setup's
    PATH fix addresses the root cause for fresh builds, but a config.mk
    generated before that fix -- e.g. this repo's own -- stays wrong
    forever, since config.mk is never regenerated once present). Patch
    HDF5_CPPFLAGS/HDF5_LDFLAGS the same way as GMT/TIFF above; leave
    HDF5_LIBS alone since it only names link flags (-lhdf5 etc), not
    paths, so it isn't the part that goes stale."""
    lines = config_mk.read_text().splitlines(keepends=True)
    if use_conda:
        lines = _patch_config_mk_line(
            lines, "GMT_INC",
            f"-I{conda_prefix}/include -I{conda_prefix}/include/gmt")
        lines = _patch_config_mk_line(
            lines, "GMT_LIB", f"-L{conda_prefix}/lib -lgmt")
        lines = _patch_config_mk_line(lines, "TIFF_INC", str(conda_prefix / "include"))
        lines = _patch_config_mk_line(lines, "TIFF_LIB", str(conda_prefix / "lib"))
        lines = _patch_config_mk_line(lines, "HDF5_CPPFLAGS", f"-I{conda_prefix}/include")
        lines = _patch_config_mk_line(lines, "HDF5_LDFLAGS", f"-L{conda_prefix}/lib")
    if not any("-Wl,-z,muldefs" in line for line in lines):
        for i, line in enumerate(lines):
            if line.split("=", 1)[0].strip() == "LDFLAGS":
                lines[i] = line.rstrip("\n") + " -Wl,-z,muldefs\n"
                break
    config_mk.write_text("".join(lines))


def _fix_lex_source_mtimes() -> None:
    """Real bug found 2026-07-14: preproc/ERS_preproc/ers_line_fixer/
    ers_line_fixer.l is NOT lex source -- it's a troff man page that
    happens to share the "<name>.l" naming convention (also used for
    section-l man pages) with the real, committed, hand-written
    ers_line_fixer.c in the same directory. GNU Make's built-in `.l.c:`
    implicit rule doesn't know that; it regenerates X.c from X.l
    whenever X.l's mtime >= X.c's mtime. A `git clone` does not
    guarantee any particular relative mtime ordering between two files
    committed at different times in history -- on this host it produced
    a fresh clone where .l appeared newer, triggering a real, cascading
    build failure: `flex`/`lex` chokes trying to parse troff markup as
    lex rules ("bad character: .", hundreds of parse errors), the real
    ers_line_fixer.c is silently thrown away, and the binary never gets
    built (ERS_Hector_EQ fails downstream with zero comparisons).

    Fixed at the install.py level, not by editing the upstream Makefile
    (outside gmtsar/python/, not this project's to patch): touch every
    committed .c file that shares a basename with a .l file in the
    repo, so the implicit rule never fires on a fresh checkout. Only
    ers_line_fixer.c/.l exist in the whole repo today, but this is
    written generally in case that ever changes."""
    for l_file in REPO_ROOT.rglob("*.l"):
        if "/work/" in str(l_file) or "/.git/" in str(l_file):
            continue
        c_file = l_file.with_suffix(".c")
        if c_file.is_file():
            c_file.touch()
            print(f"==> touched {c_file.relative_to(REPO_ROOT)} "
                  f"(newer than {l_file.name}, which is not real lex "
                  "source -- see _fix_lex_source_mtimes)")


def do_build(use_conda: bool, conda_prefix: Path | None,
             extra_env: dict[str, str] | None = None) -> None:
    """extra_env (from do_conda_setup, empty for --system ubuntu) is
    passed ONLY to the subprocess calls below that need it (configure,
    make, make install) -- not applied as a global os.environ mutation,
    so it can't silently affect any other command this script runs."""
    print(f"==> Building gmtsar in {REPO_ROOT} ...")
    os.chdir(REPO_ROOT)
    _fix_lex_source_mtimes()
    build_env = None
    if extra_env:
        build_env = dict(os.environ)
        existing_pkg_config_path = build_env.get("PKG_CONFIG_PATH", "")
        build_env.update(extra_env)
        if existing_pkg_config_path:
            build_env["PKG_CONFIG_PATH"] = (
                f"{extra_env['PKG_CONFIG_PATH']}:{existing_pkg_config_path}")

    if not Path("configure").is_file():
        run(["autoconf"])
    run_soft(["autoupdate"])  # best-effort, matches `autoupdate || true`
    config_mk = REPO_ROOT / "config.mk"
    if not config_mk.is_file():
        configure_cmd = ["./configure", f"--prefix={REPO_ROOT}",
                          f"--with-orbits-dir={REPO_ROOT}/orbits"]
        if use_conda and conda_prefix is not None:
            h5cc = conda_prefix / "bin" / "h5cc"
            if h5cc.is_file():
                # Explicit, not just PATH-order-dependent: configure's
                # HDF5 detection walks PATH for h5cc/h5pcc unless told
                # exactly which one to use (see extra_env's PATH comment
                # in do_conda_setup for the real bug this closes).
                configure_cmd.append(f"--with-hdf5={h5cc}")
        run(configure_cmd, env=build_env)
    patch_config_mk(config_mk, use_conda, conda_prefix)

    # Sequential build: gmtsar's recursive Makefile has cross-dir
    # dependencies (preproc/* links against ../../gmtsar/libgmtsar) that
    # race under -j.
    run(["make"], env=build_env)
    run(["make", "install"], env=build_env)  # installs into $REPO_ROOT/bin via --prefix (no sudo)

    bin_dir = REPO_ROOT / "bin"
    py_utils = REPO_ROOT / "gmtsar" / "python" / "utils"
    stage_execs(sorted(py_utils.iterdir()), bin_dir)

    bin_py_dir = REPO_ROOT / "gmtsar" / "python" / "bin_py"
    stage_execs([bin_py_dir / name for name in BIN_PY_NAMES], bin_dir)

    # The canonical csh scripts (pop_config.csh, p2p_processing.csh, ...) so
    # they're on PATH via $GMTSAR/bin. make install does NOT do this
    # upstream.
    csh_dir = REPO_ROOT / "gmtsar" / "csh"
    stage_execs(sorted(csh_dir.glob("*.csh")), bin_dir)

    # Deprecated per-SAT csh wrapper shims (p2p_ALOS.csh ->
    # p2p_processing.csh ALOS, etc.) so legacy tarball READMEs from
    # topex.ucsd.edu/gmtsar/tar/ work out of the box. These names were
    # superseded by p2p_processing.csh's SAT dispatch years ago, but some
    # bundled READMEs still call them.
    csh_shims_dir = REPO_ROOT / "gmtsar" / "python" / "csh_shims"
    if csh_shims_dir.is_dir():
        stage_execs(sorted(csh_shims_dir.glob("*.csh")), bin_dir)

    # Build FFTW threading shim -- neuters fftwf_plan_with_nthreads at
    # runtime (LD_PRELOAD'd by runner.py). Without it, libgmt's
    # pthread-based FFTW spawns 14-19 threads per process and contends
    # across pipelines.
    py_dir = REPO_ROOT / "gmtsar" / "python"
    run(["gcc", "-shared", "-fPIC", "-O2",
         "-o", str(py_dir / "fftw_force_serial.so"),
         str(py_dir / "fftw_force_serial.c")])


def do_orbits() -> None:
    orbits_dir = REPO_ROOT / "orbits"
    print(f"==> Fetching ORBITS.tar (~5-7 GB) into {orbits_dir} ...")
    orbits_dir.mkdir(parents=True, exist_ok=True)
    os.chdir(orbits_dir)
    tar_path = orbits_dir / "ORBITS.tar"
    if not tar_path.is_file() and not (orbits_dir / "S1A").is_dir():
        run(["wget", "-c", "http://topex.ucsd.edu/gmtsar/tar/ORBITS.tar"])
    if tar_path.is_file():
        run(["tar", "-xf", str(tar_path)])
        tar_path.unlink()


def _git_sha(path: Path) -> str:
    try:
        out = subprocess.run(["git", "-C", str(path), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=5)
        return out.stdout.strip() if out.returncode == 0 else "unknown (not a git repo?)"
    except Exception as exc:
        return f"unknown ({exc!r})"


def _setup_log(args: argparse.Namespace) -> None:
    """Open this run's log file and write a header -- same "self-
    sufficient for backtracking" discipline as gmtsar_lib.run() and
    p2p_processing's env-gate dump: a UTC timestamp, the exact argv,
    resolved repo root, and every option that affects what this run
    does, so a bug found later doesn't require reconstructing "what did
    I actually run" from memory."""
    global _LOG_PATH
    log_dir = REPO_ROOT / "gmtsar" / "python" / "install_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = _utc_now().replace(":", "-")
    _LOG_PATH = log_dir / f"install_{ts}.log"
    _log_line(f"[{_utc_now()}] install.py log start")
    _log_line(f"  argv: {' '.join(sys.argv)}")
    _log_line(f"  repo root: {REPO_ROOT}")
    _log_line(f"  repo git sha: {_git_sha(REPO_ROOT)}")
    _log_line(f"  system: {args.system!r}  conda_env: {args.conda_env!r}  "
               f"rebuild: {args.rebuild}  orbits: {args.orbits}")
    _log_line(f"  python: {sys.version.split()[0]}  platform: {sys.platform}")
    _log_line(f"  log file: {_LOG_PATH}")
    print(f"==> Logging this run to {_LOG_PATH}")


def print_summary(conda_env: str) -> None:
    print(f"""
All requested steps completed.

To use gmtsar from this checkout, add to ~/.bashrc (or run in your shell):
  export GMTSAR={REPO_ROOT}
  export PATH=$GMTSAR/bin:$PATH

If you used --system conda, also put the conda env on PATH so 'gmt' is found
(the line above only adds $GMTSAR/bin):
  conda activate {conda_env}    # or: export PATH=$CONDA_PREFIX/bin:$PATH

Sanity check:
  which p2p_processing && p2p_processing
  gmt --version        # confirms gmt is reachable (needed for actual runs)

Full log of this run (every command, timestamped, with real output): {_LOG_PATH}
""")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--system", choices=["ubuntu", "conda"],
                        help="install everything for this system: system "
                             "deps (apt for ubuntu, a conda env -- created "
                             "if missing -- for conda), Python packages, "
                             "and the in-place build")
    parser.add_argument("--conda-env", default="gmtsar",
                        help="conda env name for --system conda "
                             "(default: 'gmtsar')")
    parser.add_argument("--rebuild", action="store_true",
                        help="skip the dependency steps, just rebuild + "
                             "re-stage (requires --system, for its build "
                             "flags/env, but not its deps steps)")
    parser.add_argument("--orbits", action="store_true",
                        help="also fetch ORBITS.tar (~5-7 GB); can be "
                             "combined with --system or run alone")
    args = parser.parse_args()

    if len(sys.argv) == 1:
        parser.print_help()
        return

    if args.rebuild and args.system is None:
        sys.exit("ERROR: --rebuild requires --system ubuntu or --system conda "
                  "(needed to resolve build flags, e.g. the conda env's "
                  "include/lib paths)")

    _setup_log(args)

    use_conda = args.system == "conda"
    conda_prefix: Path | None = None
    extra_env: dict[str, str] = {}

    if args.system == "ubuntu":
        if not args.rebuild:
            do_ubuntu_deps()
    elif args.system == "conda":
        conda_prefix, extra_env = do_conda_setup(args.conda_env)

    if args.system is not None:
        if not args.rebuild:
            do_python_deps(use_conda, conda_prefix)
        do_build(use_conda, conda_prefix, extra_env)

    if args.orbits:
        do_orbits()

    print_summary(args.conda_env)


if __name__ == "__main__":
    main()
