#!/bin/bash
# sweep.sh — download + run + compare every case in cases.caseNameList.
# Designed for an unattended multi-hour run.
#
# Tier control (sets TEST_TIER, picked up by cases.py):
#   bash sweep.sh                 # full sweep (~3 h)
#   bash sweep.sh --smoke         # 1 case (~3 min, pipeline alive check)
#   bash sweep.sh --fast          # 9 SAT families (~30-40 min)
#   bash sweep.sh --unit          # pytest unit tests only (~3-5 min, no data needed)
#   bash sweep.sh --sample [N]    # N random cases seeded from HEAD SHA (default 3)
#   bash sweep.sh --smart_fast    # change-aware: run only cases touched by HEAD~1..HEAD
#
# Logs: gmtsar/python/work/sweep.log + per-case work/{python,csh}_test/<case>/log.txt

set -u

_SAMPLE_N=3   # default for --sample when N not supplied
_MODE=''      # set by --unit / --sample / --smart_fast; empty = normal sweep

case ${1:-} in
    --smoke|smoke)       export TEST_TIER=smoke ;;
    --fast|fast)         export TEST_TIER=fast  ;;
    --full|full|'')      export TEST_TIER=full  ;;
    --unit|unit)         _MODE=unit ;;
    --sample|sample)
        _MODE=sample
        # Optional second arg is N
        if [ -n "${2:-}" ] && echo "${2}" | grep -qE '^[0-9]+$'; then
            _SAMPLE_N="${2}"
        fi
        ;;
    --smart_fast|smart_fast) _MODE=smart_fast ;;
    -h|--help)
        sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1 (try --smoke / --fast / --full / --unit / --sample [N] / --smart_fast / --help)" >&2; exit 2 ;;
esac

export GMTSAR=/home/staff/dliu/gmtsar
# Prepend gmtsar bin AND the conda gmtsar env so `gmt` is on PATH for
# subprocess calls inside the unit tests (required by test_dem2topo_ra
# TestWiredFlipudParity fallback path and any test that shells out to gmt).
export PATH=$GMTSAR/bin:/home/staff/dliu/anaconda3/envs/gmtsar/bin:$PATH
PY=/home/staff/dliu/anaconda3/envs/gmtsar/bin/python3
DATASET_DIR=$GMTSAR/gmtsar/python/work/dataset
WORK=$GMTSAR/gmtsar/python/work
LOG=$WORK/sweep.log
TESTSYS=$GMTSAR/gmtsar/python/tests
mkdir -p "$DATASET_DIR" "$WORK"

# ── Tier 0: --unit ────────────────────────────────────────────────────────────
# Runs pytest over bin_py/tests/ without any SAR data downloads.
# Pytest is in anaconda_knox (which ships pytest 7.4.4); the gmtsar conda env
# python3 is missing pytest.  We use the knox python3 for collection + run,
# but the gmtsar PATH is already set above so gmt is reachable by subprocesses.
_PYTEST=/home/staff/dliu/anaconda_knox/bin/python3
_UNIT_TESTS=$GMTSAR/gmtsar/python/bin_py/tests

if [ "${_MODE:-}" = "unit" ]; then
    mkdir -p "$WORK"
    SUMMARY_UNIT="$WORK/sweep_summary_unit.md"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] === unit test run started ===" | tee -a "$LOG"
    t0=$SECONDS
    # Run pytest; capture output; tee to log so the unit run is auditable.
    UNIT_LOG="$WORK/sweep_unit.log"
    "$_PYTEST" -m pytest "$_UNIT_TESTS" -x --tb=short -q 2>&1 | tee "$UNIT_LOG"
    pytest_rc=${PIPESTATUS[0]}
    wall=$((SECONDS - t0))
    # Parse pass/fail/skip counts from the last summary line ("X passed, Y skipped...").
    summary_line=$(grep -E '^[0-9]+ (passed|failed)' "$UNIT_LOG" | tail -1)
    passed=$(echo "$summary_line" | grep -oE '[0-9]+ passed' | grep -oE '[0-9]+' || echo 0)
    failed=$(echo "$summary_line" | grep -oE '[0-9]+ failed' | grep -oE '[0-9]+' || echo 0)
    skipped=$(echo "$summary_line" | grep -oE '[0-9]+ skipped' | grep -oE '[0-9]+' || echo 0)
    {
        echo "# Unit test summary"
        echo ""
        echo "_generated $(date)_"
        echo ""
        echo "| Metric | Value |"
        echo "|---|---|"
        echo "| wall time (s) | $wall |"
        echo "| passed | ${passed:-0} |"
        echo "| failed | ${failed:-0} |"
        echo "| skipped | ${skipped:-0} |"
        echo "| exit code | $pytest_rc |"
        echo ""
        echo "## pytest invocation"
        echo ""
        echo "\`\`\`"
        echo "$_PYTEST -m pytest $_UNIT_TESTS -x --tb=short -q"
        echo "\`\`\`"
        echo ""
        echo "## Full output"
        echo ""
        echo "\`\`\`"
        cat "$UNIT_LOG"
        echo "\`\`\`"
    } > "$SUMMARY_UNIT"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] unit summary → $SUMMARY_UNIT (${wall}s, rc=$pytest_rc)" | tee -a "$LOG"
    exit $pytest_rc
fi

# ── Tier 5: --sample N ────────────────────────────────────────────────────────
# Pick _SAMPLE_N cases at random, seeded deterministically from HEAD SHA so the
# selection is reproducible (same commit → same N cases every run).
if [ "${_MODE:-}" = "sample" ]; then
    HEAD_SHA=$(cd "$TESTSYS" && git rev-parse HEAD 2>/dev/null || echo "deadbeef")
    export TEST_TIER=full   # let cases.py build the full 21-case pool first
    # Ask cases.py for the full enabled list, then sample deterministically.
    all_cases=$( cd "$TESTSYS" && "$PY" -c "
from cases import caseNameList
print(' '.join(caseNameList))
" )
    # Convert to array for indexed access.
    read -ra _ALL_ARR <<< "$all_cases"
    total=${#_ALL_ARR[@]}
    if [ "$_SAMPLE_N" -ge "$total" ]; then
        # Requesting more than available — just run all.
        export TEST_CASES=$(echo "$all_cases" | tr ' ' ',')
    else
        # Deterministic Fisher-Yates using SHA-seeded arithmetic.
        # Seed: take first 8 hex chars of SHA → decimal.
        seed_hex="${HEAD_SHA:0:8}"
        seed_dec=$(( 16#$seed_hex ))
        # Pure-bash LCG (Numerical Recipes parameters): enough for N≤21.
        lcg_state=$seed_dec
        lcg_next() { lcg_state=$(( (lcg_state * 1664525 + 1013904223) & 0xFFFFFFFF )); echo $lcg_state; }
        # Partial Fisher-Yates: pick _SAMPLE_N indices.
        indices=( $(seq 0 $((total - 1))) )
        picked=()
        for i in $(seq 0 $((_SAMPLE_N - 1))); do
            r=$(lcg_next)
            rem=$(( total - i ))
            j=$(( r % rem + i ))
            # swap indices[i] and indices[j]
            tmp=${indices[$i]}
            indices[$i]=${indices[$j]}
            indices[$j]=$tmp
            picked+=( "${_ALL_ARR[${indices[$i]}]}" )
        done
        export TEST_CASES=$(IFS=,; echo "${picked[*]}")
    fi
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] --sample $_SAMPLE_N seed=$HEAD_SHA → cases: $TEST_CASES" | tee -a "$LOG"
    # Fall through to the main sweep logic with TEST_CASES set.
    unset _MODE
fi

# ── Tier 2: --smart_fast ─────────────────────────────────────────────────────
# Map files changed in HEAD~1..HEAD to a case subset via touched_to_cases.py.
if [ "${_MODE:-}" = "smart_fast" ]; then
    export TEST_TIER=full   # pool for cases.py
    changed_files=$(cd "$TESTSYS/.." && git diff HEAD~1..HEAD --name-only 2>/dev/null || echo "")
    if [ -z "$changed_files" ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] --smart_fast: no diff HEAD~1..HEAD (initial commit?); running smoke tier" | tee -a "$LOG"
        export TEST_TIER=smoke
        unset _MODE
    else
        # stderr carries warnings (unrecognised paths etc.); only stdout is case list.
        selected=$(cd "$TESTSYS/.." && "$PY" "$TESTSYS/touched_to_cases.py" <<< "$changed_files" 2>>"$LOG")
        if [ -z "$selected" ]; then
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] --smart_fast: changed files map to 0 cases (docs/config only) — no pipeline run needed" | tee -a "$LOG"
            exit 0
        fi
        export TEST_CASES="$selected"
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] --smart_fast: changed files → cases: $TEST_CASES" | tee -a "$LOG"
        unset _MODE
    fi
fi

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
# already passing.
#
# SWEEP_FORCE — rerun semantics:
#   SWEEP_FORCE=1      hard force: wipe csh_test/<c>, python_test/<c>, and
#                      results/<c>.json. Both pipelines re-extract + re-run.
#                      ~3h for the full 21-case sweep.
#   SWEEP_FORCE=py     soft force: wipe ONLY python_test/<c> and
#                      results/<c>.json. case_runner.sh re-extracts the
#                      tarball into a fresh python_test/<c>. csh_test/<c>
#                      preserved as the immutable reference. ~1/2 the wall
#                      time of the hard force. Use for iterating on
#                      python-side code without rebuilding the csh oracle.
# Modes use rename-then-delete to survive NFS .nfs* lock files (parent of
# /tmp/<stale> directory is renamed atomically; the actual rm runs in the
# background and tolerates lingering handles).
if [ -n "${SWEEP_FORCE:-}" ]; then
    case "${SWEEP_FORCE}" in
        py|PY|python)   wipe_csh=0 ;;
        *)              wipe_csh=1 ;;
    esac
    ts=$(date +%s%N)
    for c in $cases; do
        targets="$WORK/python_test/$c"
        [ "$wipe_csh" = 1 ] && targets="$WORK/csh_test/$c $targets"
        for d in $targets; do
            if [ -d "$d" ]; then
                stale="${d}.stale.$$.$ts"
                if mv "$d" "$stale" 2>/dev/null; then
                    (rm -rf "$stale" 2>/dev/null) &
                    disown $! 2>/dev/null || true
                else
                    log "WIPE $c — FAILED to rename $d; aborting (won't run with stale outputs)"
                    exit 1
                fi
            fi
        done
        rm -f "$WORK/results/$c.json"
        if [ "$wipe_csh" = 1 ]; then
            log "WIPE $c (SWEEP_FORCE=1 hard — csh_test, python_test, results cleared)"
        else
            log "WIPE $c (SWEEP_FORCE=py soft — python_test, results cleared; csh_test preserved as reference)"
        fi
    done
fi
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

# Tier 3: blessed scorecard diff — compares python_test outputs against the
# committed golden file in docs/blessed_scorecards/<latest_tag>/<case>.json.
# Non-fatal: a blessed diff failure is surfaced in the log and the markdown
# report, but does NOT override the sweep exit code (that is set by the case
# runs via runner.py).  A dedicated --blessed-check CI job can gate on
# blessed_diff.py directly if needed.
BLESSED_DIFF_TOOL="$TESTSYS/blessed_diff.py"
if [ -f "$BLESSED_DIFF_TOOL" ]; then
    log "Running blessed scorecard diff..."
    "$PY" "$BLESSED_DIFF_TOOL" >> "$LOG" 2>&1 \
        && log "blessed diff PASS" \
        || log "WARN: blessed diff reported regressions — see $WORK/blessed_diff_*.md"
else
    log "WARN: $BLESSED_DIFF_TOOL missing — skipping blessed scorecard diff"
fi

# project_rules.md #7 — every full sweep MUST emit a perf snapshot under
# docs/perf_snapshots/ so the run is reproducible/auditable. Tier becomes a
# label so partial sweeps (smoke/fast) don't masquerade as full ones.
SNAPSHOT_TOOL="$GMTSAR/gmtsar/python/tools/perf_snapshot.py"
if [ -f "$SNAPSHOT_TOOL" ]; then
    label_for_snapshot="${TEST_TIER:-full}"
    "$PY" "$SNAPSHOT_TOOL" --label "$label_for_snapshot" >> "$LOG" 2>&1 \
        && log "perf snapshot written under docs/perf_snapshots/" \
        || log "WARN: perf_snapshot.py failed (non-fatal)"
else
    log "WARN: $SNAPSHOT_TOOL missing — skipping rule-7 snapshot"
fi

log "=== sweep finished ==="
