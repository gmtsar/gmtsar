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

1. **Phase A — Stub** (this commit): Python file with the freq-domain
   algorithm laid out, correct output format, no GPU. Untested against
   real data.
2. **Phase B — Correctness gate**: run against RS2_SLC_Hawaii;
   `freq_xcorr.dat` from xcorr_py must produce alignment params
   (after passing through fitoffset.py) within 1 pixel of the C path.
3. **Phase C — Parallelism**: process patches across cores using
   `multiprocessing.Pool` or `joblib`.
4. **Phase D — GPU optional**: behind a `--device cuda` flag, use
   `cupy` or `torch` for the FFTs.

Speed targets, against the 115s xcorr time observed on RS2 (single
thread):
- Phase B (single-process numpy):       ≤ 150s (slower OK, baseline)
- Phase C (8-core multiprocessing):     ≤ 30s
- Phase D (single GPU):                 ≤ 10s
