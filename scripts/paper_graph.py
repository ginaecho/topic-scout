#!/usr/bin/env python3
"""Provider-light scholarly graph discovery using OpenAlex."""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict


OPENALEX = "https://api.openalex.org"
MAILTO = os.environ.get("OPENALEX_MAILTO", "topic-scout@example.com")


def fetch_json(url: str, timeout: int = 30) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": f"AI-Topic-Scout mailto:{MAILTO}"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def api_url(path: str, **params) -> str:
    params["mailto"] = MAILTO
    return f"{OPENALEX}{path}?{urllib.parse.urlencode(params)}"


def abstract_text(index: dict | None) -> str:
    if not index:
        return ""
    words = [(position, token) for token, positions in index.items() for position in positions]
    return " ".join(token for _, token in sorted(words))


@dataclass
class Candidate:
    id: str
    title: str
    year: int | None
    url: str | None
    doi: str | None
    abstract: str
    citation_count: int
    topics: list[str]
    discovered_via: list[str]
    relevance_score: float = 0.0
    relevance_reason: str = ""


def normalize(work: dict, via: str) -> Candidate:
    openalex_id = work.get("id", "").rsplit("/", 1)[-1]
    location = (work.get("primary_location") or {}).get("landing_page_url")
    return Candidate(
        id=f"openalex:{openalex_id}",
        title=work.get("display_name", "").strip(),
        year=work.get("publication_year"),
        url=work.get("doi") or location or work.get("id"),
        doi=work.get("doi"),
        abstract=abstract_text(work.get("abstract_inverted_index")),
        citation_count=work.get("cited_by_count", 0),
        topics=[
            topic.get("display_name", "")
            for topic in work.get("topics", [])[:5]
            if topic.get("display_name")
        ],
        discovered_via=[via],
    )


def search(query: str, from_year: int, to_year: int, limit: int = 8) -> list[dict]:
    payload = fetch_json(
        api_url(
            "/works",
            search=query,
            filter=f"from_publication_date:{from_year}-01-01,to_publication_date:{to_year}-12-31",
            sort="relevance_score:desc",
            **{
                "per-page": limit,
                "select": (
                    "id,display_name,publication_year,cited_by_count,doi,primary_location,"
                    "abstract_inverted_index,topics,referenced_works,related_works"
                ),
            },
        )
    )
    return payload.get("results", [])


def get_works(ids: list[str]) -> list[dict]:
    if not ids:
        return []
    payload = fetch_json(
        api_url(
            "/works",
            filter=f"openalex:{'|'.join(ids[:25])}",
            **{
                "per-page": min(len(ids), 25),
                "select": (
                    "id,display_name,publication_year,cited_by_count,doi,primary_location,"
                    "abstract_inverted_index,topics"
                ),
            },
        )
    )
    return payload.get("results", [])


def relevance(candidate: Candidate, config: dict) -> tuple[float, str]:
    text = " ".join(
        [candidate.title, candidate.abstract, *candidate.topics]
    ).lower()
    include_hits = [term for term in config["include"] if term.lower() in text]
    exclude_hits = [term for term in config["exclude"] if term.lower() in text]
    query_tokens = {
        token for token in config["topic"].lower().split() if len(token) > 3
    }
    token_hits = sum(token in text for token in query_tokens)
    score = 2.0 * len(include_hits) + 0.6 * token_hits - 3.0 * len(exclude_hits)
    reason = (
        f"include={include_hits or 'none'}; "
        f"topic-token-hits={token_hits}; exclude={exclude_hits or 'none'}"
    )
    return round(score, 3), reason


def discover(config: dict, query: str | None = None, seed_limit: int = 5, neighbors: int = 8) -> dict:
    queries = [query] if query else config["search_queries"]
    nodes: dict[str, Candidate] = {}
    edges = []
    for search_query in queries:
        for work in search(search_query, config["years"]["from"], config["years"]["to"], seed_limit):
            seed = normalize(work, f"query:{search_query}")
            nodes.setdefault(seed.id, seed)
            neighbor_ids = [
                item.rsplit("/", 1)[-1]
                for item in [*work.get("related_works", [])[:neighbors], *work.get("referenced_works", [])[:neighbors]]
            ]
            for neighbor_work in get_works(neighbor_ids):
                neighbor = normalize(neighbor_work, f"neighbor:{seed.id}")
                if neighbor.id in nodes:
                    nodes[neighbor.id].discovered_via.extend(neighbor.discovered_via)
                else:
                    nodes[neighbor.id] = neighbor
                edges.append({"source": seed.id, "target": neighbor.id, "kind": "scholarly-neighbor"})
            time.sleep(0.05)

    for candidate in nodes.values():
        candidate.relevance_score, candidate.relevance_reason = relevance(candidate, config)
        candidate.discovered_via = sorted(set(candidate.discovered_via))
    ranked = sorted(
        nodes.values(),
        key=lambda item: (-item.relevance_score, -item.citation_count, -(item.year or 0)),
    )
    return {
        "topic": config["topic"],
        "queries": queries,
        "candidates": [asdict(candidate) for candidate in ranked],
        "edges": edges,
    }
