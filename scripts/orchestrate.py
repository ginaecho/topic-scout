#!/usr/bin/env python3
"""Emit or execute the topic-scout workflow for different agent runtimes."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

from workspace import DATA_DIR, PAPERS_PATH, ROOT, load_json, load_topic, write_json


def tasks(config: dict) -> list[dict]:
    return [
        {
            "id": "queries",
            "role": "query_designer",
            "objective": "Review topic.json and improve search_queries without broadening excluded scope.",
            "inputs": ["topic.json"],
            "outputs": ["topic.json"],
            "depends_on": [],
        },
        {
            "id": "discover",
            "role": "graph_scout",
            "objective": "Run scholarly graph discovery and produce candidates with provenance.",
            "inputs": ["topic.json", "data/papers.json"],
            "outputs": ["data/candidates.json"],
            "depends_on": ["queries"],
        },
        {
            "id": "review",
            "role": "relevance_reviewer",
            "objective": "Apply inclusion/exclusion rules and propose accepted candidate IDs.",
            "inputs": ["topic.json", "data/candidates.json"],
            "outputs": ["review decision"],
            "depends_on": ["discover"],
        },
        {
            "id": "library",
            "role": "librarian",
            "objective": "Accept approved IDs, deduplicate, and preserve source metadata.",
            "inputs": ["data/candidates.json", "review decision"],
            "outputs": ["data/papers.json"],
            "depends_on": ["review"],
        },
        {
            "id": "synthesis",
            "role": "analyst",
            "objective": "Classify papers and rebuild Markdown notes and synthesis.",
            "inputs": ["topic.json", "data/papers.json"],
            "outputs": ["reports/research_report.md", "reports/papers/"],
            "depends_on": ["library"],
        },
        {
            "id": "gaps",
            "role": "gap_analyst",
            "objective": "Use skills/analyze-research-gaps/SKILL.md to write evidence-backed opportunities.",
            "inputs": ["data/papers.json", "reports/research_report.md"],
            "outputs": ["data/research_opportunities.json"],
            "depends_on": ["synthesis"],
        },
        {
            "id": "publish",
            "role": "publisher",
            "objective": "Regenerate dashboard, graph, wiki, trends, and opportunity view.",
            "inputs": ["data/papers.json", "data/research_opportunities.json"],
            "outputs": ["topic-dashboard.html", "data/dashboard.json"],
            "depends_on": ["gaps"],
        },
    ]


def emit(mode: str, config: dict) -> dict:
    payload = {
        "mode": mode,
        "topic": config["topic"],
        "coordinator_instruction": (
            "Read AGENTS.md and topic.json. Assign only accepted research-contract tasks. "
            "Do not publish when no new paper is accepted."
        ),
        "tasks": tasks(config),
    }
    write_json(DATA_DIR / f"{mode}_tasks.json", payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["plan", "emit", "run"])
    parser.add_argument("--mode", choices=["sequential", "claw", "swarm"], default="sequential")
    args = parser.parse_args()
    config = load_topic()
    payload = emit(args.mode, config)
    if args.action in {"plan", "emit"}:
        print(json.dumps(payload, indent=2))
        return 0
    if args.mode != "sequential":
        raise SystemExit("`run` executes deterministic stages only; use `emit` for claw/swarm.")
    before = len(load_json(PAPERS_PATH, {"papers": []})["papers"])
    subprocess.run([sys.executable, "scripts/scout.py"], cwd=ROOT, check=True)
    after = len(load_json(PAPERS_PATH, {"papers": []})["papers"])
    if after == before:
        print("No accepted new papers; report and dashboard remain unchanged.")
        return 0
    subprocess.run([sys.executable, "scripts/build_corpus.py"], cwd=ROOT, check=True)
    subprocess.run([sys.executable, "scripts/analyze_research_gaps.py"], cwd=ROOT, check=True)
    subprocess.run([sys.executable, "scripts/build_dashboard.py"], cwd=ROOT, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
