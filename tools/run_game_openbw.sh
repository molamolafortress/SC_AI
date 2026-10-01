#!/usr/bin/env bash
# One headless 1v1 on OpenBW (verified 2026-10-01): our AI module vs an opponent AI module.
# Usage: tools/run_game_openbw.sh <our.so> <opponent.so> <map rel. to game-data> [our_race] [enemy_race] [run_dir] [game_tag]
# Env: GAME_DATA (dir with StarDat.mpq BrooDat.mpq Patch_rt.mpq + maps/), LAUNCHER, SIDECAR_HOST/PORT (passed to player 1 only),
#      OPENBW_GAME_SPEED (default 0 = max), TIMEOUT (default 900 s),
#      OPP_DATA_DIR (optional: a directory whose contents are copied into p2/bwapi-data/ before launch,
#      e.g. body/ualbertabot_port/bwapi-data with AI/UAlbertaBot_Config.txt; bots read it relative to their cwd).
set -euo pipefail
OUR=$1; OPP=$2; MAP=$3; RACE=${4:-Zerg}; ERACE=${5:-Terran}
RUN=${6:-logs/openbw/$(date +%Y%m%d_%H%M%S)_$$}; TAG=${7:-game}
GAME_DATA=${GAME_DATA:-$(pwd)/third_party/game-data}
LAUNCHER=${LAUNCHER:-$(pwd)/third_party/openbw-bwapi/build/bin/BWAPILauncher}
TIMEOUT=${TIMEOUT:-900}
for f in StarDat.mpq BrooDat.mpq Patch_rt.mpq; do [ -e "$GAME_DATA/$f" ] || { echo "missing $GAME_DATA/$f (case-sensitive; symlink from the zip's uppercase names)"; exit 2; }; done
mkdir -p "$RUN"; RUN=$(cd "$RUN" && pwd)
SOCK=$(mktemp -u /tmp/openbw_${TAG}_XXXX.sock)
for p in p1 p2; do mkdir -p "$RUN/$p/bwapi-data/write" "$RUN/$p/bwapi-data/read"; ln -sfn "$GAME_DATA/maps" "$RUN/$p/maps"; done
if [ -n "${OPP_DATA_DIR:-}" ]; then [ -d "$OPP_DATA_DIR" ] || { echo "OPP_DATA_DIR=$OPP_DATA_DIR is not a directory"; exit 2; }; cp -r "$OPP_DATA_DIR"/. "$RUN/p2/bwapi-data/"; fi
common=(OPENBW_ENABLE_UI=0 "OPENBW_GAME_SPEED=${OPENBW_GAME_SPEED:-0}" "OPENBW_MPQ_PATH=$GAME_DATA" OPENBW_LAN_MODE=LOCAL "OPENBW_LOCAL_PATH=$SOCK"
        BWAPI_CONFIG_AUTO_MENU__AUTO_MENU=LAN "BWAPI_CONFIG_AUTO_MENU__MAP=$MAP" BWAPI_CONFIG_AUTO_MENU__GAME_TYPE=MELEE BWAPI_CONFIG_AUTO_MENU__AUTO_RESTART=OFF)
( cd "$RUN/p1" && env "${common[@]}" ${SIDECAR_HOST:+SIDECAR_HOST=$SIDECAR_HOST} ${SIDECAR_PORT:+SIDECAR_PORT=$SIDECAR_PORT} \
    "BWAPI_CONFIG_AI__AI=$OUR" "BWAPI_CONFIG_AUTO_MENU__RACE=$RACE" BWAPI_CONFIG_AUTO_MENU__CHARACTER_NAME=SC_AI \
    BWAPI_CONFIG_AUTO_MENU__SAVE_REPLAY=bwapi-data/write/game.rep timeout "$TIMEOUT" "$LAUNCHER" > p1.log 2>&1 ) &
P1=$!
sleep 2
( cd "$RUN/p2" && env -u SIDECAR_HOST -u SIDECAR_PORT "${common[@]}" "BWAPI_CONFIG_AI__AI=$OPP" "BWAPI_CONFIG_AUTO_MENU__RACE=$ERACE" \
    BWAPI_CONFIG_AUTO_MENU__CHARACTER_NAME=Opponent timeout "$TIMEOUT" "$LAUNCHER" > p2.log 2>&1 ) &
P2=$!
wait $P1 || true; wait $P2 || true
rm -f "$SOCK"
# BWAPILauncher exits 0 even on errors: report from logs. The authoritative result is the sidecar's `result` record.
if grep -q "ggwp" "$RUN/p1/p1.log"; then echo "finished run_dir=$RUN"; else echo "unfinished run_dir=$RUN"; grep -h -i "error" "$RUN/p1/p1.log" "$RUN/p2/p2.log" | head -3; exit 1; fi
