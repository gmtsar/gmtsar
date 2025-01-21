/*      $Id$    */
/*****************************************************************************************
 *  Program to stitch SLCs and PRMs of TOPS images together. *
 *****************************************************************************************
 * Creator: Xiaohua(Eric) XU and David Sandwell * (Scripps Institution of
 *Oceanography)                                        * Date: 03/01/2016 *
 ****************************************************************************************/
/*****************************************************************************************
 *  Modification history: *
 ****************************************************************************************/

#include "PRM.h"
#include "gmtsar.h"
#include <math.h>
#include <stdio.h>
#include <string.h>

char *USAGE = "\n\nUSAGE: stitch_tops stem.in output_stem\n"
              "\noutput: stem.SLC stem.PRM\n"
              "\nnote: please put the files to stem.in in the order of time.\n"
              "\n      make sure all images have same rng_samp_rate and PRF. \n";

int calc_offset(struct PRM prm1, struct PRM prm2, int nl, int nl0){

    FILE *SLC1, *SLC2;
    int ntot,i,j,k,i1,j1,k1,width,width2,height,imax,jmax,is,js,ib = 10; // boundaries not used 
    short *f1, *f2, *buf;
    double sum1, sum2, ave1, ave2, sumc, corr, denom, maxcorr = -9999.0, r1, r2;
    // set search radius
    int ns = 2;
    imax = 0;
    jmax = 0;
    
    if ((SLC1 = fopen(prm1.SLC_file, "rb")) == NULL)
        die("Couldn't open input SLC file: \n", prm1.SLC_file);
    if ((SLC2 = fopen(prm2.SLC_file, "rb")) == NULL)
        die("Couldn't open input SLC file: \n", prm2.SLC_file);
    
    width = prm1.num_rng_bins;
    width2 = prm2.num_rng_bins; 
    height = nl0-nl+1;
    if (width != width2)
        die("Number of Range bins different for xcorr \n", "");

    /* run xcorr to figure out shift */
    f1 = (short *)malloc(width * 2 * sizeof(short) * (nl0-nl+1));
    f2 = (short *)malloc(width * 2 * sizeof(short) * (nl0-nl+1));
	buf = (short *)malloc(width * 2 * sizeof(short) * 2);

    for (i = 1; i < nl; i++)
        fread(buf, sizeof(short), width * 2, SLC1);
        
    for (i = 0; i < height; i++) {
        fread(buf, sizeof(short), width * 2, SLC1);
        for (j = 0; j < width; j++) {
            f1[j+i*width] = sqrt(buf[j*2]*buf[j*2] + buf[j*2+1]*buf[j*2+1]);
        }
    }
    fclose(SLC1);

    for (i = 0; i < height; i++) {
        fread(buf, sizeof(short), width * 2, SLC2);
        for (j = 0; j < width; j++) {
            f2[j+i*width] = sqrt(buf[j*2]*buf[j*2] + buf[j*2+1]*buf[j*2+1]);
        }
    }
    fclose(SLC2);

    // comput average
    ntot = 0;
    sum1 = sum2 = 0.0;

    for (i = 0; i < height; i++) {
        for (j = 0; j < width; j++) {
            k = i * width + j;
            ntot++;
            sum1 = sum1 + f1[k];
            sum2 = sum2 + f2[k];
        }   
    }   
    ave1 = sum1 / ntot;
    ave2 = sum2 / ntot;

    for (is = -ns; is <= ns; is++) {
        for (js = -ns; js <= ns; js++) {
            ntot = 0;
            sumc = sum1 = sum2 = 0.0;
            for (i = 0 + ib; i < height - ib; i++) {
                i1 = i - is;
                for (j = 0 + ib; j < width - ib; j++) {
                    j1 = j - js;
                    k = i * width + j;
                    k1 = i1 * width + j1;
                    r1 = f1[k] - ave1;
                    r2 = f2[k1] - ave2;
                    if (!isnan(r1) && !isnan(r2)) {
                        sumc = sumc + r1 * r2;
                        sum1 = sum1 + r1 * r1;
                        sum2 = sum2 + r2 * r2;
                    }
                }
            }
            corr = 0;
            denom = sum1*sum2;
            if (denom > 0.)
                corr = sumc / sqrt(denom);
            if (corr > maxcorr) {
                maxcorr = corr;
                imax = is;
                jmax = js;
            }
    
        }
    }
    printf(" optimal: rshift = %d  ashift = %d  max_correlation = %f\n", jmax, imax, maxcorr);
    return(imax);
}

int main(int argc, char **argv) {

	/* define variables */
	FILE *stemin, *SLCin, *SLCout, *PRM;
	struct PRM prm1, prm2, prm3;
	char stem[100][200], tmp_str[200];
	int ii, jj, nfile = 0, ntl = 0, nl, width, nl0, width2;
	int n_start, n_end, dr = 0;
	double prf, t1, t2;
	short *buf;
    int line_offset = 0, line_offset_total = 0;

	if (argc != 3)
		die(USAGE, "");

	/* read in the filelist */
	if ((stemin = fopen(argv[1], "r")) == NULL)
		die("Couldn't open stem file: \n", argv[1]);
	while (fscanf(stemin, "%s", tmp_str) != EOF) {
		strcpy(stem[nfile], tmp_str);
		nfile++;
	}
	fclose(stemin);
	fprintf(stderr, "Number of Files to be stitched is %d \n", nfile);

	if (nfile < 2)
		die("At least two files are needed for stitching\n", "");

	/* read in the first prarmeter file */
	strcpy(tmp_str, stem[0]);
	strcat(tmp_str, ".PRM");
	if ((PRM = fopen(tmp_str, "r")) == NULL)
		die("Couldn't open prm file: \n", tmp_str);
	null_sio_struct(&prm1);
	get_sio_struct(PRM, &prm1);
	fclose(PRM);
	t1 = prm1.clock_start + (prm1.ashift + prm1.sub_int_a) / prm1.prf / 86400.0;
	width = prm1.num_rng_bins;
	width2 = prm1.num_rng_bins;
	prf = prm1.prf;
	nl0 = prm1.num_lines;
    prm3 = prm1;

	/* malloc buf for copying, make some extra space in case the width of two
	 * images are different */
	buf = (short *)malloc(width * 2 * sizeof(short) * 2);

	/* open the output SLC file */
	strcpy(tmp_str, argv[2]);
	strcat(tmp_str, ".SLC");
	if ((SLCout = fopen(tmp_str, "wb")) == NULL)
		die("Couldn't open output SLC file: \n", tmp_str);


	/* loop over all the images */
	for (ii = 1; ii < nfile; ii++) {
		/* read in parameters for next image*/
		strcpy(tmp_str, stem[ii]);
		strcat(tmp_str, ".PRM");
		if ((PRM = fopen(tmp_str, "r")) == NULL)
			die("Couldn't open prm file: \n", tmp_str);
		null_sio_struct(&prm2);
		get_sio_struct(PRM, &prm2);
		fclose(PRM);
		t2 = prm2.clock_start + (prm2.ashift + prm2.sub_int_a) / prm2.prf / 86400.0;

		/* check whether the parameters match the first image */
		if (prm2.fs != prm1.fs)
			die("Images have different range sampling rate... \n", "");
		if (fabs(prm2.prf - prf) > 0.00001)
			die("Images have different PRF... \n", "");
		/* open the previous SLC file */
		strcpy(tmp_str, stem[ii - 1]);
		strcat(tmp_str, ".SLC");
		if ((SLCin = fopen(tmp_str, "rb")) == NULL)
			die("Couldn't open input SLC file: \n", tmp_str);

		/* figure out how many lines to be written and check whether image has that
		 * many lines */
		nl = (floor)((t2 - t1) * 86400.0 * prf + 0.5);
		if (nl > nl0)
			die("Images do not have overlapped region \n", "");

		n_start = ntl - (floor)((t1 - prm1.clock_start - (prm1.ashift + prm1.sub_int_a) / prf / 86400.0) * 86400.0 * prf + 0.5);
        if (line_offset_total != 0) {
            printf("Need to shift lines by %d\n",line_offset_total);
            n_start = n_start - line_offset_total;
        }
		n_end = floor((float)(nl0 + nl) / 2.0 + 0.5);

        line_offset = calc_offset(prm3, prm2, nl+1, nl0);
        line_offset_total = line_offset_total + line_offset;
  
		/* write the SLC files */
		fprintf(stderr, "Parsing %d lines...\n", n_start);
		for (jj = 1; jj <= n_start; jj++)
			fread(buf, sizeof(short), width2 * 2, SLCin);

		fprintf(stderr, "Writing Image %d, from line %d to line %d (%d)...\n", ii, 1 + n_start, n_end, width2);
		for (jj = 1 + n_start; jj <= n_end; jj++) {
			fread(buf, sizeof(short), width2 * 2, SLCin);
			if (dr < 0) {
				fwrite(&buf[-dr], sizeof(short), width * 2, SLCout);
			}
			else if (dr > 0) {
				fwrite(&buf[width * 2], sizeof(short), dr * 2, SLCout);
				fwrite(buf, sizeof(short), (width - dr) * 2, SLCout);
			}
			else {
				fwrite(buf, sizeof(short), width * 2, SLCout);
			}
			ntl++;
		}
		fprintf(stderr, "%d lines written...\n", n_end - n_start);
		dr = (int)((prm2.near_range - prm1.near_range) / (299792458.0 / prm2.fs / 2) + 0.5);
		fprintf(stderr, "%d diff in range...\n", dr);
		t1 = t2;
		nl0 = prm2.num_lines;
		width2 = prm2.num_rng_bins;
        prm3 = prm2;
		fclose(SLCin);
	}

	/* open the last SLC file and write to the output SLC */
	strcpy(tmp_str, stem[nfile - 1]);
	strcat(tmp_str, ".SLC");
	if ((SLCin = fopen(tmp_str, "rb")) == NULL)
		die("Couldn't open input SLC file: \n", tmp_str);
	nl = prm2.num_lines;
	n_start = ntl - (floor)((t1 - prm1.clock_start - (prm1.ashift + prm1.sub_int_a) / prf / 86400.0) * 86400.0 * prf + 0.5);
    if (line_offset_total != 0) {
        printf("Need to shift lines by %d\n",line_offset_total);
        n_start = n_start - line_offset_total;
    }
    
    if (line_offset!= 0) {
        //printf("Need to shift lines by %d\n",line_offset);
        n_start = n_start - line_offset;
    }
	/* writing the last SLC */
	fprintf(stderr, "Parsing %d lines...\n", n_start);
	for (jj = 1; jj <= n_start; jj++)
		fread(buf, sizeof(short), width2 * 2, SLCin);
	fprintf(stderr, "Writing Image %d, from line %d to line %d (%d)...\n", ii, 1 + n_start, nl, width2);
	for (jj = 1 + n_start; jj <= nl; jj++) {
		fread(buf, sizeof(short), width2 * 2, SLCin);
		if (dr < 0) {
			fwrite(&buf[-dr], sizeof(short), width * 2, SLCout);
		}
		else if (dr > 0) {
			fwrite(&buf[width * 2], sizeof(short), dr * 2, SLCout);
			fwrite(buf, sizeof(short), (width - dr) * 2, SLCout);
		}
		else {
			fwrite(buf, sizeof(short), width * 2, SLCout);
		}
		ntl++;
	}
	fprintf(stderr, "%d lines written...\n", nl - n_start);
	fclose(SLCout);

	/* prepare the output PRM */
	strcpy(tmp_str, argv[2]);
	strcat(tmp_str, ".PRM");
	if ((PRM = fopen(tmp_str, "w")) == NULL)
		die("Couldn't open output PRM file: \n", tmp_str);
	prm1.num_lines = ntl - ntl % 4;
	prm1.nrows = prm1.num_lines;
	prm1.num_valid_az = prm1.num_lines;
	prm1.SC_clock_stop = prm1.SC_clock_start + prm1.num_lines / prf / 86400;
	prm1.clock_stop = prm1.clock_start + prm1.num_lines / prf / 86400;

	strcpy(prm1.input_file, argv[2]);
	strcat(prm1.input_file, ".raw");
	strcpy(prm1.led_file, argv[2]);
	strcat(prm1.led_file, ".LED");
	strcpy(prm1.SLC_file, argv[2]);
	strcat(prm1.SLC_file, ".SLC");

	put_sio_struct(prm1, PRM);
	fprintf(stderr, "PRM set for stitched SLC...\n");
	fclose(PRM);
	free(buf);

	return 1;
}
