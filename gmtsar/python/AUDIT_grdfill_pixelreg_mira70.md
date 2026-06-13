# AUDIT — gmt_grdfill_py pixel-registration bicubic fix (Mira #70, re-dispatch)

## TL;DR

Fixed the `_bcr_bicubic_sample` bug in `utils/gmt_grdfill_py.py` that
hard-coded `in_off=0.0` and used the donor's pixel-CENTRE range
(`donor_x[0]..donor_x[-1]`) for the range check, causing
`ValueError: donor grid does not cover query x range` whenever
`gmt_grdfill_py_file` was called with a **pixel-registered** donor
(`node_offset=1`) -- the `dem2topo_ra` mode=1 production case
(`coarse.grd` built via `gmt surface -r`).

All 23 tests in `bin_py/tests/test_gmt_grdfill_py.py` pass (22 prior +
1 new), including a synthetic pixel-registered-donor case that
**raises on pre-fix code** (verified by `git stash`) and is
**roundoff-identical to `gmt grdfill` subprocess output post-fix**
(`diff < 6e-8` on float64 intermediate values, exact after the
float32 cast to output).

## Root cause (confirmed)

`_bcr_bicubic_sample` (gmtsar/python/utils/gmt_grdfill_py.py, pre-fix
~line 394-444) had THREE bugs, all stemming from never reading
`donor_node_offset`:

1. **Range check used pixel centres, not the donor's `wesn`.** For a
   pixel-registered donor, `donor_x[0]/donor_x[-1]` are inset by
   `dx/2` from the donor's declared region (`wesn[XLO]/wesn[XHI]`).
   Any query in that half-cell margin (which, for `dem2topo_ra`,
   happens at EVERY hole near the input grid's edge, since `coarse.grd`
   is built with `-r` over the same `-R` as the input) raised
   `ValueError`.

2. **`in_off` formula was wrong even after adding the parameter.**
   gmt_bcr.c:130-131 computes
   `x = (xx - wesn[XLO]) * r_inc - xy_off`. `wesn[XLO]` is the donor's
   region edge, NOT `donor_x[0]` (the first pixel CENTRE). Substituting
   `wesn[XLO] = donor_x[0] - xy_off*dx` (gmt_grdio.c:2147,
   `xy_off = 0.5*registration`):
   ```
   x = (xx - (donor_x[0] - xy_off*dx))/dx - xy_off
     = (xx - donor_x[0])/dx + xy_off - xy_off
     = (xx - donor_x[0])/dx
   ```
   The `xy_off` terms CANCEL exactly, because `donor_x`/`donor_y` (as
   returned by `read_gmt_grd`) are ALWAYS pixel-centre coordinates,
   regardless of registration. **The normalised-coordinate formula is
   identical for gridline- and pixel-registered donors**; `in_off`
   (`donor_node_offset`) ONLY affects the `wesn` bounds used for the
   `gmtbcr_reject` clamp/NaN check (item 1). Verified empirically:
   at an exact donor pixel-centre `(qx,qy)=(5,5)=(cx[2],cy[2])`, the
   formula `(qx-donor_x[0])/dx` gives the integer `2` (correct,
   `tx=0`); the `-in_off` variant gave `1.5` (wrong, `tx=0.5`),
   and the resulting bicubic value diverged from `gmt grdtrack` by
   `0.34` even for a fully-interior point.

3. **Padded-array corner-most cells initialised to NaN instead of 0.0.**
   `gmt_grd_BC_set` (gmt_support.c, X-not-periodic/Y-not-periodic case)
   explicitly does not write the 3 corner-most pad cells in each of the
   4 corners ("Loaded all but three corner-most points at each
   corner."). GMT's padded grid buffer is `gmt_M_memory`-allocated
   (calloc, zero-initialised), so those cells are `0.0`. The port
   initialised the pad to `NaN`, so the NaN-skip branch
   (gmt_bcr.c:305-ish) spuriously dropped these contributions from the
   weighted average -- only observable for a query in the donor's
   ABSOLUTE geometric corner with `in_off=0.5` (both `tx,ty` land
   `col0=row0=-2` simultaneously, touching `(jno2,iwo2)`-type cells).
   With `node_offset=0` this combination never occurs (`tx=ty=0` at
   the corner), which is why the pre-existing `test_coarse_donor`
   (gridline donor) never caught it.

## Fix (gmtsar/python/utils/gmt_grdfill_py.py)

- `_bcr_bicubic_sample(..., donor_node_offset: int = 0)`:
  - `in_off = 0.5 * donor_node_offset` (gmt_bcr.c:130-131,
    gmt_grdio.c:2147/3102).
  - `wesn_xlo/xhi/ylo/yhi = donor_x[0]/donor_x[-1]/donor_y[0]/donor_y[-1]
    ∓ in_off*dx/dy` -- the donor's actual declared region.
  - `gmtbcr_reject`-equivalent (gmt_bcr.c:86-119): query beyond
    `wesn ± GMT_CONV4_LIMIT (1e-4)` -> output NaN for that point
    (silent, matches grdfill.c:557-560's WARNING-only behaviour, NOT
    a raise). Query within `GMT_CONV4_LIMIT` but outside `wesn` ->
    clamped onto the `wesn` border before normalisation.
  - Normalised coords: `fx=(qx-donor_x[0])/dx`, `fy=(donor_y[-1]-qy)/dy`
    (NO `in_off` term -- see item 2 above).
  - Padded BCR array (`d_pad`) initialised to `0.0`, not `NaN` (item 3).
- `_grid_fill(..., donor_node_offset: int = 0)` and
  `gmt_grdfill_py(..., donor_node_offset: int = 0)`: threaded through.
- `gmt_grdfill_py_file`: reads `donor_info['node_offset']` from
  `read_gmt_grd(donor_path)` and passes it as `donor_node_offset`.

## Test results

### Before fix (git stash applied to gmt_grdfill_py.py)
```
ValueError: donor grid does not cover query x range: qx in [0, 40] vs donor [1, 39]
```
(`TestGridFill.test_pixel_registered_donor`, errors=1)

### After fix
```
$ python3 -m unittest bin_py.tests.test_gmt_grdfill_py -v
... (23 tests) ...
Ran 23 tests in 2.4s
OK
```
including `test_pixel_registered_donor` (new), which builds a
gridline-registered 41x33 input with NaN holes at all 4 corners, 4
edge-midpoints, and an interior block, plus a pixel-registered (`-r`,
`node_offset=1`) 20x16 coarse donor covering the same `wesn=[0,40]x
[0,32]` (pixel centres inset by `dx_c/2=1, dy_c/2=1`). Asserts
`gmt_grdfill_py_file` output is byte-identical to `gmt grdfill
-Agcoarse.grd` subprocess output (`np.array_equal`, NaN==NaN).

Point-by-point diagnostic (float64 intermediate, before float32 cast),
all 4 absolute corners + interior + edge-interior queries against
`gmt grdtrack -G<donor>`:
```
(0,0)    gmt=0.126638  py=0.126638  diff=5.9e-09
(40,32)  gmt=0.182100  py=0.182100  diff=4.0e-09
(0,32)   gmt=-0.938965 py=-0.938965 diff=2.7e-08
(40,0)   gmt=1.204888  py=1.204888  diff=1.9e-08
(5,5)    gmt=-0.322717 py=-0.322717 diff=1.5e-13  (exact node, tx=ty=0)
(1,1)    gmt=0.290670  py=0.290670 diff=2.4e-13  (exact node)
```
All diffs are far below the float32 ULP at these magnitudes (~6e-8),
i.e. roundoff-identical after the float32 cast.

## Performance (unchanged from prior audit)

```
gmt subprocess (read+fill+write): 186-190 ms
py_file       (read+fill+write):  83-84 ms   (2.2-2.3x)
py_array      (fill only)      :  65 ms      (~3x)
```
(900x1200 float32, single-thread; `TestPerformance.test_wall_time_vs_subprocess`.)

## Known limitations / remaining gaps

1. **Wire-in not present in this worktree.** The prior audit
   (`AUDIT_grdfill_wirein_mira_2026-05-22.md`) describes a
   `_grdfill_dispatch` wrapper added to `utils/dem2topo_ra` (lines
   582, 645) and `bin_py/dem2topo_ra_py` (line 274) gated by
   `GMTSAR_GRDFILL_PY`. **That wiring is NOT present in this
   worktree** -- both call sites still use the bare subprocess
   `gmt grdfill topo_ra_tmp.grd -Agcoarse.grd -Gpixel.grd` / `grdfill(...)`.
   Either the prior session's edit was not committed/merged, or this
   worktree branched before it landed. Per the mission scope (item 5),
   re-adding the wire-in is explicitly OUT OF SCOPE for this
   dispatch -- the orchestrator handles wire-in + default-ON as a
   follow-up. This audit documents the discrepancy so the next session
   doesn't assume the wire-in already exists.

2. **Real ALOS_haiti data not re-verified in this session.** The
   prior audit's `qx in [1, 11303] vs donor [8.00567, 11296]` failure
   mode is the same bug class fixed here (range check against pixel
   centres instead of `wesn`), and the synthetic test reproduces the
   identical `ValueError` shape pre-fix
   (`donor grid does not cover query x range: qx in [0, 40] vs donor
   [1, 39]`). Per the mission's budget constraint, the full
   ALOS_haiti `topo_ra_tmp.grd` + `coarse.grd` re-stage (Rule 9:
   read-only `work/csh_test/`) was not repeated; the synthetic fixture
   is the regression oracle for this fix. If/when the wire-in lands,
   re-running the ALOS_haiti smoke from the prior audit (mode=1,
   PRF>=1000) is the integration-level confirmation.

3. **`-As` (greenspline) remains unported** (pre-existing,
   documented in the module docstring; not used by any in-scope
   consumer).

## Files touched

- `gmtsar/python/utils/gmt_grdfill_py.py` -- `_bcr_bicubic_sample`,
  `_grid_fill`, `gmt_grdfill_py`, `gmt_grdfill_py_file`:
  `donor_node_offset` parameter, corrected `in_off`/`wesn`/normalised-
  coordinate formulas, zero-initialised BCR pad corners.
- `gmtsar/python/bin_py/tests/test_gmt_grdfill_py.py` --
  `TestGridFill.test_pixel_registered_donor` (new, 23rd test).
- `gmtsar/python/AUDIT_grdfill_pixelreg_mira70.md` (this file).
