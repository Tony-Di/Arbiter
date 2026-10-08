"""Build blind review packets and historical threshold diagnostics; zero model calls."""
import argparse
import json
from pathlib import Path

from arbiter.eval.adjudication_eval import threshold_sweep
from arbiter.eval.review_packets import make_packet, write_packet
from arbiter.eval.system_runner import load_cases, load_cached_predictions, text_fingerprint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="eval/experiments/human-review-v2")
    args = parser.parse_args()
    out = Path(args.output_dir)
    if out.exists():
        raise SystemExit("Use a new output directory; review progress must not be overwritten.")
    out.mkdir(parents=True)
    cache = load_cached_predictions("eval_cache/system-ablation-controlled-v1.jsonl")
    rows, cases, reports, audit = [], [], {}, []
    for split in ("development", "holdout", "stress"):
        split_cases = load_cases(f"eval/experiments/system-ablation-v1/{split}.jsonl")
        summary = json.loads(Path(f"eval/results/system-ablation-controlled-v1/{split}.json").read_text())
        by_id = {c["id"]: c for c in split_cases}
        selected = [r for r in cache if r["case_id"] in by_id
                    and r["config_fingerprint"] == summary["config_fingerprint"]
                    and r["cache_version"] == summary["cache_version"]
                    and r["text_sha256"] == text_fingerprint(by_id[r["case_id"]]["comment"])]
        identities = [(r["case_id"], r["variant"]) for r in selected]
        if len(identities) != len(set(identities)):
            raise ValueError("Duplicate cache identities")
        if len(selected) != len(split_cases) * len(summary["variants"]):
            raise ValueError("Incomplete historical run")
        rows.extend(selected)
        for case in split_cases:
            predictions = {r["variant"]: r["action"] for r in selected if r["case_id"] == case["id"]}
            mismatch = any(a != case["gold_action"] for a in predictions.values())
            disagreement = len(set(predictions.values())) > 1
            item = {**case, "split": "previously_seen_" + split,
                    "priority": 2 * disagreement + mismatch}
            cases.append(item)
            audit.append({"id": case["id"], "split": split, "reference_action": case["gold_action"],
                          "variant_actions": predictions, "variant_disagreement": disagreement,
                          "reference_disagreement": mismatch, "priority": item["priority"]})
        reports[split] = threshold_sweep(split_cases, [r for r in selected if r["variant"] == "policy_agent"])
    cases.sort(key=lambda c: (-c["priority"], c["id"]))
    packet = make_packet(cases, "旧实验标签盲审：优先复核分歧案例；这些样本已经用于开发，不再是独立测试集。",
        provenance={"label_status": "user_confirmed_not_individually_human_reviewed", "confirmed_on": "2026-09-22"})
    write_packet(packet, out / "all-cases")
    first = make_packet(cases[:20], "首批 20 条：旧实验分歧案例盲审。请独立按现行政策标注。",
                        provenance=packet["provenance"])
    write_packet(first, out / "first-20")
    (out / "disagreements.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "historical-thresholds.json").write_text(json.dumps(reports, indent=2) + "\n", encoding="utf-8")
    summary = {"n_cases": len(cases), "n_variant_disagreements": sum(r["variant_disagreement"] for r in audit),
               "n_reference_disagreements": sum(r["reference_disagreement"] for r in audit),
               "human_labels_completed": 0, "packet_id": packet["packet_id"],
               "annotation_status": packet["provenance"]["label_status"]}
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
