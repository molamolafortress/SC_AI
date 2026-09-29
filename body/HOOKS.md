# McRave hook analysis (Phase 0)

Target: McRave @ `7d1719a22d8b896f957abae50e2ea5efff974fe2` (2026-05-25, "shared_ptr improvement"),
cloned to `third_party/mcrave/` (git-ignored via `third_party/` in `.gitignore`).
All paths below are relative to `third_party/mcrave/Source/`. Nothing in McRave was modified.

Design reference: `docs/design_v0.5.md` §2, §3.1, §4 (three hooks: strategy injection, state
summary emission, single command-issue point).

---

## 1. Build system and portability

### 1.1 How McRave builds today

- **Visual Studio only.** `VisualStudio/McRave.sln` + `McRave.vcxproj`, PlatformToolset `v141`
  (VS2017), `Win32` only, `ConfigurationType=DynamicLibrary`. No CMake, no Makefile.
- Language standard: Debug `stdcpp17`, Release `stdcpplatest` (C++17 features used everywhere:
  structured bindings, `inline` namespace-scope variables, `std::optional`, `string_view`).
- Include path: `..\Source\BWEB;..\Source\BWEM;..\Source\Horizon;..\Source\McRave;..\..\..\include`
  and link `../lib/BWAPI.lib` (`BWAPId.lib` for Debug). I.e. it expects the **official BWAPI SDK
  layout** (`include/BWAPI.h`, `lib/BWAPI.lib`) two directories above the repo. No BWAPI version
  is pinned in-tree; API usage (`BWAPI::BroodwarPtr = game` in `gameInit`, `AIModule` virtuals,
  `UnitCommandTypes`, `Unit::getLastCommand`) is BWAPI 4.x. lukecameron reports it compiles
  cleanly against **official BWAPI 4.4.0 headers** (rev `7687da8`) and links against the
  **OpenBW BWAPI 4.2** library.
- Preprocessor: `NOMINMAX;WIN32;_WINDOWS;_USRDLL;EXAMPLEAIMODULE_EXPORTS` (Debug also defines
  `MCRAVE_PROTOSS;MCRAVE_TERRAN;MCRAVE_ZERG`, but those macros are **never referenced** in source —
  all three races are always compiled in).
- Output: `..\..\StarCraft\bwapi-data\AI\McRave.dll`.
- 114 `.cpp` translation units (BWEB 5, BWEM 18, Horizon 1, McRave 90).

### 1.2 Dependencies (all vendored as source, no submodules, no package manager)

| Dep | Location | Notes |
|---|---|---|
| BWEM | `Source/BWEM/` (+ `BaseFinder/`) | Map analysis (areas, chokepoints, bases). Includes `winutils.cpp/h` (Windows perf-counter `Timer`), enabled by `#define BWEM_USE_WINUTILS 1` in `BWEM/defs.h:34`. The Timer is only referenced in commented-out code (`mapImpl.cpp:77`). `mapDrawer.cpp` is compiled but `BWEM_USE_MAP_PRINTER` (EasyBMP) is not actually pulled in. |
| BWEB | `Source/BWEB/` | McRave's own fork of BWEB (Blocks, Stations, Walls, JPS pathfinding). `BWEB.h:14` redefines `M_PI` (warning on Clang). |
| Horizon | `Source/Horizon/` | McRave's own combat simulator (`Horizon::simulate(UnitInfo&)`). **No FAP.** |
| Learning files | runtime | `bwapi-data/read/` + `bwapi-data/write/` text files (see §4). |

### 1.3 Windows-only code (blocks a Linux/OpenBW build)

Exhaustive grep for `windows.h`, `__declspec`, `_WIN32`, `WINAPI`, `HWND`, etc.:

1. `McRave/Main/Dll.cpp` (whole file, 22 lines): `#include <Windows.h>`, `DllMain`, and
   `extern "C" __declspec(dllexport) gameInit/newAIModule`. Needs `#ifdef _WIN32` around
   `DllMain`/`Windows.h` and a `__attribute__((visibility("default")))` variant of the two
   exports for ELF/Mach-O.
2. `McRave/Main/Visuals.cpp:4` `#include <windows.h>` and `Visuals.cpp:230-239`
   `getCurrentWindow()` uses `GetForegroundWindow()/GetWindowText()` to set `gameFocused`
   (only gates drawing). Trivial to `#ifdef`.
3. `BWEM/winutils.cpp:13` `#include <windows.h>` (QueryPerformanceCounter). Set
   `BWEM_USE_WINUTILS 0` in `BWEM/defs.h` or drop the file from the build.
4. `Learning.cpp` uses forward-slash paths (`bwapi-data/read/...`) — fine on Linux.
5. No `std::thread`, `std::mutex`, `std::async`, sockets, WinSock or curl anywhere in the tree.
   McRave is strictly single-threaded (see §5.3).

### 1.4 What lukecameron/starcraft-ai patched (from `docs/mcrave-port.md`, treated as data)

Their port targets the **same commit** (`7d1719a`) and builds the full gameplay source as a
native ARM64 `McRave.dylib` against OpenBW's BWAPI 4.2 via CMake + Ninja, using
`patches/mcrave.patch`. Reported changes:

- Make the Windows DLL entry point conditional (`_WIN32`), export the same `gameInit` /
  `newAIModule` ABI on macOS.
- Disable BWEM's Windows performance-counter helper (winutils).
- Make the visual focus check portable (Visuals `getCurrentWindow`).
- Fix two Windows path separators (we could not find backslash string literals at this commit —
  possibly in code paths they hit; low risk).
- Clang `-fdelayed-template-parsing` because upstream relies on MSVC two-phase-lookup laxity.
- Conformance fixes for MSVC-accepted constructs: missing return values (`Visuals.cpp:245`
  `Text::Enum getTextColor() {}` is one such), a self-referential static initializer
  (`Combat/State.cpp:33` `static bool carrierCountReady = carrierCountReady || ...`), a reference
  to a temporary empty set, a shadowed text-color value.
- Memory-safety fixes: dangling reference to `queue.front()` after `pop()` in combat clustering
  (`Combat/Clusters.cpp`); `BWEB::Blocks::addToBlockGrid` writing outside a fixed 256x256 array on
  small maps; Zerg secondary-defense tile inserted as relative offset instead of absolute tile in
  `Station` defenses.
- Remaining warnings: `M_PI` redefinition, BWAPI template diagnostics.
- Windows x86 build "remains unverified" by them; their smoke test was a WorkerRush opponent on
  Benzene/Destination with OpenBW.

**Takeaway:** the Linux/OpenBW port is a known-feasible ~1-2 day job (CMake file listing the 114
TUs, three `#ifdef _WIN32` sites, a handful of conformance fixes). Reuse of their patch is
advisable if its license permits; otherwise re-derive from the list above.

---

## 2. Where Zerg strategy decisions live

Global build-order state is a set of `inline` variables in `McRave/Builds/All/All.h`
(namespace `McRave::BuildOrder::All`): `buildQueue`, `techQueue`, `upgradeQueue`,
`armyComposition`, `unitOrder`, `focusUnits`, `currentBuild/currentOpener/currentTransition`,
`inOpening`, `inTransition`, `transitionReady`, `wallNat/wallMain/wallThird`, `wantNatural`,
`wantThird`, `expandDesired`, `rush`, `pressure`, `gasLimit`, etc. Everything downstream
(Producing, Planning, Combat, Stations, Walls) reads these via getters in
`McRave/Builds/All/BuildOrder.cpp`. **These variables are recomputed from scratch every frame**
in `BuildOrder::updateBuild()`:

```cpp
// Builds/All/BuildOrder.cpp:24
void updateBuild()
{
    buildQueue.clear(); upgradeQueue.clear(); techQueue.clear(); armyComposition.clear();
    ...
    if (Players::getSupply(PlayerState::Self, Races::Zerg) > 0) {
        s = Players::getSupply(PlayerState::Self, Races::Zerg);
        Zerg::opener();
        Zerg::tech();
        Zerg::composition();
        Zerg::situational();
        Zerg::unlocks();
    }
    for (auto &type : focusUnits) getTechBuildings(type);
}
```

This "declarative, re-evaluated every frame" style is what makes injection cheap: a directive
just has to set the same variables *after* McRave's own logic ran (or steer the inputs).

### 2.1 Opening / build selection per matchup

- **Initial pick:** `Builds/All/Learning.cpp` — `Learning::onStart()` calls
  `createBuildMaps()` (`zergBuildMaps()` @ L335 enumerates the allowed
  build/opener/transition tuples per matchup), `getDefaultBuild()` (@ L83; ZvT default =
  `HatchPool / 12Hatch / 2HatchMuta`, ZvP = `PoolHatch / Overpool / 2HatchMuta`, ZvZ =
  `PoolLair / 9Pool / 1HatchMuta`), then `getBestBuild()` (@ L122, UCB1 over win/loss files), then
  `getPermanentBuild()` (@ L249, hard-coded test override behind `if (false)`). Result is written
  with `BuildOrder::setLearnedBuild(build, opener, transition)` into the three strings.
- **Per-frame matchup dispatch:** `Builds/Zerg/ZergBuildOrder.cpp:740 Zerg::opener()` →
  `ZvT()` / `ZvP()` / `ZvZ()` / `ZvFFA()`.
- **Per-matchup driver:** e.g. `Builds/Zerg/ZvT/ZvT.cpp:296 ZvT()`:

```cpp
void ZvT()
{
    defaultZvT();                       // resets wantNatural/wallNat/unitOrder/... every frame
    // Reactions
    if (!inTransition) {
        if (Spy::getEnemyTransition() == U_WorkerRush) { currentBuild = Z_PoolHatch; currentOpener = Z_Overpool; currentTransition = Z_2HatchMuta; }
        if (Spy::getEnemyOpener() == T_8Rax || Spy::enemyProxy()) { ...same... }
    }
    // Builds
    if (currentBuild == Z_HatchPool) ZvT_HP();
    if (currentBuild == Z_PoolHatch) ZvT_PH();
    if (currentBuild == Z_PoolLair)  ZvT_PL();
    // Transitions
    if (transitionReady) {
        if (currentTransition == Z_2HatchMuta) ZvT_2HatchMuta();
        if (currentTransition == Z_3HatchMuta) ZvT_3HatchMuta();
        if (currentTransition == Z_1HatchLurker) ZvT_1HatchLurker();
    }
}
```

- **Openers** (`ZvT_HatchPool.cpp`, `ZvT_PoolHatch.cpp`, `ZvT_PoolLair.cpp`): each opener
  function (e.g. `ZvT_HP_12Hatch()`) writes `buildQueue[...]` by supply thresholds and sets
  `transitionReady = vis(Zerg_Spawning_Pool) > 0`.
- **Transitions** (`ZvT.cpp` `ZvT_2HatchMuta()` / `ZvT_3HatchMuta()` / `ZvT_1HatchLurker()`):
  set `inTransition`, `inOpening = total(Zerg_Mutalisk) <= 12` (end of book), building counts,
  `zergUnitPump[...]` flags, `gasLimit`, `unitPressure`.
- **Build name constants:** `Strategy/Spy/Defs.h` (`Z_HatchPool`, `Z_12Hatch`, `Z_2HatchMuta`,
  `Z_3HatchHydra`, ...). These are the vocabulary a Directive `opening` field should map to.
- **Runtime chat override already exists:** `Main/Visuals.cpp:293 onSendText` — after `/bo`, typing a
  build/opener/transition name calls `setLearnedBuild`. Proof that mid-game `setLearnedBuild` is
  safe while `!inTransition`.

**How transitions happen:** the opener sets `transitionReady`; the transition function then sets
`inTransition = true` (which freezes the reaction block) and later `inOpening = false` when its
unit target is met. After `inOpening == false`, the "book" no longer controls production/expansion;
`Zerg::tech()`, `Zerg::composition()` (priority tables) and `situational()` take over.

### 2.2 Unit composition

- **In opening** (`ZergBuildOrder.cpp:847 composition()`, `if (inOpening)` branch): a strict
  priority ladder over `zergUnitPump[type]` flags set by the opener/transition functions:
  Lurker > Queen > Defiler > Ultralisk > Scourge > Mutalisk > Hydralisk > Zergling > Drone, each
  gated by available gas; exactly one type gets `armyComposition[type] = 1.0`.
- **After opening** (`!inOpening` branch @ L898-1040): `switchComposition()` (@ L38) picks
  `unitOrder` (e.g. `mutalingdefiler`, `ultraling`, `hydradefiler` — vectors defined in
  `ZergBuildOrder.h`) based on Spy info, with a 1-minute switch cooldown; then a matchup-specific
  `priorityOrder` table of `{UnitType, targetCount}` pairs is walked and the first unfulfilled,
  affordable, unlocked entry gets `armyComposition[type] = 1.0`. Fallback at the end: drones or
  lings.
- **Tech order:** `Zerg::tech()` (@ L767) inserts `unitOrder` entries into `focusUnits` and calls
  `getNewTech()` → `getTechBuildings()` which queues prerequisite structures.
- **Consumer:** `Macro/Producing/Producing.cpp` uses `BuildOrder::isUnitUnlocked()`,
  `getCompositionPercentage()` (L292-310, weighted scoring) and `getUnitReservation()`.

So `armyComposition` is effectively a one-hot "what to build next" rather than a ratio, but
Producing does honour fractional percentages, so a directive `unit_mix_target` map can be written
in directly.

### 2.3 Army stance (attack vs defend)

There is **no single global "attack/defend" flag**. Stance emerges from:

1. `Micro/Combat/State.cpp:303 updateStaticStates()` → `updateZStaticStates()` (@ L143) builds
   `staticRetreatTypes` (unit types that must stay home) from Spy/upgrade/timing rules
   (e.g. lings retreat until speed, hydras until range+speed, mutas until 6+). `isStaticRetreat(type)`
   is read by `forceGlobalRetreat()` (@ L544) → `updateGlobalState()` sets each combat unit's
   `GlobalState::Retreat` or `Attack`. That is the de-facto stance switch.
2. `Micro/Combat/Combat.cpp:43 findAttackPosition()` (enemy start until 6:00, then furthest enemy
   station) and `:91 findDefendPosition()` (natural vs main choke via `defendNatural`/`holdNatural`,
   derived from `BuildOrder::takeNatural()`, station count, Spy).
3. `BuildOrder::isRush()/isPressure()/isAllIn()` (All.h flags `rush`, `pressure`, `unitPressure`,
   `activeAllin`) short-circuit the retreat rules → aggressive.
4. `Strategy/Goals/Goals.cpp:560 updateZergGoals()` assigns small detachments to attack enemy
   expansions / deny drops.
5. Local engage/retreat per cluster is decided by the Horizon simulation (`Simulation.cpp`) in
   `updateLocalState()`; that is the tactical layer we leave alone.

### 2.4 Expansion choice

- **Whether:** `ZergBuildOrder.cpp:356 queueExpansions()` computes `expandDesired` (only when
  `!inOpening`) from saturation/tech/production saturation, then
  `buildQueue[Zerg_Hatchery] = max(buildQueue[Zerg_Hatchery], hatchCount() + expandDesired)`.
  During the opening, hatch count comes straight from the opener/transition tables.
  `wantNatural`/`wantThird` gate the natural/third specifically.
- **Where:** `Macro/Expanding/Expanding.cpp:83 updateExpandOrder()` scores all BWEB stations
  (ground/air distance to parent station, to enemy, gas vs mineral-only, island, blockers) into
  `expansionOrder`; `Macro/Planning/Planning.cpp:835 updateNextExpand()` takes the first buildable
  one as `currentExpansion`; `Planning.cpp:395-415` forces main-rebuild and natural-first.

### 2.5 Static defense (sunken/spore) counts

- **Requested counts:** `ZergBuildOrder.cpp:143 queueDefenses()` loops BWEB walls and own
  stations and queues `Zerg_Creep_Colony` (+1 per frame until satisfied), then
  `buildQueue[Zerg_Sunken_Colony]/[Zerg_Spore_Colony] = vis(...) + 1` if `needSunks/needSpores`.
- **How many are needed:** two families of functions:
  - Walls: `Map/Walls/Walls.cpp` `needGroundDefenses(wall)` / `needAirDefenses(wall)` dispatch to
    matchup tables in `Map/Walls/ZergWalls.h` (`ZvT_GroundDefenses` @ L280, `ZvT_Opener`,
    `ZvT_Transition`, `ZvP_*`, `ZvZ_*`), which are timing/Spy-rule heuristics returning a desired
    count minus current count.
  - Stations: `Map/Stations/Stations.cpp:616 needGroundDefenses(station)` / `:649
    needAirDefenses(station)` → `ZvTgroundDef` (@ L338) etc.
- **Placement** is BWEB (`Wall::getDefenses()`, `Station::getDefenses()`), consumed by Planning.

### 2.6 Wall-in via BWEB

- Walls are **always generated at startup** for main and natural chokes:
  `Map/Walls/Walls.cpp:286 onStart()` → `initializeWallParameters()` (Zerg: buildings
  `{Hatchery, Evolution_Chamber}` combos, defenses `{Sunken_Colony}`, tight vs Zergling) →
  `findWalls()` → `BWEB::Walls::createWall(...)`. Third-base walls are generated lazily in
  `Walls::onFrame()`.
- Whether the wall is **used** is the per-frame flag `wallNat` (`All.h`), set in
  `defaultZvT()` (`ZvT.cpp:34`: `wallNat = wantNatural && hatchCount() >= 2 && (enemy RaxFact ||
  enemyWalled)`), `defaultZvP()`, `defaultZvZ()`, and forced on in `queueDefenses()` when
  anticipating air. Consumers: `Macro/Planning/Planning.cpp:644-647` (only place buildings on
  wall tiles when `isWallNat()/isWallMain()/isWallThird()`), `Stations.cpp:326`.
- So "wall on/off" is a one-boolean override; no BWEB calls needed at runtime.

---

## 3. Main loop and event handlers

`McRave/Main/McRave.cpp`:

```cpp
void McRaveModule::onFrame()
{
    if (Broodwar->getGameType() != GameTypes::Use_Map_Settings && Broodwar->isPaused()) return;
    if (Util::getTime() > Time(59, 59)) Broodwar->leaveGame();
    Visuals::endPerfTest("BWAPI");
    Util::onFrame();
    // Update ingame information
    Players::onFrame(); Units::onFrame(); Grids::onFrame(); Roles::onFrame(); Targets::onFrame(); Pathing::onFrame(); Pylons::onFrame();
    // Update relevant map information and strategy
    Terrain::onFrame(); Walls::onFrame(); Resources::onFrame(); Spy::onFrame(); BuildOrder::onFrame(); Stations::onFrame();
    // Update gameplay of the bot
    Actions::onFrame(); Goals::onFrame(); Support::onFrame(); Scouts::onFrame(); Defender::onFrame(); Combat::onFrame();
    Workers::onFrame(); Transports::onFrame(); Expansion::onFrame(); Planning::onFrame(); Buildings::onFrame();
    Upgrading::onFrame(); Researching::onFrame(); Producing::onFrame();
    // Display information from this frame
    Visuals::onFrame();
}
```

Ordering that matters for hooks: `Spy` → `BuildOrder` (strategy) → `Combat` (stance) →
`Expansion`/`Planning`/`Producing` (execution). A directive must be swapped in **before
`BuildOrder::onFrame()`**, i.e. at the top of `onFrame` (after `Util::onFrame()`).

`onStart()` order: Visuals, Util, Players, Terrain, Walls, Planning, Stations, Expansion, Grids,
**Learning**, Resources, Scouts, Combat, Goals; then `setLatCom(true)`, `setLocalSpeed(0)`.
`onEnd(isWinner)` → `Learning::onEnd()` writes the learning file.

Unit events are one-liners forwarding to `inline` functions in `McRave/Main/Events.h`:
`Events::onUnitDiscover` (BWEB + `Players::storeUnit` + `Planning::onUnitDiscover` + station),
`onUnitCreate`, `onUnitDestroy` (BWEB + `Players::removeUnit` + ...), `onUnitMorph`,
`onUnitComplete`, `onUnitRenegade`. `onUnitShow/Hide/Evade`, `onReceiveText`, `onPlayerLeft`
are empty.

### 3.1 Command issue points

Most micro commands go through **one wrapper**: `Info/Unit/UnitInfo.cpp:621-720`
`UnitInfo::setCommand(...)` (6 overloads: `(UnitCommandType, Position)`,
`(UnitCommandType, UnitInfo&)`, `(UnitCommandType)`, `(TechType, Position)`,
`(TechType, UnitInfo&)`, `(TechType)`), which de-duplicates identical commands within 6 frames
and then calls `unit()->move/attack/rightClick/holdPosition/stop/burrow/unburrow/siege/unsiege/useTech`.
`Micro/All/Commands.cpp` (move/attack/kite/retreat/...) only ever calls `setCommand`.

However, **~38 raw BWAPI command calls bypass it** (grep `unit()->(train|morph|build|...)(`):

| File | Calls |
|---|---|
| `Micro/All/Specials.cpp` | 16: lift/land, gather, unsiege, repair x2, useTech(Archon_Warp), morph(Lurker/Guardian/Devourer), returnCargo x2, gather(boulder), build(...) @ L770 (all worker builds) |
| `Info/Unit/UnitInfo.cpp` | 13 (the setCommand bodies themselves) |
| `Info/Building/Buildings.cpp` | 10: cancelMorph/cancelConstruction x7, morph(morphType) @ L186 (Lair/Hive/Sunken/Spore), rightClick @ L198, build(Nydus_Canal) @ L209 |
| `Macro/Producing/Producing.cpp` | 3: `train(type)` @ L86 (every larva/unit production), `larva.unit()->stop()` x2 @ L329/337; plus `buildAddon` @ L72 |
| `Macro/Researching/Researching.cpp` | 1: `research(...)` @ L81 |
| `Macro/Upgrading/Upgrading.cpp` | 1: `upgrade(...)` @ L93 |
| `Micro/All/Commands.cpp` | 3: train(Scarab/Interceptor), stop @ L143-149 |
| `Micro/Transport/Transports.cpp` | 1: unload @ L200 |

Conclusion: commands are **mostly funnelled but not fully**. A single metering point requires a
thin `Cmd::` shim and touching ~25 call sites across 8 files (mechanical, sed-able).

---

## 4. Existing learning / opponent-model features (to override) and config files

- **Build learning:** `Builds/All/Learning.cpp`. Per opponent file
  `bwapi-data/read|write/<R>v<R>_<enemyName>_BASIL_2026_1 Learning.txt` (space-separated
  build/opener/transition W L counts) and `... Info.txt` (per-game log line). `getBestBuild()`
  runs UCB1 over allowed tuples (`isComboPossible`, `isComponentPossible` checks wall/pocket
  natural feasibility). `onEnd()` appends W/L. **We override by calling
  `BuildOrder::setLearnedBuild()` after `Learning::onStart()` (or by skipping `getBestBuild()`
  when a directive is pending).** Learning must still be allowed to run as the no-sidecar
  fallback.
- **Opponent model:** `Strategy/Spy/` (`Spy.cpp`, `SpyGeneral/Protoss/Terran/Zerg.cpp`) classifies
  enemy build/opener/transition into the string constants of `Defs.h` and flags
  (`enemyRush()`, `enemyProxy()`, `enemyFastExpand()`, `enemyWalled()`, `Terran::enemyMech()/enemyBio()`).
  These drive reactions in `ZvT()` etc. and the defense tables. We keep them (they are inputs to
  the StateSummary: `enemy_build`, `enemy_opener`, `enemy_transition` are cheap, high-value fields).
- **In-game switches:** `Visuals::onSendText` (`/bo`, `/builds`, `/states`, ...).
- **Config files:** none. No JSON/INI. Everything is compiled in. Logger writes
  `bwapi-data/write/logger.txt` (`Main/Logger.h`, `LOG/LOG_ONCE/LOG_SLOW` macros).

---

## 5. Hook proposal

Common plumbing (new files, no McRave edits): `McRave/Main/Sidecar.h/.cpp` holding

```cpp
namespace McRave::Sidecar {
    struct Directive {                       // mirrors design §4.2
        bool valid = false; int issuedFrame = 0, expiresFrame = 0; std::string id;
        std::string build, opener, transition;              // "" = keep McRave's
        std::map<BWAPI::UnitType,double> unitMix;           // empty = keep
        std::vector<BWAPI::UnitType> techPriority;
        enum class Stance { None, Defensive, Neutral, Aggressive } stance = Stance::None;
        enum class Expand { None, Never, AllowWhenSafe, Now } expand = Expand::None;
        std::optional<int> sunken, spore; std::optional<bool> wallNat;
        std::string objectiveType, objectiveLocation;
    };
    const Directive &current();       // valid only if frame < expiresFrame, else Directive{}
    void onStart(); void onFrame(); void onEnd(bool);
    void onEvent(const char *type, BWAPI::Unit);
}
```

`Sidecar::onFrame()` is called first thing in `McRaveModule::onFrame` (after `Util::onFrame()`):
it swaps the latest directive received by the network thread into `current()` under a mutex, and
every 24 frames serialises + enqueues a StateSummary. Body keeps playing McRave's defaults when
`!current().valid` (design principle 1).

### 5.1 Hook 1 — strategy injection

Minimal-diff strategy: **one `Sidecar::` call at the end of each decision function**, overriding
the `All.h` variables that McRave just computed. Because everything is recomputed per frame, an
expired directive automatically reverts to McRave logic with no state cleanup.

| Directive field | Insertion point (file:function) | What the hook does |
|---|---|---|
| `opening` (build/opener/transition) | `Builds/Zerg/ZergBuildOrder.cpp:740 opener()`, before `if (Players::vT()) ZvT();` | `if (d.valid && !inTransition && !d.build.empty()) setLearnedBuild(d.build, d.opener, d.transition);`. Validate the tuple against `Learning::getBuilds()` (same table the chat command uses). Also in `Learning::onStart()` skip `getBestBuild()` if a pre-game directive is already present. The `ZvT()` reaction block (worker-rush/8rax) may still override; keep that as a safety net or gate it with `!Sidecar::current().hasOpening()`. |
| `unit_mix_target` | `ZergBuildOrder.cpp:847 composition()`, last statement (after the drone/ling fallback) | Replace `armyComposition` with the directive map filtered by `unlockReady(type)`; ensure each requested type is in `focusUnits` (so `getTechBuildings` queues the tech). Untouched: opening one-hot ladder if `inOpening` and directive says `keep_current_plan`. |
| `tech_priority` | `ZergBuildOrder.cpp:767 tech()`, before `for (auto unit : unitOrder)` | `unitOrder = d.techPriority` and skip `switchComposition()` (add `if (d.valid && !d.techPriority.empty()) return;` at top of `switchComposition()`). |
| `stance` | `Micro/Combat/State.cpp:303 updateStaticStates()`, after `updateZStaticStates();` | `Defensive`: push every unlocked combat type into `staticRetreatTypes`; `Aggressive`: `staticRetreatTypes.clear()` (keep workers). `Neutral`: leave. Additionally set `All::pressure = (stance==Aggressive)` at the end of `opener()` so `isPressure()` consumers (defense tables, Goals) align. |
| `army_objective.location` | `Micro/Combat/Combat.cpp:91 findDefendPosition()` end; `:43 findAttackPosition()` end | Map the location name (from map knowledge) to a BWEB station/choke and overwrite `defendNatural/holdNatural/defendPosition` or `attackPosition`. |
| `expand_policy` | `ZergBuildOrder.cpp:356 queueExpansions()`, after `expandDesired` is computed and before `buildQueue[Zerg_Hatchery] = max(...)` | `Never` → `expandDesired = false; wantNatural = wantThird = false` (also caps `buildQueue[Zerg_Hatchery]` to `hatchCount()`); `Now` → `expandDesired = true` (works even while `inOpening` if the block's `if (!inOpening)` is loosened for the directive case). |
| `static_defense {sunken, spore}` | `Map/Walls/Walls.cpp needGroundDefenses/needAirDefenses` and `Map/Stations/Stations.cpp:616/:649` (top of each) | `if (d.sunken) return *d.sunken - currentCount;` (wall for natural, station for others). This keeps BWEB placement and `queueDefenses()` unchanged. |
| `wall_natural` | `Builds/All/BuildOrder.cpp:24 updateBuild()`, after `Zerg::opener()` | `if (d.wallNat) wallNat = *d.wallNat;` (single line; walls already exist from `Walls::onStart`). |

Snippet, opening injection point (copied surroundings):

```cpp
// ZergBuildOrder.cpp:757
        zergUnitPump.clear();
        // [HOOK1] Sidecar::applyOpening();  // sets currentBuild/Opener/Transition if !inTransition
        if (Players::vT())
            ZvT();
        else if (Players::vP() || againstRandom)
            ZvP();
```

Snippet, stance injection point:

```cpp
// Combat/State.cpp:303
    void updateStaticStates()
    {
        staticRetreatTypes.clear();
        updatePStaticStates();
        updateTStaticStates();
        updateZStaticStates();
        // [HOOK1] Sidecar::applyStance(staticRetreatTypes);
        // Workers
        for (auto type : {Protoss_Probe, Terran_SCV, Zerg_Drone}) {
```

Snippet, expansion policy:

```cpp
// ZergBuildOrder.cpp:399
                buildQueue[Zerg_Hatchery] = max(buildQueue[Zerg_Hatchery], hatchCount() + expandDesired);
                // [HOOK1] Sidecar::applyExpandPolicy(expandDesired, wantNatural, wantThird, buildQueue);
```

Snippet, static defense:

```cpp
// Stations.cpp:616
    int needGroundDefenses(const BWEB::Station *const station)
    {
        // [HOOK1] if (auto n = Sidecar::current().sunkenFor(station)) return *n - getGroundDefenseCount(station);
        if (BuildOrder::isRush() || BuildOrder::isPressure() || Spy::getEnemyTransition() == P_Carrier || isPocket(station))
            return 0;
```

Total McRave edits for Hook 1: ~8 one-line insertions + 2 new files.

### 5.2 Hook 2 — state summary emission

- `McRave/Main/McRave.cpp onFrame()`: insert `Sidecar::onFrame();` right after `Util::onFrame();`
  (poll directive) and `Sidecar::emitIfDue();` right before `Visuals::onFrame();` (after all
  managers updated, so `BuildOrder::getCurrentBuild()`, `Combat::getAttackPosition()`,
  `Spy::getEnemyBuild()`, `Stations::getStations(...)`, `Players::getTotalCount(...)`,
  `Units::getUnits(PlayerState::Enemy)` and Horizon sim values are fresh).
- Events: `McRave/Main/Events.h` `onUnitDiscover` / `onUnitDestroy`:

```cpp
    inline void onUnitDiscover(BWAPI::Unit unit)
    {
        BWEB::Map::onUnitDiscover(unit);
        Players::storeUnit(unit);
        Planning::onUnitDiscover(unit);
        // [HOOK2] if (unit->getPlayer() == Broodwar->enemy() && unit->getType().isBuilding()) Sidecar::onEvent("enemy_building_spotted", unit);
```

  Engagement start/end: derive in `Sidecar::emitIfDue()` from `Units::enemyThreatening()` and
  the count of self units with `LocalState::Attack` (edge-detect), no extra hook needed.
- `onEnd(bool)`: `Sidecar::onEnd(isWinner)` to flush the `result` line.
- Data sources for §4.1 fields: `Broodwar->self()->minerals()/gas()/supplyUsed()`, `vis()/com()/total()`
  helpers (`Main/Common.h`), `Players::getTotalCount/getVisibleCount(PlayerState::Enemy, type)`,
  `Stations::getStations(PlayerState::Enemy).size()`, `Spy::getEnemyBuild/Opener/Transition()`,
  `BuildOrder::getCurrentBuild()`, `Combat::getAttackPosition()`, cluster `avgPosition`
  (`Combat::Clusters::getClusters()`), `UnitInfo::getSimValue()` averaged over clusters for
  `combat_sim`.

**Threading concerns.** McRave has zero threads, mutexes or async code; every BWAPI call happens
on the BWAPI-driven main thread, and BWAPI itself is not thread-safe. Therefore:
1. Build the JSON string entirely on the main thread (cost: a few hundred µs per second of game).
2. Push the string to a `std::mutex`-guarded queue; a single `std::thread` started in
   `Sidecar::onStart()` does the loopback HTTP POST (blocking socket, 100 ms timeout) and parses
   the response into a `Directive` stored in a second mutex-guarded slot.
3. Main thread only ever does `try_lock`/swap; never waits. On thread death or connect failure,
   `valid=false` → McRave defaults.
4. Join/stop the thread in `onEnd` (and guard `DLL_PROCESS_DETACH` on Windows).
HTTP client: a header-only lib (e.g. cpp-httplib) or 60 lines of POSIX/Winsock code; both fine
under MIT. Requires the Linux build to link `-pthread`.

### 5.3 Hook 3 — command metering / limiting

Two levels:

- **Metering only (zero McRave edits):** in `Sidecar::emitIfDue()` iterate
  `Broodwar->self()->getUnits()` and count units whose `getLastCommandFrame() == frame` (or
  track per-unit `commandHistory` already kept in `UnitInfo::update()` @ `UnitInfo.cpp:70`).
  Good enough for APM logging.
- **Limiting (token bucket):** introduce `McRave/Main/Cmd.h` with inline forwarding functions
  (`Cmd::train(UnitInfo&, UnitType)`, `Cmd::morph`, `Cmd::build`, `Cmd::research`, `Cmd::upgrade`,
  `Cmd::gather`, ..., returning `bool`), each of which increments the counter, consults the APM
  profile, logs, then calls the BWAPI method. Then:
  1. Replace the bodies of the 6 `UnitInfo::setCommand` overloads (`UnitInfo.cpp:621-720`) to call
     `Cmd::` — this alone covers all micro (move/attack/kite/retreat/hold/burrow/spells).
  2. Replace the ~25 raw call sites listed in §3.1 (Producing, Buildings, Researching, Upgrading,
     Specials, Transports, Commands) with `Cmd::` equivalents. Mechanical.
  Policy recommendation: apply the token bucket only to `Role::Combat` micro commands and
  worker gather/return spam; **never drop** train/morph/build/research/upgrade/cancel (defer them
  to the next frame instead), otherwise macro breaks. Note `setCommand` already suppresses
  identical repeats within 6 frames, so the raw command rate is already moderate.

Snippet, the one place all micro goes through:

```cpp
// Info/Unit/UnitInfo.cpp:621
    void UnitInfo::setCommand(UnitCommandType cmd, Position here)
    {
        ...
        commandFrame    = Broodwar->getFrameCount();
        commandPosition = here;
        commandType     = cmd;
        // Send a new command
        if (cmd == UnitCommandTypes::Move) {
            here = getOvershootPosition(this, here);
            unit()->move(here);                 // [HOOK3] -> Cmd::move(*this, here)
        }
```

---

## 6. Risks and estimates

**Size/tangling.** Strategy is spread over `Builds/` (48 files, ~5k LOC; Zerg alone
`ZergBuildOrder.cpp` 1118 + `ZvT/ZvP/ZvZ` ~1.5k), `Strategy/Spy` (~1.3k), `Combat/State.cpp`
(687), `Walls/ZergWalls.h` (336), `Stations.cpp` defense tables. It is heavily heuristic and
interdependent through the `All.h` globals, but the "recompute every frame from globals" design
means overrides are local and revert automatically. Main risks:

1. Directive/heuristic conflicts: e.g. directive says `stance=aggressive` while Spy's
   `lingsNeeded_ZvT()` still pumps lings, or `expand=never` while a transition table hard-codes
   `buildQueue[Zerg_Hatchery] = 3`. Mitigation: override *after* McRave, clamp queues, log diffs.
2. Composition override only works for unlocked tech; a directive asking for hydras with no den
   must go through `focusUnits` → `getTechBuildings()`, which takes minutes. Validator must
   check tech tree (already planned).
3. `inTransition` freezes opening changes; changing the *transition* string mid-transition
   (e.g. 2HatchMuta → 3HatchMuta) is safe (both read `currentTransition` each frame) but
   changing the *build* after `transitionReady` will produce nonsense; restrict to `!inTransition`
   or transition-only edits.
4. Linux port: needs a CMake file and the ~6 conformance fixes lukecameron listed; MSVC-only
   template laxity may surface more errors under GCC than under Clang with delayed parsing.
5. Hook 3 token bucket can degrade micro badly; ship metering first, limiting behind a flag.

**Estimates (engineering hours, excluding the Linux port itself which is ~8-16 h):**

| Item | Hours |
|---|---|
| Sidecar plumbing: `Directive` struct, JSON parse (tiny parser or nlohmann single header), poll/expiry, logging | 4 |
| Hook 1a opening + wall + Learning bypass | 3 |
| Hook 1b unit mix + tech priority | 4 |
| Hook 1c stance + objective location (needs playtesting) | 6 |
| Hook 1d expand policy + static defense | 4 |
| Hook 2 StateSummary serialisation (all §4.1 fields, combat_sim, events) | 6 |
| Hook 2 network thread (HTTP POST, timeouts, lifecycle) | 4 |
| Hook 3 metering (post-hoc) | 1 |
| Hook 3 `Cmd::` shim + replace 25 sites + token bucket + profile config | 6 |
| **Total** | **~38 h** (~1 week), comfortably inside the 2-week Phase 0 budget in design §3.1 |
