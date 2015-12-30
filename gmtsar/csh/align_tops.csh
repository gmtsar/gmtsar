#!/bin/csh -f
#       $Id$
# Xiaohua Xu and David Sandwell Dec 23 2015
#=======================================================================
#  script to compute geometric alignment parameters of master and slave TOPS data using back projection from topography
#
alias rm 'rm -f'
unset noclobber
#
if ($#argv < 3) then
 echo " "
 echo "Usage: align_tops.csh master.PRM slave.PRM dem.grd" 
 echo " "
 echo "  LED files or links must be available in directory "
 echo " "
 exit 1
endif 
#
#  extract a subset of the topography. the topo value is irrelevant so it can be filtered and downsampled.
#
gmt grdfilter $3 -D2 -Fg4 -I1m -Gflt.grd 
gmt grd2xyz --FORMAT_FLOAT_OUT=%lf flt.grd -s > topo.llt
#
# zero the alignment parameters of the slave image
# save the alignment parameters of the master image un case this is a surrogate master
#
update_PRM.csh $2 rshift 0
update_PRM.csh $2 sub_int_r 0.0
update_PRM.csh $2 stretch_r 0.0
update_PRM.csh $2 a_stretch_r 0.0
update_PRM.csh $2 ashift 0
update_PRM.csh $2 sub_int_a 0.0
update_PRM.csh $2 stretch_a 0.0
update_PRM.csh $2 a_stretch_a 0.0
#
# map the topography into the range and azimuth of the master and slave
#
SAT_llt2rat $1 1 < topo.llt > master.ratll
SAT_llt2rat $2 1 < topo.llt > slave.ratll
#
#  paste the files and compute the dr and da
#
paste master.ratll slave.ratll | awk '{print( $1, $6-$1, $2, $7-$2, "100")}' > tmp.dat
#
#  make sure the range and azimuth are within the bounds of the master
#
set rmax = `grep num_rng_bins $1 | awk '{print $3}'`
set amax = `grep num_lines $1 | awk '{print $3}'`
awk '{if($1 > 0 && $1 < '$rmax' && $3 > 0 && $3 < '$amax') print $0 }' < tmp.dat > offset.dat
#
#  run fitoffset
#
fitoffset.csh 1 3 offset.dat >> $2
#
# clean up the mess
#
rm topo.llt master.ratll slave.ratll tmp.dat offset.dat flt.grd
