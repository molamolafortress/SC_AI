#!/usr/bin/env bash
# Run one headless 1v1 on OpenBW: our AI module vs an opponent AI module, with the sidecar.
# Usage: tools/run_game_openbw.sh <our.so> <opponent.so> <map path relative to MPQ dir> [our_race] [enemy_race]
# Requires: OPENBW_MPQ_PATH pointing at a dir with StarDat.mpq BrooDat.mpq Patch_rt.mpq and the maps;
#           BWAPILauncher built per docs/setup_openbw.md (LAUNCHER env or default path below).
set -euo pipefail
OUR=$1; OPP=$2; MAP=$3; RACE=${4:-Zerg}; ERACE=${5:-Terran}
LAUNCHER=${LAUNCHER:-third_party/openbw-bwapi/build/bin/BWAPILauncher}
: "${OPENBW_MPQ_PATH:?set OPENBW_MPQ_PATH}"
SOCK=$(mktemp -u /tmp/openbw_game_XXXX.sock)
OUT=${OUT:-logs/openbw}; mkdir -p "$OUT"
common=(env OPENBW_ENABLE_UI=0 OPENBW_GAME_SPEED=${OPENBW_GAME_SPEED:-0} OPENBW_LAN_MODE=LOCAL OPENBW_LOCAL_PATH="$SOCK"
        BWAPI_CONFIG_AUTO_MENU__AUTO_MENU=LAN BWAPI_CONFIG_AUTO_MENU__MAP="$MAP" BWAPI_CONFIG_AUTO_MENU__GAME_TYPE=MELEE
        BWAPI_CONFIG_AUTO_MENU__SAVE_REPLAY="$OUT/%MAP%_%BOTNAME%.rep")
"${common[@]}" BWAPI_CONFIG_AI__AI="$OUR" BWAPI_CONFIG_AUTO_MENU__RACE="$RACE" BWAPI_CONFIG_AUTO_MENU__CHARACTER_NAME=SC_AI \
    "$LAUNCHER" > "$OUT/p1.log" 2>&1 &
P1=$!
sleep 1
"${common[@]}" BWAPI_CONFIG_AI__AI="$OPP" BWAPI_CONFIG_AUTO_MENU__RACE="$ERACE" BWAPI_CONFIG_AUTO_MENU__CHARACTER_NAME=Opponent \
    "$LAUNCHER" > "$OUT/p2.log" 2>&1 &
P2=$!
wait $P1 $P2 || true
# BWAPILauncher exits 0 even on data errors: the harness must read the logs (and the sidecar's /game/end record).
grep -h -i -E "error|winner|game ended|left the game" "$OUT/p1.log" "$OUT/p2.log" || true
