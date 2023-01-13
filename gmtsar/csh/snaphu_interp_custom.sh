#!/bin/bash
#       $Id$
#    Steffan Davies, Jan 13, 2023
#
unset noclobber
#
if [[ "$#" -lt 3 ]]
then
    echo ""
    echo "snaphu_interp_custom.sh [GMTSAR] - Unwrap the phase with nearest neighbor interpolating low coherence and blank pixels. Allows for custom snaphu flags."
    echo " "
    echo "Usage: snaphu_interp_custom.sh correlation_threshold maximum_discontinuity xmin/xmax/ymin/ymax snaphu_flags"
    echo ""
    echo "       correlation is reset to zero when < threshold"
    echo "       maximum_discontinuity enables phase jumps for earthquake ruptures, etc."
    echo "       set maximum_discontinuity = 0 for continuous phase such as interseismic "
    echo ""
    echo "Example for unwrapping region with custom flags: "
    echo "    snaphu_interp_custom.sh .12 40 1000/3000/24000/27000 \" --tile 1 4 400 400 --nproc 4 \""
    echo ""
    echo "Example for unwrapping whole scene with custom flags: "
    echo "    snaphu_interp_custom.sh .0001 0 0/0/0/0 \"--tile 10 10 400 400 --nproc 16 -S\""
    echo ""
    echo "Reference:"
    echo "Chen C. W. and H. A. Zebker, Network approaches to two-dimensional phase unwrapping: intractability and two new algorithms, Journal of the Optical Society of America A, vol. 17, pp. 401-414 (2000)."
    echo "Agram, P. S., & Zebker, H. A. (2009). Sparse two-dimensional phase unwrapping using regular-grid methods. IEEE Geoscience and Remote Sensing Letters, 6(2), 327-331."
    exit 1
fi

if [[ -f ~/.quiet ]]
then
    V=""
else
    V="-V"
fi

#
# arguments
#
correlation_threshold="$1"
maximum_discontinuity="$2"
region="$3"


if [[ "$#" -lt 4 ]]
then
    snaphu_flags=""
else
    snaphu_flags="$4"
fi

#
# prepare the files adding the correlation mask
#

if [[ "$region" == "0/0/0/0" ]]
then
    ln -s mask.grd mask_patch.grd
    ln -s corr.grd corr_patch.grd
    ln -s phasefilt.grd phase_patch.grd
else
    gmt grdcut mask.grd -R$region -Gmask_patch.grd
    gmt grdcut corr.grd -R$region -Gcorr_patch.grd
    gmt grdcut phasefilt.grd -R$region -Gphase_patch.grd
fi


#
# create landmask
#

if [[ -f landmask_ra.grd ]]
then
    if [[ "$region" == "0/0/0/0" ]]
    then
        gmt grdsample landmask_ra.grd `gmt grdinfo -I phase_patch.grd` -Glandmask_ra_patch.grd
    else
        gmt grdsample landmask_ra.grd -R$region `gmt grdinfo -I phase_patch.grd` -Glandmask_ra_patch.grd
    fi
    gmt grdmath phase_patch.grd landmask_ra_patch.grd MUL = phase_patch.grd $V
fi


#
# user defined mask
#

if [[ -f mask_def.grd ]]
then
    if [[ "$region" == "0/0/0/0" ]]
    then
        cp mask_def.grd mask_def_patch.grd
    else
        gmt grdcut mask_def.grd -R$region -Gmask_def_patch.grd
    fi
    gmt grdmath corr_patch.grd mask_def_patch.grd MUL = corr_patch.grd $V
fi


#
# interpolate, in case there is a big vacant area, do not go too far
#

gmt grdmath corr_patch.grd $correlation_threshold GE 0 NAN mask_patch.grd MUL = mask2_patch.grd
gmt grdmath corr_patch.grd 0. XOR 1. MIN  = corr_patch.grd
gmt grdmath mask2_patch.grd corr_patch.grd MUL = corr_tmp.grd
gmt grdmath mask2_patch.grd phase_patch.grd MUL = phase_tmp.grd

nearest_grid phase_tmp.grd tmp.grd 300

mv tmp.grd phase_tmp.grd

gmt grd2xyz phase_tmp.grd -ZTLf -do0 > phase.in
gmt grd2xyz corr_tmp.grd -ZTLf  -do0 > corr.in


#
# run snaphu
#

sharedir=`gmtsar_sharedir.csh`
echo "unwrapping phase with snaphu - higher threshold for faster unwrapping "

if [[ "$maximum_discontinuity" -eq 0 ]]
then
    snaphu phase.in `gmt grdinfo -C phase_patch.grd | cut -f 10` -f $sharedir/snaphu/config/snaphu.conf.brief $snaphu_flags -c corr.in -o unwrap.out -v -s -g conncomp.out
else
    sed "s/.*DEFOMAX_CYCLE.*/DEFOMAX_CYCLE  $maximum_discontinuity/g" $sharedir/snaphu/config/snaphu.conf.brief > snaphu.conf.brief
    snaphu phase.in `gmt grdinfo -C phase_patch.grd | cut -f 10` -f snaphu.conf.brief $snaphu_flags -c corr.in -o unwrap.out -v -d -g conncomp.out
fi


#
# convert to grd
#

gmt xyz2grd unwrap.out -ZTLf -r `gmt grdinfo -I- phase_patch.grd` `gmt grdinfo -I phase_patch.grd` -Gtmp.grd
#Generate connected component
gmt xyz2grd conncomp.out -ZTLu -r `gmt grdinfo -I- phase_patch.grd` `gmt grdinfo -I phase_patch.grd` -Gconncomp.grd
gmt grdmath tmp.grd mask2_patch.grd MUL = tmp.grd
#gmt grdmath tmp.grd mask_patch.grd MUL = tmp.grd


#
# detrend the unwrapped if DEFOMAX = 0 for interseismic
#

#if [[ $maximum_discontinuity -eq 0 ]]
#then
#    gmt grdtrend tmp.grd -N3r -Dunwrap.grd
#else
mv tmp.grd unwrap.grd
#fi
#
# landmask
if [[ -f landmask_ra.grd ]]
then
    gmt grdmath unwrap.grd landmask_ra_patch.grd MUL = tmp.grd $V
    mv tmp.grd unwrap.grd
fi

#
# user defined mask
#
if [[ -f mask_def.grd ]]
then
    gmt grdmath unwrap.grd mask_def_patch.grd MUL = tmp.grd $V
    mv tmp.grd unwrap.grd
fi


#
#  plot the unwrapped phase
#

gmt grdgradient unwrap.grd -Nt.9 -A0. -Gunwrap_grad.grd
tmp=`gmt grdinfo -C -L2 unwrap.grd`
limitU=`echo $tmp | awk '{printf("%5.1f", $12+$13*2)}'`
limitU=$(echo $limitU |  tr -d ' ') # Remove trailing space
limitL=`echo $tmp | awk '{printf("%5.1f", $12-$13*2)}'`
limitL=$(echo $limitL |  tr -d ' ') # Remove trailing space
std=`echo $tmp | awk '{printf("%5.1f", $13)}'`
echo "gmt makecpt -Cseis -I -Z -T$limitL/$limitU/1 -D > unwrap.cpt" 
gmt makecpt -Cseis -I -Z -T$limitL/$limitU/1 -D > unwrap.cpt
boundR=`gmt grdinfo unwrap.grd -C | awk '{print ($3-$2)/4}'`
boundA=`gmt grdinfo unwrap.grd -C | awk '{print ($5-$4)/4}'`
gmt grdimage unwrap.grd -Iunwrap_grad.grd -Cunwrap.cpt -JX6.5i -Bxaf+lRange -Byaf+lAzimuth -BWSen -X1.3i -Y3i -P -K > unwrap.ps
gmt psscale -Runwrap.grd -J -DJTC+w5/0.2+h+e -Cunwrap.cpt -Bxaf+l"Unwrapped phase" -By+lrad -O >> unwrap.ps
gmt psconvert -Tf -P -A -Z unwrap.ps
echo "Unwrapped phase map: unwrap.pdf"


#
# clean up
#

rm -f tmp.grd corr_tmp.grd unwrap.out tmp2.grd unwrap_grad.grd phase_tmp.grd conncomp.out
rm -f phase.in corr.in
mv -f phase_patch.grd phasefilt_interp.grd


#
#   cleanup more
#

rm -f mask_patch.grd mask3.grd mask3.out
rm -f corr_patch.grd corr_cut.grd
#rm -f wrap.grd
#
