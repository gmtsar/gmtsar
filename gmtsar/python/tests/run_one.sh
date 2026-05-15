#!/bin/bash
# run_one.sh — run a single Python-side test for one case.
#
# Different from sweep.sh: this is for *new* tests, not regression.
# - No csh-side run.
# - No cross-framework compare.py.
# - Just: download (cached) → extract → run the Python recipe → show outputs.
#
# Usage:
#   tests/run_one.sh CASE_NAME              # default workdir /tmp/CASE_NAME/
#   SCRATCH=/path tests/run_one.sh CASE     # use a chosen workdir
#
# Examples:
#   tests/run_one.sh NISAR_Ethiopia
#   tests/run_one.sh ALOS4_Pinon
#   SCRATCH=/data/scratch tests/run_one.sh S1_Larsen_C

set -e
case=${1:?usage: tests/run_one.sh CASE_NAME}

# Resolve repo dirs.
TESTS=$(cd "$(dirname "$0")" && pwd)
PYDIR=$(cd "$TESTS/.." && pwd)
WORK=${SCRATCH:-/tmp/$case}/py.test
mkdir -p "$WORK/dataset" "$WORK/recipes"

# Resolve archive URL + extension from cases.py.
META=$(cd "$TESTS" && python3 -c "
from cases import CASES, archive_url
info = CASES.get('$case')
if not info:
    raise SystemExit('Unknown case: $case (see cases.py for valid names)')
print(info['ext'], archive_url('$case'))
") || exit 1
read -r EXT URL <<<"$META"

TAR="$WORK/dataset/$case.$EXT"
if [ ! -f "$TAR" ]; then
    # Try to reuse the main workdir's cache (gmtsar/python/work/dataset/).
    if [ -f "$PYDIR/work/dataset/$case.$EXT" ]; then
        ln -sf "$PYDIR/work/dataset/$case.$EXT" "$TAR"
        echo "[run_one] cached tarball reused: $PYDIR/work/dataset/$case.$EXT"
    else
        echo "[run_one] downloading $URL"
        wget -c --timeout=120 "$URL" -O "$TAR"
    fi
fi

# Stage the python recipe (case_runner.sh expects this exact path).
RECIPE_SRC="$TESTS/recipes/README_$case.txt"
[ -f "$RECIPE_SRC" ] || { echo "[run_one] missing recipe: $RECIPE_SRC"; exit 2; }
cp "$RECIPE_SRC" "$WORK/recipes/"

# Extract into a fresh case dir.
CASEDIR="$WORK/$case"
rm -rf "$CASEDIR"
mkdir -p "$CASEDIR"
tar -xzf "$TAR" -C "$CASEDIR"

# Run the python recipe in the case dir.
cd "$CASEDIR"
cp "$RECIPE_SRC" "README_$case.txt"
chmod +x "README_$case.txt"
export LD_PRELOAD="$PYDIR/fftw_force_serial.so"
echo "[run_one] running ./README_$case.txt in $CASEDIR (log → $CASEDIR/log.txt)"
./"README_$case.txt" > log.txt 2>&1
rc=$?
echo "[run_one] python recipe exited rc=$rc"
echo "[run_one] outputs:"
find "$CASEDIR/intf" "$CASEDIR/merge" -maxdepth 3 -name "*.grd" -o -name "*.png" 2>/dev/null | head -20
exit $rc
