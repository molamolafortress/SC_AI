# SC_AI — LLM strategy layer on a Brood War bot body

Read `docs/design_v0.5.md` (what we build) and `docs/design_review_2026-09.md` (why) before changing anything.

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
python -m eval.compare eval/results/<a>/metrics.json eval/results/<b>/metrics.json
```
Real LLM: set `ANTHROPIC_API_KEY` (never commit it) and `--llm anthropic`. Budget caps live in `config/sidecar.yaml`.

## Rules
- The body must play a full game without the sidecar. Never make the body wait on HTTP.
- The Strategy LLM outputs macro policy only (names from knowledge files). Coordinates and unit ids are body-side.
- Any change to prompts, knowledge, validator, or body code is adopted only if `eval.compare` says `improved` or `no_change` on the same opponent/map/seed set. One change per run.
- Keep the cached prefix byte-stable (no timestamps, sorted JSON). Tests assert this.
- Log everything to JSONL; the coach loop reads logs, not stdout.
