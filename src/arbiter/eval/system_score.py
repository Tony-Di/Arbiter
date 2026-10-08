"""Action-level metrics for the system ablation benchmark.

The existing :mod:`arbiter.eval.score` module evaluates ordinal category
predictions.  This module deliberately evaluates the *product decision* instead:
allow, human-review, or remove.  Metrics are computed only over completed
predictions; ``coverage`` makes missing/failed calls visible.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any


ACTIONS = ("allow", "human-review", "remove")
HIGH_RISK_CATEGORIES = frozenset({"threat", "identity_hate"})


def normalize_action(value: Any) -> str:
    """Return the canonical action name or raise a useful validation error."""
    if value is None:
        raise ValueError("action is required")
    action = str(value).strip().lower().replace("_", "-").replace(" ", "-")
    aliases = {
        "review": "human-review",
        "humanreview": "human-review",
        "human-review": "human-review",
    }
    action = aliases.get(action, action)
    if action not in ACTIONS:
        raise ValueError(f"unsupported action {value!r}; expected one of {ACTIONS}")
    return action


def _case_id(row: Mapping[str, Any]) -> str:
    value = row.get("id", row.get("case_id"))
    if value is None or str(value).strip() == "":
        raise ValueError("every case needs a non-empty id or case_id")
    return str(value)


def _gold_action(row: Mapping[str, Any]) -> str:
    return normalize_action(row.get("gold_action", row.get("action")))


def _prediction_action(row: Mapping[str, Any]) -> str:
    value = row.get("pred_action", row.get("action", row.get("final_action")))
    return normalize_action(value)


def _as_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes", "y"}:
        return True
    if lowered in {"0", "false", "no", "n"}:
        return False
    raise ValueError(f"cannot parse boolean value {value!r}")


def _categories(value: Any) -> set[str]:
    if value is None or value == "":
        return set()
    if isinstance(value, str):
        # load_cases normally decodes JSON CSV cells.  Keeping a small fallback
        # here makes score_predictions convenient to use directly in notebooks.
        value = value.strip().strip("[]")
        return {
            item.strip().strip("\"'")
            for item in value.replace("|", ",").replace(";", ",").split(",")
            if item.strip().strip("\"'")
        }
    if isinstance(value, Iterable):
        return {str(item) for item in value}
    raise ValueError(f"cannot parse category collection {value!r}")


def is_high_risk_case(
    row: Mapping[str, Any],
    high_risk_categories: set[str] | frozenset[str] = HIGH_RISK_CATEGORIES,
) -> bool:
    """Infer whether a gold case is high-risk, with explicit labels winning.

    Annotation files may set ``gold_high_risk``/``high_risk`` explicitly.  If
    they do not, threat/identity-hate categories, severity 3, and a gold remove
    action are treated as high-risk.  A high-risk case is considered *recalled*
    when the system does not auto-allow it (human-review and remove both catch it).
    """
    explicit = _as_bool(
        row.get("gold_high_risk", row.get("high_risk", row.get("is_high_risk")))
    )
    if explicit is not None:
        return explicit

    cats = _categories(row.get("gold_categories", row.get("categories")))
    if cats.intersection(high_risk_categories):
        return True

    severity = row.get("gold_severity", row.get("severity"))
    if severity not in (None, "") and int(severity) >= 3:
        return True
    return _gold_action(row) == "remove"


def percentile(values: Sequence[float], quantile: float) -> float | None:
    """Dependency-free linear percentile (the method used by NumPy's default)."""
    if not values:
        return None
    if not 0 <= quantile <= 1:
        raise ValueError("quantile must be between 0 and 1")
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _prediction_map(predictions: Any) -> dict[str, Mapping[str, Any]]:
    if isinstance(predictions, Mapping):
        mapped: dict[str, Mapping[str, Any]] = {}
        for key, value in predictions.items():
            if isinstance(value, str):
                mapped[str(key)] = {"case_id": str(key), "action": value}
            elif isinstance(value, Mapping):
                mapped[str(key)] = value
            else:
                raise TypeError("prediction values must be actions or mappings")
        return mapped

    mapped = {}
    for row in predictions:
        if not isinstance(row, Mapping):
            raise TypeError("predictions must contain mappings")
        mapped[_case_id(row)] = row
    return mapped


def score_predictions(
    cases: Sequence[Mapping[str, Any]],
    predictions: Sequence[Mapping[str, Any]] | Mapping[str, Any],
    *,
    high_risk_categories: set[str] | frozenset[str] = HIGH_RISK_CATEGORIES,
) -> dict[str, Any]:
    """Score one variant's predictions against canonical or raw annotation rows.

    Definitions:

    * unsafe auto-allow: gold is review/remove, prediction is allow;
    * over-remove: gold is allow/review, prediction is remove;
    * auto-decision accuracy: exact action accuracy among predicted allow/remove;
    * high-risk recall: fraction of high-risk cases predicted review/remove.
    """
    by_id = _prediction_map(predictions)
    matched: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    for case in cases:
        prediction = by_id.get(_case_id(case))
        if prediction is not None:
            # Validate here, rather than allowing an invalid cached record to
            # silently count toward coverage.
            _prediction_action(prediction)
            matched.append((case, prediction))

    n_cases = len(cases)
    n_scored = len(matched)
    coverage = n_scored / n_cases if n_cases else 0.0

    per_action: dict[str, dict[str, float | int]] = {}
    for action in ACTIONS:
        tp = fp = fn = 0
        for case, prediction in matched:
            gold = _gold_action(case)
            pred = _prediction_action(prediction)
            tp += int(gold == action and pred == action)
            fp += int(gold != action and pred == action)
            fn += int(gold == action and pred != action)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0
        per_action[action] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }
    action_macro_f1 = sum(float(per_action[a]["f1"]) for a in ACTIONS) / len(ACTIONS)

    unsafe_denominator = sum(1 for case, _ in matched if _gold_action(case) != "allow")
    unsafe_count = sum(
        1
        for case, prediction in matched
        if _gold_action(case) != "allow" and _prediction_action(prediction) == "allow"
    )
    unsafe_auto_allow_rate = unsafe_count / unsafe_denominator if unsafe_denominator else 0.0

    over_remove_denominator = sum(1 for case, _ in matched if _gold_action(case) != "remove")
    over_remove_count = sum(
        1
        for case, prediction in matched
        if _gold_action(case) != "remove" and _prediction_action(prediction) == "remove"
    )
    over_remove_rate = (
        over_remove_count / over_remove_denominator if over_remove_denominator else 0.0
    )

    human_review_count = sum(
        1 for _, prediction in matched if _prediction_action(prediction) == "human-review"
    )
    human_review_rate = human_review_count / n_scored if n_scored else 0.0

    auto_pairs = [
        (case, prediction)
        for case, prediction in matched
        if _prediction_action(prediction) in {"allow", "remove"}
    ]
    auto_correct = sum(
        1
        for case, prediction in auto_pairs
        if _gold_action(case) == _prediction_action(prediction)
    )
    auto_decision_accuracy = auto_correct / len(auto_pairs) if auto_pairs else 0.0

    high_risk_pairs = [
        (case, prediction)
        for case, prediction in matched
        if is_high_risk_case(case, high_risk_categories)
    ]
    high_risk_caught = sum(
        1
        for _, prediction in high_risk_pairs
        if _prediction_action(prediction) != "allow"
    )
    high_risk_recall = high_risk_caught / len(high_risk_pairs) if high_risk_pairs else 0.0

    latencies = [
        float(prediction["latency_ms"])
        for _, prediction in matched
        if prediction.get("latency_ms") not in (None, "")
    ]

    return {
        "n_cases": n_cases,
        "n_scored": n_scored,
        "coverage": coverage,
        "action_macro_f1": action_macro_f1,
        "unsafe_auto_allow_rate": unsafe_auto_allow_rate,
        "over_remove_rate": over_remove_rate,
        "human_review_rate": human_review_rate,
        "auto_decision_accuracy": auto_decision_accuracy,
        "high_risk_recall": high_risk_recall,
        "p50_latency_ms": percentile(latencies, 0.50),
        "p95_latency_ms": percentile(latencies, 0.95),
        "n_auto_decisions": len(auto_pairs),
        "n_high_risk": len(high_risk_pairs),
        "unsafe_auto_allow_count": unsafe_count,
        "unsafe_auto_allow_denominator": unsafe_denominator,
        "over_remove_count": over_remove_count,
        "over_remove_denominator": over_remove_denominator,
        "human_review_count": human_review_count,
        "escalated_count": sum(bool(pred.get("escalated")) for _, pred in matched),
        "logical_model_turns": sum(int(pred.get("logical_model_turns", 0)) for _, pred in matched),
        "action_confusion": {
            gold: {pred: sum(_gold_action(case) == gold and _prediction_action(row) == pred
                             for case, row in matched) for pred in ACTIONS}
            for gold in ACTIONS
        },
        "action_per_class": per_action,
    }


def score_variants(
    cases: Sequence[Mapping[str, Any]],
    predictions: Sequence[Mapping[str, Any]],
    variants: Sequence[str],
) -> dict[str, dict[str, Any]]:
    """Group prediction rows by variant and score each requested variant."""
    return {
        variant: score_predictions(
            cases,
            [row for row in predictions if row.get("variant") == variant],
        )
        for variant in variants
    }


def compare_variants(cases, predictions, before: str, after: str) -> dict[str, Any]:
    """Paired corrections/regressions on the common completed cases only."""
    left = {_case_id(p): p for p in predictions if p["variant"] == before}
    right = {_case_id(p): p for p in predictions if p["variant"] == after}
    matched = [case for case in cases if _case_id(case) in left and _case_id(case) in right]
    corrected, regressed, changed = [], [], []
    for case in matched:
        case_id = _case_id(case)
        a, b, gold = _prediction_action(left[case_id]), _prediction_action(right[case_id]), _gold_action(case)
        if a != b:
            changed.append(case_id)
        if a != gold and b == gold:
            corrected.append(case_id)
        if a == gold and b != gold:
            regressed.append(case_id)
    return {"before": before, "after": after, "n_paired": len(matched),
            "n_corrected": len(corrected), "n_regressed": len(regressed),
            "n_changed": len(changed), "corrected_ids": corrected,
            "regressed_ids": regressed, "changed_ids": changed}
