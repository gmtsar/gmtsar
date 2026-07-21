"""profiler — lightweight per-command + per-stage timing for the
gmtsar Python framework. Writes a per-case JSON to
work/profile_<case>.json that aggregation can mine for "where is the
3-hour sweep spending its wall time?".

Design:

- Activated by setting `GMTSAR_PROFILE=1` in the env. Otherwise every
  function here is a no-op (~5 ns per call); zero overhead in
  non-profiled runs.
- Records `{command, wall_s, backend}` per gmt-related call:
    backend ∈ {"clib", "subprocess", "xarray", "subprocess-pipe"}
- Records stage-level wall time when a P2P stage uses
  `with profiler.stage("P2P3 dem2topo_ra"):` blocks.
- On Python exit, writes the JSON via atexit.

The output file path: $GMTSAR_PROFILE_OUT (default
`./profile.json` in the current working directory). Sweep + case_runner
pass `GMTSAR_PROFILE_OUT=<workdir>/profile_<case>.json` so each case
lands in its own file.

Schema (json):
{
  "case": "<set by env>",
  "started":  "<ISO-8601 timestamp>",
  "calls":    [{"cmd": "gmt surface ...", "wall_s": 0.012,
                "backend": "clib"}, ...],
  "stages":   [{"name": "P2P3", "wall_s": 70.2}, ...],
  "totals":   {"all_calls_wall_s": 234.5, "n_calls": 1882},
}
"""
from __future__ import annotations

import atexit
import json
import os
import time
from contextlib import contextmanager
from typing import Iterator

ENABLED = os.environ.get("GMTSAR_PROFILE", "") == "1"
_OUT_PATH = os.environ.get("GMTSAR_PROFILE_OUT", "profile.json")
_CASE = os.environ.get("GMTSAR_PROFILE_CASE", "unknown")

_calls: list[dict] = []
_stages: list[dict] = []
_started = time.time() if ENABLED else None


def record(cmd: str, wall_s: float, backend: str = "subprocess") -> None:
    """Append a single timing record. Cheap when ENABLED is False."""
    if not ENABLED:
        return
    # Trim the command to keep the JSON small. Keep the binary name +
    # the first sub-arg (usually the file or subcommand).
    short = cmd.split()
    if len(short) > 6:
        short = short[:6] + ["..."]
    _calls.append({"cmd": " ".join(short), "wall_s": round(wall_s, 4),
                   "backend": backend})


@contextmanager
def stage(name: str) -> Iterator[None]:
    """Bracket a code region as a named stage. Records the wall time."""
    if not ENABLED:
        yield
        return
    t0 = time.time()
    try:
        yield
    finally:
        _stages.append({"name": name, "wall_s": round(time.time() - t0, 3)})


@contextmanager
def time_block(cmd: str, backend: str = "subprocess") -> Iterator[None]:
    """Bracket one command. Equivalent to record(cmd, dt, backend)
    around the timed work."""
    if not ENABLED:
        yield
        return
    t0 = time.time()
    try:
        yield
    finally:
        record(cmd, time.time() - t0, backend=backend)


def _flush() -> None:
    """Write the JSON. Registered via atexit."""
    if not ENABLED:
        return
    try:
        # If file already exists from an earlier import-level write,
        # merge our calls/stages so multi-process runs don't clobber.
        existing = {"case": _CASE, "calls": [], "stages": [], "totals": {}}
        if os.path.exists(_OUT_PATH):
            try:
                with open(_OUT_PATH) as f:
                    existing = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        existing.setdefault("case", _CASE)
        existing.setdefault("started", time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                     time.gmtime(_started)))
        existing.setdefault("calls", []).extend(_calls)
        existing.setdefault("stages", []).extend(_stages)
        existing["totals"] = {
            "all_calls_wall_s": round(sum(c["wall_s"] for c in existing["calls"]), 3),
            "n_calls": len(existing["calls"]),
            "n_stages": len(existing["stages"]),
        }
        # Ensure parent dir exists
        d = os.path.dirname(os.path.abspath(_OUT_PATH))
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        with open(_OUT_PATH, "w") as f:
            json.dump(existing, f, indent=2)
    except Exception as e:
        # Profiling must never fail the run.
        print(f"profiler: WARN failed to write {_OUT_PATH}: {e}")


if ENABLED:
    atexit.register(_flush)
