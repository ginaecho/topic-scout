#!/usr/bin/env python3
"""Validate the common opportunity artifact without external dependencies."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def require(value, message: str) -> None:
    if not value:
        raise ValueError(message)


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "data/research_opportunities.json")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        require(payload.get("generated_at"), "generated_at is required")
        require(payload.get("analysis_model"), "analysis_model is required")
        require(payload.get("summary"), "summary is required")
        opportunities = payload.get("opportunities")
        require(isinstance(opportunities, list) and 3 <= len(opportunities) <= 6, "3-6 opportunities required")
        for index, item in enumerate(opportunities, start=1):
            require(item.get("rank") == index, f"rank {index} is invalid")
            require(item.get("gap_type") in {"corpus_gap", "field_gap", "evidence_gap", "translation_gap"}, f"rank {index}: gap_type")
            require(isinstance(item.get("priority_score"), int) and 0 <= item["priority_score"] <= 100, f"rank {index}: priority")
            require(item.get("confidence") in {"low", "medium", "high"}, f"rank {index}: confidence")
            require(item.get("llm_reasoning") and item.get("uncertainty"), f"rank {index}: reasoning")
            require(len(item.get("evidence", [])) >= 2, f"rank {index}: evidence")
            coverage = item.get("coverage_check")
            require(
                isinstance(coverage, dict)
                and coverage.get("query_terms")
                and coverage.get("matched_titles") is not None
                and coverage.get("interpretation"),
                f"rank {index}: coverage_check",
            )
            require(len(item.get("research_questions", [])) >= 2, f"rank {index}: research questions")
            require(len(item.get("scout_queries", [])) >= 2, f"rank {index}: scout queries")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    print(f"VALID: {len(payload['opportunities'])} opportunities")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
