# Perf snapshot — full21_v2_0_0_milestone, 2026-05-22T11-04-58Z

**Commit:** `6ab14b0`  
**Config:** `NUMBA_NUM_THREADS=(not constrained) XCORR_PY_WORKERS=(not constrained) OMP_NUM_THREADS=(not constrained) MKL_NUM_THREADS=(not constrained) OPENBLAS_NUM_THREADS=(not constrained) BLIS_NUM_THREADS=(not constrained) VECLIB_MAXIMUM_THREADS=(not constrained) NUMEXPR_NUM_THREADS=(not constrained) MAX_PARALLEL=(not constrained) SWEEP_FORCE=(not constrained)`  
**Hardware:** AMD EPYC 7F72 24-Core Processor, 1 cores, nfs workdir (theo2)  
**Software:** Python 3.11.0  
**Sweep wall:** 0h 2m (132s)  

**Coverage:** 0 cases with scorecards. **0 pass / 0 fail**.

---

## Table 1 — Per-case (csh vs py, score)

| Case | csh | py | Δ | speedup | score |
|------|----:|---:|--:|--------:|:------|

## Table 2 — Per-binary timing (single-pair cases only)

| Case | total | dem2topo | resamp_py | xcorr_py | geocode | intf | pre_proc |
|------|------:|---------:|---------:|---------:|---------:|---------:|---------:|

## Table 3 — Aggregate cost by stage (across 0 profiled cases)

| Stage | Total | % of pipeline | Class |
|-------|------:|--------------:|-------|

## Table 4 — Failures (cases not all-SUCCESS)

_All cases all-SUCCESS._

---

_Snapshot generated: 2026-05-22T11-04-58Z_  
_Source: sweep.log_  
_Tool: gmtsar/python/tools/perf_snapshot.py_
