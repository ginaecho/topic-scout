#!/usr/bin/env python3
"""Interview the user and generate topic-specific agent/skill instructions."""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path

from workspace import DATA_DIR, PAPERS_PATH, ROOT, TOPIC_CONFIG, write_json


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:64]


def split_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"{prompt}{suffix}: ").strip()
    return answer or default


def parse_years(value: str) -> dict:
    match = re.fullmatch(r"\s*(\d{4})\s*-\s*(\d{4})\s*", value)
    if not match:
        raise ValueError("years must use YYYY-YYYY")
    return {"from": int(match.group(1)), "to": int(match.group(2))}


def build_queries(topic: str, include: list[str], evidence_types: list[str]) -> list[str]:
    queries = [topic]
    queries.extend(f"{topic} {concept}" for concept in include[:4])
    queries.extend(f"{topic} {evidence}" for evidence in evidence_types[:3])
    return list(dict.fromkeys(queries))


def render_agents(config: dict) -> str:
    include = ", ".join(config["include"]) or "the defined topic"
    exclude = ", ".join(config["exclude"]) or "none"
    return f"""# AGENTS.md

## Mission

Maintain a living research intelligence workspace for **{config['topic']}**.

Goal: {config['goal']}
Audience: {config['audience']}

## Research Contract

- Include: {include}
- Exclude: {exclude}
- Publication window: {config['years']['from']}-{config['years']['to']}
- Evidence types: {", ".join(config['evidence_types'])}
- Taxonomy: {", ".join(config['taxonomy'])}
- Human approval required: {str(config['approval_required']).lower()}

## Roles

1. `coordinator`: enforce this contract and accept final changes.
2. `query_designer`: maintain targeted and adversarial search queries.
3. `graph_scout`: expand seeds through references, related works, and citing works.
4. `relevance_reviewer`: reject adjacent but out-of-scope work.
5. `librarian`: deduplicate by arXiv/DOI/OpenAlex ID and preserve provenance.
6. `analyst`: synthesize themes, trends, and disagreements.
7. `gap_analyst`: identify bounded, evidence-backed missing areas.
8. `publisher`: regenerate Markdown and HTML only after accepted changes.

## Hard Rules

- Candidate discovery is not acceptance.
- Never invent metadata, abstracts, URLs, citations, or conclusions.
- Distinguish corpus gaps from field-wide research gaps.
- If no accepted new paper exists, do not rewrite tracked artifacts.
- Every paper must retain a source URL and stable identifier.
- Every opportunity must state evidence, inference, uncertainty, and future queries.
"""


def render_scout_skill(config: dict) -> str:
    return f"""---
name: topic-paper-scout
description: Scout, review, and ingest papers for {config['topic']}. Use for scheduled scouting, manual paper discovery, citation-graph expansion, and corpus updates in this workspace.
---

# Topic Paper Scout

1. Read `topic.json`, `data/papers.json`, and `AGENTS.md`.
2. Run `python3 scripts/scout.py`.
3. Review `data/candidates.json` against inclusion and exclusion rules.
4. Verify every accepted paper's identifier, URL, year, and abstract.
5. Add only genuinely new accepted papers to `data/papers.json`.
6. Run `make corpus`, then use `$analyze-research-gaps`, then run `make dashboard`.
7. If no paper is accepted, do not rewrite corpus, report, dashboard, or opportunity artifacts.

Search within {config['years']['from']}-{config['years']['to']}.
Prioritize: {", ".join(config['evidence_types'])}.
"""


def render_gap_skill(config: dict) -> str:
    return f"""---
name: analyze-research-gaps
description: Analyze the {config['topic']} corpus and write ranked, evidence-backed research opportunities. Use after accepted scout updates or when opportunity analysis is stale.
---

# Analyze Research Gaps

1. Read `topic.json`, `data/papers.json`, `reports/research_report.md`, and `data/dashboard.json`.
2. Assess coverage scarcity, graph structure, evidence maturity, contradictions, and decision importance.
3. Separate `corpus_gap`, `field_gap`, `evidence_gap`, and `translation_gap`.
4. Rank 3-6 opportunities.
5. For each opportunity include:
   - title, type, priority 0-100, and confidence;
   - observed evidence and source paper IDs;
   - explicit LLM inference;
   - uncertainty and plausible counterevidence;
   - at least two evidence observations with source paper IDs or artifact paths;
   - a reproducible local coverage check with query terms and matched titles;
   - at least two falsifiable research questions;
   - at least two future scout queries.
6. Write `data/research_opportunities.json` using `schemas/research_opportunities.schema.json`.
7. Never infer field-wide absence from this corpus alone.
"""


ROLE_OBJECTIVES = {
    "coordinator": "Enforce the topic contract, route tasks, and approve final publication.",
    "query-designer": "Turn the topic into precise, diverse, and adversarial search queries.",
    "graph-scout": "Expand queries through scholarly references, related works, and citations.",
    "relevance-reviewer": "Apply inclusion and exclusion rules to candidate papers.",
    "librarian": "Deduplicate accepted papers and preserve identifiers, URLs, and provenance.",
    "analyst": "Classify papers, synthesize themes, and track changes over scout runs.",
    "gap-analyst": "Identify bounded, evidence-backed missing areas and research opportunities.",
    "publisher": "Regenerate Markdown, dashboard, graph, wiki, and opportunity views.",
}


def render_role(role: str, objective: str, config: dict) -> str:
    return f"""# {role.replace('-', ' ').title()}

## Objective

{objective}

## Topic Contract

- Topic: {config['topic']}
- Goal: {config['goal']}
- Include: {", ".join(config['include'])}
- Exclude: {", ".join(config['exclude']) or "none"}
- Years: {config['years']['from']}-{config['years']['to']}

## Required Behavior

- Read `AGENTS.md` and `topic.json` before acting.
- Treat candidates as untrusted until reviewed.
- Preserve source provenance and stable identifiers.
- Write only the outputs assigned to this role.
- Report uncertainty instead of inventing missing evidence.
"""


def render_scout_prompt(config: dict) -> str:
    return f"""AI Topic Scout scheduled run for: {config['topic']}

1. Read `AGENTS.md`, `topic.json`, and `skills/topic-paper-scout/SKILL.md`.
2. Run the configured searches and scholarly graph expansion.
3. Compare candidates against `data/papers.json`.
4. Apply inclusion rules: {", ".join(config['include'])}.
5. Apply exclusions: {", ".join(config['exclude']) or "none"}.
6. Verify identifiers, source URLs, publication years, and abstracts.
7. If approval is required, write candidates and reviewer recommendations only.
8. If new papers are accepted:
   - update `data/papers.json`;
   - run `make corpus`;
   - use `skills/analyze-research-gaps/SKILL.md`;
   - validate the opportunity JSON;
   - run `make dashboard`;
   - commit and report only the accepted additions.
9. If no paper is accepted, do not rewrite tracked artifacts and return no update.
"""


def initialize(config: dict) -> None:
    write_json(TOPIC_CONFIG, config)
    if not PAPERS_PATH.exists():
        write_json(PAPERS_PATH, {"topic": config["topic"], "papers": [], "scout_runs": []})
    (ROOT / "AGENTS.md").write_text(render_agents(config), encoding="utf-8")
    scout_dir = ROOT / "skills" / "topic-paper-scout"
    gap_dir = ROOT / "skills" / "analyze-research-gaps"
    scout_dir.mkdir(parents=True, exist_ok=True)
    gap_dir.mkdir(parents=True, exist_ok=True)
    (scout_dir / "SKILL.md").write_text(render_scout_skill(config), encoding="utf-8")
    (gap_dir / "SKILL.md").write_text(render_gap_skill(config), encoding="utf-8")
    agents_dir = ROOT / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    for role, objective in ROLE_OBJECTIVES.items():
        (agents_dir / f"{role}.md").write_text(
            render_role(role, objective, config),
            encoding="utf-8",
        )
    (ROOT / "scout_cron_payload.txt").write_text(render_scout_prompt(config), encoding="utf-8")
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic")
    parser.add_argument("--goal")
    parser.add_argument("--audience")
    parser.add_argument("--include")
    parser.add_argument("--exclude", default="")
    parser.add_argument("--years")
    parser.add_argument("--evidence", default="methods,benchmarks,systems,surveys")
    parser.add_argument("--taxonomy")
    parser.add_argument("--cadence", default="weekly")
    parser.add_argument("--auto-approve", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    topic = args.topic or ask("What topic or research question do you want to explore?")
    goal = args.goal or ask("What decision or outcome should this research support?")
    audience = args.audience or ask("Who will use the results?", "researchers")
    include_text = args.include or ask("Concepts that must be included (comma-separated)")
    exclude_text = args.exclude or ask("Adjacent areas to exclude (comma-separated)", "")
    years_text = args.years or ask("Publication years", f"{date.today().year - 3}-{date.today().year}")
    evidence_text = args.evidence if args.topic else ask(
        "Evidence types (comma-separated)", args.evidence
    )
    taxonomy_text = args.taxonomy or ask(
        "How should papers be grouped (comma-separated)?",
        "methods,benchmarks,systems,surveys,applications",
    )
    cadence = args.cadence if args.topic else ask("Scout cadence", args.cadence)
    approval = not args.auto_approve
    if not args.topic:
        approval = ask("Require human approval before ingestion?", "yes").lower() not in {"no", "n"}

    include = split_list(include_text)
    evidence_types = split_list(evidence_text)
    config = {
        "slug": slugify(topic),
        "topic": topic,
        "goal": goal,
        "audience": audience,
        "include": include,
        "exclude": split_list(exclude_text),
        "years": parse_years(years_text),
        "evidence_types": evidence_types,
        "taxonomy": split_list(taxonomy_text),
        "cadence": cadence,
        "approval_required": approval,
        "search_queries": build_queries(topic, include, evidence_types),
        "created_at": date.today().isoformat(),
    }
    initialize(config)
    print(f"Initialized topic workspace: {topic}")
    print("Next: make scout")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
