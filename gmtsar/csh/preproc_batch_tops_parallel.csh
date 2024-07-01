#!/bin/csh -f

if ($#argv < 4  || $#argv > 6) then
  echo ""
  echo "Usage: preproc_batch_tops_parallel.csh data.in dem.grd n_threads mode [esd_mode]"
  echo "  preprocess and align a set of tops images in data.in, precise orbits required"
  echo ""
  echo "  format of data.in:"
  echo "    image_name:orbit_name"
  echo ""
  echo "  example of data.in"
  echo "    s1a-iw1-slc-vv-20150626...001:s1a-iw1-slc-vv-20150626...001:s1a-iw1-slc-vv-20150626...001:S1A_OPER_AUX_POEORB_V20150601_20150603.EOF"
  echo "    s1a-iw1-slc-vv-20150715...001:s1a-iw1-slc-vv-20150715...001:s1a-iw1-slc-vv-20150715...001:S1A_OPER_AUX_POEORB_V20150625_20150627.EOF"
  echo ""
  echo "  outputs:"
  echo "    baseline.pdf *.PRM *.LED *.SLC"
  echo ""
  echo "  Note:"
  echo "    The names must be in time order in each line to be stitched together"
  echo "    mode 1 is for geometric alignment, mode 2 is to use enhanced spectral diversity"
  echo "    to further coregister the image. For esd_mode check a config file or preproc_batch_tops_esd.csh "
  echo "    for more information. Default is 1 (median value)."
  echo ""
  echo ""
  echo "  Reference: Xu, X., Sandwell, D.T., Tymofyeyeva, E., González-Ortega, A. and Tong, X., "
  echo "    2017. Tectonic and Anthropogenic Deformation at the Cerro Prieto Geothermal "
  echo "    Step-Over Revealed by Sentinel-1A InSAR. IEEE Transactions on Geoscience and "
  echo "    Remote Sensing."
  echo ""
  exit 1
endif

set file = $1
set dem = $2
set ncores = $3
set mode = $4
set esd = 1
if ($#argv == 5) then
  set esd = $5
endif

set masterline = `awk 'NR==1{print $1}' data.in`
set dmaster = `echo $masterline | awk -F: '{print substr($1,16,8)}'`
set omaster = `echo $masterline | awk -F: '{print $NF}'`

# loop through the data.in file and process every pair.
rm preproc.cmd tmp_dirlist
foreach line (`awk 'NR>1{print $1}' data.in`)
  set daligned = `echo $line | awk -F: '{print substr($1,16,8)}'`
  set oaligned = `echo $line | awk -F: '{print $NF}'`
  rm -rf $dmaster"_"$daligned
  mkdir $dmaster"_"$daligned
  echo $dmaster"_"$daligned >> tmp_dirlist
  cd $dmaster"_"$daligned
  ln -s ../*$dmaster*xml .
  ln -s ../*$dmaster*tiff .
  ln -s ../$omaster .
  ln -s ../*$daligned*xml .
  ln -s ../*$daligned*tiff .
  ln -s ../$oaligned .
  ln -s ../dem.grd .
  
  echo $masterline >> data.in
  echo $line >> data.in 
  cd ..

  rm $dmaster"_"$daligned.csh
  echo "cd $dmaster"_"$daligned" >> $dmaster"_"$daligned.csh
  if ($mode == 1) then
    echo "preproc_batch_tops.csh $file $dem 2 >& log " >> $dmaster"_"$daligned.csh
  else
    echo "preproc_batch_tops_esd.csh $file $dem 2 $esd >& log" >> $dmaster"_"$daligned.csh
  endif
  echo "mv *"$daligned"*ALL*PRM .." >> $dmaster"_"$daligned.csh
  echo "mv *"$daligned"*ALL*LED .." >> $dmaster"_"$daligned.csh
  echo "mv *"$daligned"*ALL*SLC .." >> $dmaster"_"$daligned.csh
  echo "cd .. " >> $dmaster"_"$daligned.csh
  chmod +x $dmaster"_"$daligned.csh
  echo "$dmaster'_'$daligned.csh > log_$dmaster'_'$daligned" >> preproc.cmd
end

parallel --jobs $ncores < preproc.cmd

mv $dmaster"_"$daligned/*$dmaster*ALL*PRM .
mv $dmaster"_"$daligned/*$dmaster*ALL*SLC .
mv $dmaster"_"$daligned/*$dmaster*ALL*LED .

# house keeing
foreach line (`cat tmp_dirlist`)
  rm $line.csh
  rm -rf $line
  rm log_$line
end

# produce baseline table 
set masterPRM = `ls *ALL*PRM | grep $dmaster`
ls *ALL*PRM > prmlist
foreach prm_aligned (`cat prmlist`)
  baseline_table.csh $masterPRM $prm_aligned >> baseline_table.dat
  baseline_table.csh $masterPRM $prm_aligned GMT >> table.gmt
end

if($mode == 1) then
  awk '{print 2014+$1/365.25,$2,$7}' < table.gmt > text
  set region = `gmt gmtinfo text -C | awk '{print $1-0.5, $2+0.5, $3-50, $4+50}'`
  gmt pstext text -JX8.8i/6.8i -R$region[1]/$region[2]/$region[3]/$region[4] -D0.2/0.2 -X1.5i -Y1i -K -N -F+f8,Helvetica+j5 > baseline.ps
  awk '{print $1,$2}' < text > text2
  gmt psxy text2 -Sp0.2c -G0 -R -JX -Ba0.5:"year":/a50g00f25:"baseline (m)":WSen -O >> baseline.ps
  rm text text2 table.gmt
endif



