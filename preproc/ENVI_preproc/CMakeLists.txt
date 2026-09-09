#
#	$Id: $
#

if (HAVE_M_LIBRARY)
	# link the math library
	set (LINK_LIBS m)
endif (HAVE_M_LIBRARY)

# ENVI uses the ALOS orbit/PRM ABI.  Keep that include directory ahead of
# gmtsar's similarly named headers, otherwise MSVC picks incompatible PRM and
# lib_functions definitions.
include_directories (include ../ALOS_preproc/include ../../gmtsar ${GMT_INCLUDE_DIR})

add_library (ENVI lib_src/ENVI_ldr_orbit.c lib_src/read_ENVI_orb.c)
target_link_libraries (ENVI ALOS gmtsar ${LINK_LIBS})

set (LINK_LIBS ${LINK_LIBS} gmtsar ENVI ALOS)

add_executable (asa_cat ASA_CAT/asa_cat.c)
target_link_libraries (asa_cat ${LINK_LIBS})

add_executable (calc_dop_orb_envi Dop_orbit/calc_dop_orb_envi.c)
target_link_libraries (calc_dop_orb_envi ${LINK_LIBS})

add_executable (ENVI_baseline ENVI_baseline/ENVI_baseline.c ENVI_baseline/ENVI_llt2rat_sub.c)
target_link_libraries (ENVI_baseline ${LINK_LIBS})

add_executable (asa_im_decode ENVI_decode/asa_im_decode.c)
target_link_libraries (asa_im_decode ${LINK_LIBS})

add_executable (ENVI_llt2rat ENVI_llt2rat/ENVI_llt2rat.c)
target_link_libraries (ENVI_llt2rat ${LINK_LIBS})

add_executable (ENVI_look ENVI_look/ENVI_look.c)
target_link_libraries (ENVI_look ${LINK_LIBS})


# add the install targets
install (TARGETS asa_cat calc_dop_orb_envi ENVI_baseline asa_im_decode ENVI_llt2rat ENVI_look      
	ARCHIVE DESTINATION lib
	COMPONENT Runtime
	LIBRARY DESTINATION lib
	COMPONENT Runtime
	RUNTIME DESTINATION bin
	COMPONENT Runtime)

# vim: textwidth=78 noexpandtab tabstop=2 softtabstop=2 shiftwidth=2
