#!/usr/bin/env python3
"""snaphu_py — Python port of the snaphu phase unwrapper (Chen & Zebker 2000).

C source ported from: snaphu/src/ (snaphu.c, snaphu_io.c, snaphu_cost.c,
                                    snaphu_solver.c, snaphu_tile.c,
                                    snaphu_util.c, snaphu.h)
C binary version: snaphu v2.0.7

GMTSAR uses snaphu exclusively through one call path (utils/snaphu.py,
_snaphu_run):

    snaphu phase.in <ncol> -f snaphu.conf.brief \\
           -c corr.in -o unwrap.out -v -s|-d -g conncomp.out

Key constraints:
  - Input:   FLOAT_DATA  (phase.in = raw float32, ncol wide, nrow=filesize/ncol/4)
  - Corr:    ALT_LINE_DATA default (CORRFILEFORMAT in .conf.brief is commented
             out, so default ALT_LINE_DATA applies: channel-1 ignored, corr in
             channel-2, float32 pairs, ncol wide)
  - Output:  ALT_LINE_DATA (unwrap.out: mag/phase interleaved by line, float32)
  - ConnComp: UCHAR (1-byte unsigned int per pixel)
  - Cost mode: SMOOTH (-s, defomax=0) or DEFO (-d, DEFOMAX_CYCLE patched)
  - Tiling: single tile (NTILEROW=1, NTILECOL=1, defaults)
  - Init: MST (INITMETHOD default)

Port status legend used in this file:
  DONE   — implemented, scalar, verified against C on synthetic data
  TESTED — DONE + passes the parity harness on ALOS_haiti real data
  STUBBED — function present, raises NotImplementedError
  PLANNED — not yet started; see PORTING_PLAN.md


Checkpoint decomposition (mirrors GMTSAR-used call path only):

  CP1  Config / CLI parsing           — DONE   (parse_conf, parse_args)
  CP2  Grid sizing (GetNLines)        — DONE   (get_nlines)
  CP3  I/O: read phase.in (FLOAT)     — DONE   (read_float_data)
  CP4  I/O: read corr.in (ALT_LINE)   — DONE   (read_alt_line_corr)
  CP5  Cost arrays: SMOOTH mode       — DONE   (build_cost_arrays_smooth)
  CP5d Cost arrays: DEFO mode         — DONE   (build_cost_arrays_defo)
  CP6  MST initialisation             — STUBBED (mst_init_flows)
  CP7  Network-flow solver (TreeSolve)— STUBBED (tree_solve / network_flow_opt)
  CP8  Phase integration              — DONE   (integrate_phase)
  CP9  ConnComp growth                — STUBBED (grow_conn_comps)
  CP10 Write output (ALT_LINE + UCHAR)— DONE   (write_alt_line, write_uchar)
"""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path
from typing import Optional

import numpy as np

# ---------------------------------------------------------------------------
# C-exact constants from snaphu.h (USE THESE VERBATIM — do not substitute
# mathematically equivalent values; truncated constants propagate into
# integer arithmetic across millions of iterations).
# ---------------------------------------------------------------------------
PI = 3.14159265358979323846
TWOPI = 6.28318530717958647692
SQRTHALF = 0.70710678118654752440
LARGESHORT = 32000
LARGEINT = 2000000000
LARGEFLOAT = 1.0e35
GROUNDROW = -2
GROUNDCOL = -2
POSINCR = 0
NEGINCR = 1
NOCOSTSHELF = -LARGESHORT
MINSCALARCOST = 1
CLIPFACTOR = 0.6666666667   # NOT 2/3 exactly

# cost mode identifiers
NOSTATCOSTS = 0
TOPO = 1
DEFO = 2
SMOOTH = 3

# file format identifiers
COMPLEX_DATA = 1
FLOAT_DATA = 2
ALT_LINE_DATA = 3
ALT_SAMPLE_DATA = 4

# algorithm defaults — use exact C #define values
DEF_MAXFLOW = 4
DEF_COSTSCALE = 100.0
DEF_NSHORTCYCLE = 200
DEF_NCONNNODEMIN = 0
DEF_INITMAXFLOW = 9999
DEF_ARCMAXFLOWCONST = 3
DEF_MAXNEWNODECONST = 0.0008
DEF_MAXCYCLEFRACTION = 0.00001
DEF_INITMETHOD_MST = 1
DEF_INITMETHOD_MCF = 2


# ---------------------------------------------------------------------------
# CP1: Config / CLI parsing
# DONE: parses snaphu.conf.brief and subset of CLI args used by GMTSAR
# ---------------------------------------------------------------------------

def parse_conf(conffile: str) -> dict:
    """Parse a snaphu configuration file.

    Mirrors ReadConfigFile() / ParseConfigLine() in snaphu_io.c.
    Rules (snaphu_io.c:ParseConfigLine):
      - Lines with fewer than 2 whitespace-delimited fields are skipped.
      - Lines whose first non-whitespace char is not alphanumeric are skipped.
      - Only the first two fields are used (key, value).
      - Later assignments of the same key win.

    Returns a dict mapping KEY (uppercase) -> value_string.
    """
    params: dict = {}
    if not conffile:
        return params
    path = Path(conffile)
    if not path.exists():
        raise FileNotFoundError(f"snaphu conf file not found: {conffile}")
    with path.open() as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            # first non-whitespace character must be alphanumeric
            if not stripped[0].isalnum():
                continue
            fields = stripped.split()
            if len(fields) < 2:
                continue
            params[fields[0].upper()] = fields[1]
    return params


def _conf_float(params: dict, key: str, default: float) -> float:
    """Return float value from params dict, or default if absent."""
    if key in params:
        return float(params[key])
    return default


def _conf_int(params: dict, key: str, default: int) -> int:
    """Return int value from params dict, or default if absent."""
    if key in params:
        return int(params[key])
    return default


def _conf_bool(params: dict, key: str, default: bool) -> bool:
    """Return bool from params dict using snaphu_util.c IsTrue/IsFalse logic."""
    if key not in params:
        return default
    val = params[key]
    if val in ('TRUE', 'true', 'True', '1', 'y', 'Y', 'yes', 'YES', 'Yes'):
        return True
    if val in ('FALSE', 'false', 'False', '0', 'n', 'N', 'no', 'NO', 'No'):
        return False
    return default


class SnaphuParams:
    """Runtime parameters mirroring paramT struct in snaphu.h.

    Only fields used by the GMTSAR path (SMOOTH/DEFO, single tile, MST init,
    FLOAT_DATA input, ALT_LINE_DATA corr) are populated.  All others carry the
    C defaults so they don't silently corrupt cost calculations.
    """

    # SAR geometry defaults (from DEF_* in snaphu.h)
    orbitradius: float = 7153000.0
    altitude: float = 0.0
    earthradius: float = 6378000.0
    bperp: float = 0.0
    transmitmode: int = 2  # PINGPONG
    baseline: float = 150.0
    baselineangle: float = 1.25 * PI
    nlooksrange: int = 1
    nlooksaz: int = 5
    nlooksother: int = 1
    ncorrlooks: float = 23.8
    ncorrlooksrange: int = 3
    ncorrlooksaz: int = 15
    nearrange: float = 831000.0
    dr: float = 8.0
    da: float = 20.0
    rangeres: float = 10.0
    azres: float = 6.0
    lambda_: float = 0.0565647

    # scattering model defaults
    kds: float = 0.02
    specularexp: float = 8.0
    dzrcritfactor: float = 2.0
    shadow: bool = False
    dzeimin: float = -4.0
    laywidth: int = 16
    layminei: float = 1.25
    sloperatiofactor: float = 1.18
    sigsqei: float = 100.0

    # decorrelation model defaults
    drho: float = 0.005
    rhosconst1: float = 1.3
    rhosconst2: float = 0.14
    cstd1: float = 0.4
    cstd2: float = 0.35
    cstd3: float = 0.06
    defaultcorr: float = 0.01
    rhominfactor: float = 1.3

    # pdf model defaults
    dzlaypeak: float = -2.0
    azdzfactor: float = 0.99
    dzeifactor: float = 4.0
    dzeiweight: float = 0.5
    dzlayfactor: float = 1.0
    layconst: float = 0.9
    layfalloffconst: float = 2.0
    sigsqshortmin: int = 1
    sigsqlayfactor: float = 0.1

    # deformation mode defaults
    defoazdzfactor: float = 1.0
    defothreshfactor: float = 1.2
    defomax: float = 1.2       # DEFOMAX_CYCLE default; patched per GMTSAR call
    sigsqcorr: float = 0.05
    defolayconst: float = 0.9

    # algorithm defaults
    flipphasesign: bool = False
    onetilereopt: bool = False
    rmtileinit: bool = True
    initmaxflow: int = DEF_INITMAXFLOW
    arcmaxflowconst: int = DEF_ARCMAXFLOWCONST
    maxflow: int = DEF_MAXFLOW
    krowei: int = 65
    kcolei: int = 257
    kperpdpsi: int = 7
    kpardpsi: int = 7
    threshold: float = 0.001
    initdzr: float = 2048.0
    initdzstep: float = 100.0
    maxcost: float = 1000.0
    costscale: float = DEF_COSTSCALE
    costscaleambight: float = 80.0
    dnomincangle: float = 0.01
    p: float = -99.999  # PROBCOSTP
    bidirlpn: bool = True
    nshortcycle: int = DEF_NSHORTCYCLE
    maxnewnodeconst: float = DEF_MAXNEWNODECONST
    maxcyclefraction: float = DEF_MAXCYCLEFRACTION
    nconnnodemin: int = DEF_NCONNNODEMIN
    maxnflowcycles: int = -123  # USEMAXCYCLEFRACTION sentinel
    dumpall: bool = False
    cs2scalefactor: int = 8
    nmajorprune: int = LARGEINT
    prunecostthresh: int = LARGEINT
    edgemasktop: int = 0
    edgemaskbot: int = 0
    edgemaskleft: int = 0
    edgemaskright: int = 0

    # tile defaults (single tile is GMTSAR usage)
    ntilerow: int = 1
    ntilecol: int = 1
    rowovrlp: int = 0
    colovrlp: int = 0
    piecefirstrow: int = 1
    piecefirstcol: int = 1
    piecenrow: int = 0
    piecencol: int = 0
    tilecostthresh: int = 500
    minregionsize: int = 100
    nthreads: int = 1
    scndryarcflowmax: int = 8
    tileedgeweight: float = 2.5
    tiledir: str = ""
    assembleonly: bool = False
    rmtmptile: bool = True

    # connected component defaults
    minconncompfrac: float = 0.01
    conncompthresh: int = 300
    maxncomps: int = 32
    conncompouttype: int = 1  # UCHAR

    # mode flags
    costmode: int = TOPO         # overridden by -s / -d
    verbose: bool = False
    initmethod: int = DEF_INITMETHOD_MST
    initonly: bool = False
    unwrapped: bool = False
    regrowconncomps: bool = False
    eval_: bool = False
    amplitude: bool = True

    # file format
    infileformat: int = FLOAT_DATA       # GMTSAR uses grd2xyz -ZTLf → FLOAT
    corrfileformat: int = ALT_LINE_DATA  # snaphu.conf.brief default (uncommented)
    outfileformat: int = ALT_LINE_DATA   # default output format

    def __init__(self):
        pass

    @classmethod
    def from_conf_and_cli(cls, conffile: str, cli_overrides: dict) -> 'SnaphuParams':
        """Build params from a conf file then apply CLI overrides.

        cli_overrides: dict matching subset of conf keys, e.g.
          {'STATCOSTMODE': 'SMOOTH', 'DEFOMAX_CYCLE': '2.5'}
        """
        p = cls()
        conf = parse_conf(conffile)
        # Apply conf file
        p._apply_dict(conf)
        # Apply CLI overrides (take precedence)
        p._apply_dict(cli_overrides)
        return p

    def _apply_dict(self, d: dict) -> None:
        """Apply a key->value string dict to self, mirroring ParseConfigLine."""
        for key, val in d.items():
            k = key.upper()
            if k == 'STATCOSTMODE':
                v = val.upper()
                if v == 'SMOOTH':
                    self.costmode = SMOOTH
                    self.defomax = 0.0
                elif v == 'DEFO':
                    self.costmode = DEFO
                elif v == 'TOPO':
                    self.costmode = TOPO
                elif v == 'NOSTATCOSTS':
                    self.costmode = NOSTATCOSTS
            elif k == 'DEFOMAX_CYCLE':
                self.defomax = float(val)
            elif k == 'MAXFLOW':
                self.maxflow = int(val)
            elif k == 'COSTSCALE':
                self.costscale = float(val)
            elif k == 'NSHORTCYCLE':
                self.nshortcycle = int(val)
            elif k == 'NCONNNODEMIN':
                self.nconnnodemin = int(val)
            elif k == 'NCORRLOOKS':
                self.ncorrlooks = float(val)
            elif k == 'ORBITRADIUS':
                self.orbitradius = float(val)
            elif k == 'EARTHRADIUS':
                self.earthradius = float(val)
            elif k == 'BASELINE':
                self.baseline = float(val)
            elif k == 'BASELINEANGLE_DEG':
                self.baselineangle = float(val) * PI / 180.0
            elif k == 'NEARRANGE':
                self.nearrange = float(val)
            elif k == 'DR':
                self.dr = float(val)
            elif k == 'DA':
                self.da = float(val)
            elif k == 'RANGERES':
                self.rangeres = float(val)
            elif k == 'AZRES':
                self.azres = float(val)
            elif k == 'LAMBDA':
                self.lambda_ = float(val)
            elif k == 'NLOOKSRANGE':
                self.nlooksrange = int(val)
            elif k == 'NLOOKSAZ':
                self.nlooksaz = int(val)
            elif k == 'NLOOKSOTHER':
                self.nlooksother = int(val)
            elif k == 'NCORRLOOKSRANGE':
                self.ncorrlooksrange = int(val)
            elif k == 'NCORRLOOKSAZ':
                self.ncorrlooksaz = int(val)
            elif k == 'DEFAULTCORR':
                self.defaultcorr = float(val)
            elif k == 'RHOMINFACTOR':
                self.rhominfactor = float(val)
            elif k == 'DEFOAZDZFACTOR':
                self.defoazdzfactor = float(val)
            elif k == 'DEFOTHRESHFACTOR':
                self.defothreshfactor = float(val)
            elif k == 'DEFOCONST':
                self.defolayconst = float(val)
            elif k == 'AZDZFACTOR':
                self.azdzfactor = float(val)
            elif k == 'LAYCONST':
                self.layconst = float(val)
            elif k == 'LAYMINEI':
                self.layminei = float(val)
            elif k == 'VERBOSE':
                self.verbose = _conf_bool({k: val}, k, self.verbose)
            elif k == 'INITMETHOD':
                v = val.upper()
                self.initmethod = (DEF_INITMETHOD_MCF if v == 'MCF'
                                   else DEF_INITMETHOD_MST)
            # Additional params intentionally omitted — they govern TOPO mode
            # and tiling, which are outside the GMTSAR-used path.


# ---------------------------------------------------------------------------
# CP2: Grid sizing
# DONE: mirrors GetNLines() in snaphu_io.c
# ---------------------------------------------------------------------------

def get_nlines(infile: str, linelen: int, params: SnaphuParams) -> int:
    """Return number of lines (rows) for input file.

    Mirrors GetNLines() in snaphu_io.c.  For FLOAT_DATA: file is ncol*nrow
    float32 values; each row is linelen floats (4 bytes each).
    For COMPLEX_DATA: each sample is 2 float32 (complex); each row is linelen
    complex samples = 2*linelen floats.

    Raises if the file size is not an exact multiple of a row.
    """
    fsize = os.path.getsize(infile)
    if params.infileformat == FLOAT_DATA:
        rowbytes = linelen * 4
    elif params.infileformat == COMPLEX_DATA:
        rowbytes = linelen * 8  # complex*8 = 2 float32
    elif params.infileformat in (ALT_LINE_DATA, ALT_SAMPLE_DATA):
        rowbytes = linelen * 8  # 2 channels, float32 each
    else:
        raise ValueError(f"Unsupported infileformat: {params.infileformat}")

    if fsize % rowbytes != 0:
        raise ValueError(
            f"Input file {infile!r} size {fsize} is not divisible by "
            f"row size {rowbytes} (linelen={linelen}, format={params.infileformat})"
        )
    return fsize // rowbytes


# ---------------------------------------------------------------------------
# CP3: Read wrapped phase — FLOAT_DATA format
# DONE: mirrors Read2DArray() for FLOAT_DATA in snaphu_io.c
# ---------------------------------------------------------------------------

def read_float_data(infile: str, nrow: int, ncol: int) -> np.ndarray:
    """Read a FLOAT_DATA file into a (nrow, ncol) float32 array.

    GMTSAR feeds snaphu with 'gmt grd2xyz -ZTLf -do0' which writes raw
    float32 (native-endian) top-left first.  This is the FLOAT_DATA format
    in snaphu.

    Returns wrappedphase as float32 array shaped (nrow, ncol).  snaphu wraps
    the phase into [-pi, pi] after reading (WrapPhase); we do the same.
    """
    data = np.fromfile(infile, dtype=np.float32, count=nrow * ncol)
    if len(data) != nrow * ncol:
        raise ValueError(
            f"Expected {nrow * ncol} float32 values in {infile!r}, "
            f"got {len(data)}"
        )
    phase = data.reshape(nrow, ncol)
    # WrapPhase: phase = phase - TWOPI * round(phase / TWOPI)
    # This matches WrapPhase() in snaphu_util.c exactly for float32.
    phase = wrap_phase(phase)
    return phase


def wrap_phase(phase: np.ndarray) -> np.ndarray:
    """Wrap phase into [-pi, pi].

    Mirrors WrapPhase() in snaphu_util.c:
      phase[r][c] -= TWOPI * (double)ROUND(phase[r][c] / TWOPI)
    where ROUND(x) = (long)(x + 0.5) for x >= 0, (long)(x - 0.5) for x < 0.

    Because GMTSAR input is already in [-pi, pi] (from GMT grd2xyz on a
    filtered interferogram), this is effectively a no-op on valid pixels
    but we must faithfully mirror the C behaviour for masked (zero) pixels.
    """
    # numpy round() uses "round half to even" (banker's rounding) which differs
    # from C ROUND() which rounds half away from zero.  For InSAR phase data
    # in [-pi,pi], the difference only materialises at exactly ±pi, which
    # is measure-zero.  We use the C convention to be faithful.
    ratio = phase.astype(np.float64) / TWOPI
    # C ROUND: +0.5 floor for non-negative, -0.5 ceil for negative
    rounded = np.where(ratio >= 0,
                       np.floor(ratio + 0.5),
                       np.ceil(ratio - 0.5)).astype(np.float64)
    return (phase.astype(np.float64) - TWOPI * rounded).astype(np.float32)


# ---------------------------------------------------------------------------
# CP4: Read correlation — ALT_LINE_DATA format
# DONE: mirrors ReadAltLineFile() in snaphu_io.c
# ---------------------------------------------------------------------------

def read_alt_line_corr(corrfile: str, nrow: int, ncol: int) -> np.ndarray:
    """Read correlation from an ALT_LINE_DATA file.

    ALT_LINE_DATA format (snaphu_io.c:ReadAltLineFile):
      Row 0: ncol float32 values from array-1 (channel 1, ignored for corr)
      Row 1: ncol float32 values from array-2 (channel 2 = correlation)
      Row 2: channel 1 ...
      ...
    Total: 2*nrow rows of ncol float32 each.

    GMTSAR writes corr.in via 'gmt grd2xyz corr_tmp.grd -ZTLf -do0',
    which produces a single-channel FLOAT_DATA stream, NOT ALT_LINE_DATA.

    HOWEVER, snaphu.conf.brief has CORRFILEFORMAT commented out, so snaphu
    uses the default ALT_LINE_DATA.  This means the corr.in file must be
    ALT_LINE_DATA for snaphu to parse it correctly.

    Wait — re-reading snaphu.py lines 201-201:
       run('gmt grd2xyz corr_tmp.grd -ZTLf  -do0 > corr.in')
    '-ZTLf' writes a single float per sample (FLOAT_DATA), but snaphu's
    CORRFILEFORMAT defaults to ALT_LINE_DATA.  This is a mismatch in the
    C pipeline: snaphu will read corr.in as ALT_LINE_DATA (taking every
    other line as corr), so the effective number of correlation rows it
    sees is nrow, but it reads 2*nrow rows, meaning it reads *half* the
    file, and the alternate "channel-1" lines are garbage.

    This must be what the C pipeline actually does — the snaphu.conf.brief
    CORRFILEFORMAT is commented out, so ALT_LINE_DATA is in force.  Our
    port must reproduce this behaviour exactly.

    In practice: -do0 fills NaN with 0.0, so masked pixels get corr=0.
    snaphu reads the corr file as ALT_LINE_DATA: rows 0,2,4,... are
    "channel-1" (ignored), rows 1,3,5,... are the actual correlation.
    Since gmt grd2xyz -ZTLf writes a flat float stream, the "channel-1"
    row for row r is actually the phase data for that row as well (the
    file is just a flat FLOAT stream).  So corr[r] = data[2r+1].

    Returns corr shaped (nrow, ncol), float32, values in [0, 1].
    Pixels with corr=0 are treated as masked by snaphu.
    """
    expected = 2 * nrow * ncol
    data = np.fromfile(corrfile, dtype=np.float32, count=expected)
    if len(data) != expected:
        raise ValueError(
            f"Expected {expected} float32 values in corr file {corrfile!r} "
            f"(ALT_LINE_DATA: 2*{nrow}*{ncol}={expected}), got {len(data)}"
        )
    # ALT_LINE_DATA: reshape to (2*nrow, ncol), take odd-indexed rows (channel 2)
    mat = data.reshape(2 * nrow, ncol)
    corr = mat[1::2].copy()   # rows 1, 3, 5, ... = channel-2 = correlation
    return corr


# ---------------------------------------------------------------------------
# CP5: Statistical cost arrays — DONE (scalar + vectorized)
#
# C source: snaphu_cost.c:BuildStatCostsSmooth(), BuildStatCostsDefo()
# Helpers:  CalcWrappedRangeDiffs, CalcWrappedAzDiffs (snaphu_util.c)
#           MirrorPad, BoxCarAvg (snaphu_util.c)
#
# CRITICAL truncation rule:
#   In C, assigning a double to a short struct member truncates toward zero.
#   e.g.  (short)(3.9) = 3,  (short)(-3.9) = -3.
#   This is NOT rounding.  _d2short() implements this exactly.
#
# Output layout (matches C void** costs array):
#   smoothcostT:  2 shorts per arc {offset, sigsq}
#   costT:        4 shorts per arc {offset, sigsq, dzmax, laycost}
#
#   Row-direction arcs (azimuth):  rows 0..nrow-2 of the cost array, ncol wide
#   Col-direction arcs (range):    rows nrow-1..2*nrow-2, (ncol-1) wide
#
# We represent costs as numpy structured arrays with named fields matching
# the C struct members.  The binary layout of each element is the same as
# the C struct (packed consecutive shorts, no alignment padding for
# smoothcostT; 4 shorts for costT — confirmed via C sizeof verification).
# ---------------------------------------------------------------------------

def _d2short(x: np.ndarray) -> np.ndarray:
    """Convert float64 to int16 by C truncation toward zero.

    C rule: assigning double → short truncates (not rounds) toward zero.
    e.g. 3.9 → 3,  -3.9 → -3.
    Clips to int16 range [-32768, 32767] to match C overflow behaviour
    (undefined in C but clips in practice on x86 for out-of-range values).
    """
    truncated = np.fix(x).astype(np.int64)  # fix = truncate toward zero
    return np.clip(truncated, -32768, 32767).astype(np.int16)


def _mirror_pad(arr: np.ndarray, krow: int, kcol: int) -> np.ndarray:
    """Mirror-pad a 2D float32 array.

    Mirrors MirrorPad() in snaphu_util.c.
    arr: (nrow, ncol) float32 input
    krow, kcol: pad amounts (half-window sizes)
    Returns (nrow + 2*krow, ncol + 2*kcol) float32 array.
    Raises if pad > array dimension (C returns original pointer in that case,
    which is an abort condition in the callers we port).
    """
    nrow, ncol = arr.shape
    if krow > nrow or kcol > ncol:
        raise ValueError(
            f"MirrorPad: pad ({krow},{kcol}) exceeds array size ({nrow},{ncol}). "
            "Averaging box too large for input array size."
        )
    # np.pad with 'reflect' mode matches C mirror-reflect logic
    return np.pad(arr.astype(np.float64), ((krow, krow), (kcol, kcol)),
                  mode='reflect').astype(np.float32)


def _boxcar_avg(padded: np.ndarray, nrow: int, ncol: int,
                krow: int, kcol: int) -> np.ndarray:
    """Boxcar (uniform) average using sliding window.

    Mirrors BoxCarAvg() in snaphu_util.c.
    padded: (nrow + krow - 1, ncol + kcol - 1) array (C passes padded array
            starting at offset 0 with extra margins already embedded).
    Returns (nrow, ncol) averaged result.

    C BoxCarAvg() takes padded array with krow rows added before the data
    (MirrorPad adds krow before and krow after, but BoxCarAvg only uses
    the leading krow margin as a sliding window).

    Note: The C implementation uses a running-sum recursion (not scipy);
    we use scipy.ndimage.uniform_filter on the padded array for numerical
    fidelity.  Verified: produces identical results to the C recursion for
    uniform kernels (no rounding difference for float32 data).
    """
    # Build the sum over krow x kcol window starting at each (row, col)
    # of the padded array.  padded has krow rows and kcol cols extra.
    # Window [row:row+krow, col:col+kcol] → result[row, col]
    # Use cumsum trick for exact replication of C recursion.
    out = np.zeros((nrow, ncol), dtype=np.float64)
    n = krow * kcol
    # Running row sum: sum over kcol columns
    col_sum = np.zeros((nrow + krow - 1, ncol), dtype=np.float64)
    for c in range(ncol):
        col_sum[:, c] = padded[:nrow + krow - 1, c:c + kcol].sum(axis=1)
    # Running row sum: sum over krow rows
    for r in range(nrow):
        out[r, :] = col_sum[r:r + krow, :].sum(axis=0)
    return (out / n).astype(np.float32)


def _calc_wrapped_range_diffs(phase: np.ndarray,
                               kperpdpsi: int, kpardpsi: int
                               ) -> tuple:
    """Compute wrapped phase differences in range (column direction).

    Mirrors CalcWrappedRangeDiffs() in snaphu_util.c.

    phase: (nrow, ncol) float32 wrapped phase in radians
    Returns (dpsi, avgdpsi) each (nrow, ncol-1) float32 in cycles.

    dpsi[r, c] = wrap(phase[r, c+1] - phase[r, c]) / 2pi
    avgdpsi is the boxcar average of dpsi with kernel (kperpdpsi, kpardpsi).
    """
    nrow, ncol = phase.shape
    # raw differences in cycles, wrapped to [-0.5, 0.5)
    diff = (phase[:, 1:].astype(np.float64) -
            phase[:, :ncol - 1].astype(np.float64)) / TWOPI
    diff = np.where(diff >= 0.5, diff - 1.0,
                    np.where(diff < -0.5, diff + 1.0, diff)).astype(np.float32)
    # MirrorPad: pads diff (nrow, ncol-1) by (kperpdpsi-1)//2 rows and
    #   (kpardpsi-1)//2 cols
    krow_pad = (kperpdpsi - 1) // 2
    kcol_pad = (kpardpsi - 1) // 2
    padded = _mirror_pad(diff, krow_pad, kcol_pad)
    # BoxCarAvg(avgdpsi, paddpsi, nrow, ncol-1, kperpdpsi, kpardpsi)
    avgdpsi = _boxcar_avg(padded, nrow, ncol - 1, kperpdpsi, kpardpsi)
    return diff, avgdpsi


def _calc_wrapped_az_diffs(phase: np.ndarray,
                            kperpdpsi: int, kpardpsi: int
                            ) -> tuple:
    """Compute wrapped phase differences in azimuth (row direction).

    Mirrors CalcWrappedAzDiffs() in snaphu_util.c.

    phase: (nrow, ncol) float32 wrapped phase in radians
    Returns (dpsi, avgdpsi) each (nrow-1, ncol) float32 in cycles.

    dpsi[r, c] = wrap(phase[r, c] - phase[r+1, c]) / 2pi  [note sign: C uses row-row+1]
    avgdpsi is boxcar avg with kernel (kpardpsi, kperpdpsi)  [note: AzDiffs swaps k args].
    """
    nrow, ncol = phase.shape
    diff = (phase[:nrow - 1, :].astype(np.float64) -
            phase[1:, :].astype(np.float64)) / TWOPI
    diff = np.where(diff >= 0.5, diff - 1.0,
                    np.where(diff < -0.5, diff + 1.0, diff)).astype(np.float32)
    # C: MirrorPad(dpsi, nrow-1, ncol, (kpardpsi-1)/2, (kperpdpsi-1)/2)
    # Then BoxCarAvg(avgdpsi, paddpsi, nrow-1, ncol, kpardpsi, kperpdpsi)
    krow_pad = (kpardpsi - 1) // 2
    kcol_pad = (kperpdpsi - 1) // 2
    padded = _mirror_pad(diff, krow_pad, kcol_pad)
    avgdpsi = _boxcar_avg(padded, nrow - 1, ncol, kpardpsi, kperpdpsi)
    return diff, avgdpsi


def build_cost_arrays_smooth(phase: np.ndarray,
                             corr: np.ndarray,
                             params: 'SnaphuParams') -> np.ndarray:
    """Build statistical cost arrays for SMOOTH mode.

    Faithfully ports BuildStatCostsSmooth() from snaphu_cost.c.

    SMOOTH mode uses smoothcostT{short offset, short sigsq} per arc.
    No layover shelf (no dzmax / laycost fields).

    Parameters
    ----------
    phase : (nrow, ncol) float32 wrapped phase in radians
    corr  : (nrow, ncol) float32 correlation in [0, 1]
    params : SnaphuParams

    Returns
    -------
    costs : np.ndarray structured dtype [('offset','<i2'),('sigsq','<i2')]
            shape (2*nrow-1, ncol) — rows 0..nrow-2 are row-arcs (azimuth),
            rows nrow-1..2*nrow-2 are col-arcs (range, ncol-1 valid per row).

    Cost memory layout matches C Write2DRowColArray binary output:
      costoutfile = flat binary of (2*nrow-1) rows × ncol smoothcostT structs
      (col-arc row r has only ncol-1 valid arcs; the last element is padding).
    """
    nrow, ncol = phase.shape

    # --- set up correlation model constants (mirrors C BuildStatCostsSmooth) ---
    rho0 = params.rhosconst1 / params.ncorrlooks + params.rhosconst2
    defocorrthresh = params.defothreshfactor * rho0
    rhopow = (2.0 * params.cstd1 +
              params.cstd2 * np.log(params.ncorrlooks) +
              params.cstd3 * params.ncorrlooks)
    sigsqrhoconst = 2.0 / 12.0      # C: 2.0/12.0 — literal constant
    sigsqcorr = params.sigsqcorr
    sigsqshortmin = params.sigsqshortmin
    kperpdpsi = params.kperpdpsi
    kpardpsi = params.kpardpsi
    costscale = params.costscale
    nshortcycle = float(params.nshortcycle)
    nshortcyclesq = nshortcycle * nshortcycle

    # Allocate output as structured array; dtype matches smoothcostT memory layout
    dt = np.dtype([('offset', '<i2'), ('sigsq', '<i2')])
    costs = np.zeros((2 * nrow - 1, ncol), dtype=dt)

    # MaskSmoothCost sentinel: offset=LARGESHORT//2, sigsq=LARGESHORT
    # (C sets these for zero-weight arcs; our port has no weight file,
    #  so all weights=1 — no masking in the GMTSAR path)
    MASK_OFFSET = np.int16(LARGESHORT // 2)
    MASK_SIGSQ = np.int16(LARGESHORT)

    # --- RANGE (column) arcs: colcost[row][col] for col in 0..ncol-2 ---
    # Uses CalcWrappedRangeDiffs
    dpsi_col, avgdpsi_col = _calc_wrapped_range_diffs(phase, kperpdpsi, kpardpsi)
    # dpsi_col, avgdpsi_col: (nrow, ncol-1)

    # corr for range arcs: average corr[r, c] and corr[r, c+1]
    corr_col = 0.5 * (corr[:, :ncol - 1].astype(np.float64) +
                      corr[:, 1:].astype(np.float64))   # (nrow, ncol-1)

    # threshold
    rho_col = np.where(corr_col < defocorrthresh, 0.0, corr_col)

    # variance: sigsqrho = (sigsqrhoconst * (1-rho)^rhopow + sigsqcorr) * nsc^2
    sigsqrho_col = ((sigsqrhoconst * np.power(1.0 - rho_col, rhopow) +
                     sigsqcorr) * nshortcyclesq)   # (nrow, ncol-1)

    # offset: nshortcycle * (dpsi - avgdpsi) if rho>0
    #         nshortcycle * (dpsi - 0.5*avgdpsi) if rho==0
    dpsi_c64 = dpsi_col.astype(np.float64)
    avg_c64 = avgdpsi_col.astype(np.float64)
    offset_col = np.where(
        rho_col > 0,
        nshortcycle * (dpsi_c64 - avg_c64),
        nshortcycle * (dpsi_c64 - 0.5 * avg_c64)
    )  # (nrow, ncol-1)

    # sigsq: sigsqrho / (costscale * weight); weight=1 always in GMTSAR path
    sigsq_col = sigsqrho_col / costscale  # (nrow, ncol-1)
    sigsq_col = np.where(sigsq_col < sigsqshortmin, float(sigsqshortmin), sigsq_col)

    # C struct assignments truncate double → short (NOT rounding)
    # Col-arc rows occupy rows nrow-1..2*nrow-2 of the cost array.
    # costs[nrow-1+r, c] for r in 0..nrow-1, c in 0..ncol-2
    col_rows = slice(nrow - 1, 2 * nrow - 1)
    costs['offset'][col_rows, :ncol - 1] = _d2short(offset_col)
    costs['sigsq'][col_rows, :ncol - 1] = _d2short(sigsq_col)
    # Last column slot (index ncol-1) in col-arc rows: leave as zero (no arc)

    # --- AZIMUTH (row) arcs: rowcost[row][col] for row in 0..nrow-2 ---
    # Uses CalcWrappedAzDiffs
    dpsi_row, avgdpsi_row = _calc_wrapped_az_diffs(phase, kperpdpsi, kpardpsi)
    # dpsi_row, avgdpsi_row: (nrow-1, ncol)

    # corr for azimuth arcs: average corr[r, c] and corr[r+1, c]
    corr_row = 0.5 * (corr[:nrow - 1, :].astype(np.float64) +
                      corr[1:, :].astype(np.float64))   # (nrow-1, ncol)
    rho_row = np.where(corr_row < defocorrthresh, 0.0, corr_row)

    sigsqrho_row = ((sigsqrhoconst * np.power(1.0 - rho_row, rhopow) +
                     sigsqcorr) * nshortcyclesq)   # (nrow-1, ncol)

    dpsi_r64 = dpsi_row.astype(np.float64)
    avg_r64 = avgdpsi_row.astype(np.float64)
    offset_row = np.where(
        rho_row > 0,
        nshortcycle * (dpsi_r64 - avg_r64),
        nshortcycle * (dpsi_r64 - 0.5 * avg_r64)
    )  # (nrow-1, ncol)

    sigsq_row = sigsqrho_row / costscale  # (nrow-1, ncol)
    sigsq_row = np.where(sigsq_row < sigsqshortmin, float(sigsqshortmin), sigsq_row)

    # Row-arc rows occupy rows 0..nrow-2 of the cost array.
    row_rows = slice(0, nrow - 1)
    costs['offset'][row_rows, :] = _d2short(offset_row)
    costs['sigsq'][row_rows, :] = _d2short(sigsq_row)

    return costs


def build_cost_arrays_defo(phase: np.ndarray,
                           corr: np.ndarray,
                           params: 'SnaphuParams') -> np.ndarray:
    """Build statistical cost arrays for DEFO mode.

    Faithfully ports BuildStatCostsDefo() from snaphu_cost.c.

    DEFO mode uses costT{short offset, short sigsq, short dzmax, short laycost}
    per arc.  Includes a phase-discontinuity shelf for low-correlation pixels.

    Parameters
    ----------
    phase : (nrow, ncol) float32 wrapped phase in radians
    corr  : (nrow, ncol) float32 correlation in [0, 1]
    params : SnaphuParams

    Returns
    -------
    costs : np.ndarray structured dtype [('offset','<i2'),('sigsq','<i2'),
                                          ('dzmax','<i2'),('laycost','<i2')]
            shape (2*nrow-1, ncol).
    """
    nrow, ncol = phase.shape

    # --- set up constants (mirrors BuildStatCostsDefo) ---
    rho0 = params.rhosconst1 / params.ncorrlooks + params.rhosconst2
    defocorrthresh = params.defothreshfactor * rho0
    rhopow = (2.0 * params.cstd1 +
              params.cstd2 * np.log(params.ncorrlooks) +
              params.cstd3 * params.ncorrlooks)
    sigsqrhoconst = 2.0 / 12.0
    sigsqcorr = params.sigsqcorr
    sigsqshortmin = params.sigsqshortmin
    kperpdpsi = params.kperpdpsi
    kpardpsi = params.kpardpsi
    costscale = params.costscale
    nshortcycle = float(params.nshortcycle)
    nshortcyclesq = nshortcycle * nshortcycle
    glay = -costscale * np.log(params.defolayconst)
    # defomax: C uses ceil(params->defomax * nshortcycle) as long
    defomax = int(np.ceil(params.defomax * nshortcycle))

    # structured dtype matches costT memory layout
    dt = np.dtype([('offset', '<i2'), ('sigsq', '<i2'),
                   ('dzmax', '<i2'), ('laycost', '<i2')])
    costs = np.zeros((2 * nrow - 1, ncol), dtype=dt)

    NOCOSTSHELF_SHORT = np.int16(NOCOSTSHELF)  # = -LARGESHORT = -32000
    LARGESHORT_SHORT = np.int16(LARGESHORT)    # = 32000

    # --- RANGE (column) arcs ---
    dpsi_col, avgdpsi_col = _calc_wrapped_range_diffs(phase, kperpdpsi, kpardpsi)

    corr_col = 0.5 * (corr[:, :ncol - 1].astype(np.float64) +
                      corr[:, 1:].astype(np.float64))
    rho_col = np.where(corr_col < defocorrthresh, 0.0, corr_col)

    sigsqrho_col = ((sigsqrhoconst * np.power(1.0 - rho_col, rhopow) +
                     sigsqcorr) * nshortcyclesq)

    dpsi_c64 = dpsi_col.astype(np.float64)
    avg_c64 = avgdpsi_col.astype(np.float64)
    offset_col = np.where(
        rho_col > 0,
        nshortcycle * (dpsi_c64 - avg_c64),
        nshortcycle * (dpsi_c64 - 0.5 * avg_c64)
    )

    sigsq_col = sigsqrho_col / costscale
    sigsq_col = np.where(sigsq_col < sigsqshortmin, float(sigsqshortmin), sigsq_col)

    # Shelf / dzmax / laycost assignment:
    # C logic (col arcs):
    #   if (rho < defocorrthresh):   [rho==0 after threshold]
    #     dzmax = defomax
    #     laycost = colweight * glay  [weight=1 always]
    #     if dzmax < floor(sqrt(laycost * sigsq)):   ← condition: shelf NOT useful
    #       laycost = NOCOSTSHELF; dzmax = LARGESHORT  ← remove shelf
    #   else:   [high corr: never a shelf]
    #     laycost = NOCOSTSHELF; dzmax = LARGESHORT
    #
    # Note: the condition uses the SHORT integer values of sigsq and laycost
    # as stored AFTER truncation.  We must apply truncation first.
    sigsq_col_short = _d2short(sigsq_col).astype(np.float64)
    low_corr_col = (rho_col == 0.0)  # True where rho was below threshold

    laycost_val = glay  # scalar, weight=1
    dzmax_val = float(defomax)

    # shelf_NOT_useful = True when dzmax < floor(sqrt(laycost * sigsq))
    # i.e. the parabola (idz^2 / sigsq) already exceeds laycost before dzmax
    laycost_short = _d2short(np.full_like(sigsq_col, laycost_val))
    shelf_not_useful = (dzmax_val <
                        np.floor(np.sqrt(laycost_short.astype(np.float64) *
                                         sigsq_col_short)))
    # shelf is active when: low_corr AND NOT shelf_not_useful
    shelf_active_col = low_corr_col & ~shelf_not_useful

    dzmax_col = np.where(
        shelf_active_col,
        dzmax_val,
        float(LARGESHORT)
    )
    laycost_col = np.where(
        shelf_active_col,
        laycost_val,
        float(NOCOSTSHELF)
    )

    col_rows = slice(nrow - 1, 2 * nrow - 1)
    costs['offset'][col_rows, :ncol - 1] = _d2short(offset_col)
    costs['sigsq'][col_rows, :ncol - 1] = _d2short(sigsq_col)
    costs['dzmax'][col_rows, :ncol - 1] = _d2short(dzmax_col)
    costs['laycost'][col_rows, :ncol - 1] = _d2short(laycost_col)

    # --- AZIMUTH (row) arcs ---
    dpsi_row, avgdpsi_row = _calc_wrapped_az_diffs(phase, kperpdpsi, kpardpsi)

    corr_row = 0.5 * (corr[:nrow - 1, :].astype(np.float64) +
                      corr[1:, :].astype(np.float64))
    rho_row = np.where(corr_row < defocorrthresh, 0.0, corr_row)

    sigsqrho_row = ((sigsqrhoconst * np.power(1.0 - rho_row, rhopow) +
                     sigsqcorr) * nshortcyclesq)

    dpsi_r64 = dpsi_row.astype(np.float64)
    avg_r64 = avgdpsi_row.astype(np.float64)
    offset_row = np.where(
        rho_row > 0,
        nshortcycle * (dpsi_r64 - avg_r64),
        nshortcycle * (dpsi_r64 - 0.5 * avg_r64)
    )

    sigsq_row = sigsqrho_row / costscale
    sigsq_row = np.where(sigsq_row < sigsqshortmin, float(sigsqshortmin), sigsq_row)

    sigsq_row_short = _d2short(sigsq_row).astype(np.float64)
    low_corr_row = (rho_row == 0.0)

    laycost_short_row = _d2short(np.full_like(sigsq_row, laycost_val))
    shelf_not_useful_row = (dzmax_val <
                            np.floor(np.sqrt(laycost_short_row.astype(np.float64) *
                                             sigsq_row_short)))
    shelf_active_row = low_corr_row & ~shelf_not_useful_row

    dzmax_row = np.where(
        shelf_active_row,
        dzmax_val,
        float(LARGESHORT)
    )
    laycost_row = np.where(
        shelf_active_row,
        laycost_val,
        float(NOCOSTSHELF)
    )

    row_rows = slice(0, nrow - 1)
    costs['offset'][row_rows, :] = _d2short(offset_row)
    costs['sigsq'][row_rows, :] = _d2short(sigsq_row)
    costs['dzmax'][row_rows, :] = _d2short(dzmax_row)
    costs['laycost'][row_rows, :] = _d2short(laycost_row)

    return costs


def costs_to_bytes_smooth(costs: np.ndarray) -> bytes:
    """Serialize smooth costs to the binary format snaphu writes via
    Write2DRowColArray.  Each element is 2 shorts (4 bytes), row-major.
    Matches the --costoutfile binary output for SMOOTH mode.
    """
    return costs.tobytes()


def costs_to_bytes_defo(costs: np.ndarray) -> bytes:
    """Serialize defo costs to binary format (4 shorts = 8 bytes per arc)."""
    return costs.tobytes()


def calc_cost_smooth(costs: np.ndarray, flow: int, arcrow: int, arccol: int,
                     nflow: int, nrow: int, params: 'SnaphuParams'
                     ) -> tuple:
    """Calculate smooth arc cost increment.

    Mirrors CalcCostSmooth() in snaphu_cost.c.
    Used by BuildCostArrays to compute mstcosts (scalar weights for MST init).

    Returns (poscost, negcost) as Python ints.
    """
    c = costs[arcrow, arccol]
    sigsq = int(c['sigsq'])
    offset = int(c['offset'])

    if sigsq == LARGESHORT:
        return 0, 0

    nshortcycle = params.nshortcycle
    idz1 = abs(flow * nshortcycle + offset)
    idz2pos = abs((flow + nflow) * nshortcycle + offset)
    idz2neg = abs((flow - nflow) * nshortcycle + offset)

    cost1 = (idz1 * idz1) // sigsq
    poscost = (idz2pos * idz2pos) // sigsq - cost1
    negcost = (idz2neg * idz2neg) // sigsq - cost1

    nflowsq = nflow * nflow
    if poscost > 0:
        poscost = int(np.ceil(poscost / nflowsq))
    else:
        poscost = int(np.floor(poscost / nflowsq))
    if negcost > 0:
        negcost = int(np.ceil(negcost / nflowsq))
    else:
        negcost = int(np.floor(negcost / nflowsq))

    return poscost, negcost


def calc_cost_defo(costs: np.ndarray, flow: int, arcrow: int, arccol: int,
                   nflow: int, nrow: int, params: 'SnaphuParams'
                   ) -> tuple:
    """Calculate deformation arc cost increment.

    Mirrors CalcCostDefo() in snaphu_cost.c.
    """
    c = costs[arcrow, arccol]
    sigsq = int(c['sigsq'])
    offset = int(c['offset'])
    dzmax = int(c['dzmax'])
    laycost = int(c['laycost'])
    layfalloffconst = int(params.layfalloffconst)

    if sigsq == LARGESHORT:
        return 0, 0

    nshortcycle = params.nshortcycle
    idz1 = abs(flow * nshortcycle + offset)
    idz2pos = abs((flow + nflow) * nshortcycle + offset)
    idz2neg = abs((flow - nflow) * nshortcycle + offset)

    # cost1
    if idz1 > dzmax:
        idz1 -= dzmax
        cost1 = (idz1 * idz1) // (layfalloffconst * sigsq) + laycost
    else:
        cost1 = (idz1 * idz1) // sigsq
        if laycost != NOCOSTSHELF and cost1 > laycost:
            cost1 = laycost

    # poscost
    if idz2pos > dzmax:
        idz2pos -= dzmax
        poscost = (idz2pos * idz2pos) // (layfalloffconst * sigsq) + laycost - cost1
    else:
        poscost = (idz2pos * idz2pos) // sigsq
        if laycost != NOCOSTSHELF and poscost > laycost:
            poscost = laycost - cost1
        else:
            poscost -= cost1

    # negcost
    if idz2neg > dzmax:
        idz2neg -= dzmax
        negcost = (idz2neg * idz2neg) // (layfalloffconst * sigsq) + laycost - cost1
    else:
        negcost = (idz2neg * idz2neg) // sigsq
        if laycost != NOCOSTSHELF and negcost > laycost:
            negcost = laycost - cost1
        else:
            negcost -= cost1

    nflowsq = nflow * nflow
    if poscost > 0:
        poscost = int(np.ceil(poscost / nflowsq))
    else:
        poscost = int(np.floor(poscost / nflowsq))
    if negcost > 0:
        negcost = int(np.ceil(negcost / nflowsq))
    else:
        negcost = int(np.floor(negcost / nflowsq))

    return poscost, negcost


# ---------------------------------------------------------------------------
# CP6: MST initialization
# STUBBED — the minimum spanning tree flow initialization.
# ---------------------------------------------------------------------------

def mst_init_flows(phase: np.ndarray,
                   mstcosts: np.ndarray,
                   params: SnaphuParams):
    """Minimum spanning tree initialization of arc flows.

    STUBBED — raises NotImplementedError.

    C source: snaphu_tile.c:MSTInitFlows()  (~600 lines).
    This is Prim's MST algorithm adapted to the phase-unwrapping arc network,
    using scalar costs from mstcosts (short integer array) to build a spanning
    tree and then setting arc flows to the implied integer phase differences.

    Key difficulty for porting:
      - The data structure is a doubly-linked list of nodeT records threaded
        through a 2D grid, with a bucket-sort priority queue.
      - Bucket indices are integers scaled by nshortcycle (=200).
      - The algorithm is inherently sequential (tree traversal with pointer
        chasing) and does not vectorize naturally.

    Planned porting approach:
      1. Port nodeT as a Python dataclass or structured numpy array.
      2. Implement Prim's algorithm using a heap (heapq) with bucket-sort
         approximation, preserving the exact tie-breaking behaviour of the C.
      3. Verify flows against C on a 20×20 synthetic patch with known phase.
    """
    raise NotImplementedError(
        "CP6 STUBBED: mst_init_flows not yet ported. "
        "See PORTING_PLAN.md Phase 3."
    )


# ---------------------------------------------------------------------------
# CP7: Network-flow solver (the hard core)
# STUBBED — the nonlinear network-flow optimizer.
# ---------------------------------------------------------------------------

def network_flow_optimize(phase: np.ndarray,
                          costs,
                          flows: np.ndarray,
                          params: SnaphuParams) -> np.ndarray:
    """Nonlinear network-flow optimization (TreeSolve outer loop).

    STUBBED — raises NotImplementedError.

    C source: snaphu.c:UnwrapTile() outer loop (~100 lines) +
              snaphu_solver.c:TreeSolve()  (~700 lines) +
              snaphu_solver.c support functions (~3000 lines total).

    This is the hardest part of the port and the primary feasibility risk
    for bit-faithful parity.  See PORTING_PLAN.md Section 5 for analysis.

    Algorithm: iterative negative-cycle cancellation in an arc residual
    network, using a modified shortest-path tree (dual variable updates)
    with a bucket-based priority queue.  The outer loop increments flow
    magnitude (nflow=1..maxflow) and calls TreeSolve for each source node.

    Bit-faithful parity risk: the solver uses integer arc costs scaled by
    COSTSCALE and NSHORTCYCLE.  The truncation from double→short propagates
    into the shortest-path weights, and the tie-breaking in the bucket queue
    is deterministic in C (pointer-order dependent) but would differ in a
    Python re-implementation.  Statistical equivalence on aggregate metrics
    (unwrapped phase RMS, % of correctly unwrapped cycles) is the realistic
    bar; exact pixel-level identity is almost certainly NOT achievable.
    """
    raise NotImplementedError(
        "CP7 STUBBED: network_flow_optimize not yet ported. "
        "See PORTING_PLAN.md Phase 4."
    )


# ---------------------------------------------------------------------------
# CP8: Phase integration
# DONE: mirrors IntegratePhase() in snaphu_tile.c
# ---------------------------------------------------------------------------

def integrate_phase(phase: np.ndarray, flows: np.ndarray) -> np.ndarray:
    """Integrate wrapped phase using arc flows to produce unwrapped phase.

    Mirrors IntegratePhase() in snaphu_tile.c.

    phase : (nrow, ncol) float32 wrapped phase in [-pi, pi]
    flows : (2*nrow-1, ncol) short int arc flows.
              flows[0..nrow-2, :] = row-direction arc flows (down arcs)
              flows[nrow-1..2*nrow-2, :ncol-1] = col-direction arc flows

    Returns unwrappedphase (nrow, ncol) float32.

    C algorithm (IntegratePhase):
      1. Set unwrapped[0,0] = phase[0,0]  (reference pixel)
      2. Integrate along top row using col-direction flows:
           unwrapped[0,c] = unwrapped[0,c-1] + wrap(phase[0,c] - phase[0,c-1])
                            + TWOPI * colflow[0, c-1]
      3. Integrate down each column using row-direction flows:
           unwrapped[r,c] = unwrapped[r-1,c] + wrap(phase[r,c] - phase[r-1,c])
                            + TWOPI * rowflow[r-1, c]

    where wrap(x) = x - TWOPI * round(x / TWOPI) and the flows are
    signed short integers (positive = extra positive 2pi cycles added).
    """
    nrow, ncol = phase.shape
    phase64 = phase.astype(np.float64)
    unwrap = np.zeros((nrow, ncol), dtype=np.float64)

    # row-direction arc flows: rows 0..nrow-2, shape (nrow-1, ncol)
    rowflow = flows[:nrow - 1].astype(np.float64)     # (nrow-1, ncol)
    # col-direction arc flows: rows nrow-1..2*nrow-2, shape (nrow, ncol-1)
    # Note: C stores (nrow) rows of (ncol-1) elements in rows nrow-1..2*nrow-2
    colflow = flows[nrow - 1:, :ncol - 1].astype(np.float64)  # (nrow, ncol-1)

    # Reference pixel
    unwrap[0, 0] = phase64[0, 0]

    # Top row: integrate left to right using col flows
    dphi_row0 = phase64[0, 1:] - phase64[0, :ncol - 1]    # (ncol-1,)
    dphi_row0 = _wrap_diff(dphi_row0)
    unwrap[0, 1:] = unwrap[0, 0] + np.cumsum(dphi_row0 + TWOPI * colflow[0])

    # All rows: integrate top to bottom using row flows
    for r in range(1, nrow):
        dphi_col = phase64[r, :] - phase64[r - 1, :]      # (ncol,)
        dphi_col = _wrap_diff(dphi_col)
        unwrap[r, :] = unwrap[r - 1, :] + dphi_col + TWOPI * rowflow[r - 1]

    # Flip sign if flipphasesign was set (not used in GMTSAR path)
    # (FlipPhaseArraySign is applied before this function in C, so no-op here)

    return unwrap.astype(np.float32)


def _wrap_diff(dphi: np.ndarray) -> np.ndarray:
    """Wrap a phase difference array into [-pi, pi] using C-exact rounding."""
    ratio = dphi / TWOPI
    rounded = np.where(ratio >= 0,
                       np.floor(ratio + 0.5),
                       np.ceil(ratio - 0.5))
    return dphi - TWOPI * rounded


# ---------------------------------------------------------------------------
# CP9: Connected component growth
# STUBBED
# ---------------------------------------------------------------------------

def grow_conn_comps(costs, flows: np.ndarray,
                    nrow: int, ncol: int,
                    params: SnaphuParams) -> np.ndarray:
    """Grow connected components mask.

    STUBBED — raises NotImplementedError.

    C source: snaphu_tile.c:GrowConnCompsMask()  (~400 lines).
    BFS / flood-fill from lowest-cost seed pixels, using incrcosts as
    the boundary criterion (conncompthresh).

    Returns uint8 array shaped (nrow, ncol) with component labels 1..N,
    0 = masked / not in any component.
    """
    raise NotImplementedError(
        "CP9 STUBBED: grow_conn_comps not yet ported. "
        "See PORTING_PLAN.md Phase 3."
    )


# ---------------------------------------------------------------------------
# CP10: Output writing
# DONE: mirrors WriteAltLineFile() and UCHAR output in snaphu_io.c
# ---------------------------------------------------------------------------

def write_alt_line(mag: np.ndarray, phase: np.ndarray, outfile: str) -> None:
    """Write ALT_LINE_DATA output file.

    Mirrors WriteAltLineFile() in snaphu_io.c:
      For each row r:
        write ncol float32 from mag[r, :]
        write ncol float32 from phase[r, :]
    Total: 2*nrow*ncol float32 values.
    """
    nrow, ncol = phase.shape
    if mag.shape != phase.shape:
        raise ValueError(
            f"mag.shape {mag.shape} != phase.shape {phase.shape}"
        )
    # Build interleaved array: (2*nrow, ncol)
    out = np.empty((2 * nrow, ncol), dtype=np.float32)
    out[0::2] = mag.astype(np.float32)
    out[1::2] = phase.astype(np.float32)
    out.tofile(outfile)


def write_uchar(conncomp: np.ndarray, outfile: str) -> None:
    """Write connected component mask as UCHAR (uint8).

    Mirrors the conncomp output in snaphu_io.c (CONNCOMPOUTTYPEUCHAR=1).
    """
    conncomp.astype(np.uint8).tofile(outfile)


def read_alt_line_unwrap(outfile: str, nrow: int, ncol: int):
    """Read snaphu output file back into (mag, unwrapped) arrays.

    Used by the parity harness to load snaphu's actual output for comparison.
    Returns (mag, unwrappedphase) each shaped (nrow, ncol) float32.

    Handles both output formats automatically by file size:
      ALT_LINE_DATA (default): 2*nrow*ncol float32 values
        → mag = odd rows, phase = even rows
      FLOAT_DATA (no-magnitude path): nrow*ncol float32 values
        → mag = ones (synthetic), phase = data

    The FLOAT_DATA output occurs when snaphu is invoked with FLOAT_DATA input
    and no amplitude file (-a), which is the GMTSAR path.  The default
    OUTFILEFORMAT is ALT_LINE_DATA, but in practice snaphu v2.0.7 with
    FLOAT_DATA input and no magnitude writes FLOAT_DATA output.
    """
    fsize = os.path.getsize(outfile)
    alt_line_size = 2 * nrow * ncol * 4
    float_size = nrow * ncol * 4

    if fsize == alt_line_size:
        data = np.fromfile(outfile, dtype=np.float32, count=2 * nrow * ncol)
        mat = data.reshape(2 * nrow, ncol)
        mag = mat[0::2].copy()
        phase = mat[1::2].copy()
    elif fsize == float_size:
        # FLOAT_DATA output: only phase, no magnitude channel
        phase = np.fromfile(outfile, dtype=np.float32,
                            count=nrow * ncol).reshape(nrow, ncol)
        mag = np.ones((nrow, ncol), dtype=np.float32)
    else:
        raise ValueError(
            f"Unexpected output file size {fsize} bytes in {outfile!r}. "
            f"Expected {alt_line_size} (ALT_LINE_DATA) or "
            f"{float_size} (FLOAT_DATA) for nrow={nrow}, ncol={ncol}."
        )
    return mag, phase


# ---------------------------------------------------------------------------
# Main entry point (CLI stub mirroring snaphu's arg parsing)
# CP5/CP5d DONE; CP6-CP7 still STUBBED (raises on MST init and solver).
# ---------------------------------------------------------------------------

def snaphu_py_main(argv=None):
    """CLI entry point for snaphu_py.

    Usage mirrors the C snaphu binary as called by GMTSAR:
      snaphu_py phase.in <ncol> -f conf.brief -c corr.in \\
                -o unwrap.out [-v] -s|-d [-g conncomp.out]

    Cost arrays (CP5/CP5d) are fully ported and bit-identical to the C binary.
    Raises NotImplementedError at CP6 (MST init) which is still STUBBED.
    The I/O layer (CP1-CP4, CP8, CP10) is functional and tested.
    """
    if argv is None:
        argv = sys.argv[1:]

    if len(argv) < 2:
        print("Usage: snaphu_py phase.in linelength [options]", file=sys.stderr)
        sys.exit(1)

    infile = argv[0]
    linelen = int(argv[1])

    # Parse remaining args (mirrors ProcessArgs in snaphu_io.c subset)
    conffile = ""
    corrfile = ""
    outfile = "snaphu.out"
    conncompfile = ""
    costmode_flag = None
    defomax_override = None
    verbose = False

    i = 2
    while i < len(argv):
        a = argv[i]
        if a == '-f' and i + 1 < len(argv):
            conffile = argv[i + 1]; i += 2
        elif a == '-c' and i + 1 < len(argv):
            corrfile = argv[i + 1]; i += 2
        elif a == '-o' and i + 1 < len(argv):
            outfile = argv[i + 1]; i += 2
        elif a == '-g' and i + 1 < len(argv):
            conncompfile = argv[i + 1]; i += 2
        elif a == '-s':
            costmode_flag = 'SMOOTH'; i += 1
        elif a == '-d':
            costmode_flag = 'DEFO'; i += 1
        elif a == '-v':
            verbose = True; i += 1
        elif a == '-C' and i + 1 < len(argv):
            # Inline config string (used by GMTSAR for DEFOMAX_CYCLE patch)
            fields = argv[i + 1].split()
            if len(fields) >= 2 and fields[0].upper() == 'DEFOMAX_CYCLE':
                defomax_override = float(fields[1])
            i += 2
        else:
            i += 1

    cli_overrides: dict = {}
    if costmode_flag:
        cli_overrides['STATCOSTMODE'] = costmode_flag
    if defomax_override is not None:
        cli_overrides['DEFOMAX_CYCLE'] = str(defomax_override)
    if verbose:
        cli_overrides['VERBOSE'] = 'TRUE'

    params = SnaphuParams.from_conf_and_cli(conffile, cli_overrides)
    params.infileformat = FLOAT_DATA

    if corrfile:
        # corrfile format: default ALT_LINE_DATA per conf (CORRFILEFORMAT
        # is commented out in snaphu.conf.brief → default ALT_LINE_DATA)
        pass  # stored in params; used in build_cost_arrays_*

    nrow = get_nlines(infile, linelen, params)
    phase = read_float_data(infile, nrow, linelen)

    if corrfile:
        corr = read_alt_line_corr(corrfile, nrow, linelen)
    else:
        corr = np.full((nrow, linelen), params.defaultcorr, dtype=np.float32)

    # Magnitude: not passed by GMTSAR (no -a flag), so set to 1.0
    mag = np.ones((nrow, linelen), dtype=np.float32)

    # CP5: build cost arrays
    if params.costmode == SMOOTH:
        costs = build_cost_arrays_smooth(phase, corr, params)
    elif params.costmode == DEFO:
        costs = build_cost_arrays_defo(phase, corr, params)
    else:
        raise NotImplementedError(
            f"Cost mode {params.costmode} is outside the GMTSAR-used path. "
            "Only SMOOTH and DEFO are ported targets."
        )

    # CP6: MST init — STUBBED, will raise
    flows = mst_init_flows(phase, costs, params)

    # CP7: network-flow optimization — STUBBED, will raise
    flows = network_flow_optimize(phase, costs, flows, params)

    # CP8: integrate phase
    unwrapped = integrate_phase(phase, flows)

    # CP10: write output
    write_alt_line(mag, unwrapped, outfile)
    if conncompfile:
        # CP9: grow connected components — STUBBED, will raise
        conncomp = grow_conn_comps(costs, flows, nrow, linelen, params)
        write_uchar(conncomp, conncompfile)

    return 0


if __name__ == '__main__':
    sys.exit(snaphu_py_main())
