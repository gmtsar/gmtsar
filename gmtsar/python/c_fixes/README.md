# c_fixes/ — real fixes to upstream `gmtsar/*.c`, staged here

This directory holds corrected copies of files under `gmtsar/gmtsar/`
(the real upstream C source, outside `gmtsar/python/`). Per this repo's
"all dev work lives in `gmtsar/python/`, everything else is upstream and
stays untouched for clean merges" rule, real fixes to upstream `.c` files
are staged here first rather than applied directly at their original
location.

## fitoffset.c — strlcpy portability bug

Found 2026-07-23 while clean-room testing full conda-toolchain isolation
(conda-forge's own `gfortran_linux-64`/`gxx_linux-64` compiler packages,
not the system compiler). `gmtsar/fitoffset.c` calls `strlcpy()` (a BSD
function) without declaring or including it anywhere. This "works" —
implicit-declaration is only a *warning* — on GCC < 14 (e.g. the
system's Ubuntu 22.04 GCC 11.4.0, which `--system conda`'s existing
install path deliberately uses instead of a conda-provided compiler).
It's a **hard compile error** on GCC 14+ (conda-forge's compiler
packages are GCC 15.2.0), which promoted implicit function declarations
from warning to error by default as part of C23 alignment. Confirmed
directly: same source, `-Werror` NOT passed, system gcc 11.4.0 →
warning + successful link; conda gcc 15.2.0 → hard error.

This is a real forward-compatibility bug independent of conda isolation
-- it will also break `--system ubuntu` on any distro shipping GCC 14+
(Ubuntu 24.10+, Fedora 40+, Arch already do).

**Fix**: both call sites replace `strlcpy(dest, "literal", sizeof
dest)` with `snprintf(dest, sizeof dest, "%s", "literal")` -- identical
behavior for a fixed short literal into a `MAX_PATH`-sized buffer,
zero new includes, no BSD-library dependency, compiles cleanly on every
GCC version tested (11.4.0 and 15.2.0).

Applied automatically at build time by `install.py`'s `_apply_c_fixes()`
(copies each `C_FIXES` entry over its upstream target before `make`/
CMake runs) -- not yet contributed upstream to the real
`gmtsar/gmtsar/fitoffset.c`, but no longer inert either.

## conv.c — binary file reads opened in text mode (Windows)

Found 2026-07-23 while bringing up `--system conda-windows-full` (native
Windows build, MinGW toolchain). `gmtsar/conv.c` opens the raw complex
SLC file and the `.grd=bf` native-binary-float file with `fopen(path,
"r")` -- **text mode**. On POSIX this is a no-op (`"r"` and `"rb"` are
identical there), so the bug is invisible on Linux/macOS. On Windows,
text mode makes the CRT translate `\r\n` -> `\n` on read AND treat byte
`0x1A` as an EOF marker -- both of which silently corrupt/truncate a
binary stream partway through the file. Confirmed as the root cause of
a real symptom: interferogram correlation (`corr.grd`, `filter`'s
`conv`-based amplitude/correlation formation) collapsing to
near-zero over ~85% of a real RS2 pair's swath on Windows, while the
identical Python framework code produced a near-machine-precision
match to the C reference on Linux (`corr_ll.grd` RMS 1e-6 vs 4e-4)
-- i.e. not a logic bug in the port, a Windows-only binary-mode bug in
the C reader everything downstream depends on.

**Fix**: both `fopen(path, "r")` call sites (the SLC/PRM-derived input,
and the `=bf` grid input) changed to `fopen(path, "rb")`. Harmless on
POSIX (identical behavior), fixes the corruption on Windows.

Applied automatically at build time on every platform (see above) --
safe everywhere since `"rb"` behaves exactly like `"r"` on POSIX.
