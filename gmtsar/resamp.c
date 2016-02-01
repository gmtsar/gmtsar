/*	$Id$	*/
/***************************************************************************
 * resamp resamples a slave image to match the geometry of a master image. * 
 **************************************************************************/

/***************************************************************************
 * Creator:  David T. Sandwell                                             *
 *           (Scripps Institution of Oceanography)                         *
 * Date   :  03/21/13                                                      *
 ***************************************************************************/

/***************************************************************************
 * Modification history:                                                   *
 *                                                                         *
 * DATE                                                                    *
 * 11/18/96     Code largely based on phasediff.                           *
 * 01/11/14     Code modified to use mmap() instead of fread()             *
 * 01/06/15     Code modified to use only integer rshift, ashift for       *
 *              nearest (imode = 1) interpolation.
 ***************************************************************************/

#include "gmtsar.h"
#include <stdio.h>
#include <stdlib.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <sys/mman.h>
#include <fcntl.h>

char    *USAGE = "\nUsage: "
"resamp master.PRM slave.PRM new_slave.PRM intrp \n"
"   master.PRM       - PRM for master imagea \n"
"   slave.PRM        - PRM for slave image \n"
"   new_slave.PRM    - PRM for aligned slave image \n"
"   new_slave.SLC    - SLC for aligned slave image \n"
"   intrp            - interpolation method: 1-nearest; 2-bilinear; 3-biquadratic; 4-bisinc \n \n";

void print_prm_params(struct PRM, struct PRM);
void fix_prm_params(struct PRM *, char *);
void ram2ras(struct PRM , double *, double *);
void nearest(double *, short *, int , int , short *);
void bilinear(double *, short *, int , int , short *);
void bicubic(double *, short *, int , int , short *);
void bicubic_one(double *, double *, double , double , double *);
void bisinc (double *, short *, int , int , short *);
void sinc_one(double *, double *, double , double , double *);

int main (int argc, char **argv)
{
int	ii, jj;
int	debug, intrp;
int	xdimm, ydimm;		/* size of master SLC file */
int	xdims, ydims;		/* size of slave SLC file */
short   *sinn = NULL, *sout = NULL;		/* pointer to input (whole array) and output (row) files.*/
double  ram[2], ras[2] ;	/* range and azimuth locations for master and slave images */
FILE	*SLC_file2 = NULL, *prmout = NULL;
int	fdin;
double  sv_pr[6];
struct	stat statbuf;

struct PRM pm, ps;	

	debug = 0;
        intrp = 2;

	if (argc < 6) die (USAGE,"");

	/* read prm file into two pointers */
	get_prm(&pm, argv[1]);
	get_prm(&ps, argv[2]);
	intrp = atoi(argv[5]);

	if (debug) print_prm_params(pm, ps);

	/* set width and length of the master and slave images */
	xdimm = pm.num_rng_bins;
	ydimm = pm.num_patches * pm.num_valid_az;
	xdims = ps.num_rng_bins;
	ydims = ps.num_patches * ps.num_valid_az;

        /* force integer interpolation if this is nearest neighbor, needed for TOPS */
        if (intrp == 1) {
          sv_pr[0] = ps.sub_int_r;
	  ps.sub_int_r = 0.;
          sv_pr[1] = ps.stretch_r;
          ps.stretch_r = 0.;
          sv_pr[2] = ps.a_stretch_r;
          ps.a_stretch_r = 0.;
          sv_pr[3] = ps.sub_int_a;
          ps.sub_int_a = 0.;
          sv_pr[4] = ps.stretch_a;
          ps.stretch_a = 0.;
          sv_pr[5] = ps.a_stretch_a;
          ps.a_stretch_a = 0.;
        }
	
	/* allocate memory for one row of the slave image */
        if((sout = (short *) malloc(2 * xdimm * sizeof(short))) == NULL){
          fprintf(stderr,"Sorry, couldn't allocate memory for output indata.\n");
          exit(-1);
	}

	/* open the input file, determine its length and mmap the input file */
	if ((fdin = open(ps.SLC_file, O_RDONLY)) < 0)
	  die ("can't open %s for reading", ps.SLC_file);

	if (fstat (fdin,&statbuf) < 0)
	  die ("fstat error"," ");

	if ((sinn = mmap (0, statbuf.st_size, PROT_READ, MAP_SHARED,fdin, 0)) == MAP_FAILED) 
	  die ("mmap error for input"," ");

	/* open the slave slc file for writing and write one row at a time */
 	if ((SLC_file2 = fopen(argv[4],"w")) == NULL) die("Can't open SLCfile for output",argv[4]);

	for(ii=0; ii<ydimm; ii++) {
	   for(jj=0; jj<xdimm; jj++) {

	/* convert master ra to slave ra */

		ram[0] = jj;
		ram[1] = ii; 
		ram2ras(ps,ram,ras);
        
         /*  do nearest, bilinear, bicubic, or sinc interpolation */
	
		if(intrp == 1) {
		nearest  (ras, sinn, ydims, xdims, &sout[2*jj]);
		}
		else if(intrp == 2) {
		bilinear (ras, sinn, ydims, xdims, &sout[2*jj]);
		}
		else if(intrp == 3) {
		bicubic  (ras, sinn, ydims, xdims, &sout[2*jj]);
		}
		else if(intrp == 4) {
		bisinc  (ras, sinn, ydims, xdims, &sout[2*jj]);
		}
	   }
           fwrite(sout, 2*sizeof(short), xdimm, SLC_file2);
	}

        /* restore the affine parameters if this is nearest interpolation */
        if (intrp == 1) {
          ps.sub_int_r = sv_pr[0];
          ps.stretch_r = sv_pr[1];
          ps.a_stretch_r = sv_pr[2];
          ps.sub_int_a = sv_pr[3];
          ps.stretch_a = sv_pr[4];
          ps.a_stretch_a = sv_pr[5];
        }

	/* update and write the slave PRM file */
	ps.num_rng_bins = pm.num_rng_bins;
	ps.fs = pm.fs;
	ps.bytes_per_line = pm.bytes_per_line;
	ps.good_bytes = pm.good_bytes;
	ps.prf = pm.prf;
	ps.num_valid_az = pm.num_valid_az;
	ps.num_lines = pm.num_lines;
	ps.num_patches = pm.num_patches;
        if ((prmout = fopen(argv[3],"w")) == NULL) die("can't open prfile",argv[3]);
	put_sio_struct(ps, prmout);
        fclose(prmout);
	if (munmap(sinn, statbuf.st_size) == -1) die ("mmap error unmapping file"," ");
	close(fdin);
	fclose(SLC_file2);

	return(EXIT_SUCCESS);
}
