#!/usr/bin/env python3
"""blessed_diff.py — compare current python_test/<case> outputs against a
committed blessed scorecard in docs/blessed_scorecards/<TAG>/<case>.json.

Can be called standalone or imported by compare.py / report.py.

Exit codes:
    0 — all files match the blessed scorecard (or no blessed file exists for case)
    1 — one or more files differ from blessed (regression)
    2 — usage error

Usage:
    python3 blessed_diff.py [--case RS2_SLC_Hawaii] [--tag v2.0.4]

If --case is omitted, all cases that have a blessed scorecard are checked.
If --tag is omitted, the lexicographically newest tag dir under
docs/blessed_scorecards/ is used.

Writes diff results to work/blessed_diff_<TAG>.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent.parent          # <repo>/gmtsar/python/../..  → repo root
_PYTHON_DIR = _HERE.parent           # gmtsar/python/
_BLESSED_ROOT = _PYTHON_DIR / "docs" / "blessed_scorecards"
_PY_TEST_ROOT = _PYTHON_DIR / "work" / "python_test"
_WORK = _PYTHON_DIR / "work"


def md5_file(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def latest_tag() -> str | None:
    if not _BLESSED_ROOT.is_dir():
        return None
    tags = sorted(d.name for d in _BLESSED_ROOT.iterdir() if d.is_dir())
    return tags[-1] if tags else None


def diff_case(case: str, tag: str) -> dict:
    """Compare one case. Returns a result dict with keys:
        case, tag, status ('PASS'|'FAIL'|'SKIP'), diffs, missing, extra.
    """
    blessed_path = _BLESSED_ROOT / tag / f"{case}.json"
    if not blessed_path.exists():
        return {"case": case, "tag": tag, "status": "SKIP",
                "reason": f"no blessed scorecard at {blessed_path}"}

    blessed = json.loads(blessed_path.read_text())
    expected_md5s: dict[str, str] = blessed.get("file_md5s", {})

    case_root = _PY_TEST_ROOT / case
    if not case_root.is_dir():
        return {"case": case, "tag": tag, "status": "SKIP",
                "reason": f"python_test/{case} not present (case not yet run)"}

    diffs: list[dict] = []
    missing: list[str] = []
    extra: list[str] = []

    # Check every file the blessed scorecard recorded.
    for rel_path, blessed_md5 in sorted(expected_md5s.items()):
        actual = case_root / rel_path
        if not actual.exists():
            missing.append(rel_path)
            continue
        actual_md5 = md5_file(str(actual))
        if actual_md5 != blessed_md5:
            diffs.append({
                "file": rel_path,
                "blessed_md5": blessed_md5,
                "actual_md5": actual_md5,
            })

    # Files present now but not in blessed (new outputs not yet blessed).
    target_names = {
        "corr_ll.png", "display_amp_ll.png", "phasefilt_mask_ll.png",
        "corr_ll.grd", "phasefilt.grd", "filtcorr.grd", "los_ll.grd",
    }
    for fname in target_names:
        for found in sorted(case_root.rglob(fname)):
            rel = str(found.relative_to(case_root))
            if rel not in expected_md5s:
                extra.append(rel)

    status = "PASS" if (not diffs and not missing) else "FAIL"
    return {
        "case": case, "tag": tag, "status": status,
        "diffs": diffs, "missing": missing, "extra": extra,
    }


def run(cases: list[str] | None, tag: str | None) -> int:
    if tag is None:
        tag = latest_tag()
    if tag is None:
        print("ERROR: no blessed scorecard tags found under "
              f"{_BLESSED_ROOT}", file=sys.stderr)
        return 2

    blessed_tag_dir = _BLESSED_ROOT / tag
    if cases is None:
        # All cases that have a blessed file for this tag.
        cases = [p.stem for p in sorted(blessed_tag_dir.glob("*.json"))]

    if not cases:
        print(f"No cases to check for tag {tag}.")
        return 0

    results: list[dict] = []
    for case in cases:
        r = diff_case(case, tag)
        results.append(r)
        status = r.get("status", "?")
        if status == "PASS":
            print(f"  BLESSED PASS  {case}")
        elif status == "SKIP":
            print(f"  BLESSED SKIP  {case}: {r.get('reason','')}")
        else:
            print(f"  BLESSED FAIL  {case}")
            for d in r.get("diffs", []):
                print(f"    CHANGED {d['file']}: "
                      f"blessed={d['blessed_md5'][:12]}... "
                      f"actual={d['actual_md5'][:12]}...")
            for m in r.get("missing", []):
                print(f"    MISSING {m}")
            for e in r.get("extra", []):
                print(f"    EXTRA   {e} (not in blessed — bless if expected)")

    # Write markdown report.
    n_pass = sum(1 for r in results if r.get("status") == "PASS")
    n_fail = sum(1 for r in results if r.get("status") == "FAIL")
    n_skip = sum(1 for r in results if r.get("status") == "SKIP")

    out_md = _WORK / f"blessed_diff_{tag}.md"
    lines = [
        f"# Blessed scorecard diff — tag {tag}",
        "",
        f"_generated {os.popen('date').read().strip()}_",
        "",
        f"**{n_pass} PASS / {n_fail} FAIL / {n_skip} SKIP**",
        "",
        "| Case | Status | Changed files | Missing | Extra |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        status = r.get("status", "?")
        ndiffs = len(r.get("diffs", []))
        nmiss = len(r.get("missing", []))
        nextra = len(r.get("extra", []))
        lines.append(f"| {r['case']} | {status} | {ndiffs} | {nmiss} | {nextra} |")
    lines += [
        "",
        "## Details",
        "",
    ]
    for r in results:
        if r.get("status") in ("FAIL", "SKIP"):
            lines.append(f"### {r['case']} — {r.get('status')}")
            if r.get("reason"):
                lines.append(f"_{r['reason']}_")
            for d in r.get("diffs", []):
                lines.append(f"- CHANGED `{d['file']}` "
                             f"blessed=`{d['blessed_md5'][:12]}` "
                             f"actual=`{d['actual_md5'][:12]}`")
            for m in r.get("missing", []):
                lines.append(f"- MISSING `{m}`")
            for e in r.get("extra", []):
                lines.append(f"- EXTRA `{e}`")
            lines.append("")

    _WORK.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(lines) + "\n")
    print(f"\nBlessed diff → {out_md}")
    return 1 if n_fail > 0 else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Diff current python_test outputs against blessed scorecards.")
    p.add_argument("--case", nargs="*", metavar="CASE",
                   help="one or more case names; default: all blessed cases")
    p.add_argument("--tag", metavar="TAG",
                   help="scorecard tag (e.g. v2.0.4); default: latest")
    args = p.parse_args(argv)
    return run(cases=args.case, tag=args.tag)


if __name__ == "__main__":
    sys.exit(main())
