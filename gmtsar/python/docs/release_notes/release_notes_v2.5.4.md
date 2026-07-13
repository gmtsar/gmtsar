# Release notes — v2.5.4 (2026-06-18)

## proj_ra2ll: gmt-C surface for raln/ralt → geocode-region parity (fixes Greece + TOPS_LA)

`proj_ra2ll` builds `raln.grd`/`ralt.grd` (the lon/lat-vs-range/azimuth lookup
grids) and then derives the geocoded output region from them via
`gmt gmtinfo llp -I<coarse>`, which snaps the region to a coarse (10×) lattice.

**Bug:** with `GMTSAR_SURFACE_INPROC=1`, those grids came from `gmt_surface_py`,
whose ~1.5e-5° edge roundoff can push the minimum longitude across one coarse
lattice cell — shifting the whole geocoded region by a full cell vs the csh
oracle. On `S1A_SLC_TOPS_Greece` this produced `corr_ll.grd` at 5600 cols /
W=19.85556 instead of csh's 5610 / W=19.85000, failing the geocoded `_ll`
products (`corr_ll.grd`, `corr_ll.png`, `phasefilt_mask_ll.png`). Same on
`S1A_SLC_TOPS_LA`. ra-domain products were always clean — only the projection
region diverged.

**Fix:** `proj_ra2ll` now builds raln/ralt with **gmt-C surface by default**
(matching csh exactly), since the region snap demands byte-parity the port
can't provide at the grid edge. The in-process port is still available via
`GMTSAR_PROJ_SURFACE_PY=1` for experimentation. (Note: this is independent of
the global `GMTSAR_SURFACE_INPROC` gate used elsewhere, e.g. dem2topo_ra.)

### Verification

- Greece corr_ll with fix: **W=19.8500 / 5610 cols, rms vs csh = 1.2e-6**
  (threshold 0.01) — matches csh.
- 6-case validation sweep (py-vs-csh), all **CLEAN**:
  - fixes: `S1A_SLC_TOPS_Greece`, `S1A_SLC_TOPS_LA` (were `_ll`-fail, now clean)
  - no-regression: `S1_Larsen_C`, `S1A_SLC_TOPS_COVE` (TOPS), `ALOS_Baja_EQ`,
    `ERS_Hector_EQ`.

### Matrix status

Full 21-case matrix now expected **20/21** py-vs-csh clean (Greece + TOPS_LA
resolved). Remaining:
- `S1_Ridgecrest_EQ` — the genuine no-DEM-corner artifact (ra-domain
  `phasefilt.grd` undefined where the DEM does not cover the grid). Harmless,
  left as documented.
- `ALOS_haiti` `phasefilt_mask_ll.png` — a **separate** root cause (py `corr.grd`
  differs from csh by up to 0.037, flipping ~181 pixels at the `GE 0.14` mask
  threshold → different geocoded extent). Confirmed NOT the proj_ra2ll/surface
  issue (re-geocoding both masks with this fix still diverges). Tracked as a
  correlation-chain parity follow-up.
