# McRave Linux/OpenBW port

Builds `McRave.so`, an AI module that OpenBW's `BWAPILauncher` can `dlopen`, from the
unmodified upstream McRave checkout plus five patch files. Status (2026-09-30):

- **Builds and links cleanly** with gcc 13.3 / cmake 3.28 / ninja, C++17, `-O2 -fPIC`,
  `-Wl,--no-undefined` (so every BWAPI symbol McRave uses is resolved at link time).
- **Header set: the OpenBW fork's own headers** (`third_party/openbw-bwapi/bwapi/include`,
  BWAPI 4.2 API level) were sufficient. The official BWAPI 4.4.0 headers were **not needed**
  and were not cloned; `third_party/bwapi-official` does not exist. Nothing in McRave @
  `7d1719a2` uses 4.4-only API (the `--no-undefined` link would have caught a missing export).
- 39 McRave source files patched (101 insertions, 65 deletions) across 5 patches, all
  behaviour-preserving apart from the documented bug fixes in `0005`.
- Not run in a game: no MPQ data in this container (see "Unverified").

## Build

```
cd /home/user/SC_AI
# 0. OpenBW + its BWAPI fork must already be built (docs/setup_openbw.md):
#    third_party/openbw-bwapi/build/lib/libBWAPILIB.so must exist.
# 1. McRave source (git-ignored), exact commit the patches were made against:
git clone https://github.com/Cmccrave/McRave third_party/mcrave
git -C third_party/mcrave checkout 7d1719a22d8b896f957abae50e2ea5efff974fe2
# 2. Apply patches (idempotent: re-running skips already-applied ones; --reverse undoes)
body/mcrave_port/apply_patches.sh
# 3. Configure + build (Release, ninja)
cmake -S body/mcrave_port -B build/mcrave -G Ninja -DCMAKE_BUILD_TYPE=Release
ninja -C build/mcrave -j4
# -> build/mcrave/McRave.so   (~3.1 MB; 84 s wall on 4 cores for a clean build)
```

CMake cache variables (all default to the layout above): `MCRAVE_ROOT`, `BWAPI_ROOT`,
`BWAPI_INCLUDE_DIR`, `BWAPI_LIB_DIR`, `SC_AI_ROOT`.

What the CMake file does: globs the 114 `.cpp` files under `Source/{McRave,BWEM,BWEB,Horizon}`
(the same list as `VisualStudio/McRave.vcxproj`, verified identical), drops the two
Windows-only TUs (`McRave/Main/Dll.cpp`, `BWEM/winutils.cpp`) and adds
`body/mcrave_port/Dll_linux.cpp`, which exports the two-symbol ABI with default ELF
visibility. Include dirs mirror the vcxproj (`BWEB; BWEM; Horizon; McRave; <bwapi include>`),
defines are `NOMINMAX EXAMPLEAIMODULE_EXPORTS` (the vcxproj's `WIN32;_WINDOWS;_USRDLL` are
dropped). Output name has no `lib` prefix, as with `ExampleAIModule.so`. The build-tree
`.so` carries a RUNPATH to `third_party/openbw-bwapi/build/lib`; when loaded by
`BWAPILauncher`, `libBWAPILIB.so` is already in the process anyway.

## Loader test done here (no game data available)

```
$ nm -D build/mcrave/McRave.so | grep -E " T (gameInit|newAIModule)$"
000000000021e530 T gameInit
000000000021e540 T newAIModule
$ python3 -c "import ctypes; h=ctypes.CDLL('/home/user/SC_AI/build/mcrave/McRave.so'); print(bool(h.gameInit), bool(h.newAIModule))"
True True
$ ldd build/mcrave/McRave.so | grep BWAPI
        libBWAPILIB.so => /home/user/SC_AI/third_party/openbw-bwapi/build/lib/libBWAPILIB.so
```

`ctypes.CDLL` uses `RTLD_NOW`-equivalent resolution for the exported symbols and runs the
library's static initialisers, so this exercises the same path as `BWAPILauncher`'s `dlopen`
up to (but not including) `newAIModule()` being called.

## Patches (`body/patches/mcrave/`)

Applied in order by `apply_patches.sh` (`git apply --check` first, reverse-check to detect
"already applied"). Paths are relative to `third_party/mcrave/Source/`.

### 0001-windows-guards.patch (2 files)
| file | change | reason |
|---|---|---|
| `BWEM/defs.h` | `BWEM_USE_WINUTILS 1` -> `0` | `winutils.cpp` needs `<windows.h>` (QueryPerformanceCounter); the Timer is only used in commented-out code |
| `McRave/Main/Visuals.cpp` | `#include <windows.h>` and `getCurrentWindow()` body under `#ifdef _WIN32`; else `gameFocused = true` | `GetForegroundWindow`/`GetWindowText` only gate debug drawing; headless OpenBW has no window |

`McRave/Main/Dll.cpp` is not patched; it is excluded from the build and replaced by
`body/mcrave_port/Dll_linux.cpp` (same `gameInit`/`newAIModule` bodies, no `DllMain`).

### 0002-portable-includes.patch (7 files)
| file | change | reason |
|---|---|---|
| `McRave/Main/Common.h` | add `<cfloat> <climits> <cstring> <cmath> <functional>` | `DBL_MAX`, `INT_MAX`, `FLT_MAX`, `memset`, `std::strlen` came transitively from MSVC's headers |
| `BWEB/Station.h`, `BWEB/Wall.h` | add `<cfloat>` | `DBL_MAX` used in inline functions |
| `BWEB/PathFind.cpp` | add `<climits> <cstring>` | `INT_MAX`, `memset` |
| `BWEM/utils.h` | add `<cmath> <sstream>` | `sqrt`, `std::ostringstream` |
| `BWEM/area.cpp`, `BWEM/mapImpl.cpp` | `"BaseFinder\BaseFinder.h"` -> `"BaseFinder/BaseFinder.h"` | backslash include path |

### 0003-msvc-conformance.patch (15 files)
| file | change | reason |
|---|---|---|
| `McRave/Strategy/Actions/Actions.h` | `std::same_as<T,..>` -> `std::is_same_v<T,..>` | `same_as` is a C++20 concept; build is C++17 |
| `BWEM/graph.h` | `#include "tiles.h"` | `TileOfPosition` used in a template body before its declaration (two-phase lookup) |
| `BWEB/BWEB.h` | forward-declare `getAngle(T,T)` before `getAngle(pair)` | template called before declaration (two-phase lookup) |
| `McRave/Main/Util.h` | re-declare `Units::getUnits` before `namespace Util`; pass an lvalue `center` to `pred` in `testPointOnPath`/`testAllPointOnPath`/`findPointOnPath` | `Units.cpp` includes `Units.h` first, so through `Common.h` the templates see no `Units` namespace; generic `auto &` predicates cannot bind a temporary |
| `McRave/Info/Unit/UnitInfo.h` (4 setters), `UnitInfo.cpp` (`setResource`) | `c ? a = x : b.reset()` -> `if/else` | `?:` with a `void` operand is an MSVC extension |
| `McRave/Info/Building/Buildings.cpp` | `return false` -> `return nullptr` (2x) | pointer-returning functions |
| `McRave/Info/Unit/Pathing.cpp` (3 generators), `McRave/Micro/Combat/State.cpp` (`unlockedOrVis`) | `[&]` -> `[]` | namespace-scope lambdas may not have a capture-default; they capture nothing |
| `McRave/Micro/All/Commands.cpp` (`penalizeEdge`, `penalizeCorner`, `threatCalc`), `Micro/Combat/Navigation.cpp` (`threatCalc`), `Builds/All/BuildOrder.cpp` (`addBuildableRequisites`), `Macro/Planning/Planning.cpp` (`adjacentToHatch`), `Map/Grids/Grids.cpp` (`drawThisWalk`) | lambda param `auto &` -> `const auto &` | called with temporaries / converted to `std::function<..(T)>` |
| `McRave/Main/Visuals.cpp` | `start` is `high_resolution_clock::time_point` | it is assigned from `high_resolution_clock::now()`; libstdc++ keeps `steady_clock` a distinct type |

### 0004-rvalue-reference-binding.patch (11 files)
MSVC lets `auto &x = f();` bind a non-const lvalue reference to a temporary; gcc/clang do not.
Every site below now takes the value (a `shared_ptr` copy, a `Path`, a `vector`, a `Strength`,
an iterator), which is what MSVC effectively did with the lifetime-extended temporary.

| file | sites |
|---|---|
| `McRave/Micro/Transport/Transports.cpp` | lines 75, 230, 242, 329 (`c.lock()`), 318 (`cargoList.begin()`) |
| `McRave/Info/Unit/Targeting.cpp` | 318, 452 (`t.lock()`), 823 (`Units::getUnitInfo`), 839-840 (`Players::getStrength`) |
| `McRave/Info/Unit/UnitMath.cpp` | 35, 66 (`Units::getUnitInfo`) |
| `McRave/Micro/All/Commands.cpp` | 739 (`c.lock()`) |
| `McRave/Info/Resource/Resources.cpp` | 338 (`getResourceInfo`) |
| `Horizon/Horizon.cpp` | 75 (`unit.getTarget()`) |
| `McRave/Strategy/Goals/Goals.cpp` | 588 (`Stations::getStations`) |
| `McRave/Micro/Worker/Workers.cpp` 127, `Macro/Expanding/Expanding.cpp` 26 | `Stations::getPathBetween` returns by value |
| `McRave/Map/Stations/Stations.h` | 58, 79 (`getStations(player)` returns by value) |
| `McRave/Info/Unit/UnitInfo.h` | `setMarchPath`/`setRetreatPath` take `BWEB::Path` by value and `std::move` it (callers pass `std::move(newPath)` and `BWEB::Path()`) |

### 0005-memory-safety.patch (10 files) - the only patch that changes observable behaviour
| file | change | reason |
|---|---|---|
| `BWEB/Wall.h` | `getDefenses(row)` returns a `static const` empty set instead of `{}` | returned a reference to a temporary (gcc `-Wreturn-local-addr`, 91 instantiations) |
| `McRave/Micro/Combat/Clusters.cpp` | `auto node = nodeQueue.front();` (was `auto &`) before `pop()` | dangling reference into a popped `std::queue` |
| `BWEB/Block.cpp` | `addToBlockGrid` clamps x,y to `[0,256)` | `blockGrid[256][256]` written out of bounds for tiles off-map |
| `BWEB/Station.cpp` | Zerg secondary defense: `defenses.insert(base->Location() + defense)` (was the bare offset, e.g. `(4,-4)`) | inserted a relative offset as an absolute tile; the negative tile is what fed the out-of-bounds write above, and Zerg defense placement was wrong (lukecameron's finding, re-derived here) |
| `McRave/Micro/Combat/State.cpp` | `static bool carrierCountReady = com(Protoss_Carrier) >= 4;` | initializer referenced the variable itself; statics are zero-initialised, so the result is the same |
| `McRave/Main/Visuals.cpp`, `Info/Unit/Units.cpp`, `BWEB/Block.cpp`, `BWEB/Station.cpp`, `BWEB/Wall.cpp` | `c ? textColor = X : y` -> `c ? X : y` | assignment to the variable inside its own initializer (unsequenced) |
| `McRave/Main/Visuals.cpp` `getTextColor()`, `Map/Walls/Walls.cpp` three `*TypeCount` | add a `return` | non-void functions fell off the end (UB); none has a caller |
| `McRave/Macro/Producing/Producing.cpp` | `building && building->getAddon()` | `isCreateable(nullptr, type)` is called for larva; only Terran types dereference, but gcc flagged the null `this` |

### 0006-sidecar-files.patch / 0007-hooks.patch - SC_AI hooks 1-3
New `McRave/Main/Sidecar.{h,cpp}` plus 35 one-line insertions in 7 files. Off unless
`SIDECAR_HOST`/`SIDECAR_PORT` or `bwapi-data/sidecar.ini` is present. See `HOOKS_IMPL.md`.

## Remaining warnings (gcc 13, `-Wall`, 203 lines)

- 182x `backslash-newline at end of file` from `BWEB/Logger.h` and `McRave/Main/Logger.h`
  (both files end with a `\`); cosmetic.
- `BWEB/PathFind.cpp:92` `-Wclass-memaccess`: `memset` of `TileData` (has default member
  initialisers, otherwise trivially copyable); zeroing it is what the code intends.
- `BWEM/graph.h:145` "invalid use of incomplete type `MapImpl`" and `McRave/Main/Util.h`
  150/170/190/210 "incomplete type `UnitInfo`": gcc diagnoses these inside templates whose
  instantiation context is complete (they compile and link); only emitted for the
  `Units.cpp`/BWEM TUs with the inverted include order. Not touched to keep the patch minimal.
- `PvZ_FFE.cpp:25,44` comma operator (`= a, b;` - `b` discarded, matches MSVC behaviour),
  `Targeting.cpp:400` statement with no effect (`Priority::Major;`), `Units.cpp:362`
  unhandled enum `All` in switch. Upstream quirks, behaviour unchanged.

Suppressed (they are noise from upstream style, not correctness): `-Wno-unused-variable
-Wno-unused-but-set-variable -Wno-sign-compare -Wno-reorder -Wno-unused-function
-Wno-parentheses -Wno-misleading-indentation`.

## Unverified

- **The module has not been loaded by `BWAPILauncher` in a game**: the container has no
  `Patch_rt.mpq`/`BrooDat.mpq`/`StarDat.mpq`. Next step once MPQs are available:
  `BWAPI_CONFIG_AI__AI=/home/user/SC_AI/build/mcrave/McRave.so` with the single-player smoke
  test in `docs/setup_openbw.md` section 5, then a LAN game vs `ExampleAIModule.so`.
- `newAIModule()` has not been called (it constructs `McRaveModule`, which touches
  `Broodwar` only in `onStart`, so calling it outside a game would not prove much).
- McRave reads/writes learning files under `bwapi-data/read|write` relative to cwd
  (`Builds/All/Learning.cpp`); untested on Linux.
- The `BWEM_USE_MAP_PRINTER` define is still `1` but `mapPrinter.cpp` is not in the tree, so
  nothing changes; `mapDrawer.cpp` compiles fine.
- Windows build of the patched tree is unverified (patches are `#ifdef`-guarded or
  compiler-neutral, so it should still build with VS2017).
- Whether the OpenBW 4.2 `BWAPILIB` ABI matches every call McRave makes at runtime: the link
  proves symbol presence, not identical semantics (e.g. `Unit::getLastCommand`,
  `UnitCommandTypes`); a game run is the only real test.
