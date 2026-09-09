# Archive — superseded bash installer (2026-07-13)

`install.sh` was replaced by `gmtsar/python/install.py` on 2026-07-13, as
part of the same shell-env-vars-are-a-liability push behind the earlier
`tests/sweep.py`/`case_runner.py` rewrite (see `tests/archive/README.md`)
— shell flags mapped 1:1 to boolean vars (`DO_UBUNTU`/`DO_CONDA`/...) are
harder to validate and extend than a real `argparse` CLI.

The rewrite is a **faithful behavioral port**, not a redesign — verified
directly against this file, not from memory:

- `--ubuntu` / `--conda` (mutually-exclusive booleans) became one
  `--system {ubuntu,conda}` argument. The bash version's separate
  `--python`/`--build`/`--all` step flags were then collapsed further,
  post-port, per user direction: `--system` alone now installs
  everything for that system (deps + Python packages + build); `--build`
  survives only as `--rebuild` (skip deps, rebuild + re-stage only,
  requires `--system` for its build flags). `--orbits` is unchanged.
- `locate_conda_env()`, `stage_execs()` (the chmod+symlink helper
  consolidated from install.sh's 4 near-identical loops just before this
  rewrite), and the `config.mk` `sed` patches became named Python
  functions (`locate_conda_env`, `stage_execs`, `patch_config_mk`) with
  behavior verified byte-for-byte against the bash version in an isolated
  fixture (same resulting `bin/` symlink set + permissions; same
  `config.mk` edits, including the exact `sed`-semantics no-op when a
  target line like `GMT_INC` is absent — the Python port does NOT
  silently append missing keys, matching `sed -i` precisely).
- `set -e`'s "any command fails, script stops" became `subprocess.run(...,
  check=True)` on every external call (`run()` helper) — a non-zero exit
  from `apt`, `make`, `wget`, etc. raises immediately, same as before.
- CONDA_GMTSAR_ENV env var still honored as a default; `--conda-env`
  added as the explicit CLI equivalent.
- New, beyond a faithful port (explicit user requirement -- "conda or
  ubuntu should work on a new system"): the bash version's
  `locate_conda_env()` only ever *found* an existing env and errored if
  missing, so `--system conda` assumed a pre-populated env. The Python
  version's `locate_conda_env()` now *creates* the env via `conda create
  -c conda-forge gmt hdf5 libtiff liblapack ...` if it doesn't exist,
  so only a bare Miniconda/Anaconda install is required — `--system
  conda` is a real from-scratch path now, not just `--system ubuntu`.

Validated before landing: `--help`/no-args output, `--system conda` alone
against the real on-host `gmtsar` conda env (found the same path bash
would) and, separately, against a fake conda base with the env
deliberately missing (confirmed the right `conda create` command and
that the newly-"created" env is picked up); `--rebuild` without
`--system` correctly erroring; a fixture test proving `stage_execs`'s 4
call sites (utils/, the bin_py allowlist, csh/, csh_shims/) produce an
identical `bin/` symlink listing (including that names NOT in the
bin_py allowlist stay unsymlinked) to the old bash version's same
fixture; and a full real `--system conda --rebuild` run against this
repo's actual build (caught and fixed a real bug in the process: a
stray real, non-symlink `bin/__pycache__` directory from a previous
run crashed `stage_execs`'s `unlink()` since `utils/*` globs pick up
directories like `__pycache__`/`build` too — `stage_execs` now only
stages regular files and warns-and-skips instead of crashing if a real
directory already occupies a destination name).

This file is kept for reference only — not on PATH, not invoked by
anything current. If the Python port is ever found to have dropped a
documented behavior, this is the ground truth to diff against.
