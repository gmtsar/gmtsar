# PyGMT incorporation roadmap

**Status**: planning — not started.
**Owner**: TBD (proposed: kai-fischer for the refactor PRs, lars-eriksson for the audit gates).
**Last updated**: 2026-05-20.

## Goal

Replace the ~384 `subprocess.run("gmt …")` call sites in
`gmtsar/python/utils/` with native [PyGMT](https://www.pygmt.org/) calls
where a wrapper exists, and with `xarray`/`numpy` rewrites where it
doesn't. End state: the Python framework no longer shells out to `gmt`
on the happy path; only the residual non-GMT external binaries (snaphu,
the gmtsar C tools) remain as subprocess calls.

Benefits, in priority order:

1. **Reliability** — Python exceptions instead of scraping stderr; no more
   `/bin/sh: 1: gmt: not found` PATH surprises; per-site error context.
2. **Testability** — PyGMT calls can be mocked in unit tests; subprocess
   invocations cannot, cheaply.
3. **Performance** — each subprocess `gmt …` call costs ~10-30 ms of
   fork+exec+lib-load overhead. On a full 21-case sweep (~50 000 gmt
   calls) this is ~10-25 minutes against a 3 h baseline. Marginal, not
   the main motivator.
4. **Type safety / IDE** — function signatures, autocomplete, static
   analysis.

Not a goal: replicate every CLI nuance of every GMT module. Some sites
will use `pygmt.clib.Session.call_module` to pass the legacy argument
string verbatim — fine for grdmath in particular.

## Current state (inventory as of v1.12.3)

Survey command:
```bash
grep -rhE "(^|[^a-z_])gmt [a-z][a-z]*" gmtsar/python/utils gmtsar/python/tests \
  | grep -oE 'gmt [a-z][a-z2]*' | sort | uniq -c | sort -rn
```

**384 call sites** across 31 distinct GMT subcommands. Coverage table:

| Coverage | Subcommands | Sites |
|---|---|---|
| ✓ Direct PyGMT wrapper | `surface`, `grdcut`, `grdsample`, `grdimage`, `makecpt`, `grdtrack`, `blockmedian`, `blockmean`, `grdfilter`, `grd2xyz`, `xyz2grd`, `grdinfo`, `grdgradient`, `grdfill`, `grdlandmask`, `triangulate`, `grd2cpt`, `gmtinfo` | ~210 |
| ✓ `Figure`-method | `psconvert`→`Figure.psconvert`, `psscale`→`Figure.colorbar`, `psxy`→`Figure.plot`, `pstext`→`Figure.text`, `gmt set`→`pygmt.config` | ~62 |
| ⚠ **NOT wrapped (any form)** | `grdmath` (93), `grdedit` (13), `grdpaste` (3), `trend2d` (3) | **112 (29%)** |
| ? Unknown | `gmtconvert` (10) | 10 |

### The `grdmath` blocker

`gmt grdmath` is a Reverse-Polish stack calculator
(`gmt grdmath A B MUL 2 DIV = C.grd`). PyGMT has no Python wrapper.
Three options per call site:

1. **`xarray`/`numpy` rewrite** — cleanest, idiomatic Python. Every site
   is unique; cannot be regex-translated. Example:
   ```python
   # before:  gmt grdmath unwrap_mask.grd $wavel MUL -79.58 MUL = los.grd
   # after:
   import xarray as xr
   da = xr.open_dataset('unwrap_mask.grd')['z']
   (da * wavel * -79.58).rename('z').to_netcdf('los.grd')
   ```

2. **`pygmt.clib.Session.call_module`** — preserves the RPN string
   verbatim, no rewrite of the math. Trade-off: still a C-library call
   (no numpy fastpath), but no subprocess overhead, and Python-side
   exceptions. Example:
   ```python
   with pygmt.clib.Session() as ses:
       ses.call_module('grdmath',
                       'unwrap_mask.grd 0.236 MUL -79.58 MUL = los.grd')
   ```

3. **Keep `subprocess`** for grdmath only — pragmatic, defers the work.

`grdedit` and `grdpaste` can use option 2 if option 1 isn't natural.
`trend2d` (3 sites in `fitoffset.py`) is small enough for option 1 today.

## Risks

- **PyGMT API churn** — v1.0 (early 2026) introduced breaking changes;
  pin a minor version in `requirements.txt`.
- **Dependency layer** — `pygmt` requires `libgmt` + `gmt` modern mode.
  Already present in our conda env, but ship/install scripts must
  declare it.
- **Reviewer cost** — a single PR touching all 384 sites is
  unreviewable. Must stage incrementally; each phase a separate PR with
  the 21-case sweep gating merge.
- **Numerical drift** — every site rewritten in numpy/xarray is a chance
  to introduce a sign-convention, NaN-handling, or float-precision bug.
  Today's threshold of `0.1` RMS for most grids may not catch sub-pixel
  rewrite drift; consider tightening per-site or adding bit-exactness
  checks for critical sites.
- **Modern-mode-only** — PyGMT requires GMT 6+ modern mode. Spot-check
  every call site for `--gmtset` / `gmt set` patterns that imply classic
  mode; convert before porting.

## Phased plan

Each phase is a separate PR, gated by the full 21-case from-scratch
sweep + `tests/wizard.sh` passing.

| Phase | Scope | Sites | Risk | Est. time |
|---|---|---|---|---|
| **0 — Pilot** | One leaf utility: `dem2topo_ra` (uses `surface`, `grdcut`, `grdsample`, `grdimage`). Single file change; validates dev workflow, dependency declaration, test surface | ~30 | low | 1 wk |
| **1 — Easy wins** | All directly-wrapped subcommands in `utils/` except `dem2topo_ra` (already done) | ~150 | low | 2 wk |
| **2 — clib.Session** | `grdedit` + `grdpaste` + `trend2d` via direct C-library calls (no rewrite of math) | ~20 | medium | 1 wk |
| **3 — grdmath** | The 93 grdmath sites, ported to `xarray`/`numpy`. Per-utility, smallest-first. Bit-exactness gate where possible | 93 | **high** | 4-6 wk |
| **4 — Figure plotting** | `psxy`/`pstext`/`psscale`/`psconvert` rewrites for the geocode + post-processing visualisation paths | ~62 | medium | 2 wk |

Total: ~10 calendar weeks if pursued one phase at a time alongside
ongoing work. Acceptable to pause between phases for unrelated releases.

### Phase 0 — pilot, in detail

Target: `gmtsar/python/utils/dem2topo_ra`. Why this file:

- 30-ish gmt calls covering 4 of the easiest-to-wrap modules.
- Currently the long pole on csh side of `ALOS2_SCAN_SSAF`
  (surface fit stride takes ~70 min per subswath). If PyGMT shaves real
  wall time here, that validates the bigger plan economically. If it
  doesn't, the case for phases 1-4 weakens and we re-evaluate.
- Easy verification: every existing case in the 21-case sweep exercises
  `dem2topo_ra`, so a regression shows up immediately in the scorecard.

Deliverables:
- `gmtsar/python/utils/dem2topo_ra` rewritten to use `pygmt.surface`,
  `pygmt.grdcut`, `pygmt.grdsample`, `pygmt.Figure.grdimage`.
- `requirements-pygmt.txt` adding `pygmt>=0.14,<1.0` (or whichever
  minor we pin after a compatibility check).
- `install.sh` extended to install pygmt if `--pygmt` flag is passed.
- A regression-test diff: scorecard before vs after must be all-PASS.
- Wall-time delta measured per case and recorded in
  `release_notes_<next>.md`.

Exit criterion for Phase 0: scorecard unchanged (21/21 PASS), wall
time same-or-better, no new dependency conflicts on the conda env.

## Open questions

1. **PyGMT version pinning**: v0.14 (last 0.x), v1.0 (Mar 2026 with API
   breaks), or floating-latest? Recommend pin to specific minor in
   Phase 0; revisit per release.
2. **Conda vs pip install** of pygmt: should `install.sh` prefer
   `conda install -c conda-forge pygmt`? Probably yes — pygmt depends
   on `libgmt` which conda-forge ships compatible with our GMT 6.4.
3. **Bit-exactness budget**: today the test framework accepts
   1e-2-RMS rewrites. Phase 3 will likely produce true bit-exact
   results for grdmath sites (numpy float64 ↔ GMT float64), but for
   surface/grdcut sites the answers may differ by 1-2 ulp. Lock the
   tolerance up front or accept the existing thresholds?
4. **Keep the subprocess fallback?** Consider a wrapper
   `gmtsar_lib.gmt_call(cmd: str)` that uses PyGMT if available and
   falls back to subprocess. Reduces the install burden during the
   migration; adds maintenance burden afterwards.

## Decision log

- **2026-05-20**: Initial evaluation. 71% of call sites have direct
  PyGMT wrappers; 29% (mostly grdmath) need rewrite or clib.Session.
  Verdict: **worth doing, incremental not big-bang**, slot Phase 0 into
  the release cycle after the upstream PR merges.

- **2026-05-20 (best-effort scaffolding)**: Built `gmtsar/python/utils_pygmt/`
  with:
  - `gmt_compat.py` — single-shim entry point for all 24 GMT modules used
    in the framework. Routes through `pygmt.clib.Session.call_module`
    when PyGMT is installed; falls back to `subprocess.run("gmt …")`
    when it isn't. Includes an `xarray` fast-path for `grdmath` simple
    ops (FLIPUD, FLIPLR, NEG, ABS, SQRT, LOG, EXP, MUL, ADD, SUB, DIV)
    that's bit-identical to GMT.
  - `dem2topo_ra_pygmt` — Phase 0 pilot full rewrite. Drop-in for
    `utils/dem2topo_ra`. Uses PyGMT for surface/grdcut/triangulate/blockmean/
    grdfill/grd2cpt; xarray for FLIPUD; the Figure-class for plotting;
    keeps `subprocess` for the two pipelines that cross to external
    binaries (grd2xyz→SAT_llt2rat, gmtconvert→blockmedian).
  - `GMTSARFigure` class — replaces `grdimage → psscale → psconvert`
    chains with a single Figure-class flow.
  - Wizard extended with a 24-symbol import check on the compat shim.
  - Verified: PyGMT 0.8.0 in conda env; FLIPUD and MUL xarray fast-paths
    produce bit-exact results vs reference; `has_pygmt() == True` in
    conda env, `False` in system Python (fallback path active there).
  Not done (deferred to per-utility ports as they're touched):
  - The other ~25 `utils/*` files that use `gmt …` still call subprocess.
    To migrate one, `from gmt_compat import …` and replace
    `run("gmt foo ARGS")` with `foo("ARGS")`. Pattern documented in
    `utils_pygmt/README.md`.
  - End-to-end correctness check via the 21-case sweep — not run in this
    session per scope agreement. Required before a Phase 0 release.

## Out of scope

- Replacing `snaphu` calls (different external binary, no Python
  equivalent in PyGMT).
- Replacing the gmtsar C-binary calls (`fitoffset`, `xcorr`,
  `phasediff`, `resamp`, etc.) — those are not GMT, not in PyGMT, and
  remain subprocess for the foreseeable future.
- Rewriting csh-side bundled READMEs. The csh pipeline keeps shelling
  out to `gmt`; this roadmap only affects the Python framework.
