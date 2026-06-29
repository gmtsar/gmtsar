# Perf snapshot — full, 2026-06-18T16-15-03Z

**Commit:** `181dc82` (dirty)  
**Config:** `NUMBA_NUM_THREADS=(not constrained) XCORR_PY_WORKERS=(not constrained) OMP_NUM_THREADS=(not constrained) MKL_NUM_THREADS=(not constrained) OPENBLAS_NUM_THREADS=(not constrained) BLIS_NUM_THREADS=(not constrained) VECLIB_MAXIMUM_THREADS=(not constrained) NUMEXPR_NUM_THREADS=(not constrained) MAX_PARALLEL=(not constrained) SWEEP_FORCE=py`  
**Hardware:** AMD EPYC 7F72 24-Core Processor, 48 cores, nfs workdir (theo2)  
**Software:** GMT 6.4.0, Python 3.11.0  
**Sweep wall:** 0h 2m (124s)  

**Coverage:** 21 cases with scorecards. **17 pass / 4 fail**.

---

## Table 1 — Per-case (csh vs py, score)

| Case | csh | py | Δ | speedup | score |
|------|----:|---:|--:|--------:|:------|
| ✓ RS2_SLC_Hawaii | 182s | 92s | +90s | 1.98× | 6/0 |
| ✓ NISAR_Ethiopia | 454s | 293s | +161s | 1.55× | 6/0 |
| ✓ ALOS_SLC_L1.1 | 431s | 318s | +113s | 1.36× | 6/0 |
| ✓ CSK_RAW_Hawaii | 726s | 618s | +108s | 1.17× | 6/0 |
| ✗ S1_Ridgecrest_EQ | 9288s | 7935s | +1353s | 1.17× | 11/5 |
| ✓ ALOS2_SCAN_SSAF | 8929s | 7774s | +1155s | 1.15× | 14/0 |
| ✓ TSX_SLC_Hawaii | 782s | 682s | +100s | 1.15× | 6/0 |
| ✓ CSK_SLC_Italy | 791s | 708s | +83s | 1.12× | 6/0 |
| ✓ ALOS_ERSDAC_L1.0 | 904s | 821s | +83s | 1.10× | 6/0 |
| ✓ ENVI_Baja_EQ | 1735s | 1593s | +142s | 1.09× | 6/0 |
| ✓ ALOS2_Japan_Fugi_left | 1383s | 1290s | +93s | 1.07× | 6/0 |
| ✗ ALOS_haiti | 1713s | 1619s | +94s | 1.06× | 6/1 |
| ✓ ALOS4_Pinon | 1209s | 1147s | +62s | 1.05× | 6/0 |
| ✗ S1A_SLC_TOPS_LA | 6677s | 6394s | +283s | 1.04× | 8/2 |
| ✓ ENVI_Baja_EQ_SLC | 1427s | 1396s | +31s | 1.02× | 6/0 |
| ✓ ERS_Hector_EQ | 1212s | 1193s | +19s | 1.02× | 6/0 |
| ✓ ALOS2_Brazil | 944s | 933s | +11s | 1.01× | 6/0 |
| ✓ ALOS_Baja_EQ | 1046s | 1035s | +11s | 1.01× | 6/0 |
| ✗ S1A_SLC_TOPS_Greece | 3008s | 3022s | -14s | 1.00× | 7/3 |
| ✓ S1_Larsen_C | 4940s | 5043s | -103s | 0.98× | 10/0 |
| ✓ S1A_SLC_TOPS_COVE | 5521s | 6021s | -500s | 0.92× | 10/0 |

## Table 2 — Per-binary timing (single-pair cases only)

_Cases without profile (csh-side recipes or wiped mid-sweep): ALOS2_SCAN_SSAF_

| Case | total | dem2topo | resamp_py | xcorr_py | geocode | intf | pre_proc |
|------|------:|---------:|---------:|---------:|---------:|---------:|---------:|
| S1A_SLC_TOPS_LA | **8824s** | 4780s | - | - | - | 69s | 529s |
| S1A_SLC_TOPS_COVE | **8456s** | 4482s | - | - | - | 67s | 498s |
| S1_Larsen_C | **7108s** | 3633s | - | - | - | 71s | 588s |
| S1A_SLC_TOPS_Greece | **5642s** | 5894s | - | - | - | 69s | 582s |
| S1_Ridgecrest_EQ | **3870s** | 3657s | - | - | - | 69s | 536s |
| ALOS_haiti | **1616s** | 871s | 49s | 27s | 81s | 53s | 13s |
| ENVI_Baja_EQ | **1590s** | 997s | 50s | 20s | 167s | 29s | 5s |
| ENVI_Baja_EQ_SLC | **1396s** | 1121s | 25s | 20s | 109s | 17s | 21s |
| ALOS2_Japan_Fugi_left | **1290s** | 893s | 101s | 30s | 73s | 37s | 48s |
| ERS_Hector_EQ | **1192s** | 802s | 27s | 19s | 117s | 18s | 3s |
| ALOS4_Pinon | **1145s** | 872s | 38s | 17s | 74s | 22s | 23s |
| ALOS_Baja_EQ | **1029s** | 404s | 50s | 23s | 80s | 56s | 60s |
| ALOS2_Brazil | **932s** | 697s | 34s | 16s | 68s | 28s | 12s |
| ALOS_ERSDAC_L1.0 | **821s** | 437s | 25s | 27s | 90s | 17s | 6s |
| CSK_SLC_Italy | **707s** | 442s | 75s | 31s | 41s | 39s | 27s |
| TSX_SLC_Hawaii | **680s** | 341s | 83s | 28s | 77s | 38s | 37s |
| CSK_RAW_Hawaii | **616s** | 77s | 79s | 55s | 27s | 35s | 20s |
| ALOS_SLC_L1.1 | **317s** | 118s | 29s | 18s | 53s | 15s | 20s |
| NISAR_Ethiopia | **289s** | 28s | 5s | 36s | 45s | 6s | - |
| RS2_SLC_Hawaii | **92s** | 38s | 4s | 23s | 13s | 4s | 1s |

## Table 3 — Aggregate cost by stage (across 20 profiled cases)

| Stage | Total | % of pipeline | Class |
|-------|------:|--------------:|-------|
| dem2topo_ra | 30585s | 78.8% | gmt-wrapper |
| pre_proc | 3030s | 7.8% | C bin |
| merge_unwrap_geocode_tops | 2170s | 5.6% | ? |
| geocode | 1114s | 2.9% | gmt-subprocess |
| intf | 760s | 2.0% | C bin |
| resamp_py | 674s | 1.7% | Numba py |
| xcorr_py | 390s | 1.0% | scipy.fft py |
| snaphu | 111s | 0.3% | C bin |
| fitoffset_ra | 1s | 0.0% | gmt-subprocess |

## Table 4 — Failures (cases not all-SUCCESS)

### ALOS_haiti — score 6/1, py=1619s

| File | Status | Reason |
|------|--------|--------|
| corr_ll.png | ✓ SUCCESS | — |
| display_amp_ll.png | ✓ SUCCESS | — |
| phasefilt_mask_ll.png | ✗ FAIL | — |
| corr_ll.grd | ✓ SUCCESS | — |
| phasefilt.grd | ✓ SUCCESS | — |
| filtcorr.grd | ✓ SUCCESS | — |
| los_ll.grd | ✓ SUCCESS | — |

### S1A_SLC_TOPS_Greece — score 7/3, py=3022s

| File | Status | Reason |
|------|--------|--------|
| corr_ll.png | ✗ FAIL | — |
| phasefilt_mask_ll.png | ✗ FAIL | — |
| corr_ll.grd | ✗ FAIL | — |
| phasefilt.grd | ✓ SUCCESS | — |
| phasefilt.grd | ✓ SUCCESS | — |
| phasefilt.grd | ✓ SUCCESS | — |
| phasefilt.grd | ✓ SUCCESS | — |
| filtcorr.grd | ✓ SUCCESS | — |
| filtcorr.grd | ✓ SUCCESS | — |
| filtcorr.grd | ✓ SUCCESS | — |

### S1A_SLC_TOPS_LA — score 8/2, py=6394s

| File | Status | Reason |
|------|--------|--------|
| corr_ll.png | ✗ FAIL | — |
| phasefilt_mask_ll.png | ✗ FAIL | — |
| corr_ll.grd | ✓ SUCCESS | — |
| phasefilt.grd | ✓ SUCCESS | — |
| phasefilt.grd | ✓ SUCCESS | — |
| phasefilt.grd | ✓ SUCCESS | — |
| phasefilt.grd | ✓ SUCCESS | — |
| filtcorr.grd | ✓ SUCCESS | — |
| filtcorr.grd | ✓ SUCCESS | — |
| filtcorr.grd | ✓ SUCCESS | — |

### S1_Ridgecrest_EQ — score 11/5, py=7935s

| File | Status | Reason |
|------|--------|--------|
| corr_ll.png | ✗ FAIL | — |
| corr_ll.png | ✓ SUCCESS | — |
| display_amp_ll.png | ✗ FAIL | — |
| phasefilt_mask_ll.png | ✗ FAIL | — |
| phasefilt_mask_ll.png | ✓ SUCCESS | — |
| corr_ll.grd | ✗ FAIL | — |
| corr_ll.grd | ✓ SUCCESS | — |
| phasefilt.grd | ✓ SUCCESS | — |
| phasefilt.grd | ✓ SUCCESS | — |
| phasefilt.grd | ✓ SUCCESS | — |
| phasefilt.grd | ✗ FAIL | — |
| phasefilt.grd | ✓ SUCCESS | — |
| filtcorr.grd | ✓ SUCCESS | — |
| filtcorr.grd | ✓ SUCCESS | — |
| filtcorr.grd | ✓ SUCCESS | — |
| filtcorr.grd | ✓ SUCCESS | — |

---

_Snapshot generated: 2026-06-18T16-15-03Z_  
_Source: sweep.log_  
_Tool: gmtsar/python/tools/perf_snapshot.py_
