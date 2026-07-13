# Perf snapshot — fast, 2026-07-13T07-12-51Z

**Commit:** `7b6d268`  
**Config:** `NUMBA_NUM_THREADS=(not constrained) XCORR_PY_WORKERS=(not constrained) OMP_NUM_THREADS=(not constrained) MKL_NUM_THREADS=(not constrained) OPENBLAS_NUM_THREADS=(not constrained) BLIS_NUM_THREADS=(not constrained) VECLIB_MAXIMUM_THREADS=(not constrained) NUMEXPR_NUM_THREADS=(not constrained) MAX_PARALLEL=(not constrained) SWEEP_FORCE=1`  
**Hardware:** AMD EPYC 7F72 24-Core Processor, 48 cores, 1007.6G RAM, nfs workdir (theo2)  
**Software:** GMT 6.4.0, Python 3.11.0  
**Sweep wall:** 0h 15m (933s)  

**Coverage:** 2 cases with scorecards. **1 pass / 1 fail**.

---

## Table 1 — Per-case (csh vs py, score)

| Case | csh | py | Δ | speedup | score |
|------|----:|---:|--:|--------:|:------|
| ✓ RS2_SLC_Hawaii | 188s | 105s | +83s | 1.79× | 6/0 |
| ✗ ALOS_haiti | 1277s | 1179s | +98s | 1.08× | - |

## Table 2 — Per-binary timing (single-pair cases only)

_Cases without profile (csh-side recipes or wiped mid-sweep): ALOS_haiti_

| Case | total | dem2topo | resamp_py | xcorr_py | geocode | intf | pre_proc |
|------|------:|---------:|---------:|---------:|---------:|---------:|---------:|
| RS2_SLC_Hawaii | **104s** | 40s | 4s | 24s | 17s | 4s | 1s |

## Table 3 — Aggregate cost by stage (across 1 profiled cases)

| Stage | Total | % of pipeline | Class |
|-------|------:|--------------:|-------|
| dem2topo_ra | 40s | 43.5% | gmt-wrapper |
| xcorr_py | 24s | 26.6% | scipy.fft py |
| geocode | 17s | 18.9% | gmt-subprocess |
| intf | 4s | 4.9% | C bin |
| resamp_py | 4s | 4.7% | Numba py |
| pre_proc | 1s | 1.5% | C bin |

## Table 4 — Failures (cases not all-SUCCESS)

_All cases all-SUCCESS._

---

_Snapshot generated: 2026-07-13T07-12-51Z_  
_Source: sweep.log_  
_Tool: gmtsar/python/tools/perf_snapshot.py_
