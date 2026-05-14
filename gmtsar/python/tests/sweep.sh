#!/bin/bash
# run_sweep.sh — sequentially run+compare every case in pathListForTest.caseNameList.
# Downloads the tarball first if missing. Designed for an unattended multi-hour run.
#
# Logs go to gmtsar/python/work/sweep.log (and per-case logs already live under
# work/python_test/<case>/log.txt and work/csh_test/<case>/log.txt).
#
# Usage:  bash gmtsar/python/run_sweep.sh   (run in background with &)

set -u

export GMTSAR=/home/staff/dliu/gmtsar
export PATH=$GMTSAR/bin:$PATH
PY=/home/staff/dliu/anaconda3/envs/gmtsar/bin/python3
DATASET_DIR=$GMTSAR/gmtsar/python/work/dataset
WORK=$GMTSAR/gmtsar/python/work
LOG=$WORK/sweep.log
TESTSYS=$GMTSAR/gmtsar/python/tests
mkdir -p "$DATASET_DIR" "$WORK"

# Derive caseNameList from the canonical source so this script stays in sync.
cases=$(cd "$TESTSYS" && "$PY" -c "from pathListForTest import caseNameList; print(' '.join(caseNameList))")

ts() { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "[$(ts)] $*" | tee -a "$LOG"; }

log "=== sweep started ==="
log "cases: $cases"

# Kill any pre-existing wgets targeting our dataset dir. They survive across
# sweep restarts (backgrounded with &, own pgrp), and concurrent wgets writing
# to the same file via -c corrupt the partial download. Always one wget per
# case for the lifetime of this script.
orphans=$(pgrep -f "wget .*${DATASET_DIR}" 2>/dev/null || true)
if [ -n "$orphans" ]; then
    log "killing orphan wgets from previous run: $(echo $orphans | tr '\n' ' ')"
    kill -9 $orphans 2>/dev/null || true
    sleep 1
fi

# Kick off a background `wget -c` for every case at startup. wget -c does a
# HEAD against the server: it's near-instant if the file is already complete,
# resumes if partial, downloads from scratch if absent. The sweep loop later
# `wait`s for each case's wget before running it — so cases whose tarballs are
# already complete will essentially skip the wait and run immediately.
declare -A DL_PID
for c in $cases; do
    ext=tar.gz
    [[ "$c" == "NISAR_SIM_ALOS" ]] && ext=tgz
    tarball="$DATASET_DIR/$c.$ext"
    log "DOWNLOAD start (background) $c"
    wget -c -q --timeout=60 --tries=3 \
         "http://topex.ucsd.edu/gmtsar/tar/$c.$ext" -O "$tarball" &
    DL_PID[$c]=$!
done

# Dynamic scheduling with bounded parallelism. Pick whichever case's wget has
# finished first; launch up to MAX_PARALLEL case runs concurrently. Each case
# run uses ~2 cores (csh + python pipelines in parallel within the case), so
# MAX_PARALLEL=4 = ~8 cores busy plus FFTW shim keeps each FFT serial.
MAX_PARALLEL=${MAX_PARALLEL:-4}
log "max parallel cases: $MAX_PARALLEL"

run_case() {
    local c=$1
    local ext=tar.gz
    [[ "$c" == "NISAR_SIM_ALOS" ]] && ext=tgz
    local tarball="$DATASET_DIR/$c.$ext"
    if [ ! -s "$tarball" ]; then
        log "DOWNLOAD FAIL $c — tarball missing/empty"
        return 1
    fi
    log "RUN $c — starting"
    local t0=$SECONDS
    cd "$TESTSYS"
    TEST_CASES="$c" "$PY" runner.py >> "$LOG" 2>&1
    local dur=$((SECONDS - t0))
    log "DONE $c (${dur}s)"
}

remaining="$cases"
while [ -n "$(echo "$remaining" | tr -d ' ')" ] || [ $(jobs -rp | wc -l) -gt 0 ]; do
    # If we've hit the parallelism cap, wait for any case to finish.
    if [ $(jobs -rp | wc -l) -ge "$MAX_PARALLEL" ]; then
        wait -n 2>/dev/null || true
        continue
    fi
    # Find a case whose wget has finished.
    next=""
    for c in $remaining; do
        if ! kill -0 "${DL_PID[$c]}" 2>/dev/null; then
            next=$c
            break
        fi
    done
    if [ -z "$next" ]; then
        # Nothing ready yet — wait for any download or active case.
        if [ $(jobs -rp | wc -l) -gt 0 ]; then
            wait -n 2>/dev/null || true
        else
            sleep 10
        fi
        continue
    fi
    remaining=$(echo "$remaining" | tr ' ' '\n' | grep -vx "$next" | tr '\n' ' ')
    # Reap the wget exit status.
    wait "${DL_PID[$next]}"; rc=$?
    if [ $rc -ne 0 ]; then
        log "DOWNLOAD FAIL $next (wget rc=$rc) — skipping"
        ext=tar.gz; [[ "$next" == "NISAR_SIM_ALOS" ]] && ext=tgz
        [ ! -s "$DATASET_DIR/$next.$ext" ] && rm -f "$DATASET_DIR/$next.$ext"
        continue
    fi
    ext=tar.gz; [[ "$next" == "NISAR_SIM_ALOS" ]] && ext=tgz
    log "DOWNLOAD OK $next ($(du -h "$DATASET_DIR/$next.$ext" | cut -f1))"
    # Launch this case in a background subshell — up to MAX_PARALLEL run at once.
    run_case "$next" &
done

wait  # drain any still-running case
log "all case runs complete"

# Final summary: per-case download / status / timings / SUCCESS|FAIL counts.
"$PY" "$TESTSYS/report.py" >> "$LOG" 2>&1
log "summary written to $WORK/sweep_summary.md"

log "=== sweep finished ==="
