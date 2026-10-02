#!/usr/bin/env bash
# One headless 1v1 on real StarCraft 1.16.1 + BWAPI 4.4.0 under Wine (the "Pluto lane", docs/setup_pluto_lane.md):
# two bwheadless.exe processes in one Wine prefix, Local-PC (shared memory) networking, no graphics.
# Usage: tools/run_game_wine.sh <our.dll> <opponent.dll|opponent AI dir> <map rel. to install> [our_race] [enemy_race] [run_dir] [game_tag]
#   <opponent AI dir>: a directory whose contents are copied into the opponent's bwapi-data/AI/ (e.g. third_party/pluto, which
#   holds pluto.dll + pluto/{pluto_infer.exe,pluto_weights.bin}); the first *.dll in it is the module.
# Env: BW_WIN (StarCraft 1.16.1 install template: StarCraft.exe, *.mpq, maps/, bwapi-data/BWAPI.dll, bwheadless.exe; default third_party/bw_win/template),
#      WINEPREFIX (default third_party/wineprefix), TIMEOUT (default 1800 s wall), SPEED (bwapi.ini speed_override, default 0 = fastest),
#      OUR_SIDE p1|p2 (default p1; p1 hosts), SIDECAR_HOST/PORT and SC_AI_* passed to our side only (see tools/run_game_openbw.sh).
set -euo pipefail
OUR=$1; OPP=$2; MAP=$3; RACE=${4:-Zerg}; ERACE=${5:-Random}
RUN=${6:-logs/wine/$(date +%Y%m%d_%H%M%S)_$$}; TAG=${7:-game}
BW_WIN=${BW_WIN:-$(pwd)/third_party/bw_win/template}
export WINEPREFIX=${WINEPREFIX:-$(pwd)/third_party/wineprefix} WINEDEBUG=${WINEDEBUG:--all} WINEDLLOVERRIDES="mscoree,mshtml="
TIMEOUT=${TIMEOUT:-1800}; SPEED=${SPEED:-0}
for f in StarCraft.exe StarDat.mpq BrooDat.mpq Patch_rt.mpq bwheadless.exe bwapi-data/BWAPI.dll; do [ -e "$BW_WIN/$f" ] || { echo "missing $BW_WIN/$f"; exit 2; }; done
[ -d "$WINEPREFIX/drive_c" ] || { echo "no Wine prefix at $WINEPREFIX (xvfb-run wineboot --init)"; exit 2; }
mkdir -p "$RUN"; RUN=$(cd "$RUN" && pwd)
OUR_SIDE=${OUR_SIDE:-p1}; OPP_SIDE=$([ "$OUR_SIDE" = p1 ] && echo p2 || echo p1)

# Per-player install: symlink the read-only game files, private bwapi-data/ (BWAPI reads <installpath>/bwapi-data/bwapi.ini).
mk_install() {  # dir
  local d=$1; mkdir -p "$d/bwapi-data/AI" "$d/bwapi-data/read" "$d/bwapi-data/write" "$d/maps" "$d/Errors"
  for f in "$BW_WIN"/*; do case "$(basename "$f")" in bwapi-data|maps) ;; *) ln -sfn "$f" "$d/$(basename "$f")";; esac; done
  ln -sfn "$BW_WIN/maps/BroodWar" "$d/maps/BroodWar"
  cp "$BW_WIN/bwapi-data/BWAPI.dll" "$d/bwapi-data/"; [ -d "$BW_WIN/bwapi-data/data" ] && cp -r "$BW_WIN/bwapi-data/data" "$d/bwapi-data/" || true
}
# Module into <dir>/bwapi-data/AI; echoes the module path relative to the install.
place_module() {  # dir, dll-or-dir
  local d=$1 src=$2 dll
  if [ -d "$src" ]; then cp -r "$src"/. "$d/bwapi-data/AI/"; dll=$(cd "$d/bwapi-data/AI" && ls *.dll | head -1)
  else cp "$src" "$d/bwapi-data/AI/"; dll=$(basename "$src"); fi
  echo "bwapi-data/AI/$dll"
}
write_ini() {  # dir, module, race, name
  local d=$1 mod=$2 race=$3 name=$4
  cat > "$d/bwapi-data/bwapi.ini" <<INI
[ai]
ai = $mod
ai_dbg = NULL
tournament =
[auto_menu]
auto_menu = LAN
pause_dbg = OFF
lan_mode = Local PC
auto_restart = OFF
map = $MAP
game = $TAG
mapiteration = RANDOM
race = $race
enemy_count = 1
enemy_race = Random
game_type = MELEE
save_replay = bwapi-data/write/game.rep
wait_for_min_players = 2
wait_for_max_players = 2
wait_for_time = 120000
[config]
holiday = OFF
console_attach_on_startup = FALSE
console_alloc_on_startup = FALSE
console_attach_auto = TRUE
console_alloc_auto = TRUE
[window]
windowed = OFF
[starcraft]
sound = OFF
screenshots = gif
speed_override = $SPEED
seed_override =
drop_players = ON
INI
}
mk_install "$RUN/p1"; mk_install "$RUN/p2"
OUR_MOD=$(place_module "$RUN/$OUR_SIDE" "$OUR"); OPP_MOD=$(place_module "$RUN/$OPP_SIDE" "$OPP")
if [ "$OUR_SIDE" = p1 ]; then write_ini "$RUN/p1" "$OUR_MOD" "$RACE" SC_AI; write_ini "$RUN/p2" "$OPP_MOD" "$ERACE" Opponent; A_RACE=$RACE; A_NAME=SC_AI; B_RACE=$ERACE; B_NAME=Opponent
else write_ini "$RUN/p1" "$OPP_MOD" "$ERACE" Opponent; write_ini "$RUN/p2" "$OUR_MOD" "$RACE" SC_AI; A_RACE=$ERACE; A_NAME=Opponent; B_RACE=$RACE; B_NAME=SC_AI; fi

ours=(${SIDECAR_HOST:+SIDECAR_HOST=$SIDECAR_HOST} ${SIDECAR_PORT:+SIDECAR_PORT=$SIDECAR_PORT} ${SC_AI_MAX_FRAMES:+SC_AI_MAX_FRAMES=$SC_AI_MAX_FRAMES} ${SC_AI_LOCKSTEP:+SC_AI_LOCKSTEP=$SC_AI_LOCKSTEP}
      ${SC_AI_DUMP_STATE:+SC_AI_DUMP_STATE=$SC_AI_DUMP_STATE} "SC_AI_UNIT_SNAPSHOTS=bwapi-data/write/units.jsonl")
theirs=(-u SIDECAR_HOST -u SIDECAR_PORT -u SC_AI_MAX_FRAMES -u SC_AI_LOCKSTEP -u SC_AI_DUMP_STATE -u SC_AI_UNIT_SNAPSHOTS)
[ "$OUR_SIDE" = p1 ] && { A_ENV=("${ours[@]}"); B_ENV=("${theirs[@]}"); } || { A_ENV=("${theirs[@]}"); B_ENV=("${ours[@]}"); }

launch() {  # dir, env-array-name, host|join, race, name
  local d=$1; local -n e=$2; local mode=$3 race=$4 name=$5; local extra=()
  [ "$mode" = host ] && extra=(-h -m "$d/$MAP") || extra=(-j)
  ( cd "$d" && env "${e[@]}" timeout "$TIMEOUT" wine "$d/bwheadless.exe" -e "$d/StarCraft.exe" --installpath "$d" -l "$d/bwapi-data/BWAPI.dll" \
      --localpc -n "$name" -g "$TAG" -r "$race" "${extra[@]}" > "$d/launcher.log" 2>&1 )
}
launch "$RUN/p1" A_ENV host "$A_RACE" "$A_NAME" & P1=$!
sleep 4
launch "$RUN/p2" B_ENV join "$B_RACE" "$B_NAME" & P2=$!
wait $P1 || true; wait $P2 || true
# A finished game leaves a replay on the host side; the authoritative result is the sidecar's `result` record (our side)
# and bwapi-data/write/pluto_bandit_*.txt (Pluto's own end record) on the opponent side.
if ls "$RUN"/p?/bwapi-data/write/game.rep >/dev/null 2>&1; then echo "finished run_dir=$RUN"; else echo "unfinished run_dir=$RUN"; tail -n 3 "$RUN"/p?/launcher.log; exit 1; fi
