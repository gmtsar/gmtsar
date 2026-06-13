# Perf snapshot — full, 2026-05-22T11-41-50Z

**Commit:** `6fad00a`  
**Config:** `NUMBA_NUM_THREADS=1 XCORR_PY_WORKERS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 BLIS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMEXPR_NUM_THREADS=1 MAX_PARALLEL=1 SWEEP_FORCE=py`  
**Hardware:** AMD EPYC 7F72 24-Core Processor, 1 cores, nfs workdir (theo2)  
**Software:** Python 3.11.0  
**Sweep wall:** 0h 1m (106s)  

**Coverage:** 9 cases with scorecards. **9 pass / 0 fail**.

---

## Table 1 — Per-case (csh vs py, score)

| Case | csh | py | Δ | speedup | score |
|------|----:|---:|--:|--------:|:------|
| ✓ RS2_SLC_Hawaii | 175s | 89s | +86s | 1.97× | 6/0 |
| ✓ NISAR_Ethiopia | 447s | 282s | +165s | 1.59× | 6/0 |
| ✓ ALOS_SLC_L1.1 | 423s | 306s | +117s | 1.38× | 6/0 |
| ✓ TSX_SLC_Hawaii | 739s | 601s | +138s | 1.23× | 6/0 |
| ✓ CSK_RAW_Hawaii | 703s | 582s | +121s | 1.21× | 6/0 |
| ✓ ALOS2_Brazil | 935s | 806s | +129s | 1.16× | 6/0 |
| ✓ ALOS4_Pinon | 1230s | 1068s | +162s | 1.15× | 6/0 |
| ✓ ERS_Hector_EQ | 1244s | 1088s | +156s | 1.14× | 6/0 |
| ✓ ENVI_Baja_EQ_SLC | 1407s | 1273s | +134s | 1.11× | 6/0 |

## Table 2 — Per-binary timing (single-pair cases only)

| Case | total | dem2topo | resamp_py | xcorr_py | geocode | intf | pre_proc |
|------|------:|---------:|---------:|---------:|---------:|---------:|---------:|
| ENVI_Baja_EQ_SLC | **1273s** | 1021s | 28s | 21s | 102s | 16s | 22s |
| ERS_Hector_EQ | **1088s** | 718s | 27s | 22s | 110s | 16s | 3s |
| ALOS4_Pinon | **1067s** | 818s | 38s | 18s | 67s | 21s | 24s |
| ALOS2_Brazil | **806s** | 638s | 33s | 18s | 31s | 18s | 19s |
| TSX_SLC_Hawaii | **601s** | 311s | 81s | 29s | 54s | 42s | 13s |
| CSK_RAW_Hawaii | **582s** | 73s | 78s | 33s | 21s | 41s | 13s |
| ALOS_SLC_L1.1 | **306s** | 106s | 31s | 20s | 50s | 16s | 20s |
| NISAR_Ethiopia | **279s** | 24s | 6s | 41s | 38s | 4s | - |
| RS2_SLC_Hawaii | **89s** | 32s | 4s | 26s | 14s | 4s | 1s |

## Table 3 — Aggregate cost by stage (across 9 profiled cases)

| Stage | Total | % of pipeline | Class |
|-------|------:|--------------:|-------|
| dem2topo_ra | 3741s | 73.7% | gmt-wrapper |
| geocode | 486s | 9.6% | gmt-subprocess |
| resamp_py | 326s | 6.4% | Numba py |
| xcorr_py | 229s | 4.5% | scipy.fft py |
| intf | 178s | 3.5% | C bin |
| pre_proc | 114s | 2.3% | C bin |
| fitoffset_ra | 1s | 0.0% | gmt-subprocess |

## Table 4 — Failures (cases not all-SUCCESS)

_All cases all-SUCCESS._

---

_Snapshot generated: 2026-05-22T11-41-50Z_  
_Source: sweep.log_  
_Tool: gmtsar/python/tools/perf_snapshot.py_
