# Release notes — v1.1.3

## 1. Version and date

- **Version:** v1.1.3 (patch — docs cleanup + signal-handling hardening)
- **Date:** 2026-05-14
- **Previous:** v1.1.2 (archived to `docs/release_notes_v1.1.2.md`)

## 2. Summary of scope

Documentation polish (`README.md` aligned with the current `tests/` layout) and a defense-in-depth bash trap in `case_runner.sh` for cleaner signal handling. `CHANGELOG.md` removed — `release_notes_v*.md` files are now the only changelog source.

## 3. Files added / removed / renamed / cleaned up

### Modified

- `README.md` — every stale reference replaced. `testingSystem/` → `tests/`, `runAllTest.py` → `runner.py`, `checkTest.py` → `compare.py`, `pythonREADME/` → `recipes/`, `summarize_sweep.py` → `report.py`, `pathListForTest.py` → `cases.py`. Tiered-test flags documented (`--smoke`, `--fast`, `--full`). JSON result sidecar mentioned. Frozen-reference workflow mentioned. The `intfDirList` reference is gone; auto-discovery is described. The `pythonCommandListPath` reference is now `recipesDir`. Single-source-of-truth pointer to `tests/cases.py` `CASES` dict added. `xcorr_py` mention is unchanged.
- `tests/case_runner.sh` — added `trap 'kill 0 2>/dev/null; exit 130' INT TERM` so the script self-cleans on Ctrl-C / SIGTERM even when invoked directly (without `runner.py`'s wrapper). Defense in depth — `runner.py`'s `_kill_all` still fires for normal sweep runs.

### Removed

- `CHANGELOG.md` — superseded by the `release_notes_v*.md` system. Anyone reading `CHANGELOG.md` previously now reads the current release notes file directly.

### Disk cleanup (not committed; relevant for the dev box)

- Deleted ~249 GB of intermediate sweep outputs (`work/python_test/`, `work/csh_test/`) and stray `__pycache__/` directories. `work/dataset/` (53 GB of cached tarballs) and `work/results/` (the JSON sidecars) were preserved.

## 4. Content updates to master documents

- **`README.md`** — section "Testing for developers" now describes the current `tests/sweep.sh` workflow, the tier flags, and the JSON results sidecar. Section "Sample datasets" now points to `tests/cases.py` `CASES` dict as the single source of truth for satellite / extension / tier membership / enabled flag. Acknowledgments section unchanged.

## 5. Audit findings and fixes

| Rule | Finding | Status |
|---|---|---|
| 1. Pass all tests | Ran `sweep.sh --smoke` end-to-end (RS2_SLC_Hawaii from scratch including tarball extraction, csh + python in parallel, compare): **6/6 SUCCESS in 212s**. | ✅ |
| 2. All dev in `gmtsar/python/` | 3 files touched, all under `gmtsar/python/`. No upstream files modified or removed. | ✅ |

Smoke test confirmed the bash `trap` doesn't interfere with the happy path. Signal-on-interrupt cleanup wasn't separately verified (would require sending SIGINT mid-run); the trap is defensive scaffolding.

No human-judgment fixes were skipped.

## 6. Remaining open issues, unknowns, or pending bookings

Carried over from v1.1.2 (no change):

- NISAR_SIM_ALOS download blocked (topex 403); manifest marks `enabled: False`.
- Docker image not yet published / smoke-tested in a real Docker env.
- No GitHub Actions workflow. CI workflows must live at `.github/workflows/*.yml` per GitHub requirement — outside `gmtsar/python/` — so adding one is a deliberate decision against rule 2 of `PROJECT_RULES.md`. Deferred.
- Frozen-csh reference (~5.8 GB) not shipped via git; would live as a GitHub Release asset.

## 7. Totals or cost changes

Not applicable.

## 8. Assumptions used

- `release_notes_v*.md` files are the sole changelog format going forward. Anyone landing here looking for `CHANGELOG.md` is steered to the current release notes file or `docs/` archive.
- The bash trap pattern (`kill 0`) sends SIGTERM to the script's whole process group; `runner.py` starts each `case_runner.sh` in its own session (`start_new_session=True`), so the trap doesn't accidentally kill sibling cases.
