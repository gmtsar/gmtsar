# AUDIT — gmt_surface_py gcd==1 algorithm bug, fixed (Mira #68)

Mission: confirm and fix the gcd(n_columns-1, n_rows-1)==1 divergence in
`utils/gmt_surface_py.py` flagged by Mira #61 (2026-05-22), and add the
required regression test fixture per project_rules.md Rule 11.

**Verdict: FIXED.** Root cause was NOT what the original finding guessed
(C does not run a special single-stride iteration schedule for gcd==1).
Instead, **C never actually solves a mutually-prime grid** except under
`-Qr`: `surface.c:2029-2047` unconditionally calls
`gmt_optimal_dim_for_surface()` (gmt_support.c:16944) BEFORE any gcd/stride
setup, and if a larger grid with a smaller `gmtsupport_guess_surface_time()`
exists, GMT silently EXPANDS the region/grid, solves the whole multigrid
hierarchy on the EXPANDED grid, and crops back to the user's `-R` when
writing the output (`surface_write_grid`, surface.c:947-961). The Python
port was missing this entire expand-then-crop step.

## Root cause detail

surface.c:2030-2047 (`GMT_surface`, before the pixel-registration trick and
before any `current_stride` computation):

```c
if (!Ctrl->Q.as_is) {	/* Meaning we did not give -Qr to insist on the given -R */
    struct GMT_GRID *G = ...;  /* container-only grid at user's -R/-I */
    if (surface_suggest_sizes (GMT, Ctrl, G, C.factors,
            G->header->n_columns-1, G->header->n_rows-1,
            GMT->common.R.registration == GMT_GRID_PIXEL_REG)) {
        gmt_M_memcpy (wesn, Ctrl->Q.wesn, 4, double);   /* EXPANDED region */
        Ctrl->Q.adjusted = true;
    }
}
```

`surface_suggest_sizes` (surface.c:1371) calls
`gmt_optimal_dim_for_surface` (gmt_support.c:16944), which brute-forces
`(nxg, nyg)` pairs of the form `2^a 3^b 5^c` in `[n, 2n]` and picks the one
minimizing `gmtsupport_guess_surface_time` (gmt_support.c:6424) — a proxy
for total multigrid work based on the gcd/stride hierarchy. If a pair beats
the user's `(n_columns-1, n_rows-1)`, the region is grown by
`(m_x//2, m_y//2)` nodes on the low side and `m_x - m_x//2` /
`m_y - m_y//2` on the high side (surface.c:1391-1400), where
`m_x = nxg_sug - n_columns_orig`, `m_y = nyg_sug - n_rows_orig`.

At write time (`surface_write_grid`, surface.c:947-961), if
`Ctrl->Q.adjusted`, the pad is increased by
`del_pad = irint((wesn_orig - header->wesn) * r_inc)` on each side and
`header->wesn` is reset to `wesn_orig` — i.e. a `grdcut` back to the
originally-requested window.

Once the EXPANDED `n_columns`/`n_rows` are used, the second gcd computation
at surface.c:2134 (`C.current_stride = gmt_gcd_euclid(C.n_columns-1,
C.n_rows-1)`) almost always yields `current_stride > 1` — the gcd==1 case
the port's `while True` loop at gmt_surface_py.py:920-927 was designed for
essentially never fires in real `gmt surface` runs.

### Confirmed empirically

`gmt surface` on an 8x13 grid (n_columns-1=7, n_rows-1=12, gcd(7,12)=1),
`-Vd`:

```
surface [INFORMATION]: Internally speed up convergence by using the larger
  region -R0/11.4285714286/0/10 (go from 7 x 12 to optimal 8 x 12, with
  speedup-factor 3)
surface [INFORMATION]: Grid domain: ... n_columns: 8 n_rows: 12 [...]
surface [INFORMATION]: Recompute data index for next iteration [stride = 2]
surface [INFORMATION]: Set finite-difference coefficients [stride = 2]
```

i.e. C solves a 9x13 grid (n-1 = 8x12, gcd=4 -> stride hierarchy
[4,2,1]... actually realized as [2,1] since current_nx/ny>=4 already at
stride=4... empirically [2,1]), then crops 1 column from the east to
return to the requested 8x13.

Also checked the TSX/ENVI dims named in the original finding:
- TSX 9440x6937 -> (9439, 6936), gcd=1 -> suggestion (9600, 7200),
  speedup-factor **3351x**.
- ENVI 5191x7579 -> (5190, 7578), gcd=6 -> suggestion (5400, 7680),
  speedup-factor **13x**.

Both cases were running a far-from-optimal stride hierarchy even before
considering the gcd==1 collapse — the ENVI case (gcd=6, not gcd=1) was
ALSO leaving a 13x convergence-speed improvement on the table under the
old port.

## Fix

`gmtsar/python/utils/gmt_surface_py.py`:

1. New helpers `_guess_surface_time(n_columns, n_rows)` (port of
   `gmtsupport_guess_surface_time`, gmt_support.c:6424-6490) and
   `_optimal_dim_for_surface(n_columns, n_rows)` (port of
   `gmt_optimal_dim_for_surface`, gmt_support.c:16944-17003 +
   `gmtsupport_compare_sugs`, gmt_support.c:6493-6498). Both use the
   "n-1" convention (one less than node count) matching the C call sites.
   Verified against the C `-Vd` log: `(7,12) -> (8,12)` with
   `speedup-factor 3` (Python: `(8, 12, 3.0)`); `(50,50) -> None` (no
   suggestion — confirms the existing gcd>1 tests at 51x51 are unaffected).

2. In `gmt_surface_py()`, BEFORE the pixel-registration trick: compute
   `(n_columns-1, n_rows-1)` from the user's `-R`/`-I`, call
   `_optimal_dim_for_surface`. If a suggestion exists, expand
   `xmin/xmax/ymin/ymax` per surface.c:1391-1400's `m//2` / `m%2`
   arithmetic (C integer division, verified to match Python `//` for
   non-negative `m`), and record `crop_x0, crop_y0, crop_nx, crop_ny` —
   the surface_write_grid del_pad equivalent.

3. At the end of `gmt_surface_py()` (both the normal-output path and the
   `z_rms < 1e-8` early-return path): if expansion happened, crop the
   solved grid back to `[crop_y0:crop_y0+crop_ny, crop_x0:crop_x0+crop_nx]`
   after the S-N flip — this is the node-registration equivalent of
   `surface_write_grid`'s pad-increase-and-wesn-reset.

4. **Known limitation (documented, hard-fails rather than silently
   wrong):** `pixel_reg=True` combined with a region expansion raises
   `NotImplementedError`. C's `del_pad` for pixel-registered output
   involves `irint` of a value that can be a half-integer
   (`crop_x0 - 0.5`), with rounding-mode-dependent (round-to-even)
   behaviour at exact .5 boundaries — not verified against C and not
   needed by any current gmtsar caller (none combine `-r` with a
   non-highly-composite grid). If this is ever hit in production, it
   raises loudly (Rule 4) rather than silently shifting the output grid by
   a node.

## Parity results

### New fixture: `test_gcd_1_small` (8x13 grid, gcd(7,12)==1)

`region=(0,10,0,10)`, `inc=(10/7, 10/12)`, `T=0.25`, N=60 scatter
(Gaussian + noise, seed 42):

| | before fix | after fix |
|---|---|---|
| RMS(py - gmt) | **1.257e-2** (12.6x over 1e-3 threshold) | **4.81e-4** |
| max\|diff\| | 6.18e-2 | 2.88e-3 |
| stride hierarchy | `[1]` (collapsed) | `[2, 1]` (matches C's `stride=2` log) |

`test_gcd_1_small` and `test_gcd_1_stride_hierarchy_not_collapsed` both
PASS. The latter directly asserts the mechanism (stdout contains "region
expanded for gcd hierarchy" and "stride=2"), not just the output RMS, so a
future regression that re-collapses the hierarchy but coincidentally keeps
RMS low would still be caught.

### Existing gcd>1 tests — all still pass

```
bin_py/tests/test_gmt_surface_py.py -k "not Benchmark"
18 passed (16 pre-existing + 2 new), 3 deselected (Benchmark, env-gated)
```

Includes `TestGmtSurfacePyParity` (5), `TestGmtSurfacePyPixelReg` (2),
`TestGmtSurfacePyBriggs` (2), `TestGmtSurfacePyAlgorithm` (5),
`TestGmtSurfacePyMultigrid` (2). All 51x51 (gcd=50) cases: `_optimal_dim_
for_surface(50,50)` returns `None` (no suggestion beats 50,50 — already
highly composite), so the expansion path is a no-op for these — confirmed
no behavioural change.

## Scope / what was NOT done (per mission instructions)

- `GMTSAR_SURFACE_INPROC` remains default OFF. This fix removes the
  gcd==1 correctness blocker, but the known 1.9-4x perf gap (PLAN.md,
  Mira #60-style optimization pass) is unaddressed — that is a separate
  follow-up mission.
- `test_gcd_1_envi_subset` (real-data ENVI subset with gcd==1) was not
  built — the synthetic `test_gcd_1_small` fixture is the Rule-11-required
  minimum and reproduces the bug deterministically at near-zero cost
  (<10ms). The real-data ENVI grid (5191x7579) actually has gcd=6, not
  gcd=1 (per the corrected dims check above) — constructing a *real-data*
  subset with gcd==1 would require cropping to an arbitrary off-by-one
  window, which adds complexity without adding coverage beyond what
  `test_gcd_1_small` already provides (the fix path is dimension-driven,
  not data-driven).

## Files changed

- `gmtsar/python/utils/gmt_surface_py.py` — `_guess_surface_time`,
  `_optimal_dim_for_surface` (new), region-expansion + crop wiring in
  `gmt_surface_py()`.
- `gmtsar/python/bin_py/tests/test_gmt_surface_py.py` — new
  `TestGmtSurfacePyGcd1` class with `test_gcd_1_small` and
  `test_gcd_1_stride_hierarchy_not_collapsed`.

Left uncommitted in the worktree branch for orchestrator review.
