"""
Python port of the RAW-DATA PARSING core of ALOS_pre_process.c
(preproc/ALOS_preproc/ALOS_pre_process/ALOS_pre_process.c + read_ALOS_data.c
+ swap_ALOS_data_info.c), scoped to the AUIG (ALOS_format == 0) CEOS raw
image path.

SCOPE / KNOWN GAP (read this before trusting this module for anything but
the .raw byte stream and the header-derived PRM fields listed below):

  This module reproduces ONLY the part of ALOS_pre_process that can be
  computed from the IMG (raw signal data) file alone:

    - CEOS IMG-file header validation (720-byte file header:
      sardata_record + sardata_descriptor)
    - per-line sardata_info (412-byte) prefix parse + SELECTIVE big/little
      -endian byte swap (mirrors swap_ALOS_data_info.c field-by-field,
      INCLUDING the C quirk that elec_antenna_elevation_angle and
      mech_antenna_elevation_angle are never swapped)
    - near_range-drift shift/fill logic (check_shift / fill_shift_data),
      including the exact Marsaglia MWC pseudo-random fill byte stream
      used for NULL_DATA gap filling
    - num_lines / num_patches / clock_start / clock_stop bookkeeping
    - byte-exact <IMG>.raw output file

  It does NOT port:
    - read_ALOS_sarleader.c (455 lines: full CEOS LED-file ASCII
      fixed-field parser -- hundreds of %Nc fields)
    - ALOS_ldr_orbit.c (Hermite orbit interpolation -> SC_vel,
      SC_height*, earth_radius, equatorial/polar radius)
    - calc_dop.c (FFT-based Doppler-centroid estimate -> fd1/fdd1/fddd1)
    - write_ALOS_LED.c / roi_utils.c / write_ALOS_prm.c

  Consequence: the PRM fields lambda, chirp coefficients pre-override,
  xmi/xmq, orbdir, lookdir, date, ra/rc, SC_vel, SC_height*, earth_radius,
  fd1/fdd1/fddd1 are UNAVAILABLE from this module and are NOT produced.
  Only the fields listed in `RawParseResult` below are parity-verified.

  This is an intentional, documented partial port -- see the parity test
  in gmtsar/python/bin_py/tests/test_alos_pre_process_py.py and the
  handoff note at the bottom of this file. Per project rule (no wire-in
  behind a known parity gap), this module is NOT wired into any
  GMTSAR_* env-gated dispatcher.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, List, Tuple

SOL = 299792456.0
NULL_DATA = 15
HEADER_SIZE = 720          # sizeof(sardata_record) + sizeof(sardata_descriptor)
LINE_PREFIX_SIZE = 412     # sizeof(sardata_info)
RECORD_HDR_SIZE = 12       # sizeof(sardata_record)

# ---------------------------------------------------------------------------
# sardata_info (412 bytes), big-endian on-disk layout, C-struct field order.
# Field: (name, offset, size, is_swapped)
# Offsets/padding verified against `sizeof(struct sardata_info) == 412`
# compiled with the project's actual gcc/target ABI (see worktree notes).
# ---------------------------------------------------------------------------
_SDR_FIELDS: List[Tuple[str, int, int, bool]] = [
    ("sequence_number", 0, 4, True),
    ("subtype", 4, 4, False),
    ("record_length", 8, 4, True),
    ("data_line_number", 12, 4, True),
    ("data_record_index", 16, 4, True),
    ("n_left_fill_pixels", 20, 4, True),
    ("n_data_pixels", 24, 4, True),
    ("n_right_fill_pixels", 28, 4, True),
    ("sensor_update_flag", 32, 4, True),
    ("sensor_acquisition_year", 36, 4, True),
    ("sensor_acquisition_DOY", 40, 4, True),
    ("sensor_acquisition_msecs_day", 44, 4, True),
    ("channel_indicator", 48, 2, True),
    ("channel_code", 50, 2, True),
    ("transmit_polarization", 52, 2, True),
    ("receive_polarization", 54, 2, True),
    ("PRF", 56, 4, True),
    ("scan_ID", 60, 4, True),
    ("onboard_range_compress", 64, 2, True),
    ("chirp_type", 66, 2, True),
    ("chirp_length", 68, 4, True),
    ("chirp_constant_coeff", 72, 4, True),
    ("chirp_linear_coeff", 76, 4, True),
    ("chirp_quad_coeff", 80, 4, True),
    ("spare1", 84, 4, False),
    ("spare2", 88, 4, False),
    ("receiver_gain", 92, 4, True),
    # C QUIRK (swap_ALOS_data_info.c:19): nought_line_flag is declared `int`
    # (4 bytes) in struct sardata_info, but the swap code calls
    # FIX_SHORT(sdr->nought_line_flag) -- an `unsigned short*` reinterpret
    # cast -- so only the FIRST 2 bytes of this 4-byte field get
    # byte-reversed; the trailing 2 bytes pass through untouched. This is a
    # verbatim bug in the C reference and MUST be reproduced bit-for-bit
    # (see _SWAP_SLICES below, which overrides this field's generic 4-byte
    # entry with the correct 2-byte-only swap).
    ("nought_line_flag", 96, 4, False),
    ("elec_antenna_elevation_angle", 100, 4, False),  # NOT swapped in C -- verbatim quirk
    ("mech_antenna_elevation_angle", 104, 4, False),  # NOT swapped in C -- verbatim quirk
    ("elec_antenna_squint_angle", 108, 4, True),
    ("mech_antenna_squint_angle", 112, 4, True),
    ("slant_range", 116, 4, True),
    ("data_record_window_position", 120, 4, True),
    ("spare3", 124, 4, False),
    ("platform_update_flag", 128, 2, True),
    # 2 bytes of compiler padding at [130:132] before the next (4-byte
    # aligned) int field -- never touched, copied through unchanged.
    ("platform_latitude", 132, 4, True),
    ("platform_longitude", 136, 4, True),
    ("platform_altitude", 140, 4, True),
    ("platform_ground_speed", 144, 4, True),
    ("platform_velocity_x", 148, 4, True),
    ("platform_velocity_y", 152, 4, True),
    ("platform_velocity_z", 156, 4, True),
    ("platform_acc_x", 160, 4, True),
    ("platform_acc_y", 164, 4, True),
    ("platform_acc_z", 168, 4, True),
    ("platform_track_angle_1", 172, 4, True),
    ("platform_track_angle_2", 176, 4, True),
    ("platform_pitch_angle", 180, 4, True),
    ("platform_roll_angle", 184, 4, True),
    ("platform_yaw_angle", 188, 4, True),
    ("blank1", 192, 92, False),
    ("frame_counter", 284, 4, True),   # swapped only when ALOS_format == 0 (this module's scope)
    ("PALSAR_aux_data", 288, 100, False),
    ("blank2", 388, 24, False),
]
assert _SDR_FIELDS[-1][1] + _SDR_FIELDS[-1][2] == LINE_PREFIX_SIZE

_INT_FIELDS = {n: (o, s) for n, o, s, sw in _SDR_FIELDS if sw}
_SWAP_SLICES = [(o, o + s) for _, o, s, sw in _SDR_FIELDS if sw]
# nought_line_flag: only the first 2 of its 4 bytes are byte-reversed
# (FIX_SHORT applied to an int field -- see comment above). offset 96-97.
_SWAP_SLICES.append((96, 98))


def _bswap(raw: bytearray, offsets):
    """In-place byte-reversal of the given (start, end) slices of `raw`.

    This is bit-identical to the C idiom
        FIX_INT(x)  == *(unsigned int*)&x  = SWAP_4(*(unsigned int*)&x)
    on a little-endian host: reversing the raw byte order of a field that
    was written big-endian on disk yields exactly the little-endian
    encoding of that same integer value.
    """
    for a, b in offsets:
        raw[a:b] = raw[a:b][::-1]


def _get_i4(raw: bytes, name: str) -> int:
    o, s = _INT_FIELDS[name]
    assert s == 4
    return struct.unpack_from(">i", raw, o)[0]


# ---------------------------------------------------------------------------
# Marsaglia multiply-with-carry PRNG, verbatim port of the C code in
# read_ALOS_data.c:
#     #define znew (int)(z = 36969*(z & 65535) + (z >> 16))
#     static UL z = 362436069;
#     void settable(UL i1) { z = i1; for i in 0..255: t[i] = znew; }
# On this platform `unsigned long` is 64-bit, but the MWC recurrence keeps
# z within [0, 2^32) by construction, so plain Python ints reproduce it
# exactly. The recurrence is a linear congruential generator modulo
# m = 36969*65536 - 1 (classic MWC/LCG equivalence), which lets us jump
# ahead in O(log n) via modular exponentiation instead of an O(n) Python
# loop over hundreds of millions of fill bytes.
# ---------------------------------------------------------------------------
_MWC_A = 36969
_MWC_M = _MWC_A * 65536 - 1


class ALOSFillPRNG:
    """Exact replica of read_ALOS_data.c's global `z` PRNG state machine."""

    def __init__(self, seed: int = 12345):
        # settable(12345): z = 12345, then discard 256 znew draws.
        z = seed
        z = (pow(_MWC_A, 256, _MWC_M) * z) % _MWC_M
        self.z = z

    def next_bits(self, n: int) -> bytes:
        """Return n bytes, each NULL_DATA + (znew % 2), consuming n PRNG
        draws in the same order the C loop would (one znew() call per
        output byte).

        C QUIRK: `znew` expands to `(int)(z = ...)` -- z (unsigned long,
        64-bit here, but bounded < 2^32 by the MWC recurrence) is cast to
        a 32-bit *signed* int before the `% 2`. C's `%` truncates toward
        zero, so for a negative znew (low32 bit 31 set) that is odd, the
        result is -1, not +1 -- giving NULL_DATA - 1 == 14, not
        NULL_DATA + 1 == 16. Python's `%` would silently give +1 here
        (floor semantics), which is exactly the "silent substitution"
        failure mode this port must not have. Reproduced explicitly below.
        """
        if n <= 0:
            return b""
        z = self.z
        out = bytearray(n)
        for k in range(n):
            z = (_MWC_A * z) % _MWC_M
            bit = z & 1
            if bit and z >= 0x80000000:
                out[k] = NULL_DATA - 1
            else:
                out[k] = NULL_DATA + bit
        self.z = z
        return bytes(out)


@dataclass
class RawParseResult:
    """PRM fields fully determined by the IMG-file-only parsing path.
    Field names match struct PRM (image_sio.h) verbatim where applicable."""

    num_rng_bins: int = 0
    bytes_per_line: int = 0
    good_bytes: int = 0
    first_sample: int = 206
    prf: float = 0.0             # PRM.prf (kHz -> Hz, 0.001 scale applied like C)
    pulsedur: float = 0.0
    near_range: float = 0.0
    num_lines: int = 0
    num_patches: int = 0
    SC_clock_start: float = 0.0
    SC_clock_stop: float = 0.0
    clock_start: float = 0.0
    clock_stop: float = 0.0
    chirp_ext: int = 1000
    n_data_pixels: int = 0
    warnings: list = field(default_factory=list)


def _get_clock(sensor_acquisition_DOY: int, sensor_acquisition_msecs_day: int, tbias: float) -> float:
    return sensor_acquisition_DOY + sensor_acquisition_msecs_day / 1000.0 / 86400.0 + tbias / 86400.0


def read_alos_raw(
    img_path: str,
    out_raw_path: str,
    *,
    fs: float = 3.2e7,
    near_range_override: float = -1.0,
    num_valid_az: int = 9216,
    num_patches_default: int = 1000,
    tbias_cmdline: float = 0.0,
    verbose: bool = False,
) -> RawParseResult:
    """Port of read_ALOS_data() for ALOS_format == 0 (AUIG), no PRF change.

    Raises RuntimeError (mirroring C's die()) on the same hard-failure
    conditions the C code checks (header size, record_length mismatch,
    PRF change mid-file, shift exceeding data window).
    """
    tbias = tbias_cmdline - 0.0020835  # matches main(): tbias -= 0.0020835

    img_path = str(img_path)
    out_raw_path = str(out_raw_path)

    with open(img_path, "rb") as f:
        header = f.read(HEADER_SIZE)
        if len(header) != HEADER_SIZE:
            raise RuntimeError(f"header size is not 720 bytes (got {len(header)})")

        first_sdr_raw = f.read(LINE_PREFIX_SIZE)
        if len(first_sdr_raw) != LINE_PREFIX_SIZE:
            raise RuntimeError("truncated file: could not read first sardata_info")

        # --- assign_sardata_params (uses the FIRST post-header record) ---
        n_data_pixels = _get_i4(first_sdr_raw, "n_data_pixels")
        record_length_first = _get_i4(first_sdr_raw, "record_length")
        chirp_length = _get_i4(first_sdr_raw, "chirp_length")
        slant_range_first = _get_i4(first_sdr_raw, "slant_range")
        sensor_acq_year0 = _get_i4(first_sdr_raw, "sensor_acquisition_year")
        sensor_doy0 = _get_i4(first_sdr_raw, "sensor_acquisition_DOY")
        sensor_msec0 = _get_i4(first_sdr_raw, "sensor_acquisition_msecs_day")
        prf_first = _get_i4(first_sdr_raw, "PRF")

        record_length0 = record_length_first - LINE_PREFIX_SIZE
        if record_length0 > 50000:
            raise RuntimeError(
                f"record_length is {record_length0} ! expect ~21100 .... try -swap option?"
            )

        chirp_ext = 500 if fs < 17000000.0 else 1000
        # NOTE: main() sets chirp_ext=500/chirp_slope only as a *side effect* of
        # the fs<17e6 branch check; chirp_ext otherwise stays at the
        # set_ALOS_defaults() value of 1000. We mirror exactly: only override
        # to 500 in the fs<17e6 branch, matching prm.chirp_ext = 500 in C.
        if fs >= 17000000.0:
            chirp_ext = 1000

        num_rng_bins = n_data_pixels + chirp_ext
        bytes_per_line = record_length_first
        line_prefix_size = LINE_PREFIX_SIZE
        good_bytes = 2 * n_data_pixels + line_prefix_size
        line_suffix_size = record_length_first - good_bytes

        near_range = near_range_override if near_range_override >= 0 else float(slant_range_first)
        clock_start = _get_clock(sensor_doy0, sensor_msec0, tbias)
        SC_clock_start = sensor_acq_year0 * 1000.0 + clock_start

        # --- main read loop: rewind to header, read every sardata_info ---
        f.seek(HEADER_SIZE)
        prng = ALOSFillPRNG(seed=12345)

        n = 1
        shift0 = 0
        start_sdr_rec_len = None
        slant_range_old = 0
        last_sdr_raw = None
        warnings: List[str] = []

        with open(out_raw_path, "wb") as out:
            while True:
                sdr_raw_orig = f.read(LINE_PREFIX_SIZE)
                if len(sdr_raw_orig) != LINE_PREFIX_SIZE:
                    break
                n += 1

                record_length = _get_i4(sdr_raw_orig, "record_length")
                sequence_number = _get_i4(sdr_raw_orig, "sequence_number")
                prf_val = _get_i4(sdr_raw_orig, "PRF")
                slant_range = _get_i4(sdr_raw_orig, "slant_range")

                if n == 2:
                    start_sdr_rec_len = record_length

                sdr_raw = bytearray(sdr_raw_orig)
                if record_length != start_sdr_rec_len:
                    warnings.append(f"warning sdr.record_length error {record_length}")
                    record_length = start_sdr_rec_len
                    prf_val = int(round(prf_first))
                    slant_range = slant_range_old
                    struct.pack_into(">i", sdr_raw, _INT_FIELDS["record_length"][0], record_length)
                    struct.pack_into(">i", sdr_raw, _INT_FIELDS["PRF"][0], prf_val)
                    struct.pack_into(">i", sdr_raw, _INT_FIELDS["slant_range"][0], slant_range)

                if sequence_number != n:
                    warnings.append(f"missing line: n, seq# {n} {sequence_number}")

                record_length1 = record_length - line_prefix_size
                if record_length0 != record_length1:
                    raise RuntimeError("record_length changed")

                if prf_val != prf_first:
                    # handle_prf_change: not supported by this scoped port.
                    raise RuntimeError(
                        f"PRF changed from {0.001*prf_first} to {0.001*prf_val} at line {n} "
                        "-- multi-PRF-segment files are out of scope for this port"
                    )

                shift = 2 * _c_floor(0.5 + (slant_range - near_range) / (0.5 * SOL / fs))
                ishift = abs(shift)
                if ishift > record_length1:
                    raise RuntimeError(f"end: shift exceeds data window {shift}")
                if shift != shift0:
                    shift0 = shift

                data = f.read(record_length1)
                if len(data) != record_length1:
                    break

                # perform the selective byte-swap on the OUTPUT header copy
                _bswap(sdr_raw, _SWAP_SLICES)

                slant_range_old = slant_range
                last_sdr_raw = sdr_raw_orig

                out.write(sdr_raw)
                if shift == 0:
                    out.write(data)
                else:
                    out.write(_fill_shift_data(shift, ishift, data, line_suffix_size, record_length1, prng))

        if last_sdr_raw is None:
            raise RuntimeError("no data lines read")

        prf_out = 0.001 * prf_first
        sensor_acq_year_last = _get_i4(last_sdr_raw, "sensor_acquisition_year")
        doy_last = _get_i4(last_sdr_raw, "sensor_acquisition_DOY")
        msec_last = _get_i4(last_sdr_raw, "sensor_acquisition_msecs_day")
        clock_stop = _get_clock(doy_last, msec_last, tbias)
        SC_clock_stop = sensor_acq_year_last * 1000.0 + clock_stop

        num_lines = n - 1
        if num_lines == 0:
            num_lines = 1
        npatch_max = int((1.0 * n) / (1.0 * num_valid_az))
        num_patches = min(npatch_max, num_patches_default)

        return RawParseResult(
            num_rng_bins=num_rng_bins,
            bytes_per_line=bytes_per_line,
            good_bytes=good_bytes,
            first_sample=206,
            prf=prf_out,
            pulsedur=1e-9 * chirp_length,
            near_range=near_range,
            num_lines=num_lines,
            num_patches=num_patches,
            SC_clock_start=SC_clock_start,
            SC_clock_stop=SC_clock_stop,
            clock_start=clock_start,
            clock_stop=clock_stop,
            chirp_ext=chirp_ext,
            n_data_pixels=n_data_pixels,
            warnings=warnings,
        )


def _c_floor(x: float) -> int:
    """C's floor() truncated by the implicit (int) cast context in
    `2 * floor(0.5 + ...)` -- floor() then implicit double->int assigned to
    the `int shift` local. floor() itself already returns an integral
    double; math.floor gives the same result as C floor() to the ULP."""
    import math
    return int(math.floor(x))


def _fill_shift_data(shift: int, ishift: int, data: bytes, line_suffix_size: int,
                      record_length1: int, prng: ALOSFillPRNG) -> bytes:
    """Verbatim port of fill_shift_data() in read_ALOS_data.c."""
    data_length = len(data)
    shift_data = bytearray(record_length1)
    if shift > 0:
        fill = prng.next_bits(ishift)
        shift_data[0:ishift] = fill
        shift_data[ishift:ishift + (data_length - ishift)] = data[0:data_length - ishift]
    elif shift < 0:
        n_copy = data_length - ishift - line_suffix_size
        shift_data[0:n_copy] = data[ishift:ishift + n_copy]
        fill = prng.next_bits(record_length1 - n_copy)
        shift_data[n_copy:record_length1] = fill
    # fwrite writes `data_length` bytes of shift_data (not record_length1) --
    # matches C's `fwrite((char*)shift_data, data_length, 1, outfile)`.
    return bytes(shift_data[:data_length])
