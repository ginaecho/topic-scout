#!/usr/bin/env python3
"""Refine a user's research intent into a structured scouting contract."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_MODEL = "gpt-5.5"
RESPONSES_URL = "https://api.openai.com/v1/responses"

INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "minLength": 3, "maxLength": 100},
        "research_question": {"type": "string", "minLength": 10},
        "goal": {"type": "string", "minLength": 3},
        "audience": {"type": "string", "minLength": 3},
        "include": {
            "type": "array",
            "items": {"type": "string", "minLength": 2},
            "minItems": 2,
            "maxItems": 10,
        },
        "exclude": {
            "type": "array",
            "items": {"type": "string", "minLength": 2},
            "maxItems": 8,
        },
        "evidence_types": {
            "type": "array",
            "items": {"type": "string", "minLength": 2},
            "minItems": 2,
            "maxItems": 8,
        },
        "taxonomy": {
            "type": "array",
            "items": {"type": "string", "minLength": 2},
            "minItems": 3,
            "maxItems": 10,
        },
        "dashboard_sections": {
            "type": "array",
            "items": {"type": "string", "minLength": 2},
            "minItems": 3,
            "maxItems": 10,
        },
        "search_queries": {
            "type": "array",
            "items": {"type": "string", "minLength": 3},
            "minItems": 5,
            "maxItems": 15,
        },
        "scouting_strategy": {
            "type": "array",
            "items": {"type": "string", "minLength": 5},
            "minItems": 3,
            "maxItems": 8,
        },
    },
    "required": [
        "title",
        "research_question",
        "goal",
        "audience",
        "include",
        "exclude",
        "evidence_types",
        "taxonomy",
        "dashboard_sections",
        "search_queries",
        "scouting_strategy",
    ],
    "additionalProperties": False,
}


class IntentRefinementError(RuntimeError):
    """Raised when the model cannot produce a usable research contract."""


INSTRUCTIONS = (
    "You are the research-intake coordinator for AI Topic Scout. Convert a user's "
    "possibly informal, ungrammatical, or sentence-length intent into a precise research "
    "contract. The title must be concise and must not copy the full user sentence. "
    "Keep business purpose, domain or policy constraints, evaluation dimensions, and "
    "agent-system design requirements distinct. Search queries must cover direct, "
    "benchmark, system, policy, business-value, and adversarial terminology. Dashboard "
    "sections and scouting strategy must be specific to this intent. Do not invent "
    "citations, papers, results, or claims about field-wide gaps."
)


def _output_text(response: dict) -> str:
    for item in response.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                return content["text"]
    raise IntentRefinementError("OpenAI response did not contain structured output text")


def refine_intent_api(
    intent: str,
    *,
    context: dict | None = None,
    api_key: str | None = None,
    model: str | None = None,
    urlopen=urllib.request.urlopen,
) -> tuple[dict, str]:
    """Refine intent through the Responses API."""
    key = api_key or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise IntentRefinementError(
            "OPENAI_API_KEY is required for intent refinement. "
            "Set it or rerun with --offline."
        )
    selected_model = model or os.environ.get("TOPIC_SCOUT_MODEL", DEFAULT_MODEL)
    payload = {
        "model": selected_model,
        "store": False,
        "instructions": INSTRUCTIONS,
        "input": json.dumps(
            {"raw_intent": intent, "user_constraints": context or {}},
            ensure_ascii=False,
        ),
        "reasoning": {"effort": "low"},
        "text": {
            "verbosity": "low",
            "format": {
                "type": "json_schema",
                "name": "research_intent",
                "strict": True,
                "schema": INTENT_SCHEMA,
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
        with urlopen(request, timeout=90) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise IntentRefinementError(
            f"OpenAI intent refinement failed with HTTP {exc.code}: {detail}"
        ) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise IntentRefinementError(f"OpenAI intent refinement failed: {exc}") from exc

    try:
        refined = json.loads(_output_text(body))
    except json.JSONDecodeError as exc:
        raise IntentRefinementError("OpenAI returned invalid structured JSON") from exc
    return refined, selected_model


def refine_intent_codex(
    intent: str,
    *,
    context: dict | None = None,
    model: str | None = None,
    cwd: Path | str | None = None,
    run=subprocess.run,
    which=shutil.which,
) -> tuple[dict, str]:
    """Refine intent through an authenticated Codex CLI session."""
    executable = which("codex")
    if not executable:
        raise IntentRefinementError(
            "Codex CLI is not installed. Install and sign in to Codex, "
            "use --provider api, or rerun with --offline."
        )
    prompt = (
        f"{INSTRUCTIONS}\n\n"
        "Return only the requested structured research contract. Do not inspect files, "
        "run commands, browse, or modify the workspace.\n\n"
        f"Input:\n{json.dumps({'raw_intent': intent, 'user_constraints': context or {}}, ensure_ascii=False)}"
    )
    with tempfile.TemporaryDirectory(prefix="topic-scout-intent-") as directory:
        temp_dir = Path(directory)
        schema_path = temp_dir / "schema.json"
        output_path = temp_dir / "result.json"
        schema_path.write_text(json.dumps(INTENT_SCHEMA), encoding="utf-8")
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
                timeout=180,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise IntentRefinementError(f"Codex CLI intent refinement failed: {exc}") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise IntentRefinementError(
                f"Codex CLI intent refinement failed: {detail or 'unknown error'}"
            )
        output = output_path.read_text(encoding="utf-8") if output_path.exists() else result.stdout
    try:
        refined = json.loads(output)
    except json.JSONDecodeError as exc:
        raise IntentRefinementError("Codex CLI returned invalid structured JSON") from exc
    return refined, f"codex-cli:{model or 'configured-model'}"


def refine_intent(
    intent: str,
    *,
    provider: str = "codex",
    context: dict | None = None,
    api_key: str | None = None,
    model: str | None = None,
    cwd: Path | str | None = None,
    urlopen=urllib.request.urlopen,
    run=subprocess.run,
) -> tuple[dict, str]:
    """Return a structured research contract through the selected model provider."""
    if provider == "codex":
        return refine_intent_codex(
            intent,
            context=context,
            model=model,
            cwd=cwd,
            run=run,
        )
    if provider == "api":
        return refine_intent_api(
            intent,
            context=context,
            api_key=api_key,
            model=model,
            urlopen=urlopen,
        )
    raise IntentRefinementError(f"Unsupported intent provider: {provider}")
