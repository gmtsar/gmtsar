import math

def str2double_c(s: str) -> float:
    """Verbatim port of preproc/S1A_preproc/lib/xml.c:str2double (lines 501-563).
    Custom digit-by-digit decimal parser -- NOT libc strtod. Must be used
    (not Python float()) for bit-parity with the C reference: C accumulates
    digits via pow(10.0, k) instead of a single correctly-rounded conversion,
    which can differ from strtod() in the last ULP for some inputs."""
    str_tmp = s
    # skip leading spaces (C: while (str_tmp[0]==' ') ...)
    i0 = 0
    while i0 < len(str_tmp) and str_tmp[i0] == ' ':
        i0 += 1
    str_tmp = str_tmp[i0:]

    sgn = 1.0
    if len(str_tmp) > 0 and (str_tmp[0] == '-' or str_tmp[0] == '+'):
        if str_tmp[0] == '-':
            sgn = -1.0
        str_tmp = str_tmp[1:]

    e_pos = str_tmp.find('e')
    if e_pos == -1:
        e_pos = str_tmp.find('E')
    if e_pos != -1:
        tmp1 = str_tmp[0:e_pos]
        tmp2 = str_tmp[e_pos + 1:]
    else:
        tmp1 = str_tmp
        tmp2 = None

    dot = tmp1.find('.')
    value1 = 0.0
    value2 = 0.0
    value = 0.0
    if dot != -1:
        intpart = tmp1[0:dot]
        m = len(intpart)
        for i in range(m):
            value1 = value1 + float(ord(intpart[i]) - 48) * math.pow(10.0, float(m - i - 1))
        fracpart = tmp1[dot + 1:]
        m = len(fracpart)
        for i in range(m):
            value2 = value2 + float(ord(fracpart[i]) - 48) * math.pow(10.0, float(-i - 1))
        value = value1 + value2
    else:
        m = len(tmp1)
        for i in range(m):
            value = value + float(ord(tmp1[i]) - 48) * math.pow(10.0, float(m - i - 1))

    if e_pos != -1:
        value = value * math.pow(10.0, str2double_c(tmp2))

    return value * sgn


def cat_nums_c(s: str) -> str:
    """Verbatim port of xml.c:cat_nums (lines 429-455): extract digit chars,
    with the C's single-digit-field zero-padding correction around T/:/. seps."""
    out = []
    sep1 = -1
    sep2 = -1
    i = 0
    n = len(s)
    while i < n and s[i] != '\0':
        c = s[i]
        if '0' <= c <= '9':
            out.append(c)
        else:
            if len(out) > 0:
                if c == 'T' or c == ':' or c == '.':
                    sep2 = i
                    if sep2 - sep1 == 2:
                        # str_out[j] = str_out[j-1]; str_out[j-1] = '0'; j++
                        out.append(out[-1])
                        out[-2] = '0'
                        sep2 += 1
                    sep1 = i
        i += 1
    return ''.join(out)


def date2MJD_c(yr: int, mo: int, day: int, hr: int, minute: int, sec: float) -> float:
    """Verbatim port of xml.c:date2MJD (lines 457-469)."""
    part1 = 367.0 * float(yr) - math.floor(7.0 * (float(yr) + math.floor((float(mo) + 9.0) / 12.0)) / 4.0) \
        + math.floor(275.0 * float(mo) / 9.0) + float(day)
    part2 = -678987.0 + ((sec / 60.0 + float(minute)) / 60.0 + float(hr)) / 24.0
    return part1 + part2


def str_date2JD_c(str_date: str) -> str:
    """Verbatim port of xml.c:str_date2JD (lines 471-499). Input is the
    already cat_nums()-extracted all-digits date string."""
    def sub(a, b):
        # C strasign(tmp, str_date, a, b) copies inclusive [a,b]; if b exceeds
        # len(str_date) it reads past the C string into the null terminator --
        # for our fixed-width digit strings b never exceeds len-1 in practice.
        return str_date[a:b + 1]

    yr = int(str2double_c(sub(0, 3)))
    mo = int(str2double_c(sub(4, 5)))
    day = int(str2double_c(sub(6, 7)))
    hr = int(str2double_c(sub(8, 9)))
    minute = int(str2double_c(sub(10, 11)))
    sec = 0.0
    sec = sec + str2double_c(sub(12, 13))
    sec = sec + str2double_c(sub(14, 19)) / 1000000.0

    MJDyr = date2MJD_c(yr, 1, 1, 0, 0, 0.0)
    MJDday = date2MJD_c(yr, mo, day, 0, 0, 0.0)
    MJDfrac = (((hr * 60.0) + minute) * 60.0 + sec) / 86400.0
    doy = int(MJDday - MJDyr + 0.1)
    return "%.12f" % (doy + MJDfrac)
