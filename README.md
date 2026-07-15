# AI Topic Scout

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg?style=flat-square)](https://www.python.org/)
[![Data: OpenAlex](https://img.shields.io/badge/data-OpenAlex-green.svg?style=flat-square)](https://openalex.org/)

**Turn a plain-language research intent into a self-updating, beautifully formatted literature workspace — for _any_ topic.**

## Purpose

Describe what you want to track (e.g. "AI in hiring", "AI for theorem proving"). Topic Scout refines that into a topic contract, discovers papers from [OpenAlex](https://openalex.org), judges their relevance, curates a living corpus, and publishes a designed dashboard, Markdown notes, and a research-gap analysis.

```
intent → topic.json → discover → judge → curate → report + dashboard
```

## Main benefits

- **Consistent house style, for free.** The dashboard and paper notes come out in the same designed format every run — you never write HTML/CSS or spend tokens shaping output.
- **Per-topic analytics.** Corpus shape, discovery trend, an interactive citation graph, and ranked research gaps.
- **Ownable.** Everything is plain files in your git repo (`topic.json`, `data/papers.json`, Markdown, one self-contained HTML file) — versioned and yours.
- **Cheap to run.** A free deterministic prefilter drops obvious off-topic papers before the LLM, cutting LLM calls ~90% while keeping the relevant ones.

## Quick start

```bash
git clone https://github.com/ginaecho/topic-scout.git
cd topic-scout

make init          # interview → topic.json
make scout         # discover + rank candidates → data/candidates.json
make review        # inspect the review queue
python3 scripts/accept_candidates.py openalex:W123 openalex:W456
make corpus        # paper notes + reports/research_report.md
make opportunities # research-gap analysis
make dashboard     # topic-dashboard.html
```

Open `topic-dashboard.html` in a browser when done.

**Requirements:** Python 3.9+, and one of [Codex CLI](https://github.com/openai/codex) (no key needed), an `OPENAI_API_KEY`, or `--offline` mode.

## Main operations

| Command | Does |
|---|---|
| `make init` | Refine intent → `topic.json` |
| `make scout` | Discover (OpenAlex) + cheap prefilter + LLM ranking → `data/candidates.json` |
| `make review` | Print the candidate review queue |
| `make corpus` | Rebuild paper notes + `reports/research_report.md` |
| `make opportunities` | Evidence-backed research-gap analysis |
| `make dashboard` | Build `topic-dashboard.html` |
| `make eval` | Compare the cheap deterministic metric vs the LLM judge |
| `make test` | Run unit tests |

## Outputs

| Artifact | Purpose |
|---|---|
| `topic.json` | Topic contract (source of truth) |
| `data/candidates.json` | Ranked review queue |
| `data/papers.json` | Accepted corpus + scout history |
| `reports/research_report.md` | Synthesis report + one note per paper |
| `data/research_opportunities.json` | Evidence-backed research gaps |
| `topic-dashboard.html` | Self-contained interactive dashboard |

Worked example: [`examples/ai-in-hiring-processes/`](examples/ai-in-hiring-processes/).

## Configure (optional)

`topic.json` accepts optional blocks:

- **`theme`** — palette, fonts, and category colors for the dashboard.
- **`judging`** — rubric weights, the accept/uncertain/reject band, and the cheap prefilter gate.

Both fall back to sensible defaults, so they're safe to omit. See [`topic.example.json`](topic.example.json).

## License

MIT — see [LICENSE](LICENSE).
