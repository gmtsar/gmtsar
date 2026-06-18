# CLAUDE.md

Guidance for Claude Code working in this repository.

## Repo

Fork of upstream `gmtsar/gmtsar` (C/csh InSAR processor). This fork extends it with a Python framework, a Tk GUI, and Docker dev infrastructure.

- Remote `origin` → `github.com/dunyuliu/gmtsar.py.docker.dev` (this fork)
- Remote `upstream` → `github.com/gmtsar/gmtsar`
- Default branch: `master` (not `main`)

## Where dev lives

**All dev work lives in `gmtsar/python/`.** Do not modify files outside this directory — everything else is upstream `gmtsar/gmtsar` source and should be left untouched so upstream merges stay clean.

This rule applies to **every consilium-driven artifact** too: audit reports (`AUDIT*.md`), QA notes, release notes, dev rules, and any other fork-only output must be written inside `gmtsar/python/`, never at the repo root. When invoking `/audit`, `/release`, or similar slash commands, override the default destination so output lands at `gmtsar/python/AUDIT.md` (or wherever inside the python tree fits). The "fork = upstream/master + gmtsar/python/" invariant is enforced by `git diff upstream/master..HEAD -- ':!gmtsar/python'` returning empty.

Layout under `gmtsar/python/`:
- `utils/` — Python CLI tools (`p2p_processing`, `pre_proc`, `geocode`, `intf`, `filter`, …) and libraries (`gmtsar_lib.py`, `snaphu.py`)
- `utils/tkGUI.gmtsar` — Tk GUI front-end
- `tests/` — regression-test framework (`runner.py`, `sweep.sh`, `case_runner.sh`, `compare.py`, `cases.py`, `run_one.sh`) plus `tests/configs/<case>.py` (staged Python configs translated from bundled csh `config*.txt`) and `tests/recipes/README_<case>.txt` (per-case recipes)
- `docs/` — release notes archive (`release_notes_v*.md`)
- Install scripts: `install.sh`, `install.gmtsar.ubuntu.sh`, `install.packages.for.python.testing.sh`, `fetch-orbits.sh`

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
bash gmtsar/python/install.sh --conda --python --build
```
Uses the existing `gmtsar` conda env (auto-detected at `$HOME/anaconda3`, `$HOME/miniconda3`, or `/opt/conda`; set `CONDA_GMTSAR_ENV=<name>` to override the env name). Builds in-place; `make install` lands in `<repo>/bin` via `--prefix=<repo>`. `bin/` also gets the Python utilities and symlinks to all `gmtsar/csh/*.csh` so `pop_config.csh`, `p2p_processing.csh`, etc. are on `PATH`.

After install, in any shell:
```
export GMTSAR=<your-repo-root>   # e.g. /home/yourname/gmtsar
export PATH=$GMTSAR/bin:$PATH
```

## Testing system

Test orchestrator: `gmtsar/python/tests/sweep.sh` (parallel sweep with download cache, integrity check, and per-case timing) wrapping `runner.py` (Python orchestrator) wrapping `case_runner.sh` (per-case csh+py recipe runner). Workdir defaults to `gmtsar/python/work/` (override with `$SCRATCH`). Per case:

1. Sweep checks if a cached tarball is present in `work/dataset/<case>.tar.gz`; otherwise fetches from `topex.ucsd.edu/gmtsar/tar/` via `wget -c`.
2. `gzip -t` integrity check (rc≥128 = killed by signal → preserve tarball for retry; rc=1 = truly corrupt → delete and re-download).
3. `case_runner.sh` extracts the tarball into both `work/csh_test/<case>/` and `work/python_test/<case>/`.
4. Stages `tests/configs/<case>.py` into py side as `config.py` (if a staged config exists). Config-drift guard rejects mismatched py vs csh config values up front.
5. Runs `csh README.txt` (bundled tarball recipe) on csh side and `tests/recipes/README_<case>.txt` on py side **in parallel**.
6. `compare.py` performs three-way comparison (py-vs-csh, py-vs-frozen, csh-vs-frozen) and writes a per-case JSON scorecard to `work/results/<case>.json`.

Use `TEST_CASES=case1,case2 bash gmtsar/python/tests/sweep.sh` to run a subset.

Test cases are declared in `gmtsar/python/tests/cases.py` (single source of truth, with tiers: `smoke`/`fast`/`full`/`sbas` and per-case `enabled` flag). Disabled cases must document the reason in a comment above the entry.

### Performance + hardware capture (rule 6)

Every test run records per-case wall time (`work/timeSpentLog.txt`) plus a single per-sweep hardware/software snapshot at `work/perf_<timestamp>.txt` (CPU model + core count, total RAM, NFS vs local disk, GMT version, Python version, `gmtsar` C-binary commit hash). This is required by project rule #6 so that scorecards from different hosts/runs are comparable and so regressions can be attributed to environment vs code changes.
