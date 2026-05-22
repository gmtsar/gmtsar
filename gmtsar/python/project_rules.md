# Project rules

Authoritative rules for this fork. Apply to every change, every test recipe,
every script. Violations are bugs.

## 0. Pass all the tests

The Python pipeline must reproduce the csh pipeline's outputs for every
enabled case in `cases.py`. A change is not done until the relevant test
case(s) report `SUCCESS / 0 FAIL` (or the diff is below the metric threshold).
"Probably fine" is not an acceptance criterion — only running the test is.

## 1. No silent fallbacks

If an expected file, binary, or config is missing, **fail loudly and immediately**.
Do not substitute a default, do not skip the step, do not "best-effort try and
continue." A missing input means the assumption underlying the workflow is wrong,
and downstream products will look superficially OK while being meaningless.

Concrete:
- `gmtsar_lib.run()` raises on rc=127 (command not found). Do not weaken this.
- `case_runner.sh` stages `config.py` from `tests/configs/<case>.py`. If a case
  ships a bundled `config*.txt` and no matching staged `config.py` exists, the
  recipe must error — do not fall back to `pop_config` auto-generation.
- A recipe must crash if its required input (bundled config, dem.grd, raw data
  files) is missing. Do not generate a placeholder.
- Python's `pre_proc` must error if SAT isn't in its dispatch table. Do not
  print "FINISHED" with no work done.

## 2. No placeholder data

Do not emit stub / sentinel data that looks valid. Empty PRMs, zero-byte SLCs,
"-999" where a real value is required — all forbidden. Either produce the right
value, or error out so the caller knows the pipeline is broken.

## 3. Mirror the bundled README + config exactly

For every test tarball under `gmtsar/python/work/dataset/`:

- If it ships a `config*.txt`: the matching Python `config.py` must be its
  faithful translation (via `import_csh_config`), staged in `tests/configs/<case>.py`.
- If it ships only a `README*.txt`: the Python recipe must mirror the README's
  command chain exactly — same SAT, same args, same `parallel` flag, same
  `cd` / `ln -s` / `mkdir` order. Do not silently switch SAT name, swap args,
  or drop a `cd` step.

Diverging from the bundled ground truth means the Python pipeline isn't
testing the same thing the csh side is — comparisons become noise.

## 4. Errors are signal — do not swallow them

When something fails, surface the actual error message. Do not:
- catch + log + continue (unless the error is genuinely benign, like a gmt
  binary's INFORMATION-level non-zero return)
- redirect stderr to /dev/null
- print "WARN: ..." and march on for anything that produces empty downstream output
- use `|| true` to mask exit codes (the legacy filter1→filter_wavelength patch
  is OK because it's a known-safe data fixup, not error masking)

## 5. Dev confined to `gmtsar/python/`

Per CLAUDE.md: all dev in this fork lives under `gmtsar/python/`. Never edit
upstream `gmtsar/csh/`, `gmtsar/preproc/`, `gmtsar/gmtsar/`, etc. — those are
upstream-tracked. If an upstream fix is needed, work around it in `python/`
(e.g. the filter1 → filter_wavelength patch lives in `tests/case_runner.sh`,
not in upstream `pop_config.csh`).

## 6. Testing collects performance + hardware specs

Every test run must record, alongside the SUCCESS/FAIL scorecard:

- **Per-case wall time** (`work/timeSpentLog.txt`) — csh side, py side,
  total — so a regression of "still passing but 3× slower" is visible.
- **Per-sweep hardware/software snapshot** (`work/perf_<timestamp>.txt`)
  — CPU model + core count, total RAM, workdir filesystem type (NFS vs
  local), GMT version, Python version, `gmtsar` C-binary git short SHA,
  `$OMP_NUM_THREADS` and friends. Without this, scorecards from
  different hosts or runs can't be compared and regressions can't be
  attributed to environment vs code.
- **Per-case JSON scorecard embeds `git_sha`** of the framework HEAD at
  comparison time, so `sweep.sh`'s skip-already-passed guard can detect
  when a previously-verified case needs re-running because the code
  changed.

The framework refuses to ship a scorecard without these fields.

## 7. Every full sweep produces a faithfully-recorded snapshot

Every `bash tests/sweep.sh --full ...` run (whether passing or not, whether
3-case or 20-case) MUST emit a snapshot file before any performance claim
is made publicly (README, release notes, slides, papers). The snapshot:

- Lives at `docs/perf_snapshots/perf_snapshot_<UTC-iso8601>_<git-sha>.md`
  (and optionally `.json` alongside), named so it sorts chronologically and
  ties back to the source tree. `docs/` (not `work/`) so it gets committed
  with the code it benchmarks. Use the format produced by
  `tools/perf_snapshot.py` (four tables: per-case timeline, per-binary
  breakdown, aggregate by stage, failure mode).
- Captures **every** of these fields, no exceptions:
  - **invocation**: full env (`NUMBA_NUM_THREADS`, `XCORR_PY_WORKERS`,
    `OMP_NUM_THREADS`, `MKL_NUM_THREADS`, `OPENBLAS_NUM_THREADS`,
    `BLIS_NUM_THREADS`, `VECLIB_MAXIMUM_THREADS`, `NUMEXPR_NUM_THREADS`,
    `MAX_PARALLEL`, `SWEEP_FORCE`), exact `TEST_CASES` list, sweep wall
    time, scope of the run (cases set).
  - **per-case**: score (S/F), py total seconds, csh total seconds,
    speedup ratio, per-binary breakdown from `phase_profile_py.json`
    (all binaries reported by `time_run`).
  - **environment**: same fields as rule 6's `perf_*.txt` (CPU model,
    core count, RAM, disk type, GMT/Python/Numba versions, framework
    git short SHA, dirty/clean working tree flag).
  - **failures**: for any case scored ≠ all-SUCCESS, the failing-file
    list + reason text (from the scorecard's `comparisons` array).

Rule of thumb: a snapshot must contain enough information that **another
person on another machine could attempt to reproduce the measurement** and
**identify what's different** if they get different numbers. "Trust me
bro" perf claims are forbidden — point at a snapshot file or don't make
the claim.

A snapshot must NOT cherry-pick. If the sweep produced 15/20 pass and
5/20 fail, the snapshot records all 20 entries, not just the 15 wins.
"Best result" framing belongs in commentary, not in the snapshot itself.

Stale or contaminated runs (cached intermediate outputs short-circuiting
stages, mid-flight kills, env-var bleed between configurations) must be
explicitly flagged in the snapshot's `caveats` field. If a measurement
is suspect, the snapshot says so — it does not silently get folded into
aggregate claims.

The snapshot is committed alongside the code it benchmarks. Re-running
the same code against the same hardware must reproduce within ±10% wall
time (NFS I/O variance dominant); larger deviations are a signal the
underlying code or environment has drifted and must be investigated, not
papered over.

## 8. Merge only after a feature passes ALL tests

No feature, optimization, or refactor merges into `master` until the full
21-case sweep (or the relevant subset of cases the feature touches)
produces **all-PASS** scorecards.

Concretely:

- A consilium-agent worktree branch is reviewed but NOT merged until
  the user has seen a strict-single-thread sweep snapshot showing the
  feature does not regress any of the currently-passing cases.
- "Looks good in isolated test" is necessary but not sufficient.
  Isolated kernel parity does not guarantee in-sweep parity — see the
  NISAR Mira #15 → #17 → #18 saga where each isolated fix verified but
  in-sweep behaviour kept diverging.
- The merge candidate must pass at least the 3-case fast tier
  (RS2_SLC_Hawaii + NISAR_Ethiopia + ALOS_SLC_L1.1) before any
  optimization-targeted feature can be evaluated; for a refactor or
  GMT-port change, all 21 cases must pass.
- If a merge candidate breaks even one case, it goes back to the
  consilium agent (or is reverted) — do not paper over with
  per-case threshold loosening.
- **Env-gated wire-ins:** when a feature is wrapped in a runtime gate
  (env var, capability check, file existence), the smoke test must
  include at least one case that **exercises the new code path**,
  not just any case. A case that falls through to the legacy path
  via the gate proves nothing about the new path. Example failure
  (gmt_surface_py wire-in 2026-05-22): the gate was `x_inc == y_inc`
  (square cells). RS2 is anisotropic so the smoke RS2 ran the legacy
  subprocess; the actual new FMG path was not validated. Wire-in
  shipped, --fast later showed CSK_RAW (square cells) hit the new
  path which was 13× slower (numba absent on prod env). Revert at
  `98758b9`. Lesson logged in
  `docs/SESSION_LOG_2026-05-21_night.md`.

This rule sits on top of rule 0 (pass all tests) but specifically scopes
the merge decision: pre-merge passing is the gate, not post-merge
debugging. We do not merge with the intent of "I'll fix the regression
in a follow-up commit" — that's how cascading bugs land in master.

## 9. py side MUST NOT modify the csh oracle

The csh oracle at `work/csh_test/<case>/` is the immutable ground-truth
reference. The py side (anything under `work/python_test/<case>/`) is the
unit under test. They are isolated trees.

**Forbidden — every one of these breaks the parity test:**

- Any py recipe writing to `work/csh_test/...` (directly or via symlink).
- Any sweep that wipes `work/python_test/<case>/` but leaves intermediate
  files (PRM, r.grd, SLC) inside `work/csh_test/<case>/` partially
  refreshed from a different code version. The "stale oracle" failure
  Mira #18 root-caused on NISAR was a real instance of this — somewhere
  during xcorr_py iteration, a partial step touched csh_test's
  intermediates without re-running the full csh recipe to re-derive the
  downstream `.SLCresamp` files.
- Manual debugging that runs C binaries (xcorr, fitoffset, resamp) inside
  `csh_test/<case>/raw/` or `csh_test/<case>/SLC/`. That partially refreshes
  the oracle and leaves it internally inconsistent.

**Enforcement:**

- Rule 8's sentinel (`.oracle_built` with `tarball_md5 + fwk_sha`) catches
  the case where the tarball or framework changed since oracle build, but
  it does NOT catch a partial mid-run write that leaves the same tarball
  and intermediate files but inconsistent downstream outputs.
- All py work must live under `work/python_test/...`. The py recipes that
  ship in `gmtsar/python/utils/` and `gmtsar/python/bin_py/` only ever
  reference paths under `python_test/<case>/`. If a future Mira mission
  needs to read from csh_test (e.g., for comparison), it must be a
  READ-ONLY access — no writes.
- The sweep harness `tests/sweep.sh` and `tests/case_runner.sh` must not
  pass `csh_test/<case>` paths as output args to py recipes. The py side
  is `pyDir`; the csh side is `cshDir`; they never alias.

**When in doubt: delete the affected `csh_test/<case>/` and let
`case_runner.sh` rebuild from scratch.** Rule 8's sentinel will then
record a fresh `.oracle_built` and future invocations will trust it.

## 10. Don't reinvent the wheel — port the C algorithm verbatim FIRST

For any port of an upstream C/csh tool that has a public source reference
(GMT's `surface.c`, gmtsar's `xcorr.c`, etc.), the FIRST implementation
must be a line-by-line port of the algorithm choices the C code makes.
No "I'll use a simpler scheme first and optimize later" — that's how
algorithmic-complexity bugs ship.

**Concrete examples that violated this rule:**

- `gmt_surface_py` initial port (Miras #20, #26): chose Jacobi smoother
  because "easier to parallelize." gmt's surface.c uses Gauss-Seidel SOR
  with omega ≈ 1.97. Jacobi vs GS-SOR is not a constant-factor
  difference — it's a complexity-class difference for biharmonic PDEs
  (O(N²) vs O(N^1.5) iterations). This bit us when strict-single-thread
  was enforced: Jacobi on 6600×4800 grid took 11+ minutes vs gmt's 50s
  C reference. Mira #50 fixed by porting GS-SOR verbatim from surface.c.

- Multigrid scheme detour: Mira #26 tried classical V-cycle, hit
  operator-scaling divergence, switched to FMG. gmt's V-cycle works
  because it has properly scaled coarse-grid operators we never got
  right. Reading gmt's `surface_iterate()` flow before trying our own
  multigrid scheme would have avoided the detour entirely.

**The rule:**

For a port mission, the workflow is:

1. **Read every C/csh source file** the binary depends on. Header files,
   linked .c files, macros, constants. Document choices the C code
   makes (smoother type, convergence criterion, BC handling, etc.).
2. **Port verbatim** — same algorithm, same constants, same iteration
   structure. No substitutions for "ease" or "Pythonic-ness".
3. **Get bit-faithful parity FIRST** on real data.
4. **THEN** consider optimization — but only ones the C couldn't do
   (numpy SIMD, Numba JIT, batched FFT, memmap, etc.).

If the C source is genuinely opaque (closed-source binary), document
what could be observed (CLI args, file formats, timing) and port from
behavior — but flag the gap explicitly.

**Mira's existing Rule #1 ("bit-faithful first, optimize later")
already implied this — but it didn't catch the Mira #20 prototype
shortcut. Rule 10 makes the algorithm-choice constraint explicit.**

**Side benefit:** porting the C algorithm verbatim makes the parity
oracle natural — diff our Python output against the C reference on the
same input, byte-by-byte. No "I think this should give the same answer
within tolerance" hand-waving.

When in doubt: read the C source. The C author already solved the
hard problem. Don't re-derive it.
