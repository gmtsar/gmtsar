# Perf snapshot — fast, 2026-07-13T06-31-10Z

**Commit:** `d26f9c4` (dirty)  
**Config:** `NUMBA_NUM_THREADS=(not constrained) XCORR_PY_WORKERS=(not constrained) OMP_NUM_THREADS=(not constrained) MKL_NUM_THREADS=(not constrained) OPENBLAS_NUM_THREADS=(not constrained) BLIS_NUM_THREADS=(not constrained) VECLIB_MAXIMUM_THREADS=(not constrained) NUMEXPR_NUM_THREADS=(not constrained) MAX_PARALLEL=2 SWEEP_FORCE=1`  
**Hardware:** AMD EPYC 7F72 24-Core Processor, 48 cores, 1007.6G RAM, nfs workdir (theo2)  
**Software:** GMT 6.4.0, Python 3.11.0  
**Sweep wall:** 0h 15m (933s)  

**Coverage:** 21 cases with scorecards. **19 pass / 2 fail**.

---

## Table 1 — Per-case (csh vs py, score)

| Case | csh | py | Δ | speedup | score |
|------|----:|---:|--:|--------:|:------|
| ✓ NISAR_Ethiopia | 431s | 152s | +279s | 2.84× | 6/0 |
| ✓ RS2_SLC_Hawaii | 198s | 95s | +103s | 2.08× | 6/0 |
| ✓ ALOS_SLC_L1.1 | 431s | 318s | +113s | 1.36× | 6/0 |
| ✓ TSX_SLC_Hawaii | 755s | 634s | +121s | 1.19× | 6/0 |
| ✓ CSK_RAW_Hawaii | 726s | 618s | +108s | 1.17× | 6/0 |
| ✗ S1_Ridgecrest_EQ | 9288s | 7935s | +1353s | 1.17× | 11/5 |
| ✓ ALOS2_SCAN_SSAF | 8929s | 7774s | +1155s | 1.15× | 14/0 |
| ✓ ALOS_ERSDAC_L1.0 | 904s | 821s | +83s | 1.10× | 6/0 |
| ✓ ENVI_Baja_EQ | 1735s | 1593s | +142s | 1.09× | 6/0 |
| ✓ ALOS2_Japan_Fugi_left | 1383s | 1290s | +93s | 1.07× | 6/0 |
| ✓ ALOS_Baja_EQ | 1046s | 992s | +54s | 1.05× | 6/0 |
| ✓ ALOS4_Pinon | 1209s | 1147s | +62s | 1.05× | 6/0 |
| ✓ S1A_SLC_TOPS_LA | 6668s | 6338s | +330s | 1.05× | 10/0 |
| ✓ CSK_SLC_Italy | 785s | 757s | +28s | 1.04× | 6/0 |
| ✓ ERS_Hector_EQ | 1212s | 1182s | +30s | 1.03× | 6/0 |
| ✓ ENVI_Baja_EQ_SLC | 1427s | 1396s | +31s | 1.02× | 6/0 |
| ✓ ALOS2_Brazil | 944s | 933s | +11s | 1.01× | 6/0 |
| ✓ S1A_SLC_TOPS_Greece | 3003s | 3010s | -7s | 1.00× | 10/0 |
| ✓ S1_Larsen_C | 4919s | 5033s | -114s | 0.98× | 10/0 |
| ✓ S1A_SLC_TOPS_COVE | 5486s | 6006s | -520s | 0.91× | 10/0 |
| ✗ ALOS_haiti | 1713s | 2158s | -445s | 0.79× | 0/7 |

## Table 2 — Per-binary timing (single-pair cases only)

_Cases without profile (csh-side recipes or wiped mid-sweep): ALOS2_SCAN_SSAF_

| Case | total | dem2topo | resamp_py | xcorr_py | geocode | intf | pre_proc |
|------|------:|---------:|---------:|---------:|---------:|---------:|---------:|
| S1A_SLC_TOPS_LA | **8746s** | 4748s | - | - | - | 68s | 524s |
| S1A_SLC_TOPS_COVE | **8433s** | 4470s | - | - | - | 68s | 500s |
| S1_Larsen_C | **7096s** | 3626s | - | - | - | 66s | 582s |
| S1A_SLC_TOPS_Greece | **5619s** | 5921s | - | - | - | 68s | 573s |
| S1_Ridgecrest_EQ | **3870s** | 3657s | - | - | - | 69s | 536s |
| ALOS_haiti | **2158s** | 882s | 51s | 22s | 62s | 51s | 12s |
| ENVI_Baja_EQ | **1590s** | 997s | 50s | 20s | 167s | 29s | 5s |
| ENVI_Baja_EQ_SLC | **1396s** | 1121s | 25s | 20s | 109s | 17s | 21s |
| ALOS_Baja_EQ | **1343s** | 399s | 49s | 22s | 74s | 52s | 38s |
| ALOS2_Japan_Fugi_left | **1290s** | 893s | 101s | 30s | 73s | 37s | 48s |
| ERS_Hector_EQ | **1181s** | 796s | 29s | 24s | 112s | 17s | 4s |
| ALOS4_Pinon | **1145s** | 872s | 38s | 17s | 74s | 22s | 23s |
| ALOS2_Brazil | **932s** | 697s | 34s | 16s | 68s | 28s | 12s |
| ALOS_ERSDAC_L1.0 | **821s** | 437s | 25s | 27s | 90s | 17s | 6s |
| CSK_SLC_Italy | **756s** | 434s | 75s | 34s | 40s | 36s | 85s |
| TSX_SLC_Hawaii | **634s** | 343s | 83s | 26s | 54s | 36s | 16s |
| CSK_RAW_Hawaii | **616s** | 77s | 79s | 55s | 27s | 35s | 20s |
| ALOS_SLC_L1.1 | **317s** | 118s | 29s | 18s | 53s | 15s | 20s |
| NISAR_Ethiopia | **150s** | 28s | 6s | 35s | 39s | 4s | - |
| RS2_SLC_Hawaii | **94s** | 38s | 4s | 22s | 16s | 3s | 1s |

## Table 3 — Aggregate cost by stage (across 20 profiled cases)

| Stage | Total | % of pipeline | Class |
|-------|------:|--------------:|-------|
| dem2topo_ra | 30556s | 77.7% | gmt-wrapper |
| pre_proc | 3026s | 7.7% | C bin |
| merge_unwrap_geocode_tops | 2170s | 5.5% | ? |
| geocode | 1060s | 2.7% | gmt-subprocess |
| intf | 738s | 1.9% | C bin |
| snaphu | 688s | 1.7% | C bin |
| resamp_py | 678s | 1.7% | Numba py |
| xcorr_py | 389s | 1.0% | scipy.fft py |
| fitoffset_ra | 1s | 0.0% | gmt-subprocess |

## Table 4 — Failures (cases not all-SUCCESS)

### ALOS_haiti — score 0/7, py=2158s

| File | Status | Reason |
|------|--------|--------|
| corr_ll.png | ✗ FAIL | — |
| display_amp_ll.png | ✗ FAIL | — |
| phasefilt_mask_ll.png | ✗ FAIL | — |
| corr_ll.grd | ✗ FAIL | — |
| phasefilt.grd | ✗ FAIL | — |
| filtcorr.grd | ✗ FAIL | — |
| los_ll.grd | ✗ FAIL | shape mismatch py=(2110, 2130) csh=(2140, 2080) (rel diff 2.3%) |

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

_Snapshot generated: 2026-07-13T06-31-10Z_  
_Source: sweep.log_  
_Tool: gmtsar/python/tools/perf_snapshot.py_
