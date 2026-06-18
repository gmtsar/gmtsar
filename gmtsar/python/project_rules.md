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

**10a. The parity test MUST use real, FULL-SCALE input.** (Lesson: Mira #72,
2026-06-13.) `gmt_surface_py` passed every 64×64 synthetic parity test yet
diverged 0.458m RMS from `gmt surface` on the real CSK grid (6144×12600,
3.3M pts). Small/smooth grids hide algorithm-detail divergences (BC handling,
multigrid stride behavior, convergence on anisotropic heterogeneous data). A
port is NOT "bit-faithful" until it matches the C binary on a real, full-size
case from the actual pipeline. Toy-grid tests are necessary but never
sufficient — they give false confidence.

**10b. When a "verbatim" port still diverges, instrument BOTH sides and
binary-search to the first divergence.** Don't conclude "the solver is
inaccurate" — that's never the answer for deterministic visible C. Instead:
build a debug C binary that dumps intermediate state (per-stride node values,
constraint coefficients, BC rows, iteration residuals), dump the SAME points
from the Python on the SAME input, and diff to find the FIRST checkpoint where
they differ. Fix that one deviation to match C exactly; repeat until the final
output is byte-identical. Bit-identical is always achievable for deterministic
open-source C — the only question is finding which line you didn't duplicate.
THEN vectorize / numba-optimize (Rule 10 step 4).

When in doubt: read the C source. The C author already solved the
hard problem. Don't re-derive it.

**Carve-out — existing ports that ARE bit-identical to gmt C AND
faster:** these are compliant even if not line-by-line verbatim.
The spirit of the rule is "don't reinvent the wheel and end up
slower or less accurate" — if the port lands at the same numerical
answer and runs faster, the substitution is a genuine improvement,
not a shortcut.

Concrete examples that qualify for the carve-out:

- **`xcorr_py`**: uses `scipy.fft` (FFTW backend) instead of GMTSAR's
  bundled KISS-FFT. scipy.fft is the same family of algorithms
  (Cooley-Tukey radix-2/4) with a tighter implementation. Last-ULP
  differences exist; bit-identical at every commonly-used precision.
  And 1.94× faster on RS2. Keep.

- **`utils/gmt_grd_io.py`**: reverse-engineered netCDF writer from
  `ncdump -h` observation of gmt-produced files. Not derived from
  GMT's C netCDF I/O code. But the files it writes ARE accepted by
  every downstream gmt module (grdinfo, grdmath, grdcut, grdtrack,
  xyz2grd round-trip — 16 parity tests pass). Avoids xarray's
  netCDF cruft. Keep.

- **`bin_py/_gmt_native_bf.py`**: same — observation-derived =bf
  binary I/O for filter.csh's intermediate format. Files read/written
  bit-equally to gmt's own =bf I/O. Keep.

- **`utils/gmt_blockmedian_py.py`** (Mira #25, GREEN): bin index via
  banker rounding + argsort grouping + per-bin Numba median. Different
  data structure from gmt's nth_element quickselect, but byte-identical
  output at the densities the pipeline actually uses (verified on 9M-row
  ALOS_Baja_EQ trans.dat). 2.5× faster at N=8 threads. Keep.

The carve-out does NOT apply to:

- **Algorithm-class deviations that lose accuracy or speed** (Jacobi vs
  GS-SOR — gmt_surface_py KEYSTONE; scipy gaussian_filter vs gmt
  -Fg's circular truncated kernel).
- **Incomplete ports advertising drop-in replacement** (the dormant
  `bin_py/blockmedian_py` trap with scipy.stats + cell-center coords).
- **Missing functionality** (phasediff_py long-baseline NotImplementedError
  doesn't qualify — there's no output to compare for that path).

**Verification test for the carve-out:**

A port qualifies for keep-as-is if BOTH:
1. Byte-identical to gmt C on real test data (or rms below documented
   sub-ULP floor in the audit log)
2. Equal or faster than gmt C single-thread on the same hardware

If both hold and a Mira's audit says GREEN, accept the port. Otherwise
follow Rule 10's verbatim-port discipline.

## 11. Every bug found → a regression test must guard against it shipping again

When investigation surfaces a real bug (algorithmic, edge case, or
silent-divergence), the fix-Mira's deliverable MUST include a unit or
parity test that:

1. **Reproduces the bug deterministically** on the smallest fixture
   that triggers it (not the full real-world case).
2. **Asserts the corrected behaviour** with a tolerance tight enough
   to catch the original bug if it returns.
3. **Is added to the appropriate test tier** so future runs catch
   regressions:
   - Numerical kernel bugs → `bin_py/tests/test_<module>.py`
   - Pipeline-stage drift → enable the relevant case in the proper
     `--smoke`/`--smart_fast`/`--fast`/`--full` tier
   - Configuration / env-gate bugs → tests/test_env_gate_*.py

The commit message references the bug + the test that guards it.

**Concrete examples that motivated this rule:**

- **gmt_surface_py gcd=1 algorithm bug (Mira #61 finding 2026-05-22):**
  ENVI (5191×7579) and TSX (9440×6937) grids hit
  `gcd(n_columns-1, n_rows-1) == 1`. surface_py's smart_divide collapses
  to a single stride [1] → no multigrid hierarchy → wrong fixed point.
  ALL existing parity tests used grids with gcd>1, masking this regression.
  Mira #68's fix mission MUST include a gcd=1 parity test fixture
  (e.g. test_gcd_1_small with 7×13 grid, test_gcd_1_envi_subset with
  real ENVI sub-region).

- **NaN slow-path in gmt_grdsample_py (Mira #59 finding 2026-05-22):**
  Wire-in to snaphu.py landmask exposed 2.7× regression on 38%-NaN data.
  Mira #65's @njit gather fix MUST include a parity test that hits
  >30% NaN data (real ALOS_haiti landmask or synthetic equivalent).

- **fitoffset.csh vs fitoffset C-binary mismatch (Wei audit 2026-05-22):**
  utils/align_tops:211 called C `fitoffset` with csh-style args. Latent
  because no test exercises that line. Fix landed at v2.0.4, but no
  regression test was added at the time. RETROACTIVE: a test that asserts
  `align_tops` uses `fitoffset.csh` (csh wrapper) for argv shape would
  guard against silent reintroduction. Track as a Mira mission.

**The rule:**

For every bug-fix commit:

```
- file: utils/<module>.py
- file: bin_py/tests/test_<module>.py (NEW or UPDATED)
  - add a test that exercises the buggy path with the smallest fixture
  - assert correctness with tolerance tight enough to catch the bug
- commit message references both files
```

If a fix is committed WITHOUT a regression test, the test must land in
the next commit before the version tag advances. Wei enforces this on
every Mira return — if a bug-fix Mira reports the fix but not a test,
send her back with the test as the next deliverable.

**The cost of not following this rule:**

The gcd=1 bug shipped to v2.1.10 (surface wire default-on) and required
a full --fast 9 SAT to surface. Cost: ~30 min sweep + ~2 hours Mira #61
investigation + ~3 hours Mira #68 fix mission. Total ~6 hours could
have been ~30 min if a gcd=1 fixture had been in the test suite from
day 1.

## 12. No catch-and-retry-via-subprocess fallbacks in dispatchers

A `GMTSAR_*_PY` dispatcher selects between an in-process Python port and
a `gmt`/csh subprocess. The selection MUST happen via a pre-flight env
check (and, where relevant, a capability/shape check on the inputs)
**before** calling the in-process path. Once the in-process path is
called, it must run to completion or raise — its exception must NOT be
caught and silently retried via the subprocess.

**Why:** a `try: _inproc(...) except Exception: run(subprocess_args)`
pattern looks like a safety net but actively hides incomplete ports and
wastes compute:

- 2026-06-13, `dem2topo_ra::_surface_or_run` (pixel.grd call,
  `GMTSAR_SURFACE_INPROC=1`): `gmt_surface_py` ran a full ~26s multigrid
  solve on RS2_SLC_Hawaii's pixel.grd grid, then raised
  `NotImplementedError` at the pixel_reg crop-back step (a genuinely
  unimplemented Mira #68 case). The except-fallback caught this, threw
  away the 26s of work, and re-ran via the `gmt` subprocess (~12s).
  Total wall time (38s) was reported in code comments as "gmt_surface_py
  is 3.2x slower" — a real-sounding performance number that was actually
  *zero seconds of gmt_surface_py output* plus 26s of wasted compute.
  The fallback hid both the missing feature AND the true cost.

**How to apply:**

- Gate selection on `os.environ.get("GMTSAR_X_PY", default) == "1"` (and
  import success) ONLY. Do not add a second layer of `try/except` around
  the in-process call that falls through to the subprocess on failure.
- If the in-process port has a known-unsupported input shape/regime,
  check for it BEFORE calling the port (cheap shape/parameter check,
  not "try it and see") and either (a) raise immediately with a message
  naming the unsupported case, or (b) route to the subprocess via the
  pre-flight check — never via a post-hoc except.
- This does not weaken Rule 8's rollback story: `GMTSAR_X_PY=0` remains
  the instant, zero-cost rollback to the subprocess. What's forbidden is
  *automatic*, *silent*, *post-compute* fallback when `=1` is set.
- Applies to new dispatchers and is the target for auditing existing
  ones (m2s_py, grdfill, blockmedian, surface_inproc x2) opportunistically
  as they're touched — not a mandate to retrofit all of them in one pass.

## 13. Don't trust past conclusions — only fresh-run outputs are evidence

A prior session's (or prior agent's) *conclusion* is a hypothesis, not a fact.
Re-derive it with critical thinking before acting on it; if it matters, confirm
it with a FRESH run on real data. Stale conclusions are routinely wrong.

**Concrete failure this rule exists for (2026-06-14):** the "#72 surface
divergence is an inherent tol=1e-4 convergence floor, not fixable without tighter
tol" conclusion was accepted across multiple sessions. A fresh measurement showed
S1_Ridgecrest's topo_ra was **42 m** off C (vs cm on same-size siblings) — a gross,
dimension-specific BUG, not a floor. The "wall" was an unverified inherited claim.
Other examples this campaign: the v2.1.32 "RS2 byte-identical" surface flip (a
measurement error masked by a try/except subprocess fallback); "snaphu solver can
only reach statistical parity" (a 30×30 fresh run showed float32-EXACT).

**The rule:**
1. Treat any inherited conclusion ("X is impossible / fixed / bit-identical / the
   bottleneck / a floor") as UNVERIFIED until a fresh run reproduces it.
2. Prefer measuring over believing: when a claim gates a decision, re-run it on
   real, full-scale data and read the actual numbers.
3. Tests/conclusions that passed on small or synthetic inputs do NOT certify real
   behavior (see Rule 10a). A fresh real-data run is the only trustworthy oracle.
4. Be especially skeptical of "can't / impossible / inherent" conclusions — they
   end investigation prematurely. Demand file:line + reproduced evidence.
5. When you cite a past result, say whether it was freshly verified or inherited.

## 14. Sweep tripwire — verify every case as it completes; stop on failure

Do NOT wait for a full sweep to finish to learn it failed. Each case writes
its scorecard (`work/results/<case>.json`) the moment it completes. As cases
land, verify each one's `py-vs-csh` status:

- A case is **structurally broken** if any file is `missing on py` (the
  pipeline didn't produce output — e.g. the +x cascade: `git apply` strips
  working-copy execute bits under `core.fileMode=false`, so a wired script
  hits `Permission denied`). One such case means EVERY case will fail the
  same way → **kill the sweep immediately and examine**; do not waste hours.
- A case is a **real regression** if outputs exist but a metric exceeds
  threshold, and it is NOT the one documented exception (S1_Ridgecrest_EQ
  no-DEM-corner phasefilt complex-rms ~0.35). On the first such case →
  **stop the sweep and examine** the diff before continuing.
- The only accepted in-sweep failure is the documented Ridgecrest no-DEM
  corner. Anything else halts the sweep.

Mechanism: arm an event Monitor on `work/results/*.json` (or the sweep log
`DONE`/`FAIL` lines) so the first failing case wakes the supervisor to abort
— not a slow poll. After a `git apply` of any patch touching executables,
`chmod +x` the WORKING COPY (not just `git update-index`) and confirm
`test -x` BEFORE launching the sweep.

## 15. Edge-case A/B BEFORE wiring a port at a new site (don't discover divergence via a 3h sweep)

When wiring a Python port (`gmt_*_py`) into a new call site, FIRST A/B-verify the
operator on the real grid that STRESSES its known edge cases — BEFORE wiring and
BEFORE the full-sweep gate:

1. **A/B on the stressing case, not a benign smoke.** Run the op `env=0` (gmt) vs
   `env=1` (py) on the same real input and compare bit/float-exact + NaN-footprint.
   Choose the input that exercises the edge: high-relief/sparse DEM for surface
   (non-converged-float32, Mira #72); threshold-straddling corr for GE masking;
   single-precision `-bi3f` for blockmedian; each interp mode for grdsample. RS2
   smoke MISSED the ALOS_haiti GE-0.14 edge — that cost a 3h sweep abort.
2. **Wire only sites that A/B bit-exact.** Edge sites that diverge keep the gmt
   fallback — do not wire them.
3. **Then one full-sweep gate** (Rule 14 tripwire).

This converts "wire-blind → 3h sweep → maybe abort" into "minutes of targeted A/B
→ wire-only-safe → one clean sweep." Edge risks are enumerated per round by a
read-only scoping pass (parallel agents) before wiring begins.
