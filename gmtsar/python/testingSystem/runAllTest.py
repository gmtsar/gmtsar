#! /usr/bin/env python3
"""Driver: launch each case as a background bash subprocess (csh + python run
in parallel within each case), then run checkTest.py.

Override caseNameList for a subset run:  TEST_CASES=ERS_Hector_EQ,ALOS_Baja_EQ python3 runAllTest.py
"""
import os, runpy, shutil, signal, subprocess, time
from pathListForTest import caseNameList, intfDirList, rawDir, \
    SLCDir, workAbsoluteDir, pythonRunRoot, cshRefRoot, datasetRoot, pythonCommandListPath

# Topex archive naming: most cases use .tar.gz; one exception (see tkGUI.gmtsar sample_dict).
TGZ_EXCEPTIONS = {'NISAR_SIM_ALOS'}

# LD_PRELOAD shim that forces FFTW serial. libgmt is linked against libfftw3f_threads
# and ignores env vars — see fftw_force_serial.c. Resolved relative to this script
# so the install is portable; if missing, runs without it (just slower).
_PRELOAD_SHIM = os.path.abspath(os.path.join(
    os.path.dirname(__file__), os.pardir, 'fftw_force_serial.so'))

def tarball_path(case):
    ext = '.tgz' if case in TGZ_EXCEPTIONS else '.tar.gz'
    return datasetRoot + case + ext


def stage_python_readmes():
    """Copy pythonREADME/* into the workdir's pythonREADME/ (skip if already present)."""
    src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pythonREADME')
    os.makedirs(pythonCommandListPath, exist_ok=True)
    for f in os.listdir(src_dir):
        dst = os.path.join(pythonCommandListPath, f)
        if not os.path.exists(dst):
            shutil.copy2(os.path.join(src_dir, f), dst)


def case_script(case, cshDir, pyDir, tarball, pyReadme, timeLog, preload_shim):
    """Shell command for one case: csh ref + python run in parallel."""
    preload = f'export LD_PRELOAD={preload_shim}' if os.path.isfile(preload_shim) else '# (no FFTW shim — slower)'
    return f'''
set -u
# Pin known thread pools to 1; libgmt's FFTW pthreads ignore these, so we also
# LD_PRELOAD the shim built by install.sh --build.
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 FFTW_NUM_THREADS=1
{preload}

# csh reference (background) — only build if no outputs yet
(
    if [ -z "$(find {cshDir} -name '*.grd' -o -name '*.png' 2>/dev/null | head -1)" ]; then
        echo "[{case}] no csh reference — running legacy csh recipe"
        mkdir -p {cshDir}
        tar -xzf {tarball} -C {cshDir}
        t0=$SECONDS
        ( cd {cshDir} && cleanup all && csh README.txt > log.txt 2>&1 )
        echo "{case} csh used $((SECONDS-t0)) s" >> {timeLog}
    fi
) &
cshPid=$!

# python run (background) — always runs
(
    mkdir -p {pyDir}
    if [ -z "$(ls -A {pyDir} 2>/dev/null)" ]; then
        tar -xzf {tarball} -C {pyDir}
    fi
    t0=$SECONDS
    ( cd {pyDir} \\
      && cleanup all \\
      && cp {pyReadme} . \\
      && chmod +x README_{case}.txt \\
      && ./README_{case}.txt > log.txt 2>&1 )
    echo "{case} python used $((SECONDS-t0)) s" >> {timeLog}
) &
pyPid=$!

wait $cshPid $pyPid
'''


def main():
    os.makedirs(datasetRoot, exist_ok=True)
    os.makedirs(pythonRunRoot, exist_ok=True)
    os.makedirs(cshRefRoot, exist_ok=True)
    stage_python_readmes()

    timeLog = workAbsoluteDir + 'timeSpentLog.txt'
    procs = []   # list of (caseName, Popen)
    runStart = time.time()

    # start_new_session=True puts each bash in its own pgrp so SIGINT propagates
    # to the whole subtree (no orphaned csh/p2p_processing on Ctrl-C).
    def _kill_all(signum=None, _frame=None):
        for case, p in procs:
            if p.poll() is None:
                try: os.killpg(p.pid, signal.SIGTERM)
                except ProcessLookupError: pass
        if signum is not None:
            raise SystemExit(128 + signum)

    signal.signal(signal.SIGINT,  _kill_all)
    signal.signal(signal.SIGTERM, _kill_all)

    for caseName in caseNameList:
        tb = tarball_path(caseName)
        if not os.path.isfile(tb):
            print(f'[{caseName}] SKIP — tarball missing: {tb}')
            continue
        cmd = case_script(
            case=caseName,
            cshDir=cshRefRoot + caseName,
            pyDir=pythonRunRoot + caseName,
            tarball=tb,
            pyReadme=pythonCommandListPath + 'README_' + caseName + '.txt',
            timeLog=timeLog,
            preload_shim=_PRELOAD_SHIM,
        )
        p = subprocess.Popen(['bash', '-c', cmd], start_new_session=True)
        procs.append((caseName, p))
        print(f'[{caseName}] started (pid {p.pid})')

    for case, p in procs:
        p.wait()
        print(f'[{case}] exit {p.returncode}')

    wallSec = time.time() - runStart
    print('\n=== Performance summary ===')
    print(f'wall-clock total: {wallSec:.1f}s  (parallelism: {len(procs)} case(s))')
    if os.path.isfile(timeLog):
        print('-' * 50)
        with open(timeLog) as f:
            for line in f:
                print('  ' + line.rstrip())

    # Run comparison in-process — avoids a fresh interpreter startup with full
    # scipy/skimage/matplotlib imports.
    os.chdir(workAbsoluteDir)
    runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'checkTest.py'),
                   run_name='__main__')


if __name__ == '__main__':
    main()
