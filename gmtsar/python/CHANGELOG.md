# Changelog

All notable changes to the GMTSAR Python framework live here.

## [Unreleased] — 2026-05-14

### Added
- **`install.sh`** — consolidated installer for the Python framework. Single script replaces three (`install.gmtsar.ubuntu.sh`, `install.packages.for.python.testing.sh`, `fetch-orbits.sh`). Independent flags: `--ubuntu`, `--conda`, `--python`, `--build`, `--orbits`, `--all`. Builds gmtsar **in-place** from the checkout (no `/usr/local` install, no re-clone). Handles two dependency-install modes: system apt (sudo) or an existing conda env (`--conda`, no sudo).
- **`fftw_force_serial.so`** — LD_PRELOAD shim that neuters `fftwf_plan_with_nthreads()`. Built by `install.sh --build` from `fftw_force_serial.c`. Eliminates ~10× test-runner slowdown caused by libgmt's transitive `libfftw3f_threads` linkage spawning 14–19 FFTW worker threads per process; env vars like `OMP_NUM_THREADS` don't reach FFTW's pthread path.
- **`utils/xcorr_py`** — vectorized Python re-implementation of the C `xcorr` binary using batched `scipy.fft.fft2(..., workers=-1)`. Drop-in alternative for the freq-domain mode (most common path); covers complex int16 SLC data for RS2/ERS/ENVI/TSX/CSK/ALOS/S1. Outputs C-compatible `freq_xcorr.dat`. (Not yet wired into recipes — opt-in.)
- **`TEST_CASES=…` env override** in `testingSystem/pathListForTest.py` — run a subset of cases (e.g. `TEST_CASES=ERS_Hector_EQ,ALOS_Baja_EQ python3 runAllTest.py`) without editing source.

### Changed
- **`testingSystem/runAllTest.py`** rewritten:
  - Cases now fan out to background bash subprocesses (`subprocess.Popen` with `start_new_session=True`) instead of a serial Python loop. Each case's csh + Python recipes run in parallel.
  - `LD_PRELOAD` shim path resolved relative to `__file__` (no hardcoded absolute paths).
  - `checkTest.py` is invoked in-process via `runpy.run_path` (was `os.system('python3 ...')` — avoided cold-start re-importing scipy/skimage).
  - SIGINT/SIGTERM handler kills the whole process tree (no more orphaned `csh`/`p2p_processing` after Ctrl-C).
  - Per-case READMEs staged via `shutil.copy2` instead of `os.system('cp ...')`.
  - All threading env vars pinned (`OMP_NUM_THREADS=1`, etc.) inside the per-case shell script.
  - Performance summary printed at end (wall-clock + per-stage timings from `timeSpentLog.txt`).
  - Top-level script logic moved into `main()` guarded by `if __name__ == '__main__'` (no side effects on import).
- **`testingSystem/pathListForTest.py`** — work directory now resolves to `gmtsar/python/work/` by default (was hardcoded `/scratch/gmtsar.py.dev/py.test/`). `$SCRATCH` env override still supported. Adds per-tree roots `pythonRunRoot` and `cshRefRoot` (was an undocumented mix of `py.test`/`csh.test` literal strings in `checkTest.py`).
- **`testingSystem/checkTest.py`** — comparison thresholds extracted into named dicts (`PNG_SSIM_THRESHOLD`, `GRD_RMS_THRESHOLD`) with per-file overrides; previously buried as stringly-typed `'phase' in fileName` checks. Phase-named outputs use a relaxed SSIM threshold (0.95) since pixels near the 0/2π wrap boundary flip values for tiny phase differences. `skimage.metrics.structural_similarity` argument updated from deprecated `multichannel=True` → `channel_axis=-1` (required by scikit-image ≥ 0.19).
- **`utils/pop_config`** — RS2/TSX `dec_factor` default changed from `1` to `2` to match `pop_config.csh`. Previously produced 4× more pixels than csh, making outputs incomparable for testing. Override to 1 in your own `config.py` if you want higher-resolution images.
- **Default work directory layout** (`work/`) — three trees: `dataset/<case>.tar.gz` for downloaded archives, `csh_test/<case>/` for legacy csh-pipeline outputs, `python_test/<case>/` for Python-pipeline outputs. Same tarball is extracted into both trees so each is self-contained.

### Fixed
- **`utils/filter`** — resolved an unmerged git conflict (`<<<<<<< HEAD … >>>>>>> upstream/master`) at line 57 that was causing `SyntaxError: invalid syntax` whenever the script ran. This was the root cause of the Python pipeline producing no interferogram outputs (`corr.grd`, `phasefilt.grd`, etc.). Resolution: keep the dynamic `gmtsar_sharedir.csh` lookup (portable across install prefixes); drop the hardcoded `/usr/local/GMTSAR/share/gmtsar` alternative.
- **`utils/gmtsar_lib.py`** — `grep_value()` returned the local variable `val` even when no line matched the search pattern, raising `UnboundLocalError`. Initialize `val = ""` before the loop so missing keys return an empty string instead of crashing.
- **`testingSystem/checkTest.py`** — `parseCmdOutput()` had the same uninitialized-variable bug as `grep_value`. Now returns `NaN` when the search string isn't found.
- **csh script permissions** — upstream ships `gmtsar/csh/*.csh` non-executable (mode 0644). `install.sh --build` now `chmod +x`'s them before symlinking into `bin/`, so `pop_config.csh`, `p2p_processing.csh`, etc. are runnable via `$PATH`. Was failing with `Permission denied` previously.
- **gmtsar binary install** — top-level `make all` was silently skipping the binaries in `gmtsar/` (only `preproc/` built). `install.sh --build` now patches `config.mk` to set `GMT_INC`/`GMT_LIB`/`TIFF_INC`/`TIFF_LIB` (configure leaves these empty when GMT is in a conda prefix) and adds `-Wl,-z,muldefs` to `LDFLAGS` so modern linkers accept gmtsar's duplicate common symbols. Result: 184 binaries installed instead of 39 (missing core binaries: `xcorr`, `esarp`, `update_PRM`, `calc_dop_orb`, `SAT_baseline`, etc.).

### Removed
- **`install.gmtsar.ubuntu.sh`** — folded into `install.sh --ubuntu --build`.
- **`install.packages.for.python.testing.sh`** — folded into `install.sh --python`.
- **`fetch-orbits.sh`** — folded into `install.sh --orbits`.
