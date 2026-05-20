"""utils_pygmt — PyGMT-backed re-implementations of gmtsar Python utilities.

Parallel to gmtsar/python/utils/. Each *_pygmt utility is a drop-in
replacement for the same-named utility in utils/, but uses PyGMT
(or pygmt.clib.Session, or xarray) instead of `subprocess.run("gmt …")`.

See PYGMT_ROADMAP.md at gmtsar/python/ for the phased migration plan.
"""
from .gmt_compat import (
    surface, grdcut, grdsample, grdimage, makecpt, grdtrack,
    blockmedian, blockmean, grdfilter, grd2xyz, xyz2grd, grdinfo,
    grdgradient, grdfill, grdlandmask, triangulate, grd2cpt, gmtinfo,
    grdedit, grdpaste, trend2d, grdmath,
    has_pygmt,
)

__all__ = [
    'surface', 'grdcut', 'grdsample', 'grdimage', 'makecpt', 'grdtrack',
    'blockmedian', 'blockmean', 'grdfilter', 'grd2xyz', 'xyz2grd', 'grdinfo',
    'grdgradient', 'grdfill', 'grdlandmask', 'triangulate', 'grd2cpt', 'gmtinfo',
    'grdedit', 'grdpaste', 'trend2d', 'grdmath',
    'has_pygmt',
]
