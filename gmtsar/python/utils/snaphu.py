#! /usr/bin/env python3
"""
# snaphu.py is part of GMTSAR.
# This Python script is migrated from snaphu.csh by Dunyu Liu on 20231109.
# snaphu.csh was originally written by X on X.
#
# Purpose: to unwrap the phase.
#
# Module surface:
#   snaphu()                  — legacy CLI wrapper (preserved unchanged).
#   snaphu_unwrap(...)        — native Python entry mirroring snaphu.csh.
#   snaphu_interp_unwrap(...) — native Python entry mirroring snaphu_interp.csh.
#
# Both *_unwrap functions are thin orchestrators around the third-party
# `snaphu` C binary (Chen & Zebker 2000). They mirror their csh wrappers
# step-for-step — same gmt grdmath / grd2xyz / xyz2grd / snaphu invocations,
# same intermediate filenames, same cleanup. Byte-identical output to the
# csh side is the success criterion (the unwrap.grd / conncomp.grd / unwrap.pdf
# triple).
"""

import sys, os, re, configparser
import subprocess, glob, shutil
from gmtsar_lib import *
from grdsample_wrapper import grdsample as _grdsample_inproc
from xyz2grd_wrapper import xyz2grd_file as _xyz2grd_file

# Mira (2026-05-22): in-process gmt grdcut wrapper (utils/grdcut_wrapper.py).
# Default ON per Rule 10 carve-out (byte-id to gmt C + 3.3× faster file→file).
# Set GMTSAR_GRDCUT_PY=0 to fall back to the gmt subprocess for A/B parity
# debugging.
try:
    from grdcut_wrapper import grdcut_file as _grdcut_file
    _HAVE_GRDCUT_PY = True
except ImportError as _e:
    print(f"SNAPHU: WARN: grdcut_wrapper import failed ({_e}); "
          "using gmt subprocess.", file=sys.stderr)
    _HAVE_GRDCUT_PY = False


def _grdcut(in_grd: str, out_grd: str, region) -> None:
    """Cut ``in_grd`` to ``region`` → ``out_grd``. Honours
    GMTSAR_GRDCUT_PY (default ON via wrapper; subprocess fallback)."""
    if _HAVE_GRDCUT_PY:
        _grdcut_file(in_grd, out_grd, region=region)
    else:
        run(f'gmt grdcut {in_grd} -R{region} -G{out_grd}')


# ---------------------------------------------------------------------------
# Native Python entry points (called from utils/p2p_stages.py)
# ---------------------------------------------------------------------------
#
# These mirror snaphu.csh / snaphu_interp.csh. They operate in cwd (which must
# contain mask.grd, corr.grd, phasefilt.grd, just like the csh wrappers
# expect). They produce the same outputs (unwrap.grd, conncomp.grd, unwrap.pdf)
# in cwd.
#
# Difference between the two:
#   snaphu_unwrap         — direct: phase_patch.grd → grd2xyz → snaphu
#   snaphu_interp_unwrap  — fills low-coherence holes via `nearest_grid` first
#                           (helps snaphu over big vacant areas), and the
#                           landmask resample path uses -R<grid_info> instead
#                           of -R<phase_patch.grd> for the no-region branch.


def snaphu_unwrap(threshold_snaphu, defomax, region=None):
    """Single-tile snaphu unwrap. Mirrors gmtsar/csh/snaphu.csh.

    Args:
        threshold_snaphu : correlation threshold (csh arg $1). Pixels with
            corr < threshold are masked out (set to 0 in corr_tmp.grd → NaN
            in mask2_patch.grd). Use a float-castable value (e.g. .14).
        defomax          : maximum phase discontinuity in cycles (csh arg $2).
            0 → continuous-phase unwrap (-s, smooth); >0 → enables phase jumps
            (-d, defomax mode) with DEFOMAX_CYCLE patched into a local
            snaphu.conf.brief copy.
        region           : optional `<rng0>/<rngf>/<azi0>/<azif>` GMT -R region
            (csh arg $3). None → operate on the full grids.

    Returns:
        absolute path to the unwrap.grd produced in cwd.
    """
    return _snaphu_run(interp=0, threshold=str(threshold_snaphu),
                       defomax=str(defomax), region=region)


def snaphu_interp_unwrap(threshold_snaphu, defomax, region=None):
    """Interpolated snaphu unwrap. Mirrors gmtsar/csh/snaphu_interp.csh.

    Same args / return as snaphu_unwrap. Adds a `nearest_grid` step that
    fills holes in phase_patch.grd before snaphu sees it, and uses the
    grdinfo-derived increments (not the grid handle) for the no-region
    landmask resample — preserving the one byte-level difference from
    snaphu.csh.
    """
    return _snaphu_run(interp=1, threshold=str(threshold_snaphu),
                       defomax=str(defomax), region=region)


def _phase_patch_inc():
    """Return (x_inc, y_inc, node_offset) of phase_patch.grd in cwd.

    Mirrors `gmt grdinfo -I phase_patch.grd` for the wire-in path. Used
    by the landmask resample sites that previously read the gmt subprocess
    output and embedded it as a CLI string.
    """
    from gmt_grd_io import read_gmt_grd
    _d, x, y, info = read_gmt_grd('phase_patch.grd')
    dx = float(x[1] - x[0]) if len(x) > 1 else 0.0
    dy = float(y[1] - y[0]) if len(y) > 1 else 0.0
    return dx, dy, int(info.get('node_offset', 0))


def _snaphu_run(interp, threshold, defomax, region):
    """Shared core for snaphu_unwrap / snaphu_interp_unwrap.

    The two csh wrappers diverge in exactly three spots:
      (1) interpolation: snaphu_interp.csh runs `nearest_grid phase_tmp.grd ...`
          to fill low-coherence holes; snaphu.csh does not.
      (2) no-region landmask resample: snaphu.csh uses
          `-Rphase_patch.grd`, snaphu_interp.csh uses the grdinfo-derived `-I`
          increments instead.
      (3) cleanup tail: snaphu_interp.csh renames phase_patch.grd to
          phasefilt_interp.grd; snaphu.csh leaves it.
    Everything else is identical.

    Side effects: writes/removes intermediate grids in cwd (mask_patch.grd,
    corr_patch.grd, phase_patch.grd, mask2_patch.grd, corr_tmp.grd,
    phase.in, corr.in, unwrap.out, conncomp.out, tmp.grd, unwrap.grd,
    conncomp.grd, unwrap_grad.grd, unwrap.cpt, unwrap.ps, unwrap.pdf).
    """
    V = '-V'

    # --- prepare files (csh: gmt grdcut/ln -s mask/corr/phase) ----------
    if region is not None:
        # Mira (2026-05-22): in-process grdcut.
        _grdcut('mask.grd',       'mask_patch.grd',  region)
        _grdcut('corr.grd',       'corr_patch.grd',  region)
        _grdcut('phasefilt.grd',  'phase_patch.grd', region)
    else:
        file_shuttle('mask.grd', 'mask_patch.grd', 'link')
        file_shuttle('corr.grd', 'corr_patch.grd', 'link')
        file_shuttle('phasefilt.grd', 'phase_patch.grd', 'link')

    # --- landmask --------------------------------------------------------
    if check_file_report('landmask_ra.grd') is True:
        # GMTSAR_GRDSAMPLE_PY default ON since Mira #65: the @njit
        # per-pixel gather kernel makes the port byte-id AND 2.25×
        # faster than gmt C on the ALOS_haiti landmask (9.77M cells,
        # 38% NaN). Set GMTSAR_GRDSAMPLE_PY=0 to force the subprocess
        # fallback (A/B parity debugging only).
        # Default interp=bicubic matches gmt grdsample CLI default (-nc).
        if region is not None:
            # csh: gmt grdsample landmask_ra.grd -R<region> -I<inc(phase)> -G...
            dx_phase, dy_phase, _ = _phase_patch_inc()
            r = [float(v) for v in region.split('/')]
            _grdsample_inproc('landmask_ra.grd', 'landmask_ra_patch.grd',
                              region=(r[0], r[1], r[2], r[3]),
                              x_inc=dx_phase, y_inc=dy_phase)
        else:
            # Divergence (2): snaphu.csh uses -Rphase_patch.grd; snaphu_interp.csh
            # uses the grdinfo-derived `-I dx/dy` instead. Preserve both.
            if interp == 0:
                # csh: gmt grdsample landmask_ra.grd -Rphase_patch.grd -G...
                _grdsample_inproc('landmask_ra.grd', 'landmask_ra_patch.grd',
                                  ref_grd='phase_patch.grd')
            else:
                # csh: gmt grdsample landmask_ra.grd -I<inc(phase)> -G...
                dx_phase, dy_phase, _ = _phase_patch_inc()
                _grdsample_inproc('landmask_ra.grd', 'landmask_ra_patch.grd',
                                  x_inc=dx_phase, y_inc=dy_phase)
        run(f'gmt grdmath phase_patch.grd landmask_ra_patch.grd MUL = '
            f'phase_patch.grd {V}')

    # --- user-defined mask ----------------------------------------------
    if check_file_report('mask_def.grd') is True:
        if region is not None:
            # Mira (2026-05-22): in-process grdcut.
            _grdcut('mask_def.grd', 'mask_def_patch.grd', region)
        else:
            file_shuttle('mask_def.grd', 'mask_def_patch.grd', 'cp')
        run(f'gmt grdmath corr_patch.grd mask_def_patch.grd MUL = '
            f'corr_patch.grd {V}')

    # --- correlation threshold + mask composition -----------------------
    run(f'gmt grdmath corr_patch.grd {threshold} GE 0 NAN mask_patch.grd '
        f'MUL = mask2_patch.grd')
    run('gmt grdmath corr_patch.grd 0. XOR 1. MIN  = corr_patch.grd')
    run('gmt grdmath mask2_patch.grd corr_patch.grd MUL = corr_tmp.grd')

    # --- phase -> xyz (with optional nearest_grid fill for interp) ------
    if interp == 0:
        run('gmt grd2xyz phase_patch.grd -ZTLf -do0 > phase.in')
    else:
        run('gmt grdmath mask2_patch.grd phase_patch.grd MUL = phase_tmp.grd')
        run('nearest_grid phase_tmp.grd tmp.grd 300')
        file_shuttle('tmp.grd', 'phase_tmp.grd', 'mv')
        run('gmt grd2xyz phase_tmp.grd -ZTLf -do0 > phase.in')

    run('gmt grd2xyz corr_tmp.grd -ZTLf  -do0 > corr.in')

    # --- snaphu ----------------------------------------------------------
    sharedir = resolve_sharedir()
    par_tmp = catch_output_cmd(["gmt", "grdinfo", "-C", "phase_patch.grd"],
                               True, 10, -100000)

    if float(defomax) == 0:
        run(f'snaphu phase.in {par_tmp} '
            f'-f {sharedir}/snaphu/config/snaphu.conf.brief '
            f'-c corr.in -o unwrap.out -v -s -g conncomp.out')
    else:
        file_shuttle(f'{sharedir}/snaphu/config/snaphu.conf.brief',
                     'snaphu.conf.brief', 'cp')
        replace_strings('snaphu.conf.brief',
                        'DEFOMAX_CYCLE', f'DEFOMAX_CYCLE {defomax}')
        run(f'snaphu phase.in {par_tmp} -f snaphu.conf.brief '
            f'-c corr.in -o unwrap.out -v -d -g conncomp.out')

    # --- snaphu xyz -> grd ----------------------------------------------
    par1 = catch_output_cmd(["gmt", "grdinfo", "-I-", "phase_patch.grd"],
                            False, 0, -100000)
    par2 = catch_output_cmd(["gmt", "grdinfo", "-I", "phase_patch.grd"],
                            False, 0, -100000)
    # Mira #71 (2026-06-12): in-process gmt xyz2grd port (utils/gmt_xyz2grd_py.py).
    # Env-gated GMTSAR_XYZ2GRD_PY (default ON since v2.1.23; set =0 for subprocess fallback).
    _xyz2grd_file('unwrap.out', 'tmp.grd', par1=par1, par2=par2, ztype='f')
    _xyz2grd_file('conncomp.out', 'conncomp.grd', par1=par1, par2=par2, ztype='u')
    run('gmt grdmath tmp.grd mask2_patch.grd MUL = tmp.grd')
    file_shuttle('tmp.grd', 'unwrap.grd', 'mv')

    # --- post-mask -------------------------------------------------------
    if check_file_report('landmask_ra.grd') is True:
        run(f'gmt grdmath unwrap.grd landmask_ra_patch.grd MUL = tmp.grd {V}')
        file_shuttle('tmp.grd', 'unwrap.grd', 'mv')
    if check_file_report('mask_def.grd') is True:
        run(f'gmt grdmath unwrap.grd mask_def_patch.grd MUL = tmp.grd {V}')
        file_shuttle('tmp.grd', 'unwrap.grd', 'mv')

    # --- plot ------------------------------------------------------------
    run('gmt grdgradient unwrap.grd -Nt.9 -A0. -Gunwrap_grad.grd')
    tmp = catch_output_cmd(["gmt", "grdinfo", "-C", "-L2", "unwrap.grd"],
                           True, -999, -100000)
    limitU = round(float(tmp[11]) + float(tmp[12]) * 2., 1)
    limitL = round(float(tmp[11]) - float(tmp[12]) * 2., 1)
    run(f'gmt makecpt -Cseis -I -Z -T"{limitL}"/"{limitU}"/1 -D > unwrap.cpt')
    run('gmt grdimage unwrap.grd -Iunwrap_grad.grd -Cunwrap.cpt -JX6.5i '
        '-Bxaf+lRange -Byaf+lAzimuth -BWSen -X1.3i -Y3i -P -K > unwrap.ps')
    run('gmt psscale -Runwrap.grd -J -DJTC+w5/0.2+h+e -Cunwrap.cpt '
        '-Bxaf+l"Unwrapped phase" -By+lrad -O >> unwrap.ps')
    run('gmt psconvert -Tf -P -A -Z unwrap.ps')

    # --- cleanup ---------------------------------------------------------
    run('rm -f tmp.grd corr_tmp.grd unwrap.out tmp2.grd unwrap_grad.grd '
        'conncomp.out')
    run('rm -f phase.in corr.in')
    if interp == 1:
        run('rm -f phase_tmp.grd')
        # Divergence (3): snaphu_interp.csh renames phase_patch.grd to
        # phasefilt_interp.grd at this point. snaphu.csh does not.
        file_shuttle('phase_patch.grd', 'phasefilt_interp.grd', 'mv')

    if region is not None:
        file_shuttle('corr_patch.grd', 'corr_cut.grd', 'mv')
    run('rm -f mask_patch.grd mask3.grd mask3.out')
    run('rm -f corr_cut.grd corr_patch.grd')

    return os.path.abspath('unwrap.grd')


def snaphu():
    
    def Error_Message():
        print( "snaphu.py - unwrap the phase.")
        print( " if interp flag is invoked, unwrap the phase with nearest neighbor interpolating low coherence and blank pixels.")
        print( "Usage: snaphu.py correlation_threshold maximum_discontinuity interp [<rng0>/<rngf>/<azi0>/<azif>]")  
        print( " ")
        print( " correlation is reset to zero when < threshold ")
        print( " maximum_discontinuity enables phase jumps for earthquake ruptures, etc. ")
        print( " set maximum_discontinuity = 0 for continuous phase such as interseismic ")
        print( " interp=1, then calling nearest_grid to interpolate. ")
        print( " ")
        print( "Example: snaphu.py .12 40 1 1000/3000/24000/27000 ")
        print( "Reference: ")
        print( "Chen C. W. and H. A. Zebker, Network approaches to two-dimensional phase unwrapping: intractability and two new algorithms, Journal of the Optical Society of America A, vol. 17, pp. 401-414 (2000).")
        print( "Agram, P. S., & Zebker, H. A. (2009). Sparse two-dimensional phase unwrapping using regular-grid methods. IEEE Geoscience and Remote Sensing Letters, 6(2), 327-331.")
        
    print('SNAPHU - START ... ...')
    n = len(sys.argv)
    print('SNAPHU: input arguments are ', sys.argv)
    
    if n==1:
        print('SNAPHU: snaphu help information ... ...')
        Error_Message()
        sys.exit()
        
    if n<4:
        print('FILTER: Wrong # of input arguments; # should be larger than 3 ... ...')
        Error_Message()
    
    interp = int(sys.argv[3])
    if interp == 1:
        print('SNAPHU: interp is activated; unwrap the phase with nearest neighbor interpolating low coherence and blank pixels.')
    else: 
        print('SNAPHU: interp is NOT activated; unwrap the phase.')
        
    V = '-V'
    
    print('SNAPHU: prepare the files adding the correlation mask ... ...')
    if n==5:
        # Mira (2026-05-22): in-process grdcut.
        _grdcut('mask.grd',       'mask_patch.grd',  sys.argv[4])
        _grdcut('corr.grd',       'corr_patch.grd',  sys.argv[4])
        _grdcut('phasefilt.grd',  'phase_patch.grd', sys.argv[4])
    else:
        file_shuttle('mask.grd', 'mask_patch.grd', 'link')
        file_shuttle('corr.grd', 'corr_patch.grd', 'link')
        file_shuttle('phasefilt.grd', 'phase_patch.grd', 'link')
    
    print(' ')
    print('SNAPHU: ceate landmask ... ...')
    
    if check_file_report('landmask_ra.grd')==True:
        # GMTSAR_GRDSAMPLE_PY=1 opts into in-process port (default OFF;
        # see grdsample_wrapper.py docstring).
        if n==5:
            dx_phase, dy_phase, _ = _phase_patch_inc()
            r = [float(v) for v in sys.argv[4].split('/')]
            _grdsample_inproc('landmask_ra.grd', 'landmask_ra_patch.grd',
                              region=(r[0], r[1], r[2], r[3]),
                              x_inc=dx_phase, y_inc=dy_phase)
        else:
            if interp==0:
                _grdsample_inproc('landmask_ra.grd', 'landmask_ra_patch.grd',
                                  ref_grd='phase_patch.grd')
            elif interp==1:
                dx_phase, dy_phase, _ = _phase_patch_inc()
                _grdsample_inproc('landmask_ra.grd', 'landmask_ra_patch.grd',
                                  x_inc=dx_phase, y_inc=dy_phase)
        print(' ')
        run('gmt grdmath phase_patch.grd landmask_ra_patch.grd MUL = phase_patch.grd '+V)

    print(' ')
    print('SNAPHU: user defined mask ... ...')
    
    if check_file_report('mask_def.grd')==True:
        if n==5:
            # Mira (2026-05-22): in-process grdcut.
            _grdcut('mask_def.grd', 'mask_def_patch.grd', sys.argv[4])
        else:
            file_shuttle('mask_def.grd','mask_def_patch.grd','cp')
    
        print(' ')
        run('gmt grdmath corr_patch.grd mask_def_patch.grd MUL = corr_patch.grd '+V)

    
    run('gmt grdmath corr_patch.grd '+sys.argv[1]+' GE 0 NAN mask_patch.grd MUL = mask2_patch.grd')
    run('gmt grdmath corr_patch.grd 0. XOR 1. MIN  = corr_patch.grd')
    run('gmt grdmath mask2_patch.grd corr_patch.grd MUL = corr_tmp.grd') 
    
    if interp==0:
        run('gmt grd2xyz phase_patch.grd -ZTLf -do0 > phase.in')
    elif interp==1:
        run('gmt grdmath mask2_patch.grd phase_patch.grd MUL = phase_tmp.grd')
        run('nearest_grid phase_tmp.grd tmp.grd 300')
        file_shuttle('tmp.grd', 'phase_tmp.grd', 'mv')
        run('gmt grd2xyz phase_tmp.grd -ZTLf -do0 > phase.in')
    
    run('gmt grd2xyz corr_tmp.grd -ZTLf  -do0 > corr.in')
    
    print(' ')
    print('SNAPHU: run snaphu ... ...')
    
    sharedir = resolve_sharedir()
    print(' ')
    print('SNAPHU: unwrapping phase with snaphu - higher threshold for faster unwrapping ... ...')
    
    par_tmp = catch_output_cmd(["gmt","grdinfo","-C","phase_patch.grd"], True, 10, -100000)
    #par_tmp = subprocess.run(["gmt","grdinfo","-C","phase_patch.grd"], stdout=subprocess.PIPE).stdout.decode('utf-8').strip().split()[9]
    print('SNAPHU: output from gmt grdinfo -C phase_patch.grd | cut -f 10 is ', par_tmp)
    
    if float(sys.argv[2]) == 0:    
        run('snaphu phase.in '+par_tmp+' -f '+sharedir+'/snaphu/config/snaphu.conf.brief -c corr.in -o unwrap.out -v -s -g conncomp.out')
    else:
        print('SNAPHU: replacing the line containing DEFOMAX_CYCLE to DEFOMAX_CYCLE $2 from snaphu.conf.brief... ...')
        file_shuttle(sharedir+'/snaphu/config/snaphu.conf.brief','snaphu.conf.brief','cp')
        replace_strings('snaphu.conf.brief','DEFOMAX_CYCLE','DEFOMAX_CYCLE '+sys.argv[2])
        run('snaphu phase.in '+par_tmp+' -f snaphu.conf.brief -c corr.in -o unwrap.out -v -d -g conncomp.out')
    
    print(' ')
    print('SNAPHU: convert to grd ... ...')
    
    par1 = catch_output_cmd(["gmt","grdinfo","-I-","phase_patch.grd"],False,0,-100000)
    par2 = catch_output_cmd(["gmt","grdinfo","-I", "phase_patch.grd"],False,0,-100000)
    print('SNAPHU: output from gmt grdinfo -I- phase_patch.grd is', par1)
    print('SNAPHU: output from gmt grdinfo -I phase_patch.grd is', par2)
    
    # Mira #71 (2026-06-12): in-process gmt xyz2grd port (utils/gmt_xyz2grd_py.py).
    # Env-gated GMTSAR_XYZ2GRD_PY (default ON since v2.1.23; set =0 for subprocess fallback).
    _xyz2grd_file('unwrap.out', 'tmp.grd', par1=par1, par2=par2, ztype='f')
    print(' ')
    print('SNAPHU: generate connected component ... ...')
    _xyz2grd_file('conncomp.out', 'conncomp.grd', par1=par1, par2=par2, ztype='u')
    run('gmt grdmath tmp.grd mask2_patch.grd MUL = tmp.grd')
    
    print(' ')
    print('SNAPHU: detrend the unwrapped if DEFOMAX = 0 for interseismic ... ...')
    file_shuttle('tmp.grd','unwrap.grd', 'mv')
    
    print(' ')
    print('SNAPHU: landmask ... ...')
    if check_file_report('landmask_ra.grd')==True:
        run('gmt grdmath unwrap.grd landmask_ra_patch.grd MUL = tmp.grd '+V)
        file_shuttle('tmp.grd','unwrap.grd', 'mv')
    
    print(' ')
    print('SNAPHU: user defined mask ... ...')
    if check_file_report('mask_def.grd')==True:
        run('gmt grdmath unwrap.grd mask_def_patch.grd MUL = tmp.grd '+V)
        file_shuttle('tmp.grd','unwrap.grd', 'mv')
    
    print(' ')
    print('SNAPHU: plot the unwrapped phase ... ...')
    
    run('gmt grdgradient unwrap.grd -Nt.9 -A0. -Gunwrap_grad.grd')
    tmp = catch_output_cmd(["gmt","grdinfo","-C","-L2","unwrap.grd"],True,-999,-100000)
    print('SNAPHU: output from cmd gmt grdinfo -C -L2 unwrap.grd is', tmp, 'which should be a list')
    limitU = float(tmp[11])+float(tmp[12])*2.
    limitU = round(limitU,1)
    limitL = float(tmp[11])-float(tmp[12])*2.
    limitL = round(limitL,1)
    std    = round(float(tmp[12]),1)
    run('gmt makecpt -Cseis -I -Z -T'+'''"'''+str(limitL)+'''"/"'''+str(limitU)+'''"/1 -D > unwrap.cpt''')
    
    if interp==1:
        tmp1 = catch_output_cmd(["gmt","grdinfo","unwrap.grd","-C"],True,-999,-100000)
        print('SNAPHU: output from cmd gmt grdinfo unwrap.grd -C is', tmp1, 'which should be a list')
        boundR = (float(tmp1[2])-float(tmp1[1]))/4
        boundA = (float(tmp1[4])-float(tmp1[3]))/4
        
    run('gmt grdimage unwrap.grd -Iunwrap_grad.grd -Cunwrap.cpt -JX6.5i -Bxaf+lRange -Byaf+lAzimuth -BWSen -X1.3i -Y3i -P -K > unwrap.ps')
    run('''gmt psscale -Runwrap.grd -J -DJTC+w5/0.2+h+e -Cunwrap.cpt -Bxaf+l"Unwrapped phase" -By+lrad -O >> unwrap.ps''')
    run('gmt psconvert -Tf -P -A -Z unwrap.ps')
    
    print(' ')
    print('SNAPHU: unwrapped phase map: unwrap.pdf ... ...')
    
    print(' ')
    print('SNAPHU: clean up ... ...')
    
    run('rm -f tmp.grd corr_tmp.grd unwrap.out tmp2.grd unwrap_grad.grd conncomp.out')
    run('rm -f phase.in corr.in') 
    
    if interp==1:
        run('rm -f phase_tmp.grd')
        file_shuttle('phase_patch.grd','phasefilt_interp.grd','mv')
        
    if n==5:
        file_shuttle('corr_patch.grd', 'corr_cut.grd', 'mv')
    run('rm -f mask_patch.grd mask3.grd mask3.out')
    run('rm -f corr_cut.grd corr_patch.grd')
    
    print("SNAPHU - END ... ...")

if __name__ == "__main__":
    snaphu()
