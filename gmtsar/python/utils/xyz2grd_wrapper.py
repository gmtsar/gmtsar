#!/usr/bin/env python3
"""xyz2grd_wrapper — drop-in replacement for the
``gmt xyz2grd <file> -ZTL<type> -r <par1> <par2> -G<out>`` subprocess calls
in ``utils/snaphu.py``.

Bridges the existing csh-style pipeline that subprocess-calls::

    gmt xyz2grd unwrap.out   -ZTLf -r {par1} {par2} -Gtmp.grd
    gmt xyz2grd conncomp.out -ZTLu -r {par1} {par2} -Gconncomp.grd

over to the in-process ``utils/gmt_xyz2grd_py.gmt_xyz2grd_py_file`` port
(Mission #71, byte-identical to gmt 6.4.0 on a real ALOS_haiti
phase_patch.grd subset, ~10x faster than the subprocess on a real
2826x3456 grid).

Public API
----------
``xyz2grd_file(in_path, out_path, *, par1, par2, ztype)`` — file → file
replacement mirroring ``gmt xyz2grd <in> -ZTL<ztype> -r <par1> <par2> -G<out>``.

Env-gate
--------
``GMTSAR_XYZ2GRD_PY`` controls which path is used.

* ``GMTSAR_XYZ2GRD_PY=1`` (DEFAULT): in-process port (``gmt_xyz2grd_py``).
* ``GMTSAR_XYZ2GRD_PY=0``: ``gmt xyz2grd`` subprocess fallback.

History
-------
* 2026-06-12 -- initial wire-in, default OFF (mira-volkov, Mission #71).
  See docs/audits/AUDIT_xyz2grd_mira71.md for unit-level parity results (bit-identical
  on real ALOS_haiti phase_patch.grd, ~10x faster).
* 2026-06-12 -- default flipped ON after RS2_SLC_Hawaii full-pipeline
  smoke (6/6 py-vs-csh SUCCESS, blessed diff PASS at v2.1.22).
"""
from __future__ import annotations

import os

# Module-load import — must succeed even with the env-gate off (the
# wrapper module is imported at top of each consumer).
from gmt_xyz2grd_py import gmt_xyz2grd_py_file
from gmtsar_lib import run as _run


def _py_enabled() -> bool:
    """In-process port is ON by default — see module docstring.

    Set ``GMTSAR_XYZ2GRD_PY=0`` to fall back to the ``gmt xyz2grd`` subprocess.
    """
    return os.environ.get("GMTSAR_XYZ2GRD_PY", "1") == "1"


def xyz2grd_file(in_path: str, out_path: str, *, par1: str, par2: str,
                 ztype: str) -> None:
    """Reshape ``in_path`` (a ``-ZTL<ztype>`` binary blob) to ``out_path``.

    Mirrors ``gmt xyz2grd <in_path> -ZTL<ztype> -r <par1> <par2> -G<out_path>``.
    Env-gate ``GMTSAR_XYZ2GRD_PY=1`` opts into the in-process port;
    default falls back to the ``gmt xyz2grd`` subprocess for A/B parity.

    Parameters
    ----------
    par1 : str
        ``-R<w>/<e>/<s>/<n>`` string (e.g. output of ``gmt grdinfo -I-``).
    par2 : str
        ``-I<xinc>/<yinc>`` string (e.g. output of ``gmt grdinfo -I``).
    ztype : str
        GMT ``-Z`` type code (``"f"`` for float32, ``"u"`` for uint8).
    """
    if _py_enabled():
        gmt_xyz2grd_py_file(in_path, out_path, par1=par1, par2=par2,
                             ztype=ztype)
    else:
        # Subprocess fallback: byte-identical to the pre-Mira-#71 call
        # site, including gmtsar_lib.run()'s non-fatal WARN-on-nonzero-rc
        # semantics (Rule 0 -- don't change the legacy default path's
        # error behaviour as a side effect of this wire-in).
        _run(f'gmt xyz2grd {in_path} -ZTL{ztype} -r {par1} {par2} -G{out_path}')
