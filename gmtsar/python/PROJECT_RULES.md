# PROJECT_RULES.md

1. **Pass all the tests.** The `tests/` sweep must produce SUCCESS for every comparison across every supported case (where the dataset is downloadable). Cases blocked by external issues (e.g. NISAR_SIM_ALOS 403'd on topex) are documented but do not fail the release.

2. **All dev inside `gmtsar/python/`.** This fork is on top of upstream `gmtsar/gmtsar`; the rest of the tree is left untouched so upstream merges stay clean. New files, edits, refactors, and release artifacts all live under `gmtsar/python/`.
