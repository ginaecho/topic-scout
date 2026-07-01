---
name: analyze-research-gaps
description: Analyze the AI in Hiring Processes corpus and write ranked, evidence-backed research opportunities. Use after accepted scout updates or when opportunity analysis is stale.
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
8. Do not claim completion until you have run the relevant generator or validator yourself and
   verified that the written opportunity artifact is structurally valid and substantively usable.
