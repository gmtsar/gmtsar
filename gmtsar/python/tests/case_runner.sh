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
export PATH=/home/staff/dliu/anaconda3/envs/gmtsar/bin:/home/staff/dliu/gmtsar/bin:$PATH

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
    sed -i -E 's|^(p2p_(ALOS2_SCAN|S1_TOPS)_Frame\.csh .*\.txt) 0$|\1 1  # patched: parallel (case_runner.sh)|' "$readme"
done

# csh reference (background) — only build if no outputs in intf/.
(
    if [ -z "$(find "$cshDir/intf" -name '*.grd' -o -name '*.png' 2>/dev/null | head -1)" ]; then
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
    drift=""
    for key in filter_wavelength region_cut threshold_snaphu threshold_geocode dec_factor proc_stage; do
        v_csh=$(grep -E "^[[:space:]]*${key}[[:space:]]*=" "$bundledCfgs" | head -1 | awk -F= '{gsub(/^[[:space:]]+|[[:space:]]+$/,"",$2); print $2}' | awk '{print $1}')
        v_py=$(grep -E "^[[:space:]]*${key}[[:space:]]*=" "$stagedConfig" | head -1 | awk -F= '{gsub(/^[[:space:]]+|[[:space:]]+$/,"",$2); print $2}' | awk '{print $1}')
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
