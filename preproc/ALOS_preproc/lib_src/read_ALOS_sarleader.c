/********************************************************************************
 * Creator:  Rob Mellors and David T. Sandwell * (San Diego State University,
 *Scripps Institution of Oceanography)  * Date   :  10/03/2007 *
 ********************************************************************************/
/********************************************************************************
 * Modification history: * Date: 15 August 07 RJM * bug fixes get_orbit_info
 * conversions from string to values altered;          * seemed to break on 64
 * bit linux systems unless verbose flag set; not clear   * why; perhaps there
 * is another underlying problem somewhere...                * make sure that
 * tmp string is null-terminated before passing to atoi          * could be done
 * more elegantly I think                                         * 8/11/08 -
 * added check for SAR mode and added global SAR_mode			* define
 * Q_mean and I_mean for ERSDAC format based on ALOS_format flag * checks for
 * ERSDAC or AUIG format
 * *****************************************************************************/

#include "image_sio.h"
#include "lib_functions.h"

/*
void get_orbit_info(struct ALOS_ORB *, struct SAR_info);
void get_attitude_info(struct ALOS_ATT *, int, struct SAR_info);
void print_binary_position(struct sarleader_binary *, int, FILE *, FILE *);
void read_ALOS_sarleader(FILE *, struct PRM *, struct ALOS_ORB *);
void ALOS_ldr_prm(struct SAR_info, struct PRM *);
*/

void eci2ecr(double[3], double[3], double, double[3], double[3]);
double cal2ut1(int, int[3], double);
int transform_orbits_ecr2eci(struct ALOS_ORB *);

void read_ALOS_sarleader(FILE *ldrfile, struct PRM *prm, struct ALOS_ORB *orb) {
	char tmp[1000];
	char leap_second_flag;
	int i, nitems, num_orbit_points, num_att_points;
	struct SAR_info sar;
	struct sarleader_binary sb;
	struct ALOS_ATT alos_attitude_info; /* not used at present */
	FILE *logfile = NULL;
	char dummy1[100];
	char dummy2[100];

	if (verbose) {
		logfile = fopen("LED.log", "w");
		if (logfile == NULL)
			die("can't open", "LED.log");
		fprintf(stderr, " opened LED log file %s \n", "LED.log");
		if (verbose)
			fprintf(stderr, ".... reading sarleader \n");
	}

	/* allocate memory */
	sar.fixseg = (struct sarleader_fdr_fixseg *)malloc(sizeof(struct sarleader_fdr_fixseg));
	sar.varseg = (struct sarleader_fdr_varseg *)malloc(sizeof(struct sarleader_fdr_varseg));
	sar.dss_ALOS = (struct sarleader_dss_ALOS *)malloc(sizeof(struct sarleader_dss_ALOS));
	sar.platform_ALOS = (struct platform_ALOS *)malloc(sizeof(struct platform_ALOS));
	sar.attitude_info_ALOS = (struct attitude_info_ALOS *)malloc(sizeof(struct attitude_info_ALOS));

	/* read the file  - write output at each stage to assist in debugging */
	/* probably don't need it but useful for keeping track */

	nitems = fread(&sb, sizeof(struct sarleader_binary), 1, ldrfile);
	if (verbose)
		print_binary_position(&sb, nitems, ldrfile, logfile);

	/*
	The SARLEADER_FDR_FIXSEG_RCS defines the format statement;
	SARLEADER_FDR_FIXSEG_RVL is a pointer to the structure. Similarly,
	SARLEADER_FDR_FIXSEG_WCS defines the format for the output. All are defined in
	sarleader_ALOS.h. This way all you have to do is change the .h file and not
	the program each time. In theory.

	RCS are read format (Read Control String)
	RVL are pointers to structure (I forget why I used RVL)
	WCS are write format (Write Control String)
	*/

	fscanf(ldrfile, SARLEADER_FDR_FIXSEG_RCS, SARLEADER_FDR_FIXSEG_RVL(sar.fixseg));
	if (verbose)
		fprintf(logfile, SARLEADER_FDR_FIXSEG_WCS, SARLEADER_FDR_FIXSEG_RVL(sar.fixseg));

	fscanf(ldrfile, SARLEADER_FDR_VARSEG_RCS, SARLEADER_FDR_VARSEG_RVL(sar.varseg));
	if (verbose)
		fprintf(logfile, SARLEADER_FDR_VARSEG_WCS, SARLEADER_FDR_VARSEG_RVL(sar.varseg));

	nitems = fread(&sb, sizeof(struct sarleader_binary), 1, ldrfile);
	if (verbose)
		print_binary_position(&sb, nitems, ldrfile, logfile);

	fscanf(ldrfile, SARLEADER_DSS_RCS_ALOS, SARLEADER_DSS_RVL_ALOS(sar.dss_ALOS));
	if (verbose)
		fprintf(logfile, SARLEADER_DSS_WCS_ALOS, SARLEADER_DSS_RVL_ALOS(sar.dss_ALOS));
	if (prefix_off == 388)
		fseek(ldrfile, 2, SEEK_CUR); //maybe needed?
	/* check format ERSDAC or AUIG */
	if (strncmp(sar.dss_ALOS->processing_system_id, "SKY", 3) == 0)
		ALOS_format = 1;
	if (strncmp(sar.dss_ALOS->processing_system_id, "ALOS", 4) == 0)
		ALOS_format = 0;

	if (verbose)
		fprintf(stderr, " using ALOS_format %d: %3s\n", ALOS_format, sar.dss_ALOS->processing_system_id);

	SAR_mode = -1;
	SAR_mode = atoi(&sar.dss_ALOS->sensor_id_and_mode[13]);
	if (verbose) {
		if (SAR_mode == 0)
			fprintf(stderr, "SAR mode |%.32s| (HIGH RESOLUTION)\n", sar.dss_ALOS->sensor_id_and_mode);
		if (SAR_mode == 1)
			fprintf(stderr, "SAR mode |%.32s| (WIDE OBSERVATION)\n", sar.dss_ALOS->sensor_id_and_mode);
		if (SAR_mode == 2)
			fprintf(stderr, "SAR mode |%.32s| (POLARIMETRY)\n", sar.dss_ALOS->sensor_id_and_mode);
	}
	if (SAR_mode == -1) {
		if (verbose)
			fprintf(stderr, "uncertain SAR mode; assuming high resolution\n");
		SAR_mode = 0;
	}
	if (prefix_off == 388) {
                /* We are reading ALOS 4 Data */
		rewind(ldrfile);
		fseek(ldrfile, 5400, SEEK_CUR);
        }
	nitems = fread(&sb, sizeof(struct sarleader_binary), 1, ldrfile);
	if (verbose)
		print_binary_position(&sb, nitems, ldrfile, logfile);

	fscanf(ldrfile, PLATFORM_RCS_ALOS, PLATFORM_RVL_ALOS(sar.platform_ALOS));
	if (verbose)
		fprintf(logfile, PLATFORM_WCS_ALOS, PLATFORM_RVL_ALOS(sar.platform_ALOS));

	/* read in orbit positions and velocities into the structure sar.position_ALOS
	 */
	/* the number of points should be 28 */

	num_orbit_points = atoi(strncpy(dummy1, sar.platform_ALOS->num_data_points, sizeof(sar.platform_ALOS->num_data_points)));

	sar.position_ALOS = (struct position_vector_ALOS *)malloc(num_orbit_points * sizeof(struct position_vector_ALOS));

	if ((verbose) && (num_orbit_points != 28))
		fprintf(stderr, "Warning: number of orbit points %d != 28\n", num_orbit_points);
	if (verbose)
		fprintf(stderr, ".... reading sarleader %d\n", num_orbit_points);
	for (i = 0; i < num_orbit_points; i++) {
		fscanf(ldrfile, POSITION_VECTOR_RCS_ALOS, POSITION_VECTOR_RVL_ALOS(&sar.position_ALOS[i]));
		if (verbose)
			fprintf(logfile, POSITION_VECTOR_WCS_ALOS, POSITION_VECTOR_RVL_ALOS(&sar.position_ALOS[i]));
	}

	/*  mostly blanks with a leap second in between; ought to put in structure  */
	fscanf(ldrfile, "%18c%1c%579c", &tmp[0], &leap_second_flag, &tmp[0]);

	nitems = fread(&sb, sizeof(struct sarleader_binary), 1, ldrfile);
	if (verbose)
		print_binary_position(&sb, nitems, ldrfile, logfile);

	/* read in attitude data - should be 22 points of pitch, yaw, and roll */
	fscanf(ldrfile, ATTITUDE_INFO_RCS_ALOS, ATTITUDE_INFO_RVL_ALOS(sar.attitude_info_ALOS));
	if (verbose)
		fprintf(logfile, ATTITUDE_INFO_WCS_ALOS, ATTITUDE_INFO_RVL_ALOS(sar.attitude_info_ALOS));

	num_att_points =
	    atoi(strncpy(dummy2, sar.attitude_info_ALOS->num_att_data_points, sizeof(sar.attitude_info_ALOS->num_att_data_points)));

	if (verbose)
		if (num_att_points != 22)
			fprintf(stderr, "Warning: number of attitude points %d != 22\n", num_att_points);

	if (verbose)
		fprintf(stderr, ".... reading sarleader %d\n", num_att_points);
	sar.attitude_ALOS = (struct attitude_data_ALOS *)malloc(num_att_points * sizeof(struct attitude_data_ALOS));
	for (i = 0; i < num_att_points; i++) {
		fscanf(ldrfile, ATTITUDE_DATA_RCS_ALOS, ATTITUDE_DATA_RVL_ALOS(&sar.attitude_ALOS[i]));
		if (verbose)
			fprintf(logfile, ATTITUDE_DATA_WCS_ALOS, ATTITUDE_DATA_RVL_ALOS(&sar.attitude_ALOS[i]));
	}

	/* now create the prm file */
	ALOS_ldr_prm(sar, prm);

	/* get orbit and attitude information */
	/* read from sar info and put into alos_orbit_info and alos_attitude_info */

	/* debug by Xiaopeng Tong
	        fprintf(stderr,"debugging the readleader file\n");
	        fprintf(stderr,"tmp = %s",dummy1);
	        fprintf(stderr,"%d\n",num_orbit_points);
	        fprintf(stderr,"num_att_data_points =
	   %s\n",sar.attitude_info_ALOS->num_att_data_points); fprintf(stderr,"tmp =
	   %s\n",dummy2);
	        fprintf(stderr,"%d,%d\n",num_att_points,sizeof(sar.attitude_info_ALOS->num_att_data_points));
	        fprintf(stderr,"num_data_points =
	   %s\n",sar.platform_ALOS->num_data_points); fprintf(stderr,"sizeof =
	   %d\n",sizeof(sar.platform_ALOS->num_data_points));
	        fprintf(stderr,"%d\n",num_orbit_points);
	*/

	orb->nd = num_orbit_points;

	get_orbit_info(orb, sar);

	/* correct ERSDAC from earth-centered-rotating to fixed */
	if (ALOS_format == 1)
		transform_orbits_ecr2eci(orb);

	get_attitude_info(&alos_attitude_info, num_att_points, sar);

	if (verbose)
		fclose(logfile);
}
/*---------------------------------------------------------------*/
void print_binary_position(struct sarleader_binary *sb, int nitems, FILE *ldrfile, FILE *logfile) {
	fprintf(logfile, SARLEADER_FDR_BINARY_WCS, SARLEADER_FDR_BINARY_RVL(sb));
	fprintf(logfile, " read %d items (%ld bytes) at position %ld\n", nitems, sizeof(struct sarleader_binary), ftell(ldrfile));
}
/*---------------------------------------------------------------*/
/* write a PRM file */
/* adapted for ALOS data */
/* needs SC_start_time and SC_end_time (from read_data) */
/* needs sample_rate (from read_sarleader) */
#define FACTOR 1000000
void ALOS_ldr_prm(struct SAR_info sar, struct PRM *prm) {
	double c_angle;

	/* nominal PRF and prf in PRM differ at 4 decimal places */
	prm->lambda = atof(sar.dss_ALOS->radar_wavelength);

	/* convert into seconds from MHz */
	prm->pulsedur = (atof(sar.dss_ALOS->range_pulse_length) / FACTOR);
	if (ALOS_format == 0)
		prm->fs = FACTOR * (atof(sar.dss_ALOS->sampling_rate));

	/* chirp linear term 	*/
	/* need -1 term		*/
	prm->chirp_slope = -1 * atof(sar.dss_ALOS->range_pulse_amplitude_lin);

	/* mean value of inphase and quadrature */
	prm->xmi = atof(sar.dss_ALOS->dc_bias_i);
	prm->xmq = atof(sar.dss_ALOS->dc_bias_q);

	/* need to define for ERSDAC format  prm->fs (rng_sample_rate differs by 1000
	 */
	/* xmi, xmq set to 15.5
	 */
	if (ALOS_format == 1) {
		prm->fs = atof(sar.dss_ALOS->sampling_rate);
		prm->xmi = 15.5;
		prm->xmq = 15.5;
	}

	/* ellipsoid info */
	prm->ra = 1000. * atof(sar.dss_ALOS->ellipsoid_semimajor_axis);
	prm->rc = 1000. * atof(sar.dss_ALOS->ellipsoid_semiminor_axis);

	/* orbit direction			*/
	/* A Ascend or D Descend */
	strncpy(prm->orbdir, sar.dss_ALOS->time_direction_along_line, 1);

	/* look direction R or L */
	c_angle = atof(sar.dss_ALOS->clock_angle);
	strcpy(prm->lookdir, "R");
	if (c_angle < 0.)
		strcpy(prm->lookdir, "L");

	/* date yymmdd */
	strncpy(prm->date, &sar.dss_ALOS->input_scene_center_time[2], 6);
	prm->date[7] = '\0';

	/* set doppler centroid for focussed L1.1 image unles it has already been set
	 */
	if (strncmp(sar.dss_ALOS->product_type_id, "BASIC", 5) == 0 && prm->fd1 == 0.0) {
		prm->fd1 = atof(sar.dss_ALOS->spare11);
		prm->fdd1 = 0.001 * atof(sar.dss_ALOS->spare12);
	}

	/* write it all out */
	if (verbose) {
		fprintf(stdout, "radar_wavelength	= %lg\n", prm->lambda);
		fprintf(stdout, "chirp_slope		= %lg\n", prm->chirp_slope);
		fprintf(stdout, "rng_samp_rate		= %lg\n", prm->fs);
		fprintf(stdout, "I_mean			= %lf\n", prm->xmi);
		fprintf(stdout, "Q_mean			= %lf\n", prm->xmq);
		fprintf(stdout, "orbdir			= %s\n", prm->orbdir);
		fprintf(stdout, "lookdir			= %s\n", prm->lookdir);
		fprintf(stdout, "date			= %s\n", prm->date);
		fprintf(stdout, "fd1			= %lf\n", prm->fd1);
		fprintf(stdout, "fdd1			= %lf\n", prm->fdd1);
	}
}
/*---------------------------------------------------------------*/
void get_attitude_info(struct ALOS_ATT *alos_attitude_info, int num_att_points, struct SAR_info sar) {
	int i;
	char tmp[256];

	/*
	        sprintf(tmp,"%.4s", sar.attitude_info_ALOS->num_att_data_points);
	        n = strtol(tmp, NULL, 10);
	*/

	if (verbose)
		fprintf(stderr, " number of attitude points %ld \n", strtol(sar.attitude_info_ALOS->num_att_data_points, NULL, 10));

	alos_attitude_info->na = num_att_points;

	for (i = 0; i < num_att_points; i++) {

		alos_attitude_info->id[i] = strtol(strncpy(tmp, sar.attitude_ALOS[i].day_of_year, 4), NULL, 10);
		alos_attitude_info->msec[i] = strtol(sar.attitude_ALOS[i].millisecond_day, NULL, 10);

		if (verbose)
			fprintf(stderr, " doy %d ms %d \n", alos_attitude_info->id[i], alos_attitude_info->msec[i]);

		alos_attitude_info->ap[i] = strtod(sar.attitude_ALOS[i].pitch, NULL);
		alos_attitude_info->ar[i] = strtod(sar.attitude_ALOS[i].roll, NULL);
		alos_attitude_info->ay[i] = strtod(sar.attitude_ALOS[i].yaw, NULL);
		if (verbose)
			fprintf(stderr, "pitch %12.6f roll %12.6f yaw %12.6f\n", alos_attitude_info->ap[i], alos_attitude_info->ar[i],
			        alos_attitude_info->ay[i]);

		alos_attitude_info->dp[i] = strtod(sar.attitude_ALOS[i].pitch_rate, NULL);
		alos_attitude_info->dr[i] = strtod(sar.attitude_ALOS[i].roll_rate, NULL);
		alos_attitude_info->dy[i] = strtod(sar.attitude_ALOS[i].yaw_rate, NULL);
		if (verbose)
			fprintf(stderr, "pitch %12.6f roll %12.6f yaw %12.6f\n", alos_attitude_info->dp[i], alos_attitude_info->dr[i],
			        alos_attitude_info->dy[i]);
	}
}
/*---------------------------------------------------------------*/
void get_orbit_info(struct ALOS_ORB *orb, struct SAR_info sar) {
	int i;
	char tmp[256];

	/* transfer to SIO orbit structure */
	/* use strncpy to make sure we only read the required number of characters */
	/* strncpy returns destination string as well as copies to tmp */
	/* 16 August 2007 RJM */
	/* this broke; make sure that tmp is null-terminated before handing off to
	 * atoi/atof */
	/* changed atol to atoi */
	/* probably there is a better way to do this ... */

	strncpy(tmp, sar.platform_ALOS->year_of_data_points, sizeof(sar.platform_ALOS->year_of_data_points));
	tmp[sizeof(sar.platform_ALOS->year_of_data_points)] = '\0';
	orb->iy = atoi(tmp);

	strncpy(tmp, sar.platform_ALOS->day_of_data_points_in_year, sizeof(sar.platform_ALOS->day_of_data_points_in_year));
	tmp[sizeof(sar.platform_ALOS->day_of_data_points_in_year)] = '\0';
	orb->id = atoi(tmp);

	strncpy(tmp, sar.platform_ALOS->sec_of_day_of_data, sizeof(sar.platform_ALOS->sec_of_day_of_data));
	tmp[sizeof(sar.platform_ALOS->sec_of_day_of_data)] = '\0';
	orb->sec = (double)atof(tmp);

	strncpy(tmp, sar.platform_ALOS->data_points_time_gap, sizeof(sar.platform_ALOS->data_points_time_gap));
	tmp[sizeof(sar.platform_ALOS->data_points_time_gap)] = '\0';
	orb->dsec = (double)atof(tmp);

	/* added 7/27/10 RJM */
	orb->pt0 = (24.0 * 60.0 * 60.0) * orb->id + orb->sec;

	if (verbose) {
		fprintf(stderr, " nd %d \n", orb->nd);
		fprintf(stderr, " iy %d \n", orb->iy);
		fprintf(stderr, " id %d \n", orb->id);
		fprintf(stderr, " sec %lf \n", orb->sec);
		fprintf(stderr, " dsec %lf \n", orb->dsec);
		fprintf(stderr, " pt0 %lf \n", orb->pt0);
	}

	orb->points = (struct ORB_XYZ *)malloc(orb->nd * sizeof(struct ORB_XYZ));

	/* orbit stuff */
	for (i = 0; i < orb->nd; i++) {

		if (verbose)
			fprintf(stderr, "orbit point:  %d\n", i);

		strncpy(tmp, sar.position_ALOS[i].pos_x, sizeof(sar.position_ALOS[i].pos_x));
		tmp[sizeof(sar.position_ALOS->pos_x)] = '\0';
		orb->points[i].px = atof(tmp);

		strncpy(tmp, sar.position_ALOS[i].pos_y, sizeof(sar.position_ALOS[i].pos_y));
		tmp[sizeof(sar.position_ALOS->pos_y)] = '\0';
		orb->points[i].py = atof(tmp);

		strncpy(tmp, sar.position_ALOS[i].pos_z, sizeof(sar.position_ALOS[i].pos_z));
		tmp[sizeof(sar.position_ALOS->pos_z)] = '\0';
		orb->points[i].pz = atof(tmp);

		if (verbose)
			fprintf(stderr, "%g %g %g\n", orb->points[i].px, orb->points[i].py, orb->points[i].pz);

		strncpy(tmp, sar.position_ALOS[i].vel_x, sizeof(sar.position_ALOS[i].vel_x));
		tmp[sizeof(sar.position_ALOS->vel_x)] = '\0';
		orb->points[i].vx = atof(tmp);

		strncpy(tmp, sar.position_ALOS[i].vel_y, sizeof(sar.position_ALOS[i].vel_y));
		tmp[sizeof(sar.position_ALOS->vel_y)] = '\0';
		orb->points[i].vy = atof(tmp);

		strncpy(tmp, sar.position_ALOS[i].vel_z, sizeof(sar.position_ALOS[i].vel_z));
		tmp[sizeof(sar.position_ALOS->vel_z)] = '\0';
		orb->points[i].vz = atof(tmp);

		if (verbose)
			fprintf(stderr, "%g %g %g\n", orb->points[i].vx, orb->points[i].vy, orb->points[i].vz);
	}
}
/*---------------------------------------------------------------*/
// convert from earth-centered rotating to earth-centered
// code by J B but moved by RJM
int transform_orbits_ecr2eci(struct ALOS_ORB *orb) {
	int j;
	int cal[3], mode;
	double ecr_pos[3];
	double ecr_vel[3];
	double eci_pos[3];
	double eci_vel[3];
	double ut1sec, daysec;

	for (j = 0; j < orb->nd; j++) {

		orb->points[j].px = orb->points[j].px;
		orb->points[j].py = orb->points[j].py;
		orb->points[j].pz = orb->points[j].pz;
		orb->points[j].vx = orb->points[j].vx / 1000.;
		orb->points[j].vy = orb->points[j].vy / 1000.;
		orb->points[j].vz = orb->points[j].vz / 1000.;

		eci_pos[0] = orb->points[j].px;
		eci_pos[1] = orb->points[j].py;
		eci_pos[2] = orb->points[j].pz;
		eci_vel[0] = orb->points[j].vx;
		eci_vel[1] = orb->points[j].vy;
		eci_vel[2] = orb->points[j].vz;

		mode = 2;
		cal[0] = orb->iy;
		cal[1] = orb->id;
		cal[2] = -99999;
		daysec = orb->sec + j * orb->dsec;

		ut1sec = cal2ut1(mode, cal, daysec);
		eci2ecr(eci_pos, eci_vel, ut1sec, ecr_pos, ecr_vel);

		orb->points[j].px = ecr_pos[0];
		orb->points[j].py = ecr_pos[1];
		orb->points[j].pz = ecr_pos[2];
		orb->points[j].vx = ecr_vel[0];
		orb->points[j].vy = ecr_vel[1];
		orb->points[j].vz = ecr_vel[2];
	}
	return (EXIT_SUCCESS);
}
/*---------------------------------------------------------------*/
