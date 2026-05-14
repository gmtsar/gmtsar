#! /usr/bin/env python3
import os, time
import numpy as np
import xarray as xr
from skimage import io
from skimage.metrics import structural_similarity as ssim
import matplotlib.pyplot as plt
from cases import caseNameList, intfDirList, rawDir, SLCDir, \
    pythonRunRoot, cshRefRoot, referenceRoot

fileNameList = ['corr_ll.png','display_amp_ll.png','phasefilt_mask_ll.png',
        'corr_ll.grd', 'phasefilt.grd', 'filtcorr.grd']
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
    isTheSame = 'SUCCESS: python and csh '+fileName+' are the same'
    notTheSame = 'FAIL: python and csh '+fileName+' are different'

    if fileType=='png':
        imageNew = io.imread(fnNew)
        imageRef = io.imread(fnRef)
        #assert imageNew.shape == imageRef.shape, 'Images must be the same shape.'
        try:
            ssim_index = ssim(imageNew,imageRef,channel_axis=-1) if imageNew.ndim == 3 else ssim(imageNew,imageRef)
            threshold = PNG_SSIM_THRESHOLD.get(fileName, DEFAULT_PNG_SSIM)
            if ssim_index > threshold:
                print(isTheSame+' '+f'SSIM: {ssim_index}')
            else:
                print(notTheSame+' '+f'SSIM: {ssim_index}')
        except:
            print(notTheSame+' no SSIM')

        if imageNew.shape != imageRef.shape:
            print(notTheSame+' image shapes do not match')
    elif fileType=='grd':
        a = xr.open_dataset(fnNew)['z'].values
        b = xr.open_dataset(fnRef)['z'].values
        if 'phase' in fileName:
            # Phase grids: complex-domain rms |e^{ia} - e^{ib}|. Wrap-invariant
            # (a 2π flip leaves e^{ia} unchanged), so the metric reflects true
            # physical disagreement on the unit circle. Range [0, 2].
            err = np.exp(1j*a) - np.exp(1j*b)
            metric = float(np.sqrt(np.nanmean(np.abs(err)**2)))
            threshold = GRD_RMS_THRESHOLD.get(fileName, 0.1)
            tag = isTheSame if metric < threshold else notTheSame
            print(f'{tag}; complex-rms={metric:.4g} (threshold {threshold})')
        else:
            diff = a - b
            mean  = float(np.nanmean(diff))
            stdev = float(np.nanstd(diff))
            rms   = float(np.sqrt(np.nanmean(diff**2)))
            threshold = GRD_RMS_THRESHOLD.get(fileName, DEFAULT_GRD_RMS)
            tag = isTheSame if rms < threshold else notTheSame
            print(f'{tag}; diff mean={mean:.4g} stdev={stdev:.4g} rms={rms:.4g}')

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


# Three-way comparison: per file, build the (label, fnA, fnB) pairs that have
# both files present. Always includes python_vs_csh. Adds csh_vs_frozen and
# python_vs_frozen when the frozen reference exists for that file.
for caseName in caseNameList:
    print(' ')
    print('Comparing case ', caseName)
    for fileName in fileNameList:
        ftype = 'png' if fileName.endswith('.png') else 'grd'
        for intf in intfDirList[caseName]:
            py     = _file_under(pyRoot,     caseName, intf, fileName)
            csh    = _file_under(cshRoot,    caseName, intf, fileName)
            frozen = _file_under(frozenRoot, caseName, intf, fileName)
            pairs = []
            if os.path.exists(py) and os.path.exists(csh):
                pairs.append(('py-vs-csh',     py,  csh))
            if os.path.exists(csh) and os.path.exists(frozen):
                pairs.append(('csh-vs-frozen', csh, frozen))
            if os.path.exists(py) and os.path.exists(frozen):
                pairs.append(('py-vs-frozen',  py,  frozen))
            for label, fnA, fnB in pairs:
                print(f'  [{label}]', end=' ')
                compare_files(fnA, fnB, fileName, ftype)

    findErrorsInLogFiles(pyRoot+'/'+caseName)

