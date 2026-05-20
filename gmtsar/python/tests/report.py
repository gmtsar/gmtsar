#! /usr/bin/env python3
"""Walk <workdir>/results/<case>.json (written by compare.py) and
<workdir>/timeSpentLog.txt (written by case_runner.sh) and emit
<workdir>/sweep_summary.md with per-case timings and SUCCESS/FAIL counts.

Safe to run while a sweep is in progress.
"""
import glob, json, os, re, sys
from cases import caseNameList, workAbsoluteDir

RESULTS_DIR = os.path.join(workAbsoluteDir.rstrip(os.sep), 'results')
TIME_LOG    = workAbsoluteDir + 'timeSpentLog.txt'
OUT_MD      = workAbsoluteDir + 'sweep_summary.md'

_TIME_RE = re.compile(r'^(\S+)\s+(csh|python)\s+used\s+(\d+(?:\.\d+)?)\s*s')


def parse_timings():
    """Return {case: {'csh': sec, 'python': sec}}. Last value wins on duplicates."""
    t = {}
    if not os.path.isfile(TIME_LOG):
        return t
    for line in open(TIME_LOG, errors='replace'):
        m = _TIME_RE.match(line)
        if m:
            t.setdefault(m.group(1), {})[m.group(2)] = float(m.group(3))
    return t


def load_results():
    """Return {case: results_dict_from_json}."""
    results = {}
    for path in glob.glob(os.path.join(RESULTS_DIR, '*.json')):
        case = os.path.splitext(os.path.basename(path))[0]
        try:
            results[case] = json.load(open(path))
        except Exception as e:
            print(f'WARN: failed to parse {path}: {e}', file=sys.stderr)
    return results


def main():
    timings = parse_timings()
    results = load_results()

    lines = [
        '# Sweep summary', '',
        f'_generated {os.popen("date").read().strip()}_', '',
        '| Case | csh (s) | py (s) | SUCCESS | FAIL |',
        '|---|---|---|---|---|',
    ]
    total_s = total_f = 0
    for case in caseNameList:
        t = timings.get(case, {})
        comps = results.get(case, {}).get('comparisons', [])
        s = sum(1 for c in comps if c.get('status') == 'SUCCESS')
        f = sum(1 for c in comps if c.get('status') == 'FAIL')
        total_s += s
        total_f += f
        lines.append('| {} | {} | {} | {} | {} |'.format(
            case,
            f"{t.get('csh', '-'):.0f}"    if isinstance(t.get('csh'),    float) else '-',
            f"{t.get('python', '-'):.0f}" if isinstance(t.get('python'), float) else '-',
            s or '-',
            f or '-',
        ))
    lines += ['', f'**Totals:** {total_s} SUCCESS / {total_f} FAIL']

    with open(OUT_MD, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    print(open(OUT_MD).read())


if __name__ == '__main__':
    main()
