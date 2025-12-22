/***************************************************************************
 * Creator:  Xiaohua(Eric) XU                                              *
 *           (University of Science and Technology of China                *
 * Date   :  01/23/2023                                                    *
 ***************************************************************************/

/***************************************************************************
 * Modification history:                                                   *
 *                                                                         *
 * Date   :  11/10/25 - DTS - added functionality for real NISAR data      *
 *                                                                         *
 ***************************************************************************/

#include "PRM.h"
#include "hdf5.h"
#include "lib_defs.h"
#include "lib_functions.h"
#include "stateV.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>
#include <stdint.h>

char *USAGE = "\nUsage: make_slc_nsr name_of_input_file name_output output_type scale_factor [region_cut]\n"
              "         (Note region_cut for B should be the same as A.)\n"
              "\nExample: make_slc_nsr "
              "NISAR_L1_PR_RSLC_004_091_A_021_4005_DHDH_A_20251104T120256_20251104T120331_X05004_N_F_J_001.h5 NSR_20251104A AHH 40000 30000/53000/24000/47000 \n"
              "\nOutput: NSR_20251104A.SLC NSR_20251104A.PRM NSR_20251104A.LED \n";

static inline short f32_to_i16_with_checks(float x,
                                           long long *sat_hi,
                                           long long *sat_lo,
                                           long long *zero_conv);

int get_range(char *str, int *xl, int *xh, int *yl, int *yh) {
        
        int ii = 0, jj = 0, kk = 0, rr[4];
        char c;
        char tmp_c[128];

        c = str[ii]; 
        while (c != '\0') {
                if (c != '/') {
                        tmp_c[jj] = c;
                        jj++;
                }
                else if (c == '/') {
                        tmp_c[jj] = '\0';
                        rr[kk] = atoi(tmp_c);
                        jj = 0; 
                        kk++;
                }
                ii++;
                c = str[ii];
        }           
        tmp_c[jj] = c;
        rr[kk] = atoi(tmp_c);
        *xl = rr[0]; 
        *xh = rr[1];
        *yl = rr[2];
        *yh = rr[3];

        return (1);
}

int hdf5_read(void *output, hid_t file, char *n_group, char *n_dset, char *n_attr, int c) {
    hid_t memtype, type, group = -1, dset = -1, attr = -1, tmp_id, space;
    herr_t status;
    size_t sdim;
    int ndims;
    (void)status;
    (void)ndims;

    tmp_id = file;
    if (strlen(n_group) > 0) {
        group = H5Gopen(tmp_id, n_group, H5P_DEFAULT);
        tmp_id = group;
    }   
    if (strlen(n_dset) > 0) {
        dset = H5Dopen(tmp_id, n_dset, H5P_DEFAULT);
        tmp_id = dset;
    }   
    if (strlen(n_attr) > 0) {
        attr = H5Aopen(tmp_id, n_attr, H5P_DEFAULT);
        tmp_id = attr;
    }   

    if (c == 'c') {
        memtype = H5Tcopy(H5T_C_S1);
        type = H5Aget_type(tmp_id);
        sdim = H5Tget_size(type);
        sdim++;
        status = H5Tset_size(memtype, sdim);
    }   
    else if (c == 's'){
        memtype = H5Tcopy(H5T_C_S1);
        type = H5Dget_type(tmp_id);
        sdim = H5Tget_size(type);
        sdim++;
        status = H5Tset_size(memtype, sdim);
    }
    else if (c == 'd') {
        memtype = H5T_NATIVE_DOUBLE;
    }   
    else if (c == 'i' || c == 'n') {
        memtype = H5T_NATIVE_INT;
    }   
    else if (c == 'u') {
        memtype = H5T_STD_U8LE;
    }
    else if (c == 'f') {
        memtype = H5T_NATIVE_FLOAT;
    }   

    if (tmp_id == attr) {
        status = H5Aread(tmp_id, memtype, output);
    }   
    else if (tmp_id == dset && c == 'n') {
        space = H5Dget_space(dset);
        ndims = H5Sget_simple_extent_dims(space, output, NULL);
    }   
    else if (tmp_id == dset) {
        space = H5Dget_space(dset);
        H5Dread(tmp_id, memtype,space, H5S_ALL, H5P_DEFAULT,output);
    } 
    else {
        return (-1);
    }   
    
    return (1);
}

int write_slc_hdf5(hid_t input, FILE *slc, char *mode, double dfact, int *xlp, int *xhp, int *ylp, int *yhp) {

    int64_t i, j, ij, width, height, width2=0, height2=0i, count = 0;
    int xl, xh, yl, yh, wt, ht;
    double tmp_d[200],rs_A,rs_B,bw_fac,sum2 = 0;
    short *tmp;
    float *buf;
    hsize_t dims[10];
    hid_t memtype, dset, group;
    herr_t status;
    (void) status;
    long long sat_hi_count = 0;
    long long sat_lo_count = 0;
    long long zero_conv_count = 0;
    char freq[10], type[10], Group[200];
    freq[0] = mode[0]; freq[1] = '\0';
    xl = *xlp;
    xh = *xhp;
    yl = *ylp;
    yh = *yhp;
    strcpy(type,&mode[1]);
    printf("dfact %f \n", dfact);

/* get the ratio of bandwidth A to bandwidth B */

    strcpy(Group,"/science/LSAR/RSLC/swaths/frequencyA");
    hdf5_read(tmp_d, input, Group, "slantRangeSpacing", "", 'd'); 
    rs_A = tmp_d[0];
    strcpy(Group,"/science/LSAR/RSLC/swaths/frequencyB");
    hdf5_read(tmp_d, input, Group, "slantRangeSpacing", "", 'd'); 
    rs_B = tmp_d[0];
    bw_fac = rs_B/rs_A;
    printf("bw_fac %f \n", bw_fac);

    if (strcmp(freq, "A") == 0) {
      strcpy(Group,"/science/LSAR/RSLC/swaths/frequencyA");
    }
    else if (strcmp(freq, "B") == 0) {
      strcpy(Group,"/science/LSAR/RSLC/swaths/frequencyB");
    }
    else {
      fprintf(stderr,"Invalid frequency type\n");
      exit(1);
    }

/* make the B region bw_fac times smaller and completely cover A */

    if (strcmp(freq, "B") == 0 && xh > 0) {
      xl = (int)((xl)/bw_fac);
      xh = (int)((xh)/bw_fac)+1;
    }
 
    hdf5_read(dims, input, Group, type, "", 'n');

    width = (int)dims[1];
    height = (int)dims[0];
    printf("Data size %llu x %llu ... \n", (unsigned long long)dims[1], (unsigned long long)dims[0]);


    if(xl == 0 && xh == 0 && yl == 0 && yh == 0) {
	xl = 0; xh = width; yl = 0; yh = height;
    }
    if(xl < 0 || xh > width || xl >= xh || yl < 0 || yh > height || yl >= yh)  
	die("wrong range ", "");

/* the original NISAR image data are stored as Cfloat32. GMTSAR uses Cint16.*/

    buf = (float*) malloc((size_t)height * (size_t)width * 2 * sizeof(float));
    tmp = (short*) malloc((size_t)width * 2 * sizeof(short));
    if (!buf || !tmp) {
        fprintf(stderr, "OOM: need %.1f GB for buf, %.2f MB for tmp\n",
            (double)height * width * 2 * sizeof(float) / (1024.0*1024.0*1024.0),
            (double)width * 2 * sizeof(short) / (1024.0*1024.0));
    free(buf); free(tmp);
        return -1;
    }

    group = H5Gopen(input, Group, H5P_DEFAULT);
    dset = H5Dopen(group, type, H5P_DEFAULT);

    memtype = H5Dget_type(dset);

    status = H5Dread(dset, memtype, H5S_ALL, H5S_ALL, H5P_DEFAULT, buf);

/* make sure the height and width are divisible by 4 */

    wt = (xh-xl);
    ht = (yh-yl);
    width2 = wt - wt%4;
    height2 = ht - ht%4;
    xh = xl + width2;
    yh = yl + height2;

    printf("Writing SLC..Image Size: %lld X %lld... \n", (long long)width2, (long long)height2);

    ij = 0;
    for (i = yl; i < yh; i++) {
        for (j = xl; j < xh; j++) {
            tmp[(j-xl)*2] = f32_to_i16_with_checks((float)(buf[i * width * 2 + j*2]*dfact), &sat_hi_count, &sat_lo_count, &zero_conv_count);
            tmp[(j-xl)*2 + 1] = f32_to_i16_with_checks((float)(buf[i * width * 2 +  j*2 + 1]*dfact), &sat_hi_count, &sat_lo_count, &zero_conv_count);
	    ij=ij+1;
            sum2 = sum2 + tmp[(j-xl)*2]*tmp[(j-xl)*2];
            count = count + 1;

        }
        fwrite(tmp, sizeof(short), (xh-xl)*2 , slc);
    }

/*  put the updated range into the pointers to use them for the PRM file */

    *xlp = xl;
    *xhp = xh;
    *ylp = yl;
    *yhp = yh;

    printf("fraction clamped to INT16_MAX: %lf\n", (float)sat_hi_count/ij);
    printf("fraction clamped to INT16_MIN: %lf\n", (float)sat_lo_count/ij);
    printf("fraction set to 0 after cast: %lf\n", (float)zero_conv_count/ij);
    printf("sigma of integers (2048 < sig < 8192) %d\n", (int)sqrt(sum2/count));
    free(buf);
    free(tmp);
    return (1);
}

int pop_led_hdf5(hid_t input, state_vector *sv) {
    int i, count, iy; 
    char tmp_c[200], date[200];
    double t[200], t0, t_tmp;
    double x[600], v[600];

    hdf5_read(tmp_c, input, "/science/LSAR/RSLC/metadata/orbit", "time", "units", 'c');

    cat_nums(date,tmp_c);
    str_date2JD(tmp_c, date);
    t0 = str2double(tmp_c);

    date[4] = '\0';
    iy = (int)str2double(date);

    hdf5_read(&count, input, "/science/LSAR/RSLC/metadata/orbit", "time", "", 'n');

    hdf5_read(t, input, "/science/LSAR/RSLC/metadata/orbit", "time", "", 'd');
    hdf5_read(x, input, "/science/LSAR/RSLC/metadata/orbit", "position", "", 'd');
    hdf5_read(v, input, "/science/LSAR/RSLC/metadata/orbit", "velocity", "", 'd');

    for (i = 0; i < count; i++) {
        t_tmp = t[i] / 86400.0 + t0; 
        sv[i].yr = iy; 
        sv[i].jd = (int)(t_tmp - trunc(t_tmp / 1000.0) * 1000.0);
        sv[i].sec = (t_tmp - trunc(t_tmp)) * 86400.0;
        sv[i].x = (double)x[i * 3]; 
        sv[i].y = (double)x[i * 3 + 1]; 
        sv[i].z = (double)x[i * 3 + 2]; 
        sv[i].vx = (double)v[i * 3]; 
        sv[i].vy = (double)v[i * 3 + 1]; 
        sv[i].vz = (double)v[i * 3 + 2]; 
    }   

    printf("%d Lines Written for Orbit...\n", count);

    return (count);
}

int write_orb(state_vector *sv, FILE *fp, int n) {
    int i;
    double dt;

    dt = trunc((sv[1].sec) * 1e4) / 1e4 - trunc((sv[0].sec) * 1e4) / 1e4;
    if (n <= 1)
        return (-1);
    fprintf(fp, "%d %d %d %.3lf %.3lf \n", n, sv[0].yr, sv[0].jd, sv[0].sec, dt);
    for (i = 0; i < n; i++) {
        fprintf(fp, "%d %d %.3lf %.6lf %.6lf %.6lf %.8lf %.8lf %.8lf \n", sv[i].yr, sv[i].jd, sv[i].sec, sv[i].x, sv[i].y,
                sv[i].z, sv[i].vx, sv[i].vy, sv[i].vz);
    }

    return (1);
}

int pop_prm_hdf5(struct PRM *prm, hid_t input, char *file_name, char *mode, int xl, int xh, int yl, int yh) {
    char tmp_c[200], date[100],iy[100],freq[10],type[10],group[200];
    double tmp_d[200],yr,t[65535]; // not sure howmany time components will be available
    double c_speed = 299792458.0, t0 = 0.0;
    hsize_t dims[10];

    freq[0] = mode[0]; freq[1] = '\0';
    strcpy(type,&mode[1]);

    prm->nlooks = 1;
    prm->rshift = 0;
    prm->ashift = 0;
    prm->sub_int_r = 0.0;
    prm->sub_int_a = 0.0;
    prm->stretch_r = 0.0;
    prm->stretch_a = 0.0;
    prm->a_stretch_r = 0.0;
    prm->a_stretch_a = 0.0;
    prm->first_sample = 1;
    prm->st_rng_bin = 1;
    strasign(prm->dtype, "a", 0, 0);
    prm->SC_identity = 14; /* (1)-ERS1 (2)-ERS2 (3)-Radarsat (4)-Envisat (5)-ALOS
                             (6)-  (7)-TSX (8)-CSK (9)-RS2 (10) Sentinel-1a (14)-NSR*/
    prm->ra = 6378137.00; // equatorial_radius
    prm->rc = 6356752.31; // polar_radius
    strcpy(tmp_c, file_name);
    strcat(tmp_c, ".raw");
    //strcpy(prm->input_file, tmp_c);
    strcpy(tmp_c, file_name);
    strcat(tmp_c, ".LED");
    strcpy(prm->led_file, tmp_c);
    strcpy(tmp_c, file_name);
    strcat(tmp_c, ".SLC");
    strcpy(prm->SLC_file, tmp_c);
    prm->SLC_scale = 1.0;
    prm->xmi = 0.0;
    prm->xmq = 0.0;

    if (strcmp(freq, "A") == 0) {
        strcpy(group,"/science/LSAR/RSLC/swaths/frequencyA");
    } 
    else if (strcmp(freq, "B") == 0) {
        strcpy(group,"/science/LSAR/RSLC/swaths/frequencyB");
    }
    else {
        fprintf(stderr,"Invalid frequency type\n");
        exit(1);
    }
    // using nominal acquisition PRF should be OK too
    hdf5_read(tmp_d, input, group, "slantRangeSpacing", "", 'd'); 
    prm->fs = c_speed/2.0/tmp_d[0];

    // three strings are Group, Dataset and Attributes with the last being datatype
    hdf5_read(tmp_d, input, group, "processedCenterFrequency", "", 'd'); 
    prm->lambda = c_speed/tmp_d[0];

    hdf5_read(tmp_d, input, group, "nominalAcquisitionPRF", "", 'd'); 
    prm->pulsedur = 0.; // this is wrong but not needed for SLC

    hdf5_read(tmp_d, input, group, "processedRangeBandwidth", "", 'd'); 
    prm->chirp_slope = 0.; // this is wrong but not needed for SLC

    hdf5_read(tmp_d, input, "/science/LSAR/RSLC/swaths", "zeroDopplerTimeSpacing", "", 'd'); 
    prm->prf = 1.0/tmp_d[0];

    hdf5_read(t, input, group, "slantRange", "", 'd'); 
    prm->near_range = t[0] + xl * c_speed/(2.*prm->fs);// * c_speed / 2;

    hdf5_read(tmp_c, input, "/science/LSAR/RSLC/swaths", "zeroDopplerTime", "units", 'c'); 
    cat_nums(date,tmp_c);
    strcpy(iy,date);
    iy[4] = '\0';
    yr = str2double(iy);
    str_date2JD(tmp_c, date);
    t0 = str2double(tmp_c);
    hdf5_read(t, input, "/science/LSAR/RSLC/swaths", "zeroDopplerTime", "", 'd'); 
    hdf5_read(tmp_c, input, "/science/LSAR/identification", "zeroDopplerStartTime", "", 's'); 
    prm->clock_start = t0 + (t[0] + yl / prm->prf)/86400.0;
    prm->SC_clock_start = prm->clock_start + yr*1000.0;

    prm->fdd1 = 0.0;
    prm->fddd1 = 0.0;

    hdf5_read(tmp_c, input, "/science/LSAR/identification", "orbitPassDirection", "", 's'); 
    if (strcmp(tmp_c, "Ascending") == 0) {
        strasign(prm->orbdir, "A", 0, 0);
    }
    else {
        strasign(prm->orbdir, "D", 0, 0);
    }

    hdf5_read(tmp_c, input, "/science/LSAR/identification", "lookDirection", "", 's'); 
    if (strcmp(tmp_c, "Right") == 0) {
        strasign(prm->lookdir, "R", 0, 0);
    }
    else {
        strasign(prm->lookdir, "L", 0, 0);
    }

    hdf5_read(dims, input, group, type, "", 'n');
    prm->num_rng_bins = xh - xl;
    prm->num_lines =  yh - yl;

    prm->bytes_per_line = prm->num_rng_bins * 4;
    prm->good_bytes = prm->bytes_per_line;

    prm->SC_clock_stop = prm->SC_clock_start + prm->num_lines / prm->prf / 86400;
    prm->clock_stop = prm->clock_start + prm->num_lines / prm->prf / 86400;
    prm->nrows = prm->num_lines;
    prm->num_valid_az = prm->num_lines;
    prm->num_patches = 1;
    prm->chirp_ext = 0;

    printf("PRM set for Image File...\n");

    return (1);
}

int main(int argc, char **argv) {

    if (argc < 5) {
        die(USAGE, "");
    }

    FILE *OUTPUT_PRM, *OUTPUT_SLC, *OUTPUT_LED;
    char tmp_str[200],mode[10];
    struct PRM prm;
    state_vector sv[200];
    int n, xl=0, xh=0, yl=0, yh=0;
    double dfact;
    hid_t file; 

    strcpy(mode,argv[3]);

    dfact = atof(argv[4]);

    if (argc == 6) {
	get_range(argv[5], &xl, &xh, &yl, &yh);
    }

    if ((file = H5Fopen(argv[1], H5F_ACC_RDONLY, H5P_DEFAULT)) < 0)
        die("Couldn't open HDF5 file: \n", argv[1]);

    // generate the SLC file
    strcpy(tmp_str, argv[2]);
    strcat(tmp_str, ".SLC");

    if ((OUTPUT_SLC = fopen(tmp_str, "wb")) == NULL)
        die("Couldn't open tiff file: \n", tmp_str);

    write_slc_hdf5(file, OUTPUT_SLC,mode,dfact,&xl,&xh,&yl,&yh);
    fclose(OUTPUT_SLC);
    printf("Range after write_SLC xl, xh, yl, yh %d %d %d %d \n",xl, xh, yl, yh);

    null_sio_struct(&prm);
    
    // generate the PRM file
    pop_prm_hdf5(&prm, file, argv[2], mode, xl, xh, yl, yh);

    strcpy(tmp_str, argv[2]);
    strcat(tmp_str, ".PRM");
    if ((OUTPUT_PRM = fopen(tmp_str, "w")) == NULL)
        die("Couldn't open prm file: \n", tmp_str);
    put_sio_struct(prm, OUTPUT_PRM);
    fclose(OUTPUT_PRM);

    // generate the LED file
    n = pop_led_hdf5(file, sv);

    strcpy(tmp_str, argv[2]);
    strcat(tmp_str, ".LED");
    if ((OUTPUT_LED = fopen(tmp_str, "w")) == NULL)
        die("Couldn't open led file: \n", tmp_str);
    write_orb(sv, OUTPUT_LED, n); 
    fclose(OUTPUT_LED);

    H5Fclose(file);

}

static inline short f32_to_i16_with_checks(float x,
                                           long long *sat_hi,
                                           long long *sat_lo,
                                           long long *zero_conv)
{
    if (!isfinite(x)) {
        return (short)0;
    }
    if (x > (float)INT16_MAX) {
        if (sat_hi) (*sat_hi)++;
        return (short)INT16_MAX;
    }
    if (x < (float)INT16_MIN) {
        if (sat_lo) (*sat_lo)++;
        return (short)INT16_MIN;
    }
    short v = (short)x; /* truncates toward zero */
    if (v == 0 && x != 0.0f) {
        if (zero_conv) (*zero_conv)++;
    }
    return v;
}

