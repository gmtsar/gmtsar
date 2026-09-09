#!/usr/bin/env python3
"""bless.py — generate a blessed scorecard tag from current
work/python_test/<case> outputs + work/results/<case>.json.

Writes docs/blessed_scorecards/<TAG>/<case>.json for each case, in the
same format as the existing v2.0.4 scorecards (consumed by
tests/blessed_diff.py).

Usage:
    python3 bless.py --tag v2.1.21 [--case CASE ...]

If --case is omitted, all cases present under work/python_test/ are
blessed (directories with a ".stale.*" suffix are skipped).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PYTHON_DIR = _HERE.parent
_BLESSED_ROOT = _PYTHON_DIR / "docs" / "blessed_scorecards"
_PY_TEST_ROOT = _PYTHON_DIR / "work" / "python_test"
_RESULTS_ROOT = _PYTHON_DIR / "work" / "results"

_TARGET_NAMES = {
    "corr_ll.png", "display_amp_ll.png", "phasefilt_mask_ll.png",
    "corr_ll.grd", "phasefilt.grd", "filtcorr.grd", "los_ll.grd",
}


def md5_file(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def bless_case(case: str, tag: str) -> bool:
    case_root = _PY_TEST_ROOT / case
    if not case_root.is_dir():
        print(f"  SKIP {case}: no python_test output")
        return False

    file_md5s: dict[str, str] = {}
    for fname in sorted(_TARGET_NAMES):
        for found in sorted(case_root.rglob(fname)):
            rel = str(found.relative_to(case_root))
            file_md5s[rel] = md5_file(found)

    if not file_md5s:
        print(f"  SKIP {case}: no target output files found")
        return False

    compare_result: dict[str, str] = {}
    results_path = _RESULTS_ROOT / f"{case}.json"
    if results_path.exists():
        results = json.loads(results_path.read_text())
        for comp in results.get("comparisons", []):
            if comp.get("pair") == "py-vs-csh":
                compare_result[comp["file"]] = comp.get("status", "?")

    out = {
        "case": case,
        "tag": tag,
        "generated_from": str(results_path),
        "compare_result": compare_result,
        "file_md5s": file_md5s,
    }

    out_dir = _BLESSED_ROOT / tag
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{case}.json"
    out_path.write_text(json.dumps(out, indent=2) + "\n")
    print(f"  BLESSED {case} ({len(file_md5s)} files)")
    return True


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Generate a blessed scorecard tag from current python_test outputs.")
    p.add_argument("--tag", required=True, metavar="TAG",
                    help="scorecard tag to write (e.g. v2.1.21)")
    p.add_argument("--case", nargs="*", metavar="CASE",
                    help="one or more case names; default: all cases under work/python_test/")
    args = p.parse_args(argv)

    if args.case:
        cases = args.case
    else:
        cases = sorted(
            p.name for p in _PY_TEST_ROOT.iterdir()
            if p.is_dir() and ".stale." not in p.name
        )

    n = 0
    for case in cases:
        if bless_case(case, args.tag):
            n += 1
    print(f"\n{n}/{len(cases)} cases blessed under {_BLESSED_ROOT / args.tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
