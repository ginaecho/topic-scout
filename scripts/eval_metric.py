#!/usr/bin/env python3
"""Compare cheap deterministic relevance metrics against the LLM judge.

The scout keeps a fast, token-free deterministic metric and an (expensive)
LLM judge. This harness treats the LLM's ``relevance_score`` as ground truth
and measures how well each candidate deterministic metric recovers it, using
rank-based, scale-free metrics (Spearman, ROC-AUC, precision@K, NDCG, top-K
overlap). The goal: find the cheapest metric that best matches LLM quality, so
scout runs can lean on it and call the LLM far less often.

Usage:
    python3 scripts/eval_metric.py                 # bundled 540-paper example
    python3 scripts/eval_metric.py --input data/candidates.json --topic topic.json
    python3 scripts/eval_metric.py --report reports/metric_eval.md
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

from paper_graph import Candidate, relevance as current_relevance
from workspace import ROOT

EXAMPLE_DIR = ROOT / "examples" / "ai-in-hiring-processes"

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "for", "in", "to", "by", "with", "on",
    "that", "this", "their", "other", "across", "through", "while", "when",
    "which", "from", "into", "under", "over", "using", "use", "used", "is",
    "are", "be", "as", "at", "we", "our", "it", "its", "can", "based", "study",
    "paper", "approach", "method", "results", "these", "such", "than", "also",
}

POSITIVE_THRESHOLD = 7.0  # LLM score at/above which a paper counts as relevant


# --------------------------------------------------------------------------- #
# Text helpers
# --------------------------------------------------------------------------- #
def tokens(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+", (text or "").lower())
        if len(token) >= 3 and token not in STOPWORDS
    ]


def paper_text(paper: dict) -> tuple[list[str], list[str]]:
    """Return (title_tokens, body_tokens) for a candidate."""
    title = tokens(paper.get("title", ""))
    body = tokens(paper.get("abstract", "")) + tokens(" ".join(paper.get("topics", []) or []))
    return title, body


def contract_terms(config: dict) -> list[str]:
    """Flatten the topic contract into a weighted query token list."""
    parts: list[str] = []
    # Include phrases and the research question carry the most signal.
    for phrase in config.get("include", []):
        parts += tokens(phrase) * 3
    parts += tokens(config.get("topic", "")) * 2
    parts += tokens(config.get("research_question", "")) * 2
    for query in config.get("search_queries", []):
        parts += tokens(query)
    for term in config.get("taxonomy", []):
        parts += tokens(term)
    return parts


def exclude_terms(config: dict) -> set[str]:
    out: set[str] = set()
    for phrase in config.get("exclude", []):
        out.update(tokens(phrase))
    return out


# --------------------------------------------------------------------------- #
# Deterministic scorers (all token-free / no LLM)
# --------------------------------------------------------------------------- #
def score_current(paper: dict, config: dict, ctx: dict) -> float:
    candidate = Candidate(
        paper.get("id", ""), paper.get("title", ""), paper.get("year"),
        paper.get("url", ""), paper.get("doi"), paper.get("abstract", ""),
        paper.get("citation_count", 0) or 0, paper.get("topics", []) or [],
        paper.get("discovered_via", []) or [],
    )
    score, _ = current_relevance(candidate, config)
    return score


def score_lexical_v2(paper: dict, config: dict, ctx: dict) -> float:
    """Token-level include coverage with a title boost and exclude penalty.

    Fixes the current metric's fatal flaw: multi-word include phrases almost
    never appear verbatim, so exact-substring counting scores near-constant.
    Here each include phrase earns partial credit for the fraction of its
    content tokens present, weighted higher in the title.
    """
    title, body = ctx["title"], ctx["body"]
    title_set, body_set = set(title), set(body)
    all_set = title_set | body_set
    score = 0.0
    for phrase in config.get("include", []):
        toks = [t for t in tokens(phrase)]
        if not toks:
            continue
        covered = sum(t in all_set for t in toks) / len(toks)
        in_title = any(t in title_set for t in toks)
        score += covered * (1.6 if in_title else 1.0)
    topic_toks = set(tokens(config.get("topic", "")))
    score += 0.4 * len(topic_toks & all_set)
    score -= 2.0 * len(ctx["exclude"] & all_set)
    return score


def _tfidf_vectors(config: dict, ctx: dict):
    idf = ctx["idf"]
    # Query vector from the contract terms.
    qvec: dict[str, float] = {}
    for token in ctx["query_terms"]:
        qvec[token] = qvec.get(token, 0.0) + idf.get(token, ctx["idf_default"])
    return qvec


def score_tfidf_cosine(paper: dict, config: dict, ctx: dict) -> float:
    idf = ctx["idf"]
    qvec = ctx["qvec"]
    title, body = ctx["title"], ctx["body"]
    tf: dict[str, float] = {}
    for token in body:
        tf[token] = tf.get(token, 0.0) + 1.0
    for token in title:  # title tokens weighted double
        tf[token] = tf.get(token, 0.0) + 2.0
    dvec = {token: freq * idf.get(token, ctx["idf_default"]) for token, freq in tf.items()}
    num = sum(dvec.get(token, 0.0) * weight for token, weight in qvec.items())
    dnorm = math.sqrt(sum(v * v for v in dvec.values()))
    qnorm = math.sqrt(sum(v * v for v in qvec.values()))
    if dnorm == 0 or qnorm == 0:
        return 0.0
    return num / (dnorm * qnorm)


def score_bm25(paper: dict, config: dict, ctx: dict) -> float:
    idf = ctx["idf"]
    k1, b = 1.5, 0.75
    title, body = ctx["title"], ctx["body"]
    doc = body + title + title  # title tokens counted thrice overall
    if not doc:
        return 0.0
    tf: dict[str, float] = {}
    for token in doc:
        tf[token] = tf.get(token, 0.0) + 1.0
    dl = len(doc)
    avgdl = ctx["avgdl"]
    score = 0.0
    for token in set(ctx["query_terms"]):
        if token not in tf:
            continue
        term_idf = idf.get(token, ctx["idf_default"])
        freq = tf[token]
        score += term_idf * (freq * (k1 + 1)) / (freq + k1 * (1 - b + b * dl / avgdl))
    return score


def score_tfidf_cites(paper: dict, config: dict, ctx: dict) -> float:
    """TF-IDF cosine blended with a small log-citation prior."""
    base = score_tfidf_cosine(paper, config, ctx)
    cites = paper.get("citation_count", 0) or 0
    return base + 0.03 * math.log1p(cites)


def score_idf_coverage(paper: dict, config: dict, ctx: dict) -> float:
    """IDF-weighted include coverage — the fix for naive lexical_v2.

    Only rare, discriminative include tokens earn credit, so generic tokens
    shared by off-topic neighbours stop inflating the score.
    """
    idf = ctx["idf"]
    title, body = ctx["title"], ctx["body"]
    title_set, all_set = set(title), set(title) | set(body)
    score = 0.0
    for phrase in config.get("include", []):
        toks = tokens(phrase)
        if not toks:
            continue
        weight = sum(idf.get(t, ctx["idf_default"]) for t in toks if t in all_set)
        weight += 0.5 * sum(idf.get(t, ctx["idf_default"]) for t in toks if t in title_set)
        score += weight
    score -= 2.0 * sum(idf.get(t, ctx["idf_default"]) for t in ctx["exclude"] if t in all_set)
    return score


def score_hybrid(paper: dict, config: dict, ctx: dict) -> float:
    """Coarse high-precision include gate + TF-IDF resolution + citation prior.

    The current metric's exact include-phrase match is the dominant term (it
    separates on-topic from off-topic well); TF-IDF cosine breaks ties within a
    bucket so the metric can actually rank the top papers, and a gentle log-cite
    prior nudges credibility.
    """
    gate = score_current(paper, config, ctx)
    resolution = score_tfidf_cosine(paper, config, ctx)
    cites = paper.get("citation_count", 0) or 0
    return 5.0 * gate + resolution + 0.05 * math.log1p(cites)


SCORERS = {
    "current": score_current,
    "lexical_v2": score_lexical_v2,
    "idf_coverage": score_idf_coverage,
    "tfidf_cosine": score_tfidf_cosine,
    "bm25": score_bm25,
    "tfidf_cites": score_tfidf_cites,
    "hybrid": score_hybrid,
}


# --------------------------------------------------------------------------- #
# Rank-based metrics (pure Python, no deps)
# --------------------------------------------------------------------------- #
def _ranks(values: list[float]) -> list[float]:
    """Average (fractional) ranks, ties shared."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n == 0:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return 0.0
    return num / (dx * dy)


def spearman(xs: list[float], ys: list[float]) -> float:
    return pearson(_ranks(xs), _ranks(ys))


def roc_auc(scores: list[float], labels: list[int]) -> float:
    """Mann-Whitney AUC with tie handling; labels are 0/1."""
    pos = sum(labels)
    neg = len(labels) - pos
    if pos == 0 or neg == 0:
        return float("nan")
    ranks = _ranks(scores)
    rank_sum_pos = sum(r for r, l in zip(ranks, labels) if l == 1)
    return (rank_sum_pos - pos * (pos + 1) / 2.0) / (pos * neg)


def precision_at_k(scores: list[float], labels: list[int], k: int) -> float:
    order = sorted(range(len(scores)), key=lambda i: -scores[i])[:k]
    return sum(labels[i] for i in order) / max(1, len(order))


def recall_at_k(scores: list[float], labels: list[int], k: int) -> float:
    total = sum(labels)
    if total == 0:
        return float("nan")
    order = sorted(range(len(scores)), key=lambda i: -scores[i])[:k]
    return sum(labels[i] for i in order) / total


def ndcg_at_k(scores: list[float], gains: list[float], k: int) -> float:
    order = sorted(range(len(scores)), key=lambda i: -scores[i])[:k]
    dcg = sum(gains[idx] / math.log2(rank + 2) for rank, idx in enumerate(order))
    ideal = sorted(gains, reverse=True)[:k]
    idcg = sum(g / math.log2(rank + 2) for rank, g in enumerate(ideal))
    return dcg / idcg if idcg else 0.0


def overlap_at_k(scores: list[float], gains: list[float], k: int) -> float:
    top_scorer = set(sorted(range(len(scores)), key=lambda i: -scores[i])[:k])
    top_truth = set(sorted(range(len(gains)), key=lambda i: -gains[i])[:k])
    return len(top_scorer & top_truth) / max(1, k)


# --------------------------------------------------------------------------- #
# Harness
# --------------------------------------------------------------------------- #
def build_context(papers: list[dict], config: dict) -> dict:
    """Precompute IDF and contract query terms shared across scorers."""
    docs_tokens = []
    for paper in papers:
        title, body = paper_text(paper)
        docs_tokens.append(set(title) | set(body))
    n = len(docs_tokens)
    df: dict[str, int] = {}
    for doc in docs_tokens:
        for token in doc:
            df[token] = df.get(token, 0) + 1
    idf = {token: math.log((n + 1) / (count + 1)) + 1.0 for token, count in df.items()}
    idf_default = math.log((n + 1) / 1.0) + 1.0
    query_terms = contract_terms(config)
    avgdl = sum(len(paper_text(p)[0]) * 2 + len(paper_text(p)[1]) for p in papers) / max(1, n)
    ctx = {
        "idf": idf,
        "idf_default": idf_default,
        "query_terms": query_terms,
        "exclude": exclude_terms(config),
        "avgdl": max(1.0, avgdl),
    }
    ctx["qvec"] = _tfidf_vectors(config, ctx)
    return ctx


def routing_analysis(labeled: list[dict], config: dict, scorer_name: str = "current") -> dict:
    """How much LLM work a cheap prefilter can save at zero recall loss.

    Auto-drops candidates whose cheap score is at or below the highest
    threshold that loses no relevant paper, and reports what fraction still
    needs the LLM. This is the token-saving lever: the LLM only judges the
    ambiguous survivors, not the obvious-off-topic mass.
    """
    ctx = build_context(labeled, config)
    scorer = SCORERS[scorer_name]
    scores, labels = [], []
    for paper in labeled:
        title, body = paper_text(paper)
        scores.append(scorer(paper, config, {**ctx, "title": title, "body": body}))
        labels.append(1 if float(paper["relevance_score"]) >= POSITIVE_THRESHOLD else 0)
    total_pos = sum(labels)
    # Highest auto-drop threshold that still loses zero relevant papers.
    best_threshold, best_dropped = None, 0
    for threshold in sorted(set(scores)):
        dropped = [i for i, s in enumerate(scores) if s <= threshold]
        if sum(labels[i] for i in dropped) == 0 and len(dropped) > best_dropped:
            best_threshold, best_dropped = threshold, len(dropped)
    llm_calls = len(scores) - best_dropped
    return {
        "scorer": scorer_name,
        "candidates": len(scores),
        "relevant": total_pos,
        "auto_drop_threshold": best_threshold,
        "auto_dropped": best_dropped,
        "llm_calls": llm_calls,
        "llm_fraction": round(llm_calls / max(1, len(scores)), 4),
        "token_saving": round(1 - llm_calls / max(1, len(scores)), 4),
        "recall_retained": 1.0 if total_pos else float("nan"),
    }


def evaluate(papers: list[dict], config: dict) -> dict:
    labeled = [p for p in papers if p.get("relevance_score") is not None]
    gains = [float(p["relevance_score"]) for p in labeled]
    labels = [1 if g >= POSITIVE_THRESHOLD else 0 for g in gains]
    ctx = build_context(labeled, config)

    results = {}
    for name, scorer in SCORERS.items():
        per_paper_ctx = []
        scores = []
        for paper in labeled:
            title, body = paper_text(paper)
            pctx = {**ctx, "title": title, "body": body}
            scores.append(scorer(paper, config, pctx))
        results[name] = {
            "spearman": round(spearman(scores, gains), 4),
            "pearson": round(pearson(scores, gains), 4),
            "auc": round(roc_auc(scores, labels), 4),
            "precision@10": round(precision_at_k(scores, labels, 10), 4),
            "recall@10": round(recall_at_k(scores, labels, 10), 4),
            "ndcg@20": round(ndcg_at_k(scores, gains, 20), 4),
            "overlap@20": round(overlap_at_k(scores, gains, 20), 4),
            "distinct_values": len(set(round(s, 6) for s in scores)),
        }
    # Rank scorers by AUC to pick the best coarse gate for routing.
    def _auc(name):
        auc = results[name]["auc"]
        return auc if auc == auc else -1.0
    best_gate = max(results, key=_auc)
    return {
        "n": len(labeled),
        "n_positive": sum(labels),
        "positive_threshold": POSITIVE_THRESHOLD,
        "metrics": results,
        "routing": routing_analysis(labeled, config, "current"),
        "routing_best_auc": routing_analysis(labeled, config, best_gate),
    }


def render_report(summary: dict, source: str) -> str:
    metrics = summary["metrics"]
    order = ["spearman", "auc", "precision@10", "recall@10", "ndcg@20", "overlap@20", "distinct_values"]
    header = "| scorer | " + " | ".join(order) + " |"
    divider = "|" + "---|" * (len(order) + 1)
    rows = []
    # Rank scorers by AUC (nan last), then Spearman.
    def sort_key(item):
        m = item[1]
        auc = m["auc"] if m["auc"] == m["auc"] else -1  # nan guard
        return (-auc, -m["spearman"])
    for name, m in sorted(metrics.items(), key=sort_key):
        cells = [f"{m[k]}" for k in order]
        rows.append(f"| `{name}` | " + " | ".join(cells) + " |")
    lines = [
        "# Deterministic metric vs. LLM judge",
        "",
        f"- Source: `{source}`",
        f"- Labeled candidates: **{summary['n']}** "
        f"(**{summary['n_positive']}** relevant at LLM score ≥ {summary['positive_threshold']:.0f})",
        "- Ground truth: the LLM judge's `relevance_score`.",
        "- Metrics are rank-based / scale-free (higher is better; AUC 0.5 = random,"
        " 1.0 = perfect ranking).",
        "",
        header,
        divider,
        *rows,
        "",
        "`distinct_values` = how many different scores the metric produces across the"
        " set — a proxy for discriminative power (1 = useless as a ranker).",
    ]

    for label, route in (("current", summary.get("routing")), ("best-AUC", summary.get("routing_best_auc"))):
        if not route:
            continue
        saving = route["token_saving"] * 100
        lines += [
            "",
            f"## Token-saving prefilter ({label} gate: `{route['scorer']}`)",
            "",
            f"- Auto-drop candidates with score ≤ `{route['auto_drop_threshold']}` "
            f"→ removes **{route['auto_dropped']}/{route['candidates']}** candidates.",
            f"- LLM judges only the **{route['llm_calls']}** survivors "
            f"(**{route['llm_fraction'] * 100:.1f}%** of candidates) — "
            f"**~{saving:.0f}% fewer LLM calls**.",
            f"- Relevant papers retained: **{route['recall_retained']}** "
            f"({route['relevant']} of {route['relevant']} kept).",
        ]
    lines += [
        "",
        "## How to read this / recommendations",
        "",
        "- **Two jobs, two metrics.** Dropping the obvious off-topic mass (a *routing* job,"
        " measured by AUC) and ranking the shortlist (a *precision* job, measured by"
        " precision@K / NDCG / overlap) are different. High-AUC metrics (`hybrid`, `tfidf`,"
        " `bm25`) route best; exact include-phrase matching (`current`) ranks the top best but"
        " is coarse (few `distinct_values`).",
        "- **Biggest token win = prefilter routing.** Use a high-recall cheap gate to auto-drop"
        " candidates the metric is confident are off-topic, and only spend LLM tokens on the"
        " survivors + the uncertainty band. That is where the ~90% saving comes from.",
        "- **Don't expect a cheap metric to reproduce fine LLM scores.** Ranking 7-vs-10 among"
        " relevant papers needs the model; keep the LLM for the shortlist and the ambiguous"
        " band only.",
        "- **IDF-weight any lexical signal.** Naive token-coverage (`lexical_v2`) scores *worse"
        " than random* because generic tokens shared by adjacent-but-wrong papers dominate.",
        "",
        "> Numbers are for one topic/corpus and a small positive set; the LLM labels are"
        " themselves imperfect. Re-run this harness per corpus to calibrate — the framework"
        " is the deliverable, not any single number.",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", help="candidates.json with LLM relevance_score labels")
    parser.add_argument("--topic", help="topic.json contract for the dataset")
    parser.add_argument("--report", help="write the markdown report to this path")
    parser.add_argument("--json", action="store_true", help="print the raw metrics as JSON")
    args = parser.parse_args()

    input_path = Path(args.input) if args.input else EXAMPLE_DIR / "data" / "candidates.json"
    topic_path = Path(args.topic) if args.topic else input_path.parent.parent / "topic.json"
    if not topic_path.exists():
        topic_path = EXAMPLE_DIR / "topic.json"

    papers = json.loads(input_path.read_text(encoding="utf-8")).get("candidates", [])
    config = json.loads(topic_path.read_text(encoding="utf-8"))
    summary = evaluate(papers, config)

    if args.json:
        print(json.dumps(summary, indent=2))
    try:
        source = str(input_path.resolve().relative_to(ROOT))
    except ValueError:
        source = str(input_path)
    report = render_report(summary, source)
    print(report)
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report + "\n", encoding="utf-8")
        print(f"\nWrote {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
