#!/bin/csh
#
# adding syntax for usage of a single interferogram, calculate look angle maps by Xu 2025 Feb.
#
# Modified by Zhao Xiangjun in 2024.
#
# make tropospheric correction based on GACOS using GMT
# created by Wei Tang, Nov 11 2018, contact: weitang@cumtb.edu.cn

if ($#argv != 5) then
  echo ""
  echo "Usage: make_gacos_correction.csh intf_dir GACOS_path ref_range ref_azimuth dem.grd"
  echo ""
  echo "  Run gacos jobs for a single interferogram dir (such as, 2018024_2018036). Need to have GACOS file (*.ztd, *.rsc)"
  echo "  in the GACOS_path. Need to unwrap the interferogram first. "
  echo ""
  exit
endif

########################################################
########## set parameters for corrections ##############

cd $1

set line = $1
#set gacos_path = /media/student/ElementsZhao/Sentinel_ShanXi/GACOS_p113 # GACOS file (*.ztd, *.rsc) path
set gacos_path = $2
set wavelength = `ls *PRM | head -1 | grep radar_wavelength | awk '{print $3}'` # radar wavelength in meter


############wavelength output is null
set wavelength = `grep radar_wavelength *PRM | awk '{print $3}' | head -n 1`


echo "Working on $line with radar wavelength $wavelength"
set DEM = $5
set PRM = `ls *PRM | head -1`

########## unwrap phase ##############
# unwrapped interferogram phase in rad
set unwphase = unwrap.grd  # original phase
set phaseout = unwrap_gacos_corr.grd # unwrap phase after GACOS correction
set PSOUT = Correction_results.ps

# set reference area, give longitude and latitude in degree
set pixel_center = $3
set line_center = $4
set ref_minpixel = `echo $pixel_center | awk '{printf("%f",$1-50)}'`
set ref_maxpixel = `echo $pixel_center | awk '{printf("%f",$1+50)}'`
set ref_minline = `echo $line_center | awk '{printf("%f",$1-50)}'`
set ref_maxline = `echo $line_center | awk '{printf("%f",$1+50)}'`
echo "Reference to area $ref_minpixel/$ref_maxpixel/$ref_minline/$ref_maxline"

# elevation angle in degree for converting delay in zenith direction into LOS
gmt grdsample $DEM -I12s -Gtmp_dem.grd


###### RUN SAT_look, need *LED file
set LED = `grep led_file $PRM | awk '{print $3}'`
echo $LED
ln -s ../../*/raw/$LED .


gmt grd2xyz tmp_dem.grd | SAT_look $PRM > tmp_dem.lltn
awk '{print $1,$2,$6}' < tmp_dem.lltn | gmt xyz2grd -Rtmp_dem.grd -Glook_ang_cos.grd
rm tmp_dem.grd tmp_dem.lltn
#set elev = 39.24050505864262
# if remove planar trend, 1 for yes, 0 for no
set isplanar = 0
set PI = 3.141592653589793
set scale = -JX6c

  echo "Processing interferogram: $line"
  set myear = `echo $line | cut -c 1-4`
  set mday = `echo $line | cut -c 5-7`
  set masterdate = `date -d ""$mday" days "$myear"-01-01" +"%Y%m%d"`
  set syear = `echo $line | cut -c 9-12`
  set sday = `echo $line | cut -c 13-15`
  set slavedate = `date -d ""$sday" days "$syear"-01-01" +"%Y%m%d"`
  set intf = $line

  # set master ztd and slave ztd
  set mztd = ${masterdate}.ztd
  set sztd = ${slavedate}.ztd
  set mztdgrd = ${masterdate}_ztd.grd
  set sztdgrd = ${slavedate}_ztd.grd
  set mztdps = ${masterdate}_ztd.ps
  set sztdps = ${slavedate}_ztd.ps
  rm -f $mztdps $sztdps

  # link the master ztd and slave ztd to the current folder

  rm -f $mztd $sztd $mztd.rsc $sztd.rsc
  ln -s $gacos_path/$mztd .
  ln -s $gacos_path/$sztd .
  cp $gacos_path/$mztd.rsc .
  cp $gacos_path/$sztd.rsc .

  set tmp = `gmt grdinfo -C -L2 $unwphase`
  set x_inc = `echo $tmp | awk '{print $8}'`
  set y_inc = `echo $tmp | awk '{print $9}'`

  echo "process $masterdate master ztd"
  set LON_MIN = `cat $mztd.rsc | grep X_FIRST | awk '{print $2}'`
  set LAT_MAX = `cat $mztd.rsc | grep Y_FIRST | awk '{print $2}'`
  set WIDTH = `cat $mztd.rsc | grep WIDTH | awk '{print $2}'`
  set LENGTH = `cat $mztd.rsc | grep FILE_LENGTH | awk '{print $2}'`
  #set LON_STEP = `cat $mztd.rsc | grep X_STEP | awk '{print $2}'`
  set LON_STEP = 0.0008333333333333
  set LAT_STEP = -0.0008333333333333
  #set LAT_STEP = `cat $mztd.rsc | grep Y_STEP | awk '{print $2}'`
  set LON_MAX = `echo $LON_MIN $LON_STEP $WIDTH | awk '{printf("%3.5f",$1+$2*($3-1))}'`
  set LAT_MIN = `echo $LAT_MAX $LAT_STEP $LENGTH | awk '{printf("%3.5f",$1+$2*($3-1))}'`
  set region = $LON_MIN/$LON_MAX/$LAT_MIN/$LAT_MAX
  gmt xyz2grd $mztd -G$mztdgrd -R$region -I$LON_STEP -di0 -ZTLf

  echo "process $slavedate slave ztd"
  set LON_MIN = `cat $sztd.rsc | grep X_FIRST | awk '{print $2}'`
  set LAT_MAX = `cat $sztd.rsc | grep Y_FIRST | awk '{print $2}'`
  set WIDTH = `cat $sztd.rsc | grep WIDTH | awk '{print $2}'`
  set LENGTH = `cat $sztd.rsc | grep FILE_LENGTH | awk '{print $2}'`
  #set LON_STEP = `cat $sztd.rsc | grep X_STEP | awk '{print $2}'`
  #set LAT_STEP = `cat $sztd.rsc | grep Y_STEP | awk '{print $2}'`
  set LON_STEP = 0.0008333333333333
  set LAT_STEP = -0.0008333333333333
  set LON_MAX = `echo $LON_MIN $LON_STEP $WIDTH | awk '{printf("%3.8f",$1+$2*($3-1))}'`
  set LAT_MIN = `echo $LAT_MAX $LAT_STEP $LENGTH | awk '{printf("%3.8f",$1+$2*($3-1))}'`
  set region = $LON_MIN/$LON_MAX/$LAT_MIN/$LAT_MAX
  gmt xyz2grd $sztd -G$sztdgrd -R$region -I$LON_STEP -di0 -ZTLf

  # time differencing for ztd and convert from m to rad
  echo "Make time differencing"
  gmt grdmath $sztdgrd $mztdgrd SUB = diff.grd
  gmt grdmath diff.grd 4 MUL $PI MUL $wavelength DIV = diff_ztd.grd
  # convert from zenith direction to InSAR LOS
  gmt grdsample look_ang_cos.grd -Rdiff_ztd.grd -Gtmp_look_ang_cos.grd
  gmt grdmath diff_ztd.grd tmp_look_ang_cos.grd DIV = diff_delay_los.grd
  rm -f diff.grd diff_ztd.grd tmp_look_ang_cos.grd

  echo "project from geographic coordinate to radar coordinate"
  proj_ll2ra.csh trans.dat diff_delay_los.grd temp_ra.grd
  nearest_grid temp_ra.grd temp_ra_int.grd 300
  gmt grdsample temp_ra_int.grd -R$unwphase -Gdiff_delay_los_ra.grd -V   #resample to gird of unwrap.grd
  gmt grdmath diff_delay_los_ra.grd $unwphase OR = diff_delay_los_ra.grd
  rm -f temp_ra.grd temp_ra_int.grd

  # space differencing, set reference area
  echo "Make space differencing"
  gmt grdcut diff_delay_los_ra.grd -R$ref_minpixel/$ref_maxpixel/$ref_minline/$ref_maxline -Gref.grd
  set ref_gacos = `gmt grdinfo -C -L2 ref.grd | awk '{print $12}'`
  gmt grdmath diff_delay_los_ra.grd $ref_gacos SUB = diff_delay_los_ra.grd
  rm -f ref.grd

  gmt grdcut $unwphase -R$ref_minpixel/$ref_maxpixel/$ref_minline/$ref_maxline -Gref.grd
  set ref_phase = `gmt grdinfo -C -L2 ref.grd | awk '{print $12}'`
  gmt grdmath $unwphase $ref_phase SUB = unwrap_referenced.grd

  #Make correction
  gmt grdmath unwrap_referenced.grd diff_delay_los_ra.grd SUB = unwrap_gacos_corrected.grd

  ########## set GMT parameters for plotting ##############
  ########################################################
  rm -f gmt.conf
  ## GMT parameters
  gmt set MAP_FRAME_WIDTH  0.05 MAP_FRAME_PEN 1.5 MAP_FRAME_TYPE plain FORMAT_GEO_MAP ddd:mm:ssF \
  MAP_TICK_LENGTH 0.03 MAP_LOGO FALSE FONT_LABEL 8 PS_MEDIA A4 \
  FONT_TITLE 12 FONT_ANNOT_PRIMARY 8 MAP_TITLE_OFFSET 0.2
  # plot the results
  echo "Make figures"
  # plot the unwrapped interferogram
  set tmp = `gmt grdinfo -C -L2 unwrap_referenced.grd`
  set caxmin = `echo $tmp | awk '{printf("%5.2f",$12-3*$13)}'`
  set caxmax = `echo $tmp | awk '{printf("%5.2f",$12+3*$13)}'`
  gmt makecpt -Cjet -Z -T$caxmin/$caxmax/0.1 -D > temp.cpt
  rm -f $PSOUT
  gmt grdimage unwrap_referenced.grd -Runwrap_referenced.grd $scale -Ctemp.cpt -Bxaf -Byaf -BWSne+t"Unwrapped phase" -V -X2c -Y8c -K > $PSOUT
  #gmt psscale -R$phaseout -J -DJTC+w5i/0.2i+h+e -Ctemp.cpt -Baf+l"Unwrapped phase (rad)" -K -O >> $PSOUT

  # plot the GACOS delay
  #gmt makecpt -Cjet -Z -T$caxmin/$caxmax/0.1 -D > temp.cpt
  gmt grdimage diff_delay_los_ra.grd -Rdiff_delay_los_ra.grd $scale -Ctemp.cpt -Bxaf -Byaf -BWSne+t"GACOS delay" -V -X7.2c -K -O >> $PSOUT
  #gmt psscale -Rdelaylos_cut.grd -J -DJTC+w5i/0.2i+h+e -Ctemp.cpt -Baf+l"GACOS delay (rad)" -K -O >> $PSOUT

  #plot the corrected interferogram
  #gmt makecpt -Cjet -Z -T$caxmin/$caxmax/0.1 -D > temp.cpt
  gmt grdimage unwrap_gacos_corrected.grd -Runwrap_gacos_corrected.grd $scale -Ctemp.cpt -Bxaf -Byaf -BWSne+t"After correction" -V -X7.2c -K -O >> $PSOUT
  gmt psscale -Dx-8.4c/-1.0c+w8.4c/0.25c+h+e -Ctemp.cpt -Bx+l"LOS range change (rad)" -B5 -O --FONT_LABEL=8 >> $PSOUT
  gmt psconvert $PSOUT -A -Tj -P -E300

  if ($isplanar == 1) then
    echo "Detrend"
    gmt grdtrend unwrap_gacos_corrected.grd -N3 -Dunwrap_gacos_corrected_detrended.grd
    #plot the detrend interferogram
    #gmt makecpt -Cjet -Z -T$caxmin/$caxmax/0.1 -D > temp.cpt
    gmt grdimage unwrap_gacos_corrected_detrended.grd -Runwrap_gacos_corrected_detrended.grd $scale -Ctemp.cpt -Bxaf -Byaf -BWSne+t"After trend removal" -V -X2c -Y5c -K -P > unwrap_gacos_corrected_detrended.ps
    gmt psscale -Dx0c/-1.0c+w6c/0.2c+h+e -Ctemp.cpt -Bx+l"LOS range change (rad)" -B5 -O --FONT_LABEL=8 >> unwrap_gacos_corrected_detrended.ps
    gmt psconvert unwrap_gacos_corrected_detrended.ps -A -Tj -P -E300
  endif

  cd ..
