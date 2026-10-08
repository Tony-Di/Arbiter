"""Small live mechanism probe. Expectations are diagnostic, not human labels.

python scripts/probe_policy_v2.py --run-live
No database, human review or precedent writes occur.
"""
import argparse
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import partial
from pathlib import Path

from dotenv import load_dotenv

from arbiter.classify import ALL_6
from arbiter.classify.registry import REGISTRY, get_adapter
from arbiter.eval.system_runner import make_production_variant_fns
from arbiter.moderation_policy import POLICY_VERSION
from arbiter.product.context import detect_context


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-live", action="store_true")
    parser.add_argument("--model", default="gpt-5.4-mini", choices=REGISTRY)
    parser.add_argument("--output-dir", default="eval/results/policy-v2-probe")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source = root / "eval/experiments/policy-v2-probe/cases.json"
    cases = json.loads(source.read_text(encoding="utf-8"))["cases"]
    if not args.run_live:
        print(f"{len(cases)} frozen diagnostic cases; pass --run-live to call the model.")
        return
    load_dotenv()
    destination = Path(args.output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    predictions_path = destination / "predictions.jsonl"
    if predictions_path.exists():
        raise SystemExit("Output already exists; choose another --output-dir to preserve the prior probe.")
    table = {c: {"model": args.model, "threshold": 1} for c in ALL_6}
    functions = make_production_variant_fns(table, single_model=args.model,
        detect_fn=partial(detect_context, model=args.model),
        adjudicate_fn=lambda messages, tools: get_adapter(args.model).complete_with_tools(messages, tools))
    metadata = {"policy_version": POLICY_VERSION, "model": args.model,
        "provider_model": REGISTRY[args.model]["model"], "base_url": REGISTRY[args.model]["base_url"],
        "case_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "started_at": datetime.now(timezone.utc).isoformat(), "workers": 2,
        "purpose": "Assistant-authored mechanism checks, not independent accuracy measurement.",
        "source_sha256": {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sorted((root / "src/arbiter").rglob("*.py"))}}
    (destination / "manifest.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    def execute(case):
        started = time.perf_counter()
        try:
            # Expectations never cross the prediction boundary.
            prediction = functions["policy_agent"]({"id": case["id"], "comment": case["comment"]})
            flags = prediction["context_flags"]
            checks = {"action": prediction["action"] in case["actions"]}
            if case.get("no_mitigation"):
                checks["no_mitigation"] = not flags.get("mitigation_categories")
            if "language_uses" in case:
                checks["language_use"] = flags.get("language_use") in case["language_uses"]
            return {"id": case["id"], "prediction": prediction, "checks": checks,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2)}
        except Exception as exc:
            return {"id": case["id"], "error_type": type(exc).__name__}
    rows = []
    with ThreadPoolExecutor(max_workers=2) as executor, predictions_path.open("x", encoding="utf-8") as handle:
        for row in executor.map(execute, cases):
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            handle.flush()
            rows.append(row)
            print(f"{row['id']}: {row.get('checks', row.get('error_type'))}", flush=True)
    summary = {"n_cases": len(rows), "completed": sum("prediction" in r for r in rows),
        "passed_all_checks": sum(bool(r.get("checks")) and all(r["checks"].values()) for r in rows),
        "failed_cases": [r["id"] for r in rows if not r.get("checks") or not all(r["checks"].values())],
        "note": metadata["purpose"]}
    (destination / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
