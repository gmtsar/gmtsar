#!/usr/bin/env python3
"""grdcut_wrapper — drop-in replacement for `gmt grdcut <in> -R... -G<out>` subprocess calls.

Bridges the existing csh-style pipeline that subprocess-calls
``gmt grdcut <in.grd> -R<w>/<e>/<s>/<n> -G<out.grd>`` over to the
in-process ``utils/gmt_grdcut_py.gmt_grdcut_py_file`` port (committed
v2.1.14, byte-identical to gmt C, 3.3× faster file→file, 151× faster
array-only).

Public API
----------
``grdcut_file(in_grd, out_grd, *, region)`` — file → file replacement
mirroring ``gmt grdcut <in> -R<w>/<e>/<s>/<n> -G<out>``.

  * ``region`` accepts either the GMT CLI string ``"w/e/s/n"`` or a
    4-tuple ``(w, e, s, n)`` of floats.

Env-gate
--------
``GMTSAR_GRDCUT_PY`` controls which path is used.

* ``GMTSAR_GRDCUT_PY=1`` (DEFAULT — in-process port). Per
  project_rules.md Rule 10 carve-out: byte-identical to gmt C on real
  data (17/17 parity tests pass, real RS2 DEM 3241×2881) AND faster
  than the subprocess fork/exec. The carve-out's "equal or faster
  AND byte-id" both hold.
* ``GMTSAR_GRDCUT_PY=0``: A/B parity-debugging fallback to the
  ``gmt grdcut`` subprocess.

Subprocess fallback rebuilds the exact gmt CLI the wrapper would have
replaced — same flags, same argument order — so the env-gate is a
clean A/B switch.

History
-------
* 2026-05-22 — initial wire-in (mira-volkov, mission "wire grdcut").
  Replaces 9 sites across utils/dem2topo_ra, utils/snaphu.py,
  utils/correct_merge_offset. See module docstring for the per-site
  list. make_dem:49 (gmt grdcut @earth_relief_*s) was intentionally
  NOT wired because the input is a GMT remote-data reference, not a
  local .grd file; gmt_grdcut_py only handles local files.
"""
from __future__ import annotations

import os
import subprocess
from typing import Sequence, Tuple, Union

# Module-load import — must succeed even with the env-gate off (the
# wrapper module is imported at top of each consumer).
from gmt_grdcut_py import gmt_grdcut_py_file

RegionLike = Union[str, Sequence[float], Tuple[float, float, float, float]]


def _py_enabled() -> bool:
    """In-process port is ON by default — see module docstring.

    Rule 10 carve-out qualifies: byte-identical to gmt C AND faster.
    Set ``GMTSAR_GRDCUT_PY=0`` for A/B subprocess fallback.
    """
    return os.environ.get("GMTSAR_GRDCUT_PY", "1") != "0"


def _parse_region(region: RegionLike) -> Tuple[float, float, float, float]:
    """Accept either GMT CLI string 'w/e/s/n' or a 4-tuple."""
    if isinstance(region, str):
        parts = region.split("/")
        if len(parts) != 4:
            raise ValueError(
                f"grdcut_wrapper: region string must be 'w/e/s/n', "
                f"got '{region}'"
            )
        try:
            return tuple(float(p) for p in parts)  # type: ignore[return-value]
        except ValueError as exc:
            raise ValueError(
                f"grdcut_wrapper: non-numeric region '{region}': {exc}"
            )
    seq = tuple(float(v) for v in region)
    if len(seq) != 4:
        raise ValueError(
            f"grdcut_wrapper: region must have 4 values, got {seq}"
        )
    return seq  # type: ignore[return-value]


def _region_str(region: Tuple[float, float, float, float]) -> str:
    """Format a 4-tuple back into the GMT CLI 'w/e/s/n' string for
    subprocess fallback. Use repr-precision (no rounding)."""
    return "/".join(repr(v) for v in region)


def grdcut_file(in_grd: str, out_grd: str, *, region: RegionLike) -> None:
    """Cut ``in_grd`` to ``region`` and write the result to ``out_grd``.

    Mirrors the csh ``gmt grdcut <in> -R<w>/<e>/<s>/<n> -G<out>``.
    Env-gate ``GMTSAR_GRDCUT_PY=0`` falls back to the subprocess for
    A/B parity debugging.
    """
    r = _parse_region(region)
    if _py_enabled():
        gmt_grdcut_py_file(in_grd, out_grd, region=r)
    else:
        # Rebuild the gmt grdcut CLI exactly (A/B fallback path).
        cmd = ["gmt", "grdcut", in_grd, f"-R{_region_str(r)}",
               f"-G{out_grd}"]
        res = subprocess.run(cmd, capture_output=True, text=True,
                             check=False)
        if res.returncode != 0:
            raise RuntimeError(
                f"gmt grdcut failed (rc={res.returncode})\n"
                f"  cmd: {' '.join(cmd)}\n  stderr: {res.stderr}"
            )
