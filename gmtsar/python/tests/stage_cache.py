#!/usr/bin/env python3
"""stage_cache — per-stage skip-cache for the P2Pn pipeline (Mira #52).

A stage-level "did this already run with these exact inputs?" check that
lets the test harness skip re-running unchanged pipeline stages between
sweeps. Designed for the case where a developer changes a single bin_py
module and re-runs the same case: stages whose inputs haven't moved
should not waste 10-20× wall time recomputing the same bytes.

Hard constraints (see briefing):

  * Wrong cache = silent wrong test result. Default OFF; only active when
    the developer explicitly opts in via `GMTSAR_STAGE_CACHE=1`.
  * Cascade: stage N's key includes stage N-1's key, so an upstream change
    invalidates every downstream sentinel automatically.
  * No silent fall-through: an unreadable sentinel is treated as a miss,
    not a hit. A cache miss is always safe (it just re-runs); a wrongly-
    classified hit is the disaster we will never let happen.

Public API (used by p2p_processing):

  compute_cache_key(stage, input_paths, code_files, config_vals,
                    parent_key=None) -> str
      Returns a hex SHA-256 over (stage name, sorted file fingerprints
      [path, size, mtime_ns], sorted code-file fingerprints, sorted
      config-value repr, parent_key). Missing input files → key includes
      a "MISSING:<path>" sentinel string (still deterministic, won't crash).

  is_cached(case_dir, stage, key) -> bool
      Returns True iff `case_dir/.stage_done_<stage>` exists, parses as
      our sentinel format, and its recorded key matches `key` exactly.
      Returns False if cache is disabled, sentinel is missing, sentinel
      is corrupt, or key differs. Never raises on a malformed sentinel.

  mark_cached(case_dir, stage, key) -> None
      Writes the sentinel atomically (tempfile + rename) recording the
      key, timestamp, and process metadata. Safe to call after a
      successful stage; idempotent on identical keys.

  invalidate(case_dir, stage=None) -> int
      Remove sentinel(s). Returns count removed. `stage=None` removes ALL
      stage sentinels in case_dir. Used by SWEEP_FORCE=stage.

  is_enabled() -> bool
      Returns True iff GMTSAR_STAGE_CACHE=1. Single point of control so
      callers don't need to scatter env checks.

Env knobs:

  GMTSAR_STAGE_CACHE       "1" enables; anything else disables (default).
  GMTSAR_STAGE_CACHE_DEBUG "1" prints per-stage key/decision to stderr.

Sentinel file format (text, line-based, easy to inspect by hand):

    # stage_cache sentinel — gmtsar/python/tests/stage_cache.py
    stage=<name>
    key=<hex sha256>
    written_at=<iso8601 utc>
    fwk_sha=<git short sha or "no-git">
    pid=<int>

This module is import-safe (no side effects at import time) and has no
dependencies outside the Python stdlib so it can be loaded from
p2p_processing without dragging the test harness in.
"""
from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Optional


# ───────────────────────────────────────────────────────────────── enable ───

def is_enabled() -> bool:
    """Single source of truth for whether stage caching is active.

    Default-OFF semantics: any value other than literal "1" is treated as
    disabled, including "0", "yes", "true", "" — by design, to avoid the
    "it kind of worked but actually no" failure mode of accepting many
    truthy variants.
    """
    return os.environ.get("GMTSAR_STAGE_CACHE", "0") == "1"


def _debug_enabled() -> bool:
    return os.environ.get("GMTSAR_STAGE_CACHE_DEBUG", "0") == "1"


def _dbg(msg: str) -> None:
    if _debug_enabled():
        sys.stderr.write(f"[stage_cache] {msg}\n")


# ─────────────────────────────────────────────────────────────────── key ───

def _file_fingerprint(path: str | Path) -> str:
    """Compact stat-based fingerprint: (size, mtime_ns) or MISSING sentinel.

    We deliberately use stat() rather than content hashing — the inputs to
    a stage can be multi-GB SLC files; rehashing them on every cache
    check would defeat the purpose. mtime_ns + size catches every case
    we care about (file rewritten, file truncated/extended) and matches
    the granularity of what the underlying tools see when they re-read
    the file. Cost: ~1 μs per file vs ~1 s per file for a content hash.
    """
    p = Path(path)
    try:
        st = p.stat()
    except (FileNotFoundError, PermissionError, OSError):
        return f"MISSING:{p}"
    return f"{p}:size={st.st_size}:mtime_ns={st.st_mtime_ns}"


def compute_cache_key(
    stage: str,
    input_paths: Iterable[str | Path],
    code_files: Iterable[str | Path] = (),
    config_vals: Optional[Mapping[str, object]] = None,
    parent_key: Optional[str] = None,
) -> str:
    """SHA-256 over (stage, inputs, code, config, parent_key).

    Components are sorted before hashing so the key is order-independent.
    parent_key threads the upstream-stage key through, so any change in
    P2P1's inputs invalidates every downstream sentinel through the
    cascade.

    Returns a 64-char lowercase hex string.
    """
    h = hashlib.sha256()
    h.update(f"stage={stage}\n".encode("utf-8"))

    # Inputs (sorted, deduplicated by string repr).
    inputs = sorted({str(p): _file_fingerprint(p) for p in input_paths}.items())
    for k, fp in inputs:
        h.update(f"input:{k}={fp}\n".encode("utf-8"))

    # Code-file fingerprints (sorted).
    codes = sorted({str(p): _file_fingerprint(p) for p in code_files}.items())
    for k, fp in codes:
        h.update(f"code:{k}={fp}\n".encode("utf-8"))

    # Config values (sorted by key, value repr'd).
    if config_vals:
        for k in sorted(config_vals.keys()):
            h.update(f"cfg:{k}={config_vals[k]!r}\n".encode("utf-8"))

    if parent_key:
        h.update(f"parent={parent_key}\n".encode("utf-8"))

    return h.hexdigest()


# ───────────────────────────────────────────────────────────── sentinels ───

def _sentinel_path(case_dir: str | Path, stage: str) -> Path:
    return Path(case_dir) / f".stage_done_{stage}"


def is_cached(case_dir: str | Path, stage: str, key: str) -> bool:
    """True iff the sentinel exists AND its recorded key matches `key`.

    Disabled cache → always False.
    Missing sentinel → False (safe miss, re-runs the stage).
    Corrupt sentinel → False + debug log (never raise).
    Key mismatch → False.
    Exact key match → True.
    """
    if not is_enabled():
        return False
    sp = _sentinel_path(case_dir, stage)
    if not sp.is_file():
        _dbg(f"miss {stage}: no sentinel at {sp}")
        return False
    try:
        text = sp.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        _dbg(f"miss {stage}: sentinel unreadable ({e})")
        return False
    recorded = None
    for line in text.splitlines():
        if line.startswith("key="):
            recorded = line.split("=", 1)[1].strip()
            break
    if recorded is None:
        _dbg(f"miss {stage}: sentinel has no key line")
        return False
    if recorded == key:
        _dbg(f"hit  {stage}: key {key[:12]}...")
        return True
    _dbg(f"miss {stage}: key changed ({recorded[:12]}... → {key[:12]}...)")
    return False


def mark_cached(case_dir: str | Path, stage: str, key: str) -> None:
    """Write the sentinel atomically (tempfile + rename in same dir).

    Safe to call when the cache is disabled — emits the sentinel anyway
    so a later run with cache enabled can pick it up.
    """
    cd = Path(case_dir)
    cd.mkdir(parents=True, exist_ok=True)
    sp = _sentinel_path(cd, stage)
    fwk_sha = _git_short_sha(cd)
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = (
        f"# stage_cache sentinel — gmtsar/python/tests/stage_cache.py\n"
        f"stage={stage}\n"
        f"key={key}\n"
        f"written_at={now_iso}\n"
        f"fwk_sha={fwk_sha}\n"
        f"pid={os.getpid()}\n"
    )
    # Atomic write: tempfile in same dir → rename. Avoids the half-written
    # sentinel masquerading as a complete cache hit if the process is killed
    # mid-write.
    fd, tmp = tempfile.mkstemp(prefix=".stage_done_", dir=str(cd))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        os.replace(tmp, sp)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    _dbg(f"write {stage}: {sp} (key {key[:12]}...)")


def invalidate(case_dir: str | Path, stage: Optional[str] = None) -> int:
    """Remove sentinel(s). Returns count removed.

    stage=None → remove ALL .stage_done_* in case_dir.
    stage='P2P3' → remove only that one.
    Used by SWEEP_FORCE=stage to wipe the cache without touching outputs.
    """
    cd = Path(case_dir)
    if not cd.is_dir():
        return 0
    if stage is not None:
        sp = _sentinel_path(cd, stage)
        if sp.is_file():
            sp.unlink()
            return 1
        return 0
    n = 0
    for s in cd.glob(".stage_done_*"):
        try:
            s.unlink()
            n += 1
        except OSError:
            pass
    return n


# ────────────────────────────────────────────────────────────── helpers ───

def _git_short_sha(start_dir: str | Path) -> str:
    """Best-effort `git rev-parse --short HEAD` from start_dir. Falls back
    to 'no-git' if git is missing or we're not inside a worktree."""
    import subprocess
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(start_dir),
            capture_output=True, text=True, timeout=2,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return "no-git"


# ─────────────────────────────────────────────────────── high-level helper ───

def cached_stage(
    case_dir: str | Path,
    stage: str,
    *,
    input_paths: Iterable[str | Path] = (),
    code_files: Iterable[str | Path] = (),
    config_vals: Optional[Mapping[str, object]] = None,
    parent_key: Optional[str] = None,
):
    """Context-manager-style helper used by p2p_processing.

    Usage:

        with cached_stage(cwd, "P2P1",
                          input_paths=[...],
                          code_files=[...],
                          config_vals={...}) as cs:
            if cs.hit:
                pass  # stage skipped
            else:
                # ... run the stage body ...
                pass
            cs.parent_key  # always set; pass to next stage as parent_key=

    The context manager is responsible for writing the sentinel on a
    clean exit (no exception raised within the block) and for recording
    the key as parent_key for the next stage. On an exception inside the
    block, the sentinel is NOT written (so a crashed stage is re-run
    next time).
    """
    return _CachedStage(case_dir, stage, input_paths, code_files,
                        config_vals, parent_key)


class _CachedStage:
    def __init__(self, case_dir, stage, input_paths, code_files,
                 config_vals, parent_key):
        self.case_dir = case_dir
        self.stage = stage
        self.key = compute_cache_key(
            stage, input_paths, code_files, config_vals, parent_key
        )
        self.parent_key = self.key
        self.hit: bool = False

    def __enter__(self):
        self.hit = is_cached(self.case_dir, self.stage, self.key)
        return self

    def __exit__(self, exc_type, exc, tb):
        # Only write the sentinel on clean exit AND only if we actually ran
        # the stage (i.e. it wasn't a cache hit). A hit means the sentinel
        # already exists with this exact key; rewriting it would just bump
        # the timestamp.
        #
        # CRITICAL: only write when the cache is enabled. Otherwise a
        # subsequent run that turns the cache ON would see a sentinel
        # written under cache-OFF semantics (no audit of input paths) and
        # treat the run as cached when we never validated it as such. This
        # is the silent-wrong-result trap the briefing warned about.
        if exc_type is None and not self.hit and is_enabled():
            mark_cached(self.case_dir, self.stage, self.key)
        return False  # never suppress exceptions
