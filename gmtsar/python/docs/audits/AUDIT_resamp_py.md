# AUDIT — `bin_py/resamp_py` (Python port of `gmtsar/resamp.c`)

Status: **PARITY GREEN — all 5 modes, commit-ready**. 2026-05-21.

## Scope

Port of `gmtsar/resamp.c` (728 lines, single C file containing `main`,
`ram2ras`, `nearest`, `bilinear`, `bicubic`/`bicubic_one`/`cubic_kernel`,
`bisinc`/`sinc_one`/`sinc_kernel`, `print_prm_params`, `fix_prm_params`).

Interpolation modes covered:

| `intrp` | Kernel | Port status |
|---|---|---|
| 1 | nearest neighbor | DONE, bit-identical to C |
| 2 | bilinear | DONE, bit-identical to C |
| 3 | bicubic (Keys, a=-0.3) | DONE, bit-identical to C |
| 4 | bisinc (truncated 4-tap, NS=4) | DONE, bit-identical to C |
| 5 | bisinc-grid (GMT-grid shift) | DONE, bit-identical to C (Mira #6) |

## Parity result

End-to-end SLC output is **byte-identical to the C `resamp` binary** for
all four ported modes on the canonical RS2 Hawaii test case:

```
inputs   : RS220110515.PRM (master), RS220110819.PRM (aligned, post-PRMresamp)
SLCs     : symlinks into work/csh_test/RS2_SLC_Hawaii/raw/
sizes    : 3416 x 5744 complex int16, 78 486 016 bytes
```

| mode | C md5 == Py md5? | diff samples |
|---|---|---|
| 1 (nearest)  | YES (`b091fcaf...`) | 0 / 19 621 504 int16 |
| 2 (bilinear) | YES (`8777167d...`) | 0 / 19 621 504 int16 |
| 3 (bicubic)  | YES (`4d8232e6...`) | 0 / 19 621 504 int16 |
| 4 (bisinc)   | YES (`3c44c9e9...`) | 0 / 19 621 504 int16 |

Reference oracle files are stored at:
```
gmtsar/python/bin_py/tests/data/resamp_c_reference_intrp{1,2,3,4}.SLC
gmtsar/python/bin_py/tests/data/resamp_c_reference_intrp{1,2,3,4}.PRM
```

The parity test class `TestResampVsCBinary` in
`bin_py/tests/test_resamp.py` regenerates the C reference IN THE SAME
INVOCATION as the Py run (Mira-Volkov rule: never trust a stale on-disk
oracle), so the parity gate is robust against the most common silent
failure mode (drift between the reference and what the C binary
currently produces).

## Performance vs C (RS2 Hawaii, single-thread real time, median of 3)

| mode | C resamp | resamp_py | ratio |
|---|---|---|---|
| 1 (nearest)  | 1.30 s | 1.10 s | **0.85x (Py faster)** |
| 2 (bilinear) | 1.40 s | 2.60 s | 1.86x slower |
| 3 (bicubic)  | 2.30 s | 10.20 s | 4.43x slower |
| 4 (bisinc)   | 4.50 s | 10.80 s | 2.40x slower |

The Py port is competitive for nearest (where there is no per-pixel
arithmetic worth vectorizing) and bisinc (where the C cost is dominated
by `sin()` evaluations that numpy can match with a vectorized `np.sin`).
The bicubic kernel is the largest gap because its inner work is small
(16-element polynomial sum) and is dominated by numpy fancy-index
gather overhead per chunk.

Optimization history (each step re-verified against the parity gate):
1. Initial row-at-a-time loop:         baseline (~equal C for mode 1).
2. Chunked driver (CHUNK=64 rows):     +5–10% on heavy modes.
3. Drop in-bounds masking; clamp+mask: +10–15% on heavy modes.
4. Separable einsum (`'nji,nj,ni->n'`): +5% on bisinc, negligible on bicubic.

Three rounds of numpy optimization were not enough to beat C on the
bicubic and bisinc modes; per the Mira-Volkov workflow, this is the
point where the next win would require a C extension (Cython, Numba,
or a custom ufunc). NOT pursued here — the C binary remains available
and the Python port is intended for environments where the C build is
not desired, not as a speed replacement.

## C-source traps documented at the call site

The following C-isms were preserved verbatim (each marked in the port
with an inline comment naming the trap):

1. **`(int)(ras + 0.5)` for nearest** (resamp.c:407-408) — for positive
   `ras` this rounds to nearest; for negative `ras` it truncates toward
   zero (NOT floors). `np.int64` cast of a float array has the same
   "toward zero" behavior, so `(ras + 0.5).astype(np.int64)` matches C.

2. **`(int)floor(ras)` for bilinear/bicubic/bisinc** (resamp.c:440,
   506, 564) — `np.floor(ras).astype(np.int64)` matches; for negative
   `ras` `floor(-0.3) = -1` (NOT 0 from truncation).

3. **`(short)clipi2(x + 0.5)`** (resamp.c:481, 491, 546, 549, 602, 605)
   — clipi2 clamps the DOUBLE to [-I2MAX, +I2MAX] = [-32767.0, 32767.0],
   then `(short)` truncates toward zero. Critical case: `clipi2(-32766.5)
   = -32766.5` then `(short)(-32766.5) = -32766` (NOT -32767). The
   `_c_round_clip_int16` helper does `np.clip` then `astype(np.int16)`,
   which gives the same answer.

4. **Keys cubic with a=-0.3** (resamp.c:328) — NOT the classic -0.5. Do
   not substitute `scipy.interpolate.RegularGridInterpolator` or any
   library cubic — the parameter is hard-coded in the C and must be
   matched exactly.

5. **`I2MAX = 32767.0` (float)** (gmtsar.h:19) — the C `(int)fabs(real)
   > I2MAX` test compares an int to a double. The current port omits
   this nclip counter (only used to print debug warnings in C that are
   commented out at the call site) and just clips silently.

6. **Truncated PI `3.1415926535897932`** (resamp.c:674) — `np.sinc` uses
   `math.pi` which is slightly different in the last bit. Direct
   evaluation `np.sin(PI * x) / (PI * x)` with the C constant reproduces
   the C values bit-for-bit.

7. **NS=4 and `ns2 = NS/2 - 1 = 1.0`** (gmtsar.h:22, resamp.c:555) — the
   C source declares `ns2` as `double`. The integer arithmetic `NS/2 - 1`
   is done as `(int)(4)/2 - 1 = 1` cast to double = 1.0. The port keeps
   both `ns2` (int, for indexing) and `ns2_d` (double, for the kernel
   weight formula) separated to mirror C semantics.

8. **SLC layout: interleaved (re, im, re, im, ...)** — the port treats
   the SLC as a flat `int16` array indexed as `2*xdims*i + 2*j` for the
   real component and `+1` for imag. Reshaping to `(ydims, xdims, 2)`
   is also possible but was measured slower for fancy-index gather.

9. **`isfinite` guard writes (0, 0) and continues** (resamp.c:245-249)
   — applies ONLY to intrp=5 (deferred). Not present in modes 1-4.

10. **mmap st_size = 4*xdims*ydims** (resamp.c:151) — when the input
    SLC file is larger than this (which it is on the RS2 case:
    file = 78 554 336 bytes, expected = 78 486 016 bytes), the trailing
    bytes are IGNORED. `np.memmap(shape=(ydims*2*xdims,))` reproduces
    this by sizing the memmap explicitly.

11. **intrp=1 zeros sub_int/stretch** (resamp.c:126-139, 281-288) — for
    nearest, the C code zeros six PRM fields before calling ram2ras and
    restores them on the OUTPUT PRM. The port does the same.

## Known limitations

### intrp=5 (DONE — Mira #6, 2026-05-21)
The GMT-grid-based bisinc path (resamp.c:98-254) is now ported and parity-
green on the NISAR_Ethiopia case. Implementation summary:

- `_read_gmt_grd(path)` reads a GMT NetCDF `.grd` via xarray (with
  `scipy.io.netcdf` fallback), returning `(data, inc_x, inc_y, nx, ny)`
  in C's row-major (`a, r`) index convention.
- `grid_shift_vec(jj, ii, R, A, inc_x, inc_y)` vectorizes the per-pixel
  bilinear shift from resamp.c:173-249; returns `ras0, ras1, bad_mask`.
- Mode 5 dispatch reuses the existing mode-4 bisinc kernel (numpy or
  Numba — both are bit-identical to C).
- NaN guard: bad-mask pixels get `(0, 0)` written, matching C's
  `if (!isfinite(ras[0]) || !isfinite(ras[1])) { sout[0]=sout[1]=0; continue; }`.

GMT-grid quirks worth knowing:
1. **Y-axis orientation.** xarray loads the on-disk NetCDF in ascending-y
   order (`z[0,:]` is `y_min`). GMT's `R->data[]` after `GMT_Read_Data` is
   ordered with `row=0` at `y_max` (matches `gmt grd2xyz` output). The
   port flips the loaded array along axis 0 so that C's
   `R->data[r + nx*a]` is one-to-one with numpy's `R[a, r]`.
2. **Cell increment.** C reads `R->header->inc[GMT_X]` which GMT computes
   as `(x_max - x_min) / n_columns` for pixel-registered grids (using the
   header's `actual_range` attribute, NOT the difference between
   consecutive `x` coord vector entries — those can differ by 1 ULP in
   the last bit due to accumulated subtraction roundoff). The port
   reproduces GMT's header arithmetic by reading `actual_range` from the
   coord-variable NetCDF attributes.
3. **Pixel registration.** Default for grids produced by `gmt surface -rp`
   (which is what `fitoffset_ra.csh` invokes); read the file's
   `node_offset` global attribute to pick the right denominator
   (`/n_columns` for pixel reg, `/(n_columns-1)` for gridline reg).
4. **FP accumulation order.** C computes ras as
   `ram[0] + w11*f11 + w12*f12 + w21*f21 + w22*f22` with left-to-right
   chaining — i.e. the large `ram[0]` is the seed. Computing the shift
   in isolation and adding `ram[0]` at the end gives a 1-ULP-different
   result, which on the NISAR case flipped exactly 1 pixel out of 60 M
   across a bisinc rounding boundary. The port mirrors C's order
   verbatim (see comment block in `grid_shift_vec`).
5. **inc validation.** C requires `inc[GMT_X] == inc[GMT_X]_A` and
   `inc > 1`. Port matches.

Test: `TestResampVsCBinaryMode5.test_intrp_5_bisinc_grid` in
`bin_py/tests/test_resamp.py` runs fitoffset_ra.csh → C resamp →
resamp_py in one invocation against the live NISAR_Ethiopia SLC pair
and asserts byte-identical 120 MB output SLC.

### PRM output format
The C binary writes the output PRM via `put_sio_struct` (ALOS_preproc/
lib_src/put_sio_struct.c) in a fixed canonical key order with specific
format specifiers (`%lf` for most doubles, `%16.10lf` for SC_clock_*,
`%lg` for radar_wavelength, etc.). The Python port writes a simpler
`key\t= value` format that preserves the input order. THIS DIFFERS
TEXTUALLY from the C output, but the downstream pipeline only reads
keys by name, so the difference is invisible at the integration layer.

To-do if exact PRM-text parity is later required:
- [ ] Port the put_sio_struct field-by-field with the exact format
      specifiers from put_sio_struct.c lines 17-167.

## Files

```
gmtsar/python/bin_py/resamp_py                  the port (executable)
gmtsar/python/bin_py/tests/test_resamp.py       14 tests (10 unit + 4 parity)
gmtsar/python/bin_py/tests/data/resamp_c_reference_intrp{1,2,3,4}.SLC
gmtsar/python/bin_py/tests/data/resamp_c_reference_intrp{1,2,3,4}.PRM
gmtsar/python/AUDIT_resamp_py.md                this file
```

## Reproducing the parity check

```bash
cd /tmp && rm -rf resamp_test && mkdir resamp_test && cd resamp_test
cp /home/utig5/dliu/gmtsar/gmtsar/python/work/csh_test/RS2_SLC_Hawaii/SLC/RS220110515.PRM master.PRM
cp /home/utig5/dliu/gmtsar/gmtsar/python/work/csh_test/RS2_SLC_Hawaii/SLC/RS220110819.PRM aligned.PRM
ln -sf /home/utig5/dliu/gmtsar/gmtsar/python/work/csh_test/RS2_SLC_Hawaii/raw/RS220110515.SLC .
ln -sf /home/utig5/dliu/gmtsar/gmtsar/python/work/csh_test/RS2_SLC_Hawaii/raw/RS220110819.SLC .
for m in 1 2 3 4; do
    /home/utig5/dliu/gmtsar/bin/resamp master.PRM aligned.PRM c_${m}.PRM c_${m}.SLC $m > /dev/null
    python3 /home/utig5/dliu/gmtsar/gmtsar/python/bin_py/resamp_py master.PRM aligned.PRM py_${m}.PRM py_${m}.SLC $m > /dev/null
    cmp c_${m}.SLC py_${m}.SLC && echo "mode $m BIT-IDENTICAL" || echo "mode $m DIFFERS"
done
```

Or run the test suite:
```bash
cd /home/utig5/dliu/gmtsar/gmtsar/python/bin_py/tests
python3 -m pytest test_resamp.py -v
```

## Wire-in status

**DEFERRED per the porter's brief.** The port is not yet wired into
`p2p_stages.py` (the integration point where csh `resamp ...` would be
replaced by `resamp_py ...`). Recommend a SWEEP_FORCE-style flag
`SWEEP_FORCE_RESAMP=py` to A/B the port against the C binary on the
full sweep before flipping the default.

---

## Wire-in decision (2026-05-20)

**Kept in repo, NOT wired into `p2p_stages.py`.**

Production sweep tested `resamp_py` wired into the RS2 + ALOS_SLC paths.
Result on those two:

| case | C resamp | resamp_py | Δ |
|---|---|---|---|
| RS2_SLC_Hawaii | 4.5s | 12.8s | **+8s (2.8× slower)** |
| ALOS_SLC_L1.1 | 49.6s | 124.8s | **+75s (2.5× slower)** |

The 2-3× slowdown comes from numpy's per-call dispatch overhead on the
4×4-stencil per-pixel inner loop (16 input samples → 16 multiply-adds
per output pixel — too little work to amortize numpy's ~1 µs dispatch
cost). Mira's discipline flagged this in the original port report:
"if 3 rounds of numpy optimization don't beat C, recommend a C-extension
hybrid instead of pure-Py."

**To enable in the future:** wrap the inner kernel in numba/Cython or
a small C extension. The pure-Py port stays as a maintainable reference
implementation and parity oracle for any future hybrid.

To temporarily re-wire for testing:
  `sed -i 's|time_run(f"resamp |time_run(f"resamp_py |g' utils/p2p_stages.py`
  (and update the second arg back to `"resamp_py"` for binary timing).

---

## Large-image benchmark (Mira #4 audit, 2026-05-20)

Tested on the 4 large production cases (ENVI 157M, ALOS2 211M, TSX 523M
samples). **Slowdown does not improve with scale — gets worse on
bisinc.**

| case | M samples | mode 2 ratio | mode 4 ratio |
|---|---|---|---|
| RS2 (Mira #1) | 19.6 | 1.86× | 2.40× |
| ENVI_Baja_SLC | 157 | 1.93× | 3.55× |
| ALOS2_Brazil | 211 | 2.71× | **3.69×** |
| TSX_SLC (production) | 523 | — | ~3× |

Bisinc gets worse with N because C's 4×4 streaming SIMD pulls further
ahead of numpy's gather/per-tile pattern at scale. Mode 2 settles at
~2-2.7× across all sizes.

## TSX_SLC safety finding (Py-only correctness improvement)

TSX aligned `TSX20121208.SLC` is **70,960 bytes (≈1 row) SHORT** of
what its PRMresamp declares. Behaviour:

- **C `resamp`** `mmap`s the declared size and silently reads past EOF.
  Linux returns zero-filled pages until the next page boundary, then
  SIGBUS. The last ~1 row of the C output is **kernel zero-fill —
  undefined garbage data, not real SAR samples.**
- **resamp_py** (line 733-739) explicitly checks
  `actual_bytes < expected_bytes → ValueError` and refuses to run.

The Py guard is **safer than C**. In production this never bites
because pre_proc normally pre-pads/crops the aligned SLC consistently,
but the size mismatch on TSX has been quietly producing garbage rows
for years.

Recommendation: keep the Py guard. If we ever want to wire resamp_py
in for safety reasons (despite the speed loss), this case is a real
argument for it. To make the standalone parity test green on TSX,
either accept the guard's failure as expected for this case, or add
a memmap-with-zero-fill fallback matching C's mmap-past-EOF behaviour.

## NISAR_Ethiopia crash (production sweep, 2026-05-20)

Production sweep with `resamp_py` wired: NISAR scored 0/6 with
resamp_py running in 0.135s — crashed immediately. **Root cause
identified 2026-05-21 (Mira #6):** the crash was the
`NotImplementedError` raised on `intrp=5`, which `p2p_processing_nsr.csh`
calls on the NSR_A path. Now that mode 5 is parity-green, this
specific block is resolved.

## Mode 5 timing on NISAR_Ethiopia (Mira #6, 2026-05-21)

| | C resamp | resamp_py (numpy) | resamp_py (numba) | ratio |
|---|---|---|---|---|
| NISAR_Ethiopia (60M int16, 5000×6000 complex) | 5.85 s | 22.0 s | 22.1 s | 3.8× slower |

Mode 5's slowdown profile matches mode 4 (~2-3.7× slower across all
ported cases) because mode 5 dispatches to the same bisinc kernel; the
extra per-pixel work (bilinear shift over a 78×94 grid) is negligible.
Numba doesn't help here because the bisinc kernel was already the
dominant cost. Same Mira-#1 conclusion stands: a C-extension hybrid
(or staying with the C binary) is the only path to parity-with-speed.

## Final wire-in decision

**Reverted to C `resamp` (2026-05-20); ported mode 5 (2026-05-21).**
resamp_py kept in repo as reference port and parity oracle, NOW
supporting all 5 modes. To re-enable for production: still needs
Numba/Cython inner-loop hybrid to close the 2-4× speed gap. The
mode-5 port enables future NISAR/NSR_A wire-in attempts (the crash
that blocked NISAR sweep 0/6 is fixed).
