# Session log — night of 2026-05-21 → 2026-05-22 (autonomous Mira run)

User went to sleep ~22:35 CDT with instructions: "charge ahead for 24h
following plan + test gates; add new features in".

## Major work landed

| Time | Commit | Description |
|---|---|---|
| 23:46 | `de62e6d` | feat: port SAT_baseline to Python — byte-identical to C on 5 datasets (Mira #29) |
| 23:50 | `5a6058c` | wire-in: SAT_baseline_py replaces C SAT_baseline on py side |
| 00:00 | `c698262` | rules: rule 9 — py side MUST NOT modify the csh oracle |
| 00:08 | `affa266` | feat(s1tops): aggregate per-subswath phase_profile into Frame-level JSON (Mira #21) |
| 00:12 | `988df10` | feat(tier1): in-process gmt gmtconvert replacement (Mira #19) |
| 00:18 | `eada9aa` | feat(tier3): gmt surface in Numba — research prototype NOT wired (Mira #20) |
| 00:25 | `81f5489` | feat(numba): v2 resamp_py / SAT_llt2rat_py with persistent JIT cache (Mira #22) |
| 00:30 | `5d1f116` | feat(tools): perf_snapshot.py CLI for rule-7 snapshots (Mira #24) |
| 00:35 | `c2f0e15` | feat(tier1): gmt-compatible netCDF writer unblocks 18-22 subprocess kills (Mira #23) |
| 00:40 | `753f3b9` | feat(tier2): gmt blockmedian in numba prange — byte-identical, 2.5x at N=8 (Mira #25) |
| 00:45 | `6c9ecd7` | docs: perf snapshot — 21/21 PASS at strict-single-thread |
| 00:50 | `181a2c9` | feat: port phasediff + conv C binaries to Python (Mira #28) |
| 00:55 | `976c76a` | feat(tier3): gmt_surface_py with Full Multigrid — 6.5x faster than gmt surface (Mira #26 retry) |
| 01:00 | `1e4abdd` | feat: port make_los to Python (Mira #27 retry) |
| 01:05 | `c8415c0` | feat(dem2topo_ra): wire in-process FLIPUD via gmt_grd_io (4.6x speedup) (Mira #30) |
| 01:10 | `ff805e1` | docs: perf snapshot — --fast 9 SAT families all ✓ after SAT_baseline_py + FLIPUD wire-ins |

## REGRESSIONS / REVERTS

### `663da03` — gmt_surface_py wire-in (REVERTED at `98758b9`)

**What happened:** Mira #31 was dispatched to wire gmt_surface_py FMG
into dem2topo_ra and proj_ra2ll_fast (the keystone, expected ~150s/case
savings). She added 152 lines of code with conservative gating but did
NOT commit because pre-flight perf testing revealed blockers.

I checked her worktree, saw the diff looked clean (good gating,
graceful fallback), ran my own smoke test on RS2 which passed, and
committed her uncommitted changes as `663da03`.

**My mistake:** RS2 passes because it has anisotropic cells and falls
through to gmt subprocess. The smoke test did NOT exercise the new
FMG code path. I should have waited for Mira #31's full report.

**Mira #31's actual findings (the blocking issues):**

1. **numba is NOT installed in the production conda env.**
   `/home/staff/dliu/anaconda3/envs/gmtsar/bin/python3 -c "import numba"`
   raises ImportError. `gmt_surface_py._HAVE_NUMBA = False` on this
   system. Without numba JIT + prange, the FMG smoother falls back to
   plain Python loops.

2. **CSK_RAW empirical timing:** gmt surface = 48 s; gmt_surface_py
   pure-python = >10 minutes (killed at 9:35, never completed). The
   wire-in would make dem2topo_ra ~13× SLOWER on CSK, not faster.

3. **8/9 --fast cases have anisotropic cells** (-I rng/2 or rng/4 with
   rng != 2 or 4) → fall through to gmt subprocess → zero benefit.
   Only CSK_RAW (rng=4, I=4/4 square) exercises the new path, and on
   it the path is the SLOW one.

4. **Pixel-registration emulation untested.** gmt surface uses pixel
   reg; gmt_surface_py only produces gridline. The wire's region-shift
   trick + node_offset=1 is untested against the downstream pipeline
   that consumes topo_ra (sensitive at ~1.5 mm RMS).

**Action taken (this commit):** revert `663da03` → `98758b9`. Current
--fast sweep (`bguq14lmf`) was already running with the buggy code,
CSK_RAW is in the slow path (11+ min elapsed); the revert prevents
future sweeps from hitting this.

**Pre-conditions before retrying the wire-in:**

- P0: install `numba` in the gmtsar conda env, OR remove the misleading
  perf-claim docstring from gmt_surface_py (the "6.5×" requires numba).
- P1: add anisotropic-cell support to gmt_surface_py (alpha2/alpha4
  prefactors in the 12-point stencil per upstream src/surface.c
  lines 180-220). Without this, 8/9 cases get zero benefit.
- P2: add pixel-registration mode natively (not via gridline-shift trick).
- P3: port Briggs sub-cell constraint handling so off-grid scatter
  parity drops from ~1-2e-3 to ~1e-4 — required for dem2topo_ra wire.

## Lesson

Per Rule 8: "only merge when tests pass". My smoke-test gate on RS2
was insufficient because RS2 falls through to subprocess — it didn't
actually exercise the new code path. The right gate for a feature
that's only triggered under a specific condition (square cells) is
to **test a case that triggers the condition** (CSK_RAW), not just any
case.

Updated rule 8 implicit clarification (will add to project_rules.md
next): when wiring an env-gated feature, the smoke test must include
at least one case that exercises the new path, not just a fall-through
case.

## Wire-in status after revert

In production (PATH wired):
- xcorr_py, SAT_llt2rat_py (v2), resamp_py (v2), proj_ra2ll_fast,
  SAT_baseline_py
- gmt_inproc gmtconvert (Mira #19, env-gated)
- gmt_grd_io FLIPUD in dem2topo_ra (Mira #30)
- S1 TOPS phase_profile aggregation (Mira #21)
- perf_snapshot.py CLI (Mira #24) + auto-emit in sweep.sh

Parallel files (committed, NOT yet wired):
- gmt_surface_py FMG (needs numba + anisotropic + Briggs + pixel-reg)
- gmt_blockmedian_py (needs density-aware wire site — not dem2topo_ra)
- phasediff_py + conv_py + _gmt_native_bf.py
- make_los_py
- resamp_py v1 / SAT_llt2rat_py v1 backups
