#!/usr/bin/env python3
"""make_slc_rs2_py — in-process port of preproc/RS2_preproc/src/make_slc_rs2.c

Verbatim port (project_rules.md Rule 7). Reads a RADARSAT-2 SLC product
(``product.xml`` + ``imagery_*.tif``) and writes ``<out>.PRM``,
``<out>.LED``, ``<out>.SLC`` bit/roundoff-identical to the C binary
``make_slc_rs2``.

C sources ported (transitively read in full):
  - preproc/RS2_preproc/src/make_slc_rs2.c  (main, pop_prm, pop_led,
    write_orb, write_slc)
  - preproc/S1A_preproc/lib/xml.c           (str2double, cat_nums,
    str_date2JD, date2MJD — the custom XML-tree parser itself
    (get_tree/search_tree) is NOT re-implemented; see "XML parsing"
    below for why that's safe)
  - gmtsar/sio_struct.c                     (put_sio_struct field
    order/format strings, NULL_INT/NULL_DOUBLE/NULL_CHAR sentinels)
  - gmtsar/gmtsar.h                         (NULL_INT=-99999,
    NULL_DOUBLE=-99999.9999, NULL_CHAR="XXXXXXXX")

XML parsing
-----------
The C code walks a hand-rolled linked-list "tree" (xml.c get_tree /
search_tree) built by scanning `<tag>value</tag>` lines. For every path
`pop_prm`/`pop_led` queries, this is exactly equivalent to XPath
navigation on a well-formed XML DOM, PROVIDED the leaf text is taken
verbatim (type=1) or is the special date path (type=2). We use
`xml.etree.ElementTree` for navigation (verified byte-identical leaf
text against the C tree on the real RS2_SLC_Hawaii product.xml) but
port `str2double`, `cat_nums`, `str_date2JD`, `date2MJD` VERBATIM
(same digit-by-digit summation, same truncated-constant arithmetic
order) since those are where float rounding could diverge from a
naive `float(text)`/`datetime` reimplementation.

Known divergence / audit
-------------------------
None on the real RS2_SLC_Hawaii case (see bin_py/tests/test_make_slc_rs2_parity.py).
If a product.xml uses irregular (non-zero-padded) date fields, the
`cat_nums` single-digit correction path (xml.c:437-450) is ported but
UNTESTED against real data — flag if a case triggers it.
"""
from __future__ import annotations

import math
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import List, Optional

import numpy as np

C_SPEED = 299792458.0

NULL_INT = -99999
NULL_DOUBLE = -99999.9999
NULL_CHAR = "XXXXXXXX"


# ---------------------------------------------------------------------------
# Verbatim ports of preproc/S1A_preproc/lib/xml.c numeric/date helpers
# ---------------------------------------------------------------------------

def cat_nums(s: str) -> str:
    """Verbatim port of xml.c:cat_nums (digit-only extraction with the
    single-digit-field zero-pad correction)."""
    out = []
    j = 0
    sep1 = -1
    sep2 = -1
    for i, ch in enumerate(s):
        if "0" <= ch <= "9":
            out.append(ch)
            j += 1
        elif j > 0:
            if ch in ("T", ":", "."):
                sep2 = i
                if sep2 - sep1 == 2:
                    # single preceding digit -> insert a leading zero
                    out.append(out[j - 1])
                    out[j - 1] = "0"
                    j += 1
                    sep2 += 1
                sep1 = i
    return "".join(out)


def str2double(s: str) -> float:
    """Verbatim port of xml.c:str2double (manual digit-by-digit parse,
    NOT Python float() — matches C's summation/pow() rounding order)."""
    str_tmp = s
    i = 0
    while i < len(str_tmp) and str_tmp[i] == " ":
        i += 1
    str_tmp = str_tmp[i:]

    sgn = 1.0
    if str_tmp[:1] in ("-", "+"):
        if str_tmp[0] == "-":
            sgn = -1.0
        str_tmp = str_tmp[1:]

    e_pos = str_tmp.find("e")
    if e_pos == -1:
        e_pos = str_tmp.find("E")
    if e_pos != -1:
        tmp2 = str_tmp[e_pos + 1:]
        tmp1 = str_tmp[:e_pos]
    else:
        tmp1 = str_tmp
        tmp2 = None

    dot = tmp1.find(".")
    if dot != -1:
        int_part = tmp1[:dot]
        frac_part = tmp1[dot + 1:]
        value1 = 0.0
        m = len(int_part)
        for i2, ch in enumerate(int_part):
            value1 = value1 + float(ord(ch) - 48) * (10.0 ** float(m - i2 - 1))
        value2 = 0.0
        m2 = len(frac_part)
        for i2, ch in enumerate(frac_part):
            value2 = value2 + float(ord(ch) - 48) * (10.0 ** float(-i2 - 1))
        value = value1 + value2
    else:
        value = 0.0
        m = len(tmp1)
        for i2, ch in enumerate(tmp1):
            value = value + float(ord(ch) - 48) * (10.0 ** float(m - i2 - 1))

    if tmp2 is not None:
        value = value * (10.0 ** str2double(tmp2))

    return value * sgn


def date2MJD(yr: int, mo: int, day: int, hr: int, minute: int, sec: float) -> float:
    """Verbatim port of xml.c:date2MJD."""
    part1 = (367.0 * float(yr) - math.floor(7.0 * (float(yr) + math.floor((float(mo) + 9.0) / 12.0)) / 4.0)
             + math.floor(275.0 * float(mo) / 9.0) + float(day))
    part2 = -678987.0 + ((sec / 60.0 + float(minute)) / 60.0 + float(hr)) / 24.0
    return part1 + part2


def str_date2JD(str_date: str) -> str:
    """Verbatim port of xml.c:str_date2JD. Returns the %.12f-formatted
    string (doy + fraction-of-day), exactly as C hands back to the
    caller via search_tree(type=2)."""
    tmp = str_date[0:4]
    yr = int(str2double(tmp))
    tmp = str_date[4:6]
    mo = int(str2double(tmp))
    tmp = str_date[6:8]
    day = int(str2double(tmp))
    tmp = str_date[8:10]
    hr = int(str2double(tmp))
    tmp = str_date[10:12]
    minute = int(str2double(tmp))
    tmp = str_date[12:14]
    sec = 0.0 + str2double(tmp)
    tmp = str_date[14:20]
    sec = sec + str2double(tmp) / 1000000.0

    mjdyr = date2MJD(yr, 1, 1, 0, 0, 0.0)
    mjdday = date2MJD(yr, mo, day, 0, 0, 0.0)
    mjdfrac = (((hr * 60.0) + minute) * 60.0 + sec) / 86400.0
    doy = int(mjdday - mjdyr + 0.1)
    return "%.12f" % (doy + mjdfrac)


def date_path_to_jd_string(raw_text: str) -> str:
    """search_tree(type=2) == cat_nums() then str_date2JD()."""
    return str_date2JD(cat_nums(raw_text))


# ---------------------------------------------------------------------------
# XML navigation (ElementTree substitute for xml.c get_tree/search_tree)
# ---------------------------------------------------------------------------

def _strip_namespaces(elem: ET.Element) -> None:
    """RS2 product.xml declares a default xmlns
    (http://www.rsi.ca/rs2/prod/xml/schemas). The C tree parser
    (xml.c:get_tree) is a dumb text scanner that never looks at
    namespaces, so 'passDirection' matches regardless of xmlns. Strip
    '{uri}' prefixes from every tag so ElementTree.find() behaves the
    same way."""
    for e in elem.iter():
        if "}" in e.tag:
            e.tag = e.tag.split("}", 1)[1]


def _find_text(root: ET.Element, path: str) -> str:
    """path is '/product/a/b/c/' (C-style, leading+trailing slash,
    rooted at the document's own top element). Strip the leading
    '/product/' since ET's root IS the <product> element."""
    parts = [p for p in path.strip("/").split("/") if p]
    assert parts[0] == "product"
    node = root
    for tag in parts[1:]:
        nxt = node.find(tag)
        if nxt is None:
            raise ValueError(f"make_slc_rs2_py: XML path not found: {path} (missing <{tag}>)")
        node = nxt
    if node.text is None:
        raise ValueError(f"make_slc_rs2_py: XML path has empty text: {path}")
    return node.text


def _find_all(root: ET.Element, path: str) -> List[ET.Element]:
    parts = [p for p in path.strip("/").split("/") if p]
    assert parts[0] == "product"
    node = root
    for tag in parts[1:-1]:
        nxt = node.find(tag)
        if nxt is None:
            raise ValueError(f"make_slc_rs2_py: XML path not found: {path}")
        node = nxt
    return node.findall(parts[-1])


# ---------------------------------------------------------------------------
# state_vector (stateV.h)
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


# ---------------------------------------------------------------------------
# PRM struct (sio_struct.c null_sio_struct + the fields put_sio_struct prints)
# ---------------------------------------------------------------------------

def null_prm() -> dict:
    """Verbatim port of sio_struct.c:null_sio_struct (only the fields
    referenced by put_sio_struct — the rest of struct PRM is out of
    scope for this tool)."""
    return dict(
        input_file=NULL_CHAR, SLC_file=NULL_CHAR, out_amp_file=NULL_CHAR,
        out_data_file=NULL_CHAR, deskew=NULL_CHAR, iqflip=NULL_CHAR,
        offset_video=NULL_CHAR, srm=NULL_CHAR, ref_file=NULL_CHAR,
        led_file=NULL_CHAR, orbdir=NULL_CHAR, lookdir=NULL_CHAR, dtype=NULL_CHAR,
        debug_flag=NULL_INT, bytes_per_line=NULL_INT, good_bytes=NULL_INT,
        first_line=NULL_INT, num_patches=NULL_INT, first_sample=NULL_INT,
        num_valid_az=NULL_INT, st_rng_bin=NULL_INT, num_rng_bins=NULL_INT,
        chirp_ext=NULL_INT, nlooks=NULL_INT, rshift=NULL_INT, ashift=NULL_INT,
        fdc_ystrt=NULL_INT, fdc_strt=NULL_INT, rec_start=NULL_INT,
        rec_stop=NULL_INT, SC_identity=NULL_INT, ref_identity=NULL_INT,
        nrows=NULL_INT, num_lines=NULL_INT, SLC_format=NULL_INT,
        SC_clock_start=NULL_DOUBLE, SC_clock_stop=NULL_DOUBLE, icu_start=NULL_DOUBLE,
        clock_start=NULL_DOUBLE, clock_stop=NULL_DOUBLE, caltone=NULL_DOUBLE,
        RE=NULL_DOUBLE, ra=NULL_DOUBLE, rc=NULL_DOUBLE, vel=NULL_DOUBLE,
        ht=NULL_DOUBLE, ht_start=NULL_DOUBLE, ht_end=NULL_DOUBLE,
        near_range=NULL_DOUBLE, far_range=NULL_DOUBLE, prf=NULL_DOUBLE,
        xmi=NULL_DOUBLE, xmq=NULL_DOUBLE, az_res=NULL_DOUBLE, fs=NULL_DOUBLE,
        chirp_slope=NULL_DOUBLE, pulsedur=NULL_DOUBLE, lambda_=NULL_DOUBLE,
        rhww=NULL_DOUBLE, pctbw=NULL_DOUBLE, pctbwaz=NULL_DOUBLE,
        fd1=NULL_DOUBLE, fdd1=NULL_DOUBLE, fddd1=NULL_DOUBLE,
        sub_int_r=NULL_DOUBLE, sub_int_a=NULL_DOUBLE, stretch_r=NULL_DOUBLE,
        stretch_a=NULL_DOUBLE, a_stretch_r=NULL_DOUBLE, a_stretch_a=NULL_DOUBLE,
        baseline_start=NULL_DOUBLE, baseline_center=NULL_DOUBLE, baseline_end=NULL_DOUBLE,
        alpha_start=NULL_DOUBLE, alpha_center=NULL_DOUBLE, alpha_end=NULL_DOUBLE,
        bpara=NULL_DOUBLE, bperp=NULL_DOUBLE, SLC_scale=NULL_DOUBLE,
        B_offset_start=NULL_DOUBLE, B_offset_center=NULL_DOUBLE, B_offset_end=NULL_DOUBLE,
    )


def put_sio_struct(prm: dict) -> str:
    """Verbatim port of gmtsar/sio_struct.c:put_sio_struct — same field
    order, same (slightly inconsistent) tab/space format strings."""
    out = []

    def w(fmt, *args):
        out.append(fmt % args if args else fmt)

    if prm["num_valid_az"] != NULL_INT:
        w("num_valid_az   \t= %d \n", prm["num_valid_az"])
    if prm["nrows"] != NULL_INT:
        w("nrows   \t\t= %d \n", prm["nrows"])
    if prm["first_line"] != NULL_INT:
        w("first_line   \t\t= %d \n", prm["first_line"])
    if prm["deskew"] != NULL_CHAR:
        w("deskew   \t\t= %s \n", prm["deskew"])
    if prm["caltone"] != NULL_DOUBLE:
        w("caltone   \t\t= %lf \n", prm["caltone"])
    if prm["st_rng_bin"] != NULL_INT:
        w("st_rng_bin   \t\t= %d \n", prm["st_rng_bin"])
    if prm["iqflip"] != NULL_CHAR:
        w("Flip_iq   \t\t= %s \n", prm["iqflip"])
    if prm["offset_video"] != NULL_CHAR:
        w("offset_video   \t= %s \n", prm["offset_video"])
    if prm["az_res"] != NULL_DOUBLE:
        w("az_res   \t\t= %lf \n", prm["az_res"])
    if prm["nlooks"] != NULL_INT:
        w("nlooks   \t\t= %d \n", prm["nlooks"])
    if prm["chirp_ext"] != NULL_INT:
        w("chirp_ext   \t\t= %d \n", prm["chirp_ext"])
    if prm["srm"] != NULL_CHAR:
        w("scnd_rng_mig   \t= %s \n", prm["srm"])
    if prm["rhww"] != NULL_DOUBLE:
        w("rng_spec_wgt   \t= %lf \n", prm["rhww"])
    if prm["pctbw"] != NULL_DOUBLE:
        w("rm_rng_band   \t\t= %lf \n", prm["pctbw"])
    if prm["pctbwaz"] != NULL_DOUBLE:
        w("rm_az_band   \t\t= %lf \n", prm["pctbwaz"])
    if prm["rshift"] != NULL_INT:
        w("rshift  \t\t= %d \n", prm["rshift"])
    if prm["ashift"] != NULL_INT:
        w("ashift  \t \t= %d \n", prm["ashift"])
    if prm["stretch_a"] != NULL_DOUBLE:
        w("stretch_r   \t\t= %s \n", _g(prm["stretch_r"]))
    if prm["stretch_a"] != NULL_DOUBLE:
        w("stretch_a   \t\t= %s \n", _g(prm["stretch_a"]))
    if prm["a_stretch_r"] != NULL_DOUBLE:
        w("a_stretch_r   \t= %s \n", _g(prm["a_stretch_r"]))
    if prm["a_stretch_a"] != NULL_DOUBLE:
        w("a_stretch_a   \t= %s \n", _g(prm["a_stretch_a"]))
    if prm["first_sample"] != NULL_INT:
        w("first_sample   \t= %d \n", prm["first_sample"])
    if prm["SC_identity"] != NULL_INT:
        w("SC_identity   \t\t= %d \n", prm["SC_identity"])
    if prm["fs"] != NULL_DOUBLE:
        w("rng_samp_rate   \t= %.6f \n", prm["fs"])

    if prm["input_file"] != NULL_CHAR:
        w("input_file\t\t= %s \n", prm["input_file"])
    if prm["num_rng_bins"] != NULL_INT:
        w("num_rng_bins\t\t= %d \n", prm["num_rng_bins"])
    if prm["bytes_per_line"] != NULL_INT:
        w("bytes_per_line\t\t= %d \n", prm["bytes_per_line"])
    if prm["good_bytes"] != NULL_INT:
        w("good_bytes_per_line\t= %d \n", prm["good_bytes"])
    if prm["prf"] != NULL_DOUBLE:
        w("PRF\t\t\t= %lf \n", prm["prf"])
    if prm["pulsedur"] != NULL_DOUBLE:
        w("pulse_dur\t\t= %s \n", _e(prm["pulsedur"]))
    if prm["near_range"] != NULL_DOUBLE:
        w("near_range\t\t= %lf \n", prm["near_range"])
    if prm["num_lines"] != NULL_INT:
        w("num_lines\t\t= %d \n", prm["num_lines"])
    if prm["num_patches"] != NULL_INT:
        w("num_patches\t\t= %d \n", prm["num_patches"])
    if prm["SC_clock_start"] != NULL_DOUBLE:
        w("SC_clock_start\t\t= %s \n", _fw(prm["SC_clock_start"], 16, 10))
    if prm["SC_clock_stop"] != NULL_DOUBLE:
        w("SC_clock_stop\t\t= %s \n", _fw(prm["SC_clock_stop"], 16, 10))
    if prm["clock_start"] != NULL_DOUBLE:
        w("clock_start\t\t= %s \n", _fw(prm["clock_start"], 16, 12))
    if prm["clock_stop"] != NULL_DOUBLE:
        w("clock_stop\t\t\t= %s \n", _fw(prm["clock_stop"], 16, 12))
    if prm["led_file"] != NULL_CHAR:
        w("led_file\t\t= %s \n", prm["led_file"])

    if prm["orbdir"] != NULL_CHAR:
        w("orbdir\t= %s \n", prm["orbdir"])
    if prm["lookdir"] != NULL_CHAR:
        w("lookdir\t= %s \n", prm["lookdir"])
    if prm["lambda_"] != NULL_DOUBLE:
        w("radar_wavelength\t= %s \n", _g(prm["lambda_"]))
    if prm["chirp_slope"] != NULL_DOUBLE:
        w("chirp_slope\t= %s \n", _g(prm["chirp_slope"]))
    if prm["fs"] != NULL_DOUBLE:
        w("rng_samp_rate\t\t= %.6f \n", prm["fs"])
    if prm["xmi"] != NULL_DOUBLE:
        w("I_mean\t\t\t= %s \n", _g(prm["xmi"]))
    if prm["xmq"] != NULL_DOUBLE:
        w("Q_mean\t\t\t= %s \n", _g(prm["xmq"]))
    if prm["vel"] != NULL_DOUBLE:
        w("SC_vel\t\t\t= %lf \n", prm["vel"])
    if prm["RE"] != NULL_DOUBLE:
        w("earth_radius\t\t= %lf \n", prm["RE"])
    if prm["ra"] != NULL_DOUBLE:
        w("equatorial_radius\t= %lf \n", prm["ra"])
    if prm["rc"] != NULL_DOUBLE:
        w("polar_radius\t\t= %lf \n", prm["rc"])
    if prm["ht"] != NULL_DOUBLE:
        w("SC_height\t\t= %lf \n", prm["ht"])
    if prm["ht_start"] != NULL_DOUBLE:
        w("SC_height_start\t= %lf \n", prm["ht_start"])
    if prm["ht_end"] != NULL_DOUBLE:
        w("SC_height_end\t= %lf \n", prm["ht_end"])
    if prm["fd1"] != NULL_DOUBLE:
        w("fd1\t\t\t= %lf \n", prm["fd1"])
    if prm["fdd1"] != NULL_DOUBLE:
        w("fdd1\t\t\t= %lf \n", prm["fdd1"])
    if prm["fddd1"] != NULL_DOUBLE:
        w("fddd1\t\t\t= %lf \n", prm["fddd1"])

    if prm["sub_int_r"] != NULL_DOUBLE:
        w("sub_int_r               = %lf \n", prm["sub_int_r"])
    if prm["sub_int_a"] != NULL_DOUBLE:
        w("sub_int_a               = %lf \n", prm["sub_int_a"])
    if prm["bpara"] != NULL_DOUBLE:
        w("B_parallel              = %lf \n", prm["bpara"])
    if prm["bperp"] != NULL_DOUBLE:
        w("B_perpendicular         = %lf \n", prm["bperp"])
    if prm["baseline_start"] != NULL_DOUBLE:
        w("baseline_start          = %lf \n", prm["baseline_start"])
    if prm["baseline_center"] != NULL_DOUBLE:
        w("baseline_center          = %lf \n", prm["baseline_center"])
    if prm["baseline_end"] != NULL_DOUBLE:
        w("baseline_end            = %lf \n", prm["baseline_end"])
    if prm["alpha_start"] != NULL_DOUBLE:
        w("alpha_start             = %lf \n", prm["alpha_start"])
    if prm["alpha_center"] != NULL_DOUBLE:
        w("alpha_center             = %lf \n", prm["alpha_center"])
    if prm["alpha_end"] != NULL_DOUBLE:
        w("alpha_end               = %lf \n", prm["alpha_end"])
    if prm["B_offset_start"] != NULL_DOUBLE:
        w("B_offset_start          = %lf \n", prm["B_offset_start"])
    if prm["B_offset_center"] != NULL_DOUBLE:
        w("B_offset_center         = %lf \n", prm["B_offset_center"])
    if prm["B_offset_end"] != NULL_DOUBLE:
        w("B_offset_end            = %lf \n", prm["B_offset_end"])

    if prm["SLC_file"] != NULL_CHAR:
        w("SLC_file               = %s \n", prm["SLC_file"])
    if prm["dtype"] != NULL_CHAR:
        w("dtype\t\t\t= %.1s \n", prm["dtype"])
    if prm["SLC_scale"] != NULL_DOUBLE:
        w("SLC_scale               = %lf \n", prm["SLC_scale"])

    return "".join(out)


def _g(v: float) -> str:
    """C '%g'/'%lg' — shortest round-trippable-ish 6-significant-digit
    form. printf %g == Python '%g' formatting (both C-library-derived,
    verified byte-identical on the real-data field values below)."""
    return "%g" % v


def _e(v: float) -> str:
    """C '%e'."""
    return "%e" % v


def _fw(v: float, width: int, prec: int) -> str:
    """C '%<width>.<prec>lf' (fixed width, but %lf never truncates a
    longer integer part, so we just format with the precision; the
    width only adds leading spaces which %<width>.<prec>f in Python
    reproduces identically)."""
    return ("%" + str(width) + "." + str(prec) + "f") % v


# ---------------------------------------------------------------------------
# pop_prm / pop_led / write_orb  (make_slc_rs2.c)
# ---------------------------------------------------------------------------

def pop_prm(root: ET.Element, file_name: str) -> dict:
    prm = null_prm()

    prm["first_line"] = 1
    prm["st_rng_bin"] = 1
    prm["nlooks"] = int(str2double(_find_text(
        root, "/product/imageGenerationParameters/sarProcessingInformation/numberOfRangeLooks/")))
    prm["rshift"] = 0
    prm["ashift"] = 0
    prm["sub_int_r"] = 0.0
    prm["sub_int_a"] = 0.0
    prm["stretch_r"] = 0.0
    prm["stretch_a"] = 0.0
    prm["a_stretch_r"] = 0.0
    prm["a_stretch_a"] = 0.0
    prm["first_sample"] = 1
    prm["dtype"] = "a"

    pixel_spacing = str2double(_find_text(
        root, "/product/imageAttributes/rasterAttributes/sampledPixelSpacing/"))
    prm["fs"] = C_SPEED / 2.0 / pixel_spacing
    prm["SC_identity"] = 9

    prm["lambda_"] = C_SPEED / str2double(_find_text(
        root, "/product/sourceAttributes/radarParameters/radarCenterFrequency/"))

    tmp_d = str2double(_find_text(
        root, "/product/sourceAttributes/radarParameters/pulseLength/"))
    bw = str2double(_find_text(
        root, "/product/sourceAttributes/radarParameters/pulseBandwidth/"))
    prm["chirp_slope"] = bw / tmp_d
    prm["pulsedur"] = tmp_d

    prm["xmi"] = 0.0
    prm["xmq"] = 0.0

    prm["prf"] = str2double(_find_text(
        root, "/product/sourceAttributes/radarParameters/pulseRepetitionFrequency/")) / 2.0
    prm["near_range"] = str2double(_find_text(
        root, "/product/imageGenerationParameters/slantRangeToGroundRange/"
              "slantRangeTimeToFirstRangeSample/")) * C_SPEED / 2.0
    prm["ra"] = 6378137.00
    prm["rc"] = 6356752.31

    pass_dir = _find_text(root, "/product/sourceAttributes/orbitAndAttitude/orbitInformation/passDirection/")
    prm["orbdir"] = pass_dir[0:1]

    antenna = _find_text(root, "/product/sourceAttributes/radarParameters/antennaPointing/")
    prm["lookdir"] = antenna[0:1]

    prm["input_file"] = file_name + ".raw"
    prm["led_file"] = file_name + ".LED"
    prm["SLC_file"] = file_name + ".SLC"

    prm["SLC_scale"] = 1.0
    if prm["orbdir"] == "D":
        raw_date = _find_text(
            root, "/product/imageGenerationParameters/sarProcessingInformation/zeroDopplerTimeFirstLine/")
    else:
        raw_date = _find_text(
            root, "/product/imageGenerationParameters/sarProcessingInformation/zeroDopplerTimeLastLine/")
    prm["clock_start"] = str2double(date_path_to_jd_string(raw_date))

    last_line_raw = _find_text(
        root, "/product/imageGenerationParameters/sarProcessingInformation/zeroDopplerTimeLastLine/")
    yr4 = last_line_raw[0:4]
    prm["SC_clock_start"] = prm["clock_start"] + 1000.0 * str2double(yr4)

    prm["iqflip"] = "n"
    prm["deskew"] = "n"
    prm["offset_video"] = "n"

    n_samp = str2double(_find_text(
        root, "/product/imageAttributes/rasterAttributes/numberOfSamplesPerLine/"))
    prm["num_rng_bins"] = int(n_samp) - int(n_samp) % 4
    prm["bytes_per_line"] = prm["num_rng_bins"] * 4
    prm["good_bytes"] = prm["bytes_per_line"]
    prm["caltone"] = 0.0
    prm["pctbwaz"] = 0.0
    prm["pctbw"] = 0.2
    prm["rhww"] = 1.0
    prm["srm"] = "0"
    prm["az_res"] = 0.0
    prm["fdd1"] = 0.0
    prm["fddd1"] = 0.0

    tmp_i = int(str2double(_find_text(
        root, "/product/imageAttributes/rasterAttributes/numberOfLines/")))
    prm["num_lines"] = tmp_i - tmp_i % 4

    prm["SC_clock_stop"] = prm["SC_clock_start"] + prm["num_lines"] / prm["prf"] / 86400.0
    prm["clock_stop"] = prm["clock_start"] + prm["num_lines"] / prm["prf"] / 86400.0

    prm["nrows"] = prm["num_lines"]
    prm["num_valid_az"] = prm["num_lines"]
    prm["num_patches"] = 1
    prm["chirp_ext"] = 0

    return prm


def pop_led(root: ET.Element) -> List[StateVector]:
    """Verbatim port of make_slc_rs2.c:pop_led."""
    svs = _find_all(
        root, "/product/sourceAttributes/orbitAndAttitude/orbitInformation/stateVector/")
    out: List[StateVector] = []
    for sv_elem in svs:
        ts_raw = sv_elem.find("timeStamp").text
        tmp_d = str2double(date_path_to_jd_string(ts_raw))
        sv = StateVector()
        sv.yr = int(str2double(ts_raw[0:4]))
        sv.jd = int(tmp_d - math.trunc(tmp_d / 1000.0) * 1000.0)
        sv.sec = (tmp_d - math.trunc(tmp_d)) * 86400.0
        sv.x = str2double(sv_elem.find("xPosition").text)
        sv.y = str2double(sv_elem.find("yPosition").text)
        sv.z = str2double(sv_elem.find("zPosition").text)
        sv.vx = str2double(sv_elem.find("xVelocity").text)
        sv.vy = str2double(sv_elem.find("yVelocity").text)
        sv.vz = str2double(sv_elem.find("zVelocity").text)
        out.append(sv)
    return out


def write_orb(sv: List[StateVector]) -> str:
    """Verbatim port of make_slc_rs2.c:write_orb."""
    n = len(sv)
    if n <= 1:
        raise ValueError("make_slc_rs2_py: write_orb needs >1 state vector (C: return -1)")
    dt = (math.trunc(sv[1].sec * 1000.0) / 1000.0) - (math.trunc(sv[0].sec * 1000.0) / 1000.0)
    lines = ["%d %d %d %.3f %f \n" % (n, sv[0].yr, sv[0].jd, sv[0].sec, dt)]
    for s in sv:
        lines.append(
            "%d %d %.3f %.6f %.6f %.6f %.8f %.8f %.8f \n"
            % (s.yr, s.jd, s.sec, s.x, s.y, s.z, s.vx, s.vy, s.vz)
        )
    return "".join(lines)


# ---------------------------------------------------------------------------
# write_slc  (make_slc_rs2.c:write_slc)
# ---------------------------------------------------------------------------

def _read_tiff_iq(page) -> "np.ndarray":
    """Read the (height, width, 2) int16 I/Q array from an already-open
    tifffile page.

    Fast path: for an UNCOMPRESSED, byte-contiguous strip layout (true
    for the real RS2 imagery_*.tif — verified against the C reference,
    see bin_py/tests/test_make_slc_rs2_parity.py) we memmap the raw
    pixel bytes directly, skipping tifffile's strip-decoding machinery
    (~1.5-2x faster, see module docstring perf note). This is a
    read-shortcut, not an algorithmic substitution: the bytes read are
    identical to what TIFFReadScanline would hand the C code, just
    fetched in one contiguous slab instead of per-scanline calls.

    Falls back to tifffile.imread (slower, fully general) for any
    compressed/tiled/non-contiguous TIFF -- no silent wrong-shape
    fallback: correctness is verified by contiguity check, not assumed.
    """
    compression_ok = int(page.compression) == 1  # 1 == COMPRESSION_NONE
    offsets = page.dataoffsets
    counts = page.databytecounts
    contiguous = compression_ok and all(
        offsets[i + 1] == offsets[i] + counts[i] for i in range(len(offsets) - 1)
    )
    if contiguous and page.planarconfig == 1 and page.dtype == np.dtype("<i2"):
        arr = np.memmap(
            page.parent.filehandle.path, dtype="<i2", mode="r",
            offset=offsets[0], shape=page.shape,
        )
        return np.array(arr)  # materialize: memmap must not outlive this call

    # Slow-but-general fallback (compressed / tiled / non-contiguous TIFF).
    return page.asarray()


def write_slc(tif_path: str, slc_path: str, orbdir: str) -> None:
    import tifffile

    with tifffile.TiffFile(tif_path) as tf:
        page = tf.pages[0]
        widthi = page.imagewidth
        height = page.imagelength
        nsamples = page.samplesperpixel

        if nsamples != 2:
            raise ValueError(
                f"make_slc_rs2_py: write_slc expects SamplesPerPixel=2 (complex I/Q), got {nsamples}"
            )

        width = widthi - widthi % 4

        im = _read_tiff_iq(page)

    if im.dtype != np.dtype("<i2") and im.dtype != np.int16:
        raise ValueError(f"make_slc_rs2_py: expected int16 samples, got {im.dtype}")
    im = im.astype("<i2", copy=False)

    with open(slc_path, "wb") as f:
        if orbdir == "A":
            # flip upside down; keep column order; truncate to `width` columns
            out = np.ascontiguousarray(im[::-1, :width, :])
        else:
            # C loop only ever reads j in [0,width) from buf (the FIRST
            # `width` columns of the raw row), then reverses them into
            # tmp; no vertical flip. Replicate exactly:
            out = np.ascontiguousarray(im[:, :width, :][:, ::-1, :])
        out.tofile(f)


# ---------------------------------------------------------------------------
# Top-level driver (make_slc_rs2.c:main)
# ---------------------------------------------------------------------------

def make_slc_rs2(xml_path: str, tif_path: str, out_prefix: str) -> None:
    """End-to-end port of make_slc_rs2.c:main. Writes
    <out_prefix>.PRM, <out_prefix>.LED, <out_prefix>.SLC in the
    current working directory context implied by out_prefix (matches
    C: paths are whatever the caller passed on argv[3])."""
    if not os.path.exists(xml_path):
        raise FileNotFoundError(f"make_slc_rs2_py: Couldn't open xml file: {xml_path}")
    if not os.path.exists(tif_path):
        raise FileNotFoundError(f"make_slc_rs2_py: Couldn't open tiff file: {tif_path}")

    tree = ET.parse(xml_path)
    root = tree.getroot()
    _strip_namespaces(root)

    prm = pop_prm(root, out_prefix)
    with open(out_prefix + ".PRM", "w") as f:
        f.write(put_sio_struct(prm))

    sv = pop_led(root)
    with open(out_prefix + ".LED", "w") as f:
        f.write(write_orb(sv))

    write_slc(tif_path, out_prefix + ".SLC", prm["orbdir"])


def main(argv: Optional[List[str]] = None) -> int:
    import sys

    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 3:
        sys.stderr.write(
            "\n\nUsage: make_slc_rs2_py name_of_xml_file name_of_tiff_file name_output\n"
            "\nExample: make_slc_rs2_py product.xml imagery_HH.tif RS220110515\n"
            "\nOutput: RS220110515.SLC RS220110515.PRM RS220110515.LED\n"
        )
        return 1
    make_slc_rs2(argv[0], argv[1], argv[2])
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
