#!/bin/csh -f
#
#  D. Sandwell MAR 11 2026
#
#  compute range and azimuth alignment grids xcorr.dat
#
alias rm 'rm -f'
unset noclobber
#
# check for number of arguments
#
if ($#argv == 0) then
  	echo "  "
  	echo "Usage: fitoffset_ra.csh npar_rng npar_azi xcorr.dat [SNR]"
  	echo "  "
	echo "        npar_rng    - number of parameters to fit in range "
        echo "        npar_aiz    - number of parameters to fit in azimuth "
  	echo "        xcorr.dat   - files of range and azimuth offset estimates "
  	echo "        SNR         - optional SNR cutoff (default 20)"
  	echo "  "
  	echo "Example: fitoffset_ra.csh 3 3 freq_xcorr.dat "
  	echo "  "
  	exit 1
endif
#
if ($#argv == 4) then
  set SNR = $4
else
  set SNR = 20.
endif
#
#  first extract the range and azimuth data
#
 awk '{ if ($5 > '$SNR') printf("%f %f %f \n",$1,$3,$2); }' < $3 > r.xyz
 awk '{ if ($5 > '$SNR') printf("%f %f %f \n",$1,$3,$4); }' < $3 > a.xyz
#
#  make sure there are enough points remaining, otherwise exit
#
 set NPTS0 = ` wc -l $3 | awk '{print $1}'`
 set NPTS = ` wc -l r.xyz | awk '{print $1}'`
 if($NPTS < 8) then
  echo "  "
  echo " FAILED - not enough points to estimate parameters"
  echo " try lower SNR "
  echo " NPTS0, NPTS  " $NPTS0 $NPTS
  echo "  "
  exit 1
 endif

#
# compute requested number of parameters
#
 set azi_p = $2
 set rng_p = $1

 gmt trend2d r.xyz -Fxym -N"$rng_p"r > r_model.xyz  
 gmt trend2d a.xyz -Fxym -N"$azi_p"r > a_model.xyz  
#
# grid these delta_offsets to match the geometric offsets
#
gmt surface r_model.xyz `gmt grdinfo amp*.grd -I-` -rp -I64/64  -Gr_tmp.grd
gmt surface a_model.xyz `gmt grdinfo amp*.grd -I-` -rp -I64/64  -Ga_tmp.grd
gmt grdmath r_tmp.grd FLIPUD = r.grd
gmt grdmath a_tmp.grd FLIPUD = a.grd
#
#  clean up
#
rm r_model.xyz a_model.xyz rm r_tmp.grd a_tmp.grd
