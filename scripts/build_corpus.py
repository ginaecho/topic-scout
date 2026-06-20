#!/usr/bin/env python3
"""Generate Markdown notes and a synthesis report from accepted papers."""

from __future__ import annotations

import re
from collections import Counter

from workspace import PAPERS_PATH, REPORTS_DIR, REPORT_PATH, load_json, load_topic


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:90]


def category_tokens(category: str) -> list[str]:
    stop = {
        "and", "or", "the", "of", "for", "in", "to", "by", "with", "on", "a", "an",
        "that", "this", "their", "other", "across", "through", "while", "when",
        "which", "from", "into", "under", "over", "using", "use", "used",
        "technical", "documented", "relevant", "including", "should", "include",
        "evidence", "context", "quality", "details", "analysis", "assessment",
    }
    return [
        token
        for token in re.findall(r"[a-z0-9]+", category.lower())
        if len(token) >= 4 and token not in stop
    ][:12]


def classify(paper: dict, config: dict) -> str:
    if paper.get("primary_category") not in (None, "", "unclassified"):
        return paper["primary_category"]
    text = " ".join(
        [paper.get("title", ""), paper.get("abstract", ""), *paper.get("topics", [])]
    ).lower()
    scores = {
        category: sum(token in text for token in category_tokens(category))
        for category in config["taxonomy"]
    }
    return max(config["taxonomy"], key=lambda category: (scores[category], -config["taxonomy"].index(category)))


def main() -> int:
    config = load_topic()
    corpus = load_json(PAPERS_PATH, {"papers": [], "scout_runs": []})
    papers = corpus["papers"]
    scout_runs = corpus.get("scout_runs", [])
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
        f"**Scout runs:** {len(scout_runs)}",
        "",
        "## Corpus Shape",
        "",
    ]
    lines.extend(f"- **{category}:** {counts[category]}" for category in config["taxonomy"])
    total_tokens = 0
    total_cost = 0.0
    lines.extend(["", "## Scout Usage", ""])
    if scout_runs:
        for run in scout_runs:
            cost = run.get("cost") or {}
            total_tokens += int(cost.get("token_count", 0) or 0)
            total_cost += float(cost.get("money_cost_usd", 0.0) or 0.0)
            provider = cost.get("provider", "unknown")
            model = cost.get("model") or "n/a"
            lines.append(
                f"- **{run.get('date', 'unknown date')}:** {run.get('candidate_count', 0)} candidates, "
                f"{run.get('accepted_count', len(run.get('accepted_ids', [])))} accepted, "
                f"{int(cost.get('token_count', 0) or 0)} tokens, "
                f"${float(cost.get('money_cost_usd', 0.0) or 0.0):.2f} "
                f"{cost.get('currency', 'USD')} via {provider} ({model})"
            )
            if cost.get("note"):
                lines.append(f"  Note: {cost['note']}")
    else:
        lines.append("- No scout runs recorded yet.")
    lines.extend(
        [
            "",
            f"**Total scout tokens:** {total_tokens}",
            f"**Total scout spend:** ${total_cost:.2f}",
        ]
    )
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
