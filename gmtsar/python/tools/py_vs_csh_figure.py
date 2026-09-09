#!/usr/bin/env python3
"""py_vs_csh_figure.py — side-by-side Python-vs-csh output comparison figure.

Frozen 2026-07-13 from the ad-hoc script used to visually confirm the
SAT_llt2rat_py regression fix (see docs/PATHWAY_FORWARD.md). Reads real
sweep output already on disk under work/python_test/<case>/ and
work/csh_test/<case>/ — run tests/sweep.sh (or a forced single-case run)
first; this script does not run the pipeline itself.

Usage:
    python3 tools/py_vs_csh_figure.py <case> <intf_pair> [file1 file2 ...] [-o out.png]

Example:
    python3 tools/py_vs_csh_figure.py RS2_SLC_Hawaii 2011134_2011230 \\
        -o work/rs2_py_vs_csh.png

If no files are given, defaults to the three most commonly compared
products: phasefilt_mask_ll.png, corr_ll.png, display_amp_ll.png.
"""
from __future__ import annotations

import argparse
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.image as mpimg

_DEFAULT_FILES = ["phasefilt_mask_ll.png", "corr_ll.png", "display_amp_ll.png"]

# One-line description per product, shown under each row's title so a
# reader unfamiliar with GMTSAR output naming still knows what they're
# looking at.
_DESCRIPTIONS = {
    "phasefilt_mask_ll.png": "Filtered, unwrap-masked interferometric phase (geocoded)",
    "corr_ll.png": "Interferometric coherence (geocoded)",
    "display_amp_ll.png": "Radar amplitude / backscatter (geocoded)",
    "phase_mask_ll.png": "Unwrapped, masked phase (geocoded)",
}


def _find_gmtsar_root() -> str:
    env = os.environ.get("GMTSAR")
    if env:
        return env
    here = os.path.dirname(os.path.abspath(__file__))
    # tools/ -> gmtsar/python -> gmtsar -> <repo root>
    return os.path.abspath(os.path.join(here, "..", "..", ".."))


def build_figure(case: str, intf_pair: str, files: list[str], out_path: str) -> str:
    gmtsar_root = _find_gmtsar_root()
    py_dir = os.path.join(gmtsar_root, "gmtsar", "python", "work", "python_test", case, "intf", intf_pair)
    csh_dir = os.path.join(gmtsar_root, "gmtsar", "python", "work", "csh_test", case, "intf", intf_pair)

    rows = []
    for name in files:
        py_path = os.path.join(py_dir, name)
        csh_path = os.path.join(csh_dir, name)
        if not os.path.isfile(py_path) or not os.path.isfile(csh_path):
            print(f"WARN: skipping {name} — missing on py ({os.path.isfile(py_path)}) "
                  f"or csh ({os.path.isfile(csh_path)})", file=sys.stderr)
            continue
        rows.append((name, py_path, csh_path))

    if not rows:
        raise FileNotFoundError(
            f"no comparable files found for case={case} intf={intf_pair} "
            f"under {py_dir} / {csh_dir}"
        )

    fig, axes = plt.subplots(
        len(rows), 2, figsize=(11, 4.6 * len(rows)),
        squeeze=False,
    )

    for row_i, (name, py_path, csh_path) in enumerate(rows):
        desc = _DESCRIPTIONS.get(name, "")
        for col_i, (label, path) in enumerate([("Python", py_path), ("legacy csh", csh_path)]):
            ax = axes[row_i][col_i]
            ax.imshow(mpimg.imread(path))
            ax.set_xticks([])
            ax.set_yticks([])
            for spine in ax.spines.values():
                spine.set_visible(False)
            ax.set_title(f"{label} — {name}", fontsize=10, fontweight="bold")
        # One shared description spanning both columns for this row.
        if desc:
            axes[row_i][0].text(
                0.5, -0.06, desc, transform=axes[row_i][0].transAxes,
                ha="center", va="top", fontsize=9, style="italic",
                clip_on=False,
            )

    fig.suptitle(f"{case} — {intf_pair}: Python vs. legacy csh", fontsize=13, fontweight="bold", y=0.995)
    fig.tight_layout(rect=[0, 0, 1, 0.98])
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out_path


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("case", help="case name, e.g. RS2_SLC_Hawaii")
    p.add_argument("intf_pair", help="interferogram pair dir name, e.g. 2011134_2011230")
    p.add_argument("files", nargs="*", default=_DEFAULT_FILES,
                    help=f"output filenames to compare (default: {_DEFAULT_FILES})")
    p.add_argument("-o", "--out", default=None,
                    help="output PNG path (default: work/<case>_py_vs_csh.png)")
    args = p.parse_args(argv)

    out = args.out or os.path.join(_find_gmtsar_root(), "gmtsar", "python", "work",
                                    f"{args.case}_py_vs_csh.png")
    saved = build_figure(args.case, args.intf_pair, args.files, out)
    print(f"saved: {saved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
