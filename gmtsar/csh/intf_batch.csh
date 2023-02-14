#!/bin/csh -f 
#       $Id$
#
# intf_batch.csh
# Loop through a list of interferometry pairs
# modified from process2pass.csh
# Xiaopeng Tong D.Sandwell Aug 27 2010
# added support for ENVI_SLC 
# Anders Hogrelius May 22 2017

alias rm 'rm -f'
unset noclobber

# 
  if ($#argv != 3) then 
    echo ""
    echo "Usage: intf_batch.csh SAT intf.in batch.config"
    echo "  make a stack of interferograms listed in intf.in"
    echo ""
    echo " SAT can be ALOS ENVI(ENVISAT) ENVI_SLC and  ERS " 
    echo ""
    echo " format for intf.in:"
    echo "     reference1_name:repeat1_name"
    echo "     reference2_name:repeat2_name"
    echo "     reference3_name:repeat3_name"
    echo "     ......"
    echo ""
    echo " Example of intf.in for ALOS:"
    echo "    IMG-HH-ALPSRP096010650-H1.0__A:IMG-HH-ALPSRP236920650-H1.0__A"
    echo "    IMG-HH-ALPSRP089300650-H1.0__A:IMG-HH-ALPSRP096010650-H1.0__A"
    echo "    IMG-HH-ALPSRP089300650-H1.0__A:IMG-HH-ALPSRP236920650-H1.0__A"
    echo ""
    echo " Example of intf.in for ERS is:"
    echo "    e1_05783:e1_07787"
    echo "    e1_05783:e1_10292"
    echo ""
    echo " Example of intf.in for ENVISAT is:"
    echo "    ENV1_2_127_2925_07195:ENV1_2_127_2925_12706"
    echo "    ENV1_2_127_2925_07195:ENV1_2_127_2925_13207"
    echo ""
    echo " Example of intf.in for ENVI_SLC is:"
    echo "    ASA_IMS_1PNESA20030908_175832_000000182019_00399_07968_0000:ASA_IMS_1PNESA20051121_175837_000000172042_00399_19491_0000"
    echo "    ASA_IMS_1PNESA20040719_175832_000000182028_00399_12477_0000:ASA_IMS_1PNESA20051121_175837_000000172042_00399_19491_0000"
    echo "    ASA_IMS_1PNESA20040719_175832_000000182028_00399_12477_0000:ASA_IMS_1PNESA20030908_175832_000000182019_00399_07968_0000"
    echo "    ASA_IMS_1PNESA20051121_175837_000000172042_00399_19491_0000:ASA_IMS_1PNESA20040719_175832_000000182028_00399_12477_0000"
    echo ""
    echo " Example of intf.in for TSX is:"
    echo "    20171231:20180111"
    echo "    20171231:20180122"
    echo ""
    echo " batch.config is a config file for making interferograms"
    echo " See example.batch.config for an example"
    echo ""
    exit 1
  endif
#
  set SAT = $1
  if ($SAT != ALOS && $SAT != ENVI && $SAT != ERS && $SAT != ENVI_SLC && $SAT != TSX) then
    echo ""
    echo " SAT can be ALOS ENVI(ENVISAT) ENVI_SLC TSX and  ERS"
    echo ""
    exit 1
  endif
#
# make sure the file exsit
#
  if (! -f $2) then 
    echo "no input file:" $2
    exit
  endif

  if (! -f $3) then
    echo "no config file:" $3
    exit
  endif
#
# read parameters from configuration file
# 
  set stage = `grep proc_stage $3 | awk '{print $3}'`
  set master = `grep master_image $3 | awk '{print $3}'`
  if ($master == "") then
    echo ""
    echo "master image not set."
    echo ""
    exit 1
  endif
#
# if filter wavelength is not set then use a default of 200m
#
  set filter = `grep filter_wavelength $3 | awk '{print $3}'`
  if ( "x$filter" == "x" ) then
  set filter = 200
  echo " "
  echo "WARNING filter wavelength was not set in config.txt file"
  echo "        please specify wavelength (e.g., filter_wavelength = 200)"
  echo "        remove filter1 = gauss_alos_200m"
  endif
  set dec = `grep dec_factor $3 | awk '{print $3}'` 
  set topo_phase = `grep topo_phase $3 | awk '{print $3}'` 
  set shift_topo = `grep shift_topo $3 | awk '{print $3}'` 
  set threshold_snaphu = `grep threshold_snaphu $3 | awk '{print $3}'`
  set threshold_geocode = `grep threshold_geocode $3 | awk '{print $3}'`
  set region_cut = `grep region_cut $3 | awk '{print $3}'`
  set switch_land = `grep switch_land $3 | awk '{print $3}'`
  set defomax = `grep defomax $3 | awk '{print $3}'`
  set near_interp = `grep near_interp $3 | awk '{print $3}'`
  set mask_water = `grep mask_water $3 | awk '{print $3}'`
#
##################################
# 1 - start from make topo_ra  #
##################################
#
if ($stage <= 1) then
#
# clean up
#
  cleanup.csh topo
#
# make topo_ra
#
  if ($topo_phase == 1) then
    echo " "
    echo "DEM2TOPOPHASE.CSH - START"
    echo "USER SHOULD PROVIDE DEM FILE"
    cd topo
    cp ../SLC/$master.PRM master.PRM
    ln -s ../raw/$master.LED .
    if (-f dem.grd) then
      dem2topo_ra.csh master.PRM dem.grd
    else
      echo "no DEM file found: " dem.grd
      exit 1
    endif
    cd ..
    echo "DEM2TOPOPHASE.CSH - END"
#
# shift topo_ra
#
    if ($shift_topo == 1) then
      echo " "
      echo "OFFSET_TOPO - START"
      cd SLC
      if ($SAT == ALOS || $SAT == TSX) then
        set rng_samp_rate = `grep rng_samp_rate $master.PRM | awk 'NR == 1 {printf("%d", $3)}'`
        if ( $?rng_samp_rate) then
          if ($rng_samp_rate > 25000000) then
            echo "processing ALOS FBS data"
            set rng = 2
          else
            echo "processing ALOS FBD data"
            set rng = 1
          endif
        else
          echo "Undefined rng_samp_rate in the master PRM file"
          exit 1
        endif
        slc2amp.csh $master.PRM $rng amp-$master.grd
      else if ($SAT == ERS || $SAT == ENVI || $SAT == ENVI_SLC) then
        slc2amp.csh $master.PRM 1 amp-$master.grd
      endif
      cd ..
      cd topo
      ln -s ../SLC/amp-$master.grd .
      offset_topo amp-$master.grd topo_ra.grd 0 0 7 topo_shift.grd
      cd ..
      echo "OFFSET_TOPO - END"
    else if ($shift_topo == 0) then
      echo "NO TOPOPHASE SHIFT "
    else
      echo "Wrong paramter: shift_topo "$shift_topo
      exit 1
    endif
#
    else if ($topo_phase == 0) then
      echo "NO TOPOPHASE IS SUBSTRACTED"
    else
      echo "Wrong paramter: topo_phase "$topo_phase
      exit 1
    endif
  endif
#
endif # stage 1
#
##################################################
# 2 - start from make and filter interferograms  #
#                unwrap phase and geocode        #
##################################################
#
if ($stage <= 2) then
#
# make working directories
#
  echo ""
  echo "START FORM A STACK OF INTERFEROGRAMS"
  echo ""

  mkdir -p intf/
#
# loop over intf.in
#
  foreach line (`awk '{print $0}' $2`)

    set ref = `echo $line | awk -F: '{print $1}'`
    set rep = `echo $line | awk -F: '{print $2}'`
    set ref_id  = `grep SC_clock_start ./SLC/$ref.PRM | awk '{printf("%d",int($3))}' `
    set rep_id  = `grep SC_clock_start ./SLC/$rep.PRM | awk '{printf("%d",int($3))}' `
#
    echo ""
    echo "INTF.CSH, FILTER.CSH - START"
    cd intf
    mkdir $ref_id"_"$rep_id
    cd $ref_id"_"$rep_id
    ln -s ../../raw/$ref.LED .
    ln -s ../../raw/$rep.LED .
    ln -s ../../SLC/$ref.SLC .
    ln -s ../../SLC/$rep.SLC .
    cp ../../SLC/$ref.PRM .
    cp ../../SLC/$rep.PRM .
#
      if($topo_phase == 1) then
        if ($shift_topo == 1) then
          ln -s ../../topo/topo_shift.grd .
          intf.csh $ref.PRM $rep.PRM -topo topo_shift.grd
          filter.csh $ref.PRM $rep.PRM $filter $dec
        else
          ln -s ../../topo/topo_ra.grd .
          intf.csh $ref.PRM $rep.PRM -topo topo_ra.grd
          filter.csh $ref.PRM $rep.PRM $filter $dec
        endif
      else
        intf.csh $ref.PRM $rep.PRM
        filter.csh $ref.PRM $rep.PRM $filter $dec
      endif
    echo "INTF.CSH, FILTER.CSH - END"
#
    if ($region_cut == "") then
      set region_cut = `gmt grdinfo phase.grd -I- | cut -c3-20`
    endif
    if ($threshold_snaphu != 0 ) then
      if ($mask_water == 1 || $switch_land == 1) then
        cd ../../topo
        if (! -f landmask_ra.grd) then
          landmask.csh $region_cut
        endif
        cd ../intf
        cd $ref_id"_"$rep_id
        ln -s ../../topo/landmask_ra.grd .
      endif
      echo ""
      echo "SNAPHU.CSH - START"
      echo "threshold_snaphu: $threshold_snaphu"
      if ($near_interp == 1) then
        snaphu_interp.csh $threshold_snaphu $defomax $region_cut
      else
        snaphu.csh $threshold_snaphu $defomax $region_cut
      endif
      echo "SNAPHU.CSH - END"
    else 
      echo ""
      echo "SKIP UNWRAP PHASE"
    endif
    echo " "
    echo "GEOCODE.CSH - START"
    rm raln.grd ralt.grd
    if ($topo_phase == 1) then
      rm trans.dat
      ln -s  ../../topo/trans.dat . 
      echo "threshold_geocode: $threshold_geocode"
      geocode.csh $threshold_geocode
    else 
      echo "topo_ra is needed to geocode"
      exit 1
    endif
    echo "GEOCODE.CSH - END"
 
    cd ../..
  end # loop of foreach 
endif # stage 2
echo ""
echo "END FORM A STACK OF INTERFEROGRAMS"
echo ""

