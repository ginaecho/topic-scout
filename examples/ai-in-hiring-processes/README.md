# AI in Hiring Processes

This directory is a tracked example output from AI Topic Scout.

It shows what a generated topic workspace looks like after:

- `make init`
- `make scout`
- `make corpus`
- `make opportunities`
- `make dashboard`
- `python3 scripts/orchestrate.py emit --mode claw`
- `python3 scripts/orchestrate.py emit --mode swarm`

Key example artifacts:

- `topic.json`: generated research contract
- `AGENTS.md`: generated operating instructions
- `skills/`: generated topic-specific scout and gap-analysis skills
- `data/papers.json`: accepted corpus and scout history
- `data/candidates.json`: latest candidate queue
- `data/research_opportunities.json`: generated opportunity analysis
- `data/claw_tasks.json`: example Claw task manifest
- `data/swarm_tasks.json`: example swarm task manifest
- `reports/research_report.md`: generated report
- `topic-dashboard.html`: generated dashboard

These files are examples only. The live tool writes generated workspaces at the repository root and
`make reset` clears them.
