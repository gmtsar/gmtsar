# GMTSAR Python framework

## Installation

One consolidated installer: `gmtsar/python/install.sh`. It builds gmtsar **in-place** from this checkout (no system-wide install, no re-clone). Each step is an independent flag — combine as needed:

| Flag | What it does |
|---|---|
| `--ubuntu` | apt-install system deps (csh, gmt, gfortran, …) — **requires sudo** |
| `--conda`  | use an existing conda env for build deps + Python packages — **no sudo**. Default env name `gmtsar` (override with `CONDA_GMTSAR_ENV=<name>`). Mutually exclusive with `--ubuntu`. |
| `--python` | install Python packages (skimage, xarray, netcdf4, tk, …) into apt or the conda env, depending on mode |
| `--build`  | autoconf + configure + make + make install (lands in `<repo>/bin`); also builds the FFTW shim and symlinks Python utils + csh scripts into `<repo>/bin` |
| `--orbits` | fetch `ORBITS.tar` (~5-7 GB) into `<repo>/orbits` |
| `--all`    | shortcut for `--ubuntu --python --build` (omits the large orbits download) |

Typical first runs:
```
# Ubuntu / sudo path:
bash gmtsar/python/install.sh --all

# Shared-server / no-sudo path:
bash gmtsar/python/install.sh --conda --python --build
```

Then export the env vars printed at the end:
```
export GMTSAR=<this repo>
export PATH=$GMTSAR/bin:$PATH
```

Sanity check:
```
p2p_processing
```
should print the help message.

# Testing for developers

The test runner writes everything under a single work directory, resolved in this order:

1. `$SCRATCH/py.test/` — used if the `SCRATCH` environment variable is set
2. `gmtsar/python/work/` — default (inside this Python folder; gitignored)

Layout under the work directory:

```
<workdir>/
├── dataset/<caseName>.tar.gz    # downloaded raw tarballs (topex sample archive)
├── pythonREADME/                # per-case Python run scripts (README_<caseName>.txt)
├── python_test/<caseName>/...   # Python framework run outputs
└── csh_test/<caseName>/...      # legacy csh reference results
```

For each case, `runAllTest.py`:
1. Downloads `<caseName>.tar.gz` from `topex.ucsd.edu/gmtsar/tar/` into `dataset/` (if not cached).
2. Extracts the tarball **into both trees** — `csh_test/<caseName>/` and `python_test/<caseName>/` — so each tree is a fully self-contained dataset.
3. In `csh_test/<caseName>/`: runs the **bundled `README.txt`** (the legacy csh recipe shipped in the tarball) with `csh README.txt > log.txt 2>&1`. Skipped if the tree already has `.grd`/`.png` outputs.
4. In `python_test/<caseName>/`: copies `pythonREADME/README_<caseName>.txt` (your Python recipe) into the dir and runs it with `./README_<caseName>.txt > log.txt 2>&1`.
5. After all cases finish, `checkTest.py` diffs the `.grd`/`.png` outputs between the two trees and reports SUCCESS/FAIL per file.

Run all cases:
```
cd gmtsar/python/testingSystem
python3 runAllTest.py
```

Run a subset (handy for iteration):
```
TEST_CASES=ERS_Hector_EQ,ALOS_Baja_EQ python3 runAllTest.py
```

Each case runs in its own background bash subprocess (`subprocess.Popen` with `start_new_session=True`); cases execute in parallel and the driver waits for all to finish before invoking `checkTest.py` in-process via `runpy`.

## Sample datasets

Test inputs come from the GMTSAR sample archive:
```
http://topex.ucsd.edu/gmtsar/tar/{caseName}.tar.gz
```
The full case list and per-case archive names are defined in `gmtsar/python/utils/tkGUI.gmtsar` (`self.sample_dict`). One case uses `.tgz` instead of `.tar.gz`: `NISAR_SIM_ALOS`.

The case names exercised by the test runner are listed in `gmtsar/python/testingSystem/pathListForTest.py` (`caseNameList`).

## csh reference results

`gmtsar/python/testingSystem/checkTest.py` compares Python-framework outputs against reference results produced by the legacy csh framework. The reference tree lives at `<workdir>/csh_test/<caseName>/...` with the same intf paths as `intfDirList` in `pathListForTest.py`. Files compared: `corr_ll.png`, `display_amp_ll.png`, `phasefilt_mask_ll.png`, `corr_ll.grd`, `phasefilt.grd`, `filtcorr.grd`.

If `csh_test/<caseName>/` has no `.grd`/`.png` outputs, `runAllTest.py` automatically extracts the tarball and runs the bundled `README.txt` (csh recipe) to generate the reference.

## Notes on the framework
1. Per-case computing time is collected in `timeSpentLog.txt`; stdout from each case is piped to `log.txt` in the case folder. A summary (wall-clock + per-pipeline timings) prints at the end of `runAllTest.py`.
2. `gmtsar/python/testingSystem/checkTest.py` does the comparison. Required Python packages are installed by `install.sh --python`. Per-file thresholds are defined in `PNG_SSIM_THRESHOLD` / `GRD_RMS_THRESHOLD` dicts at the top of the script (phase-named outputs use relaxed thresholds because wraparound at 0/2π destroys SSIM).
3. Cases in `caseNameList` (`gmtsar/python/testingSystem/pathListForTest.py`) are validated against csh-framework reference outputs.

See [`CHANGELOG.md`](CHANGELOG.md) for the version history.
