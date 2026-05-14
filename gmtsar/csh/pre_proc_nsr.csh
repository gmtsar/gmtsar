#!/bin/csh -f
#       $Id$
#
#  David Sandwell, November, 2025
#
#  Preproces NISAR SLC data both A and B frequencies
#
alias rm 'rm -f'
unset noclobber
#
# check the number of arguments
#
  if ($#argv < 2) then
    echo ""
    echo "Usage: pre_proc_nsr.csh file.h5 config.txt"
    echo ""
    exit 1
  endif
#
# parse the command line arguments
#
set stemname = `echo $1 | awk '{print "NSR_"substr($1,44,8)}'`
echo "stemname "$stemname
#
set SLC_factor = `grep SLC_factor $2 | awk '{print $3}'`
echo "SLC_factor "$SLC_factor
#
set region_cut = `grep region_cut $2 | awk '{print $3}'`
echo "region_cut "$region_cut
#
#  make the SLC, LED, and PRM files for A and B
#
echo $stemname".PRM"
make_slc_nsr $1 $stemname"A" AHH $SLC_factor $region_cut
calc_dop_orb $stemname"A.PRM" tmp 0 0
cat tmp >> $stemname"A.PRM"
rm tmp
#
echo $stemname".PRM"
make_slc_nsr $1 $stemname"B" BHH $SLC_factor $region_cut
calc_dop_orb $stemname"B.PRM" tmp 0 0
cat tmp >> $stemname"B.PRM"
rm tmp
#
