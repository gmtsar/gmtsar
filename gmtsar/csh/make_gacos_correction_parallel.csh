#!/bin/csh -f
#
# Changing the syntax a bit by Xu 2025 Feb. 
#
# By Xiangjun Zhao 2024
#
# 
#

if ($#argv != 6) then
  echo ""
  echo "Usage: make_gacos_correction_parallel.csh intflist GACOS_path ref_range ref_azimuth dem.grd Ncores"
  echo ""
  echo "  Run gacos correction jobs parallelly. Need to install GNU parallel first."
  echo "  Note, all the interferograms have unwraped. "
  echo "Note: intflist should be as following: "
  echo "  2018024_2018036 "
  echo "  2018024_2018048 "
  echo "  ... "
  echo ""
  exit
endif

set ncores = $6
set d1 = `date`

foreach line (`awk '{print $0}' $1`)
  ln -s $5 $line/dem.grd
  echo "./make_gacos_correction.csh $line $2 $3 $4 dem.grd > log_gacos_$line.txt" >> gacos.cmd
end

parallel --jobs $ncores < gacos.cmd

echo ""
echo "Finished all gacos jobs..."
echo ""

set d2 = `date`

#echo "parallel --jobs $ncores < intf_tops.cmd" | mail -s "Unwrapping finished" "balabala@gmail.com" 
