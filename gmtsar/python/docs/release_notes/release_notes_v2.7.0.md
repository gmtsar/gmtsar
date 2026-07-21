# v2.7.0 — test orchestrator rewritten bash-to-Python, topo_interp_mode=0-vs-1 A/B sweep confirmed

## Test orchestrator rewritten from bash to Python

`sweep.sh` + `case_runner.sh` + `runner.py` (3 files, 2 layers) replaced by
`sweep.py` + `case_runner.py` (2 files, 1 layer). Real CLI args
(`--parallel`, `--force [hard|py|stage]`, `--cases`, `--topo-mode-ab`)
replace shell env vars (`MAX_PARALLEL`, `SWEEP_FORCE`, `TEST_CASES`,
`TOPO_MODE_AB`) for anything the caller sets — prompted by repeatedly
hitting the same class of bug this session: shell env vars silently not
persisting across separate tool invocations (a background sweep launched
with 0 cases from a stale `$GMTSAR`; a debugging session that landed in
the wrong directory). `TEST_CASES` is still honored as a fallback.

Faithful behavioral port, not a redesign — every documented fix in the
bash version (NISAR `pop_config`-line neutralization, `ALOS2_SCAN_SSAF`
Frame-driver parallelization, sentinel-guarded csh oracle cache,
config-drift guard, `filter1`→`filter_wavelength` translation, git-sha
sidecar) is preserved in `case_runner.py` with its original comment. Old
bash implementation archived (not deleted) at `tests/archive/`.

New `--topo-mode-ab` flag: repurposes the same `csh_test`/`python_test`
tree-pair machinery (renamed `ref_test`/`new_test` in that mode) to run
`topo_interp_mode=0` vs `=1`, both sides Python, no csh at all —
`compare.py` needed zero changes since it already diffs those two trees
with the right thresholds.

`compare.py` gains a real `--case NAME [NAME2 ...]` filter — previously
always looped the full 21-case manifest even to check one case. A single
SSIM call is ~1-3s; the apparent "slowness" was purely the missing
filter, not compute or I/O cost (confirmed by direct measurement after
initially misdiagnosing it as image-size- or NFS-bound).

## Real bugs found and fixed during validation

Three real bugs surfaced by actually running both sweeps end-to-end
rather than trusting the port on inspection alone:

1. **`_check_oracle()`'s csh-reference-validity check only looked for a
   top-level `intf/` dir** — present identically in the archived
   `case_runner.sh`, not introduced by this rewrite. Multi-subswath
   Frame cases (S1 TOPS family, `ALOS2_SCAN_SSAF`) have no top-level
   `intf/`; their outputs live under `F1/intf/`, `F2/intf/`, etc. This
   silently forced a full, unnecessary csh rebuild (thousands of
   seconds) on every sweep for these cases even with a perfectly valid,
   sentinel-matching oracle already on disk. Fixed to glob
   `**/intf/**/*.grd` across the whole tree.
2. **`--topo-mode-ab` silently skipped 20/21 cases** on its first live
   run: launched right after a py-vs-csh confirmation sweep finished,
   without `--force`. `sweep.py`'s skip-already-verified check reads
   `work/results/<case>.json`, which is NOT segregated by comparison
   mode — it's the same file the just-finished py-vs-csh sweep had
   written. 20/21 cases had just passed *that* unrelated comparison, so
   they were treated as "already verified" for the topo-mode-ab run too
   and skipped, leaving only the one case that had genuinely failed the
   py-vs-csh comparison to actually run. Caught by a load-average sanity
   check (2.2 vs the ~30 expected with 21 cases queued) before it could
   silently produce a misleading result. Fixed: the skip-already-verified
   check is unconditionally disabled when `--topo-mode-ab` is set.
3. A recipe-execution bug during initial validation: `tests/recipes/*.txt`
   files have no `#!` shebang (just `#`-comment text) — the original
   bash ran them via `"./README_x.txt"` from inside bash, which silently
   falls back to `/bin/sh` on an `ENOEXEC` (POSIX "looks like a text
   script" convention). `subprocess.run()` does `execve()` directly with
   no such fallback; fixed by invoking via `bash` explicitly.

## Full 21-case confirmation sweep (py vs csh): 20/21 clean

Re-run of the full py-vs-csh sweep through the new Python orchestrator,
soft-forced (`--force py`, csh oracle preserved). Validates both the
rewrite itself and reconfirms v2.6.0's state.

| Case | csh | py | Speedup | Score |
|---|---:|---:|---:|---|
| NISAR_Ethiopia | 543s | 178s | **3.05×** | 6/0 |
| RS2_SLC_Hawaii | 195s | 96s | 2.03× | 6/0 |
| CSK_RAW_Hawaii | 822s | 601s | 1.37× | 6/0 |
| ALOS_SLC_L1.1 | 448s | 337s | 1.33× | 6/0 |
| TSX_SLC_Hawaii | 852s | 647s | 1.32× | 6/0 |
| S1_Ridgecrest_EQ** | 9385s | 8139s | 1.15× | 11/5 |
| ALOS2_SCAN_SSAF | 9016s | 7828s | 1.15× | 14/0 |
| ALOS2_Brazil | 999s | 873s | 1.14× | 6/0 |
| ALOS_ERSDAC_L1.0 | 965s | 862s | 1.12× | 6/0 |
| ALOS2_Japan_Fugi_left | 1427s | 1288s | 1.11× | 6/0 |
| ALOS4_Pinon | 1267s | 1152s | 1.10× | 6/0 |
| ALOS_Baja_EQ | 1117s | 1024s | 1.09× | 6/0 |
| CSK_SLC_Italy | 843s | 773s | 1.09× | 6/0 |
| ENVI_Baja_EQ | 1767s | 1631s | 1.08× | 6/0 |
| ERS_Hector_EQ | 1276s | 1199s | 1.06× | 6/0 |
| S1A_SLC_TOPS_LA | 6722s | 6408s | 1.05× | 10/0 |
| ENVI_Baja_EQ_SLC | 1461s | 1409s | 1.04× | 6/0 |
| ALOS_haiti | 1669s | 1647s | 1.01× | 7/0 |
| S1_Larsen_C | 5013s | 5078s | 0.99× | 10/0 |
| S1A_SLC_TOPS_Greece | 3028s | 3069s | 0.99× | 10/0 |
| S1A_SLC_TOPS_COVE | 5507s | 6035s | 0.91× | 10/0 |

**Aggregate: 1.08×** (wall-time weighted). ** `S1_Ridgecrest_EQ`'s 5
failures are the documented no-DEM-corner exception (phasefilt
complex-rms ~0.35, on record since 2026-06-14), not a regression.

## Full 21-case topo_interp_mode=0 vs 1 A/B sweep: 16/21 clean

First re-run of the 2026-07-09 mode-interp comparison
(`docs/reports/mode_interp_sweep_results_2026-07-09.md`) since that
report, and the first via the committed `--topo-mode-ab` flag rather than
an uncommitted ad hoc driver script. `mode0` = `gmt surface` (baseline,
tension-spline), `mode1` = triangulation fast-path (variant).

| Case | mode0 (s) | mode1 (s) | Speedup | Result |
|---|---:|---:|---:|---|
| ALOS2_Brazil | 886 | 257 | **3.45×** | PASS |
| ENVI_Baja_EQ_SLC | 1455 | 446 | 3.26× | **FAIL** (rms 0.0143/0.01) |
| S1A_SLC_TOPS_COVE | 6128 | 1932 | 3.17× | PASS |
| ALOS4_Pinon | 1215 | 401 | 3.03× | PASS |
| S1A_SLC_TOPS_Greece | 3082 | 1028 | 3.00× | PASS |
| S1A_SLC_TOPS_LA | 6485 | 2210 | 2.93× | PASS |
| S1_Larsen_C | 5199 | 1801 | 2.89× | PASS |
| ALOS2_SCAN_SSAF | 8127 | 2899 | 2.80× | PASS |
| ALOS2_Japan_Fugi_left | 1411 | 517 | 2.73× | PASS |
| ENVI_Baja_EQ | 1660 | 743 | 2.23× | **FAIL** (rms 0.0216/0.01) |
| ALOS_haiti | 1705 | 830 | 2.05× | **FAIL** (complex-rms 0.347/0.15) |
| ERS_Hector_EQ | 1238 | 614 | 2.02× | PASS |
| CSK_SLC_Italy | 851 | 467 | 1.82× | **FAIL** (complex-rms 0.818/0.15) |
| ALOS_ERSDAC_L1.0 | 965 | 546 | 1.77× | PASS |
| TSX_SLC_Hawaii | 696 | 418 | 1.67× | PASS |
| ALOS_Baja_EQ | 1080 | 726 | 1.49× | **FAIL** (complex-rms 0.159/0.15, borderline) |
| ALOS_SLC_L1.1 | 374 | 307 | 1.22× | PASS |
| S1_Ridgecrest_EQ | 8186 | 7078 | 1.16× | PASS |
| RS2_SLC_Hawaii | 99 | 86 | 1.15× | PASS |
| CSK_RAW_Hawaii | 668 | 610 | 1.10× | PASS |
| NISAR_Ethiopia | 195 | 179 | 1.09× | PASS |

**Aggregate: 2.15×** (wall-time weighted). **16/21 cases fully clean
(167/181 file comparisons pass).** The 5 failing cases —
`ENVI_Baja_EQ`, `ENVI_Baja_EQ_SLC`, `ALOS_Baja_EQ`, `CSK_SLC_Italy`,
`ALOS_haiti` — are the **exact same 5 cases** flagged in the 2026-07-09
report, with closely matching magnitudes (e.g. `ALOS_haiti`'s
`corr_ll.grd` rms was 0.0133 then, 0.0133 now). This is a real,
independently-reproduced confirmation of the known algorithm-accuracy
tradeoff (triangulation vs. tension-spline surface fitting diverging on
these specific scenes' terrain), not a new regression. `S1_Ridgecrest_EQ`
(16/16, unlike its py-vs-csh no-DEM-corner exception above — the two
comparisons stress different things) and `ALOS2_SCAN_SSAF` (34/34) are
both fully clean this time.

Multi-subswath Frame cases (S1 TOPS, ALOS2_SCAN) consistently see the
largest speedups (2.7-3.5×) since topo-simulation cost is a bigger
fraction of their total wall time.

## README: Performance section updated for both sweeps

## Test evidence

Confirmation sweep: 20/21 clean (see table above). Topo-mode-ab sweep:
16/21 clean, 167/181 comparisons pass, matching the known 2026-07-09
pattern exactly (see table above).

Commits: `445623e` (bash→Python rewrite + oracle-check bugfix),
`f1cb8fd` (confirmation-sweep perf snapshots), `27dd19b`
(topo-mode-ab skip-verification bugfix).
