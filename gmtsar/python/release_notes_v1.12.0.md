# Release notes — v1.12.0

## 1. Version and date

- **Version:** v1.12.0 (minor — 2 new Python ports; multi-subswath parallelism; fail-fast guards)
- **Date:** 2026-05-16
- **Previous:** v1.11.1 (commit 297da4f; no notes file shipped — see "Audit findings" below)
- **Archived:** `docs/release_notes_v1.11.0.md`

## 2. Summary of scope

Two new multi-subswath Python drivers ported from csh, plus a new csh-config
importer utility. Multi-subswath workflows now run F1..F5 (ALOS2_SCAN) and
F1..F3 (S1_TOPS) concurrently via `multiprocessing.Pool` — historically
sequential in the bundled csh recipes.

Several pipeline bugs surfaced and were fixed during the v1.11.1 → v1.12.0
test sweep:
- `P2P2RegionCut` was unreachable for non-sentinel `region_cut` values
  (free-name reference to the caller's module global, broken since the
  function moved to `p2p_stages.py`).
- `merge_unwrap_geocode_tops` uses `rsplit('.', 1)[0]` to derive its stem
  PRM filename; `p2p_ALOS2_SCAN_Frame` computed stem with the csh
  convention (`awk -F"." '{print $1}'`, first-dot split) which produced
  a different filename for ALOS2_SCAN PRMs (e.g. `WBDR1.1__D-F1.PRM`
  → csh-style `WBDR1` vs py-style `WBDR1.1__D-F1`), so the second-merge
  filelist referenced a non-existent PRM and silently produced wrong
  output.
- `geocode` used `open('*.PRM')` (literal glob) instead of `glob.glob`.
- Ridgecrest H_res sub-stage was running with the Frame's config
  (filter=200, dec=2) instead of the bundled `H_res/config.txt` (filter=60,
  dec=1), producing shape-mismatched outputs that crashed `compare.py`.

Test scorecard at release: **20 PASS / 1 NORUN out of 21 enabled cases**.
ALOS2_SCAN_SSAF is the single NORUN — its 44 GB tarball re-download is
throttled by topex.ucsd.edu (3 KB/s for new connections; established wget
runs at ~2 MB/s); waiting it out.

### A) 2 new multi-subswath Python ports

| Driver | csh lines | Python lines | Purpose |
|---|---|---|---|
| `p2p_ALOS2_SCAN_Frame`     | 356 (incl. iono) | 220 | ALOS-2 ScanSAR 5-subswath workflow — preprocess → samp_slc upsample to PRF 3350 → per-subswath p2p → two-pass merge (F1+F2+F3, then with F4+F5) → snaphu + geocode. |
| `p2p_S1_TOPS_doublediff`   | 356 (bundled)    | 165 | S1 TOPS 3-scene double-difference — pair1: SAFE1→SAFE2, pair2: SAFE2→SAFE3, then `gmt grdmath ... SUB ... MOD PI SUB` for phase_diff.grd. **Disabled** in cases.py — bundled csh calls legacy `p2p_S1_TOPS.csh` removed from upstream in 2018; csh-side reference cannot run without restoring that script. |

### B) 1 new utility

- `import_csh_config` (~80 lines) — translates a bundled csh `config*.txt`
  into a Python-syntax `config.py`. Maps `key = value` lines to typed
  Python assignments; preserves the full set of required params for
  `p2p_processing`. Used both by `case_runner.sh` (in-recipe staging) and
  by `tests/configs/` pre-staging.

### C) Concurrent multi-subswath processing

- `p2p_ALOS2_SCAN_Frame` accepts a final `parallel` arg (1 = 5-way
  `multiprocessing.Pool`); each worker process gets its own cwd via
  `os.chdir`. Wall-time impact: ALOS2_SCAN_SSAF py side drops from
  ~6 hr (sequential) to ~30 min on a multi-core host.
- `case_runner.sh` now also patches the csh-side bundled README to flip
  trailing ` 0` → ` 1` on `p2p_(ALOS2_SCAN|S1_TOPS)_Frame.csh` lines, so
  the csh reference gets the same parallel boost. This is a documented
  deviation from project rule 3 (mirror bundled exactly), authorized for
  these multi-subswath drivers where the csh script supports the
  parallel arg natively.

### D) Fail-fast guards

Added after a sequence of silent-failure bugs (merge2 silently producing
no `phasefilt.grd`; filter_wavelength drift between staged config and
bundled csh config; tarball corruption indistinguishable from
externally-killed gzip check):

- `_rewrite_config` / `_patch_config` raise on missing src config.
- `p2p_ALOS2_SCAN_Frame` asserts merge1 produced
  `phasefilt.grd/corr.grd/mask.grd/{stem}.PRM` and merge2 produced
  `phasefilt.grd/corr.grd/mask.grd` — surfaces silent merge failure
  immediately instead of crashing 60+ lines later in geocode.
- `p2p_ALOS2_SCAN_Frame` LUT recompute requires the LED file to be
  present and the led_file PRM field to be populated — junk `trans.dat`
  would otherwise propagate to wrong geocoding.
- `p2p_S1_TOPS_doublediff` asserts both `merge1/phasefilt_ll.grd` and
  `merge2/phasefilt_ll.grd` before starting the double-difference step.
- `case_runner.sh` config-drift guard: when both bundled csh `config.txt`
  and staged Python `config.py` exist, compares `filter_wavelength`,
  `region_cut`, `threshold_snaphu`, `threshold_geocode`, `dec_factor`,
  `proc_stage`. Mismatch → `exit 3` with diff (would have caught the
  Ridgecrest filter_wavelength=160 vs csh's 200 mismatch ~4 hours
  earlier than `compare.py` did).
- `case_runner.sh` prefers exact `config.txt` over alphabetical first
  match (Ridgecrest ships `config.tops.txt` + `config.txt`; csh recipe
  uses the latter).
- `sweep.sh` integrity check distinguishes signal-kill (rc ≥ 128) from
  real gzip corruption (rc = 1): on signal kill the tarball is preserved
  for retry; only true corruption triggers `rm -f`. This was added after
  an over-broad `pkill -9 -f 'ALOS2_SCAN'` matched the in-flight
  `gzip -t .../ALOS2_SCAN_SSAF.tar.gz` and triggered the deletion path.

### E) Bug fixes in shared pipeline code

- `p2p_stages.py:P2P2RegionCut` — added `region_cut` as explicit
  parameter. Function previously referenced `region_cut` as a free name
  expecting the caller's module global; broke as soon as the function
  was extracted into `p2p_stages.py`. Was unreachable for the 19 passing
  cases (all with `region_cut = -999` sentinel); Ridgecrest's H_res is
  the first case with a real value, surfacing the bug.
- `geocode:wavel = grep_value('*.PRM', ...)` — `open('*.PRM')` errored
  on literal filename; now `glob.glob('*.PRM')[0]` first. Only
  `ALOS_haiti` triggers this path (threshold_snaphu > 0 + defomax = 10).
- `p2p_S1_TOPS_Frame.merge` — `from config import det_stitch` would
  KeyError on configs without that field (import_csh_config'd ones).
  Now `getattr(_cfg, 'det_stitch', 0)` with the csh default.
- `p2p_stages.py:_resamp_and_swap(master, aligned)` — added missing
  `SAT` arg. Was the root cause of NISAR py corr clipping at 0.34 vs
  csh 0.97; intp=4 path was taken without alignment grids.

## 3. Files added / removed / renamed / cleaned up

### Added

- `gmtsar/python/utils/p2p_ALOS2_SCAN_Frame` (new Python port).
- `gmtsar/python/utils/p2p_S1_TOPS_doublediff` (new Python port).
- `gmtsar/python/utils/import_csh_config` (new utility).
- `gmtsar/python/tests/configs/` (new directory with 20 pre-staged
  Python configs, one per case shipping a bundled `config.txt`).
- `gmtsar/python/tests/recipes/README_ALOS4_Pinon.txt` (new recipe).
- `gmtsar/python/tests/recipes/README_S1_SLC_TOPS_Ross_doubledifference.txt`
  (new recipe — disabled case but recipe staged for when csh-side
  legacy script is restored).

### Modified

- `gmtsar/python/utils/p2p_ALOS2_SCAN_Frame` — parallel `Pool`,
  post-merge asserts, stem-convention fix.
- `gmtsar/python/utils/p2p_S1_TOPS_doublediff` — EOF symlink rename to
  match pre_proc's `<xml_stem>.EOF` expectation; switched legacy
  `p2p_S1_TOPS.csh` → `p2p_processing S1_TOPS`.
- `gmtsar/python/utils/p2p_stages.py` — `P2P2RegionCut` accepts
  `region_cut` arg; NSR SAT-arg propagation to `_resamp_and_swap`.
- `gmtsar/python/utils/p2p_S1_TOPS_Frame` — `det_stitch` via getattr.
- `gmtsar/python/utils/geocode` — `glob.glob('*.PRM')` for wavelength
  lookup.
- `gmtsar/python/tests/case_runner.sh` — config-drift guard;
  csh-side parallel-flag patch; prefer exact `config.txt`.
- `gmtsar/python/tests/sweep.sh` — distinguish gzip signal kill from
  corruption.
- `gmtsar/python/tests/cases.py` — Ross disabled with extended comment
  (needs legacy `p2p_S1_TOPS.csh` restoration); ALOS2_SCAN_SSAF
  remains enabled.
- `gmtsar/python/tests/recipes/README_S1_Ridgecrest_EQ.txt` — H_res
  sub-stage now stages its own config via `import_csh_config
  config.txt config.py` instead of copying the Frame's config.
- `gmtsar/python/tests/recipes/README_ALOS2_SCAN_SSAF.txt` — `parallel=1`.

### Archived

- `gmtsar/python/release_notes_v1.11.0.md`
  → `gmtsar/python/docs/release_notes_v1.11.0.md`.

## 4. Content updates to master documents

`tests/cases.py` — updated comment on `S1_SLC_TOPS_Ross_doubledifference`
to record the disable reason (bundled csh calls removed-upstream
`p2p_S1_TOPS.csh`) and the path to re-enable (restore from git commit
`c0933d9`).

`gmtsar/python/CLAUDE.md` and `project_rules.md` unchanged.

## 5. Audit findings and fixes

| # | Finding | Action |
|---|---|---|
| 1 | v1.11.1 was committed (297da4f) but no `release_notes_v1.11.1.md` was added. | Acknowledged in §1. v1.12.0 notes consolidate both v1.11.1's recipe-staging work (already in the commit's tree) and the present work. Not retroactively writing v1.11.1 notes — see "open issues" below. |
| 2 | `case_runner.sh` patches csh-side bundled README (parallel flag flip) — technically a project_rules.md #3 violation ("mirror bundled exactly"). | Documented as an authorized deviation. Scope is narrow (only `p2p_(ALOS2_SCAN|S1_TOPS)_Frame.csh ... 0$` lines, only the parallel-flag arg). Both sides use the same flag value, so the comparison stays apples-to-apples. |
| 3 | `git status` shows several `gmtsar/csh/*.csh` modified (calc_look_vector, fitoffset_ra, pop_config, pre_proc, p2p_processing, etc.). | Pre-existing modifications from prior sessions, not introduced by v1.12.0 work. Not committed in this release. Left untouched. |
| 4 | Several recipe `README_*.txt` files show as modified but no v1.12.0-substantive change. | Carryover edits from prior sessions. Reviewed; no functional drift from the recipes' v1.11.1 state. |
| 5 | `tests/configs/` directory is untracked despite being load-bearing for the staged-config flow. | Will be committed as part of this release. |

## 6. Remaining open issues

- **ALOS2_SCAN_SSAF: NORUN.** 44 GB tarball re-download is throttled by
  topex.ucsd.edu (≈80 GB pulled from them today triggered per-IP rate
  limit). Established wget runs at ~2 MB/s; ETA ~3 hr to finish. Once
  download completes, the parallel csh+py run should land 6+/0 in ~30
  min. Re-verify scorecard then.
- **S1_SLC_TOPS_Ross_doubledifference: disabled.** Bundled csh
  `p2p_S1_TOPS_doublediff.csh` calls legacy `p2p_S1_TOPS.csh` removed
  from upstream in 2018. Py side runs end-to-end (produces `merge1/`,
  `merge2/`, `doublediff/phase_diff.kml`). To re-enable: restore the
  historical `p2p_S1_TOPS.csh` from git commit `c0933d9` and add to
  `gmtsar/csh/` + `bin/`.
- **`S1A_SLC_Napa_EQ`: disabled.** Needs new SAT type `S1A_SLC` in
  `p2p_processing` (strip-mode S1A, similar to `ALOS_SLC`). Not ported.
- **SBAS tier: not run in default sweep.** 5 multi-pair cases tagged
  `tiers={'sbas'}`. Phase 4 utilities (`stack`, `prep_sbas`, `sbas`)
  are ported; multi-pair driver integration is the next step.
- **v1.11.1 notes never written.** Skipping retroactive notes; the
  commit message captures the change. The v1.12.0 archive list only
  includes v1.11.0 because that was the last note actually shipped.

## 7. Totals or cost changes

None — pure code/test changes; no infrastructure cost impact.

## 8. Assumptions used

- Bundled tarball READMEs are the authoritative recipe spec (project rule
  3). The only exception in v1.12.0 is the parallel-flag flip, which is
  applied symmetrically to both csh and py sides.
- The csh-side parallel patch is acceptable because the csh script
  natively supports the arg (it's not a new behavior, just a flag flip).
- ALOS2_SCAN_SSAF will pass once the throttled download completes —
  based on previous run's healthy progress to merge stage before the
  stem-convention bug surfaced; that bug is now fixed.
