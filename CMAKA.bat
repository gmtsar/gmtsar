@echo off
setlocal

set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"
set "BUILD=%ROOT%\build"
set "CMAKE_EXE=C:\Program Files\Microsoft Visual Studio\18\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"
set "VCVARS=C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat"

if not exist "%CMAKE_EXE%" (
	echo ERROR: Visual Studio CMake not found: %CMAKE_EXE%
	exit /b 1
)
if not exist "%VCVARS%" (
	echo ERROR: MSVC environment script not found: %VCVARS%
	exit /b 1
)
call "%VCVARS%" >nul || exit /b 1
where nmake >nul 2>nul || (
	echo ERROR: MSVC NMake was not added to PATH by vcvars64.bat
	exit /b 1
)

"%CMAKE_EXE%" -S "%ROOT%" -B "%BUILD%" -G "NMake Makefiles" ^
	-DCMAKE_BUILD_TYPE=Release ^
	-DCMAKE_C_COMPILER=cl ^
	-DCMAKE_INSTALL_PREFIX="%ROOT%\compileds\WIN64" ^
	-DGMT_LIBRARY=C:/progs_cygw/GMTdev/gmt5/compileds/gmt6/VC14_64/lib/gmt.lib ^
	-DGMT_INCLUDE_DIR=C:/progs_cygw/GMTdev/gmt5/compileds/gmt6/VC14_64/include/gmt ^
	-DTIFF_LIBRARY=C:/programs/compa_libs/tiff-4.1.0/compileds/VC14_64/lib/libtiff_i.lib ^
	-DTIFF_INCLUDE_DIR=C:/programs/compa_libs/tiff-4.1.0/compileds/VC14_64/include ^
	-DLAPACK_LIBRARIES=C:/programs/compa_libs/lapack-3.5.0/compileds/lib/liblapack.lib ^
	-DGETOPT_LIB=C:/programs/compa_libs/getopt/compileds/VC14_64/lib/getopt.lib ^
	-DGETOPT_INC=C:/programs/compa_libs/getopt/compileds/VC14_64/include ^
	-DFFTW3F_LIBRARY=C:/programs/compa_libs/fftw-3.3.4/compileds/VC14_64/lib/libfftwf-3.3.lib || exit /b 1

"%CMAKE_EXE%" --build "%BUILD%" --target install --parallel || exit /b 1
endlocal
