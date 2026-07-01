#!/usr/bin/env python3
"""Helpers for recording scouting token and money cost."""

from __future__ import annotations


def zero_cost(provider: str = "openalex") -> dict:
    return {
        "provider": provider,
        "token_count": 0,
        "money_cost_usd": 0.0,
        "currency": "USD",
        "note": "OpenAlex discovery does not invoke a model; token usage is zero.",
    }


def usage_cost(
    *,
    provider: str,
    model: str | None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    reasoning_tokens: int = 0,
    money_cost_usd: float = 0.0,
    currency: str = "USD",
    note: str = "",
) -> dict:
    token_count = int(input_tokens) + int(output_tokens) + int(reasoning_tokens)
    payload = {
        "provider": provider,
        "model": model,
        "token_count": token_count,
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "reasoning_tokens": int(reasoning_tokens),
        "money_cost_usd": float(money_cost_usd),
        "currency": currency,
    }
    if note:
        payload["note"] = note
    return payload
