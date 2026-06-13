# Perf snapshot — full, 2026-06-13T04-50-43Z

**Commit:** `db62d13` (dirty)  
**Config:** `NUMBA_NUM_THREADS=(not constrained) XCORR_PY_WORKERS=(not constrained) OMP_NUM_THREADS=(not constrained) MKL_NUM_THREADS=(not constrained) OPENBLAS_NUM_THREADS=(not constrained) BLIS_NUM_THREADS=(not constrained) VECLIB_MAXIMUM_THREADS=(not constrained) NUMEXPR_NUM_THREADS=(not constrained) MAX_PARALLEL=1 SWEEP_FORCE=1`  
**Hardware:** AMD EPYC 7F72 24-Core Processor, 48 cores, nfs workdir (theo2)  
**Software:** GMT 6.4.0, Python 3.11.0  
**Sweep wall:** 3h 1m (10872s)  

**Coverage:** 21 cases with scorecards. **21 pass / 0 fail**.

---

## Table 1 — Per-case (csh vs py, score)

| Case | csh | py | Δ | speedup | score |
|------|----:|---:|--:|--------:|:------|
| ✓ RS2_SLC_Hawaii | 175s | 110s | +65s | 1.59× | 6/0 |
| ✓ NISAR_Ethiopia | 447s | 291s | +156s | 1.54× | 6/0 |
| ✓ ALOS_SLC_L1.1 | 423s | 302s | +121s | 1.40× | 6/0 |
| ✓ CSK_RAW_Hawaii | 841s | 666s | +175s | 1.26× | 6/0 |
| ✓ TSX_SLC_Hawaii | 739s | 603s | +136s | 1.23× | 6/0 |
| ✓ ALOS2_SCAN_SSAF | 8987s | 7354s | +1633s | 1.22× | 14/0 |
| ✓ ALOS_ERSDAC_L1.0 | 911s | 761s | +150s | 1.20× | 6/0 |
| ✓ ALOS_Baja_EQ | 1101s | 930s | +171s | 1.18× | 6/0 |
| ✓ CSK_SLC_Italy | 803s | 680s | +123s | 1.18× | 6/0 |
| ✓ S1_Ridgecrest_EQ | 9214s | 7875s | +1339s | 1.17× | 16/0 |
| ✓ ERS_Hector_EQ | 1287s | 1103s | +184s | 1.17× | 6/0 |
| ✓ ALOS4_Pinon | 1230s | 1078s | +152s | 1.14× | 6/0 |
| ✓ ENVI_Baja_EQ | 1740s | 1550s | +190s | 1.12× | 6/0 |
| ✓ ALOS2_Brazil | 935s | 833s | +102s | 1.12× | 6/0 |
| ✓ ALOS2_Japan_Fugi_left | 1346s | 1208s | +138s | 1.11× | 6/0 |
| ✓ ALOS_haiti | 1749s | 1582s | +167s | 1.11× | 7/0 |
| ✓ ENVI_Baja_EQ_SLC | 1407s | 1289s | +118s | 1.09× | 6/0 |
| ✓ S1A_SLC_TOPS_COVE | 5544s | 5100s | +444s | 1.09× | 10/0 |
| ✓ S1A_SLC_TOPS_LA | 6849s | 6414s | +435s | 1.07× | 10/0 |
| ✓ S1A_SLC_TOPS_Greece | 2995s | 2855s | +140s | 1.05× | 10/0 |
| ✓ S1_Larsen_C | 5031s | 4971s | +60s | 1.01× | 10/0 |

## Table 2 — Per-binary timing (single-pair cases only)

_Cases without profile (csh-side recipes or wiped mid-sweep): ALOS2_SCAN_SSAF_

| Case | total | dem2topo | resamp_py | xcorr_py | geocode | intf | pre_proc |
|------|------:|---------:|---------:|---------:|---------:|---------:|---------:|
| S1A_SLC_TOPS_LA | **8812s** | 4685s | - | - | - | 72s | 638s |
| S1A_SLC_TOPS_COVE | **7215s** | 3596s | - | - | - | 67s | 503s |
| S1_Larsen_C | **7010s** | 3486s | - | - | - | 66s | 670s |
| S1A_SLC_TOPS_Greece | **5411s** | 5508s | - | - | - | 112s | 575s |
| S1_Ridgecrest_EQ | **4391s** | 3980s | - | - | - | 84s | 583s |
| ALOS_haiti | **1581s** | 844s | 50s | 18s | 75s | 54s | 12s |
| ENVI_Baja_EQ | **1544s** | 960s | 52s | 19s | 174s | 29s | 7s |
| ENVI_Baja_EQ_SLC | **1287s** | 1024s | 25s | 20s | 104s | 17s | 27s |
| ALOS2_Japan_Fugi_left | **1208s** | 838s | 104s | 30s | 47s | 38s | 43s |
| ERS_Hector_EQ | **1101s** | 719s | 27s | 19s | 112s | 20s | 6s |
| ALOS4_Pinon | **1074s** | 822s | 40s | 17s | 72s | 22s | 15s |
| ALOS_Baja_EQ | **928s** | 316s | 50s | 24s | 76s | 56s | 55s |
| ALOS2_Brazil | **832s** | 639s | 33s | 16s | 57s | 18s | 12s |
| ALOS_ERSDAC_L1.0 | **760s** | 398s | 25s | 21s | 88s | 17s | 6s |
| CSK_SLC_Italy | **679s** | 402s | 75s | 30s | 35s | 41s | 31s |
| CSK_RAW_Hawaii | **665s** | 91s | 80s | 58s | 23s | 38s | 20s |
| TSX_SLC_Hawaii | **602s** | 312s | 82s | 27s | 54s | 38s | 20s |
| ALOS_SLC_L1.1 | **301s** | 105s | 31s | 17s | 50s | 15s | 20s |
| NISAR_Ethiopia | **288s** | 25s | 7s | 36s | 45s | 7s | - |
| RS2_SLC_Hawaii | **110s** | 58s | 4s | 23s | 12s | 4s | 1s |

## Table 3 — Aggregate cost by stage (across 20 profiled cases)

| Stage | Total | % of pipeline | Class |
|-------|------:|--------------:|-------|
| dem2topo_ra | 28807s | 77.2% | gmt-wrapper |
| pre_proc | 3244s | 8.7% | C bin |
| merge_unwrap_geocode_tops | 2232s | 6.0% | ? |
| geocode | 1022s | 2.7% | gmt-subprocess |
| intf | 814s | 2.2% | C bin |
| resamp_py | 686s | 1.8% | Numba py |
| xcorr_py | 374s | 1.0% | scipy.fft py |
| snaphu | 133s | 0.4% | C bin |
| fitoffset_ra | 1s | 0.0% | gmt-subprocess |

## Table 4 — Failures (cases not all-SUCCESS)

_All cases all-SUCCESS._

---

_Snapshot generated: 2026-06-13T04-50-43Z_  
_Source: sweep.log_  
_Tool: gmtsar/python/tools/perf_snapshot.py_
