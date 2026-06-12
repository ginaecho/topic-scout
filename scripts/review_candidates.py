#!/usr/bin/env python3
"""Print a compact candidate review queue and explicit acceptance command."""

from __future__ import annotations

import argparse

from workspace import CANDIDATES_PATH, PAPERS_PATH, load_json


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=20)
    args = parser.parse_args()
    candidates = load_json(CANDIDATES_PATH, {"candidates": []})
    known = {paper["id"] for paper in load_json(PAPERS_PATH, {"papers": []})["papers"]}
    rows = [paper for paper in candidates["candidates"] if paper["id"] not in known][: args.top]
    if not rows:
        print("No new candidates to review.")
        return 0
    for index, paper in enumerate(rows, start=1):
        print(
            f"{index}. {paper['title']} ({paper.get('year') or 'n/a'})\n"
            f"   ID: {paper['id']} | score={paper['relevance_score']} | "
            f"citations={paper['citation_count']}\n"
            f"   {paper.get('url') or 'no URL'}\n"
            f"   {paper['relevance_reason']}"
        )
    print("\nAccept selected IDs explicitly:")
    print("python3 scripts/accept_candidates.py openalex:W... openalex:W...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
