#!/bin/csh -f 
#       $Id$

# Align a stack of SLC images
# can be used to do stacking and time-series analysis

# Xiaopeng Tong, Aug 27 2010
#
  if ($#argv != 2) then
    echo ""
    echo "Usage: align_batch.csh SAT align.in "
    echo "  align a set of images listed in align.in file"
    echo ""
    echo " SAT can be ALOS ENVISAT or ERS"
    echo ""
    echo "  format of align.in:"
    echo "    master_name:aligned_name:supermaster_name"
    echo ""
    echo "  example of align.in for ALOS is:"
    echo "   IMG-HH-ALPSRP096010650-H1.0__A:IMG-HH-ALPSRP089300650-H1.0__A:IMG-HH-ALPSRP096010650-H1.0__A"
    echo "   IMG-HH-ALPSRP096010650-H1.0__A:IMG-HH-ALPSRP236920650-H1.0__A:IMG-HH-ALPSRP096010650-H1.0__A" 
    echo "  "
    echo "  example of align.in for ERS is:"
    echo "  e1_05783:e1_07787:e1_05783"
    echo "  e1_05783:e1_10292:e1_05783"
    echo ""
    echo "  example of align.in for ENVISAT is:"
    echo "  ENV1_2_127_2925_07195:ENV1_2_127_2925_12706:ENV1_2_127_2925_07195"
    echo "  ENV1_2_127_2925_07195:ENV1_2_127_2925_13207:ENV1_2_127_2925_07195"
    echo ""
    echo "Example: align_batch.csh ALOS align.in "
    echo ""
    exit 1
  endif
  set SAT = $1
  if ($SAT != ENVI && $SAT != ERS && $SAT != ALOS) then
    echo ""
    echo " SAT can be ALOS ENVISAT or ERS "
    echo ""
    exit 1
  endif
#
# make working directories
#
  mkdir -p SLC/
# 
# clean up 
#
  cleanup.csh SLC
  echo ""
  echo "START ALIGN A STACK OF IMAGES"
  echo ""
#
# loop start focus and align SLC images 
# 
  foreach line (`awk '{print $0}' $2`)
    set master = `echo $line | awk -F: '{print $1}'`
    set aligned = `echo $line | awk -F: '{print $2}'`
    set supermaster = `echo $line | awk -F: '{print $3}'`

    if ($master != "" && $aligned != "" && $supermaster != "") then
      echo " "
      echo "Align $aligned to $master via $supermaster - START"
      cd SLC
      cp ../raw/$master.PRM .
      cp ../raw/$aligned.PRM .
      cp ../raw/$supermaster.PRM .
#
#  need to add the SLF_file name to the master PRM's
#
      update_PRM $master.PRM SLC_file $master.SLC
      update_PRM $supermaster.PRM SLC_file $supermaster.SLC
      ln -s ../raw/$master.raw . 
      ln -s ../raw/$aligned.raw . 
      ln -s ../raw/$master.LED . 
      ln -s ../raw/$aligned.LED .
      align.csh SAT $master $aligned $supermaster
      cd ..
      echo "Align $aligned to $master via $supermaster - END"
    else 
      echo ""
      echo "Wrong format in align.in"
      exit 1
    endif
  end

  echo ""
  echo "END ALIGN A STACK OF IMAGES"
  echo ""

