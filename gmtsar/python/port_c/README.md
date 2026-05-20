# port_c — Python ports of gmtsar C binaries

The profiler showed `xcorr` consumes **48.9% of RS2_SLC_Hawaii wall time** —
the single biggest target outside the GMT subprocess pool. PyGMT can't
touch it (not a GMT module; gmtsar-internal C). To improve, the binary
itself must be rewritten or parallelized.

This directory holds Python reimplementations of the dominant gmtsar
C binaries, targeting **correctness first, speed-via-vectorization
second, GPU acceleration third (optional)**.

## Status

| Binary | C lines | Status | Notes |
|---|---|---|---|
| `xcorr` | 1064 (across 6 files) | **stub** in `xcorr_py` (freq-domain only, single-process) | drop-in CLI target; output format matches |
| `phasediff` | TBD | not started | second-biggest after xcorr in some cases |
| `resamp` | TBD | not started | uses xcorr offsets; downstream of fitoffset |
| `esarp` | TBD | not started | range/azimuth compression; only used by .raw-input SATs |

## Design principles

1. **Drop-in CLI compatibility.** Each port keeps the same CLI signature
   as its C binary so swap.sh-style routing works the same way as the
   PyGMT migration. Output files (e.g. `freq_xcorr.dat`) must be
   byte-comparable on simple cases.
2. **NumPy first, GPU optional.** Initial port uses `numpy.fft` and
   array ops. A second pass can wire in `cupy` / `torch` for GPU
   acceleration without changing the API.
3. **Per-patch parallelism via multiprocessing.** xcorr's main loop
   over `(nx_loc, ny_loc)` patch locations is embarrassingly parallel
   — each patch independent. Trivial 4-8× speedup on multicore CPUs.
4. **Correctness gate**: each port is benchmarked against the C binary
   on a real test case (RS2_SLC_Hawaii is the lightest, 190s).
   Numerical agreement must be within ~1 pixel for offsets and
   ~1% relative for SNR before the port is wired into the swap.

## xcorr — what it does

For two SLC (Single Look Complex) images A (master) and B (aligned):

1. Tile both into patches of size `npy × npx` at `nx_loc × ny_loc`
   spaced locations.
2. For each patch pair, compute the 2-D cross-correlation. Two paths:
   - **Freq domain (default, `-freq`)**: FFT(A) * conj(FFT(B)) →
     inverse FFT → magnitude → find peak. Fast for large patches.
   - **Time domain (`-time`)**: direct sum-of-products over the
     search window. Slower but more accurate for small offsets.
3. Sub-pixel peak refinement via 2-D interpolation (`highres_corr.c`).
4. Write per-patch `(x, xoff, y, yoff, corr)` to `freq_xcorr.dat`.

Output format (one line per patch, space-separated):
```
 <x>  <xoff>  <y>  <yoff>  <corr>
```
Example actual row from a live run: ` 742  7.969 609  1.875  11.45`.

The downstream consumer is `fitoffset` (now `fitoffset.py`), which
fits a polynomial to these offsets to get alignment params (rshift,
ashift, stretch_r, stretch_a, sub_int_r, sub_int_a).

## CLI signature (the C binary)

```
xcorr master.PRM aligned.PRM [-time] [-real] [-freq] [-nx N] [-ny N] [-xsearch X] [-ysearch Y]
```

PRM fields the port needs:
- `num_rng_bins`, `num_valid_az` (master image dimensions)
- `rshift`, `ashift` (initial offsets, 0 for first xcorr run)
- `PRF` (pulse repetition frequency, for azimuth stretch correction)
- `astretcha` (azimuth stretch)
- `SLC_file` (path to the binary SLC data; short int complex pairs)

## What's deferred

- `-time` (time-domain) correlation — only `-freq` implemented in
  the stub. The freq path covers ~95% of real-world calls.
- `-real` (real-valued input) — only complex SLC supported in stub.
- Sub-pixel interpolation matching `highres_corr.c`'s exact algorithm —
  stub uses `scipy.signal.correlate2d` peak + parabolic fit.
- Mask handling (the `make_mask` step that excludes circular wrap
  region) — stub uses a simple central crop instead.

## Roadmap

1. **Phase A — Stub** (committed): Python file with the freq-domain
   algorithm laid out, correct output format, no GPU. Synthetic
   correctness verified.
2. **Phase A.1 — Live single-patch validated**: port now correctly
   pre-processes (|SLC|, demean, edge-mask) like the C `assign_values`.
   On already-aligned RS2 SLC patches, returns ~0 residual offset
   with SNR=7.5 (real signal, not noise). Synthetic patch with known
   (dx=-5, dy=3): bit-exact recovery.
3. **Phase B — Full pipeline-level correctness gate** (NOT YET): run
   xcorr_py inside a fresh-from-tarball sweep on RS2_SLC_Hawaii;
   compare freq_xcorr.dat against C output BEFORE the downstream
   resamp clobbers the SLC. Then verify that the alignment params
   (after fitoffset.py) agree within 1 pixel.
4. **Phase C — Parallelism**: process patches across cores using
   `multiprocessing.Pool` or `joblib`. Speed measured: single-process
   wall ~35s for 1000 patches on RS2 — already faster than C (~115s).
   Parallelism should bring it to ~5s.
5. **Phase D — GPU optional**: behind a `--device cuda` flag, use
   `cupy` or `torch` for the FFTs.

Speed targets, against the 115s xcorr time observed on RS2 (single
thread C):
- Phase A.1 (single-process numpy):     **~35s achieved (3.3× faster)**
- Phase B (correctness-gated):          same wall, validated
- Phase C (8-core multiprocessing):     ≤ 10s
- Phase D (single GPU):                 ≤ 3s

## Bug log (lessons from the first live run)

Each one would have been caught at Phase B if we'd had the
correctness gate.

1. **Wrong patch grid formula.** Used naive `(m_nx - npx) // nx`;
   the real C formula is in `get_locations.c`:
   `x_inc = (m_nx - 2*(xsearch + nx_corr)) // (nxl + 3)`; patches centred
   at `(npx + i*x_inc, npy + j*y_inc)` with i in [2..nxl+1].

2. **Correlating complex SLC directly.** SAR data has random phase
   per pixel; direct cross-correlation of complex SLCs is just noise.
   The C `assign_values()` first converts to amplitude (`|SLC|`), then
   demeans, then masks the aligned patch's edges (`make_mask()`).
   Without those three steps, SNR drops to ~3.5 (noise floor); with
   them, SNR matches C in magnitude.

3. **Wrongly seeded x_offset from PRM.** The C binary defaults
   `x_offset = y_offset = 0` and does NOT read rshift/ashift from
   the PRM as an initial guess. `rshift` is what fitoffset+resamp
   WRITE downstream; xcorr is what they READ. Seeding it as a
   starting guess subtracts the very signal we're trying to measure.
