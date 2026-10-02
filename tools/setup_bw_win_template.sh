#!/usr/bin/env bash
# Build third_party/bw_win/template, the StarCraft 1.16.1 install that tools/run_game_wine.sh clones per game:
# symlinks to third_party/game-data (exe, MPQs, snp/dll helpers, characters, maps), a private bwapi-data/ with
# BWAPI 4.4.0's BWAPI.dll, and bwheadless.exe (tscmoo, from the sc-docker checkout or any copy you trust).
# Usage: tools/setup_bw_win_template.sh <path/to/bwheadless.exe> [game-data dir] [template dir]
set -euo pipefail
BWH=${1:?bwheadless.exe path}; GD=${2:-third_party/game-data}; T=${3:-third_party/bw_win/template}
[ -f "$BWH" ] || { echo "no such file: $BWH"; exit 2; }
for f in StarCraft.exe StarDat.mpq BrooDat.mpq Patch_rt.mpq bwapi-data/BWAPI.dll maps/BroodWar; do [ -e "$GD/$f" ] || { echo "missing $GD/$f"; exit 2; }; done
GD=$(cd "$GD" && pwd); mkdir -p "$T/bwapi-data" "$T/maps"; T=$(cd "$T" && pwd)
for f in BROODAT.MPQ BrooDat.mpq Patch_rt.mpq STARDAT.MPQ StarCraft.mpq StarDat.mpq patch_rt.mpq StarCraft.exe storm.dll standard.snp SNP_DirectIP.snp Smackw32.dll Local.dll characters; do
  [ -e "$GD/$f" ] && ln -sfn "$GD/$f" "$T/$f"; done
ln -sfn "$GD/maps/BroodWar" "$T/maps/BroodWar"
cp "$GD/bwapi-data/BWAPI.dll" "$T/bwapi-data/"; [ -d "$GD/bwapi-data/data" ] && cp -r "$GD/bwapi-data/data" "$T/bwapi-data/" || true
cp "$BWH" "$T/bwheadless.exe"
ls -la "$T"
