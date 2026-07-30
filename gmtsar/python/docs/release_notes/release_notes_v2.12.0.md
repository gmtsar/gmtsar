# v2.12.0 — merge with native Windows work; `--conda-env current`; numpy≥2

Scope: `v2.9.0..v2.12.0`. Two independent lines of work developed in
parallel (this session's Linux/conda-env work on top of `v2.9.0`, and a
separate session's native Windows port up through `v2.11.1`) merged
here — a real, conflicted merge (one hunk in `install.py`), not a
fast-forward. Both lines' real clean-room verification carried forward;
see `docs/release_notes/release_notes_v2.10.0.md` through
`release_notes_v2.11.0.md` for the Windows work's own findings
(native `--system conda-windows-full`, `distribute_gmtsar_windows.py`,
a real `conv.c` binary/text-mode bug on Windows, license attribution).

## New: `--conda-env current`

Real feedback from an external collaborator (jldz9, InSARHub
maintainer, testing this repo's `GMTSAR_S1` PR) who wanted to install
directly into an already-active conda env instead of always getting a
separate `gmtsar`-named one — a real pain point when trying to share
one env's dependency pins across two adjacent projects.
`--conda-env current` resolves to the active env via
`$CONDA_DEFAULT_ENV`/`$CONDA_PREFIX`. `locate_conda_env()` gained a
`known_prefix` param used as-is instead of re-deriving the path by
searching the fixed `CONDA_SEARCH_BASES` list by name — the active env
could legitimately live under a non-standard root a name-search would
miss. Verified end-to-end on this repo's own real dev env: activated
`gmtsar`, ran `--conda-env current --rebuild`, confirmed it targeted
that exact env (not creating a new one), full build succeeded,
`p2p_processing`/`gmt` both work afterward. Not yet wired into
`--system conda-windows-full` (a different code path entirely, doesn't
share `locate_conda_env()` — real follow-up, not done here).

## `requirements.txt`: `numpy<2` → `numpy>=2`, `numba>=0.56` → `>=0.60`

Same collaborator asked whether the long-standing, completely
undocumented `numpy<2` pin (every other pin in this file has a stated
reason; this one never did) could be lifted, since his own project
wants `numpy>=2` too. Tested for real rather than assumed safe: a
genuine clean-room env with `numpy>=2` requested, the full
`bin_py/tests/` suite run against it — **562 passed / 59 skipped / 0
failed**, including the real C-vs-Python xcorr parity test (the
bit-exact one this project's whole discipline is built around) against
real data, bit/float-identical to the `numpy<2` baseline. Both Cython
extensions (`build_surface_kernel.py`, `snaphu_py`'s build script)
rebuild cleanly against numpy2 headers. `numba` floor also raised
`>=0.56` → `>=0.60`: `numba<0.60`'s own PyPI metadata caps `numpy` well
below 2.0 (`0.56.4`: `numpy<1.24`; `0.59.x`: `numpy<1.27`) — doesn't
bite today since nothing else forces an old numba, but a real risk in
an offline/locked install.

## Merge notes

- `install.py`'s conflict: both branches added an `elif` arm for a new
  `--system` mode at the same location (`conda-linux-full` here,
  `conda-windows-full` on the Windows line) — resolved by keeping both,
  `known_prefix` threaded through the Linux full-isolation path only
  (Windows doesn't share that machinery).
- Everything else (README, CLAUDE.md, `PATHWAY_FORWARD.md`,
  `c_fixes/`, `test_install_config.py`, `requirements.txt`) merged
  cleanly with no conflicts, correctly combining both sides' real
  content — verified directly post-merge, not assumed.

## Release-boundary verification (this release)

Two independent full `tests/test_install.py --system conda --full`
clean-room runs this session, ~3h each: one at `v2.9.0` (pre-merge,
this session's own changes only), one at this merge commit (post-merge,
combining both lines of work). Both produced **the identical real
result**:

- `install.py --system conda`: **PASS**.
- `gmtsar_sharedir.csh`: **PASS**.
- `bin_py/tests/`: PASS post-merge (583 passed/60 skipped/0 failed) —
  the pre-merge run's one failure was a real, separately-confirmed-and-
  fixed test-isolation gap in this session's own `micromamba`-preference
  change (see `v2.9.0`'s notes), not present in this merge's own run.
- `sweep.py --full` (21 real py-vs-csh cases): **152/161 comparisons
  SUCCESS**, byte-for-byte identical failure set both runs:
  - `ALOS_haiti`: `los_ll.grd` — the accepted snaphu cycle-slip flake
    documented since `v2.8.0`.
  - `S1_Ridgecrest_EQ`: 8 failures, all `F1`/`F2`/`F3`/`H_res`
    intf-level files. Root-caused directly (both runs): the cached csh
    reference for this case is missing its `F1`/`F2`/`F3` directories
    entirely, has no `.oracle_built` sentinel, and the sweep itself
    flags it live (`WARN: oracle has no sentinel ... grandfathered as
    valid`) — a stale/incomplete cached csh oracle, confirmed
    pre-existing and stable across two independent runs regardless of
    the code changes in between. Needs a real oracle rebuild to
    resolve; tracked as a follow-up, not done this release (real,
    multi-hour csh processing time beyond this release's scope).

## Commits

`0d49b8b` (`v2.9.0`) `..2f7566f` — this session's 3 commits
(`--conda-env current`, `numpy`/`numba`) plus a real merge with the
Windows line's 26 commits (`0d49b8b..41d9c85`, `v2.9.0` through
`v2.11.1`).
