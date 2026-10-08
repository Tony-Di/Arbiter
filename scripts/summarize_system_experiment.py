"""Produce an auditable, offline report from exact cached experiment predictions."""
from __future__ import annotations

import csv
import json
import argparse
from pathlib import Path

from arbiter.eval.system_runner import load_cached_predictions, load_cases, text_fingerprint


ROOT = Path("eval/results/system-ablation-v1")
CASES = Path("eval/experiments/system-ablation-v1")
CACHE = Path("eval_cache/system-ablation-v1.jsonl")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mixed", action="store_true", help="Summarize the mixed-provider development diagnostic")
    args = parser.parse_args()
    root = ROOT if args.mixed else Path("eval/results/system-ablation-controlled-v1")
    cache = load_cached_predictions(CACHE if args.mixed else Path("eval_cache/system-ablation-controlled-v1.jsonl"))
    lines = [
        "# Arbiter system ablation — real API experiment", "",
        "This report is generated from saved API predictions, not simulated outputs.", "",
        "## Interpretation limits", "",
        "- Existing reference labels are frozen unchanged. Their human authorship is unverified unless a run explicitly records human-confirmed status.",
        "- The held-out split was fixed before this experiment. It is a held-out subset of an existing custom benchmark, not a previously unseen public test benchmark.",
        "- Candidates were deliberately stratified by source toxicity scores. Review and error rates on this sample do not estimate live-traffic prevalence or production reviewer workload.",
        ("- Mixed-provider diagnostic: GPT single call; routed specialists + DeepSeek context; panel + DeepSeek policy adjudicator. Differences cannot all be attributed to agent count."
         if args.mixed else "- Controlled experiment: all roles use gpt-5.4-mini. Four arms isolate joint versus split classification, adding context interpretation, then adding conditional policy adjudication. This is NOT the production mixed-model routing configuration."),
        "- Low-confidence recommendations count as human-review, matching the product. Human answers are never fed to prediction functions.",
        "- A removal label occurs only twice in holdout and once in stress. Removal-class estimates are too sparse for strong safety claims.",
        f"- Latency includes each complete variant, measured under {2 if args.mixed else 4} concurrent benchmark requests. It excludes human response time and is not a production load test.",
        "- The mixed-provider diagnostic and controlled development/holdout overlapped in wall-clock time; these are observed service latencies with background load, not isolated microbenchmarks.",
        "- Arms execute independently at temperature zero; residual response variation remains. This is one run, without repeated-run confidence intervals.",
        "- The product policy, 0.95 confidence threshold and six-step cap were unchanged. The threshold has not been calibrated for GPT.",
        "- Logical model turns exclude retries, failed attempts and embeddings. Token usage and dollar cost were not measured.",
        "- The local precedent store was empty. The human-precedent arm is pending independent reviewed data; it is not represented by a fake empty-store run.", "",
    ]
    stage_reports = {}
    for stage in ("development", "holdout", "stress"):
        path = root / f"{stage}.json"
        if not path.exists():
            continue
        report = json.loads(path.read_text(encoding="utf-8"))
        stage_reports[stage] = report
        cases = load_cases(CASES / f"{stage}.jsonl")
        by_id = {case["id"]: case for case in cases}
        selected = {}
        for prediction in cache:
            if (prediction["config_fingerprint"] == report["config_fingerprint"]
                    and prediction["cache_version"] == report["cache_version"]
                    and prediction["case_id"] in by_id
                    and prediction["text_sha256"] == text_fingerprint(by_id[prediction["case_id"]]["comment"])
                    and prediction["variant"] in report["variants"]):
                selected[(prediction["case_id"], prediction["variant"])] = prediction
        lines.extend([f"## {stage.title()} ({report['n_cases']} cases)", "",
            f"Annotation status: `{report['run_metadata']['annotation_status']}`. Failed predictions: {len(report['errors'])}.", "",
            "| Variant | Completed | Action macro-F1 | Unsafe allows | Over-removes | Human review | P50 seconds | P95 seconds |",
            "|---|---:|---:|---:|---:|---:|---:|---:|"])
        for variant in report["variants"]:
            metric = report["metrics"][variant]
            latency = lambda key: "n/a" if metric[key] is None else f"{metric[key] / 1000:.2f}"
            lines.append(f"| {variant} | {metric['n_scored']}/{metric['n_cases']} | {metric['action_macro_f1']:.3f} | "
                f"{metric['unsafe_auto_allow_count']}/{metric['unsafe_auto_allow_denominator']} | "
                f"{metric['over_remove_count']}/{metric['over_remove_denominator']} | "
                f"{metric['human_review_count']}/{metric['n_scored']} | {latency('p50_latency_ms')} | {latency('p95_latency_ms')} |")
        lines.extend(["", "Paired changes count exact matches against the frozen reference actions; they are not statistical significance tests.", ""])
        for pair in report.get("paired_comparisons", []):
            lines.append(f"- `{pair['before']}` → `{pair['after']}`: {pair['n_paired']} common cases; "
                         f"{pair['n_corrected']} corrected, {pair['n_regressed']} regressed, {pair['n_changed']} changed.")
        for variant in report["variants"]:
            rows = [row for (_, arm), row in selected.items() if arm == variant]
            degraded = [row for row in rows if any(fragment in (row.get("adjudication") or {}).get("note", "")
                        for fragment in ("unavailable", "step limit"))]
            lines.append(f"- `{variant}`: {len(degraded)} fallback decisions after adjudicator unavailability or step limit.")
        lines.extend(["", f"Configuration fingerprint: `{report['config_fingerprint']}`.",
                      f"Benchmark fingerprint: `{report['benchmark_fingerprint']}`.", ""])
        fields = ["case_id", "comment", "reference_action", "reference_rationale", "variant", "action",
                  "ai_recommended_action", "review_required", "latency_ms", "escalated", "adj_steps", "adjudicator_note"]
        with (root / f"{stage}_case_predictions.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for case in cases:
                for variant in report["variants"]:
                    row = selected.get((case["id"], variant))
                    if row is None:
                        continue
                    writer.writerow({"case_id": case["id"], "comment": case["comment"],
                        "reference_action": case["gold_action"], "reference_rationale": case.get("rationale", ""),
                        "variant": variant, "action": row["action"],
                        "ai_recommended_action": row.get("ai_recommended_action", row["action"]),
                        "review_required": row.get("review_required", row["action"] == "human-review"),
                        "latency_ms": round(row["latency_ms"], 2), "escalated": row.get("escalated", False),
                        "adj_steps": row.get("adj_steps", 0),
                        "adjudicator_note": (row.get("adjudication") or {}).get("note", "")})
    lines.extend(["## Reproducibility", "",
        "Frozen cases and manifests: `eval/experiments/system-ablation-v1/`.",
        f"Raw resumable cache: `eval_cache/system-ablation-{'v1' if args.mixed else 'controlled-v1'}.jsonl` (local, ignored by Git).",
        "Regenerate this report with `python scripts/summarize_system_experiment.py` (add `--mixed` for the mixed-provider pilot); it makes no model calls.", ""])
    root.mkdir(parents=True, exist_ok=True)
    (root / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {root / 'REPORT.md'}; stages={','.join(stage_reports)}")


if __name__ == "__main__":
    main()
