"""Freeze 60 new, unlabelled Civil Comments cases for human calibration/holdout review.

No model calls. Samples the first 50,000 source rows at the existing immutable
dataset revision; this is a stratified diagnostic sample, not population prevalence.
"""
import argparse
import ast
import hashlib
import json
import re
from itertools import islice
from pathlib import Path

from arbiter.eval.review_packets import make_packet, write_packet
from arbiter.eval.system_data import sample_civil_comments


def normalized(text):
    return " ".join(re.findall(r"\w+", text.casefold()))


def shingles(text):
    words = normalized(text).split()
    return set(zip(words, words[1:], words[2:]))


def near_duplicate(text, others):
    norm, grams = normalized(text), shingles(text)
    for prior in others:
        if norm == normalized(prior):
            return True
        other = shingles(prior)
        if grams and other and len(grams & other) / len(grams | other) >= 0.8:
            return True
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="eval/experiments/fresh-human-v2")
    args = parser.parse_args()
    out = Path(args.output_dir)
    if out.exists():
        raise SystemExit("Refusing to overwrite a frozen sample")
    old_texts, old_ids, exclusion_files = [], set(), []
    for split in ("development", "holdout", "stress"):
        path = Path(f"eval/experiments/system-ablation-v1/{split}.jsonl")
        exclusion_files.append(path)
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            old_texts.append(row.get("text", row.get("comment")))
            old_ids.add(row["id"])
    path = Path("eval/experiments/policy-v2-probe/cases.json")
    exclusion_files.append(path)
    old_texts.extend(c["comment"] for c in json.loads(path.read_text())["cases"])
    path = Path("scripts/seed_precedents.py")
    exclusion_files.append(path)
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "SEEDS" for t in node.targets):
            old_texts.extend(row[0] for row in ast.literal_eval(node.value))
    source_manifest = json.loads(Path("data/system_eval/manifest.json").read_text())
    from datasets import load_dataset
    stream = load_dataset(source_manifest["dataset_id"], split=source_manifest["dataset_split"],
                          revision=source_manifest["dataset_revision"], streaming=True)
    print("Sampling fixed source prefix; no LLM calls or labels.", flush=True)
    candidates = sample_civil_comments(islice(stream, 50000), safe=36, gray=108, harmful=36, seed=20260922)
    selected, accepted_texts = [], []
    counts = {"safe": 0, "gray": 0, "harmful": 0}
    quotas = {"safe": 12, "gray": 36, "harmful": 12}
    for case in sorted(candidates, key=lambda c: hashlib.sha256(("fresh-v2:" + c["id"]).encode()).hexdigest()):
        group = case["slice"]
        if counts[group] >= quotas[group] or case["id"] in old_ids or near_duplicate(case["text"], old_texts + accepted_texts):
            continue
        index = counts[group]
        case["split"] = "calibration" if index < quotas[group] // 3 else "holdout"
        selected.append(case)
        accepted_texts.append(case["text"])
        counts[group] += 1
    if counts != quotas:
        raise ValueError(f"Insufficient disjoint candidates: {counts}; no partial benchmark written")
    out.mkdir(parents=True)
    for split in ("calibration", "holdout"):
        cases = [c for c in selected if c["split"] == split]
        packet = make_packet(cases, f"新的 {split} 候选：尚无人工标签，不显示模型预测。",
                             provenance={"source_revision": source_manifest["dataset_revision"],
                                         "human_review_status": "pending"})
        write_packet(packet, out / split)
    metadata = {"source": source_manifest, "source_prefix_rows": 50000, "seed": 20260922,
                "n_calibration": 20, "n_holdout": 40, "source_score_quotas": quotas,
                "human_labels_completed": 0, "model_predictions_completed": 0,
                "near_duplicate_rule": "normalized text equality or word-trigram Jaccard >= 0.8; not semantic deduplication",
                "excluded_text_count": len(old_texts), "excluded_ids": len(old_ids),
                "exclusion_sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in exclusion_files},
                "protocol": ["Human-label before inference; do not expose holdout predictions during tuning.",
                             "Calibrate/choose thresholds on calibration only; freeze choices before opening holdout.",
                             "Never insert these cases into production precedents.",
                             "Source toxicity strata are not gold moderation actions.",
                             "No population accuracy or removal-recall claim from a small stratified sample."]}
    (out / "source-candidates.jsonl").write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in selected), encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: metadata[k] for k in ("n_calibration", "n_holdout", "human_labels_completed", "model_predictions_completed")}))


if __name__ == "__main__":
    main()
