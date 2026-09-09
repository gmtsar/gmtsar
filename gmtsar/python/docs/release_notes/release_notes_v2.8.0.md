# v2.8.0 — install.py hardened via clean-room testing, real dem2topo_ra Rule-7 bug fixed

## `install.py` hardened via genuine clean-room verification

`tests/test_install.py` (fresh `git clone` + fresh conda env, per Rule 15)
surfaced and fixed a run of real, previously-latent `install.py` bugs —
none of which reproduced on an already-working dev host:

- Missing `phasefilt_py` in `BIN_PY_NAMES` (`860e2c4`).
- HDF5 `h5cc` PATH-order bug — a stale system `h5cc` shadowed the
  conda-built one (`41ad2a3`).
- HDF5 1.14.x incompatible with `configure.ac`; pinned to the 1.12.x
  line instead of an open-ended floor+cap range (`9457f63`).
- Missing `flex` dependency — bootstrapped via conda-forge, not just
  documented as assumed (`761fe4e`, `3d3dd73`).
- `orbits/` reuse for clean-room clones, so every install test doesn't
  re-download orbit data (`96549f4`).
- Tarball-cache scoping — clean-room runs now only stage the tarballs
  the requested case tier actually needs (`984117f`).
- A Makefile mtime-fragility bug: GNU Make's implicit `.l.c:` rule was
  silently regenerating the committed `ers_line_fixer.c` from a troff
  man page that happens to share its basename, corrupting the build
  whenever mtimes landed in the wrong order after a fresh checkout
  (`3e96628`, `e7ef507`, `d7c3104`).

## `tests/test_install.py` itself hardened

- Fixed a false-PASS bug: the tool trusted `sweep.py`'s process exit
  code as "all passed," but that code only reflects orchestration
  crashes, not individual `compare.py` comparison failures. A clean-room
  run with 7 real comparison failures was reported PASS and its clone
  (including the only diagnostic evidence) was deleted (`2119c6c`).
- Added project_rules.md Rule 16 ("never delete test/sweep artifacts
  unless the result is a confirmed pass") codifying the fix above.
- Fixed a `--full` flag that had silently always run the 12-case
  `--fast` tier instead of the real 21-case `--full` tier, for the
  entire session, until caught (`bf40ebf`).
- Added zero-comparison-case detection as a failure mode, not a silent
  pass (`e04cdec`).

## 26 new regression tests

`bin_py/tests/test_install_config.py` (13 tests) and
`bin_py/tests/test_test_install_helpers.py` (13 tests) guard every bug
above: HDF5 pin, flex bootstrap, `_defuse_fake_lex_sources` mtime fix,
`phasefilt_py` in `BIN_PY_NAMES`, tarball/orbit cache scoping,
`check_sweep_results`'s real-failure detection, and the `--fast`/`--full`
tier mapping against `tests/cases.py`.

## Real `dem2topo_ra` Rule-7 verbatim-port bug fixed (`4ba030f`)

`dem2topo_ra.csh` uses `gmt surface ... -Q >& tmp` to capture GMT's `-Q`
probe "Hint: ..." message and auto-clip the interpolation region. The
Python port copied `>&` verbatim, but `gmtsar_lib.run()` executes via
`subprocess.run(shell=True)` → `/bin/sh -c`, and POSIX `sh` rejects
`>&<filename>` at parse time (`Bad fd number`, rc=2) — silently
swallowed by `run()`'s non-fatal-rc design. `tmp` was therefore *never*
created on the Python side, and the Hint-based `-R` auto-clip was
unconditionally skipped on every run, a real deterministic divergence
from the csh reference (project_rules.md Rule 7), not a cosmetic
warning. Fixed to the POSIX-equivalent `>tmp 2>&1` on both PRF branches.
3 new regression tests
(`TestHintProbeRedirectRegression` in `bin_py/tests/test_dem2topo_ra.py`).

Found while root-causing an unrelated intermittent `ALOS_haiti` snaphu
cycle-slip flake (~20-86 pixels out of 861,485). Direct pixel-level
diffing confirmed that flake is inherent run-to-run floating-point
nondeterminism feeding snaphu's discrete unwrapping-branch choice, NOT
a Python-port bug — left as a documented accepted flake, same tier as
the existing `S1_Ridgecrest_EQ` no-DEM-corner exception. The Hint-probe
fix does not explain or fix the `ALOS_haiti` flake; it is an
independent, real bug found along the way.

## Full 21-case sweep re-run post-fix: 20/21 clean, `S1_Ridgecrest_EQ` improved

`sweep.py --full --force py`, this repo's own installed (non-clean-room)
env, run after the `dem2topo_ra` fix landed:

- 20/21 cases clean. `S1_Ridgecrest_EQ` (the one documented no-DEM-corner
  exception) improved from 11/16 to 14/16 successes — 159/161 total
  comparisons pass across the sweep.
- No regressions across any of the 21 real cases relative to the prior
  v2.7.0 confirmation sweep.
- Snapshot: `docs/perf_snapshots/perf_snapshot_2026-07-15T00-35-57Z_4ba030f_full.md`
  (+ `.json`). Hardware: AMD EPYC 7F72 24-core, 1 TB RAM, NFS workdir.
  Software: GMT 6.4.0, Python 3.11.0. Sweep wall: 37 min.

## `docs/PATHWAY_FORWARD.md`: gate-2 (speed) benchmark backlog tracked

New "Open questions" entry: `phasediff_py`, `phasefilt_py`,
`gmt_grdfill_py`, `align_tops`, `make_los_py` are all wired ON by
correctness evidence only — no standalone C-vs-Python isolated timing
exists for any of them yet. None show evidence of *failing* gate 2, but
that's not the same as a verified pass (Rule 13). `phasediff_py` is the
most-requested first target for an isolated benchmark.

## Release-boundary verification (this release)

Fresh runs, this session, per project_rules.md Rule 5 and Rule 9 (don't
trust past conclusions — only fresh-run outputs are evidence):

- `bin_py/tests/` full suite (620 tests): **556 passed, 63 skipped, 1
  failed** when run without `bin_py` on `PATH`. The 1 failure
  (`test_dem2topo_ra.py::TestMode1ArgRegression::test_mode1_produces_topo_ra_grd`,
  `SAT_llt2rat_py: not found`, rc=127) is a `PATH` artifact of the
  invocation environment, not a code regression — confirmed by
  re-running the same file with `$GMTSAR/bin` on `PATH`: **11/11 pass**,
  matching the `4ba030f` fix commit's own stated evidence. Reproduced
  twice (two independent full-suite runs, same single failure both
  times).
- Fresh single-case `sweep.py --cases RS2_SLC_Hawaii --force py` smoke
  run at HEAD (`4ba030f`), with the `gmtsar` conda env and `$GMTSAR/bin`
  correctly on `PATH` (GMT 6.4.0): **6/6 SUCCESS**, py-vs-csh, exercising
  `topo_interp_mode=0` — the exact code path the `dem2topo_ra` fix
  touched. `dem2topo_ra` completed in 39.4s with no errors; full
  `p2p_processing` pipeline reached `P2P 7: FINISHED` cleanly.
- No full 21-case sweep was re-run for this release specifically — the
  two full sweeps documented above (both from this session, the second
  post-fix) already provide fresh, real evidence at HEAD, and a third
  multi-hour run would add no new information per the task scope.

## Assumptions

- This release's version-identity source of truth is the git tag and
  this release-note filename; no `__version__`/`pyproject.toml` string
  exists elsewhere in the tree to keep in sync (confirmed via a repo-wide
  grep for version literals — only comment-text references to `2.7.0`
  exist, not live version constants).
- `AUDIT.md` (untracked, dated 2026-07-13, predates this session's
  install.py/dem2topo_ra work by a day and covers an unrelated scope —
  env-gate Rule-1 fallback findings, `m2s_py` ledger gap) is left
  untouched: not part of this release's diff, provenance unclear, and
  its own findings were never actioned in this session. Left in the
  working tree for a human to triage separately.
- `phase_profile_py.json` (repo-root, untracked) is scratch profiling
  output from an ad hoc `dem2topo_ra` invocation during this session's
  investigation — not committed (matches the known, documented gap that
  only `bin_py/tests/phase_profile_py.json` is gitignored, not the
  root-level file; not fixed in this release, out of scope).

## Commits

`ea24769`..`4ba030f` (27 commits since `v2.7.0`/`138c848`), plus this
release's own housekeeping commit (`docs/PATHWAY_FORWARD.md` gate-2
backlog entry + this file + the perf snapshot).
