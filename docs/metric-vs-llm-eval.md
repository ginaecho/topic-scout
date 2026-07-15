# Deterministic metric vs. LLM judge

- Source: `examples/ai-in-hiring-processes/data/candidates.json`
- Labeled candidates: **540** (**8** relevant at LLM score ≥ 7)
- Ground truth: the LLM judge's `relevance_score`.
- Metrics are rank-based / scale-free (higher is better; AUC 0.5 = random, 1.0 = perfect ranking).

| scorer | spearman | auc | precision@10 | recall@10 | ndcg@20 | overlap@20 | distinct_values |
|---|---|---|---|---|---|---|---|
| `hybrid` | 0.4272 | 0.9843 | 0.5 | 0.625 | 0.5874 | 0.7 | 529 |
| `bm25` | 0.3127 | 0.9746 | 0.2 | 0.25 | 0.4879 | 0.4 | 511 |
| `tfidf_cosine` | 0.3063 | 0.9746 | 0.4 | 0.5 | 0.7487 | 0.55 | 509 |
| `current` | 0.8169 | 0.9585 | 0.7 | 0.875 | 0.8936 | 0.95 | 3 |
| `tfidf_cites` | 0.1791 | 0.8891 | 0.4 | 0.5 | 0.5361 | 0.35 | 529 |
| `idf_coverage` | 0.1039 | 0.8412 | 0.1 | 0.125 | 0.2941 | 0.3 | 425 |
| `lexical_v2` | -0.2388 | 0.2498 | 0.0 | 0.0 | 0.0047 | 0.0 | 331 |

`distinct_values` = how many different scores the metric produces across the set — a proxy for discriminative power (1 = useless as a ranker).

## Token-saving prefilter (current gate: `current`)

- Auto-drop candidates with score ≤ `0.0` → removes **485/540** candidates.
- LLM judges only the **55** survivors (**10.2%** of candidates) — **~90% fewer LLM calls**.
- Relevant papers retained: **1.0** (8 of 8 kept).

## Token-saving prefilter (best-AUC gate: `hybrid`)

- Auto-drop candidates with score ≤ `3.2721118748416806` → removes **506/540** candidates.
- LLM judges only the **34** survivors (**6.3%** of candidates) — **~94% fewer LLM calls**.
- Relevant papers retained: **1.0** (8 of 8 kept).

## How to read this / recommendations

- **Two jobs, two metrics.** Dropping the obvious off-topic mass (a *routing* job, measured by AUC) and ranking the shortlist (a *precision* job, measured by precision@K / NDCG / overlap) are different. High-AUC metrics (`hybrid`, `tfidf`, `bm25`) route best; exact include-phrase matching (`current`) ranks the top best but is coarse (few `distinct_values`).
- **Biggest token win = prefilter routing.** Use a high-recall cheap gate to auto-drop candidates the metric is confident are off-topic, and only spend LLM tokens on the survivors + the uncertainty band. That is where the ~90% saving comes from.
- **Don't expect a cheap metric to reproduce fine LLM scores.** Ranking 7-vs-10 among relevant papers needs the model; keep the LLM for the shortlist and the ambiguous band only.
- **IDF-weight any lexical signal.** Naive token-coverage (`lexical_v2`) scores *worse than random* because generic tokens shared by adjacent-but-wrong papers dominate.

> Numbers are for one topic/corpus and a small positive set; the LLM labels are themselves imperfect. Re-run this harness per corpus to calibrate — the framework is the deliverable, not any single number.
