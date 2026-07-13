# Release notes — v1.12.3

## 1. Version and date

- **Version:** v1.12.3 (patch — iono path fix + SAT dispatch fail-fast + quick test wizard)
- **Date:** 2026-05-20
- **Previous:** v1.12.2 (commit `e761f4a`; 2026-05-18)
- **Archived this release:** `release_notes_v1.12.0.md` → `docs/release_notes_v1.12.0.md`

## 2. Summary of scope

This patch closes two MAJOR findings from the victor-reyes AUDIT.md
(post-a37469f, 2026-05-20):

- **Iono path crash on first use (AUDIT #3):** `p2p_stages.py` was missing
  `import shutil` and the five iono globals (`iono_skip_est`, `iono_filt_rng`,
  `iono_filt_azi`, `mask_water`, `switch_land`) were never threaded through
  `_iono_intf_block` or `P2P4MakeFilterInterferograms`. First call with
  `iono=1` raised `NameError`. Both are now fixed.

- **SAT dispatch silent fallthrough (AUDIT #4):** `utils/pre_proc`'s
  `if/elif` chain had no terminal `else`. An unknown SAT (typo, new variant
  not yet added) fell through to `print('PREPROC: FINISHED')` with no PRM
  or SLC produced, hiding the real cause when the recipe died later.
  Appended an explicit `else: raise SystemExit(...)`.

Additionally, `tests/wizard.sh` is introduced as a 9-second pre-commit
sanity check that catches the class of bugs the 3-hour sweep.sh would not
surface until much later: missing imports, SyntaxError, shell-syntax errors,
config drift, SAT round-trip through pop_config, and PRM round-trip through
grep_value.

Commits captured since v1.12.2 (e761f4a):

| Commit | Summary |
|---|---|
| `6ee1113` | Rename snaphu + fitoffset Python wrappers to `.py` to stop shadowing C binaries |
| `44bad6d` | Update snaphu-wrapper callers to use `snaphu.py` |
| `d67601b` | ALL-PASS scorecard: fitoffset wrapper + ALOS2_SCAN port + recipe-asymmetry skip |
| `a37469f` | From-scratch sweep all-pass (5 fixes uncovered by SWEEP_FORCE=1) |
| `2b3c4ac` | CLAUDE.md: extend "all dev under gmtsar/python/" to consilium artifacts |

Plus uncommitted local changes folded into this release commit (see §3).

Test scorecard at release: **21/21 PASS, 161 SUCCESS / 0 FAIL** from a
from-scratch sweep completed 2026-05-20 01:56. Wizard: **PASS in 8s, 6/6
checks green**.

## 3. Files added / removed / renamed / cleaned up

### Added

- `gmtsar/python/tests/wizard.sh` — quick sanity wizard (9 s, 6 checks).
  Catches missing imports, SyntaxError, bash/csh syntax errors, config drift,
  SAT round-trip via pop_config, PRM round-trip via grep_value. Run before
  every commit and pre-push. Exits 0 on full pass, non-zero on any failure.

### Modified

- `gmtsar/python/utils/p2p_stages.py`
  - Line 19: added `import shutil` (was missing; `shutil.rmtree('iono_phase')`
    at line ~607 raised NameError on first iono path execution).
  - `_iono_intf_block` signature (line 537–538): added explicit parameters
    `iono_skip_est`, `mask_water`, `switch_land`, `iono_filt_rng`, `iono_filt_azi`
    — previously referenced as free names from `p2p_processing`'s module scope.
  - `P2P4MakeFilterInterferograms` signature (line 574–577): added the same
    five iono globals as keyword args with safe defaults (`iono_skip_est=1`,
    `iono_filt_rng=200`, `iono_filt_azi=200`, `mask_water=0`, `switch_land=0`).
  - Internal call sites at lines 620–627 updated to pass the five kwargs
    through to `_iono_intf_block`.

- `gmtsar/python/utils/p2p_processing`
  - Lines 227–229: `P2P4MakeFilterInterferograms` call site now passes
    `iono_skip_est`, `iono_filt_rng`, `iono_filt_azi`, `mask_water`, and
    `switch_land` as explicit kwargs. Previously the call used positional
    args only, relying on the now-removed module-global free-name references.

- `gmtsar/python/utils/pre_proc`
  - Lines 407–413: appended `else: raise SystemExit(...)` to the SAT dispatch
    chain. Message: `"PREPROC: ERROR — unknown SAT '{SAT}'. Add a dispatch
    branch to pre_proc."` Fixes AUDIT finding #4. Aligns with project rule
    #1 (no silent fallbacks) and the existing pre_proc docstring ("must error
    if SAT isn't in its dispatch table").

### Archived

- `gmtsar/python/release_notes_v1.12.0.md`
  → `gmtsar/python/docs/release_notes_v1.12.0.md`

Top-level release notes now kept: v1.12.1, v1.12.2 (implicit — captured by
commit `e761f4a` message), v1.12.3 (this file). All prior notes in `docs/`.

## 4. Content updates to master documents

- `gmtsar/python/CLAUDE.md` — "all dev under gmtsar/python/" scoping now
  explicitly covers consilium-driven artifacts (audit reports, QA notes,
  release notes). Commit `2b3c4ac`.
- `project_rules.md` — no changes in this release.
- `tests/cases.py` — no changes in this release.

## 5. Audit findings and fixes

AUDIT.md (victor-reyes, 2026-05-20) contains 17 findings (originally numbered
1-17, with entries 13-17 added as inherited/minor). This release addresses:

| # | Severity | Finding | Action |
|---|---|---|---|
| 3 | MAJOR | `p2p_stages.py` iono path: `shutil` not imported; 5 globals never threaded through. Crashes on first `iono=1` use. | Fixed. `import shutil` added at `p2p_stages.py:19`; all 5 iono params are now explicit args on `_iono_intf_block` and `P2P4MakeFilterInterferograms`; call sites in `p2p_processing` pass them explicitly. |
| 4 | MAJOR | `pre_proc` SAT dispatch has no terminal `else`; unknown SAT silently prints "FINISHED" with no output. | Fixed. `else: raise SystemExit(...)` appended at `pre_proc:407-413`. |

## 6. Known issues (deferred — not release blockers)

The following AUDIT.md findings are documented here for visibility but are
not blocking this release. They are PR-prep and housekeeping concerns.

| AUDIT # | Severity | Issue |
|---|---|---|
| 1 | MAJOR | PR body content drift: claims "160 SUCCESS" (actual 161), "CSG" (no such case — should be GF3), and branch tip mismatch (`9b3cea5` vs actual `12c61a0`). Must be corrected before PR merge. |
| 2 | MAJOR | py-vs-csh 0.0 metrics are near-tautological (shared C binaries); PR body and tests/README.md should disclose that `py-vs-csh` validates recipe equivalence, not independent reimplementation. 38 of 161 metrics are exactly 0.0 by construction. |
| 5 | MAJOR | `tests/sweep.sh:23-25` hardcodes `/home/staff/dliu/...` paths. First external reproducer fails in < 5 min. Parameterize via `git rev-parse --show-toplevel` and `command -v python3`. |
| 6 | MEDIUM | Frozen reference `tests/reference/` does not exist; `py-vs-frozen` and `csh-vs-frozen` comparison arms silently never run (`compare.py:258`). |
| 7 | MEDIUM | `p2p_S1_TOPS_Frame.merge` lacks the post-condition file-existence assertion that `p2p_ALOS2_SCAN_Frame` and `p2p_S1_TOPS_doublediff` received in v1.12.0/v1.12.1. |
| 8 | MEDIUM | `gmtsar/python/PROJECT_RULES.md` (5 lines, uppercase) coexists with root `project_rules.md` (86 lines, lowercase); divergent. The symlink installed in v1.12.1/v1.12.2 should resolve this — verify both point to the same content. |
| 9 | MEDIUM | `utils/p2p_processing:38-39` — two consecutive `sys.exit` calls; second is unreachable dead code. |

## 7. Rule compliance check

| Rule | Status |
|---|---|
| #1 No silent fallbacks | PASS — `pre_proc` now raises on unknown SAT (this release). `gmtsar_lib.run()` still raises on rc=127. |
| #3 Mirror bundled README + config exactly | PASS — no recipe changes in this release. The parallel-flag patch deviation from v1.12.0 remains documented. |
| #6 Perf + HW capture | PASS — `work/perf_20260519_173857.txt`, `work/perf_20260520_021715.txt`, `work/perf_20260520_022828.txt` present; `work/timeSpentLog.txt` present. |

## 8. Verification

- **Full sweep (from-scratch):** 21/21 PASS, 161 SUCCESS / 0 FAIL.
  Log: `gmtsar/python/work/sweep_fromscratch_v2_20260519_173857.log`.
  Completed: 2026-05-20 01:56.
- **Wizard:** PASS — 8 s, 6/6 checks (119 Python sources AST-clean,
  92 utilities compile, 4 bash scripts + 7 csh shims syntax-OK, 8 cases
  no config drift, 14 SAT codes round-trip pop_config, grep_value
  PRM round-trip correct). Run: 2026-05-20 (this release session).

## 9. Assumptions used

- The from-scratch sweep log at `gmtsar/python/work/sweep_fromscratch_v2_20260519_173857.log`
  constitutes the definitive pass baseline for this release. No re-run of
  the 3-hour sweep is required; the JSON scorecards in `work/results/` are
  still valid (no pipeline logic changed between that sweep and this commit,
  only the iono path — which is not exercised by any currently-enabled test
  case — and the pre_proc `else` branch).
- The wizard's 8 s PASS confirms no import-time or syntax regressions were
  introduced by the uncommitted changes folded into this commit.
- AUDIT findings #1, #2, #5 are PR-body corrections and do not affect the
  correctness of the local codebase or test results.
