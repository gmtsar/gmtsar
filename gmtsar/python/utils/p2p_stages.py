"""p2p_stages — stage functions for p2p_processing.

Split out of the monolithic p2p_processing script (v1.1.4). Each P2Pn function
runs one numbered stage of the pyGMTSAR pipeline:

    P2P1Preprocess               — preprocess raw / SLC data
    P2P2Clean / P2P2FocusAlign / P2P2RegionCut
                                 — image alignment
    P2P3MakeTopo                 — DEM-to-radar geometry
    P2P4MakeFilterInterferograms — form and filter interferograms
    P2P5Unwrap                   — phase unwrapping
    P2P6Geocode                  — final geocoding

Plus helpers (renameMasterAlignedForS1tops, switchMasterAligned, runFilter,
getIntfSubDirName) used by multiple stages.

Imported into the p2p_processing entry script via `from p2p_stages import *`.
"""
import sys, os, re
import subprocess, glob
from gmtsar_lib import *



# Per-SAT raw input specs for preprocess validation.
# Each entry: list of (suffix, fatal) tuples; suffix is appended to "raw/<name>".
# ALOS family + ENVI_SLC are handled separately below (bare name / any-of).
_RAW_FILE_SPEC = {
    'ERS':      [('.dat', True),  ('.ldr', True)],
    'ENVI':     [('.baq', False)],
    'S1_STRIP': [('.xml', False), ('.tiff', False)],
    'S1_TOPS':  [('.xml', False), ('.tiff', False), ('.EOF', False)],
    'CSK_RAW':  [('.h5',  False)],
    'CSK_SLC':  [('.h5',  False)],
    'RS2':      [('.xml', False), ('.tif',  False)],
    'TSX':      [('.xml', False), ('.cos',  False)],
    'GF3':      [('.xml', False), ('.tiff', False)],
    'NSR_A':    [('.h5',  False)],
    'NSR_B':    [('.h5',  False)],
}
# ALOS family: filename has no extension; raw/<name> is the input.
# NSR_A/B are L-band like ALOS but use .h5 inputs, so live in _RAW_FILE_SPEC.
_ALOS_FAMILY = {'ALOS', 'ALOS2', 'ALOS_SLC', 'ALOS_SCAN', 'ALOS4'}
# SATs that need filename rename via awk-style substr (S1_TOPS, NSR_A/B).
_NSR_FAMILY = {'NSR_A', 'NSR_B'}
_ENVI_SLC_EXTS = ('.N1', '.E1', '.E2')


def _check_preprocess_inputs(SAT, master, aligned):
    """Validate that the raw/* inputs exist before pre_proc runs.
    Aborts (sys.exit) only for SATs where missing inputs are unrecoverable
    (ALOS family, ENVI_SLC, ERS). Other SATs warn-only via check_file_report's
    own stderr message, matching the legacy csh tolerance."""
    if SAT in _ALOS_FAMILY:
        for name in (master, aligned):
            if not check_file_report(f"raw/{name}"):
                sys.exit()
        return
    if SAT == 'ENVI_SLC':
        for name in (master, aligned):
            if not any(check_file_report(f"raw/{name}{ext}") for ext in _ENVI_SLC_EXTS):
                sys.exit()
        return
    for ext, fatal in _RAW_FILE_SPEC.get(SAT, []):
        for name in (master, aligned):
            if not check_file_report(f"raw/{name}{ext}") and fatal:
                sys.exit()


def P2P1Preprocess(SAT, master, aligned, skip_master, cmdAppendix):

    print('P2P 1: PREPROCESS - START')
    print('P2P 1: Processing images '+master+' '+aligned)

    _check_preprocess_inputs(SAT, master, aligned)

    if SAT=='S1_TOPS':
        master, aligned = renameMasterAlignedForS1tops(master, aligned)
    if skip_master == 0 or skip_master == 2:
        run("rm -f raw/"+ master + ".PRM*")
        run("rm -f raw/"+ master + ".SLC")
        run("rm -f raw/"+ master + ".LED")
    if skip_master == 0 or skip_master == 1:
        run("rm -f raw/"+ aligned + ".PRM*")
        run("rm -f raw/"+ aligned + ".SLC")
        run("rm -f raw/"+ aligned + ".LED")
    if SAT =="S1_TOPS":
        master  = sys.argv[2]
        aligned = sys.argv[3]
    
    os.chdir("raw") # run("cd raw") didn't work.
    print('P2P 1: entering directory raw/')
    if SAT in _NSR_FAMILY:
        # NISAR: hand off to pre_proc_nsr which handles both A and B
        # frequencies from one .h5 product. Config file must be in parent dir.
        sys.argv2 = sys.argv[2] if len(sys.argv) > 2 else master
        sys.argv3 = sys.argv[3] if len(sys.argv) > 3 else aligned
        run(f"pre_proc_nsr {sys.argv2}.h5 ../config.py")
        run(f"pre_proc_nsr {sys.argv3}.h5 ../config.py")
    else:
        run('pre_proc '+SAT +' '+master+' '+aligned+' '+cmdAppendix)

    print('P2P 1: exiting directory raw/')
    os.chdir('..')
    print('P2P 1: PREPROCESS - END')

def renameMasterAlignedForS1tops(master0, aligned0):
    print('Renaming master and aligned for SAT==S1_TOPS')
    master = 'S1_'+master0[15:15+8]+'_'+master0[24:24+6]+'_F'+master0[6:7]
    aligned = 'S1_'+aligned0[15:15+8]+'_'+aligned0[24:24+6]+'_F'+aligned0[6:7]
    return master, aligned


def renameMasterAlignedForNSR(master0, aligned0, ab):
    """For NSR_A / NSR_B: NISAR full filenames have a YYYYMMDD date starting
    at csh-1-based position 44 (Python [43:51]). Output stem is
    'NSR_<YYYYMMDD>A' or '...B' depending on which frequency band.
    Matches the awk substr in pre_proc_nsr.csh + p2p_processing_nsr.csh."""
    suffix = 'A' if ab == 'NSR_A' else 'B'
    master = f"NSR_{master0[43:51]}{suffix}"
    aligned = f"NSR_{aligned0[43:51]}{suffix}"
    return master, aligned
    
# --- P2P2 SAT dispatch constants ---
# SATs that load .raw inputs (raw data → sarp focus step) vs everything else
# which loads .SLC inputs directly. Used by P2P2FocusAlign.
_SAT_RAW_INPUT = {'ERS', 'ENVI', 'ALOS', 'CSK_RAW'}

# xcorr search parameters by SAT (everything not ALOS2_SCAN uses the default).
_XCORR_DEFAULT_PARAMS    = "-xsearch 128 -ysearch 128 -nx 20 -ny 50"
_XCORR_ALOS2_SCAN_PARAMS = "-xsearch 32 -ysearch 256 -nx 32 -ny 128"


def _rm_slc_files(slc_dir, name):
    """rm -f <slc_dir>/<name>.PRM* + .SLC + .LED — used by P2P2Clean to wipe
    a single SAR product from a working directory before re-staging."""
    for ext in ('.PRM*', '.SLC', '.LED'):
        run(f"rm -f {slc_dir}/{name}{ext}")


def _rm_slc_xml_tiff_eof(slc_dir, name):
    """rm -f <slc_dir>/<name>.tiff + .xml + .EOF — TOPS/ENVI/etc auxiliary
    files cleaned alongside the SAR product."""
    for ext in ('.tiff', '.xml', '.EOF'):
        run(f"rm -f {slc_dir}/{name}{ext}")


def P2P2Clean(SAT, master, aligned, skip_master, iono):
    """Wipe SLC/{,L,H} working dirs prior to staging. skip_master controls
    which side(s) to clear: 0 = both, 1 = aligned only, 2 = master only.
    iono=1 also clears the SLC_L / SLC_H side dirs."""
    print('P2P 2: if stage<=2 and skip_2 == 0')

    if skip_master in (0, 2):
        _rm_slc_files("SLC", master)
    if skip_master in (0, 1):
        _rm_slc_files("SLC", aligned)

    if iono != 1:
        return

    if skip_master in (0, 2):
        _rm_slc_xml_tiff_eof("SLC", sys.argv[2])
        for d in ("SLC_L", "SLC_H"):
            _rm_slc_files(d, master)
            _rm_slc_xml_tiff_eof(d, sys.argv[2])

    if skip_master in (0, 1):
        _rm_slc_xml_tiff_eof("SLC", sys.argv[3])
        for d in ("SLC_L", "SLC_H"):
            _rm_slc_files(d, aligned)
            _rm_slc_xml_tiff_eof(d, sys.argv[3])

def _stage_slc_inputs(name, sat_uses_raw):
    """Copy PRM and symlink the SAR product + LED from ../raw/ into the
    current working directory. SATs in _SAT_RAW_INPUT use .raw inputs and a
    subsequent sarp focusing step; others use pre-focused .SLC inputs."""
    ext = '.raw' if sat_uses_raw else '.SLC'
    run(f"cp ../raw/{name}.PRM .")
    run(f"ln -sf ../raw/{name}{ext} .")
    run(f"ln -sf ../raw/{name}.LED .")


def _xcorr_and_fitoffset(SAT, master, aligned):
    """xcorr master/aligned, then run fitoffset and append to aligned.PRM.
    ALOS2_SCAN uses larger ysearch and has a manual median-filter step (legacy
    code commented out); NSR_A/B uses slc2amp + fitoffset_ra (10/10 params);
    other SATs use default xcorr params, with fitoffset polynomial degree 3
    for .raw-input SATs and 2 for everything else."""
    if SAT == "ALOS2_SCAN":
        run(f"xcorr {master}.PRM {aligned}.PRM {_XCORR_ALOS2_SCAN_PARAMS}")
        # Median-filter the azimuth-shift column of freq_xcorr.dat, keep rows
        # within median±3, then fit a 2-rng/3-az polynomial with SNR≥10.
        # Mirrors gmtsar/csh/align_ALOS2_SCAN.csh lines 80-86.
        import numpy as np
        x = np.loadtxt("freq_xcorr.dat")
        az = np.sort(x[:, 3])
        amed = az[len(az) // 2]
        keep = (x[:, 3] > amed - 3) & (x[:, 3] < amed + 3)
        np.savetxt("freq_alos2.dat", x[keep], fmt="%g")
        run(f"fitoffset.py 2 3 freq_alos2.dat 10 >> {aligned}.PRM")
    elif SAT in _NSR_FAMILY:
        # NISAR: build amp grid from master at decimation 4, then xcorr with
        # 40x40 grid and fitoffset_ra with 10/10 polynomial.
        run("rm -f amp*.grd")
        run(f"slc2amp {master}.PRM 4 amp-{master}.grd")
        run(f"xcorr {master}.PRM {aligned}.PRM -xsearch 128 -ysearch 128 -nx 40 -ny 40")
        run("fitoffset_ra 10 10 freq_xcorr.dat 20")
    else:
        run(f"xcorr {master}.PRM {aligned}.PRM {_XCORR_DEFAULT_PARAMS}")
        fit_dim = "3 3" if SAT in _SAT_RAW_INPUT else "2 2"
        run(f"fitoffset.py {fit_dim} freq_xcorr.dat 18 >> {aligned}.PRM")


def _resamp_and_swap(master, aligned, SAT=None):
    """resamp aligned vs master, then swap .SLCresamp/.PRMresamp into place.
    For NSR_A/NSR_B: uses resamp factor 5 with r.grd/a.grd alignment grids
    (produced by fitoffset_ra). Other SATs use factor 4 without those grids."""
    if SAT in _NSR_FAMILY:
        run(f"resamp {master}.PRM {aligned}.PRM {aligned}.PRMresamp {aligned}.SLCresamp 5 r.grd a.grd")
    else:
        run(f"resamp {master}.PRM {aligned}.PRM {aligned}.PRMresamp {aligned}.SLCresamp 4")
    delete(f"{aligned}.SLC")
    file_shuttle(f"{aligned}.SLCresamp", f"{aligned}.SLC", 'mv')
    file_shuttle(f"{aligned}.PRMresamp", f"{aligned}.PRM", 'cp')


def _iono_LH_propagate_wavelength(slc_side, name, params_file):
    """Inside SLC/, after split_spectrum produced params{1,2}: descend into
    SLC_L or SLC_H, copy the PRM from SLC/, link the LED from raw/, and
    replace the wavelength with the low/high-spectrum value parsed from
    SLC/<params_file>. Used by P2P2FocusAlign iono path."""
    os.chdir(f"../{slc_side}")
    wl = grep_value(f"../SLC/{params_file}", "low_wavelength", 3)
    run(f"cp ../SLC/{name}.PRM .")
    run(f"ln -sf ../raw/{name}.LED .")
    replace_strings(f"{name}.PRM", "wavelength", f"radar_wavelength = {wl}")


def _iono_LH_fitoffset_and_resamp(SAT, master, aligned, tsx_in_xcorr_group):
    """Inside SLC_L or SLC_H: cp aligned.PRM → PRM0, link the appropriate
    freq_*.dat from SLC/, run fitoffset (3-way SAT dispatch), then resamp.
    tsx_in_xcorr_group preserves legacy L-vs-H asymmetry on TSX."""
    file_shuttle(f"{aligned}.PRM", f"{aligned}.PRM0", 'cp')
    if SAT == "ALOS2_SCAN":
        freq_link, fit_dim = "freq_alos2.dat", "3 3"
    elif SAT in _SAT_RAW_INPUT or (tsx_in_xcorr_group and SAT == "TSX"):
        freq_link, fit_dim = "freq_xcorr.dat", "3 3"
    else:
        freq_link, fit_dim = "freq_alos2.dat", "2 2"
    run(f"ln -sf ../SLC/{freq_link}")
    run(f"fitoffset.py {fit_dim} freq_xcorr.dat 18 >>{aligned}.PRM")
    _resamp_and_swap(master, aligned, SAT)


def P2P2FocusAlign(SAT, master, aligned, skip_master, iono):

    print('P2P 2: focus and align SLC images')
    print("P2P 2: ALIGN.CSH - START")
    print('P2P 2: entering directory SLC/')

    if SAT != 'S1_TOPS':
        print("P2P 2: if SAT is not S1_TOPS")
        sat_uses_raw = SAT in _SAT_RAW_INPUT

        if skip_master in (0, 2):
            _stage_slc_inputs(master, sat_uses_raw)
        if skip_master in (0, 1):
            _stage_slc_inputs(aligned, sat_uses_raw)
            if sat_uses_raw and iono == 1:
                # Zero chirp extension for ionospheric phase estimation (ALOS path).
                for name in (master, aligned):
                    replace_strings(f"{name}.PRM", "fd1", "fd1 = 0.0000")
                    replace_strings(f"{name}.PRM", "chirp_ext", "chirp_ext = 0")

        if sat_uses_raw:
            print('P2P 2: calling sarp for SAT==ERS/ENVI/ALOS/CSK_RAW')
            if skip_master in (0, 2):
                run(f"sarp {master}.PRM")
            if skip_master in (0, 1):
                run(f"sarp {aligned}.PRM")
       
        if iono == 1:
            print(" ")
            print("P2P 2: if iono == 1")
            print(" ")
            if skip_master == 0 or skip_master == 2:
                file_path = f"../raw/ALOS_fbd2fbs_log_{aligned}"
                if check_file_report(file_path)==True:
                    run("split_spectrum " + master + ".PRM 1 > params1") 
                else:
                    run("split_spectrum " + master + ".PRM > params1") 
                
                file_shuttle('SLCH', '../SLC_H/'+master+'.SLC', 'mv')
                file_shuttle('SLCL', '../SLC_L/'+master+'.SLC', 'mv')
                _iono_LH_propagate_wavelength("SLC_L", master, "params1")
                _iono_LH_propagate_wavelength("SLC_H", master, "params1")
                os.chdir("../SLC")

            if skip_master == 0 or skip_master == 1:
                file_path = f"../raw/ALOS_fbd2fbs_log_{aligned}"
                if check_file_report(file_path):
                    run(f"split_spectrum {aligned}.PRM 1 > params2")
                else:
                    run(f"split_spectrum {aligned}.PRM > params2")

                run(f"mv SLCH ../SLC_H/{aligned}.SLC")
                run(f"mv SLCL ../SLC_L/{aligned}.SLC")
                _iono_LH_propagate_wavelength("SLC_L", aligned, "params2")
                _iono_LH_propagate_wavelength("SLC_H", aligned, "params2")
        # endif (iono == 1)

        if skip_master in (0, 1):
            file_shuttle(f"{aligned}.PRM", f"{aligned}.PRM0", 'cp')
            run(f"SAT_baseline {master}.PRM {aligned}.PRM0 >> {aligned}.PRM")
            _xcorr_and_fitoffset(SAT, master, aligned)
            _resamp_and_swap(master, aligned, SAT)
            
            if iono == 1:
                print("P2P 2: iono LH fitoffset + resamp")
                # NOTE: legacy code includes TSX in the freq_xcorr group for SLC_L
                # but not SLC_H. Preserved as-is since the iono path is not
                # exercised by the test suite; likely a typo (see release notes).
                os.chdir("../SLC_L")
                _iono_LH_fitoffset_and_resamp(SAT, master, aligned, tsx_in_xcorr_group=True)
                os.chdir("../SLC_H")
                _iono_LH_fitoffset_and_resamp(SAT, master, aligned, tsx_in_xcorr_group=False)
                os.chdir("../SLC")
                
    elif SAT == "S1_TOPS":
        if skip_master == 0 or skip_master == 2:
            file_shuttle("../raw/"+master+".PRM", ".", "cp")
            file_shuttle('../raw/'+master+'.SLC', '.', 'link')
            file_shuttle('../raw/'+master+'.LED', '.', 'link')

        if skip_master == 0 or skip_master == 1:
            file_shuttle("../raw/"+aligned+".PRM", ".", "cp")
            file_shuttle('../raw/'+aligned+'.SLC', '.', 'link')
            file_shuttle('../raw/'+aligned+'.LED', '.', 'link')
            
        if iono == 1:
            if (skip_master == 0 or skip_master == 2):
                file_shuttle("../raw/"+sys.argv[1]+".tiff", ".", "link")
                cmd = "split_spectrum "+master+".PRM > params1"
                run(cmd)
                file_shuttle("high.tiff", "../SLC_H/"+sys.argv[1]+".tiff", "mv")
                file_shuttle("low.tiff", "../SLC_L/"+sys.argv[1]+".tiff", "mv")
            
            if (skip_master == 0 or skip_master == 1):
                file_shuttle("../raw/"+sys.argv[2]+".tiff", ".", "link")
                cmd = "split_spectrum "+aligned+".PRM > params2"
                run(cmd)
                file_shuttle("high.tiff", "../SLC_H/"+sys.argv[2]+".tiff", "mv")
                file_shuttle("low.tiff", "../SLC_L/"+sys.argv[2]+".tiff", "mv")
                
            os.chdir("../SLC_L")
            if (skip_master == 0 or skip_master == 2):
                file_shuttle("../raw/"+sys.argv[1]+".xml", ".", "link")
                file_shuttle("../raw/"+sys.argv[1]+".EOF", ".", "link")
                file_shuttle("../topo/dem.grd", ".", "link")
            if (skip_master == 0 or skip_master == 1):
                file_shuttle("../raw/"+sys.argv[2]+".xml", ".", "link")
                file_shuttle("../raw/"+sys.argv[2]+".EOF", ".", "link")
                file_shuttle("../raw/a.grd", ".", "link")
                file_shuttle("../raw/r.grd", ".", "link")
                file_shuttle("../raw/offset*dat", ".", "link")
            
            if (skip_master == 0):
                run("align_tops "+sys.argv[1]+" "+sys.argv[1]+".EOF "+sys.argv[2]+" "+sys.argv[2]+".EOF dem.grd 1")
            elif (skip_master == 1):
                cmd = "align_tops "+sys.argv[1]+" 0 "+sys.argv[2]+" "+sys.argv[2]+".EOF dem.grd 1"
                run(cmd)
            elif (skip_master == 2):
                cmd = "align_tops "+sys.argv[1]+" "+sys.argv[1]+".EOF "+sys.argv[2]+" 0 dem.grd 1"
                run(cmd)
            
            if (skip_master == 0 or skip_master == 2):
                wl1 = grep_value("low_wavelength", "../SLC/params1", 3)
                replace_strings(master+".PRM", "wavelength", "radar_wavelength = "+wl1)
            if (skip_master == 0 or skip_master == 1):
                wl2 = grep_value("low_wavelength", "../SLC/params2", 3)
                replace_strings(aligned+".PRM", "wavelength", "radar_wavelength = "+wl2)
            
            # repeat everything for ../SLC_H
            os.chdir("../SLC_H")
            if (skip_master == 0 or skip_master == 2):
                file_shuttle("../raw/"+sys.argv[1]+".xml", ".", "link")
                file_shuttle("../raw/"+sys.argv[1]+".EOF", ".", "link")
                file_shuttle("../topo/dem.grd", ".", "link")
            elif (skip_master == 0 or skip_master == 1):
                file_shuttle("../raw/"+sys.argv[2]+".xml", ".", "link")
                file_shuttle("../raw/"+sys.argv[2]+".EOF", ".", "link")
                file_shuttle("../raw/a.grd", ".", "link")
                file_shuttle("../raw/r.grd", ".", "link")
                file_shuttle("../raw/offset*.dat", ".", "link")
            
            if (skip_master == 0):
                cmd = "align_tops "+sys.argv[1]+" "+sys.argv[1]+".EOF "+sys.argv[2]+" "+sys.argv[2]+".EOF dem.grd 1"
                run(cmd)
            elif (skip_master == 1):
                cmd = "align_tops "+sys.argv[1]+" 0 "+sys.argv[2]+" "+sys.argv[2]+".EOF dem.grd 1"
                run(cmd)
            elif (skip_master == 2):
                cmd = "align_tops "+sys.argv[1]+" "+sys.argv[1]+".EOF "+sys.argv[2]+" 0 dem.grd 1"
                run(cmd)
            
            if (skip_master == 0 or skip_master == 2):
                wl1 = grep_value("low_wavelength", "../SLC/params1", 3)
                replace_strings(master+".PRM", "wavelength", "radar_wavelength = "+wl1)
            if (skip_master == 0 or skip_master == 1):
                wl2 = grep_value("low_wavelength", "../SLC/params2", 3)
                replace_strings(aligned+".PRM", "wavelength", "radar_wavelength = "+wl2)
            
            os.chdir("../SLC")
            
def _cut_slc_to_region(name, junk_tag, region):
    """cut_slc <name>.PRM → junkN.{PRM,SLC} then rename to <name>.{PRM,SLC}."""
    run(f"cut_slc {name}.PRM {junk_tag} {region}")
    file_shuttle(f"{junk_tag}.PRM", f"{name}.PRM", 'mv')
    file_shuttle(f"{junk_tag}.SLC", f"{name}.SLC", 'mv')


def P2P2RegionCut(master, aligned, skip_master, iono, region_cut):
    """Crop SLC images to `region_cut` and write back in place. With iono=1
    repeats the crop in SLC_L and SLC_H. (Bug fix: legacy code referenced
    master.{PRM,SLC} when cutting the aligned image in the L/H paths — now
    correctly references aligned.) region_cut was previously a free-name
    reference to the caller's module global — now passed explicitly so the
    function works regardless of where it's imported from."""
    print(f"P2P 2: region_cut={region_cut}, cutting SLC images")

    def _cut_both_sides():
        if skip_master in (0, 2):
            _cut_slc_to_region(master, "junk1", region_cut)
        if skip_master in (0, 1):
            _cut_slc_to_region(aligned, "junk2", region_cut)

    _cut_both_sides()

    if iono == 1:
        for side in ("SLC_L", "SLC_H"):
            print(f"P2P 2: entering {side}")
            os.chdir(f"../{side}")
            _cut_both_sides()

def _offset_topo_shift(master):
    """Generate amp-<master>.grd at the same range sampling as topo_ra.grd,
    then run offset_topo to compute topo_shift.grd. Called when shift_topo=1."""
    print('P2P 3: OFFSET_TOPO - START, entering SLC/')
    os.chdir('SLC')
    run("gmt grdinfo ../topo/topo_ra.grd > tmp.txt")
    rng = grep_value("tmp.txt", "x_inc", 7)
    run(f"slc2amp {master}.PRM {rng} amp-{master}.grd")
    os.chdir("..")

    print('P2P 3: entering topo/')
    os.chdir("topo")
    file_shuttle(f"../SLC/amp-{master}.grd", ".", "link")
    run(f"offset_topo amp-{master}.grd topo_ra.grd 0 0 7 topo_shift.grd")
    os.chdir("..")
    print("P2P 3: OFFSET_TOPO - END")


def P2P3MakeTopo(master, aligned, topo_phase, topo_interp_mode, shift_topo):
    """Generate topo_ra.grd from dem.grd and optionally shift it to align
    against the master SLC. topo_phase=0 skips this stage entirely."""
    print('P2P 3: start from make topo_ra')
    run("cleanup topo")

    if topo_phase == 0:
        print("P2P 3: NO TOPO_RA is SUBSTRACTED")
        return
    if topo_phase != 1:
        sys.exit(f"P2P 3: wrong parameter: topo_phase {topo_phase}")

    print('P2P 3: DEM2TOPO_RA - START, entering topo/')
    os.chdir("topo")
    file_shuttle(f"../SLC/{master}.PRM", 'master.PRM', 'cp')
    file_shuttle(f"../raw/{master}.LED", ".", 'link')

    if not check_file_report('dem.grd'):
        sys.exit("no DEM file found: dem.grd")
    interp_arg = " 1" if topo_interp_mode == 1 else ""
    run(f"dem2topo_ra master.PRM dem.grd{interp_arg}")

    os.chdir('..')
    print('P2P 3: DEM2TOPO_RA - END')

    if shift_topo == 1:
        _offset_topo_shift(master)
    elif shift_topo == 0:
        print("P2P 3: NO TOPO_RA SHIFT")
    else:
        sys.exit(f"P2P 3: wrong parameter: shift_topo {shift_topo}")

def switchMasterAligned(switch_master, master, aligned):
    print('P2P 4: select the master based on switch_master')
    if switch_master == 0:
        ref = master
        rep = aligned
    elif switch_master == 1:
        ref = aligned
        rep = master
    else:
        sys.exit('P2P 4: wrong parameter: switch_master ' + switch_master)
    return ref, rep

def _stage_intf_inputs(src_dir, link_exts=(), cp_exts=()):
    """Glob files of given extensions from src_dir and link or cp them into
    the current dir. Used by P2P4 for staging SLC/SLC_H/SLC_L → intf working
    dirs."""
    for ext in link_exts:
        for f in glob.glob(f"{src_dir}/{ext}"):
            file_shuttle(f, '.', 'link')
    for ext in cp_exts:
        for f in glob.glob(f"{src_dir}/{ext}"):
            file_shuttle(f, '.', 'cp')


def _intf_and_filter(ref, rep, topo_phase, shift_topo, filter_cmd_callable):
    """Run `intf` with the appropriate topo argument (topo_shift / topo_ra /
    none, per topo_phase + shift_topo), then call filter_cmd_callable for
    the filtering step. The caller supplies the filter command since the
    main path uses runFilter (multi-arg) and the iono path uses a fixed
    `filter ... 500 dec new_incx new_incy` form."""
    if topo_phase == 1:
        topo_file = "topo_shift.grd" if shift_topo == 1 else "topo_ra.grd"
        run(f"ln -sf ../../topo/{topo_file} .")
        run(f"intf {ref}.PRM {rep}.PRM -topo {topo_file}")
    else:
        print('P2P 4: NO TOPOGRAPHIC PHASE REMOVAL PERFORMED')
        run(f"intf {ref}.PRM {rep}.PRM")
    filter_cmd_callable()


def _iono_intf_block(side, slc_dir, ref, rep, dec, new_incx, new_incy,
                     topo_phase, shift_topo, link_landmask_directly):
    """One of the three nearly-identical iono blocks (intf_h, intf_l, intf_o).
    Stages SLCs from slc_dir, runs intf+filter, snaphu_interp if requested.
    link_landmask_directly=False does the full landmask-via-grdinfo dance
    (only the first block, intf_h, needs that); the later blocks just link
    the already-produced landmask_ra.grd."""
    os.chdir(side)
    _stage_intf_inputs(slc_dir,
                       link_exts=('*.SLC', '*.LED'),
                       cp_exts=('*.PRM',))
    _stage_intf_inputs('../../SLC', cp_exts=('params*',))

    def _iono_filter():
        run(f"filter {ref}.PRM {rep}.PRM 500 {dec} {new_incx} {new_incy}")
    _intf_and_filter(ref, rep, topo_phase, shift_topo, _iono_filter)

    file_shuttle('phase.grd', 'phasefilt.grd', 'cp')

    if iono_skip_est == 0:
        if mask_water == 1 or switch_land == 1:
            if link_landmask_directly:
                file_shuttle('../../topo/landmask_ra.grd', '.', 'link')
            else:
                # First block: compute landmask region from phase.grd then
                # produce landmask_ra.grd via the landmask binary.
                output = subprocess.check_output('gmt grdinfo phase.grd -I-', shell=True)
                rcut = output[2:20].decode('utf-8')
                os.chdir('../../topo')
                run(f"landmask {rcut}")
                os.chdir(f"../iono_phase/{side}")
                file_shuttle('../../topo/landmask_ra.grd', '.', 'link')
        run('snaphu.py 0.05 0 1')
    os.chdir('..')


def P2P4MakeFilterInterferograms(ref, rep, topo_phase, shift_topo, range_dec, azimuth_dec,
                                dec, filter, compute_phase_gradient, iono, iono_dsamp):
    """Form and filter the interferogram. Main path produces a single
    intf/<sub>/phasefilt.grd; iono=1 additionally produces high/low/orig
    interferograms in iono_phase/intf_{h,l,o}/ and a final corrected
    phasefilt.grd via estimate_ionospheric_phase."""
    print('P2P 4: INTF + FILTER - START')
    run('mkdir -p intf')
    run('cleanup intf')

    os.chdir('intf')
    intfSubDirName = getIntfSubDirName(ref, rep)
    run(f"mkdir -p {intfSubDirName}")
    os.chdir(intfSubDirName)

    _stage_intf_inputs('../../SLC',
                       link_exts=(f'{ref}.LED', f'{rep}.LED',
                                  f'{ref}.SLC', f'{rep}.SLC'),
                       cp_exts=(f'{ref}.PRM', f'{rep}.PRM'))

    _intf_and_filter(
        ref, rep, topo_phase, shift_topo,
        lambda: runFilter(ref, rep, filter, dec, range_dec, azimuth_dec, compute_phase_gradient),
    )
    os.chdir('../..')

    if iono != 1:
        print('P2P 4: INTF + FILTER - END')
        return

    # iono=1: produce intf_h, intf_l, intf_o + iono correction.
    # NOTE: legacy code had a typo where the intf_l block ran inside intf_h
    # (os.chdir('intf_h') instead of 'intf_l' after the first block) — fixed
    # below. iono path is not exercised by the test suite; see release notes.
    if os.path.exists('iono_phase'):
        shutil.rmtree('iono_phase')
    os.makedirs('iono_phase')
    os.chdir('iono_phase')
    for d in ('intf_o', 'intf_h', 'intf_l', 'iono_correction'):
        os.makedirs(d, exist_ok=True)

    new_incx = int(range_dec) * int(iono_dsamp)
    new_incy = int(azimuth_dec) * int(iono_dsamp)

    _iono_intf_block('intf_h', '../../SLC_H', ref, rep, dec, new_incx, new_incy,
                     topo_phase, shift_topo, link_landmask_directly=False)
    _iono_intf_block('intf_l', '../../SLC_L', ref, rep, dec, new_incx, new_incy,
                     topo_phase, shift_topo, link_landmask_directly=True)
    _iono_intf_block('intf_o', '../../SLC',   ref, rep, dec, new_incx, new_incy,
                     topo_phase, shift_topo, link_landmask_directly=True)

    os.chdir('iono_correction')
    if iono_skip_est == 0:
        run(f"estimate_ionospheric_phase ../intf_h ../intf_l ../intf_o "
            f"../../intf/{intfSubDirName} {iono_filt_rng} {iono_filt_azi}")
        os.chdir(f"../../intf/{intfSubDirName}")
        file_shuttle('phasefilt.grd', 'phasefilt_non_corrected.grd', 'mv')
        run('grdsample ../../iono_phase/iono_correction/ph_iono_orig.grd '
            '-Rphasefilt_non_corrected.grd -Gph_iono.grd')
        run('grdmath phasefilt_non_corrected.grd ph_iono.grd SUB PI ADD '
            '2 PI MUL MOD PI SUB = phasefilt.grd')
        run('grdimage phasefilt.grd -JX6.5i -Bxaf+lRange -Byaf+lAzimuth '
            '-BWSen -Cphase.cpt -X1.3i -Y3i -P -K > phasefilt.ps')
        run('psscale -Rphasefilt.grd -J -DJTC+w5i/0.2i+h -Cphase.cpt '
            '-Bxa1.57+l"Phase" -By+lrad -O >> phasefilt.ps')
        run('gmt psconvert -Tf -P -A -Z phasefilt.ps')

    os.chdir('../../')
    print('P2P 4: INTF + FILTER - END')

def runFilter(ref, rep, filter, dec, range_dec, azimuth_dec, compute_phase_gradient):
    """Two-form filter: 3-arg (filter, dec, compute_phase_gradient) when both
    range_dec and azimuth_dec are sentinel -999, else 5-arg with explicit
    range/azimuth decimation."""
    base = f"filter {ref}.PRM {rep}.PRM {filter} {dec}"
    if range_dec == -999 and azimuth_dec == -999:
        run(f"{base} {compute_phase_gradient}")
    else:
        run(f"{base} {range_dec} {azimuth_dec} {compute_phase_gradient}")


def getIntfSubDirName(ref, rep):
    """Build the per-pair subdir name as '<ref_clock>_<rep_clock>'."""
    ref_id = int(float(grep_value(f"../raw/{ref}.PRM", "SC_clock_start", 3)))
    rep_id = int(float(grep_value(f"../raw/{rep}.PRM", "SC_clock_start", 3)))
    return f"{ref_id}_{rep_id}"


def _enter_intf_subdir(ref, rep):
    """cd into intf/<sub>; returns the sub name for reuse."""
    os.chdir("intf")
    sub = getIntfSubDirName(ref, rep)
    os.chdir(sub)
    return sub


def _ensure_landmask(sub):
    """Build landmask_ra.grd in topo/ if missing, then link it into the
    current intf/<sub>/ working dir. Bug-fixed: r_cut now holds the actual
    output of `gmt grdinfo phase.grd -I-` (cols 3-20); legacy code stored
    the command string itself. landmask_ra.grd existence check now uses a
    string literal (legacy code referenced an undefined identifier)."""
    output = subprocess.check_output('gmt grdinfo phase.grd -I- | cut -c3-20',
                                     shell=True).decode('utf-8').strip()
    os.chdir("../../topo")
    if not check_file_report('landmask_ra.grd'):
        run(f"landmask {output}")
    os.chdir(f"../intf/{sub}")
    file_shuttle("../../topo/landmask_ra.grd", ".", "link")


def P2P5Unwrap(ref, rep, threshold_snaphu, mask_water, switch_land, near_interp, defomax=0):
    """Phase unwrap via snaphu; threshold_snaphu==0 skips the stage."""
    if threshold_snaphu == 0:
        print('P2P 5: SKIP UNWRAP PHASE')
        return

    sub = _enter_intf_subdir(ref, rep)
    if mask_water == 1 or switch_land == 1:
        _ensure_landmask(sub)

    print(f'P2P 5: SNAPHU - START, threshold_snaphu={threshold_snaphu}')
    # Python snaphu unifies snaphu/snaphu_interp; the 3rd arg is interp flag.
    # Use snaphu.py (Python wrapper) explicitly. The bare name `snaphu` is
    # the upstream C binary which has a different CLI; collision with our
    # wrapper was the root cause of ALOS_haiti's silent snaphu failure.
    run(f"snaphu.py {threshold_snaphu} {defomax} {1 if near_interp == 1 else 0}")
    print('P2P 5: SNAPHU - END')
    os.chdir("../..")


def P2P6Geocode(ref, rep, threshold_geocode, topo_phase):
    """Geocode the unwrapped phase; threshold_geocode==0 skips the stage."""
    if threshold_geocode == 0:
        print('P2P 6: SKIP_GEOCODE')
        return
    if topo_phase != 1:
        sys.exit('P2P 6: topo_ra is needed to geocode')

    _enter_intf_subdir(ref, rep)
    print('P2P 6: GEOCODE - START')

    for stale in ('rain.grd', 'ralt.grd', 'trans.dat'):
        if check_file_report(stale):
            delete(stale)

    file_shuttle("../../topo/trans.dat", ".", "link")
    print(f"threshold_geocode: {threshold_geocode}")
    run(f"geocode {threshold_geocode}")
    print('P2P 6: GEOCODE - END')
    os.chdir('../..')
        
        
