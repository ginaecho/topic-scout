PYTHON ?= python3
QUERY ?=

.PHONY: help init scout review corpus dashboard plan opportunities-check test

help:
	@printf "%s\n" \
	"  make init       Interview the user and generate a topic workspace" \
	"  make scout      Search scholarly graphs for candidate papers" \
	"  make review     Print the candidate review queue" \
	"  make corpus     Rebuild Markdown paper notes and report" \
	"  make dashboard  Build HTML dashboard, graph, wiki, and opportunities" \
	"  make plan       Print the generated multi-agent task plan" \
	"  make opportunities-check  Validate LLM opportunity JSON" \
	"  make test       Run unit tests"

init:
	$(PYTHON) scripts/init_topic.py

scout:
	$(PYTHON) scripts/scout.py $(if $(QUERY),--query "$(QUERY)",)

review:
	$(PYTHON) scripts/review_candidates.py

corpus:
	$(PYTHON) scripts/build_corpus.py

dashboard:
	$(PYTHON) scripts/build_dashboard.py

plan:
	$(PYTHON) scripts/orchestrate.py plan

opportunities-check:
	$(PYTHON) scripts/validate_opportunities.py

test:
	$(PYTHON) -m unittest discover -s tests
