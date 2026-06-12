#!/usr/bin/env python3
"""Generate Markdown notes and a synthesis report from accepted papers."""

from __future__ import annotations

import re
from collections import Counter

from workspace import PAPERS_PATH, REPORTS_DIR, REPORT_PATH, load_json, load_topic


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:90]


def classify(paper: dict, config: dict) -> str:
    if paper.get("primary_category") not in (None, "", "unclassified"):
        return paper["primary_category"]
    text = " ".join(
        [paper.get("title", ""), paper.get("abstract", ""), *paper.get("topics", [])]
    ).lower()
    scores = {
        category: sum(token in text for token in category.lower().split())
        for category in config["taxonomy"]
    }
    return max(config["taxonomy"], key=lambda category: (scores[category], -config["taxonomy"].index(category)))


def main() -> int:
    config = load_topic()
    corpus = load_json(PAPERS_PATH, {"papers": [], "scout_runs": []})
    papers = corpus["papers"]
    notes_dir = REPORTS_DIR / "papers"
    notes_dir.mkdir(parents=True, exist_ok=True)
    counts = Counter()
    for paper in papers:
        category = classify(paper, config)
        paper["primary_category"] = category
        counts[category] += 1
        content = f"""# {paper['title']}

- **Identifier:** `{paper['id']}`
- **Year:** {paper.get('year') or 'unknown'}
- **Primary category:** {category}
- **Source:** {paper.get('url') or 'unavailable'}
- **Citations at discovery:** {paper.get('citation_count', 0)}

## Abstract

{paper.get('abstract') or 'Abstract unavailable.'}

## Scout Assessment

- Relevance score: {paper.get('relevance_score', 0)}
- Reason: {paper.get('relevance_reason', 'Not recorded.')}
- Notes: {paper.get('notes') or 'Pending analyst notes.'}

## Provenance

Discovered via: {", ".join(paper.get('discovered_via', []))}
"""
        (notes_dir / f"{slug(paper['title'])}.md").write_text(content, encoding="utf-8")

    lines = [
        f"# {config['topic']}: Research Scout Report",
        "",
        f"**Goal:** {config['goal']}",
        "",
        f"**Accepted papers:** {len(papers)}",
        "",
        "## Corpus Shape",
        "",
    ]
    lines.extend(f"- **{category}:** {counts[category]}" for category in config["taxonomy"])
    lines.extend(["", "## Papers", ""])
    for paper in sorted(papers, key=lambda item: (-(item.get("year") or 0), item["title"])):
        lines.extend(
            [
                f"### {paper['title']}",
                "",
                f"- Source: {paper.get('url')}",
                f"- Year: {paper.get('year')}",
                f"- Category: {paper['primary_category']}",
                "",
                paper.get("abstract") or "Abstract unavailable.",
                "",
            ]
        )
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    # Persist classifications only when content actually changed.
    from workspace import write_json
    write_json(PAPERS_PATH, corpus)
    print(f"Built {len(papers)} paper notes and {REPORT_PATH}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
