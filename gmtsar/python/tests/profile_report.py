#!/usr/bin/env python3
"""profile_report — aggregate work/profile_*.json files produced by the
profiler module. Prints a per-binary wall-time table sorted by total.

Usage:
    python3 tests/profile_report.py                # aggregate all cases
    python3 tests/profile_report.py <case>         # single case
    python3 tests/profile_report.py --by-backend   # group by backend
"""
import glob
import json
import os
import sys
from collections import defaultdict

WORK = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "..", "work")


def load_profiles(case_filter: str | None = None) -> list[dict]:
    """Read every profile_*.json under work/. Optionally filter to one case."""
    profiles = []
    for p in glob.glob(os.path.join(WORK, "profile_*.json")):
        try:
            d = json.load(open(p))
        except (json.JSONDecodeError, OSError):
            continue
        if case_filter and d.get("case") != case_filter:
            continue
        d["__file__"] = p
        profiles.append(d)
    return profiles


def main() -> None:
    by_backend = "--by-backend" in sys.argv
    case_filter = None
    for a in sys.argv[1:]:
        if a == "--by-backend":
            continue
        case_filter = a

    profiles = load_profiles(case_filter)
    if not profiles:
        print("No profile_*.json found in work/. Did you run with GMTSAR_PROFILE=1?")
        sys.exit(1)

    print(f"Loaded {len(profiles)} profile file(s).")
    if case_filter:
        print(f"Filtered to case: {case_filter}")
    print()

    # 1. Per-binary aggregation (the head of `cmd` is the binary name).
    per_bin: dict[str, dict] = defaultdict(lambda: {"wall_s": 0.0, "n": 0, "backends": defaultdict(int)})
    per_backend: dict[str, dict] = defaultdict(lambda: {"wall_s": 0.0, "n": 0})

    for p in profiles:
        for c in p.get("calls", []):
            head = c["cmd"].split()[0] if c.get("cmd") else "?"
            # For "gmt SUBCMD ...", credit "gmt SUBCMD" so we can see
            # which GMT module is hot vs. all-gmt lumped together.
            if head == "gmt" and len(c["cmd"].split()) >= 2:
                head = "gmt " + c["cmd"].split()[1]
            per_bin[head]["wall_s"] += c["wall_s"]
            per_bin[head]["n"] += 1
            per_bin[head]["backends"][c.get("backend", "?")] += 1
            per_backend[c.get("backend", "?")]["wall_s"] += c["wall_s"]
            per_backend[c.get("backend", "?")]["n"] += 1

    total_wall = sum(v["wall_s"] for v in per_bin.values())
    total_n = sum(v["n"] for v in per_bin.values())

    if by_backend:
        print(f"{'Backend':<20} {'wall_s':>12} {'n_calls':>10} {'avg_ms':>10}")
        print("-" * 56)
        for backend, v in sorted(per_backend.items(),
                                 key=lambda kv: -kv[1]["wall_s"]):
            avg_ms = (v["wall_s"] / v["n"]) * 1000 if v["n"] else 0
            print(f"{backend:<20} {v['wall_s']:>12.2f} {v['n']:>10} {avg_ms:>10.2f}")
    else:
        print(f"{'Binary / module':<28} {'wall_s':>10} {'%total':>8} {'n':>8} {'avg_ms':>10}")
        print("-" * 70)
        for cmd, v in sorted(per_bin.items(), key=lambda kv: -kv[1]["wall_s"])[:30]:
            pct = (v["wall_s"] / total_wall * 100) if total_wall else 0
            avg_ms = (v["wall_s"] / v["n"]) * 1000 if v["n"] else 0
            print(f"{cmd:<28} {v['wall_s']:>10.2f} {pct:>7.1f}% {v['n']:>8} {avg_ms:>10.2f}")
        print("-" * 70)
        print(f"{'TOTAL':<28} {total_wall:>10.2f} {'100.0%':>8} {total_n:>8}")

    # 2. Per-stage if present
    if any(p.get("stages") for p in profiles):
        print()
        print("Stages (where defined via profiler.stage(...)):")
        per_stage: dict[str, dict] = defaultdict(lambda: {"wall_s": 0.0, "n": 0})
        for p in profiles:
            for s in p.get("stages", []):
                per_stage[s["name"]]["wall_s"] += s["wall_s"]
                per_stage[s["name"]]["n"] += 1
        for name, v in sorted(per_stage.items(), key=lambda kv: -kv[1]["wall_s"]):
            print(f"  {name:<30} {v['wall_s']:>10.2f} s   (n={v['n']})")


if __name__ == "__main__":
    main()
