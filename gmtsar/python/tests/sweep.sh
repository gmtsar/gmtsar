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

# Per project rule #6: capture hardware + software snapshot so scorecards
# from different hosts/runs are comparable. Single file per sweep.
PERF_FILE="$WORK/perf_$(date +%Y%m%d_%H%M%S).txt"
{
    echo "=== hardware ==="
    echo "host: $(hostname)"
    echo "cpu_model: $(awk -F: '/^model name/ {print $2; exit}' /proc/cpuinfo | sed 's/^ *//')"
    echo "cpu_cores_logical: $(nproc)"
    echo "ram_total: $(awk '/^MemTotal:/ {printf \"%.1fG\\n\", $2/1024/1024}' /proc/meminfo)"
    echo "workdir_fs: $(stat -f -c '%T (%n)' "$WORK" 2>/dev/null || stat --file-system -c '%T' "$WORK")"
    echo "workdir_mount: $(df "$WORK" | awk 'NR==2 {print $1}')"
    echo ""
    echo "=== software ==="
    echo "kernel: $(uname -srm)"
    echo "python: $($PY --version 2>&1)"
    echo "gmt: $(gmt --version 2>/dev/null || echo 'gmt not on PATH at sweep time')"
    echo "gmtsar_bin: $(which gmtsar 2>/dev/null || echo 'gmtsar not on PATH')"
    echo "git_sha: $(cd "$TESTSYS/../.." && git rev-parse --short HEAD 2>/dev/null || echo 'no git')"
    echo "git_branch: $(cd "$TESTSYS/../.." && git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '-')"
    echo "git_dirty: $(cd "$TESTSYS/../.." && (git diff --quiet 2>/dev/null && echo no) || echo yes)"
    echo ""
    echo "=== thread limits (intended by case_runner.sh) ==="
    echo "OMP_NUM_THREADS=${OMP_NUM_THREADS:-unset}"
    echo "MKL_NUM_THREADS=${MKL_NUM_THREADS:-unset}"
    echo "OPENBLAS_NUM_THREADS=${OPENBLAS_NUM_THREADS:-unset}"
    echo "FFTW_NUM_THREADS=${FFTW_NUM_THREADS:-unset}"
    echo ""
    echo "=== sweep ==="
    echo "started: $(ts)"
    echo "cases: $cases"
    echo "max_parallel: ${MAX_PARALLEL:-12}"
} > "$PERF_FILE"
log "hw+sw snapshot → $PERF_FILE"

# Skip cases that already have an all-SUCCESS results/<case>.json from this code
# version. Restarting a failed/interrupted sweep should not re-verify what's
# already passing. Set $SWEEP_FORCE=1 to disable this and re-run everything.
# Results invalidate when the code changes — wipe work/results/ to force re-run
# across versions.
if [ -z "${SWEEP_FORCE:-}" ]; then
    new_cases=""
    for c in $cases; do
        rj="$WORK/results/$c.json"
        if [ -f "$rj" ] && $PY -c "
import json,sys
d=json.load(open('$rj'))
comps=d.get('comparisons',[])
# A genuinely verified case has ALL comparisons SUCCESS AND at least 6 of
# them (3 PNG + 3 grd). Fewer than 6 means the python run aborted mid-pipeline
# (e.g. unwrap crash) so the comparison set is incomplete — re-run not skip.
sys.exit(0 if len(comps) >= 6 and all(x.get('status')=='SUCCESS' for x in comps) else 1)
" 2>/dev/null; then
            log "SKIP $c (already verified — results/$c.json all-SUCCESS; SWEEP_FORCE=1 to override)"
        else
            new_cases+="$c "
        fi
    done
    cases="$new_cases"
    if [ -z "$(echo $cases)" ]; then
        log "all cases already verified — nothing to do"
        exit 0
    fi
fi

# Detect pre-existing wgets targeting our dataset dir. Concurrent wgets writing
# to the same file via -c corrupt the partial download, so we must serialize.
# But if a wget is already running for a tarball we want, WAIT for it rather
# than killing — the user may have an out-of-band download going. We'll
# selectively skip wget for cases whose target is being downloaded already.
declare -A EXTERN_WGET_PID
for pid in $(pgrep -f "wget .*${DATASET_DIR}" 2>/dev/null || true); do
    cmdline=$(tr '\0' ' ' < /proc/$pid/cmdline 2>/dev/null)
    for c in $cases; do
        if echo "$cmdline" | grep -q -F "${TARBALL[$c]}"; then
            EXTERN_WGET_PID[$c]=$pid
            log "external wget already running for $c (pid $pid) — will wait for it"
        fi
    done
done

# Kick off a background `wget -c` for every case at startup. wget -c does a
# HEAD against the server: it's near-instant if the file is already complete,
# resumes if partial, downloads from scratch if absent. The sweep loop later
# `wait`s for each case's wget before running it — so cases whose tarballs are
# already complete will essentially skip the wait and run immediately.
declare -A DL_PID
for c in $cases; do
    if [ -n "${EXTERN_WGET_PID[$c]:-}" ]; then
        log "DOWNLOAD using external wget for $c (pid ${EXTERN_WGET_PID[$c]})"
        DL_PID[$c]=${EXTERN_WGET_PID[$c]}
    else
        log "DOWNLOAD start (background) $c"
        wget -c -q --timeout=60 --tries=3 "${URL[$c]}" -O "${TARBALL[$c]}" &
        DL_PID[$c]=$!
    fi
done

# Dynamic scheduling with bounded parallelism. Pick whichever case's wget has
# finished first; launch up to MAX_PARALLEL case runs concurrently. Each case
# run uses ~2 cores (csh + python pipelines in parallel within the case), so
# MAX_PARALLEL=12 = ~24 cores busy on a 64-core box; FFTW shim keeps each FFT
# serial so this stays well under the core count. Watch swap if you push higher
# — heavy cases (S1_Ridgecrest_EQ, ALOS2_SCAN_SSAF) can RAM-pressure the box.
MAX_PARALLEL=${MAX_PARALLEL:-12}
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
    # Reap the wget exit status. `wait` only works on child PIDs of this shell;
    # for an externally-running wget we adopted via EXTERN_WGET_PID, just check
    # the file landed.
    if [ -n "${EXTERN_WGET_PID[$next]:-}" ]; then
        rc=0; [ ! -s "${TARBALL[$next]}" ] && rc=1
    else
        wait "${DL_PID[$next]}"; rc=$?
    fi
    if [ $rc -ne 0 ]; then
        log "DOWNLOAD FAIL $next (wget rc=$rc) — skipping"
        [ ! -s "${TARBALL[$next]}" ] && rm -f "${TARBALL[$next]}"
        continue
    fi
    # Verify tarball is a valid gzip — catches truncated/corrupted downloads
    # (e.g. concurrent wgets fighting, NFS write errors). per project_rules.md
    # #1: don't fall through to extraction on bad data — remove and skip so the
    # case is retried next sweep with a fresh download.
    # IMPORTANT: only delete on a "real" gzip-detected corruption (rc=1).
    # rc=137/143 mean gzip was killed (SIGKILL/SIGTERM) — likely an external
    # pkill that matched the tarball filename, not an actual data problem.
    # Deleting on signal would force a needless 44GB re-download.
    gzip -t "${TARBALL[$next]}" 2>/dev/null
    gz_rc=$?
    if [ $gz_rc -ne 0 ]; then
        if [ $gz_rc -ge 128 ]; then
            log "INTEGRITY CHECK killed (rc=$gz_rc) for $next — skipping run, leaving tarball intact for retry"
            continue
        fi
        log "INTEGRITY FAIL $next (gzip rc=$gz_rc) — tarball corrupt; removing and skipping"
        rm -f "${TARBALL[$next]}"
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
