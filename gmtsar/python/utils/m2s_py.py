#!/usr/bin/env python3
"""m2s_py — in-process port of gmtsar/csh/m2s.csh.

Usage mirrors the csh: ``m2s_py(pix_m, llp_path) -> (fine_inc, crude_inc)``.

Source ported (verbatim algorithm, gmtsar/csh/m2s.csh, 21 lines):

    set range = (`gmt gmtinfo $2 -bi3f -C`)
    set mlat = `gmt math -Q ${range[3]} ${range[4]} ADD 2 DIV  = `
    set dy = `gmt math -Q $pix 111195.079734 DIV 3600 MUL 2 MUL RINT 1 MAX 2 DIV  = `
    set dx = `gmt math -Q $pix 111195.079734 DIV $mlat COSD DIV 3600 MUL 2 MUL RINT 1 MAX 2 DIV  = `
    set inc1 = "${dx}s/${dy}s"
    set dx = `gmt math -Q $dx 10 MUL  = `
    set dy = `gmt math -Q $dy 10 MUL  = `
    set inc2 = "${dx}s/${dy}s"
    echo $inc1 $inc2

Checkpoints
-----------
C1. ``gmt gmtinfo $llp -bi3f -C``  — read llp as binary float32 (lon,
    lat, phase) triplets, report w/e/s/n/zmin/zmax. We need range[3]
    and range[4] (1-indexed), i.e. s = lat.min(), n = lat.max()
    (0-indexed columns 2,3 of the 6-number -C report). Verified
    (2026-06-13, real RS2_SLC_Hawaii raln/ralt-derived llp,
    /tmp/llp_real, n=38915 points): ``gmt gmtinfo -bi3f -C`` reads
    float32, promotes to float64, and prints with the SAME %.12g
    format as ``gmt math``. So ``float(np.float32_value)`` then
    %.12g-format reproduces gmtinfo's -C output exactly — but we
    never need to FORMAT range[3]/range[4]; they only feed mlat
    arithmetic below, so the float64-promoted float32 value is all
    that matters and matches GMT bit-for-bit (same IEEE 754 double
    arithmetic).

C2. mlat = (s + n) / 2  — plain float64 arithmetic, matches
    ``gmt math ADD 2 DIV``.

C3. dy = MAX(1, RINT(pix / 111195.079734 * 3600 * 2)) / 2
    RINT verified against real ``gmt math -Q <v> RINT =`` (2026-06-13):
    GMT's RINT is round-half-to-even (IEEE 754 default / C99 rint()),
    e.g. RINT(2.5)=2, RINT(1.5)=2, RINT(3.5)=4, RINT(-0.5)=-0.
    ``np.round`` (numpy) uses the SAME round-half-to-even rule —
    verified identical on the same test vectors. MAX(1, ...) always
    keeps the post-RINT value >= 1, so the -0 edge case never
    survives into the final result (a -0 would only arise for
    RINT(-0.5) which can't occur here since pix > 0 always).

C4. dx = MAX(1, RINT(pix / 111195.079734 / cosd(mlat) * 3600 * 2)) / 2
    COSD = cosine of an angle given in DEGREES — ``np.cos(np.radians(mlat))``.
    111195.079734 is the C #define-equivalent literal baked verbatim
    into the csh (1 degree of latitude in meters at the GMT
    reference ellipsoid) — used EXACTLY as written, not replaced by
    a "more correct" WGS84 constant.

C5. Number formatting: GMT's ``gmt math -Q ... = `` prints with the
    default FORMAT_FLOAT_OUT, which (verified 2026-06-13 against real
    gmt 6.4.0) is equivalent to C's ``%.12g`` — confirmed identical to
    Python's ``"%.12g" % x`` on test vectors {0.1, 1.23456789012345,
    123456789.123, 1e-06, 1000000, 0.5, 2, 5.5, 55, 95}. In particular
    GMT prints "2" (not "2.0") for integral results and "0.5" for
    halves — Python's %.12g matches both.

C6. inc1 = f"{dx}s/{dy}s"  (dx, dy formatted per C5, BEFORE the *10 step)

C7. dx2 = dx * 10, dy2 = dy * 10 — plain float64 multiply, then
    formatted per C5 again (NOT by multiplying the formatted STRING;
    multiply the float then re-format, exactly mirroring
    ``gmt math -Q $dx 10 MUL = `` which re-parses $dx as a number).

C8. inc2 = f"{dx2}s/{dy2}s"

Output: (inc1, inc2) — same two tokens csh's ``echo $inc1 $inc2`` prints
(space-separated in the csh, but callers split() the subprocess output
into two tokens anyway, so returning a tuple is the natural Python
mapping).

Divergence / known limitations
-------------------------------
None known. C1 only needs the float64-promoted-float32 lat min/max,
which numpy's default float32->python-float upcast reproduces exactly
(both are IEEE 754; gmtinfo does the identical promotion internally).
No tolerance is needed anywhere in this port — every step is either
exact-integer-valued double arithmetic or an exact %.12g string format.
"""
from __future__ import annotations

import numpy as np

# 1 degree of latitude in meters at the GMT reference ellipsoid.
# Baked verbatim from gmtsar/csh/m2s.csh:13,15 — DO NOT "correct" this
# constant; the csh's downstream RINT/MAX/format chain depends on the
# exact literal.
_METERS_PER_DEGREE_LAT = 111195.079734


def _fmt(x: float) -> str:
    """Format a float the way ``gmt math -Q ... = `` prints it.

    GMT's default FORMAT_FLOAT_OUT is equivalent to C's "%.12g"
    (verified against real gmt 6.4.0, 2026-06-13 — see module
    docstring C5). Python's "%.12g" produces byte-identical strings
    for both integral results ("2", not "2.0") and fractional
    results ("0.5", "5.5").
    """
    return "%.12g" % x


def _rint(x: float) -> float:
    """GMT's RINT: round-half-to-even (IEEE 754 / C99 rint()).

    ``np.round`` implements the same round-half-to-even rule —
    verified identical to real ``gmt math RINT`` on {0.5, 1.5, 2.5,
    3.5, -0.5, -1.5, 2.4999999, 2.5000001, 0.0, 0.49999999999}
    (2026-06-13).
    """
    return float(np.round(x))


def m2s_py(pix_m: float, llp_path: str) -> tuple[str, str]:
    """Port of ``m2s.csh pix_m llp_path`` -> (fine_inc, crude_inc).

    Parameters
    ----------
    pix_m : float
        Pixel size in meters (csh's ``$1``).
    llp_path : str
        Path to a binary float32 (lon, lat, phase) triplet file
        (csh's ``$2``, read via ``gmt gmtinfo $2 -bi3f -C``).

    Returns
    -------
    (fine_inc, crude_inc) : tuple[str, str]
        Each of the form "{dx}s/{dy}s", matching the csh's
        ``echo $inc1 $inc2`` (split into two tokens).

    Raises
    ------
    ValueError
        If ``llp_path`` contains zero records (gmtinfo on an empty
        file is undefined; the csh would also fail/hang on `range[3]`
        / `range[4]` being unset). No fallback — an empty llp is a
        caller bug.
    """
    pix = float(pix_m)

    # ---- C1: gmt gmtinfo $llp -bi3f -C -> range[3], range[4] (s, n) ----
    raw = np.fromfile(llp_path, dtype=np.float32)
    if raw.size == 0 or raw.size % 3 != 0:
        raise ValueError(
            f"m2s_py: {llp_path!r} is empty or not a multiple of 3 "
            f"float32s (got {raw.size} values) — cannot replicate "
            f"`gmt gmtinfo -bi3f -C`"
        )
    lat = raw[1::3]  # column 1 (0-indexed) = lat
    s = float(lat.min())
    n = float(lat.max())

    # ---- C2: mlat = (s + n) / 2 ----
    mlat = (s + n) / 2.0

    # ---- C3: dy = MAX(1, RINT(pix / 111195.079734 * 3600 * 2)) / 2 ----
    dy = max(1.0, _rint(pix / _METERS_PER_DEGREE_LAT * 3600.0 * 2.0)) / 2.0

    # ---- C4: dx = MAX(1, RINT(pix / 111195.079734 / cosd(mlat) * 3600 * 2)) / 2 ----
    cosd_mlat = np.cos(np.radians(mlat))
    dx = max(1.0, _rint(pix / _METERS_PER_DEGREE_LAT / cosd_mlat * 3600.0 * 2.0)) / 2.0

    # ---- C5/C6: inc1 = "{dx}s/{dy}s" ----
    inc1 = f"{_fmt(dx)}s/{_fmt(dy)}s"

    # ---- C7: dx *= 10, dy *= 10 (re-parsed-as-number, not string concat) ----
    dx10 = dx * 10.0
    dy10 = dy * 10.0

    # ---- C8: inc2 = "{dx10}s/{dy10}s" ----
    inc2 = f"{_fmt(dx10)}s/{_fmt(dy10)}s"

    return inc1, inc2


__all__ = ["m2s_py"]
