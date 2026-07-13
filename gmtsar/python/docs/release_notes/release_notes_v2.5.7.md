# v2.5.7 — 7 sensor preprocessor ports, gmt_blockmean/triangulate, resamp_py & SAT_llt2rat_py wiring fixes

## Ports landed (project_rules.md Rule 7 gates, real-data parity)

All 7 planned SAR sensor raw-format preprocessors, plus two
`dem2topo_ra` `topo_interp_mode=1` candidates. Every module is wired
behind its own env-gate and logged in `docs/PATHWAY_FORWARD.md`'s new
wiring-status ledger (see Rule 13, added this release: "ported" and
"wired ON by default" are different states, and losing to C is a valid,
tracked outcome — not a gap).

**Winners, parity + speed both pass gate, still OFF pending a full
21-case sweep (only isolated real-data parity+timing tests run so far):**

| Module | Result | Gate |
|---|---|---|
| `make_slc_s1a_py` | +1.4-1.8x, byte-identical | `GMTSAR_S1A_PREPROC_PY` |
| `make_slc_nsr_py` | +19x, byte-identical | `GMTSAR_NSR_PREPROC_PY` |
| `gmt_blockmean_py` | +3.7-19.3x, tolerance-equal (downstream `topo_ra.grd` byte-identical) | `GMTSAR_BLOCKMEAN_PY` |

**Honest losses, correctly OFF — I/O-bound or GMT already uses the
field-optimal library:**

| Module | Result | Gate |
|---|---|---|
| `make_slc_rs2_py` | ~1.3x slower, byte-identical | `GMTSAR_RS2_PREPROC_PY` |
| `make_slc_tsx_py` | slower (numpy import tax dominates one-shot calls), byte-identical | `GMTSAR_TSX_PREPROC_PY` |
| `make_slc_csk_py` | ~1.3-2x slower, byte-identical | `GMTSAR_CSK_MAKE_SLC_PY` |
| `make_slc_csk2_py` | ~4-5x slower, byte-identical; no CSG fixture in repo, no dispatcher call site | `GMTSAR_CSK_PREPROC_PY` |
| `gmt_triangulate_py` | 1.4-9x slower (scipy/Qhull vs GMT's linked Shewchuk Triangle); one documented rare tie-break divergence at 6M-pt scale | `GMTSAR_TRIANGULATE_PY` |

**Partial:** `ALOS_pre_process_py` — IMG-parsing subset only,
byte-identical, +2.1x; LED/orbit/Doppler not ported (real ~2000-line
transitive C closure), so no dispatcher exists — parity is deliberately
incomplete, not wired.

## Fixed: stale versioned-duplicate wiring

- `resamp_py` was symlinked to an unstable `resamp_py_v2` — its numba
  on-disk JIT cache defaults to `bin_py/__pycache__`, which lives on
  NFS, causing 10-58s wall-time swings from synchronous cache-validation
  stat/open round-trips. Fresh isolated measurement confirmed plain
  `resamp_py` is byte-identical and a consistent ~1.3x faster with no
  such instability. Re-wired `install.sh` + the live `bin/resamp_py`
  symlink; `resamp_py_v2` archived to `bin_py/archive/` (not deleted).
- `SAT_llt2rat_py_v2` confirmed correct as the wired default via the
  same protocol (+7.6% vs v1, no NFS instability) — no re-wire needed,
  but v1 archived instead, and `test_SAT_llt2rat.py` fixed: it hardcoded
  a path to v1 and had never actually exercised the live-wired v2
  binary. Now points at v2; all 21 tests still pass (algorithm
  identical, confirmed).
- Also fixed during merge validation: `test_make_slc_rs2_parity.py`
  used `tarfile.extractall(filter="data")`, a Python 3.12+-only API;
  this environment runs 3.11. Added a `hasattr(tarfile, "data_filter")`
  guard.

## Common cross-cutting finding

Every preprocessor port independently hit the same trap: each sensor's
C code parses XML/ASCII header fields with a hand-rolled digit-by-digit
`str2double` (not `strtod`/`float()`) — using Python's `float()` instead
silently diverges in the last ULP on real values. All ports reproduce it
verbatim rather than substituting the "obviously equivalent" library
call.

## Also this release

- Removed an orphaned, unwired copy of `gmt_blockmean_py.py` that had
  leaked into `utils/` from its worktree without the matching
  `dem2topo_ra` wiring.
- Real GUI verification (`docs/gui_screenshots/`, replacing a talk-deck
  placeholder) — found and logged a silent PATH-fallback bug in
  `utils/tkGUI.gmtsar` (defaults to the literal string `'python'` when
  `p2p_processing` isn't already on PATH at launch).
- `requirements.txt` gains `h5py>=3.0` for `make_slc_nsr_py`.
- New `project_rules.md` Rule 13 (wiring-status tracking) and a new
  `docs/PATHWAY_FORWARD.md` ledger table — the canonical reference for
  "what's ported vs. wired vs. never attempted" going forward.

## Test evidence

98 passed, 1 documented opt-in skip (slow real-data CSK test,
env-gated) across all 11 affected test files, run together after both
merge-validation fixes above. Not yet run through the full 21-case
`sweep.sh` — that's the gate for promoting any of the 3 winners above to
default ON.

Commits: `8e23591` (ports + doc/ledger), `bd8cd6b` (bin_py +x-bit fix).
