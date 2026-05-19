/* fftw_force_serial.c — LD_PRELOAD shim to force FFTW single-threaded.
 *
 * libgmt is built with libfftw3f_threads, so xcorr inherits FFTW threading at
 * load time. There's no env var to disable it from outside. This shim
 * intercepts the threading-init calls so any plan_with_nthreads() request
 * silently becomes nthreads=1, regardless of what GMT/xcorr asks for.
 *
 * Build:
 *   gcc -shared -fPIC -O2 -o gmtsar/python/fftw_force_serial.so \
 *       gmtsar/python/fftw_force_serial.c
 *
 * Use:
 *   LD_PRELOAD=$GMTSAR/gmtsar/python/fftw_force_serial.so xcorr ...
 */

/* float-precision (libfftw3f) — what xcorr actually uses */
int  fftwf_init_threads(void)            { return 1; }      /* success, but no-op */
void fftwf_plan_with_nthreads(int n)     { (void)n; }       /* ignore — keep 1 thread */
int  fftwf_cleanup_threads(void)         { return 0; }
void fftwf_make_planner_thread_safe(void){ }

/* double-precision (libfftw3) — in case anything else in the pipeline uses it */
int  fftw_init_threads(void)             { return 1; }
void fftw_plan_with_nthreads(int n)      { (void)n; }
int  fftw_cleanup_threads(void)          { return 0; }
void fftw_make_planner_thread_safe(void) { }

/* long-double (libfftw3l) — covers the third FFTW variant if linked transitively */
int  fftwl_init_threads(void)            { return 1; }
void fftwl_plan_with_nthreads(int n)     { (void)n; }
int  fftwl_cleanup_threads(void)         { return 0; }
void fftwl_make_planner_thread_safe(void){ }
