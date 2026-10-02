# ZZZKBot Linux/OpenBW port

Builds `ZZZKBot.so` (Chris Coxe's Zerg rush bot, LGPLv3, https://github.com/chriscoxe/ZZZKBot)
as an AI module that OpenBW's `BWAPILauncher` can `dlopen`, from the unmodified upstream checkout
plus one patch file. Same pattern as `body/mcrave_port`. Status (2026-10-01):

- **Builds and links cleanly** (gcc 13.3 / cmake 3.28 / ninja, C++17, `-O2 -fPIC`, `-Wl,--no-undefined`)
  against the OpenBW fork's BWAPI 4.2 headers and `libBWAPILIB.so`. ~10 s clean build (one 5.8k-line TU).
- **Played a full game** vs McRave on OpenBW (see below).
- Patches: 1 (`body/patches/zzzkbot/0001-linux-port.patch`, 1 file, 54+/27-).

## Build

```
cd /home/user/SC_AI
# 0. OpenBW + its BWAPI fork built (docs/setup_openbw.md): third_party/openbw-bwapi/build/lib/libBWAPILIB.so
# 1. ZZZKBot source (git-ignored), exact commit the patch was made against:
git clone https://github.com/chriscoxe/ZZZKBot third_party/zzzkbot
git -C third_party/zzzkbot checkout 7183e37b6b416ea53c1040c83e639a3a3c395eed
# 2. Apply patches (idempotent; --reverse undoes)
body/zzzkbot_port/apply_patches.sh
# 3. Configure + build
cmake -S body/zzzkbot_port -B build/zzzkbot -G Ninja -DCMAKE_BUILD_TYPE=Release
ninja -C build/zzzkbot -j4
# -> build/zzzkbot/ZZZKBot.so (~560 KB)
nm -D build/zzzkbot/ZZZKBot.so | grep -E " T (gameInit|newAIModule)$"   # both must be present
```

CMake cache variables: `ZZZKBOT_ROOT`, `BWAPI_ROOT`, `BWAPI_INCLUDE_DIR`, `BWAPI_LIB_DIR`, `SC_AI_ROOT`.
The vcxproj compiles two TUs: `Source/Dll.cpp` (needs `<Windows.h>` for `DllMain`; replaced by
`body/zzzkbot_port/Dll_linux.cpp`, same `gameInit`/`newAIModule` bodies) and
`Source/ZZZKBotAIModule.cpp`. Defines: `NOMINMAX NDEBUG ZZZKBOT_EXPORTS` (the vcxproj's
`WIN32;_WINDOWS;_USRDLL` dropped). Upstream files are CRLF; the patch keeps CRLF so it applies
to the pristine checkout.

## Patches (`body/patches/zzzkbot/`)

### 0001-linux-port.patch (`ZZZKBot/Source/ZZZKBotAIModule.cpp` only)
| change | reason |
|---|---|
| add `<cstring>`, `<ctime>` | `memset`, `localtime_*` came transitively from MSVC headers |
| 4x `errno_t errNo = localtime_s(&buf, &t)` -> `#ifdef _WIN32` same `#else localtime_r(&t, &buf)` | `localtime_s`/`errno_t` are MSVC-only (used for timestamps in the learning-file records) |
| 20x `(int) u->getClientInfo(k)` -> `u->getClientInfo<int>(k)` | `void*` -> `int` cast is an error on LP64; BWAPI's templated overload does the `(CT)(long)` round trip, which is what MSVC's 32-bit cast did |
| `oss << Broodwar->getRandomSeed()` wrapped in `try/catch`, logs `0` on failure | the OpenBW fork's `getRandomSeed()` throws `std::runtime_error("ReplayHead_gameSeed_randSeed")` (docs/setup_openbw.md section 7); only a log field |

Behaviour is unchanged apart from the logged seed. Remaining gcc warnings: `-Wsequence-point` at
upstream line 3662 (`newGasGatherer` modified twice in one expression; MSVC order kept) and
`-Wint-to-pointer-cast` from BWAPI's `Interface.h:94` (`setClientInfo(int)`), both harmless.

## Config / data files (relative to the launcher's cwd, i.e. `<run_dir>/p2/`)

- `bwapi-data/AI/<player name>.cfg` **optional**: per-enemy strategy overrides (format in
  `third_party/zzzkbot/ZZZKBot/Configs/bwapi-data/AI/MyInGamePlayerName.cfg`). The name is
  `Broodwar->self()->getName()`, which `tools/run_game_openbw.sh` sets to `Opponent`, so the file
  would be `bwapi-data/AI/Opponent.cfg`. Without it ZZZKBot uses its built-in defaults (ran fine).
- `bwapi-data/read/` and `bwapi-data/write/`: learning records
  `ZZZKBot_v_1.7.0.0.0_<race>_vs_<enemy>_<race>.dat` (written every game; read if present). The run
  script creates both dirs, each game starts from an empty `read/`, so no cross-game learning
  unless you copy `write/` -> `read/` yourself (or point `OPP_DATA_DIR` at a dir with `read/`).
- To pass extra files: `OPP_DATA_DIR=<dir> tools/run_game_openbw.sh ...` copies `<dir>/.` into
  `p2/bwapi-data/` before launch.

## Game run (2026-10-01)

```
TIMEOUT=900 tools/run_game_openbw.sh $PWD/build/mcrave/McRave.so $PWD/build/zzzkbot/ZZZKBot.so \
  "maps/BroodWar/sscai/(2)Benzene.scx" Zerg Zerg logs/openbw/mcrave_vs_zzzkbot zzzk
```
- `finished` (p1.log: `SC_AI: glhf` ... `SC_AI: ggwp`); p2.log: `Loaded the AI Module ... ZZZKBot.so`,
  `The matchup is Zerg vs Zerg`. No crash, no `Error:` lines.
- **Winner: McRave (SC_AI)**. ZZZKBot's own record `p2/bwapi-data/write/ZZZKBot_v_1.7.0.0.0_Zerg_vs_SC_AI_Zerg.dat`
  ends `onEnd 9272 9271 44 ... 0`: game ended at **frame 9272 (~6:27 game time)**, `isWinner = 0`
  for ZZZKBot, 44 s wall clock (speed 0). ZZZKBot 4-pooled; McRave held it.
- Registered in `eval/run_eval.py` `OPPONENTS["zzzkbot"] = ("build/zzzkbot/ZZZKBot.so", "Zerg")`.

## Unverified

- Only one game, one map, ZvZ. Terran/Protoss opponents and the other sscai maps not tried.
- The `.cfg` per-enemy override path was not exercised (no `Opponent.cfg` was provided).
- `creep_data` / debug file paths (lines ~614-791) are relative to cwd and unchanged; not exercised.
- Windows build of the patched tree is unverified (changes are `#ifdef`-guarded or compiler-neutral).
