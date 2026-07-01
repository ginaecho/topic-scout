#!/usr/bin/env python3
"""Discover candidate papers without silently accepting them."""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone

from costs import zero_cost
from paper_graph import discover
from scout_llm import ScoutModelError, score_candidates
from workspace import CANDIDATES_PATH, PAPERS_PATH, load_json, load_topic, write_json

DEFAULT_ACCEPT_SCORE = 7.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query")
    parser.add_argument("--seed-limit", type=int, default=5)
    parser.add_argument("--neighbors", type=int, default=8)
    parser.add_argument(
        "--accept-score",
        type=float,
        default=None,
        help="Accept candidates at or above this score when topic.json allows auto-approval",
    )
    parser.add_argument(
        "--provider",
        choices=["codex", "api"],
        help="Scout scoring provider. Defaults to topic.json or codex.",
    )
    parser.add_argument("--model", help="Model override for scout scoring")
    parser.add_argument(
        "--llm-candidates",
        type=int,
        default=40,
        help="How many discovered candidates to rescore with the model",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Skip model-backed scout scoring and keep OpenAlex-only heuristic ranking",
    )
    args = parser.parse_args()
    config = load_topic()
    accept_score = args.accept_score
    if accept_score is None and not config["approval_required"]:
        accept_score = DEFAULT_ACCEPT_SCORE
    result = discover(config, args.query, args.seed_limit, args.neighbors)
    existing = load_json(PAPERS_PATH, {"papers": []})
    known = {paper["id"] for paper in existing.get("papers", [])}
    result["generated_at"] = datetime.now(timezone.utc).isoformat()
    if args.offline:
        result["cost"] = zero_cost()
        result["scout_provider"] = "openalex"
    else:
        provider = (
            args.provider
            or config.get("scout_provider")
            or os.environ.get("TOPIC_SCOUT_SCOUT_PROVIDER")
            or "codex"
        )
        if provider == "openalex":
            result["cost"] = zero_cost()
            result["scout_provider"] = "openalex"
            result["new_candidate_count"] = sum(
                candidate["id"] not in known for candidate in result["candidates"]
            )
            write_json(CANDIDATES_PATH, result)
            existing.setdefault("scout_runs", []).append(
                {
                    "date": result["generated_at"][:10],
                    "queries": result["queries"],
                    "accepted_ids": [],
                    "accepted_count": 0,
                    "candidate_count": len(result["candidates"]),
                    "cost": result["cost"],
                }
            )
            write_json(PAPERS_PATH, existing)
            print(
                f"Discovered {len(result['candidates'])} candidates "
                f"({result['new_candidate_count']} not in corpus)."
            )
            print("Scout cost: 0 tokens, $0.00 USD.")
            print("topic.json requested the legacy OpenAlex-only scout path; rerun with --provider codex or --provider api to require an LLM.")
            return 0
        llm_candidates = result["candidates"][: max(0, args.llm_candidates)]
        try:
            updates, usage = score_candidates(
                config,
                llm_candidates,
                provider=provider,
                model=args.model or config.get("scout_model"),
            )
        except ScoutModelError as exc:
            raise SystemExit(f"Scout scoring failed: {exc}")
        for candidate in result["candidates"]:
            candidate["heuristic_relevance_score"] = candidate.get("relevance_score", 0)
            candidate["heuristic_relevance_reason"] = candidate.get("relevance_reason", "")
            update = updates.get(candidate["id"])
            if update:
                candidate.update(update)
        result["candidates"].sort(
            key=lambda item: (-item.get("relevance_score", 0), -item.get("citation_count", 0), -(item.get("year") or 0))
        )
        result["cost"] = usage
        result["scout_provider"] = provider
    result["new_candidate_count"] = sum(
        candidate["id"] not in known for candidate in result["candidates"]
    )
    write_json(CANDIDATES_PATH, result)

    accepted = []
    scout_run = {
        "date": result["generated_at"][:10],
        "queries": result["queries"],
        "accepted_ids": [],
        "accepted_count": 0,
        "candidate_count": len(result["candidates"]),
        "cost": result["cost"],
    }
    existing.setdefault("scout_runs", []).append(scout_run)
    if not config["approval_required"] and accept_score is not None:
        accepted = [
            candidate for candidate in result["candidates"]
            if candidate["id"] not in known
            and candidate["relevance_score"] >= accept_score
            and candidate["abstract"]
        ]
        if accepted:
            for candidate in accepted:
                candidate.update(
                    {
                        "accepted_at": result["generated_at"],
                        "primary_category": "unclassified",
                        "categories": [],
                        "notes": "",
                    }
                )
            existing["papers"].extend(accepted)
            scout_run["accepted_ids"] = [paper["id"] for paper in accepted]
            scout_run["accepted_count"] = len(accepted)
            write_json(PAPERS_PATH, existing)
    else:
        write_json(PAPERS_PATH, existing)

    print(
        f"Discovered {len(result['candidates'])} candidates "
        f"({result['new_candidate_count']} not in corpus)."
    )
    if config["approval_required"]:
        print(f"Review {CANDIDATES_PATH}; acceptance requires a librarian or human.")
    elif accepted:
        print(f"Accepted {len(accepted)} candidates at score >= {accept_score}.")
    elif not config["approval_required"]:
        print(f"No candidates met the auto-accept threshold of {accept_score}.")
    print(
        f"Scout cost: {result['cost']['token_count']} tokens, "
        f"${result['cost']['money_cost_usd']:.2f} {result['cost']['currency']}."
    )
    if result["cost"].get("note"):
        print(result["cost"]["note"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
