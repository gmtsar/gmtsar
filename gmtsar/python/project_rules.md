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
