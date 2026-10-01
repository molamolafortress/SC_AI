# OpenBW + BWAPI(OpenBW 포크) 헤드리스 셋업

Verified 2026-09-29 in a Linux container (Ubuntu 24.04, gcc 13.3, cmake 3.28, ninja, 4 cores) without MPQ game data.
Result: the fork builds headless with one trivial patch; `BWAPILauncher` starts and fails only at MPQ loading (expected).

Upstream commits used:

| repo | commit | date |
|---|---|---|
| https://github.com/OpenBW/openbw | `4b046d5f65302b10cb0a745f0fecd37ec85b20a8` | 2026-08-13 |
| https://github.com/OpenBW/bwapi | `48124ba8ed1b4d52b3dfd52acbaf34afb9a37fe2` | 2020-06-11 (BWAPI 4.2.0 API level) |

Both are cloned under `third_party/` (git-ignored): `third_party/openbw`, `third_party/openbw-bwapi`.

## 1. 사전 조건 (apt)

Headless build needs no SDL2 and no game data.

```
apt-get install -y --no-install-recommends \
    build-essential g++ cmake ninja-build git ca-certificates
# optional, only if you want the SDL window (OPENBW_ENABLE_UI=1 at cmake time):
apt-get install -y libsdl2-dev
```

Note: in this container `apt-get update` partially fails (a PPA is blocked by the proxy) but the toolchain was already present, so nothing had to be installed. The Dockerfile in `docker/Dockerfile.openbw` installs the list above.

## 2. 빌드 명령 (정확한 재현 절차)

```
cd /home/user/SC_AI
mkdir -p third_party && cd third_party
git clone --depth 1 https://github.com/OpenBW/openbw
git clone --depth 1 https://github.com/OpenBW/bwapi openbw-bwapi

# gcc 13 fix: <cstdint> missing in bwapi/include/BWAPI/Game.h (uint32_t not declared)
cd openbw-bwapi
git apply /home/user/SC_AI/body/patches/openbw/0001-bwapi-game-h-include-cstdint.patch

mkdir -p build && cd build
cmake .. -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DOPENBW_DIR=/home/user/SC_AI/third_party/openbw \
  -DOPENBW_ENABLE_UI=0
ninja -j4
```

Timing on 4 cores: about 1m40s wall for a clean build (bwgame.h is one huge template header compiled into `libOpenBWData.so`; that single TU dominates). Zero warnings with gcc 13.

`OPENBW_DIR` is a `find_path` for `bwgame.h`; it can also be given as the environment variable `OPENBW_DIR`. Passing `OPENBW_ENABLE_UI=1` adds `${OPENBW_DIR}/ui` as a subproject and requires SDL2 (`find_package(SDL2 REQUIRED)`).
`-DOPENBWAPI_BUILD_STATIC_LIBS=ON` builds `libBWAPI` / `libOpenBWData` as static archives instead of `.so`.

### 빌드 산출물

```
build/bin/BWAPILauncher        # the "StarCraft + BWAPI injector" equivalent (22 KB; all logic is in the libs)
build/lib/libOpenBWData.so     # OpenBW engine (bwgame.h) + BW::Game glue        (~1.9 MB)
build/lib/libBWAPI.so          # BWAPI GameImpl/Server, config, auto-menu, dlopen of the AI module
build/lib/libBWAPILIB.so       # BWAPI types (UnitType, Position, ...) - what a bot links against
build/lib/libBWAPIClient.a     # client-mode helper (shared-memory server; not used in our lane)
build/lib/ExampleAIModule.so   # sample AI module (no lib prefix, see CMakeLists)
build/lib/TestAIModule.so      # BWAPI's test module
```

`ldd bin/BWAPILauncher` resolves `libBWAPI.so`, `libOpenBWData.so`, `libBWAPILIB.so` through the build rpath, so running it from the build tree works without `make install`. If you `ninja install`, headers land in `<prefix>/include/BWAPI*`, libs in `<prefix>/lib`, launcher in `<prefix>/bin`.

## 3. 환경변수 표 (소스 grep 기준)

Two independent env-var families exist.

### 3a. BWAPI config overrides (`bwapi/BWAPI/Source/Config.cpp`)

Every `bwapi.ini` key can be overridden with `BWAPI_CONFIG_<SECTION>__<KEY>` (upper-case, double underscore). Env var wins over the ini file. Examples:

| env var | ini equivalent | notes |
|---|---|---|
| `BWAPI_CONFIG_INI` | (path to ini) | default `./bwapi-data/bwapi.ini`, relative to cwd |
| `BWAPI_CONFIG_AI__AI` | `[ai] ai` | path of the AI module `.so` (dlopen with RTLD_NOW); absolute path recommended |
| `BWAPI_CONFIG_AI__TOURNAMENT` | `[ai] tournament` | tournament module `.so` |
| `BWAPI_CONFIG_AUTO_MENU__AUTO_MENU` | `[auto_menu] auto_menu` | `SINGLE_PLAYER` or `LAN` (anything else/`OFF` = no auto menu = nothing happens) |
| `BWAPI_CONFIG_AUTO_MENU__MAP` | `[auto_menu] map` | map path relative to cwd; wildcards in filename allowed; `.rep` path = replay playback |
| `BWAPI_CONFIG_AUTO_MENU__RACE` | `[auto_menu] race` | `Terran|Protoss|Zerg|Random` |
| `BWAPI_CONFIG_AUTO_MENU__ENEMY_RACE` | `[auto_menu] enemy_race` | single player only |
| `BWAPI_CONFIG_AUTO_MENU__ENEMY_COUNT` | `[auto_menu] enemy_count` | single player only |
| `BWAPI_CONFIG_AUTO_MENU__GAME_TYPE` | `[auto_menu] game_type` | `MELEE` etc. |
| `BWAPI_CONFIG_AUTO_MENU__AUTO_RESTART` | `[auto_menu] auto_restart` | `ON` loops games forever; use `OFF` for one game |
| `BWAPI_CONFIG_AUTO_MENU__SAVE_REPLAY` | `[auto_menu] save_replay` | honored (`GameEvents.cpp` -> `bwgame.saveReplay`); supports `%MAP%`, `%BOTNAME6%`, `$Y$b$d` style tokens |
| `BWAPI_CONFIG_AUTO_MENU__CHARACTER_NAME` | `[auto_menu] character_name` | player name shown in game; `FIRST` -> "bwapi" |
| `BWAPI_CONFIG_AUTO_MENU__WAIT_FOR_MIN_PLAYERS` etc. | `wait_for_*` | read, but the OpenBW LAN start rule is simply "2 players present -> start" |
| `BWAPI_CONFIG_STARCRAFT__SPEED_OVERRIDE` | `[starcraft] speed_override` | read; prefer `OPENBW_GAME_SPEED` (below) |
| `BWAPI_CONFIG_STARCRAFT__SEED_OVERRIDE` | `[starcraft] seed_override` | read into `GameImpl::seedOverride` but never applied by the fork (grep shows no consumer). Do not rely on it. |

Not used on OpenBW: `[auto_menu] lan_mode`, `[window]`, `[config] shared_memory` (no real effect), `ai_dbg` (only when built `BUILD_DEBUG`).

### 3b. OpenBW engine variables (`bwapi/OpenBWData/BW/BWData.cpp`, `openbw/data_loading.h`)

| env var | default | semantics |
|---|---|---|
| `OPENBW_MPQ_PATH` | `.` (cwd) | directory containing `Patch_rt.mpq`, `BrooDat.mpq`, `StarDat.mpq`; trailing slash optional |
| `OPENBW_ENABLE_UI` | `1` | `0`/`OFF`/`NO`/`FALSE`/`N` (case-insensitive) disables the SDL window. Only matters when built with `-DOPENBW_ENABLE_UI=1`; a headless build has no UI code at all, but set `0` anyway for clarity |
| `OPENBW_GAME_SPEED` | (unset = game speed setting, 42 ms "fastest") | milliseconds per frame; `0` (or negative) = no throttling, run as fast as the CPU allows. This is the knob for headless evaluation |
| `OPENBW_LAN_MODE` | `LOCAL_AUTO` (Linux) / `TCP` (Windows) | `TCP`, `LOCAL`, `LOCAL_FD`, `LOCAL_AUTO`, `FILE`, `FD` (case-insensitive) |
| `OPENBW_TCP_LISTEN_HOSTNAME` / `OPENBW_TCP_LISTEN_PORT` | `0.0.0.0` / `6112` | TCP mode: bind address |
| `OPENBW_TCP_CONNECT_HOSTNAME` / `OPENBW_TCP_CONNECT_PORT` | `127.0.0.1` / `6112` | TCP mode: peer; no error if bind/connect fails |
| `OPENBW_LOCAL_PATH` | (required for `LOCAL`) | unix socket path; first process binds, second connects (retries 10x) |
| `OPENBW_LOCAL_AUTO_DIRECTORY` | `/tmp/openbw` | `LOCAL_AUTO`: each process binds `<dir>/<uid>.socket` and connects to every other socket there; stale sockets are unlinked |
| `OPENBW_LOCAL_FD` | (required for `LOCAL_FD`) | already-connected unix socket fd |
| `OPENBW_FILE_READ` / `OPENBW_FILE_WRITE` | (required for `FILE`) | FIFO paths; SIGPIPE ignored |
| `OPENBW_FD_READ` / `OPENBW_FD_WRITE` | (required for `FD`) | file descriptors |

Order of lookup: a value set programmatically via `Game::setOverrideEnvVar()` wins, then the process environment, then the default.

## 4. MPQ와 맵 배치

OpenBW reads exactly these three files (names are case-sensitive on Linux, see `data_files_directory()` in `openbw/data_loading.h`):

```
$OPENBW_MPQ_PATH/Patch_rt.mpq
$OPENBW_MPQ_PATH/BrooDat.mpq
$OPENBW_MPQ_PATH/StarDat.mpq
```

Copy them from a StarCraft: Brood War 1.16.1 install (or from `scbw_bwapi440.zip`, see design_v0.5 section 8.2). If your copies are lower-case (`patch_rt.mpq`), rename or symlink them. Keep them out of git (mount as a private volume in docker).

Recommended run directory layout (one per launcher instance):

```
run/
  Patch_rt.mpq BrooDat.mpq StarDat.mpq   # or set OPENBW_MPQ_PATH to a shared dir
  bwapi-data/bwapi.ini                   # or BWAPI_CONFIG_INI / env overrides
  bwapi-data/read/  bwapi-data/write/    # bot I/O (bots use relative paths from cwd)
  bwapi-data/AI/<bot>.so
  maps/(4)Fighting Spirit.scx            # map path is relative to cwd
  maps/replays/
```

## 5. 헤드리스 1게임: AI 모듈 두 개 대결

An AI module is a shared object exporting two C symbols (see `bwapi/ExampleAIModule/Source/Dll.cpp`):

```
extern "C" void gameInit(BWAPI::Game* game);      // sets BWAPI::BroodwarPtr
extern "C" BWAPI::AIModule* newAIModule();
```

Build it against `third_party/openbw-bwapi/bwapi/include` and link `libBWAPILIB.so` (`bwapi/ExampleAIModule/CMakeLists.txt` is the template; note `CMAKE_SHARED_LIBRARY_PREFIX ""`).

One `BWAPILauncher` process = one player. `Game::getInstanceNumber()` always returns 0 in the fork, so the comma-separated multi-instance syntax of `ai=` / `race=` is meaningless: always give a single `.so` per process. Two processes are synchronised through `OPENBW_LAN_MODE`.

```
# shared
export OPENBW_ENABLE_UI=0
export OPENBW_GAME_SPEED=0                 # as fast as possible
export OPENBW_MPQ_PATH=/data/mpq           # private volume with the 3 MPQs
export OPENBW_LAN_MODE=LOCAL
export OPENBW_LOCAL_PATH=/tmp/sc_game_1.socket   # must NOT exist beforehand
export BWAPI_CONFIG_AUTO_MENU__AUTO_MENU=LAN
export BWAPI_CONFIG_AUTO_MENU__MAP="maps/(4)Fighting Spirit.scx"   # identical on both sides
export BWAPI_CONFIG_AUTO_MENU__GAME_TYPE=MELEE
export BWAPI_CONFIG_AUTO_MENU__AUTO_RESTART=OFF

# player 1 (our bot), cwd = run/p1
( cd run/p1 && BWAPI_CONFIG_AI__AI=/bots/mcrave.so BWAPI_CONFIG_AUTO_MENU__RACE=Zerg \
  BWAPI_CONFIG_AUTO_MENU__CHARACTER_NAME=McRave \
  BWAPI_CONFIG_AUTO_MENU__SAVE_REPLAY=maps/replays/%MAP%_p1.rep \
  /path/to/build/bin/BWAPILauncher > p1.log 2>&1 ) &

# player 2 (opponent), cwd = run/p2
( cd run/p2 && BWAPI_CONFIG_AI__AI=/bots/zzzkbot.so BWAPI_CONFIG_AUTO_MENU__RACE=Zerg \
  BWAPI_CONFIG_AUTO_MENU__CHARACTER_NAME=ZZZKBot \
  /path/to/build/bin/BWAPILauncher > p2.log 2>&1 ) &
wait
```

Flow (from `AutoMenuManager::startGame` + `BWData.cpp`): each process loads the map given by `map`, calls `createMultiPlayerGame`, binds/connects the socket, and calls `startGame()` as soon as 2 player slots are filled. Both processes must use the same map file. With `LOCAL_AUTO` (default) you can omit `OPENBW_LOCAL_PATH`, but then any other launcher on the host that happens to be in `/tmp/openbw` will be matched; use `LOCAL` with an explicit path (or a per-game `OPENBW_LOCAL_AUTO_DIRECTORY`) for parallel evaluation.

Single-player smoke test (opponent does nothing, OpenBW has no built-in AI):

```
cd run/p1
OPENBW_ENABLE_UI=0 BWAPI_CONFIG_AUTO_MENU__AUTO_MENU=SINGLE_PLAYER \
BWAPI_CONFIG_AI__AI=$PWD/../../third_party/openbw-bwapi/build/lib/ExampleAIModule.so \
BWAPI_CONFIG_AUTO_MENU__MAP="maps/(4)Fighting Spirit.scx" \
BWAPI_CONFIG_AUTO_MENU__RACE=Zerg BWAPI_CONFIG_AUTO_MENU__ENEMY_RACE=Protoss \
BWAPI_CONFIG_AUTO_MENU__AUTO_RESTART=OFF ../../third_party/openbw-bwapi/build/bin/BWAPILauncher
```

## 6. 알려진 함정 (gotchas)

1. **gcc >= 13**: `bwapi/include/BWAPI/Game.h` uses `uint32_t` without `<cstdint>` -> `error: 'uint32_t' has not been declared`. Patch: `body/patches/openbw/0001-bwapi-game-h-include-cstdint.patch`. Bots including `BWAPI.h` get the fix for free after patching.
2. **Exit code is always 0**. `BWAPILauncher/Source/Main.cpp` ignores the lambda's return value; on error it prints `Error: ...` to stdout and exits 0. Without MPQs the exact output is:
   `Error: file_reader: failed to open ./Patch_rt.mpq for reading` (with `OPENBW_MPQ_PATH` set, the path is prefixed). Harness code must grep stdout, not check `$?`.
   Similarly, if the AI module fails to `dlopen`, the game prints `dlerror: ...` and `ERROR: Failed to load the AI Module`, then `No module loaded, exiting` and returns... 1 from the lambda, but 0 from the process.
3. **Case-sensitive MPQ names**: `Patch_rt.mpq`, `BrooDat.mpq`, `StarDat.mpq` exactly.
4. **`auto_restart = ON` (the example ini default) loops forever**; set `OFF` for one game per process.
5. **`seed_override` is not implemented** in the OpenBW fork (read but unused). Determinism must come from elsewhere (OpenBW itself is deterministic given identical inputs, but the initial seed is time-based).
6. **`OPENBW_GAME_SPEED`** unset means real-time 42 ms/frame (~24 fps) even headless; set `0` for evaluation runs.
7. **`getInstanceNumber()` is always 0** -> one bot per process; the `ai = a.so, b.so` form does not give two players.
8. `bwapi.ini` `[ai] ai` path and `map` path are relative to the process cwd, not to the ini file. Use absolute paths for `.so` files.
9. **BWAPI API level is 4.2.0**, not 4.4.0. Bots written for 4.4.0 (McRave etc.) need source patches (see design_v0.5 section 8.3).
10. Multiplayer is 1v1 only; more than two launcher processes on the same socket/dir will break. Real StarCraft clients cannot join.
11. `OPENBW_ENABLE_UI=1` at cmake time pulls SDL2 and starts a UI thread (`sacrificeThreadForUI`); the headless build compiles that helper as a plain call, so there is no window and no X11 dependency.
12. There is no console output at all during a normal game unless the bot prints (`Broodwar->sendText` / `printf`); `setPrintTextCallback` in Main.cpp forwards in-game text to stdout.

## 7. 파일 위치

- Clones: `third_party/openbw`, `third_party/openbw-bwapi` (git-ignored)
- Build tree: `third_party/openbw-bwapi/build` (`bin/BWAPILauncher`, `lib/*.so`)
- Patch: `body/patches/openbw/0001-bwapi-game-h-include-cstdint.patch`
- Container recipe: `docker/Dockerfile.openbw` (not yet built here: the docker daemon is not reachable in this container)


## 7. 검증 기록 (2026-10-01, 실제 게임 데이터로)

- 게임 데이터: `scbw_bwapi440.zip`을 `third_party/game-data/`에 풀었다. zip 안의 파일명은 `STARDAT.MPQ`, `BROODAT.MPQ`, `patch_rt.mpq`이고 OpenBW는 `StarDat.mpq`, `BrooDat.mpq`, `Patch_rt.mpq`를 찾으므로 **심볼릭 링크 3개**를 만든다 (`ln -s STARDAT.MPQ StarDat.mpq` 등). 맵은 `maps/BroodWar/{sscai,aiide,cog,iccup}/`에 84개.
- `Game::getRandomSeed()`는 이 포크에서 `ReplayHead_gameSeed_randSeed` 예외를 던진다. 봇 코드에서 호출하지 말 것.
- 단일 프로세스 싱글플레이(`AUTO_MENU=SINGLE_PLAYER`)는 상대가 가만히 있으므로 McRave가 4:47에 이긴다. 파이프라인 확인용.
- 2프로세스 LAN(`OPENBW_LAN_MODE=LOCAL` + 소켓 경로)은 `tools/run_game_openbw.sh`로 검증했다. 플레이어마다 작업 디렉터리(`p1/`, `p2/`)에 `bwapi-data/write`, `bwapi-data/read`, `maps` 링크가 있어야 한다. 상대 프로세스에는 `SIDECAR_*` 변수를 넘기지 않는다(넘기면 상대 게임도 사이드카에 집계된다).
- 속도: 속도 0에서 약 5게임분(6,700프레임)이 20초 안팎. `python -m eval.run_eval --runner openbw --games 2 --parallel 2`가 43초.
