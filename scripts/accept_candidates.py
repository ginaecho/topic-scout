#!/usr/bin/env python3
"""Accept explicitly selected candidate IDs into the normalized corpus."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from costs import zero_cost
from workspace import CANDIDATES_PATH, PAPERS_PATH, load_json, load_topic, write_json


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("ids", nargs="+", help="OpenAlex IDs, e.g. openalex:W123")
    args = parser.parse_args()
    config = load_topic()
    candidates = load_json(CANDIDATES_PATH, {"candidates": []})
    corpus = load_json(PAPERS_PATH, {"topic": config["topic"], "papers": [], "scout_runs": []})
    existing = {paper["id"] for paper in corpus["papers"]}
    selected = {
        paper["id"]: paper for paper in candidates["candidates"] if paper["id"] in args.ids
    }
    missing = sorted(set(args.ids) - set(selected))
    if missing:
        raise SystemExit(f"Candidate IDs not found: {', '.join(missing)}")

    timestamp = datetime.now(timezone.utc).isoformat()
    accepted = []
    for identifier in args.ids:
        if identifier in existing:
            continue
        paper = selected[identifier]
        if not paper.get("url") or not paper.get("title"):
            raise SystemExit(f"{identifier} lacks required provenance")
        paper.update(
            {
                "accepted_at": timestamp,
                "primary_category": "unclassified",
                "categories": [],
                "notes": "",
            }
        )
        corpus["papers"].append(paper)
        accepted.append(identifier)
    if not accepted:
        print("No new papers accepted; corpus unchanged.")
        return 0
    scout_runs = corpus.setdefault("scout_runs", [])
    if scout_runs and scout_runs[-1].get("accepted_ids", []) == []:
        scout_runs[-1].update(
            {
                "accepted_ids": accepted,
                "accepted_count": len(accepted),
                "cost": candidates.get("cost", zero_cost()),
            }
        )
    else:
        scout_runs.append(
            {
                "date": timestamp[:10],
                "queries": candidates.get("queries", []),
                "accepted_ids": accepted,
                "accepted_count": len(accepted),
                "candidate_count": len(candidates.get("candidates", [])),
                "cost": candidates.get("cost", zero_cost()),
            }
        )
    write_json(PAPERS_PATH, corpus)
    print(f"Accepted {len(accepted)} papers. Run `make corpus`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
