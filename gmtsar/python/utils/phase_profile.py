"""phase_profile — per-phase wall-time tracker for p2p_processing.

Usage from the py driver:

    from phase_profile import phase, dump_profile

    with phase("P2P1_preprocess"):
        P2P1Preprocess(...)
    ...
    dump_profile()                         # writes phase_profile_py.json
                                           # in the current working dir.

The CSH side is profiled separately via grep on its log.txt — see
`phase_profile_from_csh_log(path)` below — so the JSON shape matches.

JSON format (intended to be diff-able between py and csh):

    {
      "side":   "py" | "csh",
      "case":   "RS2_SLC_Hawaii",  (filled by caller)
      "phases": [
        {"name": "P2P1_preprocess",  "duration_sec": 12.345},
        {"name": "P2P2_focus_align", "duration_sec": 45.678},
        ...
      ],
      "total_sec": 84.0
    }
"""
from __future__ import annotations

import atexit
import json
import os
import re
import time
from contextlib import contextmanager
from typing import Optional


# -- live timing collected via the `phase` context manager ---------------
_PHASES: list[dict] = []


@contextmanager
def phase(name: str):
    """Time a block; append a {name, duration_sec, start, end} entry."""
    t0 = time.time()
    try:
        yield
    finally:
        t1 = time.time()
        _PHASES.append({
            "name": name,
            "duration_sec": round(t1 - t0, 3),
            "start_epoch": t0,
            "end_epoch": t1,
        })


def reset() -> None:
    _PHASES.clear()
    _BINARY_TIMES.clear()


# Per-binary timing — finer-grained than phase(), records each call's
# wall time keyed on the binary name (extracted from the first token of
# the command line). Aggregated in dump_profile under "binaries".
_BINARY_TIMES: dict[str, list[float]] = {}


def time_run(cmd: str, name: Optional[str] = None):
    """Wrap gmtsar_lib.run() with per-binary wall-time recording.

    Use in place of `run(...)` for any binary you want a separate row
    for in phase_profile_py.json. The binary name defaults to the first
    token of the command. Pass `name=...` to override (e.g. when the
    same script is called with different roles).
    """
    from gmtsar_lib import run as _run     # lazy import to avoid cycles
    n = name or cmd.split()[0]
    t0 = time.time()
    try:
        return _run(cmd)
    finally:
        _BINARY_TIMES.setdefault(n, []).append(time.time() - t0)


def dump_profile(path: str = "phase_profile_py.json",
                 case: Optional[str] = None) -> None:
    """Write the accumulated phase profile to `path` (cwd by default)."""
    total = round(sum(p["duration_sec"] for p in _PHASES), 3)
    # Aggregate per-binary calls: total seconds + call count per binary.
    binaries = []
    for name in sorted(_BINARY_TIMES):
        times = _BINARY_TIMES[name]
        binaries.append({
            "name": name,
            "calls": len(times),
            "total_sec": round(sum(times), 3),
            "avg_sec": round(sum(times) / len(times), 3),
            "max_sec": round(max(times), 3),
        })
    out = {"side": "py", "case": case, "phases": list(_PHASES),
           "binaries": binaries, "total_sec": total}
    with open(path, "w") as f:
        json.dump(out, f, indent=2)


# -- Frame-level aggregation (S1 TOPS: F1+F2+F3 → case root) -----------
#
# p2p_S1_TOPS_Frame runs p2p_processing once per-subswath in F1/F2/F3.
# Each per-subswath p2p_processing dumps its own phase_profile_py.json.
# This aggregator sums those into a single Frame-level JSON at the case
# root (cwd by default), then optionally appends extra phases/binaries
# captured by the caller (e.g. the merge_unwrap_geocode_tops step that
# the Frame driver runs after the subswaths complete).
#
# Aggregation rules (designed so the numbers are physically meaningful):
#   - binaries: sum calls + total_sec across subswaths; recompute avg
#     (= sum_total / sum_calls) and max (= max of per-subswath max).
#   - phases: for parallel runs the subswaths overlap in wall time, so
#     summing duration_sec across F1/F2/F3 over-counts. We use the wall
#     time inferred from per-subswath start/end epochs: phase wall =
#     max(end) - min(start) across the three subswaths for that phase
#     name. For sequential runs each subswath runs disjoint in time so
#     this max-end - min-start still equals the sum of durations.
#   - total_sec = sum of aggregated phase durations + any extra phases.


def _read_profile(path: str) -> Optional[dict]:
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def aggregate_subswath_profiles(
    subswath_dirs: list[str],
    out_path: str = "phase_profile_py.json",
    case: Optional[str] = None,
    extra_phases: Optional[list[dict]] = None,
    extra_binaries: Optional[dict[str, list[float]]] = None,
) -> Optional[dict]:
    """Read F1/F2/F3 phase_profile_py.json and write a Frame-level JSON.

    `subswath_dirs` — paths to F1, F2, F3 (or analogues). Missing/unparseable
    JSONs are skipped silently (the file may be absent on the first run if
    a subswath crashed; we still emit what we have).

    `extra_phases` — list of `{name, duration_sec, start_epoch, end_epoch}`
    entries to append AFTER the aggregated subswath phases. Use for stages
    that run at the Frame level outside p2p_processing (e.g. the merge step).

    `extra_binaries` — `{name: [secs, ...]}` of per-binary call durations to
    merge into the aggregated binaries dict. Use for binaries the Frame
    driver wraps directly (e.g. `merge_unwrap_geocode_tops`).

    Returns the written dict (also serialised to `out_path`), or None if no
    subswath profiles were found AND no extras were provided.
    """
    profiles = [_read_profile(os.path.join(d, "phase_profile_py.json"))
                for d in subswath_dirs]
    profiles = [p for p in profiles if p is not None]

    # If nothing to aggregate AND no extras → bail out (do not clobber an
    # existing file with an empty profile).
    if not profiles and not extra_phases and not extra_binaries:
        return None

    # --- binaries: sum calls + total_sec by name; max of per-subswath max
    bin_calls: dict[str, int] = {}
    bin_total: dict[str, float] = {}
    bin_max:   dict[str, float] = {}
    for prof in profiles:
        for b in prof.get("binaries", []):
            n = b["name"]
            bin_calls[n] = bin_calls.get(n, 0) + int(b.get("calls", 0))
            bin_total[n] = bin_total.get(n, 0.0) + float(b.get("total_sec", 0.0))
            bin_max[n]   = max(bin_max.get(n, 0.0), float(b.get("max_sec", 0.0)))
    # Fold in any extra per-binary times the caller passed.
    if extra_binaries:
        for n, times in extra_binaries.items():
            if not times:
                continue
            bin_calls[n] = bin_calls.get(n, 0) + len(times)
            bin_total[n] = bin_total.get(n, 0.0) + sum(times)
            bin_max[n]   = max(bin_max.get(n, 0.0), max(times))
    binaries = []
    for n in sorted(bin_calls):
        c = bin_calls[n]
        binaries.append({
            "name": n,
            "calls": c,
            "total_sec": round(bin_total[n], 3),
            "avg_sec": round(bin_total[n] / c, 3) if c > 0 else 0.0,
            "max_sec": round(bin_max[n], 3),
        })

    # --- phases: max-of-per-subswath-duration per phase name.
    by_name: dict[str, list[dict]] = {}
    phase_order: list[str] = []
    for prof in profiles:
        for ph in prof.get("phases", []):
            n = ph["name"]
            if n not in by_name:
                by_name[n] = []
                phase_order.append(n)
            by_name[n].append(ph)
    phases = []
    for n in phase_order:
        entries = by_name[n]
        # For parallel subswath runs, the phase wall-time is the max of
        # per-subswath durations (the slowest subswath dominates). Using
        # max(end_epoch) - min(start_epoch) across subswaths overcounts:
        # near-zero-duration phases (e.g. P2P5_unwrap at the subswath
        # level, where snaphu is deferred to merge) would otherwise pick
        # up the gap between subswath finish times. max-of-durations is
        # also the right answer for sequential runs, since the slowest
        # subswath equals the sum when subswaths run disjointly per-phase.
        # We still record min(start)/max(end) for diagnostic purposes
        # (lets the reader see if subswaths overlapped).
        durations = [float(e.get("duration_sec", 0.0)) for e in entries]
        starts = [e.get("start_epoch") for e in entries if e.get("start_epoch") is not None]
        ends   = [e.get("end_epoch")   for e in entries if e.get("end_epoch")   is not None]
        entry = {
            "name": n,
            "duration_sec": round(max(durations) if durations else 0.0, 3),
            "subswath_count": len(entries),
            "per_subswath_sec": [round(d, 3) for d in durations],
        }
        if starts and ends:
            entry["start_epoch_min"] = min(starts)
            entry["end_epoch_max"]   = max(ends)
        phases.append(entry)

    if extra_phases:
        phases.extend(extra_phases)

    total = round(sum(float(p.get("duration_sec", 0.0)) for p in phases), 3)
    out = {
        "side": "py",
        "case": case,
        "scope": "frame_aggregate",
        "subswaths": [os.path.basename(d.rstrip(os.sep)) for d in subswath_dirs
                      if _read_profile(os.path.join(d, "phase_profile_py.json"))],
        "phases": phases,
        "binaries": binaries,
        "total_sec": total,
    }
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    return out


# Auto-dump on interpreter exit so even crashed runs leave a profile.
def _atexit_dump():
    if _PHASES:
        try:
            dump_profile()
        except Exception:
            pass

atexit.register(_atexit_dump)


# -- post-hoc profiling from csh log.txt ---------------------------------
# The csh recipe (p2p_processing.csh) and align.csh print stage markers
# like "ALIGN.CSH - START" / "ALIGN.CSH - END" mixed with `time` output.
# This parses log.txt for stage entry/exit markers and elapsed-time
# lines to build the same JSON.

_CSH_STAGE_PATTERNS = [
    # (marker_re_start, marker_re_end, canonical_name)
    (r'(?i)preprocess(?:\.csh)?\s*-\s*start',  r'(?i)preprocess(?:\.csh)?\s*-\s*end',  "P2P1_preprocess"),
    (r'(?i)align(?:\.csh)?\s*-\s*start',       r'(?i)align(?:\.csh)?\s*-\s*end',       "P2P2_focus_align"),
    (r'(?i)dem2topo_ra\s*-\s*start',           r'(?i)dem2topo_ra\s*-\s*end',           "P2P3_make_topo"),
    (r'(?i)intf\s*-\s*start',                  r'(?i)intf\s*-\s*end',                  "P2P4_intf"),
    (r'(?i)filter\s*-\s*start',                r'(?i)filter\s*-\s*end',                "P2P4_filter"),
    (r'(?i)snaphu(?:\.csh)?\s*-\s*start',      r'(?i)snaphu(?:\.csh)?\s*-\s*end',      "P2P5_unwrap"),
    (r'(?i)geocode(?:\.csh)?\s*-\s*start',     r'(?i)geocode(?:\.csh)?\s*-\s*end',     "P2P6_geocode"),
]


def phase_profile_from_csh_log(log_path: str,
                               out_path: str = "phase_profile_csh.json",
                               case: Optional[str] = None) -> dict:
    """Build phase_profile_csh.json from log.txt timestamps.

    Looks for "STAGE - START" / "STAGE - END" pairs and uses the line's
    inferred time-of-arrival from any preceding `elapsed time: N.NNNNN`
    or unix-timestamp prefixes. Fallback: line ordinal + sweep_log
    DONE/RUN markers (best-effort).
    """
    phases: list[dict] = []
    # First pass: collect each START/END line index and any nearby "elapsed
    # time: X" measurement (the gmtsar pipeline binaries emit those).
    with open(log_path, errors="ignore") as f:
        lines = f.readlines()

    for start_re, end_re, name in _CSH_STAGE_PATTERNS:
        srx, erx = re.compile(start_re), re.compile(end_re)
        s_idx = e_idx = None
        for i, ln in enumerate(lines):
            if s_idx is None and srx.search(ln):
                s_idx = i
            elif s_idx is not None and erx.search(ln):
                e_idx = i
                break
        if s_idx is None or e_idx is None:
            continue
        # Sum any "elapsed time: N" lines between start and end as a
        # rough phase wall time. (gmtsar C binaries print these.)
        secs = 0.0
        for ln in lines[s_idx:e_idx + 1]:
            m = re.search(r'elapsed time:\s*([\d.]+)', ln)
            if m:
                secs += float(m.group(1))
        phases.append({
            "name": name,
            "duration_sec": round(secs, 3),
            "start_line": s_idx,
            "end_line": e_idx,
        })

    total = round(sum(p["duration_sec"] for p in phases), 3)
    out = {"side": "csh", "case": case, "phases": phases,
           "total_sec": total, "src_log": os.path.abspath(log_path)}
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    return out
