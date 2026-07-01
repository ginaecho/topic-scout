#!/usr/bin/env python3
"""Shared paths and configuration helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path


ROOT = Path(os.environ.get("TOPIC_SCOUT_ROOT", Path(__file__).resolve().parents[1])).resolve()
TOPIC_CONFIG = ROOT / "topic.json"
TOPIC_AGENTS_PATH = ROOT / "TOPIC_AGENTS.md"
DATA_DIR = ROOT / "data"
REPORTS_DIR = ROOT / "reports"
PAPERS_PATH = DATA_DIR / "papers.json"
CANDIDATES_PATH = DATA_DIR / "candidates.json"
OPPORTUNITIES_PATH = DATA_DIR / "research_opportunities.json"
REPORT_PATH = REPORTS_DIR / "research_report.md"
DASHBOARD_PATH = ROOT / "topic-dashboard.html"


def load_topic() -> dict:
    if not TOPIC_CONFIG.exists():
        raise SystemExit("topic.json is missing. Run `make init` first.")
    return json.loads(TOPIC_CONFIG.read_text(encoding="utf-8"))


def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
