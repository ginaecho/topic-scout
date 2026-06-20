---
name: topic-paper-scout
description: Scout, review, and ingest papers for AI in Hiring Processes. Use for scheduled scouting, manual paper discovery, citation-graph expansion, and corpus updates in this workspace.
---

# Topic Paper Scout

1. Read `topic.json`, `data/papers.json`, and `AGENTS.md`.
2. Run `python3 scripts/scout.py`.
3. Review `data/candidates.json` against inclusion and exclusion rules.
4. Verify every accepted paper's identifier, URL, year, and abstract.
5. Add only genuinely new accepted papers to `data/papers.json`.
6. Run `make corpus`, then use `$analyze-research-gaps`, then run `make dashboard`.
7. If no paper is accepted, do not rewrite corpus, report, dashboard, or opportunity artifacts.
8. Do not stop at implementation alone. Run the code paths you changed, verify the generated files
   or outputs yourself, and only report success after the executed results are good.

Search within 2023-2026.
Prioritize: methods, benchmarks, systems, surveys.
Report token_count and money_cost_usd for every scouting run, even when the cost is zero.

## Topic-Specific Scouting Strategy

- Map evidence to each hiring stage before comparing impacts across the full process.
- Separate technical benchmark performance from real-world organizational outcomes and candidate impacts.
- Prioritize studies with defined tasks, populations, baselines, subgroup analyses, and reproducible evaluation methods.
- Compare AI-only, human-only, and human-AI workflows where evidence permits.
- Extract business-value measures separately from validity, fairness, privacy, and candidate-experience measures.
- Record jurisdiction, job type, labor-market setting, deployment scale, and vendor dependence for each system.
- Assess agent-system requirements including tool permissions, data boundaries, human approval points, audit logs, escalation paths, and continuous monitoring.
- Search for both intended benefits and adversarial or failure-oriented evidence, including applicant gaming and recruiter automation bias.
