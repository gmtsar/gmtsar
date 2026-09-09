# v2.11.0 — first distributable Windows bundle: license attribution + published zip

Scope: `v2.10.3..v2.11.0`. Small in code, significant in what it
unlocks: v2.10.3 proved the self-contained bundle works (bundle-only
RS2 run, bit-identical output) but flagged public distribution as
blocked on third-party license collation. This release closes that and
publishes the bundle as a GitHub release asset.

## `do_write_licenses()` (new distribute step)

The bundle redistributes GMT (LGPL-3), GDAL, openblas, **ghostscript
(AGPL-3.0 — called out prominently)**, Git Bash + GNU coreutils + the
MSYS2 runtime (GPL-3.0+), the MSVC runtime, and GMTSAR itself (GPL-3).
The new step writes, into the bundle:

- `THIRD_PARTY_NOTICES.md` — attribution manifest with a per-package
  name/version/license table generated from the BUILD env's
  `conda-meta` (excluded from the packed pyenv, so captured at build
  time), plus source-availability pointers (this repo's tag for GMTSAR;
  gitforwindows.org/msys2.org; anaconda.org/conda-forge).
- `LICENSE.TXT` — GMTSAR's GPL-3 text at the bundle root.
- `git-bash/LICENSE.txt` — Git for Windows' license file.
- `licenses/` — per-package license texts where conda-forge installed
  them (`Library/share/licenses`).

Guarded by a new regression test (36 total across the Windows suites).

## Published artifact

`gmtsar-windows-<version>.zip` attached to this release on the fork:
unzip anywhere, run `gmtsar_shell.bat` (first run relocates the
bundled Python env via conda-unpack), and `p2p_processing` is on PATH
with no conda, no Git for Windows, no admin rights required.

Honest caveats carried forward from v2.10.3: verified on the dev host
(isolated-PATH 3-layer verify + a full bundle-only RS2 run,
`phasefilt.grd` complex-rms 0.000e+00 vs reference); a physically
different bare machine has not executed the bundle yet — first-report
feedback welcome.
