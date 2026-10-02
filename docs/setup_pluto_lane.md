# Pluto lane: real StarCraft 1.16.1 + BWAPI 4.4.0 under Wine

Why a second lane: Pluto (tscmoo, CoG 2026 winner, self-play RL, binary-only) ships as a 32-bit BWAPI 4.4.0
module for the Windows game (`pluto.dll` + a 64-bit `pluto_infer.exe` next to it). It cannot load into OpenBW
(different binary, 4.2 API, Linux). So games against Pluto run the real 1.16.1 game headless under Wine, the
way sc-docker / the SSCAIT ladder do: `bwheadless.exe` (tscmoo) starts StarCraft.exe without graphics, sound or
input; BWAPI.dll is injected; two such processes on one machine play over the "Local PC" (shared memory) provider.

Everything below lives in git-ignored `third_party/` and `build/`; nothing is redistributed.

## 1. Pieces

| piece | where | from |
|---|---|---|
| StarCraft 1.16.1 install (exe, MPQs, maps, BWAPI 4.4.0 BWAPI.dll) | `third_party/game-data` | docs/setup_openbw.md §7 (Churchill's scbw_bwapi440.zip) |
| bwheadless.exe | `third_party/bw_win/template/` | sc-docker `docker/bwheadless.exe` (tscmoo/bwheadless, MIT) |
| Pluto release | `third_party/pluto/` (pluto.dll, pluto/pluto_infer.exe, pluto/pluto_weights.bin) | github.com/tscmoo/pluto releases, `pluto-cog2026-2578600.zip` (272 MB) |
| Wine 9 (wine32:i386 + wine64) | apt | Ubuntu 24.04. `libgd3` had to be downgraded to the Ubuntu build (a PPA version blocked the i386 multiarch set) |
| Wine prefix | `third_party/wineprefix` | `WINEDLLOVERRIDES="mscoree,mshtml=" xvfb-run -a wineboot --init` |
| MSVC CRT + Windows SDK (x86) | `third_party/xwin/splat` | `xwin --accept-license --arch x86 splat --output third_party/xwin/splat` (Jake-Shadle/xwin 0.10.0) |
| BWAPI 4.4.0 SDK (headers + BWAPILIB sources) | `third_party/bwapi440/Release_Binary` | github.com/bwapi/bwapi releases `BWAPI.7z` |
| our body as a Windows DLL | `build/mcrave_win/McRave.dll` | `body/mcrave_port/build_win.sh` (clang-cl 18 + lld-link; `_ALLOW_COMPILER_AND_STL_VERSION_MISMATCH` because the 2026 MSVC STL wants Clang 19) |

Pluto requirements (its README): AVX2 (AVX-VNNI recommended), 6+ cores, ~2 GB RAM. This container: 4 cores with
AVX-VNNI. Pluto paces itself by inference (one model step per 6 frames, waits for the answer), so fewer cores only
make the game slower, not Pluto weaker. Games therefore run one at a time (`--parallel 1`).

## 2. Build our body for Windows

```
body/mcrave_port/apply_patches.sh          # same patched McRave tree as the Linux build
body/mcrave_port/build_win.sh              # -> build/mcrave_win/McRave.dll (145 TUs: 30 BWAPILIB + 115 McRave incl. Sidecar.cpp)
```
The sidecar client is header-only and portable (httplib uses winsock on Windows; `getpid` guarded in
SidecarClient.hpp), so the same hooks, state emission and lockstep work in this lane. `SIDECAR_*`/`SC_AI_*`
environment variables pass through Wine to the module.

## 3. Run

```
# one game, our body (observe-only unless a sidecar is up) vs Pluto, Fighting Spirit:
tools/run_game_wine.sh build/mcrave_win/McRave.dll third_party/pluto "maps/BroodWar/sscai/(4)FightingSpirit.scx" Zerg Random
# the eval harness, same flags as the OpenBW runner:
python -m eval.run_eval --runner wine --opponent pluto --games 30 --parallel 1 --strategy fixed
python -m eval.run_eval --runner wine --opponent pluto --games 12 --parallel 1 --strategy llm --llm claude-cli
```
Per game the runner builds two private installs under the run dir (symlinks to the template, private
`bwapi-data/`), writes each `bwapi.ini` (auto_menu LAN / Local PC, MELEE, `speed_override = 0`), hosts with
p1 and joins with p2. Results: our side's sidecar `result` record (as on OpenBW); Pluto's own record in its
`bwapi-data/write/pluto_bandit_<opponent>.txt` (per-opponent bandit over its openings + one JSON line per game
with its win-probability trajectory, useful for the coach loop). Replays land in `bwapi-data/write/game.rep`.

Pluto writes `pluto.log` / `pluto_infer.log` into its install dir; if the engine cannot start it exits the game
process on purpose ("quitting in 10 seconds") so a crash is distinguishable from a loss.

## 4. Status

- 2026-10-02: Wine, prefix, bwheadless (`--help` runs), Pluto release, BWAPI SDK, xwin splat in place;
  `build_win.sh` builds `McRave.dll` (3.2 MB, static CRT, imports only WS2_32/USER32/KERNEL32) and
  `loadtest.exe`; `wine loadtest.exe McRave.dll` resolves both exports. `tools/run_game_wine.sh` and
  `--runner wine` + `--opponent pluto` in `eval/run_eval.py` are written.
  Not yet done: `tools/setup_bw_win_template.sh <bwheadless.exe>` and the first game (placing and running the
  external binaries bwheadless.exe/pluto.dll needs a permission grant in this environment).
- Open: Pluto's repo has no LICENSE file; the README's stated purpose is local play against it. We use it only as
  a local sparring opponent; nothing of it is redistributed.
