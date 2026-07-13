#!/usr/bin/env python3
"""sweep.py — download + run + compare every case in cases.caseNameList.

Python port of sweep.sh + runner.py (2026-07-13), collapsed into one file:
sweep.sh's bash orchestration (download scheduling, bounded parallelism,
SWEEP_FORCE wipe, hw/sw snapshot) and runner.py's per-case dispatch loop are
now one layer instead of two, since runner.py was already a thin wrapper
around spawning case_runner subprocesses. case_runner.py still does the
actual per-case work as its own process (needed for signal/process-group
isolation, same as the original bash design).

Real CLI args replace env vars for anything the CALLER sets (--fast/--full,
--parallel, --force, --cases, --topo-mode-ab) -- see project_rules.md and
the 2026-07-13 session note on why: env vars are easy to lose across shells.
TEST_CASES=<name> is still honored as a fallback for existing docs/muscle
memory, but --cases is now the documented way. Internal env vars that must
cross a subprocess boundary (thread pins, LD_PRELOAD, GMTSAR_PROFILE) are
unavoidable regardless of language and stay as such -- they're set fresh in
case_runner.py per case, not read from the caller's shell.

Usage:
    python3 sweep.py                       # full sweep, all 21 cases (~3h)
    python3 sweep.py --full                # same, explicit
    python3 sweep.py --fast                # 12 cases (~27 min)
    python3 sweep.py --fast --cases RS2_SLC_Hawaii
    python3 sweep.py --fast --parallel 6   # cap concurrent cases (default 12)
    python3 sweep.py --force               # hard: wipe csh_test+python_test+results
    python3 sweep.py --force py            # soft: wipe only python_test+results
    python3 sweep.py --force stage         # wipe only stage-cache sentinels
    python3 sweep.py --fast --topo-mode-ab # py(mode0) vs py(mode1), not csh-vs-py

Logs: gmtsar/python/work/sweep.log + per-case work/{csh,python}_test/<case>/log.txt
(or ref_test/new_test when --topo-mode-ab).
"""
from __future__ import annotations

import argparse
import glob
import gzip
import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)


def _log_line(log_path: str, msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(log_path, "a") as f:
        f.write(line + "\n")


def _derive_gmtsar() -> str:
    gmtsar = os.environ.get("GMTSAR")
    if gmtsar:
        return gmtsar
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=_HERE,
                              capture_output=True, text=True, timeout=5).stdout.strip()
        if out:
            return out
    except Exception:
        pass
    print("sweep.py: cannot derive GMTSAR — set GMTSAR env var or run from inside the git repo",
          file=sys.stderr)
    sys.exit(1)


def _hw_sw_snapshot(work: str, tests_dir: str, max_parallel: int) -> str:
    perf_file = os.path.join(work, f"perf_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
    lines = ["=== hardware ==="]
    lines.append(f"host: {platform.node()}")
    cpu_model = ""
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name"):
                    cpu_model = line.split(":", 1)[1].strip()
                    break
    except OSError:
        pass
    lines.append(f"cpu_model: {cpu_model}")
    lines.append(f"cpu_cores_logical: {os.cpu_count()}")
    ram_gb = ""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    ram_gb = f"{kb/1024/1024:.1f}G"
                    break
    except OSError:
        pass
    lines.append(f"ram_total: {ram_gb}")
    try:
        fs = subprocess.run(["stat", "--file-system", "-c", "%T", work],
                             capture_output=True, text=True).stdout.strip()
    except Exception:
        fs = "?"
    lines.append(f"workdir_fs: {fs}")
    try:
        mount = subprocess.run(["df", work], capture_output=True, text=True).stdout.splitlines()[1].split()[0]
    except Exception:
        mount = "?"
    lines.append(f"workdir_mount: {mount}")
    lines.append("")
    lines.append("=== software ===")
    lines.append(f"kernel: {platform.uname().system} {platform.uname().release} {platform.uname().machine}")
    lines.append(f"python: Python {platform.python_version()}")
    try:
        gmt_v = subprocess.run(["gmt", "--version"], capture_output=True, text=True).stdout.strip()
    except FileNotFoundError:
        gmt_v = "gmt not on PATH at sweep time"
    lines.append(f"gmt: {gmt_v}")
    repo_root = os.path.dirname(os.path.dirname(tests_dir))
    def _git(args):
        try:
            return subprocess.run(["git"] + args, cwd=repo_root, capture_output=True,
                                   text=True, timeout=5).stdout.strip()
        except Exception:
            return ""
    lines.append(f"git_sha: {_git(['rev-parse', '--short', 'HEAD']) or 'no git'}")
    lines.append(f"git_branch: {_git(['rev-parse', '--abbrev-ref', 'HEAD']) or '-'}")
    dirty = subprocess.run(["git", "diff", "--quiet"], cwd=repo_root).returncode != 0
    lines.append(f"git_dirty: {'yes' if dirty else 'no'}")
    lines.append("")
    lines.append("=== thread limits (intended by case_runner.py) ===")
    for v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "FFTW_NUM_THREADS"):
        lines.append(f"{v}={os.environ.get(v, 'unset')}")
    lines.append("")
    lines.append("=== sweep ===")
    lines.append(f"started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"max_parallel: {max_parallel}")
    with open(perf_file, "w") as f:
        f.write("\n".join(lines) + "\n")
    return perf_file


def _wipe_stale(path: str) -> None:
    """rename-then-delete so we survive NFS .nfs* lock files."""
    if not os.path.isdir(path):
        return
    stale = f"{path}.stale.{os.getpid()}.{int(time.time()*1e9)}"
    try:
        os.rename(path, stale)
    except OSError:
        print(f"sweep.py: WIPE FAILED to rename {path}; aborting (won't run with stale outputs)",
              file=sys.stderr)
        sys.exit(1)
    threading.Thread(target=shutil.rmtree, args=(stale,), kwargs={"ignore_errors": True},
                      daemon=True).start()


def _apply_force(cases: list[str], mode: str, work: str, log_path: str,
                  csh_root_name: str, py_root_name: str) -> None:
    if mode == "stage":
        for c in cases:
            py_dir = os.path.join(work, py_root_name, c)
            if os.path.isdir(py_dir):
                # Matches the original `find <py_dir> -maxdepth 3 -name
                # .stage_done_*`: only purge sentinels, leave outputs intact
                # so a stale-cache-hit suspicion can be diagnosed post-hoc.
                base_depth = py_dir.rstrip(os.sep).count(os.sep)
                sentinels = []
                for root, _dirs, files in os.walk(py_dir):
                    if root.rstrip(os.sep).count(os.sep) - base_depth > 2:
                        _dirs[:] = []
                        continue
                    sentinels.extend(os.path.join(root, f) for f in files
                                      if f.startswith(".stage_done_"))
                for s in sentinels:
                    os.remove(s)
                _log_line(log_path, f"WIPE {c} (--force stage — removed {len(sentinels)} "
                                     f"stage-cache sentinels under {py_dir}; outputs preserved)")
            else:
                _log_line(log_path, f"WIPE {c} (--force stage — nothing to do, no {py_dir})")
        return
    wipe_csh = mode == "hard"
    for c in cases:
        targets = [os.path.join(work, py_root_name, c)]
        if wipe_csh:
            targets.insert(0, os.path.join(work, csh_root_name, c))
        for d in targets:
            _wipe_stale(d)
        results_json = os.path.join(work, "results", f"{c}.json")
        if os.path.exists(results_json):
            os.remove(results_json)
        if wipe_csh:
            _log_line(log_path, f"WIPE {c} (--force hard — {csh_root_name}, {py_root_name}, results cleared)")
        else:
            _log_line(log_path, f"WIPE {c} (--force py soft — {py_root_name}, results cleared; "
                                 f"{csh_root_name} preserved as reference)")


def _already_verified(case: str, work: str) -> bool:
    rj = os.path.join(work, "results", f"{case}.json")
    if not os.path.isfile(rj):
        return False
    try:
        d = json.load(open(rj))
    except Exception:
        return False
    comps = d.get("comparisons", [])
    # A genuinely verified case has ALL comparisons SUCCESS AND at least 6
    # of them (3 PNG + 3 grd). Fewer than 6 means the python run aborted
    # mid-pipeline (e.g. unwrap crash) so the comparison set is incomplete.
    return len(comps) >= 6 and all(x.get("status") == "SUCCESS" for x in comps)


def _gzip_ok(path: str) -> int:
    """0 = valid, 1 = corrupt (safe to delete+retry), >=128 = killed by
    signal (leave tarball intact for retry -- an external pkill matching the
    filename shouldn't force a needless multi-GB re-download)."""
    try:
        with gzip.open(path, "rb") as f:
            while f.read(1 << 20):
                pass
        return 0
    except OSError:
        return 1
    except Exception:
        return 1


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    tier = p.add_mutually_exclusive_group()
    tier.add_argument("--fast", action="store_true")
    tier.add_argument("--full", action="store_true")
    p.add_argument("--parallel", "-p", type=int, default=12)
    p.add_argument("--force", nargs="?", const="hard", default=None,
                   choices=["hard", "py", "stage"],
                   help="hard (default if bare): wipe csh+python+results. "
                        "py: wipe only python+results. stage: wipe only "
                        "stage-cache sentinels.")
    p.add_argument("--cases", nargs="+", default=None,
                   help="run only these cases (else TEST_CASES env var, else the tier list)")
    p.add_argument("--topo-mode-ab", action="store_true",
                   help="py(mode0) vs py(mode1) instead of csh-vs-py")
    p.add_argument("--profile", action="store_true")
    args = p.parse_args()

    gmtsar = _derive_gmtsar()
    os.environ["GMTSAR"] = gmtsar
    os.environ["PATH"] = os.path.join(gmtsar, "bin") + ":" + os.environ.get("PATH", "")
    if not shutil.which("python3"):
        print("sweep.py: python3 not on PATH — activate conda env or set PATH", file=sys.stderr)
        sys.exit(1)

    tests_dir = _HERE
    tier_name = "fast" if args.fast else "full"
    os.environ["TEST_TIER"] = tier_name
    if args.topo_mode_ab:
        os.environ["TOPO_MODE_AB"] = "1"  # cases.py still reads this to pick tree names
    # tools/perf_snapshot.py introspects these two as env vars for its
    # Config: line -- set them here (parent->child signal, not a
    # caller-facing footgun) so its report doesn't regress to always
    # showing "(not constrained)" now that they're real CLI args.
    os.environ["MAX_PARALLEL"] = str(args.parallel)
    os.environ["SWEEP_FORCE"] = args.force or ""

    from cases import CASES, caseNameList, archive_path, archive_url, \
        workAbsoluteDir, pythonRunRoot, cshRefRoot, datasetRoot, recipesDir

    work = workAbsoluteDir.rstrip(os.sep)
    log_path = os.path.join(work, "sweep.log")
    os.makedirs(datasetRoot, exist_ok=True)
    os.makedirs(work, exist_ok=True)
    os.makedirs(pythonRunRoot, exist_ok=True)
    os.makedirs(cshRefRoot, exist_ok=True)
    os.makedirs(os.path.join(work, "results"), exist_ok=True)

    src_recipes = os.path.join(tests_dir, "recipes")
    os.makedirs(recipesDir, exist_ok=True)
    for f in os.listdir(src_recipes):
        dst = os.path.join(recipesDir, f)
        if not os.path.exists(dst):
            shutil.copy2(os.path.join(src_recipes, f), dst)

    if args.cases:
        cases = args.cases
    elif os.environ.get("TEST_CASES"):
        cases = [c.strip() for c in os.environ["TEST_CASES"].split(",") if c.strip()]
    else:
        cases = caseNameList

    _log_line(log_path, "=== sweep started ===")
    _log_line(log_path, f"cases: {' '.join(cases)}")

    perf_file = _hw_sw_snapshot(work, tests_dir, args.parallel)
    _log_line(log_path, f"hw+sw snapshot → {perf_file}")
    with open(perf_file, "a") as f:
        f.write(f"cases: {' '.join(cases)}\n")

    csh_root_name = os.path.basename(cshRefRoot.rstrip(os.sep))
    py_root_name = os.path.basename(pythonRunRoot.rstrip(os.sep))

    if args.force:
        _apply_force(cases, args.force, work, log_path, csh_root_name, py_root_name)
    else:
        cases = [c for c in cases if not _already_verified(c, work)]
        if not cases:
            _log_line(log_path, "all cases already verified — nothing to do")
            return

    tarball = {c: archive_path(c) for c in cases}
    url = {c: archive_url(c) for c in cases}

    _log_line(log_path, f"max parallel cases: {args.parallel}")

    # Kick off a background download for every case. Reuses an already-
    # complete/partial file via `wget -c` semantics (resume, or near-instant
    # HEAD-only check if already complete).
    dl_procs: dict[str, subprocess.Popen] = {}
    for c in cases:
        dl_procs[c] = subprocess.Popen(
            ["wget", "-c", "-q", "--timeout=60", "--tries=3", url[c], "-O", tarball[c]])
        _log_line(log_path, f"DOWNLOAD start (background) {c}")

    preload_shim = os.path.abspath(os.path.join(tests_dir, os.pardir, "fftw_force_serial.so"))
    time_log = os.path.join(work, "timeSpentLog.txt")

    sem = threading.Semaphore(args.parallel)
    threads: list[threading.Thread] = []

    def _run_one(c: str):
        with sem:
            p = dl_procs[c]
            rc = p.wait()
            if rc != 0 or not os.path.isfile(tarball[c]) or not os.path.getsize(tarball[c]):
                _log_line(log_path, f"DOWNLOAD FAIL {c} (wget rc={rc}) — skipping")
                return
            gz_rc = _gzip_ok(tarball[c])
            if gz_rc != 0:
                _log_line(log_path, f"INTEGRITY FAIL {c} — tarball corrupt; removing and skipping")
                os.remove(tarball[c])
                return
            size = os.path.getsize(tarball[c])
            _log_line(log_path, f"DOWNLOAD OK {c} ({size/1e6:.0f}M)")
            _log_line(log_path, f"RUN {c} — starting")
            t0 = time.time()
            case_log = open(os.path.join(work, f".case_{c}.log"), "w")
            cmd = [sys.executable, os.path.join(tests_dir, "case_runner.py"),
                   c, os.path.join(work, csh_root_name, c), os.path.join(work, py_root_name, c),
                   tarball[c], os.path.join(recipesDir, f"README_{c}.txt"), time_log,
                   "--preload-shim", preload_shim, "--gmtsar-bin", os.path.join(gmtsar, "bin")]
            if args.topo_mode_ab:
                cmd.append("--topo-mode-ab")
            if args.profile:
                cmd.append("--profile")
            subprocess.run(cmd, stdout=case_log, stderr=subprocess.STDOUT, cwd=tests_dir,
                            start_new_session=True)
            case_log.close()
            with open(os.path.join(work, f".case_{c}.log")) as f:
                shutil.copyfileobj(f, open(log_path, "a"))
            os.remove(os.path.join(work, f".case_{c}.log"))
            _log_line(log_path, f"DONE {c} ({int(time.time()-t0)}s)")

    for c in cases:
        t = threading.Thread(target=_run_one, args=(c,))
        t.start()
        threads.append(t)
    for t in threads:
        t.join()

    _log_line(log_path, "all case runs complete")

    # Final comparison — same in-process call runner.py used to make, now
    # invoked directly from here since runner.py's dispatch loop is gone.
    os.chdir(work)
    import runpy
    runpy.run_path(os.path.join(tests_dir, "compare.py"), run_name="__main__")

    subprocess.run([sys.executable, os.path.join(tests_dir, "report.py")],
                    cwd=tests_dir, stdout=open(log_path, "a"), stderr=subprocess.STDOUT)
    _log_line(log_path, f"summary written to {os.path.join(work, 'sweep_summary.md')}")

    blessed_tool = os.path.join(tests_dir, "blessed_diff.py")
    if os.path.isfile(blessed_tool) and not args.topo_mode_ab:
        _log_line(log_path, "Running blessed scorecard diff...")
        rc = subprocess.run([sys.executable, blessed_tool], cwd=tests_dir,
                             stdout=open(log_path, "a"), stderr=subprocess.STDOUT).returncode
        _log_line(log_path, "blessed diff PASS" if rc == 0 else
                   f"WARN: blessed diff reported regressions — see {work}/blessed_diff_*.md")
    else:
        _log_line(log_path, f"WARN: {blessed_tool} missing or --topo-mode-ab — skipping blessed scorecard diff")

    snapshot_tool = os.path.join(gmtsar, "gmtsar", "python", "tools", "perf_snapshot.py")
    if os.path.isfile(snapshot_tool) and not args.topo_mode_ab:
        rc = subprocess.run([sys.executable, snapshot_tool, "--label", tier_name],
                             cwd=tests_dir, stdout=open(log_path, "a"),
                             stderr=subprocess.STDOUT).returncode
        _log_line(log_path, "perf snapshot written under docs/perf_snapshots/" if rc == 0 else
                   "WARN: perf_snapshot.py failed (non-fatal)")
    else:
        _log_line(log_path, f"WARN: {snapshot_tool} missing or --topo-mode-ab — skipping rule-7 snapshot")

    _log_line(log_path, "=== sweep finished ===")


if __name__ == "__main__":
    main()
