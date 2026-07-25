#
#	$Id$
#

if (WIN32)
	# Real, confirmed-by-repro bug: LAPACK_LIBRARIES on Windows resolves to
	# conda-forge's openblas.lib, which exports ~77,000 symbols. Linking
	# ANY DLL against the full import library corrupts that DLL at
	# runtime with this toolchain's old binutils (2.25.1 / GCC 5.3.0) --
	# even calling a trivial unrelated function (e.g. reading its own
	# 2nd string-pointer argument) inside that DLL segfaults. Isolated
	# with a minimal repro (a one-line die(char*,char*) function crashes
	# when its containing DLL links openblas.lib, but not when it links
	# libtiff.lib or gmt.lib, and not when linked against a HAND-BUILT
	# import lib exporting only the symbols actually used) -- looks like
	# an IAT/thunk generation bug triggered by the sheer symbol count,
	# not anything about GMTSAR/GMT/openblas's actual code.
	#
	# gmtsar only ever calls ONE LAPACK routine, dgelsy_ (sbas.c /
	# sbas_utils.c; preproc/ doesn't link LAPACK at all) -- build a
	# minimal import library exporting just that symbol against the
	# real openblas.dll, sidestepping the huge-import-table trigger
	# entirely instead of linking the full openblas.lib.
	get_filename_component (_mingw_bin_dir "${CMAKE_C_COMPILER}" DIRECTORY)
	find_program (DLLTOOL_EXECUTABLE dlltool HINTS "${_mingw_bin_dir}")
	if (NOT DLLTOOL_EXECUTABLE)
		message (FATAL_ERROR "dlltool not found -- needed to work around "
			"the Windows openblas.lib linking bug (see comment above)")
	endif ()
	set (OPENBLAS_MIN_DEF "${CMAKE_CURRENT_BINARY_DIR}/openblas_min.def")
	file (WRITE "${OPENBLAS_MIN_DEF}" "LIBRARY openblas.dll\nEXPORTS\ndgelsy_\n")
	set (OPENBLAS_MIN_LIB "${CMAKE_CURRENT_BINARY_DIR}/libopenblas_min.dll.a")
	add_custom_command (
		OUTPUT "${OPENBLAS_MIN_LIB}"
		COMMAND "${DLLTOOL_EXECUTABLE}" -d "${OPENBLAS_MIN_DEF}" -l "${OPENBLAS_MIN_LIB}" -D openblas.dll
		DEPENDS "${OPENBLAS_MIN_DEF}"
		COMMENT "Generating minimal openblas import lib (Windows linker workaround, see gmtsar/CMakeLists.txt)")
	add_custom_target (openblas_min_lib_target DEPENDS "${OPENBLAS_MIN_LIB}")
	set (LAPACK_LIBRARIES "${OPENBLAS_MIN_LIB}")
endif (WIN32)

if (WIN32)
	# Real clean-machine failure (2026-07-24, fresh conda env on another
	# host): find_package(TIFF REQUIRED) succeeded but left TIFF_LIBRARY
	# empty, so TIFF silently vanished from GMTSAR_LINK_LIBS and the ONE
	# executable calling libtiff directly (split_spectrum.c: TIFFOpen/
	# TIFFReadScanline/...) failed at link with undefined references --
	# every other target linked fine, hiding the root cause. conda-forge's
	# libtiff has shipped its import library under both names
	# (libtiff.lib and/or tiff.lib) across builds; coalesce explicitly
	# and FAIL AT CONFIGURE TIME if nothing resolves, never link without
	# TIFF silently. (Fresh cache var for the fallback: a stale
	# TIFF_LIBRARY-NOTFOUND in CMakeCache.txt would otherwise pin the
	# fallback search to its old failure.)
	if (NOT TIFF_LIBRARY AND TIFF_LIBRARIES)
		set (TIFF_LIBRARY ${TIFF_LIBRARIES})
	endif ()
	if (NOT TIFF_LIBRARY)
		find_library (TIFF_LIBRARY_WIN_FALLBACK NAMES tiff libtiff)
		if (TIFF_LIBRARY_WIN_FALLBACK)
			set (TIFF_LIBRARY ${TIFF_LIBRARY_WIN_FALLBACK})
		endif ()
	endif ()
	if (NOT TIFF_LIBRARY)
		message (FATAL_ERROR "TIFF import library not found (checked "
			"TIFF_LIBRARY, TIFF_LIBRARIES, and a direct search for "
			"tiff.lib/libtiff.lib) -- refusing to configure a build that "
			"would silently drop TIFF from the link line and fail only at "
			"split_spectrum.exe's link step. Is libtiff installed in the "
			"conda env this build is using?")
	endif ()
endif (WIN32)

set (GMTSAR_LINK_LIBS ${GMT_LIBRARY} ${TIFF_LIBRARY} ${LAPACK_LIBRARIES})

if (HAVE_M_LIBRARY)
	# link the math library
	set (GMTSAR_LINK_LIBS ${GMTSAR_LINK_LIBS} m)
endif (HAVE_M_LIBRARY)

include_directories (${GMT_INCLUDE_DIR} ${TIFF_INCLUDE_DIR})

if (WIN32)
	# sbas_utils.c / resamp.c / sbas.c #include <sys/mman.h>, which MinGW
	# doesn't provide -- a local mmap()/munmap() shim covers the subset
	# they actually use (see compat_win32/sys/mman.h).
	include_directories (${CMAKE_CURRENT_SOURCE_DIR}/compat_win32)
endif (WIN32)

add_library (gmtsar aastretch.c acpatch.c calc_dop.c conv2d.c do_freq_xcorr.c
	do_time_int_xcorr.c fft_bins.c fft_interpolate_routines.c file_stuff.c
	geoxyz.c get_locations.c get_params.c hermite_c.c highres_corr.c
	interpolate_orbit.c intp_coef.c ldr_orbit.c parse_xcorr_input.c plxyz.c
	polyfit.c print_results.c radopp.c read_orb.c read_xcorr_data.c
	SAT_llt2rat_sub.c rmpatch.c rng_cmp.c rng_ref.c set_prm_defaults.c shift.c
	sio_struct.c siocomplex.c spline.c trans_col.c utils.c utils_complex.c
	write_orb.c sbas_utils.c stringutils.c update_PRM_sub.c rng_filter.c
	lib_strfuncs.c gmtsar.h lib_functions.h llt2xyz.h orbit.h
	sarleader_ALOS.h sarleader_fdr.h sfd_complex.h siocomplex.h soi.h xcorr.h)
target_link_libraries (gmtsar ${GMTSAR_LINK_LIBS})
if (WIN32)
	add_dependencies (gmtsar openblas_min_lib_target)
endif (WIN32)

set (GMTSAR_LINK_LIBS ${GMTSAR_LINK_LIBS} gmtsar)

add_executable (bperp bperp.c gmtsar.h)
target_link_libraries (bperp ${GMTSAR_LINK_LIBS})

add_executable (calc_dop_orb calc_dop_orb.c gmtsar.h orbit.h)
target_link_libraries (calc_dop_orb ${GMTSAR_LINK_LIBS})

add_executable (conv conv.c gmtsar.h)
target_link_libraries (conv ${GMTSAR_LINK_LIBS})

add_executable (esarp esarp.c soi.h gmtsar.h)
target_link_libraries (esarp ${GMTSAR_LINK_LIBS})

add_executable (extend_orbit extend_orbit.c gmtsar.h orbit.h lib_functions.h)
target_link_libraries (extend_orbit ${GMTSAR_LINK_LIBS})

add_executable (make_gaussian_filter make_gaussian_filter.c PRM.h lib_functions.h)
target_link_libraries (make_gaussian_filter ${GMTSAR_LINK_LIBS})

add_executable (offset_topo offset_topo.c gmtsar.h)
target_link_libraries (offset_topo ${GMTSAR_LINK_LIBS})

add_executable (phase2topo phase2topo.c gmtsar.h)
target_link_libraries (phase2topo ${GMTSAR_LINK_LIBS})

add_executable (phasediff phasediff.c gmtsar.h)
target_link_libraries (phasediff ${GMTSAR_LINK_LIBS})

add_executable (phasefilt phasefilt.c gmtsar.h)
target_link_libraries (phasefilt ${GMTSAR_LINK_LIBS})

add_executable (resamp resamp.c gmtsar.h lib_functions.h)
target_link_libraries (resamp ${GMTSAR_LINK_LIBS})

add_executable (SAT_baseline SAT_baseline.c gmtsar.h orbit.h)
target_link_libraries (SAT_baseline ${GMTSAR_LINK_LIBS})

add_executable (SAT_llt2rat SAT_llt2rat.c gmtsar.h orbit.h llt2xyz.h)
target_link_libraries (SAT_llt2rat ${GMTSAR_LINK_LIBS})

add_executable (SAT_look SAT_look.c gmtsar.h orbit.h llt2xyz.h)
target_link_libraries (SAT_look ${GMTSAR_LINK_LIBS})

add_executable (sbas sbas.c gmtsar.h sbas.h)
target_link_libraries (sbas ${GMTSAR_LINK_LIBS})

add_executable (update_PRM update_PRM.c update_PRM.h gmtsar.h)
target_link_libraries (update_PRM ${GMTSAR_LINK_LIBS})

add_executable (get_PRM get_PRM.c update_PRM.h)
target_link_libraries (get_PRM ${GMTSAR_LINK_LIBS})

add_executable (nearest_grid nearest_grid.c gmtsar.h)
target_link_libraries (nearest_grid ${GMTSAR_LINK_LIBS})

add_executable (fitoffset fitoffset.c update_PRM.h)
target_link_libraries (fitoffset ${GMTSAR_LINK_LIBS})
if (WIN32)
	# fitoffset.c is the only file calling getline(), a glibc/POSIX
	# extension the mingw-w64 runtime doesn't provide (see
	# compat_win32/getline_shim.h). Force-include the shim for this one
	# target only, instead of editing the upstream .c file.
	target_compile_options (fitoffset PRIVATE
		-include "${CMAKE_CURRENT_SOURCE_DIR}/compat_win32/getline_shim.h")
endif (WIN32)

add_executable (solid_tide solid_tide.c lib_functions.h)
target_link_libraries (solid_tide ${GMTSAR_LINK_LIBS})

add_executable (p_scatter p_scatter.c gmtsar.h)
target_link_libraries (p_scatter ${GMTSAR_LINK_LIBS})

add_executable (split_spectrum split_spectrum.c gmtsar.h)
target_link_libraries (split_spectrum ${GMTSAR_LINK_LIBS})

add_executable (cut_slc cut_slc.c gmtsar.h)
target_link_libraries (cut_slc ${GMTSAR_LINK_LIBS})

add_executable (split_aperture split_aperture.c gmtsar.h)
target_link_libraries (split_aperture ${GMTSAR_LINK_LIBS})

add_executable (phasediff_get_topo_phase phasediff_get_topo_phase.c gmtsar.h)
target_link_libraries (phasediff_get_topo_phase ${GMTSAR_LINK_LIBS})

add_executable (geocode_slc geocode_slc.c gmtsar.h llt2xyz.h orbit.h)
target_link_libraries (geocode_slc ${GMTSAR_LINK_LIBS})

add_executable (xcorr xcorr.c gmtsar.h)
target_link_libraries (xcorr ${GMTSAR_LINK_LIBS})

# add the install targets
install (TARGETS gmtsar bperp calc_dop_orb conv esarp extend_orbit make_gaussian_filter offset_topo phase2topo phasediff phasefilt resamp SAT_baseline SAT_llt2rat SAT_look sbas xcorr update_PRM get_PRM nearest_grid fitoffset solid_tide p_scatter split_spectrum cut_slc split_aperture phasediff_get_topo_phase geocode_slc
	ARCHIVE DESTINATION lib
	COMPONENT Runtime
	LIBRARY DESTINATION lib
	COMPONENT Runtime
	RUNTIME DESTINATION bin
	COMPONENT Runtime)

add_subdirectory (csh)

# vim: textwidth=78 noexpandtab tabstop=2 softtabstop=2 shiftwidth=2
