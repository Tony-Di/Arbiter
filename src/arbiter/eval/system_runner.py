"""Resumable runner for action-level system ablations.

Variant functions are ordinary injected callables ``case -> prediction``.  This
keeps the runner zero-network-testable while :func:`make_production_variant_fns`
adapts Arbiter's real classify/graph pipeline to that small interface.
"""

from __future__ import annotations

import csv
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from arbiter.classify import ALL_6, classify
from arbiter.product.adjudicator import default_adjudicate_fn, needs_human
from arbiter.product.aggregator import aggregate
from arbiter.product.context import ContextFlags, detect_context
from arbiter.product.graph import build_graph
from arbiter.product.state import initial_state

from .system_score import ACTIONS, normalize_action, score_variants


VARIANTS = ("single_call", "specialist_panel", "policy_agent", "full_system")
AVAILABLE_VARIANTS = (*VARIANTS, "specialists_only")
CACHE_VERSION = "2"  # v1 incorrectly scored low-confidence recommendations as automatic
DEFAULT_CONTEXT_FLAGS = {
    "sarcasm": False,
    "quotation": False,
    "reclaimed_slur": False,
    "direct_threat": False,
    "ambiguity": False,
    "note": None,
}

METRIC_COLUMNS = (
    "action_macro_f1",
    "unsafe_auto_allow_rate",
    "over_remove_rate",
    "human_review_rate",
    "auto_decision_accuracy",
    "high_risk_recall",
    "p50_latency_ms",
    "p95_latency_ms",
    "coverage",
    "n_cases",
    "n_scored",
    "n_auto_decisions",
    "n_high_risk",
)


def _parse_categories(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("["):
            try:
                decoded = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON category list: {value!r}") from exc
            if not isinstance(decoded, list):
                raise ValueError("category JSON must be a list")
            return [str(item) for item in decoded]
        return [
            item.strip()
            for item in stripped.replace("|", ",").replace(";", ",").split(",")
            if item.strip()
        ]
    if isinstance(value, Sequence):
        return [str(item) for item in value]
    raise ValueError(f"cannot parse categories {value!r}")


def _normalize_case(row: Mapping[str, Any], *, row_number: int | None = None) -> dict[str, Any]:
    location = f" at row {row_number}" if row_number is not None else ""
    case_id = row.get("id", row.get("case_id"))
    if case_id is None or not str(case_id).strip():
        raise ValueError(f"missing case id{location}")

    comment = row.get("comment", row.get("text"))
    if comment is None or not str(comment).strip():
        raise ValueError(f"missing comment/text for case {case_id!r}{location}")

    gold_value = row.get("gold_action", row.get("action"))
    try:
        gold_action = normalize_action(gold_value)
    except ValueError as exc:
        raise ValueError(f"invalid gold action for case {case_id!r}{location}: {exc}") from exc

    normalized = dict(row)
    normalized.update(
        {
            "id": str(case_id),
            "comment": str(comment),
            "gold_action": gold_action,
            "gold_categories": _parse_categories(
                row.get("gold_categories", row.get("categories"))
            ),
        }
    )
    severity = row.get("gold_severity", row.get("severity"))
    if severity not in (None, ""):
        normalized["gold_severity"] = int(severity)
    return normalized


def load_cases(path: str | Path) -> list[dict[str, Any]]:
    """Load and validate human-annotated JSONL or CSV benchmark cases.

    Accepted aliases are ``id``/``case_id``, ``comment``/``text``, and
    ``gold_action``/``action``.  Categories may be a JSON list or a comma,
    semicolon, or pipe-separated CSV cell.
    """
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix not in {".jsonl", ".csv"}:
        raise ValueError("case file must end in .jsonl or .csv")

    rows: list[Mapping[str, Any]] = []
    if suffix == ".jsonl":
        with source.open(encoding="utf-8-sig") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    decoded = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSON on line {line_number} of {source}") from exc
                if not isinstance(decoded, Mapping):
                    raise ValueError(f"line {line_number} of {source} is not an object")
                rows.append(decoded)
    else:
        with source.open(newline="", encoding="utf-8-sig") as handle:
            rows.extend(csv.DictReader(handle))

    cases = [_normalize_case(row, row_number=i) for i, row in enumerate(rows, start=1)]
    ids = [case["id"] for case in cases]
    duplicates = sorted({case_id for case_id in ids if ids.count(case_id) > 1})
    if duplicates:
        raise ValueError(f"duplicate case ids: {', '.join(duplicates)}")
    if not cases:
        raise ValueError(f"no benchmark cases found in {source}")
    return cases


def make_config_fingerprint(config: Any) -> str:
    """Hash a JSON-serializable run configuration into a stable cache identity."""
    canonical = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def text_fingerprint(comment: str) -> str:
    return hashlib.sha256(comment.encode("utf-8")).hexdigest()


def load_cached_predictions(path: str | Path) -> list[dict[str, Any]]:
    """Load all structurally valid JSONL cache records; malformed tail rows are skipped."""
    source = Path(path)
    if not source.exists():
        return []
    rows = []
    with source.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                normalize_action(row.get("action"))
                if all(
                    key in row
                    for key in (
                        "case_id",
                        "variant",
                        "text_sha256",
                        "config_fingerprint",
                        "cache_version",
                    )
                ):
                    rows.append(row)
            except (json.JSONDecodeError, TypeError, ValueError):
                # An interrupted append must not make the otherwise resumable run
                # unusable.  It remains absent and is retried on the next run.
                continue
    return rows


def _json_ready(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    # Round-trip gives cache writes one predictable, JSON-only contract and
    # handles IntEnum severities without adding a Pydantic dependency here.
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _normalize_prediction(output: Any) -> dict[str, Any]:
    if isinstance(output, str):
        prediction = {"action": output}
    elif hasattr(output, "model_dump"):
        prediction = output.model_dump(mode="json")
    elif isinstance(output, Mapping):
        prediction = dict(output)
    else:
        raise TypeError("variant function must return an action string or mapping")

    action = prediction.get(
        "action", prediction.get("pred_action", prediction.get("final_action"))
    )
    prediction["action"] = normalize_action(action)
    return _json_ready(prediction)


def _cache_key(row: Mapping[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(row["case_id"]),
        str(row["text_sha256"]),
        str(row["variant"]),
        str(row["config_fingerprint"]),
        str(row["cache_version"]),
    )


def run_system_eval(
    cases: Sequence[Mapping[str, Any]] | str | Path,
    variant_fns: Mapping[str, Callable[[Mapping[str, Any]], Any]],
    cache_path: str | Path,
    *,
    variants: Sequence[str] = VARIANTS,
    config_fingerprint: str = "injected-default-v1",
    cache_version: str = CACHE_VERSION,
    clock: Callable[[], float] = time.perf_counter,
    max_workers: int = 1,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run requested variants, resuming only exact cache-identity matches.

    Failed calls are returned under ``errors`` and are intentionally not cached,
    so rerunning retries only the missing case/variant pairs.  ``config_fingerprint``
    should identify prompts, schemas, routing, and model configuration; the CLI
    constructs that production fingerprint automatically.
    """
    if isinstance(cases, (str, Path)):
        normalized_cases = load_cases(cases)
    else:
        normalized_cases = [_normalize_case(row) for row in cases]
        ids = [case["id"] for case in normalized_cases]
        if len(ids) != len(set(ids)):
            raise ValueError("case ids must be unique")

    requested = tuple(variants)
    if not requested or len(requested) != len(set(requested)):
        raise ValueError("variants must be non-empty and unique")
    unknown = [variant for variant in requested if variant not in AVAILABLE_VARIANTS]
    if unknown:
        raise ValueError(f"unknown variants: {', '.join(unknown)}")
    missing = [variant for variant in requested if variant not in variant_fns]
    if missing:
        raise ValueError(f"missing variant functions: {', '.join(missing)}")
    if not config_fingerprint:
        raise ValueError("config_fingerprint must be non-empty")
    if max_workers < 1:
        raise ValueError("max_workers must be positive")

    cache_file = Path(cache_path)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cached_by_key = {_cache_key(row): row for row in load_cached_predictions(cache_file)}
    if cache_file.exists() and cache_file.stat().st_size:
        with cache_file.open("rb") as handle:
            handle.seek(-1, 2)
            needs_newline = handle.read(1) != b"\n"
        if needs_newline:
            # Preserve an interrupted tail, but do not concatenate the next
            # successful record onto it and silently lose that prediction too.
            with cache_file.open("a", encoding="utf-8") as handle:
                handle.write("\n")

    predictions: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    n_cached = 0
    n_new = 0

    jobs = []
    # Interleave variants, rotating their order per case to reduce time/order bias.
    for index, case in enumerate(normalized_cases):
        offset = index % len(requested) if requested else 0
        for variant in requested[offset:] + requested[:offset]:
            identity = {
                "case_id": case["id"],
                "text_sha256": text_fingerprint(case["comment"]),
                "variant": variant,
                "config_fingerprint": config_fingerprint,
                "cache_version": cache_version,
            }
            key = _cache_key(identity)
            cached = cached_by_key.get(key)
            if cached is not None:
                predictions.append(cached)
                n_cached += 1
                continue
            jobs.append((variant, case, identity))

    def execute(job):
        variant, case, identity = job
        started = clock()
        try:
            # Gold labels and rationales never cross the prediction boundary.
            output = _normalize_prediction(variant_fns[variant](
                {"id": case["id"], "comment": case["comment"]}
            ))
            return {**output, **identity,
                    "latency_ms": max(0.0, (clock() - started) * 1000.0)}, None
        except Exception as exc:
            return None, {"case_id": case["id"], "variant": variant,
                          "error_type": type(exc).__name__, "message": str(exc)}

    # Only this coordinator writes cache records, even with parallel requests.
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(execute, job) for job in jobs]
        for future in as_completed(futures):
            record, error = future.result()
            if record is not None:
                with cache_file.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                predictions.append(record)
                n_new += 1
            else:
                errors.append(error)
            if progress is not None:
                progress({"completed": n_cached + n_new + len(errors),
                          "total": len(normalized_cases) * len(requested),
                          "variant": (record or error)["variant"],
                          "case_id": (record or error)["case_id"],
                          "ok": record is not None})

    order = {case["id"]: i for i, case in enumerate(normalized_cases)}
    predictions.sort(key=lambda row: (requested.index(row["variant"]), order[row["case_id"]]))

    return {
        "cache_version": cache_version,
        "config_fingerprint": config_fingerprint,
        "variants": list(requested),
        "n_cases": len(normalized_cases),
        "n_cached_predictions": n_cached,
        "n_new_predictions": n_new,
        "max_workers": max_workers,
        "predictions": predictions,
        "errors": errors,
        "metrics": score_variants(normalized_cases, predictions, requested),
    }


def write_reports(
    result: Mapping[str, Any],
    output_dir: str | Path,
    *,
    basename: str = "system_eval_metrics",
) -> dict[str, str]:
    """Write an auditable summary JSON and one-row-per-variant metrics CSV."""
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    json_path = destination / f"{basename}.json"
    csv_path = destination / f"{basename}.csv"

    summary = {
        key: result[key]
        for key in (
            "cache_version",
            "config_fingerprint",
            "benchmark_fingerprint",
            "variants",
            "n_cases",
            "n_cached_predictions",
            "n_new_predictions",
            "max_workers",
            "run_metadata",
            "paired_comparisons",
            "errors",
            "metrics",
        )
        if key in result
    }
    summary["metric_definitions"] = {
        "unsafe_auto_allow_rate": "predicted allow among gold human-review/remove cases",
        "over_remove_rate": "predicted remove among gold allow/human-review cases",
        "auto_decision_accuracy": "exact action accuracy among predicted allow/remove cases",
        "high_risk_recall": "predicted human-review/remove among gold high-risk cases",
        "coverage": "completed predictions divided by total benchmark cases",
    }
    json_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=("variant", *METRIC_COLUMNS))
        writer.writeheader()
        for variant in result["variants"]:
            metrics = result["metrics"][variant]
            writer.writerow({"variant": variant, **{key: metrics.get(key) for key in METRIC_COLUMNS}})
    return {"json": str(json_path), "csv": str(csv_path)}


def make_production_variant_fns(
    routing_table: Mapping[str, Mapping[str, Any]],
    *,
    single_model: str = "deepseek-chat",
    classify_fn: Callable[..., Any] = classify,
    detect_fn: Callable[..., Any] = detect_context,
    adjudicate_fn: Callable[..., Any] = default_adjudicate_fn,
    store: Any = None,
    graph_builder: Callable[..., Any] = build_graph,
) -> dict[str, Callable[[Mapping[str, Any]], dict[str, Any]]]:
    """Compose the real Arbiter primitives into the four ablation variants.

    ``full_system`` receives the injected precedent store. No human decision is
    supplied. The product confidence gate is applied to the final graph state so
    low-confidence allow/remove recommendations count as human-review, exactly
    as the checkpointed API would queue them.
    """
    table = {category: dict(config) for category, config in routing_table.items()}
    missing_categories = [category for category in ALL_6 if category not in table]
    if missing_categories:
        raise ValueError(f"routing table is missing: {', '.join(missing_categories)}")

    def policy_only_adjudicate(messages: list[dict[str, Any]], tools: list[dict[str, Any]]):
        """Expose written policy, but neither precedent schema nor precedent prompt.

        Merely passing ``store=None`` would still advertise search_precedents to
        the model and measure a failed retrieval attempt.  That is not a clean
        ablation, so this adapter removes both affordances before the real model
        function sees the turn.
        """
        filtered_tools = [
            tool
            for tool in tools
            if tool.get("function", {}).get("name") != "search_precedents"
        ]
        filtered_messages = []
        for message in messages:
            copied = dict(message)
            if copied.get("role") == "system" and isinstance(copied.get("content"), str):
                copied["content"] = copied["content"].replace(
                    " and search_precedents to see how human moderators ruled similar comments",
                    "",
                )
            filtered_messages.append(copied)
        return adjudicate_fn(filtered_messages, filtered_tools)

    specialist_graph = graph_builder(table, classify_fn=classify_fn, detect_fn=detect_fn)
    policy_graph = graph_builder(
        table,
        classify_fn=classify_fn,
        detect_fn=detect_fn,
        adjudicate_fn=policy_only_adjudicate,
        store=None,
    )
    full_graph = graph_builder(
        table,
        classify_fn=classify_fn,
        detect_fn=detect_fn,
        adjudicate_fn=adjudicate_fn,
        store=store,
    )

    def single_call(case: Mapping[str, Any]) -> dict[str, Any]:
        result = classify_fn(single_model, case["comment"], list(ALL_6))
        if hasattr(result, "model_dump"):
            dumped = result.model_dump(mode="json")
        elif isinstance(result, Mapping):
            dumped = dict(result)
        else:
            raise TypeError("classify_fn must return ClassifyResult or a mapping")
        raw_verdicts = dumped.get("verdicts", dumped)
        if not isinstance(raw_verdicts, Mapping):
            raise TypeError("single-call verdicts must be a category mapping")
        returned_categories = set(raw_verdicts)
        expected_categories = set(ALL_6)
        if returned_categories != expected_categories:
            missing = sorted(expected_categories - returned_categories)
            extra = sorted(returned_categories - expected_categories)
            details = []
            if missing:
                details.append(f"missing={','.join(missing)}")
            if extra:
                details.append(f"extra={','.join(extra)}")
            raise ValueError("single-call category contract violated: " + " ".join(details))
        decision = aggregate(raw_verdicts, dict(DEFAULT_CONTEXT_FLAGS))
        return {
            **decision,
            "raw_verdicts": raw_verdicts,
            "context_flags": dict(DEFAULT_CONTEXT_FLAGS),
            "routing_snapshot": {category: single_model for category in raw_verdicts},
            "escalated": False,
            "logical_model_turns": 1,
        }

    def invoke(graph: Any, case: Mapping[str, Any], base_turns: int = 7) -> dict[str, Any]:
        state = graph.invoke(initial_state(case["comment"]))
        output = dict(state)
        output["ai_recommended_action"] = state["action"]
        output["review_required"] = state["action"] == "human-review"
        if state.get("escalated") and state.get("adjudication"):
            output["review_required"] = needs_human(state) == "human"
            if output["review_required"]:
                output["action"] = "human-review"
        # Logical turns, not billing usage: excludes retries and embeddings.
        output["logical_model_turns"] = base_turns + state.get("adj_steps", 0)
        return output

    def specialists_only(case: Mapping[str, Any]) -> dict[str, Any]:
        # Same six classifiers and aggregation, with no model/context modifier.
        graph = graph_builder(table, classify_fn=classify_fn,
                              detect_fn=lambda _: ContextFlags())
        return invoke(graph, case, base_turns=6)

    return {
        "single_call": single_call,
        "specialists_only": specialists_only,
        "specialist_panel": lambda case: invoke(specialist_graph, case),
        "policy_agent": lambda case: invoke(policy_graph, case),
        "full_system": lambda case: invoke(full_graph, case),
    }


__all__ = [
    "ACTIONS",
    "CACHE_VERSION",
    "VARIANTS",
    "load_cases",
    "load_cached_predictions",
    "make_config_fingerprint",
    "make_production_variant_fns",
    "run_system_eval",
    "text_fingerprint",
    "write_reports",
]
