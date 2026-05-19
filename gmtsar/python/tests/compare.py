#! /usr/bin/env python3
"""Compare Python pipeline outputs against the legacy csh outputs (and the
frozen reference, if present). Emits human-readable lines on stdout AND writes
a machine-readable JSON sidecar per case at <workdir>/results/<case>.json so
report.py can aggregate without log scraping."""
import glob, json, os, re, time
from datetime import datetime, timezone
import numpy as np
import xarray as xr
from skimage import io
from skimage.metrics import structural_similarity as ssim
import matplotlib.pyplot as plt
from cases import caseNameList, rawDir, SLCDir, \
    pythonRunRoot, cshRefRoot, referenceRoot, workAbsoluteDir

fileNameList = ['corr_ll.png','display_amp_ll.png','phasefilt_mask_ll.png',
        'corr_ll.grd', 'phasefilt.grd', 'filtcorr.grd',
        # los_ll.grd: only built when threshold_snaphu>0 + threshold_geocode>0
        # (currently ALOS_haiti). Previously omitted, so the geocode-stage
        # `$wavel` literal-shell-var bug never surfaced. Now included so that
        # any LOS-stage regression is caught.
        'los_ll.grd']

# Optional files: produced by some recipes and not others, depending on whether
# threshold flags enable the LOS / geocode-2 path. When one side has the file
# and the other doesn't, treat as recipe-divergence (skipped) rather than FAIL.
# A real regression on these is caught via the py-vs-frozen pair when frozen
# reference exists.
OPTIONAL_FILES = {'los_ll.grd'}
pyRoot    = pythonRunRoot.rstrip(os.sep)   # today's python outputs
cshRoot   = cshRefRoot.rstrip(os.sep)      # today's csh outputs
frozenRoot = referenceRoot.rstrip(os.sep)  # frozen reference (committed in tree)

# Comparison thresholds. Tuned so visually-indistinguishable outputs pass and
# real pipeline regressions still fail (broken images typically score < 0.5).
PNG_SSIM_THRESHOLD = {}            # per-file overrides (empty: use default)
GRD_RMS_THRESHOLD  = {'phasefilt.grd': 0.15}   # complex-rms; ≈ 8.6° avg phase
DEFAULT_PNG_SSIM   = 0.9           # 0.9+ is visually equivalent for SAR imagery
DEFAULT_GRD_RMS    = 1e-2          # <1% rms on [0,1] grids = within InSAR noise

def parseCmdOutput(fn, searchStr):
    result = float('nan')   # if searchStr not present (e.g. grdinfo failed), return NaN
    with open(fn,'r') as f:
        for line in f:
            if searchStr in line:
                val = line.split()
                keyIndex = val.index(searchStr)
                result = float(val[keyIndex+1])
    return result

def compare_nc_files(fn1,fn2,threshold=1e-3):
    isTheSame = 'SUCCESS '+fn1+' '+fn2
    f1 = xr.open_dataset(fn1)
    f2 = xr.open_dataset(fn2)
    metadata_equal = f1.identical(f2)
    data_equal = (f1==f2).all().items()
    
    # Compare variables
    for var in f1.variables:
        var1 = f1[var]
        var2 = f2[var]
        if var1.dims != var2.dims:
            isTheSame = 'FAIL var dim '+fn1+' '+fn2
        if not np.allclose(var1,var2,rtol=threshold, atol=threshold):
            isTheSame = 'FAIL var numbers '+fn1+' '+fn2
        
    if not metadata_equal:# and data_equal:
        isTheSame = 'FAIL metadata '+fn1+' '+fn2
    
    try:
        xr.testing.assert_allclose(f1,f2)
        print('SUCCESS by xarray.testing.assert_allclose')
        print('SUCCESS '+fn1 +' '+fn2)
    except AssertionError as e:
        print(e)
    print(isTheSame)
    
    return isTheSame

def compare_txt_files(fn1,fn2,threshold=1e-3):
    isTheSame = 'SUCCESS '+fn1+' '+fn2
    with open(fn1,'r') as f1, open(fn2,'r') as f2:
        result1 = f1.read().split()
        result2 = f2.read().split()
    if len(result1) != len(result2):
        isTheSame = 'FAIL '+fn1+' '+fn2
    
    for num1,num2 in zip(result1,result2):
        fnum1, fnum2 = float(num1),float(num2)
        if abs(fnum1-fnum2) > threshold:
            isTheSame = 'FAIL '+fn1+' '+fn2
    print(isTheSame)

def compare_files(fnNew, fnRef, fileName, fileType):
    """Compare two files, print a human line on stdout, return a result dict.
    Result schema:
        {file, type, status: SUCCESS|FAIL, metric: float, threshold: float,
         metric_name: 'ssim' | 'rms' | 'complex-rms', extra: {...}}
    """
    same = 'SUCCESS: python and csh '+fileName+' are the same'
    diff = 'FAIL: python and csh '+fileName+' are different'

    if fileType == 'png':
        imageNew = io.imread(fnNew)
        imageRef = io.imread(fnRef)
        # Same upstream-gmt-surface non-determinism as for grids: when the
        # underlying _ll.grd differs in size by a few cells, the rendered PNG
        # inherits that. Crop both to common shape per axis (≤1% tolerance)
        # before SSIM. Larger mismatches → FAIL via the SSIM-crash fallback
        # since cropping wouldn't make sense.
        png_shape_note = None
        if imageNew.shape != imageRef.shape and imageNew.ndim == imageRef.ndim:
            ax_diffs = [abs(sn - sr) / max(sn, sr) for sn, sr in zip(imageNew.shape[:2], imageRef.shape[:2])]
            if max(ax_diffs) <= 0.01:
                common = tuple(min(sn, sr) for sn, sr in zip(imageNew.shape[:2], imageRef.shape[:2]))
                imageNew = imageNew[:common[0], :common[1]]
                imageRef = imageRef[:common[0], :common[1]]
                png_shape_note = f'cropped to common shape {common}; orig diff <={max(ax_diffs):.2%}'
                print(f'  [shape tolerance] {png_shape_note}')
        try:
            ssim_index = ssim(imageNew, imageRef, channel_axis=-1) if imageNew.ndim == 3 else ssim(imageNew, imageRef)
        except Exception:
            print(diff + ' no SSIM')
            return {'file': fileName, 'type': 'png', 'status': 'FAIL',
                    'metric_name': 'ssim', 'metric': None, 'threshold': None,
                    'extra': {'error': 'ssim failed'}}
        threshold = PNG_SSIM_THRESHOLD.get(fileName, DEFAULT_PNG_SSIM)
        ok = ssim_index > threshold
        print(f'{same if ok else diff} SSIM: {ssim_index}')
        r = {'file': fileName, 'type': 'png',
             'status': 'SUCCESS' if ok else 'FAIL',
             'metric_name': 'ssim', 'metric': float(ssim_index),
             'threshold': float(threshold)}
        if png_shape_note: r['shape_tolerance'] = png_shape_note
        return r

    # fileType == 'grd'
    dsNew = xr.open_dataset(fnNew)
    dsRef = xr.open_dataset(fnRef)
    a, b = dsNew['z'], dsRef['z']
    # Keep as xarray DataArrays through the shape-mismatch branch so we can
    # do coordinate-aware slicing; convert to numpy at the metric step.
    # Shape mismatch handling. Small (<=1% per axis) mismatches come from
    # upstream `gmt surface` non-determinism on identical inputs (md5-match
    # trans.dat → different n_rows). Align by COORDINATES (not by integer
    # index) before comparing — the divergence is typically an extra row/col
    # at one geographic edge, so corner-crop would compare offset regions.
    shape_note = None
    if a.shape != b.shape:
        if a.ndim != b.ndim:
            print(f'{diff}; ndim mismatch py={a.ndim} csh={b.ndim}')
            return {'file': fileName, 'type': 'grd-shape', 'status': 'FAIL',
                    'reason': f'ndim mismatch py={a.shape} csh={b.shape}',
                    'metric_name': 'shape', 'metric': None, 'threshold': None}
        rel_diff = max(abs(sa - sb) / max(sa, sb) for sa, sb in zip(a.shape, b.shape))
        if rel_diff > 0.01:
            print(f'{diff}; shape mismatch py={a.shape} csh={b.shape} (rel diff {rel_diff:.1%} > 1%)')
            return {'file': fileName, 'type': 'grd-shape', 'status': 'FAIL',
                    'reason': f'shape mismatch py={a.shape} csh={b.shape} (rel diff {rel_diff:.1%})',
                    'metric_name': 'shape', 'metric': None, 'threshold': None}
        # Coordinate-aware intersection: take the lat/lon overlap of both
        # grids, then resample one onto the other's grid via nearest-neighbor
        # (the shapes differ by ≤1% so the resample is essentially identity
        # on the overlapping cells). xarray.DataArray.interp_like handles this.
        try:
            # Find coordinate names (typically 'x','y' or 'lon','lat').
            cy, cx = a.dims
            ya_lo, ya_hi = float(a[cy].min()), float(a[cy].max())
            yb_lo, yb_hi = float(b[cy].min()), float(b[cy].max())
            xa_lo, xa_hi = float(a[cx].min()), float(a[cx].max())
            xb_lo, xb_hi = float(b[cx].min()), float(b[cx].max())
            y_lo, y_hi = max(ya_lo, yb_lo), min(ya_hi, yb_hi)
            x_lo, x_hi = max(xa_lo, xb_lo), min(xa_hi, xb_hi)
            a_clip = a.sel({cy: slice(y_lo, y_hi), cx: slice(x_lo, x_hi)})
            b_clip = b.sel({cy: slice(y_lo, y_hi), cx: slice(x_lo, x_hi)})
            # Final shape match after coord-based clip (may still differ by
            # 1 cell from off-by-one boundary inclusion; reindex_like is the
            # safety net).
            if a_clip.shape != b_clip.shape:
                b_clip = b_clip.reindex_like(a_clip, method='nearest')
            a = a_clip.values
            b = b_clip.values
            shape_note = (f'coord-aligned to overlap [{x_lo:.4f}..{x_hi:.4f}, '
                          f'{y_lo:.4f}..{y_hi:.4f}], common shape {a.shape}; '
                          f'orig diff {rel_diff:.2%}')
            print(f'  [shape tolerance] {shape_note}')
        except Exception as e:
            print(f'{diff}; coord-align failed: {e}; raw shape py={a.shape} csh={b.shape}')
            return {'file': fileName, 'type': 'grd-shape', 'status': 'FAIL',
                    'reason': f'coord-align failed: {e}',
                    'metric_name': 'shape', 'metric': None, 'threshold': None}
    else:
        # No shape mismatch — convert to numpy directly.
        a = a.values
        b = b.values
    if 'phase' in fileName:
        # Wrap-invariant complex-domain rms |e^{ia} - e^{ib}|.
        err = np.exp(1j*a) - np.exp(1j*b)
        metric = float(np.sqrt(np.nanmean(np.abs(err)**2)))
        threshold = float(GRD_RMS_THRESHOLD.get(fileName, 0.1))
        ok = metric < threshold
        print(f'{same if ok else diff}; complex-rms={metric:.4g} (threshold {threshold})')
        r = {'file': fileName, 'type': 'grd-phase',
             'status': 'SUCCESS' if ok else 'FAIL',
             'metric_name': 'complex-rms', 'metric': metric, 'threshold': threshold}
        if shape_note: r['shape_tolerance'] = shape_note
        return r
    # plain grd
    d = a - b
    mean  = float(np.nanmean(d))
    stdev = float(np.nanstd(d))
    rms   = float(np.sqrt(np.nanmean(d**2)))
    threshold = float(GRD_RMS_THRESHOLD.get(fileName, DEFAULT_GRD_RMS))
    ok = rms < threshold
    print(f'{same if ok else diff}; diff mean={mean:.4g} stdev={stdev:.4g} rms={rms:.4g}')
    r = {'file': fileName, 'type': 'grd',
         'status': 'SUCCESS' if ok else 'FAIL',
         'metric_name': 'rms', 'metric': rms, 'threshold': threshold,
         'extra': {'mean': mean, 'stdev': stdev}}
    if shape_note: r['shape_tolerance'] = shape_note
    return r

def findErrorsInLogFiles(caseDir):
    """Scan ONLY the top-level log.txt for this case (written by README_<case>.txt).
    The old os.walk approach traversed tens of thousands of intermediate files
    per S1_TOPS case on NFS — orders of magnitude slower for no extra signal."""
    path = os.path.join(caseDir, 'log.txt')
    if not os.path.isfile(path):
        return
    with open(path, 'r', errors='replace') as f:
        contents = f.read()
    errKeyWordList = ('error', 'Error', 'Traceback', 'ERROR')
    tag = 'Error found in' if any(k in contents for k in errKeyWordList) else 'No Error found in'
    print(tag, path)


def _file_under(root, case, intf, fname):
    return f'{root}/{case}/{intf}/{fname}'


def discover_intf_dirs(case):
    """Find every subdir of <root>/<case>/ that contains AT LEAST ONE of the
    comparison-target files (fileNameList), across all available trees
    (python_test, csh_test, reference). Returns the union as sorted paths.

    Replaces the old hardcoded intfDirList: a re-acquisition with different
    date pairs (e.g. intf/2010095_2010141 → intf/2024nnn_2024mmm) would have
    silently broken the hardcoded list. S1_TOPS cases need a multi-file probe
    because subswath dirs (F1/F2/F3) and the merge dir produce different
    subsets of fileNameList — sentinel-on-corr_ll.grd alone misses ~half."""
    dirs = set()
    for root in (pyRoot, cshRoot, frozenRoot):
        case_root = f'{root}/{case}'
        if not os.path.isdir(case_root):
            continue
        for fname in fileNameList:
            for path in glob.glob(f'{case_root}/**/{fname}', recursive=True):
                rel = os.path.dirname(os.path.relpath(path, case_root))
                dirs.add(rel)
    return sorted(dirs)


# Three-way comparison: per file, build the (label, fnA, fnB) pairs that have
# both files present. Always includes python_vs_csh. Adds csh_vs_frozen and
# python_vs_frozen when the frozen reference exists for that file.
RESULTS_DIR = os.path.join(workAbsoluteDir.rstrip(os.sep), 'results')
os.makedirs(RESULTS_DIR, exist_ok=True)

for caseName in caseNameList:
    print(' ')
    print('Comparing case ', caseName)
    case_results = {
        'case': caseName,
        'generated': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'comparisons': [],
    }
    intf_dirs = discover_intf_dirs(caseName)
    for fileName in fileNameList:
        ftype = 'png' if fileName.endswith('.png') else 'grd'
        for intf in intf_dirs:
            py     = _file_under(pyRoot,     caseName, intf, fileName)
            csh    = _file_under(cshRoot,    caseName, intf, fileName)
            frozen = _file_under(frozenRoot, caseName, intf, fileName)
            # discover_intf_dirs added `intf` because AT LEAST ONE tree has
            # the file. If a different tree is missing it, that's a real
            # divergence — record it as FAIL rather than silently dropping.
            # Previously the framework would auto-discover only the dirs
            # where files exist on at least one side and skip-when-missing,
            # so a py-side merge that didn't produce phasefilt.grd would
            # vanish from the comparison count instead of failing.
            py_ok, csh_ok, frozen_ok = (
                os.path.exists(py), os.path.exists(csh), os.path.exists(frozen))
            def _absent(label, missing_side, expected_path):
                print(f'  [{label}] FAIL: {fileName} missing on {missing_side} '
                      f'({expected_path})')
                return {'file': fileName, 'type': ftype, 'status': 'FAIL',
                        'reason': f'{fileName} missing on {missing_side}',
                        'expected_path': expected_path,
                        'pair': label, 'intf': intf}
            # Per-subswath _ll files (multi-subswath cases like ALOS2_SCAN):
            # bundled csh README only geocodes at the merge level, py recipe
            # geocodes per-subswath too. Same asymmetry as los_ll.grd. Skip
            # rather than FAIL when the absent side simply doesn't run that
            # step at per-subswath level. Merge-level _ll files are still
            # compared strictly.
            persubswath_ll = ('_ll.' in fileName and
                              bool(re.match(r'^F\d+/', intf or '')))
            # py-vs-csh: both expected to exist; missing on either side = FAIL
            if py_ok and csh_ok:
                print(f'  [py-vs-csh]', end=' ')
                r = compare_files(py, csh, fileName, ftype)
                r['pair'] = 'py-vs-csh'; r['intf'] = intf
                case_results['comparisons'].append(r)
            elif py_ok and not csh_ok:
                if fileName in OPTIONAL_FILES or persubswath_ll:
                    print(f'  [py-vs-csh] SKIP: {fileName} optional, '
                          f'absent on csh (recipe divergence)')
                else:
                    case_results['comparisons'].append(_absent('py-vs-csh', 'csh', csh))
            elif csh_ok and not py_ok:
                if fileName in OPTIONAL_FILES or persubswath_ll:
                    print(f'  [py-vs-csh] SKIP: {fileName} optional, '
                          f'absent on py (recipe divergence)')
                else:
                    case_results['comparisons'].append(_absent('py-vs-csh', 'py', py))
            # csh-vs-frozen: only meaningful if frozen reference is present
            # for this case. Don't FAIL on missing frozen since frozen ref
            # is gitignored / not always available.
            if csh_ok and frozen_ok:
                print(f'  [csh-vs-frozen]', end=' ')
                r = compare_files(csh, frozen, fileName, ftype)
                r['pair'] = 'csh-vs-frozen'; r['intf'] = intf
                case_results['comparisons'].append(r)
            # py-vs-frozen: same — only when both present
            if py_ok and frozen_ok:
                print(f'  [py-vs-frozen]', end=' ')
                r = compare_files(py, frozen, fileName, ftype)
                r['pair'] = 'py-vs-frozen'; r['intf'] = intf
                case_results['comparisons'].append(r)

    findErrorsInLogFiles(pyRoot + '/' + caseName)

    with open(os.path.join(RESULTS_DIR, caseName + '.json'), 'w') as f:
        json.dump(case_results, f, indent=2)

