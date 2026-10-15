/*
 * sbas0_chunked.c
 *
 * A minimal SBAS inversion for GMTSAR, processed in row blocks.
 *
 * Memory: only -rows rows of phase and displacement are held at once.
 * GMT reads geographic row strips from each input, opening each file once
 * per block. One full output grid and full velocity/rms grids remain in RAM.
 * Completed displacement strips are spooled to an automatically removed
 * temporary file in the working directory (4 * rows * columns * scenes bytes).
 * Numerical inversion and output conventions match sbas0.c.
 *
 * Purpose:
 *   Convert a set of N unwrapped interferograms into a displacement
 *   time series for S SAR acquisitions, with N > S-1.
 *
 * Philosophy:
 *   Keep only the essential network inversion:
 *
 *       phase(ref,rep) = phase_state(rep) - phase_state(ref)
 *
 *   The first acquisition is fixed to zero, leaving S-1 unknown phase
 *   states.  At each pixel, all finite interferograms are inverted by
 *   unweighted least squares using LAPACK DGELSY.  The resulting phase
 *   states are converted to LOS displacement in mm using the GMTSAR
 *   convention
 *
 *       displacement_mm = -1000 * wavelength/(4*pi) * phase_radians
 *
 *   There is intentionally NO:
 *       coherence weighting
 *       temporal smoothing
 *       DEM-error estimation
 *       velocity estimation
 *       atmospheric phase-screen estimation
 *       robust fitting
 *
 * Input table formats:
 *
 *   intf.tab:
 *       unwrap.grd  ref_id  rep_id
 *
 *
 *   Scene IDs and relative acquisition times are derived from columns 2 and 3
 *   of intf.tab. IDs use YYYYDDD with zero-based day numbers (000-359).
 *
 * Usage:
 *   sbas0 intf.tab [-wavelength wl] [-rows nr] [-reference rng0 azi0] [-partial_coverage]
 *
 * Output:
 *   disp_XXXXXXX.grd
 *
 * Automatically retain only the network connected to the earliest scene.
 * Default: use a common finite-data mask and the fast single-factorization
 * Cholesky solver. Reject a pixel in every output if any interferogram is
 * nonfinite. With -partial_coverage, use available finite interferograms
 * at each pixel with the slower per-pixel DGELSY solver and require full rank.
 *
 * David T. Sandwell / GMTSAR
 * September 2026
 */

#include "gmtsar.h"
#define _FILE_OFFSET_BITS 64
#include <stdint.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

#define MAX_NAME 512

/*
 * GMTSAR currently links SBAS against an ILP64 LAPACK interface.
 * Keep the same DGELSY declaration used by the existing sbas code.
 */
void dgelsy_(const int64_t *m, const int64_t *n, const int64_t *nrhs,
             double *A, const int64_t *lda, double *b, const int64_t *ldb,
             int64_t *jpvt, const double *rcond, int64_t *rank,
             double *work, const int64_t *lwork, int64_t *info);
void dpotrf_(const char *uplo, const int64_t *n, double *A,
             const int64_t *lda, int64_t *info);
void dpotrs_(const char *uplo, const int64_t *n, const int64_t *nrhs,
             const double *A, const int64_t *lda, double *B,
             const int64_t *ldb, int64_t *info);

static char *USAGE =
"\n"
"USAGE: sbas0 intf.tab [-wavelength wl] [-rows nr] [-reference rng0 azi0] [-partial_coverage]\n"
"\n"
"  intf.tab   three-column format:\n"
"             unwrap.grd ref_id rep_id\n"
"\n"
"  Scene IDs are formed by sorting unique dates from columns 2 and 3.\n"
"  Dates use YYYYDDD (DDD = 000-365, January 1 = 000).\n"
"  Elapsed time uses actual Gregorian year lengths for velocity fitting.\n"
"\n"
"  Interferogram and scene counts are determined from intf.tab.\n"
"  Disconnected scenes and interferograms are automatically excluded.\n"
"  Blank lines and # comments are ignored.\n"
"  Grid dimensions are read from the first interferogram.\n"
"  All subsequent interferograms must have the same dimensions.\n"
"\n"
"  -wavelength wl   radar wavelength in meters; default = 0.0554658\n"
"  -rows nr         rows per processing block; default = 400\n"
"  -reference rng0 azi0  reference to nearest grid node/cell at grid x,y\n"
"                       (coordinates from grdinfo; not pixel indices)\n"
"                       subtract mean phase of centered 3x3 cells; all nine must be finite\n"
"  Default: common finite-data mask; batched DPOTRS (8192 pixels/batch)\n"
"  -partial_coverage   use available finite interferograms at each pixel\n"
"                      (slow per-pixel DGELSY; requires full rank)\n"
"\n"
"OUTPUT:\n"
"  disp_XXXXXXX.grd  cumulative LOS displacement in mm\n"
"  vel.grd           linear LOS velocity in mm/yr\n"
"  rms.grd           velocity uncertainty in mm/yr\n"
"\n";

/* Return scene index for scene ID, or -1 if not found. */
static int64_t scene_index(int64_t id, const int64_t *scene_id, int64_t S)
{
    int64_t i;
    for (i = 0; i < S; i++)
        if (scene_id[i] == id)
            return i;
    return -1;
}

/* Sort GMTSAR acquisition date IDs (YYYYDDD) numerically. */
static int compare_scene_ids(const void *aa, const void *bb)
{
    int64_t a = *(const int64_t *)aa, b = *(const int64_t *)bb;
    return (a > b) - (a < b);
}

/* Convert YYYYDDD (zero-based DDD, 000-365) to a Gregorian day count. */
static int64_t date_to_day(int64_t id)
{
    int64_t year = id / 1000, doy = id % 1000;
    int64_t y = year - 1;
    if (year < 1 || year > 9999 || doy < 0 || doy > 365) {
        fprintf(stderr, "invalid YYYYDDD scene ID: %lld\n", (long long)id);
        exit(EXIT_FAILURE);
    }
    return 365 * y + y / 4 - y / 100 + y / 400 + doy;
}

/* Keep only the connected component containing the chronologically first scene.
 * Compact scene/interferogram arrays in place before opening grid files.
 * The original input tables are never changed. */
static void retain_reference_network(int64_t *N, int64_t *S,
                                     int64_t *scene_id, double *scene_time,
                                     int64_t *ref_id, int64_t *rep_id,
                                     int64_t *iref, int64_t *irep, char **gfile)
{
    int64_t oldS = *S, oldN = *N, i, a, b, keepS = 0, keepN = 0;
    int64_t *parent = (int64_t *)malloc((size_t)oldS * sizeof(int64_t));
    int64_t *mapping = (int64_t *)malloc((size_t)oldS * sizeof(int64_t));
    int64_t *counts = (int64_t *)calloc((size_t)oldS, sizeof(int64_t));
    if (!parent || !mapping || !counts)
        die("memory allocation failed in network filtering", "");
    for (i = 0; i < oldS; i++) {
        int64_t j;
        parent[i] = i;
        mapping[i] = -1;
        for (j = 0; j < i; j++)
            if (scene_id[i] == scene_id[j])
                die("duplicate scene ID in generated scene list", "");
    }
    /* Union each interferogram's reference and repeat scenes. */
    for (i = 0; i < oldN; i++) {
        a = iref[i]; b = irep[i];
        while (parent[a] != a) { parent[a] = parent[parent[a]]; a = parent[a]; }
        while (parent[b] != b) { parent[b] = parent[parent[b]]; b = parent[b]; }
        if (a != b) parent[b] = a;
    }
    for (i = 0; i < oldS; i++) {
        a = i;
        while (parent[a] != a) { parent[a] = parent[parent[a]]; a = parent[a]; }
        parent[i] = a;
        counts[a]++;
    }
    a = parent[0];
    {
        int64_t components = 0;
        for (i = 0; i < oldS; i++)
            if (counts[i] != 0) components++;
        fprintf(stderr, "network components = %lld (reference component: %lld scenes)\n",
                (long long)components, (long long)counts[a]);
        if (components > 1) {
            fprintf(stderr, "excluding scenes disconnected from first scene %lld:\n",
                    (long long)scene_id[0]);
            for (i = 0; i < oldS; i++)
                if (parent[i] != a)
                    fprintf(stderr, "  scene %lld (component %lld, %lld scenes)\n",
                            (long long)scene_id[i], (long long)parent[i],
                            (long long)counts[parent[i]]);
        }
    }
    /* Build old-index -> new-index map; retain chronological table order. */
    for (i = 0; i < oldS; i++)
        if (parent[i] == parent[0]) {
            mapping[i] = keepS;
            scene_id[keepS] = scene_id[i];
            scene_time[keepS] = scene_time[i];
            keepS++;
        }
    if (keepS < 2)
        die("reference scene has no connected interferograms", "");
    for (i = 0; i < oldN; i++) {
        if (mapping[iref[i]] < 0 || mapping[irep[i]] < 0) {
            free(gfile[i]);
            continue;
        }
        gfile[keepN] = gfile[i];
        ref_id[keepN] = ref_id[i];
        rep_id[keepN] = rep_id[i];
        iref[keepN] = mapping[iref[i]];
        irep[keepN] = mapping[irep[i]];
        keepN++;
    }
    if (keepN < keepS - 1)
        die("internal network-filtering error", "");
    fprintf(stderr, "retained network: %lld scenes, %lld interferograms"
                    " (removed %lld scenes and %lld interferograms)\n",
            (long long)keepS, (long long)keepN,
            (long long)(oldS - keepS), (long long)(oldN - keepN));
    *S = keepS;
    *N = keepN;
    free(parent);
    free(mapping);
    free(counts);
}

/*
 * Build one direct-displacement design row.
 *
 * Unknown vector:
 *     x = [p1 p2 ... p(S-1)]
 *
 * with p0 fixed to zero.
 *
 * Interferogram equation:
 *     phi(ref,rep) = p(rep) - p(ref)
 */
static void build_design_matrix(double *G, int64_t N, int64_t S,
                                const int64_t *iref, const int64_t *irep)
{
    int64_t i, j;
    int64_t n = S - 1;

    for (j = 0; j < n; j++)
        for (i = 0; i < N; i++)
            G[i + N * j] = 0.0;

    for (i = 0; i < N; i++) {
        if (iref[i] != 0)
            G[i + N * (iref[i] - 1)] = -1.0;
        if (irep[i] != 0)
            G[i + N * (irep[i] - 1)] =  1.0;
    }
}

/* Compute the rank of the full interferogram network once. */
static int64_t network_rank(const double *G0, int64_t N, int64_t n)
{
    int64_t i, j;
    int64_t nrhs = 1;
    int64_t lda = MAX((int64_t)1, N);
    int64_t ldb = MAX((int64_t)1, MAX(N, n));
    int64_t lwork = MAX((int64_t)1, N * n + MAX(N * n, nrhs) * 16);
    int64_t rank = 0, info = 0;
    double rcond = 1.0e-10;

    double *A = (double *)malloc((size_t)N * (size_t)n * sizeof(double));
    double *b = (double *)calloc((size_t)ldb, sizeof(double));
    double *work = (double *)malloc((size_t)lwork * sizeof(double));
    int64_t *jpvt = (int64_t *)calloc((size_t)n, sizeof(int64_t));

    if (!A || !b || !work || !jpvt)
        die("memory allocation failed", "");

    for (j = 0; j < n; j++)
        for (i = 0; i < N; i++)
            A[i + N * j] = G0[i + N * j];

    dgelsy_(&N, &n, &nrhs, A, &lda, b, &ldb, jpvt,
            &rcond, &rank, work, &lwork, &info);

    free(A);
    free(b);
    free(work);
    free(jpvt);

    if (info != 0)
        die("DGELSY failed while checking network rank", "");

    return rank;
}

/* Build the common-mask normal matrix G^T G once. */
static void build_normal_matrix(double *C, int64_t S, const int64_t *iref,
                                const int64_t *irep, int64_t N)
{
    int64_t i, j;
    int64_t n = S - 1;

    for (j = 0; j < n * n; j++)
        C[j] = 0.0;

    for (i = 0; i < N; i++) {
        int64_t a = iref[i];
        int64_t b = irep[i];

        if (a != 0)
            C[(a - 1) + n * (a - 1)] += 1.0;
        if (b != 0)
            C[(b - 1) + n * (b - 1)] += 1.0;
        if (a != 0 && b != 0) {
            C[(a - 1) + n * (b - 1)] -= 1.0;
            C[(b - 1) + n * (a - 1)] -= 1.0;
        }
    }
}

/* Read one table record, ignoring blank lines and # comments. */
static int next_table_row(FILE *fp, char *path, int columns,
                          char fields[3][MAX_NAME])
{
    char line[3 * MAX_NAME + 128];
    char *token, *comment;
    int count;

    while (fgets(line, sizeof(line), fp)) {
        if (!strchr(line, '\n') && !feof(fp))
            die("table line is too long: ", path);
        if ((comment = strchr(line, '#')) != NULL)
            *comment = '\0';
        count = 0;
        for (token = strtok(line, " \t\r\n"); token != NULL;
             token = strtok(NULL, " \t\r\n")) {
            if (count >= columns || strlen(token) >= MAX_NAME)
                die("invalid table row: ", path);
            strcpy(fields[count++], token);
        }
        if (count == 0)
            continue;
        if (count != columns)
            die("wrong number of columns in table: ", path);
        return 1;
    }
    if (ferror(fp))
        die("error reading table: ", path);
    return 0;
}

static int64_t count_table_rows(char *path, int columns)
{
    FILE *fp;
    char fields[3][MAX_NAME];
    int64_t count = 0;

    if ((fp = fopen(path, "r")) == NULL)
        die("can't open ", path);
    while (next_table_row(fp, path, columns, fields)) {
        if (count == INT64_MAX)
            die("too many rows in table: ", path);
        count++;
    }
    fclose(fp);
    return count;
}

int main(int argc, char **argv)
{
    int64_t N, S, xdim, ydim, n;
    int64_t i, j, p, npix, total_pixels, first_row, rows, block_pixels;
    int64_t block_rows = 400;
    int use_reference = 0;
    double rng0 = 0.0, azi0 = 0.0;
    int64_t ref_col = -1, ref_row = -1;
    float *reference_phase = NULL;
    int common_mask = 1;  /* default: fast solver with common finite-data mask */
    double grid_wesn[4], grid_inc[2];
    unsigned int grid_registration;
    FILE *disp_store = NULL;
    char store_name[] = "sbas0_displacements_XXXXXX";
    int store_fd;
    int64_t *scene_id = NULL, *ref_id = NULL, *rep_id = NULL;
    int64_t *iref = NULL, *irep = NULL;
    double *scene_time = NULL;
    char **gfile = NULL;
    double *G0 = NULL;

    float *phi = NULL;
    float *disp = NULL;
    float *vel = NULL;
    float *rms = NULL;

    FILE *fp = NULL;
    void *API = NULL;
    struct GMT_GRID *GG = NULL, *Out = NULL;

    double wl = 0.0554658;
    double phase_to_mm;

    char fields[3][MAX_NAME];
    char outfile[MAX_NAME], title[MAX_NAME], command[2048];

    int64_t full_rank;
    double *chol = NULL;
    int64_t chol_lda = 0;

    if (argc < 2)
        die("\n", USAGE);

    N = count_table_rows(argv[1], 3);
    if (N < 1 || N > INT64_MAX / 2)
        die("intf.tab requires at least one interferogram", "");
    S = 2 * N;  /* upper bound before sorting and uniquing scene IDs */

    for (i = 2; i < argc; i++) {
        if (!strcmp(argv[i], "-wavelength")) {
            if (++i >= argc)
                die("no value after -wavelength", "");
            wl = atof(argv[i]);
        }
        else if (!strcmp(argv[i], "-partial_coverage")) {
            common_mask = 0;
        }
        else if (!strcmp(argv[i], "-reference")) {
            char *end;
            if (i + 2 >= argc)
                die("-reference requires grid coordinates rng0 azi0", "");
            rng0 = strtod(argv[++i], &end);
            if (end == argv[i] || *end || !isfinite(rng0))
                die("invalid range grid coordinate: ", argv[i]);
            azi0 = strtod(argv[++i], &end);
            if (end == argv[i] || *end || !isfinite(azi0))
                die("invalid azimuth grid coordinate: ", argv[i]);
            use_reference = 1;
        }
        else if (!strcmp(argv[i], "-rows")) {
            char *end;
            long long value;
            if (++i >= argc)
                die("no value after -rows", "");
            value = strtoll(argv[i], &end, 10);
            if (*end || value < 1 || value > INT32_MAX)
                die("invalid row block size: ", argv[i]);
            block_rows = (int64_t)value;
        }
        else {
            fprintf(stderr, "%s\n", USAGE);
            die("option not recognized: ", argv[i]);
        }
    }

    phase_to_mm = -1000.0 * wl / (4.0 * M_PI);

    if ((API = GMT_Create_Session(argv[0], 0U, 0U, NULL)) == NULL)
        return EXIT_FAILURE;

    /* Hide GMT informational chatter while retaining warnings and errors. */
    if (GMT_Set_Default(API, "GMT_VERBOSE", "warning"))
        die("could not set GMT verbosity", "");

    scene_id   = (int64_t *)malloc((size_t)S * sizeof(int64_t));
    scene_time = (double  *)malloc((size_t)S * sizeof(double));
    ref_id     = (int64_t *)malloc((size_t)N * sizeof(int64_t));
    rep_id     = (int64_t *)malloc((size_t)N * sizeof(int64_t));
    iref       = (int64_t *)malloc((size_t)N * sizeof(int64_t));
    irep       = (int64_t *)malloc((size_t)N * sizeof(int64_t));
    gfile      = (char **)malloc((size_t)N * sizeof(char *));
    if (!scene_id || !scene_time || !ref_id || !rep_id || !iref || !irep ||
        !gfile)
        die("memory allocation failed", "");

    for (i = 0; i < N; i++) {
        gfile[i] = (char *)malloc(MAX_NAME);
        if (!gfile[i])
            die("memory allocation failed", "");
    }

    /* Read intf.tab: unwrap.grd ref_id rep_id. */
    if ((fp = fopen(argv[1], "r")) == NULL)
        die("can't open ", argv[1]);

    i = 0;
    while (next_table_row(fp, argv[1], 3, fields)) {
        if (i >= N)
            die("intf.tab changed while being read", "");
        strcpy(gfile[i], fields[0]);
        ref_id[i] = (int64_t)atoll(fields[1]);
        rep_id[i] = (int64_t)atoll(fields[2]);

        if (ref_id[i] == rep_id[i])
            die("interferogram has identical reference and repeat scenes", "");

        /* Keep both dates; sort and unique after reading the table. */
        scene_id[2 * i] = ref_id[i];
        scene_id[2 * i + 1] = rep_id[i];

        i++;
    }
    fclose(fp);

    if (i != N)
        die("intf.tab changed while being read", "");

    /* Generate scene list = sort -u of both date columns. */
    qsort(scene_id, (size_t)S, sizeof(int64_t), compare_scene_ids);
    {
        int64_t unique_count = 0;
        for (i = 0; i < S; i++) {
            if (unique_count == 0 || scene_id[i] != scene_id[unique_count - 1])
                scene_id[unique_count++] = scene_id[i];
        }
        S = unique_count;
    }
    if (S < 2)
        die("fewer than two unique acquisition dates", "");

    /* Gregorian elapsed days relative to earliest acquisition; DDD starts at 000. */
    {
        int64_t origin = date_to_day(scene_id[0]);
        for (i = 0; i < S; i++)
            scene_time[i] = (double)(date_to_day(scene_id[i]) - origin);
    }
    for (i = 0; i < N; i++) {
        iref[i] = scene_index(ref_id[i], scene_id, S);
        irep[i] = scene_index(rep_id[i], scene_id, S);
        if (iref[i] < 0 || irep[i] < 0)
            die("internal error matching generated acquisition dates", "");
    }
    fprintf(stderr, "generated %lld unique chronological scenes from intf.tab\n",
            (long long)S);

    /* Remove disconnected scenes and their interferograms automatically.
     * This must precede reference-grid sampling and all pixel allocations. */
    retain_reference_network(&N, &S, scene_id, scene_time,
                             ref_id, rep_id, iref, irep, gfile);
    n = S - 1;
    G0 = (double *)malloc((size_t)N * (size_t)n * sizeof(double));
    if (!G0)
        die("memory allocation failed", "");

    fprintf(stderr, "\nsbas0: simple unweighted SBAS inversion\n");
    fprintf(stderr, "N interferograms = %lld\n", (long long)N);
    fprintf(stderr, "S scenes         = %lld\n", (long long)S);
    fprintf(stderr, "unknowns         = %lld (first scene fixed to zero)\n",
            (long long)n);
    fprintf(stderr, "wavelength       = %.6f m\n", wl);
    fprintf(stderr, "phase -> disp    = %.9f mm/radian\n", phase_to_mm);
    fprintf(stderr, "solver mode = %s\n\n",
            common_mask ? "common mask (fast Cholesky)" : "partial coverage (DGELSY)");

    /* Infer grid dimensions before allocating any pixel arrays. */
    if ((GG = GMT_Read_Data(API, GMT_IS_GRID, GMT_IS_FILE, GMT_IS_SURFACE,
                            GMT_GRID_HEADER_ONLY, NULL, gfile[0], NULL)) == NULL)
        die("can't open ", gfile[0]);

    xdim = (int64_t)GG->header->n_columns;
    ydim = (int64_t)GG->header->n_rows;
    if (xdim < 1 || ydim < 1 || xdim > INT64_MAX / ydim)
        die("invalid grid dimensions in ", gfile[0]);
    total_pixels = xdim * ydim;
    block_rows = (block_rows < ydim ? block_rows : ydim);
    block_pixels = xdim * block_rows;
    npix = block_pixels;
    memcpy(grid_wesn, GG->header->wesn, sizeof(grid_wesn));
    memcpy(grid_inc, GG->header->inc, sizeof(grid_inc));
    grid_registration = GG->header->registration;

    /* Convert GMT grid x/y coordinates to nearest column and row.
     * GMT stores grid rows north-to-south.  Pixel-registered coordinates
     * refer to cell centers, half a grid interval in from the bounds. */
    if (use_reference) {
        double col_fraction, row_fraction;
        double registration_offset = grid_registration ? 0.5 : 0.0;
        if (grid_inc[0] <= 0.0 || grid_inc[1] <= 0.0)
            die("invalid grid spacing for -reference", "");
        if (rng0 < grid_wesn[0] || rng0 > grid_wesn[1] ||
            azi0 < grid_wesn[2] || azi0 > grid_wesn[3])
            die("-reference coordinate outside grid bounds", "");
        col_fraction = (rng0 - grid_wesn[0]) / grid_inc[0] - registration_offset;
        row_fraction = (grid_wesn[3] - azi0) / grid_inc[1] - registration_offset;
        ref_col = (int64_t)floor(col_fraction + 0.5);
        ref_row = (int64_t)floor(row_fraction + 0.5);
        /* Allow points on pixel-registered grid boundaries to select
         * the nearest outermost cell. */
        if (ref_col < 0) ref_col = 0;
        if (ref_col >= xdim) ref_col = xdim - 1;
        if (ref_row < 0) ref_row = 0;
        if (ref_row >= ydim) ref_row = ydim - 1;
        fprintf(stderr,
                "reference grid x=%.9g y=%.9g -> column=%lld row=%lld "
                "(grid cell center x=%.9g y=%.9g)\n",
                rng0, azi0, (long long)ref_col, (long long)ref_row,
                grid_wesn[0] + (ref_col + registration_offset) * grid_inc[0],
                grid_wesn[3] - (ref_row + registration_offset) * grid_inc[1]);
    }

    if ((uint64_t)total_pixels > SIZE_MAX / sizeof(float))
        die("output grid exceeds supported array size", "");

    /* Prevent overflow of pixel-array sizes and signed indexing. */
    if (npix > INT64_MAX / N || npix > INT64_MAX / S ||
        (uint64_t)npix > SIZE_MAX / sizeof(float) / (uint64_t)N ||
        (uint64_t)npix > SIZE_MAX / sizeof(float) / (uint64_t)S)
        die("grid dimensions exceed supported array size: ", gfile[0]);

    fprintf(stderr, "grid dimensions  = %lld columns x %lld rows (from %s)\n",
            (long long)xdim, (long long)ydim, gfile[0]);

    if (GMT_Destroy_Data(API, &GG))
        die("error freeing grid ", gfile[0]);

    /* Read a three-row strip from every input once to get its 3x3 reference mean.
     * This is independent of -rows, including when the reference is in a
     * later processing block. Grid rows are indexed north to south. */
    if (use_reference) {
        double region[4];
        int64_t start_row = ref_row - 1;
        int64_t strip_rows = 3;
        if (xdim < 3 || ydim < 3 || ref_col < 1 || ref_col >= xdim - 1 ||
            ref_row < 1 || ref_row >= ydim - 1)
            die("-reference needs a complete 3x3 neighborhood within the grid", "");
        reference_phase = (float *)malloc((size_t)N * sizeof(float));
        if (!reference_phase)
            die("memory allocation failed", "");
        memcpy(region, grid_wesn, sizeof(region));
        region[3] = grid_wesn[3] - start_row * grid_inc[1];
        region[2] = region[3] - (strip_rows - (grid_registration ? 0 : 1)) * grid_inc[1];
        fprintf(stderr, "referencing interferograms to 3x3 mean centered on grid coordinates range=%.9g azimuth=%.9g\n",
                rng0, azi0);
        for (i = 0; i < N; i++) {
            if ((GG = GMT_Read_Data(API, GMT_IS_GRID, GMT_IS_FILE, GMT_IS_SURFACE,
                                    GMT_GRID_HEADER_ONLY, NULL, gfile[i], NULL)) == NULL)
                die("can't open reference grid: ", gfile[i]);
            if ((int64_t)GG->header->n_columns != xdim ||
                (int64_t)GG->header->n_rows != ydim ||
                GG->header->registration != grid_registration)
                die("grid geometry does not match first interferogram: ", gfile[i]);
            for (j = 0; j < 4; j++)
                if (fabs(GG->header->wesn[j] - grid_wesn[j]) >
                    1.0e-6 * grid_inc[j < 2 ? 0 : 1])
                    die("grid bounds do not match first interferogram: ", gfile[i]);
            for (j = 0; j < 2; j++)
                if (fabs(GG->header->inc[j] - grid_inc[j]) > 1.0e-6 * grid_inc[j])
                    die("grid spacing does not match first interferogram: ", gfile[i]);
            if ((GG = GMT_Read_Data(API, GMT_IS_GRID, GMT_IS_FILE, GMT_IS_SURFACE,
                                    GMT_GRID_DATA_ONLY, region, gfile[i], GG)) == NULL)
                die("can't read reference strip: ", gfile[i]);
            if ((int64_t)GG->header->n_columns != xdim ||
                (int64_t)GG->header->n_rows != strip_rows)
                die("unexpected reference strip dimensions: ", gfile[i]);
            {
                int64_t dr, dc;
                double sum = 0.0;
                for (dr = 0; dr < 3; dr++) {
                    for (dc = -1; dc <= 1; dc++) {
                        float value = GG->data[dr * xdim + ref_col + dc];
                        if (!isfinite(value)) {
                            fprintf(stderr,
                                    "nonfinite value in 3x3 reference neighborhood of interferogram %lld: %s\n",
                                    (long long)(i + 1), gfile[i]);
                            exit(EXIT_FAILURE);
                        }
                        sum += (double)value;
                    }
                }
                reference_phase[i] = (float)(sum / 9.0);
            }
            if (GMT_Destroy_Data(API, &GG))
                die("error freeing reference strip: ", gfile[i]);
        }
    }

    phi  = (float *)malloc((size_t)N * (size_t)npix * sizeof(float));
    disp = (float *)malloc((size_t)S * (size_t)npix * sizeof(float));
    vel  = (float *)malloc((size_t)total_pixels * sizeof(float));
    rms  = (float *)malloc((size_t)total_pixels * sizeof(float));
    if (!phi || !disp || !vel || !rms)
        die("memory allocation failed", "");

    build_design_matrix(G0, N, S, iref, irep);

    full_rank = network_rank(G0, N, n);
    fprintf(stderr, "network rank = %lld of %lld\n",
            (long long)full_rank, (long long)n);

    if (full_rank != n)
        die("interferogram network is rank deficient; cannot solve all scene displacements", "");

    if (common_mask) {
        int64_t info = 0;
        char uplo = 'U';
        chol_lda = MAX((int64_t)1, n);
        chol = (double *)malloc((size_t)n * (size_t)n * sizeof(double));
        if (!chol)
            die("memory allocation failed", "");
        build_normal_matrix(chol, S, iref, irep, N);
        dpotrf_(&uplo, &n, chol, &chol_lda, &info);
        if (info != 0)
            die("DPOTRF failed while factoring G^T G for common-mask solver", "");
        fprintf(stderr, "common-mask solver = single Cholesky factorization of G^T G\n");
    }

    /* One complete output grid, reused for every scene. */
    if ((Out = GMT_Read_Data(API, GMT_IS_GRID, GMT_IS_FILE, GMT_IS_SURFACE,
                             GMT_GRID_ALL, NULL, gfile[0], NULL)) == NULL)
        die("can't read output template: ", gfile[0]);

    /* An unlinked temporary file is removed automatically on exit.
     * Keep it in the working directory so large runs use local disk. */
    if (total_pixels > INT64_MAX / S / (int64_t)sizeof(float))
        die("temporary displacement file is too large", "");
    if ((store_fd = mkstemp(store_name)) < 0)
        die("can't create temporary displacement file", "");
    if ((disp_store = fdopen(store_fd, "w+b")) == NULL) {
        close(store_fd);
        unlink(store_name);
        die("can't open temporary displacement stream", "");
    }
    if (unlink(store_name))
        die("can't unlink temporary displacement file: ", store_name);

    fprintf(stderr, "processing blocks of %lld rows; temporary disk = %.3f GB\n",
            (long long)block_rows, 4.0 * total_pixels * S / 1.0e9);

    for (first_row = 0; first_row < ydim; first_row += block_rows) {
        double region[4];
        int64_t read_first_row, read_rows, skip_rows;
        rows = (ydim - first_row < block_rows ? ydim - first_row : block_rows);
        npix = rows * xdim;
        read_first_row = first_row;
        read_rows = rows;
        skip_rows = 0;
        /* A gridline subset needs distinct north and south bounds. */
        if (!grid_registration && rows == 1 && ydim > 1) {
            read_rows = 2;
            if (first_row > 0) {
                read_first_row--;
                skip_rows = 1;
            }
        }
        memcpy(region, grid_wesn, sizeof(region));
        region[3] = grid_wesn[3] - read_first_row * grid_inc[1];
        region[2] = region[3] - (read_rows - (grid_registration ? 0 : 1)) * grid_inc[1];
        fprintf(stderr, "rows %lld-%lld of %lld: reading and solving ...\n",
                (long long)(first_row + 1), (long long)(first_row + rows),
                (long long)ydim);

        for (i = 0; i < N; i++) {
            if ((GG = GMT_Read_Data(API, GMT_IS_GRID, GMT_IS_FILE, GMT_IS_SURFACE,
                                    GMT_GRID_HEADER_ONLY, NULL, gfile[i], NULL)) == NULL)
                die("can't open ", gfile[i]);
            if ((int64_t)GG->header->n_columns != xdim ||
                (int64_t)GG->header->n_rows != ydim ||
                GG->header->registration != grid_registration)
                die("grid geometry does not match the first interferogram: ", gfile[i]);
            for (j = 0; j < 4; j++)
                if (fabs(GG->header->wesn[j] - grid_wesn[j]) >
                    1.0e-6 * grid_inc[j < 2 ? 0 : 1])
                    die("grid bounds do not match the first interferogram: ", gfile[i]);
            for (j = 0; j < 2; j++)
                if (fabs(GG->header->inc[j] - grid_inc[j]) > 1.0e-6 * grid_inc[j])
                    die("grid spacing does not match the first interferogram: ", gfile[i]);
            /* GMT reads only this geographic row strip; session padding is zero. */
            if ((GG = GMT_Read_Data(API, GMT_IS_GRID, GMT_IS_FILE, GMT_IS_SURFACE,
                                    GMT_GRID_DATA_ONLY, region, gfile[i], GG)) == NULL)
                die("can't read row block: ", gfile[i]);
            if ((int64_t)GG->header->n_columns != xdim ||
                (int64_t)GG->header->n_rows != read_rows)
                die("unexpected row block dimensions: ", gfile[i]);
            for (p = 0; p < npix; p++) {
                float value = GG->data[skip_rows * xdim + p];
                phi[p * N + i] = (use_reference && isfinite(value))
                                  ? value - reference_phase[i] : value;
            }
            if (GMT_Destroy_Data(API, &GG))
                die("error freeing grid ", gfile[i]);
        }

    if (common_mask) {
    /*
     * Common finite-data mask: every interferogram must be finite.
     * Accumulate up to 8192 valid right-hand sides and solve them together
     * with one LAPACK DPOTRS call (NRHS = number of valid pixels in batch).
     * The Cholesky factorization of G^T G is still computed only once.
     */
    {
        const int64_t batch_capacity = 8192;
        int64_t ldb = MAX((int64_t)1, n);
        int64_t batch_count = 0;
        int64_t good_pixels = 0;
        int64_t masked_pixels = 0;
        int64_t failed_pixels = 0;
        int64_t *batch_pixels;
        double *rhs;
        char uplo = 'U';

        if ((uint64_t)ldb > SIZE_MAX / sizeof(double) / (uint64_t)batch_capacity)
            die("batch RHS allocation size overflow", "");
        rhs = (double *)malloc((size_t)ldb * (size_t)batch_capacity * sizeof(double));
        batch_pixels = (int64_t *)malloc((size_t)batch_capacity * sizeof(int64_t));
        if (!rhs || !batch_pixels)
            die("memory allocation failed for batched Cholesky solver", "");

        fprintf(stderr, "solving displacement time series with common finite-data mask "
                        "(DPOTRS batches of up to %lld pixels) ...\n",
                (long long)batch_capacity);

        for (p = 0; p < npix; p++) {
            int valid = 1;
            double *column = rhs + batch_count * ldb;

            /* Initialize all scenes to NaN until this pixel is solved. */
            for (i = 0; i < S; i++)
                disp[i * npix + p] = NAN;

            for (j = 0; j < n; j++)
                column[j] = 0.0;

            /* Require finite phase in EVERY interferogram at this pixel. */
            for (i = 0; i < N; i++) {
                float v = phi[p * N + i];
                if (!isfinite(v)) {
                    valid = 0;
                    break;
                }
                if (iref[i] != 0)
                    column[iref[i] - 1] -= (double)v;
                if (irep[i] != 0)
                    column[irep[i] - 1] += (double)v;
            }
            if (!valid) {
                masked_pixels++;
                continue;
            }

            batch_pixels[batch_count++] = p;
            if (batch_count == batch_capacity || p == npix - 1) {
                int64_t info = 0;
                int64_t nrhs = batch_count;
                int64_t k;
                dpotrs_(&uplo, &n, &nrhs, chol, &chol_lda, rhs, &ldb, &info);
                if (info != 0) {
                    failed_pixels += batch_count;
                } else {
                    for (k = 0; k < batch_count; k++) {
                        int64_t pixel = batch_pixels[k];
                        const double *solution = rhs + k * ldb;
                        disp[pixel] = 0.0f;
                        for (i = 1; i < S; i++)
                            disp[i * npix + pixel] =
                                (float)(phase_to_mm * solution[i - 1]);
                    }
                    good_pixels += batch_count;
                }
                batch_count = 0;
            }
        }

        /* Flush a final partial batch when the last pixel was masked. */
        if (batch_count > 0) {
            int64_t info = 0;
            int64_t nrhs = batch_count;
            int64_t k;
            dpotrs_(&uplo, &n, &nrhs, chol, &chol_lda, rhs, &ldb, &info);
            if (info != 0) {
                failed_pixels += batch_count;
            } else {
                for (k = 0; k < batch_count; k++) {
                    int64_t pixel = batch_pixels[k];
                    const double *solution = rhs + k * ldb;
                    disp[pixel] = 0.0f;
                    for (i = 1; i < S; i++)
                        disp[i * npix + pixel] =
                            (float)(phase_to_mm * solution[i - 1]);
                }
                good_pixels += batch_count;
            }
        }

        fprintf(stderr,
                "solved pixels = %lld, common-masked pixels = %lld, solve-failed pixels = %lld\n",
                (long long)good_pixels, (long long)masked_pixels,
                (long long)failed_pixels);

        free(batch_pixels);
        free(rhs);
    }

    } else {
    /*
     * Solve independently at every pixel.
     *
     * Only finite interferograms are included.  A pixel is accepted only
     * if its available interferograms have full rank S-1.
     */
    {
        int64_t nrhs = 1;
        int64_t ldb = MAX((int64_t)1, MAX(N, n));
        int64_t lwork = MAX((int64_t)1,
                            N * n + MAX(N * n, nrhs) * 16);
        double rcond = 1.0e-10;

        double *A = (double *)malloc((size_t)N * (size_t)n * sizeof(double));
        double *Ac = (double *)malloc((size_t)N * (size_t)n * sizeof(double));
        double *b = (double *)malloc((size_t)ldb * sizeof(double));
        double *work = (double *)malloc((size_t)lwork * sizeof(double));
        int64_t *jpvt = (int64_t *)malloc((size_t)n * sizeof(int64_t));

        int64_t good_pixels = 0;
        int64_t bad_pixels = 0;

        if (!A || !Ac || !b || !work || !jpvt)
            die("memory allocation failed", "");

        fprintf(stderr, "solving displacement time series ...\n");

        for (p = 0; p < npix; p++) {
            int64_t mv = 0;
            int64_t rank = 0, info = 0;

            /*
             * Compress the valid interferograms into the first mv rows
             * of A and b.
             */
            for (i = 0; i < N; i++) {
                float v = phi[p * N + i];

                if (isfinite(v)) {
                    b[mv] = (double)v;

                    for (j = 0; j < n; j++)
                        A[mv + N * j] = G0[i + N * j];

                    mv++;
                }
            }

            /*
             * First scene defines the phase origin.
             * Set all output scenes to NaN until a valid solution exists.
             */
            for (i = 0; i < S; i++)
                disp[i * npix + p] = NAN;

            if (mv < n) {
                bad_pixels++;
                continue;
            }

            /*
             * DGELSY requires a column-major matrix with leading dimension
             * lda.  The compressed matrix above currently has stride N.
             * Repack in place into a temporary contiguous mv-by-n matrix.
             */
            {
                int64_t ldac = MAX((int64_t)1, mv);
                int64_t ldbc = MAX((int64_t)1, MAX(mv, n));

                for (j = 0; j < n; j++)
                    for (i = 0; i < mv; i++)
                        Ac[i + mv * j] = A[i + N * j];

                for (i = mv; i < ldbc; i++)
                    b[i] = 0.0;

                for (j = 0; j < n; j++)
                    jpvt[j] = 0;

                dgelsy_(&mv, &n, &nrhs, Ac, &ldac, b, &ldbc, jpvt,
                        &rcond, &rank, work, &lwork, &info);
            }

            if (info != 0 || rank != n) {
                bad_pixels++;
                continue;
            }

            disp[p] = 0.0f;
            for (i = 1; i < S; i++)
                disp[i * npix + p] =
                    (float)(phase_to_mm * b[i - 1]);

            good_pixels++;
        }

        fprintf(stderr,
                "solved pixels = %lld, rank-deficient/insufficient pixels = %lld\n",
                (long long)good_pixels, (long long)bad_pixels);

        free(A);
        free(Ac);
        free(b);
        free(work);
        free(jpvt);
    }

    }

    /*
     * Compute linear velocity and rms.grd from the displacement time series.
     * This follows the regression used by the original GMTSAR sbas code.
     * scene_time is in days, disp is already in mm, so the fitted slope is
     * multiplied by 365 to obtain mm/yr.  rms.grd is the uncertainty of the
     * fitted velocity, also in mm/yr.
     */
    fprintf(stderr, "computing velocity.grd and rms.grd ...\n");

    for (p = 0; p < npix; p++) {
        double sumxx = 0.0, sumxy = 0.0, sumx = 0.0, sumy = 0.0;
        double sumyy = 0.0, aa, slope, denom;
        int valid = 1;

        for (i = 0; i < S; i++) {
            double y = disp[i * npix + p];
            if (!isfinite(y)) {
                valid = 0;
                break;
            }
            sumxy += scene_time[i] * y;
            sumxx += scene_time[i] * scene_time[i];
            sumy  += y;
            sumx  += scene_time[i];
        }

        denom = S * sumxx - sumx * sumx;
        if (!valid || denom <= 0.0) {
            vel[first_row * xdim + p] = NAN;
            rms[first_row * xdim + p] = NAN;
            continue;
        }

        slope = (S * sumxy - sumx * sumy) / denom;  /* mm/day */
        vel[first_row * xdim + p] = (float)(slope * 365.0);             /* mm/yr  */

        aa = sumy / S - slope * sumx / S;

        /* Preserve the original sbas rms calculation: residuals from
         * scenes 2 through S-3, with the original normalization. */
        for (i = 2; i < S - 2; i++) {
            double r = disp[i * npix + p] - scene_time[i] * slope - aa;
            sumyy += r * r;
        }

        if (S > 2)
            rms[first_row * xdim + p] = (float)(sqrt(S * sumyy / ((S - 2) * denom)) * 365.0);
        else
            rms[first_row * xdim + p] = NAN;
    }

        /* Store contiguous row blocks at their scene-major disk offsets. */
        for (i = 0; i < S; i++) {
            off_t offset = (off_t)((i * total_pixels + first_row * xdim) * sizeof(float));
            if (fseeko(disp_store, offset, SEEK_SET) ||
                fwrite(disp + i * npix, sizeof(float), (size_t)npix, disp_store) != (size_t)npix)
                die("error writing temporary displacement file (check disk space)", "");
        }
    } /* row-block loop */
    free(phi);
    phi = NULL;
    free(disp);
    disp = NULL;
    if (fflush(disp_store))
        die("error flushing temporary displacement file", "");
    npix = total_pixels;

    /* Build command string for the GMT grid history. */
    command[0] = '\0';
    for (i = 0; i < argc; i++) {
        size_t left = sizeof(command) - strlen(command) - 1;
        if (left > 1) {
            strncat(command, argv[i], left);
            left = sizeof(command) - strlen(command) - 1;
            if (left > 1)
                strncat(command, " ", left);
        }
    }

    strcpy(Out->header->title, "");
    strcpy(Out->header->remark, "");

    if (GMT_Set_Comment(API, GMT_IS_GRID, GMT_COMMENT_IS_COMMAND,
                        command, Out))
        die("could not set grid command", "");

    /* Write one displacement grid per acquisition. */
    fprintf(stderr, "writing displacement grids ...\n");

    for (i = 0; i < S; i++) {

        if (fseeko(disp_store, (off_t)(i * total_pixels * sizeof(float)), SEEK_SET) ||
            fread(Out->data, sizeof(float), (size_t)total_pixels, disp_store) != (size_t)total_pixels)
            die("error reading temporary displacement file", "");

        snprintf(outfile, sizeof(outfile), "disp_%07lld.grd",
                 (long long)scene_id[i]);
        snprintf(title, sizeof(title),
                 "LOS displacement for scene %07lld",
                 (long long)scene_id[i]);

        strcpy(Out->header->title, "");
        strcpy(Out->header->remark, "");

        if (GMT_Set_Comment(API, GMT_IS_GRID, GMT_COMMENT_IS_REMARK,
                            "Simple SBAS LOS displacement (mm)", Out))
            die("could not set grid remark", "");

        if (GMT_Set_Comment(API, GMT_IS_GRID, GMT_COMMENT_IS_TITLE,
                            title, Out))
            die("could not set grid title", "");

        if (GMT_Write_Data(API, GMT_IS_GRID, GMT_IS_FILE, GMT_IS_SURFACE,
                           GMT_GRID_ALL, NULL, outfile, Out))
            die("failed to write output grid ", outfile);
    }

    /* Write linear LOS velocity. */
    for (p = 0; p < npix; p++)
        Out->data[p] = vel[p];

    strcpy(Out->header->title, "");
    strcpy(Out->header->remark, "");
    if (GMT_Set_Comment(API, GMT_IS_GRID, GMT_COMMENT_IS_REMARK,
                        "Mean LOS velocity from SBAS (mm/yr)", Out))
        die("could not set grid remark", "");
    if (GMT_Set_Comment(API, GMT_IS_GRID, GMT_COMMENT_IS_TITLE,
                        "Mean Line-Of-Sight velocity from SBAS", Out))
        die("could not set grid title", "");
    if (GMT_Write_Data(API, GMT_IS_GRID, GMT_IS_FILE, GMT_IS_SURFACE,
                       GMT_GRID_ALL, NULL, "vel.grd", Out))
        die("failed to write output grid ", "vel.grd");

    /* Write velocity uncertainty using the original sbas rms formula. */
    for (p = 0; p < npix; p++)
        Out->data[p] = rms[p];

    strcpy(Out->header->title, "");
    strcpy(Out->header->remark, "");
    if (GMT_Set_Comment(API, GMT_IS_GRID, GMT_COMMENT_IS_REMARK,
                        "Velocity uncertainty from SBAS (mm/yr)", Out))
        die("could not set grid remark", "");
    if (GMT_Set_Comment(API, GMT_IS_GRID, GMT_COMMENT_IS_TITLE,
                        "RMS uncertainty of LOS velocity from SBAS", Out))
        die("could not set grid title", "");
    if (GMT_Write_Data(API, GMT_IS_GRID, GMT_IS_FILE, GMT_IS_SURFACE,
                       GMT_GRID_ALL, NULL, "rms.grd", Out))
        die("failed to write output grid ", "rms.grd");

    if (fclose(disp_store))
        die("error closing temporary displacement file", "");

    if (Out != NULL)
        GMT_Destroy_Data(API, &Out);

    if (GMT_Destroy_Session(API))
        return EXIT_FAILURE;

    for (i = 0; i < N; i++)
        free(gfile[i]);

    free(gfile);
    free(scene_id);
    free(scene_time);
    free(ref_id);
    free(rep_id);
    free(iref);
    free(irep);
    free(G0);
    free(chol);
    free(phi);
    free(disp);
    free(reference_phase);
    free(vel);
    free(rms);

    fprintf(stderr, "sbas0 complete.\n");

    return EXIT_SUCCESS;
}
