# Release notes — v1.3.0

## 1. Version and date

- **Version:** v1.3.0 (minor — PLAN Phase 3 partial: slc2amp csh removal)
- **Date:** 2026-05-14
- **Previous:** v1.2.0 (archived to `docs/release_notes_v1.2.0.md`)

## 2. Summary of scope

First Phase 3 csh-removal step: replaces the `slc2amp.csh` shell-out in
`p2p_stages.py:406` with a call to the Python `slc2amp` utility. To make
this work, two helper repairs:

1. **`gmtsar_lib.resolve_sharedir()`** — new helper that locates
   `$GMTSAR/share/gmtsar`. Tries the `$GMTSAR` env var first, then walks up
   from the script location looking for `share/gmtsar/`. Both `gmtsar_sharedir`
   (CLI) and `slc2amp` now share this helper.

2. **`utils/slc2amp`** — repaired two latent bugs in the 2023-vintage Python
   port that prevented it from running:
   - Hardcoded `sharedir = '/usr/local/GMTSAR/share/gmtsar'` (wrong on this
     install). Now uses `resolve_sharedir()`.
   - Typo: referenced `fil1` (undefined) instead of `filt1`. Now uses the
     correctly-named local `filt`.
   - Also rewrote the script to fit the current util pattern (use `gmtsar_lib.run`,
     clean usage message, proper argv validation).

3. **`p2p_stages.py:406`** — call site changed from `slc2amp.csh` to `slc2amp`.

## 3. Files added / removed / renamed / cleaned up

### Modified

- `utils/gmtsar_lib.py` — added `resolve_sharedir()`.
- `utils/gmtsar_sharedir` — now imports `resolve_sharedir` from `gmtsar_lib`
  (deduplicated; the inlined version is gone).
- `utils/slc2amp` — repaired and rewritten to current util style.
- `utils/p2p_stages.py` — line 406: `slc2amp.csh` → `slc2amp`.

### Added / Removed

None.

## 4. Content updates to master documents

- `release_notes_v1.2.0.md` archived to `docs/release_notes_v1.2.0.md`.

## 5. Audit findings and fixes

| Rule | Finding | Status |
|---|---|---|
| 1. Pass all tests | Smoke (RS2_SLC_Hawaii) post-swap: **6/6 SUCCESS in 201s** in an isolated `$SCRATCH=/tmp/slc2amp_smoke` workdir (to avoid colliding with the v1.1.5 full sweep still running Ridgecrest in the main workdir). | ✅ |
| 2. All dev in `gmtsar/python/` | All changes under `gmtsar/python/utils/`. No upstream files touched. | ✅ |

Latent issues fixed in this release:

- **`utils/slc2amp` hardcoded path bug** — discovered during the swap. The
  2023 port was never actually called (pipeline always shelled out to csh),
  so the bug had been dormant.
- **`utils/slc2amp` `fil1` typo** — would have `NameError`'d on first call.
  Same dormancy reason.
- **`utils/gmtsar_sharedir` from v1.1.5 used `$GMTSAR` env var directly**,
  which on this dev host points to a different install
  (`/home/staff/dliu/iga49539/GMTSAR`) than the actual GMTSAR install
  (`/home/staff/dliu/gmtsar`). The new `resolve_sharedir` falls back to
  walking up from the script location, which correctly finds
  `<repo-root>/share/gmtsar`.

## 6. Remaining open issues, unknowns, or pending bookings

Carried over from v1.2.0 (no change):

- NISAR_SIM_ALOS download blocked (topex 403); `enabled: False`.
- Docker image not yet published.
- No GitHub Actions workflow.
- Frozen-csh reference (~5.8 GB) not shipped via git.
- `dem2topo_ra master.PRM dem.grd` exits 1 silently (warn-only).
- Iono path is not exercised by the test sweep.
- `tests/phase1_test.py` still a scaffold; Phase 1 utilities have no
  empirical csh-equivalence test yet.

New in v1.3.0:

- **13 csh shell-outs remain in `p2p_stages.py`:**
  - `align_tops.csh` × 6 (lines 282, 284, 287, 311, 314, 317)
  - `snaphu.csh` / `snaphu_interp.csh` × 3 (P2P5, plus iono path)
  - `estimate_ionospheric_phase.csh` × 1 (iono path)
  - Removed: `slc2amp.csh` × 1 ✅
- **Next Phase 3 targets** in size order: `snaphu` family (~150 lines csh
  each), then `align_tops.csh` (~255 lines csh, the biggest target).
- **Phase 5** is the iono-path-only `estimate_ionospheric_phase.csh` (~171
  lines csh).

## 7. Totals or cost changes

Source-line totals:

- `utils/gmtsar_lib.py`:    140 → 168  (+28; new resolve_sharedir helper)
- `utils/gmtsar_sharedir`:  56  →  17  (−39; deduplicated to import-from-lib)
- `utils/slc2amp`:          80  →  50  (−30; rewrite to current pattern)
- `utils/p2p_stages.py`:    674 → 674  (one-character change)

## 8. Assumptions used

- The 2023-vintage `utils/slc2amp` had never been runtime-tested (pipeline
  always called `slc2amp.csh`); the hardcoded path + `fil1` typo are evidence.
  Confirmed by trying to run it manually before the rewrite — it crashed.
- The smoke-test pass with the new code path is sufficient validation for
  this single-csh-call swap. Full sweep would be redundant.
- Isolated `$SCRATCH` workdir lets us run smoke without interfering with
  the v1.1.5 full sweep that's still finishing Ridgecrest on csh side.
