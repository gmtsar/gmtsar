# CLAUDE.md

Guidance for Claude Code working in this repository.

## Repo

Fork of upstream `gmtsar/gmtsar` (C/csh InSAR processor). This fork extends it with a Python framework, a Tk GUI, and Docker dev infrastructure.

- Remote `origin` → `github.com/dunyuliu/gmtsar.py.docker.dev` (this fork)
- Remote `upstream` → `github.com/gmtsar/gmtsar`
- Default branch: `master` (not `main`)

## Read this before any port, test, or sweep

**`gmtsar/python/project_rules.md`** — 13 numbered rules, each written
after a real incident (silent fallbacks, lost sweep artifacts, stale
"done" claims, etc.). Read it at the start of any task involving:
porting a C/GMT module, running or reporting on a test sweep, or wiring
a new env-gate dispatcher.

**`gmtsar/python/docs/PATHWAY_FORWARD.md`** — the living ledger of what's
ported, what's wired ON vs OFF and why, and what's never been attempted.
Read it before re-deriving "what's left to port" from scratch, and update
it (per Rule 13: "ported" and "wired ON by default" are different states
— track both) in the same edit that lands any new port or wiring change.

## Where dev lives

**All dev work lives in `gmtsar/python/`.** Do not modify files outside this directory — everything else is upstream `gmtsar/gmtsar` source and should be left untouched so upstream merges stay clean.

This rule applies to **every consilium-driven artifact** too: audit reports (`AUDIT*.md`), QA notes, release notes, dev rules, and any other fork-only output must be written inside `gmtsar/python/`, never at the repo root. When invoking `/audit`, `/release`, or similar slash commands, override the default destination so output lands at `gmtsar/python/AUDIT.md` (or wherever inside the python tree fits). The "fork = upstream/master + gmtsar/python/" invariant is enforced by `git diff upstream/master..HEAD -- ':!gmtsar/python'` returning empty.

Layout under `gmtsar/python/`:
- `utils/` — Python CLI tools (`p2p_processing`, `pre_proc`, `geocode`, `intf`, `filter`, …) and libraries (`gmtsar_lib.py`, `snaphu.py`)
- `utils/tkGUI.gmtsar` — Tk GUI front-end
- `tests/` — regression-test framework (`sweep.py`, `case_runner.py`, `compare.py`, `cases.py`, `run_one.sh`) plus `tests/configs/<case>.py` (staged Python configs translated from bundled csh `config*.txt`) and `tests/recipes/README_<case>.txt` (per-case recipes). The old `sweep.sh`/`case_runner.sh`/`runner.py` bash implementation is archived at `tests/archive/` (2026-07-13 rewrite — real CLI args instead of shell env vars; see `tests/archive/README.md`).
- `docs/` — release notes archive (`release_notes_v*.md`)
- Install script: `install.py` (`--system ubuntu|conda|conda-linux-full|conda-windows-full` installs everything for that system — deps, Python packages, build; `--rebuild` and `--orbits` are optional add-ons). `conda-linux-full` additionally provisions the compiler/build-tool chain via conda (Linux x86_64 only). `conda-windows-full` is native Windows — no WSL, no MSYS2/Cygwin toolchain — still requires Git for Windows for `gmtsar_lib.py`'s POSIX-shell routing. Old bash version archived at `archive/install.sh` (2026-07-13 rewrite — real CLI args instead of shell env vars; see `archive/README.md`).

## Syncing from upstream

```bash
git fetch upstream
git merge upstream/master       # prefer merge over rebase (published fork)
git push origin master
```

Merge over rebase: this fork is public, so don't rewrite history. Conflicts should be rare since dev is confined to `gmtsar/python/`.

## Running

Python framework is invoked via the scripts in `gmtsar/python/utils/` (most are executable, no `.py` extension). The GUI launches via `python3 gmtsar/python/utils/tkGUI.gmtsar`.

## Install (sudo-free path)

```
python3 gmtsar/python/install.py --system conda
```
Uses the `gmtsar` conda env (auto-detected at `$HOME/anaconda3`, `$HOME/miniconda3`, or `/opt/conda`; set `CONDA_GMTSAR_ENV=<name>` or `--conda-env <name>` to override). If that env doesn't exist yet, it's created via `conda create -c conda-forge gmt hdf5 libtiff liblapack ...` — only a bare Anaconda/Miniconda install is assumed, not a pre-populated env (network required for that create step). Builds in-place; `make install` lands in `<repo>/bin` via `--prefix=<repo>`. `bin/` also gets the Python utilities and symlinks to all `gmtsar/csh/*.csh` so `pop_config.csh`, `p2p_processing.csh`, etc. are on `PATH`. Once installed, iterate with `--system conda --rebuild` to skip the dependency steps.

`--system ubuntu` is the sudo path: assumes a raw Ubuntu box (nothing pre-installed) and apt-installs the full system dependency set itself.

After install, in any shell:
```
export GMTSAR=<your-repo-root>   # e.g. /home/yourname/gmtsar
export PATH=$GMTSAR/bin:$PATH
```

## Testing system

Test orchestrator: `gmtsar/python/tests/sweep.py` (parallel sweep with download cache, integrity check, and per-case timing) dispatching `case_runner.py` (per-case csh+py recipe runner, one subprocess per case for process-group isolation). Workdir defaults to `gmtsar/python/work/` (override with `$SCRATCH`). Per case:

1. Sweep checks if a cached tarball is present in `work/dataset/<case>.tar.gz`; otherwise fetches from `topex.ucsd.edu/gmtsar/tar/` via `wget -c`.
2. gzip integrity check (killed-by-signal → preserve tarball for retry; truly corrupt → delete and re-download).
3. `case_runner.py` extracts the tarball into both `work/csh_test/<case>/` and `work/python_test/<case>/`.
4. Stages `tests/configs/<case>.py` into py side as `config.py` (if a staged config exists). Config-drift guard rejects mismatched py vs csh config values up front.
5. Runs `csh README.txt` (bundled tarball recipe) on csh side and `tests/recipes/README_<case>.txt` on py side **in parallel**.
6. `compare.py` performs three-way comparison (py-vs-csh, py-vs-frozen, csh-vs-frozen) and writes a per-case JSON scorecard to `work/results/<case>.json`.

Use `python3 gmtsar/python/tests/sweep.py --cases case1 case2` to run a subset (or `TEST_CASES=case1,case2` env var, still honored). `--topo-mode-ab` reuses the same csh_test/python_test tree-pair machinery to run py(topo_interp_mode=0) vs py(topo_interp_mode=1) instead of csh-vs-py (folders renamed `ref_test`/`new_test` in that mode so they aren't mislabeled "csh").

Test cases are declared in `gmtsar/python/tests/cases.py` (single source of truth, with tiers: `smoke`/`fast`/`full`/`sbas` and per-case `enabled` flag). Disabled cases must document the reason in a comment above the entry.

### Performance + hardware capture (rule 6)

Every test run records per-case wall time (`work/timeSpentLog.txt`) plus a single per-sweep hardware/software snapshot at `work/perf_<timestamp>.txt` (CPU model + core count, total RAM, NFS vs local disk, GMT version, Python version, `gmtsar` C-binary commit hash). This is required by project rule #6 so that scorecards from different hosts/runs are comparable and so regressions can be attributed to environment vs code changes.
