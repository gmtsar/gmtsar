#!/bin/csh -f
#       $Id$
#
#  Xiaohua Xu, Jan, 2018
#
#  Automatically perform two-path processing on raw(1.0)/SLC(1.1) data
#  

  if ($#argv != 3 && $#argv != 4) then
    echo ""
    echo "Usage: p2p_processing.csh SAT master_image aligned_image [configuration_file] "
    echo ""
    echo "Example: p2p_processing.csh ALOS IMG-HH-ALPSRP055750660-H1.0__A IMG-HH-ALPSRP049040660-H1.0__A [config.alos.txt]"
    echo ""
    echo "    Put the data and orbit files in the raw folder, put DEM in the topo folder"
    echo "    The SAT needs to be specified, choices with in ERS, ENVI, ALOS, ALOS_SLC, ALOS2, ALOS2_SCAN"
    echo "    S1_STRIP, S1_TOPS, ENVI_SLC, CSK_RAW, CSK_SLC, TSX, RS2, GF3"
    echo ""
    echo "    Make sure the files from the same date have the same stem, e.g. aaaa.tif aaaa.xml aaaa.cos aaaa.EOF, etc"
    echo ""
    echo "    If the configuration file is left blank, the program will generate one "
    echo "    with default parameters "
    echo ""
    exit 1
  endif
    
# start 
#  Make sure the config exist
  if ($#argv == 4) then 
    if(! -f $4 ) then
      echo " no configure file: "$4
      echo " Leave it blank to generate config file with default values."
      exit 1
    endif
  endif
  
#
#  Read parameters from the configure file
#
  set SAT = `echo $1`
  if ($#argv == 4) then
    set conf = `echo $4`
  else
    pop_config.csh $SAT > config.$SAT.txt
    set conf = `echo "config.$SAT.txt"`
  endif
  # conf may need to be changed later on
  set stage = `grep proc_stage $conf | awk '{print $3}'`
  set s_stages = `grep skip_stage $conf | awk '{print $3}' | awk -F, '{print $1,$2,$3,$4,$5,$6}'`
  set skip_1 = 0
  set skip_2 = 0 
  set skip_3 = 0 
  set skip_4 = 0 
  set skip_5 = 0 
  set skip_6 = 0 
  foreach line (`echo $s_stages`)
    if ($line == 1) set skip_1 = 1
    if ($line == 2) set skip_2 = 1
    if ($line == 3) set skip_3 = 1
    if ($line == 4) set skip_4 = 1
    if ($line == 5) set skip_5 = 1
    if ($line == 6) set skip_6 = 1
  end
  if ("x$s_stages" != "x") then
    echo ""
    echo "Skipping stage $s_stages ..."
  endif
  set skip_master = `grep skip_master $conf | awk '{print $3}'`
  if ($skip_master == "") set skip_master = 0
  if ($skip_master == 2) then
    set skip_4 = 1
    set skip_5 = 1
    set skip_6 = 1
    echo "Skipping stage 4,5,6 as skip_master is set to 2 ..."
  endif
  set num_patches = `grep num_patches $conf | awk '{print $3}'`
  set near_range = `grep near_range $conf | awk '{print $3}'`
  set earth_radius = `grep earth_radius $conf | awk '{print $3}'`
  set fd = `grep fd1 $conf | awk '{print $3}'`
  set topo_phase = `grep topo_phase $conf | awk '{print $3}'`
  set topo_interp_mode = `grep topo_interp_mode $conf | awk '{print $3}'`
  if ( "x$topo_interp_mode" == "x" ) then
    set topo_interp_mode = 0
  endif
  set shift_topo = `grep shift_topo $conf | awk '{print $3}'`
  set switch_master = `grep switch_master $conf | awk '{print $3}'`
  set filter = `grep filter_wavelength $conf | awk '{print $3}'` 
  set compute_phase_gradient = `grep compute_phase_gradient $conf | awk '{print $3}'` 
  set iono = `grep correct_iono $conf | awk '{print $3}'`
  if ( "x$iono" == "x" ) then 
    set iono = 0
  endif
  set iono_filt_rng = `grep iono_filt_rng $conf | awk '{print $3}'`
  set iono_filt_azi = `grep iono_filt_azi $conf | awk '{print $3}'`
  set iono_dsamp = `grep iono_dsamp $conf | awk '{print $3}'`
  set iono_skip_est = `grep iono_skip_est $conf | awk '{print $3}'`
  set spec_div = `grep spec_div $conf | awk '{print $3}'`
  if ( "x$spec_div" == "x" ) then
    set spec_div = 0
  endif
  set spec_mode = `grep spec_mode $conf | awk '{print $3}'`
  #  set filter = 200
  #  echo " "
  #  echo "WARNING filter wavelength was not set in config.txt file"
  #  echo "        please specify wavelength (e.g., filter_wavelength = 200)"
  #  echo "        remove filter1 = gauss_alos_200m"
  #endif
  set dec = `grep dec_factor $conf | awk '{print $3}'` 
  set threshold_snaphu = `grep threshold_snaphu $conf | awk '{print $3}'`
  set threshold_geocode = `grep threshold_geocode $conf | awk '{print $3}'`
  set region_cut = `grep region_cut $conf | awk '{print $3}'`
  set mask_water = `grep mask_water $conf | awk '{print $3}'`
  set switch_land = `grep switch_land $conf | awk '{print $3}'`
  set defomax = `grep defomax $conf | awk '{print $3}'`
  set range_dec = `grep range_dec $conf | awk '{print $3}'`
  set azimuth_dec = `grep azimuth_dec $conf | awk '{print $3}'`
  set SLC_factor = `grep SLC_factor $conf | awk '{print $3}'`
  set near_interp = `grep near_interp $conf | awk '{print $3}'`
  set master = ` echo $2 `
  set aligned =  ` echo $3 `
  echo ""
  

#
#  combine preprocess parameters
#  
  set commandline = ""
  if (!($earth_radius == "")) then 
    set commandline = "$commandline -radius $earth_radius"
  endif
  if (!($num_patches == "")) then  
    set commandline = "$commandline -npatch $num_patches"
  endif
  if (!($SLC_factor == "")) then  
    set commandline = "$commandline -SLC_factor $SLC_factor"
  endif
  if (!($spec_div == 0)) then
    set commandline = "$commandline -ESD $spec_mode"
  endif
  if (!($skip_master == "")) then
    set commandline = "$commandline -skip_master $skip_master"
  endif
  


#############################
# 1 - start from preprocess #
#############################
#
#   make sure the files exist
#
  if ($stage == 1 && $skip_1 == 0) then
    echo ""
    echo "PREPROCESS - START"
    echo ""
    echo "Working on images $master $aligned ..."
    if ($SAT == "ALOS" || $SAT == "ALOS2" || $SAT == "ALOS_SLC" || $SAT == "ALOS2_SCAN") then
      if(! -f raw/$master ) then
        echo " no file  raw/"$master
        exit
      endif
      if(! -f raw/$aligned ) then
        echo " no file  raw/"$aligned
        exit
      endif
    else if ($SAT == "ENVI_SLC") then
      if(! -f raw/$master.N1 && ! -f raw/$master.E1 && ! -f raw/$master.E2) then
        echo " no file  raw/"$master
        exit
      endif
      if(! -f raw/$aligned.N1 && ! -f raw/$aligned.E1 && ! -f raw/$aligned.E2 ) then
        echo " no file  raw/"$aligned
        exit
      endif
    else if ($SAT == "ERS") then
      if(! -f raw/$master.dat ) then
        echo " no file  raw/"$master.dat
        exit
      endif
      if(! -f raw/$aligned.dat ) then
        echo " no file  raw/"$aligned.dat
        exit
      endif
      if(! -f raw/$master.ldr ) then
        echo " no file  raw/"$master.ldr
        exit
      endif
      if(! -f raw/$aligned.ldr ) then
        echo " no file  raw/"$aligned.ldr
        exit
      endif
    else if ($SAT == "ENVI") then
      if(! -f raw/$master.baq ) then
        echo " no file  raw/"$master.baq
        exit
      endif
      if(! -f raw/$aligned.baq ) then
        echo " no file  raw/"$aligned.baq
        exit
      endif
    else if ($SAT == "S1_STRIP" || $SAT == "S1_TOPS") then
      if(! -f raw/$master.xml ) then
        echo " no file  raw/"$master".xml"
        exit
      endif
      if(! -f raw/$master.tiff ) then
        echo " no file  raw/"$master".tiff"
        exit
      endif
      if(! -f raw/$aligned.xml ) then
        echo " no file  raw/"$aligned".xml"
        exit
      endif
      if(! -f raw/$aligned.tiff ) then
        echo " no file  raw/"$aligned".tiff"
        exit
      endif
      if ($SAT == "S1_TOPS") then
        if(! -f raw/$master.EOF ) then
          echo " no file  raw/"$master".EOF"
        endif
        if(! -f raw/$aligned.EOF ) then
          echo " no file  raw/"$aligned".EOF"
        endif
      endif
    else if ($SAT == "CSK_RAW" || $SAT == "CSK_SLC") then
      if(! -f raw/$master.h5 ) then
        echo " no file  raw/"$master".h5"
        exit
      endif
      if(! -f raw/$aligned.h5 ) then
        echo " no file  raw/"$aligned".h5"
        exit
      endif
    else if ($SAT == "RS2") then
      if(! -f raw/$master.xml ) then
        echo " no file  raw/"$master".xml"
        exit
      endif
      if(! -f raw/$master.tif ) then
        echo " no file  raw/"$master".tif"
        exit
      endif
      if(! -f raw/$aligned.xml ) then
        echo " no file  raw/"$aligned".xml"
        exit
      endif
      if(! -f raw/$aligned.tif ) then
        echo " no file  raw/"$aligned".tif"
        exit
      endif
    else if ($SAT == "TSX") then
      if(! -f raw/$master.xml ) then
        echo " no file  raw/"$master".xml"
        exit
      endif
      if(! -f raw/$aligned.xml ) then
        echo " no file  raw/"$aligned".xml"
        exit
      endif
      if(! -f raw/$master.cos ) then
        echo " no file  raw/"$master".cos"
        exit
      endif
      if(! -f raw/$aligned.cos ) then
        echo " no file  raw/"$aligned".cos"
        exit
      endif
    else if ($SAT == "GF3") then
      if(! -f raw/$master.xml ) then
        echo " no file  raw/"$master".xml"
        exit
      endif
      if(! -f raw/$aligned.xml ) then
        echo " no file  raw/"$aligned".xml"
        exit 
      endif
      if(! -f raw/$master.tiff ) then
        echo " no file  raw/"$master".tiff"
        exit 
      endif
      if(! -f raw/$aligned.tiff ) then
        echo " no file  raw/"$aligned".tiff"
        exit
      endif
    endif

#
#  Start preprocessing
#
    if ($SAT == "S1_TOPS") then
      set master = `echo $master | awk '{ print "S1_"substr($1,16,8)"_"substr($1,25,6)"_F"substr($1,7,1)}'`
      set aligned = `echo $aligned | awk '{ print "S1_"substr($1,16,8)"_"substr($1,25,6)"_F"substr($1,7,1)}'`
    endif
    if ($skip_master == 0 || $skip_master == 2) then
      rm -f raw/$master.PRM*
      rm -f raw/$master.SLC
      rm -f raw/$master.LED
    endif
    if ($skip_master == 0 || $skip_master == 1) then
      rm -f raw/$aligned.PRM*
      rm -f raw/$aligned.SLC
      rm -f raw/$aligned.LED
    endif
    if ($SAT == "S1_TOPS") then
      set master = ` echo $2 `
      set aligned = `echo $3`
    endif
    cd raw
    
    echo "pre_proc.csh $SAT $master $aligned $commandline"
    pre_proc.csh $SAT $master $aligned $commandline   
        
    cd ..
    echo " "
    echo "PREPROCESS - END"
    echo ""
  endif
 
#############################################
# 2 - start from focus and align SLC images #
#############################################
# 

  mkdir -p SLC
  if ($iono == 1) then
    mkdir -p SLC_L 
    mkdir -p SLC_H
  endif

  if ($SAT == "S1_TOPS") then
    set master = `echo $master | awk '{ print "S1_"substr($1,16,8)"_"substr($1,25,6)"_F"substr($1,7,1)}'`
    set aligned = `echo $aligned | awk '{ print "S1_"substr($1,16,8)"_"substr($1,25,6)"_F"substr($1,7,1)}'`
  endif

  if ($stage <= 2 && $skip_2 == 0) then 
    #cleanup.csh SLC
    if ($skip_master == 0 || $skip_master == 2) then
      rm -f SLC/$master.PRM*
      rm -f SLC/$master.SLC
      rm -f SLC/$master.LED
    endif
    if ($skip_master == 0 || $skip_master == 1) then
      rm -f SLC/$aligned.PRM*
      rm -f SLC/$aligned.SLC
      rm -f SLC/$aligned.LED
    endif
    if ($iono == 1) then
      if ($skip_master == 0 || $skip_master == 2) then
        rm -f SLC/$2.tiff
        rm -f SLC/$2.xml
        rm -f SLC/$2.EOF
        rm -f SLC_L/$master.PRM*
        rm -f SLC_L/$master.SLC
        rm -f SLC_L/$master.LED
        rm -f SLC_L/$2.tiff
        rm -f SLC_L/$2.xml
        rm -f SLC_L/$2.EOF
        rm -f SLC_H/$master.PRM*
        rm -f SLC_H/$master.SLC
        rm -f SLC_H/$master.LED
        rm -f SLC_H/$2.tiff
        rm -f SLC_H/$2.xml
        rm -f SLC_H/$2.EOF
      endif
      if ($skip_master == 0 || $skip_master == 1) then
        rm -f SLC/$3.tiff
        rm -f SLC/$3.xml
        rm -f SLC/$3.EOF
        rm -f SLC_L/$aligned.PRM*
        rm -f SLC_L/$aligned.SLC
        rm -f SLC_L/$aligned.LED
        rm -f SLC_L/$3.tiff
        rm -f SLC_L/$3.xml
        rm -f SLC_L/$3.EOF
        rm -f SLC_H/$aligned.PRM*
        rm -f SLC_H/$aligned.SLC
        rm -f SLC_H/$aligned.LED
        rm -f SLC_H/$3.tiff
        rm -f SLC_H/$3.xml
        rm -f SLC_H/$3.EOF
      endif
    endif


#
# focus and align SLC images 
# 
    echo " "
    echo "ALIGN.CSH - START"
    echo ""
    cd SLC
    if ($SAT != "S1_TOPS") then
      if ($SAT == "ERS" || $SAT == "ENVI" || $SAT == "ALOS" || $SAT == "CSK_RAW") then
        if ($skip_master == 0 || $skip_master == 2) then
          cp ../raw/$master.PRM .
          ln -s ../raw/$master.raw . 
          ln -s ../raw/$master.LED . 
        endif
        if ($skip_master == 0 || $skip_master == 1) then
          cp ../raw/$aligned.PRM .
          ln -s ../raw/$aligned.raw . 
          ln -s ../raw/$aligned.LED . 
          if ($iono == 1) then
            # set chirp extention to zero for ionospheric phase estimation
            sed "s/.*fd1.*/fd1 = 0.0000/g" $master.PRM > tmp
            sed "s/.*chirp_ext.*/chirp_ext = 0/g" tmp > tmp2
            mv tmp2 $master.PRM
            sed "s/.*fd1.*/fd1 = 0.0000/g" $aligned.PRM > tmp
            sed "s/.*chirp_ext.*/chirp_ext = 0/g" tmp > tmp2
            mv tmp2 $aligned.PRM
            rm tmp
          endif
        endif
      else
        cp ../raw/$master.PRM .
        cp ../raw/$aligned.PRM .
        ln -s ../raw/$master.SLC .
        ln -s ../raw/$aligned.SLC .
        ln -s ../raw/$master.LED .
        ln -s ../raw/$aligned.LED .
      endif

      if ($SAT == "ERS" || $SAT == "ENVI" || $SAT == "ALOS" || $SAT == "CSK_RAW") then
        if ($skip_master == 0 || $skip_master == 2) then
          sarp.csh $master.PRM
        endif
        if ($skip_master == 0 || $skip_master == 1) then
          sarp.csh $aligned.PRM
        endif
      endif

      if ($iono == 1) then
        if ($skip_master == 0 || $skip_master == 2) then
          if (-f ../raw/ALOS_fbd2fbs_log_$aligned) then
            split_spectrum $master.PRM 1 > params1
          else 
            split_spectrum $master.PRM > params1
          endif
          mv SLCH ../SLC_H/$master.SLC
          mv SLCL ../SLC_L/$master.SLC

          cd ../SLC_L
          set wl1 = `grep low_wavelength ../SLC/params1 | awk '{print $3}'`
          cp ../SLC/$master.PRM .
          ln -s ../raw/$master.LED .
          sed "s/.*wavelength.*/radar_wavelength    = $wl1/g" $master.PRM > tmp
          mv tmp $master.PRM
          cd ../SLC_H
          set wh1 = `grep high_wavelength ../SLC/params1 | awk '{print $3}'`
          cp ../SLC/$master.PRM .
          ln -s ../raw/$master.LED .
          sed "s/.*wavelength.*/radar_wavelength    = $wh1/g" $master.PRM > tmp
          mv tmp $master.PRM
          cd ../SLC
        endif

        if ($skip_master == 0 || $skip_master == 1) then 
          if (-f ../raw/ALOS_fbd2fbs_log_$master) then
            split_spectrum $aligned.PRM 1 > params2
          else
            split_spectrum $aligned.PRM > params2
          endif
          mv SLCH ../SLC_H/$aligned.SLC
          mv SLCL ../SLC_L/$aligned.SLC

          cd ../SLC_L
          set wl2 = `grep low_wavelength ../SLC/params2 | awk '{print $3}'`
          cp ../SLC/$aligned.PRM .
          ln -s ../raw/$aligned.LED .
          sed "s/.*wavelength.*/radar_wavelength    = $wl2/g" $aligned.PRM > tmp
          mv tmp $aligned.PRM
          cd ../SLC_H
          set wh2 = `grep high_wavelength ../SLC/params2 | awk '{print $3}'`
          cp ../SLC/$aligned.PRM .
          ln -s ../raw/$aligned.LED .
          sed "s/.*wavelength.*/radar_wavelength    = $wh2/g" $aligned.PRM > tmp
          mv tmp $aligned.PRM
          cd ../SLC
        endif
      endif

      if ($skip_master == 0 || $skip_master == 1) then
        cp $aligned.PRM $aligned.PRM0
        SAT_baseline $master.PRM $aligned.PRM0 >> $aligned.PRM
        if ($SAT == "ALOS2_SCAN") then
          xcorr $master.PRM $aligned.PRM -xsearch 32 -ysearch 256 -nx 32 -ny 128
          awk '{print $4}' < freq_xcorr.dat > tmp.dat
          set amedian = `sort -n tmp.dat | awk ' { a[i++]=$1; } END { print a[int(i/2)]; }'`
          set amax = `echo $amedian | awk '{print $1+3}'`
          set amin = `echo $amedian | awk '{print $1-3}'`
          awk '{if($4 > '$amin' && $4 < '$amax') print $0}' < freq_xcorr.dat > freq_alos2.dat
          fitoffset.csh 2 3 freq_alos2.dat 10 >> $aligned.PRM
        else if ($SAT == "ERS" || $SAT == "ENVI" || $SAT == "ALOS" || $SAT == "CSK_RAW") then
          xcorr $master.PRM $aligned.PRM -xsearch 128 -ysearch 128 -nx 20 -ny 50
          fitoffset.csh 3 3 freq_xcorr.dat 18 >> $aligned.PRM
        else
          xcorr $master.PRM $aligned.PRM -xsearch 128 -ysearch 128 -nx 20 -ny 50
          fitoffset.csh 2 2 freq_xcorr.dat 18 >> $aligned.PRM
        endif
        resamp $master.PRM $aligned.PRM $aligned.PRMresamp $aligned.SLCresamp 4
        rm $aligned.SLC
        mv $aligned.SLCresamp $aligned.SLC
        cp $aligned.PRMresamp $aligned.PRM

        if ($iono == 1) then
          cd ../SLC_L
          cp $aligned.PRM $aligned.PRM0
          if ($SAT == "ALOS2_SCAN") then
            ln -s ../SLC/freq_alos2.dat
            fitoffset.csh  2 3 freq_alos2.dat 10 >> $aligned.PRM
          else if ($SAT == "ERS" || $SAT == "ENVI" || $SAT == "ALOS" || $SAT == "CSK_RAW" || $SAT == "TSX") then
            ln -s ../SLC/freq_xcorr.dat .
            fitoffset.csh 3 3 freq_xcorr.dat 18 >> $aligned.PRM
          else
            ln -s ../SLC/freq_xcorr.dat .
            fitoffset.csh 2 2 freq_xcorr.dat 18 >> $aligned.PRM
          endif
          resamp $master.PRM $aligned.PRM $aligned.PRMresamp $aligned.SLCresamp 4
          rm $aligned.SLC
          mv $aligned.SLCresamp $aligned.SLC
          cp $aligned.PRMresamp $aligned.PRM
       
          cd ../SLC_H
          cp $aligned.PRM $aligned.PRM0
          if ($SAT == "ALOS2_SCAN") then
            ln -s ../SLC/freq_alos2.dat
            fitoffset.csh  2 3 freq_alos2.dat 10 >> $aligned.PRM
          else if ($SAT == "ERS" || $SAT == "ENVI" || $SAT == "ALOS" || $SAT == "CSK_RAW") then
            ln -s ../SLC/freq_xcorr.dat .
            fitoffset.csh 3 3 freq_xcorr.dat 18 >> $aligned.PRM
          else
            ln -s ../SLC/freq_xcorr.dat .
            fitoffset.csh 2 2 freq_xcorr.dat 18 >> $aligned.PRM
          endif
          resamp $master.PRM $aligned.PRM $aligned.PRMresamp $aligned.SLCresamp 4
          rm $aligned.SLC
          mv $aligned.SLCresamp $aligned.SLC
          cp $aligned.PRMresamp $aligned.PRM
          cd ../SLC
        endif
      endif

    else if ($SAT == "S1_TOPS") then
      if ($skip_master == 0 || $skip_master == 2) then
        cp ../raw/$master.PRM .
        ln -s ../raw/$master.SLC . 
        ln -s ../raw/$master.LED . 
      endif
      if ($skip_master == 0 || $skip_master == 1) then
        cp ../raw/$aligned.PRM .
        ln -s ../raw/$aligned.SLC . 
        ln -s ../raw/$aligned.LED .
      endif
 
      if ($iono == 1) then
        if ($skip_master == 0 || $skip_master == 2) then
          ln -s ../raw/$2.tiff .
          split_spectrum $master.PRM > params1
          mv high.tiff ../SLC_H/$2.tiff
          mv low.tiff ../SLC_L/$2.tiff
        endif
        if ($skip_master == 0 || $skip_master == 1) then
          ln -s ../raw/$3.tiff .
          split_spectrum $aligned.PRM > params2
          mv high.tiff ../SLC_H/$3.tiff
          mv low.tiff ../SLC_L/$3.tiff
        endif

        cd ../SLC_L
        if ($skip_master == 0 || $skip_master == 2) then
          ln -s ../raw/$2.xml .
          ln -s ../raw/$2.EOF .
          ln -s ../topo/dem.grd .
        endif
        if ($skip_master == 0 || $skip_master == 1) then
          ln -s ../raw/$3.xml .
          ln -s ../raw/$3.EOF .
          ln -s ../raw/a.grd .
          ln -s ../raw/r.grd .
          ln -s ../raw/offset*.dat .
        endif
        #if ($spec_div == 1) then
        #  align_tops_esd.csh $2 $2.EOF $3 $3.EOF dem.grd 1 $spec_mode
        #else
        if ($skip_master == 0) then
           align_tops.csh $2 $2.EOF $3 $3.EOF dem.grd 1
        else if ($skip_master == 1) then
           align_tops.csh $2 0 $3 $3.EOF dem.grd 1
        else if ($skip_master == 2) then
           align_tops.csh $2 $2.EOF $3 0 dem.grd 1
        endif
        #endif
        if ($skip_master == 0 || $skip_master == 2) then
          set wl1 = `grep low_wavelength ../SLC/params1 | awk '{print $3}'`
          sed "s/.*wavelength.*/radar_wavelength    = $wl1/g" $master.PRM > tmp
          mv tmp $master.PRM
        endif
        if ($skip_master == 0 || $skip_master == 1) then
          set wl2 = `grep low_wavelength ../SLC/params2 | awk '{print $3}'`
          sed "s/.*wavelength.*/radar_wavelength    = $wl2/g" $aligned.PRM > tmp
          mv tmp $aligned.PRM
        endif
        #cp ../raw/$master.PRM .
        #ln -s ../raw/$master.LED .
        #cp ../raw/$aligned.PRM .
        #ln -s ../raw/$aligned.LED .

        cd ../SLC_H
        if ($skip_master == 0 || $skip_master == 2) then
          ln -s ../raw/$2.xml .
          ln -s ../raw/$2.EOF .
          ln -s ../topo/dem.grd .
        endif
        if ($skip_master == 0 || $skip_master == 1) then
          ln -s ../raw/$3.xml .
          ln -s ../raw/$3.EOF .
          ln -s ../raw/a.grd .
          ln -s ../raw/r.grd .
          ln -s ../raw/offset*.dat .
        endif
        if ($skip_master == 0) then
           align_tops.csh $2 $2.EOF $3 $3.EOF dem.grd 1
        else if ($skip_master == 1) then
           align_tops.csh $2 0 $3 $3.EOF dem.grd 1
        else if ($skip_master == 2) then
           align_tops.csh $2 $2.EOF $3 0 dem.grd 1
        endif
        if ($skip_master == 0 || $skip_master == 2) then
          set wh1 = `grep high_wavelength ../SLC/params1 | awk '{print $3}'`
          sed "s/.*wavelength.*/radar_wavelength    = $wh1/g" $master.PRM > tmp
          mv tmp $master.PRM
        endif
        if ($skip_master == 0 || $skip_master == 1) then
          set wh2 = `grep high_wavelength ../SLC/params2 | awk '{print $3}'`
          sed "s/.*wavelength.*/radar_wavelength    = $wh2/g" $aligned.PRM > tmp
          mv tmp $aligned.PRM
        endif
        #cp ../raw/$master.PRM .
        #ln -s ../raw/$master.LED .
        #cp ../raw/$aligned.PRM .
        #ln -s ../raw/$aligned.LED .

        cd ../SLC

      endif

    endif

    if ($region_cut != "") then
      echo "Cutting SLC image to $region_cut"
      if ($skip_master == 0 || $skip_master == 2) then
        cut_slc $master.PRM junk1 $region_cut
        mv junk1.PRM $master.PRM 
        mv junk1.SLC $master.SLC
      endif
      if ($skip_master == 0 || $skip_master == 1) then
        cut_slc $aligned.PRM junk2 $region_cut
        mv junk2.PRM $aligned.PRM
        mv junk2.SLC $aligned.SLC
      endif

      if ($iono == 1) then
        cd ../SLC_L
        if ($skip_master == 0 || $skip_master == 2) then
          cut_slc $master.PRM junk1 $region_cut
          mv junk1.PRM $master.PRM
          mv junk1.SLC $master.SLC
        endif
        if ($skip_master == 0 || $skip_master == 1) then
          cut_slc $aligned.PRM junk2 $region_cut
          mv junk2.PRM $aligned.PRM
          mv junk2.SLC $aligned.SLC
        endif 
        cd ../SLC_H
        if ($skip_master == 0 || $skip_master == 2) then
          cut_slc $master.PRM junk1 $region_cut
          mv junk1.PRM $master.PRM
          mv junk1.SLC $master.SLC
        endif
        if ($skip_master == 0 || $skip_master == 1) then
          cut_slc $aligned.PRM junk2 $region_cut
          mv junk2.PRM $aligned.PRM
          mv junk2.SLC $aligned.SLC
        endif
      endif
    endif

    cd ..
    echo ""
    echo "ALIGN.CSH - END"
    echo ""  
  
  endif
##################################
# 3 - start from make topo_ra  #
##################################
#
  if ($stage <= 3 && $skip_3 == 0) then
#
# clean up
#
    cleanup.csh topo
#
# make topo_ra if there is dem.grd
#
    if ($topo_phase == 1) then 
      echo " "
      echo "DEM2TOPO_RA.CSH - START"
      echo "USER SHOULD PROVIDE DEM FILE"
      cd topo
      cp ../SLC/$master.PRM master.PRM 
      ln -s ../raw/$master.LED . 
      if (-f dem.grd) then 
        if ($topo_interp_mode == 1) then
          dem2topo_ra.csh master.PRM dem.grd 1
        else
          dem2topo_ra.csh master.PRM dem.grd
        endif
      else 
        echo "no DEM file found: " dem.grd 
        exit 1
      endif
      cd .. 
      echo "DEM2TOPO_RA.CSH - END"
# 
# shift topo_ra
# 
      if ($shift_topo == 1) then 
        echo " "
        echo "OFFSET_TOPO - START"
        cd SLC 
        set rng_samp_rate = `grep rng_samp_rate $master.PRM | awk 'NR == 1 {printf("%d", $3)}'`
        set rng = `gmt grdinfo ../topo/topo_ra.grd | grep x_inc | awk '{print $7}'`
        slc2amp.csh $master.PRM $rng amp-$master.grd 
        cd ..
        cd topo
        ln -s ../SLC/amp-$master.grd . 
        offset_topo amp-$master.grd topo_ra.grd 0 0 7 topo_shift.grd 
        cd ..
        echo "OFFSET_TOPO - END"
      else if ($shift_topo == 0) then 
        echo "NO TOPO_RA SHIFT "
      else 
        echo "Wrong paramter: shift_topo "$shift_topo
        exit 1
      endif

    else if ($topo_phase == 0) then 
      echo "NO TOPO_RA IS SUBSTRACTED"
    else 
      echo "Wrong paramter: topo_phase "$topo_phase
      exit 1
    endif
  endif

##################################################
# 4 - start from make and filter interferograms  #
##################################################
#

#
# select the master
#    
  if ($switch_master == 0) then
    set ref = $master
    set rep = $aligned
  else if ($switch_master == 1) then
    set ref = $aligned
    set rep = $master
  else
    echo "Wrong paramter: switch_master "$switch_master
  endif

  if ($stage <= 4 && $skip_4 == 0) then
#
# clean up
# 
    mkdir -p intf
    cleanup.csh intf
# 
# make and filter interferograms
# 
    echo " "
    echo "INTF.CSH, FILTER.CSH - START"
    cd intf/
    set ref_id  = `grep SC_clock_start ../raw/$ref.PRM | awk '{printf("%d",int($3))}' `
    set rep_id  = `grep SC_clock_start ../raw/$rep.PRM | awk '{printf("%d",int($3))}' `
    mkdir $ref_id"_"$rep_id
    cd $ref_id"_"$rep_id
    ln -s ../../SLC/$ref.LED . 
    ln -s ../../SLC/$rep.LED .
    ln -s ../../SLC/$ref.SLC . 
    ln -s ../../SLC/$rep.SLC .
    cp ../../SLC/$ref.PRM . 
    cp ../../SLC/$rep.PRM .
    if($topo_phase == 1) then
      if ($shift_topo == 1) then
        ln -s ../../topo/topo_shift.grd .
        intf.csh $ref.PRM $rep.PRM -topo topo_shift.grd  
        filter.csh $ref.PRM $rep.PRM $filter $dec $range_dec $azimuth_dec $compute_phase_gradient
      else 
        ln -s ../../topo/topo_ra.grd . 
        intf.csh $ref.PRM $rep.PRM -topo topo_ra.grd 
        filter.csh $ref.PRM $rep.PRM $filter $dec $range_dec $azimuth_dec $compute_phase_gradient
      endif
    else
      echo "NO TOPOGRAPHIC PHASE REMOVAL PORFORMED"
      intf.csh $ref.PRM $rep.PRM
      filter.csh $ref.PRM $rep.PRM $filter $dec $range_dec $azimuth_dec $compute_phase_gradient
    endif
    cd ../..

    if ($iono == 1) then
      if (-e iono_phase ) rm -r iono_phase
      mkdir -p iono_phase
      cd iono_phase 
      mkdir -p intf_o intf_h intf_l iono_correction

      set new_incx = `echo $range_dec $iono_dsamp | awk '{print $1*$2}'`
      set new_incy = `echo $azimuth_dec $iono_dsamp | awk '{print $1*$2}'`

      echo ""
      cd intf_h
      ln -s ../../SLC_H/*.SLC .
      ln -s ../../SLC_H/*.LED .
      cp ../../SLC_H/*.PRM .
      cp ../../SLC/params* .
      if($topo_phase == 1) then
        if ($shift_topo == 1) then
          ln -s ../../topo/topo_shift.grd .
          intf.csh $ref.PRM $rep.PRM -topo topo_shift.grd  
          filter.csh $ref.PRM $rep.PRM 500 $dec $new_incx $new_incy
        else 
          ln -s ../../topo/topo_ra.grd . 
          intf.csh $ref.PRM $rep.PRM -topo topo_ra.grd 
          filter.csh $ref.PRM $rep.PRM 500 $dec $new_incx $new_incy
        endif
      else
        echo "NO TOPOGRAPHIC PHASE REMOVAL PORFORMED"
        intf.csh $ref.PRM $rep.PRM
        filter.csh $ref.PRM $rep.PRM 500 $dec $new_incx $new_incy
      endif
      cp phase.grd phasefilt.grd
      if ($iono_skip_est == 0) then
        if ($mask_water == 1 || $switch_land == 1) then
          set rcut = `gmt grdinfo phase.grd -I- | cut -c3-20`
          cd ../../topo
          landmask.csh $rcut
          cd ../iono_phase/intf_h
          ln -s ../../topo/landmask_ra.grd .
        endif
        snaphu_interp.csh 0.05 0
      endif
      cd ..

      echo ""
      cd intf_l
      ln -s ../../SLC_L/*.SLC .
      ln -s ../../SLC_L/*.LED .
      cp ../../SLC_L/*.PRM .
      cp ../../SLC/params* .
      if($topo_phase == 1) then
        if ($shift_topo == 1) then
          ln -s ../../topo/topo_shift.grd .
          intf.csh $ref.PRM $rep.PRM -topo topo_shift.grd
          filter.csh $ref.PRM $rep.PRM 500 $dec $new_incx $new_incy
        else
          ln -s ../../topo/topo_ra.grd .
          intf.csh $ref.PRM $rep.PRM -topo topo_ra.grd
          filter.csh $ref.PRM $rep.PRM 500 $dec $new_incx $new_incy
        endif
      else
        echo "NO TOPOGRAPHIC PHASE REMOVAL PORFORMED"
        intf.csh $ref.PRM $rep.PRM
        filter.csh $ref.PRM $rep.PRM 500 $dec $new_incx $new_incy
      endif
      cp phase.grd phasefilt.grd
      if ($iono_skip_est == 0) then
        if ($mask_water == 1 || $switch_land == 1) ln -s ../../topo/landmask_ra.grd .
        snaphu_interp.csh 0.05 0
      endif
      cd ..

      echo ""
      cd intf_o
      ln -s ../../SLC/*.SLC .
      ln -s ../../SLC/*.LED .
      cp ../../SLC/*.PRM .
      if($topo_phase == 1) then
        if ($shift_topo == 1) then
          ln -s ../../topo/topo_shift.grd .
          intf.csh $ref.PRM $rep.PRM -topo topo_shift.grd
          filter.csh $ref.PRM $rep.PRM 500 $dec $new_incx $new_incy
        else
          ln -s ../../topo/topo_ra.grd .
          intf.csh $ref.PRM $rep.PRM -topo topo_ra.grd
          filter.csh $ref.PRM $rep.PRM 500 $dec $new_incx $new_incy
        endif
      else
        echo "NO TOPOGRAPHIC PHASE REMOVAL PORFORMED"
        intf.csh $ref.PRM $rep.PRM
        filter.csh $ref.PRM $rep.PRM 500 $dec $new_incx $new_incy
      endif
      cp phase.grd phasefilt.grd
      if ($iono_skip_est == 0) then
        if ($mask_water == 1 || $switch_land == 1) ln -s ../../topo/landmask_ra.grd .
        snaphu_interp.csh 0.05 0
      endif
      cd ../iono_correction
      echo ""

      if ($iono_skip_est == 0) then
        estimate_ionospheric_phase.csh ../intf_h ../intf_l ../intf_o ../../intf/$ref_id"_"$rep_id $iono_filt_rng $iono_filt_azi
      
        cd ../../intf/$ref_id"_"$rep_id
        mv phasefilt.grd phasefilt_non_corrected.grd
        gmt grdsample ../../iono_phase/iono_correction/ph_iono_orig.grd -Rphasefilt_non_corrected.grd -Gph_iono.grd
        gmt grdmath phasefilt_non_corrected.grd ph_iono.grd SUB PI ADD 2 PI MUL MOD PI SUB = phasefilt.grd
        gmt grdimage phasefilt.grd -JX6.5i -Bxaf+lRange -Byaf+lAzimuth -BWSen -Cphase.cpt -X1.3i -Y3i -P -K > phasefilt.ps
        gmt psscale -Rphasefilt.grd -J -DJTC+w5i/0.2i+h -Cphase.cpt -Bxa1.57+l"Phase" -By+lrad -O >> phasefilt.ps
        gmt psconvert -Tf -P -A -Z phasefilt.ps
        #rm phasefilt.ps
      endif
      cd ../../
    endif

    echo "INTF.CSH, FILTER.CSH - END"
  endif


################################
# 5 - start from unwrap phase  #
################################
#
  if ($stage <= 5 && $skip_5 == 0) then
    if ($threshold_snaphu != 0 ) then
      cd intf
      set ref_id  = `grep SC_clock_start ../raw/$ref.PRM | awk '{printf("%d",int($3))}' `
      set rep_id  = `grep SC_clock_start ../raw/$rep.PRM | awk '{printf("%d",int($3))}' `
      cd $ref_id"_"$rep_id
#
# landmask
#
      if ($mask_water == 1 || $switch_land == 1) then
        set r_cut = `gmt grdinfo phase.grd -I- | cut -c3-20`
        cd ../../topo
        if (! -f landmask_ra.grd) then
          landmask.csh $r_cut
        endif
        cd ../intf
        cd $ref_id"_"$rep_id
        ln -s ../../topo/landmask_ra.grd .
      endif
#
      echo " "
      echo "SNAPHU.CSH - START"
      echo "threshold_snaphu: $threshold_snaphu"
#
      if ($near_interp == 1) then
        snaphu_interp.csh $threshold_snaphu $defomax
      else
        snaphu.csh $threshold_snaphu $defomax
      endif
#
      echo "SNAPHU.CSH - END"
      cd ../..
    else 
      echo ""
      echo "SKIP UNWRAP PHASE"
    endif
  endif

###########################
# 6 - start from geocode  #
###########################
#
  if ($stage <= 6 && $skip_6 == 0) then
    if ($threshold_geocode != 0 ) then
      cd intf
      set ref_id  = `grep SC_clock_start ../raw/$ref.PRM | awk '{printf("%d",int($3))}' `
      set rep_id  = `grep SC_clock_start ../raw/$rep.PRM | awk '{printf("%d",int($3))}' `
      cd $ref_id"_"$rep_id
      echo " "
      echo "GEOCODE.CSH - START"
      if (-f raln.grd) rm raln.grd 
      if (-f ralt.grd) rm ralt.grd
      if (-f trans.dat)  rm trans.dat
      if ($topo_phase == 1) then
        ln -s  ../../topo/trans.dat . 
        echo "threshold_geocode: $threshold_geocode"
        geocode.csh $threshold_geocode
      else 
        echo "topo_ra is needed to geocode"
        exit 1
      endif
      echo "GEOCODE.CSH - END"
      cd ../..
    else
      echo ""
      echo "SKIP GEOCODE"
      echo ""
    endif
  endif
#
# end  
  
  
  
  
  
  
  
  
  
  
  
  
  
  
  
  
  
  
  
  
