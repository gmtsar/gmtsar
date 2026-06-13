# Perf snapshot — smoke, 2026-05-22T21-21-20Z

**Commit:** `1c0849e`  
**Config:** `NUMBA_NUM_THREADS=(not constrained) XCORR_PY_WORKERS=(not constrained) OMP_NUM_THREADS=(not constrained) MKL_NUM_THREADS=(not constrained) OPENBLAS_NUM_THREADS=(not constrained) BLIS_NUM_THREADS=(not constrained) VECLIB_MAXIMUM_THREADS=(not constrained) NUMEXPR_NUM_THREADS=(not constrained) MAX_PARALLEL=(not constrained) SWEEP_FORCE=py`  
**Hardware:** AMD EPYC 7F72 24-Core Processor, 48 cores, nfs workdir (theo2)  
**Software:** GMT 6.4.0, Python 3.11.0  
**Sweep wall:** 0h 0m (12s)  

**Coverage:** 11 cases with scorecards. **10 pass / 1 fail**.

---

## Table 1 — Per-case (csh vs py, score)

| Case | csh | py | Δ | speedup | score |
|------|----:|---:|--:|--------:|:------|
| ✓ ALOS4_Pinon | 1230s | 501s | +729s | 2.46× | 6/0 |
| ✓ RS2_SLC_Hawaii | 178s | 94s | +84s | 1.89× | 6/0 |
| ✓ ALOS2_Brazil | 935s | 497s | +438s | 1.88× | 6/0 |
| ✓ NISAR_Ethiopia | 447s | 290s | +157s | 1.54× | 6/0 |
| ✓ ALOS_SLC_L1.1 | 423s | 323s | +100s | 1.31× | 6/0 |
| ✓ CSK_RAW_Hawaii | 841s | 646s | +195s | 1.30× | 6/0 |
| ✓ ALOS_Baja_EQ | 1101s | 991s | +110s | 1.11× | 6/0 |
| ✓ ALOS_haiti | 1749s | 1646s | +103s | 1.06× | 7/0 |
| ✗ ENVI_Baja_EQ_SLC | 1407s | 1532s | -125s | 0.92× | 3/3 |
| ✓ ERS_Hector_EQ | 1287s | 1492s | -205s | 0.86× | 6/0 |
| ✓ TSX_SLC_Hawaii | 739s | 1963s | -1224s | 0.38× | 6/0 |

## Table 2 — Per-binary timing (single-pair cases only)

| Case | total | dem2topo | resamp_py | xcorr_py | geocode | intf | pre_proc |
|------|------:|---------:|---------:|---------:|---------:|---------:|---------:|
| TSX_SLC_Hawaii | **1963s** | 1677s | 81s | 29s | 54s | 37s | 12s |
| ALOS_haiti | **1646s** | 876s | 66s | 35s | 71s | 54s | 13s |
| ENVI_Baja_EQ_SLC | **1532s** | 1282s | 25s | 23s | 101s | 16s | 22s |
| ERS_Hector_EQ | **1492s** | 1121s | 27s | 21s | 111s | 17s | 3s |
| ALOS_Baja_EQ | **990s** | 357s | 50s | 25s | 75s | 66s | 40s |
| CSK_RAW_Hawaii | **645s** | 133s | 78s | 40s | 22s | 36s | 14s |
| ALOS4_Pinon | **499s** | 264s | 37s | 19s | 66s | 20s | 13s |
| ALOS2_Brazil | **497s** | 335s | 33s | 18s | 31s | 17s | 11s |
| ALOS_SLC_L1.1 | **323s** | 118s | 28s | 25s | 49s | 15s | 21s |
| NISAR_Ethiopia | **286s** | 34s | 6s | 41s | 39s | 5s | - |
| RS2_SLC_Hawaii | **94s** | 33s | 4s | 24s | 16s | 5s | 1s |

## Table 3 — Aggregate cost by stage (across 11 profiled cases)

| Stage | Total | % of pipeline | Class |
|-------|------:|--------------:|-------|
| dem2topo_ra | 6231s | 76.4% | gmt-wrapper |
| geocode | 635s | 7.8% | gmt-subprocess |
| resamp_py | 436s | 5.3% | Numba py |
| xcorr_py | 301s | 3.7% | scipy.fft py |
| intf | 289s | 3.5% | C bin |
| pre_proc | 150s | 1.8% | C bin |
| snaphu | 118s | 1.4% | C bin |
| fitoffset_ra | 1s | 0.0% | gmt-subprocess |

## Table 4 — Failures (cases not all-SUCCESS)

### ENVI_Baja_EQ_SLC — score 3/3, py=1532s

| File | Status | Reason |
|------|--------|--------|
| corr_ll.png | ✓ SUCCESS | — |
| display_amp_ll.png | ✓ SUCCESS | — |
| phasefilt_mask_ll.png | ✓ SUCCESS | — |
| corr_ll.grd | ✗ FAIL | — |
| phasefilt.grd | ✗ FAIL | — |
| filtcorr.grd | ✗ FAIL | — |

---

_Snapshot generated: 2026-05-22T21-21-20Z_  
_Source: sweep.log_  
_Tool: gmtsar/python/tools/perf_snapshot.py_
