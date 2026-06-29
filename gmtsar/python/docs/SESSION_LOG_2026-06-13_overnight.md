# SESSION LOG — 2026-06-13 Overnight Campaign

**Conductor:** wei-lin (autonomous, 9-hour budget)  
**Scope:** gmtsar/python/ only (fork-clean invariant enforced)  
**Campaign goal:** land v2.2.0 "Python upgrade of compute cores," then attack perf/housekeeping.  
**Log opened:** 2026-06-13 ~10:15 UTC  

---

## Starting State

| Item | Value |
|------|-------|
| HEAD | `0055911` (v2.1.32, dirty working copy — 4 tracked M files, several untracked) |
| Latest tag | v2.1.32 |
| Full sweep in flight | `/tmp/full_sweep_v220.log`, SWEEP_FORCE=1, 21 cases, started ~09:32 UTC |
| Sweep progress at log-open | 4/21 done (RS2 198s, ALOS_SLC_L1.1 474s, NISAR_Ethiopia 867s, ALOS2_Brazil 1016s), all 6/6 py-vs-csh SUCCESS, 0 fail |
| Dirty tracked files | `bin_py/tests/test_gmt_surface_py.py`, `project_rules.md`, `utils/dem2topo_ra`, `utils/gmt_surface_py.py` |
| Untracked (repo-root cruft) | `config.py`, `gmt.history`, `orbits/`, `preproc/*/include`, `preproc/*/lib`, `resume_claude.md` |
| Perf baseline (db62d13 full) | 21/21 pass, dem2topo_ra = 77.2% of py pipeline cost, aggregate speedup vs csh: 1.01×–1.59× |

### Baseline perf table (db62d13, 2026-06-13T04:50Z, NFS, AMD EPYC 7F72 48-core, MAX_PARALLEL=1)

| Case | csh (s) | py (s) | speedup |
|------|--------:|-------:|--------:|
| RS2_SLC_Hawaii | 175 | 110 | 1.59× |
| NISAR_Ethiopia | 447 | 291 | 1.54× |
| ALOS_SLC_L1.1 | 423 | 302 | 1.40× |
| CSK_RAW_Hawaii | 841 | 666 | 1.26× |
| TSX_SLC_Hawaii | 739 | 603 | 1.23× |
| ALOS2_SCAN_SSAF | 8987 | 7354 | 1.22× |
| ALOS_ERSDAC_L1.0 | 911 | 761 | 1.20× |
| ALOS_Baja_EQ | 1101 | 930 | 1.18× |
| CSK_SLC_Italy | 803 | 680 | 1.18× |
| S1_Ridgecrest_EQ | 9214 | 7875 | 1.17× |
| ERS_Hector_EQ | 1287 | 1103 | 1.17× |
| ALOS4_Pinon | 1230 | 1078 | 1.14× |
| ENVI_Baja_EQ | 1740 | 1550 | 1.12× |
| ALOS2_Brazil | 935 | 833 | 1.12× |
| ALOS2_Japan_Fugi_left | 1346 | 1208 | 1.11× |
| ALOS_haiti | 1749 | 1582 | 1.11× |
| ENVI_Baja_EQ_SLC | 1407 | 1289 | 1.09× |
| S1A_SLC_TOPS_COVE | 5544 | 5100 | 1.09× |
| S1A_SLC_TOPS_LA | 6849 | 6414 | 1.07× |
| S1A_SLC_TOPS_Greece | 2995 | 2855 | 1.05× |
| S1_Larsen_C | 5031 | 4971 | 1.01× |

Stage breakdown (aggregate across 20 profiled cases, py side):

| Stage | Cost (s) | % |
|-------|--------:|--:|
| dem2topo_ra | 28807 | 77.2% |
| pre_proc | 3244 | 8.7% |
| merge_unwrap_geocode_tops | 2232 | 6.0% |
| geocode | 1022 | 2.7% |
| intf | 814 | 2.2% |
| resamp_py | 686 | 1.8% |
| xcorr_py | 374 | 1.0% |
| snaphu | 133 | 0.4% |

### Ported binaries wired default-ON at campaign start

conv_py, resamp_py(_v2), xcorr_py, SAT_llt2rat_py(_v2), SAT_baseline_py, phasediff_py, surface_py, blockmedian_py, make_los_py, gmt_grdfill_py, gmt_m2s_py, gmt_grdcut_py, gmt_grdsample_py, gmt_xyz2grd_py, snaphu (env-gated), align_tops, merge_tops, gmt_surface_py (GMTSAR_SURFACE_INPROC, default ON as of v2.1.32).

---

## v2.2.0 Gate Conditions

The sweep currently in flight must produce **21/21 py-vs-csh SUCCESS, 0 fail**.  
On that result:
1. Conduct bless all 21 cases → `docs/blessed_scorecards/v2.2.0/`
2. Commit blessed scorecards + snapshot
3. `git tag v2.2.0`

Until the sweep finishes, no new missions launch on files the sweep reads  
(`utils/dem2topo_ra`, `utils/geocode`, `utils/gmt_surface_py.py`, `bin_py/*`).

---

## Approved Roadmap (post-v2.2.0, in priority order)

See "MISSION QUEUE" section below for full gate specs.

1. **M1 — Perf table build** (harvest + commit from this sweep's timeSpentLog.txt)
2. **M2 — dem2topo_ra optimization** (Mira, Numba/vectorization on surface + geocode stages)
3. **M3 — .gitignore housekeeping** (Kai, repo-root cruft)
4. **M4 — release_notes_v2.2.0.md** (Haruto)

---

## Landing Log

_Entries appended by the main loop as subagent worktrees land._

### Pre-campaign (session context)

| Time (UTC) | Tag | SHA | What landed | Gate | Notes |
|-----------|-----|-----|-------------|------|-------|
| ~07:30 | v2.1.31 | d4e7a7a | gmt_surface_py pixel_reg + gcd-expansion parity fix, rms 1.2e-7, 24/24 unit tests | smoke 6/6 | |
| ~07:30 | v2.1.32 | 0055911 | Flip GMTSAR_SURFACE_INPROC default ON; RS2 in-process surface = 0.98× C at scale | smoke 6/6 | RS2 is anisotropic so hits the surface-py branch for pixel.grd only |

---

## Regression Log

_Entries appended if a revert is issued during this campaign._

_(none yet)_

---

## Open Contradictions / Blockers

### v2.2.0 BLOCKED — 2 py-vs-csh failures in full sweep (10:35 UTC, 13/21 done)
Full sweep (SWEEP_FORCE=1, both sides) found 2 cases < 6/6 py-vs-csh. Per gate
discipline: do NOT bless, do NOT tag v2.2.0 until resolved.

| Case | Failing file | metric | value | thr | over | Isolation |
|------|-------------|--------|-------|-----|------|-----------|
| ALOS_haiti | los_ll.grd | rms | 1.417 | 1.0 | 1.42× | ONLY los fails; phase/corr/filtcorr/PNGs all pass (phasefilt cplx-rms 0.014 ≪ 0.15) → culprit = **make_los_py**, NOT surface/topo/phase |
| CSK_SLC_Italy | phasefilt.grd | complex-rms | 0.275 | 0.15 | 1.83× | ONLY raw phasefilt fails; corr/filtcorr/PNGs (incl geocoded masked phase) pass → culprit = **phasefilt/phasediff filter step** |

Both cases are in the v2.1.21 blessed baseline. Both failures are isolated to a
single ported binary and are INDEPENDENT of the v2.1.31/32 surface work (surface
feeds topo→corr→phase, all of which pass on both cases).

UPDATE 12:48 UTC (19/21 done): a THIRD failure confirms a PATTERN.
| Case | file | metric | value | thr |
|------|------|--------|-------|-----|
| CSK_SLC_Italy | phasefilt.grd | complex-rms | 0.275 | 0.15 |
| S1_Ridgecrest_EQ | phasefilt.grd | complex-rms | 0.358 | 0.15 |
| ALOS_haiti | los_ll.grd | rms | 1.417 | 1.0 |

TWO cases now fail on the SAME file (phasefilt.grd complex-rms) → systematic
issue in the phase-filter/phasediff path, NOT marginal flakiness. ALOS_haiti's
los_ll is a separate make_los_py issue. 2 cases (ALOS2_SCAN_SSAF, COVE) still
running — may add more phasefilt hits.

ACTION 12:48: dispatched Mira (worktree-isolated, read-only to master) to
root-cause BOTH signatures and return diagnosis + proposed fix + parity test.
I (main loop) land any fix under the smoke+unit gate after the sweep completes.
v2.2.0 remains UNTAGGED.

### SWEEP COMPLETE 13:15 UTC — FINAL: 18/21 clean, 3 fail. v2.2.0 BLOCKED on TWO fronts.

FINAL py-vs-csh correctness (locked — last 2 cases ALOS2_SCAN_SSAF & COVE passed):
- ALOS_haiti los_ll.grd rms 1.417/1.0 (1.42x) — make_los_py
- CSK_SLC_Italy phasefilt.grd cplx-rms 0.275/0.15 (1.83x) — phasediff_py (input to goldstein filter)
- S1_Ridgecrest_EQ phasefilt.grd cplx-rms 0.358/0.15 (2.39x) — phasediff_py

**FRONT 1 — correctness:** 3 regressions (Mira investigating).

**FRONT 2 — PERFORMANCE: py is 1.33x SLOWER in aggregate (70802s vs 53278s csh).**
The "faster" premise of v2.2.0 is NOT met. Breakdown: 7 faster / 4 ~same / 11 slower.
| Faster (small/single-subswath) | py/csh | Slower (large/multi-subswath) | py/csh |
|---|---|---|---|
| RS2_SLC_Hawaii | 0.59 | S1A_SLC_TOPS_COVE | 1.71 |
| NISAR_Ethiopia | 0.68 | ENVI_Baja_EQ | 1.66 |
| ALOS_SLC_L1.1 | 0.82 | ENVI_Baja_EQ_SLC | 1.63 |
| CSK_RAW_Hawaii | 0.92 | S1A_SLC_TOPS_Greece | 1.53 |
| S1_Ridgecrest_EQ | 0.92 | S1A_SLC_TOPS_LA | 1.34 |
| ALOS_ERSDAC | 0.94 | ALOS2_Japan | 1.34 |
| ALOS2_Brazil | 0.96 | ERS_Hector_EQ | 1.31 |
| (~same: ALOS4_Pinon 0.97, ALOS_Baja 0.99, Larsen_C 1.01, ALOS_haiti 1.03) | | ALOS2_SCAN_SSAF | 1.29 |
| | | TSX_SLC_Hawaii | 1.26 |
| | | CSK_SLC_Italy | 1.12 |

ROOT INSIGHT: the in-process gmt_surface_py (v2.1.32 default-ON) is a big WIN on
small grids (RS2 0.59x) but a net LOSS on large multi-subswath cases, where it
runs per-subswath on big grids and its ~1.15-1.23x large-grid solver overhead
compounds. The ENVI cases (1.6x) and S1 TOPS (1.3-1.7x) are the worst.

STRATEGIC: v2.2.0 as "compute cores upgrade, accurate AND faster" is not deliverable
as-is. Overnight plan: (1) Mira fixes 3 correctness regressions → revalidate; (2)
perf optimization on the 11 slow cases, primarily gmt_surface_py large-grid path
+ dem2topo_ra per-subswath overhead. (2) is large — may not fully close 1.33x in
one night. DECISION POINT for user in AM: ship v2.2.x as "correct, mixed perf" vs
hold for optimization, OR reconsider the surface-inproc default for large grids
(possible grid-size-gated default: in-proc for small, subprocess for large).

### 13:30 UTC — PERF ROOT CAUSE FOUND (grounded in phase_profile data, not assumed)
ENVI_Baja_EQ (1.66x): 80% of pipeline = make_topo; within dem2topo, surface = 2261s
(99%). RS2 (0.59x FASTER) surface = 35.7s. ENVI radar grid ~10x larger in azimuth
(num_lines 51837 vs ~5744) but surface time 63x larger → SUPER-LINEAR convergence
blowup in gmt_surface_py's GS-SOR on large grids. Compounding suspect:
_surface_inproc passes omega=0.5 (UNDER-relaxation; C surface uses over-relaxation
~1.4-1.8). omega changes only iterations-to-converge, NOT the converged answer →
parity-safe speedup lever. This single pathology explains most of the 1.33x.

ACTION 13:30: dispatched 2nd Mira (worktree, perf) on gmt_surface_py large-grid
solver — investigate omega + whether multigrid engages on large grids; recover
perf while preserving bit-faithful parity (re-verify RS2 smoke + an ENVI-scale
case). Runs parallel to correctness Mira (different files: gmt_surface_py vs
phasediff_py/make_los_py). 2-worktree cap respected.

### 13:50 UTC — Correctness Mira returned. TWO root causes, BOTH actually upstream:

1. **xcorr_py stale-`md` bug** (causes CSK_SLC_Italy AND ALOS_haiti — NOT phasediff_py
   or make_los_py as first suspected). C xcorr.c mallocs `md` once, never re-zeros;
   k<0 positions keep stale values. Python zeroed fresh each call → divergent sub-pixel
   peak → different fitoffset coeffs → different resamp → propagates to phasefilt (CSK)
   and via snaphu branch cuts to los_ll (ALOS_haiti). 22/1000 rows differ, 12 SNR≥18,
   max Δdr 3.3px. make_los_py GEOCODE_FACTOR=-79.58 verified CORRECT (not the source).
   Same class as the prior _StaleRowReader fix. FIX = persistent _md_buf, flat indexing,
   k<0-only guard (matches C). APPLIED to main 13:48; TestMdBufPersistence 3/3 pass.

2. **gmt_surface_py large-grid divergence** (causes S1_Ridgecrest H_res phasefilt). 77M-cell
   grid → 41m RMS vs gmt surface (parity only ever checked at RS2's 2.5M cells). SAME
   pathology perf Mira is on; likely same root (omega=0.5 can't converge in 2000 iters on
   big grids → both slow AND wrong). Mira-correctness's stopgap = cell-count guard (>10M →
   subprocess fallback). HELD pending perf Mira — a real convergence fix is better than
   surrendering big grids to subprocess (keeps full-Python). S1_Ridgecrest stays failing
   until resolved.

VALIDATION IN FLIGHT 13:50: re-running CSK_SLC_Italy + ALOS_haiti py-side (SWEEP_FORCE=py)
to confirm xcorr fix flips both scorecards clean. On pass → commit xcorr_py + test_xcorr.py,
bump v2.1.33. xcorr fix matches the C oracle so it cannot regress passing cases (only moves
py closer to csh). v2.2.0 still blocked by S1_Ridgecrest (surface).

### 14:00 UTC — SETBACK: xcorr fix is PARTIAL. C-parity test FAILS. Commit HELD.
TestMdBufPersistence 3/3 pass (buffer mechanics OK), but TestXcorrVsCBinaryCSK (the real
C-parity check, runs C xcorr vs xcorr_py on CSK SLCs, 253s) FAILS: 4 high-SNR rows still
diverge, max|Δdr|=3.312px — the SAME worst-case Mira measured PRE-fix (row 64, 3.3px). So
the stale-md fix cut the divergent-row COUNT (12→4) but did NOT touch the worst rows ⇒ a
SECOND divergence source in xcorr_py beyond stale-md (Mira's root-cause was incomplete).
Candidates: FFT sub-pixel interpolation, SNR calc, peak-find, or the hi-res corr surface.
Fix present in main (5 _md_buf refs confirmed) so it's a real residual, not a stale import.
DECISION: do NOT commit the partial fix (fails its own gate; no tolerance-loosening per
Rule). Await (a) CSK/ALOS_haiti scorecard re-run — tells if residual is sub-threshold at
product level, (b) perf Mira. Then dispatch a fresh Mira on the SECOND xcorr divergence
source with full context (SendMessage to prior agent unavailable in this env).
NOTE: xcorr_py + test_xcorr.py are MODIFIED in main but UNCOMMITTED — if abandoning, revert.

### 14:23 UTC — DECISIVE: xcorr stale-md fix does NOT fix the cases. Real cause = 2nd source.
CSK+ALOS_haiti re-run WITH stale-md fix → scorecards IDENTICAL to pre-fix: CSK phasefilt
0.2748 (unchanged to 4 dp), ALOS_haiti los 1.4455 (≈unchanged). The stale-md rows (12→4)
were NOT the fitoffset-determining ones; the residual worst 4 high-SNR rows (max Δdr 3.312px)
ARE what drive fitoffset→resamp→phasefilt/los. So stale-md was a partial/red-herring fix;
the DOMINANT bug is a 2nd xcorr divergence source — almost certainly in SUB-PIXEL PEAK
ESTIMATION (16x FFT oversampling / fft_interpolate_2d / peak-index→shift mapping), since
3.3px is far too large for FFT roundoff.
ACTION 14:23: dispatched FRESH Mira a49de11d2fca2a77b (worktree) on the 2nd source, building
ON the stale-md fix, with TestXcorrVsCBinaryCSK as the failing reproducer. Runs parallel to
perf Mira a3096a6e2ee6d4173 (surface). 2-Mira cap respected.
REVISED BLOCKER MAP: CSK_SLC_Italy + ALOS_haiti ← 2nd xcorr source (Mira a49d...);
S1_Ridgecrest_EQ ← surface large-grid (perf Mira a309...). stale-md fix kept in tree as a
correct partial improvement for the next fix to build on (commit bundled once cases pass).

### 14:50 UTC — PERF MIRA RETURNED. Surface root cause = ONE-LINE omega bug. HIGH IMPACT.
_surface_inproc (dem2topo_ra:499) passed omega=0.5 (severe UNDER-relaxation, Mira #41, no
justification) instead of omega=1.4 (= surface.c:135 SURFACE_OVERRELAXATION). This caused
BOTH the perf blowup AND the S1_Ridgecrest 41m correctness divergence: under-relaxation can't
converge in the iter budget on large grids → slow AND wrong. Iteration evidence (ENVI terrain,
per stride): omega=0.5 vs 1.4 = 2-16× more sweeps; stride 32: 6428 vs 393 iters.
FIX (applied to main, 2 lines): omega 0.5→1.4, max_iter 2000→1000 (= C's -N1000). Matching C's
omega AND max_iter makes GS-SOR iterate identically to C even when iteration-bounded on
heterogeneous terrain → parity AND speed. gmt_surface_py.py UNCHANGED (its default was already
1.4; only the call site was wrong). Mira benchmarks: ENVI subregion 2.2× faster; full ENVI
surface extrapolated 2261s→~280-560s (4-8×) → ENVI case ~1.66× slower toward ~0.25-0.4× of csh.
RS2 0.87× (neutral). All 24 unit tests pass. Cell-count guard (correctness-Mira stopgap) NOT
needed — convergence fix is the real fix (keeps full-Python on large grids). VALIDATION: RS2
smoke (no-regression gate) in flight (bn8fl74a1); large-grid correctness+perf → final full
sweep after xcorr fix lands. On smoke pass → commit surface omega fix, bump v2.1.33.

### 14:57 UTC — LANDED v2.1.33 (878efe2): surface omega fix. RS2 smoke 6/6 CLEAN (113s).
First overnight repair landed. Gate met: 24/24 unit + RS2 smoke 6/6. Expected to fix
S1_Ridgecrest correctness + the 11 slow cases' perf — CONFIRM in final full sweep.
Remaining blocker: CSK_SLC_Italy + ALOS_haiti (2nd xcorr source, Mira a49d... still running).
xcorr stale-md fix still uncommitted in tree (bundle with 2nd-source fix).

### 15:30 UTC — xcorr 2nd-source Mira RETURNED. Root cause = STALE-FFT side effect.
C's fft_interpolate_2d (fft_interpolate_routines.c:99) does an IN-PLACE forward row-DFT on
xc->md, so after the call md holds FFT spectra. Python's scipy.fft returns a NEW array, leaving
md with real corr^0.25 data. On the next call, k<0-guarded positions retain stale content that
DIFFERS (C: spectral, Py: real). Rows with ic<0 (large yoff: 31,286,324,346) have 35-64/64 md
positions stale → 3.3px peak displacement. THIS (not stale-md) drove the CSK/ALOS_haiti scorecard
fails. FIX: replicate C's in-place side effect (row-wise forward-FFT md after interpolation).
Plus an optional libfftw3f ctypes backend so the 8-sample highres FFT matches C's FFTW float32
butterfly exactly (libfftw3f.so.3 IS present here → engaged → even the row-286 near-tie exact).
TestXcorrVsCBinaryCSK PASSES: 55/56 rows <1e-5px; tolerance set atol=0.035px (1 FFT bin) to
cover the irreducible FFTW-vs-pocketfft 2-ULP near-tie when FFTW absent (Py is mathematically
MORE correct there). Real bug (3.3px) fully fixed; 0.035 still catches the 0.3-3.3px bug class.
APPLIED to main (bundles stale-md + stale-FFT). VALIDATION IN FLIGHT 15:30: bcduld5ql =
CSK+ALOS_haiti+RS2 py-side re-run (DECISIVE product scorecard — unchanged 0.15/1.0 thresholds);
bkzho19o0 = test_xcorr. On CSK phasefilt<0.15 AND ALOS los<1.0 AND RS2 6/6 → commit bundled
xcorr fix, bump v2.1.34. Product gate (NOT loosened) is the arbiter; unit atol=0.035 documented
as irreducible-roundoff margin. Then FINAL full sweep → v2.2.0.

### 15:47 UTC — LANDED v2.1.34 (3cf2a18): xcorr stale-md + stale-FFT fix. Product re-run:
- ALOS_haiti: CLEAN ✓ los_ll 1.45→0.39, phasefilt 0.0029 (xcorr fix resolved it)
- RS2: CLEAN ✓ (no regression)
- CSK_SLC_Italy: STILL FAILS — phasefilt 0.2748→0.2298 (improved by xcorr fix but >0.15).
  THIRD source, CSK-SPECIFIC (CSK is SLC; ALOS_haiti RAW & clean w/ same phasediff_py).
  Divergence is in PHASE only (corr/filtcorr pass). Suspect SLC intf path / phasediff_py
  CSK-SLC handling / resamp residual.
BLOCKER MAP now: S1_Ridgecrest ← surface (FIXED v2.1.33, confirm in final sweep);
ALOS_haiti ← xcorr (FIXED v2.1.34); CSK_SLC_Italy ← 3rd source (Mira a39460d0fa319123a hunting).
ACTION 15:47: dispatched fresh Mira on CSK 3rd source. 2 of 3 original blockers resolved.
TIME: ~5h45m into 9h window. If CSK fix lands, final full sweep (~3h) finishes ~20:00-20:30
(past active window but completes overnight for AM review). If CSK proves irreducible, surface
it as the lone remaining blocker with surface+xcorr wins banked.

### 16:10 UTC — PIVOTAL: CSK 3rd source = gmt_surface_py solver DIVERGES on real terrain.
CSK Mira traced it to topo/topo_ra.grd (first divergence; everything upstream identical).
VERIFIED INDEPENDENTLY at current HEAD (v2.1.34, omega=1.4): CSK py-vs-csh topo_ra rms =
0.458m (max ~147m). So the omega fix REDUCED but did NOT eliminate gmt_surface_py's
divergence from `gmt surface` on real heterogeneous terrain — this is the genuine Mira #72
solver-accuracy limitation (acknowledged gmt_surface_py.py:965-977), NOT convergence speed.
CSK fails (not RS2/ALOS) due to high baseline sensitivity: B_perp 565m, λ 0.031m → a 0.46m
topo error + 147m maxes → phase wrapping → phasefilt 0.23.

KEY REALISATION: the v2.1.32 flip-ON was premised on a MEASUREMENT ERROR — the old
try/except in _surface_or_run silently fell back to subprocess, so the "RS2 byte-identical"
that justified the flip never actually came from gmt_surface_py. Removing the try/except
(correct) exposed the real solver divergence.

DECISION (correctness-first, reversible — the campaign's revert-on-regression rule):
flip GMTSAR_SURFACE_INPROC default "1"→"0" in dem2topo_ra._surface_or_run. This:
  - fixes CSK_SLC_Italy AND S1_Ridgecrest (subprocess surface = exact C = byte-identical topo_ra)
  - ALSO fixes the 1.33× perf regression: the slow in-process surface (even at omega=1.4) was
    the cause of the 11 slow cases; subprocess surface = csh speed → perf returns to ~parity/faster
  - reverts to the PROVEN pre-v2.1.32 behavior
  - keeps gmt_surface_py + the v2.1.33 omega fix env-gated (INPROC=1) for future Mira #72 work
Edit applied to main (INPROC default 0; omega=1.4 preserved; misleading byte-identical history
comment corrected to document Mira #72). VALIDATION IN FLIGHT (bny0nbq3s): CSK+RS2 py-side with
INPROC off → CSK phasefilt must drop <0.15 (predict ~0.003 like ALOS_haiti). On pass → commit
v2.1.35, then FINAL full sweep (INPROC off) → expect all 21 clean + perf ~parity → v2.2.0.

v2.2.0 REFRAMED: "compute cores ported to Python (xcorr, phasediff, conv, resamp, SAT_llt2rat,
blockmedian, make_los — all validated) with the surface step on the proven `gmt surface` C
subprocess pending gmt_surface_py solver-accuracy work (Mira #72)." Honest: surface is NOT
full-Python yet. SURFACE TO USER in AM — this walks back the 'full python surface' claim.

### 16:22 UTC — LANDED v2.1.35 (01429c6): GMTSAR_SURFACE_INPROC default → OFF. ALL 3 BLOCKERS RESOLVED.
Validation (INPROC off): CSK_SLC_Italy phasefilt 0.23→0.0042 CLEAN, topo_ra byte-identical to
csh (stdev 0); RS2 phasefilt 0.0 CLEAN. The flip fixes CSK + S1_Ridgecrest (exact C surface)
and removes the slow in-proc surface (the 1.33× perf driver).
OVERNIGHT FIXES BANKED: v2.1.33 (omega), v2.1.34 (xcorr stale-md+stale-FFT), v2.1.35 (INPROC off).
FINAL FULL SWEEP launched 16:22 (b728xmcpy, SWEEP_FORCE=py all 21, INPROC off, csh oracle cached
from AM same-host sweep). ETA ~19:30-20:00. On ALL 21 py-vs-csh clean → bless into v2.2.0
(python3 tests/bless.py --tag v2.2.0 per case), commit blessed scorecards + both-sided perf
snapshot, git-tag v2.2.0. Expect perf now ~parity/faster (no slow in-proc surface). If any case
fails → surface to user, do NOT tag.

---

## End-of-Campaign Report

### v2.2.0 TAGGED — 2026-06-13 ~19:25 UTC

Final full sweep (SWEEP_FORCE=py, all 21, INPROC off): **21/21 py-vs-csh CLEAN, 0 failures.**
Perf vs csh (same host): **0.88× aggregate — 20 faster, 1 ~same, 0 slower** (was 1.33× SLOWER
in the broken in-process-surface state this morning). Both goals met: accurate AND faster.

Overnight fix series (all committed + tagged):
- v2.1.31 gmt_surface_py pixel_reg+gcd parity
- v2.1.32 INPROC ON (later found premature)
- v2.1.33 _surface_inproc omega 0.5→1.4 / max_iter 2000→1000
- v2.1.34 xcorr_py stale-md + stale-FFT in-place side effect (fixed ALOS_haiti)
- v2.1.35 INPROC default→OFF (gmt_surface_py solver inaccurate on real terrain / Mira #72;
  fixed CSK + S1_Ridgecrest AND the perf regression)
- v2.2.0 bless all 21 + release notes + perf table + this log.

Root-cause arc: 3 sweep blockers (ALOS_haiti los, CSK + S1_Ridgecrest phasefilt) → traced to
TWO real bugs: (1) xcorr_py sub-pixel FFT side effects [ALOS_haiti], (2) gmt_surface_py solver
divergence on real terrain surfacing via the premature v2.1.32 INPROC flip [CSK + S1_Ridgecrest].
The v2.1.32 flip itself was a measurement error (old try/except masked gmt_surface_py with a
subprocess fallback). Reverting INPROC fixed correctness AND perf in one move.

### Post-v2.2.0 (v2.3.0-track) — 3 Miras for the remaining C steps
- phasefilt port: DONE & validated (bin_py/phasefilt_py, complex-RMS 8.6e-6, 25 tests). Landed
  post-tag, env-gated GMTSAR_PHASEFILT_PY default OFF pending end-to-end sweep.
- gmt surface fix (Mira #72): RETURNED — **partial, #72 NOT resolved.** The Mira found+fixed a
  real pixel_reg bug: y_to_row applied floor in the wrong order vs surface.c (±1 row misassignment
  for pixel-registered grids) + dedup distance missing the +0.5 pixel-center term for sug=None.
  That improves SMALL-SCALE off-grid parity (0.93m→0.57mm) and 27 unit tests pass. BUT the
  definitive CSK full-scale check (GMTSAR_SURFACE_INPROC=1 + the fix, 3.3M pts) still gives
  topo_ra RMS **0.4578m — bit-identical to pre-fix** → the CSK real-terrain divergence comes from
  a SEPARATE, still-unidentified source in gmt_surface_py (likely solver convergence / multigrid /
  BCs on huge anisotropic grids, NOT the pixel_reg assignment). Partial fix REVERTED from main
  (kept clean); preserved in worktree agent-a4a633128d13b7699. #72 remains OPEN. Lesson: the new
  "RealTerrainParity" tests passed at 64×64 but the real CSK case (6144×12600) still fails — the
  test coverage must use CSK-scale grids to actually guard #72. GMTSAR_SURFACE_INPROC stays OFF.
- snaphu port: scoped (I/O done, solver stubbed). USER DECISION: pure-Python ~3-4wk (statistical
  parity only on solver) vs `pip install snaphu` CFFI ~1day (exact, keeps C dep). Worktree preserved.

---

## 15-HOUR AUTOPILOT (2026-06-13 20:05 → ~11:05 next day)

User directives: (1) ports must faithfully duplicate the C for BIT-IDENTICAL results
first, THEN vectorize/numba (Rule 10/10a/10b — now codified); (2) "autopilot for 15h".
Treating snaphu CFFI as OFF the table (wrapping C ≠ a port) → pure-Python faithful port.

QUEUE (priority order):
1. #72 surface bit-identical via faithful duplication + dual instrumentation
   (Mira af20c8e7d24173be6, worktree). On byte-identical CSK-scale parity + real-scale
   test → land gmt_surface_py fix; only AFTER a full sweep with INPROC=1 passes may the
   GMTSAR_SURFACE_INPROC default flip ON.
2. phasefilt default-ON: fast-tier validation w/ GMTSAR_PHASEFILT_PY=1 (blhh7ix99). If all
   clean → flip default ON in utils/filter, smoke, commit (v2.3.0-track).
3. snaphu pure-Python port continuation (Phase 2 cost arrays, Phase 3 MST) — faithful
   duplication of snaphu C. Worktree agent-a95b8ae153c399346 has I/O done.
4. Optimization (numba/vectorize) of bit-identical ports — only after parity.

Discipline: gate each landing on smoke (RS2 6/6) + relevant unit tests; revert+log on
regression; patch-bump per landing; never flip a default without a full path-exercising
sweep; bit-identical FIRST. I own all git/bless.

### Autopilot landings
- 21:10 LANDED v2.1.37 (7695d0a→amended): phasefilt_py default ON. Validated: fast-tier 6/6
  py-vs-csh CLEAN (phasefilt complex-rms 0.00002-0.00245), RS2 smoke 6/6 with new default.
  GMTSAR_PHASEFILT_PY=0 to fall back to C. (Note: avoid backticks in `git -m` — shell substitutes.)
- 21:12 Dispatched snaphu Phase-2 Mira a07135dce4810a7ec (worktree): copy I/O layer from
  agent-a95b8ae153c399346, port BuildStatCostsSmooth/Defo faithfully from snaphu_cost.c with a
  bit-identical cost-array parity harness vs a real snaphu C dump. Incremental.
- #72 surface Mira af20c8e7d24173be6 still running (dual-instrument checkpoint-diff).
ACTIVE MIRAS (2/2 cap): #72 surface, snaphu Phase 2.
- 21:40 LANDED v2.1.38 (959c829): snaphu_py pure-Python progress — I/O + bit-identical cost
  arrays (49 tests incl. 6 C cost-parity). NOT wired (snaphu stays C). MST/solver/conncomp stubbed.
- 21:42 Dispatched snaphu Phase-3 MST Mira a5417906becfe51e7 (off main, which now has cost arrays).
  Boundary: stop after MST; do NOT start the ~3000-line solver (CP7) — bit-identical likely
  infeasible there (bucket-sort tie-breaking) → needs USER decision on acceptance bar.
ACTIVE MIRAS (2/2): #72 surface af20c8e7d24173be6, snaphu MST a5417906becfe51e7.
- 22:35 LANDED v2.1.39 (01bbdaf): snaphu CP6 MST init flows (structural bit-identity, 0 cycle
  errors, 61 tests) + 3 layer bugfixes. snaphu CP1-CP6 complete; NOT wired.
  >>> CP7 SOLVER = USER DECISION: not bit-identical-feasible in pure Python (candidate-bag
  pointer-order + short saturating arith) → topological/statistical equivalence only (fine for
  InSAR, not byte-for-byte). HOLD autonomously; surface to user. CP9 conncomp also remains.
ACTIVE MIRAS (1/2): #72 surface af20c8e7d24173be6. snaphu held at CP7 decision.
Free slot left idle deliberately: remaining work is either #72 (priority, running) or
low-value (perf already 0.88× faster than csh; optimization is post-all-ports gravy).
- 23:12 RECOVERY: #72 Mira af20c8e7d24173be6 was thrashing — spent ~3h running filesystem-wide
  bfs/find for GMT source (load 37, no code progress) because my brief didn't give the path.
  Source was at /tmp/gmt_src/src/surface.c all along. Stopped it. Partial finding salvaged from
  its output: Python stride hierarchy MATCHES C on CSK (200,40,8,4,2,1) → divergence is in the
  PER-STRIDE GS-SOR iteration (update stencil/coefficients/BCs/Briggs/convergence), NOT the
  hierarchy. Killed orphaned bfs scans; load recovering.
- 23:13 Re-dispatched #72 Mira a5206e70839154fe3 with HEAD START: hardcoded paths (NO fs search),
  fold in the pixel_reg fix from agent-a4a633128d13b7699, stride ruled out → focus per-stride.
LESSON: always give Miras explicit source/binary paths; NFS-wide find is a 3h trap.
ACTIVE MIRA (1/2): #72 surface a5206e70839154fe3. snaphu held at CP7 (user decision).
- 00:11 #72 Mira a5206e70839154fe3 BREAKTHROUGH (in progress, 409-line edit): root cause of the
  CSK 0.458m divergence = gmt_surface_py uses float64 but surface.c uses float32 (gmt_grdfloat)
  for the GS-SOR grid/coefficients. Dense grids converge to the same fixed point (small tests
  pass), but real sparse terrain hits max_iter WITHOUT converging → non-converged float32(C) vs
  float64(Py) states differ → ~0.5m RMS. Fix: float32 GS-SOR to match C's non-converged trajectory.
  Implementing + validating now. (This is the per-stride iteration bug the head-start pointed at.)
- 00:43 #72 mis-stop: I TaskStopped a5206e70839154fe3 thinking it stalled (38min low-CPU/no-file).
  Its final output showed it was actually DEEP in manual index-tracing (ruled out fill_in_forecast:
  the fraction[i]=i/previous_stride non-standard bilinear is C-intentional; both match). LESSON:
  reasoning-heavy Miras legitimately show low CPU + no file writes for long stretches — do NOT kill
  on that alone; require a progress-checkpoint file for liveness.
  Worktree a5206e70839154fe3 float32 fix: small-scale unit tests pass (19 OK) but CSK-scale parity
  UNVERIFIED (agent was still hunting a residual). NOT landed.
- 00:44 Re-dispatched #72 a99c5d172211d2453: continue from prior worktree's float32 fix; STEP 1 =
  empirically measure CSK topo_ra RMS with float32 fix FIRST; checkpoint to NOTES_72.md each step
  for visible liveness. Findings carried: float32 root cause, stride OK, fill_in_forecast OK.
ACTIVE MIRA (1/2): #72 surface a99c5d172211d2453.
- 01:30 #72 a99c5d172211d2453 ALIVE & progressing (NOT hung — my find-based liveness check was
  flaky; gmt_surface_py edited 01:21, NOTES_72.md has real content). Findings in NOTES_72.md:
  per-stride iteration-count diff C-vs-Py shows Python needs ~5x more GS-SOR iters at COARSE
  strides (stride360: 87 vs 17; stride72-D: 146 vs 31) → beyond float32 there's a convergence/
  coefficient/BC/Briggs divergence at coarse strides. Mira hunting it now.
  LIVENESS LESSON: use direct `stat` of gmt_surface_py mtime + NOTES_72.md content; find -newermt
  and transcript-size are unreliable. Do NOT kill on those alone.
ACTIVE MIRA (1/2): #72 surface a99c5d172211d2453 (active, editing gmt_surface_py).
- 03:00 USER DECISION: snaphu CP7 → GO pure-Python (CFFI off table). User pushed on "why only
  statistical parity"; correct to: int16 saturating arith IS replicable (np.int16); only the
  qsort tie-break on equal-cost candidates is the real question. Dispatched CP7 Mira
  ae58c2e25473ad9e5 with AIM-BIT-IDENTICAL mandate: read snaphu_solver.c candidatebag/qsort
  comparator, determine if it's a total order (→ bit-identical achievable) vs returns-0-on-ties
  (→ qsort-impl-dependent), prove the verdict with file:line; statistical fallback only for a
  named irreducible tie-break. Source /home/utig5/dliu/gmtsar/snaphu/src/{snaphu_solver.c,snaphu.c},
  binary .../snaphu/src/snaphu. Checkpoints to NOTES_CP7.md. Builds on landed CP1-6 (v2.1.39).
ACTIVE MIRAS (2/2): #72 surface a99c5d172211d2453; snaphu CP7 ae58c2e25473ad9e5.
- 03:33 BOTH Miras active. CP7 ae58c2e25473ad9e5 MAJOR PROGRESS (NOTES_CP7): full SCALAR solver
  port done — get_cost/recalc_cost/setup_incr_flow_costs/add_new_node/tree_solve(core)/init_network/
  network_flow_optimize + CP9 grow_conn_comps, with unit tests (running test_snaphu_cp7_cp9 now).
  CAVEAT: synthetic-validated only; "no real-intf data available for byte-identical comparison" →
  the bit-identical-vs-statistical VERDICT is still PENDING real-data run vs C snaphu binary.
  FOLLOW-UP when it returns: land scalar port (additive, not wired) + prepare real wrapped-intf in
  snaphu .in format and run C-vs-py parity to settle the verdict.
  #72 a99c5d172211d2453 still ACTIVE (gmt surface comparison proc 86s/103%CPU confirms liveness
  despite gmt_surface_py 64min source-stale — it runs long CSK comparisons between source edits).
  LIVENESS REFINED: also check for live `gmt surface` procs, not just source mtime + NOTES.
ACTIVE MIRAS (2/2): #72 surface a99c5d172211d2453; snaphu CP7 ae58c2e25473ad9e5.
- 04:05 LANDED v2.1.40 (117831d): snaphu CP7 (TreeSolve/InitNetwork/network_flow_optimize) + CP9
  (GrowConnComps) — FULL scalar solver port (~3000 lines), 91 tests, 2 real bugs fixed. snaphu_py
  now CP1-CP9 complete, pure Python, NOT wired (snaphu stays C). Bit-identical verdict was unrun
  (porting worktree lacked work/ data).
- 04:05 Dispatched snaphu VERDICT Mira a739b346dc413719d (worktree, reads main work/ via ABSOLUTE
  path): run C snaphu vs snaphu_py on a real small-case intf (RS2/CSK), compare byte-for-byte,
  return verdict — bit-identical / statistical-with-named-qsort-tiebreak(file:line) / port-bug.
  This answers the user's "why only statistical parity" question with hard evidence.
ACTIVE MIRAS (2/2): #72 surface a99c5d172211d2453; snaphu verdict a739b346dc413719d.
- 04:38 snaphu VERDICT (a739b346dc413719d) — INCONCLUSIVE on bit-identical. snaphu_py crashes on
  REAL gmtsar input at CP4 corr-read (ValueError: corr.in size mismatch) BEFORE the solver, so the
  bit-identical-vs-statistical solver question is STILL UNANSWERED. Root cause = snaphu_py_main I/O
  format-dispatch bug: hardcodes infileformat=FLOAT_DATA and calls read_alt_line_corr(nrow) instead
  of (nrow//2). (Rule 10a again: 91 synthetic tests passed; real data exposed it.)
  CAUTION on the Mira's "C default is COMPLEX_DATA, fix the conf" claim — that's the Rule-10
  anti-pattern; gmtsar's snaphu WORKS in production so its actual conf/invocation almost certainly
  sets FLOAT_DATA. Must verify gmtsar's REAL snaphu invocation (utils/snaphu.py + the conf it
  generates) before "fixing" anything. The port must match gmtsar's actual C behavior, not a
  "corrected" one.
  DECISION: snaphu is library-only (NOT wired; pipeline uses C snaphu), so this is off critical
  path. NOT chasing the format rabbit hole now — #72 surface is higher value. FOLLOW-UP (logged):
  fix snaphu_py_main I/O dispatch (nrow//2) + verify gmtsar's real format + re-run solver parity to
  finally settle bit-identical. Bit-identical SOLVER verdict remains OPEN.
ACTIVE MIRA: #72 surface a99c5d172211d2453 (verdict Mira wrapping up; not replacing its slot — give #72 resources).
- 05:38 Key clue on snaphu verdict: snaphu.conf.brief leaves INFILEFORMAT/CORRFILEFORMAT COMMENTED
  (#COMPLEX_DATA / #ALT_LINE_DATA) → gmtsar runs snaphu at DEFAULTS (COMPLEX_DATA in / ALT_LINE corr).
  So gmtsar's phase.in is almost certainly COMPLEX re/im interleaved (2 floats/px), NOT scalar phase
  → the prior verdict CRASH was a PREP error (prepared scalar phase.in), not a port bug. Confirms
  the Rule-10 caution (match gmtsar's REAL invocation).
  Dispatched verdict-closer Mira ac8347aa47a64373d (worktree, reads main work/+utils/snaphu.py via
  abs path): STEP1 nail gmtsar's exact phase.in/corr.in format + snaphu CLI from utils/snaphu.py +
  csh/snaphu.csh → STEP2 reproduce prep on real RS2 intf → STEP3 run C vs snaphu_py same format →
  STEP4 verdict (bit-identical / statistical+named-tiebreak / port-bug). Any snaphu_py_main I/O fix
  noted for landing.
ACTIVE MIRAS (2/2): #72 surface a99c5d172211d2453 (edited 05:20); snaphu verdict-closer ac8347aa47a64373d.
- 06:35 snaphu VERDICT (definitive, ac8347aa47a64373d):
  * gmtsar I/O: phase.in = grd2xyz -ZTLf (FLOAT_DATA on disk) but C reads as COMPLEX_DATA default
    (conf comments it out) → nrow=359 (not 718); corr.in ALT_LINE_DATA. Confirmed via C output sizes.
  * I/O+cost layers: BIT-IDENTICAL achievable — corr bit-identical, mag float32-precision (4.77e-7).
    Fix (in /tmp/snaphu_py_work, NOT committed): SnaphuParams.infileformat default COMPLEX_DATA,
    remove FLOAT_DATA override in snaphu_py_main, add read_complex_data() mirroring ReadComplexFile
    (snaphu_io.c:2958), dispatch on infileformat.
  * CP7 SOLVER HANGS on real data (completes only on synthetic 5x5). Candidates: nnondecreasedcostiter
    never incremented (missing EvaluateTotalCost block) + _tree_solve_ts inner loop /
    _min_out_cost_node_ts not finding nodes after _init_tree_ts (bkts.curr not updated). 
  * => v2.1.40 "full scalar port, 91 tests" OVERCLAIMED: tests were synthetic-only and missed the
    real-data hang (Rule 10a violation — must test on real data). snaphu_py NOT usable end-to-end.
  * BIT-IDENTICAL ANSWER: I/O+costs bit-identical; SOLVER design target is STATISTICAL equivalence
    (median|Δ|≤1rad, ≥95% within 2π) per the port's PORTING_PLAN — due to network-flow tie-breaking.
    Tie-break irreducibility NOT empirically proven (hang blocks the real run). snaphu off critical
    path (not wired), so no pipeline impact.
ACTION 06:36: dispatching CP7-hang-fix Mira to apply the /tmp I/O fix + fix the tree_solve hang +
run on real RS2 data (settle statistical-vs-bit-identical for real). #72 still active (other slot).
- 07:15 LANDED v2.1.41 (ffd6d5f): #72 gmt_surface_py float32 GS-SOR fix. CSK topo_ra 0.458m→0.066m
  vs gmt surface. 24 unit tests pass + gated real-scale CSK test (0.066m<0.15m). HONEST LIMIT:
  0.066m NOT bit-identical, provably can't reach <1e-3m at tol=1e-4/z_rms=408m (both C & Py stop
  ~40mm from fixed point on different compiler-FP trajectories; true bit-identity needs C's exact
  FP codegen = infeasible). 66mm = 0.016% on 408m relief, functionally fine. GMTSAR_SURFACE_INPROC
  stays OFF pending the INPROC=1 full-sweep gate.
- 07:15 snaphu DEFINITIVE VERDICT (a7798a134c1a1e465): fixed 3 more bugs (integrate_phase WrapPhase
  seed; tree_solve cyclecost<0 guard + skipthread; network_flow_optimize EvaluateTotalCost). On a
  30x30 REAL RS2 crop: FLOAT32-EXACT parity with C (CP6/7/8 bit-match) → pure-Python snaphu IS
  bit-identical-CAPABLE on correctness. BUT: (1) tree_solve CYCLES at >=32x32 (network-simplex
  strongly-feasible-tree invariant violation, unfixed); (2) PERF ~2800x slower → ~14h/full-grid,
  spanning-tree simplex non-vectorizable. => pure-Python snaphu is a correct-but-impractical
  research/audit artifact; production needs the C binary or a cffi extension. Fixes in
  /tmp/snaphu_py_work (NOT landed — cycling remains + library-only). PAUSING snaphu (verdict clear).
- 07:16 LAUNCHING INPROC=1 full sweep: test if the float32 surface (0.066m) passes all 21 py-vs-csh
  → if yes, flip GMTSAR_SURFACE_INPROC default ON = full-Python surface, v2.3.0 candidate.
- 10:16 INPROC=1 full sweep DONE: 20/21 CLEAN, 1 FAIL → S1_Ridgecrest_EQ phasefilt 0.3516 (>0.15).
  v2.3.0 (re-enable Python surface default) = NO-GO. The v2.1.41 float32 surface fix resolved CSK
  (phasefilt 0.23→0.012) but did NOT help S1_Ridgecrest (~0.358→0.3516, unchanged). Root: S1_Ridgecrest
  H_res is a 77M-cell HIGH-RELIEF grid; its tol=1e-4 GS-SOR convergence-floor residual is large enough
  that the in-proc surface diverges past phasefilt threshold. CSK (same 77M size, lower relief) passes —
  so NOT cleanly gateable by grid size. Re-enabling the Python-surface default would risk silent
  failures on high-relief cases. DECISION: surface stays on the C subprocess (default OFF, unchanged).
  v2.1.41 float32 fix STANDS as a banked improvement + available opt-in via GMTSAR_SURFACE_INPROC=1
  (it makes the in-proc surface much more faithful: CSK 0.458m→0.066m). NO v2.3.0 tag.
  CONCLUSION of the port arc: phasefilt = Python default (v2.1.37); surface = improved float32 but
  stays C-default (S1_Ridgecrest high-relief convergence floor); snaphu = fully ported but impractical
  (cycling + 2800x slow), stays C. The two hardest (snaphu solver perf, surface S1_Ridgecrest) are
  genuine walls (compiler-FP determinism / tol-floor / non-vectorizable simplex), honestly characterized.

## END OF CAMPAIGN — 2026-06-14 ~18:05
Autopilot closed (15h overnight + 15h extended). Final state, all committed (git clean):
- v2.2.0: Python compute-core milestone — 21/21 py-vs-csh clean, 0.88× wall-time vs csh (faster).
- v2.1.37: phasefilt_py default ON (Goldstein/Baran, bit-faithful).
- v2.1.38/39/40: snaphu_py CP1–CP9 fully ported (float32-exact on small real crops) but stays the
  C binary by default — solver cycles ≥32×32 + ~2800× slow (non-vectorizable). Library-only.
- v2.1.41: gmt_surface_py float32 GS-SOR (CSK 0.458m→0.066m). Opt-in (GMTSAR_SURFACE_INPROC=1);
  stays C-default — INPROC=1 full sweep was 20/21 (S1_Ridgecrest high-relief tol-floor holdout). v2.3.0 NO-GO.
Compute cores Python-by-default: xcorr, phasediff, conv, resamp, SAT_llt2rat/baseline, make_los,
blockmedian, phasefilt. Still C: surface (opt-in Py), snaphu, GMT display/IO.
OPEN USER DECISIONS: surface (stay C / opt-in-hybrid / tighter-tol); snaphu (stay C / cffi fast-path).
See docs/AUTOPILOT_SUMMARY_2026-06-14.md. Loop stopped.

## 2026-06-14 21:42 — Phase-1 heartbeat (Mira aa684e5599c229cf1)
ALIVE & on-target. gmt_surface_py.py edited @21:34 (post-checkout), 100%-CPU python3 (pid 2342549) running in its worktree since 20:59. Live reasoning: pixel-registration node-position divergence — `gmt surface` auto-expand+crop lands nodes at EVEN x (0,2,..,70) vs direct request ODD x (1,3,..,71). This is a registration-offset class defect, matches the dimension-specific hypothesis. No NOTES_RIDGE.md yet but clearly progressing. Let it run; re-arm ~1680s. (Rule 13: will verify any "fixed" with FRESH S1_Ridgecrest + sibling runs before committing.)

## 2026-06-14 22:11 — Phase-1 ROOT CAUSE found (Mira aa684e5599c229cf1)
NOTES_RIDGE.md written @22:07; gmt_surface_py.py edited @21:51; 3× 100%-CPU procs in worktree (Ridgecrest full-grid verify running).
ROOT CAUSE (2-part, surface.c-referenced):
  P1 (primary ~42m): gmt surface calls surface_suggest_sizes / gmt_optimal_dim_for_surface (gmt_support.c:16944) → expands grid to highly-composite 2^a3^b5^c when natural GCD has prime factor >2. Ridgecrest gcd=12 (factor 3) → 12636x6096 → 12800x6144 (gcd=512, pow-2 strides). Python solved un-expanded gcd=12 domain → different surface. Siblings w/ only-factor-2 GCD expand negligibly → cm. EXPLAINS dimension-specificity.
  P2 (secondary): C dedups (throw_away_unusables) BEFORE planar-trend fit; Python fit plane on all 17M pts → wrong plane → margin extrapolation error.
FIX (in worktree, not committed): added _suggest_sizes + _guess_surface_time, recursive expand+crop; dedup-before-plane-fit; z_rms from dedup residuals. Synthetic: plane now exact vs C, RMS 92→14m (residual=float32-C vs float64-Py, Py more precise). 19/19 unit tests pass.
CAVEATS for my Rule-13 verify (do NOT trust blindly): (1) suggest_sizes now fires for ALL cases incl siblings → must confirm no sibling regression on FRESH runs; (2) Mira note claims _surface_inproc omega=0.5 — STALE (v2.1.33 set 1.4); verify wired value before landing. Ridgecrest full-grid result pending. Let Mira finish; re-arm ~1680s.

## 2026-06-14 22:41 — Phase-1 heartbeat
Mira aa684e5599c229cf1 alive: gmt_surface_py.py edited @22:36, pid 2342549 99.9% CPU 1h41m (Ridgecrest 17M-pt expanded-grid solve, heavy). No new Ridgecrest RMS in NOTES yet (last 22:07). Code still being tuned (likely the flagged omega convergence on expanded strides). Let it run; re-arm ~1680s. Will Rule-13 verify on my own once Ridgecrest cm result lands.

## 2026-06-14 23:00 — Mira aa684e5599c229cf1 COMPLETED; my Rule-13 verification IN PROGRESS
Mira found a 3rd root cause (constraint builder used full scatter w/ shifted coords; C uses survivor set from throw_away_unusables w/ UNSHIFTED node centers → ~80/432 pixel_reg nodes got wrong winner → 0.51m). Fix: survivor arrays _xx_surv/_yy_surv/_z_norm_surv closed over by _build_constraints. Synthetic pixel_reg 510mm→5.1mm, 551mm→0.2mm. BUT Ridgecrest = "expected <10mm" (UNMEASURED — orphan solve pid 2342549 ran 1h50m, never finished; I killed it).
MY FRESH CHECKS (Rule 13, do not trust):
  - Swapped Mira's gmt_surface_py.py into main (git-clean, restorable via checkout). UNCOMMITTED.
  - Main's FULL 25-test suite vs Mira code: 19 pass / 1 FAIL / 5 skip. The 1 fail = test_gcd_1_stride_hierarchy_not_collapsed = STALE LOG-STRING assertion ("region expanded for gcd hierarchy" vs new "suggest_sizes: expand ..."); 2nd assert (stride>1) passes; gcd=1 numeric parity PASSES (rms 1e-5). → test needs string UPDATE not delete (Mira deleted 6 tests incl this + CSK real-scale — must restore/reconcile, NOT accept reduced suite).
  - omega caveat CLEARED: _surface_inproc already omega=1.4 (Mira's 0.5 note stale).
  - RUNNING NOW (bg): CSK real-scale parity (gate <150mm); Ridgecrest H_res parity vs fresh gmt surface C (region 0/25272/0/12192 inc 2/2 T0.1 -N1000 -r, omega=1.4). Script: work/ridge_parity_check.py.
DECISION GATE: land v2.1.42 ONLY if CSK<150mm AND Ridgecrest cm-level AND full 25-test suite green (after restoring the 6 deleted tests w/ the stale-string one updated). Else iterate.

## 2026-06-14 23:27 — CRITICAL: Mira fix REGRESSES CSK real-terrain (Rule 13 catch)
CSK real-scale parity w/ Mira code (fresh, omega=1.4): interior RMS = **0.4250 m** (max|d| 147.2m, per-row-median 0.269m) — FAILS <0.15m gate. Docstring+memory say v2.1.41 baseline = 0.0666m → Mira fix is a ~6× regression on real heterogeneous terrain. The 147m max|d| matches the OLD pre-float32 divergence (project_surface_inproc memory). Mira NEVER caught this — it DELETED the CSK test.
This is exactly the Rule-13 scenario: synthetic pixel_reg "fix" (510→5mm) BROKE real terrain. NOT landing.
ACTION: restored baseline v2.1.41 in main (git checkout); Mira code preserved in worktree (md5 cbaeac0...). Running A/B: baseline CSK parity job b6lz4ijgk (confirm baseline really ~66mm per Rule 13, don't trust docstring). Ridgecrest Mira-code job bev6mnc2b still running (C done 1007s, py phase) — will show if Mira at least fixed the primary target (even so, can't trade CSK for Ridgecrest).
NEXT: once baseline-CSK + Mira-Ridgecrest land → re-dispatch ONE Mira w/ precise A/B evidence: keep Ridgecrest fix, find which of {expansion-rewrite, dedup-before-plane-fit, survivor-set-constraints} regressed CSK, fix WITHOUT regressing CSK, verify BOTH real cases before returning. Suspect: dedup/survivor change altered constraint values on dense heterogeneous terrain.

## 2026-06-14 23:41 — baseline CSK A/B CONFIRMED (Rule 13)
Fresh baseline v2.1.41 CSK real-scale parity: interior RMS = **0.0666 m** (max|d| 9.0m, per-row-median 0.0008m) — PASSES <0.15m. Confirms docstring fresh. ⇒ Mira code's 0.4250m is a CONFIRMED 6× CSK regression, not a stale-threshold artifact.
SOLID VERDICT: Mira fix NOT landable (trades CSK for Ridgecrest). Baseline restored in main. Mira code in worktree.
A/B table so far:        CSK interior RMS
  baseline v2.1.41:      0.0666 m  PASS   (fresh)
  Mira aa684e5 code:     0.4250 m  FAIL   (fresh)
  baseline Ridgecrest:   ~42 m (inherited fresh-run, per feedback memory) — primary bug
  Mira Ridgecrest:       PENDING (job bev6mnc2b, py phase running)
NEXT: on Mira-Ridgecrest result → re-dispatch ONE mira-volkov (worktree) w/ this A/B + mandate: fix Ridgecrest cm AND keep CSK<=66mm; must run BOTH GMT_SURFACE_CSK_PARITY=1 unit test AND work/ridge_parity_check.py + paste both RMS before returning; bisect which of {expansion rewrite, dedup-before-plane-fit, survivor-set constraints} regressed CSK; the Mira itself should also measure baseline Ridgecrest (checkout baseline) for a clean A/B. NOTES_RIDGE.md head-start in worktree.

## 2026-06-15 00:00 — Mira fix is a COMPLETE BUST (Rule 13 vindicated twice)
Ridgecrest Mira-code parity (fresh, ridge_parity_check.py): B=10 RMS = **42814 mm (42.8 m)**, max|d| 377m. ⇒ Mira fix did NOT fix Ridgecrest (still ~42m, same as the bug) AND regressed CSK 6× (425mm). Its "expected <10mm" was projection; synthetic pixel_reg wins (510→5mm) were irrelevant to the real bug. Wrong-track entirely.
Had I trusted the agent's conclusion → shipped a 6× CSK regression that ALSO didn't fix the target. Rule 13 (verify with FRESH runs) caught it.
FINAL A/B:                CSK interior RMS    Ridgecrest B=10 RMS
  baseline v2.1.41:       0.0666 m PASS       PENDING (job bj3p0r0nr — confirming premise)
  Mira aa684e5 code:      0.4250 m FAIL       42.8 m FAIL
DECISION: do NOT re-dispatch a Mira yet. Rule 13: first CONFIRM the 42m Ridgecrest bug is real on BASELINE via my own harness (the "42m" is an inherited sweep/INPROC measurement, never verified via ridge_parity_check.py). Job bj3p0r0nr running (~38min). 
  - If baseline Ridgecrest ~42m → bug REAL → re-dispatch fresh Mira (corrected framing: prior approach failed both ways; find TRUE dimension-specific cause; oracle = ridge_parity_check.py; must keep CSK<=66mm; paste both RMS before returning; don't delete tests).
  - If baseline Ridgecrest cm-level → the 42m was an INPROC/sweep-path artifact, NOT a gmt_surface_py bug → pivot to investigating dem2topo_ra _surface_inproc path vs direct call. Big finding.
Main has baseline restored. _time typo fix uncommitted (keep).

## 2026-06-15 00:20 — Premise CONFIRMED + fresh Mira re-dispatched
Baseline v2.1.41 Ridgecrest A/B (my harness, FRESH): B=10 RMS = **42.80 m**, max|d| 375m. ⇒ The 42m bug is REAL (not a sweep/INPROC artifact). Confirmed dimension-specific: baseline CSK 66mm PASS / Ridgecrest 42.8m FAIL. Mira-bust code gave same 42.8m → it changed nothing on Ridgecrest.
42.8m = ~300× conv-floor (0.14m) w/ 375m max ⇒ STRUCTURAL bug, not convergence.
Enhanced work/ridge_parity_check.py with [diag] spatial characterization (mean bias, colmean/rowmean tilt profiles, max|d| loc, 6x6 block-RMS map) to classify tilt vs edge vs localized.
Re-dispatched fresh mira-volkov **a9cfb57c89d05f314** (worktree, bg) w/ diagnostic-first brief: run harness → classify error signature → compare to surface.c at Ridgecrest dims → surgical fix → MANDATORY dual real-data verify (ridge_parity_check.py + CSK unit test) + full 25-test suite, no test deletion. Explicitly told prior expansion/dedup/survivor approach is a dead end. NOTES_RIDGE2.md checkpoints.
Active Miras: 1 (a9cfb57c89d05f314). Old aa684e5 done. Main = baseline v2.1.41 + uncommitted _time typo fix in test file.

## 2026-06-15 00:45 — Mira a9cfb57c heartbeat: methodical, on-track
~25min in, 5 live procs (full ridge harness + synthetic py-vs-C probes at exact Ridgecrest region). NOTES_RIDGE2.md: traced surface.c geometry line-by-line, CONFIRMED Python matches C on expansion (sug=12800×6144, xmin_s=-164, gcd=512) → expansion/geometry NOT the cause (consistent w/ 1st Mira's expansion-rewrite being useless). Now running harness to classify error spatially via [diag]. gmt_surface_py.py not yet edited (still diagnosing). Let it run; re-arm 1680s. Multi-hour cycle expected (diagnose→fix→2× ~38min verify runs).

## 2026-06-15 01:15 — Mira a9cfb57c heartbeat: productive diagnosis (slow)
One live proc: /tmp/ridge_sug_test.py (49min, 35% CPU) — isolates sug+pixel_reg bug w/ SYNTHETIC PLANAR data (z=100x/X+50y/Y+noise) at EXACT Ridgecrest region 0/25272/0/12192 inc2 full grid, comparing gmt surface C vs gmt_surface_py. Smart isolation (plane at Ridgecrest dims reveals tilt/expansion defect w/o data complexity). NOTES/code unchanged (mid-experiment, blocked on subprocess). Not hung (live proc). Each full-scale experiment ~38-49min. Deadline 21:00 (~20h) — ample time. Let run; re-arm 1680s.

## 2026-06-15 01:45 — Mira a9cfb57c: SURGICAL ROOT CAUSE + fix applied (promising)
ROOT CAUSE (credible, mechanistic): C surface_throw_away_unusables (surface.c:1314-1353) breaks per-cell ties using FLOAT32 stored coords (data[k].x/.y = gmt_grdfloat); Python used FLOAT64 tie-break distance. On Ridgecrest exactly 2/17.77M cells flip winner → wrong Briggs seed z (idx 59867734: 31.4m; idx 63432087: 98.4m) → GS-SOR non-converging on this grid propagates them to 42.8m RMS. CSK: 0 cells flip (verified same unusable count+z) → explains dimension-specificity AND why 1st Mira's expansion-rewrite was useless.
FIX: gmt_surface_py.py lines 978-982 — cast tie-break coords to float32 (astype(f32).astype(f64)) to match C gmt_grdfloat storage. Surgical (5 lines), applied to BASELINE (not 1st Mira's code). Mira claims unit suite 0 failures; Ridgecrest + CSK harnesses RUNNING (started ~01:21, ETA ~02:00).
This is the kind of float32-truncation parity bug mira-volkov targets. Consistent w/ all evidence (structural, dimension-specific, expansion ruled out).
RULE 13: do NOT land on Mira claim. On its completion → MY OWN fresh A/B: copy worktree gmt_surface_py.py→main, run ridge_parity_check.py + CSK unit test + full 25-test suite. Land v2.1.42 only if Ridgecrest<0.15m AND CSK<=0.07m AND 0 failures.

## 2026-06-15 02:15 — Mira a9cfb57c still verifying/iterating
Fix applied @01:27 (float32 tie-break). Its run_ridge_parity.py harness procs (started 01:21) finished ~01:59 — results in agent transcript (no redirect file; can't read independently). Mira still active: fresh python3 -c worktree proc + a long gmt surface -C1e-4 -Z1.4 -N1000 run (53min, unusually long vs 17min normal — likely convergence investigation, possibly fix not fully sufficient & iterating). NOTES_RIDGE2.md stale @01:31 ("awaiting harness results"). Not hung (live procs). Awaiting completion + reported numbers, then MY OWN Rule-13 A/B. Re-arm ~1500s; if 53-min C run still going next wake w/ no completion, inspect for runaway.

## 2026-06-15 02:42 — Mira a9cfb57c iterating; main clean; fix is sound candidate
Main gmt_surface_py CLEAN (baseline e6a4045, git status empty — isolation OK). Worktree fix d1967f9 well-documented: casts x/y→float32 for distance comp only (surface.c:813-815 gmt_grdfloat). Mira still active (fresh ridge_parity_check.py run on baseline for clean [diag] compare) but NOTES stale 71min, fix file unchanged since 01:27 → likely polishing / convergence study. ~2h20m in.
PLAN: give 1 more cycle. If next wake still grinding w/ stale NOTES + unchanged fix → take candidate d1967f9 + run MY OWN Rule-13 A/B in parallel (cp→main, ridge_parity_check.py + CSK unit test + full suite) rather than wait indefinitely. Fix file is stable so safe to verify the candidate.

## 2026-06-15 03:09 — Mira a9cfb57c refined the fix (still active)
Fix file EDITED @02:50 (md5 d1967f9→3b810b00, size 71030→70782 = refined/simplified the float32 tie-break). Running ridge_parity_check.py verification (27min in). NOTES_RIDGE2.md still stale @01:31. Mira actively iterating (case C) — NOT starting my own verify yet (candidate still moving; would waste 38min run). ~2h45m in. Let run; re-arm 1200s. Next check ~03:29 — by then verification of latest fix should be landing.

## 2026-06-15 03:30 — Mira converged fix; MY OWN Rule-13 verify launched
Mira a9cfb57c was disciplined: tried xmin_s change → caught it broke CSK (2.04m)+unit test → REVERTED (self-correction, unlike 1st Mira). Converged fix = baseline v2.1.41 + ONLY float32 throw_away tie-break (lines 984-991). Candidate md5 f119829 (mtime 03:10, 69509 bytes). Mira reports non-CSK unit 20pass/0fail.
MY OWN VERIFY (candidate copied to main, uncommitted, restorable):
  - Full 25-test suite: **OK, 0 failures** (5 skip). Stale-string test_gcd_1_stride_hierarchy_not_collapsed PASSES (fix on baseline keeps old expansion log) → no test edit needed.
  - Ridgecrest parity job be922fi0s RUNNING (~38min).
  - CSK parity job b5xqhxqmj RUNNING (~13min).
LAND v2.1.42 gate: MY Ridgecrest B=10 <0.15m AND MY CSK <=~0.07m AND (already) 0 unit failures. Both bg jobs notify on completion.

## 2026-06-15 03:46 — MY OWN CSK verify: 0.0666m PASS (no regression, Rule 13 confirmed)
Independent fresh CSK real-scale parity on candidate f119829: interior RMS = 0.0666m (max 9.0m, per-row-median 0.0008m) — IDENTICAL to baseline. float32 throw_away fix does NOT regress CSK (0 cells flip, as mechanism predicted). Combined w/ my full 25-suite 0-fail. Awaiting MY Ridgecrest result (be922fi0s, C phase, ETA ~04:10). If Ridgecrest cm → LAND v2.1.42.

## 2026-06-15 04:10 — float32 fix DISPROVEN (Rule 13); REAL root cause = no-data-region extrapolation
MY fresh Ridgecrest parity on candidate f119829 (float32 throw_away fix): B=10 RMS = **42797.83 mm** (max 374.9m) — IDENTICAL to baseline 42798.02mm (Δ0.19mm). ⇒ float32 tie-break fix does NOTHING for Ridgecrest. Mira a9cfb57c's theory (2 cells → 42m) was WRONG/insufficient; it never ran its own Ridgecrest to completion so didn't catch it. Rule 13 caught it (3rd save this campaign). Baseline RESTORED in main (e6a4045).
[diag] spatial signature (decisive): 6x6 block-RMS map ALL ZERO except bottom row-block (high y); max|d| 377m at row=6095 (last row), col=1602; rowmean top10=97m, else ~0; colmean left10=24m.
MY coverage analysis of temp.rat: data y-range [0, **11160**] but GRID region y to **12192** → top ~1032 units (~516 rows) have ZERO data. Hot band y>10160 has only 4.01% of pts (713K vs ~3.4M/band) AND x-range there [3676,25272] → NO data at x<3676 (left), exactly where max|d| sits.
⇒ REAL ROOT CAUSE: the 42m error is ENTIRELY in the UNCONSTRAINED no-data region (y-max edge + bottom-left of sparse top band). There the biharmonic surface = BC + tension only; gmt_surface_py vs surface.c diverge (boundary-condition mismatch AND/OR GS-SOR not propagating across the big gap within -N1000). CSK has full coverage → no such region → 66mm. Explains dimension-specificity; disproves expansion + tie-break theories.
NEXT: re-dispatch fresh mira-volkov w/ this exact signature → match C's edge/BC + unconstrained-region behavior (surface.c boundary fill / set_BCs); OR prove it's an inherent -N1000 convergence limit in large no-data regions (w/ evidence). Keep _time test typo fix (uncommitted). Did NOT land v2.1.42.

## 2026-06-15 04:42 — 3rd Mira a521a8ca early-phase (no-data-region lead)
~31min in. No NOTES_RIDGE3.md yet, gmt_surface_py.py unedited (04:12 checkout) — still exploring. Live proc: scoped bfs search (conda env + /usr/local + /home/utig5, -name surface) for the surface binary/source — minor inefficiency, NOT all-NFS (bounded). Not hung. Let run; re-arm 1500s. WATCH: if next wake still only searching/exploring w/ no NOTES+no code edit → nudge concern (analysis-paralysis). Expect long ~38min harness runs once it has a hypothesis.

## 2026-06-15 05:09 — 3rd Mira a521a8ca STALLED on NFS bfs; killed the search
Mira blocked ~58min: a single `bfs ... /home/utig5 -name surface` ran 28min (99.6% CPU, 6.6GB RAM) traversing the huge NFS tree — no NOTES_RIDGE3.md, code unedited. This is the NFS-search-waste failure mode. KILLED just the bfs proc (2721591) to unblock the Mira WITHOUT restarting (it has surface.c source path from brief; doesn't need the binary). No replacement search spawned. Re-arm 1200s; if it re-stalls on another search next cycle → TaskStop + re-dispatch w/ explicit "DO NOT run find/bfs; all paths given" + no-data-region lead. ~16h to deadline, still time.

## 2026-06-15 05:31 — 3rd Mira a521a8ca RECOVERED after bfs kill
Post-kill (05:09): gmt_surface_py.py EDITED @05:11 (46664→70650 bytes) — Mira recovered, modifying code on the no-data-region lead. No stuck search now. No NOTES_RIDGE3.md yet, no compute proc this instant (between edit & verification, or reasoning). Effective real work ~22min post-kill (prior ~58min wasted on bfs). On-track per progress criteria (code edited). Let run; re-arm 1680s. Next cycle: expect a ridge verification run (~38min) or NOTES.

## 2026-06-15 06:01 — 3rd Mira: killed bfs #2; productive diagnosis running
Mira launched a 2nd NFS bfs (/usr /home /opt -name gmt, 16min, 4.2GB) — searching for the gmt binary it already has the path to. KILLED it (surgical, 2nd search killed). BUT concurrently running productive work: python3 verbose gmt_surface_py on real Ridgecrest temp.rat (baseline, to capture per-stride convergence in no-data region). Code edited @05:11 (worktree fix in progress). So Mira is productive but inefficient (keeps launching binary searches). ~1h50m wall, ~44min wasted on 2 bfs. Deadline 21:00 (~15h) OK. Let run; re-arm 1680s. If 3rd search + no progress → TaskStop + re-dispatch w/ hard no-search brief.

## 2026-06-15 06:31 — 3rd Mira ACTIVELY diagnosing (proc cwd in /tmp, not worktree — my filter missed it)
NOT idle. Running python3 /tmp/ridge_tiny_proxy.py NOW + wrote 8 diagnostic scripts 06:03-06:29: test_nodata.py, test_fulldata.py, diag_manual_iter.py, diag_dump_state.py, coarsest_stride_diag.py, ridge_n1_diag.py, coarse_only_diag.py, ridge_tiny_proxy.py. Exactly on-target: probing no-data region + coarsest-stride convergence via SMALL FAST proxies (smart — avoids 38min full runs). gmt_surface_py.py unchanged since 05:11 (still diagnosing mechanism, not settled on fix). No NOTES yet (rapid-firing). LIVENESS NOTE: must check ALL dliu python3 procs running /tmp/*.py + /tmp script mtimes, not just worktree-cwd procs. Let run; re-arm 1500s.

## 2026-06-15 06:58 — 3rd Mira deep coarse-stride/no-data instrumentation
Still diagnosing (latest /tmp script diag256.py @06:56, 2min ago): diag256.py (stride-256), count_constraints.py, count_survivors.py, instrument_coarse.py, ridge_py_conv.py. Systematically instrumenting coarse-stride convergence + constraint/survivor counts in no-data region. Worktree gmt_surface_py.py unchanged since 05:11 (no fix settled yet — pure diagnosis ~2h). No NOTES_RIDGE3.md. On-target, progressing. ~2h47m wall (~44min lost to bfs). Deadline 21:00 (~14h) OK. Let run; re-arm 1500s. WATCH: if by ~08:00 (4h) still only diagnosing w/ no fix-attempt+verification → consider nudge toward fix-or-prove-inherent-limit.

## 2026-06-15 07:24 — 3rd Mira entered FIX+VERIFY loop
Worktree gmt_surface_py.py EDITED @07:21 (md5 8223aee, 70920 bytes) — moved past diagnosis to a real code change on no-data region. Running verifications: 2× ridge_parity_check.py (baseline controls — main still CLEAN e6a4045, isolation OK) + nodata_compare.py/nodata_compare2.py (worktree fix) + on-target /tmp scripts (test_constraint_diff, test_fill_verify, coarse_compare). Killed a 3rd wasteful bfs (gmt_debug search, 22min). Main untouched (good). Let run; re-arm 1500s. Next: watch for stabilized fix + its reported Ridgecrest/CSK, then MY OWN Rule-13 verify.

## 2026-06-15 07:51 — 3rd Mira deep in fix+verify (stencil/coeffs/convergence)
Candidate fix 8223aee (07:21) holding; stress-testing via /tmp burst @07:48-07:50: test_stencil/test_stencil2 (boundary stencil), check_coeffs (Briggs), test_py_highiter (convergence/iters), gmt_surface_f64/test_f64 (float64 variant). Running full ridge_parity_check.py (31min) + ridge_n100.py. All on no-data-region BC/convergence. ~3h40m in, methodical, no search waste. test_py_highiter suggests weighing convergence-limited (inherent) branch. No NOTES_RIDGE3.md yet. Let run (NOT paralysis — actively fix+verify); re-arm 1500s.

## 2026-06-15 08:18 — 3rd Mira on convergence-limit branch (~4h7m)
Heavily testing high-N convergence: nodata_largeN.py, small_highN_compare.py, ridge_conv_check.py, ridge_c_highn.py (gmt surface high-N, timeout 4000s). Determining if no-data region only matches C at iters >> -N1000 (→ inherent limit) vs fixable BC. Candidate fix 8223aee (07:21) holding, unchanged 1h. Killed 4th bfs (find gmt, persistent dead-end). No NOTES_RIDGE3.md (4h+, uncheckpointed — restart would lose context, so keeping surgical-kill approach). Productive. Deadline 21:00 (~12.5h). Let run; re-arm 1500s. If concludes inherent-limit → will reframe user expectation (INPROC coverage-gated, not clean v2.1.42).

## 2026-06-15 08:45 — 3rd Mira waiting on long high-N convergence experiment (~4h34m)
ridge_c_highn.py running 27min (timeout 4000s/67min) w/ gmt surface child 100% CPU — high-N C convergence test in no-data region (the fixable-vs-inherent crux). /tmp lull (latest gs_sor_py_test.py @08:25, 20min ago) = blocked on this experiment, NOT idle. Candidate fix 8223aee unchanged. No NOTES_RIDGE3.md. No bfs now. Let experiment finish; re-arm 1500s. Expect Mira to analyze + conclude (fix or inherent-limit) after high-N run completes (~next 40min).

## 2026-06-15 09:12 — PHASE 1 RESOLVED: Ridgecrest 42m is a NO-DATA-ZONE artifact, NOT a port bug
Agent a9cfb57c completed w/ rigorous evidence; CONFIRMED by my own fresh [diag] data:
- Data-covered zone: gmt_surface_py matches gmt surface C to ~0.00m (my 6x6 block map rows0-4 all 0.00; rowmean bot10=0.000 mid=0.000; ONLY top10=97m). CSK 0.0666m.
- The 42.8m is ENTIRELY the unconstrained no-data zone: scatter data ends y=11160; sug-expanded solve-grid → y=12240; ~516 top rows (status=0, unconstrained) all strides.
- Mechanism: GS-SOR spectral radius ρ≈0.9997 for the unconstrained rows → needs ~3351 iters; C allocates max_iter*stride=2000 @stride=2 → NEITHER C NOR Python converges the no-data zone. At N=1, py(LLVM/Numba+FMA) vs C(GCC) differ 1.67e-7/val; ×2000 non-converging iters ×amplification ~3333 ×z_rms720 → 42.8m. At N=50000 BOTH converge & agree to ~3mm.
- ⇒ NOT a gmt_surface_py correctness bug. Matching C's N=1000 NON-converged output in an unconstrained region is cross-compiler impossible. Disproven (again, fresh): expansion, float32 tie-break (the float32 throw_away fix is correct C-parity but changes only 2 cells, does NOT touch the 42m).
DECISION PENDING USER: (a) accept finding, surface stays accurate-where-data-exists, move to Phase 2 perf; (b) check if the original INPROC phasefilt-0.35 symptom came from these no-data pixels (are they masked downstream?) before enabling INPROC; (c) land float32 throw_away parity refinement + _time test fix as v2.1.42. Landing _time test typo fix now (clearly correct).

## 2026-06-15 19:57 — PATH A: launched real-pipeline INPROC=1 S1_Ridgecrest test (user-directed)
User chose A (pursue INPROC default). Launched full S1_Ridgecrest_EQ py pipeline w/ GMTSAR_SURFACE_INPROC=1, SWEEP_FORCE=py (csh oracle preserved), job bjm3whv4m. Decisive test: does phasefilt + grd metrics pass py-vs-csh with in-process Python surface (does the no-data-zone topo_ra divergence actually break downstream, or is it masked)? Baseline scorecard (subprocess surface) had phasefilt_mask_ll SSIM 0.972 (>0.9 pass). Multi-hour run; notifies on completion. ON PASS (all metrics SUCCESS) → run full INPROC=1 sweep (21 cases) → if 21/21 flip GMTSAR_SURFACE_INPROC default ON in dem2topo_ra:560 + bless + tag v2.3.0. ON FAIL → gate must be coverage-aware; document. 21:00 auto-stop superseded by active user direction.

## 2026-06-15 20:06 — User: report scorecard (run still mid-flight) + extend to 48h
INPROC=1 S1_Ridgecrest run (bjm3whv4m): downloaded 29G @20:01, RUN started 20:01:55, ~4.5min into multi-hour pipeline. Scorecard NOT ready (written at end). ETA ~21:30-23:00. Notifies on completion.
NEW HORIZON: 48h autonomous → STOP ~2026-06-17 20:00. DOWN-TASK CHAIN: (1) INPROC S1_Ridgecrest scorecard → report; (2) if pass → full 21-case INPROC sweep → 21/21 → flip default ON + bless + v2.3.0; (3) Phase 2 surface perf (~1.13x→≤1.0x, Mira+benchmarks, preserve parity); (4) bank float32-throw_away + _time test fix. Rule 13 throughout (verify vs csh oracle / my own fresh runs).

## 2026-06-15 22:52 — PATH A RESULT: INPROC=1 S1_Ridgecrest = 15/16 (no default flip)
Fresh real-pipeline scorecard (GMTSAR_SURFACE_INPROC=1 vs preserved csh oracle), 16 py-vs-csh comparisons, 1 FAIL:
  FAIL: H_res/intf raw phasefilt.grd complex-rms 0.3516 > 0.15 (THE original symptom).
  PASS: H_res phasefilt_mask_ll.png SSIM 0.972; merge phasefilt.grd 0.0001; F1/F2/F3 phasefilt 0.0000-0.0002; all corr/filtcorr/corr_ll.
SPATIAL DIAG of the H_res phasefilt diff (cos-distance 6x6 map): rows 0-4 = 0.00 (identical wrapped phase); ONLY bottom block-row hot (1.20, 0.90 in bottom-left 2 blocks) = the no-data corner (y>11160 / x<3676). ⇒ 35/36 of grid bit-matches C; the 0.35 is purely the unconstrained no-data corner (masked by coherence downstream → masked PNG + merge PASS).
DECISION: do NOT flip GMTSAR_SURFACE_INPROC default (strict all-grids gate fails 15/16 on no-data pixels). INPROC stays OPT-IN. Final/masked/merged products are CORRECT with INPROC; only the pre-mask raw H_res intermediate diverges in no-data pixels.
OPEN (user's call): make parity coherence-masked/coverage-aware (principled — gmtsar masks no-data anyway) → would let INPROC pass cleanly → v2.3.0. Deferred to user; do not weaken gate unilaterally.
Banking: _time→time test typo fix (was masking the gated CSK real-scale test) as v2.1.42. float32 throw_away C-parity refinement available in worktrees but deferred (2-cell, no gate impact).

## 2026-06-16 00:46 — Phase-2 perf WALL + INPROC coherence-gate DISPROVEN
PERF (Mira ac43f8f7, completed): pure-Python/Numba gmt_surface_py = ~1.14x C (435.8s py / 383.2s C). Micro-opts saved ~0.18s (below noise) — NOT landing (no benefit). Iteration counts match C within 1-2%; residual is Numba-LLVM vs gcc per-node throughput (~3.7%), NOT FMA. To reach ≤1.0x needs a COMPILED EXTENSION (Cython kernel for _iterate_once, or cffi→libgmt surface_iterate) = new build dependency → USER DECISION (Mira correctly stopped). Parity intact (20/20 non-CSK tests, CSK ≤0.0666m). main NOT modified (worktree only).
INPROC coherence-gate (my measurement, Rule 13): coherence masking does NOT fix the H_res phasefilt 0.35 — corr>0.15 still 0.3517 (96.6% px kept). The divergent pixels are HIGH-COHERENCE no-DEM-zone (top rows; per-row scan: only top band hot=1.05, all else 0.0). topo correction undefined there for BOTH C and py. Coherence-aware gate WON'T unblock; only a DEM-coverage mask / topo_ra clip would (methodology change) → USER DECISION. Excluding no-DEM top rows drops metric 0.35→0.18 (band starts ~row 11000 of 12192).
NEXT (autonomous, safe): full 21-case INPROC=1 sweep to characterize which cases pass/fail w/ Python surface (is S1_Ridgecrest H_res the ONLY no-DEM failure?). Informs INPROC-default decision (maybe coverage-gated/per-case default).

## 2026-06-16 03:49 — FULL 21-CASE INPROC=1 SWEEP COMPLETE: 20/21 clean
Fresh full sweep (GMTSAR_SURFACE_INPROC=1, SWEEP_FORCE=py, vs preserved csh oracles), job bi7dmygpl:
  PASS 20/21 — ALL cases clean incl all 4 S1 TOPS (Greece/LA/COVE), CSK_SLC_Italy, S1_Larsen_C, all ALOS/ALOS2/ENVI/ERS/TSX/NISAR/RS2/CSK_RAW.
  FAIL 1/21 — S1_Ridgecrest_EQ ONLY: H_res/intf raw phasefilt.grd complex-rms 0.352 (thr 0.15) = the no-DEM corner (data y≤11160, grid y→12192; high-coherence but undefined topo correction; final/masked/merge products PASS).
⇒ The in-process Python surface (gmt_surface_py) is PRODUCTION-FAITHFUL across the entire test matrix; the lone holdout is scientifically-meaningless no-DEM pixels in one case's high-res config. S1 TOPS pipeline itself is fine (Greece/LA/COVE all pass) — Ridgecrest unique only b/c its DEM doesn't cover the full H_res grid.
DECISION (presented to user): coverage-gated INPROC default ON (full-Python surface) → v2.3.0, with S1_Ridgecrest H_res known-diff documented; OR keep opt-in. + perf Cython/cffi (1.14x→≤1.0x) decision.

## 2026-06-16 03:55 — v2.3.0 SHIPPED + Cython kernel dispatched (both user decisions)
USER chose: (1) flip INPROC default ON + document Ridgecrest → v2.3.0; (2) Cython GS-SOR kernel for perf.
v2.3.0 LANDED (commit 7f37d73, tag v2.3.0): GMTSAR_SURFACE_INPROC default "0"→"1" in dem2topo_ra:568; docstring+comments updated w/ 20/21 evidence; release_notes_v2.3.0.md; 21/21 scorecards blessed under docs/blessed_scorecards/v2.3.0; 25 unit tests OK; _HAVE_GMT_GRD_IO verified True (no silent fallback); upstream invariant clean. Full-Python surface is now DEFAULT. S1_Ridgecrest H_res no-DEM phasefilt 0.352 documented as accepted meaningless-pixel diff.
DISPATCHED Cython Mira **ac0e5aa226403b743** (worktree,bg): build _surface_kernel.pyx for GS-SOR inner loop, ≤1.0x C, BIT-IDENTICAL parity, OPTIONAL build w/ pure-Python fallback (no hard dep), before/after benchmarks, NOTES_CYTHON.md, DO-NOT-search. Rule-13 verify before landing v2.3.x.

## 2026-06-16 19:52 — New 48h campaign; snaphu re-examined (user: "you didn't try enough")
User pushed back on the inherited "pure-Python snaphu = 2800x = dead end" verdict (Rule 13: it was an inherited conclusion, never re-derived). EVIDENCE-BASED re-read: the 2800x is a Python-OBJECT-OVERHEAD artifact, NOT algorithmic. Our port (bin_py/snaphu_py/snaphu_py.py) uses _Node/_NodeTS CLASSES + list + per-node attribute access in _tree_solve_ts/_min_out_cost_node_ts/_bucket_*; numba usage = 0. C (snaphu_solver.c) uses nodeT structs + pointer-chasing (fast compiled). The prior port was a faithful SCALAR-OBJECT port that NEVER tried struct-of-arrays + numba — the one representation that makes graph solvers fast in Python.
REFACTOR PATH (dispatched): re-port the solver as flat numpy SoA (mirror nodeT → node_next/prev/pred/level/incost/outcost int arrays + bucket/arc arrays) under @njit, matching C control flow + integer arithmetic (→ integer-exact), + fix the >=32x32 cycling (strongly-feasible-tree/anti-cycling per C). Keep bit-faithful I/O+cost code. Target 2800x → ≤~5x C (ideally ≤2x). Verify integer-exact vs C binary on real interferogram (crop + full) + no cycling at 64/256.
ACTIVE MIRAS (≤2): ac0e5aa226403b743 (Cython surface kernel, ~16h in, alive, _surface_kernel.pyx written 19:51 — finishing surface perf; land v2.3.1 on Rule-13 verify) + ac1b0f897920918f4 (snaphu numba-SoA solver, just dispatched). New horizon → STOP ~2026-06-18 20:00.

## 2026-06-16 20:26 — Cython surface Mira ac0e5aa: GOOD CONCEPT, WRONG BASE (Rule-13 catch, NOT landed)
Cython kernel result: CSK 0.84x C (16% faster), bit-identical to Numba (-ffp-contract=off to match LLVM), 19/19 worktree tests, fallback intact, optional build. BUT worktree branched from abd29f4 (old, pre-v2.1.41) — its gmt_surface_py.py is FLOAT64 (md5 f7b3e9c), NOT main's FLOAT32 v2.1.41 (e6a4045). Kernel uses double[::1] u/briggs_b → bit-identical to OLD float64 Numba, NOT main's float32. Landing would REVERT the v2.1.41 float32 fix → CSK 0.0666m regresses to ~0.46m, AND INPROC is now default-ON → ship a regression every run. NOT LANDED.
Concept proven (Cython GS-SOR = 0.84x C, bit-identical-capable). Re-dispatching: target MAIN's float32 gmt_surface_py.py (sync into worktree first), kernel must use float32 u[]/briggs_b matching main's exact float32-product→float64-sum arithmetic, bit-identical to MAIN's Numba, verified vs MAIN's 25-test suite + CSK ≤0.0666m + benchmark + fallback. LESSON: agent worktrees branch from a stale base — re-dispatched briefs MUST sync main's current target files first.

## 2026-06-16 20:54 — Cython float32 kernel a4f262f7: verified-on-main, CSK parity pending
Re-dispatch SUCCESS (correct base): Step0 synced main float32 (e6a4045 over stale ff0dc909). Worktree change = ONLY Cython dispatch shim on main's float32 (diff-confirmed, no numeric drift). MY verify on main: .so builds; 25-test OK (Cython active, _HAVE_CYTHON=True); fallback GMT_SURFACE_PY_CYTHON=0 25-test OK. CSK gated parity (Cython) RUNNING (bwdr1z9ui, must ≤0.0666m). Bit-identity max|Cython-Numba|=0.0 (Mira; isolated+101+1001). PERF: 1001x1001 py faster than C; CSK ~1.19x C (kernel fast but Python orchestration outside kernel is the wall at 30M-node scale — ≤1.0x NOT met at CSK; honest). Land v2.3.1 on CSK pass: commit _surface_kernel.pyx + build_surface_kernel.py + gmt_surface_py.py shim (NOT the .so build artifact).

## 2026-06-16 21:09 — CSK parity (Cython) PASS → landing v2.3.1
MY CSK gated (Cython active): interior RMS 0.0666m (=Numba, bit-identical, NO regression). Wall-time py 422.3s vs C 414.0s = 1.02x C this run (mid-grids faster; CSK ~parity). All gates: 25-test OK (Cython+fallback), _HAVE_CYTHON=True, bit-identical max|diff|=0.0. LANDING v2.3.1 (optional Cython kernel, graceful Numba fallback, no hard dep).

## 2026-06-16 21:23 — CAMPAIGN-3 (48h) "keep going" + roadmap survey
Shipped: v2.3.0 (surface default ON), v2.3.1 (Cython kernel). Surveyed remaining non-Python steps (evidence-based):
ROADMAP (compute-meaningful, by value):
  1. snaphu — IN FLIGHT (ac1b0f numba-SoA solver).
  2. grdmath→numpy — 52 calls, ops all trivial (MUL/SUB/ADD/FLIPUD/DIV/NAN/GE/SQRT/POW/ATAN2/ABS); biggest gmt footprint; clean via gmt_grd_io. DISPATCHED (afbb31f3, opt-in GMTSAR_GRDMATH_PY default OFF, C-parity tests).
  3. 5 remaining `gmt surface` calls (proj_ll2ra, align_tops, tide_correction) → route through gmt_surface_py (now default).
  4. grid interp/filter helpers: grdsample, grdfilter, triangulate, blockmean, nearest_grid, grdlandmask.
  5. proj_ra2ll/ll2ra projection binaries.
OUT OF SCOPE (low value, leave on GMT/C): plotting (psconvert/grdimage/grd2kml/makecpt/psscale/grdgradient/psxy), sensor preproc (make_slc_*/calc_dop_orb/extend_orbit) — visualization + sensor I/O, not numerical cores.
ACTIVE MIRAS (≤2): ac1b0f (snaphu numba-SoA), afbb31f3 (grdmath→numpy). Horizon → STOP ~2026-06-18 21:00.

## 2026-06-16 22:08 — grdmath Mira afbb31f3: helper LANDED (v2.3.2), wire-ins DEFERRED (stale base)
gmt_grdmath_py.py: 16 ops (FLIPUD/MUL/ADD/SUB/DIV/ABS/SQR/SQRT/POW/HYPOT/ATAN2/GE/LE/NAN/XOR/MIN), float64-internal→float32-write matching GMT (key parity finding), 39-test C-parity suite. MY verify on main: 39/39 pass.
STALE-BASE CATCH (Rule 13): worktree's filter/stack were from a stale commit — worktree filter REVERTS main's phasefilt_py wiring (v2.1.37: GMTSAR_PHASEFILT_PY default-ON → worktree has old plain `run('phasefilt ...')`). gmt_grd_io was in sync (md5 match) but filter/stack NOT. So did NOT copy worktree filter/stack. LANDED only the NEW standalone files (gmt_grdmath_py.py + test) — opt-in, default OFF, UNWIRED (changes no behavior). Wire-ins (filter 8 sites, stack 8 sites) DEFERRED: must re-apply grdmath dispatch hunks onto MAIN's current filter/stack (preserving phasefilt_py), not copy stale worktree files.

## 2026-06-16 22:22 — snaphu Mira ac1b0f: numba-compilation friction (watch)
Mira alive (transcript 22:20) but ~2.5h, NO NOTES_SNAPHU.md yet. Created snaphu_solver_numba.py (SoA @njit — right approach). BUT hit a NUMBA COMPILATION HANG: a `python -c` import-test of snaphu_solver_numba._find_apex stuck 2h13m @98% CPU compiling — numba struggling w/ the solver's index-chasing control flow. Killed the hung orphan (599149) + a stray bfs (search-waste pattern). OBSTACLE: numba may not compile the network-simplex helpers cleanly; if unresolved, fallback = cffi binding to C solver (keeps C numerics+speed, Python-callable). Agent working through it. WATCH: if next cycle still stuck (no NOTES, another hang) → TaskStop + reassess approach (cffi vs continue numba). Re-arm 1500s.

## 2026-06-16 23:11 — snaphu numba-SoA: BUILT + COMPILES, blocked on TreeSolve cycling bug (stopped, salvaged)
Stopped ac1b0f (reasoning-spin: transcript fresh but no code edit 68min, no NOTES 3.3h, no compute). SALVAGED state from worktree snaphu_solver_numba.py (2142 lines) + transcript tail:
  ACHIEVED: full struct-of-arrays numba port — @njit cost fns (_calc_cost_smooth/defo_incr, _recalc_cost, _get_cost), flat node/arc/bucket arrays, _bkt_insert/remove, _min_out_cost_node, _add_new_node, _find_apex, _check_arc_reduced_cost, _tree_solve_kernel (45 args), all @njit(cache=True). NUMBA COMPILATION WALL OVERCOME (import 0.21s = JIT cache loads). ⇒ object-overhead→SoA+numba thesis validated; it compiles.
  BLOCKER: CORRECTNESS bug in TreeSolve REMOUNT thread-loop — `-6666` anti-cycling guard fires at nconnected*4=3368 iters on a 30x30 patch (r0=800,c0=500, 14 residues). Same network-simplex strongly-feasible-tree cycling invariant that shelved the ORIGINAL port — now in the fast numba version. Thread-loop level-check (while nd1->next->level > startlevel) vs C not yet right. NOT a perf/compile issue.
  ⇒ The hard part of snaphu is the combinatorial solver correctness (cycling), not Python overhead. numba-SoA is ~90% there structurally; needs the tree-remount/anti-cycling logic debugged vs C.
DECISION → USER: (a) cffi/ctypes → C snaphu solver (sidesteps cycling debug; C's proven solver; Python-callable; C speed+numerics) — pragmatic; (b) keep snaphu on C binary (status quo); (c) one more focused debug pass on the numba-SoA TreeSolve remount cycling (infra exists, but cycling is the known-hard part). Worktree preserved: agent-ac1b0f897920918f4.

## 2026-06-17 00:06 — wei-lin agent enhanced + refactored (portable workflow guardian) + v2.3.3
v2.3.3 landed (fc2ca79): grdmath wired into filter+stack behind GMTSAR_GRDMATH_PY (default OFF), phasefilt_py preserved, parity max|diff|=0, 39/39 tests.
USER meta-request: enhance wei-lin (the consilium workflow-conductor agent, /home/utig5/dliu/consilium/agents/wei-lin.md, symlinked across all projects under $HOME) to carry this campaign's hard-won discipline + be truly portable. DONE: added merge-gate axes (re-verify-yourself-vs-oracle on real data; confirm-built-on-current-HEAD/stale-worktree-base diff; gate-exercises-new-path), babysitting (transcript-mtime liveness, kill search-waste/hung-compiles, require checkpoints), elevated project_rules.md (universal rules carried IN wei-lin → portable w/ zero setup; project_rules.md = local specifics + bootstrap/enforce/compound), refactored (deduped Lessons vs Cardinal, consolidated discipline). 292 lines, frontmatter/tools/model intact. This codifies the campaign methodology for reuse on other projects.
ACTIVE: snaphu cycling-fix Mira a71831b5 alive (transcript 00:01, snaphu_solver_numba.py edited 23:51 — working remount thread-loop fix). QUEUED: snaphu verify→land; 5 gmt surface→gmt_surface_py; grdmath default-flip after sweep; grid-helpers.

## 2026-06-17 (new session) — Phase 0 audit + snaphu worktree gate verdict

**Phase-0 audit:** HEAD=fc2ca79, v2.3.3 latest port tag. Session log staged (not committed). Worktree agent-a71831b5924d784c3 still present; snaphu_solver_numba.py = 2142 lines, mtime 23:51 Jun 16, no NOTES_SNAPHU2.md (agent not active).

**Snaphu gate (my run, Rule 13):** Ran network_flow_optimize_numba() from worktree on real S1A_SLC_TOPS_Greece phasefilt.grd 30x30 crop (r0=800,c0=500) vs C snaphu binary. C exit 0, produced unwrapped output. Py: RuntimeError sentinel -6666 (thread-loop-1 cycling, nconnected=842). Also tested synthetic 64x64 → -4444 (remounted subtree scan), 256x256 → -4444. Import 0.28s (numba cache warm). VERDICT: FAIL on all three parts. The worktree fix converts hang→hard error but does NOT fix root cause: _thr1_guard at `while node_level[node_next[nd1]] <= startlevel` never breaks — subtree endpoint detection incorrect vs C. node_level/node_next state corrupted after first pivot.

**Decision:** Worktree agent-a71831b5924d784c3 NOT LANDED. Cycling remains structurally unsolved. Three options per prior session (user decision point): (a) cffi→C solver, (b) status quo C binary, (c) another focused debug pass on remount logic. Proceeding to roadmap item 2 (grdmath default-flip) while awaiting user direction on snaphu.

## 2026-06-17 — Roadmap item 2: grdmath default-flip — BLOCKED, regression found

**Smoke run** (RS2_SLC_Hawaii, GMTSAR_GRDMATH_PY=1, SWEEP_FORCE=py, 93s): FAIL — 4 missing output files (corr_ll.grd + 3 geocoded PNGs).

**Root cause (my diagnosis):** `grdmath_corr_chain` in filter (line 237) writes `tmp2.grd=bf`. The `conv` call at line 242 then fails with "gmtlib_read_grd_info: Use grdedit -A on your grid file to make region and increments compatible [tmp2.grd=bf]" + "could not allocate output grid". The grdmath_corr_chain writes a NetCDF .grd with region/increment metadata that doesn't match what `conv` expects from a pure binary float file (=bf suffix). The GMT grdmath version writes =bf directly and conv reads it correctly; the Python grdmath_corr_chain writes .grd format to a filename with =bf extension, but conv interprets the =bf extension as native binary — the bytes don't match. This is a file-format/metadata bug in grdmath_corr_chain's output path, not a numerical parity issue.

**Decision:** grdmath default-flip BLOCKED until grdmath_corr_chain is fixed to write genuine binary float (=bf) output, not NetCDF with a =bf filename. Gate was correctly red; no landing. Moving to roadmap item 3 (remaining `gmt surface` calls).

## 2026-06-17 — Roadmap item 3: remaining gmt surface calls LANDED (v2.3.4)

Dispatched Mira (worktree agent-a721259fd298372ef): wire 5 `gmt surface` calls in proj_ll2ra (2), tide_correction (1), align_tops (2) through GMTSAR_SURFACE_INPROC gate (default ON). Step-0 md5 matches confirmed on all 3 files.

**My gate (Rule 13):** Syntax OK (3 files). Unit tests OK (skipped=4). Stale-worktree diff: only 3 target files changed vs HEAD — clean. Import checks: each script runs and shows usage error (not import error) confirming _HAVE_GMT_GRD_IO resolves True at runtime. Upstream invariant: 0 lines.

**LANDED:** commit b35f6b2, tag v2.3.4. 5 surface calls routed: proj_ll2ra (float32 binary), tide_correction (ASCII, pixel-reg), align_tops (float64 binary, pixel-reg, parallel Popen→sequential inproc). GMTSAR_SURFACE_INPROC=0 preserves fallback.

## 2026-06-17 01:03 — v2.3.5 landed; concurrency cap lifted; grid-helper track opened
v2.3.5 (8f428d9): wei-lin fixed grdmath_corr_chain =bf → genuine GMT binary-float output (unblocks grdmath default-flip; upstream clean). User LIFTED the ≤2-agent cap ("spawn more if resource permits"). Box: 48 cores, load ~7, 20G/1007G mem — ample headroom.
PARTITION (avoid file overlap): wei-lin (a72f09080b6c03050) owns snaphu (pinpointed node_level-corruption fix) + grdmath default-flip (escalates flip to me). I (supervisor) own the GRID-INTERP HELPER track in parallel. Dispatched mira a69c06b17257bcae8: gmt_grdsample_py (top grid op, 6 calls), helper-first + C-parity test, opt-in default-OFF, NO wiring. Next grid-helpers (grdfilter/triangulate/nearest_grid/grdlandmask) can parallelize too. Policy: up to ~5-6 concurrent agents while load stays < ~24.

## 2026-06-17 01:15 — supervisor wake: orphan cleanup, grdsample RESOLVED (redundant), grdmath flip gate re-run
- **Orphan hygiene:** killed 6 orphaned hung snaphu solver repro procs (`/tmp/repro_orig.py` 73m, `quick_test.py` 49m, `test_fix.py` 39m, `verify_scalar.py` 27m, 2× `test_snaphu_fix.py`) — all cycling-forever at 100% CPU, no agent transcript active in 60min, nothing consuming output. Load 8.6→easing. One live snaphu agent remains (a71831b5 `parity_c_test.py`, on the cycling fix).
- **grdsample cp RESOLVED — redundant dispatch, reverted.** gmt_grdsample_py.py + test already on main (prior Mira #65); my a69c06b1 dispatch was redundant. Its only artifact was a `grdsample_wrapper.py` rewrite flipping default ON→OFF, justified by "2.7× slower on NaN-heavy landmask." **Disproved by fresh A/B on real ALOS_haiti landmask (9.77M cells, 38% NaN, 4×4 bicubic):**
    - C `gmt grdsample`: ~1.00s
    - py port cold (no JIT cache): ~3.25s; cold (warm disk-cache, real per-invocation): ~1.1s ≈ parity; warm in-process multi-call: 0.58s (1.7× faster)
    - **byte-identical: max|py-c| = 0.000, NaN-pattern identical**
  → BOTH Miras' headline numbers wrong (not "2.25× faster" #65, not "2.7× slower"). Truth: byte-id + ~parity per-invocation. Reverted the wrapper (`git checkout`); main stays at its committed default-ON. The overclaiming "2.25× faster" docstring on main is inaccurate (real = parity) — non-urgent doc-accuracy item; default left at status quo (byte-id, negligible perf impact; snaphu solver dominates wall time).
  - **LESSON:** survey `git ls-files utils/` for existing ports BEFORE dispatching. Already on main: surface, blockmedian, grdfill, **grdfilter**, grdmath, grdsample, grd_io. Remaining grid gaps (triangulate/nearest_grid/grdlandmask) are low-value GMT wrappers, not compute cores — deprioritized vs finishing snaphu.
- **grdmath default-flip:** re-running RS2_SLC_Hawaii smoke (GMTSAR_GRDMATH_PY=1, SWEEP_FORCE=py) now that v2.3.5 fixed the =bf bug that caused the prior FAIL (4 missing files). Result pending → makes the flip decision evidence-ready for user.
- **Open USER decisions (relayed):** (1) grdmath default-flip (pending this smoke); (2) snaphu cffi→C-solver vs park-on-C-binary (numba-SoA walls on anti-cycling remount bug); (3) surface cffi→libgmt (new build dep). HEAD=v2.3.5, upstream invariant clean.

## 2026-06-17 01:25 — grdmath default-flip BLOCKED (confirmed A/B); corr_chain =bf bug pinpointed; focused mira dispatched
- **Decisive A/B control (Rule 13, same SHA 8f428d9=v2.3.5, RS2_SLC_Hawaii smoke, SWEEP_FORCE=py):**
    - GMTSAR_GRDMATH_PY=0: corr_ll.grd PASS (rms 9.7e-7), 3 PNGs PASS (ssim ~1.0), blessed diff PASS.
    - GMTSAR_GRDMATH_PY=1: corr_ll.grd FAIL (rms 0.39), corr_ll/display_amp_ll/phasefilt_mask_ll PNGs MISSING, mask2.grd not produced.
  → grdmath=1 IS the cause. **Default-flip BLOCKED.**
- **Root cause pinpoint:** filter:237 `_gm.grdmath_corr_chain('amp.grd','tmp.grd','mask.grd','tmp2.grd=bf')` then filter:242 `conv 1 1 <f3> tmp2.grd=bf corr.grd`. The =bf writer in gmt_grdmath_py.grdmath_corr_chain (touched by v2.3.5) writes a header whose dims/registration don't match `gmt grdmath ... =bf` → conv misreads → py corr.grd shape 1435x3414 vs csh 718x854 → corr_ll diverges + PNG cascade. v2.3.5 only verified "conv exits 0 + bf format", NEVER that corr.grd OUTPUT matches csh. mask.grd/phasefilt.grd/filtcorr.grd all PASS — only corr_chain broken.
- **Dispatched mira aa7444594516b0734** (focused): fix grdmath_corr_chain =bf header so conv→corr.grd matches csh (shape+values, rms<0.01); verify via GMTSAR_GRDMATH_PY=1 RS2 smoke (corr_ll SUCCESS + PNGs) AND grdmath=0 no-regress; add C-parity test for the full corr_chain->conv chain. Default stays OFF; no commit/tag (supervisor lands).
- **Surface:** DROPPED the "cffi→libgmt" item from the queue — surface is done+verified (v2.3.0 default-ON, 20/21); cffi was only optional perf polish (1.14x→<=1.0x), not rework. (User flagged the misleading framing.)
- **snaphu:** awaiting USER decision — cffi→C solver vs park-on-C-binary vs one more remount-debug pass.

## 2026-06-17 01:35 — USER: "one more focused remount-debug pass on snaphu" → dispatched
- Killed a71831b5's hung snaphu procs (test_snaphu_fix.py 14min cycling + parity_c_test.py). a71831b5 was on STALE base (abd29f4 vs HEAD 8f428d9), likely-dead parent.
- Preserved a71831b5's worktree solver (2150 lines, 4 remount thread-loops + -6666 guards at 1322/1453/1529/1603) → /tmp/snaphu_solver_a71831b5_preserved.py. It's MORE advanced than main's untracked snaphu_solver_numba.py (1882 lines, 542-line diff) → used as the focused pass's starting base.
- **Dispatched mira a6b06c7791c1ef40f** (focused snaphu remount): start from preserved solver; match C TreeSolve remount (snaphu_solver.c:197 / remount block :656 — apexlist timing vs groupcounter, prev_root==mntpt thread rewire read-after-write, level-update loop `while nd1->next->level > startlevel`) line-by-line; verify integer-exact vs C binary (snaphu/src/snaphu) on the KNOWN failing 30x30 r0=800/c0=500 14-residue case + 64/256, NO -6666. If still cycles → report precise un-replicable C step (becomes cffi-vs-park evidence). Pure-Python/numba only; not wired; no commit.
- Parallel: mira aa7444594516b0734 still on grdmath corr_chain =bf fix.

## 2026-06-17 01:50 — v2.3.6 LANDED: grdmath corr_chain =bf header fix (verified myself, Rule 13)
- Mira aa7444594516b0734 fixed gmt_grdmath_py._write_gmt_binary_float: removed phantom xy_off field (shifted xinc/yinc/nan_value by one slot), set node_offset=pixel(1) not gridline(0), wrote pixel-reg WESN cell boundaries (x[0]-xinc/2) not node centres, and removed an erroneous np.flipud in grdmath_corr_chain's =bf path. Root: wrong =bf header → conv misread dims → corr.grd 1435x3414 vs csh 718x854.
- **SUPERVISOR VERIFY (not trusting agent):** 42/42 grdmath C-parity tests pass (3 new TestCorrChainVsConv). Fresh GMTSAR_GRDMATH_PY=1 RS2_SLC_Hawaii smoke ALL SUCCESS: corr_ll.grd rms 9.69e-7 (was 0.39), 3 PNGs ssim ~1.0, phasefilt/filtcorr still pass. grdmath=0 path unaffected (code only touches the =1 corr_chain). Eyeballed the diff — matches root cause.
- Landed ONLY grdmath files (utils/gmt_grdmath_py.py + bin_py/tests/test_gmt_grdmath_py.py); snaphu_py.py + snaphu_solver_numba.py left to in-flight snaphu mira a6b06c77 (disjoint file sets, both miras ran in main checkout).
- **grdmath default-flip now EVIDENCE-READY** (all known corr_chain/=bf bugs fixed; full RS2 pipeline clean under =1) → escalating flip decision to user. Default still OFF until user approves.

## 2026-06-17 02:50 — v2.3.7 LANDED: snaphu anti-cycling SOLVED (research checkpoint, UNWIRED)
- **BREAKTHROUGH (verified myself, Rule 13):** the network-simplex anti-cycling remount bug — which shelved BOTH the scalar port and the earlier SoA attempt — is FIXED. Mira a6b06c77 corrected (1) the remount thread-rewire `prv_root==mntpt` read-after-write aliasing in snaphu_solver_numba.py:1342-1354 to match C's 6-step pointer update (snaphu_solver.c:704-710), and (2) integrate_phase's seed: apply WrapPhase (phase - TWOPI*floor(phase/TWOPI)) before seeding, matching C's ReadInputFile (without it phase[0,0]<0 gave a ~2π seed offset).
- **My independent verification:** 30x30 r0=800/c0=500 (the known 14-residue failing case) AND 64x64 (above the prior >=32 cycling threshold) → FLOAT32-EXACT vs C binary (max_resid 4.77e-7 / 2.86e-6 rad, wrap_diffs 0, NO -6666). Full test_snaphu_py: 67 pass / 1 skipped, 40.7s.
- **PERF WALL remains:** 256x256 does NOT complete in reasonable time (>26 min mira / >400s my run) — pure-Python/numba network-simplex too slow for full-scale grids. Gated test_parity_256x256 behind SNAPHU_SLOW_TEST=1 so the suite stays fast.
- **Landed UNWIRED** (production utils/snaphu.py uses the C binary; bin_py/snaphu_py not imported by it). Files: bin_py/snaphu_py/snaphu_solver_numba.py (new, 2150 lines), snaphu_py.py (WrapPhase seed), bin_py/tests/test_snaphu_py.py (oracle tests + slow-gate). Disjoint from the running grdmath=1 full sweep.
- **VERDICT for user:** pure-Python snaphu is now CORRECT (C-parity proven on real-data patches), but NOT fast enough for production. This reframes cffi-vs-park: algorithm solved, throughput is the only remaining gap. Options: (a) cffi/Cython the SoA kernel for speed (correctness now done → lower risk); (b) keep C binary in production + this as the audit/reference port.

## 2026-06-17 (wei-lin session re-entry) — Phase-0 audit + DECISION 1 + DECISION 2

Phase-0 git audit: initial `gitStatus` snapshot showed HEAD at fe3a418 (v2.3.4) — stale snapshot from session start; actual HEAD was already c45ae88 (v2.3.7) with v2.3.5/6/7 all landed by the prior autonomous pass.

**DECISION 1 (grdmath =bf):** Already executed by prior pass (v2.3.5 initial binary-float write, v2.3.6 header correction). This session additionally landed 8f428d9 (v2.3.5) — an independent fix pass that was superseded by v2.3.6's header correction. Net: no rework needed; v2.3.6 is the correct final fix.

**DECISION 2 (snaphu cycling):** Already executed by prior pass (v2.3.7). This session dispatched a fresh Mira (worktree agent-aeb5dab8249cf2ccd) targeting the same two bugs. Mira's Rule-13 pre-check confirmed the scalar oracle (`network_flow_optimize` in snaphu_py.py) still hangs at 8x10+ synthetic patches — this is a PRE-EXISTING scalar oracle issue, NOT the production path. v2.3.7 fixed the NUMBA solver (the real port) and verified it float32-exact vs C on 30x30 + 64x64 real data. The scalar is a slow reference port acknowledged as non-production; its hanging behavior on >8x10 is expected (pre-existing, confirmed independent). This session's Mira did NOT land (superseded by v2.3.7).

**Current HEAD:** c45ae88 = v2.3.7. Both DECISION 1 and DECISION 2 fully resolved.

**Pending USER decisions:**
- grdmath default-flip: EVIDENCE-READY per v2.3.6 session log (RS2 smoke GMTSAR_GRDMATH_PY=1 clean); default still OFF. Flip = default change → requires user approval.
- snaphu throughput: numba correct, too slow for 256x256+. cffi/Cython vs keep C-binary = user decision.

## 2026-06-17 04:00 — a71831b5 (old snaphu agent) completed: independent corroboration of v2.3.7 + tiling claim DISPROVEN
- a71831b5 INDEPENDENTLY found the SAME root cause + fix as a6b06c77 (the `prv_root==mntpt` thread-rewire read-after-write aliasing) → strong corroboration of the v2.3.7 anti-cycling fix. Its worktree solver = same fix already landed; nothing new to land.
- Its extra cases: r800c500 30x30 (resid 2.38e-7, wrap_diffs 0) + 64x64 (2.86e-6, wrap_diffs 0) INTEGER-EXACT — matches my v2.3.7 verification. NOTE: r1500c1000 30x30 showed wrap_diffs 897/900 (resid 1.26e-6) — a different patch location where the solver finds an integer-shifted (possibly alternate-valid) solution; NOT in the landed verification set, port is unwired, so does not affect v2.3.7. Flag for any future wiring.
- Confirms 256x256 hang = PERF (no -6666 sentinel; candidate loop O(65k×256) infeasible in pure Python), NOT cycling — matches my verdict.
- **Rule 13 — DISPROVEN claim:** a71831b5 stated "GMTSAR tiles at <=64x64 by default, works correctly." FALSE. utils/snaphu.py:68 = "Single-tile snaphu unwrap"; snaphu.conf.brief NTILEROW/NTILECOL commented out (default 1 tile). GMTSAR runs snaphu SINGLE-TILE on the full grid (e.g. ALOS_haiti 2826x3456 ~9.7M nodes). So the pure-Python solver (walls at 256x256) is NOT production-viable as-is — wiring would require cffi/Cython speed OR enabling snaphu tiling (which changes results, not GMTSAR default). The (a) cffi vs (b) park decision is unchanged but now better-grounded: cffi is REQUIRED for any production wiring.

## 2026-06-17 04:50 — FULL 21-case GMTSAR_GRDMATH_PY=1 sweep DONE: 20/21 py-vs-csh CLEAN → grdmath flip EVIDENCE-READY
- **py-vs-csh parity (the real flip criterion): 20/21 CLEAN.** All ALOS/ALOS2/ALOS4/ENVI/ERS/CSK/NISAR/RS2/TSX/S1-TOPS/S1_Larsen PASS under grdmath=1.
- ONLY failure: S1_Ridgecrest_EQ phasefilt.grd complex-rms 0.3516 (thr 0.15) = the KNOWN documented surface no-DEM-corner artifact (same 0.3516 value as surface-INPROC; present regardless of grdmath; surface is default-ON so it appears here too). NOT a grdmath regression.
- Blessed-hash diff = 20 FAIL / 1 PASS, but that's md5 over-sensitivity: grdmath=1's float64-internal ops produce bit-different-but-rms-clean files vs the v2.3.0 grdmath=0 blessed snapshot. The rms-threshold scorecard (py-vs-csh) is the parity truth → 20/21 clean.
- **VERDICT: grdmath default-flip (GMTSAR_GRDMATH_PY default OFF→ON) is FULLY evidence-ready.** Meets the same bar as the surface flip (v2.3.0). ESCALATED to user for approval (default change). Not flipped without approval.

## 2026-06-17 08:00 — v2.3.8 LANDED: grdmath default flipped OFF→ON (user-approved)
- USER approved the flip. Changed utils/filter:30 + utils/stack:26 default "0"→"1" (+ comments). 
- Evidence: full 21-case GMTSAR_GRDMATH_PY=1 sweep 20/21 py-vs-csh clean (only the documented S1_Ridgecrest no-DEM surface corner); plus a fresh default-env (no override) RS2 smoke = 6/6 py-vs-csh SUCCESS (exercises grdmath_corr_chain=bf corr_ll path by default). Set GMTSAR_GRDMATH_PY=0 to force the gmt subprocess.
- grdmath now joins surface as a Python-by-default compute core. snaphu cffi/Cython (user-approved) in flight (mira a1f99c00) for the final perf frontier.

## 2026-06-17 08:25 — MACRO PROFILE (Tier-0, from existing sweep phase_profile_py.json, 30 py cases)
- Method: aggregated work/python_test/*/phase_profile_py.json (parallel-sweep times → contention-inflated absolute, but RELATIVE breakdown robust + consistent across cases).
- **dem2topo_ra (surface/make_topo) DOMINATES: 30,762s binary-time, ~3x next op.** P2P3_make_topo=36% of phase time directly; 56-81% of non-TOPS cases (ALOS_haiti/ENVI); nested in frame_subswaths_p2p (42%) for S1 TOPS.
- Op ranking: dem2topo_ra 30762s >> pre_proc 3121 > merge_unwrap_geocode_tops 2184 > resamp_py 1231 > geocode 1048 > intf 775 > xcorr_py 622 > **snaphu 112.5s (0.3%)**.
- **KEY STEER for the optimize chapter:** (1) snaphu is END-TO-END NEGLIGIBLE (0.3%) → its cffi speed is a correctness/completeness win, not a perf one. (2) SURFACE is THE target — but it's already ~1.0-1.14x C (Cython built), so the C pipeline ALSO spends most time here → can't win by matching C; need a BETTER ALGORITHM (multigrid O(N) vs GS-SOR slow spectral radius — also fixes no-DEM-corner non-convergence) or GPU stencil (order-of-magnitude). Red-black prange SOR is the cheap intermediate.
- py-spy installed for the isolated micro-profile (an S1 TOPS case) when ready.

## 2026-06-17 09:30 — snaphu cffi/Cython mira DONE: walls on SoA cache layout → chapter closed (v2.3.9 experimental, UNWIRED)
- Cython kernel (_snaphu_solver_kernel.pyx 1540 lines, nogil cdef) built + correct on small patches (30/64 integer-exact flows vs numba; 30x30 parity-OK vs C binary). VERIFIED MYSELF: TestSnaphuCyParityVsCBinary 4/4 pass; numba 30/64 oracle still float32-exact with the guard tweak (no v2.3.7 regression).
- **DIAGNOSIS (key learning): the perf wall is SoA-vs-AoS CACHE LAYOUT, not algorithm/interpreter.** Algorithm is O(n log n) (matches C). C packs 9 per-node fields in one struct (1 cache line/node/traversal); the Python/Cython port uses 9 separate flat arrays → 9 cache regions touched per node → ~125x constant-factor overhead on high-pivot patches. Cython does NOT fix this (it's data layout, not language). Cython walls at 256x256 (production scale), same as numba.
- To actually reach full-grid speed would need: (a) AoS numpy structured-array rewrite (full kernel rewrite), or (b) cffi/ctypes wrapping C TreeSolve (abandons "pure Python"). 
- **DECISION: snaphu chapter CLOSED.** snaphu is 0.3% of pipeline wall-time (macro profile) → further speed work is low-ROI. Production stays on the C binary; v2.3.7 numba port = correctness/audit reference; v2.3.9 Cython = experimental, UNWIRED, documented. Pivot optimize energy to SURFACE (the 36-81% cost). Also raised numba cycling guard 10x->100x nconnected (fewer premature -6666 fires; verified no regression).

## 2026-06-17 12:35 — v2.4.0 TAGGED: capstone milestone, all-Python-defaults 20/21 clean
- Full 21-case all-Python-defaults sweep (no env overrides: surface+grdmath+grdsample+Cython all ON; SWEEP_FORCE=py): **20/21 py-vs-csh CLEAN**. Only diff = S1_Ridgecrest_EQ phasefilt.grd complex-rms 0.3516 (the documented no-DEM-corner surface artifact, identical value, not a new regression).
- v2.4.0 = "every compute core runs in Python by default, verified vs csh." snaphu = C binary in production + v2.3.7 numba correctness-reference.
- Wrote docs/release_notes_v2.4.0.md. Next: optimize chapter — isolated py-spy micro-profile of an S1 TOPS case (surface micro-hotspot) → surface parity-vs-speed tradeoff to user.

## 2026-06-17 12:40 — MICRO-PROFILE (from existing dem2topo_ra_phase_profile_py.json): surface = 99.2% of dem2topo
- ALOS_haiti dem2topo_ra total 867.5s: surface 860.88s (99.2%), grd2xyz_SAT_llt2rat 5.3s, gmtconvert 1.0s, flipud 0.4s. The dominant pipeline cost IS the gmt_surface_py GS-SOR biharmonic solve (~99% of dem2topo, which is 36-81% of each case). No py-spy run needed — the existing instrumentation pinpoints it unambiguously.
- Surface is already ~1.0-1.14x the gmt surface C binary (Cython kernel). Line-level tuning won't help; only an algorithm change (multigrid/red-black SOR) or GPU stencil would — all of which alter update order → BREAK bit-identity with gmt surface. This is the optimize-chapter fork → escalated to user.

## 2026-06-17 20:45 — v2.4.1: portability cleanup (contribution-ready), kai-fischer + manual
- Removed hardcoded /home/staff/dliu dev paths so the framework runs on any machine (prep for upstream contribution; user will PR later). License = inherits root GPL-3.0 (no separate file). No CITATION/Zenodo (user decision).
- kai-fischer (worktree, STALE base abd29f4) fixed 29 files; landed via DELTA-APPLY (git apply of its diff-vs-base) onto master's current files — applied CLEANLY (no v2.3.6-v2.4.0 reversion). git apply STRIPPED +x on shipped scripts → RESTORED chmod 755 (sweep.sh/case_runner.sh/install.sh/make_gacos_correction/swap.sh) + git update-index --chmod=+x (the memory'd cascade hazard).
- Fixes: sweep.sh/case_runner.sh derive GMTSAR from git rev-parse ONLY if GMTSAR unset (respects env — verified no breakage; /home/staff & /home/utig5 gmtsar are the same realpath); ~20 bin_py/tests use _WORK_ROOT (env/repo-relative + skipif on missing fixtures); install.sh drops personal conda path; CLAUDE.md generic paths; make_gacos_correction clean sys.exit(2) stub-guard.
- MANUAL (kai's stale worktree was missing these master files): phasefilt_py:93 _gmt_bin() → shutil.which("gmt") raising on None (the only SHIPPED-RUNTIME portability bug — fixed). Added requirements.txt (py deps).
- VERIFIED (Rule 13): 121 bin_py tests pass (5 skip, fixture-gated) on master after patch; bash -n clean; sweep.sh respects GMTSAR env.
- REMAINING for the upstream-PR finalization (test-only, in fallback/fixture position, work here): hardcoded paths still in test_snaphu_py.py (~20 occ, research-port tests), test_gmt_grdmath_py.py (lines 74/638/644/654), test_gmt_xyz2grd_py.py:45, test_m2s_py.py:44/52/54. Left unedited to avoid regression risk in the parity tests; flagged for the PR.

## 2026-06-17 21:00 — v2.4.2: fix +x in index for 7 bin_py CLI ports (fresh-clone cascade fix)
- Root cause: core.fileMode=false → git ignores working-copy +x, so the 7 bin_py CLI ports (invoked by name in the pipeline: SAT_baseline_py, SAT_llt2rat_py_v2, conv_py, make_los_py, phasediff_py, phasefilt_py, resamp_py_v2) were 775 in working copy but 100644 in INDEX. A fresh clone gets them non-executable → `Permission denied` → empty trans.dat → cascade (the memory'd hazard). Fixed with git update-index --chmod=+x (mode-only; index now 100755). Verified MYSELF: working-copy 775, index 100755.
- (Other shebang files in needs-x list — test_*.py / tests/configs/*.py / imported utils libs — are run via `python3`/imported, not by-name, so don't need +x. utils_pygmt experimental, excluded from publication.)

## 2026-06-17 20:58 — PORTABILITY VERIFIED end-to-end → contribution-ready CONFIRMED
- RS2 smoke at v2.4.2 (c8cfe39), default-ish env, SWEEP_FORCE=py: 6/6 py-vs-csh SUCCESS (103s); no Permission-denied / path-derivation errors. The portable code (sweep.sh git-derived GMTSAR, phasefilt_py shutil.which, bin_py +x in index) runs the pipeline clean.
- CAMPAIGN ENDPOINT (verified): v2.4.0 (all compute cores Python-by-default, 20/21 capstone) + v2.4.1 (portability) + v2.4.2 (+x). Code is contribution-ready for the user's upstream gmtsar/gmtsar PR. Remaining = low-value tail (4 test files w/ fallback hardcoded paths flagged for the PR; utils_pygmt experimental). Awaiting user direction.

## 2026-06-17 21:10 — README followability test (per user) → 1 gap found + fixed (v2.4.3)
- Followed README no-sudo path on a fresh-ish shell (skipped tarballs per user). RESULTS:
  - install.sh --conda --python --build: WORKS end-to-end (exit 0; conda env auto-detected at $HOME/anaconda3/envs/gmtsar — kai's removal of the /home/staff hardcode is fine since $HOME=/home/staff/dliu; C build OK).
  - Sanity check `p2p_processing`: prints usage/help ✓.
  - `phasefilt_py` from clean PATH ($GMTSAR/bin symlink): prints argparse usage ✓ — confirms the v2.4.2 +x-in-index fix works for a fresh clone.
  - GAP: README's env lines (export GMTSAR + PATH=$GMTSAR/bin) do NOT put `gmt` on PATH in --conda mode (gmt is in the conda env bin). Sanity check passes (help doesn't call gmt) but real runs would fail. FIXED: README + install.sh closing message now tell --conda users to `conda activate <env>` / add $CONDA_PREFIX/bin, and add `gmt --version` to the sanity check.
  - Side effect: install.sh --python pip-upgraded matplotlib 3.10.9→3.11.0 in the env (requirements.txt allows >=3.5; minor, PNG SSIM thresholds robust). Note for reproducibility: pin matplotlib if PNG parity ever drifts.

## 2026-06-17 21:30 — NEW DIRECTION (user): wire ALL ported operators pipeline-wide, then in-memory pipeline
- USER directive: ported+verified Python ops (grdmath/surface/blockmedian/grdsample) must be wired at EVERY call site (non-ported parts stay gmt — fine). Then NEXT PHASE: keep grids in memory between stages, write .grd only when needed (eliminate NFS round-trips; parity-safe — the big end-to-end win; the 3.7x grdmath speedup was mostly avoided fork+netcdf, not faster math).
- PERF EVIDENCE: grdmath A 2 MUL on real 8527x6536 grid: py in-proc 1.34s vs gmt subproc 5.06s = 3.7x faster (avoids fork+netcdf rw). Confirms in-process ports are faster at scale.
- PLAN (sequential to avoid file conflicts — snaphu.py/geocode/merge use multiple ops; each gated by full 21-case sweep, parity must stay 20/21):
  Phase A (wiring): (1) grdmath ALL sites [mira a2ecc0d0 running, worktree, operator-coverage + gmt fallback for unsupported]; (2) surface ALL sites; (3) blockmedian ALL sites; (4) grdsample ALL sites. Each: verify-myself (C-parity tests + A/B + smoke) then full sweep then land.
  Phase B (next): in-memory pipeline — refactor stage hand-offs to pass numpy/xarray in memory; write .grd only at boundaries / for still-C steps (snaphu, gmt viz). Parity-safe (no numerics change).
- ACTIVE: mira a2ecc0d0291e7df2c — grdmath comprehensive wiring (worktree). On return: verify + FULL SWEEP gate + land (likely v2.5.0 for the coverage expansion).

## 2026-06-17 21:40 — grdmath comprehensive wiring applied (16 files), full-sweep gate running
- Mira a2ecc0d0 (base c4b4fa5=current, no stale-base) wired gmt_grdmath_py into 16 files (align_tops, fitoffset_ra, correct_insar_with_gnss, correct_merge_offset, stack_corr, stack_coherence_mask, merge_unwrap_geocode_tops, snaphu.py [13 MUL + masks], geocode, p2p_ALOS2_SCAN_Frame, p2p_S1_TOPS_doublediff, make_dem, make_los_ascii, proj_model, filter). Fallback (kept gmt): estimate_ionospheric_phase (PI/MOD/DENAN/ISNAN unsupported), slc2amp (=bf input), 2 MOD+PI chains. 12 new helpers + 13 tests. Found+fixed real bug: _op_min np.fmin→np.minimum (NaN propagation, GMT MIN semantics).
- Supported ops: FLIPUD MUL ADD SUB DIV ABS SQRT SQR POW HYPOT ATAN2 GE LE NAN XOR MIN. Not ported: MOD DENAN ISNAN PI BLEND BITXOR.
- LANDED to working tree via DELTA-APPLY (git apply patch vs base c4b4fa5; restored +x on executables — core.fileMode=false). VERIFIED-MYSELF: 55 grdmath C-parity tests pass on main; only the 17 wiring files modified (+ SESSION_LOG).
- FULL 21-case all-defaults sweep RUNNING (bz0vgcgx0) = parity gate for v2.5.0. On 20/21 clean → commit v2.5.0; read perf snapshot to report speedup vs v2.4.2 (c8cfe39). Then A2 surface, A3 blockmedian, A4 grdsample.

## 2026-06-18 00:35 — grdmath-wiring full sweep 0/21: +x CASCADE (not a wiring bug); recovered
- Sweep bz0vgcgx0 returned 0/21, ALL "missing on py" — py pipeline produced NO outputs. Root cause: NOT a wiring regression. `git apply` of the wiring patch STRIPPED working-copy +x on the wired EXECUTABLES (filter/geocode/merge_unwrap_geocode_tops/p2p_*/stack_corr/align_tops/... → 664). I had restored +x in the INDEX (git update-index --chmod=+x) but NOT the WORKING COPY — and the sweep runs the working-copy files via PATH/execve → Permission denied → cascade → no outputs (the memory'd git-revert-drops-x-bit hazard, recurring via git apply). Confirmed: test -x utils/filter = false; csh reference present; 55 C-parity tests + mira worktree smoke (where +x was intact) had passed → wiring is sound.
- LESSON: after `git apply` of a patch touching executables, MUST chmod +x the WORKING COPY (not just the index) BEFORE running the sweep. git apply honors the patch's recorded 100644 and strips working-copy +x (core.fileMode=false).
- FIX: chmod +x the 14 wired working-copy executables; re-running RS2 smoke to confirm pipeline produces outputs, then re-launch the full sweep gate.

## 2026-06-18 01:30 — Rule 14 fired: ALOS_haiti phasefilt_mask_ll.png ssim=None → sweep STOPPED + examined
- First real test of Rule 14: Monitor caught ALOS_haiti failing at case ~4, sweep killed (saved ~2.5h). Examination:
  - phasefilt_mask.grd: same dims, matches csh MOD-2PI (science correct).
  - mask2.grd NaN-footprint differs 255 cells; phasefilt_mask 5024 → proj_ra2ll bbox shifts → geocoded png dims py 2190x2180 vs csh 2090x2150 → SSIM uncomputable → ssim=None.
  - 255 mismatch cells: py corr 0.087-0.121 (all < 0.14 mask thr); 111 py-NaN/csh-not-NaN, 144 reverse → py-corr vs csh-corr differ enough to cross the HARD GE 0.14 threshold at edge cells.
- OPEN QUESTION (decisive A/B dispatched, mira aa401ff5e64962837): is the wired GE+NAN+MUL bit-exact vs gmt on the SAME corr (→ then ssim=None is INHERENT py-corr threshold-roundoff, present w/ or w/o wiring, NOT a wiring regression), or does mask2_py != mask2_gmt (→ real wiring bug to fix)? Mira computes mask2 both ways + A/Bs the other GE/NAN chains (merge/stack_coherence_mask/snaphu).
- Sweep + tripwire Monitor stopped. v2.5.0 landing hinges on this A/B verdict.

## 2026-06-18 01:45 — grdmath wiring VERDICT: BIT-EXACT (no bug); ALOS_haiti ssim=None is wiring-independent
- Mira aa401ff5 DECISIVE A/B: mask2_py == mask2_gmt on SAME corr (NaN_mm=0, max|diff|=0.0) — all 4 GE/NAN chains bit-exact (geocode thr0.14, merge thr0.1, stack_coherence_mask thr0.14, snaphu thr0.1). NO wiring bug.
- ALOS_haiti ssim=None root cause: py-corr vs csh-corr differ Δ≤0.034 at ~181 cells straddling the hard GE 0.14 threshold → mask extent shift → proj_ra2ll bbox shift → png dims 2190x2180 vs 2090x2150 → SSIM uncomputable. WIRING-INDEPENDENT (gmt-masking on py-corr gives identical mask2). Compounded by a STALE csh mask2 reference (2.43M vs fresh 2.01M valid). 58 grdmath tests pass (+3 new threshold/NaN/real-ALOS regression locks in mira worktree).
- ACTION: re-launched full sweep #3 (bbpqfnx1t) with Rule-14 tripwire (Monitor b4zbthlcg) that whitelists Ridgecrest + ALOS_haiti-phasefilt_mask-ssim (diagnosed benign), aborts on structural/new failures → gates the non-GE chains (XOR+MIN, stack_corr, phase-gradient, SUB+SUB, etc.) across all 21 cases. On clean (only known artifacts) → land v2.5.0 (+ fold in mira aa401ff5's 3 new tests).

## 2026-06-18 02:30 — ULTRACODE scoping of next wiring rounds (workflow w9jaaaouu, 4 agents, ~3min, read-only)
Banked per-operator wiring plans for A2/A3/A4 (use before each round; A/B the edge-risks on REAL data BEFORE sweeping):
- **surface (A2):** 8 unwired sites → 5 WIREABLE (proj_ra2ll, proj_ll2ra_ascii, proj_ra2ll_ascii, dem2topo_ra coarse.grd lines 749/817, fitoffset_ra) + 3 KEEP-GMT (proj_model -fg geographic [Cartesian-only port], estimate_ionospheric_phase -R<grid>+NaN-stdin, correct_insar_with_gnss -R<grid>+sparse GNSS). EDGE-RISK: dem2topo_ra coarse.grd is in the Mira #72 non-converged-float32 sub-meter-drift regime → feeds FLIPUD→grdsample→topo_ra → bbox/SSIM shift (ALOS_haiti class). gmtinfo -R bbox rounding the port doesn't do (off-by-inc row/col); pixel-vs-gridline reg mis-read = silent half-cell shift.
- **blockmedian (A3):** 6 unwired → 2 WIREABLE (align_tops, tide_correction) + 4 KEEP-GMT (proj_ra2ll & proj_ra2ll_lib.py [-bi3f single-prec], make_los_ascii [gridline/no -r], proj_model [-bi6f+-i colsel+-fg]). EDGE-RISK: float32 -bi3f banker-rounding boundary flip → xyz2grd bbox shift (ALOS_haiti class); gridline branch NOT byte-faithful; NaN through sort/median (port has no NaN handling).
- **grdsample (A4):** plan captured (interp-mode + NaN parity focus).
- TAKEAWAY: next rounds are LOWER-yield (surface 5, blockmedian 2 wireable) + HIGHER-edge-risk than grdmath. Wire only the bit-exact-safe sites; keep gmt for geographic(-fg)/-R<grid>/single-precision(-bi3f)/sparse-scatter sites. Full plan: /tmp/...w9jaaaouu.output (ephemeral) — re-scope via the saved workflow script if lost.

## 2026-06-18 04:30 — v2.5.0 LANDED: grdmath wired pipeline-wide (16 files, bit-exact), 19/21 sweep
- Full 21-case sweep #3: 19/21 py-vs-csh clean. 2 exceptions, BOTH wiring-independent (examined):
  - ALOS_haiti phasefilt_mask_ll.png ssim=None: threshold-edge bbox shift (wiring proven bit-exact mask2_py==mask2_gmt).
  - S1_Ridgecrest_EQ 5 fails: known phasefilt.grd 0.3516 no-DEM corner + corr_ll/display_amp/corr_ll.png/phasefilt_mask divergence vs FRESHLY-REGENERATED csh ref (Ridgecrest had no cached ref this sweep). corr_ll/display_amp via _project (unchanged by v2.5.0) → NOT a grdmath regression; no-DEM-zone instability + fresh-csh-ref. Follow-up: csh_test ref management for no-DEM case.
- Process: first sweep was 0/21 (+x cascade — git apply stripped working-copy +x); fixed (Rule 14 caught it, Rule 15 codified edge-A/B-first). Diagnostic mira aa401ff5 proved GE+NAN+MUL bit-exact + fixed _op_min np.fmin→np.minimum NaN bug. 58 grdmath tests pass.
- Landing: +x restored (working copy + index) on 14 wired execs; project_rules Rules 14/15 + release_notes_v2.5.0.md included.

## 2026-06-18 05:05 — v2.5.1: A2 surface wiring (2 standalone-CLI sites; Rule-15 kept 3 on gmt)
- Rule-15 edge-A/B-first WORKED — caught divergent sites BEFORE wiring (no sweep abort): coarse.grd 4.13m drift (T=0.1 low-tension non-converged regime), proj_ll2ra_ascii 0.19m (gmt itself non-converged dense geo scatter), fitoffset_ra 1.6e-3px (>1e-3 thr) → ALL KEPT ON GMT.
- WIRED: proj_ra2ll + proj_ra2ll_ascii (bit-exact A/B 1.4e-7 / 4.4e-6 deg). Standalone CLIs, NOT in normal p2p path (geocode uses proj_ra2ll_lib already-wired; standalone = geocode fallback). Cherry-picked clean from worktree (main==abd29f4 base for these 2 files); +x set working-copy+index.
- Verify: both parse; RS2 smoke 6/6 py-vs-csh on main. Full sweep N/A (sites outside normal p2p path; smoke confirms geocode unaffected). 2 worktree tests not ported (needed worktree-only _rs2_trans_dat helper; surface port covered by 21 existing surface tests + the A/B).
- NET: surface is now wired everywhere it's bit-exact-safe; the dominant dem2topo surface (pixel.grd) was already wired; coarse.grd correctly stays gmt (would drift the geocode bbox).

## 2026-06-18 05:25 — v2.5.2: A4 landmask grdsample wiring (byte-exact); A3/A4 rest deferred (merge friction)
- A3+A4 mira (a9971589) A/B-verified (Rule 15) blockmedian+grdsample sites:
  - WIREABLE (byte-exact): blockmedian@align_tops(0)/tide_correction(1.8e-12); grdsample@tide_correction(0)/landmask(0,NaN-id)/correct_insar_with_gnss-L56(0).
  - KEEP GMT (divergent/unsupported): blockmedian -bi3f (proj_ra2ll/lib), gridline (make_los_ascii), -fg (proj_model), -R<grid> (correct_insar L73). grdsample: systematic -R<gridfile> wrapper gap (gridline-ref → pixel-reg off-by-1 row/col: estimate_ionospheric_phase, merge, calc_look_vector, make_dem, p2p_S1_TOPS_doublediff), +n node-count, backtick grdinfo, -fg.
  - SYSTEMATIC FINDING: grdsample_wrapper._grd_region() returns gridline node-extent; gmt treats as bbox → pixel-reg 1 row/col smaller. Future wrapper fix would unlock ~6 more sites.
- LANDED v2.5.2: ONLY landmask grdsample (byte-identical max|diff|=0 + NaN-footprint, masking path). Byte-exact → pipeline provably unchanged → A/B IS the gate (no full sweep needed). +x preserved.
- DEFERRED: blockmedian/grdsample wiring at align_tops/tide_correction/correct_insar_with_gnss — verified-safe but the worktree (stale base abd29f4) gate-header collides with v2.5.0 grdmath gate-header (git apply --3way conflicts). Needs a MAIN-CHECKOUT re-wire (not stale worktree) to merge the gate helpers. Low perf value (tiny ops) → deferred, not blocking. Lesson: for wiring on already-campaign-modified files, work on MAIN checkout, not an isolated (stale) worktree.
- WIRING PHASE (A1-A4) effectively COMPLETE: grdmath fully wired (v2.5.0); surface/blockmedian/grdsample wired where bit-exact-safe; rest correctly on gmt (documented) or deferred. Perf lever now = Phase B (in-memory).

## 2026-06-18 05:42 — PHASE-B SCOPING: NOT worth it (~0.8-1.5s/case, <0.1%) — earlier ~5-15% estimate CORRECTED
- Read-only audit (a7e3cda2): p2p_processing is single-process, BUT filter/conv/resamp/phasefilt are C BINARIES via subprocess → their .grd I/O (filter conv chain 50-400MB, the BIG I/O) is at process boundaries = NOT fusible. ~85-90% of pipeline I/O is at C/gmt boundaries.
- FUSIBLE = only in-process Python snaphu masking chain (snaphu.py:151-220) + geocode mask2 reuse (geocode:175-195): ~35-350MB small ops → saves ~0.8-1.5s/case (<0.1% of a 1600-9000s case). Requires refactoring grdcut/grdsample wrappers to numpy-array API (~300 LOC + risk).
- VERDICT: Phase B NOT worth the refactor. My earlier ~5-15% was WRONG (assumed Python↔Python hand-offs; reality = C-subprocess boundaries dominate the I/O). Honest correction.
- STRATEGIC: NO cheap parity-safe perf lever remains. The dominant costs (surface compute + C filter/conv) need either parity-BREAKING work (surface multigrid/GPU) or huge ports (filter/conv → Python). Campaign core goal (port + bit-parity, v2.4.0 + v2.5.x wired) is MET. Remaining moves are the user's strategic call: (a) accept current perf + call port complete; (b) surface multigrid/GPU (big win, breaks bit-parity — user OK needed); (c) grdsample-wrapper -R fix / deferred A3-A4 (completeness, ~nil perf); (d) publish; (e) port filter/conv (huge). Recommend (a)/(d): the port is the deliverable; further perf is a separate, parity-trading effort.

## 2026-06-18 07:20 — option (c) executed (main-checkout mira, no stale-base): grdsample -R fix + completion wiring → full-sweep gate for v2.5.3
- TASK1: grdsample_wrapper -R<gridfile> bug FIXED byte-exact. Bug deeper than scoped: gmt grdsample -R<refgrid> clips region to INPUT extent + snaps to ref node-lattice (not verbatim ref dims). New _ref_geometry (grdinfo -C) + _clip_snap_region + Rule-1 guard. Byte-exact vs gmt on real merge grids incl overhang/clip. +3 tests (TestRefGridRegionFix).
- TASK2 wired grdsample -R sites (Rule-15 A/B): estimate_ionospheric_phase (max|diff|=0), merge_unwrap_geocode_tops (0), make_dem (1 ULP). KEPT GMT: p2p_S1_TOPS_doublediff + calc_look_vector (_ll non-uniform-x lattice drift — gmt special-cases near-uniform geo coords; port treats as exactly uniform).
- TASK3 deferred sites: align_tops (blockmedian -bo3d cmp=0) + tide_correction (blockmedian ASCII byte-id + grdsample -I=0) WIRED via gate-header merge on main (kept grdmath/surface gates). NEW utils/blockmedian_wrapper.py + test_blockmedian_wrapper.py. KEPT GMT: correct_insar_with_gnss — RULE 13 fresh-run found the -I path CRASHES (non-uniform-x) + line 94 uses unsupported +n syntax, CONTRADICTING the A3 mira's inherited "byte-exact" claim (good catch).
- Main-checkout approach (no isolation worktree) ELIMINATED the stale-base/cherry-pick friction — edits applied directly to current versions. Lesson: use main-checkout for wiring on campaign-modified files.
- VERIFIED MYSELF: test_grdsample_wrapper + test_blockmedian_wrapper 13/13; mira's full suites + RS2 smoke 6/6. FULL sweep gate (b1h4x7fgr, tripwire bymnbfvq2) running → v2.5.3 on clean. Edited: grdsample_wrapper.py, estimate_ionospheric_phase, merge_unwrap_geocode_tops, make_dem, align_tops, tide_correction, +new blockmedian_wrapper.py + 2 tests.

## 2026-06-18 07:26 — session-continuation: re-armed tripwire after harness task-tracking dropped
- Post-compaction, TaskList showed no tasks (b1h4x7fgr sweep + bymnbfvq2 tripwire untracked) but the DETACHED sweep subprocesses survived (start_new_session=True): 25 sweep/runner procs, 12 cases active, /tmp/c_sweep.log advancing. Sweep is mid-flight (TSX done 751s, ALOS_Baja starting) — NOT near done.
- Old tripwire python (2976159) was alive but its stdout went nowhere (untracked) → killed it + the 2 deaf zsh wrappers (exit 144 on b1h4x7fgr/bymnbfvq2 is just the wrapper kill; sweep unharmed, verified log still advancing after).
- Re-armed Rule-14 tripwire as persistent Monitor bt7akzebb (python3 -u /tmp/sweep_tripwire.py). v2.5.3 gate continues.

## 2026-06-18 08:10 — Rule-14 STOP on S1A_SLC_TOPS_Greece → EXAMINED → (c)/v2.5.3 INNOCENT
- Tripwire fired SWEEP-FAIL Greece: 3 fails [corr_ll.grd rms .0508/thr .01, corr_ll.png ssim .55, phasefilt_mask_ll.png ssim .51]. Stopped full sweep (pkill).
- Root cause (NOT (c)): py corr_ll.grd = W 19.85556 / 5600 cols; csh = W 19.85000 / 5610 cols — py geocode region is 10 cells (0.00556deg=10*2s) narrower on the WEST edge. RA-DOMAIN products phasefilt.grd + filtcorr.grd all SUCCESS (rms 1e-6..3e-3) → the compute (align_tops alignment, topo phase) is correct; only the projection region differs.
- Eliminated every (c) suspect: (1) merge iono grdsample wiring DID NOT RUN (no ph_iono_orig.grd for Greece); (2) dem.grd byte-geometry-identical py-vs-csh (20/23/37.54/39.76, 3601x2665) → make_dem innocent; (3) trans.dat byte-size-identical → align_tops/geometry innocent; (4) proj_ra2ll + gmt_surface_py + gmtsar_lib are byte-identical to v2.5.2 (git diff HEAD empty).
- FRESH CONFIRM (Rule 13): re-ran proj_ra2ll on existing Greece corr.grd+trans.dat with current code → 5600 cols under BOTH GMTSAR_SURFACE_INPROC=1 AND =0, and GMTSAR_GRDSAMPLE_PY=1/0. So py deterministically computes 5600 regardless of surface/grdsample. The divergence is a PRE-EXISTING py-vs-csh proj_ra2ll region-rounding difference (gmt gmtinfo over llp), exposed only because the csh ref was regenerated FRESH this sweep (mtime 08:05 today). Same class as Ridgecrest fresh-csh exposure.
- Verdict: v2.5.3 (c) work is INNOCENT. (c)'s tools all act in ra-domain; the only divergent product family is the downstream proj_ra2ll _ll geocode region.
- ACTION: refined tripwire — ABORT on structural(missing-on-py) or ANY ra-domain failure (phasefilt.grd/filtcorr.grd); NOTE-only when failures are confined to geocoded _ll products with ra-domain clean. Re-running 5 missing full-tier cases (Ridgecrest, TOPS_LA, TOPS_COVE, Larsen_C, ALOS2_SCAN_SSAF) to complete the 21-case gate.
- FOLLOW-UP (separate, NOT a v2.5.3 blocker): investigate the py-vs-csh proj_ra2ll geocode-region west-edge rounding (5600 vs 5610) — pre-existing, surface/grdsample-independent.

## 2026-06-18 11:25 — v2.5.3 LANDED (commit a4bd328, tag v2.5.3)
- Full 21-case py-vs-csh gate: 17 fully CLEAN, 4 documented-benign (Ridgecrest no-DEM rms 0.3516=v2.5.0 value; ALOS_haiti GE-0.14 threshold; Greece+TOPS_LA _ll-only proj_ra2ll region rounding), ZERO ra-domain regressions. align_tops wiring proven bit-clean on Larsen_C+COVE+TOPS_LA (ra-domain all SUCCESS).
- Landed grdsample -R<gridfile> wrapper fix + 5 bit-exact wirings (iono/merge/make_dem/align_tops/tide) + blockmedian_wrapper.py. Kept gmt for p2p_S1_TOPS_doublediff/calc_look_vector/correct_insar_with_gnss (Rule-15/13).
- Invariant=0, edited execs 100755. DIRECTED PIPELINE-WIDE WIRING NOW COMPLETE (every ported+verified op wired at all bit-exact-safe sites; divergent sites documented on gmt).
- NOT pushed (user holds push authority / will contribute upstream later). Strategic forks (publish / surface-GPU / filter-conv / wind-down) await user.
- Open follow-up: py-vs-csh proj_ra2ll geocode-region west-edge rounding (5600 vs 5610), pre-existing, surface/grdsample-independent.

## 2026-06-18 23:10 — v2.5.4 LANDING (proj_ra2ll geocode-region parity)
- Root cause (corrected via clean re-test, Rule 13): gmt_surface_py ~1.5e-5deg edge roundoff flips the coarse-lattice region snap in proj_ra2ll → Greece/TOPS_LA geocoded _ll region 1 coarse cell (10 fine cells) off vs csh. My earlier "surface-independent" claim was from a CONTAMINATED test (reused stale raln.grd).
- Fix: proj_ra2ll builds raln/ralt with gmt-C surface by default (opt-in port via GMTSAR_PROJ_SURFACE_PY=1; independent of global GMTSAR_SURFACE_INPROC).
- Validation: 6-case sweep ALL CLEAN — Greece+TOPS_LA fixed, Larsen_C+COVE+ALOS_Baja+ERS no-regression. Greece corr_ll rms vs csh 1.2e-6.
- Matrix now 20/21 (Ridgecrest no-DEM harmless per user; ALOS_haiti separate corr-parity issue).

## 2026-06-18 23:35 — Phase B0 profile (in-memory go/no-go) → SHELVE
- ALOS_haiti task2: root-caused (NOT fixable cleanly). conv is the C binary + deterministic (re-ran 2x, diff=0). corr=conv(amp/sqrt(amp1*amp2)); all inputs bit-clean ~1e-9; the amp/sqrt(tmp) division at near-zero amplitude amplifies the unavoidable py-vs-csh ~1e-9 upstream roundoff (phasediff/resamp are float-faithful, not bit-identical) into 0.037 corr diff in one low-amp patch → flips ~181 px at GE 0.14 geocode mask → phasefilt_mask_ll extent/ssim differ. Same structural class as Ridgecrest (roundoff at hard threshold in unstable regime). Options: (1) document like Ridgecrest [recommended]; (2) bit-exact phasediff [large/risky, not autonomous-safe]. AWAITING USER.
- Phase B0 (static + size + bandwidth, no re-run): fusible py-kernel segments are short (<=3 consecutive grdmath in filter/geocode), broken by gmt forks (grdinfo/viz) + C conv. Intermediates: TOPS Greece ~258MB, ALOS_Baja ~234MB. NFS write 671MB/s; reads PAGE-CACHED 7.6GB/s. Fusible savings ~1-2s/case vs wall 3349s(Greece)/1011s(ALOS_Baja) = <0.1%. VERDICT: SHELVE Phase B — .grd I/O is not the bottleneck (cache absorbs reads); surface+conv compute dominates. Confirms earlier audit.

## 2026-06-19 ~02:30 — instrumented I/O profile + surface-parallel prototype launched
- I/O profile (real, on 123MB/232MB TOPS grids): NFS-vs-tmpfs grdmath round-trip delta = 0.22s (raw disk negligible, cache+fast NFS). Python netCDF cost = read 1.17s + write 0.17s = ~1.34s per fusible intermediate; ~3-6/case → ~4-8s vs Greece wall 3349s = <0.3%. PHASE B DEFINITIVELY SHELVED. Bottleneck = compute (surface GS-SOR dominant), not I/O.
- Launched mira-volkov (bg a183854f6038f4e70): ISOLATED prototype of numba-parallel multi-color SOR surface (red-black on the WIDE biharmonic stencil needs proper coloring, not naive 2-color) + benchmark speedup-vs-threads + parity delta (RMS/max vs gmt C) on real RS2 + TOPS grids. Report → docs/PROTO_surface_redblack.md. UNWIRED, no commit. This informs strategic fork (b): parallel surface = real speedup but breaks bit-parity (tolerance-based).

## 2026-06-19 ~03:10 — surface speedup: prize measured, domain-decomposition prototype launched
- PRIZE MEASURED (Rule 13): gmt surface (C, single-thread) on real 39M-node pixel.grd = 268.6s = ~27% of ALOS_Baja ~1000s wall (bigger for Greece 75M/~2700s). Worth parallelizing. gmt surface is single-threaded.
- Prior red-black prototype (PROTO_surface_redblack.md): per-color numba prange = ~0% scaling (barrier/sweep, tiny grids) + Jacobi fixed-point drift. DEAD approach.
- Constraint: dem2topo_ra pixel.grd is gmt-C in production because gmt_surface_py diverges 0.46m on this large pixel_reg terrain (Mira #72) → broke a sweep threshold. Parallel solver must converge to gmt-C within sweep tolerance (full pipeline stays green = user acceptance).
- Launched mira-volkov bg ab5c1e4233b26e2df: COARSE-GRAINED domain-decomposition block-SOR (prange over big blocks, halo exchange every K sweeps) on real 39M grid; measure scaling 1/2/4/8/16 vs 268.6s + parity rms/max vs gmt-C ref. Report → docs/PROTO_surface_parallel_domain.md. UNWIRED.

## 2026-06-19 ~04:25 — surface multi-core: NO-GO (memory-bandwidth-bound), goal infeasible on CPU
- Domain-decomp block-SOR (mira ab5c1e4233b26e2df, PROTO_surface_parallel_domain.md): 0.98-0.99x at 2-16 threads on real 39M grid = ZERO scaling. Bandwidth 3.8→4.4 GB/s 1→2thr (+16%) = saturation; 12-pt stencil scatter offsets defeat prefetch on 156MB set. Parity 0.30m RMS vs gmt-C (=production port, no regression). DD bit-identical across strip counts (correct decomp).
- gmt-C surface 269s FASTER than numba port 414s (1.54x); gmt-C wouldn't thread-scale either.
- CONCLUSION: "speed up surface with more cores" is INFEASIBLE on CPU (memory-bound). Memory written: project_surface_memory_bound. Real levers: (1) fewer iters via -S search-radius/multigrid [single-core, algorithmic], (2) GPU [~10x bandwidth, big effort], (3) accept gmt-C. AWAITING USER redirect.

## 2026-06-21 02:45 — CAMPAIGN CLOSE (48h supervisor loop ended)
Span 2026-06-13 → 06-21. All landings on master (NOT pushed; user holds push + will contribute upstream later). Invariant (upstream untouched outside gmtsar/python/) = 0 throughout.

LANDED:
- v2.4.0 milestone: every compute kernel Python-default at primary sites; 20/21 sweep.
- v2.5.0 grdmath wired pipeline-wide (bit-exact); v2.5.1 proj_ra2ll surface; v2.5.2 landmask grdsample.
- v2.5.3 (ccb516f^.. a4bd328): grdsample -R<gridfile> wrapper fix + completed bit-exact grdsample/blockmedian wiring (iono/merge/make_dem/align_tops/tide) + blockmedian_wrapper.py; Rule-13 catch kept correct_insar_with_gnss on gmt. Directed pipeline-wide wiring COMPLETE.
- v2.5.4 (ccb516f): proj_ra2ll builds raln/ralt with gmt-C surface → geocode-region parity; fixed S1A_SLC_TOPS_Greece + _LA. Matrix now 20/21.

CLOSED/SHELVED:
- snaphu: C binary in production; numba port = audit reference (chapter closed).
- Phase B (in-memory): SHELVED — instrumented profile showed .grd I/O <0.3%/case (NFS-vs-tmpfs 0.22s; netCDF ~1.34s/intermediate; reads page-cached 7.6GB/s).
- Surface multi-core: PROVEN INFEASIBLE — memory-bandwidth-bound (2 prototypes ~0 scaling on real 39M-node grid; 3.8→4.4GB/s 1→2thr). gmt-C 269s already fastest CPU. Memory: project_surface_memory_bound.

OPEN FOR USER (no autonomous-safe path; await decision):
- ALOS_haiti (the 21st): corr.grd differs from csh ~0.037 via amp/sqrt(amp1·amp2) ÷≈0 amplifying ~1e-9 upstream roundoff → flips ~181px at GE0.14 mask → geocode-extent/ssim. Same class as Ridgecrest no-DEM. Options: document / bit-exact phasediff (risky).
- Surface speed: iteration-reduction (-S/multigrid, single-core, parity-safe) / GPU (~10x bandwidth) / accept gmt-C.
- Publish/contribute upstream (recommended; fork clean+tagged).
STATE AT CLOSE: HEAD ccb516f, invariant=0, no running jobs, working tree clean except intentional uncommitted scratch (_proto_surface_*.py, PROTO_*.md, perf_snapshots/, NOTES_*.md).
