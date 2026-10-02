# SC_AI — LLM strategy layer on a Brood War bot body

Read `docs/design_v0.5.md` (what we build), `docs/design_review_2026-09.md` (why) and `docs/roadmap.md` (milestones, what is decided and what is deferred) before changing anything.

## Layout
- `bot/sidecar/` Python sidecar: HTTP loopback server, state store, summarizer, plan ledger, validator, strategy caller, LLM backends (`anthropic|fake|recorded`), JSONL logger.
- `knowledge/` fixed prompt prefix: `rules.md`, `builds/<matchup>.json`, `maps/<map>.json`. **Map files are edited only after human review.**
- `eval/` harness: `run_eval.py` (runners: `mock` now, `openbw` TODO), `metrics.py`, `compare.py`.
- `tools/fake_body.py` simulates the bot body for end-to-end dev without a game.
- `body/` McRave hooks and patches (see `body/HOOKS.md`), `docker/` OpenBW images, `config/` yaml.
- `third_party/`, `logs/`, `replays/`, `eval/results/` are git-ignored.

## Commands
```
pip install -e ".[dev]"            # or: uv pip install -e ".[dev]"
python -m pytest -q                 # unit + end-to-end (fake LLM) tests, must pass before commit
python -m bot.sidecar.server --config config/sidecar.yaml --llm fake     # sidecar on 127.0.0.1:8770
python -m tools.fake_body --minutes 8                                    # drive it, prints directives
python -m eval.run_eval --games 30 --strategy fixed --runner mock        # metrics.json under eval/results/
python -m eval.run_eval --runner openbw --games 3 --parallel 3 --opponent zzzkbot --strategy fixed   # real games, baseline body
python -m eval.run_eval --runner openbw --games 3 --parallel 3 --opponent mcrave --strategy llm --llm claude-cli
python -m eval.compare eval/results/<a>/metrics.json eval/results/<b>/metrics.json
```
`--runner wine --opponent pluto` plays real StarCraft 1.16.1 under Wine against Pluto (`docs/setup_pluto_lane.md`; needs `build/mcrave_win/McRave.dll` from `body/mcrave_port/build_win.sh` and `third_party/bw_win/template`).
Opponents (`eval/run_eval.py` OPPONENTS): `probe` (idle), `mcrave` (pristine body), `zzzkbot`, `ualbertabot`. Real games need
`third_party/game-data` (MPQs + maps, see `docs/setup_openbw.md` §7) and the built bots (`build/*/*.so`, see `body/*_port/README.md`).
`--strategy fixed` runs the sidecar in observe-only mode (logs, no overrides); `--max-frames` caps games (timeout = not a win).
LLM backends: `claude-cli` (Claude Code login, no key; default), `anthropic` (needs `ANTHROPIC_API_KEY` in the environment, never in chat or git), `fake`, `recorded`. Budget caps live in `config/sidecar.yaml`.

## Rules
- The body must play a full game without the sidecar. Never make the body wait on HTTP.
- The Strategy LLM outputs macro policy only (names from knowledge files). Coordinates and unit ids are body-side.
- Any change to prompts, knowledge, validator, or body code is adopted only if `eval.compare` says `improved` or `no_change` on the same opponent/map/seed set. One change per run.
- Keep the cached prefix byte-stable (no timestamps, sorted JSON). Tests assert this.
- Log everything to JSONL; the coach loop reads logs, not stdout.
