# Perf snapshot — v2_1_0_milestone, 2026-05-22T15-34-08Z

**Commit:** `102f22b`  
**Config:** `NUMBA_NUM_THREADS=(not constrained) XCORR_PY_WORKERS=(not constrained) OMP_NUM_THREADS=(not constrained) MKL_NUM_THREADS=(not constrained) OPENBLAS_NUM_THREADS=(not constrained) BLIS_NUM_THREADS=(not constrained) VECLIB_MAXIMUM_THREADS=(not constrained) NUMEXPR_NUM_THREADS=(not constrained) MAX_PARALLEL=(not constrained) SWEEP_FORCE=(not constrained)`  
**Hardware:** AMD EPYC 7F72 24-Core Processor, 1 cores, nfs workdir (theo2)  
**Software:** GMT 6.4.0, Python 3.11.0  
**Sweep wall:** 0h 26m (1567s)  

**Coverage:** 11 cases with scorecards. **11 pass / 0 fail**.

---

## Table 1 — Per-case (csh vs py, score)

| Case | csh | py | Δ | speedup | score |
|------|----:|---:|--:|--------:|:------|
| ✓ RS2_SLC_Hawaii | 178s | 91s | +87s | 1.96× | 6/0 |
| ✓ NISAR_Ethiopia | 447s | 282s | +165s | 1.59× | 6/0 |
| ✓ CSK_RAW_Hawaii | 841s | 592s | +249s | 1.42× | 6/0 |
| ✓ ALOS_SLC_L1.1 | 423s | 312s | +111s | 1.36× | 6/0 |
| ✓ TSX_SLC_Hawaii | 739s | 611s | +128s | 1.21× | 6/0 |
| ✓ ERS_Hector_EQ | 1287s | 1094s | +193s | 1.18× | 6/0 |
| ✓ ALOS2_Brazil | 935s | 810s | +125s | 1.15× | 6/0 |
| ✓ ALOS4_Pinon | 1230s | 1070s | +160s | 1.15× | 6/0 |
| ✓ ALOS_Baja_EQ | 1101s | 991s | +110s | 1.11× | 6/0 |
| ✓ ENVI_Baja_EQ_SLC | 1407s | 1272s | +135s | 1.11× | 6/0 |
| ✓ ALOS_haiti | 1749s | 1646s | +103s | 1.06× | 7/0 |

## Table 2 — Per-binary timing (single-pair cases only)

| Case | total | dem2topo | resamp_py | xcorr_py | geocode | intf | pre_proc |
|------|------:|---------:|---------:|---------:|---------:|---------:|---------:|
| ALOS_haiti | **1646s** | 876s | 66s | 35s | 71s | 54s | 13s |
| ENVI_Baja_EQ_SLC | **1272s** | 1022s | 27s | 21s | 99s | 16s | 22s |
| ERS_Hector_EQ | **1094s** | 719s | 28s | 26s | 110s | 17s | 3s |
| ALOS4_Pinon | **1070s** | 820s | 38s | 18s | 66s | 20s | 25s |
| ALOS_Baja_EQ | **990s** | 357s | 50s | 25s | 75s | 66s | 40s |
| ALOS2_Brazil | **810s** | 639s | 33s | 18s | 31s | 18s | 20s |
| TSX_SLC_Hawaii | **611s** | 313s | 81s | 28s | 55s | 39s | 16s |
| CSK_RAW_Hawaii | **592s** | 73s | 80s | 45s | 24s | 35s | 13s |
| ALOS_SLC_L1.1 | **311s** | 105s | 31s | 24s | 49s | 15s | 20s |
| NISAR_Ethiopia | **279s** | 25s | 6s | 40s | 40s | 5s | - |
| RS2_SLC_Hawaii | **91s** | 33s | 4s | 27s | 13s | 4s | 1s |

## Table 3 — Aggregate cost by stage (across 11 profiled cases)

| Stage | Total | % of pipeline | Class |
|-------|------:|--------------:|-------|
| dem2topo_ra | 4983s | 71.7% | gmt-wrapper |
| geocode | 634s | 9.1% | gmt-subprocess |
| resamp_py | 443s | 6.4% | Numba py |
| xcorr_py | 310s | 4.5% | scipy.fft py |
| intf | 291s | 4.2% | C bin |
| pre_proc | 174s | 2.5% | C bin |
| snaphu | 118s | 1.7% | C bin |
| fitoffset_ra | 1s | 0.0% | gmt-subprocess |

## Table 4 — Failures (cases not all-SUCCESS)

_All cases all-SUCCESS._

---

_Snapshot generated: 2026-05-22T15-34-08Z_  
_Source: sweep.log_  
_Tool: gmtsar/python/tools/perf_snapshot.py_
