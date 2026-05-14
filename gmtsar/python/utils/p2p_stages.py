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



def P2P1Preprocess(SAT, master, aligned, skip_master, cmdAppendix):
     
    print('P2P 1: PREPROCESS - START')
    print('P2P 1: Processing images '+master+' '+aligned)
    
    if SAT=="ALOS" or SAT=="ALOS2" or SAT=="ALOS_SLC" or SAT=="ALOS_SCAN":
        if check_file_report("raw/"+master)==False:
            sys.exit()
        if check_file_report("raw/"+aligned)==False:
            sys.exit()
    elif SAT == "ENVI_SLC":
        if check_file_report("raw/"+master+".N1") == False and \
           check_file_report("raw/"+master+".E1") == False and \
           check_file_report("raw/"+master+".E2") == False:
            print(" no file raw/" + master)
            sys.exit()
        if check_file_report("raw/"+aligned+".N1") == False and \
           check_file_report("raw/"+aligned+".E1") == False and \
           check_file_report("raw/"+aligned+".E2") == False:
            print(" no file raw/" + aligned)
            sys.exit()
    elif SAT == "ERS":
        if check_file_report("raw/"+master+".dat") == False:
            print(" no file raw/" + master + ".dat")
            sys.exit()
        if check_file_report("raw/"+aligned+".dat") == False:
            print(" no file raw/" + aligned + ".dat")
            sys.exit()
        if check_file_report("raw/"+master+".ldr") == False:
            print(" no file raw/" + master + ".ldr") 
            sys.exit()
        fn = "raw/"+aligned+".ldr"
        if check_file_report(fn) == False:
            print(" no file " + fn)
            sys.exit()
    elif SAT == "ENVI":
        check_file_report("raw/"+master+".baq")
        check_file_report("raw/"+aligned+".baq")
    elif SAT == "S1_STRIP" or SAT == "S1_TOPS":   
        check_file_report("raw/" + master  + ".xml")
        check_file_report("raw/" + master  + ".tiff")
        check_file_report("raw/" + aligned + ".xml")
        check_file_report("raw/" + aligned + ".tiff")
        if SAT == "S1_TOPS":
            check_file_report("raw/" + master  + ".EOF")
            check_file_report("raw/" + aligned + ".EOF")
    elif SAT == "CSK_RAW" or SAT == "CSK_SLC":
        check_file_report("raw/" + master  + ".h5")
        check_file_report("raw/" + aligned + ".h5")
    elif SAT == "RS2":
        check_file_report("raw/" + master  + ".xml")
        check_file_report("raw/" + master  + ".tif")
        check_file_report("raw/" + aligned + ".xml")
        check_file_report("raw/" + aligned + ".xml")
    elif SAT == "TSX":
        check_file_report("raw/" + master  + ".xml") 
        check_file_report("raw/" + aligned + ".xml") 
        check_file_report("raw/" + master  + ".cos") 
        check_file_report("raw/" + aligned + ".cos")
    elif SAT == "GF3":
        check_file_report("raw/" + master  + ".xml") 
        check_file_report("raw/" + aligned + ".xml")

        check_file_report("raw/" + master  + ".tiff") 
        check_file_report("raw/" + aligned + ".tiff")

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
    run('pre_proc '+SAT +' '+master+' '+aligned+' '+cmdAppendix)

    print('P2P 1: exiting directory raw/')
    os.chdir('..')
    print('P2P 1: PREPROCESS - END')

def renameMasterAlignedForS1tops(master0, aligned0):
    print('Renaming master and aligned for SAT==S1_TOPS')
    master = 'S1_'+master0[15:15+8]+'_'+master0[24:24+6]+'_F'+master0[6:7]
    aligned = 'S1_'+aligned0[15:15+8]+'_'+aligned0[24:24+6]+'_F'+aligned0[6:7]
    return master, aligned
    
def P2P2Clean(SAT, master, aligned, skip_master, iono):
     
    print('P2P 2: if stage<=2 and skip_2 == 0')
     
    if skip_master == 0 or skip_master == 2:
        print(" ")
        print(" if skip_master == 0 or 2")
        print(" ")
        run("rm -f SLC/" + master + ".PRM*")
        run("rm -f SLC/" + master + ".SLC")
        run("rm -f SLC/" + master + ".LED")
    if skip_master == 0 or skip_master == 1:
        print(" ")
        print(" if skip_master == 0 or 1")
        print(" ")
        run("rm -f SLC/" + aligned + ".PRM*")
        run("rm -f SLC/" + aligned + ".SLC")
        run("rm -f SLC/" + aligned + ".LED")
    if iono == 1:
        print(" ")
        print(" if iono == 1 and then check skip_master")
        print(" ")
        if skip_master == 0 or skip_master == 2:
            run("rm -f SLC/" + sys.argv[2] + ".tiff")
            run("rm -f SLC/" + sys.argv[2] + ".xml")
            run("rm -f SLC/" + sys.argv[2] + ".EOF")

            run("rm -f SLC_L/" + master + ".PRM*")
            run("rm -f SLC_L/" + master + ".SLC")
            run("rm -f SLC_L/" + master + ".LED")
    
            run("rm -f SLC_L/" + sys.argv[2] + ".tiff")
            run("rm -f SLC_L/" + sys.argv[2] + ".xml")
            run("rm -f SLC_L/" + sys.argv[2] + ".EOF")

            run("rm -f SLC_H/" + master + ".PRM*")
            run("rm -f SLC_H/" + master + ".SLC")
            run("rm -f SLC_H/" + master + ".LED")
     
            run("rm -f SLC_H/" + sys.argv[2] + ".tiff")
            run("rm -f SLC_H/" + sys.argv[2] + ".xml")
            run("rm -f SLC_H/" + sys.argv[2] + ".EOF")
        
        if skip_master == 0 or skip_master == 1:
            run("rm -f SLC/" + sys.argv[3] + ".tiff")
            run("rm -f SLC/" + sys.argv[3] + ".xml")
            run("rm -f SLC/" + sys.argv[3] + ".EOF")

            run("rm -f SLC_L/" + aligned + ".PRM*")
            run("rm -f SLC_L/" + aligned + ".SLC")
            run("rm -f SLC_L/" + aligned + ".LED")
    
            run("rm -f SLC_L/" + sys.argv[3] + ".tiff")
            run("rm -f SLC_L/" + sys.argv[3] + ".xml")
            run("rm -f SLC_L/" + sys.argv[3] + ".EOF")

            run("rm -f SLC_H/" + aligned + ".PRM*")
            run("rm -f SLC_H/" + aligned + ".SLC")
            run("rm -f SLC_H/" + aligned + ".LED")
     
            run("rm -f SLC_H/" + sys.argv[3] + ".tiff")
            run("rm -f SLC_H/" + sys.argv[3] + ".xml")
            run("rm -f SLC_H/" + sys.argv[3] + ".EOF")

def P2P2FocusAlign(SAT, master, aligned, skip_master, iono):
     
    print('P2P 2: focus and align SLC images')
    print("P2P 2: ALIGN.CSH - START")
    print('P2P 2: entering directory SLC/')
    
    if SAT != 'S1_TOPS':
         
        print("P2P 2: if SAT is not S1_TOPS")
        if SAT == "ERS" or SAT == "ENVI" or SAT == "ALOS" or SAT == "CSK_RAW":
            if skip_master == 0 or skip_master == 2:
                run("cp ../raw/" + master + ".PRM .")
                run("ln -sf ../raw/" + master + ".raw .")
                run("ln -sf ../raw/" + master + ".LED .")

            if skip_master == 0 or skip_master == 1:
                run("cp ../raw/" + aligned + ".PRM .")
                run("ln -sf ../raw/" + aligned + ".raw .")
                run("ln -sf ../raw/" + aligned + ".LED .")
                
                if iono == 1:
                    # set chirp extension to zero for ionospheric phase estimation.
                    replace_strings(master+".PRM", "fd1", "fd1 = 0.0000")
                    replace_strings(master+".PRM", "chirp_ext", "chirp_ext = 0")
                    
                    replace_strings(aligned+".PRM", "fd1", "fd1 = 0.0000")
                    replace_strings(aligned+".PRM", "chirp_ext", "chirp_ext = 0")
        else:
            run("cp ../raw/" + master + ".PRM .")
            run("ln -sf ../raw/" + master + ".SLC .")
            run("ln -sf ../raw/" + master + ".LED .")

            run("cp ../raw/" + aligned + ".PRM .")
            run("ln -sf ../raw/" + aligned + ".SLC .")
            run("ln -sf ../raw/" + aligned + ".LED .")

        if SAT == "ERS" or SAT == "ENVI" or SAT == "ALOS" or SAT == "CSK_RAW":
             
            print('P2P 2: calling sarp for SAT==ERS/ENVI/ALOS/CSK_RAW')
            if skip_master == 0 or skip_master == 2:
                run("sarp " + master + ".PRM")
            if skip_master == 0 or skip_master == 1:
                run("sarp " + aligned + ".PRM")
       
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
                os.chdir("../SLC_L")
                wl1 = grep_value("../SLC/params1", "low_wavelength", 3)
                cmd = "cp ../SLC/" + master + ".PRM ."
                run(cmd)
                cmd = "ln -sf ../raw" + master + ".LED ."
                run(cmd)
                replace_strings(master+".PRM", "wavelength", "radar_wavelength = "+wl1)
                
                os.chdir("../SLC_H")
                wh1 = grep_value("../SLC/params1", "low_wavelength", 3)
                cmd = "cp ../SLC/" + master + ".PRM ."
                run(cmd)
                cmd = "ln -sf ../raw" + master + ".LED ."
                run(cmd)
                replace_strings(master+".PRM", "wavelength", "radar_wavelength = "+wh1)
                
                os.chdir("../SLC")
            
            if skip_master == 0 or skip_master == 1:
                file_path = f"../raw/ALOS_fbd2fbs_log_{aligned}"
                if check_file_report(file_path):
                    run("split_spectrum " + aligned + ".PRM 1 > params2")
                else:
                    run("split_spectrum " + aligned + ".PRM > params2")
                
                cmd = "mv SLCH ../SLC_H/" + aligned + ".SLC"
                run(cmd)
                cmd = "mv SLCL ../SLC_L/" + aligned + ".SLC"
                run(cmd)
                
                os.chdir("../SLC_L")
                wl2 = grep_value("../SLC/params2", "low_wavelength", 3)
                cmd = "cp ../SLC/" + aligned + ".PRM ."
                run(cmd)
                cmd = "ln -sf ../raw" + aligned + ".LED ."
                run(cmd)
                replace_strings(aligned+".PRM", "wavelength", "radar_wavelength = "+wl2)
                
                os.chdir("../SLC_H")
                wh2 = grep_value("../SLC/params2", "low_wavelength", 3)
                cmd = "cp ../SLC/" + aligned + ".PRM ."
                run(cmd)
                cmd = "ln -sf ../raw" + aligned + ".LED ."
                run(cmd)
                replace_strings(aligned+".PRM", "wavelength", "radar_wavelength = "+wh2)   
        # endif (iono == 1)
        #
        if skip_master == 0 or skip_master == 1:
            file_shuttle(aligned+'.PRM', aligned+'.PRM0', 'cp')
            run("SAT_baseline " + master + ".PRM " + aligned + ".PRM0 >> " + aligned + ".PRM")

            if SAT == "ALOS2_SCAN":
                run("xcorr " + master + ".PRM " + aligned + ".PRM -xsearch 32 -ysearch 256 -nx 32 -ny 128")
                # set amedian = `sort -n tmp.dat | awk ' { a[i++]=$1; } END { print a[int(i/2)]; }'`
                # set amax = `echo $amedian | awk '{print $1+3}'`
                # set amin = `echo $amedian | awk '{print $1-3}'`
                # awk '{if($4 > '$amin' && $4 < '$amax') print $0}' < freq_xcorr.dat > freq_alos2.dat
                # fitoffset 2 3 freq_alos2.dat 10 >> $aligned.PRM
            elif SAT == "ERS" or SAT == "ENVI" or SAT == "ALOS" or SAT == "CSK_RAW":
                run("xcorr " + master + ".PRM " + aligned + ".PRM -xsearch 128 -ysearch 128 -nx 20 -ny 50")
                run("fitoffset 3 3 freq_xcorr.dat 18 >> " + aligned + ".PRM")
            else: 
                run("xcorr " + master + ".PRM " + aligned + ".PRM -xsearch 128 -ysearch 128 -nx 20 -ny 50")
                run("fitoffset 2 2 freq_xcorr.dat 18 >> " + aligned + ".PRM")
            
            run("resamp " + master + ".PRM " + aligned + ".PRM " + aligned + ".PRMresamp " + aligned + ".SLCresamp 4")
            delete(aligned + ".SLC")
            file_shuttle(aligned+'.SLCresamp', aligned+'.SLC', 'mv')
            file_shuttle(aligned+'.PRMresamp', aligned+'.PRM', 'cp')
            
            if iono == 1:
                print(" ")
                print("P2P 2: if iono == 1")
                print(" ")
                os.chdir("../SLC_L")
                cmd = "cp " + aligned + ".PRM " + aligned + ".PRM0"
                run(cmd)
                
                if (SAT == "ALOS2_SCAN"):
                    cmd = "ln -sf ../SLC/freq_alos2.dat"
                    run(cmd)
                    cmd = "fitoffset 3 3 freq_xcorr.dat 18 >>" + aligned + ".PRM"
                    run(cmd)
                elif (SAT == "ERS" or SAT == "ENVI" or SAT == "ALOS" or SAT == "CSK_RAW" or SAT == "TSX"):
                    cmd = "ln -sf ../SLC/freq_xcorr.dat"
                    run(cmd)
                    cmd = "fitoffset 3 3 freq_xcorr.dat 18 >>" + aligned + ".PRM"
                    run(cmd)
                else:
                    cmd = "ln -sf ../SLC/freq_alos2.dat"
                    run(cmd)
                    cmd = "fitoffset 2 2 freq_xcorr.dat 18 >>" + aligned + ".PRM"
                    run(cmd)
                
                cmd = "resamp "+master+".PRM "+aligned+".PRM "+aligned+".PRMresamp "+aligned+".SLCresamp 4"                
                run(cmd)
                delete(aligned + ".SLC")
                file_shuttle(aligned+".SLCresamp", aligned+".SLC", "mv")
                file_shuttle(aligned+".PRMresamp", aligned+".PRM", "cp")
                
                os.chdir("../SLC_H")
                file_shuttle(aligned+".PRM ", aligned+".PRM0", "cp")
                if (SAT == "ALOS2_SCAN"):
                    cmd = "ln -sf ../SLC/freq_alos2.dat"
                    run(cmd)
                    cmd = "fitoffset 3 3 freq_xcorr.dat 18 >>" + aligned + ".PRM"
                    run(cmd)
                elif (SAT == "ERS" or SAT == "ENVI" or SAT == "ALOS" or SAT == "CSK_RAW"):
                    cmd = "ln -sf ../SLC/freq_xcorr.dat"
                    run(cmd)
                    cmd = "fitoffset 3 3 freq_xcorr.dat 18 >>" + aligned + ".PRM"
                    run(cmd)
                else:
                    cmd = "ln -sf ../SLC/freq_alos2.dat"
                    run(cmd)
                    cmd = "fitoffset 2 2 freq_xcorr.dat 18 >>" + aligned + ".PRM"
                    run(cmd)
                    
                cmd = "resamp "+master+".PRM "+aligned+".PRM "+aligned+".PRMresamp "+aligned+".SLCresamp 4"                
                run(cmd)
                delete(aligned + ".SLC")
                file_shuttle(aligned+".SLCresamp", aligned+".SLC", "mv")
                file_shuttle(aligned+".PRMresamp", aligned+".PRM", "cp")
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
                run("align_tops.csh "+sys.argv[1]+" "+sys.argv[1]+".EOF "+sys.argv[2]+" "+sys.argv[2]+".EOF dem.grd 1")
            elif (skip_master == 1):
                cmd = "align_tops.csh "+sys.argv[1]+" 0 "+sys.argv[2]+" "+sys.argv[2]+".EOF dem.grd 1"
                run(cmd)
            elif (skip_master == 2):
                cmd = "align_tops.csh "+sys.argv[1]+" "+sys.argv[1]+".EOF "+sys.argv[2]+" 0 dem.grd 1"
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
                cmd = "align_tops.csh "+sys.argv[1]+" "+sys.argv[1]+".EOF "+sys.argv[2]+" "+sys.argv[2]+".EOF dem.grd 1"
                run(cmd)
            elif (skip_master == 1):
                cmd = "align_tops.csh "+sys.argv[1]+" 0 "+sys.argv[2]+" "+sys.argv[2]+".EOF dem.grd 1"
                run(cmd)
            elif (skip_master == 2):
                cmd = "align_tops.csh "+sys.argv[1]+" "+sys.argv[1]+".EOF "+sys.argv[2]+" 0 dem.grd 1"
                run(cmd)
            
            if (skip_master == 0 or skip_master == 2):
                wl1 = grep_value("low_wavelength", "../SLC/params1", 3)
                replace_strings(master+".PRM", "wavelength", "radar_wavelength = "+wl1)
            if (skip_master == 0 or skip_master == 1):
                wl2 = grep_value("low_wavelength", "../SLC/params2", 3)
                replace_strings(aligned+".PRM", "wavelength", "radar_wavelength = "+wl2)
            
            os.chdir("../SLC")
            
def P2P2RegionCut(master, aligned, skip_master, iono):
    print("P2P 2: region_cut !=-999 ")
    print("P2P 2: cutting SLC image to " + str(region_cut))
    if skip_master == 0 or skip_master == 2:
        run("cut_slc " + master + ".PRM junk1 " + str(region_cut))
        run("mv junk1.PRM " + master + ".PRM")
        run("mv junk1.SLC " + master + ".SLC")

    if skip_master == 0 or skip_master == 1:
        run("cut_slc " + aligned + ".PRM junk2 " + str(region_cut))
        run("mv junk2.PRM " + aligned + ".PRM")
        run("mv junk2.SLC " + aligned + ".SLC")
    
    if iono == 1:
        print('P2P 2: iono = 1')
        print('P2P 2: entering SLC_L')
        os.chdir("../SLC_L")
        if (skip_master == 0 or skip_master == 2):
            run("cut_slc "+master+".PRM junk1 "+str(region_cut))
            file_shuttle("junk1.PRM", master+".PRM", "mv")
            file_shuttle("junk1.SLC", master+".SLC", "mv")
        if (skip_master == 0 or skip_master == 1):
            run("cut_slc "+aligned+".PRM junk2 "+str(region_cut))
            file_shuttle("junk2.PRM", master+".PRM", "mv")
            file_shuttle("junk2.SLC", master+".SLC", "mv")
        
        # redo everything for ../SLC_H
        print('P2P 2: entering SLC_H')
        os.chdir("../SLC_H")
        if (skip_master == 0 or skip_master == 2):
            run("cut_slc "+master+".PRM junk1 "+str(region_cut))
            file_shuttle("junk1.PRM", master+".PRM", "mv")
            file_shuttle("junk1.SLC", master+".SLC", "mv")
        if (skip_master == 0 or skip_master == 1):
            run("cut_slc "+aligned+".PRM junk2 "+str(region_cut))
            file_shuttle("junk2.PRM", master+".PRM", "mv")
            file_shuttle("junk2.SLC", master+".SLC", "mv")

def P2P3MakeTopo(master, aligned, topo_phase, topo_interp_mode, shift_topo):
    print('P2P 3: start from make topo_ra')
    run("cleanup topo")
    
    print('P2P 3: make topo_ra if there is dem.grd')
    if topo_phase == 1: 
        print(" ")
        print('P2P 3: topo_phase=1')
        print("P2P 3: DEM2TOPO_RA.CSH - START")
        print("P2P 3: USER SHOULD PROVIDE DEM FILE")
        
        print('P2P 3: entering directory topo/')
        os.chdir("topo")
        file_shuttle('../SLC/'+master+'.PRM', 'master.PRM', 'cp')
        run("ln -sf ../raw/" + master + ".LED .")
        
        if check_file_report('dem.grd')==True:
            if topo_interp_mode==1:
                run("dem2topo_ra master.PRM dem.grd 1")
            else:
                run("dem2topo_ra master.PRM dem.grd")
        else:
            print("no DEM file found: dem.grd")
            sys.exit(1)
        
        print('P2P 3: exiting directory topo/')
        os.chdir('..')
        print('P2P 3: DEM2TOPO_RA.CSH - END')
        print('P2P 3: shift topo_ra')
        if shift_topo == 1:
            print('P2P 3: OFFSET_TOPO - START')
            print('P2P 3: entering directory SLC/')
            os.chdir('SLC')
            rng_samp_rate = grep_value(master+".PRM", "rng_samp_rate", 3)
            run("gmt grdinfo ../topo/topo_ra.grd > tmp.txt")
            rng = grep_value("tmp.txt", "x_inc", 7)
            run('slc2amp.csh '+master+'.PRM '+str(rng)+' amp-'+master+'.grd')
            print('P2P 3: exiting SLC/')
            os.chdir("..")
            
            print('P2P 3: entering topo/')
            os.chdir("topo")
            file_shuttle("../SLC/amp-"+master+".grd", ".", "link")
            run('offset_topo amp-'+master+'.grd topo_ra.grd 0 0 7 topo_shift.grd')
            print('P2P 3: exiting topo/')
            os.chdir("..")
            print("P2P 3: OFFSET_TOPO - END")
        elif shift_topo == 0:
            print("P2P 3: NO TOPO_RA SHIFT ")
        else:
            print("P2P 3: wrong parameter: shift_topo " + shift_topo)
            sys.exit(1)
            
    elif topo_phase == 0:
        print("P2P 3: NO TOPO_RA is SUBSTRACTED")
    else:
        print("P2P 3: wrong parameter: topo_phase " + topo_phase)
        sys.exit(1)

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

def P2P4MakeFilterInterferograms(ref, rep, topo_phase, shift_topo, range_dec, azimuth_dec, 
                                dec, filter, compute_phase_gradient, iono, iono_dsamp):

    print('P2P 4: start from make and filter interferograms')
    run('mkdir -p intf')
    run('cleanup intf')
    
    print('P2P 4: INTF.CSH, FILTER.CSH - START')
    print('P2P 4: entering intf/')
    os.chdir('intf')
    intfSubDirName = getIntfSubDirName(ref, rep)
    run('mkdir -p '+intfSubDirName)
    os.chdir(intfSubDirName)   

    run('ln -sf ../../SLC/'+ref + '.LED .')
    run('ln -sf ../../SLC/'+rep + '.LED .')
    run('ln -sf ../../SLC/'+ref + '.SLC .')
    run('ln -sf ../../SLC/'+rep + '.SLC .')
    run('cp ../../SLC/' + ref + '.PRM .')
    run('cp ../../SLC/' + rep + '.PRM .')
    
    if topo_phase == 1:
        if shift_topo == 1:
            run('ln -s ../../topo/topo_shift.grd .')
            run('intf ' + ref + '.PRM ' + rep + '.PRM -topo topo_shift.grd')
            runFilter(ref, rep, filter, dec, range_dec, azimuth_dec, compute_phase_gradient)
        else:
            run('ln -s ../../topo/topo_ra.grd .')
            run('intf ' + ref + '.PRM ' + rep + '.PRM -topo topo_ra.grd')
            runFilter(ref, rep, filter, dec, range_dec, azimuth_dec, compute_phase_gradient)
    else:
        print('P2P 4: NO TOPOGRAPHIC PHASE REMOVAL PORFORMED')
        run('intf '+ref+'.PRM '+rep+'.PRM')
        runFilter(ref, rep, filter, dec, range_dec, azimuth_dec, compute_phase_gradient)
        
    os.chdir('../..')
    
    if (iono == 1):
        if os.path.exists('iono_phase'):
             shutil.rmtree('iono_phase')
        os.makedirs('iono_phase')
        os.chdir('iono_phase')
        directories = ['intf_o', 'intf_h', 'intf_l', 'iono_correction']
        for directory in directories:
            os.makedirs(directory, exist_ok=True)
        new_incx = int(range_dec) * int(iono_dsamp)
        new_incy = int(azimuth_dec) * int(iono_dsamp)
        os.chdir('intf_h')
        files = glob.glob('../../SLC_H/*.SLC')
        for file in files:
            file_shuttle(file, '.', 'link')
            
        files = glob.glob('../../SLC_H/*.LED')
        for file in files:
            file_shuttle(file, '.', 'link')
            
        files = glob.glob('../../SLC_H/*.PRM')
        for file in files:
            file_shuttle(file, '.', 'cp')

        files = glob.glob('../../SLC/params*')
        for file in files:
            file_shuttle(file, '.', 'cp')
        
        if (topo_phase == 1):
            if (shift_topo == 1):
                file_shuttle('../../topo/topo_shift.grd', '.', 'link')
                run('intf '+ref+'.PRM '+rep+'.PRM -topo topo_shift.grd')
                run('filter '+ref+'.PRM '+rep+'.PRM 500 '+dec+' '+new_incx+' '+new_incy)
            else:
                file_shuttle('../../topo/topo_ra.grd', '.', 'link')
            
                run('intf '+ref+'.PRM '+rep+'.PRM -topo topo_ra.grd')
                run('filter '+ref+'.PRM '+rep+'.PRM 500 '+dec+' '+new_incx+' '+new_incy)
        else:
            print('NO TOPOGRAPHIC PHASE REMOVAL PORFORMED')
            run('intf '+ref+'.PRM '+rep+'.PRM')
            run('filter '+ref+'.PRM '+rep+'.PRM 500 '+dec+' '+new_incx+' '+new_incy)
        
        file_shuttle('phase.grd', 'phasefilt.grd', 'cp')
        
        if (iono_skip_est == 0):
            if (mask_water == 1 or switch_land == 1):
                output = subprocess.check_output('gmt grdinfo phase.grd -I-', shell=True)
                rcut = output[2:20].decode('utf-8')
                
                os.chdir('../../topo')
                run('landmask '+rcut)
                os.chdir('../iono_phase/intf_h')
                file_shuttle('../../topo/landmask_ra.grd', '.', 'link')

            run('snaphu_interp.csh 0.05 0')
        os.chdir('..')
        os.chdir('intf_h')
        files = glob.glob('../../SLC_L/*.SLC')
        for file in files:
            file_shuttle(file, '.', 'link')

        files = glob.glob('../../SLC_L/*.LED')
        for file in files:
            file_shuttle(file, '.', 'link')
            
        files = glob.glob('../../SLC_L/*.PRM')
        for file in files:
            file_shuttle(file, '.', 'cp')

        files = glob.glob('../../SLC/params*')
        for file in files:
            file_shuttle(file, '.', 'cp')
        
        if (topo_phase == 1):
            if (shift_topo == 1):
                file_shuttle('../../topo/topo_shift.grd', '.', 'link')
            
                cmd = 'intf '+ref+'.PRM '+rep+'.PRM -topo topo_shift.grd'
                run(cmd)
                
                cmd = 'filter '+ref+'.PRM '+rep+'.PRM 500 '+dec+' '+new_incx+' '+new_incy
                run(cmd)
            
            else:
                file_shuttle('../../topo/topo_ra.grd', '.', 'link')
            
                cmd = 'intf '+ref+'.PRM '+rep+'.PRM -topo topo_ra.grd'
                run(cmd)
                
                cmd = 'filter '+ref+'.PRM '+rep+'.PRM 500 '+dec+' '+new_incx+' '+new_incy
                run(cmd)
            #endif (shift_topo == 1)
        
        else:
            print('P2P 4: NO TOPOGRAPHIC PHASE REMOVAL PORFORMED')
            
            cmd = 'intf '+ref+'.PRM '+rep+'.PRM'
            run(cmd)
            
            cmd = 'filter '+ref+'.PRM '+rep+'.PRM 500 '+dec+' '+new_incx+' '+new_incy
            run(cmd)
        #endif (topo_phase == 1)
        
        file_shuttle('phase.grd', 'phasefilt.grd', 'cp')
        
        if (iono_skip_est == 0):
            if (mask_water == 1 or switch_land == 1):
                file_shuttle('../../topo/landmask_ra.grd', '.', 'link')
            #endif (mask_water == 1 or switch_land == 1)
            
            cmd = 'snaphu_interp.csh 0.05 0'
            run(cmd)
            
        os.chdir('..')
        #endif iono_skip_est == 0
        
        # redo everything for intf_o
         
        
        os.chdir('intf_o')
        files = glob.glob('../../SLC/*.SLC')
        for file in files:
            file_shuttle(file, '.', 'link')
            
        files = glob.glob('../../SLC/*.LED')
        for file in files:
            file_shuttle(file, '.', 'link')

        files = glob.glob('../../SLC/*.PRM')
        for file in files:
            file_shuttle(file, '.', 'cp')
        
        if (topo_phase == 1):
            if (shift_topo == 1):
                file_shuttle('../../topo/topo_shift.grd', '.', 'link')
            
                cmd = 'intf '+ref+'.PRM '+rep+'.PRM -topo topo_shift.grd'
                run(cmd)
                
                cmd = 'filter '+ref+'.PRM '+rep+'.PRM 500 '+dec+' '+new_incx+' '+new_incy
                run(cmd)
            
            else:
                file_shuttle('../../topo/topo_ra.grd', '.', 'link')
            
                cmd = 'intf '+ref+'.PRM '+rep+'.PRM -topo topo_ra.grd'
                run(cmd)
                
                cmd = 'filter '+ref+'.PRM '+rep+'.PRM 500 '+dec+' '+new_incx+' '+new_incy
                run(cmd)
            #endif (shift_topo == 1)
        
        else:
            print('NO TOPOGRAPHIC PHASE REMOVAL PORFORMED')
            
            cmd = 'intf '+ref+'.PRM '+rep+'.PRM'
            run(cmd)
            
            cmd = 'filter '+ref+'.PRM '+rep+'.PRM 500 '+dec+' '+new_incx+' '+new_incy
            run(cmd)
        #endif (topo_phase == 1)
        
        file_shuttle('phase.grd', 'phasefilt.grd', 'cp')
        
        if (iono_skip_est == 0):
            if (mask_water == 1 or switch_land == 1):
                file_shuttle('../../topo/landmask_ra.grd', '.', 'link')
            #endif (mask_water == 1 or switch_land == 1)
            
            cmd = 'snaphu_interp.csh 0.05 0'
            run(cmd)
            
        os.chdir('../iono_correction')
         
        #endif iono_skip_est == 0
        
        if (iono_skip_est == 0):
            cmd = 'estimate_ionospheric_phase.csh ../intf_h ../intf_l ../intf_o ../../intf/'+intfSubDirName \
                    +' '+iono_filt_rng+' '+iono_filt_azi
            run(cmd)
            os.chdir('../../intf/'+intfSubDirName)
            file_shuttle('phasefilt.grd', 'phasefilt_non_corrected.grd', 'mv')
            run('grdsample ../../iono_phase/iono_correction/ph_iono_orig.grd -Rphasefilt_non_corrected.grd -Gph_iono.grd')
            run('grdmath phasefilt_non_corrected.grd ph_iono.grd SUB PI ADD 2 PI MUL MOD PI SUB = phasefilt.grd')
            run('grdimage phasefilt.grd -JX6.5i -Bxaf+lRange -Byaf+lAzimuth -BWSen -Cphase.cpt -X1.3i -Y3i -P -K > phasefilt.ps')
            run('psscale -Rphasefilt.grd -J -DJTC+w5i/0.2i+h -Cphase.cpt -Bxa1.57+l"Phase" -By+lrad -O >> phasefilt.ps')
            run('gmt psconvert -Tf -P -A -Z phasefilt.ps')
        
        os.chdir('../../')
    print('INTF.CSH, FILTER.CSH - END')

def runFilter(ref, rep, filter, dec, range_dec, azimuth_dec, compute_phase_gradient):
    if range_dec == -999 and azimuth_dec == -999:
        run('filter '+ref+'.PRM '+rep+'.PRM '+str(filter)+' '+str(dec)+' '+str(compute_phase_gradient))
    else:
        run('filter '+ref+'.PRM '+rep+'.PRM '+str(filter)+' '+str(dec)+' '+str(range_dec)+' '+str(azimuth_dec)+' '+str(compute_phase_gradient))

def getIntfSubDirName(ref, rep):
    ref_id = int(float(grep_value("../raw/"+ref+".PRM", "SC_clock_start", 3)))
    rep_id = int(float(grep_value("../raw/"+rep+".PRM", "SC_clock_start", 3)))
    intfSubDirName = str(ref_id)+'_'+str(rep_id)
    return intfSubDirName
    
def P2P5Unwrap(ref, rep, threshold_snaphu, mask_water, switch_land, near_interp):
    if threshold_snaphu != 0:
        print('P2P 5: threshold_snaphu != 0')
        print('P2P 5: entering intf/')
        os.chdir("intf")
        intfSubDirName = getIntfSubDirName(ref, rep)
        os.chdir(intfSubDirName)
    
        print('P2P 5: landmask')
        if mask_water == 1 or switch_land == 1:
            r_cut = "gmt grdinfo phase.grd -I- | cut -c3-20"
            os.chdir("../../topo")
            if check_file_report(landmask_ra.grd) == False:
                run("landmask " + r_cut)
            os.chdir("../intf")
            os.chdir(intfSubDirName)
            run("ln -sf ../../topo/landmask_ra.grd .")
        print('P2P 5: SNAPHU.CSH - START')
        print('P2P 5: threshold_snaphu = ', threshold_snaphu)
        if near_interp == 1:
            run("snaphu_interp.csh " + str(threshold_snaphu) + " " + str(defomax))
        else:
            run("snaphu.csh " + str(threshold_snaphu) + " " + str(defomax))
        print('P2P 5: SNAPHU.CSH - END')
        os.chdir("../..")
    else:
        print('P2P 5: SKIP UNWRAP PAHSE') 

def P2P6Geocode(ref, rep, threshold_geocode, topo_phase):
    if threshold_geocode != 0:
        print('P2P 6: threshold_geocode != 0')
        print('P2P 6: entering intf/')
        os.chdir("intf")
        intfSubDirName = getIntfSubDirName(ref, rep)
        os.chdir(intfSubDirName)
        
        print('P2P 6: GEOCODE.CSH - START')
        
        if check_file_report("rain.grd") == True: 
            delete("rain.grd")
        if check_file_report("ralt.grd") == True:
            delete("ralt.grd")
        if check_file_report('trans.dat') == True:
            delete('trans.dat')
        if topo_phase == 1:
            run('ln -sf ../../topo/trans.dat .')
            print('threshold_geocode: ', threshold_geocode)
            run('geocode ' + str(threshold_geocode))
        else:
            print('P2P 6: topo_ra is needed to geocode')
            sys.exit(1)

        print('P2P 6: GEOCODE.CSH - END')
        os.chdir('../..')
    else:
        print('P2P 6: SKIP_GEOCODE')
        
        
