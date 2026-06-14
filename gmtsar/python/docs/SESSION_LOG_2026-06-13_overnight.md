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
- gmt surface fix (Mira #72): in progress.
- snaphu port: scoped (I/O done, solver stubbed). USER DECISION: pure-Python ~3-4wk (statistical
  parity only on solver) vs `pip install snaphu` CFFI ~1day (exact, keeps C dep). Worktree preserved.
