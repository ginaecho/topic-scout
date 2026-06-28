# Topic Scouting and Auto Dashboard Generation

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21009802.svg)](https://doi.org/10.5281/zenodo.21009802)

Turn any research question into a persistent, agent-operated paper intelligence workspace.

AI Topic Scout asks the user what they want to investigate, generates topic-specific agent and
skill instructions, searches scholarly graphs, maintains a deduplicated paper corpus, and builds:

- Markdown paper notes and synthesis reports
- topic ratios and scout-run trends
- an interactive paper association graph
- a searchable Karpathy-style wiki
- evidence-backed research gaps and opportunities
- task manifests for one agent, Claw agents, or subagent swarms

## Quick Start

```bash
codex login
make init
make scout
make review
make dashboard
```

By default, `make init` calls the installed Codex CLI in non-interactive mode and reuses its saved
ChatGPT login. This uses Codex subscription access and does not require an OpenAI API key. The
Codex agent runs ephemerally in a read-only sandbox and returns schema-constrained JSON.

During intake, it converts the user's raw intent into a concise title, research question, dashboard
structure, targeted search queries, and a topic-specific scouting strategy before generating any
agent or skill Markdown.

Or initialize non-interactively:

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
# Default: use the logged-in Codex CLI and ChatGPT/Codex subscription
make init

# Direct Responses API usage and API billing
export OPENAI_API_KEY="..."
python3 scripts/init_topic.py --provider api

# No model call
python3 scripts/init_topic.py --offline
```

Set `TOPIC_SCOUT_PROVIDER=api` to change the default provider. Pass `--model` to override the
selected provider's configured model. Offline mode preserves literal-input behavior.

To discard a generated topic workspace and restart intake:

```bash
make reset
make init
```

`make reset` removes only generated topic files, agent roles, topic-specific skills, corpus state,
scout candidates, reports, task manifests, and dashboard output. These generated paths are also
excluded by `.gitignore`, while application source, examples, schemas, and the setup skill remain
trackable.

Then inspect:

- `topic.json`: the research contract
- `AGENTS.md`: generated operating instructions
- `skills/topic-paper-scout/SKILL.md`: generated scout procedure
- `skills/analyze-research-gaps/SKILL.md`: generated opportunity-analysis procedure
- `data/papers.json`: normalized scholarly corpus
- `reports/research_report.md`: generated synthesis
- `topic-dashboard.html`: dashboard, graph, wiki, and opportunities
- `scout_cron_payload.txt`: generated prompt for a scheduled Claw scout

## Intent Intake

`make init` asks for one complete research intent. Immediately after that input, the LLM derives:

- a concise title and research question;
- business purpose, audience, and scope boundaries;
- evaluation dimensions, evidence types, and taxonomy;
- dashboard sections;
- targeted and adversarial search queries;
- a citation-graph scouting strategy.

Interactive setup then asks only for publication years, cadence, and approval policy. Non-interactive
flags such as `--goal`, `--include`, and `--taxonomy` are optional constraints on the LLM.

The refined contract and original `raw_intent` become version-controlled instructions rather than
disappearing into chat history.

## Agent Modes

```bash
# Show the generated task plan
python3 scripts/orchestrate.py plan

# Run deterministic local stages
python3 scripts/orchestrate.py run --mode sequential

# Emit task briefs for a Claw coordinator and workers
python3 scripts/orchestrate.py emit --mode claw

# Emit independent subagent tasks and a synthesis task
python3 scripts/orchestrate.py emit --mode swarm
```

Roles:

- `coordinator`: owns the research contract and final acceptance
- `query_designer`: expands the topic into targeted searches
- `graph_scout`: searches scholarly graphs and citation neighborhoods
- `relevance_reviewer`: applies inclusion/exclusion criteria
- `librarian`: deduplicates and writes paper records
- `analyst`: maintains taxonomy, trends, and synthesis
- `gap_analyst`: produces evidence-backed opportunities
- `publisher`: regenerates Markdown and HTML artifacts

## Scout Semantics

- Candidate discovery does not automatically imply acceptance.
- Every accepted paper must have a stable scholarly identifier and source URL.
- Existing records are compared before writeback.
- If no accepted new paper exists, tracked artifacts are not rewritten.
- Research-gap conclusions are LLM hypotheses over the current corpus and must include evidence,
  uncertainty, and targeted follow-up queries.

Review and accept candidates:

```bash
make review
python3 scripts/accept_candidates.py openalex:W123 openalex:W456
make corpus
make dashboard
```

## Commands

```bash
make help
make init
make reset
make scout
make corpus
make dashboard
make plan
make test
```

No Python package installation is required for the core workflow.
