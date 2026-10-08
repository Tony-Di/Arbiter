"""Replay deterministic decisions on the SAME saved intermediate outputs (no API)."""
import json
from pathlib import Path

from arbiter.eval.system_runner import DEFAULT_CONTEXT_FLAGS, load_cases, load_cached_predictions, text_fingerprint
from arbiter.eval.system_score import compare_variants
from arbiter.product.aggregator import aggregate


def main():
    root = Path("eval/results/system-ablation-controlled-v1")
    cached = load_cached_predictions("eval_cache/system-ablation-controlled-v1.jsonl")
    audits = {}
    for stage in ("development", "holdout", "stress"):
        summary_path = root / f"{stage}.json"
        if not summary_path.exists():
            continue
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        cases = load_cases(f"eval/experiments/system-ablation-v1/{stage}.jsonl")
        by_id = {case["id"]: case for case in cases}
        selected = {}
        for row in cached:
            if (row["case_id"] in by_id and row["config_fingerprint"] == summary["config_fingerprint"]
                    and row["cache_version"] == summary["cache_version"]
                    and row["text_sha256"] == text_fingerprint(by_id[row["case_id"]]["comment"])):
                selected[(row["case_id"], row["variant"])] = row
        stage_audit = {}
        for arm, mechanism in (("specialist_panel", "context"), ("policy_agent", "adjudication_and_gate")):
            paired = []
            for (case_id, variant), row in selected.items():
                if variant != arm:
                    continue
                flags = DEFAULT_CONTEXT_FLAGS if mechanism == "context" else row["context_flags"]
                before = aggregate(row["raw_verdicts"], flags)["action"]
                paired.extend([{"case_id": case_id, "variant": "before", "action": before},
                               {"case_id": case_id, "variant": "after", "action": row["action"]}])
            stage_audit[mechanism] = compare_variants(cases, paired, "before", "after")
        policy_rows = [row for (_, arm), row in selected.items() if arm == "policy_agent"]
        stage_audit["confidence_gate"] = {
            "escalated": sum(bool(row.get("escalated")) for row in policy_rows),
            "recommendations_sent_to_review": sum(row.get("ai_recommended_action") != "human-review"
                and row["action"] == "human-review" for row in policy_rows),
        }
        audits[stage] = stage_audit
    payload = {
        "method": "Counterfactual deterministic replay on identical saved classifier outputs. No additional model calls; not a separate end-to-end arm and no latency assigned.",
        "stages": audits,
    }
    (root / "mechanism_audit.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({stage: {name: {key: val for key, val in metric.items() if not key.endswith('_ids')}
                              for name, metric in result.items()} for stage, result in audits.items()}, indent=2))


if __name__ == "__main__":
    main()
