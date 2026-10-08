"""Pair actual before/after decisions only after an explicit human review export."""
import argparse
import json
from pathlib import Path

from arbiter.eval.adjudication_eval import threshold_sweep
from arbiter.eval.review_packets import validate_review_export
from arbiter.eval.system_score import compare_variants, percentile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", required=True)
    parser.add_argument("--reviewed", required=True)
    parser.add_argument("--decisions", default="eval/results/adjudicator-v2-probe/decisions.jsonl")
    parser.add_argument("--model", default="gpt-5.4-mini")
    parser.add_argument("--kind", choices=["natural", "component"], default="natural")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    packet = json.loads(Path(args.packet).read_text(encoding="utf-8"))
    exported = json.loads(Path(args.reviewed).read_text(encoding="utf-8-sig"))
    labels = validate_review_export(packet, exported, require_complete=True)
    rows = [json.loads(line) for line in Path(args.decisions).read_text(encoding="utf-8").splitlines()]
    rows = [r for r in rows if r["kind"] == args.kind and r["model"] == args.model and "prediction" in r]
    if {r["id"] for r in rows} != {r["id"] for r in labels} or len(rows) != len(labels):
        raise ValueError("Complete, unique prediction coverage for exactly the reviewed packet is required")
    by_id = {r["id"]: r for r in labels}
    for r in rows:
        if r["prediction"]["comment"] != by_id[r["id"]]["text"]:
            raise ValueError("Prediction and reviewed text differ")
        if r["prediction"].get("audit", {}).get("policy_version") != packet["policy_version"]:
            raise ValueError("Prediction and annotation policy versions differ")
    pairs = [record for row in rows for record in [
        {"case_id": row["id"], "variant": "before", "action": row["baseline_action"]},
        {"case_id": row["id"], "variant": "after", "action": row["prediction"]["action"]}]]
    latency = [r["added_latency_ms"] for r in rows if r["prediction"].get("escalated")]
    report = {"packet_id": packet["packet_id"], "policy_version": packet["policy_version"],
        "annotation_methods": sorted({r["annotation_method"] for r in labels}),
        "model": args.model, "kind": args.kind, "paired": compare_variants(labels, pairs, "before", "after"),
        "added_latency_p50_ms": percentile(latency, .5), "added_latency_p95_ms": percentile(latency, .95),
        "thresholds": threshold_sweep(labels, [{"case_id": r["id"], **r["prediction"]} for r in rows], label_status="attested_human_review"),
        "scope": "Reviewed diagnostic cases, not an independent unseen population benchmark. No threshold selected."}
    with Path(args.output).open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["paired"]))


if __name__ == "__main__":
    main()
