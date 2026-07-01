#!/usr/bin/env python3
"""Generate evidence-backed research opportunities from the accepted corpus."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from intent_refiner import DEFAULT_MODEL, RESPONSES_URL, _output_text
from workspace import OPPORTUNITIES_PATH, PAPERS_PATH, REPORT_PATH, TOPIC_CONFIG, load_json, write_json


OPPORTUNITY_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "minLength": 20},
        "opportunities": {
            "type": "array",
            "minItems": 3,
            "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "rank": {"type": "integer", "minimum": 1, "maximum": 6},
                    "title": {"type": "string", "minLength": 5},
                    "gap_type": {
                        "type": "string",
                        "enum": ["corpus_gap", "field_gap", "evidence_gap", "translation_gap"],
                    },
                    "priority_score": {"type": "integer", "minimum": 0, "maximum": 100},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                    "scope": {"type": "string", "minLength": 10},
                    "evidence": {
                        "type": "array",
                        "minItems": 2,
                        "items": {
                            "type": "object",
                            "properties": {
                                "observation": {"type": "string", "minLength": 5},
                                "source": {"type": "string", "minLength": 3},
                            },
                            "required": ["observation", "source"],
                            "additionalProperties": False,
                        },
                    },
                    "llm_reasoning": {"type": "string", "minLength": 10},
                    "uncertainty": {"type": "string", "minLength": 10},
                    "coverage_check": {
                        "type": "object",
                        "properties": {
                            "query_terms": {
                                "type": "array",
                                "minItems": 1,
                                "items": {"type": "string", "minLength": 2},
                            },
                            "matched_titles": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "interpretation": {"type": "string", "minLength": 10},
                        },
                        "required": ["query_terms", "matched_titles", "interpretation"],
                        "additionalProperties": False,
                    },
                    "research_questions": {
                        "type": "array",
                        "minItems": 2,
                        "items": {"type": "string", "minLength": 10},
                    },
                    "scout_queries": {
                        "type": "array",
                        "minItems": 2,
                        "items": {"type": "string", "minLength": 3},
                    },
                },
                "required": [
                    "rank",
                    "title",
                    "gap_type",
                    "priority_score",
                    "confidence",
                    "scope",
                    "evidence",
                    "llm_reasoning",
                    "uncertainty",
                    "coverage_check",
                    "research_questions",
                    "scout_queries",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "opportunities"],
    "additionalProperties": False,
}

INSTRUCTIONS = (
    "You are the gap analyst for AI Topic Scout. Read the provided accepted-paper corpus, report "
    "summary, and topic contract. Produce only bounded, evidence-backed research opportunities. "
    "Do not infer field-wide absence from sparse corpus evidence. Each opportunity must cite "
    "specific local evidence, explain the inference, note uncertainty, and propose follow-up "
    "scout queries."
)


class OpportunityAnalysisError(RuntimeError):
    """Raised when gap analysis fails."""


def _input_payload() -> str:
    topic = json.loads(TOPIC_CONFIG.read_text(encoding="utf-8"))
    corpus = load_json(PAPERS_PATH, {"papers": [], "scout_runs": []})
    report = REPORT_PATH.read_text(encoding="utf-8") if REPORT_PATH.exists() else ""
    papers = corpus.get("papers", [])
    compact_papers = [
        {
            "id": paper["id"],
            "title": paper.get("title", ""),
            "year": paper.get("year"),
            "primary_category": paper.get("primary_category"),
            "citation_count": paper.get("citation_count", 0),
            "topics": paper.get("topics", [])[:6],
            "relevance_reason": paper.get("relevance_reason", ""),
            "abstract": (paper.get("abstract") or "")[:1200],
        }
        for paper in papers[:80]
    ]
    scout_runs = corpus.get("scout_runs", [])[-8:]
    return json.dumps(
        {
            "topic": {
                "topic": topic.get("topic"),
                "research_question": topic.get("research_question"),
                "goal": topic.get("goal"),
                "include": topic.get("include", []),
                "exclude": topic.get("exclude", []),
                "taxonomy": topic.get("taxonomy", []),
                "search_queries": topic.get("search_queries", []),
                "dashboard_sections": topic.get("dashboard_sections", []),
            },
            "report_excerpt": report[:12000],
            "accepted_paper_count": len(papers),
            "papers": compact_papers,
            "scout_runs": scout_runs,
        },
        ensure_ascii=False,
    )


def _finalize(parsed: dict, model_name: str) -> dict:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "analysis_model": model_name,
        "summary": parsed["summary"].strip(),
        "opportunities": parsed["opportunities"],
    }
    return payload


def analyze_api(*, api_key: str | None = None, model: str | None = None, urlopen=urllib.request.urlopen) -> tuple[dict, str]:
    key = api_key or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise OpportunityAnalysisError(
            "OPENAI_API_KEY is required for research-gap analysis. Set it or use --provider codex."
        )
    selected_model = model or os.environ.get("TOPIC_SCOUT_GAP_MODEL") or os.environ.get("TOPIC_SCOUT_MODEL", DEFAULT_MODEL)
    request = urllib.request.Request(
        RESPONSES_URL,
        data=json.dumps(
            {
                "model": selected_model,
                "store": False,
                "instructions": INSTRUCTIONS,
                "input": _input_payload(),
                "reasoning": {"effort": "medium"},
                "text": {
                    "verbosity": "low",
                    "format": {
                        "type": "json_schema",
                        "name": "research_opportunities",
                        "strict": True,
                        "schema": OPPORTUNITY_SCHEMA,
                    },
                },
            }
        ).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=180) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise OpportunityAnalysisError(f"OpenAI gap analysis failed with HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise OpportunityAnalysisError(f"OpenAI gap analysis failed: {exc}") from exc
    try:
        parsed = json.loads(_output_text(body))
    except json.JSONDecodeError as exc:
        raise OpportunityAnalysisError("OpenAI gap analysis returned invalid structured JSON") from exc
    return _finalize(parsed, selected_model), selected_model


def analyze_codex(*, model: str | None = None, cwd: Path | str | None = None, run=subprocess.run) -> tuple[dict, str]:
    executable = shutil.which("codex")
    if not executable:
        raise OpportunityAnalysisError("Codex CLI is not installed. Install it, use --provider api, or skip opportunities generation.")
    prompt = (
        f"{INSTRUCTIONS}\n\n"
        "Return only the requested structured output. Do not inspect files, run commands, or modify the workspace.\n\n"
        f"Input:\n{_input_payload()}"
    )
    with tempfile.TemporaryDirectory(prefix="topic-scout-gaps-") as directory:
        temp_dir = Path(directory)
        schema_path = temp_dir / "schema.json"
        output_path = temp_dir / "result.json"
        schema_path.write_text(json.dumps(OPPORTUNITY_SCHEMA), encoding="utf-8")
        command = [
            executable,
            "exec",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--sandbox",
            "read-only",
            "--color",
            "never",
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(output_path),
        ]
        if model:
            command.extend(["--model", model])
        command.append(prompt)
        try:
            result = run(
                command,
                cwd=str(cwd) if cwd else None,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=240,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise OpportunityAnalysisError(f"Codex gap analysis failed: {exc}") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise OpportunityAnalysisError(f"Codex gap analysis failed: {detail or 'unknown error'}")
        output = output_path.read_text(encoding="utf-8") if output_path.exists() else result.stdout
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError as exc:
        raise OpportunityAnalysisError("Codex gap analysis returned invalid structured JSON") from exc
    model_name = f"codex-cli:{model or 'configured-model'}"
    return _finalize(parsed, model_name), model_name


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["codex", "api"], default=os.environ.get("TOPIC_SCOUT_GAP_PROVIDER", "codex"))
    parser.add_argument("--model", help="Model override for gap analysis")
    args = parser.parse_args()
    corpus = load_json(PAPERS_PATH, {"papers": []})
    if not corpus.get("papers"):
        print("No accepted papers yet; skipping research opportunities.")
        return 0
    try:
        if args.provider == "api":
            payload, model_name = analyze_api(model=args.model)
        else:
            payload, model_name = analyze_codex(model=args.model)
    except OpportunityAnalysisError as exc:
        raise SystemExit(f"Gap analysis failed: {exc}")
    write_json(OPPORTUNITIES_PATH, payload)
    print(f"Wrote {OPPORTUNITIES_PATH} with {len(payload['opportunities'])} opportunities via {model_name}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
