"""Run the four-way, action-level Arbiter ablation benchmark.

Example:
    python scripts/run_system_eval.py --cases data/system_eval/gold.jsonl

The case file must already contain human gold actions.  Predictions are cached
per text/config/variant, so an interrupted run safely resumes while prompt or
routing changes automatically invalidate stale records.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import datetime
import os
from functools import partial
from pathlib import Path

from dotenv import load_dotenv

from arbiter.api.db import Precedent, init_db, make_engine, make_session_factory
from arbiter.classify import ALL_6
from arbiter.classify.prompt import PROMPT_VERSION, build_prompt
from arbiter.classify.registry import REGISTRY, get_adapter
from arbiter.classify.schema import SCHEMA_VERSION
from arbiter.eval.system_runner import (
    VARIANTS,
    AVAILABLE_VARIANTS,
    load_cases,
    make_config_fingerprint,
    make_production_variant_fns,
    run_system_eval,
    write_reports,
)
from arbiter.eval.system_data import load_annotations
from arbiter.eval.system_score import compare_variants
from arbiter.precedents import EMBED_MODEL, PrecedentStore
from arbiter.product.adjudicator import (
    ADJUDICATOR_MODEL,
    CONFIDENCE_THRESHOLD,
    MAX_TOOL_STEPS,
    build_adjudicator_messages,
)
from arbiter.product.context import CONTEXT_MODEL, build_context_prompt, detect_context
from arbiter.product.policy import get_policy
from arbiter.product.routing import load_routing_table


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _precedent_store(database_url: str) -> tuple[PrecedentStore, str]:
    """Build the injected store and fingerprint its human-ruling content."""
    engine = make_engine(database_url)
    init_db(engine)
    sessions = make_session_factory(engine)
    session = sessions()
    try:
        rows = session.query(Precedent).order_by(Precedent.id).all()
        content = [
            {
                "id": row.id,
                "comment": row.comment_text,
                "action": row.action,
                "severity": row.overall_severity,
                "note": row.note,
                "source": row.source,
            }
            for row in rows
        ]
    finally:
        session.close()
    if not content:
        raise SystemExit(
            "full_system requires a non-empty, human-reviewed precedent database; "
            "seed one first or omit full_system from --variants"
        )
    if any(row["source"] != "human" for row in content):
        raise SystemExit("precedent database contains a non-human row; refusing benchmark")
    return PrecedentStore(sessions), make_config_fingerprint(content)


def _config_fingerprint(
    routing_table: dict,
    *,
    single_model: str,
    variants: list[str],
    precedent_fingerprint: str,
    context_model: str = CONTEXT_MODEL,
    adjudicator_model: str = ADJUDICATOR_MODEL,
    workers: int = 1,
) -> str:
    sample_state = {
        "action": "human-review",
        "overall_severity": 2,
        "effective_verdicts": {category: 0 for category in ALL_6},
        "context_flags": {},
        "comment": "__CACHE_FINGERPRINT__",
    }
    prompt_material = {
        "classify": build_prompt("__CACHE_FINGERPRINT__", list(ALL_6)),
        "context": build_context_prompt("__CACHE_FINGERPRINT__"),
        "adjudicator": build_adjudicator_messages(sample_state),
        "policies": {category: get_policy(category) for category in ALL_6},
    }
    used_model_ids = {
        single_model,
        context_model,
        adjudicator_model,
        *(entry["model"] for entry in routing_table.values()),
    }
    provider_config = {
        model_id: {
            "base_url": REGISTRY[model_id]["base_url"],
            "provider_model": REGISTRY[model_id]["model"],
            "api_key_env": REGISTRY[model_id]["api_key_env"],
        }
        for model_id in sorted(used_model_ids)
    }
    return make_config_fingerprint(
        {
            # Include implementation + tool schemas, not only the base prompt.
            "source_sha256": {
                "src/arbiter/moderation_policy.py": _sha256((Path(__file__).resolve().parents[1] / "src/arbiter/moderation_policy.py").read_text(encoding="utf-8")),
                **{
                str(path.relative_to(Path(__file__).resolve().parents[1])): _sha256(path.read_text(encoding="utf-8"))
                for directory in ("product", "classify", "eval")
                for path in sorted((Path(__file__).resolve().parents[1] / "src" / "arbiter" / directory).rglob("*.py"))
                },
            },
            "classify_prompt_version": PROMPT_VERSION,
            "schema_version": SCHEMA_VERSION,
            "prompt_material_sha256": _sha256(
                json.dumps(prompt_material, ensure_ascii=False, sort_keys=True)
            ),
            "routing_table": routing_table,
            "single_model": single_model,
            "context_model": context_model,
            "adjudicator_model": adjudicator_model,
            "workers": workers,
            "http_timeout": float(os.environ.get("ARBITER_LLM_TIMEOUT", "30")),
            "provider_config": provider_config,
            "max_tool_steps": MAX_TOOL_STEPS,
            "confidence_threshold": CONFIDENCE_THRESHOLD,
            "embed_model": EMBED_MODEL,
            "precedents_sha256": precedent_fingerprint,
            # Variant identity is already in the cache key. Adding another arm
            # must not invalidate otherwise identical completed predictions.
        }
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, help="Human-annotated .jsonl or .csv")
    parser.add_argument("--routing-table", default="routing_table.json")
    parser.add_argument("--single-model", default="deepseek-chat")
    parser.add_argument("--context-model", default=CONTEXT_MODEL, choices=REGISTRY)
    parser.add_argument("--adjudicator-model", default=ADJUDICATOR_MODEL, choices=REGISTRY)
    parser.add_argument(
        "--variants",
        nargs="+",
        choices=AVAILABLE_VARIANTS,
        default=list(VARIANTS),
    )
    parser.add_argument("--cache", default="eval_cache/system_eval.jsonl")
    parser.add_argument("--output-dir", default="eval/results/system_eval")
    parser.add_argument("--report-name", default="system_eval_metrics")
    parser.add_argument("--workers", type=int, default=1, help="Concurrent case/variant requests")
    parser.add_argument("--limit", type=int, help="Smoke-test only the first N frozen cases")
    parser.add_argument("--annotation-status", choices=["unverified", "human-confirmed"], default="unverified")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="validate the completed annotation file without calling any model",
    )
    parser.add_argument(
        "--precedent-db-url",
        default="sqlite:///./arbiter.db",
        help="Database used by full_system precedent retrieval",
    )
    parser.add_argument(
        "--disable-precedents",
        action="store_true",
        help="Run full_system without a precedent store (mainly for diagnostics)",
    )
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    args = parse_args()
    if Path(args.cases).suffix.lower() == ".csv":
        # The annotation template has a stricter contract than generic runner
        # inputs: every gold field and rationale must be completed and coherent.
        load_annotations(args.cases)
    cases = load_cases(args.cases)
    if args.validate_only:
        print(f"validated {len(cases)} completed annotations -> {args.cases}")
        return
    if args.limit is not None:
        if args.limit < 1:
            raise SystemExit("--limit must be positive")
        cases = cases[:args.limit]
    table = load_routing_table(args.routing_table)

    store = None
    precedent_fingerprint = "disabled"
    if "full_system" in args.variants and not args.disable_precedents:
        store, precedent_fingerprint = _precedent_store(args.precedent_db_url)

    config_fingerprint = _config_fingerprint(
        table,
        single_model=args.single_model,
        variants=args.variants,
        precedent_fingerprint=precedent_fingerprint,
        context_model=args.context_model,
        adjudicator_model=args.adjudicator_model,
        workers=args.workers,
    )
    variant_fns = make_production_variant_fns(
        table,
        single_model=args.single_model,
        store=store,
        detect_fn=partial(detect_context, model=args.context_model),
        adjudicate_fn=lambda messages, tools: get_adapter(args.adjudicator_model).complete_with_tools(messages, tools),
    )
    result = run_system_eval(
        cases,
        variant_fns,
        args.cache,
        variants=args.variants,
        config_fingerprint=config_fingerprint,
        max_workers=args.workers,
        progress=lambda event: print(
            f"[{event['completed']}/{event['total']}] {event['variant']} {event['case_id']} "
            f"{'ok' if event['ok'] else 'FAILED'}", flush=True),
    )
    result["run_metadata"] = {
        "finished_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "cases_path": args.cases,
        "annotation_status": args.annotation_status,
        "single_model": args.single_model,
        "routing_table": table,
        "context_model": args.context_model,
        "adjudicator_model": args.adjudicator_model,
        "precedent_fingerprint": precedent_fingerprint,
        "confidence_threshold": CONFIDENCE_THRESHOLD,
        "max_tool_steps": MAX_TOOL_STEPS,
        "latency_scope": "complete variant including confidence gate, excluding human response time; concurrent benchmark load",
        "logical_model_turns_scope": "successful logical model turns; excludes retries, failed attempts, embeddings; not token or dollar cost",
    }
    result["paired_comparisons"] = [
        compare_variants(cases, result["predictions"], before, after)
        for before, after in zip(args.variants, args.variants[1:])
    ]
    result["benchmark_fingerprint"] = make_config_fingerprint(
        [
            {
                "id": case["id"],
                "text": case["comment"],
                "gold_action": case["gold_action"],
                "gold_categories": case.get("gold_categories", []),
                "gold_severity": case.get("gold_severity"),
            }
            for case in cases
        ]
    )
    paths = write_reports(result, args.output_dir, basename=args.report_name)

    print(f"cases={result['n_cases']} new={result['n_new_predictions']} "
          f"cached={result['n_cached_predictions']} errors={len(result['errors'])}")
    print(f"config_fingerprint={config_fingerprint}")
    print(f"json={paths['json']}")
    print(f"csv={paths['csv']}")
    print("\nvariant             macro-F1  unsafe-allow  review-rate  high-risk-R  p95-ms  coverage")
    for variant in args.variants:
        metric = result["metrics"][variant]
        p95 = metric["p95_latency_ms"]
        p95_text = "n/a" if p95 is None else f"{p95:.1f}"
        print(
            f"{variant:20} {metric['action_macro_f1']:8.3f}  "
            f"{metric['unsafe_auto_allow_rate']:12.3f}  "
            f"{metric['human_review_rate']:11.3f}  "
            f"{metric['high_risk_recall']:11.3f}  "
            f"{p95_text:>6}  {metric['coverage']:8.3f}"
        )

    if result["errors"]:
        print("\nSome predictions failed and were left uncached; rerun to retry them.")
        raise SystemExit(2)


if __name__ == "__main__":
    main()
