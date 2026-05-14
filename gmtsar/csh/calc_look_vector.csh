#!/bin/csh -f
#

  if ($#argv <1 || $#argv >3) then
    echo ""
    echo "Usage: calc_look_vector.csh input_PRM dem.grd unwrap_ll.grd"
    echo ""
    echo "  Make usre LED file exist, DEM is larger than unwrap_ll.grd"
    echo ""
    echo "  Example: calc_look_vector.csh S1_20190312_ALL_F1.PRM dem.grd unwrap_ll.grd"
    echo ""
    echo "  Output: east_look.grd north_look.grd up_look.grd (same registration as input unwrap_ll.grd)"
    echo ""
    exit 1
  endif

  set prm = $1
  set dem = $2
  set file = $3

  gmt grdsample $dem -R$file -Gtmp_dem_00.grd
  gmt grd2xyz $dem -s | SAT_look $prm > tmp_look_00.lltn
  awk '{print $1,$2,$4}' tmp_look_00.lltn | gmt xyz2grd -R$file -Geast_look.grd
  awk '{print $1,$2,$5}' tmp_look_00.lltn | gmt xyz2grd -R$file -Gnorth_look.grd
  awk '{print $1,$2,$6}' tmp_look_00.lltn | gmt xyz2grd -R$file -Gup_look.grd
 
  rm tmp_dem_00.grd tmp_look_00.lltn
