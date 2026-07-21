#!/usr/bin/env python3
"""perf_snapshot — emit a faithful sweep snapshot per project_rules.md #7.

Reads `work/` artifacts written by sweep.sh / case_runner.sh and produces:

    docs/perf_snapshots/perf_snapshot_<UTC>_<sha>[_<label>].md
    docs/perf_snapshots/perf_snapshot_<UTC>_<sha>[_<label>].json

The markdown file has four tables (matching the manually-generated
snapshots shipped before this tool existed):

    1. Per-case timeline    (csh vs py wall, score)
    2. Per-binary timing    (where time goes inside each case)
    3. Aggregate by stage   (bottleneck overview across profiled cases)
    4. Failures             (cases with non-SUCCESS comparisons)

Inputs read:
    work/results/<case>.json                  — compare.py scorecards
    work/python_test/<case>/phase_profile_py.json — per-binary timings
    work/timeSpentLog.txt                     — csh + py wall times
    git rev-parse --short HEAD                — commit sha

CLI:
    perf_snapshot.py [--workdir work] [--out docs/perf_snapshots/]
                     [--label LABEL] [--commit SHA]
                     [--diff PREV_SNAPSHOT_JSON]

Constraints (rule 7):
- Honest about gaps. Missing profile → "no profile" row, not fabricated 0s.
- No cherry-picking. Every case with a scorecard goes in Table 1.
- Idempotent: re-running on the same data produces the same file content.

Pure stdlib + numpy. No extra deps.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
from collections import OrderedDict
from datetime import datetime, timezone


# -------------------------------------------------------------- env capture --

# Rule-7 env vars to capture. Order matches the historical snapshot format.
_ENV_VARS = (
    "NUMBA_NUM_THREADS",
    "XCORR_PY_WORKERS",
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "BLIS_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "MAX_PARALLEL",
    "SWEEP_FORCE",
)


def capture_env() -> dict[str, str]:
    """Return {var: value-or-'(not constrained)'} for each rule-7 env var."""
    return {v: os.environ.get(v, "(not constrained)") for v in _ENV_VARS}


def env_one_liner(env: dict[str, str]) -> str:
    """`VAR=val VAR2=val2 ...` line in the same shape as historical snapshots."""
    return " ".join(f"{k}={v}" for k, v in env.items())


# ----------------------------------------------------------- git + metadata --

def git_short_sha(repo_dir: str) -> str:
    """`git rev-parse --short HEAD` from repo_dir; '(no-git)' on failure."""
    try:
        r = subprocess.run(
            ["git", "-C", repo_dir, "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True, timeout=10,
        )
        return r.stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError):
        return "(no-git)"


def git_dirty(repo_dir: str) -> bool:
    """True if working tree has uncommitted changes."""
    try:
        r = subprocess.run(
            ["git", "-C", repo_dir, "diff", "--quiet"],
            capture_output=True, timeout=10,
        )
        return r.returncode != 0
    except Exception:
        return False


# ------------------------------------------------------- read sweep artifacts --

_TIME_RE = re.compile(r"^(\S+)\s+(csh|python)\s+used\s+(\d+(?:\.\d+)?)\s*s")


def parse_timings(time_log: str) -> dict[str, dict[str, float]]:
    """Parse work/timeSpentLog.txt → {case: {'csh': sec, 'python': sec}}.

    Last value wins on duplicates (sweep.sh appends; later entries are newer).
    """
    out: dict[str, dict[str, float]] = {}
    if not os.path.isfile(time_log):
        return out
    with open(time_log, errors="replace") as fh:
        for line in fh:
            m = _TIME_RE.match(line)
            if not m:
                continue
            case, side, sec = m.group(1), m.group(2), float(m.group(3))
            out.setdefault(case, {})[side] = sec
    return out


def load_scorecards(results_dir: str) -> dict[str, dict]:
    """Return {case: parsed-scorecard-json}. Skips unreadable files."""
    out: dict[str, dict] = {}
    for path in sorted(glob.glob(os.path.join(results_dir, "*.json"))):
        case = os.path.splitext(os.path.basename(path))[0]
        try:
            out[case] = json.load(open(path))
        except (json.JSONDecodeError, OSError):
            continue
    return out


def load_profile(python_test_dir: str, case: str) -> dict | None:
    """Return parsed work/python_test/<case>/phase_profile_py.json, or None.

    Stale dirs (`<case>.stale.*`) are skipped — only the canonical case dir
    counts. If the canonical dir is gone (case was wiped mid-sweep), returns
    None and the snapshot will show 'no profile' for that case.
    """
    path = os.path.join(python_test_dir, case, "phase_profile_py.json")
    if not os.path.isfile(path):
        return None
    try:
        return json.load(open(path))
    except (json.JSONDecodeError, OSError):
        return None


def score(scorecard: dict) -> tuple[int, int]:
    """(n_success, n_fail) over comparisons[]."""
    s = f = 0
    for c in scorecard.get("comparisons", []):
        st = c.get("status")
        if st == "SUCCESS":
            s += 1
        elif st == "FAIL":
            f += 1
    return s, f


# ------------------------------------------------------------ build report --

def _fmt_sec(v: float | None) -> str:
    return f"{v:.0f}s" if isinstance(v, (int, float)) and v > 0 else "-"


def _row_check(succ: int, fail: int) -> str:
    return "✓" if fail == 0 and succ > 0 else "✗"


def build_table1(cases: list[str],
                 timings: dict[str, dict[str, float]],
                 scorecards: dict[str, dict]) -> list[str]:
    """Table 1: per-case (csh vs py, score)."""
    lines = [
        "## Table 1 — Per-case (csh vs py, score)",
        "",
        "| Case | csh | py | Δ | speedup | score |",
        "|------|----:|---:|--:|--------:|:------|",
    ]
    rows: list[tuple[str, str]] = []  # (sort_key_str, formatted_line)
    for case in cases:
        t = timings.get(case, {})
        csh = t.get("csh")
        py = t.get("python")
        succ, fail = score(scorecards.get(case, {}))
        mark = _row_check(succ, fail)
        # Sort by speedup descending (csh/py). Cases with no timing sink to end.
        if csh and py and py > 0:
            speedup = csh / py
            delta = csh - py
            delta_str = f"+{delta:.0f}s" if delta >= 0 else f"{delta:.0f}s"
            speedup_str = f"{speedup:.2f}×"
            sort_key = -speedup  # sort descending
        else:
            speedup = float("-inf")
            delta_str = "-"
            speedup_str = "-"
            sort_key = float("inf")
        score_str = f"{succ}/{fail}" if (succ + fail) > 0 else "-"
        line = (f"| {mark} {case} | {_fmt_sec(csh)} | {_fmt_sec(py)} | "
                f"{delta_str} | {speedup_str} | {score_str} |")
        rows.append((sort_key, line))
    rows.sort(key=lambda r: r[0])
    lines.extend(r[1] for r in rows)
    lines.append("")
    return lines


# Binaries reported in Table 2 (matches historical snapshot column order).
_T2_BINS = ("dem2topo_ra", "resamp_py", "xcorr_py", "geocode", "intf", "pre_proc")
_T2_COLS = ("dem2topo", "resamp_py", "xcorr_py", "geocode", "intf", "pre_proc")


def build_table2(cases: list[str],
                 profiles: dict[str, dict]) -> list[str]:
    """Table 2: per-binary timing.

    Only cases with phase_profile_py.json appear. Cases without (S1 TOPS,
    ALOS2_SCAN that use csh-side recipes; cases wiped mid-sweep) are NOTED
    in a comment line, not silently dropped.
    """
    lines = [
        "## Table 2 — Per-binary timing (single-pair cases only)",
        "",
    ]
    missing = [c for c in cases if c not in profiles]
    if missing:
        lines.append(f"_Cases without profile (csh-side recipes or wiped "
                     f"mid-sweep): {', '.join(missing)}_")
        lines.append("")

    header = "| Case | total | " + " | ".join(_T2_COLS) + " |"
    sep = "|------|------:|" + "|".join(["---------:"] * len(_T2_COLS)) + "|"
    lines.append(header)
    lines.append(sep)

    rows: list[tuple[float, str]] = []
    for case in cases:
        prof = profiles.get(case)
        if not prof:
            continue
        total = prof.get("total_sec") or 0.0
        bin_by_name = {b["name"]: b.get("total_sec", 0.0)
                       for b in prof.get("binaries", [])}
        cells = []
        for b in _T2_BINS:
            v = bin_by_name.get(b)
            cells.append(f"{v:.0f}s" if v is not None and v > 0 else "-")
        line = (f"| {case} | **{total:.0f}s** | " + " | ".join(cells) + " |")
        rows.append((-total, line))
    rows.sort(key=lambda r: r[0])
    lines.extend(r[1] for r in rows)
    lines.append("")
    return lines


# Stage classes (matches historical snapshot).
_STAGE_CLASS = {
    "dem2topo_ra": "gmt-wrapper",
    "resamp_py": "Numba py",
    "geocode": "gmt-subprocess",
    "xcorr_py": "scipy.fft py",
    "intf": "C bin",
    "pre_proc": "C bin",
    "snaphu": "C bin",
    "fitoffset_ra": "gmt-subprocess",
}


def build_table3(profiles: dict[str, dict]) -> list[str]:
    """Table 3: aggregate by stage across all profiled cases."""
    agg: dict[str, float] = {}
    for prof in profiles.values():
        for b in prof.get("binaries", []):
            agg[b["name"]] = agg.get(b["name"], 0.0) + b.get("total_sec", 0.0)
    total = sum(agg.values()) or 1.0

    lines = [
        f"## Table 3 — Aggregate cost by stage (across {len(profiles)} profiled cases)",
        "",
        "| Stage | Total | % of pipeline | Class |",
        "|-------|------:|--------------:|-------|",
    ]
    for stage, secs in sorted(agg.items(), key=lambda kv: -kv[1]):
        pct = 100.0 * secs / total
        cls = _STAGE_CLASS.get(stage, "?")
        lines.append(f"| {stage} | {secs:.0f}s | {pct:.1f}% | {cls} |")
    lines.append("")
    return lines


def build_table4(scorecards: dict[str, dict],
                 timings: dict[str, dict[str, float]]) -> list[str]:
    """Table 4: failures — every case with at least one non-SUCCESS row."""
    lines = ["## Table 4 — Failures (cases not all-SUCCESS)", ""]
    any_fail = False
    for case in sorted(scorecards):
        sc = scorecards[case]
        comps = sc.get("comparisons", [])
        fails = [c for c in comps if c.get("status") != "SUCCESS"]
        if not fails:
            continue
        any_fail = True
        succ, fail = score(sc)
        py = timings.get(case, {}).get("python")
        py_str = _fmt_sec(py)
        lines.append(f"### {case} — score {succ}/{fail}, py={py_str}")
        lines.append("")
        lines.append("| File | Status | Reason |")
        lines.append("|------|--------|--------|")
        for c in comps:
            f = c.get("file", "?")
            st = c.get("status", "?")
            mark = "✓ SUCCESS" if st == "SUCCESS" else f"✗ {st}"
            reason = c.get("reason") or c.get("error") or "—"
            lines.append(f"| {f} | {mark} | {reason} |")
        lines.append("")
    if not any_fail:
        lines.append("_All cases all-SUCCESS._")
        lines.append("")
    return lines


# ------------------------------------------------------------ assemble doc --

def build_markdown(*, ts_iso: str, sha: str, dirty: bool,
                   label: str | None, env: dict[str, str],
                   cases: list[str],
                   timings: dict[str, dict[str, float]],
                   scorecards: dict[str, dict],
                   profiles: dict[str, dict],
                   sweep_wall_sec: float | None,
                   source_log: str | None,
                   perf_fields: dict[str, str]) -> str:
    n_pass = sum(1 for c in cases if c in scorecards
                 and score(scorecards[c]) == (
                     len(scorecards[c].get("comparisons", [])),
                     0)
                 and len(scorecards[c].get("comparisons", [])) > 0)
    n_fail = len(cases) - n_pass
    n_total = len(cases)

    title_suffix = f" — {label}" if label else ""
    sha_marker = f"`{sha}`" + (" (dirty)" if dirty else "")

    lines = []
    lines.append(f"# Perf snapshot{title_suffix}, {ts_iso}")
    lines.append("")
    lines.append(f"**Commit:** {sha_marker}  ")
    lines.append(f"**Config:** `{env_one_liner(env)}`  ")
    if perf_fields:
        cpu = perf_fields.get("cpu_model") or "?"
        cores = perf_fields.get("cpu_cores_logical") or "?"
        ram = perf_fields.get("ram_total") or "?"
        host = perf_fields.get("host") or "?"
        wfs_short = (perf_fields.get("workdir_fs") or "?").split(" ")[0]
        hw_bits = [f"{cpu}"]
        if cores != "?":
            hw_bits.append(f"{cores} cores")
        if ram and ram != "?":
            hw_bits.append(f"{ram} RAM")
        if wfs_short and wfs_short != "?":
            hw_bits.append(f"{wfs_short} workdir")
        if host and host != "?":
            hw_bits[-1] += f" ({host})"
        lines.append(f"**Hardware:** {', '.join(hw_bits)}  ")
        sw_bits = []
        gmt_str = perf_fields.get("gmt", "")
        # gmt may be: '6.5.0' or 'gmt not on PATH at sweep time' — only keep
        # the version when it actually parses as a version number.
        if gmt_str and gmt_str[0].isdigit():
            sw_bits.append(f"GMT {gmt_str.split()[0]}")
        py_str = perf_fields.get("python", "")
        if py_str:
            sw_bits.append(py_str)
        if sw_bits:
            lines.append(f"**Software:** {', '.join(sw_bits)}  ")
    if sweep_wall_sec is not None:
        h = int(sweep_wall_sec // 3600)
        m = int((sweep_wall_sec % 3600) // 60)
        lines.append(f"**Sweep wall:** {h}h {m}m ({sweep_wall_sec:.0f}s)  ")
    lines.append("")
    lines.append(f"**Coverage:** {n_total} cases with scorecards. "
                 f"**{n_pass} pass / {n_fail} fail**.")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.extend(build_table1(cases, timings, scorecards))
    lines.extend(build_table2(cases, profiles))
    lines.extend(build_table3(profiles))
    lines.extend(build_table4(scorecards, timings))
    lines.append("---")
    lines.append("")
    lines.append(f"_Snapshot generated: {ts_iso}_  ")
    if source_log:
        lines.append(f"_Source: {source_log}_  ")
    lines.append(f"_Tool: gmtsar/python/tools/perf_snapshot.py_")
    lines.append("")
    return "\n".join(lines)


def build_json(*, ts_iso: str, sha: str, dirty: bool,
               label: str | None, env: dict[str, str],
               cases: list[str],
               timings: dict[str, dict[str, float]],
               scorecards: dict[str, dict],
               profiles: dict[str, dict],
               sweep_wall_sec: float | None,
               perf_fields: dict[str, str]) -> dict:
    """Machine-readable sibling (rule 7)."""
    per_case = OrderedDict()
    for case in cases:
        t = timings.get(case, {})
        sc = scorecards.get(case, {})
        succ, fail = score(sc)
        prof = profiles.get(case)
        per_case[case] = {
            "csh_sec": t.get("csh"),
            "py_sec": t.get("python"),
            "score": {"success": succ, "fail": fail,
                      "comparisons": len(sc.get("comparisons", []))},
            "has_profile": prof is not None,
            "binaries": ({b["name"]: b.get("total_sec", 0.0)
                          for b in prof.get("binaries", [])}
                         if prof else None),
            "profile_total_sec": (prof.get("total_sec") if prof else None),
            "failures": [
                {"file": c.get("file"), "status": c.get("status"),
                 "metric": c.get("metric"),
                 "threshold": c.get("threshold"),
                 "metric_name": c.get("metric_name")}
                for c in sc.get("comparisons", []) if c.get("status") != "SUCCESS"
            ],
        }
    return {
        "generated_utc": ts_iso,
        "commit": {"sha": sha, "dirty": dirty},
        "label": label,
        "env": env,
        "hardware": perf_fields,
        "sweep_wall_sec": sweep_wall_sec,
        "n_cases": len(cases),
        "n_pass": sum(1 for c in per_case.values()
                      if c["score"]["fail"] == 0
                      and c["score"]["success"] > 0),
        "n_fail": sum(1 for c in per_case.values()
                      if c["score"]["fail"] > 0),
        "per_case": per_case,
    }


# --------------------------------------------------------------- diff mode --

def diff_snapshots(prev_path: str, cur: dict) -> str:
    """Compare a previous JSON snapshot to the current one.

    Flags:
      - cases that regressed in score (more FAILs than before, or status moved
        from pass to fail).
      - cases whose py runtime grew by > 10%.

    Returns a markdown report.
    """
    with open(prev_path) as fh:
        prev = json.load(fh)
    prev_pc = prev.get("per_case", {})
    cur_pc = cur["per_case"]
    lines = [f"## Diff vs {os.path.basename(prev_path)}", ""]
    score_regs: list[str] = []
    perf_regs: list[str] = []
    score_imp: list[str] = []
    for case, cur_v in cur_pc.items():
        prev_v = prev_pc.get(case)
        if not prev_v:
            continue
        # Score regression: more fails now, or any fail when there were zero.
        cur_f = cur_v["score"]["fail"]
        prev_f = prev_v["score"]["fail"]
        if cur_f > prev_f:
            score_regs.append(
                f"- {case}: {prev_v['score']['success']}/{prev_f} → "
                f"{cur_v['score']['success']}/{cur_f}")
        elif cur_f < prev_f:
            score_imp.append(
                f"- {case}: {prev_v['score']['success']}/{prev_f} → "
                f"{cur_v['score']['success']}/{cur_f}")
        # Perf regression: > 10% increase in py wall.
        prev_py = prev_v.get("py_sec")
        cur_py = cur_v.get("py_sec")
        if prev_py and cur_py and prev_py > 0:
            ratio = cur_py / prev_py
            if ratio > 1.10:
                perf_regs.append(
                    f"- {case}: {prev_py:.0f}s → {cur_py:.0f}s "
                    f"(+{(ratio-1)*100:.0f}%)")
    if score_regs:
        lines.append("**Score regressions (more failures):**")
        lines.extend(score_regs)
        lines.append("")
    if score_imp:
        lines.append("**Score improvements:**")
        lines.extend(score_imp)
        lines.append("")
    if perf_regs:
        lines.append("**Perf regressions (py wall > +10%):**")
        lines.extend(perf_regs)
        lines.append("")
    if not (score_regs or perf_regs or score_imp):
        lines.append("_No regressions or score changes detected._")
        lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------- entry point ------

def parse_perf_file(workdir: str) -> dict[str, str]:
    """Read the most-recent work/perf_*.txt (written by sweep.sh per rule 6).

    Returns a dict of fields used in the snapshot header: cpu_model,
    cpu_cores_logical, ram_total, workdir_fs, kernel, python, gmt,
    gmtsar_bin, git_sha, host. Empty dict if no perf file exists.
    """
    perfs = sorted(glob.glob(os.path.join(workdir, "perf_*.txt")))
    if not perfs:
        return {}
    fields: dict[str, str] = {}
    with open(perfs[-1], errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if ":" in line and not line.startswith("==="):
                k, _, v = line.partition(":")
                fields[k.strip()] = v.strip()
    return fields


def parse_sweep_wall(log_path: str) -> tuple[float | None, str | None]:
    """Best-effort parse of the LAST COMPLETED sweep's wall from sweep.log.

    sweep.log accumulates entries across many invocations. We pick the most
    recent matched (started → finished) pair. If no completed sweep is in
    the log (only an in-progress one), return None — a snapshot must not
    quote a misleading in-progress wall as the canonical sweep duration.
    """
    if not os.path.isfile(log_path):
        return None, None
    ts_pat = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] ")
    pairs: list[tuple[str, str]] = []
    pending_start: str | None = None
    with open(log_path, errors="replace") as fh:
        for line in fh:
            m = ts_pat.match(line)
            if not m:
                continue
            if "sweep started" in line:
                pending_start = m.group(1)
            elif pending_start and "sweep finished" in line:
                pairs.append((pending_start, m.group(1)))
                pending_start = None
    if not pairs:
        return None, log_path
    last_start, last_end = pairs[-1]
    fmt = "%Y-%m-%d %H:%M:%S"
    try:
        t0 = datetime.strptime(last_start, fmt)
        t1 = datetime.strptime(last_end, fmt)
        return (t1 - t0).total_seconds(), log_path
    except ValueError:
        return None, log_path


def main(argv: list[str] | None = None) -> int:
    here = os.path.abspath(os.path.dirname(__file__))
    pydir = os.path.abspath(os.path.join(here, os.pardir))  # gmtsar/python/

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--workdir", default=os.path.join(pydir, "work"),
                    help="sweep workdir (default: gmtsar/python/work)")
    ap.add_argument("--out", default=os.path.join(pydir, "docs", "perf_snapshots"),
                    help="output directory")
    ap.add_argument("--label", default=None,
                    help="optional suffix for filename (e.g. FULL_strict1)")
    ap.add_argument("--commit", default=None,
                    help="override git sha (default: git rev-parse --short HEAD)")
    ap.add_argument("--diff", default=None,
                    help="compare against a previous .json snapshot and emit "
                         "a regression report (no .md is written for --diff)")
    args = ap.parse_args(argv)

    workdir = os.path.abspath(args.workdir)
    out_dir = os.path.abspath(args.out)

    results_dir = os.path.join(workdir, "results")
    time_log = os.path.join(workdir, "timeSpentLog.txt")
    python_test = os.path.join(workdir, "python_test")
    sweep_log = os.path.join(workdir, "sweep.log")

    sha = args.commit or git_short_sha(pydir)
    dirty = (args.commit is None) and git_dirty(pydir)
    env = capture_env()
    ts_dt = datetime.now(timezone.utc).replace(microsecond=0)
    ts_iso = ts_dt.strftime("%Y-%m-%dT%H-%M-%SZ")

    timings = parse_timings(time_log)
    scorecards = load_scorecards(results_dir)
    # Scope = cases with a current scorecard in work/results/. This is what
    # *this sweep* produced. timeSpentLog.txt is append-only across many
    # sweeps and includes stale entries — pulling cases from it would
    # contaminate the snapshot with non-scope data.
    cases = sorted(scorecards)
    profiles: dict[str, dict] = {}
    for case in cases:
        p = load_profile(python_test, case)
        if p is not None:
            profiles[case] = p

    sweep_wall_sec, source_log = parse_sweep_wall(sweep_log)
    perf_fields = parse_perf_file(workdir)

    md = build_markdown(
        ts_iso=ts_iso, sha=sha, dirty=dirty, label=args.label, env=env,
        cases=cases, timings=timings, scorecards=scorecards,
        profiles=profiles, sweep_wall_sec=sweep_wall_sec,
        source_log=(os.path.basename(source_log) if source_log else None),
        perf_fields=perf_fields,
    )
    js = build_json(
        ts_iso=ts_iso, sha=sha, dirty=dirty, label=args.label, env=env,
        cases=cases, timings=timings, scorecards=scorecards,
        profiles=profiles, sweep_wall_sec=sweep_wall_sec,
        perf_fields=perf_fields,
    )

    if args.diff:
        # Diff mode prints to stdout; does not write the new snapshot.
        sys.stdout.write(diff_snapshots(args.diff, js))
        return 0

    os.makedirs(out_dir, exist_ok=True)
    base = f"perf_snapshot_{ts_iso}_{sha}"
    if args.label:
        base = f"{base}_{args.label}"
    md_path = os.path.join(out_dir, f"{base}.md")
    js_path = os.path.join(out_dir, f"{base}.json")
    with open(md_path, "w") as fh:
        fh.write(md)
    with open(js_path, "w") as fh:
        json.dump(js, fh, indent=2, sort_keys=False)
        fh.write("\n")

    print(f"wrote {md_path}")
    print(f"wrote {js_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
