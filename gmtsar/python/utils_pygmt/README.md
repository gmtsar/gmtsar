# utils_pygmt — PyGMT-backed utility ports

Parallel to `gmtsar/python/utils/`. Each `*_pygmt` script is a drop-in
replacement for the same-named utility in `utils/`, with `subprocess.run("gmt …")`
replaced by PyGMT calls (or `pygmt.clib.Session.call_module`, or
`xarray`/`numpy` for grdmath).

See [PYGMT_ROADMAP.md](../PYGMT_ROADMAP.md) for the full phased plan.

## What lives here right now

| File | Phase | Status |
|---|---|---|
| `gmt_compat.py` | 1, 2, 3, 4 | scaffolded — all 24 GMT module wrappers + `GMTSARFigure` |
| `dem2topo_ra_pygmt` | 0 (pilot) | full port, syntax-clean, not yet end-to-end tested with a real case |
| `__init__.py` | — | re-exports the public surface of gmt_compat |

## How `gmt_compat.py` is organised

Four backends, picked per-call:

1. **Direct PyGMT wrapper** (when one exists): `pygmt.surface(...)`,
   `pygmt.grdcut(...)`, etc. For now, every wrapped subcommand routes
   through option 2 instead, because option 2 lets us keep CLI argument
   strings verbatim across the port (minimises diff per call site).
2. **`pygmt.clib.Session.call_module(name, args)`**: pass the legacy CLI
   arg string straight to libgmt. Bypasses subprocess (~10× faster);
   keeps the exact argument grammar. Default for everything.
3. **`xarray`/`numpy` fast-path**: only for `grdmath` simple ops
   (FLIPUD, FLIPLR, NEG, ABS, SQRT, LOG, EXP, MUL, ADD, SUB, DIV).
   Bit-identical to GMT for these. Falls through to option 2 if the
   expression isn't recognised.
4. **`subprocess.run("gmt …")` fallback**: kicks in automatically if
   PyGMT isn't importable (`has_pygmt() == False`), OR if the call
   involves a shell pipe to an external binary (e.g.
   `gmt grd2xyz a.grd | SAT_llt2rat …` — PyGMT can't pipe to an
   external process cleanly).

So a port-site author writes the same `gmt_compat.surface("temp.rat -R… -I… …")`
call regardless of which backend ends up handling it.

## Pattern for adding a new port

Take an existing utility, e.g. `utils/filter`, and:

1. Copy it to `utils_pygmt/filter_pygmt`.
2. Add: `from gmt_compat import grdmath, grdimage, makecpt, …` for whichever
   subcommands the utility uses.
3. Replace every `run('gmt foo arg1 arg2 …')` with
   `gmt_compat.foo("arg1 arg2 …")`. Leave the CLI string intact.
4. For chained pipes (`gmt A … | gmt B …` or `gmt … | external_binary`),
   either keep `subprocess.run(...)` for now, or split into a temp file
   + two separate calls.
5. For plotting chains (`gmt grdimage … > A.ps; gmt psscale … >> A.ps;
   gmt psconvert -Tf A.ps`), replace with a `GMTSARFigure` instance.
6. Confirm with `bash gmtsar/python/tests/wizard.sh` (AST + import sanity).
7. Run the relevant case via `bash gmtsar/python/tests/run_one.sh <case>`
   to verify drop-in equivalence.
8. Once green, add a stanza to PYGMT_ROADMAP.md decision log.

## Known gaps

- Shell pipelines that cross GMT ↔ external binary (e.g.
  `grd2xyz | SAT_llt2rat`) stay subprocess. `dem2topo_ra_pygmt` shows
  the pattern.
- Binary stdin/stdout chains between two GMT modules
  (`gmtconvert -bi5d -bo3d | blockmedian -bi3d -bo3d`) currently also
  stay subprocess. clib.Session could chain them via a tempfile, but
  the speedup vs. the existing subprocess pipe is marginal.
- The `grdmath` fast-path covers only single-operator forms; multi-step
  RPN (`A B MUL C ADD = D.grd`) falls through to clib.Session. That's
  fine for correctness; the xarray rewrite is still pending site-by-site
  for the gnarlier expressions.

## Performance posture

Today's full-sweep wall time is bounded by the 21-case 3 h sweep,
dominated by the gmtsar C binaries (xcorr, phasediff, esarp) and the
piped pipelines — not by `gmt` subprocess overhead. The ~10-25 min that
clib.Session+PyGMT could shave off is marginal in the context of the
full pipeline. The real prize is **reliability + testability**:
per-site Python exceptions, mockable calls, no more `gmt: not found`
PATH surprises.
