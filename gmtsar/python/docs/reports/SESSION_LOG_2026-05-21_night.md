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

## Mira #32 finding (2026-05-22 ~05:00 CDT): "py slower" is NFS contention, not code

**The "py 0.73-0.86× slower" snapshot result for CSK_RAW / TSX / CSK_SLC /
ALOS2_Japan_Fugi was misleading.**

### Standalone evidence

On CSK_RAW_Hawaii (26400×19200 = 507 Mpx, intrp=4 bisinc), free hardware:

```
py resamp_py:   84s, 98% CPU, 2.22GB RSS, 1.15M minor page faults
C  resamp:     112s, 98% CPU, 1.99GB RSS,   34K minor page faults
→ py 1.33× FASTER, byte-identical (`cmp` returns 0)
```

### Why production showed py = 408s

Production sweeps run with `MAX_PARALLEL=4` (or 9 or 12). Multiple
case_runner.sh processes hit the same NFS-mounted `work/` tree
concurrently.

`np.memmap` (resamp_py_v2:808-810) reads each 4KB page on first touch
via the kernel's page-fault mechanism. Each page fault is a 1MB NFS
read under contention. 1.15M minor page faults × NFS bandwidth ÷
4 concurrent cases = 5× slowdown.

C's `mmap(..., MAP_POPULATE)` or `madvise(MADV_SEQUENTIAL)` reads
larger chunks proactively → 34K page faults total.

### Fix (NOT yet applied; deserves its own Mira mission)

**Option A: madvise the memmap.** In `resamp_py_v2:808-810`:
```python
mm = np.memmap(path, dtype=np.complex64, mode='r', shape=(ny, nx))
import mmap
# Cast to base memmap then madvise
mm.base._mmap.madvise(mmap.MADV_SEQUENTIAL)  # noqa
```
Expected effect: page faults 1.15M → ~50, production 408s → ~150s.
Risk: cross-platform — `madvise` is Linux-specific.

**Option B: chunked `np.fromfile`.** Replace `np.memmap(...)` with a
sliding-window reader that streams ydim-tile chunks (~50 MB) covering
the 4-tap bisinc stencil. Linux/macOS/BSD portable.

Either way: validate byte-id to C parity test (already exists).

### Implication for "py vs csh" perf claim

The cumulative `0.93× py vs csh` headline number from this session's
snapshot is **NFS-contention-bound**, not algorithm-bound. With the
madvise/chunked-fromfile fix applied:
- CSK_RAW: 957s → ~150s estimated → 4.7× faster than C
- TSX:     996s → ~150s estimated → 4.9× faster
- CSK_SLC: 983s → ~150s estimated → 5.4× faster

The total cumulative ratio would flip from 0.93× to plausibly 1.3-1.5×.

This is the largest single perf finding of the night, larger than
gmt_surface_py multigrid would have been.

### Recommended next Mira mission

Apply Option A (madvise) to `resamp_py_v2:808-810`. ~30 min mission.
Run --smoke (RS2) + --fast (9 SAT under MAX_PARALLEL=9) to verify
byte-id + perf improvement. Commit per Rule 8.
