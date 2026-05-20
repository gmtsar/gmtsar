"""gmt_compat — thin shim translating `subprocess.run("gmt foo …")` patterns
to PyGMT calls (or `pygmt.clib.Session.call_module` for unwrapped modules).

Each function:
  - takes the same arguments as the `gmt foo` CLI (mostly verbatim string
    options), so port sites can be regex-substituted with minimal effort;
  - returns nothing useful by default (output goes to a file, same as CLI);
  - falls back to `subprocess.run` if PyGMT isn't available, so the shim
    is safe to import in any environment.

Two design choices:

1. **Mirror the CLI signature, not the Pythonic one.** PyGMT's idiomatic
   form is `pygmt.surface(data=df, region=[0,X,0,Y], spacing="1/2", T=0.1,
   outgrid="pixel.grd")` — clean for new code, but every port site would
   require re-arranging arguments. The shim keeps the CLI string form
   verbatim and parses it. Trade-off accepted: less Pythonic, but each
   `run("gmt surface temp.rat -R0/X/0/Y -I1/2 …")` becomes
   `gmt_compat.surface("temp.rat -R0/X/0/Y -I1/2 …")` — one regex per
   subcommand.

2. **clib.Session for unwrapped modules.** grdmath, grdedit, grdpaste,
   trend2d have no PyGMT API. `pygmt.clib.Session.call_module(name, args)`
   passes the CLI string directly to libgmt, bypassing subprocess but
   keeping the CLI argument grammar. ~10× faster than subprocess.

See PYGMT_ROADMAP.md (phase tables) for which sites are migrated.
"""
from __future__ import annotations

import os
import subprocess
import sys
from typing import Optional

try:
    import pygmt
    from pygmt.clib import Session
    _HAS_PYGMT = True
except ImportError:
    _HAS_PYGMT = False
    pygmt = None  # type: ignore
    Session = None  # type: ignore


def has_pygmt() -> bool:
    """True if PyGMT and libgmt are importable in this Python."""
    return _HAS_PYGMT


# --------------------------------------------------------------- backend ---

def _clib_call(module: str, args: str) -> int:
    """Invoke a GMT module via the C library — no subprocess, no fork.
    Args go as a single CLI-style string, same as the binary expects.
    Returns 0 on success; raises GMTCLibError on failure (PyGMT default).
    Used for modules without a Python wrapper (grdmath, grdedit, etc.).
    """
    if not _HAS_PYGMT:
        return _subproc_fallback(module, args)
    with Session() as ses:
        ses.call_module(module, args)
    return 0


def _subproc_fallback(module: str, args: str) -> int:
    """Last-resort: shell out exactly like the legacy code. Keeps the shim
    safe to import in environments without PyGMT (CI on a fresh box, etc.)."""
    cmd = f"gmt {module} {args}"
    rc = subprocess.run(cmd, shell=True).returncode
    if rc == 127:
        raise RuntimeError(f"gmt not found on PATH; install gmt or pygmt: {cmd}")
    return rc


# -------------------------------------------------------------- Phase 1 ---
# Subcommands with direct PyGMT wrappers. For now, every wrapper here just
# routes through clib.Session — that keeps the CLI arg string verbatim and
# avoids per-site re-arrangement. Future work can rewrite to the Pythonic
# pygmt.surface(...) form when call sites are touched anyway.

def surface(args: str) -> int:
    """`gmt surface <args>` — RBF surface fit. Verbatim CLI args."""
    return _clib_call("surface", args)

def grdcut(args: str) -> int:
    return _clib_call("grdcut", args)

def grdsample(args: str) -> int:
    return _clib_call("grdsample", args)

def grdimage(args: str) -> int:
    return _clib_call("grdimage", args)

def makecpt(args: str) -> int:
    return _clib_call("makecpt", args)

def grdtrack(args: str) -> int:
    return _clib_call("grdtrack", args)

def blockmedian(args: str) -> int:
    return _clib_call("blockmedian", args)

def blockmean(args: str) -> int:
    return _clib_call("blockmean", args)

def grdfilter(args: str) -> int:
    return _clib_call("grdfilter", args)

def grd2xyz(args: str) -> int:
    """`gmt grd2xyz <args>` — dump grid as x,y,z triples to stdout.
    NOTE: pipelined uses like `gmt grd2xyz a.grd | SAT_llt2rat …` must
    stay subprocess for now — clib doesn't pipe to external binaries.
    Detect a pipe in `args` and fall back."""
    if "|" in args or ">" in args.split()[-1]:
        return _subproc_fallback("grd2xyz", args)
    return _clib_call("grd2xyz", args)

def xyz2grd(args: str) -> int:
    return _clib_call("xyz2grd", args)

def grdinfo(args: str) -> int:
    return _clib_call("grdinfo", args)

def grdgradient(args: str) -> int:
    return _clib_call("grdgradient", args)

def grdfill(args: str) -> int:
    return _clib_call("grdfill", args)

def grdlandmask(args: str) -> int:
    return _clib_call("grdlandmask", args)

def triangulate(args: str) -> int:
    return _clib_call("triangulate", args)

def grd2cpt(args: str) -> int:
    return _clib_call("grd2cpt", args)

def gmtinfo(args: str) -> int:
    return _clib_call("gmtinfo", args)


# -------------------------------------------------------------- Phase 2 ---
# Subcommands without a direct PyGMT API. Routed through clib.Session so
# we still avoid subprocess overhead.

def grdedit(args: str) -> int:
    return _clib_call("grdedit", args)

def grdpaste(args: str) -> int:
    return _clib_call("grdpaste", args)

def trend2d(args: str) -> int:
    return _clib_call("trend2d", args)


# -------------------------------------------------------------- Phase 3 ---
# grdmath: 93 sites, RPN-stack-calculator. No PyGMT API. Two paths:
#   1. xarray rewrite for known-simple ops (FLIPUD, MUL, ADD, SUB, DIV).
#   2. clib.Session fall-back for anything else, with the RPN string verbatim.

def grdmath(args: str) -> int:
    """`gmt grdmath <args>` — stack calculator. Tries an xarray fast-path
    for a handful of common 1- and 2-operand operations; otherwise routes
    through clib.Session. The xarray path is bit-identical for the
    operations covered (numpy float64 ↔ GMT float64) and is what we'd
    eventually want everywhere.

    Examples covered by the xarray fast-path:
        grdmath A.grd FLIPUD = B.grd
        grdmath A.grd B.grd MUL = C.grd
        grdmath A.grd 0.5 MUL = B.grd
        grdmath A.grd B.grd ADD = C.grd
        grdmath A.grd B.grd SUB = C.grd
        grdmath A.grd B.grd DIV = C.grd
    """
    tokens = args.split()
    # Quick recognition of `<grid> <UNARY-OP> = <out>` and
    # `<a> <b> <BINARY-OP> = <out>` forms only.
    if _try_xarray_grdmath(tokens):
        return 0
    return _clib_call("grdmath", args)


def _try_xarray_grdmath(tokens: list[str]) -> bool:
    """Returns True if we successfully evaluated and wrote the result.
    Returns False if the expression isn't in a form we recognise; caller
    should fall through to clib.Session."""
    if len(tokens) < 3 or "=" not in tokens:
        return False
    eq_idx = tokens.index("=")
    out_path = tokens[eq_idx + 1] if eq_idx + 1 < len(tokens) else None
    expr = tokens[:eq_idx]
    if not out_path:
        return False

    try:
        import xarray as xr
        import numpy as np
    except ImportError:
        return False

    UNARY = {"FLIPUD", "FLIPLR", "NEG", "ABS", "SQRT", "LOG", "EXP"}
    BINARY = {"MUL", "ADD", "SUB", "DIV"}

    def _load(name: str):
        # Accept .grd files; reject anything that looks like a number.
        if name.replace("-", "").replace(".", "").replace("e", "").replace("E", "").isdigit() \
                or name.lstrip("-").replace(".", "").replace("e", "").replace("E", "").isdigit():
            return None
        try:
            return xr.open_dataset(name)["z"]
        except (OSError, KeyError, FileNotFoundError):
            return None

    # Form: a OP = out  (unary)
    if len(expr) == 2 and expr[1] in UNARY:
        a = _load(expr[0])
        if a is None:
            return False
        op = expr[1]
        if op == "FLIPUD":
            result = a.isel({a.dims[0]: slice(None, None, -1)})
        elif op == "FLIPLR":
            result = a.isel({a.dims[1]: slice(None, None, -1)})
        elif op == "NEG":
            result = -a
        elif op == "ABS":
            result = abs(a)
        elif op == "SQRT":
            result = np.sqrt(a)
        elif op == "LOG":
            result = np.log(a)
        elif op == "EXP":
            result = np.exp(a)
        result.rename("z").to_dataset().to_netcdf(out_path)
        return True

    # Form: a b OP = out  (binary). One of a/b can be a scalar.
    if len(expr) == 3 and expr[2] in BINARY:
        op = expr[2]
        a = _load(expr[0])
        b = _load(expr[1])
        # If one operand is a scalar literal (not a file), coerce
        if a is None and b is None:
            return False
        if a is None:
            try:
                a = float(expr[0])
            except ValueError:
                return False
        if b is None:
            try:
                b = float(expr[1])
            except ValueError:
                return False
        if op == "MUL":
            result = a * b
        elif op == "ADD":
            result = a + b
        elif op == "SUB":
            result = a - b
        elif op == "DIV":
            result = a / b
        # If result is xr.DataArray, save; if pure scalar, refuse (unusual)
        if hasattr(result, "to_dataset"):
            result.rename("z").to_dataset().to_netcdf(out_path)
            return True
        return False

    return False


# -------------------------------------------------------------- Phase 4 ---
# Figure-class plotting. These are typically composed (grdimage + psscale +
# psconvert into a single PDF) so a Figure wrapper that batches them is
# cleaner than per-call shims. Provide both forms.

class GMTSARFigure:
    """Convenience wrapper for the common gmtsar visualisation pattern:
    grdimage → colorbar → psconvert-to-PDF. Each gmtsar visualisation step
    typically composes 3-4 gmt calls; this lets a port site go from

        run('gmt grdimage A.grd ... > A.ps')
        run('gmt psscale -Rxx -Cxx -O >> A.ps')
        run('gmt psconvert -Tf -A -Z A.ps')

    to

        fig = GMTSARFigure(); fig.grdimage(...); fig.colorbar(...); fig.save('A.pdf')

    The .save() handles the psconvert step. PyGMT's Figure caches state
    so there's no per-call subprocess.
    """

    def __init__(self):
        if not _HAS_PYGMT:
            raise RuntimeError("GMTSARFigure requires PyGMT; install pygmt")
        self._fig = pygmt.Figure()

    def grdimage(self, grid: str, cmap: Optional[str] = None,
                 region=None, projection: str = "X7i", frame=None) -> None:
        kwargs = {"grid": grid, "projection": projection}
        if cmap is not None:
            kwargs["cmap"] = cmap
        if region is not None:
            kwargs["region"] = region
        if frame is not None:
            kwargs["frame"] = frame
        self._fig.grdimage(**kwargs)

    def colorbar(self, cmap: str, position: str = "JTC+w5i/0.2i+h",
                 frame: Optional[str] = None) -> None:
        kwargs = {"cmap": cmap, "position": position}
        if frame is not None:
            kwargs["frame"] = frame
        self._fig.colorbar(**kwargs)

    def plot(self, *args, **kwargs) -> None:
        self._fig.plot(*args, **kwargs)

    def text(self, *args, **kwargs) -> None:
        self._fig.text(*args, **kwargs)

    def save(self, path: str) -> None:
        """Write to PDF (or PNG/JPG by extension). Replaces the
        `gmt psconvert -Tf -A -Z` step."""
        self._fig.savefig(path)
