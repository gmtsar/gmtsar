# GMT netCDF attribute spec (required for downstream gmt modules)

Extracted 2026-07-13 from `PLAN.md` §9, which is otherwise archived to
`docs/reports/` (superseded by `docs/PATHWAY_FORWARD.md`) — this section
is kept live because it's genuinely still-referenced technical
documentation, not history. Any Python code that writes a `.grd` file
GMT itself will later read (`grdinfo`, `grdmath`, `grdcut`, `grdtrack`,
`grd2xyz`, `xyz2grd`, ...) must emit these attributes so GMT treats the
file identically to one it wrote itself.

Origin: derived by `ncdump -h` on a sample of GMT-written files (GMT
4.5.7, 6.3.0, 6.4.0) shipped with this repo. Reference implementation:
`utils/gmt_grd_io.py`'s `write_gmt_grd()` — a pure-Python (numpy +
netCDF4) writer. Required because xarray's default `to_netcdf()` writes
a netCDF GMT *can* open but with missing `actual_range` (`grdinfo`
reports `v_min=0 v_max=0`) and missing `node_offset` (pixel-registered
grids get silently half-cell-shifted by `grdcut`). Any replacement for
`grdmath`, `grdcut`, `xyz2grd` etc. that produces `.grd` output must
route through `write_gmt_grd`, not `xr.Dataset.to_netcdf`. Parity tests:
`bin_py/tests/test_gmt_grd_io.py`.

## Global attributes

| Attribute | Required? | Value | Why GMT needs it |
|---|---|---|---|
| `Conventions` | yes | `"CF-1.7"` (modern) or `"COARDS/CF-1.0"` (legacy) | reader dispatch — without it, GMT falls back to no-conventions mode |
| `title` | recommended | free string | `grdinfo: Title:` field |
| `history` | recommended | free string (typically the command line) | `grdinfo: Command:` field |
| `description` | recommended | free string (may be `""`) | reserved by GMT 6+ |
| `GMT_version` | recommended | free string | provenance; reported by `grdinfo` |
| `node_offset` | **REQUIRED FOR PIXEL** | int32 `1` | pixel-vs-gridline registration switch. Omit for gridline (default). Silent half-cell shift in `grdcut` etc. if missing on a pixel-reg grid. |

## Coordinate variables (`x`/`y` for Cartesian, `lon`/`lat` for geographic)

| Attribute | Required? | Value | Why |
|---|---|---|---|
| dtype | yes | `float64` (`f8`) | GMT's reader assumes double-precision coords |
| `long_name` | recommended | `"x"`/`"y"`/`"longitude"`/`"latitude"` | CF convention; reported by `grdinfo` |
| `units` | **REQUIRED FOR GEOGRAPHIC** | `"degrees_east"` / `"degrees_north"` | switches `grdinfo` to "Geographic grid" mode. Without it, lon/lat grids are reported as Cartesian. |
| `axis` | recommended | `"X"` / `"Y"` | CF axis hint |
| `actual_range` | strongly recommended | `[min, max]` float64 | propagated by `grdmath`; without it some chains lose track of bounds |

## Data variable (`z`)

| Attribute | Required? | Value | Why |
|---|---|---|---|
| dtype | yes | `float32` (`f4`) | this is GMT's `nf` format — what `grdmath`, `xyz2grd`, etc. always emit |
| `long_name` | recommended | `"z"` | CF convention |
| `_FillValue` | yes | float32 NaN (`NaNf`) | GMT marks missing data with NaN. Other sentinels break `grdmath` and `grdfill` |
| `actual_range` | **REQUIRED** | `[min, max]` float64 over non-NaN values | without this, `grdinfo` reports `v_min=0 v_max=0` for the data variable. Silent failure mode. |

## Dimension order / orientation

- `z(y, x)` — y is the slowest dimension (rows), x is the fastest (cols).
- y values MUST be monotonically ASCENDING in the file. Row 0 is at
  `y_min`. (GMT's `grd2xyz` then emits the file top-down — flipping
  internally — but on disk the storage is y-ascending.)
- x values MUST be monotonically ascending in the file.
- Spacing MUST be uniform along each axis. GMT tolerates ~1e-4
  relative non-uniformity; `write_gmt_grd` enforces 1e-6.
