#!/usr/bin/env bash
# Apply body/patches/ualbertabot/NNNN-*.patch to third_party/ualbertabot, in order, idempotently.
# A patch that is already applied (reverse-check passes) is skipped; a patch that neither
# applies nor reverse-applies aborts with the failing name. Usage:
#   body/ualbertabot_port/apply_patches.sh            # apply
#   body/ualbertabot_port/apply_patches.sh --reverse  # undo (reverse order)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
UAB="${UAB_ROOT:-$ROOT/third_party/ualbertabot}"
PATCHES="$ROOT/body/patches/ualbertabot"
EXPECTED_COMMIT=558899d8793456f4a6ec4196efbb5235552e24db

[ -d "$UAB/UAlbertaBot/Source" ] || { echo "UAlbertaBot not found at $UAB (clone it first, see README.md)" >&2; exit 1; }
head=$(git -C "$UAB" rev-parse HEAD)
[ "$head" = "$EXPECTED_COMMIT" ] || echo "warning: UAlbertaBot HEAD is $head, patches were made against $EXPECTED_COMMIT" >&2

reverse=0; [ "${1:-}" = "--reverse" ] && reverse=1
mapfile -t list < <(ls "$PATCHES"/[0-9][0-9][0-9][0-9]-*.patch | sort)
[ $reverse = 1 ] && mapfile -t list < <(printf '%s\n' "${list[@]}" | sort -r)

for p in "${list[@]}"; do
    name=$(basename "$p")
    if [ $reverse = 0 ]; then
        if git -C "$UAB" apply --check --reverse "$p" 2>/dev/null; then
            echo "skip  $name (already applied)"
        elif git -C "$UAB" apply --check "$p"; then
            git -C "$UAB" apply "$p" && echo "apply $name"
        else
            echo "FAIL  $name does not apply cleanly to $UAB" >&2; exit 1
        fi
    else
        if git -C "$UAB" apply --check --reverse "$p" 2>/dev/null; then
            git -C "$UAB" apply --reverse "$p" && echo "undo  $name"
        else
            echo "skip  $name (not applied)"
        fi
    fi
done
