#!/usr/bin/env python3
"""Deterministic relevance aggregation for scout judging.

The LLM judge scores each candidate on a small rubric (0..1 per dimension);
this module turns that rubric into a single ranked score, a confidence signal,
and an accept / uncertain / reject verdict. Keeping the ranking math here (not
in the model) makes it transparent, reproducible, and tunable per topic via a
``judging`` block in ``topic.json``.
"""

from __future__ import annotations

# Rubric dimensions the judge scores independently, each in [0, 1].
RUBRIC_DIMENSIONS = ("topical_fit", "evidence_match", "rigor")

DEFAULT_JUDGING = {
    # Weights applied to the rubric dimensions; normalized to sum to 1.
    "weights": {"topical_fit": 0.5, "evidence_match": 0.3, "rigor": 0.2},
    # Gentle linear recency decay, expressed on the 0..1 multiplier scale.
    "recency": {"decay_per_year": 0.03, "floor": 0.75, "unknown_year": 0.9},
    # Two-threshold band on the 0..10 relevance scale.
    "accept_hi": 7.0,
    "accept_lo": 4.0,
    # Minimum heuristic/LLM concordance required to auto-accept.
    "min_confidence": 0.35,
    # Divisor that squashes the unbounded heuristic score into [0, 1].
    "heuristic_scale": 6.0,
    # Cheap pre-LLM gate: drop candidates whose deterministic score is at or
    # below `threshold` before spending any LLM tokens. `threshold: 0.0` on the
    # default `current` scorer drops candidates with no positive topical
    # evidence — empirically a zero-recall-loss cut (see docs/metric-vs-llm-eval.md).
    "prefilter": {
        "enabled": True,
        "scorer": "current",
        "threshold": 0.0,
        "keep_min": 5,
    },
}


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def resolve_judging(config: dict, *, accept_hi: float | None = None) -> dict:
    """Merge an optional ``judging`` block from topic.json over the defaults.

    Partial or malformed values fall back to the default, so a topic that only
    tweaks, say, ``weights.topical_fit`` is always safe. ``accept_hi`` (e.g. a
    ``--accept-score`` CLI override) wins over both when provided.
    """
    block = config.get("judging") or {}

    weights_in = block.get("weights") or {}
    weights = {}
    for dimension in RUBRIC_DIMENSIONS:
        raw = weights_in.get(dimension, DEFAULT_JUDGING["weights"][dimension])
        try:
            weights[dimension] = max(0.0, float(raw))
        except (TypeError, ValueError):
            weights[dimension] = DEFAULT_JUDGING["weights"][dimension]
    total = sum(weights.values())
    if total <= 0:
        weights = dict(DEFAULT_JUDGING["weights"])
        total = sum(weights.values())
    weights = {dimension: value / total for dimension, value in weights.items()}

    recency_in = block.get("recency") or {}
    recency = {**DEFAULT_JUDGING["recency"]}
    for key in recency:
        if key in recency_in:
            try:
                recency[key] = float(recency_in[key])
            except (TypeError, ValueError):
                pass

    def _number(key: str) -> float:
        try:
            return float(block[key])
        except (KeyError, TypeError, ValueError):
            return float(DEFAULT_JUDGING[key])

    prefilter_in = block.get("prefilter") or {}
    prefilter = {**DEFAULT_JUDGING["prefilter"]}
    if "enabled" in prefilter_in:
        prefilter["enabled"] = bool(prefilter_in["enabled"])
    if prefilter_in.get("scorer"):
        prefilter["scorer"] = str(prefilter_in["scorer"])
    for key in ("threshold", "keep_min"):
        if key in prefilter_in:
            try:
                prefilter[key] = float(prefilter_in[key])
            except (TypeError, ValueError):
                pass
    prefilter["keep_min"] = max(0, int(prefilter["keep_min"]))

    resolved = {
        "weights": weights,
        "recency": recency,
        "accept_hi": _number("accept_hi"),
        "accept_lo": _number("accept_lo"),
        "min_confidence": _clamp(_number("min_confidence")),
        "heuristic_scale": max(1e-6, _number("heuristic_scale")),
        "prefilter": prefilter,
    }
    if accept_hi is not None:
        resolved["accept_hi"] = float(accept_hi)
    # Keep the band coherent even if a user inverts the thresholds.
    resolved["accept_lo"] = min(resolved["accept_lo"], resolved["accept_hi"])
    return resolved


def recency_weight(year, reference_year, recency: dict) -> float:
    """Gentle linear decay: recent papers keep full credit, older ones taper
    down to a floor. Missing years get a neutral multiplier."""
    if not year:
        return _clamp(recency.get("unknown_year", 0.9))
    age = max(0, int(reference_year) - int(year))
    weight = 1.0 - recency.get("decay_per_year", 0.0) * age
    return _clamp(weight, recency.get("floor", 0.0), 1.0)


def normalize_heuristic(score: float, scale: float) -> float:
    """Squash the unbounded keyword heuristic score into [0, 1]."""
    try:
        return _clamp(float(score) / scale)
    except (TypeError, ValueError):
        return 0.0


def aggregate(
    rubric: dict,
    judging: dict,
    *,
    year=None,
    reference_year: int,
    heuristic_score: float = 0.0,
) -> dict:
    """Combine a judged rubric into a ranked score, confidence, and verdict.

    Returns a dict with ``relevance_score`` (0..10), ``relevance_confidence``
    (0..1), ``relevance_verdict`` (accept | uncertain | reject), and the
    normalized components used, so every number is auditable.
    """
    weights = judging["weights"]
    dims = {
        dimension: _clamp(float(rubric.get(dimension, 0.0) or 0.0))
        for dimension in RUBRIC_DIMENSIONS
    }
    exclusion_hit = bool(rubric.get("exclusion_hit", False))

    base = sum(weights[dimension] * dims[dimension] for dimension in RUBRIC_DIMENSIONS)
    recency = recency_weight(year, reference_year, judging["recency"])
    combined = base * recency  # 0..1
    score10 = round(combined * 10.0, 2)

    # Confidence = agreement between the independent cheap heuristic and the
    # LLM rubric. Strong disagreement routes a candidate to human review.
    heuristic_norm = normalize_heuristic(heuristic_score, judging["heuristic_scale"])
    confidence = round(_clamp(1.0 - abs(heuristic_norm - combined)), 3)

    if exclusion_hit:
        verdict = "reject"
        score10 = 0.0
    elif score10 >= judging["accept_hi"] and confidence >= judging["min_confidence"]:
        verdict = "accept"
    elif score10 <= judging["accept_lo"]:
        verdict = "reject"
    else:
        verdict = "uncertain"

    return {
        "relevance_score": score10,
        "relevance_confidence": confidence,
        "relevance_verdict": verdict,
        "relevance_components": {
            **dims,
            "exclusion_hit": exclusion_hit,
            "recency_weight": round(recency, 3),
            "heuristic_norm": round(heuristic_norm, 3),
        },
    }
