# Release notes — v1.6.0

## 1. Version and date

- **Version:** v1.6.0 (minor — PLAN Phase 2 starts: unwrap_parallel + scaffolds)
- **Date:** 2026-05-14
- **Previous:** v1.5.0 (archived to `docs/release_notes_v1.5.0.md`)

## 2. Summary of scope

Begins PLAN Phase 2 (batch / multi-pair drivers). Phase 2 is isolated from
the running pipeline — all new files, no edits to existing P2P code paths.

1. **`utils/unwrap_parallel` implemented (60 lines)** — Python port of the
   csh script that fans out snaphu unwrapping jobs across multiple intf
   directories. Replaces GNU parallel with Python's `multiprocessing.Pool`
   (no external dependency).
2. **Scaffolds for the other 4 Phase 2 utilities:**
   - `pre_proc_batch`  (314 csh lines → scaffold)
   - `align_batch`     (179 csh lines → scaffold)
   - `intf_batch`      (282 csh lines → scaffold)
   - `batch_processing` (365 csh lines → scaffold)

Each scaffold validates its CLI signature and raises `NotImplementedError`,
matching the v1.1.5 pattern for Phase 1 scaffolds.

## 3. Files added / removed / renamed / cleaned up

### Added (all under `utils/`)

- `unwrap_parallel` — implemented (60 lines).
- `pre_proc_batch`, `align_batch`, `intf_batch`, `batch_processing` —
  scaffolds.

### Modified / Removed

None.

## 4. Content updates to master documents

- `release_notes_v1.5.0.md` archived to `docs/release_notes_v1.5.0.md`.

## 5. Audit findings and fixes

| Rule | Finding | Status |
|---|---|---|
| 1. Pass all tests | These are new standalone utilities; not imported by any pipeline code. No regression risk; 84/0 baseline preserved trivially. | ✅ |
| 2. All dev in `gmtsar/python/` | All changes under `gmtsar/python/utils/`. | ✅ |

## 6. Remaining open issues, unknowns, or pending bookings

Carried over (no change):

- NISAR_SIM_ALOS download blocked.
- Docker image not yet published.
- No GitHub Actions workflow.
- Frozen-csh reference not shipped.
- Ridgecrest empty-results-JSON bug (v1.1.5 sweep).

Phase 2 remaining: implement `pre_proc_batch`, `align_batch`, `intf_batch`,
`batch_processing`. Per the recommended order in PLAN.md, `align_batch` is
the natural next target (179 csh lines, simplest of the three batch
orchestrators).

After Phase 2: Phase 4 (SBAS/time series) — blocked on test fixture.

## 7. Totals or cost changes

- `utils/unwrap_parallel`: new file, 60 Python lines (replaces 39 csh lines
  + a runtime dependency on GNU parallel).
- 4 scaffolds: ~20 lines each.

## 8. Assumptions used

- `multiprocessing.Pool` is a reasonable replacement for GNU parallel in
  this context (CPU-bound fan-out of independent snaphu processes). If
  the user has `parallel` installed and prefers it, swapping back is a
  one-line change.
- The custom-script-in-cwd convention (`unwrap_intf` or `unwrap_intf.csh`)
  is honored if present — matches the csh original.
