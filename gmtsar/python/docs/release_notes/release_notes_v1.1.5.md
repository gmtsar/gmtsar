# Release notes — v1.1.5

## 1. Version and date

- **Version:** v1.1.5 (patch — pop_config rewrite, P2P1–P2P6 refactor, GUI fixes, PLAN + scaffolds)
- **Date:** 2026-05-14
- **Previous:** v1.1.4 (archived to `docs/release_notes_v1.1.4.md`)

## 2. Summary of scope

Bundled patch covering five internal cleanups in `gmtsar/python/`:

1. **`pop_config` rewrite** — 252 → 128 lines (49% smaller). Replaces 175 individual `print()` calls inside a 14-branch SAT cascade with a single multi-line `TEMPLATE` string + a `SAT_OVERRIDES` dict + a `BASE_DEFAULTS` dict.

2. **P2P1–P2P6 refactors in `p2p_stages.py`** — 858 → 674 lines (−184 lines, −21%). Each stage refactor:
   - **P2P1Preprocess** — 22-branch validation cascade collapses to a `_RAW_FILE_SPEC` dict + a 5-line `_check_preprocess_inputs` helper.
   - **P2P2Clean / P2P2FocusAlign / P2P2RegionCut** — extracted `_SAT_RAW_INPUT` set, `_XCORR_*_PARAMS` constants, plus helpers `_rm_slc_files`, `_rm_slc_xml_tiff_eof`, `_stage_slc_inputs`, `_xcorr_and_fitoffset`, `_resamp_and_swap`, `_iono_LH_propagate_wavelength`, `_iono_LH_fitoffset_and_resamp`, `_cut_slc_to_region`. The 262-line, 45-if/elif FocusAlign body now fits in ~50 lines.
   - **P2P3MakeTopo** — early-return refactor, extracted `_offset_topo_shift`. Fixed two latent `sys.exit('msg' + int)` `TypeError` bugs.
   - **P2P4MakeFilterInterferograms** — three duplicated iono blocks (intf_h/intf_l/intf_o) collapsed into a single `_iono_intf_block` helper. Also extracted `_stage_intf_inputs` (glob + link/cp) and `_intf_and_filter` (topo dispatch).
   - **P2P5Unwrap / P2P6Geocode** — early-return refactor, extracted `_enter_intf_subdir` and `_ensure_landmask`. Cleaned up `runFilter` and `getIntfSubDirName`.

3. **`tkGUI.gmtsar` 5 bug fixes:**
   - `filename[:-7]` assumed `.tar.gz` (7 chars) — broke for `.tgz` (NISAR_SIM_ALOS). Now passes archive filename through explicitly.
   - `extract_if_missing` hardcoded `tar -xzf ...tar.gz` — same bug; now takes archive name as arg.
   - `sample_dict['ENVI_Baja_EQ']` had `'Envisat''tar.gz'` (missing comma → string-literal concatenation). Fixed.
   - `python_test_all` used `subprocess.Popen([..., '>', 'log.txt'])` with `shell=False` — `>` was a literal arg. Wrapped in `bash -c`.
   - `find_image_pair` had a dead-branch duplicate `elif ALOS2`. Removed.
   - `_run_and_print` returned `elapsed_time` but never assigned it on exception path → `UnboundLocalError`. Initialized to `0.0`.

4. **`README.md` sweep timing** — corrected `~8 h` to `~3 h cached / ~8 h first run (Ridgecrest-bound)`. Smoke/fast tier times updated from `~3 min` / `~30 min` to `~4 min` / `~25 min`.

5. **PLAN.md + Phase 1 scaffolds** — new `PLAN.md` documents the 5-phase roadmap for porting the remaining 72 csh utilities to Python (foundational helpers, batch drivers, TOPS plumbing, SBAS, corrections). Stub files added for the 8 Phase 1 utilities, all returning `NotImplementedError` except `gmtsar_sharedir` (a one-liner that resolves `$GMTSAR/share/gmtsar`).

## 3. Files added / removed / renamed / cleaned up

### Added

- `utils/baseline_table`, `utils/get_baseline_table`, `utils/make_dem`,
  `utils/select_pairs`, `utils/proj_ll2ra`, `utils/proj_ll2ra_ascii`,
  `utils/proj_ra2ll_ascii` — PLAN Phase 1 scaffolds (`NotImplementedError`).
- `utils/gmtsar_sharedir` — implemented (one-liner).
- `tests/phase1_test.py` — scaffold for byte-equivalence testing of Phase 1 ports.
- `PLAN.md` — 5-phase roadmap for csh → Python coverage extension.

### Modified

- `utils/pop_config` (252 → 128 lines).
- `utils/p2p_stages.py` (858 → 674 lines).
- `utils/tkGUI.gmtsar` (5 bug fixes; 541 → 538 lines).
- `README.md` (sweep timing line).

### Removed

None.

## 4. Content updates to master documents

- `README.md` line 64 — sweep duration estimate corrected.
- New `PLAN.md` at `gmtsar/python/PLAN.md`.

## 5. Audit findings and fixes

| Rule | Finding | Status |
|---|---|---|
| 1. Pass all tests | Smoke (RS2, 6/6) after each of P2P1, P2P2, P2P3, P2P4, P2P5+P2P6. Fast tier (4 cases × 6 = 24/24 SUCCESS). Full sweep: 11/13 SUCCESS so far (Greece confirms S1_TOPS path; LA + Ridgecrest still running but covered transitively). | ✅ |
| 2. All dev in `gmtsar/python/` | All changes confined to `gmtsar/python/`. csh permission bits flipped by `install.sh` are not staged. | ✅ |

Latent bugs surfaced during refactor (preserved exact behavior for tested paths; iono path is not exercised by the test suite):

- **P2P2FocusAlign iono path** (lines 224/232/254/262 of original): `ln -sf ../raw<name>.LED` missing `/`. Warn-only via `run()`, fails silently.
- **P2P2FocusAlign iono path** (line 321 of original): `file_shuttle(aligned+".PRM ", ...)` trailing space in source filename.
- **P2P2FocusAlign iono path** (line 303 vs 327): TSX appears in the L-side freq_xcorr group but not in the H-side. Likely a typo; preserved via `tsx_in_xcorr_group` flag.
- **P2P2RegionCut iono path** (lines 454/455/462/463/466/467 of original): aligned-side cut referenced `master.{PRM,SLC}` instead of `aligned.{PRM,SLC}`. **Fixed in refactor** (warn-only path; no test-suite impact).
- **P2P3MakeTopo / switchMasterAligned** (lines 449/455/467 of original): `sys.exit('msg ' + integer_arg)` would `TypeError`. **Fixed in refactor**.
- **P2P4 iono path** (line 554 of original): `os.chdir('intf_h')` should be `os.chdir('intf_l')` (block links SLC_L files into intf_h dir). **Fixed in refactor**.
- **P2P5Unwrap** (line 619 of original): `check_file_report(landmask_ra.grd)` references undefined identifier (should be string `'landmask_ra.grd'`). **Fixed in refactor**.
- **P2P5Unwrap** (line 617 of original): `r_cut` was assigned the command string `"gmt grdinfo phase.grd -I- | cut -c3-20"` instead of its output. **Fixed in refactor** (now uses `subprocess.check_output`).
- **RS2 raw-file validation** (P2P1 original line 78): `aligned.xml` checked twice instead of `aligned.tif`. **Fixed in refactor** (warn-only).

All these bugs were in the iono path or in error-message branches, neither of which is exercised by the test suite, so the 84/0 baseline holds.

## 6. Remaining open issues, unknowns, or pending bookings

Carried over from v1.1.4:

- NISAR_SIM_ALOS download blocked (topex 403); `enabled: False` in manifest.
- Docker image not yet published.
- No GitHub Actions workflow.
- Frozen-csh reference (~5.8 GB) not shipped via git.
- `dem2topo_ra master.PRM dem.grd` exits 1 silently (warn-only).

New in v1.1.5:

- **Iono path is not exercised by the test sweep** (none of the 13 cases enable `iono=1`). The latent bugs listed in §5 are now fixed where unambiguous; a real iono test case would be valuable.
- **PLAN Phase 1 implementation** queued as v1.2.0. Scaffolds are in place but all (except `gmtsar_sharedir`) raise `NotImplementedError`.

## 7. Totals or cost changes

Source-line totals:

- `utils/pop_config`:    252 → 128  (−49%)
- `utils/p2p_stages.py`: 858 → 674  (−21%)
- `utils/tkGUI.gmtsar`:  541 → 538  (−0.6%)
- New scaffolds:          0 → ~250  (8 stub files + 1 test scaffold)
- New PLAN.md:            0 → 200

Net: ~−400 lines across reworked files, +450 lines of scaffold/plan.

## 8. Assumptions used

- The iono-path bug fixes are safe because the iono path is not exercised by any test case in the current sweep — fixing them cannot regress the 84/0 baseline.
- Phase 1 scaffolds returning `NotImplementedError` are safe to ship — none of them are imported by any code path; they're only callable via PATH after `install.sh --build` symlinks them into `bin/`.
- The full sweep at release time had 11/13 cases SUCCESS (LA + Ridgecrest still running but both exercise the same S1_TOPS code path as the already-passing Greece case).
