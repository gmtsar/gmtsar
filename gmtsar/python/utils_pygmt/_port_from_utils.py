#!/usr/bin/env python3
"""Mechanical porter: utils/<X> → utils_pygmt/<X>_pygmt.

For each source file, finds every `run('gmt <subcommand> <args>')` call:
  - If the args contain a shell pipe ('|') or are piped to a non-gmt
    external binary, leave the run() call untouched (keep subprocess).
  - Otherwise, rewrite to `gmt_compat.<subcommand>('<args>')`.

Imports for the subcommands used are inserted near the top of the file.
The result is a parallel file in utils_pygmt/ named <X>_pygmt (or <X>.py
if the source ended in .py). Existing files in utils_pygmt/ are
preserved (the porter never overwrites the hand-written pilot).

Reports per-file:
  - n gmt calls found
  - n ported
  - n left as subprocess (pipe / external)
"""
from __future__ import annotations

import re
import os
import sys
from pathlib import Path

UTILS = Path(__file__).resolve().parent.parent / "utils"
TARGET = Path(__file__).resolve().parent

# Subcommands the shim knows. Calls to anything else stay subprocess.
SHIM_SUBCOMMANDS = {
    "surface", "grdcut", "grdsample", "grdimage", "makecpt", "grdtrack",
    "blockmedian", "blockmean", "grdfilter", "grd2xyz", "xyz2grd", "grdinfo",
    "grdgradient", "grdfill", "grdlandmask", "triangulate", "grd2cpt", "gmtinfo",
    "grdedit", "grdpaste", "trend2d", "grdmath",
}

# Skip hand-written + clearly unrelated files.
SKIP_NAMES = {
    "dem2topo_ra",                  # hand-written pilot already exists as _pygmt
    "gmtsar_lib.py",                # library, no gmt calls in the function bodies we care about
    "p2p_stages.py",                # already refactored separately
    "tkGUI.gmtsar",                 # Tk GUI, special
    "snaphu", "snaphu.py",          # snaphu wrapper (renamed to .py); not gmt-based
}

# match run('gmt FOO ARGS') or run("gmt FOO ARGS") on one line.
# - allow whitespace around `run`
# - allow optional f-string `f'...'` (not common but possible)
# - capture FOO and the rest of the args before the closing quote
RUN_GMT = re.compile(
    r"""(?P<lead>\brun\s*\(\s*)(?P<q>['"])gmt\s+(?P<cmd>[a-z][a-z0-9]*)\s*(?P<args>.*?)(?P=q)\s*\)""",
    re.DOTALL,
)


def has_pipe(line: str) -> bool:
    """Crude: any `|` in the call string means we keep subprocess."""
    return "|" in line


def port_file(src: Path) -> dict:
    text = src.read_text()
    used = set()
    skipped = 0
    ported = 0
    total = 0

    def repl(m: re.Match) -> str:
        nonlocal skipped, ported, total
        total += 1
        full_match = m.group(0)
        cmd = m.group("cmd")
        args = m.group("args").strip()
        # Decline if subcommand isn't shim-known, or if there's a pipe.
        if cmd not in SHIM_SUBCOMMANDS or has_pipe(full_match) or has_pipe(args):
            skipped += 1
            return full_match
        # Decline if args contain redirection to file — those usually have a
        # downstream consumer that expects the file to exist with the exact
        # binary format gmt produces.
        if re.search(r"\s>\s", args) or re.search(r"\s>>\s", args):
            skipped += 1
            return full_match
        ported += 1
        used.add(cmd)
        # Re-emit args inside the quotes intact (whitespace preserved).
        # gmt_compat.cmd(args)  — same q-style as original
        # Keep the original string concatenation intact: only strip the
        # leading "gmt FOO " — easiest to do by reconstructing the call.
        q = m.group("q")
        return f'gmt_compat.{cmd}({q}{args}{q})'

    new_text, _ = RUN_GMT.subn(repl, text)
    if total == 0 or ported == 0:
        return {"ported": 0, "total": total, "skipped": skipped, "used": used}

    # Insert the import after the existing `from gmtsar_lib import *` line,
    # or after the last `import` line.
    imp = "from utils_pygmt import gmt_compat\n"
    # Don't double-add
    if "import gmt_compat" not in new_text and "from utils_pygmt" not in new_text:
        m = re.search(r"^(from gmtsar_lib import .*\n)", new_text, re.MULTILINE)
        if m is None:
            m = re.search(r"^(import [^\n]+\n)+", new_text, re.MULTILINE)
        if m:
            insert_at = m.end()
            new_text = new_text[:insert_at] + imp + new_text[insert_at:]
        else:
            new_text = imp + new_text

    # Tag the file so a future reader knows it was machine-ported.
    # preserve line-1 shebang (next() if present), then write banner, then rest
    lines = new_text.splitlines(keepends=True)
    shebang = ""
    if lines and lines[0].startswith("#!"):
        shebang = lines[0]
        lines = lines[1:]
    banner = (f"# AUTO-PORTED from utils/{src.name} by utils_pygmt/_port_from_utils.py.\n"
              f"# {ported}/{total} gmt calls migrated to gmt_compat; "
              f"{skipped} kept as subprocess (shell pipe, file redirect, or unsupported subcommand).\n"
              f"# Manual review recommended for the kept-subprocess calls.\n")
    new_text = banner + new_text

    target_name = src.name + ("_pygmt" if not src.name.endswith(".py") else "")
    if src.name.endswith(".py"):
        target_name = src.name.replace(".py", "_pygmt.py")
    target = TARGET / target_name
    if target.exists():
        return {"ported": 0, "total": total, "skipped": skipped, "used": used,
                "note": f"target exists: {target.name}"}
    target.write_text(new_text)
    # Preserve executable bit if source had one
    target.chmod(src.stat().st_mode)
    return {"ported": ported, "total": total, "skipped": skipped, "used": used}


def main() -> None:
    files = []
    for p in sorted(UTILS.iterdir()):
        if not p.is_file() or p.name in SKIP_NAMES or p.suffix == ".csh":
            continue
        # only files with a gmt call worth porting
        try:
            t = p.read_text()
        except Exception:
            continue
        if not RUN_GMT.search(t):
            continue
        files.append(p)

    print(f"Found {len(files)} candidate utilities.\n")
    grand_ported = grand_total = grand_skipped = 0
    grand_used: set[str] = set()
    skipped_files = []

    for p in files:
        r = port_file(p)
        if "note" in r:
            print(f"  skip   {p.name}  ({r['note']})")
            skipped_files.append(p.name)
            continue
        if r["total"] == 0:
            continue
        print(f"  port   {p.name}: {r['ported']}/{r['total']} ported, "
              f"{r['skipped']} kept-subprocess  ({sorted(r['used'])})")
        grand_ported += r["ported"]
        grand_total += r["total"]
        grand_skipped += r["skipped"]
        grand_used.update(r["used"])

    print(f"\nGrand total: {grand_ported}/{grand_total} ported, "
          f"{grand_skipped} kept-subprocess across {len(files) - len(skipped_files)} files.")
    print(f"Distinct subcommands ported: {sorted(grand_used)}")
    if skipped_files:
        print(f"Skipped (target exists): {skipped_files}")


if __name__ == "__main__":
    main()
