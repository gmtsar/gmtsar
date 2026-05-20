#!/usr/bin/env bash
# swap.sh — toggle the production-path bin symlinks between the legacy
# utils/ versions and the PyGMT utils_pygmt/ versions.
#
# Usage:
#   ./swap.sh --on        switch all available _pygmt versions into bin/
#   ./swap.sh --off       restore the legacy utils/ versions
#   ./swap.sh --status    show which path each bin entry currently points to
#
# Non-destructive: the legacy targets stay as `bin/<name>.orig` symlinks
# while the swap is on, and are restored verbatim by --off.

set -u
BIN="/home/staff/dliu/gmtsar/bin"
LEGACY_UTILS="/home/staff/dliu/gmtsar/gmtsar/python/utils"
PYGMT_UTILS="/home/staff/dliu/gmtsar/gmtsar/python/utils_pygmt"

mode=${1:-}

declare -a names
for f in "$PYGMT_UTILS"/*_pygmt; do
    [ -f "$f" ] || continue
    base=$(basename "$f")
    name=${base%_pygmt}
    names+=("$name")
done

case "$mode" in
--on)
    n=0
    for name in "${names[@]}"; do
        legacy="$BIN/$name"
        pygmt="$BIN/${name}_pygmt"
        [ -L "$legacy" ] || continue
        [ -L "$pygmt" ] || continue
        # Save current target as <name>.orig once
        if [ ! -L "$BIN/$name.orig" ]; then
            cp -P "$legacy" "$BIN/$name.orig"
        fi
        ln -sf "$PYGMT_UTILS/${name}_pygmt" "$legacy"
        n=$((n+1))
    done
    echo "swap.sh --on: $n utilities now point to utils_pygmt/"
    ;;
--off)
    n=0
    for name in "${names[@]}"; do
        orig="$BIN/$name.orig"
        if [ -L "$orig" ]; then
            target=$(readlink "$orig")
            ln -sf "$target" "$BIN/$name"
            rm "$orig"
            n=$((n+1))
        fi
    done
    echo "swap.sh --off: $n utilities restored to utils/"
    ;;
--status)
    for name in "${names[@]}"; do
        target=$(readlink "$BIN/$name" 2>/dev/null || echo "[missing]")
        case "$target" in
            *utils_pygmt*) printf '  %-30s PYGMT\n' "$name" ;;
            *utils/*)      printf '  %-30s legacy\n' "$name" ;;
            *)             printf '  %-30s %s\n' "$name" "$target" ;;
        esac
    done
    ;;
*)
    echo "Usage: $0 --on | --off | --status"
    exit 1
    ;;
esac
