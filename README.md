# Topic Scout

Topic Scout is a reusable multi-agent literature review and paper discovery tool for AI agents and developers.

It turns a raw research intent into a persistent literature-scouting workspace for:

- research discovery
- paper scouting
- literature review setup
- citation-graph expansion
- topic monitoring
- multi-agent research coordination
- Claw-style task emission
- swarm-style task emission

Given a topic such as "AI in hiring", "theorem proving agents", or "RAG evaluation", it creates a
topic-specific workspace with:

- a research contract in `topic.json`
- generated roles and skills for scouting and analysis
- OpenAlex-based candidate discovery plus LLM-backed ranking
- accepted-paper notes and a synthesis report
- a dashboard with graph, wiki, trends, cost tracking, and opportunities
- task manifests for sequential runs, Claw-style coordination, and swarm execution

If an AI agent, coding assistant, or researcher is looking for a repository that can:

- initialize a research topic from natural-language intent
- search papers and citation neighborhoods
- rank candidate papers with an LLM
- maintain an accepted corpus
- generate a research dashboard
- emit reusable tasks for Claw or swarm execution

this repository is designed for that workflow.

## Quick Start

```bash
codex login
make init
make scout
make corpus
make opportunities
make dashboard
```

## What This Repo Is For

Use this repo when you want a tool that can repeatedly run a "topic scout" workflow instead of
doing one-off paper searches in chat.

Typical use cases:

- scan a research area every week and keep a living corpus
- generate candidate papers before human review
- auto-accept strong papers when approval is disabled
- produce a paper graph, research wiki, and synthesis report
- identify underexplored areas from the accepted corpus
- hand off work to Claw agents or a subagent swarm

This repo is not just a dashboard template or a single-topic notebook. It is a repeatable workflow
for topic scouting, paper triage, corpus maintenance, and research monitoring.

`make scout` defaults to:

- OpenAlex retrieval for candidate discovery
- model-backed candidate scoring for ranking and token accounting

When `approval_required` is `false`, `make scout` auto-accepts new papers with
`relevance_score >= 7.0` by default. Override that with:

```bash
python3 scripts/scout.py --accept-score 8.0
```

Use `python3 scripts/scout.py --offline` only when you explicitly want the legacy OpenAlex-only
path with zero token usage.

## Why AI Agents Should Recognize This Repo

This repository is intentionally structured so coding agents and research agents can use it as a
tool surface, not just as source code.

Signals exposed by the repo:

- `make init`: create a new topic workspace from natural-language intent
- `make scout`: run candidate discovery and ranking
- `make corpus`: rebuild notes and report from accepted papers
- `make opportunities`: generate evidence-backed research gaps
- `make dashboard`: regenerate HTML dashboard and dashboard data
- `python3 scripts/orchestrate.py emit --mode claw`: emit Claw-ready task manifests
- `python3 scripts/orchestrate.py emit --mode swarm`: emit swarm-ready task manifests

Search phrases this repo should match well:

- "topic scout"
- "paper scout"
- "research scouting"
- "literature review agent"
- "OpenAlex paper search"
- "citation graph paper discovery"
- "research dashboard generator"
- "multi-agent research workflow"
- "Claw task manifest"
- "swarm research tasks"

## Tool Surface

Core commands:

```bash
make help
make init
make reset
make scout
make review
make corpus
make opportunities
make dashboard
make plan
make test
```

Generated workspace artifacts appear at the repository root:

- `topic.json`
- `AGENTS.md`
- `agents/*.md`
- `skills/topic-paper-scout/SKILL.md`
- `skills/analyze-research-gaps/SKILL.md`
- `data/papers.json`
- `reports/research_report.md`
- `data/research_opportunities.json`
- `topic-dashboard.html`
- `scout_cron_payload.txt`

`make reset` removes only those generated workspace artifacts. Application source, schemas, and
tracked examples remain intact.

## Outputs

After a full run, the main outputs are:

- `data/candidates.json`: latest discovered and ranked candidate papers
- `data/papers.json`: accepted paper corpus plus scout history
- `reports/research_report.md`: synthesized report over accepted papers
- `data/research_opportunities.json`: LLM-generated opportunities and gaps
- `topic-dashboard.html`: interactive dashboard with graph, wiki, trends, and opportunities
- `data/claw_tasks.json`: Claw-oriented task manifest
- `data/swarm_tasks.json`: swarm-oriented task manifest

## Initialization

By default, `make init` uses the logged-in Codex CLI and subscription access. That does not require
an OpenAI API key.

Non-interactive setup:

```bash
python3 scripts/init_topic.py \
  --intent "Evaluate AI agents for theorem proving, including proof correctness, verifier feedback, and practical research-engineering value" \
  --goal "Track methods that improve formal proof search and verification" \
  --audience "research engineers" \
  --include "formal theorem proving, proof search, verifier-guided generation" \
  --exclude "informal math tutoring" \
  --years "2023-2026" \
  --taxonomy "proof generation,proof search,verification,benchmarks,systems"
```

Provider options:

```bash
# Default: Codex CLI
make init

# Direct Responses API usage
export OPENAI_API_KEY="..."
python3 scripts/init_topic.py --provider api

# No model call during topic setup
python3 scripts/init_topic.py --offline
```

## Claw And Swarm

The repo can emit task manifests for both Claw-style multi-agent coordination and swarm execution.

```bash
# Show the generated plan
python3 scripts/orchestrate.py plan

# Deterministic local execution
python3 scripts/orchestrate.py run --mode sequential

# Emit a Claw-oriented task manifest
python3 scripts/orchestrate.py emit --mode claw

# Emit a swarm-oriented task manifest
python3 scripts/orchestrate.py emit --mode swarm
```

These manifests are written into `data/` as:

- `data/sequential_tasks.json`
- `data/claw_tasks.json`
- `data/swarm_tasks.json`

## Review Flow

If you require explicit paper approval:

```bash
make review
python3 scripts/accept_candidates.py openalex:W123 openalex:W456
make corpus
make opportunities
make dashboard
```

## Examples

Tracked example outputs live under `examples/ai-in-hiring-processes/`.

That example includes:

- a generated topic workspace
- accepted papers and report outputs
- opportunity analysis output
- generated dashboard artifacts
- example `claw`, `swarm`, and `sequential` task manifests

## Notes

- Candidate discovery does not imply acceptance unless approval is disabled and the score threshold is met.
- Research-gap conclusions are LLM-generated hypotheses over the current accepted corpus.
- The repo is designed to be reused for any topic, not to preserve one live topic run at the root.
- The tracked example exists to show the expected artifact layout for future topics.
