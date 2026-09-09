# Archive — superseded bash test orchestrator (2026-07-13)

`sweep.sh`, `case_runner.sh`, and `runner.py` (the old thin Python dispatch
layer between them) were replaced by `tests/sweep.py` + `tests/case_runner.py`
on 2026-07-13, after a session that repeatedly hit the same class of bug:
shell env vars (`GMTSAR`, `PATH`, `TOPO_MODE_AB`) silently not persisting
across separate tool invocations, causing multiple real failures that took
time to diagnose (a background sweep silently launched with 0 cases; a
strace experiment that landed in the wrong `$GMTSAR`).

The rewrite is a **faithful behavioral port**, not a redesign — every
documented fix/rationale in the bash version (the NISAR pop_config-line
neutralization, the ALOS2_SCAN_SSAF Frame-driver parallelization patch, the
sentinel-guarded csh oracle cache, the config-drift guard, the
filter1->filter_wavelength translation, the git-sha sidecar) is preserved in
`case_runner.py` with its original comment. What changed:

- Real CLI args (`--parallel`, `--force [hard|py|stage]`, `--cases`,
  `--topo-mode-ab`) replace what used to be shell env vars
  (`MAX_PARALLEL`, `SWEEP_FORCE`, `TEST_CASES`, `TOPO_MODE_AB`) for
  anything the *caller* sets. `TEST_CASES` is still honored as a fallback.
  Internal env vars that must cross a subprocess boundary regardless of
  language (thread pins, `LD_PRELOAD`, `GMTSAR_PROFILE`) are still set —
  as real OS env vars, computed fresh per case-runner invocation, not read
  from the caller's shell.
- `sweep.sh` + `runner.py` (2 layers) collapsed into `sweep.py` (1 layer),
  since `runner.py` was already a thin wrapper spawning `case_runner.sh`
  subprocesses.
- New `--topo-mode-ab` flag: repurposes the same `csh_test`/`python_test`
  tree-pair machinery (renamed `ref_test`/`new_test` in that mode) to run
  `topo_interp_mode=0` vs `=1`, both sides Python, no csh at all —
  `compare.py` needs zero changes since it already diffs those two trees
  with the right thresholds.

Validated before landing: a direct `case_runner.py` run on `RS2_SLC_Hawaii`
(matching known-good 6/6), a full `sweep.py --fast --cases RS2_SLC_Hawaii
--force py` end-to-end run (97s wall, matches known timing, blessed diff
PASS, perf snapshot written), and a `--topo-mode-ab` run confirming
`config.py`'s `topo_interp_mode` was correctly forced to 0/1 in the two
trees. A full 21-case `--force py` confirmation sweep followed immediately
(see `docs/release_notes/release_notes_v2.7.0.md`).

These files are kept for reference only — not on PATH, not imported by
anything current. If the Python rewrite is ever found to have dropped a
documented behavior, this is the ground truth to diff against.
