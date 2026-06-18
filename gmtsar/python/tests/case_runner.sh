#!/usr/bin/env bash
# Run one test case: extract tarball into both trees, run the legacy csh
# recipe (if no outputs yet) and the Python recipe IN PARALLEL.
#
# Invoked by runner.py — not designed for direct interactive use, but you can:
#   bash case_runner.sh RS2_SLC_Hawaii \
#        /path/work/csh_test/RS2_SLC_Hawaii \
#        /path/work/python_test/RS2_SLC_Hawaii \
#        /path/work/dataset/RS2_SLC_Hawaii.tar.gz \
#        /path/work/recipes/README_RS2_SLC_Hawaii.txt \
#        /path/work/timeSpentLog.txt \
#        /path/gmtsar/python/fftw_force_serial.so

set -u

# On Ctrl-C or SIGTERM, kill every process in our process group (csh, python,
# tar, etc.) so we don't leak orphaned recipe runs. `kill 0` signals the whole
# pgrp; runner.py starts each case_runner.sh in its own session, so this only
# kills our own subtree.
trap 'kill 0 2>/dev/null; exit 130' INT TERM

case=${1:?case name}
cshDir=${2:?csh test dir}
pyDir=${3:?python test dir}
tarball=${4:?tarball}
pyReadme=${5:?python recipe}
timeLog=${6:?time log}
preloadShim=${7:-}

# ─── Git-SHA capture at case start (project_rules.md #6, #8) ─────────────────
# Records the framework git state (SHA + dirty file list under gmtsar/python/)
# at the moment this case starts, so compare.py can embed it in the per-case
# JSON scorecard. After the case completes, we re-read HEAD; if it advanced
# mid-case, the result is flagged MIXED_VINTAGE_SHA_CHANGE.
#
# The scorecard sidecar is a plain key=value file at
#   <workdir>/results/<case>.git_sidecar
# which compare.py reads + deletes. Keeping it as a separate file (not env
# vars) lets case_runner.sh's csh+python subshells run their full pipeline
# without polluting their env, and survives if compare.py is run later.
#
# Repo root: this script lives at <repo>/gmtsar/python/tests/case_runner.sh,
# so the repo root is three directories up. We use git's own working-tree
# resolution (the script may be invoked from any cwd, and worktrees count).
_repo_root_for_sha="$(cd "$(dirname "$0")/../../.." && git rev-parse --show-toplevel 2>/dev/null || echo "")"
sha_at_case_start=""
dirty_files_at_case_start=""
case_launched_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
if [ -n "$_repo_root_for_sha" ]; then
    sha_at_case_start="$(cd "$_repo_root_for_sha" && git rev-parse HEAD 2>/dev/null || echo "")"
    # Dirty files scoped to gmtsar/python/ — outside that path doesn't affect
    # the pipeline per project_rules.md #5.
    dirty_files_at_case_start="$(cd "$_repo_root_for_sha" && git diff --name-only HEAD -- gmtsar/python/ 2>/dev/null | tr '\n' ',' | sed 's/,$//')"
fi
# Sidecar destination: <workdir>/results/<case>.git_sidecar. The workdir is
# the parent of $pyDir's parent (pyDir = work/python_test/<case>).
_results_dir="$(dirname "$(dirname "$pyDir")")/results"
mkdir -p "$_results_dir"
_sidecar="$_results_dir/${case}.git_sidecar"
cat > "$_sidecar" <<EOF
# git-sha sidecar — written by case_runner.sh at case start.
# compare.py reads and deletes this to embed into the per-case JSON.
case=$case
launched_at=$case_launched_at
sha_at_start=$sha_at_case_start
dirty_files_at_start=$dirty_files_at_case_start
EOF

# Pin known thread pools to 1; libgmt's FFTW pthreads ignore these, so we also
# LD_PRELOAD the shim built by install.sh --build (if present).
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 FFTW_NUM_THREADS=1
if [ -n "$preloadShim" ] && [ -f "$preloadShim" ]; then
    export LD_PRELOAD="$preloadShim"
fi

# Ensure the gmt binary and gmtsar tools are in PATH for both the csh side
# (which calls `gmt ...` directly from bundled csh recipes) and the py side
# (whose Python utilities subprocess-call `gmt ...`). Without this, sweeps
# launched from a shell lacking `conda activate gmtsar` will silently fail
# in dem2topo_ra (gmt surface → 1×1 grid → no topo_ra.grd) and csh recipes
# (`gmt: Command not found.` in log). Was the root cause of v1.12.0's
# false-pass on COVE/Larsen — their topo_ra.grd never got built but the
# auto-discovered comparison set hid the missing files.
# Ensure gmtsar tools are reachable. Derive the repo bin/ from the script
# location (case_runner.sh lives at <repo>/gmtsar/python/tests/), then
# honour GMTSAR env if set (sweep.sh always exports it).
_CR_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && git rev-parse --show-toplevel 2>/dev/null || echo "")"
_CR_GMTSAR_BIN="${GMTSAR:+$GMTSAR/bin}"
_CR_REPO_BIN="${_CR_REPO_ROOT:+$_CR_REPO_ROOT/bin}"
export PATH="${_CR_GMTSAR_BIN:+$_CR_GMTSAR_BIN:}${_CR_REPO_BIN:+$_CR_REPO_BIN:}$PATH"

# If GMTSAR_PROFILE=1 is set by the caller (or below by passing
# CASE_RUNNER_PROFILE=1), emit per-case timing JSON. Profiler is a no-op
# when GMTSAR_PROFILE isn't set, so this costs nothing in production.
if [ -n "${GMTSAR_PROFILE:-}" ] || [ -n "${CASE_RUNNER_PROFILE:-}" ]; then
    export GMTSAR_PROFILE=1
    export GMTSAR_PROFILE_CASE="$case"
    export GMTSAR_PROFILE_OUT="$(dirname "$pyDir")/../profile_${case}.json"
    rm -f "$GMTSAR_PROFILE_OUT"  # always start fresh per case
fi

# Extract tarball into each tree if the tree's intf/ isn't there yet.
# (Don't search the whole tree for .grd: bundled tarballs include topo/dem.grd,
# which would falsely look like a finished run.)
if [ ! -d "$cshDir/intf" ]; then
    mkdir -p "$cshDir" && tar -xzf "$tarball" -C "$cshDir"
fi
mkdir -p "$pyDir"
if [ ! -d "$pyDir/intf" ]; then
    tar -xzf "$tarball" -C "$pyDir"
fi

# Some old tarballs ship a config with `filter1 = gauss_<sat>_<NNN>m` and no
# `filter_wavelength` — upstream p2p_processing.csh only reads filter_wavelength
# and silently passes an empty arg to filter.csh, which then bails with its
# usage banner. Translate filter1 → filter_wavelength when only filter1 exists,
# so the csh side works. Applies to both trees.
for tree in "$cshDir" "$pyDir"; do
    for cfg in "$tree"/config*.txt; do
        [ -f "$cfg" ] || continue
        if grep -q "^filter1" "$cfg" && ! grep -q "^filter_wavelength" "$cfg"; then
            wl=$(grep "^filter1" "$cfg" | grep -oE "_[0-9]+m" | grep -oE "[0-9]+" | head -1)
            if [ -n "$wl" ]; then
                echo "filter_wavelength = $wl" >> "$cfg"
            fi
        fi
    done
done

# Some tarballs (e.g. NISAR_Ethiopia) bundle a pre-edited config.txt AND a
# README that starts with `pop_config.csh SAT > config.txt`. That line
# OVERWRITES the bundled (manually-edited) config with vanilla pop_config
# defaults, and the README then has comments instructing a human to re-apply
# the edits. Our automation can't do that human step, so neutralize the
# pop_config line: the bundled config is already the ground truth.
for readme in "$cshDir"/README*.txt; do
    [ -f "$readme" ] || continue
    while read -r line; do
        cfg=$(echo "$line" | grep -oE "> *[a-zA-Z0-9_.]+\.txt" | sed 's/^> *//')
        if [ -n "$cfg" ] && [ -f "$cshDir/$cfg" ]; then
            # Comment out this pop_config line so bundled $cfg survives.
            sed -i "s|^${line}$|# &  # patched: preserve bundled $cfg (case_runner.sh)|" "$readme"
        fi
    done < <(grep -E "^pop_config\.csh " "$readme")
done

# Parallelize csh's multi-subswath Frame drivers when the bundled README left
# them sequential (last arg = 0). The csh side is otherwise the bottleneck:
# ALOS2_SCAN_SSAF csh runs F1..F5 strictly sequential (~6h) while the Python
# port already uses a 5-way multiprocessing.Pool. Flipping the trailing 0 to
# 1 on these driver lines makes csh process subswaths concurrently via its
# own `wait` pattern, so the run finishes in roughly 1/N of the wall time.
# We only touch lines that end with " 0" (not other zeros mid-arg) and only
# for the *_Frame.csh family — single-subswath p2p_processing.csh calls are
# untouched.
for readme in "$cshDir"/README*.txt; do
    [ -f "$readme" ] || continue
    # Use @ as the sed delimiter; the search pattern contains `|` in the
    # (ALOS2_SCAN|S1_TOPS) alternation, which would otherwise be parsed as the
    # delimiter and silently break the substitution. The bug left
    # ALOS2_SCAN_SSAF running F1..F5 sequentially (~8h instead of ~2.5h).
    sed -i -E 's@^(p2p_(ALOS2_SCAN|S1_TOPS)_Frame\.csh .*\.txt) 0$@\1 1  # patched: parallel (case_runner.sh)@' "$readme"
done

# csh reference (background) — sentinel-guarded.
#
# Stale-oracle problem (NISAR_Ethiopia 2026-05-21): an oracle on disk can
# look "complete" (intf/*.grd present) but be inconsistent with current
# inputs if a prior partial run touched intermediate files. The old guard
# `if intf is empty` then skipped re-running csh and let the stale oracle
# survive across sweeps. Mira #18 root-caused; we now add a sentinel.
#
# Sentinel file: $cshDir/.oracle_built records the framework git SHA and
# tarball md5 at oracle-build time. On the next sweep we compare both.
# Mismatch → invalidate (wipe csh_test/<case>) and force rebuild. Missing
# sentinel + intf populated = treat as a pre-sentinel oracle (trust it,
# but warn so the user knows there's a one-time grandfathered run).
oracle_sentinel="$cshDir/.oracle_built"
tarball_md5=$(md5sum "$tarball" 2>/dev/null | awk '{print $1}')
fwk_sha=$(cd "$(dirname "$pyReadme")/.." && git rev-parse --short HEAD 2>/dev/null || echo "no-git")

oracle_valid=0
if [ -n "$(find "$cshDir/intf" -name '*.grd' -o -name '*.png' 2>/dev/null | head -1)" ]; then
    if [ -f "$oracle_sentinel" ]; then
        prev_sha=$(grep -oE 'fwk_sha=[a-f0-9]+' "$oracle_sentinel" | head -1 | cut -d= -f2)
        prev_md5=$(grep -oE 'tarball_md5=[a-f0-9]+' "$oracle_sentinel" | head -1 | cut -d= -f2)
        if [ "$prev_md5" = "$tarball_md5" ]; then
            # Tarball matches — oracle inputs are the same as recorded.
            # Framework SHA mismatch is OK (oracle only depends on C binaries
            # + tarball, not on Python framework) BUT we surface it for the log.
            oracle_valid=1
            if [ "$prev_sha" != "$fwk_sha" ]; then
                echo "[$case] oracle was built under fwk_sha=$prev_sha; current fwk_sha=$fwk_sha (tarball unchanged → oracle still valid)"
            fi
        else
            echo "[$case] oracle tarball_md5=$prev_md5 ≠ current=$tarball_md5 — INVALIDATING oracle, wiping csh_test/$case for rebuild"
            rm -rf "$cshDir"
            mkdir -p "$cshDir" && tar -xzf "$tarball" -C "$cshDir"
            # Re-apply the same per-tree config patches we did above.
            for cfg in "$cshDir"/config*.txt; do
                [ -f "$cfg" ] || continue
                if grep -q "^filter1" "$cfg" && ! grep -q "^filter_wavelength" "$cfg"; then
                    wl=$(grep "^filter1" "$cfg" | grep -oE "_[0-9]+m" | grep -oE "[0-9]+" | head -1)
                    [ -n "$wl" ] && echo "filter_wavelength = $wl" >> "$cfg"
                fi
            done
        fi
    else
        # Pre-sentinel grandfather case: intf has outputs but no sentinel
        # file. Trust the oracle but log a warning so the user can decide
        # to force-rebuild manually.
        oracle_valid=1
        echo "[$case] WARN: oracle has no sentinel (.oracle_built) — grandfathered as valid. To force rebuild: rm -rf $cshDir"
    fi
fi

(
    if [ "$oracle_valid" = 0 ]; then
        echo "[$case] no csh reference — running legacy csh recipe"
        t0=$SECONDS
        # Some tarballs (e.g. S1_Larsen_C) ship README_Frame.txt / README_proc.txt
        # instead of a plain README.txt. Pick the most likely entry-point if
        # plain README.txt is missing: prefer *_Frame*, then *proc*, then any.
        readme="README.txt"
        if [ ! -f "$cshDir/$readme" ]; then
            # NISAR ships README_A_B.txt (alphabetically first) and
            # README_eruption.txt; the Python recipe mirrors the eruption
            # workflow, so prefer that on csh side too.
            for cand in "$cshDir"/README*Frame*.txt "$cshDir"/README*proc*.txt "$cshDir"/README*eruption*.txt "$cshDir"/README_*.txt; do
                [ -f "$cand" ] && readme=$(basename "$cand") && break
            done
        fi
        ( cd "$cshDir" && cleanup all && csh "$readme" > log.txt 2>&1 )
        echo "$case csh used $((SECONDS-t0)) s" >> "$timeLog"
        # Write the sentinel — we just successfully built the oracle from
        # this tarball and this framework SHA.
        cat > "$oracle_sentinel" <<EOF
# csh oracle build sentinel — written by case_runner.sh
# DO NOT delete unless you want to force csh oracle rebuild on next sweep
built_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
case=$case
tarball=$tarball
tarball_md5=$tarball_md5
fwk_sha=$fwk_sha
csh_wall_sec=$((SECONDS-t0))
EOF
    fi
) &
cshPid=$!

# python run (background) — always runs.
# Stage a pre-translated config.py if one is checked in under tests/configs/<case>.py.
# Per project_rules.md #1: if the bundled tarball ships a config*.txt, a matching
# staged config.py is REQUIRED — refuse to fall back to pop_config. Cases that
# don't ship a bundled config (e.g. RS2_SLC_Hawaii) are fine to skip staging.
stagedConfig="$(cd "$(dirname "$pyReadme")/../configs" 2>/dev/null && pwd)/${case}.py"
# Prefer canonical config.txt; some tarballs ship multiple (e.g. Ridgecrest:
# config.tops.txt + config.txt; csh recipe uses config.txt). Fall back to the
# first config*.txt only if config.txt isn't present.
if [ -f "$pyDir/config.txt" ]; then
    bundledCfgs="$pyDir/config.txt"
else
    bundledCfgs=$(ls "$pyDir"/config*.txt 2>/dev/null | head -1)
fi
if [ -n "$bundledCfgs" ] && [ ! -f "$stagedConfig" ]; then
    echo "[$case] ERROR: tarball ships bundled config(s) ($bundledCfgs) but no staged config.py at $stagedConfig — refusing to fall back to pop_config (see project_rules.md #1)" >&2
    exit 2
fi

# Config-drift guard: when BOTH the bundled csh config and the staged python
# config exist, compare critical fields. A mismatch here is almost always a
# bug — the python side will run a different pipeline than csh and the
# divergence won't be caught until compare.py much later. The Ridgecrest
# filter_wavelength=160 vs csh's 200 burned ~4 hours before surfacing.
if [ -n "$bundledCfgs" ] && [ -f "$stagedConfig" ]; then
    # Strip matching surrounding quotes; the python config commonly writes
    # 'string' values as Python string literals (e.g. region_cut='18000/23000/...')
    # while csh ships them bare. Without this normalization, NISAR_Ethiopia's
    # region_cut tripped the drift guard and the entire py recipe was skipped.
    norm() { sed -e "s/^'//" -e "s/'$//" -e 's/^"//' -e 's/"$//'; }
    drift=""
    for key in filter_wavelength region_cut threshold_snaphu threshold_geocode dec_factor proc_stage; do
        v_csh=$(grep -E "^[[:space:]]*${key}[[:space:]]*=" "$bundledCfgs" | head -1 | awk -F= '{gsub(/^[[:space:]]+|[[:space:]]+$/,"",$2); print $2}' | awk '{print $1}' | norm)
        v_py=$(grep -E "^[[:space:]]*${key}[[:space:]]*=" "$stagedConfig" | head -1 | awk -F= '{gsub(/^[[:space:]]+|[[:space:]]+$/,"",$2); print $2}' | awk '{print $1}' | norm)
        # Treat py's -999 sentinel as "use default" — ignore drift in that case.
        if [ "$v_py" = "-999" ] || [ -z "$v_csh" ] || [ -z "$v_py" ]; then continue; fi
        if [ "$v_csh" != "$v_py" ]; then
            drift+="  $key: csh=$v_csh py=$v_py\n"
        fi
    done
    if [ -n "$drift" ]; then
        echo "[$case] CONFIG DRIFT between bundled csh config ($bundledCfgs) and staged python config ($stagedConfig):" >&2
        printf "$drift" >&2
        echo "[$case] Re-run import_csh_config or update tests/configs/${case}.py to match." >&2
        exit 3
    fi
fi
(
    t0=$SECONDS
    ( cd "$pyDir" \
      && cleanup all \
      && cp "$pyReadme" . \
      && chmod +x "README_${case}.txt" \
      && { [ -f "$stagedConfig" ] && cp "$stagedConfig" config.py || true; } \
      && "./README_${case}.txt" > log.txt 2>&1 )
    echo "$case python used $((SECONDS-t0)) s" >> "$timeLog"
) &
pyPid=$!

wait $cshPid $pyPid

# ─── Git-SHA capture at case end ─────────────────────────────────────────────
# Re-read HEAD and dirty list now that csh+py finished. compare.py will
# diff these against the at-start values to flag MIXED_VINTAGE_*.
sha_at_case_end=""
dirty_files_at_case_end=""
case_finished_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
if [ -n "$_repo_root_for_sha" ]; then
    sha_at_case_end="$(cd "$_repo_root_for_sha" && git rev-parse HEAD 2>/dev/null || echo "")"
    dirty_files_at_case_end="$(cd "$_repo_root_for_sha" && git diff --name-only HEAD -- gmtsar/python/ 2>/dev/null | tr '\n' ',' | sed 's/,$//')"
fi
cat >> "$_sidecar" <<EOF
finished_at=$case_finished_at
sha_at_end=$sha_at_case_end
dirty_files_at_end=$dirty_files_at_case_end
EOF
