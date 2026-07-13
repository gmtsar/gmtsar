# AUDIT — gmt_grdfill_py wire-in attempt (Mira, 2026-05-22)

## TL;DR

`utils/gmt_grdfill_py` passes 22/22 isolated parity tests and runs 1.65–2.0×
faster than `gmt grdfill` subprocess on synthetic gridline-registered donors,
**BUT it does NOT work on the production dem2topo_ra mode=1 pipeline**.
The wire-in has been added at the three sites Mira #63 flagged
(`utils/dem2topo_ra` PRF<1000 + PRF>=1000 mode=1; `bin_py/dem2topo_ra_py`
mode=1) but is **default-OFF** (`GMTSAR_GRDFILL_PY=0`) until the gap closes.
The user's "default-ON unless investigated" directive triggered the
investigation; the investigation found a blocking gap, so default-OFF it is.

## Wire-in sites (file:line, post-edit)

| Site | Wrapper introduced | Subprocess call replaced |
|------|--------------------|--------------------------|
| `utils/dem2topo_ra:27`   | `_grdfill_dispatch` (import + helper) | — |
| `utils/dem2topo_ra:614`  | call site (PRF<1000, mode=1) | `run("gmt grdfill topo_ra_tmp.grd -Agcoarse.grd -Gpixel.grd")` |
| `utils/dem2topo_ra:679`  | call site (PRF>=1000, mode=1) | `run("gmt grdfill topo_ra_tmp.grd -Agcoarse.grd -Gpixel.grd")` |
| `bin_py/dem2topo_ra_py:51`  | `_grdfill_dispatch` (import + helper) | — |
| `bin_py/dem2topo_ra_py:303` | call site (mode=1) | `grdfill("topo_ra_tmp.grd -Agcoarse.grd -Gpixel.grd")` |

(Line numbers are approximate post-edit; grep for `_grdfill_dispatch`.)

## The gap

`gmt_grdfill_py._bcr_bicubic_sample` hard-codes `in_off = 0.0` (gmtsar/python/
utils/gmt_grdfill_py.py:429), which is correct for **gridline-registered**
donors (`-Ag` with `node_offset=0`). The function's own comment (line 424-428)
acknowledges this is wrong for the dem2topo_ra production case but does not
fix it:

> "We always treat donor as gridline-registered here — the dem2topo_ra
> production path passes pixel-registered topo_ra_tmp through the same
> bicubic at the same registration; the in_off applies in both axes if
> the donor is pixel-reg. We default to 0.0 (gridline); the file-wrapper
> passes the actual node_offset."

The file wrapper **does not** pass `node_offset` to `_bcr_bicubic_sample`
— there is no parameter. So a pixel-registered donor produces query
coordinates that fall outside the donor's pixel-centre range, and the
range-check at line 435 raises:

    ValueError: donor grid does not cover query x range:
      qx in [1, 11303] vs donor [8.00567, 11296]

## Smoke evidence (real ALOS_haiti temp.rat)

Staged from `work/python_test/ALOS_haiti/topo/temp.rat` (read-only;
Rule 9 respected — csh_test not touched). Generated `topo_ra_tmp.grd`
+ `coarse.grd` via `gmt triangulate` + `gmt blockmean | gmt surface` at
mode=1 PRF>=1000 settings (`region=0/11304/0/27648 rng=2 az_div=4
rng2=16 az_div2=32`).

| Path | Wall time | Result |
|------|-----------|--------|
| `gmt grdfill ... -Agcoarse.grd -Gpixel.grd` (subprocess) | **3.55 s** | `pixel.grd` 78,706,074 bytes, v_min=-314.45, v_max=2005.71 |
| `gmt_grdfill_py_file(..., algorithm='g', donor_path='coarse.grd')` | **1.52 s before raise** | **ValueError**, no output written |

**Byte-id comparison was not possible because the port did not produce
output.** This is exactly the "isolated parity vs in-sweep parity" failure
mode of Mira #15 → #18 — synthetic tests pass, real pipeline doesn't.

## What needs to happen before default-ON

1. **Port the registration math.** Add `donor_node_offset: int = 0` to
   `_bcr_bicubic_sample` and propagate from `gmt_grdfill_py_file` based on
   `info['node_offset']` returned by `read_gmt_grd`. The C code reads it via
   `GMT_GRID->header.registration` and applies `in_off = 0.5` for pixel-reg
   in `gmt_bcr_get_z` (cf. gmt_bcr.c:130-131 BCR_PIX_OFFSET).
2. **Port the boundary handling.** The C code lets out-of-donor queries
   fall back to the natural-BC pad zone (silently). The port raises. Either
   match the C silent behaviour (and document it) OR keep the raise behind
   a strict flag — but the dem2topo_ra-driven production case will hit
   out-of-coverage queries every time, so raising blocks production.
3. **Add a production-case parity test.** The existing
   `test_coarse_donor` uses `np.linspace(x[0], x[-1], cnx)` with
   `node_offset=0` — that's gridline-registered with aligned edges,
   which is the *exact case that already passes*. Add a test using
   `gmt blockmean` + `gmt surface ... -r` on real xyz to produce a
   pixel-registered coarse donor whose centres are inset from the
   input's by `inc/2`, then assert byte-id with gmt grdfill subprocess.
4. **Then** flip the default to `GMTSAR_GRDFILL_PY=1` and the original
   carve-out (Rule 10 byte-id + faster) applies.

## Files touched

- `gmtsar/python/utils/dem2topo_ra` — added `_grdfill_dispatch` helper +
  import block, replaced 2 `run("gmt grdfill ...")` calls.
- `gmtsar/python/bin_py/dem2topo_ra_py` — added `_grdfill_dispatch`
  helper + import block, replaced 1 `grdfill(...)` call.
- `gmtsar/python/AUDIT_grdfill_wirein_mira_2026-05-22.md` (this file).

## Verification

- `python3 -m unittest bin_py.tests.test_gmt_grdfill_py` — 22/22 OK
  (isolated tests still green; the wire-in does not regress them).
- Wire-on smoke (ALOS_haiti mode=1, real temp.rat) — RAISES,
  documented above.
- Wire-off smoke (same inputs, GMTSAR_GRDFILL_PY unset = default-OFF) —
  legacy `gmt grdfill` subprocess path, identical to pre-wire behaviour.

## Wall-time savings — projected, not realised

If/when the gap closes:
- Per-case mode=1 dem2topo_ra: ~2 s saved per grdfill call
  (3.55 s gmt → ~1.5 s py). dem2topo_ra is called once per topo build
  per sweep case, so 2 s × N_mode1_cases.
- However, **NO case in `tests/configs/*.py` uses `topo_interp_mode=1`**
  (all 21 staged configs set it to 0). The wall-time savings in the
  current sweep matrix is **0 s**. The port only helps users who set
  mode=1 manually (rare in tight geometry cases).

This makes the wire-in a low-priority follow-up: fix the gap if/when a
mode=1 production case is added to the sweep, otherwise the legacy
subprocess path is fine.

## Commit-ready

Y for default-OFF wire-in (no behaviour change, conservative scaffolding).
N for default-ON (requires the gap fix above first).
