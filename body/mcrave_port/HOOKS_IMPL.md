# McRave hooks 1-3: implementation notes

Implements `body/HOOKS.md` section 5 on McRave @ `7d1719a2` as two extra patches on top of the
Linux port (`body/patches/mcrave/0006-sidecar-files.patch`, `0007-hooks.patch`; `0007-hooks.patch (economy-lever call sites folded in)` adds the
`drone_target` call sites, see "Economy lever"). Status
(2026-10-01): builds with zero errors (`ninja -C build/mcrave`, 114 TUs, `-Wl,--no-undefined`),
verified pristine -> `apply_patches.sh` -> rebuild gives an identical symbol table; **not run in a
game** (no MPQ data in this container).

## Files

| File | Role |
|---|---|
| `third_party/mcrave/Source/McRave/Main/Sidecar.h` (new, 0006) | light header: lifecycle + `apply*()` entry points, forward-declares `Directive` so no McRave TU but Sidecar.cpp sees httplib/json |
| `third_party/mcrave/Source/McRave/Main/Sidecar.cpp` (new, 0006) | owns one `SidecarClient` + `StateTracker` (from `body/sidecar_client/`), config, opening table, all hook logic |
| `body/sidecar_client/StateTracker.hpp` | +3 public json members `combatSim`, `bodyDefaults`, `metrics`, emitted as `combat_sim`, `body_defaults`, `metrics` |
| `body/mcrave_port/CMakeLists.txt` | +`SC_AI_SIDECAR_CLIENT_DIR` include dir (`body/sidecar_client`, which holds `third_party/httplib.h`, `json.hpp`); `Threads::Threads` was already linked |
| 7 McRave files (0007, 35 changed lines) | one-line calls listed below |

`apply_patches.sh` needed no change: 0006 is an intent-to-add diff (`git add -N`), which `git apply`
creates and `--reverse` deletes; the "already applied" reverse-check works for both patches and
the two patches do not overlap any hunk of 0001-0005 (the wall override deliberately lives in
`updateDefenses()`, not next to the 0005 hunk at `Walls.cpp:355`).

## Configuration (body plays without the sidecar by default)

`Sidecar::onStart()` reads, in this order:

1. `bwapi-data/sidecar.ini` (relative to the BWAPI working directory, same place as McRave's
   learning files). Presence enables the sidecar. Keys: `host` (127.0.0.1), `port` (8770),
   `every` (24 frames), `timeout_ms` (2000), `enabled` (`0`/`false` disables).
2. Environment `SIDECAR_HOST` / `SIDECAR_PORT`: either one enables the sidecar and overrides the ini.

Without both, `Sidecar::enabled()` is false and every function is a no-op (no thread, no socket,
no JSON). With the sidecar enabled but unreachable, `SidecarClient` fails the POST in its own
thread, `directive()` stays empty, and McRave plays its defaults (design principle 1). The game
thread never waits on HTTP: `SidecarClient::onFrame` only swaps a string under a mutex.

Log lines go to McRave's `bwapi-data/write/logger.txt` (prefix `Sidecar:`); the current directive
id/stance/expand/expiry is drawn at screen (432,46), next to McRave's build line.

## Hook 2: lifecycle and state emission (`Main/McRave.cpp`)

| McRave point | Call | What |
|---|---|---|
| `onStart()` after `Util::onStart()` | `Sidecar::onStart()` | read config, construct tracker + client (starts the POST thread, `game_id = <time>_<map>_<seed>`) |
| `onFrame()` after `Util::onFrame()` | `Sidecar::onFrame()` | copy latest directive from the client; drop it unless `valid(frame)` (`frame <= expires_frame`); log on id change |
| `onFrame()` before `Visuals::onFrame()` | `Sidecar::emitIfDue()` | hook-3 metering, `tracker.update()` (enemy memory, events), every 24 frames or on pending events fill `combat_sim`/`body_defaults`, then `client.onFrame(tracker)` posts `/state` |
| `onUnitDiscover` | `Sidecar::onUnitDiscover` | no-op (first-seen enemy buildings are detected by `StateTracker::update()`) |
| `onUnitDestroy` (before `Events::onUnitDestroy`) | `Sidecar::onUnitDestroy` | tracker building-count decrement; event `my_building_lost` for own buildings |
| `onEnd(bool)` after `Learning::onEnd` | `Sidecar::onEnd(isWinner)` | POST `/game/end?game_id=` with `win|loss`, join thread, free client |

`combat_sim` (from `Players::getStrength` and Horizon per-unit sim): `my_strength`,
`enemy_strength`, `my_army_vs_seen` (ratio, only when enemy > 0), `my_ground_to_ground`,
`enemy_ground_to_ground`, `enemy_air_to_ground`, `sim_win_fraction`, `sim_value_mean`,
`global_attack_frac` (over `Role::Combat` units), `enemy_threatening`.
`body_defaults`: `build`, `opener`, `transition`, `opening` (`B/O/T`), `stance`
(`all_in|aggressive|defensive` from McRave's rush/pressure flags), `expand`, `wall_natural`,
`in_opening`, `enemy_build/opener/transition` (Spy). All strings, matching `StateSummary.body_defaults: dict[str,str]`.
`intel` (`Sidecar::fillIntel()`, same cadence, `StateSummary.intel` / `schemas.Intel`): the scouting brief for the
Strategy LLM. `enemy_build/opener/transition` + `*_state` (`unknown|possible|likely`, from Spy's name and
likely-time), `flags` (Spy `likely` strats: expand, rush, proxy, possible_proxy, gas_steal, pressure, wall, greedy,
invis, detection, turtle, fortress), `mirror` (ZvZ pool/speed vs ours, `terran_style`), `workers_pulled`,
`buildings{name: count, first_seen_frame, started_frame/time, completes_frame/time}` (start/complete are McRave's
`UnitInfo::frameStartedWhen/CompletesWhen` health-based estimates, the same numbers Spy logs as "starts at", merged
across frames so destroyed buildings keep their timings), `workers_seen_max`, `gas{count, first_seen_*}`,
`expansions` (max of `Stations` enemy stations and seen town halls), `scout{enemy_main_found, main/natural_scouted_*
(first frame `Stations::isBaseExplored`), full_scout, scout_denied, main/natural_last_seen_frame (`Stations::lastVisible`)}`,
`army{first_seen_*, max_by_type}`. Spy's `enemy*Time()` accessors are declared but not defined upstream and are not used.
`resolveOpening()` also accepts McRave native names (`PoolHatch/12Pool/2HatchMuta`, `2HatchMuta`, `HatchPool/12Hatch`),
matched per '/'-part against `Learning::getBuilds()`.

## Hook 1: strategy injection, exact insertion points

All overrides run after McRave computed its value for the frame and return immediately when
`directive()` is empty. Globals are McRave's `BuildOrder::All` inline variables (recomputed each
frame), so expiry needs no cleanup. The only sticky effect is `setLearnedBuild` (build strings
are not reset per frame by McRave either).

| Directive field | File:function, line inserted | Behaviour |
|---|---|---|
| `opening` | `Builds/Zerg/ZergBuildOrder.cpp opener()`, after `zergUnitPump.clear()`, before `if (Players::vT()) ZvT()` -> `Sidecar::applyOpening()` | map name via the table below, validate against `Learning::getBuilds()` (same table as the `/bo` chat command and UCB1), `setLearnedBuild(build, opener, transition)`. Build/opener change only while `!inTransition`; transition-only change while `inOpening`; nothing once `!inOpening`. Unknown or disallowed name: one log line, no override. McRave's reaction block (worker rush / 8rax / proxy) stays as a safety net and may still override. |
| `wall_natural`, `stance=all_in` | `Builds/All/BuildOrder.cpp updateBuild()`, after `Zerg::opener()` -> `Sidecar::applyBuildFlags()` | `wallNat = (wall_natural != "none")` (walls already exist from `Walls::onStart`); `all_in` also sets `pressure = true`. Zerg only. |
| `tech_priority` | `ZergBuildOrder.cpp tech()`, before the `for (auto unit : unitOrder)` loop -> `Sidecar::applyTechPriority()`; `switchComposition()` top -> `if (Sidecar::techPriorityActive()) return;` | army unit names in the list become `unitOrder` (McRave's tech path); upgrade/building names (`metabolic_boost`, `lair`) are ignored (McRave's `queueUpgrades`/`getTechBuildings` keep handling them). Empty result: no override and `switchComposition` runs as usual. |
| `unit_mix_target` | `ZergBuildOrder.cpp composition()`, last statement -> `Sidecar::applyComposition()` | `armyComposition` = requested weights for types with `unlockReady()`; not-yet-unlocked types are inserted into `focusUnits` so `getTechBuildings()` queues their tech. Skipped while `inOpening && keep_current_plan` (leaves the book's one-hot ladder). Unknown names logged once. |
| `expand_policy` | `ZergBuildOrder.cpp queueExpansions()`, after `buildQueue[Zerg_Hatchery] = max(...)` (inside `if (!inOpening)`) -> `Sidecar::applyExpandPolicy(hatchCount())` | `never`: `expandDesired=false`, `wantThird=false`, `wantNatural=false` once 2 stations, hatchery queue capped to `hatchCount()`. `greedy`: when no hatchery is in progress and <=5 mining stations, `expandDesired=true`, queue `hatchCount()+1`, `wantNatural/wantThird` by station count. `allow_when_safe`: McRave. Inert during the opening book (the opener's hatch count is the validator's job). |
| `stance` | `Micro/Combat/State.cpp updateStaticStates()`, after `updateZStaticStates()` -> `Sidecar::applyStance(staticRetreatTypes)` | `defensive`: every unlocked Zerg army type is pushed into `staticRetreatTypes` (global retreat). `aggressive`/`all_in`: `staticRetreatTypes.clear()` (workers are re-added by the lines that follow). `neutral`: McRave. `pressure` is set only for `all_in` (see above), because `isPressure()` also zeroes static defenses. |
| `army_objective` | `Micro/Combat/Combat.cpp onFrame()`: after `findAttackPosition()` -> `Sidecar::applyAttackPosition(attackPosition)`; after `findDefendPosition()` -> `Sidecar::applyDefendPosition(defendNatural, holdNatural, defendChoke, defendArea, defendPosition, defendStation)` | type `attack|contain|harass` + `enemy_main|enemy_natural`: `attackPosition = station->getResourceCentroid()` only if that station is enemy-owned (else McRave's target). type `defend|hold` + `natural`: natural choke/area/`Stations::getDefendPosition` only if we own the natural; `main`: main choke. Other locations: no override (coordinates stay body-side). |
| `drone_target {total, priority, override_opening}` | `ZergBuildOrder.cpp composition()`: last statement after `Sidecar::applyComposition()`, and before the `return` of the `if (inOpening)` branch (0008) -> `Sidecar::applyDroneTarget()` | Economy lever, see "Economy lever" below. `total<=0` or absent: no override. Inert while `inOpening` unless `override_opening=true`. |
| `static_defense {sunken, spore}` | `Map/Walls/Walls.cpp updateDefenses(wall)` (feeds `needGroundDefenses/needAirDefenses(wall)`) and `Map/Stations/Stations.cpp needGroundDefenses/needAirDefenses(station)` top | desired count minus current count, for the **natural only**: the natural wall if McRave built one, otherwise the natural station. Main/third stations keep McRave's tables. BWEB placement and `queueDefenses()` are untouched. |

### Opening-name mapping (`Sidecar.cpp openingTable`)

Names are lower-cased, spaces/hyphens -> `_`. Empty cell = keep McRave's current value; after a
build change, a kept transition that the new build does not allow becomes the first allowed one.
Allowed tuples per matchup come from `Learning::zergBuildMaps()` (ZvT: PoolHatch{Overpool,12Pool}
x{2HatchMuta,3HatchMuta}, HatchPool{11Hatch,12Hatch,3Hatch}x{2HatchMuta,3HatchMuta}; ZvP adds
3/4/6HatchHydra and drops 12Pool/3Hatch; ZvZ: PoolHatch{12Pool,Overpool}x{2HatchMuta},
PoolLair{9Pool,Overpool,Gaspool}x{1HatchMuta}).

| Directive `opening` | build | opener | transition |
|---|---|---|---|
| `12hatch_11pool`, `12hatch` | HatchPool | 12Hatch | keep |
| `11hatch` / `10hatch` / `9hatch` | HatchPool | 11Hatch / 10Hatch / 9Hatch | keep |
| `3hatch`, `3hatch_before_pool` | HatchPool | 3Hatch | keep |
| `overpool` | PoolHatch | Overpool | keep |
| `12pool` | PoolHatch | 12Pool | keep |
| `9pool`, `9pool_speed`, `gaspool`, `4pool` | PoolLair | 9Pool / 9Pool / Gaspool / 4Pool | keep (PoolLair is only allowed in ZvZ, so these are rejected and logged in ZvT/ZvP) |
| `1hatch_muta` / `2hatch_muta` / `3hatch_muta` | keep | keep | 1HatchMuta / 2HatchMuta / 3HatchMuta |
| `2hatch_hydra` / `3hatch_hydra` / `4hatch_hydra` / `6hatch_hydra` | keep | keep | 2/3/4/6HatchHydra |
| `1hatch_lurker`, `lurker_contain` / `2hatch_lurker` | keep | keep | 1HatchLurker / 2HatchLurker |
| `2hatch_speedling` / `3hatch_speedling` | keep | keep | 2HatchSpeedling / 3HatchSpeedling |

Unit names for `unit_mix_target`/`tech_priority`: StateTracker's normalised BWAPI names
(`zergling`, `hydralisk`, `mutalisk`, `lurker`, `scourge`, `ultralisk`, `defiler`, `guardian`,
`devourer`, `queen`, `drone`) plus aliases `ling(s)`, `muta(s)`, `hydra`, `ultra`.

## Hook 3: command metering (no McRave edits, no limiting)

`Sidecar::emitIfDue()` runs every frame and counts own units whose `getLastCommandFrame()` equals
the current frame (covers `UnitInfo::setCommand` and the ~38 raw BWAPI calls alike). Emitted as a
top-level `metrics` object (ignored by the pydantic `StateSummary`, kept in the raw JSONL log):
`commands_this_frame`, `commands_total`, `apm_60s` (commands in the last 1440 frames, scaled
before the first minute), `apm_game`. Nothing is throttled.

## Untested (no MPQ data here)

- No game has run: the sidecar thread, `/state` POST cadence, directive parsing on the body side,
  screen drawing and every `apply*()` are compile-verified only. `SidecarClient`/`StateTracker`
  were exercised earlier by `body/sidecar_client/probe_module` in a different session only.
- Whether `Unit::getLastCommandFrame()` is populated by OpenBW the same way as BWAPI 1.16.1
  (if it is always 0 the metrics read 0; nothing else depends on it).
- Learning bypass: `Learning::onStart()` still runs UCB1; a pre-game directive cannot exist yet
  (the first `/state` goes out at frame 0 and the answer arrives asynchronously), so the opening
  is switched by `applyOpening()` on the first valid directive instead (safe while `!inTransition`).
- Interaction risks listed in HOOKS.md section 6 (directive vs Spy reactions, `never` vs a
  transition's hard-coded hatch count) are mitigated by overriding after McRave and clamping, but
  need playtesting; stance `defensive` is the schema default and does hold the whole army home
  while a directive is valid.
- Windows/VS build of `Sidecar.cpp` (uses `getenv`, `<thread>`; cpp-httplib needs Winsock
  linking there) is unverified.

## Test plan once game data exists

1. `python -m bot.sidecar.server --config config/sidecar.yaml --llm fake` (listens on
   127.0.0.1:8770).
2. Build and point BWAPILauncher at `build/mcrave/McRave.so` (docs/setup_openbw.md section 5)
   with `SIDECAR_PORT=8770` in the environment (or drop `bwapi-data/sidecar.ini` with `port=8770`).
3. Expect, in order:
   - `bwapi-data/write/logger.txt`: `Sidecar: enabled, 127.0.0.1:8770 every 24 frames, game_id ...`.
   - Sidecar JSONL log (`logs/games/<game_id>.jsonl`): a `state` line every 24 frames
     (`frame` increases by 24), `me.units.drone` = 4 at frame 0 growing, `metrics.commands_total`
     increasing, `body_defaults.opening` = `HatchPool/12Hatch/2HatchMuta` (ZvT default) and
     `combat_sim.my_strength` > 0 once lings exist.
   - A directive id (`d-0001`) drawn on screen at (432,46) in green and
     `Sidecar: directive d-0001 opening=12hatch_11pool stance=defensive ...` in logger.txt; the
     fake backend emits that opening, so the build line next to it should read
     `HatchPool: 12Hatch 2HatchMuta` from the first directive on.
   - When the directive expires (no new one), the screen line turns grey (`no directive`) and
     McRave's own stance/expansion logic resumes.
   - On game end: one `/game/end` POST (sidecar `result` line) and
     `Sidecar: game end, win|loss, posts N failed 0`.
4. Negative test: start the game with no sidecar process; expect `posts 0/N` failed on screen,
   no stalls (frame time unchanged), and the game to finish normally.
5. Only then run `python -m eval.run_eval ... --runner openbw` and `eval.compare` per CLAUDE.md
   before adopting any change to the opening table or the apply rules.


## Playtest notes (2026-10-01)

- Verified in real OpenBW games (single player and 2-process LAN): state posts every 24 frames, directive drawn/logged, `/game/end` received, replay saved.
- `applyOpening()` now applies **once per directive id**. Per-frame application fought McRave's scouting reaction (2Rax -> PoolHatch/Overpool) every frame (2,059 log lines in one game). The body stays reactive; the next directive re-decides.
- `Game::getRandomSeed()` throws on the OpenBW fork; the client uses the pid for the game id instead.

## Audit items A/B/C/E on the body side (2026-10-01)

All new keys are filled on emit frames only (every `every` frames or when events are pending); the per-frame work is the
loss window (item C) and the override recording inside the hooks. No existing key changed.

### A. Positions as named regions (`Sidecar.cpp buildRegions()/regionName()`, `Sidecar::regionNameFor(Position)`)

`"regions": {name: {"tile": [x, y], "owner": "me|enemy|none"}}` is emitted in every post. Names: `main`, `natural`, `third`,
`fourth` (McRave `Expansion::getExpandOrder()` after main/natural; before it exists, the closest stations by ground distance
from the natural), `enemy_main`, `enemy_natural`, `enemy_third` (first other enemy station), `center` (BWEM map center),
`path_mid` (center of the middle chokepoint of the BWEM path main -> enemy main). Built on the first emit frame (McRave's
Terrain/Stations/Walls are initialised *after* `Sidecar::onStart`) and refreshed on every emit (owners, enemy_* once scouted).
`regionNameFor(p)` = nearest named region within 12 tiles, else `unknown_area_<BWEM area id>`. The tracker gets this as
`StateTracker::regionNamer` and uses it for `me.army_region` (own army centroid) and `enemy.army_region_seen` +
`enemy.army_last_seen_time` (centroid of the visible enemy army the last time any was visible, from `StateTracker::update()`).

`me.bases[]` (`fillMyBases()`): `{name, workers_minerals, workers_gas, mineral_patches, gas_geysers, saturation (=
workers_minerals / (2 * patches), capped 1.0), hatcheries}` from `Resources::getMyMinerals()/getMyGas()` gatherer counts per
`ResourceInfo::getStation()`; hatcheries = own resource depots within 10 tiles of the station. `me.production`:
`{"in_progress": {type: count}, "larva": n}` from eggs/cocoons/lurker eggs (`getBuildType()`), morphing and incomplete buildings.

`intel.buildings[type].positions[]`: `{region, tile, progress (0..1; from `getRemainingBuildTime()` while visible, 1.0 when
completed, else McRave's start/complete estimate), completes_time ("m:ss", "?" once completed or unknown), last_seen_time}` for every
enemy building McRave still remembers (`Units::getUnits(Enemy)`, keyed by BWAPI unit so unseen buildings keep their last state).
`intel.enemy_bases[]`: `{region, workers_seen_max, last_seen_time, hatcheries, owner}` per McRave enemy station; workers are
visible enemy workers within 10 tiles on emit frames (max kept), hatcheries = remembered enemy depots within 10 tiles.

### B. Execution feedback (`execution.overrides[]`, `execution.results`)

Each `apply*()` records what it did on its frame with `recordOverride(field, applied, before, after, note)`:
`opening` (tuple before/after, notes: no allowed build / transition already started / already current / opening book finished),
`wall` (`none|natural_wall`), `tech_priority` (unitOrder list), `unit_mix` (armyComposition `type:weight,...`, note lists units
whose tech was queued instead), `expand_policy` (`expand|hold,hatch_queue=n`), `stance` (`retreat_types=...`), `objective`
(region of attack/defend position before -> `type@location`), `static_defense` (`sunken have=n` -> `want=m`; one entry per key,
or `applied=false` when we hold neither the natural wall nor the natural). Statuses persist for the directive id and are cleared
when the id changes (or the directive expires / is observe-only, so `--strategy fixed` posts an empty list). One McRave log line
(`Sidecar: override <field> applied|not applied: before -> after (note)`) is written only when a field's before/after/note changes.
`results`: `{sunken, spore (built or morphing), army_actual {type: count}, drones, drone_delta_since_directive}` (drones at the
frame the directive id was first seen). `goals` stays `[]`.

### C. Engagement events (`updateEngagement()`, every frame, from `onUnitDestroy`)

Own and enemy unit losses (mineral+gas value, halved for two-per-egg types; larva/eggs skipped) go into a 240-frame sliding window.
When the window total first exceeds 150, event `engagement_start` (`what` = region of the losses' centroid, `detail = {my_losses,
enemy_losses, my_value, enemy_value}`). After 120 frames without a loss: `engagement_end` with the engagement totals, `ratio`
(enemy value / my value), `outcome` (`lost` < 0.7, `won` > 1.4, else `even`), `start_frame`, `end_frame`. Both go through
`StateTracker::pushEvent(type, what, detail)` (events now carry an optional `detail` object) and trigger an immediate post.

### E. Map dump: `SC_AI_MAP_DUMP=<path>`

On the first `emitIfDue()` (frame 0, all managers initialised, sidecar not required) writes a JSON with `map`, `map_file`,
`size_tiles`, `start_locations`, `our_start_tile`, `regions` (`{name: [x, y]}`, the converter's format) + `regions_detail`
(`{name: {tile, owner}}`), `bases[]` (`tile` = BWEM hall location, `center_tile`, `minerals`, `minerals_total`, `gas`, `gas_total`,
`isStart`, `is_main`, `is_natural`, `area_id`, `region`, `owner`, `ground_distance_from_main` px, BWEB `defense_tiles`), `chokes[]`
(`center`/`center_tile`, `width` px + `width_tiles`, `areas`, `blocked`, `is_main_choke`, `is_natural_choke`, `region`),
`wall_natural`/`wall_main` (full BWEB wall: raw building list, large/medium/small tiles, openings, defense tiles by row,
`zergling_tight: null` because BWEB keeps tightType/requireTight private; McRave creates Zerg natural walls with
`tight=false, openWall=true`, reported as `open_wall: true`), the converter's `natural_wall` (`buildings`, `tiles`,
`zergling_tight: false`), `natural_defenses` (flat tile list: natural station defenses then the wall's first defense row),
`natural_detail` (pocket defense, defend position) and McRave's `expand_order`; then `leaveGame()`. Converter:
`python -m tools.map_knowledge_from_dump <dump> [--out ...]` -> `knowledge/maps/<map>.json` (human review before adoption).
Reference dump: `eval/results/map_dump_fighting_spirit.json` (git-ignored; 14 bases, 29 chokes, natural wall hatchery+evo).
The regions in a dump are for the start position the dumping game happened to get.

### Debug: `SC_AI_DUMP_STATE=<path>`

`SidecarClient` appends every posted StateSummary as one JSON line (written by the POST thread, not the game thread), so the
payload can be checked without the sidecar. `tools/run_game_openbw.sh` forwards `SC_AI_DUMP_STATE` and `SC_AI_MAP_DUMP` to our
side only (and unsets them for the opponent), like the other `SC_AI_*` variables.

## Economy lever: `drone_target` (2026-10-01, patch 0008)

Why: the first ZvZ A/B (docs/eval_log.md) showed the LLM cannot move the economy. `unit_mix_target: {drone: 0.6}` is applied to
`armyComposition`, but McRave's droning is decided by its own ladder and saturation checks, and a 0.6 weight competes with army
units on `Producing::scoreUnit()` (= `percentage / trained count`), so with 20 drones and 8 mutas the muta always wins.

### How McRave drones (what the lever overrides)

Outside the opening book, `Builds/Zerg/ZergBuildOrder.cpp composition()` (every frame, from `BuildOrder::updateBuild()`):

1. `switchComposition()` then a per-transition `priorityOrder` ladder (`{Drone, 30}, {Muta, 16}, {Drone, 45}, ...`): the first
   entry whose count is not reached becomes the one-hot `armyComposition`; a `Drone` entry is "available" only while
   `!Resources::isMineralSaturated() || !Resources::isGasSaturated()`, so once saturated the ladder skips to army.
2. Fallback when nothing was picked or gas is 0: lings if `zergUnitPump[Zergling]` / `vis(Drone) >= droneCap(60)` / saturated,
   else drones.
3. `unlocks()` turns every `armyComposition` key with weight > 0 into `unlockedType`; `Producing::isSuitable()` refuses anything
   else, and `Producing::updateLarva()` scores the remaining larva types by `getCompositionPercentage(type) / trained`.
4. Hard cap in `Producing::validLarva()`: no drone from a larva whose closest station has `getSaturationRatio() >= 2.0`
   (unless workers can be transferred). This is a physical limit the lever does not remove.

Inside the opening book the same function returns early after the `zergUnitPump` one-hot (the opener files set
`zergUnitPump[Zerg_Drone]`), so droning there is the book's business.

### What `applyDroneTarget()` does (`Main/Sidecar.cpp`, called as the last step of both branches of `composition()`)

With `d = directive()`, `target = drone_target.total`, `current = vis(Zerg_Drone)`:

- `target <= 0`: nothing. `inOpening && !override_opening`: `recordOverride("drone_target", false, ..., "opening book")`, nothing.
- `current >= target`: `armyComposition.erase(Drone)`; if no army entry remains and the pool is done, `Zergling = 1.0`
  (McRave's own fallback shape). Droning stops on the next larva because `unlocks()` no longer unlocks `Zerg_Drone`.
- `current < target`, by `priority`:
  - `economy`: `armyComposition = {Drone: 1.0}` (one-hot, like the opening book's drone pump): every larva becomes a drone
    until the target, or the 2.0 station saturation cap, is hit.
  - `balanced` (default): `armyComposition[Drone] = 1.0` next to McRave's picks; the `Zergling` entry is dropped when it is the
    only army entry (McRave's "lings when saturated" fallback), tech units from the ladder stay. `scoreUnit()` then prefers
    whichever type is rarer relative to its weight, and gas-starved tech units score -1, so larva alternate between drones and
    the tech unit instead of all-lings.
  - `army`: McRave's composition stays; drones are only forced when it requests no army type (i.e. the lever only acts as a
    cap plus "drone when idle").

Execution feedback: field `drone_target`, before = McRave's composition, after = the composition applied, note =
`below target by n, priority p` / `target reached, droning stopped` / `opening book (override_opening=false)`. The Python
ledger prints `목표 N` next to the drone count in the feedback section.

Interactions: `unit_mix_target` with a `drone` weight is applied first (`applyComposition()`), `drone_target` then owns the
drone entry. `expand_policy=never` plus a high target saturates to 2.0 per station and stops; `greedy` plus `economy` is the
"drone up" combination. Nothing in Workers/Resources is touched: gas worker counts (`gasLimit = drones/3..5`) and station
transfers stay McRave's.

Patch: `0007-hooks.patch (economy-lever call sites folded in)` = the two `Sidecar::applyDroneTarget();` lines in `ZergBuildOrder.cpp composition()` (on top of
0007); the function itself is in 0006 (`Sidecar.h/.cpp`). `apply_patches.sh` picks it up by the `NNNN-*.patch` glob.
Built in `build/mcrave_econ` (not in a game yet).
