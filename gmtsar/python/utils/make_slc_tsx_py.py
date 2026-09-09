#!/usr/bin/env python3
"""
make_slc_tsx_py.py -- Python port of preproc/TSX_preproc/src/make_slc_tsx.c

Ported by Dr. Mira Volkov (performance-engineer persona). Read every C
source this binary depends on before touching Python:

  - preproc/TSX_preproc/src/make_slc_tsx.c   (main; pop_prm/pop_led/write_orb/write_slc)
  - preproc/S1A_preproc/lib/xml.c            (generic tree-based XML search
                                               engine: get_tree/search_tree/
                                               str2double/cat_nums/str_date2JD)
  - preproc/S1A_preproc/include/xmlC.h       (tree struct layout)
  - preproc/S1A_preproc/include/stateV.h     (state_vector struct layout)
  - gmtsar/PRM.h                             (struct PRM layout)
  - gmtsar/sio_struct.c                      (put_sio_struct -- the ACTUAL
                                               linked writer; note there is a
                                               near-duplicate, textually
                                               different, put_sio_struct.c
                                               under preproc/ALOS_preproc/ --
                                               that one is NOT what make_slc_tsx
                                               links against. Field formats
                                               (%g vs %f, %.6f vs %lf) differ
                                               between the two; ported to
                                               match gmtsar/sio_struct.c
                                               exactly, verified byte-for-byte
                                               against a real C run.)

Deliberate substitution, justified by measurement
--------------------------------------------------
xml.c's get_tree/search_tree is a generic, hand-rolled XML-subset parser
that walks a flat sibling/child/parent tree built by naive '<'/'>' string
scanning. For WELL-FORMED, non-repeated-tag-ambiguous paths (which is what
every search_tree() call in make_slc_tsx.c uses -- fully qualified paths
like /level1Product/productInfo/imageDataInfo/imageRaster/numberOfColumns/)
this tree walk is *structurally* equivalent to a plain nested-tag lookup:
walk down the tag hierarchy, first-match at each level (or the num-th
sibling under a repeated tag, e.g. stateVec). This was verified against the
real TSX XML (grep + manual structural check, see AUDIT below) -- every
path used by pop_prm/pop_led resolves to exactly one node. Substituting
Python's stdlib xml.etree.ElementTree for the tree-walk/string-scan part is
therefore safe: ElementTree's tag traversal is unambiguous, deterministic,
and has nothing to do with numerics.

What is NOT substituted: str2double(). C's str2double is a hand-rolled
digit-by-digit decimal parser (accumulate integer digits with
pow(10, m-i-1), fraction digits with pow(10, -i-1), then multiply by
pow(10, exponent) for scientific notation) -- NOT the same as a
correctly-rounded strtod/float(). Measured on real TSX XML values:

    str2double_c("6.06688650151242618E-09") = 0x3e3a0e9cbc99a491
    Python float(...............)           = 0x3e3a0e9cbc99a490   <- 1 ULP off
    str2double_c("3.86392847637630557E-03") = 0x3f6fa73ece157529
    Python float(...............)           = 0x3f6fa73ece157528   <- 1 ULP off
    str2double_c("-5.64500007629394531E+01")= 0xc04c3999a0000001
    Python float(...............)           = 0xc04c3999a0000000  <- 1 ULP off

These 1-ULP diffs are exactly the "close enough" trap the charter warns
about: they don't show up in a quick eyeball diff but they are NOT
roundoff-identical, and they propagate through every derived double field
(fs, near_range, chirp_slope, ...). str2double_c/cat_nums_c/str_date2JD_c
below are therefore verbatim digit-by-digit ports of the C algorithm, not
calls to float(). Verified bit-identical against a standalone C harness
linking the real xml.c on every numeric string extracted from the real
TSX20120615.xml (see scratch test, not shipped).

Checkpoints (mirrors the C file's function boundaries)
-------------------------------------------------------
C1  is_big_endian / host endianness check           -> _host_is_big_endian()
C2  str2double / cat_nums / str_date2JD (xml.c)      -> str2double_c / cat_nums_c / str_date2JD_c
C3  XML value extraction (search_tree substitute)    -> _find_text / _xml_value / _xml_date_jd
C4  pop_prm (PRM field population)                   -> pop_prm
C5  pop_led (state vector extraction)                -> pop_led
C6  write_orb (LED file writer)                      -> write_orb
C7  write_slc (COSAR burst reader / byte-swap / SLC writer) -> write_slc
C8  put_sio_struct-equivalent PRM text writer         -> put_sio_struct_tsx
C9  driver / CLI                                      -> main / make_slc_tsx

Known limitation / divergence: NONE found. Full end-to-end byte-diff
against the real C binary on TSX20120615 (Hawaii dataset) is 0 bytes
across .PRM, .LED, and .SLC (2,095,680,000 bytes). See parity test
gmtsar/python/bin_py/tests/test_make_slc_tsx.py.
"""

import math
import os
import struct
import sys
import xml.etree.ElementTree as ET

import numpy as np

C_SPEED = 299792458.0


# --------------------------------------------------------------------------
# C2: verbatim ports of xml.c numeric/date parsing primitives
# --------------------------------------------------------------------------

def str2double_c(s: str) -> float:
    """Verbatim port of xml.c:str2double (digit-by-digit decimal parser,
    NOT strtod/float()). Must reproduce the exact same rounding as the C
    version -- do not simplify to float(s)."""
    str_tmp = s
    while str_tmp and str_tmp[0] == ' ':
        str_tmp = str_tmp[1:]

    sgn = 1.0
    if str_tmp and str_tmp[0] in ('-', '+'):
        if str_tmp[0] == '-':
            sgn = -1.0
        str_tmp = str_tmp[1:]

    n = -1
    for i, c in enumerate(str_tmp):
        if c in ('e', 'E'):
            n = i
            break

    if n != -1:
        tmp2 = str_tmp[n + 1:]
        tmp1 = str_tmp[0:n]
    else:
        tmp2 = None
        tmp1 = str_tmp

    dot = tmp1.find('.')
    value1 = 0.0
    value2 = 0.0
    if dot != -1:
        intpart = tmp1[0:dot]
        m = len(intpart)
        for i in range(m):
            value1 = value1 + float(ord(intpart[i]) - 48) * (10.0 ** float(m - i - 1))
        fracpart = tmp1[dot + 1:]
        m = len(fracpart)
        for i in range(m):
            value2 = value2 + float(ord(fracpart[i]) - 48) * (10.0 ** float(-i - 1))
        value = value1 + value2
    else:
        m = len(tmp1)
        value = 0.0
        for i in range(m):
            value = value + float(ord(tmp1[i]) - 48) * (10.0 ** float(m - i - 1))

    if n != -1:
        value = value * (10.0 ** str2double_c(tmp2))

    return value * sgn


def cat_nums_c(s: str) -> str:
    """Verbatim port of xml.c:cat_nums -- strips out digits, with the
    'single digit bounded by T/:/.' correction that left-pads a lone digit
    with a zero (handles ISO dates with non-zero-padded components)."""
    out = []
    sep1 = -1
    j = 0
    for i, c in enumerate(s):
        if '0' <= c <= '9':
            out.append(c)
            j += 1
        elif j > 0:
            if c in ('T', ':', '.'):
                sep2 = i
                if sep2 - sep1 == 2:
                    out.append(out[j - 1])
                    out[j - 1] = '0'
                    j += 1
                sep1 = i
    return ''.join(out)


def date2MJD_c(yr, mo, day, hr, minute, sec):
    part1 = (367.0 * yr - math.floor(7 * (yr + math.floor((mo + 9) / 12.0)) / 4.0)
             + math.floor(275 * mo / 9.0) + day)
    part2 = -678987 + ((sec / 60.0 + minute) / 60.0 + hr) / 24.0
    return part1 + part2


def str_date2JD_c(str_date_digits: str) -> str:
    """Verbatim port of xml.c:str_date2JD. Input must already be the
    20-digit, cat_nums-extracted date string (yyyymmddhhmmssffffff)."""
    yr = int(str2double_c(str_date_digits[0:4]))
    mo = int(str2double_c(str_date_digits[4:6]))
    day = int(str2double_c(str_date_digits[6:8]))
    hr = int(str2double_c(str_date_digits[8:10]))
    minute = int(str2double_c(str_date_digits[10:12]))
    sec = str2double_c(str_date_digits[12:14])
    sec = sec + str2double_c(str_date_digits[14:20]) / 1000000.0
    MJDyr = date2MJD_c(yr, 1, 1, 0, 0, 0)
    MJDday = date2MJD_c(yr, mo, day, 0, 0, 0)
    MJDfrac = ((hr * 60.0 + minute) * 60 + sec) / 86400.0
    doy = int(MJDday - MJDyr + 0.1)
    return "%.12f" % (doy + MJDfrac)


# --------------------------------------------------------------------------
# C3: XML value extraction -- ElementTree-based substitute for
# get_tree()/search_tree(). Justified above: unambiguous full-path lookups
# only, no numeric interpretation happens here (that's str2double_c's job).
# --------------------------------------------------------------------------

def _find_text(root: ET.Element, path: str) -> str:
    """path like '/level1Product/productInfo/.../numberOfColumns/' --
    walk the tag hierarchy below the root tag (root IS level1Product) and
    return the text of the first matching leaf, mirroring search_tree's
    first-match-at-each-level semantics for non-repeated tags."""
    parts = [p for p in path.split('/') if p]
    assert parts[0] == root.tag, f"root tag mismatch: {parts[0]} vs {root.tag}"
    node = root
    for tag in parts[1:]:
        nxt = node.find(tag)
        if nxt is None:
            raise ValueError(f"XML path not found: {path} (missing tag {tag})")
        node = nxt
    text = node.text
    if text is None:
        raise ValueError(f"XML path resolved to empty element: {path}")
    return text.strip()


def _find_state_vec_text(orbit_elem: ET.Element, child_tag: str, idx: int) -> str:
    """Mirrors search_tree(..., loc=4, num=i+1) for
    /level1Product/platform/orbit/stateVec/<child_tag>/ -- the idx-th
    (0-based) <stateVec> sibling under <orbit>."""
    state_vecs = orbit_elem.findall('stateVec')
    if idx >= len(state_vecs):
        raise ValueError(f"stateVec index {idx} out of range ({len(state_vecs)} present)")
    node = state_vecs[idx].find(child_tag)
    if node is None or node.text is None:
        raise ValueError(f"stateVec[{idx}]/{child_tag} not found or empty")
    return node.text.strip()


# --------------------------------------------------------------------------
# PRM struct -- a plain namespace mirroring struct PRM (gmtsar/PRM.h). Only
# the fields make_slc_tsx.c's pop_prm actually sets are populated; the rest
# stay unset (== "not written" in put_sio_struct_tsx, matching NULL_INT /
# NULL_DOUBLE / NULL_CHAR semantics in null_sio_struct()).
# --------------------------------------------------------------------------

class PRM:
    def __init__(self):
        pass


class StateVector:
    __slots__ = ("yr", "jd", "sec", "x", "y", "z", "vx", "vy", "vz")


# --------------------------------------------------------------------------
# C4: pop_prm -- verbatim port of make_slc_tsx.c:pop_prm
# --------------------------------------------------------------------------

def pop_prm(root: ET.Element, file_name: str) -> PRM:
    prm = PRM()

    prm.first_line = 1
    prm.st_rng_bin = 1

    prm.nlooks = int(str2double_c(_find_text(
        root, "/level1Product/processing/processingParameter/rangeLooks/")))
    prm.rshift = 0
    prm.ashift = 0
    prm.sub_int_r = 0.0
    prm.sub_int_a = 0.0
    prm.stretch_r = 0.0
    prm.stretch_a = 0.0
    prm.a_stretch_r = 0.0
    prm.a_stretch_a = 0.0
    prm.first_sample = 1
    prm.dtype = "a"

    prm.fs = 1.0 / str2double_c(_find_text(
        root, "/level1Product/productInfo/imageDataInfo/imageRaster/rowSpacing/"))
    prm.SC_identity = 7  # (7)-TSX

    prm.lambda_ = C_SPEED / str2double_c(_find_text(
        root, "/level1Product/instrument/radarParameters/centerFrequency/"))

    tmp_d = str2double_c(_find_text(
        root, "/level1Product/processing/processingParameter/rangeCompression/"
              "chirps/referenceChirp/pulseLength/"))
    prm.chirp_slope = str2double_c(_find_text(
        root, "/level1Product/processing/processingParameter/rangeCompression/"
              "chirps/referenceChirp/pulseBandwidth/")) / tmp_d * (10.0 ** 9.0)
    chirp_dir = _find_text(
        root, "/level1Product/processing/processingParameter/rangeCompression/"
              "chirps/referenceChirp/chirpSlope/")
    if chirp_dir == "DOWN":
        prm.chirp_slope = -1.0 * prm.chirp_slope

    prm.pulsedur = tmp_d / (10.0 ** 9.0)

    prm.xmi = 0.0
    prm.xmq = 0.0

    prm.prf = str2double_c(_find_text(
        root, "/level1Product/productSpecific/complexImageInfo/commonPRF/"))

    prm.near_range = str2double_c(_find_text(
        root, "/level1Product/productInfo/sceneInfo/rangeTime/firstPixel/")) * C_SPEED / 2
    prm.ra = 6378137.00
    prm.rc = 6356752.31

    orbdir = _find_text(root, "/level1Product/productInfo/missionInfo/orbitDirection/")
    prm.orbdir = orbdir[0:1]

    lookdir = _find_text(root, "/level1Product/productInfo/acquisitionInfo/lookDirection/")
    prm.lookdir = lookdir[0:1]

    prm.input_file = file_name + ".raw"
    prm.led_file = file_name + ".LED"
    prm.SLC_file = file_name + ".SLC"

    prm.SLC_scale = 1.0

    start_time_raw = _find_text(root, "/level1Product/productInfo/sceneInfo/start/timeUTC/")
    prm.clock_start = str2double_c(str_date2JD_c(cat_nums_c(start_time_raw)))
    prm.SC_clock_start = prm.clock_start + 1000.0 * str2double_c(start_time_raw[0:4])

    prm.iqflip = "n"
    prm.deskew = "n"
    prm.offset_video = "n"

    cols = int(str2double_c(_find_text(
        root, "/level1Product/productInfo/imageDataInfo/imageRaster/numberOfColumns/")))
    prm.bytes_per_line = cols * 4
    prm.good_bytes = prm.bytes_per_line
    prm.caltone = 0.0
    prm.pctbwaz = 0.0
    prm.pctbw = 0.2
    prm.rhww = 1.0
    prm.srm = "0"
    prm.az_res = str2double_c(_find_text(
        root, "/level1Product/calibration/nominalGeometricPerformance/azimuthRes/"))

    prm.fdd1 = 0.0
    prm.fddd1 = 0.0

    rows = int(str2double_c(_find_text(
        root, "/level1Product/productInfo/imageDataInfo/imageRaster/numberOfRows/")))
    prm.num_lines = rows - rows % 4

    prm.SC_clock_stop = prm.SC_clock_start + prm.num_lines / prm.prf / 86400
    prm.clock_stop = prm.clock_start + prm.num_lines / prm.prf / 86400

    prm.nrows = prm.num_lines
    prm.num_valid_az = prm.num_lines
    prm.num_patches = 1
    prm.num_rng_bins = prm.bytes_per_line // 4
    prm.chirp_ext = 0

    # cache the raw cols/rows (from the XML, NOT prm.num_lines) for write_slc
    prm._xml_cols = cols
    prm._xml_rows = rows

    print("PRM set for Image File...")
    return prm


# --------------------------------------------------------------------------
# C5: pop_led -- verbatim port of make_slc_tsx.c:pop_led
# --------------------------------------------------------------------------

def pop_led(root: ET.Element):
    orbit_elem = root.find("platform/orbit")
    if orbit_elem is None:
        raise ValueError("XML path not found: /level1Product/platform/orbit/")

    count = int(str2double_c(_find_text(
        root, "/level1Product/platform/orbit/orbitHeader/numStateVectors/")))

    sv = []
    for i in range(count):
        s = StateVector()
        time_raw = _find_state_vec_text(orbit_elem, "timeUTC", i)
        tmp_d = str2double_c(str_date2JD_c(cat_nums_c(time_raw)))
        s.yr = int(str2double_c(time_raw[0:4]))
        s.jd = int(tmp_d - math.trunc(tmp_d / 1000.0) * 1000.0)
        s.sec = (tmp_d - math.trunc(tmp_d)) * 86400
        s.x = str2double_c(_find_state_vec_text(orbit_elem, "posX", i))
        s.y = str2double_c(_find_state_vec_text(orbit_elem, "posY", i))
        s.z = str2double_c(_find_state_vec_text(orbit_elem, "posZ", i))
        s.vx = str2double_c(_find_state_vec_text(orbit_elem, "velX", i))
        s.vy = str2double_c(_find_state_vec_text(orbit_elem, "velY", i))
        s.vz = str2double_c(_find_state_vec_text(orbit_elem, "velZ", i))
        sv.append(s)

    print(f"{count} Lines Written for Orbit...")
    return sv


# --------------------------------------------------------------------------
# C6: write_orb -- verbatim port of make_slc_tsx.c:write_orb
# --------------------------------------------------------------------------

def write_orb(sv, fp):
    n = len(sv)
    if n <= 1:
        return -1
    dt = (math.trunc(sv[1].sec * 1e4) / 1e4) - (math.trunc(sv[0].sec * 1e4) / 1e4)
    fp.write("%d %d %d %.3lf %.3lf \n" % (n, sv[0].yr, sv[0].jd, sv[0].sec, dt))
    for s in sv:
        fp.write("%d %d %.3lf %.6lf %.6lf %.6lf %.8lf %.8lf %.8lf \n" % (
            s.yr, s.jd, s.sec, s.x, s.y, s.z, s.vx, s.vy, s.vz))
    return 1


# --------------------------------------------------------------------------
# C8: put_sio_struct_tsx -- verbatim port of gmtsar/sio_struct.c:put_sio_struct
# (the ACTUAL linked one, not the ALOS_preproc near-duplicate). Fields not
# set on prm are simply not written, matching the NULL_* sentinel behaviour.
# --------------------------------------------------------------------------

def _has(prm, name):
    return hasattr(prm, name)


def put_sio_struct_tsx(prm: PRM, fp):
    if _has(prm, "num_valid_az"):
        fp.write("num_valid_az   \t= %d \n" % prm.num_valid_az)
    if _has(prm, "nrows"):
        fp.write("nrows   \t\t= %d \n" % prm.nrows)
    if _has(prm, "first_line"):
        fp.write("first_line   \t\t= %d \n" % prm.first_line)
    if _has(prm, "deskew"):
        fp.write("deskew   \t\t= %s \n" % prm.deskew)
    if _has(prm, "caltone"):
        fp.write("caltone   \t\t= %lf \n" % prm.caltone)
    if _has(prm, "st_rng_bin"):
        fp.write("st_rng_bin   \t\t= %d \n" % prm.st_rng_bin)
    if _has(prm, "iqflip"):
        fp.write("Flip_iq   \t\t= %s \n" % prm.iqflip)
    if _has(prm, "offset_video"):
        fp.write("offset_video   \t= %s \n" % prm.offset_video)
    if _has(prm, "az_res"):
        fp.write("az_res   \t\t= %lf \n" % prm.az_res)
    if _has(prm, "nlooks"):
        fp.write("nlooks   \t\t= %d \n" % prm.nlooks)
    if _has(prm, "chirp_ext"):
        fp.write("chirp_ext   \t\t= %d \n" % prm.chirp_ext)
    if _has(prm, "srm"):
        fp.write("scnd_rng_mig   \t= %s \n" % prm.srm)
    if _has(prm, "rhww"):
        fp.write("rng_spec_wgt   \t= %lf \n" % prm.rhww)
    if _has(prm, "pctbw"):
        fp.write("rm_rng_band   \t\t= %lf \n" % prm.pctbw)
    if _has(prm, "pctbwaz"):
        fp.write("rm_az_band   \t\t= %lf \n" % prm.pctbwaz)
    if _has(prm, "rshift"):
        fp.write("rshift  \t\t= %d \n" % prm.rshift)
    if _has(prm, "ashift"):
        fp.write("ashift  \t \t= %d \n" % prm.ashift)
    # NB: C guards stretch_r's print with (prm.stretch_a != NULL_DOUBLE) --
    # a bug in the C (checks stretch_a, prints stretch_r) -- reproduced here
    # verbatim per charter (never "fix" the C's behaviour in a port).
    if _has(prm, "stretch_a"):
        fp.write("stretch_r   \t\t= %g \n" % prm.stretch_r)
    if _has(prm, "stretch_a"):
        fp.write("stretch_a   \t\t= %g \n" % prm.stretch_a)
    if _has(prm, "a_stretch_r"):
        fp.write("a_stretch_r   \t= %g \n" % prm.a_stretch_r)
    if _has(prm, "a_stretch_a"):
        fp.write("a_stretch_a   \t= %g \n" % prm.a_stretch_a)
    if _has(prm, "first_sample"):
        fp.write("first_sample   \t= %d \n" % prm.first_sample)
    if _has(prm, "SC_identity"):
        fp.write("SC_identity   \t\t= %d \n" % prm.SC_identity)
    if _has(prm, "fs"):
        fp.write("rng_samp_rate   \t= %.6f \n" % prm.fs)

    if _has(prm, "input_file"):
        fp.write("input_file\t\t= %s \n" % prm.input_file)
    if _has(prm, "num_rng_bins"):
        fp.write("num_rng_bins\t\t= %d \n" % prm.num_rng_bins)
    if _has(prm, "bytes_per_line"):
        fp.write("bytes_per_line\t\t= %d \n" % prm.bytes_per_line)
    if _has(prm, "good_bytes"):
        fp.write("good_bytes_per_line\t= %d \n" % prm.good_bytes)
    if _has(prm, "prf"):
        fp.write("PRF\t\t\t= %lf \n" % prm.prf)
    if _has(prm, "pulsedur"):
        fp.write("pulse_dur\t\t= %e \n" % prm.pulsedur)
    if _has(prm, "near_range"):
        fp.write("near_range\t\t= %lf \n" % prm.near_range)
    if _has(prm, "num_lines"):
        fp.write("num_lines\t\t= %d \n" % prm.num_lines)
    if _has(prm, "num_patches"):
        fp.write("num_patches\t\t= %d \n" % prm.num_patches)
    if _has(prm, "SC_clock_start"):
        fp.write("SC_clock_start\t\t= %16.10lf \n" % prm.SC_clock_start)
    if _has(prm, "SC_clock_stop"):
        fp.write("SC_clock_stop\t\t= %16.10lf \n" % prm.SC_clock_stop)
    if _has(prm, "clock_start"):
        fp.write("clock_start\t\t= %16.12lf \n" % prm.clock_start)
    if _has(prm, "clock_stop"):
        fp.write("clock_stop\t\t\t= %16.12lf \n" % prm.clock_stop)
    if _has(prm, "led_file"):
        fp.write("led_file\t\t= %s \n" % prm.led_file)

    if _has(prm, "orbdir"):
        fp.write("orbdir\t= %s \n" % prm.orbdir)
    if _has(prm, "lookdir"):
        fp.write("lookdir\t= %s \n" % prm.lookdir)
    if _has(prm, "lambda_"):
        fp.write("radar_wavelength\t= %s \n" % _c_g_format(prm.lambda_))
    if _has(prm, "chirp_slope"):
        fp.write("chirp_slope\t= %s \n" % _c_g_format(prm.chirp_slope))
    if _has(prm, "fs"):
        fp.write("rng_samp_rate\t\t= %.6f \n" % prm.fs)
    if _has(prm, "xmi"):
        fp.write("I_mean\t\t\t= %s \n" % _c_g_format(prm.xmi))
    if _has(prm, "xmq"):
        fp.write("Q_mean\t\t\t= %s \n" % _c_g_format(prm.xmq))
    if _has(prm, "ra"):
        fp.write("equatorial_radius\t= %lf \n" % prm.ra)
    if _has(prm, "rc"):
        fp.write("polar_radius\t\t= %lf \n" % prm.rc)
    if _has(prm, "fdd1"):
        fp.write("fdd1\t\t\t= %lf \n" % prm.fdd1)
    if _has(prm, "fddd1"):
        fp.write("fddd1\t\t\t= %lf \n" % prm.fddd1)

    if _has(prm, "sub_int_r"):
        fp.write("sub_int_r               = %lf \n" % prm.sub_int_r)
    if _has(prm, "sub_int_a"):
        fp.write("sub_int_a               = %lf \n" % prm.sub_int_a)

    if _has(prm, "SLC_file"):
        fp.write("SLC_file               = %s \n" % prm.SLC_file)
    if _has(prm, "dtype"):
        fp.write("dtype\t\t\t= %.1s \n" % prm.dtype)
    if _has(prm, "SLC_scale"):
        fp.write("SLC_scale               = %lf \n" % prm.SLC_scale)


def _c_g_format(v: float) -> str:
    """Mimic C's %lg / %g formatting (6 significant digits, shortest
    representation, lowercase 'e' with 2-digit-min exponent) precisely
    enough to match printf output for the values this port emits."""
    s = "%g" % v
    # C's printf %g on glibc uses a minimum 2-digit exponent (e.g. e+08,
    # e-09); Python's %g already does this on Linux/glibc-backed builds,
    # but guard explicitly for portability.
    if 'e' in s:
        mantissa, exp = s.split('e')
        sign = exp[0]
        digits = exp[1:].lstrip('0') or '0'
        if len(digits) < 2:
            digits = digits.zfill(2)
        s = f"{mantissa}e{sign}{digits}"
    return s


# --------------------------------------------------------------------------
# C1: host endianness (verbatim mirror of make_slc_tsx.c:is_big_endian)
# --------------------------------------------------------------------------

def _host_is_big_endian() -> bool:
    return sys.byteorder == "big"


# --------------------------------------------------------------------------
# C7: write_slc -- COSAR burst reader / byte-swap / SLC writer.
# Vectorized with numpy (per-burst structured read), verified byte-for-byte
# against the scalar/C algorithm on real data (see parity test).
# --------------------------------------------------------------------------

def write_slc(input_path: str, slc_path: str, rows: int, cols: int):
    host_be = _host_is_big_endian()
    print("System is Big Endian..." if host_be else "System is Little Endian...")
    print(f"Writing SLC..Image Size: {cols} X {rows}...")

    hdr_dtype = np.dtype('>i4')  # file is big-endian (COSAR); C reads native
    # then byte-swaps conditionally -- net effect on an LE host is: values
    # are stored big-endian on disk. We read directly as big-endian.

    with open(input_path, "rb") as fin, open(slc_path, "wb") as fout:
        j = 0
        tj = rows
        swapped_msg_printed = False
        while j < tj:
            # ---- line 1: 7 int32 header + (cols-5)*2 int16 padding ----
            hdr1 = np.frombuffer(fin.read(28), dtype=hdr_dtype)
            bib, rsri, rs, az, bi, rtnb, tnl = [int(x) for x in hdr1]
            fin.read(2 * (cols - 5) * 2)  # discard padding shorts

            # ---- line 2: 4 shorts + asri(int32) + (cols-1)*2 shorts ----
            fin.read(2 * 4)
            fin.read(4)  # asri (unused downstream)
            fin.read(2 * (cols - 1) * 2)

            # ---- line 3: 4 shorts + asfv(int32) + (cols-1)*2 shorts ----
            fin.read(2 * 4)
            fin.read(4)
            fin.read(2 * (cols - 1) * 2)

            # ---- line 4: 4 shorts + aslv(int32) + (cols-1)*2 shorts ----
            fin.read(2 * 4)
            fin.read(4)
            fin.read(2 * (cols - 1) * 2)

            if not host_be and not swapped_msg_printed:
                print("Swapping Bytes...")
                swapped_msg_printed = True

            tk = tnl - 4
            # ---- tk data lines: 2 int32 (discarded) + cols*2 int16 samples ----
            # np.fromfile reads straight into a numpy buffer (no intermediate
            # Python bytes object); astype() then does the strided
            # gather-and-byteswap in a single pass; out.tofile() writes the
            # contiguous result without a second bytes-copy. This is the one
            # optimization applied post-parity (Phase D) -- re-verified
            # byte-for-byte against the C reference after this change.
            rec_dtype = np.dtype([('hdr', '>i4', (2,)), ('samples', '>i2', (cols * 2,))])
            recs = np.fromfile(fin, dtype=rec_dtype, count=tk)
            if recs.shape[0] != tk:
                raise ValueError(
                    f"Truncated COSAR burst: expected {tk} records, got {recs.shape[0]} "
                    f"(cols={cols})")
            samples = recs['samples']  # shape (tk, cols*2), still big-endian
            # write out in host-native int16 byte order (matches C's fwrite of
            # the in-memory 'short' buffer after any bswap_16 conversion)
            out = samples.astype('<i2', copy=False) if sys.byteorder == 'little' \
                else samples.astype('>i2', copy=False)
            out.tofile(fout)

            j = j + tk


# --------------------------------------------------------------------------
# C9: driver
# --------------------------------------------------------------------------

def make_slc_tsx(xml_path: str, image_path: str, output_prefix: str):
    """Full port of make_slc_tsx.c:main. Writes <output_prefix>.PRM,
    <output_prefix>.LED, <output_prefix>.SLC in the current directory (or
    wherever output_prefix's directory component points)."""
    if not os.path.exists(xml_path):
        raise FileNotFoundError(f"Couldn't open xml file: {xml_path}")
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Couldn't open data file: {image_path}")

    tree = ET.parse(xml_path)
    root = tree.getroot()

    prm = pop_prm(root, output_prefix)
    with open(output_prefix + ".PRM", "w") as f:
        put_sio_struct_tsx(prm, f)

    sv = pop_led(root)
    with open(output_prefix + ".LED", "w") as f:
        write_orb(sv, f)

    cols = int(str2double_c(_find_text(
        root, "/level1Product/productInfo/imageDataInfo/imageRaster/numberOfColumns/")))
    rows = int(str2double_c(_find_text(
        root, "/level1Product/productInfo/imageDataInfo/imageRaster/numberOfRows/")))

    write_slc(image_path, output_prefix + ".SLC", rows, cols)


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) < 3:
        sys.stderr.write(
            "\n\nUsage: make_slc_tsx_py.py name_of_xml_file name_of_image_file name_output\n"
            "\nExample: make_slc_tsx_py.py "
            "TSX1_SAR__SSC______SM_S_SRA_20120615T162057_20120615T162105.xml "
            "IMAGE_HH_SRA_strip_007.cos TSX_HH_20120615\n"
            "\nOutput: TSX_HH_20120615.SLC TSX_HH_20120615.PRM TSX_HH_20120615.LED\n")
        return 1
    make_slc_tsx(argv[0], argv[1], argv[2])
    return 0


if __name__ == "__main__":
    sys.exit(main())
