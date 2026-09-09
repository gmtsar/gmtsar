# v2.10.0 — `--system conda-windows-full`: native Windows install (no WSL, no MSYS/Cygwin toolchain)

## New: `--system conda-windows-full`

`install.py --system conda-windows-full` builds and runs GMTSAR natively on
Windows — no WSL, no MSYS2/Cygwin userland, no admin rights. Bootstraps
a conda env with the Windows-native build toolchain
(`m2w64-toolchain`, `cmake`, `ninja`, plus `gmt`/`openblas`/`libtiff`
per the usual `CONDA_FORGE_BOOTSTRAP_PACKAGES`), builds via CMake/Ninja
against it (the existing `./configure && make` path is POSIX-shell/
Makefile-only and doesn't target Windows library layouts), and stages
the Python framework + `.csh` scripts into `bin/` exactly like the
other `--system` modes.

The one thing this mode does still depend on: Git for Windows, for a
real POSIX shell (`gmtsar_lib.py` shells out via Git Bash for syntax —
`ln -sf`, `rm -rf`, `mkdir -p`, `&&` — that `cmd.exe` can't run). Nearly
universal on Windows dev/science machines already; `gmtsar/python/
distribute_gmtsar_windows.py` (new, WIP) packages a fully self-contained
bundle that includes a minimal Git Bash for machines that don't have it.

## `gmtsar/CMakeLists.txt` / `CMakeLists.txt`: closing real gaps in the CMake build

The CMake path (previously exercised only incidentally, never as a
release target) was missing real coverage the Makefile has had for
years:

- 11 C programs built by `make` but never added to CMake's
  `add_executable`/`install(TARGETS ...)`: `update_PRM`, `get_PRM`,
  `nearest_grid`, `fitoffset`, `solid_tide`, `p_scatter`,
  `split_spectrum`, `cut_slc`, `split_aperture`,
  `phasediff_get_topo_phase`, `geocode_slc`. `update_PRM` specifically
  is on the hot path for every pre-processing run (`pre_proc` calls it
  directly) — its absence broke every case at the very first
  Preprocess stage.
- `share/gmtsar` (filter kernels, snaphu configs, virgin PRM templates)
  was never installed by the CMake path at all — only the Makefile's
  `install:` target populated it. Without it, `filter`'s Gaussian
  filtering (`gauss15x5` etc.) failed outright.
- `libgmtsar`'s object list was missing `stringutils.c`,
  `update_PRM_sub.c`, `rng_filter.c`, `lib_strfuncs.c` — present in the
  Makefile's `LIB_C` but never added to CMake's `add_library`, breaking
  the link step for anything calling into them (`update_PRM`,
  `get_PRM`, `fitoffset`).
- WIN32-only: a `dlltool`-generated minimal import library exporting
  just `dgelsy_` (the one LAPACK routine GMTSAR actually calls),
  working around a real MinGW binutils bug where linking against the
  *full* `openblas.lib` (~77,000 exported symbols) corrupts the
  resulting DLL at runtime regardless of which function is called —
  isolated with a minimal repro, not specific to GMTSAR's own code. A
  `sys/mman.h` shim (`gmtsar/compat_win32/`, `mmap`/`munmap` over
  `CreateFileMapping`) for `sbas_utils.c`/`resamp.c`/`sbas.c`, which
  `#include <sys/mman.h>` (not provided by MinGW). A `getline()` shim
  (same directory) for `fitoffset.c`, force-included for that one
  target only via `target_compile_options(-include ...)` rather than
  editing the `.c` file — mingw-w64's runtime doesn't export this
  glibc/POSIX extension.

## Real GMTSAR source bug found: `conv.c` opens binary files in text mode

`gmtsar/conv.c` opens the raw complex SLC file and the `.grd=bf`
native-binary-float file with `fopen(path, "r")` — **text mode**.
Invisible on POSIX (`"r"`/`"rb"` are identical there), but on Windows
text mode makes the CRT translate `\r\n` → `\n` on read and treat byte
`0x1A` as an EOF marker, silently corrupting or truncating a binary
stream partway through the file.

Root-caused from a real, visually-obvious symptom, not a synthetic
test: `filter`'s `conv`-based amplitude/correlation formation
(`amp1.grd`/`amp2.grd`/`realfilt.grd`/`imagfilt.grd`) produced a
correlation grid that was 84.8% *exactly* zero on a real RS2 pair
(median correlation 0.0) — collapsing the geocoded, masked
interferogram to a thin diagonal sliver of real fringes surrounded by
blank space, instead of full-swath coverage. Confirmed as a Windows-
only binary-mode bug, not a Python-port logic bug, two ways: (1) a
direct synthetic repro — `conv.exe` reading a hand-written `.grd=bf`
file with a known NaN block via `fopen(..., "r")` silently produced
non-NaN garbage past the corruption point, clean via `"rb"`; (2) the
*identical* Python framework code, same commit, produces a
near-machine-precision match against the real C/csh reference on Linux
(`corr_ll.grd` RMS 9.7e-7, `phasefilt.grd` complex-RMS 2.2e-5) — ruling
out the algorithm itself.

**Fix**: both `fopen(path, "r")` call sites → `fopen(path, "rb")`.
Identical behavior on POSIX. Staged at `gmtsar/python/c_fixes/conv.c`
per the `fitoffset.c` convention from v2.9.0 (real fixes to upstream
`gmtsar/*.c` staged in `gmtsar/python/`, not edited in place, so
`gmtsar/gmtsar/` stays a clean diff against upstream) and applied
automatically at build time by `_apply_c_fixes()` — which this release
also wires into `do_windows_build()` (previously only called from
`do_build()`, so the Windows path silently skipped both this fix and
v2.9.0's `fitoffset.c` one until now).

## `gmtsar_lib.py`: two real Windows-only bugs in the Git Bash routing itself

- **Race condition**: `_win_bash()` set its "already resolved" flag
  *before* actually assigning the resolved path, memoized across the
  whole process. `gmtsar/python/tests/case_runner.py` runs two threads
  concurrently per case (`csh_slot`/`py_slot`, or their `topo-mode-ab`
  equivalents) — a thread racing in during that window read
  `_WIN_BASH_RESOLVED = True` but `_WIN_BASH` still `None`, silently
  falling through `shell_run()`'s `shell=True` fallback into
  `cmd.exe`. Confirmed directly: one of two concurrent `cleanup all`
  calls failed with `cmd.exe`'s `'cleanup' is not recognized...` while
  the other succeeded, same run. Fixed with a real `threading.Lock`.
- **PATH format**: an earlier iteration of this release's Windows PATH
  handling pre-converted `PATH` to POSIX/MSYS form (`/c/...`) before
  handing it to the `bash -c` subprocess, on the theory that bash's own
  command lookup needs a POSIX-style `PATH`. This is true for bash's
  *own* lookups, but broke every single `.exe` bash then launched:
  Windows' PE loader resolves DLL dependencies (`gmt.dll`,
  `openblas.dll`, ...) via the *Windows-style* `PATH` in the process's
  environment block, which it cannot parse in `/c/...` form — silently
  producing `STATUS_DLL_NOT_FOUND`, surfaced by `gmtsar_lib.run()` as a
  bare, message-free `rc=127`. Confirmed via a direct `CreateProcess`
  repro bypassing bash entirely: POSIX-form `PATH` → `0xC0000135`;
  Windows-form `PATH` → clean run. Fixed by never touching `PATH`'s
  format at all — Git Bash's own MSYS runtime already handles the
  POSIX-view-internally / Windows-view-to-children duality correctly
  on its own; the only real bug was PATH going stale/wrong-format
  across nested bash→python→bash hops, fixed by threading the
  pristine Windows-style value through explicitly (`GMTSAR_WIN_PATH`)
  rather than trusting whatever the immediate parent process's own
  `PATH` currently held.

## Windows staging: copy-not-symlink breaks sibling-file/package imports

Every other `--system` mode symlinks staged files into `bin/`
(`stage_execs`) — edits to the source tree are picked up live, and a
script's `__file__`, resolved through the symlink, still points at its
real location alongside its siblings. Windows has no reliable
unprivileged symlink, so `stage_execs` copies instead (existing
behavior, unchanged this release) — but that silently breaks every
staged script that locates a sibling module/package relative to
`__file__`:

- `bin_py/{SAT_baseline_py,SAT_llt2rat_py,make_los_py,make_slc_s1a_py,
  phasediff_py}`: `sys.path` insertion assumed `_HERE.parent` still
  contained a `utils/` sibling (true when `_HERE` resolves through a
  symlink back to `bin_py/`; false when it's a flat copy in `bin/`).
  Now falls back to `$GMTSAR/gmtsar/python/utils` when the naive
  relative guess doesn't exist.
- `phasediff_py` additionally dynamically loads `_gmt_native_bf.py`
  from its own directory (`importlib.util.spec_from_file_location`) —
  never staged into `bin/` at all on Windows since it isn't a `bin_py`
  entry point in its own right. `install.py` now stages it alongside
  `phasediff_py` explicitly.
- `utils/filter` shelled out to `gmtsar_sharedir.csh` (a POSIX-only
  script Windows can't exec directly without going through Git Bash)
  to resolve the share directory; now calls `gmtsar_lib.resolve_sharedir()`
  directly, which does the identical lookup in-process.
- `utils/intf` and `case_runner.py` called `subprocess.run(["cleanup",
  ...])`/`["pop_config", ...])` directly — extensionless shebang
  scripts Windows' `CreateProcess` cannot exec (it only auto-appends
  `.exe` to a bare name, and there is no `cleanup.exe`). Routed through
  `gmtsar_lib.shell_run()` (Windows: `bash -c`) instead.

## `gmtsar/python/tests/{sweep,case_runner,cases}.py`: three real, platform-agnostic bugs found via Windows testing

None of these are Windows-specific bugs — they were latent on every
platform, just never triggered on POSIX:

- `sweep.py` and `case_runner.py` each hardcoded `":"` instead of
  `os.pathsep` when building a `PATH` value. Harmless on POSIX
  (`os.pathsep == ":"` there), silently produces a malformed `PATH` on
  Windows.
- `cases.py` built `cshRefRoot`/`pythonRunRoot`/etc. via
  `workAbsoluteDir + "ref_test/"` — a literal forward slash appended
  after a path already using `os.sep`. On Windows this leaves a mixed-
  separator path whose trailing character is `/`, not `os.sep`; a
  downstream `.rstrip(os.sep)` (used to derive the tree's directory
  *name* for building the per-case output path) then does nothing,
  `os.path.basename()` of a separator-terminated path returns `""`,
  and both the "csh"/mode-0 and "python"/mode-1 trees for
  `--topo-mode-ab` silently collapsed into the *same* directory —
  both threads writing the same case concurrently, corrupting each
  other's output, while `case_runner.py` still reported success.
  Fixed by using `os.sep` consistently.
- `case_runner.py`'s `_run_recipe()` invoked the recipe via a bare
  `["bash", ...]`, trusting `PATH` order to find Git Bash. Windows 10+
  ships a `System32\bash.exe` stub that launches WSL — if it resolves
  first (a real, not hypothetical, `PATH`-ordering outcome), the
  entire recipe run silently no-ops against a WSL "no installed
  distributions" prompt instead of Git Bash, while `case_runner.py`
  still reports success. `gmtsar_lib._win_bash()` already guards
  against exactly this for every other bash invocation in the
  framework (checks real file presence, rejects anything resolving
  under `system32`); `_run_recipe()` now uses the same resolution
  instead of a bare name.

## `gmtsar/python/distribute_gmtsar_windows.py` (new, WIP)

Packages a working `--system conda-windows-full` build into a self-
contained, relocatable bundle — no conda, no Git for Windows required
on the target machine:

- `conda-pack`s the env's Python runtime (numpy/scipy/numba/netCDF4/
  matplotlib/h5py/...), excluding build-only content a *user* of the
  pre-built binaries never needs (`m2w64-toolchain`, headers, debug
  symbols) — full env ~3.5GB, runtime-only subset a fraction of that.
- Recursively resolves every non-system DLL the built `.exe`/`.dll`
  files depend on (`objdump -p`, BFS over the PE import table;
  "system" determined by real presence in `System32`/`SysWOW64`, not a
  maintained name-pattern list) and copies them alongside the `.exe`
  files — this is what makes the `.exe`s runnable without the conda
  env on `PATH`, the same DLL-resolution issue as this release's
  `conv.c` fix, solved here by co-location instead of by `PATH`.
- Bundles a minimal Git Bash (`bash.exe`, `msys-2.0.dll`, the specific
  coreutils the framework's `shell_run()` calls actually invoke).
- `--verify` runs every staged `.exe` and the bundled `python` under a
  deliberately **isolated** `PATH` (Windows system dirs + the bundle
  only — no conda, no Git) to prove the bundle is genuinely self-
  contained rather than passing only because the dev machine's own
  toolchain is still on `PATH`. Caught a real gap in an earlier version
  of this check: a naive `PATH.prepend()` verify passed even with 27 of
  38 `.exe` files unable to start standalone.

Not yet done: a full pipeline (RS2 case) run against the packaged,
zipped bundle on a machine with nothing else installed — the real bar
for "self-contained," intentionally left as a follow-up given this
release's scope.

## Release-boundary verification (this release)

`install.py --system conda-windows-full` from a **fully clean slate**
(`bin/`, `lib/`, `share/`, `build-win/` all wiped, not just
`--rebuild`): 159/159 CMake/Ninja build steps, 0 errors, all 41 `.exe`
files + `share/gmtsar` data + Python/`.csh` staging installed
correctly.

`sweep.py --topo-mode-ab` (no `csh`/`tcsh` interpreter exists on
Windows at all, so this release's verification substitutes a
`topo_interp_mode` 0-vs-1 comparison for the normal py-vs-csh one —
see `cases.py`'s existing `TOPO_MODE_AB` machinery) against that clean
build: `RS2_SLC_Hawaii` **6/6 comparisons SUCCESS** — SSIM ≥0.999 on
all three images, grid RMS ≤0.0007 — matching, to within normal
floating-point variation, a real py-vs-csh run's numbers from the same
commit on Linux (`corr_ll.grd` RMS 9.7e-7 vs this release's 4.1e-4;
both far inside the 0.01 threshold).

Not yet done, tracked as real follow-ups rather than silently out of
scope: a true py-vs-csh comparison on Windows (blocked on no `csh`/
`tcsh` for Windows existing at all — `--topo-mode-ab` is a real but
imperfect substitute); the full 21-case sweep (`--full`) on Windows,
run so far only for the fast-tier `RS2_SLC_Hawaii` case; `bin_py/
tests/` on Windows; `distribute_gmtsar_windows.py`'s packaged-bundle
verification beyond the isolated-`PATH` `.exe`/`python`/bash smoke
checks described above.

## Commits

`v2.9.0`..`v2.10.0`: the `conda-windows-full` work (previously developed
against a shallow clone of upstream `gmtsar/gmtsar` at the commit
matching this fork's own `v2.8.0`, rebased onto `v2.8.0` directly) plus
this release's merge of `v2.9.0`'s `conda-linux-full` work.
