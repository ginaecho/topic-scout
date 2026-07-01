# Topic Scout Repository Guide

## Purpose

This repository is a reusable Topic Scout tool. It is meant to help agents and human operators
create topic-specific research workspaces for literature scouting, paper triage, corpus
maintenance, dashboard generation, and opportunity analysis.

Use this repository when the goal is to:

- turn a raw research intent into a structured topic contract
- discover papers with OpenAlex and citation-graph expansion
- rank candidate papers with an LLM
- build and maintain an accepted paper corpus
- generate a research dashboard and evidence-backed opportunities
- emit task manifests for sequential, Claw-style, or swarm execution

## Command Surface

Primary commands:

1. `make init`
2. `make scout`
3. `make review`
4. `make corpus`
5. `make opportunities`
6. `make dashboard`
7. `python3 scripts/orchestrate.py emit --mode claw`
8. `python3 scripts/orchestrate.py emit --mode swarm`

## Repo Rules

- Treat the repository root as the live generated workspace surface.
- Do not assume the current topic; inspect `topic.json` and `TOPIC_AGENTS.md` after `make init`.
- `AGENTS.md` is permanent repo-level guidance.
- `TOPIC_AGENTS.md` is generated topic-specific guidance.
- Generated role briefs live under `agents/`.
- Generated topic-specific skills live under `skills/topic-paper-scout/` and
  `skills/analyze-research-gaps/`.
- Example outputs live under `examples/` and should not be treated as the active workspace.

## Validation

- Do not stop at implementation alone.
- Run the relevant commands yourself.
- Verify generated outputs are structurally correct and substantively usable before claiming
  success.
