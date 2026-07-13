#!/usr/bin/env bash
# Consolidated installer for the GMTSAR Python framework (fork: gmtsar.py.docker.dev).
# Installs deps, builds gmtsar IN-PLACE from this checkout, and stages Python
# utilities into <repo>/bin. Re-runnable (idempotent).
#
# Install location: the existing clone. The script never re-clones and never
# installs system-wide. `make install` lands in <repo>/bin via --prefix=<repo>.
#
# Two dependency-install modes (pick one):
#   --ubuntu     apt-install system deps (REQUIRES SUDO)
#   --conda      use an existing conda env (no sudo). Set CONDA_GMTSAR_ENV to
#                pick which env (default: 'gmtsar'); env must already contain
#                gmt, libtiff, libhdf5, liblapack, etc.
#
# Other independent steps:
#   --python     install Python packages (apt in --ubuntu mode, pip in --conda)
#   --build      build gmtsar in-place and stage Python utils into <repo>/bin
#   --orbits     fetch ORBITS.tar (~5-7 GB) into <repo>/orbits
#   --all        equivalent to --ubuntu --python --build (skips --orbits)
#
# Examples:
#   bash gmtsar/python/install.sh --conda --python --build    # no-sudo path
#   bash gmtsar/python/install.sh --all                       # sudo path
#   bash gmtsar/python/install.sh --build                     # rebuild only (no deps)
#   bash gmtsar/python/install.sh --orbits                    # download Sentinel-1 orbits

set -euo pipefail

DO_UBUNTU=0; DO_CONDA=0; DO_PYTHON=0; DO_ORBITS=0; DO_BUILD=0
[[ $# -eq 0 ]] && { sed -n '2,24p' "$0"; exit 0; }
for arg in "$@"; do
  case "$arg" in
    --ubuntu)  DO_UBUNTU=1 ;;
    --conda)   DO_CONDA=1 ;;
    --python)  DO_PYTHON=1 ;;
    --orbits)  DO_ORBITS=1 ;;
    --build)   DO_BUILD=1 ;;
    --all)     DO_UBUNTU=1; DO_PYTHON=1; DO_BUILD=1 ;;
    -h|--help) sed -n '2,24p' "$0"; exit 0 ;;
    *) echo "unknown arg: $arg" >&2; exit 2 ;;
  esac
done

[[ $DO_UBUNTU -eq 1 && $DO_CONDA -eq 1 ]] && { echo "ERROR: --ubuntu and --conda are mutually exclusive" >&2; exit 2; }

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd -- "$SCRIPT_DIR/../.." && pwd)
SUDO=$([[ $EUID -eq 0 ]] && echo "" || echo "sudo")

require_apt() {
  command -v apt >/dev/null || { echo "ERROR: apt not found (this script targets Ubuntu/Debian)" >&2; exit 1; }
}

# Locate the conda env when --conda mode is active. CONDA_PREFIX_GMTSAR is exported
# so subsequent steps can wire CPPFLAGS/LDFLAGS without re-resolving.
locate_conda_env() {
  local envname="${CONDA_GMTSAR_ENV:-gmtsar}"
  for base in "$HOME/anaconda3" "$HOME/miniconda3" "/opt/conda"; do
    if [[ -d "$base/envs/$envname" ]]; then
      CONDA_PREFIX_GMTSAR="$base/envs/$envname"
      return 0
    fi
  done
  echo "ERROR: conda env '$envname' not found. Set CONDA_GMTSAR_ENV=<name> or install it." >&2
  exit 1
}

# ------------------------------------------------------ Ubuntu apt deps ---
if [[ $DO_UBUNTU -eq 1 ]]; then
  require_apt
  echo "==> Installing Ubuntu apt system dependencies..."
  $SUDO apt update
  $SUDO apt install -y \
    python-is-python3 csh subversion autoconf libtiff5-dev libhdf5-dev wget \
    liblapack-dev gfortran g++ libgmt-dev gmt-dcw gmt-gshhg gmt ghostscript \
    git make vim
fi

# ----------------------------------------------------- conda env setup ---
if [[ $DO_CONDA -eq 1 ]]; then
  locate_conda_env
  echo "==> Using conda env at $CONDA_PREFIX_GMTSAR (no sudo)"
  # Use conda libs/includes WITHOUT activating the env, so system gfortran/gcc
  # stay in use. Full conda activation pollutes CC/F77 and breaks configure.
  export CPPFLAGS="-I$CONDA_PREFIX_GMTSAR/include -I$CONDA_PREFIX_GMTSAR/include/gmt"
  export LDFLAGS="-L$CONDA_PREFIX_GMTSAR/lib -Wl,-rpath,$CONDA_PREFIX_GMTSAR/lib"
  export PKG_CONFIG_PATH="$CONDA_PREFIX_GMTSAR/lib/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
fi

# ---------------------------------------------------- Python packages ---
if [[ $DO_PYTHON -eq 1 ]]; then
  REQUIREMENTS_TXT="$REPO_ROOT/gmtsar/python/requirements.txt"
  if [[ $DO_CONDA -eq 1 ]]; then
    echo "==> Installing Python packages into conda env $CONDA_PREFIX_GMTSAR from requirements.txt ..."
    # requirements.txt is the single source of truth (2026-07-13: this used
    # to hardcode a separate, shorter list here that had drifted out of sync
    # -- missing scipy/numba/cython/h5py, which are required for the
    # default-ON compute kernels (xcorr_py, resamp_py, SAT_llt2rat_py,
    # gmt_surface_py) and make_slc_nsr_py. A fresh install via this path
    # left the framework broken out of the box. Read from requirements.txt
    # directly so the two lists can't diverge again.
    "$CONDA_PREFIX_GMTSAR/bin/pip" install --upgrade -r "$REQUIREMENTS_TXT"
  else
    require_apt
    echo "==> Installing Python packages via apt..."
    $SUDO apt install -y \
      python3-skimage python3-matplotlib python3-xarray python3-netcdf4 \
      python3-tk python3-numpy python3-scipy python3-h5py python3-pip
    # numba and cython aren't reliably available as apt packages across
    # Ubuntu releases -- pip install them (see requirements.txt comment on
    # what's NOT apt-installable). Required for xcorr_py/resamp_py/
    # SAT_llt2rat_py/gmt_surface_py, all wired ON by default.
    $SUDO python3 -m pip install --upgrade 'numba>=0.56' 'cython>=3.0'
  fi
fi

# ------------------------------------------- build gmtsar inside repo ---
if [[ $DO_BUILD -eq 1 ]]; then
  echo "==> Building gmtsar in $REPO_ROOT ..."
  cd "$REPO_ROOT"
  [[ -f configure ]] || autoconf
  autoupdate || true
  [[ -f config.mk ]] || ./configure --prefix="$REPO_ROOT" --with-orbits-dir="$REPO_ROOT/orbits"

  # Patch config.mk: configure leaves GMT_INC/GMT_LIB/TIFF_* empty or wrong, and
  # the modern-linker muldefs flag must live in LDFLAGS (not CFLAGS) because the
  # gmtsar/Makefile link rule uses $(LDFLAGS) only.
  if [[ $DO_CONDA -eq 1 ]]; then
    sed -i "s|^GMT_INC\s*=.*|GMT_INC = -I$CONDA_PREFIX_GMTSAR/include -I$CONDA_PREFIX_GMTSAR/include/gmt|" config.mk
    sed -i "s|^GMT_LIB\s*=.*|GMT_LIB = -L$CONDA_PREFIX_GMTSAR/lib -lgmt|" config.mk
    sed -i "s|^TIFF_INC\s*=.*|TIFF_INC = $CONDA_PREFIX_GMTSAR/include|" config.mk
    sed -i "s|^TIFF_LIB\s*=.*|TIFF_LIB = $CONDA_PREFIX_GMTSAR/lib|" config.mk
  fi
  if ! grep -q -- '-Wl,-z,muldefs' config.mk; then
    sed -i 's|^\(LDFLAGS\s*=.*\)$|\1 -Wl,-z,muldefs|' config.mk
  fi

  # Sequential build: gmtsar's recursive Makefile has cross-dir dependencies
  # (preproc/* links against ../../gmtsar/libgmtsar) that race under -j.
  make
  make install   # installs into $REPO_ROOT/bin via --prefix=$REPO_ROOT (no sudo)

  # Stage Python utilities alongside compiled binaries.
  # Symlink (not copy) so edits in gmtsar/python/utils/ are picked up live.
  chmod -R 755 "$REPO_ROOT/gmtsar/python/utils"
  for f in "$REPO_ROOT/gmtsar/python/utils/"*; do
    ln -sf "$f" "$REPO_ROOT/bin/$(basename "$f")"
  done

  # Symlink the bin_py/ ports that utils/p2p_stages.py invokes by bare name
  # via subprocess (resamp_py, xcorr_py, etc.) -- these must be on PATH too.
  # One production copy per tool, no version suffixes (project_rules.md
  # Rule 13) -- superseded variants (resamp_py_v2, SAT_llt2rat_py's old v1)
  # were kept at bin_py/archive/ for reference, removed in the v2.7.1 doc
  # cleanup (recoverable from git history if needed), never on PATH.
  chmod +x "$REPO_ROOT/gmtsar/python/bin_py/"*_py
  for name in phasediff_py make_los_py SAT_baseline_py xcorr_py resamp_py make_slc_s1a_py SAT_llt2rat_py; do
    ln -sf "$REPO_ROOT/gmtsar/python/bin_py/$name" "$REPO_ROOT/bin/$name"
  done

  # Symlink the canonical csh scripts (pop_config.csh, p2p_processing.csh, ...) so
  # they're on PATH via $GMTSAR/bin. make install does NOT do this upstream.
  # Source files may ship non-executable in the tree (mode 0644), so chmod first.
  chmod +x "$REPO_ROOT/gmtsar/csh/"*.csh
  ln -sf "$REPO_ROOT/gmtsar/csh/"*.csh "$REPO_ROOT/bin/"

  # Symlink deprecated per-SAT csh wrapper shims (p2p_ALOS.csh → p2p_processing.csh
  # ALOS, etc.) so legacy tarball READMEs from topex.ucsd.edu/gmtsar/tar/ work
  # out of the box. These names were superseded by p2p_processing.csh's SAT
  # dispatch years ago, but some bundled READMEs still call them.
  if [ -d "$REPO_ROOT/gmtsar/python/csh_shims" ]; then
    chmod +x "$REPO_ROOT/gmtsar/python/csh_shims/"*.csh
    ln -sf "$REPO_ROOT/gmtsar/python/csh_shims/"*.csh "$REPO_ROOT/bin/"
  fi

  # Build FFTW threading shim — neuters fftwf_plan_with_nthreads at runtime
  # (LD_PRELOAD'd by runner.py). Without it, libgmt's pthread-based FFTW
  # spawns 14-19 threads per process and contends across pipelines.
  gcc -shared -fPIC -O2 \
      -o "$REPO_ROOT/gmtsar/python/fftw_force_serial.so" \
         "$REPO_ROOT/gmtsar/python/fftw_force_serial.c"
fi

# ------------------------------------------------ orbits (optional, big) --
if [[ $DO_ORBITS -eq 1 ]]; then
  echo "==> Fetching ORBITS.tar (~5-7 GB) into $REPO_ROOT/orbits ..."
  mkdir -p "$REPO_ROOT/orbits"
  cd "$REPO_ROOT/orbits"
  [[ -f ORBITS.tar || -d S1A ]] || wget -c http://topex.ucsd.edu/gmtsar/tar/ORBITS.tar
  [[ -f ORBITS.tar ]] && { tar -xf ORBITS.tar && rm -f ORBITS.tar; }
fi

# --------------------------------------------------------- env summary ---
cat <<EOF

All requested steps completed.

To use gmtsar from this checkout, add to ~/.bashrc (or run in your shell):
  export GMTSAR=$REPO_ROOT
  export PATH=\$GMTSAR/bin:\$PATH

If you used --conda, also put the conda env on PATH so 'gmt' is found
(the line above only adds \$GMTSAR/bin):
  conda activate \${CONDA_GMTSAR_ENV:-gmtsar}    # or: export PATH=\$CONDA_PREFIX/bin:\$PATH

Sanity check:
  which p2p_processing && p2p_processing
  gmt --version        # confirms gmt is reachable (needed for actual runs)
EOF
