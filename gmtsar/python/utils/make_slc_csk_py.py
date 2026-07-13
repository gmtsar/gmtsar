#!/usr/bin/env python3
"""make_slc_csk_py — Python port of preproc/CSK_preproc/src_slc/make_slc_csk.c

Reads a COSMO-SkyMed (1st generation) HDF5 RAW_B/SCS_B product and writes
the GMTSAR triplet: <out>.PRM, <out>.LED, <out>.SLC.

Ported verbatim (Rule 7 / Phase B) from:
  preproc/CSK_preproc/src_slc/make_slc_csk.c   (393 lines, main + 4 fns)
  preproc/S1A_preproc/lib/xml.c                (cat_nums, str_date2JD,
                                                 str2double, strasign helpers
                                                 make_slc_csk.c relies on via
                                                 lib_functions.h)
  gmtsar/sio_struct.c   (put_sio_struct field order/format — copied literally)
  gmtsar/gmtsar.h       (I2MAX=32767.0, clipi2 macro, NULL_INT/NULL_DOUBLE)

Checkpoints (mirrors the C call graph 1:1):
  C1  hdf5_read (h5py substitute; same group/dataset/attr addressing)
  C2  str2double / cat_nums / strasign / str_date2JD / date2MJD
      (transliterated digit-by-digit, NOT Python float()/datetime)
  C3  pop_prm_hdf5  -> PRM dict, dataset "/S01/SBI" (NOT "/S01/IMG" — that's
      the CSK2/CSG sibling make_slc_csk2.c, a DIFFERENT dataset name)
  C4  pop_led_hdf5  -> state vectors. count comes DIRECTLY from the
      "Number of State Vectors" HDF5 attribute (hdf5_read(..,'i')) —
      make_slc_csk.c does NOT use the zero-stop heuristic that
      make_slc_csk2.c uses (csk2.c zero-inits t[200] and scans for the
      first t[i]==0; csk.c has no such init/scan). This is a REAL
      divergence between the two C source files, not a stylistic choice.
  C5  write_orb     -> .LED text
  C6  write_slc_hdf5 -> .SLC binary (clipi2 clamp + nclip counter),
      dataset "/S01/SBI"
  C7  put_sio_struct-equivalent -> .PRM text (literal field/format list)
  C8  main() driver / CLI

Known C-side limitation (verified on real data, NOT a porting bug):
  write_slc_hdf5() hardcodes group/dataset "/S01/SBI" regardless of
  Product Type. For genuine RAW_B products (dataset is "/S01/B001", not
  "/S01/SBI") the C binary's H5Dread of a nonexistent dataset silently
  fails (HDF5 emits diagnostic warnings to stderr, `dims` is left as
  stack garbage) and produces a corrupt/empty .SLC — confirmed by running
  the real C binary on CSK_RAW_Hawaii's genuine RAW_B .h5 files. This is
  moot in practice: pre_proc's CSK_SLC recipe (the only caller of
  make_slc_csk, see preproc/CSK_preproc/README and gmtsar/csh/pre_proc.csh)
  only ever feeds it SCS_B products (RAW_B goes through the sibling
  make_raw_csk binary instead). This port targets SCS_B parity, matching
  the C binary's actual working code path; RAW_B is left unfixed to match
  the C reference exactly (no "fix" the C doesn't have).

Real-data parity: gmtsar/python/bin_py/tests/test_make_slc_csk_parity.py
runs this against the real C `make_slc_csk` binary on CSK_SLC_Italy's
genuine CSKS2 SCS_B acquisitions.
"""
from __future__ import annotations

import math
import sys

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


# ---------------------------------------------------------------------------
# C1: hdf5_read substitute (h5py)
# ---------------------------------------------------------------------------

def h5_attr(h5: h5py.File, group: str, dset: str, attr: str):
    obj = h5
    if group:
        obj = obj[group]
    if dset:
        obj = obj[dset]
    return obj.attrs[attr]


def h5_str(h5: h5py.File, group: str, dset: str, attr: str) -> str:
    val = h5_attr(h5, group, dset, attr)
    if isinstance(val, bytes):
        return val.decode("ascii")
    return str(val)


def h5_double(h5: h5py.File, group: str, dset: str, attr: str) -> float:
    return float(h5_attr(h5, group, dset, attr))


def h5_dims(h5: h5py.File, group: str, dset: str):
    return h5[group][dset].shape


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
        lti = h5_double(h5, "/S01", "SBI", "Line Time Interval")
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
        zdrft = h5_double(h5, "/S01", "SBI", "Zero Doppler Range First Time")
        prm["near_range"] = zdrft * C_SPEED / 2.0

        ref_utc_raw = h5_str(h5, "/", "", "Reference UTC")
        zdaft = h5_double(h5, "/S01", "SBI", "Zero Doppler Azimuth First Time")
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

    dims = h5_dims(h5, "/S01", "SBI")
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

class StateVector:
    __slots__ = ("yr", "jd", "sec", "x", "y", "z", "vx", "vy", "vz")


def pop_led_hdf5(h5: h5py.File):
    # count comes directly from the "Number of State Vectors" attribute
    # (hdf5_read(..,'i') -> H5T_NATIVE_INT). No zero-stop heuristic here
    # (that's csk2.c only) -- csk.c trusts the attribute.
    count = int(h5_attr(h5, "/", "", "Number of State Vectors"))

    raw_utc = h5_str(h5, "/", "", "Reference UTC")
    date = cat_nums(raw_utc)
    jd_str = str_date2JD(date)
    t0 = str2double(jd_str)
    iy = int(str2double(date[0:4]))

    t = np.asarray(h5_attr(h5, "/", "", "State Vectors Times"), dtype=np.float64)
    x = np.asarray(h5_attr(h5, "/", "", "ECEF Satellite Position"), dtype=np.float64).reshape(-1)
    v = np.asarray(h5_attr(h5, "/", "", "ECEF Satellite Velocity"), dtype=np.float64).reshape(-1)

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
# C6: write_slc_hdf5 -- dataset "/S01/SBI"
# ---------------------------------------------------------------------------

def write_slc_hdf5(h5: h5py.File, slc_path: str, slc_factor: float) -> None:
    dims = h5_dims(h5, "/S01", "SBI")
    height, widthi = int(dims[0]), int(dims[1])
    width = widthi - widthi % 4
    height_trunc = height - height % 4

    print(f"Data size {dims[0]} x {dims[1]} x {dims[2] if len(dims) > 2 else 0}...")
    print(f"Writing SLC..Image Size: {width} X {height_trunc}...")

    dset = h5["/S01"]["SBI"]

    # C does ONE H5Dread of the entire (height x widthi x 2) buffer, then
    # loops row-by-row over it in memory. A literal row-by-row h5py
    # dset[i, 0:width, :] read (one HDF5 call per row) is not a scalar-vs-
    # vectorized parity question -- it is pathologically slow (chunked
    # storage + per-call Python/HDF5 overhead: >2 minutes for one image
    # vs the C's ~1 minute end-to-end). We batch the HDF5 reads in
    # row-chunks (bounded memory) to mirror C's single-bulk-read I/O
    # pattern; the per-element numeric algorithm below is unchanged and
    # is verified byte-for-byte against the real C binary in
    # bin_py/tests/test_make_slc_csk_parity.py.
    chunk_rows = 2000
    nclip = 0
    with open(slc_path, "wb") as fp:
        for i0 in range(0, height_trunc, chunk_rows):
            i1 = min(i0 + chunk_rows, height_trunc)
            block = dset[i0:i1, 0:width, :]  # (rows, width, 2) int16

            rr64 = block[:, :, 0].astype(np.float64) * slc_factor
            ii64 = block[:, :, 1].astype(np.float64) * slc_factor
            # C: rr,ii are `float` locals -- round-trip through float32
            rr32 = rr64.astype(np.float32)
            ii32 = ii64.astype(np.float32)

            rr_d = rr32.astype(np.float64)
            ii_d = ii32.astype(np.float64)

            nclip += int(np.count_nonzero(
                (np.trunc(rr_d).astype(np.int64) > I2MAX) |
                (np.trunc(ii_d).astype(np.int64) > I2MAX)))

            rr_clip = np.where(rr_d > I2MAX, I2MAX, np.where(rr_d < -I2MAX, -I2MAX, rr_d))
            ii_clip = np.where(ii_d > I2MAX, I2MAX, np.where(ii_d < -I2MAX, -I2MAX, ii_d))

            tmp_r = np.trunc(rr_clip).astype(np.int16)
            tmp_i = np.trunc(ii_clip).astype(np.int16)

            out = np.empty((i1 - i0, width * 2), dtype=np.int16)
            out[:, 0::2] = tmp_r
            out[:, 1::2] = tmp_i
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
    # NB: stretch_r's print is gated on stretch_a (literal C bug, preserved
    # from gmtsar/sio_struct.c:366-369)
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
        fp.write(fmt % (value,))


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
            raise RuntimeError(
                "make_slc_csk_py: Product type being nither RAW nor SLC "
                f"(file={input_h5!r}); C reference continues with a garbage "
                "PRM struct in this case -- Python port raises instead "
                "(no-silent-failure)")

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
            "\n\nUsage: make_slc_csk_py name_of_input_file name_output [SLC_factor]\n"
            "\nExample: make_slc_csk_py "
            "CSKS2_SCS_B_HI_09_HH_RA_SF_20090412050638_20090412050645.h5 CSK_20090412\n"
            "\nOutput: CSK_20090412.SLC CSK_20090412.PRM CSK_20090412.LED\n"
            "\nDefault SLC_factor is 1.0.\n")
        return 1
    slc_factor = 1.0
    if len(argv) == 4:
        slc_factor = float(argv[3])
    run(argv[1], argv[2], slc_factor)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
