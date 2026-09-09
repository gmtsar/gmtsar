#! /usr/bin/env python3
"""Driver: launch each case as a background bash subprocess (csh + python run
in parallel within each case), then run compare.py.

Override caseNameList for a subset run:  TEST_CASES=ERS_Hector_EQ,ALOS_Baja_EQ python3 runner.py
"""
import os, runpy, shutil, signal, subprocess, time
from cases import caseNameList, rawDir, SLCDir, \
    workAbsoluteDir, pythonRunRoot, cshRefRoot, datasetRoot, recipesDir, \
    archive_path

# Topex archive naming: most cases use .tar.gz; one exception (see tkGUI.gmtsar sample_dict).

# LD_PRELOAD shim that forces FFTW serial. libgmt is linked against libfftw3f_threads
# and ignores env vars — see fftw_force_serial.c. Resolved relative to this script
# so the install is portable; if missing, runs without it (just slower).
_PRELOAD_SHIM = os.path.abspath(os.path.join(
    os.path.dirname(__file__), os.pardir, 'fftw_force_serial.so'))



def stage_python_readmes():
    """Copy recipes/* into the workdir's recipes/ (skip if already present)."""
    src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'recipes')
    os.makedirs(recipesDir, exist_ok=True)
    for f in os.listdir(src_dir):
        dst = os.path.join(recipesDir, f)
        if not os.path.exists(dst):
            shutil.copy2(os.path.join(src_dir, f), dst)


_CASE_RUNNER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'case_runner.sh')


def case_argv(case, cshDir, pyDir, tarball, pyReadme, timeLog, preload_shim):
    """Build the argv for case_runner.sh (positional args)."""
    return ['bash', _CASE_RUNNER, case, cshDir, pyDir, tarball, pyReadme, timeLog, preload_shim]


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
        tb = archive_path(caseName)
        if not os.path.isfile(tb):
            print(f'[{caseName}] SKIP — tarball missing: {tb}')
            continue
        argv = case_argv(
            case=caseName,
            cshDir=cshRefRoot + caseName,
            pyDir=pythonRunRoot + caseName,
            tarball=tb,
            pyReadme=recipesDir + 'README_' + caseName + '.txt',
            timeLog=timeLog,
            preload_shim=_PRELOAD_SHIM,
        )
        p = subprocess.Popen(argv, start_new_session=True)
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
    runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'compare.py'),
                   run_name='__main__')


if __name__ == '__main__':
    main()
