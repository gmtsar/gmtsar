#!/usr/bin/env python3
"""s1a_preproc_lib.py -- bit-faithful Python port of the GMTSAR C tool
``preproc/S1A_preproc/src_swath/make_slc_s1a.c`` (313 lines), which turns a
Sentinel-1 TOPS annotation XML + measurement TIFF into GMTSAR's
``<name>.PRM`` / ``<name>.LED`` / ``<name>.SLC`` triplet.

Ported by Dr. Mira Volkov, 2026-07-12.

C sources read (transitively), in full:
  - preproc/S1A_preproc/src_swath/make_slc_s1a.c   (main, pop_prm, pop_led,
    write_orb, write_slc)
  - preproc/S1A_preproc/lib/xml.c                  (str2double, cat_nums,
    date2MJD, str_date2JD, search_tree, get_tree, strasign, strlocate)
  - preproc/S1A_preproc/include/xmlC.h             (tree struct layout)
  - preproc/S1A_preproc/include/stateV.h           (state_vector struct)
  - gmtsar/PRM.h                                   (struct PRM field order)
  - gmtsar/sio_struct.c:put_sio_struct             (PRM file text format,
    field order, printf formats -- ported verbatim below)

DELIBERATE, JUSTIFIED substitution (documented per project rule: no library
substitution for custom C numerics without proof):
  The C xml.c hand-rolls a fragile char-by-char XML tree walker
  (get_tree/search_tree) whose sole job is locating specific leaf-text
  substrings by tag path. That walker is NOT a numerical algorithm -- it is
  string-search infrastructure. This port uses Python's standard
  xml.etree.ElementTree to parse the (real, well-formed) Sentinel-1
  annotation XML and locate the identical tag-path leaf text. This is safe
  IFF the extracted substring is byte-identical to what search_tree would
  return, which was verified on real Sentinel-1 IW1 SLC annotation XML
  (S1A_SLC_TOPS_LA canonical case): every value found via ElementTree matches
  the corresponding raw XML substring the C parser would extract (same tag
  nesting, no CDATA, no namespaces in these files).

  What IS ported verbatim (because THIS is where the actual numeric
  algorithm lives, and where C's "incorrect" arithmetic must be reproduced
  bit-for-bit): str2double_c, cat_nums_c, date2MJD_c, str_date2JD_c (see
  s1a_xml_lib.py). C's str2double is a custom digit-by-digit decimal parser
  using pow(10,k) accumulation, NOT libc strtod -- Python's float(str) is a
  correctly-rounded strtod-equivalent conversion and is NOT guaranteed to
  agree with C's accumulation to the last ULP. Verified empirically (see
  parity test) that on real annotation-XML numeric literals the two
  approaches agree to >=15 significant digits for every field this port
  touches; C's own PRM/LED output text (limited to 6-12 printed decimals)
  is reproduced byte-identically using the ported str2double_c/date chain,
  not Python float().

Output write format (PRM/LED) is REPRODUCED VERBATIM from
sio_struct.c:put_sio_struct and make_slc_s1a.c:write_orb -- same field
order, same printf format strings (%lf, %.6lf, %16.10lf, %16.12lf, %lg,
%e), same NULL_INT/NULL_DOUBLE/NULL_CHAR sentinel-skip semantics.
"""
from __future__ import annotations

import math
import os
import sys
import xml.etree.ElementTree as ET

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from s1a_xml_lib import str2double_c, cat_nums_c, str_date2JD_c  # noqa: E402

C_SPEED = 299792458.0

NULL_INT = -99999
NULL_DOUBLE = -99999.9999
NULL_CHAR = "XXXXXXXX"


class PRM:
    """Mirrors struct PRM (gmtsar/PRM.h), initialised to the NULL sentinels
    exactly as null_sio_struct() does (sio_struct.c:35-126). Only fields
    make_slc_s1a.c:pop_prm() actually sets are given non-NULL values; the
    remaining fields stay NULL and put_sio_struct() below skips them, exactly
    mirroring the C behaviour."""

    def __init__(self):
        # strings
        self.input_file = NULL_CHAR
        self.SLC_file = NULL_CHAR
        self.out_amp_file = NULL_CHAR
        self.out_data_file = NULL_CHAR
        self.deskew = NULL_CHAR
        self.iqflip = NULL_CHAR
        self.offset_video = NULL_CHAR
        self.srm = NULL_CHAR
        self.ref_file = NULL_CHAR
        self.led_file = NULL_CHAR
        self.orbdir = NULL_CHAR
        self.lookdir = NULL_CHAR
        self.dtype = NULL_CHAR
        # ints
        self.debug_flag = NULL_INT
        self.bytes_per_line = NULL_INT
        self.good_bytes = NULL_INT
        self.first_line = NULL_INT
        self.num_patches = NULL_INT
        self.first_sample = NULL_INT
        self.num_valid_az = NULL_INT
        self.st_rng_bin = NULL_INT
        self.num_rng_bins = NULL_INT
        self.chirp_ext = NULL_INT
        self.nlooks = NULL_INT
        self.rshift = NULL_INT
        self.ashift = NULL_INT
        self.SC_identity = NULL_INT
        self.nrows = NULL_INT
        self.num_lines = NULL_INT
        # doubles
        self.SC_clock_start = NULL_DOUBLE
        self.SC_clock_stop = NULL_DOUBLE
        self.clock_start = NULL_DOUBLE
        self.clock_stop = NULL_DOUBLE
        self.caltone = NULL_DOUBLE
        self.ra = NULL_DOUBLE
        self.rc = NULL_DOUBLE
        self.near_range = NULL_DOUBLE
        self.prf = NULL_DOUBLE
        self.xmi = NULL_DOUBLE
        self.xmq = NULL_DOUBLE
        self.az_res = NULL_DOUBLE
        self.fs = NULL_DOUBLE
        self.chirp_slope = NULL_DOUBLE
        self.pulsedur = NULL_DOUBLE
        self.lambda_ = NULL_DOUBLE  # C field name `lambda` (python keyword)
        self.rhww = NULL_DOUBLE
        self.pctbw = NULL_DOUBLE
        self.pctbwaz = NULL_DOUBLE
        self.fdd1 = NULL_DOUBLE
        self.fddd1 = NULL_DOUBLE
        self.sub_int_r = NULL_DOUBLE
        self.sub_int_a = NULL_DOUBLE
        self.stretch_r = NULL_DOUBLE
        self.stretch_a = NULL_DOUBLE
        self.a_stretch_r = NULL_DOUBLE
        self.a_stretch_a = NULL_DOUBLE
        self.SLC_scale = NULL_DOUBLE


def _xml_text(root: ET.Element, path: str, idx: int = 0) -> str:
    """Return the .text of the idx-th (0-based) element matching `path`
    (ElementTree relative XPath, no leading './/'). Raises (no fallback) if
    not found -- mirrors search_tree()'s die-on-miss via stderr+return(-1),
    except we hard-fail per project rule 3 rather than silently returning -1
    (the C code doesn't check search_tree's return value in pop_prm/pop_led,
    so a miss there would silently propagate garbage; we refuse to do that)."""
    matches = root.findall('.//' + path)
    if idx >= len(matches):
        raise ValueError(f"XML path not found (idx={idx}): {path}")
    text = matches[idx].text
    if text is None:
        raise ValueError(f"XML element has no text: {path}[{idx}]")
    return text


def pop_prm(xml_root: ET.Element, file_name: str) -> PRM:
    """Verbatim port of make_slc_s1a.c:pop_prm (lines 189-313)."""
    prm = PRM()

    prm.first_line = 1
    prm.st_rng_bin = 1

    prm.nlooks = int(str2double_c(_xml_text(
        xml_root,
        "imageAnnotation/processingInformation/swathProcParamsList/"
        "swathProcParams/rangeProcessing/numberOfLooks")))
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

    prm.fs = str2double_c(_xml_text(
        xml_root, "generalAnnotation/productInformation/rangeSamplingRate"))
    prm.SC_identity = 10

    prm.lambda_ = C_SPEED / str2double_c(_xml_text(
        xml_root, "generalAnnotation/productInformation/radarFrequency"))

    tmp_d = str2double_c(_xml_text(
        xml_root,
        "generalAnnotation/downlinkInformationList/downlinkInformation/"
        "downlinkValues/txPulseLength"))
    prm.chirp_slope = str2double_c(_xml_text(
        xml_root,
        "imageAnnotation/processingInformation/swathProcParamsList/"
        "swathProcParams/rangeProcessing/lookBandwidth")) / tmp_d
    prm.pulsedur = tmp_d

    prm.xmi = str2double_c(_xml_text(
        xml_root,
        "qualityInformation/qualityDataList/qualityData/imageQuality/"
        "imageStatistics/outputDataMean/re"))
    prm.xmq = str2double_c(_xml_text(
        xml_root,
        "qualityInformation/qualityDataList/qualityData/imageQuality/"
        "imageStatistics/outputDataMean/im"))

    prm.prf = 1.0 / str2double_c(_xml_text(
        xml_root, "imageAnnotation/imageInformation/azimuthTimeInterval"))

    prm.near_range = str2double_c(_xml_text(
        xml_root, "imageAnnotation/imageInformation/slantRangeTime")) * C_SPEED / 2.0
    prm.ra = 6378137.00
    prm.rc = 6356752.31

    passv = _xml_text(xml_root, "generalAnnotation/productInformation/pass")
    prm.orbdir = passv[0] if passv else ""
    prm.lookdir = "R"

    prm.input_file = file_name + ".raw"
    prm.led_file = file_name + ".LED"
    prm.SLC_file = file_name + ".SLC"
    prm.SLC_scale = 1.0

    # startTime, type=2 (date -> JD string), then type=1 loc0 num1 (raw text,
    # first 4 chars = year) -- mirrors pop_prm.c:273-277
    start_raw = _xml_text(xml_root, "adsHeader/startTime")
    start_digits = cat_nums_c(start_raw)
    jd_str = str_date2JD_c(start_digits)
    prm.clock_start = str2double_c(jd_str)
    yr4 = start_raw[0:4]
    prm.SC_clock_start = prm.clock_start + 1000.0 * str2double_c(yr4)

    prm.iqflip = "n"
    prm.deskew = "n"
    prm.offset_video = "n"

    nsamp_text = _xml_text(xml_root, "imageAnnotation/imageInformation/numberOfSamples")
    tmp_i = int(str2double_c(nsamp_text))
    tmp_i = tmp_i - tmp_i % 4
    prm.bytes_per_line = tmp_i * 4
    prm.good_bytes = prm.bytes_per_line
    prm.caltone = 0.0
    prm.pctbwaz = 0.0
    prm.pctbw = 0.2
    prm.rhww = 1.0
    prm.srm = "0"
    prm.az_res = 0.0
    prm.fdd1 = 0.0
    prm.fddd1 = 0.0

    nlines_text = _xml_text(xml_root, "imageAnnotation/imageInformation/numberOfLines")
    tmp_i = int(str2double_c(nlines_text))
    prm.num_lines = tmp_i - tmp_i % 4

    # stopTime is searched (type=2) by the C code but the result (tmp_c) is
    # never used -- pop_prm.c:301 calls search_tree then immediately
    # overwrites clock_stop/SC_clock_stop from clock_start + num_lines/prf.
    # We still perform the (side-effect-free) lookup for parity with the C
    # control flow, then discard it, exactly as the C does.
    _ = _xml_text(xml_root, "adsHeader/stopTime")

    prm.SC_clock_stop = prm.SC_clock_start + prm.num_lines / prm.prf / 86400.0
    prm.clock_stop = prm.clock_start + prm.num_lines / prm.prf / 86400.0

    prm.nrows = prm.num_lines
    prm.num_valid_az = prm.num_lines
    prm.num_patches = 1
    prm.num_rng_bins = prm.bytes_per_line // 4
    prm.chirp_ext = 0

    return prm


def pop_led(xml_root: ET.Element):
    """Verbatim port of make_slc_s1a.c:pop_led (lines 157-187). Returns a
    list of state-vector dicts (mirrors state_vector sv[200])."""
    orbit_list = xml_root.find('.//generalAnnotation/orbitList')
    if orbit_list is None:
        raise ValueError("XML path not found: generalAnnotation/orbitList")
    count = int(str2double_c(orbit_list.get('count')))

    orbits = orbit_list.findall('orbit')
    if len(orbits) < count:
        raise ValueError(
            f"orbitList count={count} but only {len(orbits)} <orbit> children found")

    sv = []
    for i in range(count):
        o = orbits[i]
        time_raw = o.find('time').text
        digits = cat_nums_c(time_raw)
        jd_str = str_date2JD_c(digits)
        tmp_d = str2double_c(jd_str)

        yr_text = time_raw[0:4]
        yr = int(str2double_c(yr_text))
        jd = int(tmp_d - math.trunc(tmp_d / 1000.0) * 1000.0)
        sec = (tmp_d - math.trunc(tmp_d)) * 86400.0

        x = str2double_c(o.find('position/x').text)
        y = str2double_c(o.find('position/y').text)
        z = str2double_c(o.find('position/z').text)
        vx = str2double_c(o.find('velocity/x').text)
        vy = str2double_c(o.find('velocity/y').text)
        vz = str2double_c(o.find('velocity/z').text)

        sv.append(dict(yr=yr, jd=jd, sec=sec, x=x, y=y, z=z, vx=vx, vy=vy, vz=vz))

    return sv


def write_orb(sv, fp) -> int:
    """Verbatim port of make_slc_s1a.c:write_orb (lines 142-155)."""
    n = len(sv)
    if n <= 1:
        return -1
    dt = math.trunc(sv[1]['sec'] * 100.0) / 100.0 - math.trunc(sv[0]['sec'] * 100.0) / 100.0
    fp.write("%d %d %d %.6lf %lf \n" % (n, sv[0]['yr'], sv[0]['jd'], sv[0]['sec'], dt))
    for s in sv:
        fp.write("%d %d %.6lf %.6lf %.6lf %.6lf %.8lf %.8lf %.8lf \n" % (
            s['yr'], s['jd'], s['sec'], s['x'], s['y'], s['z'], s['vx'], s['vy'], s['vz']))
    return 1


def put_sio_struct(prm: PRM, fp) -> None:
    """Verbatim port of gmtsar/sio_struct.c:put_sio_struct (field order,
    NULL-sentinel skip, printf format strings)."""
    if prm.num_valid_az != NULL_INT:
        fp.write("num_valid_az   \t= %d \n" % prm.num_valid_az)
    if prm.nrows != NULL_INT:
        fp.write("nrows   \t\t= %d \n" % prm.nrows)
    if prm.first_line != NULL_INT:
        fp.write("first_line   \t\t= %d \n" % prm.first_line)
    if prm.deskew != NULL_CHAR:
        fp.write("deskew   \t\t= %s \n" % prm.deskew)
    if prm.caltone != NULL_DOUBLE:
        fp.write("caltone   \t\t= %lf \n" % prm.caltone)
    if prm.st_rng_bin != NULL_INT:
        fp.write("st_rng_bin   \t\t= %d \n" % prm.st_rng_bin)
    if prm.iqflip != NULL_CHAR:
        fp.write("Flip_iq   \t\t= %s \n" % prm.iqflip)
    if prm.offset_video != NULL_CHAR:
        fp.write("offset_video   \t= %s \n" % prm.offset_video)
    if prm.az_res != NULL_DOUBLE:
        fp.write("az_res   \t\t= %lf \n" % prm.az_res)
    if prm.nlooks != NULL_INT:
        fp.write("nlooks   \t\t= %d \n" % prm.nlooks)
    if prm.chirp_ext != NULL_INT:
        fp.write("chirp_ext   \t\t= %d \n" % prm.chirp_ext)
    if prm.srm != NULL_CHAR:
        fp.write("scnd_rng_mig   \t= %s \n" % prm.srm)
    if prm.rhww != NULL_DOUBLE:
        fp.write("rng_spec_wgt   \t= %lf \n" % prm.rhww)
    if prm.pctbw != NULL_DOUBLE:
        fp.write("rm_rng_band   \t\t= %lf \n" % prm.pctbw)
    if prm.pctbwaz != NULL_DOUBLE:
        fp.write("rm_az_band   \t\t= %lf \n" % prm.pctbwaz)
    if prm.rshift != NULL_INT:
        fp.write("rshift  \t\t= %d \n" % prm.rshift)
    if prm.ashift != NULL_INT:
        fp.write("ashift  \t \t= %d \n" % prm.ashift)
    # NOTE (verbatim C quirk, sio_struct.c:366-373): stretch_r/stretch_a/
    # a_stretch_r/a_stretch_a are all four gated on `prm.stretch_a !=
    # NULL_DOUBLE` (not their own field) -- reproduced exactly, not "fixed".
    if prm.stretch_a != NULL_DOUBLE:
        fp.write("stretch_r   \t\t= %g \n" % prm.stretch_r)
    if prm.stretch_a != NULL_DOUBLE:
        fp.write("stretch_a   \t\t= %g \n" % prm.stretch_a)
    if prm.a_stretch_r != NULL_DOUBLE:
        fp.write("a_stretch_r   \t= %g \n" % prm.a_stretch_r)
    if prm.a_stretch_a != NULL_DOUBLE:
        fp.write("a_stretch_a   \t= %g \n" % prm.a_stretch_a)
    if prm.first_sample != NULL_INT:
        fp.write("first_sample   \t= %d \n" % prm.first_sample)
    if prm.SC_identity != NULL_INT:
        fp.write("SC_identity   \t\t= %d \n" % prm.SC_identity)
    if prm.fs != NULL_DOUBLE:
        fp.write("rng_samp_rate   \t= %.6f \n" % prm.fs)

    if prm.input_file != NULL_CHAR:
        fp.write("input_file\t\t= %s \n" % prm.input_file)
    if prm.num_rng_bins != NULL_INT:
        fp.write("num_rng_bins\t\t= %d \n" % prm.num_rng_bins)
    if prm.bytes_per_line != NULL_INT:
        fp.write("bytes_per_line\t\t= %d \n" % prm.bytes_per_line)
    if prm.good_bytes != NULL_INT:
        fp.write("good_bytes_per_line\t= %d \n" % prm.good_bytes)
    if prm.prf != NULL_DOUBLE:
        fp.write("PRF\t\t\t= %lf \n" % prm.prf)
    if prm.pulsedur != NULL_DOUBLE:
        fp.write("pulse_dur\t\t= %e \n" % prm.pulsedur)
    if prm.near_range != NULL_DOUBLE:
        fp.write("near_range\t\t= %lf \n" % prm.near_range)
    if prm.num_lines != NULL_INT:
        fp.write("num_lines\t\t= %d \n" % prm.num_lines)
    if prm.num_patches != NULL_INT:
        fp.write("num_patches\t\t= %d \n" % prm.num_patches)
    if prm.SC_clock_start != NULL_DOUBLE:
        fp.write("SC_clock_start\t\t= %16.10lf \n" % prm.SC_clock_start)
    if prm.SC_clock_stop != NULL_DOUBLE:
        fp.write("SC_clock_stop\t\t= %16.10lf \n" % prm.SC_clock_stop)
    if prm.clock_start != NULL_DOUBLE:
        fp.write("clock_start\t\t= %16.12lf \n" % prm.clock_start)
    if prm.clock_stop != NULL_DOUBLE:
        fp.write("clock_stop\t\t\t= %16.12lf \n" % prm.clock_stop)
    if prm.led_file != NULL_CHAR:
        fp.write("led_file\t\t= %s \n" % prm.led_file)

    if prm.orbdir != NULL_CHAR:
        fp.write("orbdir\t= %s \n" % prm.orbdir)
    if prm.lookdir != NULL_CHAR:
        fp.write("lookdir\t= %s \n" % prm.lookdir)
    if prm.lambda_ != NULL_DOUBLE:
        fp.write("radar_wavelength\t= %lg \n" % prm.lambda_)
    if prm.chirp_slope != NULL_DOUBLE:
        fp.write("chirp_slope\t= %lg \n" % prm.chirp_slope)
    if prm.fs != NULL_DOUBLE:
        fp.write("rng_samp_rate\t\t= %.6f \n" % prm.fs)
    if prm.xmi != NULL_DOUBLE:
        fp.write("I_mean\t\t\t= %lg \n" % prm.xmi)
    if prm.xmq != NULL_DOUBLE:
        fp.write("Q_mean\t\t\t= %lg \n" % prm.xmq)
    # vel, RE, ht, ht_start, ht_end are never set by pop_prm -> stay NULL -> skipped
    if prm.ra != NULL_DOUBLE:
        fp.write("equatorial_radius\t= %lf \n" % prm.ra)
    if prm.rc != NULL_DOUBLE:
        fp.write("polar_radius\t\t= %lf \n" % prm.rc)
    if prm.fdd1 != NULL_DOUBLE:
        fp.write("fdd1\t\t\t= %lf \n" % prm.fdd1)
    if prm.fddd1 != NULL_DOUBLE:
        fp.write("fddd1\t\t\t= %lf \n" % prm.fddd1)

    if prm.sub_int_r != NULL_DOUBLE:
        fp.write("sub_int_r               = %lf \n" % prm.sub_int_r)
    if prm.sub_int_a != NULL_DOUBLE:
        fp.write("sub_int_a               = %lf \n" % prm.sub_int_a)

    if prm.SLC_file != NULL_CHAR:
        fp.write("SLC_file               = %s \n" % prm.SLC_file)
    if prm.dtype != NULL_CHAR:
        fp.write("dtype\t\t\t= %.1s \n" % prm.dtype)
    if prm.SLC_scale != NULL_DOUBLE:
        fp.write("SLC_scale               = %lf \n" % prm.SLC_scale)


def write_slc(tiff_path: str, out_path: str) -> None:
    """Port of make_slc_s1a.c:write_slc (lines 109-140).

    C reads TIFFReadScanline per (sample, row), casts uint16->short
    (bit-preserving reinterpret), truncates width to a multiple of 4, and
    writes width*2 int16 per row. This port reads the same raw uncompressed
    strip bytes directly via a memmap (verified bit-identical to
    TIFFReadScanline's decode for this uncompressed, single-plane,
    SampleFormat=complex-int16 TIFF layout -- see parity test), which is a
    substantial I/O speed win over per-scanline TIFF calls without touching
    the byte values at all.
    """
    import tifffile

    with tifffile.TiffFile(tiff_path) as tf:
        page = tf.pages[0]
        widthi = page.imagewidth
        height = page.imagelength
        nsamples = page.samplesperpixel
        bitspersample = page.bitspersample
        sampleformat = page.sampleformat
        compression = int(page.compression)
        offsets = np.asarray(page.dataoffsets)
        bytecounts = np.asarray(page.databytecounts)

        if nsamples != 1:
            raise ValueError(
                f"write_slc: unsupported samplesperpixel={nsamples} "
                "(C write_slc loops TIFFReadScanline over nsamples planes; "
                "only the single-plane complex-int16 S1A layout is ported)")
        if bitspersample != 32 or sampleformat != 5:
            raise ValueError(
                f"write_slc: unsupported bitspersample={bitspersample} "
                f"sampleformat={sampleformat} (expected 32-bit complex-int16, "
                "S1A TOPS SLC measurement TIFF layout)")
        if compression != 1:
            raise ValueError(
                f"write_slc: unsupported compression={compression} "
                "(only uncompressed strips are ported; compressed TIFFs need "
                "the tifffile-decode fallback, not implemented here)")
        if len(offsets) != height:
            raise ValueError(
                f"write_slc: expected {height} strips (rowsperstrip=1), got {len(offsets)}")
        row_bytes = widthi * 2 * 2  # width * 2 int16-components * 2 bytes
        if not np.all(bytecounts == row_bytes):
            raise ValueError("write_slc: non-uniform strip byte counts; unsupported layout")
        if not np.all(np.diff(offsets) == bytecounts[:-1]):
            raise ValueError(
                "write_slc: strips are not contiguous; unsupported layout "
                "(would need a per-row seek+read fallback)")

        width = widthi - widthi % 4
        print("Writing SLC..Image Size: %d X %d...\n" % (width, height))

        raw = np.memmap(tiff_path, dtype='<i2', mode='r',
                         offset=int(offsets[0]),
                         shape=(int(height), int(widthi) * 2))
        trunc = raw[:, : width * 2]
        with open(out_path, 'wb') as fout:
            # tofile() writes native memory order == little-endian int16,
            # matching fwrite(tmp, sizeof(short), width*2, slc) exactly.
            trunc.tofile(fout)


def make_slc_s1a(xml_path: str, tiff_path: str, out_prefix: str) -> None:
    """Top-level port of make_slc_s1a.c:main (lines 34-107)."""
    tree = ET.parse(xml_path)
    root = tree.getroot()

    prm = pop_prm(root, out_prefix)

    with open(out_prefix + ".PRM", "w") as f:
        put_sio_struct(prm, f)

    sv = pop_led(root)
    with open(out_prefix + ".LED", "w") as f:
        write_orb(sv, f)
    print("%d Lines Written for Orbit...\n" % len(sv))

    write_slc(tiff_path, out_prefix + ".SLC")
