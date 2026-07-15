PYTHON ?= python3
QUERY ?=

.PHONY: help init reset scout review corpus opportunities dashboard plan opportunities-check test

help:
	@printf "%s\n" \
	"  make init       Use Codex CLI to refine intent and generate a topic workspace" \
	"  make reset      Remove the generated topic workspace for a fresh start" \
	"  make scout      Search scholarly graphs for candidate papers" \
	"  make review     Print the candidate review queue" \
	"  make corpus     Rebuild Markdown paper notes and report" \
	"  make opportunities  Generate LLM-backed research opportunities" \
	"  make dashboard  Build HTML dashboard, graph, wiki, and opportunities" \
	"  make plan       Print the generated multi-agent task plan" \
	"  python3 scripts/orchestrate.py emit --mode copilot|copilot-cli|microsoft-scouting" \
	"  make opportunities-check  Validate LLM opportunity JSON" \
	"  make eval       Compare the cheap deterministic metric vs the LLM judge" \
	"  make test       Run unit tests"

init:
	$(PYTHON) scripts/init_topic.py

reset:
	rm -rf TOPIC_AGENTS.md agents data/candidates.json data/dashboard.json \
		data/papers.json data/research_opportunities.json \
		data/sequential_tasks.json data/claw_tasks.json data/swarm_tasks.json \
		data/copilot_tasks.json data/copilot-cli_tasks.json \
		data/microsoft-scouting_tasks.json \
		reports scout_cron_payload.txt skills/analyze-research-gaps \
		skills/topic-paper-scout topic-dashboard.html topic.json

scout:
	$(PYTHON) scripts/scout.py $(if $(QUERY),--query "$(QUERY)",)

review:
	$(PYTHON) scripts/review_candidates.py

corpus:
	$(PYTHON) scripts/build_corpus.py

dashboard:
	$(PYTHON) scripts/analyze_research_gaps.py
	$(PYTHON) scripts/build_dashboard.py

opportunities:
	$(PYTHON) scripts/analyze_research_gaps.py

plan:
	$(PYTHON) scripts/orchestrate.py plan

opportunities-check:
	$(PYTHON) scripts/validate_opportunities.py

eval:
	$(PYTHON) scripts/eval_metric.py $(if $(INPUT),--input "$(INPUT)",) $(if $(REPORT),--report "$(REPORT)",)

test:
	$(PYTHON) -m unittest discover -s tests
