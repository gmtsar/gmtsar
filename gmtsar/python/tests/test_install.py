#!/usr/bin/env python3
"""test_install.py — clean-room verification of gmtsar/python/install.py.

Not a unit test of install.py's internals (see bin_py/tests/ for that) --
this actually RUNS install.py, for real, from a fresh `git clone` into a
new conda env (or a real apt install for --system ubuntu), the same way a
new user following README.md would. Catches the class of bug unit tests
and fixtures can't: wrong conda-forge package names, PATH/env assumptions
that only break outside this dev host, stale symlinks, etc. -- exactly
the two real bugs this tool's manual precursor (a one-off agent run) found
in install.py on 2026-07-13 (see git log for "gshhg-gmt" and
"locate_conda_env").

Two modes:
    --smoke (default)  fresh install + gmtsar_sharedir.csh (upstream's own
                        post-build sanity check, from .github/workflows/
                        gmtsar.yml) + the bin_py/tests/ unit/parity suite.
                        Minutes, not the better part of an hour.
    --full              --smoke, plus tests/sweep.py --fast (12 real
                        py-vs-csh cases) inside the same fresh clone.

Per project_rules.md Rule 14: everything is fresh (clone, conda env,
build, sweep outputs) EXCEPT the sample tarball cache, which is reused
from this checkout's own work/dataset/ if present -- re-downloading
multi-GB immutable fixtures on every clean-room run wastes time for zero
verification value.

Usage:
    python3 tests/test_install.py --system conda
    python3 tests/test_install.py --system conda --full
    python3 tests/test_install.py --system ubuntu --smoke
    python3 tests/test_install.py --system conda --keep   # don't rm the clone after
"""
from __future__ import annotations

import argparse
import datetime
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PYTHON_DIR = _HERE.parent  # gmtsar/python/
_REPO_ROOT = (_PYTHON_DIR / ".." / "..").resolve()

_LOG_PATH: Path | None = None


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _log(line: str) -> None:
    print(line)
    if _LOG_PATH is not None:
        with open(_LOG_PATH, "a") as f:
            f.write(line + "\n")


def _run(cmd: list[str], step_name: str, **kwargs) -> tuple[bool, float]:
    """Run a subprocess, teeing its combined output live + to the log
    (same discipline as install.py's own run()). Returns (passed, secs)
    -- does NOT raise, so the caller can keep going and report a full
    step-by-step summary instead of aborting on the first failure."""
    cmd_str = " ".join(cmd)
    _log(f"[{_utc_now()}] ==> [{step_name}] {cmd_str}")
    t0 = time.time()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True,
                             bufsize=1, **kwargs)
    for line in proc.stdout:
        _log(line.rstrip("\n"))
    rc = proc.wait()
    dt = time.time() - t0
    ok = rc == 0
    status = "PASS" if ok else f"FAIL (rc={rc})"
    _log(f"[{_utc_now()}] [{step_name}] {status} in {dt:.1f}s: {cmd_str}")
    return ok, dt


def _fresh_clone(work_root: Path) -> Path:
    ts = _utc_now().replace(":", "-")
    clone_dir = work_root / f"clone_{ts}"
    _log(f"[{_utc_now()}] git clone --local {_REPO_ROOT} -> {clone_dir}")
    subprocess.run(["git", "clone", "--local", str(_REPO_ROOT), str(clone_dir)],
                    check=True, capture_output=True)
    return clone_dir


def _reuse_tarball_cache(clone_python_dir: Path) -> None:
    """Rule 14: copy the tarball cache (immutable input data) into the
    fresh clone's work/dataset/ so sweep.py/case_runner.py don't
    re-download multi-GB fixtures. Everything ELSE in the clone's work/
    dir stays absent -- produced fresh by whatever this run actually
    does, never copied in."""
    src = _PYTHON_DIR / "work" / "dataset"
    if not src.is_dir():
        _log(f"[{_utc_now()}] no existing tarball cache at {src} -- "
             "sweep.py will download fresh (only relevant for --full)")
        return
    dst = clone_python_dir / "work" / "dataset"
    dst.mkdir(parents=True, exist_ok=True)
    n = 0
    for tarball in src.glob("*.tar.gz"):
        target = dst / tarball.name
        if not target.exists():
            shutil.copy2(tarball, target)
            n += 1
    for tarball in src.glob("*.tgz"):
        target = dst / tarball.name
        if not target.exists():
            shutil.copy2(tarball, target)
            n += 1
    _log(f"[{_utc_now()}] reused {n} cached tarball(s) from {src} -> {dst}")


def _check_sweep_results(clone_python_dir: Path) -> tuple[bool, str]:
    """sweep.py's own exit code only reflects whether the ORCHESTRATION
    crashed -- it returns 0 even when individual case comparisons FAIL
    (compare.py logs the failure but doesn't propagate it to sweep.py's
    exit status). The real pass/fail signal is compare.py's own
    per-comparison verdict in work/results/<case>.json (project_rules.md
    Rule 12b: "'pass' means compare.py's own criteria"). Real bug found
    2026-07-14: an earlier version of this function didn't exist at all
    -- test_install.py trusted sweep.py's exit code, reported a false
    PASS, and deleted the fresh clone (destroying the diagnostic
    evidence) despite 7 real comparison failures."""
    import json
    results_dir = clone_python_dir / "work" / "results"
    fails = []
    total = 0
    for f in sorted(results_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text())
        except Exception as exc:
            fails.append(f"{f.name}: could not parse ({exc!r})")
            continue
        for c in data.get("comparisons", []):
            if c.get("pair") != "py-vs-csh":
                continue
            total += 1
            if c.get("status") != "SUCCESS":
                fails.append(
                    f"{data.get('case', f.stem)}: {c.get('file')} "
                    f"[{c.get('intf', '')}] -> {c.get('status')} "
                    f"({c.get('metric_name')}={c.get('metric')})")
    if not fails:
        return True, f"{total}/{total} py-vs-csh comparisons SUCCESS"
    summary = f"{total - len(fails)}/{total} py-vs-csh comparisons SUCCESS -- FAILURES:\n"
    summary += "\n".join(f"    {line}" for line in fails)
    return False, summary


def _locate_fresh_conda_prefix(conda_env: str) -> Path | None:
    """install.py's locate_conda_env() may create the env under a conda
    base outside the usual search list (see its own docstring for the
    real bug this covers) -- ask `conda info` for the true env path
    rather than re-guessing common bases here."""
    conda_exe = os.environ.get("CONDA_EXE") or shutil.which("conda")
    if not conda_exe:
        return None
    try:
        out = subprocess.run([conda_exe, "env", "list"], capture_output=True,
                              text=True, timeout=15).stdout
    except Exception:
        return None
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # The env path is always the LAST whitespace-separated token,
        # whether or not conda printed a leading name column. conda only
        # shows a name for envs registered under the CURRENTLY-RESOLVED
        # conda installation's own envs_dirs -- an env belonging to a
        # different conda install on the same host (this dev host has
        # 3+: anaconda3, anaconda_knox, knox/anaconda3) shows up as a
        # bare path with NO name column at all. Matching column[0]=='name'
        # silently misses those. Matching the path's basename instead is
        # robust to both formats.
        path_str = line.split()[-1]
        if Path(path_str).name == conda_env:
            return Path(path_str)
    return None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--system", choices=["ubuntu", "conda"], required=True,
                    help="passed straight to install.py --system")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--smoke", action="store_true",
                       help="(default) fresh install + gmtsar_sharedir.csh "
                            "+ bin_py/tests/ -- minutes, not the better "
                            "part of an hour")
    mode.add_argument("--full", action="store_true",
                       help="--smoke, plus tests/sweep.py --fast (12 real "
                            "py-vs-csh cases) in the same fresh clone")
    p.add_argument("--conda-env", default=None,
                    help="conda env name to create (default: "
                         "gmtsar_test_install_<UTC timestamp>, always "
                         "fresh/never-before-used)")
    p.add_argument("--keep", action="store_true",
                    help="don't rm the fresh clone afterward (default: "
                         "removed only if every step passed)")
    p.add_argument("--cases", nargs="+", default=None,
                    help="--full only: pass through to sweep.py --fast "
                         "--cases, to cheaply re-verify specific cases "
                         "instead of the full 12")
    args = p.parse_args()

    global _LOG_PATH
    work_root = _PYTHON_DIR / "work" / "install_test"
    work_root.mkdir(parents=True, exist_ok=True)
    ts = _utc_now().replace(":", "-")
    _LOG_PATH = work_root / f"test_install_{ts}.log"
    conda_env = args.conda_env or f"gmtsar_test_install_{ts}"

    _log(f"[{_utc_now()}] test_install.py log start")
    _log(f"  argv: {' '.join(sys.argv)}")
    _log(f"  system: {args.system}  mode: {'full' if args.full else 'smoke'}  "
         f"conda_env: {conda_env!r}")
    _log(f"  log file: {_LOG_PATH}")

    results: list[tuple[str, bool, float]] = []

    clone_dir = _fresh_clone(work_root)
    clone_python_dir = clone_dir / "gmtsar" / "python"
    _reuse_tarball_cache(clone_python_dir)

    install_cmd = ["python3", str(clone_python_dir / "install.py"),
                   "--system", args.system]
    if args.system == "conda":
        install_cmd += ["--conda-env", conda_env]
    ok, dt = _run(install_cmd, "install", cwd=str(clone_python_dir))
    results.append(("install.py --system " + args.system, ok, dt))

    if not ok:
        _log(f"[{_utc_now()}] install failed -- skipping remaining steps "
             "(nothing downstream can be trusted).")
        _print_summary(results, clone_dir)
        return 1

    env = dict(os.environ)
    env["GMTSAR"] = str(clone_dir)
    env["PATH"] = f"{clone_dir}/bin:{env.get('PATH', '')}"
    py_exe = "python3"
    if args.system == "conda":
        prefix = _locate_fresh_conda_prefix(conda_env)
        if prefix is not None:
            env["PATH"] = f"{prefix}/bin:{env['PATH']}"
            py_exe = str(prefix / "bin" / "python3")
        else:
            _log(f"[{_utc_now()}] WARN: could not locate the fresh conda "
                 f"env {conda_env!r} via `conda env list` -- falling back "
                 "to whatever python3/gmt are already on PATH, which "
                 "defeats the point of this being a clean-room test. "
                 "Treat remaining steps' results with that caveat.")

    ok, dt = _run(["gmtsar_sharedir.csh"], "gmtsar_sharedir.csh",
                   cwd=str(clone_dir), env=env)
    results.append(("gmtsar_sharedir.csh (upstream sanity check)", ok, dt))

    ok, dt = _run([py_exe, "-m", "pytest", "bin_py/tests/", "-q"],
                   "bin_py/tests/", cwd=str(clone_python_dir), env=env)
    results.append(("bin_py/tests/ (unit/parity suite)", ok, dt))

    if args.full:
        sweep_cmd = [py_exe, "tests/sweep.py", "--fast"]
        if args.cases:
            sweep_cmd += ["--cases"] + args.cases
        ok, dt = _run(sweep_cmd, "sweep.py --fast", cwd=str(clone_python_dir), env=env)
        if ok:
            # sweep.py's own exit code only reflects orchestration
            # health -- it's 0 even when individual comparisons FAIL.
            # Re-derive the real verdict from compare.py's own output.
            ok, verdict = _check_sweep_results(clone_python_dir)
            _log(f"[{_utc_now()}] [sweep.py --fast] real verdict: {verdict}")
        cases_label = ", ".join(args.cases) if args.cases else "12 cases"
        results.append((f"tests/sweep.py --fast ({cases_label})", ok, dt))

    all_passed = _print_summary(results, clone_dir)

    if all_passed and not args.keep:
        _log(f"[{_utc_now()}] all steps passed -- removing clone {clone_dir}")
        shutil.rmtree(clone_dir, ignore_errors=True)
    else:
        _log(f"[{_utc_now()}] clone left in place for inspection: {clone_dir}")

    return 0 if all_passed else 1


def _print_summary(results: list[tuple[str, bool, float]], clone_dir: Path) -> bool:
    _log("")
    _log(f"[{_utc_now()}] ===== test_install.py summary =====")
    all_passed = True
    for name, ok, dt in results:
        status = "PASS" if ok else "FAIL"
        all_passed = all_passed and ok
        _log(f"  [{status}] {name} ({dt:.1f}s)")
    _log(f"  clone: {clone_dir}")
    _log(f"  log: {_LOG_PATH}")
    _log(f"[{_utc_now()}] overall: {'PASS' if all_passed else 'FAIL'}")
    return all_passed


if __name__ == "__main__":
    sys.exit(main())
