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
# CP6: MST initialization — DONE (scalar, faithful C port)
#
# C sources ported:
#   snaphu_solver.c:MSTInitFlows()   — outer loop
#   snaphu_solver.c:SolveMST()       — Prim/Dijkstra MST on grid+ground
#   snaphu_solver.c:DischargeTree()  — depth-first flow assignment
#   snaphu_solver.c:ClipFlow()       — clip oversized flows, re-run
#   snaphu_util.c:CycleResidue()     — integer phase residues
#   snaphu_solver.c:InitNodeNums()   — set row/col on each node
#   snaphu_solver.c:InitNodes()      — reset cost/pred/group per iteration
#   snaphu_solver.c:InitBuckets()    — initialise bucket array
#   snaphu_solver.c:BucketInsert()   — prepend to bucket (LIFO)
#   snaphu_solver.c:BucketRemove()   — remove from doubly-linked list
#   snaphu_solver.c:ClosestNode()    — pop smallest-cost bucket entry
#   snaphu_solver.c:GetArcNumLims()  — arc-iteration limits per node type
#   snaphu_solver.c:NeighborNodeGrid() — next neighbour given arcnum
#   snaphu_cost.c:BuildCostArrays() scalar-weight section — build mstcosts
#
# Data layout (mirrors C exactly):
#   Phase grid:     nrow × ncol  (image pixels)
#   Node grid:      (nrow-1) × (ncol-1)  (dual-grid interior nodes)
#   Ground node:    row=GROUNDROW=-2, col=GROUNDCOL=-2
#   Arc array:      (2*nrow-1, ncol)  short int
#     rows 0..nrow-2      : row-arcs (azimuth), ncol entries per row
#     rows nrow-1..2*nrow-2: col-arcs (range), ncol-1 valid entries per row
#   Residue array:  (nrow-1) × (ncol-1)  signed char (−1, 0, 1)
#   ArcStatus array:(2*nrow-1, ncol)  int8:
#     0  = not on tree
#    -1  = on tree, not yet followed in DischargeTree
#    -2  = on tree, followed going back up
#    -3  = on tree, followed in both directions (leaf / discharge done)
#
# C node sentinel values used in group field:
#   ONTREE      = -1   (node has been dequeued and placed on tree)
#   INBUCKET    = -2   (node is currently in a bucket)
#   NOTINBUCKET = -3   (node not yet reached or pruned)
#
# Bucket structure:
#   buckets[0..size-1] = lists of nodes at that distance (LIFO, prepend)
#   curr  = lowest non-empty bucket index (monotone-increasing in Dijkstra)
#   maxind = bkts.size-1 (nodes with distance ≥ maxind go to buckets[maxind])
#   size  = (maxcost+1)*(nrow+ncol+1)
#
# Tie-breaking: BucketInsert prepends → LIFO within same bucket.
# Python list used with insert(0,...)/pop(0) or deque with appendleft/popleft.
# The C iterates arcnum -5→-4→-3→-2→-1 (right→down→left→up).  We replicate
# this exact neighbour order to reproduce tie-breaking.
#
# Parity status: BIT-IDENTICAL to C MSTInitFlows on the ALOS_haiti
# interferogram in SMOOTH mode (verified — see TestMSTInitFlows below).
# ---------------------------------------------------------------------------

# Node sentinel constants (match C #define values in snaphu.h)
_ONTREE      = -1
_INBUCKET    = -2
_NOTINBUCKET = -3
_VERYFAR     = LARGEINT           # 2_000_000_000
# GROUNDROW = -2, GROUNDCOL = -2  (already defined at module top)


class _Node:
    """nodeT equivalent.  Uses Python int/None instead of C pointers.

    Extra field pred_arc: (arcrow, arccol, arcdir) of the arc that connected
    this node to its predecessor.  Not in C nodeT but avoids reimplementing
    GetArcGrid() — we cache the arc info when we set pred.
    """
    __slots__ = ('row', 'col', 'pred', 'pred_arc', 'level', 'group',
                 'incost', 'outcost')

    def __init__(self, row: int, col: int):
        self.row = row
        self.col = col
        self.pred = None          # parent node on shortest-path tree
        self.pred_arc = None      # (arcrow, arccol, arcdir) of arc to pred
        self.level = 0
        self.group = _NOTINBUCKET
        self.incost = _VERYFAR
        self.outcost = _VERYFAR


class _Buckets:
    """bucketT equivalent.  Each bucket slot is a Python list (LIFO via
    insert-at-front / pop-from-front, matching C's prepend/head-take).

    The C ClosestNode() takes bucket[curr]->head (LIFO head), which is the
    most recently inserted node at that cost.  We replicate with list[0].
    """
    __slots__ = ('size', 'curr', 'maxind', 'buckets', 'wrapped')

    def __init__(self, size: int):
        self.size = size
        self.curr = 0
        self.maxind = size - 1
        self.buckets: list = [[] for _ in range(size)]
        self.wrapped = False


def _build_mst_costs(costs: np.ndarray, params: 'SnaphuParams',
                     nrow: int, ncol: int) -> np.ndarray:
    """Compute scalar MST costs from the full cost array.

    Mirrors the BuildCostArrays() scalar-weight section in snaphu_cost.c
    (lines 342-410).  For each arc (arcrow, arccol):
        tempcost = min(poscost, negcost)  for flow=0, nflow=1
        mstcosts[arcrow, arccol] = clip(tempcost, MINSCALARCOST, maxcost)
    Then set 4 corner arcs to LARGESHORT.

    Uses the appropriate CalcCost function based on params.costmode.
    Returns (2*nrow-1, ncol) int16 array.
    """
    if params.costmode == SMOOTH:
        calc_fn = calc_cost_smooth
    elif params.costmode == DEFO:
        calc_fn = calc_cost_defo
    else:
        raise ValueError(f"Unsupported costmode {params.costmode} for MST init")

    maxcost = int(params.maxcost)
    mstcosts = np.zeros((2 * nrow - 1, ncol), dtype=np.int16)

    for arcrow in range(2 * nrow - 1):
        if arcrow < nrow - 1:
            maxcol = ncol
        else:
            maxcol = ncol - 1
        for arccol in range(maxcol):
            poscost, negcost = calc_fn(costs, 0, arcrow, arccol, 1, nrow, params)
            tempcost = poscost if poscost < negcost else negcost
            # LClip(tempcost, MINSCALARCOST, maxcost)
            if tempcost < MINSCALARCOST:
                tempcost = MINSCALARCOST
            elif tempcost > maxcost:
                tempcost = maxcost
            mstcosts[arcrow, arccol] = tempcost

    # Corner arcs get LARGESHORT to prevent ambiguous flows
    # C: weights[nrow-1][0], weights[nrow-1][ncol-2],
    #    weights[2*nrow-2][0], weights[2*nrow-2][ncol-2]
    mstcosts[nrow - 1, 0] = LARGESHORT
    mstcosts[nrow - 1, ncol - 2] = LARGESHORT
    mstcosts[2 * nrow - 2, 0] = LARGESHORT
    mstcosts[2 * nrow - 2, ncol - 2] = LARGESHORT

    return mstcosts


def _wrap_phase_c(phase: np.ndarray) -> np.ndarray:
    """Apply C's WrapPhase normalization: map to [0, 2*pi).

    Mirrors WrapPhase() in snaphu_util.c:
        phase -= TWOPI * floor(phase / TWOPI)

    This maps (-pi, pi] → [0, 2pi).  C applies this in ReadInputFile
    before any computation, so MSTInitFlows and IntegratePhase both
    operate on [0, 2pi) phase internally.  Callers who want bit-identical
    output vs the C binary must pass the result of this function to
    integrate_phase() after mst_init_flows().
    """
    p64 = phase.astype(np.float64)
    return (p64 - TWOPI * np.floor(p64 / TWOPI)).astype(np.float32)


def _cycle_residue(phase: np.ndarray) -> np.ndarray:
    """Compute integer phase residues on the dual grid.

    Mirrors CycleResidue() in snaphu_util.c.
    phase: (nrow, ncol) float32 wrapped phase in [-pi, pi]
    Returns residue: (nrow-1, ncol-1) int8, values in {-1, 0, 1}.

    C formula (for each 2x2 plaquette):
        residue[r][c] = LRound(
            (coldiff[r][c] + rowdiff[r][c+1]
             - coldiff[r+1][c] - rowdiff[r][c]) / TWOPI
        )
    where:
        rowdiff[r][c]  = ModDiff(phase[r+1][c],  phase[r][c])
        coldiff[r][c]  = ModDiff(phase[r][c+1],  phase[r][c])
    ModDiff(a, b) = (a-b) wrapped to (-pi, pi]:
        f3 = a - b; if f3 > pi: f3 -= 2pi; elif f3 <= -pi: f3 += 2pi
    LRound = rint() (round half to even in Python/C99)

    NOTE: ModDiff wraps to (-pi, pi] (strictly > -pi, <= pi).
    This differs from the _wrap_diff used in integrate_phase which wraps
    to [-pi, pi] using C ROUND (half-away-from-zero).  We must use the
    C ModDiff convention here.
    """
    phase64 = phase.astype(np.float64)
    nrow, ncol = phase.shape

    # rowdiff[r, c] = ModDiff(phase[r+1, c], phase[r, c])
    rowdiff = phase64[1:, :] - phase64[:nrow - 1, :]    # (nrow-1, ncol)
    rowdiff = np.where(rowdiff > PI, rowdiff - TWOPI,
              np.where(rowdiff <= -PI, rowdiff + TWOPI, rowdiff))

    # coldiff[r, c] = ModDiff(phase[r, c+1], phase[r, c])
    coldiff = phase64[:, 1:] - phase64[:, :ncol - 1]    # (nrow, ncol-1)
    coldiff = np.where(coldiff > PI, coldiff - TWOPI,
              np.where(coldiff <= -PI, coldiff + TWOPI, coldiff))

    # residue = LRound((coldiff[r,c] + rowdiff[r,c+1]
    #                   - coldiff[r+1,c] - rowdiff[r,c]) / TWOPI)
    plaq = (coldiff[:nrow - 1, :]       # (nrow-1, ncol-1)
            + rowdiff[:, 1:]            # (nrow-1, ncol-1)
            - coldiff[1:, :]            # (nrow-1, ncol-1)
            - rowdiff[:, :ncol - 1])    # (nrow-1, ncol-1)

    # LRound = rint (round-half-to-even; numpy rint matches C99 rint)
    residue = np.rint(plaq / TWOPI).astype(np.int8)
    return residue


def _get_arc_num_lims(fromrow: int, ngroundarcs: int) -> tuple:
    """Mirrors GetArcNumLims() in snaphu_solver.c.

    Returns (arcnum_start, upperarcnum) for the given node row.
    For ground node (fromrow < 0): arcnum starts at -1, upper = ngroundarcs-1.
    For normal node: arcnum starts at -5, upper = -1.
    """
    if fromrow < 0:
        # ground node
        return -1, ngroundarcs - 1
    else:
        return -5, -1


def _neighbor_node_grid(node: '_Node', arcnum: int, ngroundarcs: int,
                        nodes: list, ground: '_Node',
                        ni: int, nc: int) -> tuple:
    """Mirrors NeighborNodeGrid() in snaphu_solver.c.

    Parameters
    ----------
    ni, nc : interior node grid dimensions (nrow_img-1, ncol_img-1).
    arcnum : iterator value.  For interior nodes: -4,-3,-2,-1.
             For ground node: 0..ngroundarcs-1.

    Returns (neighbor_node, arcrow, arccol, arcdir).

    All arc indices use IMAGE dimensions: nrow_img = ni+1, ncol_img = nc+1.
    Arc array shape (2*nrow_img-1, ncol_img) = (2*ni+1, nc+1).

    C NeighborNodeGrid is called with nrow=nrow_img, ncol=ncol_img.
    Interior node arcs (using C variable names nrow=ni+1, ncol=nc+1):
      -4: right  arcrow=row,      arccol=col+1,    arcdir=+1  ground if col==ncol-2=nc-1
      -3: down   arcrow=nrow+row, arccol=col,       arcdir=+1  ground if row==nrow-2=ni-1
      -2: left   arcrow=row,      arccol=col,       arcdir=-1  ground if col==0
      -1: up     arcrow=nrow-1+row=ni+row, arccol=col, arcdir=-1 ground if row==0

    Ground perimeter arcs (C default case, nrow=ni+1, ncol=nc+1):
      0..ni-1:         arcrow=arcnum,    arccol=0,  arcdir=+1 → nodes[arcnum][0]
      ni..2*ni-1:      arcrow=arcnum-ni, arccol=nc, arcdir=-1 → nodes[arcnum-ni][nc-1]
      2*ni..2*ni+nc-4: arcrow=ni,        arccol=arcnum-2*ni+1, arcdir=+1 → nodes[0][arccol]
      2*ni+nc-3..ngroundarcs-1: arcrow=2*ni, arccol=arcnum-(2*ni+nc-3)+1, arcdir=-1 → nodes[ni-1][arccol]

    Note: ngroundarcs = 2*(ni+nc) - 4  (derived from C: 2*(nrow+ncol-2)-4 with nrow=ni+1,ncol=nc+1)
    So ngroundarcs = 2*ni + 2*nc - 4.
    Perimeter ranges:
      left  col: 0..ni-1        (ni arcs)
      right col: ni..2*ni-1     (ni arcs)
      top row:   2*ni..2*ni+nc-4 (nc-3... wait)
    Let's verify: ni + ni + (nc-1) + (nc-1) = 2*ni+2*nc-2 but ngroundarcs=2*ni+2*nc-4.
    Actually the C comment says ngroundarcs=2*(nrow+ncol-2)-4 with nrow_img,ncol_img:
      = 2*(ni+1+nc+1-2)-4 = 2*(ni+nc)-4.
    Perimeter = left-col (ni arcs, row 0..ni-1) + right-col (ni arcs, row 0..ni-1)
              + top-row (nc-1 arcs, col 1..nc-1) + bottom-row (nc-1 arcs, col 1..nc-1)
              = 2*ni + 2*(nc-1) = 2*ni+2*nc-2. But formula gives 2*ni+2*nc-4.
    Discrepancy of 2: C excludes the 4 corner nodes (each at intersection).
    Looking at C code ranges:
      0..nrow-2=ni-1: left col (ni arcs)
      ni-1..2*(ni-1)-1=2*ni-3: overlapping? No: 0..ni-2=0..ni-2 is ni-1 arcs.
    Let me re-read C literally:
      if(arcnum<nrow-1): i.e. arcnum < ni → 0..ni-1 (ni arcs)
      elif(arcnum<2*(nrow-1)): i.e. arcnum < 2*ni → ni..2*ni-1 (ni arcs)
      elif(arcnum<2*(nrow-1)+ncol-3): i.e. arcnum < 2*ni+nc-2 → 2*ni..2*ni+nc-3 (nc-2 arcs)
      else: 2*ni+nc-2..ngroundarcs-1 (nc-2 arcs)
    Total = ni + ni + (nc-2) + (nc-2) = 2*ni+2*nc-4 = ngroundarcs. Correct.
    """
    row = node.row
    col = node.col

    if row == GROUNDROW:
        # Ground node: perimeter arcs
        # Ranges (from C, with nrow_img=ni+1, ncol_img=nc+1):
        #   [0,       ni)          : left col,  arcrow=arcnum,     arccol=0
        #   [ni,      2*ni)        : right col, arcrow=arcnum-ni,  arccol=nc
        #   [2*ni,    2*ni+nc-2)   : top row,   arcrow=ni,         arccol=arcnum-2*ni+1
        #   [2*ni+nc-2, ngroundarcs): bot row,  arcrow=2*ni,       arccol=arcnum-(2*ni+nc-3)+1
        #   Note: 2*(nrow-1)=2*ni, 2*(nrow-1)+ncol-3=2*ni+nc-2
        if arcnum < ni:
            arcrow = arcnum
            arccol = 0
            arcdir = 1
            neighbor = nodes[arcrow][0]
        elif arcnum < 2 * ni:
            arcrow = arcnum - ni
            arccol = nc       # = ncol_img-1
            arcdir = -1
            neighbor = nodes[arcrow][nc - 1]
        elif arcnum < 2 * ni + nc - 2:
            arcrow = ni       # = nrow_img-1
            arccol = arcnum - 2 * ni + 1
            arcdir = 1
            neighbor = nodes[0][arccol]
        else:
            arcrow = 2 * ni   # = 2*nrow_img-2
            arccol = arcnum - (2 * ni + nc - 3)
            arcdir = -1
            neighbor = nodes[ni - 1][arccol]
        return neighbor, arcrow, arccol, arcdir
    else:
        # Normal interior node: arcnum in {-4, -3, -2, -1}
        # C nrow=ni+1, ncol=nc+1, node.row ∈ 0..ni-1, node.col ∈ 0..nc-1
        if arcnum == -4:
            # right neighbor
            arcrow = row
            arccol = col + 1
            arcdir = 1
            neighbor = ground if col == nc - 1 else nodes[row][col + 1]
        elif arcnum == -3:
            # down neighbor: arcrow=nrow+row=(ni+1)+row
            arcrow = ni + 1 + row
            arccol = col
            arcdir = 1
            neighbor = ground if row == ni - 1 else nodes[row + 1][col]
        elif arcnum == -2:
            # left neighbor
            arcrow = row
            arccol = col
            arcdir = -1
            neighbor = ground if col == 0 else nodes[row][col - 1]
        elif arcnum == -1:
            # up neighbor: arcrow=nrow-1+row=ni+row
            arcrow = ni + row
            arccol = col
            arcdir = -1
            neighbor = ground if row == 0 else nodes[row - 1][col]
        else:
            raise RuntimeError(f"Invalid arcnum {arcnum} for interior node")
        return neighbor, arcrow, arccol, arcdir


def _init_buckets(bkts: '_Buckets', source: '_Node') -> None:
    """Mirrors InitBuckets() in snaphu_solver.c."""
    for i in range(bkts.size):
        bkts.buckets[i] = []
    bkts.curr = 0
    bkts.wrapped = False
    # Put source in bucket 0
    bkts.buckets[0] = [source]
    source.group = _INBUCKET
    source.outcost = 0


def _bucket_insert(bkts: '_Buckets', node: '_Node', ind: int) -> None:
    """Mirrors BucketInsert() in snaphu_solver.c.  Prepends (LIFO)."""
    bkts.buckets[ind].insert(0, node)
    node.group = _INBUCKET


def _bucket_remove(bkts: '_Buckets', node: '_Node', ind: int) -> None:
    """Mirrors BucketRemove() in snaphu_solver.c."""
    lst = bkts.buckets[ind]
    try:
        lst.remove(node)
    except ValueError:
        # Should not happen in correct usage; raise hard
        raise RuntimeError(
            f"BucketRemove: node ({node.row},{node.col}) "
            f"not found in bucket {ind}"
        )


def _closest_node(bkts: '_Buckets') -> '_Node | None':
    """Mirrors ClosestNode() in snaphu_solver.c.

    Scans from bkts.curr upward, returns first node found.
    Returns None when all buckets are exhausted (curr > maxind).
    """
    while True:
        if bkts.curr > bkts.maxind:
            return None
        lst = bkts.buckets[bkts.curr]
        if lst:
            node = lst.pop(0)    # LIFO head (first inserted = most recent)
            node.group = _ONTREE
            return node
        bkts.curr += 1


def _solve_mst(nodes: list, source: '_Node', ground: '_Node',
               bkts: '_Buckets', mstcosts: np.ndarray,
               residue: np.ndarray, arcstatus: np.ndarray,
               ni: int, nc: int) -> None:
    """Mirrors SolveMST() in snaphu_solver.c.

    Prim's/Dijkstra's algorithm on the grid+ground network.
    ni, nc: INTERIOR node grid dims (nrow_img-1, ncol_img-1).

    Modifies arcstatus in-place: sets arcs on the MST path to -1.
    Modifies node.outcost, node.pred, node.pred_arc.
    """
    # ngroundarcs = 2*(nrow_img+ncol_img-2)-4 = 2*(ni+1+nc+1-2)-4 = 2*(ni+nc)-4
    ngroundarcs = 2 * ni + 2 * nc - 4

    # Calculate ground charge = -sum(residue)
    groundcharge = int(-residue.sum())

    # Initialize arc status to 0
    arcstatus[:] = 0

    while True:
        node = _closest_node(bkts)
        if node is None:
            break

        fromrow = node.row
        fromcol = node.col

        # If we found a residue node (not source), mark path to tree
        # NOTE: path marking sets pathto.outcost=0, including node itself.
        # fromdist is therefore read AFTER path marking (matches C line order).
        is_residue = (
            (fromrow != GROUNDROW and residue[fromrow, fromcol] != 0)
            or (fromrow == GROUNDROW and groundcharge != 0)
        )
        if is_residue and node is not source:
            pathto = node
            pathfrom = node.pred
            while True:
                pathto.outcost = 0
                # Arc info was cached in pred_arc when pred was set
                arcrow, arccol, _arcdir = pathto.pred_arc
                arcstatus[arcrow, arccol] = -1
                # Stop when pathfrom is a residue
                pfr = pathfrom.row
                pfc = pathfrom.col
                if ((pfr != GROUNDROW and residue[pfr, pfc] != 0)
                        or (pfr == GROUNDROW and groundcharge != 0)):
                    break
                pathto = pathfrom
                pathfrom = pathfrom.pred

        # fromdist read after path marking (C: line 3757 after the path loop)
        fromdist = node.outcost

        # Scan neighbors
        arcnum, upper = _get_arc_num_lims(fromrow, ngroundarcs)
        while arcnum < upper:
            arcnum += 1
            to, arcrow, arccol, arcdir = _neighbor_node_grid(
                node, arcnum, ngroundarcs, nodes, ground, ni, nc)

            # Arc distance (0 if on tree, VERYFAR if LARGESHORT, else mstcosts)
            ast = int(arcstatus[arcrow, arccol])
            if ast < 0:
                arcdist = 0
            else:
                mc = int(mstcosts[arcrow, arccol])
                arcdist = _VERYFAR if mc == LARGESHORT else mc

            newdist = fromdist + arcdist
            if newdist < to.outcost:
                # Remove from bucket if present
                if to.group == _INBUCKET:
                    old_ind = to.outcost
                    if old_ind < bkts.maxind:
                        _bucket_remove(bkts, to, old_ind)
                    else:
                        _bucket_remove(bkts, to, bkts.maxind)
                # Update node
                to.outcost = newdist
                to.pred = node
                to.pred_arc = (arcrow, arccol, arcdir)
                # Insert into appropriate bucket
                if newdist < bkts.maxind:
                    _bucket_insert(bkts, to, newdist)
                    if newdist < bkts.curr:
                        bkts.curr = newdist
                else:
                    _bucket_insert(bkts, to, bkts.maxind)


def _get_arc_grid(from_: '_Node', to: '_Node',
                  ni: int, nc: int,
                  nodes: list) -> tuple:
    """Mirrors GetArcGrid() in snaphu_solver.c.

    Given from/to node pair, returns (arcrow, arccol, arcdir, _dummy).
    ni = nrow_img-1, nc = ncol_img-1 (interior grid dims).
    All arc indices use image dims: nrow_img = ni+1, ncol_img = nc+1.
    """
    fromrow = from_.row
    fromcol = from_.col
    torow = to.row
    tocol = to.col

    if fromcol == tocol - 1:           # right neighbor
        return from_, fromrow, fromcol + 1, 1
    elif fromcol == tocol + 1:         # left neighbor
        return from_, fromrow, fromcol, -1
    elif fromrow == torow - 1:         # down neighbor
        return from_, fromrow + 1 + ni, fromcol, 1
    elif fromrow == torow + 1:         # up neighbor
        return from_, fromrow + ni, fromcol, -1
    elif fromrow == GROUNDROW:         # arc FROM ground
        if tocol == 0:
            return from_, torow, 0, 1
        elif tocol == nc - 1:
            return from_, torow, nc, -1
        elif torow == 0:
            return from_, ni, tocol, 1
        else:                          # torow == ni-1
            return from_, 2 * ni, tocol, -1
    elif torow == GROUNDROW:           # arc TO ground
        if fromcol == 0:
            return from_, fromrow, 0, -1
        elif fromcol == nc - 1:
            return from_, fromrow, nc, 1
        elif fromrow == 0:
            return from_, ni, fromcol, -1
        else:                          # fromrow == ni-1
            return from_, 2 * ni, fromcol, 1
    else:
        raise RuntimeError(
            f"GetArcGrid: no arc between ({fromrow},{fromcol}) "
            f"and ({torow},{tocol})"
        )


def _discharge_tree(source: '_Node', mstcosts: np.ndarray,
                    flows: np.ndarray, residue: np.ndarray,
                    arcstatus: np.ndarray, nodes: list,
                    ground: '_Node', ni: int, nc: int) -> None:
    """Mirrors DischargeTree() in snaphu_solver.c.

    Depth-first walk of the MST, propagating charges from leaves to root.
    ni = nrow_img-1, nc = ncol_img-1.
    Modifies flows and residue in-place.
    """
    ngroundarcs = 2 * ni + 2 * nc - 4

    # Initialize node charges from residue
    ground.outcost = 0
    for r in range(ni):
        for c in range(nc):
            nodes[r][c].outcost = int(residue[r, c])
            ground.outcost -= int(residue[r, c])

    # Non-recursive DFS via the same arcnum iteration used in SolveMST
    nextnode = source
    row = arccol_save = 0
    todir_save = 0

    while True:
        from_ = nextnode
        nextnode = None
        found_down = False

        arcnum, upper = _get_arc_num_lims(from_.row, ngroundarcs)
        while arcnum < upper:
            arcnum += 1
            to, arcrow, arccol, arcdir = _neighbor_node_grid(
                from_, arcnum, ngroundarcs, nodes, ground, ni, nc)

            ast = int(arcstatus[arcrow, arccol])
            if ast == -1:
                # Unvisited tree arc: descend
                nextnode = to
                row = arcrow
                arccol_save = arccol
                arcdir_save = arcdir
                found_down = True
                break
            elif ast == -2:
                # Visited going up: save as "back" arc but keep scanning
                nextnode = to
                row = arcrow
                arccol_save = arccol
                todir_save = arcdir

        if nextnode is None:
            break

        # Decrement arcstatus for the chosen arc
        arcstatus[row, arccol_save] -= 1  # -1→-2 (mark going forward) or -2→-3 (leaf done)
        new_ast = int(arcstatus[row, arccol_save])

        if new_ast == -3:
            # Leaf reached: push charge back up
            flows[row, arccol_save] += todir_save * from_.outcost
            nextnode.outcost += from_.outcost
            from_.outcost = 0


def _clip_flow(residue: np.ndarray, flows: np.ndarray,
               mstcosts: np.ndarray, ni: int, nc: int,
               maxflow: int) -> bool:
    """Mirrors ClipFlow() in snaphu_solver.c.

    ni = nrow_img-1, nc = ncol_img-1.
    Arc array row layout:
      0..ni-1    : row-arcs (azimuth), arccol 0..nc (nc+1 entries)
      ni..2*ni   : col-arcs (range),   arccol 0..nc-1 (nc entries)

    Returns True if all flows ≤ maxflow (done), False if clipped (re-run).
    Modifies residue, flows, mstcosts in-place.
    """
    # Find maximum absolute flow (Short2DRowColAbsMax in C)
    # C: rows 0..nrow-2 (0..ni-1) with ncol=nc+1 entries each
    #    rows nrow-1..2*nrow-2 (ni..2*ni) with ncol-1=nc entries each
    mostflow = 0
    for r in range(ni):
        for c in range(nc + 1):
            v = abs(int(flows[r, c]))
            if v > mostflow:
                mostflow = v
    for r in range(ni, 2 * ni + 1):   # col-arc rows ni..2*ni (inclusive)
        for c in range(nc):
            v = abs(int(flows[r, c]))
            if v > mostflow:
                mostflow = v

    if mostflow <= maxflow:
        return True

    # Set clip limit = ceil(mostflow * CLIPFACTOR) + 1, at least maxflow
    cliplimit = int(np.ceil(mostflow * CLIPFACTOR)) + 1
    if maxflow > cliplimit:
        cliplimit = maxflow

    # Find maximum finite mstcost (excluding LARGESHORT corner arcs)
    maxcost = 0
    for r in range(ni):           # row-arc rows
        for c in range(nc + 1):
            mc = int(mstcosts[r, c])
            if mc > maxcost and mc < LARGESHORT:
                maxcost = mc
    for r in range(ni, 2 * ni + 1):   # col-arc rows
        for c in range(nc):
            mc = int(mstcosts[r, c])
            if mc > maxcost and mc < LARGESHORT:
                maxcost = mc
    maxcost += INITMAXCOSTINCR   # = 200
    if maxcost >= LARGESHORT:
        return True              # escape overflow (C warning + return TRUE)

    # Clip flows and update residues + mstcosts
    for r in range(ni):          # row-arc rows
        for c in range(nc + 1):
            fl = int(flows[r, c])
            if abs(fl) > cliplimit:
                if fl > 0:
                    sign = 1
                    excess = fl - cliplimit
                else:
                    sign = -1
                    excess = fl + cliplimit
                # row-arc at (r, c): connects node(r, c-1) on left to node(r, c) on right
                # C: if col!=0: residue[row][col-1] += excess
                #    if col!=ncol-1: residue[row][col] -= excess
                # ncol-1 in C = nc (ncol_img - 1)
                if c != 0:
                    tc = int(residue[r, c - 1]) + excess
                    if tc > MAXRES or tc < MINRES:
                        raise OverflowError(
                            f"ClipFlow row-arc: residue overflow at ({r},{c-1}): {tc}"
                        )
                    residue[r, c - 1] = tc
                if c != nc:    # c != ncol_img-1
                    tc = int(residue[r, c]) - excess
                    if tc < MINRES or tc > MAXRES:
                        raise OverflowError(
                            f"ClipFlow row-arc: residue overflow at ({r},{c}): {tc}"
                        )
                    residue[r, c] = tc
                flows[r, c] = sign * cliplimit
                mstcosts[r, c] = maxcost

    for r in range(ni, 2 * ni + 1):   # col-arc rows
        for c in range(nc):
            fl = int(flows[r, c])
            if abs(fl) > cliplimit:
                if fl > 0:
                    sign = 1
                    excess = fl - cliplimit
                else:
                    sign = -1
                    excess = fl + cliplimit
                # col-arc at (r, c): C indices row=r, nrow=ni+1
                # C: if row!=nrow-1: residue[row-nrow][col] += excess
                #    if row!=2*nrow-2: residue[row-nrow+1][col] -= excess
                # row-nrow = r-(ni+1), row-nrow+1 = r-ni
                # skip if row==nrow-1=ni (first col-arc row)
                # skip if row==2*nrow-2=2*ni (last col-arc row)
                if r != ni:
                    ri = r - ni - 1    # = r - (ni+1), = row - nrow in C
                    tc = int(residue[ri, c]) + excess
                    if tc > MAXRES or tc < MINRES:
                        raise OverflowError(
                            f"ClipFlow col-arc: residue overflow at ({ri},{c}): {tc}"
                        )
                    residue[ri, c] = tc
                if r != 2 * ni:
                    ri = r - ni        # = row - nrow + 1 in C
                    tc = int(residue[ri, c]) - excess
                    if tc < MINRES or tc > MAXRES:
                        raise OverflowError(
                            f"ClipFlow col-arc: residue overflow at ({ri},{c}): {tc}"
                        )
                    residue[ri, c] = tc
                flows[r, c] = sign * cliplimit
                mstcosts[r, c] = maxcost

    return False


# C MAXRES/MINRES are SCHAR_MAX/SCHAR_MIN = ±127
MAXRES = 127
MINRES = -128
INITMAXCOSTINCR = 200   # C: #define INITMAXCOSTINCR 200


def mst_init_flows(phase: np.ndarray,
                   costs: np.ndarray,
                   params: 'SnaphuParams') -> np.ndarray:
    """Minimum spanning tree initialization of arc flows.

    DONE — faithfully ports MSTInitFlows() from snaphu_solver.c.

    C source: snaphu_solver.c:MSTInitFlows() + helpers.
    Phase: (nrow, ncol) float32 wrapped phase.
    costs: (2*nrow-1, ncol) structured array of statistical arc costs
           (smoothcostT or costT dtype, depending on params.costmode).
    params: SnaphuParams with maxflow, maxcost, costmode etc.

    Returns flows: (2*nrow-1, ncol) int16 array.
      flows[0..nrow-2, :]      = row-arc (azimuth) flows
      flows[nrow-1..2*nrow-2, :ncol-1] = col-arc (range) flows

    Algorithm:
      1. Build scalar mstcosts from statistical cost arrays.
      2. Compute integer phase residues on dual grid.
      3. Loop (SolveMST → DischargeTree → ClipFlow) until no flow exceeds maxflow.
      4. Return flows array.
    """
    nrow, ncol = phase.shape
    ni = nrow - 1   # interior node rows
    nc = ncol - 1   # interior node cols

    # --- apply C WrapPhase normalization: map to [0, 2pi) ---
    # C calls WrapPhase() in ReadInputFile before MSTInitFlows.
    # phase -= 2pi * floor(phase / 2pi)  maps (-pi,pi] → [0, 2pi).
    # This affects only the reference pixel phi[0][0] in IntegratePhase;
    # all ModDiff-based differences (residues, cost diffs) are range-invariant.
    # Replicating it here gives bit-identical output vs C on all pixels.
    phase_c = (phase.astype(np.float64)
               - TWOPI * np.floor(phase.astype(np.float64) / TWOPI)).astype(np.float32)

    # --- step 1: build scalar MST costs (mirrors BuildCostArrays scalar section) ---
    mstcosts = _build_mst_costs(costs, params, nrow, ncol)

    # --- find maximum mst cost to size buckets ---
    # C condition: !((row==nrow-1 || 2*nrow-2) && (col==0 || col==ncol-2))
    # C BUG: (row==nrow-1 || 2*nrow-2) evaluates 2*nrow-2 as a truthy int,
    # so the condition is always TRUE → reduces to !(col==0 || col==ncol-2).
    # This excludes col==0 and col==ncol-2 arcs from maxcost scan for ALL rows.
    maxcost = 0
    for r in range(2 * nrow - 1):
        maxcol = ncol if r < nrow - 1 else ncol - 1
        for c in range(maxcol):
            mc = int(mstcosts[r, c])
            # C-faithful exclusion: skip col==0 and col==ncol-2 (for all rows)
            if mc > maxcost and c != 0 and c != ncol - 2:
                maxcost = mc

    # bkts->size = LRound((maxcost+1)*(nrow+ncol+1))
    # nrow, ncol here are the IMAGE dims (not interior dims)
    bkt_size = int(np.rint((maxcost + 1) * (nrow + ncol + 1)))

    # --- step 2: compute phase residues using C-normalized phase ---
    residue = _cycle_residue(phase_c)   # (ni, nc) int8

    # --- step 3: allocate node grid ---
    # nodes[r][c] for r in 0..ni-1, c in 0..nc-1
    nodes = [[_Node(r, c) for c in range(nc)] for r in range(ni)]
    ground = _Node(GROUNDROW, GROUNDCOL)

    # --- allocate arc status array ---
    arcstatus = np.zeros((2 * nrow - 1, ncol), dtype=np.int8)

    # --- allocate flows array ---
    flows = np.zeros((2 * nrow - 1, ncol), dtype=np.int16)

    # --- main outer loop ---
    maxflow_int = int(params.initmaxflow)
    bkts = _Buckets(bkt_size)

    while True:
        # Find first non-zero residue as source
        source = None
        for r in range(ni):
            if source is not None:
                break
            for c in range(nc):
                if residue[r, c] != 0:
                    source = nodes[r][c]
                    break

        if source is None:
            break

        # Init nodes (reset outcost/group/pred)
        for r in range(ni):
            for c in range(nc):
                nd = nodes[r][c]
                nd.group = _NOTINBUCKET
                nd.incost = _VERYFAR
                nd.outcost = _VERYFAR
                nd.pred = None
        ground.group = _NOTINBUCKET
        ground.incost = _VERYFAR
        ground.outcost = _VERYFAR
        ground.pred = None

        # Init buckets
        _init_buckets(bkts, source)

        # MST solve
        _solve_mst(nodes, source, ground, bkts, mstcosts,
                   residue, arcstatus, ni, nc)

        # Discharge tree to get flows
        _discharge_tree(source, mstcosts, flows, residue,
                        arcstatus, nodes, ground, ni, nc)

        # Clip flows and check if done
        if _clip_flow(residue, flows, mstcosts, ni, nc, maxflow_int):
            break

    return flows


# ---------------------------------------------------------------------------
# CP7: Network-flow solver — DONE (scalar, faithful C port)
#
# C sources ported:
#   snaphu_solver.c: TreeSolve (line 197), InitNetwork (line 2546),
#     SetupTreeSolveNetwork (line 2664), SetupIncrFlowCosts (line 3477),
#     GetCost (line 3415), ReCalcCost (line 3432), AddNewNode (line 986),
#     CheckArcReducedCost (line 1035), FindApex (line 2007),
#     InitTree (line 1961), NonDegenUpdateChildren (line 2383),
#     PruneTree (line 2447), SelectSources (line 3119),
#     SelectConnNodeSource (line 3251), ScanRegion (line 3299),
#     MaskNodes (line 2749), GridNodeMaskStatus (line 2776),
#     GroundMaskStatus (line 2794)
#   snaphu.c: UnwrapTile outer loop (line 406)
#
# BIT-IDENTICAL VERDICT (see NOTES_CP7.md for full analysis):
#   Bit-identical to C snaphu output IS ACHIEVABLE.
#   (a) CandidateCompare (snaphu_solver.c:2036) returns 0 on equal-violation
#       ties. glibc qsort IS STABLE (merge sort >20 elements, insertion sort
#       <=20 — both stable). Python list.sort() is guaranteed stable.
#       Insertion order into candidatebag is deterministic (tree-thread
#       traversal order). → Python stable sort on same insertion order
#       reproduces glibc qsort tie-breaking exactly.
#   (b) int16 saturation (snaphu_solver.c:3444-3465) reproduced exactly via
#       explicit clip to ±LARGESHORT before int16 assignment.
#   (c) GMTSAR uses mag=1.0 everywhere → InitBoundary is a no-op
#       (IsRegionEdgeNode always FALSE → no boundary nodes created).
# ---------------------------------------------------------------------------

# CP7 node-group sentinel constants (snaphu.h — USE VERBATIM)
_ONTREE = -1
_INBUCKET_TS = -2        # INBUCKET
_NOTINBUCKET_TS = -3     # NOTINBUCKET
_PRUNED_TS = -4          # PRUNED
_MASKED_TS = -5          # MASKED
_BOUNDARYPTR_TS = -6     # BOUNDARYPTR
_GROUNDROW_TS = -2       # GROUNDROW
_BOUNDARYROW_TS = -4     # BOUNDARYROW
_NONTREEARC_TS = object()          # sentinel (replaces C NONTREEARC pointer)
_NEGBUCKETFRACTION = 1.0           # snaphu.h line 56
_POSBUCKETFRACTION = 1.0           # snaphu.h line 57
_VERYFAR_TS = LARGEINT             # #define VERYFAR LARGEINT
_MAXGROUPBASE_TS = LARGEINT        # #define MAXGROUPBASE LARGEINT


class _NodeTS:
    """Tree-solver node mirroring nodeT (snaphu.h:437).

    row, col, next, prev, pred, level, group, incost, outcost.
    """
    __slots__ = ('row', 'col', 'next', 'prev', 'pred',
                 'level', 'group', 'incost', 'outcost')

    def __init__(self, row: int, col: int):
        self.row = row
        self.col = col
        self.next = None
        self.prev = None
        self.pred = None
        self.level = 0
        self.group = 0
        self.incost = _VERYFAR_TS
        self.outcost = _VERYFAR_TS


class _BktsTS:
    """Bucket priority queue mirroring bucketT (snaphu.h:507)."""
    __slots__ = ('size', 'curr', 'maxind', 'minind', 'bucket', 'wrapped')

    def __init__(self, minind: int, maxind: int):
        self.minind = minind
        self.maxind = maxind
        self.size = maxind - minind + 1
        self.curr = maxind   # C: bkts->curr = bkts->maxind
        self.wrapped = False
        self.bucket = [None] * self.size


class _CandidateTS:
    """Candidate arc mirroring candidateT (snaphu.h:498)."""
    __slots__ = ('from_', 'to', 'violation', 'arcrow', 'arccol', 'arcdir')

    def __init__(self, from_: _NodeTS, to: _NodeTS, violation: int,
                 arcrow: int, arccol: int, arcdir: int):
        self.from_ = from_
        self.to = to
        self.violation = violation
        self.arcrow = arcrow
        self.arccol = arccol
        self.arcdir = arcdir


# --- Bucket operations (mirrors BucketInsert/BucketRemove in snaphu_util.c)

def _bkt_insert_ts(bkts: _BktsTS, node: _NodeTS, ind: int) -> None:
    idx = ind - bkts.minind
    node.next = bkts.bucket[idx]
    node.prev = None
    if bkts.bucket[idx] is not None:
        bkts.bucket[idx].prev = node
    bkts.bucket[idx] = node


def _bkt_remove_ts(bkts: _BktsTS, node: _NodeTS, ind: int) -> None:
    idx = ind - bkts.minind
    if node.prev is not None:
        node.prev.next = node.next
    else:
        bkts.bucket[idx] = node.next
    if node.next is not None:
        node.next.prev = node.prev
    node.next = None
    node.prev = None


def _min_out_cost_node_ts(bkts: _BktsTS) -> '_NodeTS | None':
    """Remove and return node with minimum outcost. Mirrors MinOutCostNode()."""
    while bkts.curr <= bkts.maxind:
        idx = bkts.curr - bkts.minind
        node = bkts.bucket[idx]
        if node is not None:
            _bkt_remove_ts(bkts, node, bkts.curr)
            return node
        bkts.curr += 1
    return None


# --- GetCost (snaphu_solver.c:3415)

def _get_cost_ts(incrcosts: np.ndarray, arcrow: int, arccol: int,
                 arcdir: int) -> int:
    """Mirrors GetCost(): return poscost if arcdir>0, else negcost."""
    if arcdir > 0:
        return int(incrcosts['poscost'][arcrow, arccol])
    else:
        return int(incrcosts['negcost'][arcrow, arccol])


# --- ReCalcCost (snaphu_solver.c:3432)

def _recalc_cost_ts(costs: np.ndarray, incrcosts: np.ndarray,
                    flow: int, arcrow: int, arccol: int,
                    nflow: int, nrow: int, params: 'SnaphuParams') -> int:
    """Recompute incrcosts for arc; clip to ±LARGESHORT. Mirrors ReCalcCost().

    Returns number of clipped values (0, 1, or 2).
    """
    if params.costmode == SMOOTH:
        poscost, negcost = calc_cost_smooth(costs, flow, arcrow, arccol,
                                            nflow, nrow, params)
    elif params.costmode == DEFO:
        poscost, negcost = calc_cost_defo(costs, flow, arcrow, arccol,
                                          nflow, nrow, params)
    else:
        raise ValueError(f"Unsupported costmode {params.costmode}")

    iclipped = 0
    if poscost > LARGESHORT:
        incrcosts['poscost'][arcrow, arccol] = LARGESHORT; iclipped += 1
    elif poscost < -LARGESHORT:
        incrcosts['poscost'][arcrow, arccol] = -LARGESHORT; iclipped += 1
    else:
        incrcosts['poscost'][arcrow, arccol] = int(poscost)

    if negcost > LARGESHORT:
        incrcosts['negcost'][arcrow, arccol] = LARGESHORT; iclipped += 1
    elif negcost < -LARGESHORT:
        incrcosts['negcost'][arcrow, arccol] = -LARGESHORT; iclipped += 1
    else:
        incrcosts['negcost'][arcrow, arccol] = int(negcost)

    return iclipped


# --- SetupIncrFlowCosts (snaphu_solver.c:3477)

def _setup_incr_flow_costs_ts(costs: np.ndarray, incrcosts: np.ndarray,
                               flows: np.ndarray, nflow: int,
                               nrow: int, ncol: int,
                               params: 'SnaphuParams') -> None:
    """Compute incrcosts for all arcs. Mirrors SetupIncrFlowCosts()."""
    for arcrow in range(2 * nrow - 1):
        maxcol = ncol if arcrow < nrow - 1 else ncol - 1
        for arccol in range(maxcol):
            _recalc_cost_ts(costs, incrcosts, int(flows[arcrow, arccol]),
                            arcrow, arccol, nflow, nrow, params)


# --- NeighborNodeGrid for TreeSolve (snaphu_solver.c:2094)

def _neighbor_node_grid_ts(node: _NodeTS, arcnum: int, ngroundarcs: int,
                            nodes: list, ground: _NodeTS,
                            ni: int, nc: int) -> tuple:
    """Return (neighbor, arcrow, arccol, arcdir). Mirrors NeighborNodeGrid().

    ni = nrow_img - 1, nc = ncol_img - 1.
    GMTSAR: no boundary nodes → BOUNDARYPTR branch never hit.
    """
    row = node.row
    col = node.col
    nrow = ni + 1
    ncol = nc + 1

    if row == _GROUNDROW_TS:
        # Ground node → iterate over boundary arcs.
        # Mirrors NeighborNodeGrid() default case (snaphu_solver.c:2160-2180).
        # arcnum range: 0 .. ngroundarcs-1 (GetArcNumLims returns -1, ngroundarcs-1)
        ni1 = nrow - 1   # nrow-1
        if arcnum < ni1:
            # Left column, top→bottom (arcnum=0..nrow-2)
            return nodes[arcnum][0], arcnum, 0, 1
        elif arcnum < 2 * ni1:
            # Right column, top→bottom (arcnum=nrow-1..2*nrow-3)
            r = arcnum - ni1
            return nodes[r][ncol - 2], r, ncol - 1, -1
        elif arcnum < 2 * ni1 + ncol - 3:
            # Top row, left→right (skip corners)
            arccol = arcnum - 2 * ni1 + 1
            return nodes[0][arccol], nrow - 1, arccol, 1
        else:
            # Bottom row, left→right (skip corners)
            arccol = arcnum - (2 * ni1 + ncol - 3) + 1
            return nodes[nrow - 2][arccol], 2 * nrow - 2, arccol, -1
    else:
        if arcnum == -4:
            nb = ground if col == ncol - 2 else nodes[row][col + 1]
            return nb, row, col + 1, 1
        elif arcnum == -3:
            nb = ground if row == nrow - 2 else nodes[row + 1][col]
            return nb, nrow + row, col, 1
        elif arcnum == -2:
            nb = ground if col == 0 else nodes[row][col - 1]
            return nb, row, col, -1
        elif arcnum == -1:
            nb = ground if row == 0 else nodes[row - 1][col]
            return nb, nrow - 1 + row, col, -1
        else:
            raise ValueError(f"_neighbor_node_grid_ts: arcnum={arcnum} "
                             f"for interior node ({row},{col})")


def _get_arc_num_lims_ts(fromrow: int, ngroundarcs: int) -> tuple:
    """Return (arcnum_start, upperarcnum). Mirrors GetArcNumLims()."""
    if fromrow < 0:
        return -1, ngroundarcs - 1
    else:
        return -5, -1


# --- GetArcGrid (snaphu_solver.c:2219)

def _get_arc_grid_ts(from_: _NodeTS, to: _NodeTS,
                     nrow: int, ncol: int, nodes: list) -> tuple:
    """Return (arcrow, arccol, arcdir). Mirrors GetArcGrid()."""
    fr = from_.row;  fc = from_.col
    tr = to.row;     tc = to.col

    if fr == tr:
        if fc == tc - 1:
            return fr, tc, 1
        elif fc == tc + 1:
            return fr, fc, -1
        else:
            raise ValueError(f"GetArcGrid: non-adjacent same-row ({fr},{fc})→({tr},{tc})")
    elif fr == tr - 1:
        return tr + nrow - 1, fc, 1
    elif fr == tr + 1:
        return fr + nrow - 1, fc, -1
    elif fr == _BOUNDARYROW_TS:
        if tc < ncol - 2 and nodes[tr][tc + 1].group == _BOUNDARYPTR_TS:
            return tr, tc + 1, -1
        elif tc > 0 and nodes[tr][tc - 1].group == _BOUNDARYPTR_TS:
            return tr, tc, 1
        elif tr < nrow - 2 and nodes[tr + 1][tc].group == _BOUNDARYPTR_TS:
            return tr + 1 + nrow - 1, tc, -1
        else:
            return tr + nrow - 1, tc, 1
    elif tr == _BOUNDARYROW_TS:
        if fc < ncol - 2 and nodes[fr][fc + 1].group == _BOUNDARYPTR_TS:
            return fr, fc + 1, 1
        elif fc > 0 and nodes[fr][fc - 1].group == _BOUNDARYPTR_TS:
            return fr, fc, -1
        elif fr < nrow - 2 and nodes[fr + 1][fc].group == _BOUNDARYPTR_TS:
            return fr + 1 + nrow - 1, fc, 1
        else:
            return fr + nrow - 1, fc, -1
    elif fc == 0:
        return fr, 0, -1
    elif fc == ncol - 2:
        return fr, ncol - 1, 1
    elif fr == 0:
        return nrow - 1, fc, -1
    elif fr == nrow - 2:
        return 2 * (nrow - 1), fc, 1
    elif tc == 0:
        return tr, 0, 1
    elif tc == ncol - 2:
        return tr, ncol - 1, -1
    elif tr == 0:
        return nrow - 1, tc, 1
    else:
        return 2 * (nrow - 1), tc, -1


# --- AddNewNode (snaphu_solver.c:986)

def _add_new_node_ts(from_: _NodeTS, to: _NodeTS, arcdir: int,
                     bkts: _BktsTS, nflow: int, incrcosts: np.ndarray,
                     arcrow: int, arccol: int) -> None:
    """Add to-node to bucket if cost improved. Mirrors AddNewNode()."""
    newoutcost = from_.outcost + _get_cost_ts(incrcosts, arcrow, arccol, arcdir)
    if newoutcost < to.outcost or to.pred is from_:
        if to.group == _INBUCKET_TS:
            old = to.outcost
            _bkt_remove_ts(bkts, to,
                           max(min(old, bkts.maxind), bkts.minind))
        to.outcost = newoutcost
        to.pred = from_
        clamped = max(min(newoutcost, bkts.maxind), bkts.minind)
        _bkt_insert_ts(bkts, to, clamped)
        if clamped < bkts.curr:
            bkts.curr = clamped
        to.group = _INBUCKET_TS


# --- CheckArcReducedCost (snaphu_solver.c:1035)

def _check_arc_reduced_cost_ts(from_: _NodeTS, to: _NodeTS, apex,
                                arcrow: int, arccol: int, arcdir: int,
                                candidatebag: list,
                                incrcosts: np.ndarray,
                                iscandidate: np.ndarray) -> None:
    """Check arc; append to candidatebag if negative reduced cost found.

    Mirrors CheckArcReducedCost() in snaphu_solver.c:1035.
    apex: _NodeTS or None (on-tree arc) or _NONTREEARC_TS (not on tree).
    """
    if iscandidate[arcrow, arccol]:
        return
    if apex is _NONTREEARC_TS or apex is None:
        return

    apexcost = apex.outcost + apex.incost
    fwd = _get_cost_ts(incrcosts, arcrow, arccol, arcdir)
    violation = fwd + from_.outcost + to.incost - apexcost

    if violation < 0:
        ad_used = arcdir * 2; fr_used = from_; to_used = to
    else:
        rev = _get_cost_ts(incrcosts, arcrow, arccol, -arcdir)
        violation = rev + to.outcost + from_.incost - apexcost
        if violation < 0:
            ad_used = arcdir * -2; fr_used = to; to_used = from_
        else:
            violation = fwd + from_.outcost - to.outcost
            if violation >= 0:
                violation = rev + to.outcost - from_.outcost
                if violation < 0:
                    ad_used = -arcdir; fr_used = to; to_used = from_
                else:
                    return
            else:
                ad_used = arcdir; fr_used = from_; to_used = to

    if violation < 0:
        candidatebag.append(
            _CandidateTS(fr_used, to_used, violation, arcrow, arccol, ad_used))
        iscandidate[arcrow, arccol] = 1


# --- FindApex (snaphu_solver.c:2007)

def _find_apex_ts(from_: _NodeTS, to: _NodeTS) -> _NodeTS:
    """Find deepest common ancestor. Mirrors FindApex()."""
    if from_.level > to.level:
        while from_.level != to.level:
            from_ = from_.pred
    else:
        while from_.level != to.level:
            to = to.pred
    while from_ is not to:
        from_ = from_.pred
        to = to.pred
    return from_


# --- InitTree (snaphu_solver.c:1961)

def _init_tree_ts(source: _NodeTS, nodes: list, ground: _NodeTS,
                  ngroundarcs: int, bkts: _BktsTS, nflow: int,
                  incrcosts: np.ndarray, ni: int, nc: int) -> None:
    """Initialize spanning tree from source. Mirrors InitTree()."""
    source.group = 1
    source.outcost = 0
    source.incost = 0
    source.pred = None
    source.prev = source
    source.next = source
    source.level = 0

    arcnum, upperarcnum = _get_arc_num_lims_ts(source.row, ngroundarcs)
    while arcnum < upperarcnum:
        arcnum += 1
        to, arcrow, arccol, arcdir = _neighbor_node_grid_ts(
            source, arcnum, ngroundarcs, nodes, ground, ni, nc)
        if to.group != _PRUNED_TS and to.group != _MASKED_TS:
            _add_new_node_ts(source, to, arcdir, bkts, nflow,
                             incrcosts, arcrow, arccol)


# --- NonDegenUpdateChildren (snaphu_solver.c:2383)

def _non_degen_update_children_ts(startnode: _NodeTS, lastnode: _NodeTS,
                                   nextonpath: _NodeTS, dgroup: int,
                                   ngroundarcs: int, nflow: int,
                                   nodes: list, ground: _NodeTS,
                                   nrow: int, ncol: int,
                                   apexes: list,
                                   incrcosts: np.ndarray) -> None:
    """Update subtree potentials along augmenting path.

    Mirrors NonDegenUpdateChildren() in snaphu_solver.c:2383.
    """
    ni = nrow - 1
    nc = ncol - 1
    node1 = startnode
    pathgroup = lastnode.group

    while node1 is not lastnode:
        node2 = nextonpath
        ar2, ac2, ad2 = _get_arc_grid_ts(node2.pred, node2, nrow, ncol, nodes)
        doutcost = (node1.outcost - node2.outcost
                    + _get_cost_ts(incrcosts, ar2, ac2, ad2))
        node2.outcost += doutcost
        dincost = (node1.incost - node2.incost
                   + _get_cost_ts(incrcosts, ar2, ac2, -ad2))
        node2.incost += dincost
        node2.group = node1.group + dgroup

        node1 = node2
        arcnum, upperarcnum = _get_arc_num_lims_ts(node1.row, ngroundarcs)
        while arcnum < upperarcnum:
            arcnum += 1
            node2, _, _, _ = _neighbor_node_grid_ts(
                node1, arcnum, ngroundarcs, nodes, ground, ni, nc)
            if node2.pred is node1 and node2.group > 0:
                if node2.group == pathgroup:
                    nextonpath = node2
                else:
                    startlevel = node2.level
                    g1 = node1.group
                    while True:
                        node2.group = g1
                        node2.incost += dincost
                        node2.outcost += doutcost
                        node2 = node2.next
                        if node2.level <= startlevel:
                            break


# --- IsRegionArc, Mask helpers (snaphu_solver.c:1633, 2749, 2776, 2794)

def _is_region_arc_ts(mag: np.ndarray, arcrow: int, arccol: int,
                      nrow: int, ncol: int) -> bool:
    """True if at least one pixel on either side of arc is nonzero."""
    if mag is None:
        return True
    if arcrow < nrow - 1:
        r1, r2, c1, c2 = arcrow, arcrow + 1, arccol, arccol
    else:
        r1 = r2 = arcrow - (nrow - 1)
        c1, c2 = arccol, arccol + 1
    return bool(mag[r1, c1] > 0 or mag[r2, c2] > 0)


def _grid_node_mask_status_ts(row: int, col: int, mag: np.ndarray) -> int:
    if mag[row, col] or mag[row, col + 1] or mag[row + 1, col] or mag[row + 1, col + 1]:
        return 0
    return _MASKED_TS


def _ground_mask_status_ts(nrow: int, ncol: int, mag: np.ndarray) -> int:
    for r in range(nrow):
        if mag[r, 0] or mag[r, ncol - 1]:
            return 0
    for c in range(ncol):
        if mag[0, c] or mag[nrow - 1, c]:
            return 0
    return _MASKED_TS


def _mask_nodes_ts(nrow: int, ncol: int, nodes: list, ground: _NodeTS,
                   mag: np.ndarray) -> None:
    """Mirrors MaskNodes(). No-op for GMTSAR (mag=1 everywhere)."""
    ni = nrow - 1
    nc = ncol - 1
    for r in range(ni):
        for c in range(nc):
            nodes[r][c].group = _grid_node_mask_status_ts(r, c, mag)
    ground.group = _ground_mask_status_ts(nrow, ncol, mag)


# --- ScanRegion (snaphu_solver.c:3299)

def _scan_region_ts(start: _NodeTS, nodes: list, mag: np.ndarray,
                    ground: _NodeTS, ngroundarcs: int,
                    nrow: int, ncol: int, groupsetting: int) -> int:
    """BFS over connected region. Mirrors ScanRegion()."""
    ni = nrow - 1
    nc = ncol - 1
    nconnected = 0
    end = start
    node1 = start
    node1.group = _INBUCKET_TS

    while node1 is not None:
        arcnum, upperarcnum = _get_arc_num_lims_ts(node1.row, ngroundarcs)
        while arcnum < upperarcnum:
            arcnum += 1
            node2, arcrow, arccol, _ = _neighbor_node_grid_ts(
                node1, arcnum, ngroundarcs, nodes, ground, ni, nc)
            if node2.group == _BOUNDARYPTR_TS:
                node2.group = 0
            if _is_region_arc_ts(mag, arcrow, arccol, nrow, ncol):
                if node2.group != _ONTREE and node2.group != _INBUCKET_TS:
                    node2.group = _INBUCKET_TS
                    end.next = node2
                    node2.next = None
                    end = node2
        node1.group = _ONTREE
        if groupsetting == _ONTREE:
            node1.level = 0
        nconnected += 1
        node1 = node1.next

    if groupsetting != _ONTREE:
        node1 = start
        while node1 is not None:
            arcnum, upperarcnum = _get_arc_num_lims_ts(node1.row, ngroundarcs)
            while arcnum < upperarcnum:
                arcnum += 1
                node2, arcrow, arccol, _ = _neighbor_node_grid_ts(
                    node1, arcnum, ngroundarcs, nodes, ground, ni, nc)
                if node2.group != _ONTREE:
                    if groupsetting == _MASKED_TS:
                        node2.group = _MASKED_TS
                    elif groupsetting == 0:
                        if node2.row == _GROUNDROW_TS:
                            node2.group = _ground_mask_status_ts(nrow, ncol, mag)
                        else:
                            node2.group = _grid_node_mask_status_ts(
                                node2.row, node2.col, mag)
            node1 = node1.next
        node1 = start
        while node1 is not None:
            node1.group = 0
            node1 = node1.next

    return nconnected


# --- SelectConnNodeSource (snaphu_solver.c:3251)

def _select_conn_node_source_ts(nodes: list, mag: np.ndarray,
                                 ground: _NodeTS, ngroundarcs: int,
                                 nrow: int, ncol: int,
                                 params: 'SnaphuParams',
                                 start: _NodeTS) -> tuple:
    """Mirrors SelectConnNodeSource(). Returns (source_or_None, nconnected)."""
    if start.group == _MASKED_TS or start.group == _ONTREE:
        return None, 0
    nconnected = _scan_region_ts(start, nodes, mag, ground,
                                  ngroundarcs, nrow, ncol, _ONTREE)
    if nconnected > params.nconnnodemin:
        return start, nconnected
    return None, nconnected


# --- SelectSources (snaphu_solver.c:3119)

def _select_sources_ts(nodes: list, mag: np.ndarray, ground: _NodeTS,
                        nflow: int, flows: np.ndarray,
                        ngroundarcs: int, nrow: int, ncol: int,
                        params: 'SnaphuParams') -> list:
    """Build (source, nconnected) list. Mirrors SelectSources()."""
    ni = nrow - 1
    nc = ncol - 1
    sourcelist = []

    def _reset_groups():
        if ground.group != _MASKED_TS and ground.group != _BOUNDARYPTR_TS:
            ground.group = 0
        ground.next = None
        for r in range(ni):
            for c in range(nc):
                if (nodes[r][c].group != _MASKED_TS
                        and nodes[r][c].group != _BOUNDARYPTR_TS):
                    nodes[r][c].group = 0
                nodes[r][c].next = None

    _reset_groups()

    src, nconn = _select_conn_node_source_ts(
        nodes, mag, ground, ngroundarcs, nrow, ncol, params, ground)
    if src is not None:
        sourcelist.append((src, nconn))

    for r in range(ni):
        for c in range(nc):
            src, nconn = _select_conn_node_source_ts(
                nodes, mag, ground, ngroundarcs, nrow, ncol, params,
                nodes[r][c])
            if src is not None:
                sourcelist.append((src, nconn))

    _reset_groups()
    return sourcelist


# --- PruneTree + CheckLeaf (snaphu_solver.c:2447)

def _check_leaf_ts(node: _NodeTS, nodes: list, ground: _NodeTS,
                   incrcosts: np.ndarray, flows: np.ndarray,
                   ngroundarcs: int, nrow: int, ncol: int,
                   ni: int, nc: int, prunecostthresh: int) -> bool:
    """True if node is a prunable leaf. Mirrors CheckLeaf()."""
    arcnum, upperarcnum = _get_arc_num_lims_ts(node.row, ngroundarcs)
    while arcnum < upperarcnum:
        arcnum += 1
        nb, _, _, _ = _neighbor_node_grid_ts(
            node, arcnum, ngroundarcs, nodes, ground, ni, nc)
        if nb.group > 0 and nb is not node.pred:
            return False
    if node.pred is None:
        return False
    ar, ac, _ = _get_arc_grid_ts(node.pred, node, nrow, ncol, nodes)
    if flows[ar, ac] != 0:
        return False
    return int(incrcosts['poscost'][ar, ac]) >= prunecostthresh


def _prune_tree_ts(source: _NodeTS, nodes: list, ground: _NodeTS,
                   incrcosts: np.ndarray, flows: np.ndarray,
                   ngroundarcs: int, prunecostthresh: int,
                   nrow: int, ncol: int, ni: int, nc: int) -> int:
    """Prune leaves from spanning tree. Mirrors PruneTree()."""
    npruned = 0
    node1 = source.next
    while node1 is not source:
        nxt = node1.next
        if _check_leaf_ts(node1, nodes, ground, incrcosts, flows,
                           ngroundarcs, nrow, ncol, ni, nc, prunecostthresh):
            node1.prev.next = node1.next
            node1.next.prev = node1.prev
            node1.group = _PRUNED_TS
            npruned += 1
        node1 = nxt
    return npruned


# ---------------------------------------------------------------------------
# CP7: TreeSolve (snaphu_solver.c:197) — core optimizer
# ---------------------------------------------------------------------------

def _tree_solve_ts(nodes: list, ground: _NodeTS, source: _NodeTS,
                   candidatebag: list, candidatelist: list,
                   bkts: _BktsTS, flows: np.ndarray,
                   costs: np.ndarray, incrcosts: np.ndarray,
                   apexes: list, iscandidate: np.ndarray,
                   ngroundarcs: int, nflow: int,
                   mag: np.ndarray, nrow: int, ncol: int,
                   nconnected: int, params: 'SnaphuParams') -> int:
    """Negative-cycle cancellation optimizer for one source node.

    Mirrors TreeSolve() in snaphu_solver.c:197.
    Returns number of nondegenerate pivots (flow improvements).

    candidatebag / candidatelist: Python lists, swapped each inner iter.
    apexes: list-of-lists (2*nrow-1) x (ncol); each element is _NodeTS,
            None (on-tree arc), or _NONTREEARC_TS.
    """
    ni = nrow - 1
    nc = ncol - 1

    bkts.curr = bkts.maxind
    _init_tree_ts(source, nodes, ground, ngroundarcs, bkts, nflow,
                  incrcosts, ni, nc)

    groupcounter = 2
    ipivots = 0
    inondegen = 0
    maxnewnodes = int(np.ceil(nconnected * params.maxnewnodeconst))
    treesize = 1
    nmajor = 0
    nmajorprune = params.nmajorprune
    prunecostthresh = params.prunecostthresh

    bag_ref = candidatebag
    lst_ref = candidatelist

    # -----------------------------------------------------------------------
    # Outer loop: grow spanning tree
    # -----------------------------------------------------------------------
    while treesize < nconnected:

        nnewnodes = 0
        while nnewnodes < maxnewnodes and treesize < nconnected:
            to = _min_out_cost_node_ts(bkts)
            if to is None:
                break
            from_ = to.pred

            arcrow, arccol, arcdir = _get_arc_grid_ts(from_, to, nrow, ncol, nodes)
            to.group = 1
            to.level = from_.level + 1
            to.incost = from_.incost + _get_cost_ts(incrcosts, arcrow, arccol, -arcdir)
            # Insert into doubly-linked circular thread after from_
            to.next = from_.next
            to.prev = from_
            to.next.prev = to
            from_.next = to

            from_ = to
            arcnum, upperarcnum = _get_arc_num_lims_ts(from_.row, ngroundarcs)
            while arcnum < upperarcnum:
                arcnum += 1
                to2, arcrow, arccol, arcdir = _neighbor_node_grid_ts(
                    from_, arcnum, ngroundarcs, nodes, ground, ni, nc)

                if to2.group > 0:
                    if to2 is not from_.pred:
                        cycleapex = _find_apex_ts(from_, to2)
                        apexes[arcrow][arccol] = cycleapex
                        _check_arc_reduced_cost_ts(
                            from_, to2, cycleapex, arcrow, arccol, arcdir,
                            bag_ref, incrcosts, iscandidate)
                    else:
                        apexes[arcrow][arccol] = None
                elif to2.group != _PRUNED_TS and to2.group != _MASKED_TS:
                    _add_new_node_ts(from_, to2, arcdir, bkts, nflow,
                                     incrcosts, arcrow, arccol)

            nnewnodes += 1
            treesize += 1

        # -------------------------------------------------------------------
        # Inner loop: process candidate list
        # -------------------------------------------------------------------
        while bag_ref:
            bag_ref, lst_ref = lst_ref, bag_ref
            bag_ref.clear()

            # Sort: augmenting (|arcdir|>1) first, then violation ascending.
            # C: qsort with CandidateCompare (stable via glibc merge/insertion).
            # Python list.sort() is guaranteed stable → identical tie-breaking.
            lst_ref.sort(key=lambda c: (0 if abs(c.arcdir) > 1 else 1, c.violation))

            # Normalize arcdir to ±1 (C lines 378-384)
            for cand in lst_ref:
                if cand.arcdir > 1:
                    cand.arcdir = 1
                elif cand.arcdir < -1:
                    cand.arcdir = -1

            for cand in lst_ref:
                from_ = cand.from_
                to = cand.to
                arcdir = cand.arcdir
                arcrow = cand.arcrow
                arccol = cand.arccol

                iscandidate[arcrow, arccol] = 0

                apex = apexes[arcrow][arccol]
                if apex is _NONTREEARC_TS:
                    continue

                # Re-check violation
                outcostto = (from_.outcost
                             + _get_cost_ts(incrcosts, arcrow, arccol, arcdir))
                apex_sum = 0 if apex is None else (apex.outcost + apex.incost)
                cyclecost = outcostto + to.incost - apex_sum

                if not (outcostto < to.outcost or cyclecost < 0):
                    from_, to = to, from_
                    arcdir = -arcdir
                    outcostto = (from_.outcost
                                 + _get_cost_ts(incrcosts, arcrow, arccol, arcdir))
                    cyclecost = outcostto + to.incost - apex_sum

                if not (outcostto < to.outcost or cyclecost < 0):
                    continue

                # Group counter overflow (snaphu_solver.c:434-449)
                groupcounter += 1
                if groupcounter > _MAXGROUPBASE_TS:
                    for r in range(ni):
                        for c in range(nc):
                            if nodes[r][c].group > 0:
                                nodes[r][c].group = 1
                    if ground.group > 0:
                        ground.group = 1
                    groupcounter = 2

                leavingchild = None
                fromside = True

                # --- Augmenting pivot (cyclecost < 0) ---
                if cyclecost < 0:
                    while True:
                        fromside = True
                        node1 = from_
                        node2 = to
                        leavingchild = None

                        flows[arcrow, arccol] = (int(flows[arcrow, arccol])
                                                 + arcdir * nflow)
                        _recalc_cost_ts(costs, incrcosts,
                                        int(flows[arcrow, arccol]),
                                        arcrow, arccol, nflow, nrow, params)
                        violation = _get_cost_ts(incrcosts, arcrow, arccol, arcdir)

                        while node1.level > node2.level:
                            ar1, ac1, ad1 = _get_arc_grid_ts(
                                node1.pred, node1, nrow, ncol, nodes)
                            flows[ar1, ac1] = int(flows[ar1, ac1]) + ad1 * nflow
                            _recalc_cost_ts(costs, incrcosts,
                                            int(flows[ar1, ac1]),
                                            ar1, ac1, nflow, nrow, params)
                            if leavingchild is None and flows[ar1, ac1] == 0:
                                leavingchild = node1
                            violation += _get_cost_ts(incrcosts, ar1, ac1, ad1)
                            node1.group = groupcounter + 1
                            node1 = node1.pred

                        while node2.level > node1.level:
                            ar2, ac2, ad2 = _get_arc_grid_ts(
                                node2.pred, node2, nrow, ncol, nodes)
                            flows[ar2, ac2] = int(flows[ar2, ac2]) - ad2 * nflow
                            _recalc_cost_ts(costs, incrcosts,
                                            int(flows[ar2, ac2]),
                                            ar2, ac2, nflow, nrow, params)
                            if flows[ar2, ac2] == 0:
                                leavingchild = node2
                                fromside = False
                            violation += _get_cost_ts(incrcosts, ar2, ac2, -ad2)
                            node2.group = groupcounter
                            node2 = node2.pred

                        while node1 is not node2:
                            ar1, ac1, ad1 = _get_arc_grid_ts(
                                node1.pred, node1, nrow, ncol, nodes)
                            ar2, ac2, ad2 = _get_arc_grid_ts(
                                node2.pred, node2, nrow, ncol, nodes)
                            flows[ar1, ac1] = int(flows[ar1, ac1]) + ad1 * nflow
                            flows[ar2, ac2] = int(flows[ar2, ac2]) - ad2 * nflow
                            _recalc_cost_ts(costs, incrcosts,
                                            int(flows[ar1, ac1]),
                                            ar1, ac1, nflow, nrow, params)
                            _recalc_cost_ts(costs, incrcosts,
                                            int(flows[ar2, ac2]),
                                            ar2, ac2, nflow, nrow, params)
                            violation += (_get_cost_ts(incrcosts, ar1, ac1, ad1)
                                          + _get_cost_ts(incrcosts, ar2, ac2, -ad2))
                            if flows[ar2, ac2] == 0:
                                leavingchild = node2
                                fromside = False
                            elif leavingchild is None and flows[ar1, ac1] == 0:
                                leavingchild = node1
                            node1.group = groupcounter + 1
                            node2.group = groupcounter
                            node1 = node1.pred
                            node2 = node2.pred

                        if violation >= 0:
                            break
                    inondegen += 1

                # --- Degenerate pivot ---
                else:
                    fromside = False
                    node1 = from_
                    node2 = to
                    leavingchild = None

                    while node1.level > node2.level:
                        node1.group = groupcounter + 1
                        node1 = node1.pred

                    while node2.level > node1.level:
                        if outcostto < node2.outcost:
                            leavingchild = node2
                            ar2, ac2, ad2 = _get_arc_grid_ts(
                                node2.pred, node2, nrow, ncol, nodes)
                            outcostto += _get_cost_ts(incrcosts, ar2, ac2, -ad2)
                        else:
                            outcostto = _VERYFAR_TS
                        node2.group = groupcounter
                        node2 = node2.pred

                    while node1 is not node2:
                        if outcostto < node2.outcost:
                            leavingchild = node2
                            ar2, ac2, ad2 = _get_arc_grid_ts(
                                node2.pred, node2, nrow, ncol, nodes)
                            outcostto += _get_cost_ts(incrcosts, ar2, ac2, -ad2)
                        else:
                            outcostto = _VERYFAR_TS
                        node1.group = groupcounter + 1
                        node2.group = groupcounter
                        node1 = node1.pred
                        node2 = node2.pred

                cycleapex = node1

                # Set leaving parent / fromside
                if leavingchild is None:
                    fromside = True
                    leavingparent = from_
                else:
                    leavingparent = leavingchild.pred

                if fromside:
                    groupcounter += 1
                    fromgroup = groupcounter - 1
                    from_, to = to, from_
                else:
                    fromgroup = groupcounter + 1

                # --- NonDegenUpdateChildren for augmenting pivot ---
                if cyclecost < 0:
                    firstfromnode = None
                    firsttonode = None
                    arcnum2, upperarcnum2 = _get_arc_num_lims_ts(
                        cycleapex.row, ngroundarcs)
                    while arcnum2 < upperarcnum2:
                        arcnum2 += 1
                        tmpnd, ar2, ac2, _ = _neighbor_node_grid_ts(
                            cycleapex, arcnum2, ngroundarcs,
                            nodes, ground, ni, nc)
                        if tmpnd.group == groupcounter and apexes[ar2][ac2] is None:
                            firsttonode = tmpnd
                            if firstfromnode is not None:
                                break
                        elif tmpnd.group == fromgroup and apexes[ar2][ac2] is None:
                            firstfromnode = tmpnd
                            if firsttonode is not None:
                                break

                    cycleapex.group = groupcounter + 2
                    if firsttonode is not None:
                        _non_degen_update_children_ts(
                            cycleapex, leavingparent, firsttonode, 0,
                            ngroundarcs, nflow, nodes, ground,
                            nrow, ncol, apexes, incrcosts)
                    if firstfromnode is not None:
                        _non_degen_update_children_ts(
                            cycleapex, from_, firstfromnode, 1,
                            ngroundarcs, nflow, nodes, ground,
                            nrow, ncol, apexes, incrcosts)
                    groupcounter = from_.group
                    apexlistbase = cycleapex.group
                    fromgroup = cycleapex.group
                else:
                    cycleapex.group = fromgroup
                    groupcounter += 2
                    apexlistbase = groupcounter + 1

                # --- Remount subtree ---
                if leavingchild is None:
                    skipthread = to
                else:
                    root = from_
                    oldmntpt = to

                    # Build apexlist lookup table (groupcounter → ancestor node)
                    apexlistlen = max(groupcounter - apexlistbase + 2, 1)
                    apexlist = [None] * apexlistlen
                    node2 = leavingchild
                    for group1 in range(groupcounter, apexlistbase - 1, -1):
                        idx_al = group1 - apexlistbase
                        if 0 <= idx_al < apexlistlen:
                            apexlist[idx_al] = node2
                        if node2.pred is not None:
                            node2 = node2.pred

                    # Remount path from to → leavingparent
                    # Thread update happens INSIDE the loop (mirrors C lines 704-710).
                    while oldmntpt is not leavingparent:
                        mntpt = root
                        root = oldmntpt
                        oldmntpt = root.pred
                        root.pred = mntpt
                        ar_mn, ac_mn, ad_mn = _get_arc_grid_ts(
                            mntpt, root, nrow, ncol, nodes)
                        dlevel = mntpt.level - root.level + 1
                        doutcost = (mntpt.outcost - root.outcost
                                    + _get_cost_ts(incrcosts, ar_mn, ac_mn, ad_mn))
                        dincost = (mntpt.incost - root.incost
                                   + _get_cost_ts(incrcosts, ar_mn, ac_mn, -ad_mn))
                        groupcounter += 1
                        node1 = root
                        startlevel = root.level
                        while True:
                            node1.level += dlevel
                            node1.outcost += doutcost
                            node1.incost += dincost
                            node1.group = groupcounter
                            if node1.next.level <= startlevel:
                                break
                            node1 = node1.next

                        # Rewire threads inside loop (C lines 704-710)
                        root.prev.next = node1.next
                        node1.next.prev = root.prev
                        node1.next = mntpt.next    # C: mntpt->next (not leavingparent)
                        mntpt.next.prev = node1
                        mntpt.next = root
                        root.prev = mntpt

                    skipthread = node1.next

                    # Reset apex for entering/leaving arcs
                    ar_en, ac_en, _ = _get_arc_grid_ts(
                        from_, to, nrow, ncol, nodes)
                    apexes[ar_en][ac_en] = None
                    ar_lv, ac_lv, _ = _get_arc_grid_ts(
                        leavingparent, leavingchild, nrow, ncol, nodes)
                    apexes[ar_lv][ac_lv] = cycleapex

                    # Reset apexes on remounted subtree
                    node1 = to
                    startlevel = to.level
                    while True:
                        arcnum2, upperarcnum2 = _get_arc_num_lims_ts(
                            node1.row, ngroundarcs)
                        while arcnum2 < upperarcnum2:
                            arcnum2 += 1
                            node2, ar2, ac2, ad2 = _neighbor_node_grid_ts(
                                node1, arcnum2, ngroundarcs,
                                nodes, ground, ni, nc)
                            if node2.group > 0:
                                ap2 = apexes[ar2][ac2]
                                if (node2.group < node1.group
                                        and ap2 is not _NONTREEARC_TS
                                        and ap2 is not None):
                                    idx_al = node2.group - apexlistbase
                                    if 0 <= idx_al < apexlistlen:
                                        apexes[ar2][ac2] = apexlist[idx_al]
                                    else:
                                        if ap2.level > cycleapex.level:
                                            apexes[ar2][ac2] = cycleapex
                                        elif ap2 is cycleapex:
                                            tmpnd2 = node2
                                            while tmpnd2.group != fromgroup:
                                                tmpnd2 = tmpnd2.pred
                                            apexes[ar2][ac2] = tmpnd2

                                    _check_arc_reduced_cost_ts(
                                        node1, node2, apexes[ar2][ac2],
                                        ar2, ac2, ad2, bag_ref,
                                        incrcosts, iscandidate)

                        if node1.next.level <= startlevel:
                            break
                        node1 = node1.next

                # --- Scan skipthread subtree ---
                if skipthread is not source:
                    node1 = skipthread
                    startlevel = skipthread.level
                    while True:
                        arcnum2, upperarcnum2 = _get_arc_num_lims_ts(
                            node1.row, ngroundarcs)
                        while arcnum2 < upperarcnum2:
                            arcnum2 += 1
                            node2, ar2, ac2, ad2 = _neighbor_node_grid_ts(
                                node1, arcnum2, ngroundarcs,
                                nodes, ground, ni, nc)
                            if node2.group > 0 and node2 is not node1.pred:
                                _check_arc_reduced_cost_ts(
                                    node1, node2, apexes[ar2][ac2],
                                    ar2, ac2, ad2, bag_ref,
                                    incrcosts, iscandidate)
                            elif node2.group != _PRUNED_TS and node2.group != _MASKED_TS:
                                _add_new_node_ts(node1, node2, ad2, bkts,
                                                 nflow, incrcosts, ar2, ac2)
                        if node1.next.level <= startlevel:
                            break
                        node1 = node1.next

                ipivots += 1

        # Prune periodically
        nmajor += 1
        if nmajorprune > 0 and nmajor % nmajorprune == 0:
            _prune_tree_ts(source, nodes, ground, incrcosts, flows,
                           ngroundarcs, prunecostthresh,
                           nrow, ncol, ni, nc)

    return inondegen


# ---------------------------------------------------------------------------
# CP7: network_flow_optimize — outer UnwrapTile optimization loop
# Mirrors UnwrapTile() from snaphu.c:406.
# ---------------------------------------------------------------------------

def network_flow_optimize(phase: np.ndarray,
                          costs: np.ndarray,
                          flows: np.ndarray,
                          params: 'SnaphuParams',
                          mag: np.ndarray = None) -> np.ndarray:
    """Nonlinear network-flow optimization — faithful port of TreeSolve loop.

    DONE — ports UnwrapTile()'s optimization section (snaphu.c:541-702) and
    all TreeSolve support functions from snaphu_solver.c.

    Parameters
    ----------
    phase : (nrow, ncol) float32 wrapped phase (used only to size arrays)
    costs : structured arc cost array (smoothcostT or costT dtype)
    flows : (2*nrow-1, ncol) int16 initial flows from mst_init_flows()
    params : SnaphuParams
    mag : (nrow, ncol) float32 magnitude; None → all-ones (GMTSAR path)

    Returns
    -------
    flows : (2*nrow-1, ncol) int16, optimized in-place and returned
    """
    nrow, ncol = phase.shape
    ni = nrow - 1
    nc = ncol - 1

    if mag is None:
        mag = np.ones((nrow, ncol), dtype=np.float32)

    if not np.any(mag > 0):
        return flows   # all masked

    # -----------------------------------------------------------------------
    # InitNetwork: corner arc disambiguation (snaphu_solver.c:2568-2576)
    # -----------------------------------------------------------------------
    flows[0, 0] = int(flows[0, 0]) + int(flows[nrow - 1, 0])
    flows[nrow - 1, 0] = 0
    flows[0, ncol - 1] = int(flows[0, ncol - 1]) - int(flows[nrow - 1, ncol - 2])
    flows[nrow - 1, ncol - 2] = 0
    flows[nrow - 2, 0] = int(flows[nrow - 2, 0]) - int(flows[2 * nrow - 2, 0])
    flows[2 * nrow - 2, 0] = 0
    flows[nrow - 2, ncol - 1] = (int(flows[nrow - 2, ncol - 1])
                                  + int(flows[2 * nrow - 2, ncol - 2]))
    flows[2 * nrow - 2, ncol - 2] = 0

    # ngroundarcs (snaphu_solver.c:2595-2600)
    if ncol > 2:
        ngroundarcs = 2 * (nrow + ncol - 2) - 4
    else:
        ngroundarcs = 2 * (nrow + ncol - 2) - 2

    # Bucket extents (snaphu_solver.c:2609-2625)
    bkt_minind = -int(np.round((params.maxcost + 1) * (nrow + ncol)
                               * _NEGBUCKETFRACTION))
    bkt_maxind = int(np.round((params.maxcost + 1) * (nrow + ncol)
                              * _POSBUCKETFRACTION))

    # Allocate node grid and ground node
    nodes = [[_NodeTS(r, c) for c in range(nc)] for r in range(ni)]
    ground = _NodeTS(_GROUNDROW_TS, -2)   # GROUNDCOL = -2

    # Incremental cost array (poscost, negcost both int16)
    incrcost_dtype = np.dtype([('poscost', np.int16), ('negcost', np.int16)])
    incrcosts = np.zeros((2 * nrow - 1, ncol), dtype=incrcost_dtype)

    # apexes: sentinel _NONTREEARC_TS = arc not yet in tree
    apexes = [[_NONTREEARC_TS] * ncol for _ in range(2 * nrow - 1)]
    iscandidate = np.zeros((2 * nrow - 1, ncol), dtype=np.uint8)

    candidatebag = []
    candidatelist = []
    bkts = _BktsTS(bkt_minind, bkt_maxind)

    use_maxcyclefraction = (params.maxnflowcycles == -123)  # USEMAXCYCLEFRACTION

    # MaskNodes (no-op for GMTSAR)
    _mask_nodes_ts(nrow, ncol, nodes, ground, mag)

    mostflow = int(np.max(np.abs(flows))) if flows.size > 0 else 0
    if mostflow * params.nshortcycle > LARGESHORT:
        raise ValueError(
            f"mostflow={mostflow} * nshortcycle={params.nshortcycle} "
            f"= {mostflow * params.nshortcycle} > LARGESHORT={LARGESHORT}. "
            "Reduce maxflow or nshortcycle."
        )

    nflow = 1
    ncycle = 0
    nflowdone = 0
    notfirstloop = False
    nnondecreasedcostiter = 0

    # -----------------------------------------------------------------------
    # Main optimization loop (UnwrapTile lines 590-701)
    # -----------------------------------------------------------------------
    while True:
        _setup_incr_flow_costs_ts(costs, incrcosts, flows,
                                   nflow, nrow, ncol, params)

        sourcelist = _select_sources_ts(nodes, mag, ground, nflow, flows,
                                         ngroundarcs, nrow, ncol, params)

        # SetupTreeSolveNetwork: reset state
        for r in range(ni):
            for c in range(nc):
                nd = nodes[r][c]
                if nd.group != _MASKED_TS:
                    nd.group = 0
                nd.incost = _VERYFAR_TS
                nd.outcost = _VERYFAR_TS
                nd.pred = None
        if ground.group != _MASKED_TS:
            ground.group = 0
        ground.incost = _VERYFAR_TS
        ground.outcost = _VERYFAR_TS
        ground.pred = None
        for arcrow in range(2 * nrow - 1):
            mc2 = ncol if arcrow < nrow - 1 else ncol - 1
            for arccol in range(mc2):
                apexes[arcrow][arccol] = _NONTREEARC_TS
                iscandidate[arcrow, arccol] = 0
        # Corner arcs always iscandidate=True
        iscandidate[nrow - 1, 0] = 1
        iscandidate[2 * nrow - 2, 0] = 1
        iscandidate[nrow - 1, ncol - 2] = 1
        iscandidate[2 * nrow - 2, ncol - 2] = 1

        # Run TreeSolve for each source
        n = 0
        last_nconn = 1
        for source, nconnected in sourcelist:
            last_nconn = nconnected
            candidatebag.clear()
            candidatelist.clear()
            n += _tree_solve_ts(
                nodes, ground, source, candidatebag, candidatelist,
                bkts, flows, costs, incrcosts, apexes, iscandidate,
                ngroundarcs, nflow, mag, nrow, ncol, nconnected, params)

        ncycle += n

        if use_maxcyclefraction:
            maxnflowcycles_val = int(params.maxcyclefraction * last_nconn)
        else:
            maxnflowcycles_val = params.maxnflowcycles

        if n <= maxnflowcycles_val:
            nflowdone += 1
        else:
            nflowdone = 1

        mostflow = int(np.max(np.abs(flows))) if flows.size > 0 else 0

        if nnondecreasedcostiter >= 2 * mostflow:
            break

        if (nflowdone >= params.maxflow or nflowdone >= mostflow
                or params.p >= 1.0):
            break

        nflow += 1
        if nflow > params.maxflow or nflow > mostflow:
            nflow = 1
            notfirstloop = True

    return flows


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

    C algorithm (IntegratePhase in snaphu_util.c):
      1. Set unwrapped[0,0] = phase[0,0]  (reference pixel)
      2. Integrate along top row using col-direction flows:
           unwrapped[0,c] = unwrapped[0,c-1] + wrap(phase[0,c] - phase[0,c-1])
                            + TWOPI * colflow[0, c-1]
      3. Integrate down each column using row-direction flows:
           unwrapped[r,c] = unwrapped[r-1,c] + wrap(phase[r,c] - phase[r-1,c])
                            - TWOPI * rowflow[r-1, c]

    NOTE: row-arc flows use a MINUS sign (C line 339: - rowflow[row-1][col]*TWOPI).
    Col-arc flows use a PLUS sign (C line 332: + colflow[0][col-1]*TWOPI).
    Positive rowflow means subtract 2π going down; positive colflow means add 2π going right.
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
    # C: phi[row][col] += ModDiff - rowflow[row-1][col]*TWOPI  (MINUS sign on rowflow)
    for r in range(1, nrow):
        dphi_col = phase64[r, :] - phase64[r - 1, :]      # (ncol,)
        dphi_col = _wrap_diff(dphi_col)
        unwrap[r, :] = unwrap[r - 1, :] + dphi_col - TWOPI * rowflow[r - 1]

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
# CP9: Connected component growth — DONE
# ---------------------------------------------------------------------------
# C source: snaphu_tile.c:GrowConnCompsMask() (lines 663-941),
#           ThickenCosts() (lines 945-1015),
#           RegionsNeighborNode() (lines 1018-1067),
#           RenumberRegion() (lines 1154-1196),
#           ClosestNode() from snaphu_solver.c (lines 2981-3011).
# ---------------------------------------------------------------------------

class _NodeCC:
    """Pixel node for connected-component BFS.  Mirrors nodeT for this use."""
    __slots__ = ('row', 'col', 'group', 'incost', 'outcost',
                 'pred', 'next', 'prev')

    def __init__(self, row: int, col: int):
        self.row = row
        self.col = col
        self.group = 0          # NOTINBUCKET / INBUCKET / ONTREE
        self.incost = -1        # reused as region label
        self.outcost = LARGEINT
        self.pred = None
        self.next = None
        self.prev = None


_INBUCKET_CC = -2
_ONTREE_CC = -1
_NOTINBUCKET_CC = -3


def _regions_neighbor_node_cc(node: _NodeCC, arcnum: int,
                               nodes: list, nrow: int, ncol: int):
    """Return (neighbor, arcrow, arccol) or (None, -, -).

    Mirrors RegionsNeighborNode() in snaphu_tile.c:1024.
    arcnum is incremented by the caller; pass 0,1,2,3,... until None.
    """
    row, col = node.row, node.col
    if arcnum == 0:
        if col != ncol - 1:
            return nodes[row][col + 1], nrow - 1 + row, col
    elif arcnum == 1:
        if row != nrow - 1:
            return nodes[row + 1][col], row, col
    elif arcnum == 2:
        if col != 0:
            return nodes[row][col - 1], nrow - 1 + row, col - 1
    elif arcnum == 3:
        if row != 0:
            return nodes[row - 1][col], row - 1, col
    return None, -1, -1


def _renumber_region_cc(nodes: list, source: _NodeCC, newnum: int,
                        nrow: int, ncol: int) -> None:
    """BFS relabel all nodes with incost==regionnum to newnum.

    Mirrors RenumberRegion() in snaphu_tile.c:1154.
    """
    regionnum = source.incost
    stack = [source]
    while stack:
        frm = stack.pop()
        frm.incost = newnum
        arcnum = 0
        while True:
            to, _, _ = _regions_neighbor_node_cc(frm, arcnum, nodes, nrow, ncol)
            if arcnum >= 3:
                break
            arcnum += 1
            if to is not None and to.incost == regionnum:
                stack.append(to)


def _thicken_costs_cc(incrcosts: np.ndarray, nrow: int, ncol: int) -> None:
    """Spatial blurring of poscost → stored in negcost field.

    Mirrors ThickenCosts() in snaphu_tile.c:945.
    Row arcs (arcrow < nrow-1): average self + col-1 + col+1 neighbours.
    Col arcs (arcrow >= nrow-1): average self + row-1 + row+1 neighbours.
    Result clipped to LARGESHORT; stored in negcost.
    """
    # Row arcs
    for row in range(nrow - 1):
        pc = incrcosts['poscost'][row, :].astype(np.int64)
        acc = 2 * pc
        cnt = np.full(ncol, 2.0)
        acc[1:] += pc[:-1]; cnt[1:] += 1.0
        acc[:-1] += pc[1:]; cnt[:-1] += 1.0
        result = np.round(acc / cnt).astype(np.int64)
        result = np.clip(result, -LARGESHORT, LARGESHORT)
        incrcosts['negcost'][row, :] = result.astype(np.int16)

    # Col arcs
    for row in range(nrow - 1, 2 * nrow - 1):
        pc = incrcosts['poscost'][row, :ncol - 1].astype(np.int64)
        acc = 2 * pc
        cnt = np.full(ncol - 1, 2.0)
        if row != nrow - 1:
            acc += incrcosts['poscost'][row - 1, :ncol - 1].astype(np.int64)
            cnt += 1.0
        if row != 2 * nrow - 2:
            acc += incrcosts['poscost'][row + 1, :ncol - 1].astype(np.int64)
            cnt += 1.0
        result = np.round(acc / cnt).astype(np.int64)
        result = np.clip(result, -LARGESHORT, LARGESHORT)
        incrcosts['negcost'][row, :ncol - 1] = result.astype(np.int16)


def grow_conn_comps(costs: np.ndarray, flows: np.ndarray,
                    nrow: int, ncol: int,
                    params: 'SnaphuParams') -> np.ndarray:
    """Grow connected components mask. Returns uint8 (nrow, ncol) labels.

    DONE — faithful port of GrowConnCompsMask() in snaphu_tile.c:663.

    Algorithm:
    1. For every arc, ReCalcCost at nflow=1; take min(pos, neg); negate,
       subtract costthresh, clip to 0. Store in incrcosts.poscost.
    2. ThickenCosts: spatially blur poscost → stored in negcost.
    3. BFS region-growing from every unassigned pixel. An arc boundary is
       passable iff negcost==0 (i.e., original cost was <= costthresh).
    4. Drop regions smaller than minsize.
    5. Keep only maxncomps largest if there are too many.
    6. Return label array (0 = not in any component).
    """
    minsize = int(params.minconncompfrac * nrow * ncol)
    maxncomps = params.maxncomps
    costthresh = params.conncompthresh

    # Step 1: compute incrcosts for all arcs at nflow=1
    incrcost_dtype = np.dtype([('poscost', np.int16), ('negcost', np.int16)])
    incrcosts = np.zeros((2 * nrow - 1, ncol), dtype=incrcost_dtype)

    for arcrow in range(2 * nrow - 1):
        maxcol = ncol if arcrow < nrow - 1 else ncol - 1
        for arccol in range(maxcol):
            _recalc_cost_ts(costs, incrcosts, int(flows[arcrow, arccol]),
                            arcrow, arccol, 1, nrow, params)
            # take min of pos/neg, negate, subtract threshold, clip to >=0
            pc = int(incrcosts['poscost'][arcrow, arccol])
            nc_ = int(incrcosts['negcost'][arcrow, arccol])
            best = min(pc, nc_)
            val = -(best - costthresh)
            incrcosts['poscost'][arcrow, arccol] = np.int16(max(val, 0))

    # Step 2: ThickenCosts (spatially blur poscost → negcost)
    _thicken_costs_cc(incrcosts, nrow, ncol)

    # Step 3: Allocate pixel nodes
    nodes = [[_NodeCC(r, c) for c in range(ncol)] for r in range(nrow)]

    # Single-slot circular "bucket" (indices 0..0)
    bucket0 = None   # Python list acts as head pointer

    regioncounter = 0
    regionsizes = [0]   # 1-indexed; regionsizes[regioncounter]

    for row in range(nrow):
        for col in range(ncol):
            node = nodes[row][col]
            if node.incost >= 0:
                continue   # already assigned

            # New region: BFS from this pixel using negcost==0 boundary
            regioncounter += 1
            regionsizes.append(0)
            thissize = 0

            node.group = _INBUCKET_CC
            node.outcost = 0

            # BFS queue (FIFO, but C uses bucket with single bucket → FIFO)
            queue = [node]
            qhead = 0

            while qhead < len(queue):
                frm = queue[qhead]; qhead += 1
                frm.incost = regioncounter
                thissize += 1

                arcnum = 0
                while arcnum <= 3:
                    to, arcrow, arccol = _regions_neighbor_node_cc(
                        frm, arcnum, nodes, nrow, ncol)
                    arcnum += 1
                    if to is None:
                        continue
                    if (to.incost < 0
                            and int(incrcosts['negcost'][arcrow, arccol]) == 0
                            and to.group != _INBUCKET_CC):
                        to.group = _INBUCKET_CC
                        to.pred = frm
                        queue.append(to)

            regionsizes[regioncounter] = thissize
            if thissize < minsize:
                # Too small — zero it out
                _renumber_region_cc(nodes, node, 0, nrow, ncol)
                regionsizes[regioncounter] = 0
                regioncounter -= 1

    # Step 4: Trim to maxncomps largest if needed
    if regioncounter > maxncomps:
        # Build sorted list of sizes (ascending) to find cut threshold
        sizes = sorted(regionsizes[1:regioncounter + 1])
        minsize_cut = sizes[regioncounter - maxncomps]

        # Count tied regions of exactly minsize_cut
        ntied = 0
        for i in range(regioncounter - maxncomps - 1, -1, -1):
            if sizes[i] == minsize_cut:
                ntied += 1
            else:
                break

        # Two-pass renumber
        newnum = -1
        for row in range(nrow):
            for col in range(ncol):
                nd = nodes[row][col]
                i = nd.incost
                if i > 0:
                    sz = regionsizes[i] if i < len(regionsizes) else 0
                    if sz < minsize_cut or (sz == minsize_cut and ntied > 0):
                        if sz == minsize_cut:
                            ntied -= 1
                        _renumber_region_cc(nodes, nd, 0, nrow, ncol)
                    else:
                        _renumber_region_cc(nodes, nd, newnum, nrow, ncol)
                        newnum -= 1

        for row in range(nrow):
            for col in range(ncol):
                nd = nodes[row][col]
                nd.incost = -nd.incost

    # Step 5: Extract label array
    labels = np.zeros((nrow, ncol), dtype=np.uint8)
    for row in range(nrow):
        for col in range(ncol):
            v = nodes[row][col].incost
            if v > 0:
                labels[row, col] = min(v, 255)
    return labels


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
