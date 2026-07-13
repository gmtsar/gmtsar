# AUDIT — stage-cache validation on real multi-stage pipeline (Mira #57)

Mission: validate `tests/stage_cache.py` (landed v2.1.3 by Mira #51) against a
real multi-stage pipeline run, then flip `GMTSAR_STAGE_CACHE` default to `1`
if safe.

**Verdict: KEEP DEFAULT OFF.** The cache infrastructure is sound in
isolation (25 unit tests pass) but the wire-in into `utils/p2p_processing`
has correctness gaps that cause silent pipeline failures on the very first
cache-hit scenario. Two concrete defects, plus one missing-coverage issue.

Framework HEAD at evaluation time: `14bf485`.

## Procedure

Hardware: 64-core box, NFS workdir. Case under test: `RS2_SLC_Hawaii`
(`--smoke` tier, the canonical pipeline-alive check).

1. Verified Mira #51 unit suite: `25 passed in 0.09s`.
2. **Run 1** — cold cache: `GMTSAR_STAGE_CACHE=1 SWEEP_FORCE=py bash
   tests/sweep.sh --smoke`. Wall time: **103 s**. Scorecard: 6 SUCCESS / 0
   FAIL. All 6 sentinels (`.stage_done_P2P{1..6}_*`) written under
   `work/python_test/RS2_SLC_Hawaii/`. Outputs (39 .grd/.PRM/.SLC/.LED)
   snapshotted for byte-identity check.
3. **Run 2** — same cwd, sentinels preserved, only `results/<case>.json`
   removed so the sweep skip-guard doesn't bypass us:
   `GMTSAR_STAGE_CACHE=1 bash tests/sweep.sh --smoke`. Wall time: **4 s**.
   Scorecard: **0 SUCCESS / 6 FAIL** — pipeline crashed in P2P2 with
   `FileNotFoundError: '../raw/RS220110515.PRM'`.
4. Cascading-invalidation test (touch `utils/dem2topo_ra`): skipped — the
   wire-in does not pass `code_files=` so a code-only edit can never
   invalidate downstream stages even when the infra would correctly hash
   them.
5. Byte-id check: deferred — Run 2 produced no usable outputs to diff
   against Run 1.

## Findings

### F1 — Cache-hit corrupts pipeline state (BLOCKER)

`utils/p2p_processing` lines 251-253 fingerprint stage inputs as
`raw/<files>` at the start of the stage. **The fingerprint captures
pre-stage state, but the pipeline destructively mutates that state across
stage boundaries:** P2P1's `pre_proc` writes `raw/<name>.{PRM,SLC,LED}`,
which P2P2 then consumes via `cp ../raw/<name>.PRM .` and later, by
chain-of-`mv` / `_rm_slc_files`, ends with `raw/` back to its pristine
tarball state (no `.PRM` left over).

Consequence on a Run 1 → Run 2 sequence:

* Run 1 P2P1: `raw/` fingerprint = pristine tarball. Sentinel written.
* Run 1 P2P2..6 complete; final `raw/` = pristine tarball again
  (intermediates moved to `SLC/`).
* Run 2 P2P1: `raw/` fingerprint = pristine tarball = Run 1's key.
  Cache **hit**. P2P1 skipped → `raw/<name>.PRM` is NOT created.
* Run 2 P2P2: tries to `cp ../raw/<master>.PRM .` → `FileNotFoundError`.
  Whole pipeline dies.

Reference: `p2p_stages.py:373-380` (RS2/S1_STRIP/etc branch) and
`p2p_stages.py:121-127` (P2P1's `rm -f raw/*.PRM*`).

**A stage cache-hit must mean "all the byte-state downstream needs is
already on disk." The current wire-in cannot guarantee that, because P2P1's
effective outputs span paths that later stages mutate.** This is the
classic "transient intermediate" trap in pipeline caches.

### F2 — `code_files=` not threaded through (cascading-invalidation gap)

`stage_cache.compute_cache_key()` accepts `code_files=` so a touch to
`utils/dem2topo_ra` invalidates P2P3 onward. The wire-in in
`utils/p2p_processing` (lines 268-394) never passes `code_files=` — all
six `_stage_block` calls only pass `inputs=` (data files) and
`config_vals=`. Therefore changes to the Python implementation modules
(`p2p_stages.py`, `utils/dem2topo_ra`, `utils/intf`, etc.) will silently
**not** invalidate the cache. A developer iterating on Python code with
`GMTSAR_STAGE_CACHE=1` will see stale outputs masquerading as fresh.

Briefing cascading-invalidation test could not even be evaluated as a
result; the failure mode is architectural, not run-time.

### F3 — `parent_key` cascade present but useless given F1

Wire-in correctly threads `_pkey = _cs.parent_key` from each stage to the
next, so an upstream input change does propagate downstream via the SHA.
This logic is correct. But it's downstream of F1: a P2P1 cache-hit
already destroys downstream correctness regardless of whether the parent
key changed.

## Wire-in site map

* Stage-cache module: `gmtsar/python/tests/stage_cache.py` (346 lines, all
  written by Mira #51).
* Wire-in: `gmtsar/python/utils/p2p_processing:17-66` (env-gated import,
  `_stage_block` helper, `_NoopStage` no-op fallback), then six call
  sites:
  - P2P1: `p2p_processing:267-276`
  - P2P2: `p2p_processing:280-313`
  - P2P3: `p2p_processing:317-330`
  - P2P4: `p2p_processing:336-356`
  - P2P5: `p2p_processing:360-379`
  - P2P6: `p2p_processing:383-402`
* Sweep wipe mode for sentinels: `tests/sweep.sh:251-272`
  (`SWEEP_FORCE=stage`).

## Measurements

| metric                          | value                                    |
|---------------------------------|------------------------------------------|
| Run 1 wall (cold cache)         | 103 s                                    |
| Run 2 wall (cache hit attempt)  | 4 s — pipeline crashed in P2P2           |
| Run 2 scorecard                 | 0/6 SUCCESS                              |
| Sentinels written Run 1         | 6 (P2P1..P2P6)                           |
| Sentinels reused Run 2          | 1 (P2P1 only — the rest changed key)     |
| Byte-id of skipped-stage output | N/A (Run 2 produced no outputs)          |
| Cache OFF re-run (restore)      | 106 s, 6/6 SUCCESS — matches Run 1 wall  |

The Run 2 "4 s" includes case_runner.sh setup time and the P2P2 crash; the
P2P1 skip itself saved ~1 s (per Run 1's `phase_profile_py.json`). So even
if F1 didn't crash the pipeline, the speed-up on RS2 would be negligible —
P2P1 is only 0.9 s of the 103 s budget. The real wins (P2P3 dem2topo_ra =
33 s, P2P2 focus_align = 29 s, P2P6 geocode = 14 s) require fixing F1
first so those stages can actually cache-hit safely.

## Recommendations

Default **stays OFF**. Two paths forward, ranked:

**(A) Re-scope what each stage's cache represents (preferred).** A cache
hit must imply that downstream's *consumed* inputs are already present.
Two concrete refactors:

1. Fingerprint the **post-stage** state (output paths the next stage
   reads), not the pre-stage input paths. E.g. P2P1's cache key should
   include `SLC/<name>.{PRM,SLC,LED}` if those are what P2P2 consumes.
   Then a hit means "the downstream-visible outputs are on disk in the
   exact form Run 1 left them."
2. Or fingerprint BOTH input AND output paths and require both to match
   the recorded sentinel.

**(B) Coarsen stage granularity.** Merge P2P1+P2P2 into a single cache
unit since they share transient raw/ state. Same for any other
chain-of-mv. Easier but loses skip granularity (touching just the geocode
stage no longer saves anything until P2P5 outputs are stable too).

**Independently of (A)/(B), F2 must be fixed:** the wire-in must list the
Python source files that implement each stage and pass them as
`code_files=` to `_stage_block`. Without that, editing any stage's
implementation produces stale cached outputs — the silent-wrong-result
trap the briefing explicitly warned against.

## What I did NOT do (and why)

* No code edits to `p2p_processing` — the fixes above need a design
  decision (path A vs B) that the user should make. Shipping (A) without
  understanding the chain-of-mv invariants risks a different correctness
  failure.
* No flip of the default to `1` — would have produced silent wrong
  results on every developer's first re-run.
* No commit yet — the audit is the deliverable; the fix is a follow-up
  mission.

## Reproduce

```bash
cd $GMTSAR/gmtsar/python
# Run 1 (cold): builds sentinels, expected 6/6 SUCCESS, ~100 s
GMTSAR_STAGE_CACHE=1 SWEEP_FORCE=py bash tests/sweep.sh --smoke

# Run 2 (warm): delete results JSON only, keep python_test/.
# Expected: pipeline crashes in P2P2 with FileNotFoundError on
# ../raw/<master>.PRM. Cache hit on P2P1 only; cache miss + re-run
# attempt on P2P2 that then fails.
rm -f work/results/RS2_SLC_Hawaii.json
GMTSAR_STAGE_CACHE=1 GMTSAR_STAGE_CACHE_DEBUG=1 bash tests/sweep.sh --smoke
grep stage_cache work/python_test/RS2_SLC_Hawaii/log.txt
```

— Dr. Mira Volkov, 2026-05-22
