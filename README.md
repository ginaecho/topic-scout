# AI Topic Scout

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
make init
make scout
make review
make dashboard
```

Or initialize non-interactively:

```bash
python3 scripts/init_topic.py \
  --topic "AI for theorem proving" \
  --goal "Track methods that improve formal proof search and verification" \
  --audience "research engineers" \
  --include "formal theorem proving, proof search, verifier-guided generation" \
  --exclude "informal math tutoring" \
  --years "2023-2026"
```

Then inspect:

- `topic.json`: the research contract
- `AGENTS.md`: generated operating instructions
- `skills/topic-paper-scout/SKILL.md`: generated scout procedure
- `skills/analyze-research-gaps/SKILL.md`: generated opportunity-analysis procedure
- `data/papers.json`: normalized scholarly corpus
- `reports/research_report.md`: generated synthesis
- `topic-dashboard.html`: dashboard, graph, wiki, and opportunities
- `scout_cron_payload.txt`: generated prompt for a scheduled Claw scout

## Topic Interview

`make init` asks:

1. What topic or question do you want to explore?
2. What decision or outcome should this research support?
3. Who will use the results?
4. What concepts must be included?
5. What adjacent areas should be excluded?
6. What publication years matter?
7. Which evidence types matter: methods, benchmarks, surveys, systems, products?
8. How should papers be grouped?
9. How often should scouting run?
10. Should updates require human approval before entering the corpus?

The answers become version-controlled instructions rather than disappearing into chat history.

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
make scout
make corpus
make dashboard
make plan
make test
```

No Python package installation is required for the core workflow.
