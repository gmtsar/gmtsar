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

# csh reference (background) — only build if no outputs in intf/.
(
    if [ -z "$(find "$cshDir/intf" -name '*.grd' -o -name '*.png' 2>/dev/null | head -1)" ]; then
        echo "[$case] no csh reference — running legacy csh recipe"
        t0=$SECONDS
        ( cd "$cshDir" && cleanup all && csh README.txt > log.txt 2>&1 )
        echo "$case csh used $((SECONDS-t0)) s" >> "$timeLog"
    fi
) &
cshPid=$!

# python run (background) — always runs.
(
    t0=$SECONDS
    ( cd "$pyDir" \
      && cleanup all \
      && cp "$pyReadme" . \
      && chmod +x "README_${case}.txt" \
      && "./README_${case}.txt" > log.txt 2>&1 )
    echo "$case python used $((SECONDS-t0)) s" >> "$timeLog"
) &
pyPid=$!

wait $cshPid $pyPid
