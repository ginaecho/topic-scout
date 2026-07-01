#!/usr/bin/env python3
"""Emit or execute the topic-scout workflow for different agent runtimes."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

from workspace import DATA_DIR, PAPERS_PATH, ROOT, load_json, load_topic, write_json


SUPPORTED_MODES = ("sequential", "claw", "swarm", "copilot", "copilot-cli", "microsoft-scouting")

MODE_PROFILES = {
    "sequential": {
        "runtime": "local-python",
        "consumer": "Deterministic local runner",
        "manifest": "data/sequential_tasks.json",
    },
    "claw": {
        "runtime": "claw",
        "consumer": "Claw-style delegated research agents",
        "manifest": "data/claw_tasks.json",
    },
    "swarm": {
        "runtime": "swarm",
        "consumer": "Subagent swarm orchestration",
        "manifest": "data/swarm_tasks.json",
    },
    "copilot": {
        "runtime": "github-copilot",
        "consumer": "GitHub Copilot coding agent or chat workspace",
        "manifest": "data/copilot_tasks.json",
    },
    "copilot-cli": {
        "runtime": "github-copilot-cli",
        "consumer": "GitHub Copilot CLI task execution",
        "manifest": "data/copilot-cli_tasks.json",
    },
    "microsoft-scouting": {
        "runtime": "microsoft-scouting",
        "consumer": "Microsoft scouting-style research agents",
        "manifest": "data/microsoft-scouting_tasks.json",
    },
}


def tasks(config: dict) -> list[dict]:
    shared = [
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
    for task in shared:
        task["agent_brief"] = f"agents/{task['role'].replace('_', '-')}.md"
        task["contract_files"] = ["AGENTS.md", "TOPIC_AGENTS.md", "topic.json"]
    return shared


def emit(mode: str, config: dict) -> dict:
    profile = MODE_PROFILES[mode]
    payload = {
        "mode": mode,
        "runtime": profile["runtime"],
        "consumer": profile["consumer"],
        "topic": config["topic"],
        "topic_contract": {
            "topic": config["topic"],
            "research_question": config.get("research_question"),
            "goal": config.get("goal"),
            "audience": config.get("audience"),
            "include": config.get("include", []),
            "exclude": config.get("exclude", []),
            "years": config.get("years", {}),
            "approval_required": config.get("approval_required", True),
        },
        "coordinator_instruction": (
            "Read AGENTS.md, TOPIC_AGENTS.md, and topic.json. Assign only accepted research-contract tasks. "
            "Use the generated role briefs under agents/. Do not publish when no new paper is accepted."
        ),
        "commands": {
            "init": "make init",
            "scout": "make scout",
            "review": "make review",
            "accept": "python3 scripts/accept_candidates.py <candidate-id>...",
            "corpus": "make corpus",
            "opportunities": "make opportunities",
            "dashboard": "make dashboard",
        },
        "tasks": tasks(config),
    }
    write_json(ROOT / profile["manifest"], payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["plan", "emit", "run"])
    parser.add_argument("--mode", choices=SUPPORTED_MODES, default="sequential")
    args = parser.parse_args()
    config = load_topic()
    payload = emit(args.mode, config)
    if args.action in {"plan", "emit"}:
        print(json.dumps(payload, indent=2))
        return 0
    if args.mode != "sequential":
        raise SystemExit("`run` executes deterministic stages only; use `emit` for agent runtimes.")
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
