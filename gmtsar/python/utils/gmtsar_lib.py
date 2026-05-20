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
import subprocess, glob


def resolve_sharedir():
    """Return the GMTSAR shared data directory ($GMTSAR/share/gmtsar).
    First tries $GMTSAR env var; falls back to walking up from this file's
    location looking for share/gmtsar. Raises SystemExit if not found."""
    gmtsar = os.environ.get('GMTSAR')
    if gmtsar:
        candidate = os.path.join(gmtsar, 'share', 'gmtsar')
        if os.path.isdir(candidate):
            return candidate

    # Walk up from this file's location (handles direct + symlinked installs).
    cur = os.path.dirname(os.path.realpath(__file__))
    for _ in range(5):
        candidate = os.path.join(cur, 'share', 'gmtsar')
        if os.path.isdir(candidate):
            return candidate
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent

    sys.exit("resolve_sharedir: could not locate share/gmtsar directory "
             "(set $GMTSAR or install via install.sh --build)")


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
    rc = subprocess.run(cmd, shell=True).returncode
    if rc != 0:
        print(f"WARN: file_shuttle exited {rc}: {cmd}", file=sys.stderr)

def delete(fn):
    """Remove a file or directory tree by name. Shells out to preserve glob
    semantics: delete('amp*.grd') must still work. Silent on rm -rf failures
    (matches prior behavior)."""
    subprocess.run(f"rm -rf {fn}", shell=True)
    
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
    them fatal."""
    print(" ")
    print(cmd)
    rc = subprocess.run(cmd, shell=True).returncode
    if rc != 0:
        print(f"WARN: command exited {rc}: {cmd}", file=sys.stderr)

def renameMasterAlignedForS1tops(master0, aligned0):
    print('Renaming master and aligned for SAT==S1_TOPS')
    master = 'S1_'+master0[15:15+8]+'_'+master0[24:24+6]+'_F'+master0[6:7]
    aligned = 'S1_'+aligned0[15:15+8]+'_'+aligned0[24:24+6]+'_F'+aligned0[6:7]
    return master, aligned