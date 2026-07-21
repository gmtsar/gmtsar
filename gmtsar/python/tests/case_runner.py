#!/usr/bin/env python3
"""case_runner.py — run one test case: extract tarball into both trees, run
the legacy csh recipe (if no outputs yet) and the Python recipe IN PARALLEL.

Python port of case_runner.sh (2026-07-13). Faithful behavioral port, not a
redesign — every documented fix/rationale from the bash version is preserved
verbatim below with its original comment, keyed to the original incident it
fixed. Real CLI args replace what used to be shell environment variables
(TOPO_MODE_AB, CASE_RUNNER_PROFILE) per project_rules.md: env vars are easy
to lose across shells (this exact class of bug repeatedly bit the 2026-07-13
session that prompted this rewrite -- forgotten exports, stale GMTSAR in a
new Bash call, etc.). Thread-pin/LD_PRELOAD/PATH env vars are still set as
real OS env vars for the ONE subprocess that runs the recipe, since that's
how the recipe's own subprocess chain (and profiler.py) reads them -- that
part is an unavoidable process-boundary detail, not a caller-facing footgun.

Invoked by sweep.py (not designed for direct interactive use, but works):
    python3 case_runner.py RS2_SLC_Hawaii \\
        work/csh_test/RS2_SLC_Hawaii work/python_test/RS2_SLC_Hawaii \\
        work/dataset/RS2_SLC_Hawaii.tar.gz \\
        work/recipes/README_RS2_SLC_Hawaii.txt work/timeSpentLog.txt \\
        --preload-shim fftw_force_serial.so
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from cases import CASES  # noqa: E402


def _repo_root() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], cwd=_HERE,
            capture_output=True, text=True, timeout=5
        ).stdout.strip()
    except Exception:
        return ""


def _git_sha(repo_root: str) -> str:
    if not repo_root:
        return ""
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root,
                               capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return ""


def _git_dirty_files(repo_root: str) -> str:
    if not repo_root:
        return ""
    try:
        out = subprocess.run(
            ["git", "diff", "--name-only", "HEAD", "--", "gmtsar/python/"],
            cwd=repo_root, capture_output=True, text=True, timeout=5
        ).stdout
        return ",".join(l for l in out.splitlines() if l)
    except Exception:
        return ""


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _force_topo_interp_mode(cfg_path: str, mode: int) -> None:
    """Force `topo_interp_mode = <mode>` in a staged/generated config.py.
    Shared by both A/B branches of a --topo-mode-ab run."""
    text = open(cfg_path).read()
    if re.search(r"^\s*topo_interp_mode\s*=", text, re.M):
        text = re.sub(r"^(\s*topo_interp_mode\s*=\s*)\S+", rf"\g<1>{mode}",
                       text, count=1, flags=re.M)
    else:
        text += f"\ntopo_interp_mode       = {mode}\n"
    open(cfg_path, "w").write(text)


def _fix_filter_wavelength(tree: str) -> None:
    """Some old tarballs ship a config with `filter1 = gauss_<sat>_<NNN>m`
    and no `filter_wavelength` -- upstream p2p_processing.csh only reads
    filter_wavelength and silently passes an empty arg to filter.csh, which
    then bails with its usage banner. Translate filter1 -> filter_wavelength
    when only filter1 exists, so the csh side works. Applies to both trees."""
    for cfg in glob.glob(os.path.join(tree, "config*.txt")):
        text = open(cfg).read()
        if re.search(r"^filter1", text, re.M) and not re.search(r"^filter_wavelength", text, re.M):
            m = re.search(r"^filter1.*?_(\d+)m", text, re.M)
            if m:
                with open(cfg, "a") as f:
                    f.write(f"filter_wavelength = {m.group(1)}\n")


def _neutralize_pop_config_line(csh_dir: str) -> None:
    """Some tarballs (e.g. NISAR_Ethiopia) bundle a pre-edited config.txt
    AND a README that starts with `pop_config.csh SAT > config.txt`. That
    line OVERWRITES the bundled (manually-edited) config with vanilla
    pop_config defaults, and the README then has comments instructing a
    human to re-apply the edits. Our automation can't do that human step,
    so neutralize the pop_config line: the bundled config is already the
    ground truth."""
    for readme in glob.glob(os.path.join(csh_dir, "README*.txt")):
        text = open(readme).read()
        changed = False
        for line in text.splitlines():
            if not line.startswith("pop_config.csh "):
                continue
            m = re.search(r">\s*([a-zA-Z0-9_.]+\.txt)", line)
            if m and os.path.isfile(os.path.join(csh_dir, m.group(1))):
                replacement = f"# {line}  # patched: preserve bundled {m.group(1)} (case_runner.py)"
                text = text.replace(line, replacement, 1)
                changed = True
        if changed:
            open(readme, "w").write(text)


def _parallelize_frame_drivers(csh_dir: str) -> None:
    """Parallelize csh's multi-subswath Frame drivers when the bundled
    README left them sequential (last arg = 0). The csh side is otherwise
    the bottleneck: ALOS2_SCAN_SSAF csh runs F1..F5 strictly sequential
    (~6h) while the Python port already uses a 5-way multiprocessing.Pool.
    Flipping the trailing 0 to 1 on these driver lines makes csh process
    subswaths concurrently via its own `wait` pattern, so the run finishes
    in roughly 1/N of the wall time. Only touches *_Frame.csh lines ending
    in literal " 0" -- single-subswath p2p_processing.csh calls untouched."""
    pattern = re.compile(
        r"^(p2p_(?:ALOS2_SCAN|S1_TOPS)_Frame\.csh .*\.txt) 0$", re.M)
    for readme in glob.glob(os.path.join(csh_dir, "README*.txt")):
        text = open(readme).read()
        new_text = pattern.sub(r"\1 1  # patched: parallel (case_runner.py)", text)
        if new_text != text:
            open(readme, "w").write(new_text)


def _stage_config(case: str, tree_dir: str, staged_config: str, topo_mode: int | None,
                   env: dict) -> None:
    """Copy the staged config.py if present, else (only needed when
    topo_mode must be forced pre-run) generate one via pop_config. Then
    force topo_interp_mode if topo_mode is not None."""
    cfg_path = os.path.join(tree_dir, "config.py")
    if os.path.exists(staged_config):
        shutil.copy(staged_config, cfg_path)
    elif topo_mode is not None and not os.path.exists(cfg_path):
        sat = CASES[case]["satellite"]
        with open(cfg_path, "w") as f:
            subprocess.run(["pop_config", sat], cwd=tree_dir, env=env, check=True, stdout=f)
    if topo_mode is not None and os.path.exists(cfg_path):
        _force_topo_interp_mode(cfg_path, topo_mode)


def _check_config_drift(case: str, bundled_cfg: str, staged_config: str) -> None:
    """Config-drift guard: when BOTH the bundled csh config and the staged
    python config exist, compare critical fields. A mismatch here is almost
    always a bug -- the python side will run a different pipeline than csh
    and the divergence won't be caught until compare.py much later. The
    Ridgecrest filter_wavelength=160 vs csh's 200 burned ~4 hours before
    surfacing."""
    def _norm(v: str) -> str:
        return v.strip().strip("'\"")

    def _read_key(path: str, key: str) -> str | None:
        for line in open(path):
            m = re.match(rf"\s*{re.escape(key)}\s*=\s*(\S+)", line)
            if m:
                return _norm(m.group(1))
        return None

    drift = []
    for key in ("filter_wavelength", "region_cut", "threshold_snaphu",
                "threshold_geocode", "dec_factor", "proc_stage"):
        v_csh = _read_key(bundled_cfg, key)
        v_py = _read_key(staged_config, key)
        # Treat py's -999 sentinel as "use default" — ignore drift in that case.
        if v_py == "-999" or not v_csh or not v_py:
            continue
        if v_csh != v_py:
            drift.append(f"  {key}: csh={v_csh} py={v_py}")
    if drift:
        print(f"[{case}] CONFIG DRIFT between bundled csh config ({bundled_cfg}) "
              f"and staged python config ({staged_config}):", file=sys.stderr)
        print("\n".join(drift), file=sys.stderr)
        print(f"[{case}] Re-run import_csh_config or update tests/configs/{case}.py to match.",
              file=sys.stderr)
        sys.exit(3)


def _pick_csh_readme(csh_dir: str) -> str:
    """Some tarballs (e.g. S1_Larsen_C) ship README_Frame.txt /
    README_proc.txt instead of a plain README.txt. Pick the most likely
    entry-point if plain README.txt is missing: prefer *_Frame*, then
    *proc*, then any. NISAR ships README_A_B.txt (alphabetically first)
    and README_eruption.txt; the Python recipe mirrors the eruption
    workflow, so prefer that on csh side too."""
    if os.path.isfile(os.path.join(csh_dir, "README.txt")):
        return "README.txt"
    for pattern in ("README*Frame*.txt", "README*proc*.txt",
                    "README*eruption*.txt", "README_*.txt"):
        matches = sorted(glob.glob(os.path.join(csh_dir, pattern)))
        if matches:
            return os.path.basename(matches[0])
    return "README.txt"


def _run_subprocess_env(preload_shim: str | None, gmtsar_bin: str | None,
                         profile: bool, case: str, profile_out: str | None) -> dict:
    """Build the env dict for the ONE subprocess that runs a recipe. Thread
    pins + LD_PRELOAD are process-boundary details the recipe subprocess
    reads via its own os.environ -- unavoidable regardless of caller
    language, unlike TOPO_MODE_AB which this rewrite turned into a real
    function argument instead."""
    env = os.environ.copy()
    # NUMBA_NUM_THREADS=1 added 2026-07-13: verified every current numba
    # kernel (xcorr_py, resamp_py, SAT_llt2rat_py, gmt_surface_py,
    # gmt_blockmedian_py, gmt_grdsample_py, vector.py) is already genuinely
    # single-threaded (no prange, or prange with parallel=False) -- this was
    # harmless-but-missing defensive pinning, added so a future kernel that
    # DOES use parallel=True/prange doesn't silently break the
    # single-thread gate-2 measurement this script exists to produce.
    env.update(OMP_NUM_THREADS="1", MKL_NUM_THREADS="1",
               OPENBLAS_NUM_THREADS="1", FFTW_NUM_THREADS="1",
               NUMBA_NUM_THREADS="1")
    if preload_shim and os.path.isfile(preload_shim):
        env["LD_PRELOAD"] = preload_shim
    # Ensure the gmt binary and gmtsar tools are in PATH -- root cause of
    # v1.12.0's false-pass on COVE/Larsen (their topo_ra.grd never got
    # built but the auto-discovered comparison set hid the missing files).
    prefix = []
    if gmtsar_bin:
        prefix.append(gmtsar_bin)
    repo_root = _repo_root()
    if repo_root:
        prefix.append(os.path.join(repo_root, "bin"))
    if prefix:
        env["PATH"] = ":".join(prefix) + ":" + env.get("PATH", "")
    if profile:
        env["GMTSAR_PROFILE"] = "1"
        env["GMTSAR_PROFILE_CASE"] = case
        if profile_out:
            env["GMTSAR_PROFILE_OUT"] = profile_out
            if os.path.exists(profile_out):
                os.remove(profile_out)
    return env


def _run_recipe(tree_dir: str, case: str, env: dict) -> subprocess.CompletedProcess:
    """Recipe files (tests/recipes/README_<case>.txt) have no `#!` shebang
    -- just `#`-comment text. The original bash case_runner.sh ran them via
    `"./README_x.txt"` from inside bash, which silently falls back to
    /bin/sh on an ENOEXEC (POSIX "looks like a text script" convention).
    subprocess.run() does execve() directly with no such fallback, so we
    invoke via bash explicitly instead of relying on it."""
    log_path = os.path.join(tree_dir, "log.txt")
    with open(log_path, "w") as logf:
        return subprocess.run(["bash", f"README_{case}.txt"], cwd=tree_dir, env=env,
                               stdout=logf, stderr=subprocess.STDOUT)


def run_case(case: str, csh_dir: str, py_dir: str, tarball: str, py_readme: str,
             time_log: str, preload_shim: str | None = None,
             topo_mode_ab: bool = False, profile: bool = False,
             gmtsar_bin: str | None = None) -> int:
    """Faithful Python port of case_runner.sh's body. Returns 0 on success,
    matching the shell script's exit codes for the two guard failures (2:
    missing staged config for a bundled-config tarball; 3: config drift)."""
    repo_root = _repo_root()

    # ─── Git-SHA capture at case start (project_rules.md #6, #8) ──────────
    sha_at_start = _git_sha(repo_root)
    dirty_at_start = _git_dirty_files(repo_root)
    launched_at = _utc_now()
    results_dir = os.path.join(os.path.dirname(os.path.dirname(py_dir)), "results")
    os.makedirs(results_dir, exist_ok=True)
    sidecar = os.path.join(results_dir, f"{case}.git_sidecar")
    with open(sidecar, "w") as f:
        f.write("# git-sha sidecar — written by case_runner.py at case start.\n"
                "# compare.py reads and deletes this to embed into the per-case JSON.\n"
                f"case={case}\nlaunched_at={launched_at}\n"
                f"sha_at_start={sha_at_start}\ndirty_files_at_start={dirty_at_start}\n")

    profile_out = os.path.join(os.path.dirname(py_dir), f"profile_{case}.json")
    # Computed once, used for EVERY subprocess this case launches (cleanup,
    # csh, pop_config, the recipe) -- matches case_runner.sh's single global
    # `export PATH=...`/thread-pin block applied before either slot runs.
    env = _run_subprocess_env(preload_shim, gmtsar_bin, profile, case, profile_out)

    # Extract tarball into each tree if the tree's intf/ isn't there yet.
    # (Don't search the whole tree for .grd: bundled tarballs include
    # topo/dem.grd, which would falsely look like a finished run.)
    if not os.path.isdir(os.path.join(csh_dir, "intf")):
        os.makedirs(csh_dir, exist_ok=True)
        with tarfile.open(tarball) as tf:
            tf.extractall(csh_dir)
    os.makedirs(py_dir, exist_ok=True)
    if not os.path.isdir(os.path.join(py_dir, "intf")):
        with tarfile.open(tarball) as tf:
            tf.extractall(py_dir)

    _fix_filter_wavelength(csh_dir)
    _fix_filter_wavelength(py_dir)
    _neutralize_pop_config_line(csh_dir)
    _parallelize_frame_drivers(csh_dir)

    staged_config = os.path.join(_HERE, "configs", f"{case}.py")

    # ─── "csh" slot: real csh oracle, OR (topo_mode_ab) mode0 python run ──
    def csh_slot():
        t0 = time.time()
        if topo_mode_ab:
            # Mode-AB "baseline" slot: run the Python recipe (not csh) into
            # csh_dir, forced to topo_interp_mode=0.
            subprocess.run(["cleanup", "all"], cwd=csh_dir, env=env)
            shutil.copy(py_readme, os.path.join(csh_dir, os.path.basename(py_readme)))
            readme_path = os.path.join(csh_dir, os.path.basename(py_readme))
            os.chmod(readme_path, 0o755)
            _stage_config(case, csh_dir, staged_config, topo_mode=0, env=env)
            _run_recipe(csh_dir, case, env)
            _append_time_log(time_log, f"{case} mode0(ref) used {int(time.time()-t0)} s")
            return

        oracle_sentinel = os.path.join(csh_dir, ".oracle_built")
        tarball_md5 = _md5(tarball)
        fwk_sha = _git_sha_short(repo_root)
        oracle_valid = _check_oracle(csh_dir, oracle_sentinel, tarball_md5, fwk_sha, case, tarball)
        if oracle_valid:
            return
        print(f"[{case}] no csh reference — running legacy csh recipe")
        readme = _pick_csh_readme(csh_dir)
        subprocess.run(["cleanup", "all"], cwd=csh_dir, env=env)
        log_path = os.path.join(csh_dir, "log.txt")
        with open(log_path, "w") as logf:
            subprocess.run(["csh", readme], cwd=csh_dir, env=env, stdout=logf, stderr=subprocess.STDOUT)
        wall = int(time.time() - t0)
        _append_time_log(time_log, f"{case} csh used {wall} s")
        with open(oracle_sentinel, "w") as f:
            f.write("# csh oracle build sentinel — written by case_runner.py\n"
                    "# DO NOT delete unless you want to force csh oracle rebuild on next sweep\n"
                    f"built_at={_utc_now()}\ncase={case}\ntarball={tarball}\n"
                    f"tarball_md5={tarball_md5}\nfwk_sha={fwk_sha}\ncsh_wall_sec={wall}\n")

    # ─── "python" slot: always runs (mode1 override when topo_mode_ab) ────
    def py_slot() -> int:
        bundled_cfg = os.path.join(py_dir, "config.txt")
        if not os.path.isfile(bundled_cfg):
            candidates = sorted(glob.glob(os.path.join(py_dir, "config*.txt")))
            bundled_cfg = candidates[0] if candidates else ""
        if bundled_cfg and not os.path.isfile(staged_config):
            print(f"[{case}] ERROR: tarball ships bundled config(s) ({bundled_cfg}) "
                  f"but no staged config.py at {staged_config} — refusing to fall back "
                  f"to pop_config (see project_rules.md #1)", file=sys.stderr)
            return 2
        if not topo_mode_ab and bundled_cfg and os.path.isfile(staged_config):
            _check_config_drift(case, bundled_cfg, staged_config)

        t0 = time.time()
        subprocess.run(["cleanup", "all"], cwd=py_dir, env=env)
        readme_path = os.path.join(py_dir, os.path.basename(py_readme))
        shutil.copy(py_readme, readme_path)
        os.chmod(readme_path, 0o755)
        _stage_config(case, py_dir, staged_config, topo_mode=1 if topo_mode_ab else None, env=env)
        _run_recipe(py_dir, case, env)
        wall = int(time.time() - t0)
        label = "python(mode1/new)" if topo_mode_ab else "python"
        _append_time_log(time_log, f"{case} {label} used {wall} s")
        return 0

    import threading
    csh_exc: list = []
    py_rc: list = [0]

    def _csh_thread():
        try:
            csh_slot()
        except SystemExit as e:
            csh_exc.append(e)

    def _py_thread():
        py_rc[0] = py_slot()

    t_csh = threading.Thread(target=_csh_thread)
    t_py = threading.Thread(target=_py_thread)
    t_csh.start(); t_py.start()
    t_csh.join(); t_py.join()

    # ─── Git-SHA capture at case end ───────────────────────────────────────
    sha_at_end = _git_sha(repo_root)
    dirty_at_end = _git_dirty_files(repo_root)
    with open(sidecar, "a") as f:
        f.write(f"finished_at={_utc_now()}\nsha_at_end={sha_at_end}\n"
                f"dirty_files_at_end={dirty_at_end}\n")

    return py_rc[0] or (2 if csh_exc else 0)


def _md5(path: str) -> str:
    import hashlib
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_sha_short(repo_root: str) -> str:
    if not repo_root:
        return "no-git"
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo_root,
                              capture_output=True, text=True, timeout=5).stdout.strip()
        return out or "no-git"
    except Exception:
        return "no-git"


def _check_oracle(csh_dir: str, sentinel: str, tarball_md5: str, fwk_sha: str, case: str,
                   tarball: str) -> bool:
    """Sentinel-guarded oracle validity check. See case_runner.sh's original
    'Stale-oracle problem (NISAR_Ethiopia 2026-05-21)' comment: an oracle on
    disk can look complete but be stale relative to current inputs.

    Real pre-existing bug fixed 2026-07-13 (found during the v2.7.0
    confirmation sweep, present identically in the archived case_runner.sh
    -- not something this rewrite introduced): multi-subswath Frame cases
    (S1 TOPS: S1_Larsen_C, S1A_SLC_TOPS_*; ALOS2_SCAN_SSAF) have NO
    top-level `intf/` dir -- their outputs live under `F1/intf/`,
    `F2/intf/`, etc. The old `<csh_dir>/intf/**/*.grd` glob always missed
    them, so oracle_valid was unconditionally False for every one of these
    cases on every sweep -- forcing a full, unnecessary csh rebuild
    (thousands of seconds) even with a perfectly valid, sentinel-matching
    oracle already on disk. Search the whole tree for any `intf/` dir
    (single-pair OR per-subswath) instead of assuming one fixed path.
    """
    intf_has_output = bool(
        glob.glob(os.path.join(csh_dir, "**", "intf", "**", "*.grd"), recursive=True) or
        glob.glob(os.path.join(csh_dir, "**", "intf", "**", "*.png"), recursive=True))
    if not intf_has_output:
        return False
    if not os.path.isfile(sentinel):
        print(f"[{case}] WARN: oracle has no sentinel (.oracle_built) — grandfathered "
              f"as valid. To force rebuild: rm -rf {csh_dir}")
        return True
    text = open(sentinel).read()
    prev_sha = re.search(r"fwk_sha=(\S+)", text)
    prev_md5 = re.search(r"tarball_md5=(\S+)", text)
    prev_sha = prev_sha.group(1) if prev_sha else ""
    prev_md5 = prev_md5.group(1) if prev_md5 else ""
    if prev_md5 == tarball_md5:
        if prev_sha != fwk_sha:
            print(f"[{case}] oracle was built under fwk_sha={prev_sha}; current "
                  f"fwk_sha={fwk_sha} (tarball unchanged → oracle still valid)")
        return True
    print(f"[{case}] oracle tarball_md5={prev_md5} != current={tarball_md5} — "
          f"INVALIDATING oracle, wiping csh_test/{case} for rebuild")
    shutil.rmtree(csh_dir, ignore_errors=True)
    os.makedirs(csh_dir)
    with tarfile.open(tarball) as tf:
        tf.extractall(csh_dir)
    # Re-apply the same per-tree config patch we did above.
    _fix_filter_wavelength(csh_dir)
    return False


def _append_time_log(path: str, line: str) -> None:
    with open(path, "a") as f:
        f.write(line + "\n")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("case")
    p.add_argument("csh_dir")
    p.add_argument("py_dir")
    p.add_argument("tarball")
    p.add_argument("py_readme")
    p.add_argument("time_log")
    p.add_argument("--preload-shim", default=None)
    p.add_argument("--topo-mode-ab", action="store_true",
                   help="Run the Python recipe into BOTH trees (mode0 into "
                        "csh_dir, mode1 into py_dir) instead of csh-vs-py.")
    p.add_argument("--profile", action="store_true",
                   help="Enable GMTSAR_PROFILE for the recipe subprocess.")
    p.add_argument("--gmtsar-bin", default=None)
    args = p.parse_args()
    rc = run_case(args.case, args.csh_dir, args.py_dir, args.tarball, args.py_readme,
                  args.time_log, preload_shim=args.preload_shim,
                  topo_mode_ab=args.topo_mode_ab, profile=args.profile,
                  gmtsar_bin=args.gmtsar_bin)
    sys.exit(rc)


if __name__ == "__main__":
    main()
