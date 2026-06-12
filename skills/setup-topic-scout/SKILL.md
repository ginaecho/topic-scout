---
name: setup-topic-scout
description: Interview a user about a research topic and initialize AI Topic Scout. Use when topic.json is missing, when starting a new research workspace, or when the user wants generated agent roles, scout skills, queries, taxonomy, and inclusion/exclusion rules.
---

# Setup Topic Scout

Ask the user concise questions about:

1. topic or research question;
2. decision or outcome;
3. audience;
4. required concepts;
5. excluded adjacent areas;
6. publication years;
7. evidence types;
8. taxonomy;
9. cadence;
10. approval policy.

Then run `python3 scripts/init_topic.py` with explicit flags or interactively.

Verify that initialization creates:

- `topic.json`
- `AGENTS.md`
- `agents/*.md`
- `skills/topic-paper-scout/SKILL.md`
- `skills/analyze-research-gaps/SKILL.md`
- `data/papers.json`

Do not start broad scouting until the user confirms the generated topic contract.
