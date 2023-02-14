#!/bin/csh -f
#       $Id$
#
#  Xiaopeng Tong, Mar 2 2010 
#  modified by D. Sandwell MAR 11 2010
#  modified by A Hogrelius May 22 2017 (added support for ENVI_SLC)
#  modified by D. Sandwell NOV 11 2011 (added support for TSX)
#
#  preprocess all the data based on data.in table file and generate: 
#  1. raw files
#  2. PRM files 
#  3. time-baseline plot for user to create stacking pairs 

#  format in data.in table file: 
#  	line 1: master_name  
# 	line 2 and below: aligned_name

alias rm 'rm -f'
unset noclobber

#
# check the number of arguments 
# 
  if ($#argv != 3) then 
    echo ""
    echo "Usage: pre_proc_batch.csh SAT data.in batch.config"
    echo "       preprocess a set of images using a common rear_range and radius"
    echo ""
    echo " SAT can be ALOS ERS ENVI(ENVISAT) ENVI_SLC TSX"
    echo ""
    echo "       format of data.in is:"
    echo "         line 1: master_name "
    echo "         line 2 and below: aligned_name"
    echo ""
    echo "       example of data.in for ALOS is:"
    echo "         IMG-HH-ALPSRP096010650-H1.0__A" 
    echo "         IMG-HH-ALPSRP089300650-H1.0__A"
    echo "         IMG-HH-ALPSRP236920650-H1.0__A"
    echo ""
    echo "       example of data.in for ERS is:"
    echo "         e1_05783"
    echo "         e1_07787"
    echo "         e1_10292"
    echo ""
    echo "       example of data.in for ENVISAT is:"
    echo "         ENV1_2_127_2925_07195"
    echo "         ENV1_2_127_2925_12706"
    echo "         ENV1_2_127_2925_13207"
    echo ""
    echo "       example of data.in for ENVI_SLC is:"
    echo "         ASA_IMS_1PNESA20030908_175832_000000182019_00399_07968_0000"	
    echo "         ASA_IMS_1PNESA20040719_175832_000000182028_00399_12477_0000"	
    echo "         ASA_IMS_1PNESA20051121_175837_000000172042_00399_19491_0000"
    echo ""
    echo "       example of data.in for TSX is:"
    echo "         20171231"
    echo "         20180111"
    echo "         20180122"
    echo ""
    echo "Example: pre_proc_batch.csh ENVI data.in batch.config"
    echo ""
    exit 1
  endif

  set SAT = $1
  if ($SAT != ALOS && $SAT != ENVI && $SAT != ENVI_SLC && $SAT != ERS && $SAT != TSX) then
    echo ""
    echo " SAT can be ALOS ERS ENVI(ENVISAT) ENVI_SLC or TSX "
    echo ""
    exit 1
  endif
#
# read parameters from configuration file
#
  set num_patches = `grep num_patches $3 | awk '{print $3}'`
  set near_range = `grep near_range $3 | awk '{print $3}'`
  set earth_radius = `grep earth_radius $3 | awk '{print $3}'`
  set fd = `grep fd1 $3 | awk '{print $3}'`
#
  set commandline = ""
  if ($SAT == ERS || $SAT == ENVI) then
    if (!($near_range == "")) then
      set commandline = "$commandline $near_range"
    else 
      set commandline = "$commandline 0"
    endif

    if (!($earth_radius == "")) then
      set commandline = "$commandline $earth_radius"
    else 
      set commandline = "$commandline 0"
    endif
    
    if (!($num_patches == "")) then
      set commandline = "$commandline $num_patches"
    else
      set commandline = "$commandline 0"
    endif

    if (!($fd == "")) then
      set commandline = "$commandline $fd"
    else 
      set commandline = "$commandline"
    endif

  else if ($SAT == ALOS) then
    if (!($earth_radius == "")) then
      set commandline = "$commandline -radius $earth_radius"
    endif
    if (!($near_range == "")) then
      set commandline = "$commandline -near $near_range"
    endif
    if (!($num_patches == "")) then
      set commandline = "$commandline -npatch $num_patches"
    endif
    if (!($fd == "")) then
      set commandline = "$commandline -fd1 $fd"
    endif
  endif 

  echo $commandline
#
# open and read data.in table 
#
  echo ""
  echo "START PREPROCESS A STACK OF IMAGES"
  echo ""
  echo "preprocess master image"
  set line1 = `awk 'NR==1 {print $0}' $2`
  if ($SAT == ERS || $SAT == ENVI || $SAT == ENVI_SLC || $SAT == TSX) then
    set master = $line1[1]
  else if ($SAT == ALOS) then
    set master = `echo $line1[1] | awk '{ print substr($1,8,length($1)-7)}'`
  endif
#
# unpack the master if necessary
#
  if ($SAT == ERS || $SAT == ENVI) then

    if(! -f $master.raw || ! -f $master.LED) then
      $1_pre_process $master $commandline
    endif

    set NEAR = `grep near_range $master.PRM | awk '{print $3}'`
    set RAD = `grep earth_radius $master.PRM | awk '{print $3}'`
    set FD1 = `grep fd1 $master.PRM | awk '{print $3}'`
    set npatch = `grep num_patch $master.PRM | awk '{print $3}'`

    echo "before baseline"
    baseline_table.csh $master.PRM $master.PRM >! baseline_table.dat
    baseline_table.csh $master.PRM $master.PRM GMT >! table.gmt
    echo "after baseline"
 
  else if ($SAT == ENVI_SLC) then
  
  if ($earth_radius == "") then
  	set earth_radius = 0
  endif

    if(! -f $master.SLC || ! -f $master.LED) then
      ENVI_SLC_pre_process $master $earth_radius
    endif

    set NEAR = `grep near_range $master.PRM | awk '{print $3}'`
    set RAD = `grep earth_radius $master.PRM | awk '{print $3}'`
    set FD1 = `grep fd1 $master.PRM | awk '{print $3}'`
    set npatch = `grep num_patch $master.PRM | awk '{print $3}'`

    echo "before baseline"
    baseline_table.csh $master.PRM $master.PRM >! baseline_table.dat
    baseline_table.csh $master.PRM $master.PRM GMT >! table.gmt
    echo "after baseline"
  else if ($SAT == ALOS) then

    if(! -f IMG-HH-$master.raw || ! -f IMG-HH-$master.PRM ) then
      $1_pre_process IMG-HH-$master LED-$master $commandline
    endif

    set NEAR = `grep near_range IMG-HH-$master.PRM | awk '{print $3}'`
    set RAD = `grep earth_radius IMG-HH-$master.PRM | awk '{print $3}'`
    set rng_samp_rate_m = `grep rng_samp_rate IMG-HH-$master.PRM | awk 'NR == 1 {printf("%d", $3)}'`
    set FD1 = `grep fd1 IMG-HH-$master.PRM | awk '{print $3}'`
    set npatch = `grep num_patch IMG-HH-$master.PRM | awk '{print $3}'`
  
    baseline_table.csh IMG-HH-$master.PRM IMG-HH-$master.PRM >! baseline_table.dat
    baseline_table.csh IMG-HH-$master.PRM IMG-HH-$master.PRM GMT >! table.gmt

  else if ($SAT == TSX) then

    if(! -f $master.raw || ! -f $master.PRM ) then
      make_slc_tsx $master.xml $master.cos $master
      cp $master.PRM $master.PRM0
      calc_dop_orb $master.PRM0 $master.log 0 0
      cat $master.PRM0 $master.log > $master.PRM
      echo "fdd1                    = 0" >> $master.PRM
      echo "fddd1                   = 0" >> $master.PRM
    endif

    set NEAR = `grep near_range $master.PRM | awk '{print $3}'`
    set RAD = `grep earth_radius $master.PRM | awk '{print $3}'`
    set rng_samp_rate_m = `grep rng_samp_rate $master.PRM | awk 'NR == 1 {printf("%d", $3)}'`
    set FD1 = `grep fd1 $master.PRM | awk '{print $3}'`
    set npatch = `grep num_patch $master.PRM | awk '{print $3}'`

    baseline_table.csh $master.PRM $master.PRM >! baseline_table.dat
    baseline_table.csh $master.PRM $master.PRM GMT >! table.gmt

  endif
#
# loop and unpack the aligned image using the same earth radius and near range as the master image
#
  foreach line2 (`awk 'NR>1 {print $0}' $2`)
    echo "pre_proc_batch.csh"
    echo "preprocess aligned images"
    if ($SAT == ERS || $SAT == ENVI) then

      set aligned = $line2  
      if(! -f $aligned.raw || ! -f $aligned.LED) then
        $1_pre_process $aligned $NEAR $RAD $npatch $FD1
      endif
      baseline_table.csh $master.PRM $aligned.PRM >> baseline_table.dat
      baseline_table.csh $master.PRM $aligned.PRM GMT >> table.gmt

    else if ($SAT == TSX) then

      set aligned = $line2
      if(! -f $aligned.SLC || ! -f $aligned.LED) then
        make_slc_tsx $aligned.xml $aligned.cos $aligned
      endif
      set RAD = `grep earth_radius $master.PRM | awk '{print $3}'`
      cp $aligned.PRM $aligned.PRM0
      calc_dop_orb $aligned.PRM0 $aligned.log $RAD 0
      cat $aligned.PRM0 $aligned.log > $aligned.PRM
      echo "fdd1                    = 0" >> $aligned.PRM
      echo "fddd1                   = 0" >> $aligned.PRM
      baseline_table.csh $master.PRM $aligned.PRM >> baseline_table.dat
      baseline_table.csh $master.PRM $aligned.PRM GMT >> table.gmt

    else if ($SAT == ENVI_SLC) then

      set aligned = $line2
      if(! -f $aligned.SLC || ! -f $aligned.LED) then
        $1_pre_process $aligned $RAD
      endif
      baseline_table.csh $master.PRM $aligned.PRM >> baseline_table.dat
      baseline_table.csh $master.PRM $aligned.PRM GMT >> table.gmt

    else if ($SAT == ALOS) then 

      set aligned = ` echo $line2 | awk '{ print substr($1,8,length($1)-7)}'`
      if(! -f IMG-HH-$aligned.raw || ! -f IMG-HH-$aligned.PRM ) then
        $1_pre_process IMG-HH-$aligned LED-$aligned -fd1 $FD1 -near $NEAR -radius $RAD -npatch $npatch
      endif
#
# check the range sampling rate of the aligned images and do conversion if necessary
#
      set rng_samp_rate_s = `grep rng_samp_rate IMG-HH-$aligned.PRM | awk 'NR == 1 {printf("%d", $3)}'`
      set t = `echo $rng_samp_rate_m $rng_samp_rate_s | awk '{printf("%1.1f\n", $1/$2)}'`
      if ($t == 1.0) then
        echo "The range sampling rate for master and aligned images are: "$rng_samp_rate_m
#
        baseline_table.csh IMG-HH-$master.PRM IMG-HH-$aligned.PRM >> baseline_table.dat
        baseline_table.csh IMG-HH-$master.PRM IMG-HH-$aligned.PRM GMT >> table.gmt
      else if ($t == 2.0) then
        echo "Convert the aligned image from FBD to FBS mode"
        ALOS_fbd2fbs IMG-HH-$aligned.PRM IMG-HH-$aligned"_"FBS.PRM
#
        baseline_table.csh IMG-HH-$master.PRM IMG-HH-$aligned"_"FBS.PRM >> baseline_table.dat
        baseline_table.csh IMG-HH-$master.PRM IMG-HH-$aligned"_"FBS.PRM GMT >> table.gmt
        echo "Overwriting the old aligned image"
        mv IMG-HH-$aligned"_"FBS.PRM IMG-HH-$aligned.PRM
        update_PRM IMG-HH-$aligned.PRM input_file IMG-HH-$aligned.raw
        mv IMG-HH-$aligned"_"FBS.raw IMG-HH-$aligned.raw

      else if  ($t == 0.5) then
	echo "Use FBS mode image as master"
        exit 1
      else
        echo "The range sampling rate for master and aligned images are not convertable"
        exit 1
      endif    
# end of the if ($SAT == ALOS) 
    endif 
# end of the loop over aligned images
  end

#
# make baseline plots
#

  if ($SAT == ERS || $SAT == ENVI || $SAT == ENVI_SLC) then
    awk '{print 1992+$1/365.25,$2,$7}' < table.gmt > text
#    awk '{print 1992+$1/365.25,$2,7,$4,$5,$6,$7}' < table.gmt > text
#    awk '{print 1992+$1/365.25,$2,7,-45,$5,$6,$7}' < table.gmt > text
  else if ($SAT == TSX) then
    awk '{print 2007+$1/365.25,$2,$7}' < table.gmt > text
  else if ($SAT == ALOS) then
    awk '{print 2006.5+($1-181)/365.25,$2,$7}' < table.gmt > text
#    awk '{print 2006.5+($1-181)/365.25,$2,9,$4,$5,$6,$7}' < table.gmt > text
  endif
  set region = `gmt gmtinfo text -C | awk '{print $1-0.5, $2+0.5, $3-500, $4+500}'`
# set region = `minmax text -C | awk '{print $1-0.5, $2+0.5, -1200, 1200}'`
  gmt pstext text -JX8.8i/6.8i -R$region[1]/$region[2]/$region[3]/$region[4] -D0.2/0.2 -X1.5i -Y1i -K -N -F+f8,Helvetica+j5 > stacktable_all.ps
  awk '{print $1,$2}' < text > text2
  gmt psxy text2 -Sp0.2c -G0 -R -JX -Ba1:"year":/a200g00f100:"baseline (m)":WSen -O >> stacktable_all.ps

  echo ""
  echo "END PREPROCESS A STACK OF IMAGES"
  echo ""

#
# clean up the mess
#
  rm text text2 *.PRM0
