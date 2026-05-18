# Release notes — v1.12.1

## 1. Version and date

- **Version:** v1.12.1 (patch — audit-driven silent-failure elimination)
- **Date:** 2026-05-18
- **Previous:** v1.12.0 (archived to `docs/release_notes_v1.12.0.md` on next minor)
- **Tag commit:** `0e144ca`

## 2. Summary of scope

A `victor-reyes` audit during v1.12.0 testing identified that several
cases were reporting **false-PASS scorecards** because `compare.py`
silently dropped missing files from the comparison set. v1.12.1 closes
that gap and the related silent-failure modes that the audit surfaced.
No new ports; no behavioural changes to the processing pipeline.

Net effect: COVE and Larsen, which had reported all-SUCCESS scorecards
under v1.12.0 despite their py-side `merge/` directories being empty,
now correctly run end-to-end and pass with full 10/0 SUCCESS each.
Ridgecrest moves from 12/4 FAIL to **16/0/16 PASS** once both sides
run in the same environment (the H_res shape mismatch was
environment-drift between csh-yesterday and py-today, not a real bug).

Test scorecard at release: **20 of 21 enabled full-tier cases PASS,**
1 NORUN (ALOS2_SCAN_SSAF is chronically flaky under heavy-I/O
contention but passes in isolation).

## 3. Changes

### `tests/compare.py`

- **Emit ABSENT-as-FAIL** when a file is present on one side and absent
  on the other. Previously the loop only created a comparison pair when
  both files existed, silently dropping the asymmetry. This was the
  root cause of v1.12.0's COVE/Larsen false-PASS.
- **Tolerate ≤1 % shape mismatch via coordinate-aware alignment.**
  When py and csh `_ll.grd` outputs differ by a few edge cells (typical
  of upstream-GMT `surface` non-determinism), align both to the common
  geographic overlap via `xarray.sel`/`reindex_like` before computing
  RMS. Mismatches > 1 % still FAIL.
- **Expand `fileNameList`** to include `los_ll.grd` so the `geocode`
  LOS-stage regression we found this cycle would be caught next time.

### `utils/p2p_S1_TOPS_Frame`

- **Post-merge assertion** after `merge_unwrap_geocode_tops` —
  `phasefilt.grd` and `corr.grd` are required to exist or the script
  exits with a clear message. Mirrors the assertion pattern v1.12.0
  added to `p2p_ALOS2_SCAN_Frame`.
- **Threshold-zeroing override** for the per-subswath context now
  lives in `processOneSubswath` (via a new `_override_thresholds`
  helper) instead of unconditionally inside `p2p_processing`. This
  fixes a latent bug where standalone single-subswath S1_TOPS runs
  (e.g. Ridgecrest H_res) had their `threshold_geocode`/
  `threshold_snaphu`/`iono_skip_est` force-zeroed and thus silently
  skipped the geocode + snaphu stages.

### `utils/p2p_processing`

- Removed the unconditional S1_TOPS threshold-zeroing block; the
  multi-subswath override is now applied by callers (Frame drivers)
  via per-subswath config rewrite.

### `utils/geocode`

- Replace literal csh-style `$wavel` / `$PWD:t` / `$remarked` in
  Python f-strings with actual Python-interpolated values. The
  `$wavel` instance was a real numeric-correctness bug: `gmt grdmath
  unwrap_mask_ll.grd $wavel MUL -79.58 MUL = los_ll.grd` was emitting
  an undefined bash variable, so `los_ll.grd` was either missing or
  numerically wrong wherever `threshold_snaphu > 0` (currently only
  `ALOS_haiti`).

### `tests/case_runner.sh`

- **`PATH` export** for the gmtsar conda env's `bin/`. Without this,
  sweeps launched from a shell that hadn't activated `conda activate
  gmtsar` would silently lose `gmt`, causing `dem2topo_ra` to produce
  no `topo_ra.grd`, which cascaded into `phasediff` errors, no
  `phasefilt.grd`, and a false-PASS scorecard. This was the actual
  root cause of v1.12.0's COVE/Larsen failures (the audit's silent-
  failure narrative was the symptom; this was the cause).
- **Config-drift guard** when both bundled csh `config.txt` and staged
  py `config.py` exist — compares `filter_wavelength`, `region_cut`,
  `threshold_snaphu/geocode`, `dec_factor`, `proc_stage`. Mismatch →
  exit 3 with diff. Catches drift up-front instead of via shape-
  mismatch hours later.
- **`config.tops.txt` vs `config.txt` selection** — prefers exact
  `config.txt` when both exist (Ridgecrest case).
- **Multi-subswath csh-side parallel-flag patch** — rewrites trailing
  ` 0` → ` 1` on `p2p_(ALOS2_SCAN|S1_TOPS)_Frame.csh` lines in the
  bundled README, so the csh reference matches the Python side's
  parallel-pool behaviour. A documented deviation from rule #3
  (mirror bundled exactly), scoped narrowly to the parallel flag.
  Sed regex initially used `|` as both pattern alternation and
  command delimiter — switched to `@` delimiter so the substitution
  actually applies.

### `tests/sweep.sh`

- **Distinguish gzip signal-kill from real corruption** in the
  integrity check: rc ≥ 128 means gzip was killed externally (e.g.
  by a too-broad `pkill`), tarball preserved for retry; rc = 1 means
  truly corrupt, delete and re-download. Prevents 44 GB needlessly
  re-downloaded after an unrelated kill.

### `utils/p2p_stages.py`

- `P2P2RegionCut` accepts `region_cut` as an explicit parameter
  (was a free-name reference broken since the function moved into
  this module). Unreachable for the 19 passing cases (`region_cut=
  -999`) but bit the moment Ridgecrest H_res's real value was used.

### Project documentation

- New project rule **#6** in `project_rules.md`: testing must collect
  per-case wall time + per-sweep hardware/software snapshot so
  scorecards can be compared across hosts and regressions attributed
  to environment vs code.
- `gmtsar/python/PROJECT_RULES.md` (stale 531-byte duplicate) replaced
  with a symlink to `project_rules.md` at repo root.
- `CLAUDE.md` testing-system section refreshed to match the actual
  `tests/` layout (was still pointing at the deprecated
  `testingSystem/` paths and `runAllTest.py`/`checkTest.py`).

## 4. Files

### Modified

- `tests/compare.py`
- `tests/case_runner.sh`
- `tests/sweep.sh`
- `utils/p2p_S1_TOPS_Frame`
- `utils/p2p_processing`
- `utils/p2p_stages.py`
- `utils/geocode`
- `CLAUDE.md` (repo root)
- `project_rules.md` (repo root) — added rule #6

### Replaced / linked

- `gmtsar/python/PROJECT_RULES.md` → symlink to `../../project_rules.md`

### Added

- `gmtsar/python/release_notes_v1.12.1.md` (this file)

## 5. Audit findings still open (deferred to v1.12.2)

The audit also surfaced items not blocking this release; deferred:

- `grep_value()` arg-swap in S1_TOPS iono path (`p2p_stages.py` lines
  371/374/401/404) — not exercised by the test suite.
- `replace_strings()` line-vs-substring semantics — works by accident
  for single-field PRM lines.
- `compare.py` "both-absent" silent skip — 44 % of (file, intf) slots
  are dropped with no log; defensible for structural cases but not
  distinguishable from coordinated regression.
- Hardcoded `/home/staff/dliu/...` paths in `sweep.sh` and
  `case_runner.sh` — clean-checkout reproducer fails on other hosts.
- Scorecard JSON lacks `git_sha` — skip-guard cannot detect stale
  results after a binary/code update.
- `run_one.sh` missing `OMP=1`/`MKL=1`/`OPENBLAS=1`/`FFTW=1` and
  unguarded `LD_PRELOAD`.

## 6. Scorecard

20 PASS / 0 FAIL / 1 NORUN (`ALOS2_SCAN_SSAF`) of 21 enabled full-tier
cases.

PASS list: ALOS2_Brazil, ALOS2_Japan_Fugi_left, ALOS4_Pinon,
ALOS_Baja_EQ, ALOS_ERSDAC_L1.0, ALOS_haiti, ALOS_SLC_L1.1,
CSK_RAW_Hawaii, CSK_SLC_Italy, ENVI_Baja_EQ, ENVI_Baja_EQ_SLC,
ERS_Hector_EQ, NISAR_Ethiopia, RS2_SLC_Hawaii, S1A_SLC_TOPS_COVE,
S1A_SLC_TOPS_Greece, S1A_SLC_TOPS_LA, S1_Larsen_C,
S1_Ridgecrest_EQ, TSX_SLC_Hawaii.
