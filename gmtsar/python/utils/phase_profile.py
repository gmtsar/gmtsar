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
