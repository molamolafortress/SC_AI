#!/usr/bin/env bash
# Apply body/patches/mcrave/NNNN-*.patch to third_party/mcrave, in order, idempotently.
# A patch that is already applied (reverse-check passes) is skipped; a patch that neither
# applies nor reverse-applies aborts with the failing name. Usage:
#   body/mcrave_port/apply_patches.sh            # apply
#   body/mcrave_port/apply_patches.sh --reverse  # undo (reverse order)
# Patches: 0001-0005 Linux port, 0006 Sidecar.{h,cpp} (intent-to-add diff), 0007 hook call sites,
# 0008 economy lever (drone_target call sites in ZergBuildOrder.cpp composition(), on top of 0007).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
MCRAVE="${MCRAVE_ROOT:-$ROOT/third_party/mcrave}"
PATCHES="$ROOT/body/patches/mcrave"
EXPECTED_COMMIT=7d1719a22d8b896f957abae50e2ea5efff974fe2

[ -d "$MCRAVE/Source" ] || { echo "McRave not found at $MCRAVE (clone it first, see README.md)" >&2; exit 1; }
head=$(git -C "$MCRAVE" rev-parse HEAD)
[ "$head" = "$EXPECTED_COMMIT" ] || echo "warning: McRave HEAD is $head, patches were made against $EXPECTED_COMMIT" >&2

reverse=0; [ "${1:-}" = "--reverse" ] && reverse=1
mapfile -t list < <(ls "$PATCHES"/[0-9][0-9][0-9][0-9]-*.patch | sort)
[ $reverse = 1 ] && mapfile -t list < <(printf '%s\n' "${list[@]}" | sort -r)

for p in "${list[@]}"; do
    name=$(basename "$p")
    if [ $reverse = 0 ]; then
        if git -C "$MCRAVE" apply --check --reverse "$p" 2>/dev/null; then
            echo "skip  $name (already applied)"
        elif git -C "$MCRAVE" apply --check "$p"; then
            git -C "$MCRAVE" apply "$p" && echo "apply $name"
        else
            echo "FAIL  $name does not apply cleanly to $MCRAVE" >&2; exit 1
        fi
    else
        if git -C "$MCRAVE" apply --check --reverse "$p" 2>/dev/null; then
            git -C "$MCRAVE" apply --reverse "$p" && echo "undo  $name"
        else
            echo "skip  $name (not applied)"
        fi
    fi
done
