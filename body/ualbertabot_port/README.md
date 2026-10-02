# UAlbertaBot Linux/OpenBW port

Builds `UAlbertaBot.so` (David Churchill's UAlbertaBot, MIT, https://github.com/davechurchill/ualbertabot,
master @ `558899d`) as an AI module that OpenBW's `BWAPILauncher` can `dlopen`. Same pattern as
`body/mcrave_port`. Status (2026-10-01):

- **Builds and links cleanly** (gcc 13.3 / cmake 3.28 / ninja, C++17, `-O2 -fPIC`, `-Wl,--no-undefined`)
  against the OpenBW fork's BWAPI 4.2 headers. 114 TUs (UAlbertaBot 42 + BOSS 34 + SparCraft 37 +
  `Dll_linux.cpp`), ~70 s clean build on 4 cores, 1.5 MB `.so`.
- **No BWTA/BWEM dependency**: current master uses its own `BaseLocationManager`/`DistanceMap`/`MapTools`
  (`DrawBWTAInfo` in the config is a leftover flag). No boost either; SparCraft's/BOSS's GUI, experiment
  and `*_main` files (SDL/OpenGL/CImg) are simply not compiled, exactly as the library vcxprojs do.
- Upstream master is a **BWAPI client executable** (`Source/main.cpp` pumps `BWAPIClient` events into
  `UAlbertaBotModule`, which is not a `BWAPI::AIModule`). `Dll_linux.cpp` wraps it in an `AIModule`
  adapter and runs `SparCraft::init()`/`BOSS::init()` once in `newAIModule()`, as `main()` did.
- Patches: 2 (`body/patches/ualbertabot/`, 15 files, 24+/17-).

## Build

```
cd /home/user/SC_AI
git clone https://github.com/davechurchill/ualbertabot third_party/ualbertabot
git -C third_party/ualbertabot checkout 558899d8793456f4a6ec4196efbb5235552e24db
body/ualbertabot_port/apply_patches.sh          # idempotent; --reverse undoes
cmake -S body/ualbertabot_port -B build/ualbertabot -G Ninja -DCMAKE_BUILD_TYPE=Release
ninja -C build/ualbertabot -j4
# -> build/ualbertabot/UAlbertaBot.so
nm -D build/ualbertabot/UAlbertaBot.so | grep -E " T (gameInit|newAIModule)$"
```

CMake cache variables: `UAB_ROOT`, `BWAPI_ROOT`, `BWAPI_INCLUDE_DIR`, `BWAPI_LIB_DIR`, `SC_AI_ROOT`.
Source lists are the three vcxprojs' lists written out explicitly (`UAlbertaBot.vcxproj` minus
`main.cpp`; `BOSS.vcxproj`; `SparCraft.vcxproj`), not globs: `Source/UnitInfoManager.cpp` is a stale
file outside the vcxproj that includes a non-existent `Util.h`. Defines: `NOMINMAX NDEBUG
EXAMPLEAIMODULE_EXPORTS BOSS_USE_BWAPI_GAMESTATE` (see patch 0001).

## Patches (`body/patches/ualbertabot/`)

### 0001-linux-port.patch (14 files, compiler portability only)
| file | change | reason |
|---|---|---|
| `UAlbertaBot/Source/Profiler.hpp` | `#include <thread>` | `std::this_thread` used without the header |
| `CombatSimulation.h`, `ParseUtils.cpp` | `..\..\SparCraft\source\X.h`, `rapidjson\document.h` -> forward slashes | backslash include paths |
| `UnitUtil.cpp` | `std::sqrtf` -> `std::sqrt` (float overload) | libstdc++ has no `std::sqrtf` |
| `UnitData.cpp`, `SquadData.cpp`, `BuildingManager.cpp`, `BuildingData.cpp` | `auto & it = x.find(..)` -> `auto it` | non-const lvalue ref bound to a temporary (MSVC extension) |
| `ProductionManager.cpp` | `BuildOrder & bo = getBuildOrder()` -> by value | same (`getBuildOrder()` returns by value) |
| `ParseUtils.cpp` | `addStrategy(name, Strategy(..))` -> named local | `addStrategy` takes `Strategy &` |
| `UABAssert.cpp`, `Logger.cpp` | `vsnprintf_s` -> `vsnprintf`; `localtime_s` -> `#ifdef _WIN32` / `localtime_r` | MSVC-only CRT functions |
| `BOSS/source/GameState.{h,cpp}` | `#ifdef _MSC_VER` -> `#if defined(_MSC_VER) \|\| defined(BOSS_USE_BWAPI_GAMESTATE)` | the `GameState(BWAPI::GameWrapper&, Player, ..)` ctor that `BOSSManager.cpp` needs was compiled out on non-MSVC (upstream comment: "we won't be using this on linux", because upstream's Linux target was the emscripten/BOSS-only build) |
| `BOSS/source/BOSSAssert.cpp` | `#include <cstring>` | `strlen` |

### 0002-config-under-bwapi-data.patch (1 file, behaviour: config path)
`UAlbertaBot/Source/Config.cpp`: `ConfigFileLocation = "UAlbertaBot_Config.txt"` ->
`"bwapi-data/AI/UAlbertaBot_Config.txt"` (the SSCAIT/AIIDE convention; upstream expects the file next
to StarCraft.exe). This keeps every opponent file under `p2/bwapi-data/` so `OPP_DATA_DIR` covers it.

## Config / data files (relative to the launcher's cwd, i.e. `<run_dir>/p2/`)

- `bwapi-data/AI/UAlbertaBot_Config.txt` **required** (JSON despite the `.txt`): without it the bot
  draws "config not found" on screen and does nothing. Shipped copy: `body/ualbertabot_port/bwapi-data/AI/UAlbertaBot_Config.txt`
  (verbatim upstream `UAlbertaBot/bin/UAlbertaBot_Config.txt`). The `Strategy` section picks the
  opening by the race BWAPI assigns (`Protoss` -> `Protoss_ZealotRush`, `Terran` -> `Terran_MarineRush`,
  `Zerg` -> `Zerg_ZerglingRush`), so the same file works for any `<opp_race>` argument.
- `bwapi-data/read/`, `bwapi-data/write/`: strategy win/loss records (`UseStrategyIO: true`); created
  by the run script, empty each game.
- `bwapi-data/AI/UAlbertaBot_ErrorLog.txt`: assert log (`LogAssertToErrorFile: false` by default).
- Pass it with `OPP_DATA_DIR=body/ualbertabot_port/bwapi-data tools/run_game_openbw.sh ...` (the
  script copies the directory contents into `p2/bwapi-data/` before launch). `eval/run_eval.py` does
  this automatically for `--opponent ualbertabot` (`OPPONENT_DATA_DIRS`).

## Game run (2026-10-01)

```
OPP_DATA_DIR=body/ualbertabot_port/bwapi-data TIMEOUT=900 tools/run_game_openbw.sh \
  $PWD/build/mcrave/McRave.so $PWD/build/ualbertabot/UAlbertaBot.so \
  "maps/BroodWar/sscai/(2)Benzene.scx" Zerg Protoss logs/openbw/mcrave_vs_ualbertabot uab
```
- `finished` (p1.log ends `SC_AI: ggwp`); p2.log: `Loaded the AI Module ... UAlbertaBot.so`, `Opponent: BWAPI
  4.2.0.0 RELEASE is now live`, `Enabled Flag UserInput`. No `Error:`/`dlerror`, no crash; both processes
  exited normally.
- **Winner: McRave (SC_AI)**. UAlbertaBot's own strategy record `p2/bwapi-data/write/SC_AI.txt` (written in
  `onEnd` by `StrategyManager::writeResults`) has `Protoss_ZealotRush 0 1` = 0 wins, 1 loss. McRave's
  `logger.txt` last entry is at **12:00 game time, frame 17164** (3-base muta/hydralurk), so the game ran
  ~17.2k frames; ~3 min wall clock at speed 0 (McRave is the CPU-bound side; UAlbertaBot used ~35 s CPU).
- p2.log also contains 20 `!Assert` blocks: 12x `BOSS/source/GameState.cpp:777 "Shouldn't have 0 mineral
  workers"` plus the 8 `BOSSManager.cpp` "BOSS SmartSearch/Timeout Naive Search Exception" that catch them.
  That is upstream behaviour (BOSS throws when asked to plan with no workers, `BOSSManager` catches and
  prints), triggered once the zealot rush failed and its probes were dead - not a port defect, left as is.
- Registered in `eval/run_eval.py`: `OPPONENTS["ualbertabot"] = ("build/ualbertabot/UAlbertaBot.so", "Protoss")`
  and `OPPONENT_DATA_DIRS["ualbertabot"] = "body/ualbertabot_port/bwapi-data"`.

## Unverified

- One game, one map, ZvP only; UAlbertaBot as Terran/Zerg not run (the code paths are config-selected).
- `DrawXxx` config flags are left as upstream (true for a few); drawing calls are no-ops headless.
- `UseAutoObserver: false`, `UserInput: true` as upstream; `SetLocalSpeed(0)` is called by the bot
  (harmless, `OPENBW_GAME_SPEED` governs).
- Windows build of the patched tree is unverified (changes are `#ifdef`-guarded or compiler-neutral).
- `eval.compare` gating is not applicable (no prompt/knowledge/validator/body change; this only adds opponents).
