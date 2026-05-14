#! /usr/bin/env python3
"""Walk the test work dir and emit work/sweep_summary.md with per-case results,
timings, and comparison status. Safe to run while a sweep is in progress.

Reads:
  work/sweep.log          — DOWNLOAD / RUN / DONE / FAIL lines from run_sweep.sh
  work/timeSpentLog.txt   — per-pipeline wall times appended by runner's case_script
  work/{csh_test,python_test}/<case>/log.txt — per-pipeline run logs
                                              (scanned for SUCCESS:/FAIL: markers)
Writes:
  work/sweep_summary.md
"""
import os, re, sys
from cases import caseNameList, workAbsoluteDir, pythonRunRoot, cshRefRoot

SWEEP_LOG = workAbsoluteDir + 'sweep.log'
TIME_LOG  = workAbsoluteDir + 'timeSpentLog.txt'
OUT_MD    = workAbsoluteDir + 'sweep_summary.md'


def parse_timings():
    """Returns {case: {'csh': sec, 'python': sec}}. Multiple appends use the last."""
    t = {}
    if not os.path.isfile(TIME_LOG):
        return t
    pat = re.compile(r'^(\S+)\s+(csh|python)\s+used\s+(\d+(?:\.\d+)?)\s*s')
    for line in open(TIME_LOG, errors='replace'):
        m = pat.match(line)
        if m:
            t.setdefault(m.group(1), {})[m.group(2)] = float(m.group(3))
    return t


def parse_sweep_log():
    """Returns {case: {'download': str, 'total': int, 'status': str}}."""
    s = {}
    if not os.path.isfile(SWEEP_LOG):
        return s
    for line in open(SWEEP_LOG, errors='replace'):
        m = re.search(r'DOWNLOAD (OK|FAIL) (\S+)', line)
        if m:
            s.setdefault(m.group(2), {})['download'] = m.group(1)
        m = re.search(r'DONE (\S+)\s+\((\d+)s\)', line)
        if m:
            s.setdefault(m.group(1), {})['total'] = int(m.group(2))
            s[m.group(1)]['status'] = 'finished'
        m = re.search(r'RUN (\S+) — starting', line)
        if m and 'status' not in s.get(m.group(1), {}):
            s.setdefault(m.group(1), {})['status'] = 'running'
    return s


def parse_compare_log(path):
    """Count SUCCESS/FAIL lines from compare output captured in sweep.log
    immediately after each RUN line. We grep all sweep.log for the case section."""
    # compare output gets piped into sweep.log; greppable per-case is fuzzy.
    # Instead, just count occurrences across the whole sweep.log per case name.
    return None  # placeholder — comparison counts read in main()


def main():
    timings  = parse_timings()
    swp      = parse_sweep_log()

    # Read full sweep.log once for SUCCESS:/FAIL: scanning per case.
    sweep_text = open(SWEEP_LOG, errors='replace').read() if os.path.isfile(SWEEP_LOG) else ''

    lines = ['# Sweep summary', '',
             f'_generated {os.popen("date").read().strip()}_',
             '', '| Case | Download | Status | csh (s) | py (s) | total (s) | SUCCESS | FAIL |',
             '|---|---|---|---|---|---|---|---|']

    for case in caseNameList:
        s  = swp.get(case, {})
        t  = timings.get(case, {})
        # Count SUCCESS:/FAIL: lines mentioning this case's outputs.
        # compare prints them grouped under "Comparing case  <case>" — scan that block.
        succ = fail = 0
        m = re.search(r'Comparing case\s+' + re.escape(case) + r'\b(.*?)(?:Comparing case|\Z)',
                      sweep_text, re.S)
        if m:
            block = m.group(1)
            succ = len(re.findall(r'^\s*SUCCESS:', block, re.M))
            fail = len(re.findall(r'^\s*FAIL:',    block, re.M))
        lines.append('| {} | {} | {} | {} | {} | {} | {} | {} |'.format(
            case,
            s.get('download', '-'),
            s.get('status',   '-'),
            f"{t.get('csh', '-'):.0f}" if isinstance(t.get('csh'), float) else '-',
            f"{t.get('python', '-'):.0f}" if isinstance(t.get('python'), float) else '-',
            s.get('total', '-'),
            succ or '-',
            fail or '-',
        ))

    with open(OUT_MD, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    print(open(OUT_MD).read())


if __name__ == '__main__':
    main()
