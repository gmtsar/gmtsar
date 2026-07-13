#! /usr/bin/env python3
"""make_slc_nsr_py — Python port of preproc/NSR_preproc/src_slc/make_slc_nsr.c

Reads a NISAR L1 RSLC HDF5 product and writes GMTSAR-format .SLC / .PRM /
.LED files. This is a raw-format PREPROCESSOR (HDF5 parsing + Cfloat32 ->
Cint16 quantization + orbit-state-vector extraction) — it does NOT do any
SAR focusing math.

Ported line-for-line from make_slc_nsr.c (515 lines) plus the shared
helpers it calls transitively:
  - preproc/S1A_preproc/lib/xml.c        (cat_nums, str_date2JD, str2double,
                                           date2MJD, strasign)
  - gmtsar/sio_struct.c                  (null_sio_struct / put_sio_struct
                                           field list + exact fprintf format
                                           strings, incl. literal tab/space
                                           padding)
  - preproc/S1A_preproc/include/stateV.h (state_vector struct)
  - gmtsar/PRM.h                         (struct PRM layout)

Checkpoints (C1..C8):
  C1. get_range()            — region_cut "xl/xh/yl/yh" parser (atoi-like).
  C2. cat_nums / str_date2JD / date2MJD — HDF5 ISO-date-string -> day-of-year
      fraction, INCLUDING the C's ASCII round-trip (sprintf "%.12f" then
      re-parse) which truncates precision — replicated exactly, not skipped.
  C3. f32_to_i16_with_checks — Cfloat32 -> Cint16 saturating cast with
      isfinite guard (NaN/Inf -> 0, not clamped).
  C4. write_slc_hdf5         — bw_fac region rescale for frequency B,
      width/height read, xl/xh/yl/yh multiple-of-4 crop, per-row quantize
      + write.
  C5. pop_prm_hdf5           — derives every PRM field make_slc_nsr sets
      (near_range, clock_start/SC_clock_start via C2, prf, fs, lambda, ...).
  C6. pop_led_hdf5           — orbit state vectors (yr/jd/sec via C2 + ECEF
      pos/vel straight copy).
  C7. write_orb              — LED file writer (header line + per-vector
      line), exact printf format.
  C8. put_sio_struct (restricted to the field subset make_slc_nsr sets) —
      PRM file writer; format strings copied byte-for-byte (verified via
      `cat -A` against a fresh C run) including literal tab/space padding
      that differs per field.

KNOWN AUDITED SIMPLIFICATIONS (do NOT affect output bytes — verified against
a fresh C binary run on real NISAR data, see AUDIT note below):
  - nominalAcquisitionPRF and processedRangeBandwidth are read by the C
    binary into tmp_d but IMMEDIATELY DISCARDED (prm->pulsedur and
    prm->chirp_slope are hardcoded to 0.0 right after the read, with an
    inline C comment "this is wrong but not needed for SLC"). This port
    skips those two reads entirely rather than reading-then-discarding.
  - identification/zeroDopplerStartTime is read by the C binary into a
    scratch buffer that is never used again (dead code / no-op read in the
    C source). This port skips that read.
  - The C's `hdf5_read(&count, ..., 'n')` writes an 8-byte hsize_t into a
    4-byte `int*`, a latent stack-corruption bug that happens to be benign
    on this binary's stack layout (confirmed byte-identical across two
    independent runs of the real C binary, see bit-parity test). This port
    reads the dataset extent the correct/safe way (h5py .shape), which is
    numerically identical to the (accidentally-correct) C behavior on real
    data.
  - str_date2JD's C source reads str_date[14:19] (6 chars) for a fractional-
    seconds field that DOES NOT EXIST in the "seconds since
    YYYY-MM-DDTHH:MM:SS" units string NISAR actually emits (cat_nums output
    is only 14 digits long) — another latent out-of-bounds read that is
    reliably zero-filled on this stack layout (confirmed empirically). This
    port replicates the OBSERVED behavior: slicing past the end of the
    digit string yields an empty Python string, which this port's `_num()`
    maps to 0.0 — the SAME zero-fractional-seconds result the C binary
    produces. This is a documented, verified byte-for-byte match, not a
    guess.

Usage:
    make_slc_nsr_py.py h5file output_stem mode dfact [region_cut]

    mode:        <freq><type>, e.g. AHH, BHH  (freq='A'/'B', type=HDF5
                 dataset name under swaths/frequency<freq>/, e.g. "HH")
    dfact:       Cfloat32 -> Cint16 scale factor (SLC_factor)
    region_cut:  "xl/xh/yl/yh" (optional; default = full extent)

Output: <output_stem>.SLC  <output_stem>.PRM  <output_stem>.LED
"""
from __future__ import annotations

import math
import sys

import h5py
import numpy as np

C_SPEED = 299792458.0
INT16_MAX = 32767
INT16_MIN = -32768
EARTH_RA = 6378137.00      # equatorial_radius (make_slc_nsr.c:336)
EARTH_RC = 6356752.31      # polar_radius      (make_slc_nsr.c:337)
SC_IDENTITY_NSR = 14


# ---------------------------------------------------------------------------
# C1. get_range() — region_cut "xl/xh/yl/yh" parser
# ---------------------------------------------------------------------------

def _atoi(tok: str) -> int:
    """C atoi(): skip leading whitespace, optional sign, digits, stop at
    first non-digit; 0 if no digits found. (make_slc_nsr.c's get_range uses
    atoi on hand-split substrings; region_cut values are always clean
    integers in practice, but we replicate atoi's tolerance rather than
    raising on it, per the C's actual behavior.)"""
    s = tok.strip()
    i = 0
    n = len(s)
    sign = 1
    if i < n and s[i] in "+-":
        if s[i] == "-":
            sign = -1
        i += 1
    j = i
    while j < n and s[j].isdigit():
        j += 1
    if j == i:
        return 0
    return sign * int(s[i:j])


def get_range(region_cut: str):
    """Mirrors get_range() in make_slc_nsr.c:36-65."""
    parts = region_cut.split("/")
    if len(parts) != 4:
        raise ValueError(
            f"region_cut must be 'xl/xh/yl/yh' (4 slash-separated ints), got: {region_cut!r}"
        )
    xl, xh, yl, yh = (_atoi(p) for p in parts)
    return xl, xh, yl, yh


# ---------------------------------------------------------------------------
# C2. cat_nums / str_date2JD / date2MJD  (ported from xml.c)
# ---------------------------------------------------------------------------

def cat_nums(s: str) -> str:
    """Mirrors cat_nums() in xml.c:429-455. Extracts digits from s, with a
    correction that left-pads single-digit HH/MM/SS fields (bounded by
    'T', ':', '.') with a '0'."""
    out = []
    sep1 = -1
    for i, c in enumerate(s):
        if c.isdigit():
            out.append(c)
        elif len(out) > 0:
            if c in ("T", ":", "."):
                sep2 = i
                if sep2 - sep1 == 2:
                    out.append(out[-1])
                    out[-2] = "0"
                    sep2 += 1
                sep1 = i
    return "".join(out)


def _num(s: str) -> float:
    """str2double() applied to a purely-digit (or empty) substring, as
    produced by slicing a cat_nums() digit-string. Empty -> 0.0, matching
    str2double("") == 0.0 in the C (xml.c:501-563)."""
    return float(s) if s else 0.0


def date2MJD(yr: float, mo: float, day: float, hr: float, minute: float, sec: float) -> float:
    """Mirrors date2MJD() in xml.c:457-469."""
    part1 = (
        367.0 * yr
        - math.floor(7.0 * (yr + math.floor((mo + 9.0) / 12.0)) / 4.0)
        + math.floor(275.0 * mo / 9.0)
        + day
    )
    part2 = -678987.0 + ((sec / 60.0 + minute) / 60.0 + hr) / 24.0
    return part1 + part2


def str_date2JD(date_digits: str) -> float:
    """Mirrors str_date2JD() in xml.c:471-499, INCLUDING the sprintf("%.12f")
    ASCII round-trip (the C reparses its own %.12f-formatted text via
    str2double — we replicate that precision truncation with Python's
    equivalent %.12f format + float() reparse, both of which are
    correctly-rounded decimal<->binary conversions)."""

    def seg(a, b):  # inclusive C-index slice [a,b]
        return date_digits[a : b + 1]

    yr = float(int(_num(seg(0, 3))))
    mo = float(int(_num(seg(4, 5))))
    day = float(int(_num(seg(6, 7))))
    hr = float(int(_num(seg(8, 9))))
    minute = float(int(_num(seg(10, 11))))
    sec = _num(seg(12, 13))
    sec = sec + _num(seg(14, 19)) / 1000000.0

    mjd_yr = date2MJD(yr, 1.0, 1.0, 0.0, 0.0, 0.0)
    mjd_day = date2MJD(yr, mo, day, 0.0, 0.0, 0.0)
    mjd_frac = (((hr * 60.0) + minute) * 60.0 + sec) / 86400.0
    doy = int(mjd_day - mjd_yr + 0.1)

    str_jd = "%.12f" % (doy + mjd_frac)
    return float(str_jd)


def _hdf5_units_to_t0_yr(ds: h5py.Dataset):
    """cat_nums(units attr) -> str_date2JD -> t0 (day-of-year fraction, via
    the C's ASCII round-trip) and yr (int year, from the first 4 digits).
    Shared by pop_led_hdf5 and pop_prm_hdf5 (both call this on a "units"
    attribute string of the form "seconds since YYYY-MM-DDTHH:MM:SS")."""
    units = ds.attrs["units"]
    if isinstance(units, bytes):
        units = units.decode("ascii")
    digits = cat_nums(units)
    t0 = str_date2JD(digits)
    yr = int(_num(digits[0:4]))
    return t0, yr


# ---------------------------------------------------------------------------
# C3. f32_to_i16_with_checks — vectorized
# ---------------------------------------------------------------------------

def f32_to_i16_batch(x_f32: np.ndarray):
    """Vectorized mirror of f32_to_i16_with_checks() in make_slc_nsr.c:493-514.

    x_f32 MUST already be float32 (the C casts the double product back to
    float BEFORE calling this, so the saturation/truncation compares happen
    in float32 precision, not double).

    Returns (int16 array, sat_hi_count, sat_lo_count, zero_conv_count).
    """
    if x_f32.dtype != np.float32:
        raise TypeError("f32_to_i16_batch requires float32 input (C casts to float before compare)")

    finite = np.isfinite(x_f32)
    hi = x_f32 > np.float32(INT16_MAX)
    lo = x_f32 < np.float32(INT16_MIN)

    sat_hi_count = int(np.count_nonzero(finite & hi))
    sat_lo_count = int(np.count_nonzero(finite & lo))

    trunc = np.trunc(x_f32)
    out = np.select(
        [~finite, hi, lo],
        [np.float32(0.0), np.float32(INT16_MAX), np.float32(INT16_MIN)],
        default=trunc,
    ).astype(np.int16)

    zero_conv_count = int(np.count_nonzero(finite & ~hi & ~lo & (out == 0) & (x_f32 != 0.0)))

    return out, sat_hi_count, sat_lo_count, zero_conv_count


# ---------------------------------------------------------------------------
# C4. write_slc_hdf5
# ---------------------------------------------------------------------------

def write_slc_hdf5(h5file: h5py.File, slc_path: str, mode: str, dfact: float,
                    xl: int, xh: int, yl: int, yh: int, verbose: bool = True):
    """Mirrors write_slc_hdf5() in make_slc_nsr.c:134-256.

    Returns the ADJUSTED (xl, xh, yl, yh) — xh/yh are cropped down so that
    (xh-xl) and (yh-yl) are multiples of 4, matching the C exactly.

    Deviates from the C only in HOW the HDF5 data is fetched: the C reads
    the ENTIRE frequency/type dataset into RAM then crops; this reads only
    the [yl:yh, xl:xh] sub-region via h5py fancy indexing. Both produce
    bit-identical float32 values for the region actually written (HDF5
    slicing is a solved, deterministic I/O primitive — this is a Phase D
    perf optimization, not an algorithmic change, and is verified by the
    byte-for-byte parity test against the real C binary).
    """
    freq = mode[0]
    dtype_name = mode[1:]

    rs_a = h5file["/science/LSAR/RSLC/swaths/frequencyA/slantRangeSpacing"][()]
    rs_b = h5file["/science/LSAR/RSLC/swaths/frequencyB/slantRangeSpacing"][()]
    bw_fac = rs_b / rs_a
    if verbose:
        print(f"dfact {dfact:f} ")
        print(f"bw_fac {bw_fac:f} ")

    if freq == "A":
        group = "/science/LSAR/RSLC/swaths/frequencyA"
    elif freq == "B":
        group = "/science/LSAR/RSLC/swaths/frequencyB"
    else:
        raise ValueError("Invalid frequency type")

    if freq == "B" and xh > 0:
        xl = int(xl / bw_fac)
        xh = int(xh / bw_fac) + 1

    ds = h5file[f"{group}/{dtype_name}"]
    height, width = ds.shape  # dims[0], dims[1]
    if verbose:
        print(f"Data size {width} x {height} ... ")

    if xl == 0 and xh == 0 and yl == 0 and yh == 0:
        xl, xh, yl, yh = 0, width, 0, height
    if xl < 0 or xh > width or xl >= xh or yl < 0 or yh > height or yl >= yh:
        raise ValueError("wrong range ")

    wt = xh - xl
    ht = yh - yl
    width2 = wt - wt % 4
    height2 = ht - ht % 4
    xh = xl + width2
    yh = yl + height2
    if verbose:
        print(f"Writing SLC..Image Size: {width2} X {height2}... ")

    region = ds[yl:yh, xl:xh]  # complex64, shape (height2, width2)
    real64 = region.real.astype(np.float64)
    imag64 = region.imag.astype(np.float64)
    real32 = (real64 * dfact).astype(np.float32)
    imag32 = (imag64 * dfact).astype(np.float32)

    real_i16, sh_r, sl_r, zc_r = f32_to_i16_batch(real32)
    imag_i16, sh_i, sl_i, zc_i = f32_to_i16_batch(imag32)

    sat_hi_count = sh_r + sh_i
    sat_lo_count = sl_r + sl_i
    zero_conv_count = zc_r + zc_i
    # C's `ij` counts PIXELS (incremented once per (I,Q) pair in the j-loop),
    # not samples -- match that denominator for the diagnostic printfs below
    # (cosmetic only; not written to any output file).
    ij = height2 * width2

    interleaved = np.empty((height2, width2, 2), dtype=np.int16)
    interleaved[:, :, 0] = real_i16
    interleaved[:, :, 1] = imag_i16

    sum2 = float(np.sum(real_i16.astype(np.int64) ** 2))
    count = height2 * width2

    with open(slc_path, "wb") as fp:
        fp.write(interleaved.tobytes())

    if verbose:
        print(f"fraction clamped to INT16_MAX: {sat_hi_count / ij:f}")
        print(f"fraction clamped to INT16_MIN: {sat_lo_count / ij:f}")
        print(f"fraction set to 0 after cast: {zero_conv_count / ij:f}")
        print(f"sigma of integers (2048 < sig < 8192) {int(math.sqrt(sum2 / count))}")

    return xl, xh, yl, yh


# ---------------------------------------------------------------------------
# C5. pop_prm_hdf5
# ---------------------------------------------------------------------------

class PRM:
    """Minimal attribute bag standing in for `struct PRM` (gmtsar/PRM.h).
    Only fields make_slc_nsr.c's pop_prm_hdf5() sets are populated; the
    writer (write_prm) below only ever emits those, matching put_sio_struct's
    NULL-valued-field suppression (gmtsar/sio_struct.c:329-487) for exactly
    this field subset."""

    def __init__(self):
        pass


def pop_prm_hdf5(h5file: h5py.File, file_name: str, mode: str, xl: int, xh: int, yl: int, yh: int) -> PRM:
    """Mirrors pop_prm_hdf5() in make_slc_nsr.c:313-429."""
    freq = mode[0]
    dtype_name = mode[1:]

    prm = PRM()
    prm.nlooks = 1
    prm.rshift = 0
    prm.ashift = 0
    prm.sub_int_r = 0.0
    prm.sub_int_a = 0.0
    prm.stretch_r = 0.0
    prm.stretch_a = 0.0
    prm.a_stretch_r = 0.0
    prm.a_stretch_a = 0.0
    prm.first_sample = 1
    prm.st_rng_bin = 1
    prm.dtype = "a"
    prm.SC_identity = SC_IDENTITY_NSR
    prm.ra = EARTH_RA
    prm.rc = EARTH_RC
    prm.led_file = file_name + ".LED"
    prm.SLC_file = file_name + ".SLC"
    prm.SLC_scale = 1.0
    prm.xmi = 0.0
    prm.xmq = 0.0

    if freq == "A":
        group = "/science/LSAR/RSLC/swaths/frequencyA"
    elif freq == "B":
        group = "/science/LSAR/RSLC/swaths/frequencyB"
    else:
        raise ValueError("Invalid frequency type")

    rs = h5file[f"{group}/slantRangeSpacing"][()]
    prm.fs = C_SPEED / 2.0 / rs

    center_freq = h5file[f"{group}/processedCenterFrequency"][()]
    prm.lambda_ = C_SPEED / center_freq

    # nominalAcquisitionPRF / processedRangeBandwidth: C reads these but
    # immediately overwrites pulsedur/chirp_slope with 0.0 — see module
    # docstring AUDITED SIMPLIFICATIONS. Not read here.
    prm.pulsedur = 0.0
    prm.chirp_slope = 0.0

    zdt_spacing = h5file["/science/LSAR/RSLC/swaths/zeroDopplerTimeSpacing"][()]
    prm.prf = 1.0 / zdt_spacing

    slant_range = h5file[f"{group}/slantRange"]
    t_first = slant_range[0]
    prm.near_range = t_first + xl * C_SPEED / (2.0 * prm.fs)

    zdt_ds = h5file["/science/LSAR/RSLC/swaths/zeroDopplerTime"]
    t0, yr = _hdf5_units_to_t0_yr(zdt_ds)
    t_zdt0 = zdt_ds[0]
    # identification/zeroDopplerStartTime: read-and-discard in C, skipped
    # here — see module docstring AUDITED SIMPLIFICATIONS.
    prm.clock_start = t0 + (t_zdt0 + yl / prm.prf) / 86400.0
    prm.SC_clock_start = prm.clock_start + yr * 1000.0

    prm.fdd1 = 0.0
    prm.fddd1 = 0.0

    orbit_pass = h5file["/science/LSAR/identification/orbitPassDirection"][()]
    if isinstance(orbit_pass, bytes):
        orbit_pass = orbit_pass.decode("ascii")
    prm.orbdir = "A" if orbit_pass == "Ascending" else "D"

    look_dir = h5file["/science/LSAR/identification/lookDirection"][()]
    if isinstance(look_dir, bytes):
        look_dir = look_dir.decode("ascii")
    prm.lookdir = "R" if look_dir == "Right" else "L"

    prm.num_rng_bins = xh - xl
    prm.num_lines = yh - yl
    prm.bytes_per_line = prm.num_rng_bins * 4
    prm.good_bytes = prm.bytes_per_line

    prm.SC_clock_stop = prm.SC_clock_start + prm.num_lines / prm.prf / 86400.0
    prm.clock_stop = prm.clock_start + prm.num_lines / prm.prf / 86400.0
    prm.nrows = prm.num_lines
    prm.num_valid_az = prm.num_lines
    prm.num_patches = 1
    prm.chirp_ext = 0

    return prm


# ---------------------------------------------------------------------------
# C8. write_prm — mirrors the make_slc_nsr-relevant subset of put_sio_struct
#     (gmtsar/sio_struct.c:329-487). Format strings (incl. literal
#     tab/space padding) verified byte-for-byte via `cat -A` against a
#     fresh C-binary-produced PRM file.
# ---------------------------------------------------------------------------

def write_prm(prm: PRM, fp) -> None:
    fp.write("num_valid_az   \t= %d \n" % prm.num_valid_az)
    fp.write("nrows   \t\t= %d \n" % prm.nrows)
    fp.write("st_rng_bin   \t\t= %d \n" % prm.st_rng_bin)
    fp.write("nlooks   \t\t= %d \n" % prm.nlooks)
    fp.write("chirp_ext   \t\t= %d \n" % prm.chirp_ext)
    fp.write("rshift  \t\t= %d \n" % prm.rshift)
    fp.write("ashift  \t \t= %d \n" % prm.ashift)
    fp.write("stretch_r   \t\t= %g \n" % prm.stretch_r)
    fp.write("stretch_a   \t\t= %g \n" % prm.stretch_a)
    fp.write("a_stretch_r   \t= %g \n" % prm.a_stretch_r)
    fp.write("a_stretch_a   \t= %g \n" % prm.a_stretch_a)
    fp.write("first_sample   \t= %d \n" % prm.first_sample)
    fp.write("SC_identity   \t\t= %d \n" % prm.SC_identity)
    fp.write("rng_samp_rate   \t= %.6f \n" % prm.fs)
    fp.write("num_rng_bins\t\t= %d \n" % prm.num_rng_bins)
    fp.write("bytes_per_line\t\t= %d \n" % prm.bytes_per_line)
    fp.write("good_bytes_per_line\t= %d \n" % prm.good_bytes)
    fp.write("PRF\t\t\t= %.6f \n" % prm.prf)
    fp.write("pulse_dur\t\t= %e \n" % prm.pulsedur)
    fp.write("near_range\t\t= %.6f \n" % prm.near_range)
    fp.write("num_lines\t\t= %d \n" % prm.num_lines)
    fp.write("num_patches\t\t= %d \n" % prm.num_patches)
    fp.write("SC_clock_start\t\t= %16.10f \n" % prm.SC_clock_start)
    fp.write("SC_clock_stop\t\t= %16.10f \n" % prm.SC_clock_stop)
    fp.write("clock_start\t\t= %16.12f \n" % prm.clock_start)
    fp.write("clock_stop\t\t\t= %16.12f \n" % prm.clock_stop)
    fp.write("led_file\t\t= %s \n" % prm.led_file)
    fp.write("orbdir\t= %s \n" % prm.orbdir)
    fp.write("lookdir\t= %s \n" % prm.lookdir)
    fp.write("radar_wavelength\t= %g \n" % prm.lambda_)
    fp.write("chirp_slope\t= %g \n" % prm.chirp_slope)
    fp.write("rng_samp_rate\t\t= %.6f \n" % prm.fs)
    fp.write("I_mean\t\t\t= %g \n" % prm.xmi)
    fp.write("Q_mean\t\t\t= %g \n" % prm.xmq)
    fp.write("equatorial_radius\t= %.6f \n" % prm.ra)
    fp.write("polar_radius\t\t= %.6f \n" % prm.rc)
    fp.write("fdd1\t\t\t= %.6f \n" % prm.fdd1)
    fp.write("fddd1\t\t\t= %.6f \n" % prm.fddd1)
    fp.write("sub_int_r               = %.6f \n" % prm.sub_int_r)
    fp.write("sub_int_a               = %.6f \n" % prm.sub_int_a)
    fp.write("SLC_file               = %s \n" % prm.SLC_file)
    fp.write("dtype\t\t\t= %.1s \n" % prm.dtype)
    fp.write("SLC_scale               = %.6f \n" % prm.SLC_scale)


# ---------------------------------------------------------------------------
# C6. pop_led_hdf5
# ---------------------------------------------------------------------------

def pop_led_hdf5(h5file: h5py.File):
    """Mirrors pop_led_hdf5() in make_slc_nsr.c:258-295.

    Returns a list of state_vector-like objects (namedtuple-free simple
    objects with .yr/.jd/.sec/.x/.y/.z/.vx/.vy/.vz).
    """
    time_ds = h5file["/science/LSAR/RSLC/metadata/orbit/time"]
    t0, yr = _hdf5_units_to_t0_yr(time_ds)

    t = time_ds[()]
    x = h5file["/science/LSAR/RSLC/metadata/orbit/position"][()]
    v = h5file["/science/LSAR/RSLC/metadata/orbit/velocity"][()]
    count = t.shape[0]

    class _SV:
        __slots__ = ("yr", "jd", "sec", "x", "y", "z", "vx", "vy", "vz")

    svs = []
    for i in range(count):
        t_tmp = t[i] / 86400.0 + t0
        sv = _SV()
        sv.yr = yr
        sv.jd = int(t_tmp - math.trunc(t_tmp / 1000.0) * 1000.0)
        sv.sec = (t_tmp - math.trunc(t_tmp)) * 86400.0
        sv.x = float(x[i, 0])
        sv.y = float(x[i, 1])
        sv.z = float(x[i, 2])
        sv.vx = float(v[i, 0])
        sv.vy = float(v[i, 1])
        sv.vz = float(v[i, 2])
        svs.append(sv)

    print(f"{count} Lines Written for Orbit...")
    return svs


# ---------------------------------------------------------------------------
# C7. write_orb
# ---------------------------------------------------------------------------

def write_orb(svs, fp) -> None:
    """Mirrors write_orb() in make_slc_nsr.c:297-311."""
    n = len(svs)
    if n <= 1:
        return
    dt = math.trunc(svs[1].sec * 1e4) / 1e4 - math.trunc(svs[0].sec * 1e4) / 1e4
    fp.write("%d %d %d %.3f %.3f \n" % (n, svs[0].yr, svs[0].jd, svs[0].sec, dt))
    for sv in svs:
        fp.write(
            "%d %d %.3f %.6f %.6f %.6f %.8f %.8f %.8f \n"
            % (sv.yr, sv.jd, sv.sec, sv.x, sv.y, sv.z, sv.vx, sv.vy, sv.vz)
        )


# ---------------------------------------------------------------------------
# main / CLI (mirrors main() in make_slc_nsr.c:431-491)
# ---------------------------------------------------------------------------

USAGE = (
    "Usage: make_slc_nsr_py.py name_of_input_file name_output output_type scale_factor [region_cut]\n"
    "         (Note region_cut for B should be the same as A.)"
)


def make_slc_nsr(h5_path: str, out_stem: str, mode: str, dfact: float,
                  region_cut: str | None = None, verbose: bool = True) -> None:
    xl = xh = yl = yh = 0
    if region_cut is not None:
        xl, xh, yl, yh = get_range(region_cut)

    with h5py.File(h5_path, "r") as h5file:
        slc_path = out_stem + ".SLC"
        xl, xh, yl, yh = write_slc_hdf5(h5file, slc_path, mode, dfact, xl, xh, yl, yh, verbose=verbose)
        if verbose:
            print(f"Range after write_SLC xl, xh, yl, yh {xl} {xh} {yl} {yh} ")

        prm = pop_prm_hdf5(h5file, out_stem, mode, xl, xh, yl, yh)
        with open(out_stem + ".PRM", "w") as fp:
            write_prm(prm, fp)
        if verbose:
            print("PRM set for Image File...")

        svs = pop_led_hdf5(h5file)
        with open(out_stem + ".LED", "w") as fp:
            write_orb(svs, fp)


def main(argv=None):
    argv = sys.argv if argv is None else argv
    if len(argv) < 5:
        sys.exit(USAGE)
    h5_path = argv[1]
    out_stem = argv[2]
    mode = argv[3]
    dfact = float(argv[4])
    region_cut = argv[5] if len(argv) >= 6 else None
    make_slc_nsr(h5_path, out_stem, mode, dfact, region_cut)


if __name__ == "__main__":
    main()
