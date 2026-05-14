#!/bin/bash
# sweep.sh — download + run + compare every case in cases.caseNameList.
# Designed for an unattended multi-hour run.
#
# Tier control (sets TEST_TIER, picked up by cases.py):
#   bash sweep.sh                 # full sweep (~8 h)
#   bash sweep.sh --smoke         # 1 case (~3 min, pipeline alive check)
#   bash sweep.sh --fast          # 4 small cases (~30 min, covers main paths)
#
# Logs: gmtsar/python/work/sweep.log + per-case work/{python,csh}_test/<case>/log.txt

set -u

case ${1:-} in
    --smoke|smoke) export TEST_TIER=smoke ;;
    --fast|fast)   export TEST_TIER=fast  ;;
    --full|full|'') export TEST_TIER=full ;;
    -h|--help)
        sed -n '2,11p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1 (try --smoke / --fast / --full / --help)" >&2; exit 2 ;;
esac

export GMTSAR=/home/staff/dliu/gmtsar
export PATH=$GMTSAR/bin:$PATH
PY=/home/staff/dliu/anaconda3/envs/gmtsar/bin/python3
DATASET_DIR=$GMTSAR/gmtsar/python/work/dataset
WORK=$GMTSAR/gmtsar/python/work
LOG=$WORK/sweep.log
TESTSYS=$GMTSAR/gmtsar/python/tests
mkdir -p "$DATASET_DIR" "$WORK"

# Derive case list + per-case (path, url) from cases.py in one shot — single
# source of truth for archive extension (.tar.gz vs .tgz) and URL.
declare -A TARBALL URL
cases=""
while IFS=$'\t' read -r c path url; do
    cases+="$c "
    TARBALL[$c]=$path
    URL[$c]=$url
done < <(cd "$TESTSYS" && "$PY" -c "
from cases import caseNameList, archive_path, archive_url
for c in caseNameList: print(f'{c}\t{archive_path(c)}\t{archive_url(c)}')
")

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
    log "DOWNLOAD start (background) $c"
    wget -c -q --timeout=60 --tries=3 "${URL[$c]}" -O "${TARBALL[$c]}" &
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
    if [ ! -s "${TARBALL[$c]}" ]; then
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
        [ ! -s "${TARBALL[$next]}" ] && rm -f "${TARBALL[$next]}"
        continue
    fi
    log "DOWNLOAD OK $next ($(du -h "${TARBALL[$next]}" | cut -f1))"
    # Launch this case in a background subshell — up to MAX_PARALLEL run at once.
    run_case "$next" &
done

wait  # drain any still-running case
log "all case runs complete"

# Final summary: per-case download / status / timings / SUCCESS|FAIL counts.
"$PY" "$TESTSYS/report.py" >> "$LOG" 2>&1
log "summary written to $WORK/sweep_summary.md"

log "=== sweep finished ==="
