#!/usr/bin/env python3
"""Discover candidate papers without silently accepting them."""

from __future__ import annotations

import argparse
import os
from urllib.error import HTTPError, URLError
from datetime import datetime, timezone

from costs import zero_cost
from eval_metric import cheap_scores
from judging import aggregate, resolve_judging
from paper_graph import discover
from scout_llm import ScoutModelError, score_candidates
from workspace import CANDIDATES_PATH, PAPERS_PATH, load_json, load_topic, write_json

DEFAULT_ACCEPT_SCORE = 7.0


def select_for_llm(candidates, config, prefilter, limit):
    """Rank candidates by a cheap score and split into (pool, prefiltered).

    ``pool`` is sent to the LLM; ``prefiltered`` is the below-threshold,
    obviously-off-topic tail that is dropped *before* any LLM call — the token
    saving. Candidates above the threshold but beyond ``limit`` are left as-is
    (heuristic only), matching the prior over-cap behaviour. A ``keep_min``
    floor guarantees the run never empties out on a sparse topic.
    """
    scores = cheap_scores(candidates, config, prefilter.get("scorer", "current"))
    ranked = sorted(candidates, key=lambda c: -scores.get(c["id"], 0.0))
    if not prefilter.get("enabled", True):
        return ranked[:limit], [], scores
    threshold = prefilter.get("threshold", 0.0)
    above = [c for c in ranked if scores.get(c["id"], 0.0) > threshold]
    below = [c for c in ranked if scores.get(c["id"], 0.0) <= threshold]
    keep_min = int(prefilter.get("keep_min", 0) or 0)
    if len(above) < keep_min:  # rescue the best of the tail so the run isn't empty
        rescued = ranked[:keep_min]
        rescued_ids = {c["id"] for c in rescued}
        above = rescued
        below = [c for c in ranked if c["id"] not in rescued_ids]
    return above[:limit], below, scores


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
    prefilter_group = parser.add_mutually_exclusive_group()
    prefilter_group.add_argument(
        "--prefilter",
        dest="prefilter",
        action="store_true",
        default=None,
        help="Drop obviously-off-topic candidates with a cheap score before LLM judging",
    )
    prefilter_group.add_argument(
        "--no-prefilter",
        dest="prefilter",
        action="store_false",
        help="Send every discovered candidate to the LLM (disable the cheap gate)",
    )
    parser.add_argument("--prefilter-score", type=float, help="Prefilter drop threshold override")
    parser.add_argument("--prefilter-scorer", help="Prefilter scorer override (current, hybrid, tfidf_cosine, bm25)")
    args = parser.parse_args()
    config = load_topic()
    accept_score = args.accept_score
    if accept_score is None and not config["approval_required"]:
        accept_score = DEFAULT_ACCEPT_SCORE
    discovery_error = None
    try:
        result = discover(config, args.query, args.seed_limit, args.neighbors)
    except (HTTPError, URLError, TimeoutError) as exc:
        discovery_error = f"{type(exc).__name__}: {exc}"
        result = {
            "topic": config["topic"],
            "queries": [args.query] if args.query else config["search_queries"],
            "candidates": [],
            "edges": [],
            "discovery_error": discovery_error,
        }
    existing = load_json(PAPERS_PATH, {"papers": []})
    known = {paper["id"] for paper in existing.get("papers", [])}
    result["generated_at"] = datetime.now(timezone.utc).isoformat()
    if discovery_error:
        result["cost"] = zero_cost()
        result["scout_provider"] = "openalex"
    elif args.offline:
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
        judging = resolve_judging(config, accept_hi=args.accept_score)
        prefilter = dict(judging["prefilter"])
        if args.prefilter is not None:
            prefilter["enabled"] = args.prefilter
        if args.prefilter_score is not None:
            prefilter["threshold"] = args.prefilter_score
        if args.prefilter_scorer:
            prefilter["scorer"] = args.prefilter_scorer
        llm_candidates, prefiltered, cheap = select_for_llm(
            result["candidates"], config, prefilter, max(0, args.llm_candidates)
        )
        result["prefiltered_count"] = len(prefiltered)
        try:
            updates, usage = score_candidates(
                config,
                llm_candidates,
                provider=provider,
                model=args.model or config.get("scout_model"),
            )
        except ScoutModelError as exc:
            raise SystemExit(f"Scout scoring failed: {exc}")
        reference_year = (config.get("years") or {}).get("to") or int(result["generated_at"][:4])
        for candidate in result["candidates"]:
            # Preserve the independent keyword heuristic before the judge's
            # rubric overwrites the ranked score.
            heuristic_score = candidate.get("relevance_score", 0)
            candidate["heuristic_relevance_score"] = heuristic_score
            candidate["heuristic_relevance_reason"] = candidate.get("relevance_reason", "")
            rubric = updates.get(candidate["id"])
            if rubric:
                verdict = aggregate(
                    rubric,
                    judging,
                    year=candidate.get("year"),
                    reference_year=reference_year,
                    heuristic_score=heuristic_score,
                )
                candidate.update(verdict)
                candidate["relevance_reason"] = rubric["relevance_reason"]
                candidate["rubric"] = {
                    key: rubric[key]
                    for key in ("topical_fit", "evidence_match", "rigor", "exclusion_hit")
                }
        # Mark the cheap-dropped tail (after heuristic fields are preserved) so
        # nothing is silently lost and it never auto-accepts.
        prefiltered_ids = {candidate["id"] for candidate in prefiltered}
        for candidate in result["candidates"]:
            if candidate["id"] in prefiltered_ids:
                candidate["relevance_verdict"] = "prefiltered"
                candidate["relevance_reason"] = (
                    f"Cheap {prefilter.get('scorer', 'current')} score "
                    f"{cheap.get(candidate['id'], 0.0):.2f} <= prefilter threshold "
                    f"{prefilter.get('threshold', 0.0)}; not LLM-judged."
                )
        result["candidates"].sort(
            key=lambda item: (
                -item.get("relevance_score", 0),
                -item.get("relevance_confidence", 0),
                -item.get("citation_count", 0),
                -(item.get("year") or 0),
            )
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
        "prefiltered_count": result.get("prefiltered_count", 0),
        "cost": result["cost"],
    }
    existing.setdefault("scout_runs", []).append(scout_run)
    def _auto_acceptable(candidate: dict) -> bool:
        if candidate["id"] in known or not candidate.get("abstract"):
            return False
        # When the judge produced a verdict, honor the accept/uncertain/reject
        # band; the uncertainty band stays in the review queue for a human.
        # Otherwise (offline/heuristic path) fall back to the raw threshold.
        if "relevance_verdict" in candidate:
            return candidate["relevance_verdict"] == "accept"
        return candidate["relevance_score"] >= accept_score

    if not config["approval_required"] and accept_score is not None:
        accepted = [
            candidate for candidate in result["candidates"]
            if _auto_acceptable(candidate)
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
    prefiltered_count = result.get("prefiltered_count", 0)
    if prefiltered_count:
        total = len(result["candidates"])
        judged = total - prefiltered_count
        saving = 100 * prefiltered_count / total if total else 0
        print(
            f"Prefilter dropped {prefiltered_count}/{total} obvious-off-topic candidates "
            f"before LLM scoring ({judged} judged, ~{saving:.0f}% fewer LLM calls)."
        )
    if discovery_error:
        print(f"OpenAlex discovery failed; wrote an empty candidate queue. {discovery_error}")
    uncertain = [
        candidate for candidate in result["candidates"]
        if candidate.get("relevance_verdict") == "uncertain" and candidate["id"] not in known
    ]
    if config["approval_required"]:
        print(f"Review {CANDIDATES_PATH}; acceptance requires a librarian or human.")
    elif accepted:
        print(f"Accepted {len(accepted)} candidates (verdict=accept, score >= {accept_score}).")
    elif not config["approval_required"]:
        print(f"No candidates met the auto-accept bar (verdict=accept, score >= {accept_score}).")
    if uncertain:
        print(
            f"{len(uncertain)} candidate(s) landed in the uncertainty band; "
            f"review {CANDIDATES_PATH} for verdict=uncertain."
        )
    print(
        f"Scout cost: {result['cost']['token_count']} tokens, "
        f"${result['cost']['money_cost_usd']:.2f} {result['cost']['currency']}."
    )
    if result["cost"].get("note"):
        print(result["cost"]["note"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
