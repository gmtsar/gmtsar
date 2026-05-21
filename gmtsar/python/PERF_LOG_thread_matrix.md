# NUMBA Thread Scaling Matrix — pyGMTSAR v2.0

Per-case py-only timings at `NUMBA_NUM_THREADS=N XCORR_PY_WORKERS=N` for
`N ∈ {1, 2, 4, 8}`. Used to drive next-phase optimization decisions and
to populate the README/slides performance section.

Hardware reference (captured per sweep in `work/perf_<ts>.txt`):
- 48-core Intel Xeon, 1 TB RAM
- NFS-attached work dir
- GMT 6.5.0, Python 3.12.10, Numba 0.59.1
- Branch: `master` at the recorded commit hash.

Methodology:
- Each batch: 3 cases × 4 NUMBA values × `SWEEP_FORCE=py` (keep tarball-extracted input).
- csh oracle reused from prior runs (immutable reference).
- py time = sum of `phase_profile_py.json::total_sec`; comparison `score = S/F` from `work/results/<case>.json`.

Notes for readers:
- **Per-case wall time is essentially FLAT across NUMBA={1,...,8} on these cases.**
  Numba kernels DO scale 4-7× when isolated, but their share of binary runtime is
  small. GMT subprocess steps (dem2topo/geocode) dominate and don't scale.
- Throughput wins come from `MAX_PARALLEL` (multiple cases concurrent), not per-case
  thread count.
- Bit-parity preserved at all NUMBA settings (all rows below: `6/0`).

---

## Batch 1 — 2026-05-21, commit 8844ad6 (parallel Numba kernels merged)

| Case             | csh   | N=1  | N=2  | N=4  | N=8  | best (N=) | score |
|------------------|-------|------|------|------|------|-----------|-------|
| RS2_SLC_Hawaii    | 178 s |  94 s| 101 s|  95 s|  94 s| 1.89× (8) | 6/0 ✓ |
| NISAR_Ethiopia    | 459 s | 282 s| 288 s| 278 s| 279 s| 1.65× (4) | 6/0 ✓ |
| ALOS_SLC_L1.1     | 449 s | 393 s| 390 s| 391 s| 387 s| 1.16× (8) | 6/0 ✓ |

Sweep wall times:
- N=1 (MAX_PARALLEL=3): 565 s for 3 cases
- N=2 (MAX_PARALLEL=3): 560 s
- N=4 (MAX_PARALLEL=2): 562 s
- N=8 (MAX_PARALLEL=2): 558 s (from earlier dedicated sweep bwbr2icnu)

`MAX_PARALLEL=3` throughput vs sequential N=8: 565 s vs (94+279+387) = 760 s → **1.35× throughput**.

