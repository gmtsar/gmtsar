#!/usr/bin/env python3
"""NISAR GSLC pair processing with GMTSAR p2p arguments and configurations."""
# Author: Xin Wang, USTC; Contact: xinw11@mail.ustc.edu.cn
# Repository: https://github.com/Xin-Wang-520/gmtsar-nisar-gslc-dinsar-workflow
# Numerical conventions follow the author's GSLC workflow and GMTSAR filters.
# License: GNU GPL v3; see LICENSE. GMTSAR/GMT/SNAPHU retain their authorship.
import argparse
from contextlib import ExitStack
from datetime import datetime
import json
import logging
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import h5py
import netCDF4
import numpy as np
from pyproj import CRS
from scipy.ndimage import convolve1d, distance_transform_edt

LOG = logging.getLogger('p2p_gslc')
C = 299792458.0
DEFAULTS = dict(proc_stage='1', skip_stage='', switch_master='0', dec_factor='2',
                threshold_snaphu='0.1', threshold_geocode='0.1', defomax='0',
                near_interp='0', mask_water='0', correct_iono='0', compute_phase_gradient='0')
EXTENSIONS = dict(gslc_polarization='HH', gslc_spacing_x='', gslc_spacing_y='', gslc_region='',
                  gslc_plot='1', gslc_goldstein_mode='coherence', gslc_filter_alpha='0.5',
                  gslc_unwrap_tiles_y='0', gslc_unwrap_tiles_x='0', gslc_unwrap_nproc='2',
                  gslc_effective_looks='', gslc_min_valid_fraction='0.8')
RADAR_KEYS = set('skip_master num_patches earth_radius near_range fd1 SLC_factor geometric_coreg '
                 'topo_phase topo_interp_mode shift_topo iono_filt_rng iono_filt_azi iono_dsamp '
                 'iono_skip_est spec_div spec_mode region_cut range_dec azimuth_dec switch_land'.split())
LAYERS = ('display_amp', 'phase', 'corr', 'phasefilt', 'unwrap', 'los')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def run(command, cwd, env=None, logfile=None):
    with Path(logfile or Path(cwd)/'tools.log').open('a') as log:
        log.write(json.dumps(list(map(str, command)))+'\n'); log.flush()
        subprocess.run(list(map(str, command)), cwd=cwd, env=env, stdout=log,
                       stderr=subprocess.STDOUT, check=True)


def scalar(value):
    if isinstance(value, np.ndarray): value = value.item()
    if isinstance(value, np.generic): value = value.item()
    return value.decode().rstrip('\x00') if isinstance(value, bytes) else value


def configuration_text(band):
    spacing = '40' if band == 'A' else '120'
    values = {**DEFAULTS, 'filter_wavelength': '160' if band == 'A' else '640', **EXTENSIONS,
              'gslc_spacing_x': spacing, 'gslc_spacing_y': spacing}
    sections = (
        ('processing stage',
         '1-3: validate GSLC inputs; focusing and terrain flattening are already applied.\n'
         '4: make and filter interferograms; 5: unwrap phase; 6: export longitude/latitude.\n'
         'proc_stage starts here and runs the remaining stages. skip_stage: comma-separated, blank for none.',
         'proc_stage skip_stage'),
        ('parameters for input and map grid',
         'gslc_polarization: HH, HV, VH or VV, as available in both products.\n'
         'gslc_region: XMIN/XMAX/YMIN/YMAX in product-CRS metres; blank for the common full extent.\n'
         'gslc_spacing_x/y: output east/north spacing in metres; defaults A=40/40 m, B=120/120 m.\n'
         'Use integer multiples of the native spacing. Clear both values for automatic decimation.\n'
         'gslc_min_valid_fraction: minimum joint valid fraction for filtering and output blocks (0,1].',
         'gslc_polarization gslc_region gslc_spacing_x gslc_spacing_y gslc_min_valid_fraction'),
        ('parameters for make and filter interferograms',
         'switch_master: 0 uses master as reference; 1 exchanges reference and secondary.\n'
         'Phase convention: angle(reference * conjugate(secondary)).\n'
         'filter_wavelength: Gaussian wavelength in metres; 0 uses block averaging.\n'
         'dec_factor: automatic map-grid decimation multiplier (1, 2 or 4); explicit spacings override it.\n'
         'gslc_goldstein_mode: coherence (adaptive) or fixed; gslc_filter_alpha applies only to fixed mode.',
         'switch_master filter_wavelength dec_factor gslc_goldstein_mode gslc_filter_alpha'),
        ('parameters for unwrap phase',
         'threshold_snaphu: coherence threshold (0-1); 0 skips unwrapping.\n'
         'near_interp: 1 fills solver inputs with nearest reliable phase; final quality mask is restored.\n'
         'mask_water: 1 uses a supplied, matching landmask.grd; no automatic landmask is generated.\n'
         'defomax: discontinuity in cycles; 0 selects smooth costs, positive values select deformation costs.\n'
         'gslc_unwrap_tiles_y/x: tile rows/columns; 0 selects automatically. gslc_unwrap_nproc: workers.\n'
         'gslc_effective_looks: SNAPHU correlation looks; blank uses the provisional nominal block count.',
         'threshold_snaphu near_interp mask_water defomax gslc_unwrap_tiles_y gslc_unwrap_tiles_x '
         'gslc_unwrap_nproc gslc_effective_looks'),
        ('parameters for geocode and figures',
         'threshold_geocode: coherence threshold for geographic phase/LOS; 0 skips geographic export.\n'
         'gslc_plot: 1 draws unshaded GMT PDFs with bottom colorbars; 0 skips figures.',
         'threshold_geocode gslc_plot'),
        ('other parameters',
         'Ionospheric correction and phase gradients are outside this compact processor; keep both at 0.',
         'correct_iono compute_phase_gradient'))
    text = ('# Example configuration for p2p_gslc.csh and p2p_gslc.py: NSR_'+band+'\n'
            '# Use parameter = value; comments start with #. Blank values follow the notes below.\n'
            '# Keep parameter names unchanged and list each parameter only once.\n')
    for title, notes, keys in sections:
        text += '\n'+'#'*72+'\n# '+title+'\n'+'#'*72+'\n'
        text += ''.join('# '+line+'\n' for line in notes.splitlines())
        text += ''.join(f'{key} = {values[key]}\n' for key in keys.split())
    return text


def configuration(path, band):
    defaults = {**DEFAULTS, 'filter_wavelength': '160' if band == 'A' else '640'}
    if path is None:
        path = Path(f'config_NSR_GSLC_{band}.txt')
        if not path.exists():
            path.write_text(configuration_text(band))
    values = {}
    for number, line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
        text = line.split('#', 1)[0].strip()
        if not text: continue
        require('=' in text, f'{path}:{number}: expected key = value')
        key, value = map(str.strip, text.split('=', 1))
        require(key not in values, f'{path}:{number}: duplicate parameter {key}')
        require(key in defaults or key in EXTENSIONS or key in RADAR_KEYS, f'Unknown parameter: {key}')
        values[key] = value
    cfg = {**defaults, **EXTENSIONS}
    cfg.update({k: v for k, v in values.items() if v or k in RADAR_KEYS})
    for key in ('correct_iono', 'compute_phase_gradient', 'geometric_coreg', 'switch_land'):
        require(float(cfg.get(key) or 0) == 0, f'{key} is not supported by this compact GSLC processor')
    for key in ('region_cut', 'range_dec', 'azimuth_dec'):
        require(not cfg.get(key), f'{key} uses radar coordinates; use gslc_region/spacing_x/spacing_y instead')
    return cfg, path.resolve()


class Product:
    """North-up metre-based GSLC, including complex16 and known legacy B masks."""
    def __init__(self, h5, band, pol):
        self.h5, self.pol = h5, pol
        root = '/science/LSAR/GSLC'
        group = h5[f'{root}/grids/frequency{band}']
        self.data = group[pol]
        self.x, self.y = group['xCoordinates'][:], group['yCoordinates'][:]
        self.dx, self.dy = float(self.x[1]-self.x[0]), float(self.y[1]-self.y[0])
        require(self.dx > 0 and self.dy < 0 and all(np.allclose(np.diff(a), d) for a, d in
                ((self.x, self.dx), (self.y, self.dy))), 'Expected a regular north-up GSLC grid')
        require(self.data.shape == (len(self.y), len(self.x)), 'Complex data/grid shape mismatch')
        self.crs = CRS.from_epsg(int(group['projection'][()]))
        require(self.crs.is_projected and all(abs(a.unit_conversion_factor-1) < 1e-10
                for a in self.crs.axis_info), 'GSLC CRS must be projected in metres')
        self.frequency = float(group['centerFrequency'][()])
        require(np.isfinite(self.frequency) and self.frequency > 0, 'Invalid centerFrequency')
        ident = h5['/science/LSAR/identification']
        self.meta = {k: scalar(ident[k][()]) for k in ('productType', 'isGeocoded', 'trackNumber',
            'frameNumber', 'orbitPassDirection', 'lookDirection', 'zeroDopplerStartTime')}
        require(self.meta['productType'] == 'GSLC' and str(self.meta['isGeocoded']).lower()
                in ('true', '1'), 'Input must be an identified geocoded GSLC product')
        for key in ('ellipsoidalFlatteningApplied', 'topographicFlatteningApplied'):
            flag = scalar(h5[f'{root}/metadata/processingInformation/parameters/{key}'][()])
            require(str(flag).lower() in ('true', '1'), f'{key} must be true')
        dem = f'{root}/metadata/processingInformation/inputs/demSource'
        self.dem = scalar(h5[dem][()]) if dem in h5 else None
        self.meta.update({k: scalar(ident[k][()]) if k in ident else None
                          for k in ('compositeReleaseId', 'productVersion', 'productSpecificationVersion')})
        self.mask, self.exception = group.get('mask'), group.get('inputDataExceptionMask')
        require(self.mask is None or self.mask.shape == self.data.shape, 'Invalid subswath mask grid')
        self.new_bits = self.exception is not None and 'validity mask bits' in str(
            scalar(self.exception.attrs.get('description', b''))).lower()
        require(self.exception is None or self.new_bits or self.exception.dtype == np.dtype('u1'),
                'Unknown multi-byte exception mask encoding')
        self.ratio = None
        if self.exception is not None and self.exception.shape != self.data.shape:
            require(band == 'B' and not self.new_bits and self.exception.dtype == np.dtype('u1'),
                    'Unknown inputDataExceptionMask grid')
            a = h5[f'{root}/grids/frequencyA']
            ax, ay = a['xCoordinates'][:], a['yCoordinates'][:]
            ratios = [self.dy/(ay[1]-ay[0]), self.dx/(ax[1]-ax[0])]
            require(all(n >= 1 and abs(n-round(n)) < 1e-6 for n in ratios), 'Invalid legacy mask ratios')
            self.ratio = tuple(round(n) for n in ratios)
            ry, rx = self.ratio
            require(self.exception.shape == (len(ay), len(ax)) == (len(self.y)*ry, len(self.x)*rx)
                    and int(a['projection'][()]) == self.crs.to_epsg()
                    and np.allclose([ax[0]-(ax[1]-ax[0])/2, ax[-1]+(ax[1]-ax[0])/2,
                                     ay[0]-(ay[1]-ay[0])/2, ay[-1]+(ay[1]-ay[0])/2],
                                    [self.x[0]-self.dx/2, self.x[-1]+self.dx/2,
                                     self.y[0]-self.dy/2, self.y[-1]+self.dy/2], rtol=0, atol=1e-5),
                    'Legacy B quality mask does not match the A/B pixel footprints')
        typ = self.data.id.get_type()
        require(typ.get_class() == h5py.h5t.COMPOUND and typ.get_nmembers() == 2,
                'Input samples must be complex, not detected power')
        require(all(typ.get_member_type(i).get_class() == h5py.h5t.FLOAT for i in range(2)),
                'Complex components must be floating point')
        names = {typ.get_member_name(i).decode() for i in range(2)}
        self.fields = next((p for p in (('r', 'i'), ('real', 'imag'), ('real', 'imaginary'))
                            if set(p) == names), None)
        require(self.fields is not None, 'Unknown complex sample fields')

    def read(self, r, c, h, w):
        dtype = np.dtype([(name, 'f4') for name in self.fields])
        values = np.empty((h, w), dtype=dtype)
        space = self.data.id.get_space(); space.select_hyperslab((r, c), (h, w))
        self.data.id.read(h5py.h5s.create_simple((h, w)), space, values, mtype=h5py.h5t.py_create(dtype))
        z = values[self.fields[0]] + np.complex64(1j)*values[self.fields[1]]
        good = np.isfinite(z) & (abs(z) > 0)
        if self.mask is not None:
            m = self.mask[r:r+h, c:c+w]; good &= (m > 0) & (m < 255)
        if self.exception is not None:
            ry, rx = self.ratio or (1, 1)
            e = self.exception[r*ry:(r+h)*ry, c*rx:(c+w)*rx].astype('u4')
            if self.ratio:
                e = np.bitwise_or.reduce(np.bitwise_or.reduce(e.reshape(h, ry, w, rx), axis=3), axis=1)
            bit = 1 << (8 + ('HH', 'HV', 'VH', 'VV', 'LH', 'LV', 'RH', 'RV').index(self.pol))
            good &= ((e & 255) == 0) & ((e & bit) != 0) if self.new_bits else e == 0
        return np.where(good, z, 0), good


def grid(path, x, y, crs, unit='1'):
    ds = netCDF4.Dataset(path, 'w', format='NETCDF4_CLASSIC')
    ds.Conventions, ds.node_offset = 'CF-1.8', np.int32(1)
    ds.title = Path(path).stem
    for name, axis in (('x', x), ('y', y)):
        ds.createDimension(name, len(axis)); v = ds.createVariable(name, 'f8', (name,)); v[:] = axis
        v.units = ('degrees_east' if name == 'x' else 'degrees_north') if crs.is_geographic else 'm'
        v.standard_name = ('longitude' if name == 'x' else 'latitude') if crs.is_geographic else f'projection_{name}_coordinate'
        v.axis = name.upper(); half = abs(axis[1]-axis[0])/2
        v.actual_range = [min(axis)-half, max(axis)+half]
    projection = ds.createVariable('crs', 'i4'); projection.assignValue(0)
    projection.setncatts(crs.to_cf()); projection.spatial_ref = crs.to_wkt()
    projection.GeoTransform = f'{x[0]-(x[1]-x[0])/2} {x[1]-x[0]} 0 {y[0]-(y[1]-y[0])/2} 0 {y[1]-y[0]}'
    z = ds.createVariable('z', 'f4', ('y', 'x'), fill_value=np.float32(np.nan), zlib=True, complevel=2)
    z.units, z.grid_mapping = unit, 'crs'
    return ds


def read_grid(path):
    with netCDF4.Dataset(path) as ds:
        ds.set_auto_mask(False)
        data, x, y = ds['z'][:], ds['x'][:], ds['y'][:]
    if y[0] < y[-1]: data, y = data[::-1], y[::-1]
    if x[0] > x[-1]: data, x = data[:, ::-1], x[::-1]
    return data, x, y


def identity(paths):
    return {str(p): [p.stat().st_size, p.stat().st_mtime_ns] for p in paths}


def form(a, b, cfg, out):
    wavelength, dec = float(cfg['filter_wavelength']), int(cfg['dec_factor'])
    require(np.isfinite(wavelength) and (wavelength == 0 or 2 <= wavelength <= 10000)
            and dec in (1, 2, 4), 'Invalid filter_wavelength or dec_factor')
    spacing = [cfg['gslc_spacing_y'], cfg['gslc_spacing_x']]
    require(bool(spacing[0]) == bool(spacing[1]), 'Set both gslc_spacing_x and gslc_spacing_y')
    ratios = [float(s)/d if s else dec*max(1, math.floor(wavelength/10.6/d))
              for s, d in zip(spacing, (-a.dy, a.dx))]
    require(all(np.isfinite(n) and n >= 1 and abs(n-round(n)) < 1e-6 for n in ratios),
            'Output spacing must be an integer multiple of native spacing')
    ly, lx = (round(n) for n in ratios)
    offsets = [(a.y[0]-b.y[0])/a.dy, (a.x[0]-b.x[0])/a.dx]
    require(np.allclose(offsets, np.rint(offsets), atol=1e-5, rtol=0), 'Fractional grid offset needs coregistration')
    ro, co = map(lambda n: int(round(n)), offsets)
    r0, c0 = max(0, -ro), max(0, -co)
    r1, c1 = min(len(a.y), len(b.y)-ro), min(len(a.x), len(b.x)-co)
    if cfg['gslc_region']:
        xmin, xmax, ymin, ymax = map(float, cfg['gslc_region'].split('/'))
        require(xmin < xmax and ymin < ymax, 'gslc_region must be XMIN/XMAX/YMIN/YMAX in metres')
        r0, r1 = max(r0, np.searchsorted(-a.y, -ymax)), min(r1, np.searchsorted(-a.y, -ymin, side='right'))
        c0, c1 = max(c0, np.searchsorted(a.x, xmin)), min(c1, np.searchsorted(a.x, xmax, side='right'))
    r1, c1 = r0+(r1-r0)//ly*ly, c0+(c1-c0)//lx*lx
    require(r1-r0 >= 2*ly and c1-c0 >= 2*lx, 'Common region is smaller than two output pixels')
    x = a.x[c0:c1].reshape(-1, lx).mean(1); y = a.y[r0:r1].reshape(-1, ly).mean(1)
    def kernel(d, stride):
        if wavelength == 0: return np.ones(stride)/stride
        sigma = wavelength/5.3/d; n = int(4*sigma); n += 1 if n % 2 == 0 else 0
        n += stride % 2 == 0
        power = -0.5*((np.arange(n)-(n-1)/2)/sigma)**2
        weights = np.exp(power-power.max()); return weights/weights.sum()
    ky, kx = kernel(-a.dy, ly), kernel(a.dx, lx)
    names = ('realfilt', 'imagfilt', 'amp1', 'amp2', 'phase', 'corr', 'mask', 'display_amp')
    fraction = float(cfg['gslc_min_valid_fraction'])
    require(0 < fraction <= 1, 'gslc_min_valid_fraction must be in (0,1]')
    LOG.info('Output %d x %d, spacing %.3f x %.3f m', len(y), len(x), a.dx*lx, -a.dy*ly)
    with ExitStack() as stack:
        writers = {n: stack.enter_context(grid(out/(n+'.grd'), x, y, a.crs,
                   'radian' if n == 'phase' else '1')) for n in names}
        for row in range(0, len(y), 128):
            for col in range(0, len(x), 128):
                h, w = min(128, len(y)-row), min(128, len(x)-col)
                r, c = r0+row*ly, c0+col*lx
                ay, ax = r+np.arange(h)*ly+ly//2, c+np.arange(w)*lx+lx//2
                top, left = min(r, ay[0]-len(ky)//2), min(c, ax[0]-len(kx)//2)
                bottom, right = max(r+h*ly, ay[-1]+(len(ky)-1)//2+1), max(c+w*lx, ax[-1]+(len(kx)-1)//2+1)
                rr, cc = max(top, 0, -ro), max(left, 0, -co)
                rb, cb = min(bottom, len(a.y), len(b.y)-ro), min(right, len(a.x), len(b.x)-co)
                za, va = a.read(rr, cc, rb-rr, cb-cc); zb, vb = b.read(rr+ro, cc+co, rb-rr, cb-cc)
                padding = ((rr-top, bottom-rb), (cc-left, right-cb))
                valid = np.pad(va & vb, padding)
                cross = np.pad(np.where(va & vb, za*np.conj(zb), 0), padding)
                def sample(v):
                    q = np.lib.stride_tricks.sliding_window_view(v, len(kx), axis=1)
                    q = np.einsum('ijk,k->ij', q[:, ax-left-len(kx)//2, :], kx, dtype='f8')
                    q = np.lib.stride_tricks.sliding_window_view(q, len(ky), axis=0)
                    return np.einsum('ijk,k->ij', q[ay-top-len(ky)//2], ky, dtype='f8')
                support = sample(valid); divisor = np.maximum(support, np.finfo(float).tiny)
                z = (sample(cross.real)+1j*sample(cross.imag))/divisor
                powers = [sample(np.pad(np.where(va & vb, abs(v)**2, 0), padding))/divisor for v in (za, zb)]
                blocks = valid[r-top:r-top+h*ly, c-left:c-left+w*lx].reshape(h, ly, w, lx)
                good = (blocks.mean((1, 3)) >= fraction) & (support >= fraction-1e-12) & (powers[0]*powers[1] > 0)
                corr = np.divide(abs(z), np.sqrt(powers[0]*powers[1]), out=np.zeros_like(support), where=powers[0]*powers[1] > 0)
                values = (z.real, z.imag, *powers, np.angle(z), np.clip(corr, 0, 1), np.ones((h, w)), np.sqrt(abs(z)))
                for name, values in zip(names, values):
                    writers[name]['z'][row:row+h, col:col+w] = np.where(good, values, np.nan)
            LOG.info('Interferogram row %d/%d', min(row+128, len(y)), len(y))
    (out/'corr.grd').rename(out/'corr_gaussian.grd')
    with netCDF4.Dataset(out/'corr_gaussian.grd') as src, grid(out/'corr.grd', x, y, a.crs) as ds:
        weights = np.array([1., 2., 1.])/4
        smooth = lambda z: convolve1d(convolve1d(z, weights, axis=1, mode='constant'), weights, axis=0, mode='constant')
        for row in range(0, len(y), 256):
            top, bottom = max(0, row-1), min(len(y), row+257)
            original = src['z'][top:bottom].filled(np.nan); valid = np.isfinite(original)
            values = np.where(valid, smooth(np.nan_to_num(original))/np.maximum(smooth(valid.astype(float)), 1e-12), np.nan)
            ds['z'][row:min(row+256, len(y))] = values[row-top:row-top+min(256, len(y)-row)]
    return x, y, [ly, lx]


def goldstein(out, cfg, x, y, crs):
    mode, alpha = cfg['gslc_goldstein_mode'], float(cfg['gslc_filter_alpha'])
    require(mode in ('coherence', 'fixed') and 0 <= alpha <= 1.5, 'Invalid Goldstein mode/alpha')
    with ExitStack() as stack:
        inputs = {n: stack.enter_context(netCDF4.Dataset(out/(n+'.grd'))) for n in ('realfilt', 'imagfilt', 'amp1', 'amp2', 'mask')}
        output = stack.enter_context(grid(out/'phasefilt.grd', x, y, crs, 'radian'))
        for row in range(0, len(y), 1024):
            for col in range(0, len(x), 1024):
                h, w = min(1024, len(y)-row), min(1024, len(x)-col)
                r, c = max(0, row-32), max(0, col-32)
                bottom, right = min(len(y), row+h+32), min(len(x), col+w+32)
                pad = ((32-row+r, row+h+32-bottom+(-h)%32), (32-col+c, col+w+32-right+(-w)%32))
                with tempfile.TemporaryDirectory(prefix='.goldstein_', dir=out) as tmp:
                    tmp = Path(tmp)
                    for src, dst in (('realfilt', 'real'), ('imagfilt', 'imag'), ('amp1', 'amp1'), ('amp2', 'amp2')):
                        data = np.pad(np.nan_to_num(inputs[src]['z'][r:bottom, c:right].filled(np.nan)), pad, mode='edge')
                        tx = x[0]+(col-32+np.arange(data.shape[1]))*(x[1]-x[0])
                        ty = y[0]+(row-32+np.arange(data.shape[0]))*(y[1]-y[0])
                        with grid(tmp/(dst+'.grd'), tx, ty, crs) as ds: ds['z'][:] = data
                    command = ['phasefilt', '-real', 'real.grd', '-imag', 'imag.grd', '-alpha', str(alpha), '-psize', '32']
                    if mode == 'coherence': command += ['-amp1', 'amp1.grd', '-amp2', 'amp2.grd']
                    run(command, tmp, logfile=out/'phasefilt.log')
                    filtered, _, _ = read_grid(tmp/'filtphase.grd')
                    mask = inputs['mask']['z'][row:row+h, col:col+w].filled(np.nan)
                    output['z'][row:row+h, col:col+w] = np.where(np.isfinite(mask), filtered[32:32+h, 32:32+w], np.nan)


def unwrap(out, cfg, x, y, crs, wavelength, looks):
    threshold = float(cfg['threshold_snaphu'])
    require(not (out/'unwrap.grd').exists(), 'unwrap.grd already exists; move old unwrap/LOS before rerunning stage 5')
    phase, _, _ = read_grid(out/'phasefilt.grd'); corr, _, _ = read_grid(out/'corr.grd')
    good = np.isfinite(phase) & np.isfinite(corr) & (corr >= threshold)
    land = next((p for p in (out/'landmask.grd', Path('landmask.grd')) if p.is_file()), None)
    if int(cfg['mask_water']):
        if land:
            mask, mx, my = read_grid(land)
            require(np.array_equal(mx, x) and np.array_equal(my, y), 'landmask.grd must match the GSLC output grid')
            good &= np.isfinite(mask) & (mask > 0)
        else: LOG.warning('mask_water=1 but no map-grid landmask.grd supplied; only GSLC validity/coherence masking is applied')
    require(good.sum() >= 16, 'Fewer than 16 reliable unwrap pixels')
    near = int(cfg['near_interp']) == 1
    if near: phase = phase[tuple(distance_transform_edt(~good, return_distances=False, return_indices=True))]
    tiles = [int(cfg[k]) or math.ceil(n/2500) for k, n in zip(('gslc_unwrap_tiles_y', 'gslc_unwrap_tiles_x'), phase.shape)]
    require(min(tiles) > 0, 'SNAPHU tile counts must be positive or 0 (automatic)')
    overlap = [512 if n > 1 else 0 for n in tiles]
    tile_shape = [math.ceil((s+(n-1)*o)/n) for s, n, o in zip(phase.shape, tiles, overlap)]
    last = [s-(n-1)*(t-o) for s, n, t, o in zip(phase.shape, tiles, tile_shape, overlap)]
    require(min(last) >= 2 and all(o < t for o, t in zip(overlap, tile_shape)) and math.prod(tile_shape) <= 16000000,
            'Invalid or excessive SNAPHU tile size; adjust gslc_unwrap_tiles_y/x')
    effective = float(cfg['gslc_effective_looks'] or math.prod(looks))
    require(np.isfinite(effective) and effective >= 1, 'gslc_effective_looks must be finite and >= 1')
    LOG.warning('SNAPHU effective looks %.3g are provisional, not measured independent looks', effective)
    with tempfile.TemporaryDirectory(prefix='.snaphu_', dir=out) as tmp:
        tmp = Path(tmp)
        np.where(good | near, phase, 0).astype('=f4').tofile(tmp/'phase.bin')
        np.where(good, corr, 0).astype('=f4').tofile(tmp/'corr.bin')
        (np.ones_like(good) if near else good).astype('i1').tofile(tmp/'mask.bin')
        (tmp/'snaphu.conf').write_text('INFILEFORMAT FLOAT_DATA\nOUTFILEFORMAT FLOAT_DATA\nCORRFILEFORMAT FLOAT_DATA\n'
            'BYTEMASKFILE mask.bin\nCONNCOMPOUTTYPE UINT\nMINCONNCOMPFRAC 0.001\nMAXNCOMPS 1000\n'
            f'LAMBDA {wavelength}\nNCORRLOOKS {effective}\nDEFOMAX_CYCLE {cfg["defomax"]}\n')
        command = ['snaphu', 'phase.bin', str(len(x)), '-f', 'snaphu.conf', '-c', 'corr.bin',
                   '-o', 'unwrap.bin', '-g', 'conncomp.bin', '-s' if float(cfg['defomax']) == 0 else '-d']
        if math.prod(tiles) > 1:
            command += ['--tile', *map(str, tiles), *map(str, overlap), '--nproc', cfg['gslc_unwrap_nproc'], '--tiledir', 'tiles']
        shutil.copy2(tmp/'snaphu.conf', out/'snaphu.conf')
        run(command, tmp, logfile=out/'snaphu.log')
        require((tmp/'unwrap.bin').stat().st_size == phase.size*4 and
                (tmp/'conncomp.bin').stat().st_size == phase.size*4, 'Unexpected SNAPHU output size')
        values = np.fromfile(tmp/'unwrap.bin', dtype='=f4').reshape(phase.shape)
        labels = np.fromfile(tmp/'conncomp.bin', dtype='=u4').reshape(phase.shape)
        accepted = good & (labels > 0) & np.isfinite(values)
        for name, data, unit in (('unwrap', values, 'radian'), ('conncomp', labels, '1'), ('los', -wavelength/(4*np.pi)*values, 'm')):
            with grid(out/(name+'.grd'), x, y, crs, unit) as ds: ds['z'][:] = np.where(accepted, data, np.nan if name != 'conncomp' else 0)
    if math.prod(tiles) > 1: LOG.warning('SNAPHU component labels are tile-local; inspect assembled phase continuity')


def geographic(out, cfg, crs):
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.vrt import WarpedVRT
    from rasterio.windows import Window
    target = out/'lonlat'
    require(not target.exists(), 'lonlat/ already exists; move it before rerunning stage 6')
    target.mkdir()
    with rasterio.Env(GDAL_CACHEMAX=64*1024*1024), ExitStack() as stack:
        corr = stack.enter_context(rasterio.open(out/'corr.grd'))
        reference = stack.enter_context(WarpedVRT(corr, crs='EPSG:4326', resampling=Resampling.nearest, nodata=np.nan))
        t = reference.transform
        x = t.c+(np.arange(reference.width)+.5)*t.a; y = t.f+(np.arange(reference.height)+.5)*t.e
        for name in (*LAYERS, 'mask', 'conncomp'):
            source = out/(name+'.grd')
            if not source.exists(): continue
            with rasterio.open(source) as src, WarpedVRT(src, crs='EPSG:4326', width=len(x), height=len(y),
                    transform=t, resampling=Resampling.nearest, nodata=np.nan) as vrt:
                with grid(target/(name+'_ll.grd'), x, y, CRS.from_epsg(4326), 'm' if name == 'los' else
                          'radian' if name in ('phase', 'phasefilt', 'unwrap') else '1') as ds:
                    for row in range(0, len(y), 256):
                        window = Window(0, row, len(x), min(256, len(y)-row))
                        data = vrt.read(1, window=window, masked=True).filled(np.nan)
                        coherence = reference.read(1, window=window, masked=True).filled(np.nan)
                        if name not in ('corr', 'mask', 'conncomp'):
                            data = np.where(coherence >= float(cfg['threshold_geocode']), data, np.nan)
                        ds['z'][row:row+len(data)] = data


def figures(out, geographic=False):
    out = Path(out).resolve()
    suffix = '_ll' if geographic else ''
    with tempfile.TemporaryDirectory(prefix='.gmt_', dir=out) as tmp:
        tool_dir = str(Path(shutil.which('gmt')).resolve().parent)
        env = {**os.environ, 'GMT_USERDIR': tmp, 'GMT_SESSION_NAME': str(os.getpid()),
               'PATH': tool_dir+os.pathsep+os.environ.get('PATH', '')}
        if not (Path(tool_dir)/'gs').is_file(): env.pop('GS_LIB', None)
        for name in LAYERS:
            source, pdf = out/(name+suffix+'.grd'), out/(name+suffix+'.pdf')
            if not source.exists() or pdf.exists(): continue
            data, x, y = read_grid(source); finite = data[np.isfinite(data)]
            if not finite.size: continue
            if name == 'los':
                with netCDF4.Dataset(source) as ds: crs = CRS.from_wkt(ds['crs'].spatial_ref)
                source = Path(tmp)/'los_mm.grd'
                with grid(source, x, y, crs, 'mm') as ds: ds['z'][:] = data*1000
                finite = finite*1000
            palette = ['-Crainbow', '-T-3.15/3.15'] if name in ('phase', 'phasefilt') else ['-Cgray', '-T0/1'] if name == 'corr' else ['-Cpolar']
            if name not in ('phase', 'phasefilt', 'corr'):
                lo, hi = np.quantile(finite, [.02, .98]); palette += [f'-T{lo if hi > lo else lo-1}/{hi if hi > lo else hi+1}']
            aspect = abs(len(y)*(y[1]-y[0])/(len(x)*(x[1]-x[0])))
            width = min(15, 20/aspect)
            projection = '-JM15c' if geographic else f'-JX{width:g}c/{width*aspect:g}c'
            axes = ['-Bxa', '-Bya'] if geographic else ['-Bxaf+lEasting (m)', '-Byaf+lNorthing (m)']
            for command in (['gmt', 'begin', pdf.stem, 'pdf', 'A+m0.2c'],
                            ['gmt', 'set', 'MAP_FRAME_TYPE', 'plain', 'COLOR_NAN', 'white', 'FORMAT_GEO_MAP', 'ddd.xxxxF', 'FONT_TITLE', '12p', 'FONT_LABEL', '10p'],
                            ['gmt', 'makecpt', *palette, '-Z', '-D'],
                            ['gmt', 'grdimage', str(source), projection, *axes, '-BWSen+t'+name+suffix, '-nn+a'],
                            ['gmt', 'colorbar', '-DJBC+w12c/0.3c+o0c/1.2c+h', '-Baf+l'+('LOS (mm)' if name == 'los' else 'Coherence' if name == 'corr' else 'Phase (rad)' if name != 'display_amp' else 'Amplitude')],
                            ['gmt', 'end']):
                run(command, out, env)


def main():
    example = ('python p2p_gslc.py NSR_A '
               'NISAR_L2_PR_GSLC_033_112_A_018_2005_DHDH_M_20261019T225848_20261019T225923_P05023_N_F_J_001.h5 '
               'NISAR_L2_PR_GSLC_034_112_A_018_2005_DHDH_M_20261031T225848_20261031T225923_P05036_N_F_J_001.h5')
    parser = argparse.ArgumentParser(description=__doc__, add_help=False,
        usage='%(prog)s NSR_A|NSR_B master_image aligned_image [configuration_file]',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f'Example:\n  {example}\n\nPreparation:\n'
               '  Put the two NISAR GSLC .h5 files in raw/ and run from its parent directory.\n'
               '  Flattened GSLC products need no separate orbit or DEM files.\n'
               '  Install requirements.txt.\n\n'
               'Configuration:\n'
               '  Without a configuration argument, use config_NSR_GSLC_A.txt or config_NSR_GSLC_B.txt;\n'
               '  create it with defaults if absent, then continue processing.\n\n'
               'Author: Xin Wang, USTC Contact: xinw11@mail.ustc.edu.cn Date: 2026-11-16')
    parser.add_argument('-h', '--help', action='help', help=argparse.SUPPRESS)
    parser.add_argument('satellite', choices=('NSR_A', 'NSR_B'), help=argparse.SUPPRESS)
    parser.add_argument('master_image', help=argparse.SUPPRESS)
    parser.add_argument('aligned_image', help=argparse.SUPPRESS)
    parser.add_argument('configuration_file', nargs='?', type=Path, help=argparse.SUPPRESS)
    if len(sys.argv) == 1:
        parser.print_help()
        return 0
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    try:
        band = args.satellite[-1]; cfg, conf = configuration(args.configuration_file, band)
        stage = int(cfg['proc_stage']); skip = {int(s) for s in cfg['skip_stage'].split(',') if s.strip()}
        require(1 <= stage <= 6 and all(1 <= s <= 6 for s in skip), 'Stages must be 1..6')
        require(int(cfg['switch_master']) in (0, 1), 'switch_master must be 0 or 1')
        for key in ('threshold_snaphu', 'threshold_geocode'):
            require(math.isfinite(float(cfg[key])) and 0 <= float(cfg[key]) <= 1, f'{key} must be in [0,1]')
        require(math.isfinite(float(cfg['defomax'])) and float(cfg['defomax']) >= 0
                and int(cfg['gslc_unwrap_nproc']) > 0, 'Invalid defomax or worker count')
        require(all(int(cfg[k]) in (0, 1) for k in ('mask_water', 'near_interp', 'gslc_plot')), 'Mask/interpolation/plot flags must be 0 or 1')
        for tool in (['phasefilt'] if stage <= 4 and 4 not in skip else []) + (['snaphu'] if stage <= 5 and 5 not in skip and float(cfg['threshold_snaphu']) else []) + (['gmt', 'gs'] if int(cfg['gslc_plot']) else []):
            require(shutil.which(tool) is not None, f'Cannot find {tool} on PATH')
        if stage <= 6 and 6 not in skip and float(cfg['threshold_geocode']):
            import rasterio
            rasterio.crs.CRS.from_epsg(4326)
        def locate(name):
            paths = [Path(name), Path('raw')/name]
            paths += [Path(str(p)+'.h5') for p in paths if p.suffix != '.h5']
            found = next((p.resolve() for p in paths if p.is_file()), None)
            require(found is not None, f'Cannot find GSLC input {name}; put it in raw/')
            return found
        paths = [locate(args.master_image), locate(args.aligned_image)]
        require(paths[0] != paths[1], 'The two acquisitions must differ')
        if int(cfg['switch_master']): paths.reverse()
        with h5py.File(paths[0], 'r') as ha, h5py.File(paths[1], 'r') as hb:
            a, b = [Product(f, band, cfg['gslc_polarization']) for f in (ha, hb)]
            require(a.crs == b.crs and np.allclose([a.dx, a.dy, a.frequency], [b.dx, b.dy, b.frequency], rtol=1e-8),
                    'Incompatible CRS, spacing or center frequency')
            require(all(a.meta[k] == b.meta[k] for k in ('trackNumber', 'frameNumber', 'orbitPassDirection', 'lookDirection')), 'Incompatible observation geometry')
            if a.dem != b.dem or a.dem is None: LOG.warning('Different or missing flattening DEM versions: residual phase may remain')
            if any(a.meta[k] != b.meta[k] for k in ('compositeReleaseId', 'productVersion', 'productSpecificationVersion')):
                LOG.warning('Different GSLC processing versions; evaluate residual effects')
            LOG.warning('Map-grid matching is not a precision coregistration or scientific validation')
            days = [datetime.fromisoformat(p.meta['zeroDopplerStartTime'][:19]).strftime('%Y%j') for p in (a, b)]
            require(days[0] != days[1], 'Use two different acquisition dates')
            out = Path('intf')/('_'.join(days)); report_path = out/'p2p_gslc.json'
            signature = {k: cfg[k] for k in ('switch_master', 'filter_wavelength', 'dec_factor', *EXTENSIONS)
                         if k not in ('gslc_plot', 'gslc_unwrap_tiles_y', 'gslc_unwrap_tiles_x', 'gslc_unwrap_nproc', 'gslc_effective_looks')}
            if stage <= 4 and 4 not in skip:
                require(not out.exists() or not any(out.iterdir()), f'Existing pair directory: {out}; use proc_stage=5/6 to continue')
                out.mkdir(parents=True, exist_ok=True)
                report = dict(status='running', band=band, config=str(conf), signature=signature, inputs=identity(paths),
                              phase_convention='reference * conjugate(secondary)', epsg=a.crs.to_epsg(),
                              products=[a.meta, b.meta], flattening_dem=[a.dem, b.dem])
                report_path.write_text(json.dumps(report, indent=2))
                x, y, looks = form(a, b, cfg, out)
                goldstein(out, cfg, x, y, a.crs)
                report.update(status='filtered', looks_yx=looks)
                report_path.write_text(json.dumps(report, indent=2))
            else:
                report = json.loads(report_path.read_text())
                require(report['band'] == band and report['signature'] == signature and report['inputs'] == identity(paths),
                        'Inputs or filtering parameters differ from the saved interferogram')
                require(report['status'] in ('filtered', 'complete'), 'Interferogram is incomplete')
                _, x, y = read_grid(out/'phasefilt.grd'); looks = report['looks_yx']
            if stage <= 5 and 5 not in skip and float(cfg['threshold_snaphu']):
                unwrap(out, cfg, x, y, a.crs, C/a.frequency, looks)
                report['unwrap_parameters'] = {k: cfg[k] for k in ('threshold_snaphu', 'defomax', 'near_interp',
                    'mask_water', 'gslc_unwrap_tiles_y', 'gslc_unwrap_tiles_x', 'gslc_unwrap_nproc', 'gslc_effective_looks')}
            if stage <= 6 and 6 not in skip and float(cfg['threshold_geocode']):
                geographic(out, cfg, a.crs)
            if int(cfg['gslc_plot']):
                figures(out)
                if (out/'lonlat').exists(): figures(out/'lonlat', True)
            report.update(status='complete', configuration_used=cfg)
            report_path.write_text(json.dumps(report, indent=2))
            print(f'Complete: {out.resolve()}')
        return 0
    except (ValueError, KeyError, OSError, TypeError, ImportError, subprocess.CalledProcessError) as exc:
        LOG.error('%s', exc); return 1


if __name__ == '__main__':
    raise SystemExit(main())
