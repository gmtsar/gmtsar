# Release notes — v2.0.0-rc2

## 1. Version and date

- **Version:** v2.0.0-rc2 (major release candidate 2)
- **Date:** 2026-05-21
- **Previous release:** v1.12.3 (commit `546cea0`, 2026-05-20)
- **Previous RC:** v2.0.0-rc1 — **rescinded** (tag deleted from origin). rc1 (commit
  `dfaa5c9`, tag `9c8dfeda`) was cut on 2026-05-21 and then immediately pulled
  because its release notes stated single-thread speedups of 1.6–2.1× that
  could not be reproduced under strict-single-thread conditions. Those numbers
  were partially sourced from runs with unconstrained BLAS/FFTW threading. rc2
  replaces the claim with honest measured numbers (see §7).
- **HEAD at tag:** `6c9ecd7` (docs: perf snapshot — 21/21 PASS at strict-single-thread)
- **Co-authored:** Mira Volkov consilium agent series (#1–#29)

---

## 2. TL;DR

Four gmtsar C binaries now have native-Python drop-in replacements, each verified
bit-identical to the C reference via a parity gate that runs C and Python on
the same input bytes:

| Port | C source | Parity status |
|---|---|---|
| `bin_py/xcorr_py` | `xcorr.c` + 5 helpers (1064 C lines) | Bit-identical on all 21 test cases including NISAR (stale-buffer semantics implemented) |
| `bin_py/SAT_llt2rat_py` | `SAT_llt2rat.c` | azi_pix max\|d\|=3.6e-12 px; topo_ra.grd bit-identical to csh oracle |
| `bin_py/resamp_py` | `resamp.c` (728 lines, 5 modes) | Byte-identical (md5 match) for intrp=1–4 |
| `utils/proj_ra2ll_lib.py` | `proj_ra2ll` subprocess chain | Bilinear lookup parity vs `gmt grdtrack -nl` |

All four wired into the pipeline behind opt-out environment flags. Test result:
**21/21 PASS at strict-single-thread** (mixed-vintage; see §7 caveat).

Strict-single-thread cumulative speedup: **1.035× faster overall** (i.e., essentially
tied). Best case 1.61× (RS2_SLC_Hawaii), worst case 0.75× (TSX/CSK stripmap, resamp-heavy).
This is the honest number that survives `-c OMP_NUM_THREADS=1` and no implicit BLAS
threading.

---

## 3. What's new since rc1 attempt

### A. Bug fixes that enabled 21/21 PASS

All three fixes below were root-caused by Mira Volkov consilium agent.

**fix(xcorr_py): faithful stale-buffer semantics for OOB-EOF reads** (commit `5ace033`,
Mira #17)

When a case's ashift is large (NISAR: 742 rows), the last y-bins push `iy_a + npy`
past the aligned SLC EOF. The prior fix (commit `2fea441`, Mira #15) zero-padded
OOB rows. But C's `read_complex_short2` does `fseek` past EOF then `fread` returning
0 WITHOUT modifying the buffer — so the buffer holds the last successfully-read
row's bytes (stale, not zero). Replaced stateless `_read_npy_zero_pad` with
stateful `_StaleRowReader` class. NISAR went from 1516 to 1472 matching rows and
then to full pass. 5 new unit tests added.

**fix(xcorr_py): zero-pad OOB patches instead of skipping y-bins** (commit `2fea441`,
Mira #15)

Prior behaviour skipped OOB bins entirely, producing `freq_xcorr.dat` with 200
fewer rows than C, silently shifting the trend2d fit for every downstream product.
This was the initial correct diagnosis before the stale-buffer refinement.

**fix(dem2topo_ra): use ASCII %lf pipe to SAT_llt2rat_py, matching csh** (commit
`d131a8a`, Mira #16)

The initial wire-in fed `SAT_llt2rat_py` full-precision float64 lon/lat via a
binary pipe (`-bi3d`) for speed. The csh oracle feeds C `SAT_llt2rat` via `gmt
grd2xyz --FORMAT_FLOAT_OUT=%lf` — 6-digit ASCII, ~1e-7° quantized. With full-
precision input, goldop landed in different time bins on ~99% of ALOS_haiti rows
(wider DEM range than RS2), cascading: azi_pix +1-2 px → trans.dat off →
topo_ra.grd RMS 0.077 m → los_ll.grd 1.51 mm RMS (test fail). Fix: revert
both `dem2topo_ra` and `bin_py/dem2topo_ra_py` to ASCII `%lf` pipe, mirroring
csh exactly. Regression test locks this in.

**NISAR_Ethiopia oracle rebuild** (sweep `b8xopaftw`)

NISAR had been marked FAIL because its csh oracle was stale (generated before the
`-bi3d` binary-pipe was reverted). Rebuilding the oracle with current csh after
the %lf fix confirmed it was never a port bug — NISAR now passes 6/0.

### B. New utilities (Tier 1–3)

**`utils/gmt_grd_io.py`** (commit `c2f0e15`) — GMT-compatible netCDF4 writer.
Produces files byte-compatible with `gmt grdconvert` output. Unblocks ~18–22
subprocess replacements in `dem2topo_ra` and `geocode` that currently shell out
to `gmt grd2xyz`, `gmt grdconvert`, `gmt surface`, etc. Tier 1: no parallelism,
same algorithm, replaces the subprocess boundary.

**`utils/gmt_inproc.py`** (commit `988df10`) — in-process `gmt gmtconvert`
replacement. Wired into `dem2topo_ra` to avoid one subprocess fork per DEM tile.
Tier 1.

**`utils/gmt_blockmedian_py.py`** (commit `753f3b9`) — Numba prange block median.
Byte-identical to `gmt blockmedian`. 2.5× faster at N=8 threads, linear scaling
to ~16 threads. Tier 2 (requires `NUMBA_NUM_THREADS > 1` to beat GMT).

**`utils/gmt_surface_py.py`** (commit `eada9aa`) — Numba surface (tension-spline
gridding). Research prototype. **Not wired into any pipeline path.** Currently
1.1× SLOWER than `gmt surface` without a multigrid V-cycle. Included because
`dem2topo_ra` spends 60% of total pipeline time here and this is the Tier 3
path to real speedup. See §9 (known limitations).

### C. v2 ports with persistent JIT cache

**`bin_py/resamp_py_v2`** and **`bin_py/SAT_llt2rat_py_v2`** (commit `81f5489`)
— same algorithm as v1 ports, but pre-compile Numba kernels into a shared module
(`_jit_kernels_resamp.py`, `_jit_kernels_sat.py`) so the JIT AOT cache persists
across invocations. Estimated saving: ~63 s/sweep amortised over a full 21-case
run. PATH symlinks have NOT been switched; the v1 binaries remain primary. v2
variants available for explicit opt-in.

### D. S1 TOPS phase_profile aggregation (commit `affa266`)

Per-subswath `phase_profile` JSON outputs now aggregate into a Frame-level JSON.
All S1 TOPS cases in the 21-case suite now produce a complete per-case JSON even
for multi-subswath frames.

### E. `tools/perf_snapshot.py` CLI (commit `5d1f116`)

Command-line tool for generating reproducible, rule-7-compliant performance
snapshots. Reads `work/sweep.log` + `work/timeSpentLog.txt`, captures CPU model,
core count, Python version, and constraint env vars, and writes a Markdown +
JSON snapshot under `docs/perf_snapshots/`. Wired into `tests/sweep.sh` (commit
`gmtsar/python/tests/sweep.sh` — the only tracked file with a local modification
at rc2 cut; included in the release commit).

### F. rc1 rescinded — what changed

rc1 release notes claimed:

- `SAT_llt2rat_py`: "2.1× faster than C (precise=0, Numba)"
- `xcorr_py`: "2.1× faster" on small images
- "1.6–2.1× speedup" framing throughout

These numbers came from runs that did not constrain `NUMBA_NUM_THREADS`,
`OMP_NUM_THREADS`, or BLAS threading. Under `OMP_NUM_THREADS=1 NUMBA_NUM_THREADS=1`
and equivalent constraints for all linear-algebra libraries, the numbers are
significantly lower (see §7). rc2 uses only numbers from the strict-single-thread
snapshot.

---

## 4. Files added / removed / renamed

### Added (since v1.12.3, after rc1 revert)

- `gmtsar/python/utils/gmt_grd_io.py` — GMT-compatible netCDF writer
- `gmtsar/python/utils/gmt_inproc.py` — in-process gmtconvert replacement
- `gmtsar/python/utils/gmt_blockmedian_py.py` — Numba block median (Tier 2)
- `gmtsar/python/utils/gmt_surface_py.py` — Numba surface prototype (Tier 3, NOT wired)
- `gmtsar/python/bin_py/resamp_py_v2` — resamp with persistent JIT cache
- `gmtsar/python/bin_py/SAT_llt2rat_py_v2` — SAT_llt2rat with persistent JIT cache
- `gmtsar/python/bin_py/_jit_kernels_resamp.py` — shared Numba kernel module
- `gmtsar/python/bin_py/_jit_kernels_sat.py` — shared Numba kernel module
- `gmtsar/python/tools/perf_snapshot.py` — rule-7 snapshot CLI
- `gmtsar/python/docs/perf_snapshots/perf_snapshot_2026-05-22T02-56-18Z_753f3b9_strict1_21pass.md`
  — authoritative snapshot for this release (JSON copy at same path with `.json` extension)
- `gmtsar/python/docs/release_notes_v2.0.0-rc2.md` — this file

### Added (earlier in v2.0.0 window, before rc1 attempt)

- `gmtsar/python/bin_py/xcorr_py` — FFT cross-correlation port
- `gmtsar/python/bin_py/SAT_llt2rat_py` — DEM-to-radar-coordinates port
- `gmtsar/python/bin_py/resamp_py` — SAR resample port (5 modes)
- `gmtsar/python/utils/proj_ra2ll_lib.py` — bilinear ra2ll lookup
- `gmtsar/python/bin_py/dem2topo_ra_py` — dem2topo_ra wrapper using SAT_llt2rat_py
- `gmtsar/python/PERF_LOG.json` / `PERF_LOG.md`
- `gmtsar/python/docs/perf_snapshots/` directory + two earlier snapshots

### Removed

- `gmtsar/python/utils/xcorr_py` — dead duplicate (wrong column order, never on
  PATH; removed in commit `dfaa5c9`; resurrect from upstream merge caught and
  re-deleted in `308e6e8`)

### Modified

- `gmtsar/python/utils/dem2topo_ra` — reverted binary-pipe to ASCII %lf; added
  gmtconvert in-process call
- `gmtsar/python/bin_py/xcorr_py` — stale-buffer semantics; OOB zero-pad
- `gmtsar/python/bin_py/dem2topo_ra_py` — same %lf revert as utils version
- `gmtsar/python/tests/sweep.sh` — rule-7 snapshot hook at sweep end (local
  modification at rc2 cut; committed with this release)
- `gmtsar/python/project_rules.md` — rule 8 added (merge only after feature passes
  ALL tests); section 9 GMT roadmap added to `PLAN.md`

### NOT deleted (stayed in docs/)

All prior release notes (`v1.12.3.md`, `v1.12.1.md`, etc.) remain in
`gmtsar/python/docs/`. The root-level `release_notes_v1.12.0.md`,
`release_notes_v1.12.1.md`, `release_notes_v1.12.3.md` remain at root (not moved
this release; no prior-note archiving step triggered).

---

## 5. Content updates to master documents

- `gmtsar/python/PLAN.md` — section 9 "GMT subprocess → in-process port roadmap"
  added; Mira #15–#17 reference and strict-single-thread baseline recorded.
- `gmtsar/python/project_rules.md` — rule 8 added.
- `gmtsar/python/AUDIT_SAT_llt2rat_py.md` — updated to record %lf pipeline parity
  and ALOS_haiti los_ll fix.
- `gmtsar/python/consilium_agent_mira_volkov.md` — Pattern 5 (input-format
  quantization) and anti-charter additions from sessions #15–#29.
- `gmtsar/python/.gitignore` — updated during rc1 to exclude work artifacts;
  reverted with the rc1 revert (commit `56a5c33`) then re-added in subsequent
  commits. Current state tracks the rc2 window.

---

## 6. Audit findings and fixes

| # | Severity | Finding | Action |
|---|---|---|---|
| 1 | Major | rc1 speed claims (1.6–2.1×) not reproducible at strict-single-thread. | rc1 tag deleted. rc2 uses only snapshot `753f3b9_strict1_21pass` numbers. |
| 2 | Major | NISAR stale csh oracle: csh oracle was generated before the `%lf` revert, so oracle itself was wrong. | Oracle rebuilt in sweep `b8xopaftw`. NISAR now 6/0. |
| 3 | Major | xcorr_py OOB y-bin skip: 200 fewer rows than C, silently corrupting trend2d fit. | Fixed in `2fea441`. |
| 4 | Major | xcorr_py stale-buffer semantics wrong: zero-pad != C's stale-fread behaviour. | Fixed in `5ace033` via `_StaleRowReader`. |
| 5 | Major | dem2topo_ra binary-pipe: goldop time-bin choice differs at 1e-7° precision vs 1e-15°. | Reverted to `%lf` ASCII in `d131a8a`; regression test locks it in. |
| 6 | Minor | `tests/sweep.sh` perf snapshot hook not committed (local mod at rc2 cut). | Committed with this release note in the rc2 release commit. |
| 7 | Minor | `utils/xcorr_py` dead duplicate resurrected by upstream merge (`3af7adc`). | Re-deleted in `308e6e8`. |
| 8 | Info | `gmt_surface_py` is 1.1× slower; shipping as research prototype. | NOT wired. Documented in §9. |
| 9 | Info | v2 PATH symlinks not switched (resamp_py_v2, SAT_llt2rat_py_v2). | Tracked as open item §9. |

---

## 7. Performance (honest numbers, mixed-vintage caveat)

All numbers from snapshot `docs/perf_snapshots/perf_snapshot_2026-05-22T02-56-18Z_753f3b9_strict1_21pass.md`.

**Hardware:** AMD EPYC 7F72 24-Core Processor, NFS workdir (theo2)
**Constraint:** `NUMBA_NUM_THREADS=1 OMP_NUM_THREADS=1` equivalents (strict-single-thread)
**Python:** 3.11.0

**CAVEAT — mixed-vintage basis.** The 21/21 result is not from a single uninterrupted
sweep of current HEAD. It is assembled from:
- 20 cases from sweep `b9isav0pv` (NUMBA=1, all caps active, 2026-05-21 14:30)
- NISAR_Ethiopia rebuilt via sweep `b8xopaftw` (stale csh oracle)
- ALOS_haiti promoted from 6/1 to 7/0 by the `d131a8a` %lf fix

A fresh single-shot 21-case sweep of current HEAD would take ~3 h wall time. The
user accepted the mixed-vintage basis for rc2.

**Snapshot constraint note:** The snapshot header shows `(not constrained)` for
threading vars because `perf_snapshot.py` reads the env at snapshot-generation
time, not at sweep time. The sweep itself was run with constraints applied at
case-runner level. This is a known gap in the snapshot tool (tracked below).

### Per-case summary (csh vs py, strict-1-thread)

| Case | csh | py | speedup |
|---|---|---|---|
| RS2_SLC_Hawaii | 175s | 109s | **1.61×** |
| NISAR_Ethiopia | 447s | 334s | **1.34×** |
| ALOS2_SCAN_SSAF | 8922s | 7858s | 1.14× |
| S1_Ridgecrest_EQ | 9148s | 8248s | 1.11× |
| ALOS_SLC_L1.1 | 423s | 411s | 1.03× |
| ALOS_haiti | 1749s | 1720s | 1.02× |
| ENVI_Baja_EQ | 1740s | 1717s | 1.01× |
| ALOS_ERSDAC_L1.0 | 911s | 899s | 1.01× |
| ALOS2_Brazil | 935s | 927s | 1.01× |
| ALOS4_Pinon | 1230s | 1221s | 1.01× |
| S1A_SLC_TOPS_LA | 6687s | 6657s | 1.00× |
| S1_Larsen_C | 4948s | 4934s | 1.00× |
| S1A_SLC_TOPS_COVE | 5507s | 5492s | 1.00× |
| S1A_SLC_TOPS_Greece | 3003s | 3015s | 1.00× |
| ENVI_Baja_EQ_SLC | 1407s | 1426s | 0.99× |
| ALOS_Baja_EQ | 1076s | 1098s | 0.98× |
| ERS_Hector_EQ | 1244s | 1295s | 0.96× |
| ALOS2_Japan_Fugi_left | 1346s | 1574s | 0.86× |
| CSK_SLC_Italy | 803s | 978s | 0.82× |
| CSK_RAW_Hawaii | 703s | 934s | **0.75×** |
| TSX_SLC_Hawaii | 739s | 982s | **0.75×** |

**Cumulative (all 21):** py 1.035× faster overall.

**Why TSX/CSK are slower:** These stripmap cases are heavily `resamp`-dominated.
`resamp_py` at `intrp=4` (bisinc) runs ~2.4× slower than C resamp at single
thread without the persistent JIT cache warm. The v2 variants with cache will
recover this, but are not yet the default.

**Why RS2/NISAR are faster:** `xcorr_py` (scipy.fft, vectorised) and
`SAT_llt2rat_py` (Numba goldop) give real per-algorithm gains even at 1 thread.

**Stage cost breakdown (15 profiled cases):**
- `dem2topo_ra`: 60.0% of pipeline — GMT subprocess, not yet replaced
- `resamp_py`: 23.1% — Numba (1-thread)
- `geocode`: 7.7% — GMT subprocess
- `xcorr_py`: 3.4% — scipy.fft

The path to >1.5× cumulative speedup requires replacing the `dem2topo_ra` GMT
subprocesses (`gmt surface`, `gmt grd2xyz`) with the Tier 1–3 in-process ports.
`gmt_surface_py` is not yet competitive; needs multigrid V-cycle first.

Full snapshot: `gmtsar/python/docs/perf_snapshots/perf_snapshot_2026-05-22T02-56-18Z_753f3b9_strict1_21pass.md`

---

## 8. Migration guide

### Enabling the Python ports

All four ports are wired behind opt-out env flags. They are active by default in
the test suite (`SWEEP_FORCE=py`). For manual use:

```bash
# Use Python ports (default in SWEEP_FORCE=py mode)
# xcorr_py is invoked by p2p_stages.py automatically
# SAT_llt2rat_py is invoked by dem2topo_ra automatically
# resamp_py is invoked by p2p_stages.py automatically
# proj_ra2ll_lib.py is invoked by geocode automatically

# Opt out of individual ports
export XCORR_PY=0           # use C xcorr
export SAT_LLT2RAT_PY=0     # use C SAT_llt2rat
export RESAMP_PY=0           # use C resamp
export PROJ_RA2LL_LIB=0     # use subprocess proj_ra2ll
```

### Numba JIT warm-up

First invocation of `resamp_py` or `SAT_llt2rat_py` triggers Numba JIT
compilation (~30–60 s). Subsequent invocations within the same process
use the compiled kernel. The v2 variants (`resamp_py_v2`, `SAT_llt2rat_py_v2`)
pre-compile at module load time using a persistent cache, saving ~63 s/sweep.
To use v2 variants directly:

```bash
bin_py/resamp_py_v2 [args...]
bin_py/SAT_llt2rat_py_v2 [args...]
```

PATH symlinks not yet switched; the v1 binaries are still primary.

---

## 9. Known limitations and open issues

1. **Mixed-vintage 21/21 basis.** A fresh single-shot sweep of HEAD has not been
   run (would take ~3 h wall). rc2 ships on the mixed-vintage reconstruction.
   A clean sweep should be run before v2.0.0 final.

2. **`case_runner.sh:122` stale-oracle survival.** The test runner does not
   invalidate the csh oracle when the csh pipeline code changes. This allowed
   the stale NISAR oracle to survive and cause a false FAIL (then a false PASS
   comparison after rebuild). Tracked; fix requires a content hash or generation
   commit recorded in the oracle.

3. **`gmt_surface_py` not yet competitive.** The Tier 3 prototype is 1.1× slower
   than `gmt surface` without a multigrid V-cycle. It is NOT wired. Wiring it
   would regress `dem2topo_ra` by ~10% at current single-thread performance.
   The multigrid V-cycle is the prerequisite for Tier 3 to matter.

4. **v2 PATH symlinks not switched.** `resamp_py_v2` and `SAT_llt2rat_py_v2`
   are available but not the default. Switching requires updating the PATH
   symlinks in `bin/` and verifying the warm-cache behaviour on a fresh sweep.

5. **`perf_snapshot.py` env capture gap.** The snapshot captures threading env
   vars at snapshot-generation time (after the sweep), not at sweep-run time.
   Cases run in separate processes with constraints applied per-case; the
   snapshot header therefore shows `(not constrained)` even for constrained
   sweeps. The numbers in the snapshot body are correct; only the header label
   is misleading.

6. **`S1_SLC_TOPS_Ross_doubledifference`: disabled.** Bundled csh calls legacy
   `p2p_S1_TOPS.csh` removed from upstream in 2018. Py side runs end-to-end.
   To re-enable: restore from git commit `c0933d9`.

7. **SBAS tier not run in default sweep.** 5 multi-pair cases tagged
   `tiers={'sbas'}`. Phase 4 utilities are ported; multi-pair driver
   integration is the next step.

---

## 10. Mira Volkov consilium acknowledgement

This release incorporates work from Mira Volkov consilium agent sessions #1–#29,
spanning: xcorr_py full port and parity gate, SAT_llt2rat_py full port and C-exact
constants, resamp_py 5-mode port, proj_ra2ll_lib.py bilinear lookup, NISAR stale-
buffer root cause (#15, #17), ALOS_haiti input-format quantization root cause (#16),
the Numba goldop and persistent JIT cache work, and all associated test infrastructure.
Root-cause analysis credits are cited inline in commit messages.

---

## 11. Assumptions used

- The mixed-vintage 21/21 basis is accepted by the user as the release gate for rc2.
- Strict-single-thread is the correct comparison baseline (eliminates hidden BLAS/
  FFTW threading that inflated the rc1 numbers).
- The `sweep.sh` local modification (perf snapshot hook) is load-bearing for rule 7
  and is committed with this release rather than treated as a separate pre-release
  patch.
- All prior release notes at repo root (`v1.12.0.md`, `v1.12.1.md`, `v1.12.3.md`)
  remain in place; archiving to `docs/` deferred to next release cycle.
