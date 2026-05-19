#February 18, 2015
#David T. Sandwell

#This is an example to process ALOS L1.0 in the ERSDAC format.  The region is near Palm Springs.
#T213 F0660

#First rename the ERSDAC filenames to corresponding AUIG filenames. Constructing the AUIG names requires
#a bit of searching around in the *.meta files. Why are there two different formats for the dame data!!!!!!
#The number 230210660 must simply have the correct number of digits and the IMG and LED numbers should match for each scene.

#mv PASL10C1005210615471008110011.raw IMG-HH-ALPSRP230210660-H1.1__A
#mv PASL10C1005210615471008110011.ldr LED-ALPSRP230210660-H1.1__A
#mv PASL10C1007060615191008110012.ldr LED-ALPSRP236920660-H1.1__A
#mv PASL10C1007060615191008110012.raw IMG-HH-ALPSRP236920660-H1.1__A

#Now the raw directory should have the following 4 files.
#-rwxr-xr-x+ 1 sandwell  admin  677134452 Feb 18 08:07 IMG-HH-ALPSRP230210660-H1.1__A
#-rwxr-xr-x+ 1 sandwell  admin  677134452 Feb 18 08:07 IMG-HH-ALPSRP236920660-H1.1__A
#-rwxr-xr-x+ 1 sandwell  admin      13776 Feb 18 07:35 LED-ALPSRP230210660-H1.1__A
#-rwxr-xr-x+ 1 sandwell  admin      13776 Feb 18 07:34 LED-ALPSRP236920660-H1.1__A

#Next run the job.

############## Command for GMTSAR ##################
p2p_processing ALOS IMG-HH-ALPSRP230210660-H1.1__A IMG-HH-ALPSRP236920660-H1.1__A
