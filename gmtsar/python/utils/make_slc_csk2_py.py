#!/usr/bin/env python3
"""make_slc_csk2_py — Python port of preproc/CSK_preproc/src_slc2/make_slc_csk2.c

Reads a COSMO-SkyMed 2nd-Generation (CSG) HDF5 SLC/RAW product and writes
the GMTSAR triplet: <out>.PRM, <out>.LED, <out>.SLC.

Ported verbatim (Rule 7 / Phase B) from:
  preproc/CSK_preproc/src_slc2/make_slc_csk2.c   (407 lines, main + 4 fns)
  preproc/S1A_preproc/lib/xml.c                  (cat_nums, str_date2JD,
                                                   str2double, strasign,
                                                   date2MJD helper functions
                                                   make_slc_csk2.c relies on
                                                   via lib_functions.h)
  gmtsar/sio_struct.c   (put_sio_struct field order/format — copied literally)
  gmtsar/gmtsar.h       (I2MAX=32767.0, clipi2 macro, NULL_INT/NULL_DOUBLE)

Checkpoints (mirrors the C call graph 1:1):
  C1  hdf5_read (h5py substitute; same group/dataset/attr addressing)
  C2  str2double / cat_nums / strasign / str_date2JD / date2MJD
      (transliterated digit-by-digit, NOT Python float()/datetime —
       see "Why not use library date/float parsing" below)
  C3  pop_prm_hdf5  -> PRM dict (only fields the C sets are populated;
      put_sio_struct-equivalent write skips all others, exactly like the
      NULL_INT/NULL_DOUBLE/NULL_CHAR sentinel skip in the C)
  C4  pop_led_hdf5  -> state vectors
  C5  write_orb     -> .LED text
  C6  write_slc_hdf5 -> .SLC binary (clipi2 clamp + nclip counter)
  C7  put_sio_struct-equivalent -> .PRM text (literal field/format list)
  C8  main() driver / CLI

Why not use library date/float parsing
---------------------------------------
The C's str2double() parses digit strings via manual
``value += digit * 10**k`` accumulation (xml.c:501-563), not strtod().
This is bit-parity-relevant because pop_led_hdf5/pop_prm_hdf5 route the
"Reference UTC" / "Scene Sensing Start UTC" strings through
cat_nums -> str_date2JD -> str2double before they ever become a
prm.clock_start double. Python's float() is a *correctly-rounded*
strtod and is NOT guaranteed to agree with the C's digit-accumulation
+ pow(10,k) algorithm to the last ULP once the string round-trips
through str_date2JD's ``sprintf("%.12f", ...)``. This module
transliterates str2double/cat_nums/strasign/str_date2JD/date2MJD
line-for-line instead of substituting datetime/float() — verified
bit-identical against the real C binary on CSK_SLC_Italy (see
bin_py/tests/test_make_slc_csk2_parity.py).

Known divergence from the real C binary's CSG code path
---------------------------------------------------------
No genuine CSG-format HDF5 product was available in this checkout (see
module-level NOTE in bin_py/tests/test_make_slc_csk2_parity.py). Parity
was proven against the real C binary using a byte-for-byte real CSK1
acquisition (CSK_SLC_Italy) with its pixel dataset hard-linked from
"SBI" to "IMG" so make_slc_csk2's hardcoded "/S01/IMG" lookups resolve
(CSK1 and CSG share every attribute name this code reads; only the
pixel dataset name/group differs — confirmed by diffing
src_slc/make_slc_csk.c against src_slc2/make_slc_csk2.c). All pixel
values, orbit state vectors, and product metadata are the genuine
CSKS2 acquisition; only the dataset *label* was relinked.

Performance (Phase D, real CSK_SLC_Italy fixture, 21470x22380 pixels,
1.9GB SLC output, single-threaded, same host, /usr/bin/time -v):
  C binary (src_slc2/make_slc_csk2):                  ~4-6s wall,  2.0GB RSS
  Python port, row-by-row h5py + fwrite (1st cut):     ~54s wall,  77MB RSS
  Python port, chunked hyperslab read + buffered write: ~42s wall, 4.9GB RSS
  Python port, + slc_factor==1.0 integer fast path:    ~21s wall, 0.9GB RSS

Net: the port is ~4-5x SLOWER than the C binary, even after two rounds
of numpy optimization (chunked I/O, then an integer-domain fast path
for the default SLC_factor=1.0 case that the real p2p_CSK.csh always
uses). "Tried, couldn't beat C" — a third round was not attempted (see
final report); h5py's per-hyperslab overhead plus the fundamentally
memory-bandwidth-bound nature of a straight 1.9GB buffer copy leave
little further headroom without a C extension for the read step,
which is out of scope without a build-system-dependency sign-off.
"""
from __future__ import annotations

import math
import os
import struct
import sys
from dataclasses import dataclass, field
from typing import Optional

import h5py
import numpy as np

I2MAX = 32767.0
C_SPEED = 299792458.0


# ---------------------------------------------------------------------------
# C2: transliterated string/date helpers (preproc/S1A_preproc/lib/xml.c)
# ---------------------------------------------------------------------------

def strasign(s: str, n1: int, n2: int) -> str:
    """C strasign(str_out, str, n1, n2): copy s[n1..n2] inclusive."""
    if n1 > n2:
        raise ValueError(f"strasign: n1({n1}) > n2({n2})")
    return s[n1:n2 + 1]


def strlocate(s: str, c: str, n: int) -> int:
    """C strlocate(str, c, n): 0-based index of the n-th (1-indexed) c, else -1."""
    j = 0
    for i, ch in enumerate(s):
        if ch == c:
            j += 1
            if j == n:
                return i
    return -1


def cat_nums(s: str) -> str:
    """C cat_nums(str_out, str): concatenate digits, with the T/:/. single-digit
    zero-pad correction (xml.c:429-455), transliterated exactly."""
    out = []
    sep1 = -1
    for i, ch in enumerate(s):
        if "0" <= ch <= "9":
            out.append(ch)
        elif len(out) > 0:
            if ch in ("T", ":", "."):
                sep2 = i
                if sep2 - sep1 == 2:
                    out.append(out[-1])
                    out[-2] = "0"
                sep1 = i
    return "".join(out)


def str2double(s: str) -> float:
    """C str2double(char*) — digit-by-digit accumulation, NOT strtod.
    Transliterated from xml.c:501-563."""
    s = s[:100]
    str_tmp = s
    while len(str_tmp) > 0 and str_tmp[0] == " ":
        str_tmp = str_tmp[1:]

    sgn = 1.0
    if len(str_tmp) > 0 and str_tmp[0] in ("-", "+"):
        if str_tmp[0] == "-":
            sgn = -1.0
        str_tmp = str_tmp[1:]

    e_idx = strlocate(str_tmp, "e", 1)
    if e_idx == -1:
        e_idx = strlocate(str_tmp, "E", 1)
    if e_idx != -1:
        tmp2 = str_tmp[e_idx + 1:]
        tmp1 = str_tmp[0:e_idx]
    else:
        tmp1 = str_tmp
        tmp2 = None

    dot = strlocate(tmp1, ".", 1)
    value1 = 0.0
    value2 = 0.0
    if dot != -1:
        intpart = tmp1[0:dot]
        m = len(intpart)
        for i in range(m):
            value1 += float(ord(intpart[i]) - 48) * (10.0 ** float(m - i - 1))
        fracpart = tmp1[dot + 1:]
        m = len(fracpart)
        for i in range(m):
            value2 += float(ord(fracpart[i]) - 48) * (10.0 ** float(-i - 1))
        value = value1 + value2
    else:
        m = len(tmp1)
        value = 0.0
        for i in range(m):
            value += float(ord(tmp1[i]) - 48) * (10.0 ** float(m - i - 1))

    if e_idx != -1:
        value = value * (10.0 ** str2double(tmp2))

    return value * sgn


def date2MJD(yr: int, mo: int, day: int, hr: int, mnt: int, sec: float) -> float:
    part1 = (367.0 * float(yr) - math.floor(7.0 * (float(yr) + math.floor((float(mo) + 9.0) / 12.0)) / 4.0)
             + math.floor(275.0 * float(mo) / 9.0) + float(day))
    part2 = -678987.0 + ((sec / 60.0 + float(mnt)) / 60.0 + float(hr)) / 24.0
    return part1 + part2


def str_date2JD(str_date: str) -> str:
    """C str_date2JD(str_JD, str_date) — returns the computed JD string
    (str_date must already be the cat_nums-concatenated digit string)."""
    tmp = strasign(str_date, 0, 3)
    yr = int(str2double(tmp))
    tmp = strasign(str_date, 4, 5)
    mo = int(str2double(tmp))
    tmp = strasign(str_date, 6, 7)
    day = int(str2double(tmp))
    tmp = strasign(str_date, 8, 9)
    hr = int(str2double(tmp))
    tmp = strasign(str_date, 10, 11)
    mnt = int(str2double(tmp))
    tmp = strasign(str_date, 12, 13)
    sec = str2double(tmp)
    tmp = strasign(str_date, 14, 19)
    sec = sec + str2double(tmp) / 1000000.0

    mjd_yr = date2MJD(yr, 1, 1, 0, 0, 0.0)
    mjd_day = date2MJD(yr, mo, day, 0, 0, 0.0)
    mjd_frac = ((hr * 60.0) + mnt) * 60.0 + sec
    mjd_frac = mjd_frac / 86400.0
    doy = int(mjd_day - mjd_yr + 0.1)
    return "%.12f" % (doy + mjd_frac)


def parse_hdf5_utc(raw: str) -> float:
    """cat_nums(date, tmp_c); str_date2JD(tmp_c, date); return str2double(tmp_c)."""
    date = cat_nums(raw)
    jd_str = str_date2JD(date)
    return str2double(jd_str)


# ---------------------------------------------------------------------------
# C1: hdf5_read substitute (h5py)
# ---------------------------------------------------------------------------

def h5_attr(h5: h5py.File, group: str, dset: str, attr: str):
    obj = h5
    if group:
        obj = obj[group]
    if dset:
        obj = obj[dset]
    val = obj.attrs[attr]
    return val


def h5_str(h5: h5py.File, group: str, dset: str, attr: str) -> str:
    val = h5_attr(h5, group, dset, attr)
    if isinstance(val, bytes):
        return val.decode("ascii")
    return str(val)


def h5_double(h5: h5py.File, group: str, dset: str, attr: str) -> float:
    return float(h5_attr(h5, group, dset, attr))


def h5_dims(h5: h5py.File, group: str, dset: str):
    obj = h5[group][dset]
    return obj.shape


# ---------------------------------------------------------------------------
# PRM: a plain dict-based stand-in for struct PRM. Only keys pop_prm_hdf5
# would set in the C are ever populated -- put_sio_struct's NULL_INT /
# NULL_DOUBLE / NULL_CHAR sentinel-skip behavior is reproduced by simply
# never emitting a line for a key that is absent from the dict.
# ---------------------------------------------------------------------------

def null_sio_struct() -> dict:
    return {}


def pop_prm_hdf5(prm: dict, h5: h5py.File, file_name: str) -> dict:
    prm["nlooks"] = 1
    prm["rshift"] = 0
    prm["ashift"] = 0
    prm["sub_int_r"] = 0.0
    prm["sub_int_a"] = 0.0
    prm["stretch_r"] = 0.0
    prm["stretch_a"] = 0.0
    prm["a_stretch_r"] = 0.0
    prm["a_stretch_a"] = 0.0
    prm["first_sample"] = 1
    prm["st_rng_bin"] = 1
    prm["dtype"] = "a"
    prm["SC_identity"] = 8
    prm["ra"] = 6378137.00
    prm["rc"] = 6356752.31
    prm["input_file"] = file_name + ".raw"
    prm["led_file"] = file_name + ".LED"
    prm["SLC_file"] = file_name + ".SLC"
    prm["SLC_scale"] = 1.0
    prm["xmi"] = 127.5
    prm["xmq"] = 127.5

    prm["fs"] = h5_double(h5, "/S01", "", "Sampling Rate")
    prm["lambda"] = h5_double(h5, "/", "", "Radar Wavelength")
    prm["chirp_slope"] = h5_double(h5, "/S01", "", "Range Chirp Rate")
    prm["pulsedur"] = h5_double(h5, "/S01", "", "Range Chirp Length")

    rec = h5_str(h5, "/", "", "Acquisition Mode")
    prm["prf"] = h5_double(h5, "/S01", "", "PRF")
    if rec == "SPOTLIGHT":
        lti = h5_double(h5, "/S01", "IMG", "Line Time Interval")
        prm["prf"] = 1.0 / lti

    rec = h5_str(h5, "/", "", "Product Type")
    if rec == "RAW_B":
        rft = h5_double(h5, "/S01", "B001", "Range First Times")
        prm["near_range"] = rft * C_SPEED / 2.0

        raw_utc = h5_str(h5, "/", "", "Scene Sensing Start UTC")
        date = cat_nums(raw_utc)
        jd_str = str_date2JD(date)
        prm["clock_start"] = str2double(jd_str)
        yr4 = date[0:4]
        prm["SC_clock_start"] = prm["clock_start"] + 1000.0 * str2double(yr4)
    elif rec == "SCS_B":
        zdrft = h5_double(h5, "/S01", "IMG", "Zero Doppler Range First Time")
        prm["near_range"] = zdrft * C_SPEED / 2.0

        ref_utc_raw = h5_str(h5, "/", "", "Reference UTC")
        zdaft = h5_double(h5, "/S01", "IMG", "Zero Doppler Azimuth First Time")
        date = cat_nums(ref_utc_raw)
        jd_str = str_date2JD(date)
        prm["clock_start"] = str2double(jd_str) + zdaft / 86400.0
        yr4 = date[0:4]
        prm["SC_clock_start"] = prm["clock_start"] + 1000.0 * str2double(yr4)

        prm["fdd1"] = 0.0
        prm["fddd1"] = 0.0
    else:
        sys.stderr.write("Product type being nither RAW nor SLC...\n")
        return None

    orbdir = h5_str(h5, "/", "", "Orbit Direction")
    prm["orbdir"] = "A" if orbdir == "ASCENDING" else "D"

    lookdir = h5_str(h5, "/", "", "Look Side")
    prm["lookdir"] = "R" if lookdir == "RIGHT" else "L"

    dims = h5_dims(h5, "/S01", "IMG")
    d0, d1 = int(dims[0]), int(dims[1])

    prm["bytes_per_line"] = (d1 - d1 % 4) * 4
    prm["good_bytes"] = prm["bytes_per_line"]
    prm["num_lines"] = d0 - d0 % 4

    prm["SC_clock_stop"] = prm["SC_clock_start"] + prm["num_lines"] / prm["prf"] / 86400.0
    prm["clock_stop"] = prm["clock_start"] + prm["num_lines"] / prm["prf"] / 86400.0
    prm["nrows"] = prm["num_lines"]
    prm["num_valid_az"] = prm["num_lines"]
    prm["num_patches"] = 1
    prm["num_rng_bins"] = prm["bytes_per_line"] // 4
    prm["chirp_ext"] = 0

    print("PRM set for Image File...")
    return prm


# ---------------------------------------------------------------------------
# C4: pop_led_hdf5
# ---------------------------------------------------------------------------

@dataclass
class StateVector:
    yr: int = 0
    jd: int = 0
    sec: float = 0.0
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    vz: float = 0.0


def pop_led_hdf5(h5: h5py.File):
    raw_utc = h5_str(h5, "/", "", "Reference UTC")
    date = cat_nums(raw_utc)
    jd_str = str_date2JD(date)
    t0 = str2double(jd_str)
    iy = int(str2double(date[0:4]))

    t = np.asarray(h5_attr(h5, "/", "", "State Vectors Times"), dtype=np.float64)
    x = np.asarray(h5_attr(h5, "/", "", "ECEF Satellite Position"), dtype=np.float64).reshape(-1)
    v = np.asarray(h5_attr(h5, "/", "", "ECEF Satellite Velocity"), dtype=np.float64).reshape(-1)

    # C zero-pads t/x/v to length 200/600 and stops at the first t[i]==0
    count = len(t)
    for i in range(len(t)):
        if t[i] == 0:
            count = i
            break
    print(f"Reading {count} state vectors ... ")

    sv = []
    for i in range(count):
        t_tmp = t[i] / 86400.0 + t0
        s = StateVector()
        s.yr = iy
        s.jd = int(t_tmp - math.trunc(t_tmp / 1000.0) * 1000.0)
        s.sec = (t_tmp - math.trunc(t_tmp)) * 86400.0
        s.x = float(x[i * 3])
        s.y = float(x[i * 3 + 1])
        s.z = float(x[i * 3 + 2])
        s.vx = float(v[i * 3])
        s.vy = float(v[i * 3 + 1])
        s.vz = float(v[i * 3 + 2])
        sv.append(s)

    print(f"{count} Lines Written for Orbit...")
    return sv


def write_orb(sv, fp) -> int:
    n = len(sv)
    if n <= 1:
        return -1
    dt = math.trunc(sv[1].sec * 1e4) / 1e4 - math.trunc(sv[0].sec * 1e4) / 1e4
    fp.write("%d %d %d %.3f %.3f \n" % (n, sv[0].yr, sv[0].jd, sv[0].sec, dt))
    for s in sv:
        fp.write("%d %d %.3f %.6f %.6f %.6f %.8f %.8f %.8f \n" %
                  (s.yr, s.jd, s.sec, s.x, s.y, s.z, s.vx, s.vy, s.vz))
    return 1


# ---------------------------------------------------------------------------
# C6: write_slc_hdf5
# ---------------------------------------------------------------------------

def write_slc_hdf5(h5: h5py.File, slc_path: str, slc_factor: float) -> None:
    dims = h5_dims(h5, "/S01", "IMG")
    height, widthi = int(dims[0]), int(dims[1])
    width = widthi - widthi % 4
    height_trunc = height - height % 4

    print(f"Data size {dims[0]} x {dims[1]} x {dims[2] if len(dims) > 2 else 0}...")
    print(f"Writing SLC..Image Size: {width} X {height_trunc}...")

    dset = h5["/S01"]["IMG"]

    # D2 optimization (batched I/O, mirrors the C's single H5Dread of the
    # whole dataset into one malloc'd buffer): chunked hyperslab reads
    # instead of height_trunc separate row reads, vectorized clip/cast
    # across the whole chunk, one buffered write instead of height_trunc
    # separate fwrite calls. Numerically identical per-element (same
    # float32 narrowing, same clip, same truncation) to an unrolled
    # row-at-a-time version -- verified byte-identical against the C
    # reference (bin_py/tests/test_make_slc_csk2_parity.py).
    row_chunk = max(1, min(height_trunc, (256 * 1024 * 1024) // max(1, widthi * 2 * 2)))

    # D3 optimization: for slc_factor == 1.0 (the real-world default -- the
    # only factor p2p_CSK.csh passes when $SLC_factor == 0, see
    # gmtsar/csh/pre_proc.csh:431-434), rr/ii are exactly the raw int16
    # values with no rounding (int16 magnitude <= 32768 is exactly
    # representable in float32/float64, so the double->float32->double
    # round-trip is a no-op). The only thing clipi2 can still do is clamp
    # the single edge case raw == -32768 (outside +-I2MAX=32767) to -32767.
    # Do that clamp directly in the integer domain (exact, no float ops)
    # instead of paying for 6 float64 array temporaries per chunk.
    # Verified byte-identical to the general float path and to the C
    # reference for slc_factor=1.0 (test_parity_default_factor).
    fast_path = (slc_factor == 1.0)

    nclip = 0
    with open(slc_path, "wb", buffering=1024 * 1024) as fp:
        for start in range(0, height_trunc, row_chunk):
            stop = min(start + row_chunk, height_trunc)
            block = dset[start:stop, 0:width, :]  # (rows, width, 2) int16

            if fast_path:
                # nclip stays 0: (int)rr > I2MAX can never hold since raw
                # int16 values are already <= 32767 (matches the C's
                # observed "number of points clipped to short int 0").
                out = np.empty((stop - start, width * 2), dtype=np.int16)
                out[:, 0::2] = np.maximum(block[:, :, 0], -32767)
                out[:, 1::2] = np.maximum(block[:, :, 1], -32767)
            else:
                rr64 = block[:, :, 0].astype(np.float64) * slc_factor
                ii64 = block[:, :, 1].astype(np.float64) * slc_factor
                rr_d = rr64.astype(np.float32).astype(np.float64)
                ii_d = ii64.astype(np.float32).astype(np.float64)

                nclip += int(np.count_nonzero(
                    (np.trunc(rr_d).astype(np.int64) > I2MAX) |
                    (np.trunc(ii_d).astype(np.int64) > I2MAX)))

                rr_clip = np.where(rr_d > I2MAX, I2MAX, np.where(rr_d < -I2MAX, -I2MAX, rr_d))
                ii_clip = np.where(ii_d > I2MAX, I2MAX, np.where(ii_d < -I2MAX, -I2MAX, ii_d))

                out = np.empty((stop - start, width * 2), dtype=np.int16)
                out[:, 0::2] = np.trunc(rr_clip).astype(np.int16)
                out[:, 1::2] = np.trunc(ii_clip).astype(np.int16)
            fp.write(out.tobytes())

    sys.stderr.write(f"number of points clipped to short int {nclip} \n")


# ---------------------------------------------------------------------------
# C7: put_sio_struct-equivalent (literal field order/format from
# gmtsar/sio_struct.c put_sio_struct)
# ---------------------------------------------------------------------------

_PRM_FIELDS = [
    ("num_valid_az", "num_valid_az   \t= %d \n"),
    ("nrows", "nrows   \t\t= %d \n"),
    ("first_line", "first_line   \t\t= %d \n"),
    ("deskew", "deskew   \t\t= %s \n"),
    ("caltone", "caltone   \t\t= %f \n"),
    ("st_rng_bin", "st_rng_bin   \t\t= %d \n"),
    ("iqflip", "Flip_iq   \t\t= %s \n"),
    ("offset_video", "offset_video   \t= %s \n"),
    ("az_res", "az_res   \t\t= %f \n"),
    ("nlooks", "nlooks   \t\t= %d \n"),
    ("chirp_ext", "chirp_ext   \t\t= %d \n"),
    ("srm", "scnd_rng_mig   \t= %s \n"),
    ("rhww", "rng_spec_wgt   \t= %f \n"),
    ("pctbw", "rm_rng_band   \t\t= %f \n"),
    ("pctbwaz", "rm_az_band   \t\t= %f \n"),
    ("rshift", "rshift  \t\t= %d \n"),
    ("ashift", "ashift  \t \t= %d \n"),
    # NB: stretch_r's print is gated on stretch_a (literal C bug, preserved)
    ("stretch_a", "stretch_r   \t\t= %g \n", "stretch_r"),
    ("stretch_a", "stretch_a   \t\t= %g \n"),
    ("a_stretch_r", "a_stretch_r   \t= %g \n"),
    ("a_stretch_a", "a_stretch_a   \t= %g \n"),
    ("first_sample", "first_sample   \t= %d \n"),
    ("SC_identity", "SC_identity   \t\t= %d \n"),
    ("fs", "rng_samp_rate   \t= %.6f \n"),
    ("input_file", "input_file\t\t= %s \n"),
    ("num_rng_bins", "num_rng_bins\t\t= %d \n"),
    ("bytes_per_line", "bytes_per_line\t\t= %d \n"),
    ("good_bytes", "good_bytes_per_line\t= %d \n"),
    ("prf", "PRF\t\t\t= %f \n"),
    ("pulsedur", "pulse_dur\t\t= %e \n"),
    ("near_range", "near_range\t\t= %f \n"),
    ("num_lines", "num_lines\t\t= %d \n"),
    ("num_patches", "num_patches\t\t= %d \n"),
    ("SC_clock_start", "SC_clock_start\t\t= %16.10f \n"),
    ("SC_clock_stop", "SC_clock_stop\t\t= %16.10f \n"),
    ("clock_start", "clock_start\t\t= %16.12f \n"),
    ("clock_stop", "clock_stop\t\t\t= %16.12f \n"),
    ("led_file", "led_file\t\t= %s \n"),
    ("orbdir", "orbdir\t= %s \n"),
    ("lookdir", "lookdir\t= %s \n"),
    ("lambda", "radar_wavelength\t= %g \n"),
    ("chirp_slope", "chirp_slope\t= %g \n"),
    ("fs", "rng_samp_rate\t\t= %.6f \n"),
    ("xmi", "I_mean\t\t\t= %g \n"),
    ("xmq", "Q_mean\t\t\t= %g \n"),
    ("vel", "SC_vel\t\t\t= %f \n"),
    ("RE", "earth_radius\t\t= %f \n"),
    ("ra", "equatorial_radius\t= %f \n"),
    ("rc", "polar_radius\t\t= %f \n"),
    ("ht", "SC_height\t\t= %f \n"),
    ("ht_start", "SC_height_start\t= %f \n"),
    ("ht_end", "SC_height_end\t= %f \n"),
    ("fd1", "fd1\t\t\t= %f \n"),
    ("fdd1", "fdd1\t\t\t= %f \n"),
    ("fddd1", "fddd1\t\t\t= %f \n"),
    ("sub_int_r", "sub_int_r               = %f \n"),
    ("sub_int_a", "sub_int_a               = %f \n"),
    ("bpara", "B_parallel              = %f \n"),
    ("bperp", "B_perpendicular         = %f \n"),
    ("baseline_start", "baseline_start          = %f \n"),
    ("baseline_center", "baseline_center          = %f \n"),
    ("baseline_end", "baseline_end            = %f \n"),
    ("alpha_start", "alpha_start             = %f \n"),
    ("alpha_center", "alpha_center             = %f \n"),
    ("alpha_end", "alpha_end               = %f \n"),
    ("B_offset_start", "B_offset_start          = %f \n"),
    ("B_offset_center", "B_offset_center         = %f \n"),
    ("B_offset_end", "B_offset_end            = %f \n"),
    ("SLC_file", "SLC_file               = %s \n"),
    ("dtype", "dtype\t\t\t= %.1s \n"),
    ("SLC_scale", "SLC_scale               = %f \n"),
]


def _c_percent_format(fmt: str, value) -> str:
    """Minimal C-printf-compatible formatter for the small set of verbs
    used above (%d, %s, %f, %e, %g, %16.10f, %16.12f, %.1s, %.6f)."""
    return fmt % (value,)


def put_sio_struct(prm: dict, fp) -> None:
    for entry in _PRM_FIELDS:
        if len(entry) == 3:
            gate_key, fmt, value_key = entry
        else:
            gate_key, fmt = entry
            value_key = gate_key
        if gate_key not in prm:
            continue
        value = prm[value_key]
        fp.write(_c_percent_format(fmt, value))


# ---------------------------------------------------------------------------
# C8: driver
# ---------------------------------------------------------------------------

def run(input_h5: str, out_prefix: str, slc_factor: float = 1.0) -> None:
    if slc_factor != 1.0:
        print("Setting SLC_factor to %.6f" % slc_factor)

    with h5py.File(input_h5, "r") as h5:
        prm = null_sio_struct()
        prm = pop_prm_hdf5(prm, h5, out_prefix)
        if prm is None:
            raise RuntimeError("Product type being nither RAW nor SLC")

        with open(out_prefix + ".PRM", "w") as fp:
            put_sio_struct(prm, fp)

        sv = pop_led_hdf5(h5)
        with open(out_prefix + ".LED", "w") as fp:
            write_orb(sv, fp)

        write_slc_hdf5(h5, out_prefix + ".SLC", slc_factor)


def main(argv=None) -> int:
    argv = sys.argv if argv is None else argv
    if len(argv) < 3:
        sys.stderr.write(
            "\n\nUsage: make_slc_csk2_py name_of_input_file name_output [SLC_factor]\n")
        return 1
    slc_factor = 1.0
    if len(argv) == 4:
        slc_factor = float(argv[3])
    run(argv[1], argv[2], slc_factor)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
