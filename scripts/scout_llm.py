#!/usr/bin/env python3
"""Model-backed candidate evaluation for scout runs."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from costs import usage_cost
from intent_refiner import DEFAULT_MODEL, RESPONSES_URL, _output_text


SCOUT_SCHEMA = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "minLength": 3},
                    "relevance_score": {"type": "number", "minimum": 0, "maximum": 10},
                    "relevance_reason": {"type": "string", "minLength": 5},
                },
                "required": ["id", "relevance_score", "relevance_reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["candidates"],
    "additionalProperties": False,
}

SCOUT_INSTRUCTIONS = (
    "You are a research scout reviewer. Score candidate papers against the provided research "
    "contract. Use the candidate title, abstract, topics, and provenance only. Be conservative. "
    "Prefer low scores when relevance is ambiguous. Penalize items that match excluded scope. "
    "Return every provided candidate id exactly once with a relevance_score from 0 to 10 and a "
    "short concrete reason grounded in the candidate text."
)


class ScoutModelError(RuntimeError):
    """Raised when scout candidate evaluation fails."""


def _candidate_payload(config: dict, candidates: list[dict]) -> str:
    compact = []
    for item in candidates:
        compact.append(
            {
                "id": item["id"],
                "title": item.get("title", ""),
                "year": item.get("year"),
                "abstract": (item.get("abstract") or "")[:1800],
                "topics": item.get("topics", [])[:8],
                "discovered_via": item.get("discovered_via", [])[:4],
                "citation_count": item.get("citation_count", 0),
                "heuristic_relevance_score": item.get("relevance_score", 0),
                "heuristic_relevance_reason": item.get("relevance_reason", ""),
            }
        )
    return json.dumps(
        {
            "topic": config["topic"],
            "research_question": config.get("research_question"),
            "goal": config.get("goal"),
            "include": config.get("include", []),
            "exclude": config.get("exclude", []),
            "taxonomy": config.get("taxonomy", []),
            "candidates": compact,
        },
        ensure_ascii=False,
    )


def _usage_cost_from_responses(provider: str, model: str, body: dict) -> dict:
    usage = body.get("usage") or {}
    input_tokens = int(usage.get("input_tokens", 0) or 0)
    output_tokens = int(usage.get("output_tokens", 0) or 0)
    output_details = usage.get("output_tokens_details") or {}
    reasoning_tokens = int(output_details.get("reasoning_tokens", 0) or 0)
    note = ""
    if provider == "api":
        note = (
            "Token usage is recorded from the Responses API. USD cost defaults to 0 unless "
            "you map model pricing separately."
        )
    return usage_cost(
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        reasoning_tokens=reasoning_tokens,
        money_cost_usd=0.0,
        note=note,
    )


def score_candidates_api(
    config: dict,
    candidates: list[dict],
    *,
    api_key: str | None = None,
    model: str | None = None,
    urlopen=urllib.request.urlopen,
) -> tuple[dict[str, dict], dict]:
    key = api_key or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise ScoutModelError(
            "OPENAI_API_KEY is required for model-backed scout scoring. "
            "Set it or rerun scout with --offline."
        )
    selected_model = model or os.environ.get("TOPIC_SCOUT_SCOUT_MODEL") or os.environ.get(
        "TOPIC_SCOUT_MODEL",
        DEFAULT_MODEL,
    )
    payload = {
        "model": selected_model,
        "store": False,
        "instructions": SCOUT_INSTRUCTIONS,
        "input": _candidate_payload(config, candidates),
        "reasoning": {"effort": "low"},
        "text": {
            "verbosity": "low",
            "format": {
                "type": "json_schema",
                "name": "scout_evaluation",
                "strict": True,
                "schema": SCOUT_SCHEMA,
            },
        },
    }
    request = urllib.request.Request(
        RESPONSES_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=120) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ScoutModelError(f"OpenAI scout scoring failed with HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ScoutModelError(f"OpenAI scout scoring failed: {exc}") from exc

    try:
        parsed = json.loads(_output_text(body))
    except json.JSONDecodeError as exc:
        raise ScoutModelError("OpenAI scout scoring returned invalid structured JSON") from exc
    mapping = {
        row["id"]: {
            "relevance_score": float(row["relevance_score"]),
            "relevance_reason": row["relevance_reason"].strip(),
        }
        for row in parsed.get("candidates", [])
    }
    return mapping, _usage_cost_from_responses("api", selected_model, body)


def score_candidates_codex(
    config: dict,
    candidates: list[dict],
    *,
    model: str | None = None,
    cwd: Path | str | None = None,
    run=subprocess.run,
) -> tuple[dict[str, dict], dict]:
    executable = shutil.which("codex")
    if not executable:
        raise ScoutModelError(
            "Codex CLI is not installed. Install and sign in to Codex, use --provider api, "
            "or rerun scout with --offline."
        )
    prompt = (
        f"{SCOUT_INSTRUCTIONS}\n\n"
        "Return only the requested structured output. Do not inspect files, run commands, "
        "or modify the workspace.\n\n"
        f"Input:\n{_candidate_payload(config, candidates)}"
    )
    with tempfile.TemporaryDirectory(prefix="topic-scout-score-") as directory:
        temp_dir = Path(directory)
        schema_path = temp_dir / "schema.json"
        output_path = temp_dir / "result.json"
        schema_path.write_text(json.dumps(SCOUT_SCHEMA), encoding="utf-8")
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
            "--json",
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
            raise ScoutModelError(f"Codex scout scoring failed: {exc}") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise ScoutModelError(f"Codex scout scoring failed: {detail or 'unknown error'}")
        output = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ScoutModelError("Codex scout scoring returned invalid structured JSON") from exc
    usage = {}
    for line in (result.stdout or "").splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "turn.completed":
            usage = event.get("usage") or {}
    mapping = {
        row["id"]: {
            "relevance_score": float(row["relevance_score"]),
            "relevance_reason": row["relevance_reason"].strip(),
        }
        for row in parsed.get("candidates", [])
    }
    selected_model = f"codex-cli:{model or 'configured-model'}"
    return mapping, usage_cost(
        provider="codex",
        model=selected_model,
        input_tokens=int(usage.get("input_tokens", 0) or 0),
        output_tokens=int(usage.get("output_tokens", 0) or 0),
        reasoning_tokens=int(usage.get("reasoning_output_tokens", 0) or 0),
        money_cost_usd=0.0,
        note="Codex CLI reports token usage but does not expose billable USD cost in this workflow.",
    )


def score_candidates(
    config: dict,
    candidates: list[dict],
    *,
    provider: str = "codex",
    model: str | None = None,
    cwd: Path | str | None = None,
    urlopen=urllib.request.urlopen,
    run=subprocess.run,
) -> tuple[dict[str, dict], dict]:
    if provider == "codex":
        return score_candidates_codex(config, candidates, model=model, cwd=cwd, run=run)
    if provider == "api":
        return score_candidates_api(config, candidates, model=model, urlopen=urlopen)
    raise ScoutModelError(f"Unsupported scout provider: {provider}")
