#! /usr/bin/env python3
"""Walk <workdir>/results/<case>.json (written by compare.py) and
<workdir>/timeSpentLog.txt (written by case_runner.py) and emit
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


def _vintage_section(results):
    """Build the 'Git vintage / mid-sweep SHA tracking' Markdown block.

    Aggregates the per-case git fields populated by compare.py (read from
    case_runner.py's sidecar). The summary shows:
      * the sweep-start SHA (earliest 'launched_at' across cases)
      * the sweep-end SHA   (latest  'finished_at' across cases) — flagged
        'ADVANCED to <sha>' when it differs from the start SHA
      * count of cases tagged MIXED_VINTAGE_*
      * a per-case listing for any case carrying a vintage warning

    Per project_rules.md #6/#8: SHA tracking lives next to wall-time so a
    "looks right but ran across a SHA boundary" pass is visible at a glance,
    not buried in a JSON.
    """
    cases_with_sha = []
    for case in caseNameList:
        r = results.get(case) or {}
        sha_start = r.get('git_sha') or ''
        sha_end   = r.get('sha_at_end') or ''
        launched  = r.get('launched_at') or ''
        finished  = r.get('finished_at') or ''
        warnings  = r.get('vintage_warnings') or []
        if sha_start or sha_end or warnings:
            cases_with_sha.append((case, sha_start, sha_end, launched, finished, warnings))

    if not cases_with_sha:
        # No sidecars present (legacy sweep). Stay silent to keep the
        # summary terse — the absence is itself an indicator.
        return []

    # Earliest launched_at → sweep-start SHA; latest finished_at → sweep-end SHA.
    # Use lexicographic compare since the timestamps are ISO-8601 with a
    # fixed UTC suffix.
    by_start  = sorted([c for c in cases_with_sha if c[3]], key=lambda c: c[3])
    by_finish = sorted([c for c in cases_with_sha if c[4]], key=lambda c: c[4])
    sweep_start_sha = by_start[0][1]  if by_start  else ''
    sweep_end_sha   = by_finish[-1][2] if by_finish else ''

    mixed = [c for c in cases_with_sha if c[5]]

    out = ['', '## Git vintage / mid-sweep SHA tracking', '']
    out.append(f'- Sweep SHA (start): `{sweep_start_sha or "?"}`')
    if sweep_end_sha and sweep_start_sha and sweep_end_sha != sweep_start_sha:
        out.append(f'- Sweep SHA (end):   `{sweep_end_sha}` (ADVANCED to `{sweep_end_sha}` mid-sweep)')
    else:
        out.append(f'- Sweep SHA (end):   `{sweep_end_sha or "?"}`')
    out.append(f'- Cases with mixed vintage: {len(mixed)}')
    if mixed:
        out += ['', '| Case | SHA start | SHA end | Warnings |', '|---|---|---|---|']
        for case, sha_s, sha_e, _ls, _lf, ws in mixed:
            out.append(f'| {case} | `{sha_s or "?"}` | `{sha_e or "?"}` | {" / ".join(ws)} |')
    return out


def main():
    timings = parse_timings()
    results = load_results()

    lines = [
        '# Sweep summary', '',
        f'_generated {os.popen("date").read().strip()}_', '',
        '| Case | csh (s) | py (s) | SUCCESS | FAIL | git_sha | vintage |',
        '|---|---|---|---|---|---|---|',
    ]
    total_s = total_f = 0
    for case in caseNameList:
        t = timings.get(case, {})
        r = results.get(case, {})
        comps = r.get('comparisons', [])
        s = sum(1 for c in comps if c.get('status') == 'SUCCESS')
        f = sum(1 for c in comps if c.get('status') == 'FAIL')
        total_s += s
        total_f += f
        # Per-row git_sha + vintage marker: '-' for legacy/missing,
        # 'MIXED' when warnings present, otherwise blank ('ok').
        sha = r.get('git_sha') or '-'
        if r.get('vintage_warnings'):
            vintage = 'MIXED'
        elif r.get('git_sha'):
            vintage = 'ok'
        else:
            vintage = '-'
        lines.append('| {} | {} | {} | {} | {} | {} | {} |'.format(
            case,
            f"{t.get('csh', '-'):.0f}"    if isinstance(t.get('csh'),    float) else '-',
            f"{t.get('python', '-'):.0f}" if isinstance(t.get('python'), float) else '-',
            s or '-',
            f or '-',
            sha,
            vintage,
        ))
    lines += ['', f'**Totals:** {total_s} SUCCESS / {total_f} FAIL']
    lines += _vintage_section(results)

    with open(OUT_MD, 'w') as f:
        f.write('\n'.join(lines) + '\n')
    print(open(OUT_MD).read())


if __name__ == '__main__':
    main()
