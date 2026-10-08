"""Real tool-contract and natural-routing probes, with frozen paired upstreams.

No reference labels enter prompts. Component success measures valid submissions,
not correct moderation. Natural and constructed-state results remain separate.
"""
import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
import time

from dotenv import load_dotenv

from arbiter.classify import ALL_6
from arbiter.classify.registry import REGISTRY, get_adapter
from arbiter.eval.adjudication_eval import adjudicate_snapshot, threshold_sweep
from arbiter.eval.review_packets import make_packet, write_packet
from arbiter.moderation_policy import POLICY_VERSION
from arbiter.product.aggregator import aggregate
from arbiter.product.context import ContextFlags, detect_context
from arbiter.product.graph import build_graph
from arbiter.product.state import initial_state


def component_state(case):
    state = initial_state(case["comment"])
    state["raw_verdicts"] = {c: {"severity": case["severities"].get(c, 0), "reason": "Injected diagnostic fixture", "span": None} for c in ALL_6}
    state["context_flags"] = ContextFlags(**case["context"]).model_dump()
    state.update(aggregate(state["raw_verdicts"], state["context_flags"]))
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-live", action="store_true")
    parser.add_argument("--models", nargs="+", default=["gpt-5.4-mini", "deepseek-chat"], choices=REGISTRY)
    parser.add_argument("--natural-model", default="gpt-5.4-mini", choices=REGISTRY)
    parser.add_argument("--output-dir", default="eval/results/adjudicator-v2-probe")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    path = root / "eval/experiments/adjudicator-v2-probe/cases.json"
    fixture = json.loads(path.read_text(encoding="utf-8"))
    if not args.run_live:
        print("8 natural inputs + 6 constructed states per model. Pass --run-live to call providers.")
        return
    load_dotenv()
    out = Path(args.output_dir)
    if out.exists():
        raise SystemExit("Refusing to overwrite prior live results; choose another output directory")
    out.mkdir(parents=True)
    manifest = {"policy_version": POLICY_VERSION, "started_at": datetime.now(timezone.utc).isoformat(),
        "case_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "workers": 2,
        "models": {m: {k: REGISTRY[m][k] for k in ("base_url", "model")} for m in set(args.models + [args.natural_model])},
        "adjudication_timeout_seconds": 20, "sdk_retries": 0, "node_attempts_per_turn": 2,
        "source_sha256": {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((root / "src/arbiter").rglob("*.py"))},
        "limitations": ["No human gold labels; do not interpret contract success as decision accuracy.",
                        "Constructed upstreams do not validate natural triggering or end-to-end quality.",
                        "No human precedents injected; search can return an empty store.",
                        "Model results are paired on the same upstream evidence; latency uses two workers."]}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    graph = build_graph({c: {"model": args.natural_model, "threshold": 1} for c in ALL_6},
                         detect_fn=partial(detect_context, model=args.natural_model))
    jobs, upstreams = [], []
    def upstream(case):
        start = time.perf_counter()
        try:
            return {"id": case["id"], "state": graph.invoke(initial_state(case["comment"])),
                    "upstream_latency_ms": (time.perf_counter() - start) * 1000}
        except Exception as exc:
            return {"id": case["id"], "error_type": type(exc).__name__}
    with ThreadPoolExecutor(max_workers=2) as pool, (out / "upstreams.jsonl").open("x", encoding="utf-8") as handle:
        for row in pool.map(upstream, fixture["natural"]):
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            upstreams.append(row)
            if "state" in row:
                jobs.append(("natural", row["id"], args.natural_model, row["state"], False))
            print(f"upstream {row['id']}: {'saved' if 'state' in row else row['error_type']}", flush=True)
    for case in fixture["component"]:
        for model in args.models:
            jobs.append(("component", case["id"], model, component_state(case), True))
    class EmptyStore:
        def search(self, query, k=3):
            return []
    def run(job):
        kind, case_id, model, state, forced = job
        adapter = get_adapter(model)
        adapter.client = adapter.client.with_options(timeout=20, max_retries=0)
        result = adjudicate_snapshot(state, adapter.complete_with_tools, force=forced, store=EmptyStore())
        return {"id": case_id, "kind": kind, "model": model, **result}
    results = []
    with ThreadPoolExecutor(max_workers=2) as pool, (out / "decisions.jsonl").open("x", encoding="utf-8") as handle:
        futures = {pool.submit(run, job): job for job in jobs}
        for future in as_completed(futures):
            job = futures[future]
            try:
                row = future.result()
            except Exception as exc:
                row = {"kind": job[0], "id": job[1], "model": job[2], "error_type": type(exc).__name__}
            results.append(row)
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            adj = row.get("prediction", {}).get("adjudication", {})
            print(f"{row['kind']} {row['id']} {row['model']}: {adj.get('status', row.get('error_type', 'not-triggered'))}", flush=True)
    reports = {}
    for kind in ("natural", "component"):
        for model in sorted({r["model"] for r in results if r["kind"] == kind}):
            group = [r for r in results if r["kind"] == kind and r["model"] == model]
            completed = [r for r in group if "prediction" in r]
            predictions = [{"case_id": r["id"], **r["prediction"]} for r in completed]
            reports[kind + ":" + model] = {
                "n_cases": len(group), "n_completed": len(completed),
                "n_triggered": sum(r["prediction"].get("escalated", False) for r in completed),
                "n_valid_submissions": sum(r["prediction"].get("adjudication", {}).get("status") == "submitted" for r in completed),
                "n_fallbacks": sum(r["prediction"].get("adjudication", {}).get("status") == "needs_review" for r in completed),
                "n_changed_after_gate": sum(r["baseline_action"] != r["prediction"]["action"] for r in completed),
                "api_attempts": sum(r["api_attempts"] for r in completed),
                "added_latency_ms": [r["added_latency_ms"] for r in completed if r["prediction"].get("escalated")],
                "thresholds": threshold_sweep(None, predictions, label_status="no_gold_labels")}
    (out / "summary.json").write_text(json.dumps(reports, indent=2) + "\n", encoding="utf-8")
    write_packet(make_packet(fixture["natural"], "真实路由探针盲审；助手编写，已有模型预测，不是独立测试集。"), out / "human-review")
    print(json.dumps({k: {f: v for f, v in report.items() if f not in {"thresholds", "added_latency_ms"}} for k, report in reports.items()}))


if __name__ == "__main__":
    main()
