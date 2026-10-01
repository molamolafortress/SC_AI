#!/usr/bin/env bash
# Apply body/patches/zzzkbot/NNNN-*.patch to third_party/zzzkbot, in order, idempotently.
# A patch that is already applied (reverse-check passes) is skipped; a patch that neither
# applies nor reverse-applies aborts with the failing name. Usage:
#   body/zzzkbot_port/apply_patches.sh            # apply
#   body/zzzkbot_port/apply_patches.sh --reverse  # undo (reverse order)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
ZZZKBOT="${ZZZKBOT_ROOT:-$ROOT/third_party/zzzkbot}"
PATCHES="$ROOT/body/patches/zzzkbot"
EXPECTED_COMMIT=7183e37b6b416ea53c1040c83e639a3a3c395eed

[ -d "$ZZZKBOT/ZZZKBot/Source" ] || { echo "ZZZKBot not found at $ZZZKBOT (clone it first, see README.md)" >&2; exit 1; }
head=$(git -C "$ZZZKBOT" rev-parse HEAD)
[ "$head" = "$EXPECTED_COMMIT" ] || echo "warning: ZZZKBot HEAD is $head, patches were made against $EXPECTED_COMMIT" >&2

reverse=0; [ "${1:-}" = "--reverse" ] && reverse=1
mapfile -t list < <(ls "$PATCHES"/[0-9][0-9][0-9][0-9]-*.patch | sort)
[ $reverse = 1 ] && mapfile -t list < <(printf '%s\n' "${list[@]}" | sort -r)

for p in "${list[@]}"; do
    name=$(basename "$p")
    if [ $reverse = 0 ]; then
        if git -C "$ZZZKBOT" apply --check --reverse "$p" 2>/dev/null; then
            echo "skip  $name (already applied)"
        elif git -C "$ZZZKBOT" apply --check "$p"; then
            git -C "$ZZZKBOT" apply "$p" && echo "apply $name"
        else
            echo "FAIL  $name does not apply cleanly to $ZZZKBOT" >&2; exit 1
        fi
    else
        if git -C "$ZZZKBOT" apply --check --reverse "$p" 2>/dev/null; then
            git -C "$ZZZKBOT" apply --reverse "$p" && echo "undo  $name"
        else
            echo "skip  $name (not applied)"
        fi
    fi
done
