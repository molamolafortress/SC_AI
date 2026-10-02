# ADR 0001: Open-source bot body + Python sidecar brain

Date: 2026-09-29. Status: accepted (revisit after Phase 3 A/B).

Decision: use McRave (fallback UAlbertaBot) as the execution body and a Python sidecar for the LLM strategy layer,
communicating over HTTP loopback with the body never blocking on the sidecar.

Why: the project hypothesis is about strategic adaptation, not about re-implementing production/placement/micro.
Prior work (design_review 3장, Brood War Bench 9.1) shows LLMs issuing low-level commands stay at beginner level;
a competent body is required to measure the strategy layer at all. Consequences: C++ hooks in a foreign codebase;
OpenBW port needed for headless eval; State Manager functions partly live in the body's InformationManager.
