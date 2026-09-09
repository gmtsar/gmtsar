# v2.9.0 — `--system conda-full`: real full conda-toolchain isolation for install.py

## New: `--system conda-full`

`install.py --system conda-full` provisions the compiler/build-tool
chain via conda too (`gfortran_linux-64`, `gxx_linux-64`, `make`,
`autoconf`, `ghostscript`, `tcsh`), not just GMT/HDF5/TIFF/LAPACK —
genuinely no system packages required beyond a bare conda/miniconda
install. Plain `--system conda` still deliberately uses the system's
own compiler (see `do_conda_setup`'s docstring for why activation was
previously avoided); `conda-full` is the new, real opt-in for full
isolation.

Confirmed feasible and correct via multiple real clean-room builds this
session (fresh `git clone` + fresh conda env each time, no reuse) —
not a design-only claim. `do_conda_setup(full_isolation=True)` resolves
conda-forge's target-triplet-prefixed compiler binaries
(`x86_64-conda-linux-gnu-{gcc,g++,gfortran}` — conda-forge's compiler
packages don't install plain-named `gcc`/`g++`/`gfortran`, only these,
meant to be picked up via env activation) and sets `CC`/`CXX`/`F77`
explicitly to them, still only in the subprocess-only `extra_env` dict
this script has always used — plain `--system conda`'s "never mutate
this process's own environment" discipline is unchanged.
`_check_conda_full_isolation_tools()` verifies a reused pre-existing
env actually has the full tool set, and creates a `csh -> tcsh` symlink
(no plain `csh` package exists on conda-forge — confirmed by search;
only `tcsh`, which Debian/Ubuntu's own `csh` package itself just wraps).

## Real GMTSAR source bug found: `fitoffset.c`'s `strlcpy` on GCC 14+

`gmtsar/fitoffset.c` calls `strlcpy()` with no declaration/include
anywhere. Implicit-declaration is only a *warning* on GCC < 14 (e.g.
the system compiler `--system conda` uses today), a **hard compile
error** on GCC 14+ (conda-forge's `gxx_linux-64` package is 15.2.0 —
GCC 14 promoted implicit function declarations to an error by default,
part of C23 alignment). Confirmed directly: identical source, no
`-Werror` passed, GCC 11.4.0 → warning + successful link; GCC 15.2.0 →
hard error. **Not conda-full-specific** — will also eventually break
`--system ubuntu` on any host shipping GCC 14+ (Ubuntu 24.10+, Fedora
40+, Arch already do).

Fix (`strlcpy` → `snprintf`, identical behavior for the fixed short
literals involved) is staged at `gmtsar/python/c_fixes/fitoffset.c` and
applied as a **build-time patch for every `--system` mode**
(`_apply_c_fixes()`, called from `do_build()`) — NOT committed to the
real `gmtsar/fitoffset.c` directly, per this repo's "everything outside
`gmtsar/python/` is upstream and stays untouched for clean merges" rule.

## Two more real bugs, found by the conda-full clean-room test itself

- `CONDA_FORGE_BOOTSTRAP_PACKAGES` never listed `pip` explicitly —
  `python` is pulled in transitively (via `gdal`'s python bindings, a
  `gmt` dependency) but `pip` is not guaranteed to be. A genuinely
  fresh env (either `conda` or `conda-full`) hit `FileNotFoundError` on
  `bin/pip` during `do_python_deps` — every earlier manual test this
  session happened to reuse a pre-existing env that already had `pip`
  from unrelated prior setup, masking this until an actual from-scratch
  env creation exposed it.
- The FFTW threading shim build hardcoded literal `"gcc"` with no
  `env=` passed, silently using the ambient PATH's (system) `gcc` even
  under `--system conda-full` — defeating `conda-full`'s actual purpose
  on a box with no system compiler at all. Now uses the resolved `CC`
  from `build_env` when set, falling back to `"gcc"` only for plain
  `conda`/`ubuntu`.

## `locate_conda_env` prefers `micromamba` when present

Real bug found during this session's own manual clean-room testing
(before any of the above was wired in): classic `conda`'s solver
(pre-libmamba-solver, e.g. `conda 4.14.0`) fell back from the fast
repodata index to the full one and hung **28+ minutes with zero
output** solving the real `CONDA_FORGE_BOOTSTRAP_PACKAGES` set — a
known classic-solver failure mode on older hosts, not specific to any
one package. `micromamba` (a standalone binary, no bootstrapping
chicken-and-egg) solved and installed the identical package set in
under a minute. `locate_conda_env()` now prefers `micromamba` for the
actual `create` call when found on `PATH`, falling back to classic
`conda create` (with a printed warning it may be slow) otherwise.

This exposed a real test-isolation gap in an existing unit test
(`test_locate_conda_env_creates_when_missing_at_resolved_base`), which
mocked `install.run` but not `shutil.which` — a real `micromamba`
happening to be on the test host's own `PATH` bypassed the test's fake
conda mock entirely. Fixed by explicitly forcing the classic-conda path
that test exercises; added a new test,
`test_locate_conda_env_prefers_micromamba_when_present`, covering the
micromamba path itself (not previously covered at all).

## `install.py --system conda`: fail-fast pre-flight check for missing system build tools

Plain `--system conda` deliberately assumes the system already
provides `gfortran`/`g++`/`make`/`autoconf`/`csh`/`ghostscript` (see
`do_conda_setup`'s docstring). No pre-flight check existed for this —
a missing tool surfaced as a cryptic `autoconf`/`make` error deep
inside the build. `_check_system_build_tools()` now checks up front and
exits with a clear, actionable message naming exactly which tools are
missing and how to install them.

## Housekeeping: stale `insarhub-api` scaffold removed

A v0 `GMTSAR_S1` processor scaffold was staged directly in this repo
before InSARHub development moved to the dedicated
`dunyuliu/InSARHub-GMTSAR-dev` fork (this repo stays at its own version
line per project direction). Dead weight, removed.

## Renamed `--system conda-full` -> `conda-linux-full`; platform scope documented for both conda modes

Neither conda-backed `--system` choice had ever documented what
platforms it actually covers.

- `conda-linux-full` is genuinely Linux x86_64-only — conda-forge's
  compiler-activation packages are per-target
  (`gfortran_linux-64`/`gxx_linux-64`), macOS/ARM would need entirely
  different package names, not implemented here. Renamed from
  `conda-full` to make this explicit in the flag itself.
  `_check_conda_linux_full_platform()` fails fast with a clear message
  on any other platform, instead of `conda create` silently erroring
  on unknown package names.
- Plain `--system conda` was never actually Linux-restricted — it
  defers entirely to whatever compiler is already on the system's
  `PATH` (Homebrew's `gfortran`/`gcc` on macOS works the same as a
  Linux distro's apt-installed ones), and every package in
  `CONDA_FORGE_BOOTSTRAP_PACKAGES` has cross-platform conda-forge
  builds. Just never documented which platforms it actually covers
  until now.

## Release-boundary verification (this release)

`tests/test_install.py --system conda --full` (fresh clone, fresh
conda env, per Rule 15) run at HEAD:

- `install.py` real build+install: **PASS in 82.3s**.
- `gmtsar_sharedir.csh` (upstream sanity check): **PASS**.
- `bin_py/tests/` (620 tests): initially caught the real
  `micromamba`-preference test-isolation regression above (1 failed,
  560 passed, 59 skipped) — fixed and re-verified standalone (14/14 in
  `test_install_config.py`, the file containing both the fix and the
  new coverage) before the sweep phase; the clean-room clone under test
  predates that fix commit, so its own `bin_py/tests/` run still shows
  the pre-fix failure — a real, separately-confirmed-fixed issue, not
  a live gap.
- `sweep.py --full` (all 21 real py-vs-csh cases, ~3h wall):
  **152/161 comparisons SUCCESS**. Two real failure clusters,
  both root-caused, neither caused by anything in this release:
  - `ALOS_haiti`: `los_ll.grd` — the same accepted flake documented in
    `v2.8.0`'s release notes (inherent snaphu cycle-slip
    nondeterminism, not a code bug).
  - `S1_Ridgecrest_EQ`: 8 failures, all `F1`/`F2`/`F3`/`H_res`
    intf-level files. Root-caused directly: the cached csh reference
    ("oracle") for this case is missing its `F1`/`F2`/`F3` directories
    entirely (confirmed via `ls` — they don't exist on the csh side at
    all, while the Python side has complete, real output at the same
    paths), has no `.oracle_built` sentinel, and the sweep itself
    flagged it live: `WARN: oracle has no sentinel (.oracle_built) —
    grandfathered as valid`. A stale/incomplete cached csh oracle
    predating whatever expanded this case's comparison scope to
    include `F1`/`F2`/`F3` — a real, pre-existing test-infrastructure
    gap, not a regression from anything in this release. Needs a real
    csh oracle rebuild for `S1_Ridgecrest_EQ` to resolve — tracked as a
    follow-up, not done this release (would need real, multi-hour csh
    processing time beyond this release's scope).
- `--system conda-linux-full` itself: confirmed via multiple real
  clean-room builds this session (fresh clone + fresh env each time) —
  real binaries (`esarp`, `xcorr`, `phasefilt`, `p2p_processing`, ...)
  built, linked, and ran correctly, `ldd` showed zero missing shared
  libraries, `gmt --version`/`gmt grdinfo` both worked from the
  fully-isolated env. Not yet covered by `tests/test_install.py`
  itself (`--system` choices there are still `{ubuntu, conda}` only) —
  a real follow-up, not done this release.

## Commits

`4ba030f`..`3fa0fbf` (9 commits since `v2.8.0`).
