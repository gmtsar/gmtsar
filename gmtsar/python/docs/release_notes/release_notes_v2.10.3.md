# v2.10.3 — `distribute_gmtsar_windows.py` proven: bundle-only RS2 run, bit-identical

Scope: `v2.10.2..v2.10.3`. Closes the one do-not-ship item v2.10.2's
ledger flagged: the self-contained Windows bundle's isolated-PATH
verify failing 27/38 exes. Root-caused, fixed through five real bugs,
and proven by the strongest test available: a full RS2 pipeline run
using **only the bundle** — no conda, no Git for Windows anywhere in
the process environment — producing `phasefilt.grd` **bit-identical**
(complex-rms 0.000e+00) to the clean-room sweep's mode0 reference.

## Root cause of the 27/38 failure: export forwarders (MKL shims)

conda-forge's win-64 `libblas.dll`/`liblapack.dll` default to the MKL
variant — pure forwarder shims whose EXPORTS forward to `mkl_rt.N.dll`.
The loader resolves forwarders at import time exactly like static
imports, but they live in the export table where no import walk sees
them, so MKL was never bundled and `gmt.dll` (which imports the shims)
died STATUS_DLL_NOT_FOUND with every import-table dependency present.
Diagnosed by strict elimination: static import closure complete against
System32, every import loadable individually by bare name,
`DONT_RESOLVE_DLL_REFERENCES` loads clean — then the shims' forwarder
strings named `mkl_rt` directly.

Fixes (each with a regression guard in `test_windows_port.py`):
- `_pe_forwarder_targets()` — minimal stdlib PE export-directory parse;
  the dependency walk now BFSes imports + forwarders. (Test fixture: a
  real one — `kernel32.dll`'s famous forwards to ntdll.)
- `WINDOWS_CONDA_BOOTSTRAP_PACKAGES` pins `libblas/liblapack/libcblas
  =*=*openblas` — co-installing openblas does NOT flip conda-forge's
  default MKL shims (confirmed on a genuinely fresh env), and MKL can't
  be bundled anyway (mkl_rt dispatches to mkl_core/mkl_avx* via runtime
  LoadLibrary no static walk can see). The walk also fail-louds with
  that guidance if MKL ever enters the closure.
- `_is_system_dll()` policy: api-set names are virtual on Win10+ (never
  bundle the stub files); `vcruntime*/msvcp*/concrt*` are NEVER system
  (System32 presence only proves the DEV machine has a VC redist);
  SysWOW64 dropped (32-bit DLLs can't satisfy x64 exes).

## Four more real bugs, found by the bundle smoke itself

1. Git for Windows' `Git\bin\bash.exe` is a **launcher stub** that
   re-executes `..\usr\bin\bash.exe` — bundled alone it dies with
   "Need a valid command-line". The bundle now replicates the real
   `usr/bin` layout (real bash + coreutils + each tool's `msys-*.dll`
   deps resolved via its actual import table), ships `git-bash/tmp`
   (MSYS `/tmp`), and everything points at `usr/bin/bash.exe`.
2. MSYS bash does NOT implicitly put its own `/usr/bin` on PATH for
   non-login `bash -c` — the launcher provides it; the verify now
   mirrors that instead of false-failing with `ln: command not found`.
3. The `gmt.exe` CLI driver (and ghostscript) live inside the packed
   pyenv's `Library\bin` — the pipeline shells out to `gmt ...`
   constantly and died rc=127 until the launcher PATH gained it.
   Likewise `GMT_SHAREDIR` is pinned to the bundle's share (the
   `gmt.dll` copy in `dist\bin` has the BUILD env's absolute share
   path baked in — invisible on the dev machine, broken elsewhere).
4. The staged `bin_py` tools resolve their `utils` package via the
   `$GMTSAR/gmtsar/python/utils` fallback — the bundle now carries
   `gmtsar/python/{utils,bin_py}` so that tree exists at the bundle's
   GMTSAR root.

Plus a verify-harness fix: exes that read stdin (`esarp` etc.) blocked
forever on an inherited console handle — stdin is now closed (EOF-exit)
and a genuine 15s timeout counts as started-OK (DLL failures are
instant), instead of crashing the whole verify. `0xC000007B` (32/64
mismatch) is caught alongside `0xC0000135`.

## Verification record

- 3-layer isolated-PATH verify (bundle + System32 only): **38/38 exes
  start, bundled python imports numpy/scipy/numba/netCDF4/matplotlib,
  bundled bash runs echo/ln/mkdir/rm** — all PASS.
- Full-pipeline bundle smoke: RS2_SLC_Hawaii `p2p_processing` end-to-end
  under a scrubbed environment (PATH = bundle dirs + System32 only,
  GMTSAR/GMTSAR_WIN_BASH/GMT_SHAREDIR pointing into the bundle):
  `P2P 7: FINISHED`, zero rc=127, zero tracebacks, `corr.grd` mean
  0.4126 / zero-frac 0.000, and `phasefilt.grd` complex-rms
  **0.000e+00** vs the v2.10.2 clean-room sweep's mode0 reference.
- Honest caveats: all evidence is from the dev host (a physically
  different bare machine hasn't executed the bundle); the final `.zip`
  is produced on demand (run without `--skip-zip`); LICENSE/attribution
  collation for the bundled third-party binaries is still a TODO before
  public distribution.

## Tests

8 new guards appended to `bin_py/tests/test_windows_port.py` (35 total
across the two install/Windows suites, all passing on the Windows dev
host): openblas variant pins, `_is_system_dll` policy, forwarder parser
on real kernel32 forwards + non-PE tolerance, forwarder-walk + MKL
guard presence, launcher-template contract (pyenv\Library\bin,
usr\bin\bash.exe, GMT_SHAREDIR), framework-tree bundling, and the
stdin/timeout verify-harness behavior.
