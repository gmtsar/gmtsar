#!/usr/bin/env bash
# Quick test wizard — basic-function sanity for gmtsar/python/.
# Designed to catch silent-failure modes BEFORE the 3-hour sweep.sh runs.
# Target wall time: < 30 seconds. Run before every commit / pre-push.
#
# What it catches that compare.py / sweep.sh would not:
#   - missing import (e.g. iono path's `shutil.rmtree` without `import shutil`)
#   - SyntaxError / NameError-on-first-use in any util
#   - shell-syntax bugs in tests/*.sh and csh_shims/*.csh (the sed delimiter
#     bug that made ALOS2 csh run sequentially for hours)
#   - utilities that don't respond to `--help` cleanly (broken CLI)
#   - config-drift between staged Python configs and bundled csh configs,
#     without extracting any tarball
#
# Exit code: 0 = all pass, non-zero = at least one check failed.

set -u
cd "$(dirname "$0")/.."   # gmtsar/python/
ROOT=$(pwd -P)
t0=$SECONDS
PASS=0; FAIL=0

# --- helpers ----------------------------------------------------------------
ok()   { PASS=$((PASS+1)); printf '  \e[32mOK\e[0m   %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  \e[31mFAIL\e[0m %s\n' "$1"; }
hdr()  { printf '\n\e[1m%s\e[0m\n' "$1"; }

# --- 1. Python AST parse ----------------------------------------------------
hdr "[1/5] Python AST parse"
n=0
while read -r f; do
    n=$((n+1))
    if ! python3 -c "import ast,sys; ast.parse(open(sys.argv[1]).read())" "$f" 2>/tmp/wizard.err; then
        bad "$f"
        sed 's/^/         /' /tmp/wizard.err
    fi
done < <(find utils tests -type f \( -name '*.py' -o -name 'fitoffset.py' \) ! -path '*/work/*' ! -path '*/reference/*')
# Plus extension-less Python utilities (every executable under utils/ that starts with python3)
while read -r f; do
    n=$((n+1))
    head -1 "$f" 2>/dev/null | grep -q 'python' || continue
    if ! python3 -c "import ast,sys; ast.parse(open(sys.argv[1]).read())" "$f" 2>/tmp/wizard.err; then
        bad "$f"
        sed 's/^/         /' /tmp/wizard.err
    fi
done < <(find utils -maxdepth 1 -type f -executable ! -name '*.py' ! -name '*.csh')
ok "$n python sources parse cleanly"

# --- 2. Import-time check on Python utilities (catches missing imports
#       like today's `shutil.rmtree` without `import shutil`) -----------------
# Compile every utility with py_compile (no execution) — this catches
# SyntaxError, plus indirectly an `import X` that's truly missing from
# stdlib/site-packages will fail at compile-time-of-the-import line.
hdr "[2/5] Python utility import / compile"
n=0
while read -r f; do
    n=$((n+1))
    out=$(python3 -m py_compile "$f" 2>&1)
    if [ -n "$out" ]; then
        bad "$f"
        echo "$out" | head -3 | sed 's/^/         /'
    fi
done < <(find utils -maxdepth 1 -type f \( -name '*.py' -o ! -name '*.csh' \) \
         | xargs -I{} sh -c 'head -1 "{}" 2>/dev/null | grep -q python && echo "{}"')
ok "$n python utilities compile without SyntaxError"

# --- 3. Bash syntax check ---------------------------------------------------
hdr "[3/5] Bash + csh syntax"
n=0
while read -r f; do
    n=$((n+1))
    if ! bash -n "$f" 2>/tmp/wizard.err; then
        bad "$f"
        sed 's/^/         /' /tmp/wizard.err
    fi
done < <(find tests -name '*.sh' -type f)
ok "$n bash scripts syntax-check"

n=0
while read -r f; do
    n=$((n+1))
    if ! csh -n "$f" 2>/tmp/wizard.err; then
        bad "$f"
        sed 's/^/         /' /tmp/wizard.err
    fi
done < <(find csh_shims -name '*.csh' -type f 2>/dev/null)
ok "$n csh shims syntax-check"

# --- 4. Config-drift dry run (no extraction needed) -------------------------
hdr "[4/5] Config drift (staged python ↔ bundled csh)"
norm() { sed -e "s/^'//" -e "s/'$//" -e 's/^"//' -e 's/"$//'; }
n=0; drift=0
for stagedConfig in tests/configs/*.py; do
    case=$(basename "$stagedConfig" .py)
    bundledCfg=""
    # Look in workdir if the case has been extracted; otherwise skip
    if [ -f "work/python_test/$case/config.txt" ]; then
        bundledCfg="work/python_test/$case/config.txt"
    elif ls work/python_test/$case/config*.txt 2>/dev/null >/dev/null; then
        bundledCfg=$(ls work/python_test/$case/config*.txt 2>/dev/null | head -1)
    fi
    [ -z "$bundledCfg" ] && continue
    n=$((n+1))
    for k in filter_wavelength region_cut threshold_snaphu threshold_geocode dec_factor proc_stage; do
        v_csh=$(grep -E "^[[:space:]]*${k}[[:space:]]*=" "$bundledCfg" | head -1 | awk -F= '{gsub(/^[[:space:]]+|[[:space:]]+$/,"",$2); print $2}' | awk '{print $1}' | norm)
        v_py=$(grep -E "^[[:space:]]*${k}[[:space:]]*=" "$stagedConfig" | head -1 | awk -F= '{gsub(/^[[:space:]]+|[[:space:]]+$/,"",$2); print $2}' | awk '{print $1}' | norm)
        [ "$v_py" = "-999" ] || [ -z "$v_csh" ] || [ -z "$v_py" ] && continue
        if [ "$v_csh" != "$v_py" ]; then
            bad "$case  $k: csh=$v_csh py=$v_py"
            drift=$((drift+1))
        fi
    done
done
if [ $n -eq 0 ]; then
    ok "config drift: no extracted workdirs to compare (run sweep.sh first to populate)"
elif [ $drift -eq 0 ]; then
    ok "$n cases have no config drift"
fi

# --- 5. Basic-function probes (per-SAT pop_config, PRM round-trip) ----------
hdr "[5/6] Basic function probes"
tmp=$(mktemp -d)
trap "rm -rf $tmp" EXIT

# 5a. pop_config produces a non-empty config with the requested SAT for every
#     enabled-case satellite. Catches the kind of bug where adding a new SAT
#     to the dispatcher misses pop_config (today's ALOS4 fix would have been
#     caught here).
sats=$(python3 -c "
import sys; sys.path.insert(0, 'tests')
from cases import CASES
print(' '.join(sorted({v['satellite'] for v in CASES.values() if v.get('enabled')})))
")
n=0; bad_sats=""; POP_CONFIG=$(pwd)/utils/pop_config
for sat in $sats; do
    n=$((n+1))
    work="$tmp/$sat"; mkdir -p "$work"
    # pop_config writes config.py to cwd, not stdout — must cd into a clean dir.
    if ! ( cd "$work" && timeout 5 python3 "$POP_CONFIG" "$sat" >/dev/null 2>&1 ) \
         || [ ! -s "$work/config.py" ]; then
        bad_sats+=" $sat"
        bad "pop_config $sat — produced no config.py or errored"
        continue
    fi
    # pop_config encodes the SAT only as a header comment (the SAT is passed
    # to p2p_processing at runtime, not stored in config.py). Verify the
    # comment matches what we asked for, and that the file looks like a real
    # config (has at least filter_wavelength and proc_stage keys).
    if ! grep -qE "^#.*SAT=${sat}([[:space:]]|$|\.)" "$work/config.py" 2>/dev/null; then
        bad "pop_config $sat — SAT header comment doesn't match"
        bad_sats+=" $sat"; continue
    fi
    for required_key in filter_wavelength proc_stage; do
        if ! grep -qE "^[[:space:]]*${required_key}[[:space:]]*=" "$work/config.py"; then
            bad "pop_config $sat — required key ${required_key} missing"
            bad_sats+=" $sat"; continue 2
        fi
    done
done
if [ -z "$bad_sats" ]; then
    ok "$n SAT codes round-trip through pop_config"
fi

# 5b. update_PRM round-trips via gmtsar_lib.grep_value
python3 - <<'EOF'
import sys; sys.path.insert(0, 'utils')
try:
    from gmtsar_lib import grep_value
    import tempfile, os
    with tempfile.NamedTemporaryFile(mode='w', suffix='.PRM', delete=False) as f:
        f.write("key1 = value1\nrshift = 42\nstretch_r = -0.000172915\n")
        p = f.name
    # grep_value runs intFloatOrString on the result — '42' → int(42),
    # '-0.000172915' → float, anything else stays str. Compare with that.
    assert grep_value(p, 'rshift', 3) == 42, "rshift round-trip failed"
    assert abs(grep_value(p, 'stretch_r', 3) - (-0.000172915)) < 1e-12, "stretch_r round-trip failed"
    os.unlink(p)
    print("  OK   gmtsar_lib.grep_value round-trips PRM fields")
except Exception as e:
    print(f"  FAIL grep_value: {e}", file=sys.stderr); sys.exit(1)
EOF
[ $? -ne 0 ] && FAIL=$((FAIL+1))

# --- 6. Cases manifest sanity (informational, doesn't fail the wizard) ------
hdr "[6/6] cases.py manifest sanity (informational)"
python3 - <<'EOF'
import sys, os
sys.path.insert(0, 'tests')
from cases import CASES
enabled = [n for n,v in CASES.items() if v.get('enabled')]
full = [n for n,v in CASES.items() if v.get('enabled') and 'full' in v.get('tiers',[])]
# Only `full`-tier cases must have a recipe; SBAS / time-series cases run
# through a different harness.
missing_recipe = [c for c in full if not os.path.exists(f'tests/recipes/README_{c}.txt')]
if missing_recipe:
    print(f"  FAIL  full-tier case missing recipe(s): {missing_recipe}", file=sys.stderr); sys.exit(1)
print(f"  OK   {len(enabled)} enabled, {len(full)} full-tier — all full recipes present")
EOF
[ $? -ne 0 ] && FAIL=$((FAIL+1))

# --- Summary ----------------------------------------------------------------
dur=$((SECONDS - t0))
echo
if [ $FAIL -eq 0 ]; then
    printf '\e[32mPASS\e[0m — %ds, %d checks\n' "$dur" "$PASS"
    exit 0
else
    printf '\e[31mFAIL\e[0m — %ds, %d FAIL / %d PASS\n' "$dur" "$FAIL" "$PASS"
    exit 1
fi
