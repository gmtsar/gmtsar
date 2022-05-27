#!/bin/csh -f 
#       $Id$

# Align a stack of SLC images
# can be used to do stacking and time-series analysis

# Xiaopeng Tong, Aug 27 2010
#
  if ($#argv != 1) then
    echo ""
    echo "Usage: align_batch_ALOS_SLC.csh align.in "
    echo "  align a set of images listed in align.in file"
    echo ""
    echo "  format of align.in:"
    echo "    master_name:aligned_name:supermaster_name"
    echo ""
    echo "  example of align.in for ALOS is:"
    echo "   IMG-HH-ALPSRP096010650-H1.0__A:IMG-HH-ALPSRP089300650-H1.0__A:IMG-HH-ALPSRP096010650-H1.0__A"
    echo "   IMG-HH-ALPSRP096010650-H1.0__A:IMG-HH-ALPSRP236920650-H1.0__A:IMG-HH-ALPSRP096010650-H1.0__A" 
    echo "  "
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
  foreach line (`awk '{print $0}' $1`)
    set master = `echo $line | awk -F: '{print $1}'`
    set aligned = `echo $line | awk -F: '{print $2}'`
    set supermaster = `echo $line | awk -F: '{print $3}'`
    set masterstem = ` echo $master | awk '{ print substr($1,8,length($1)-7)}'`
    set alignedstem =  ` echo $aligned | awk '{ print substr($1,8,length($1)-7)}'`
    set supermasterstem = ` echo $supermaster | awk '{ print substr($1,8,length($1)-7)}'`

    if ($master != "" && $aligned != "" && $supermaster != "") then
      echo " "
      echo "Align $aligned to $master via $supermaster - START"
      cd SLC
      cp ../raw/IMG-HH-$masterstem.PRM .
      cp ../raw/IMG-HH-$alignedstem.PRM .
      cp ../raw/IMG-HH-$supermasterstem.PRM .
#
#  need to add the SLC_file name to the master PRM's
#
      update_PRM IMG-HH-$masterstem.PRM SLC_file IMG-HH-$masterstem.SLC
      update_PRM IMG-HH-$supermasterstem.PRM SLC_file IMG-HH-$supermasterstem.SLC
      ln -s ../raw/IMG-HH-$masterstem.SLC . 
      ln -s ../raw/IMG-HH-$alignedstem.SLC . 
      ln -s ../raw/IMG-HH-$masterstem.LED . 
      ln -s ../raw/IMG-HH-$alignedstem.LED .
      ln -s ../raw/IMG-HH-$supermasterstem.LED .
      align_ALOS_SLC.csh $master $aligned $supermaster
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

