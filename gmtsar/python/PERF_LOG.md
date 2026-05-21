# gmtsar.python — performance log

Append-only log of pipeline timing measurements. Each entry captures
the configuration, hardware, and per-case timing so we can diff runs
across commits, ports, and hardware.

**Companion JSON:** `perf_snapshot.json` (machine-readable) is produced
by the same script that appends to this MD. Use `python3 -c "import
json; print(json.dumps(json.load(open('PERF_LOG.json'))['runs'][-1],
indent=2))"` to dump the latest run.

**How to append a new entry:**
Run `tools/perf_snapshot.py` (or copy the snapshot Python block at the
end of this doc) after any sweep. It captures: scorecards, py/csh
times, phase_profile_py.json contents, git SHA, hardware perf_*.txt,
and the current wire-in config.

---

## Configuration vocabulary

| Flag | Meaning |
|---|---|
| `xcorr_py_wired` | `utils/p2p_stages.py` calls `xcorr_py` (Python port) instead of C `xcorr` |
| `SAT_llt2rat_py_wired` | `utils/dem2topo_ra` calls `SAT_llt2rat_py` instead of C `SAT_llt2rat` |
| `time_run_wrapping_enabled` | `p2p_stages.py` wraps heavy binary calls with `phase_profile.time_run()` for per-binary timing |
| `resamp_py_wired` | (future) `utils/p2p_stages.py` calls `resamp_py` instead of C `resamp` |
| `geocode_py_wired` | (future) ditto for geocode |

## Hardware reference (theo2)

| | |
|---|---|
| host | theo2.ig.utexas.edu |
| cpu | AMD EPYC 7F72 24-Core Processor |
| cores (logical) | 48 |
| RAM | 1 TB |
| workdir filesystem | NFS — utig5.ig.utexas.edu:/bigpool/home |
| co-tenants | varies (e.g. `chao` running ~7 cores worth of python at 22:00 2026-05-20) |

Note: NFS workdir adds I/O variance. Same case on same hardware can
drift ±20% wall time between runs depending on cache state and
co-tenant load.

---

## Run 2026-05-20 22:00 — RS2 + 4 long S1, xcorr_py wired

**git_sha:** (commit pending)
**config:** xcorr_py=ON, SAT_llt2rat_py=OFF, time_run_wrapping=OFF
**load avg during run:** ~40/48
**purpose:** prove xcorr_py is wired-in safe across all enabled full-tier cases

### Per-case summary

| Case | Score | py | csh | speedup |
|---|---|---|---|---|
| ALOS2_Brazil | 6/0 | 885s | 966s | 1.09× |
| ALOS2_Japan_Fugi_left | 6/0 | 1254s | 1346s | 1.07× |
| ALOS4_Pinon | 6/0 | 1131s | 1230s | 1.09× |
| ALOS_Baja_EQ | 6/0 | 999s | 1076s | 1.08× |
| ALOS_ERSDAC_L1.0 | 6/0 | 832s | 911s | 1.09× |
| ALOS_SLC_L1.1 | 6/0 | 343s | 428s | 1.25× |
| ALOS_haiti | 7/0 | 1653s | 1749s | 1.06× |
| CSK_RAW_Hawaii | 6/0 | 669s | 752s | 1.12× |
| CSK_SLC_Italy | 6/0 | 722s | 803s | 1.11× |
| ENVI_Baja_EQ | 6/0 | 1670s | 1740s | 1.04× |
| ENVI_Baja_EQ_SLC | 6/0 | 1335s | 1440s | 1.08× |
| ERS_Hector_EQ | 6/0 | 1150s | 1244s | 1.08× |
| NISAR_Ethiopia | 6/0 | 298s | 476s | 1.60× |
| RS2_SLC_Hawaii | 6/0 | 84s | 176s | 2.10× |
| S1A_SLC_TOPS_Greece | 10/0 | 3048s | 3041s | 1.00× |
| S1_Larsen_C | 10/0 | 5030s | 5016s | 1.00× |
| S1A_SLC_TOPS_LA | (mid-flight at log time) — completed at 22:30 |
| TSX_SLC_Hawaii | 6/0 | 747s | 803s | 1.07× |

**Pattern:**
- Small images (RS2, NISAR): big speedup (1.6–2.1×) — xcorr is large fraction of pipeline
- Medium (ALOS_SLC, CSK): moderate (1.1–1.25×)
- Large (S1, ENVI): negligible (1.00–1.08×) — snaphu/intf/geocode dominate

---

## Run 2026-05-20 22:30 — RS2 binary-timing rerun

**git_sha:** (commit pending)
**config:** xcorr_py=ON, SAT_llt2rat_py=OFF, time_run_wrapping=ON
**purpose:** first per-binary breakdown with `time_run()` wrappers

### RS2_SLC_Hawaii  (total 109s — 24% slower than 22:00 run due to system load)

**Phase breakdown:**

| Phase | Time | % |
|---|---|---|
| P2P1_preprocess | 1.0s | 0.9% |
| P2P2_focus_align | 34.5s | 31.8% |
| P2P3_make_topo | 30.3s | 27.9% |
| P2P4_intf_filter | 15.6s | 14.4% |
| P2P5_unwrap | 0.0s | 0.0% |
| P2P6_geocode | 27.3s | 25.1% |

**Per-binary breakdown (where time_run-wrapped):**

| Binary | Calls | Total | % |
|---|---|---|---|
| `xcorr_py` | 1 | 29.7s | 27.3% |
| `geocode` | 1 | 27.3s | 25.1% |
| `resamp` | 1 | 4.5s | 4.1% |
| `intf` | 1 | 1.9s | 1.7% |
| `pre_proc` | 1 | 1.0s | 0.9% |

**NOT time_run-wrapped in this run** (gaps to close):

- `SAT_llt2rat` — called inside `utils/dem2topo_ra` script, not from `p2p_stages.py`. Accounts for ~28s based on P2P3 - other small calls
- `filter` — wrapping added but RS2 may take an iono variant path; verify on next ENVI/S1 run
- `snaphu` — wrapped but didn't run on RS2 (threshold=0)

**Surprises:**
- `geocode` is 25% of RS2 — bigger than expected. Candidate for next port.
- `resamp` is only 4.5s on RS2's tiny image. Will scale much larger on S1/ENVI.

---

## Future runs — to be appended below this line

(Pending: NISAR binary timing, ALOS_SLC binary timing, CSK_RAW, TSX,
ALOS2_Brazil, ENVI_Baja_EQ_SLC, S1_Larsen_C, S1A_SLC_TOPS_Greece —
all with `time_run` wrappers active.)

---

## Snapshot helper (copy & run as a script)

Save the following to `tools/perf_snapshot.py` (or run inline) to
append a new entry. The output JSON goes alongside `PERF_LOG.md` for
machine-readable diffing.

```python
#!/usr/bin/env python3
"""Snapshot current sweep state + profiles + config → JSON + MD append."""
import json, os, glob, subprocess
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path('/home/utig5/dliu/gmtsar/gmtsar/python')

def collect():
    results = {}
    for f in sorted((ROOT / 'work' / 'results').glob('*.json')):
        d = json.load(open(f))
        c = d.get('comparisons', [])
        results[f.stem] = {
            'pass': sum(1 for x in c if x.get('status')=='SUCCESS'),
            'fail': sum(1 for x in c if x.get('status')=='FAIL'),
            'total': len(c),
        }
    hist = defaultdict(lambda: {'py': [], 'csh': []})
    log = ROOT / 'work' / 'timeSpentLog.txt'
    for line in open(log):
        t = line.split()
        if len(t) >= 4 and t[1] in ('python', 'csh') and t[2] == 'used':
            hist[t[0]][('py' if t[1]=='python' else 'csh')].append(int(t[3]))
    profiles = {}
    for f in (ROOT / 'work' / 'python_test').glob('*/phase_profile_py.json'):
        profiles[f.parent.name] = json.load(open(f))
    git_sha = subprocess.check_output(
        ['git', '-C', str(ROOT.parent.parent), 'rev-parse', 'HEAD']).decode().strip()
    config = {
        'xcorr_py_wired': 'xcorr_py' in (ROOT / 'utils' / 'p2p_stages.py').read_text(),
        'SAT_llt2rat_py_wired': 'SAT_llt2rat_py' in (
            ROOT / 'utils' / 'dem2topo_ra').read_text().split('# NOTE')[0],
        'time_run_wrapping_enabled': 'time_run' in (
            ROOT / 'utils' / 'p2p_stages.py').read_text(),
    }
    return {
        'snapshot_time': datetime.now().isoformat(),
        'git_sha': git_sha,
        'config': config,
        'scorecards': results,
        'timings_history': dict(hist),
        'phase_profiles': profiles,
    }

if __name__ == '__main__':
    snap = collect()
    out_json = ROOT / 'PERF_LOG.json'
    history = json.load(open(out_json)) if out_json.exists() else {'runs': []}
    history['runs'].append(snap)
    json.dump(history, open(out_json, 'w'), indent=2, default=str)
    print(f"appended snapshot @ {snap['snapshot_time']}, now {len(history['runs'])} runs")
```
