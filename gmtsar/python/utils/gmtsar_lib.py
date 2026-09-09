#! /usr/bin/env python3
"""
# gmtsar_lib.py is part of pyGMTSAR. 
# It hosts commonly used functions similar to CSH.
# Dunyu Liu, 20230202.

# check_file_report
# grep_value
# replace_strings
# file_shuttle
"""

import sys, os, re, configparser
import subprocess, glob, shutil, threading

_WIN_BASH = None
_WIN_BASH_RESOLVED = False
_WIN_BASH_LOCK = threading.Lock()


def _win_bash():
    """Locate Git-for-Windows' bash.exe (memoized). subprocess's shell=True
    invokes cmd.exe on Windows, which understands none of the POSIX shell
    syntax (&&, ln -sf, rm -rf, mkdir -p, backticks, pipes to /dev/null,
    ...) used throughout this pipeline -- Git Bash (near-universally
    present alongside a Windows git install, and this repo already
    requires git) provides a real POSIX shell without needing WSL/sudo."""
    global _WIN_BASH, _WIN_BASH_RESOLVED
    if _WIN_BASH_RESOLVED:
        return _WIN_BASH
    with _WIN_BASH_LOCK:
        # Re-check inside the lock: another thread may have finished
        # resolving while this one was waiting on the lock. Without the
        # lock (and with the old code's _WIN_BASH_RESOLVED=True set
        # BEFORE _WIN_BASH itself was assigned), two threads racing here
        # -- as case_runner.py's csh_slot()/py_slot() do -- could see
        # _WIN_BASH_RESOLVED already True but _WIN_BASH still None,
        # silently falling through shell_run() to its shell=True/cmd.exe
        # fallback instead of Git Bash. Real bug hit standing this up:
        # one of two concurrent `cleanup all` calls failed with cmd.exe's
        # "'cleanup' is not recognized ..." while the other succeeded.
        if _WIN_BASH_RESOLVED:
            return _WIN_BASH
        if os.name == 'nt':
            path_bash = shutil.which('bash')
            # Windows 10+ ships a System32\bash.exe stub that launches WSL --
            # NOT a real shell (this project is native-Windows-only, no WSL),
            # and it'd otherwise shadow Git Bash whenever System32 precedes
            # Git\bin on PATH. Reject it explicitly rather than trusting
            # PATH order.
            if path_bash and 'system32' in path_bash.lower():
                path_bash = None
            for candidate in (
                os.environ.get('GMTSAR_WIN_BASH'),
                r'C:\Program Files\Git\bin\bash.exe',
                r'C:\Program Files (x86)\Git\bin\bash.exe',
                path_bash,
            ):
                if candidate and os.path.isfile(candidate):
                    _WIN_BASH = candidate
                    break
            else:
                sys.exit(
                    "gmtsar_lib: running on Windows but no Git-for-Windows "
                    "bash.exe found (checked $GMTSAR_WIN_BASH, PATH, "
                    "C:\\Program Files\\Git\\bin\\bash.exe) -- this pipeline "
                    "shells out using POSIX syntax (ln -sf, rm -rf, mkdir -p, "
                    "&&) that cmd.exe cannot run. Install Git for Windows, or "
                    "set GMTSAR_WIN_BASH to a bash.exe path.")
        _WIN_BASH_RESOLVED = True
    return _WIN_BASH


_WIN_PATH_VAR = 'GMTSAR_WIN_PATH'
# Carries the pristine Windows-style PATH through nested bash/python hops
# (p2p_processing -> bash -c 'pre_proc ...' -> pre_proc.py -> bash -c
# 'extend_orbit ...' -> ...), as a defensive fallback only -- see
# _bash_env(). Deliberately NOT used to convert PATH to POSIX/MSYS form:
# an earlier version of this function did exactly that (rewriting each
# entry to /c/... form for bash's own env=), which seemed right (bash's
# *own* command lookup does need a POSIX-style PATH) but broke every
# single gmtsar .exe launched from within that bash -- confirmed via a
# direct CreateProcess repro (bypassing bash entirely) that returned
# 0xC0000135 / STATUS_DLL_NOT_FOUND with a POSIX PATH and rc=0 with a
# Windows-style one. Reason: those .exes dynamically link gmt.dll /
# openblas.dll / tiff.dll from the conda env's Library/bin, and the
# WINDOWS PE LOADER (not bash) resolves that at process-create time --
# it cannot parse a colon-separated /c/... PATH at all. Git Bash/MSYS
# already handles the POSIX-view-internally / Windows-view-to-children
# duality correctly on its own (that's why the ORIGINAL, unmodified
# gmtsar_lib.py -- no env override whatsoever -- ran extend_orbit fine
# even nested inside pre_proc.py); the fix here is limited to making
# sure a Windows-style PATH is what gets fed in, never re-deriving one
# ourselves.


def _bash_env(kwargs):
    """Pop/build the env= to hand to a bash -c subprocess: caller-supplied
    env (or a copy of os.environ), with a Windows-style PATH guaranteed
    (see _WIN_PATH_VAR module comment for why this must NOT be POSIX-
    converted). Git Bash's own MSYS runtime does the POSIX-vs-Windows
    translation in both directions from here."""
    env = dict(kwargs.pop('env', None) or os.environ)
    win_path = env.get(_WIN_PATH_VAR) or env.get('PATH', '')
    env[_WIN_PATH_VAR] = win_path
    env['PATH'] = win_path
    return env


def shell_run(cmd, **kwargs):
    """subprocess.run() for a POSIX-shell-syntax command string. On POSIX,
    plain shell=True. On Windows, routes through Git Bash's `bash -c`
    instead of shell=True's cmd.exe (see _win_bash())."""
    bash = _win_bash()
    if bash:
        return subprocess.run([bash, '-c', cmd], env=_bash_env(kwargs), **kwargs)
    return subprocess.run(cmd, shell=True, **kwargs)


def shell_check_output(cmd, **kwargs):
    """subprocess.check_output() for a POSIX-shell-syntax command string
    (pipes, redirections, ...) -- Windows equivalent of shell_run()."""
    bash = _win_bash()
    if bash:
        return subprocess.check_output([bash, '-c', cmd], env=_bash_env(kwargs), **kwargs)
    return subprocess.check_output(cmd, shell=True, **kwargs)


def resolve_sharedir():
    """Return the GMTSAR shared data directory ($GMTSAR/share/gmtsar).
    First tries $GMTSAR env var; falls back to walking up from this file's
    location looking for share/gmtsar. Raises SystemExit if not found.

    Returned path always uses forward slashes, even on Windows: callers
    (filter, fitoffset.py, ...) embed this directly into shell command
    STRINGS run via shell_run()/run() (e.g. f'conv ... {sharedir}/filters/
    gauss15x5 ...'), and that string is handed to `bash -c` unquoted --
    bash's own escaping rules treat backslash+letter as an escape
    sequence and silently DROP the backslash, corrupting any embedded
    Windows-style path (D:\\...\\share\\gmtsar becomes D:...sharegmtsar).
    Forward slashes are valid path separators to both Windows file APIs
    and bash, so they survive either consumer intact."""
    gmtsar = os.environ.get('GMTSAR')
    if gmtsar:
        candidate = os.path.join(gmtsar, 'share', 'gmtsar')
        if os.path.isdir(candidate):
            return candidate.replace('\\', '/')

    # Walk up from this file's location (handles direct + symlinked installs).
    cur = os.path.dirname(os.path.realpath(__file__))
    for _ in range(5):
        candidate = os.path.join(cur, 'share', 'gmtsar')
        if os.path.isdir(candidate):
            return candidate.replace('\\', '/')
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent

    sys.exit("resolve_sharedir: could not locate share/gmtsar directory "
             "(set $GMTSAR or install via install.py --system conda --rebuild)")


def check_file_report(fn):
    # Check if a file exists.
    # If not, print error message.
    #
    exist = True
    if os.path.isfile(fn) == False:
        exist = False
        print(" no file " + fn)
        #sys.exit()
    return exist

def catch_output_cmd(cmd_list, choose_split=False, split_id=-999, digit_id=-100000):
    # catch_output_cmd takes in cmd_list and return the string
    tmp = subprocess.run(cmd_list, stdout=subprocess.PIPE).stdout.decode('utf-8').strip()
    
    if choose_split==True:
        
        if split_id==-999:
            out = tmp.split() # return a list
        else:
            out = tmp.split()[split_id-1] # return a value
            
            if digit_id!=-100000:
                out = tmp.split()[split_id-1][digit_id-1]
    else:
        out = tmp 
        # If choose_split==False, default return is a string. 
    return out

def intFloatOrString(val):
    if val.isdigit():
        return int(val)
    else:
        try:
            return float(val)
        except ValueError:
            return ""
            
def grep_value(fn, s, i):
    # grep_value performs similar functions to unix grep.
    # Given a file name - fn, and a character string - s, find the ith value.
    # The character should be unique in file fn.
    val = ""
    with open(fn, 'r') as f:
        for line in f.readlines():
            if re.search(s, line):
                print(line)
                val = line.split()[i-1]
    return intFloatOrString(val)

def replace_strings(fn, s0, s1):
    # replace_strings will replace str s0 in file fn0,
    #   with the string s1, and update fn0.
    with open(f"{fn}") as f:
        lines = f.readlines()

    updated_lines = []
    for line in lines:
        if s0 in line:
            line = f"{s1}\n"
        updated_lines.append(line)

    with open(f"{fn}", "w") as f:
        f.writelines(updated_lines)

def append_new_line(fn,s0):
    # append the string s0 as a new line at the end of file named fn.
    with open(fn,"a+") as f:
        f.seek(0)
        data = f.read(100)
        if len(data)>0:
            f.write("\n")
        f.write(s0)

def file_shuttle(fn0, fn1, opt):
    """Copy / move / symlink fn0 to fn1. Shells out (still) to preserve
    behavior on glob-bearing args, e.g. file_shuttle('*.PRM', 'dst/', 'cp').
    Warns on non-zero exit but does not raise (consistent with run())."""
    if opt == "cp":
        cmd = f"cp {fn0} {fn1}"
    elif opt == "mv":
        cmd = f"mv {fn0} {fn1}"
    elif opt == "link":
        cmd = f"ln -sf {fn0} {fn1}"
    else:
        raise ValueError(f"file_shuttle: unknown opt {opt!r}")
    print(cmd)
    rc = shell_run(cmd).returncode
    if rc != 0:
        print(f"WARN: file_shuttle exited {rc}: {cmd}", file=sys.stderr)

def delete(fn):
    """Remove a file or directory tree by name. Shells out to preserve glob
    semantics: delete('amp*.grd') must still work. Silent on rm -rf failures
    (matches prior behavior)."""
    shell_run(f"rm -rf {fn}")
    
def assign_arg(arg, str):
    # arg is the list that contains arguments from a terminal input.
    # the function will search for string specified in 'str', and 
    # return the value next to it in arg.
    if str in arg:
       val = arg[arg.index(str)+1]
       return intFloatOrString(val)
    else:
       return 0

def run(cmd):
    """Run a shell command. Non-zero exit prints a WARN to stderr but does
    NOT raise — gmtsar binaries exit non-zero for benign reasons (warnings,
    missing-but-optional files), and the legacy csh pipeline tolerates that.
    Switching from os.system was about VISIBILITY of failures, not making
    them fatal.

    EXCEPTION: rc=127 (command not found, per shell convention) always
    raises. That is never a benign gmtsar warning — it means a binary or
    script isn't on PATH, and the pipeline should fail loudly rather than
    silently no-op through every subsequent step (project_rules.md Rule 1).

    Every call prints a UTC timestamp + the resolved command before running
    it, and a one-line "done" summary (elapsed time + exit code) after —
    unconditionally, not just under GMTSAR_PROFILE=1 — so any case's
    log.txt is self-sufficient for backtracking exactly which commands ran,
    when, and how long each took (see p2p_processing's env-gate config dump
    for the matching backend-selection half of this picture).

    If GMTSAR_PROFILE=1, ALSO records the wall time via profiler.record(...)
    for the aggregate perf-snapshot tooling. The profiler module is a no-op
    when disabled (zero overhead)."""
    import time as _t
    import datetime as _dt_mod
    def _utc_now():
        return _dt_mod.datetime.now(_dt_mod.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    print(" ")
    print(f"[{_utc_now()}] {cmd}")
    _t0 = _t.time()
    rc = shell_run(cmd).returncode
    _dt = _t.time() - _t0
    print(f"[{_utc_now()}] done in {_dt:.3f}s (rc={rc})")
    try:
        from profiler import record as _prof_record  # type: ignore
        _prof_record(cmd, _dt, backend="subprocess")
    except ImportError:
        pass
    if rc == 127:
        raise RuntimeError(f"command not found (rc=127): {cmd}")
    if rc != 0:
        print(f"WARN: command exited {rc}: {cmd}", file=sys.stderr)

def run_make_slc_tsx(xml_path, image_path, output_prefix):
    """Env-gated dispatcher for make_slc_tsx (preproc/TSX_preproc).

    GMTSAR_TSX_PREPROC_PY unset/1 (DEFAULT since 2026-07-13) -> in-process
        Python port (make_slc_tsx_py.py).
    GMTSAR_TSX_PREPROC_PY=0 -> shells out to the C binary. Instant
        rollback: set the env var to 0.

    Parity: verified byte-for-byte (.PRM, .LED, .SLC) against the real C
    binary on two real TSX scenes (TSX_SLC_Hawaii dataset,
    TSX20120615/TSX20121208). See
    gmtsar/python/bin_py/tests/test_make_slc_tsx.py. Performance: as a
    one-shot CLI call the Python port is slower than C (numpy import is a
    ~2.5s fixed tax); amortized (warm interpreter) it is roughly on par.
    pre_proc is only ~7.8% of total case wall time, and a pure-Python
    path removes the C-compiler dependency for this binary -- see
    docs/PATHWAY_FORWARD.md for the measured aggregate impact.
    """
    if os.environ.get("GMTSAR_TSX_PREPROC_PY", "1") == "1":
        print(" ")
        print(f"[make_slc_tsx_py] {xml_path} {image_path} {output_prefix}")
        import time as _t
        _t0 = _t.time()
        import make_slc_tsx_py
        make_slc_tsx_py.make_slc_tsx(xml_path, image_path, output_prefix)
        _dt = _t.time() - _t0
        try:
            from profiler import record as _prof_record  # type: ignore
            _prof_record(f"make_slc_tsx_py {xml_path} {image_path} {output_prefix}",
                         _dt, backend="py_inproc")
        except ImportError:
            pass
    else:
        run(f"make_slc_tsx {xml_path} {image_path} {output_prefix}")


def renameMasterAlignedForS1tops(master0, aligned0):
    print('Renaming master and aligned for SAT==S1_TOPS')
    master = 'S1_'+master0[15:15+8]+'_'+master0[24:24+6]+'_F'+master0[6:7]
    aligned = 'S1_'+aligned0[15:15+8]+'_'+aligned0[24:24+6]+'_F'+aligned0[6:7]
    return master, aligned