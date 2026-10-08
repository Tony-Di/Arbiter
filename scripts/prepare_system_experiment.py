"""Freeze existing reference labels before inference; never invent human labels."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from arbiter.eval.system_data import load_annotations


DESTINATION = Path("eval/experiments/system-ablation-v1")
DEV_QUOTAS = {"allow": 15, "human-review": 4, "remove": 1}


def freeze(path: Path, content: str) -> None:
    if path.exists() and path.read_text(encoding="utf-8") != content:
        raise SystemExit(f"Refusing to overwrite a different frozen experiment: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> None:
    paths = [Path("data/system_eval/annotation.csv"),
             Path("data/system_eval/high_risk_addendum/annotation.csv")]
    primary, stress = [load_annotations(path) for path in paths]
    if {row["id"] for row in primary} & {row["id"] for row in stress}:
        raise SystemExit("Primary and stress sets overlap")
    dev = []
    for action, count in DEV_QUOTAS.items():
        pool = sorted((row for row in primary if row["gold_action"] == action),
                      key=lambda row: hashlib.sha256(("arbiter-v1:" + row["id"]).encode()).hexdigest())
        if len(pool) <= count:
            raise SystemExit(f"Not enough {action} cases to leave a holdout")
        dev.extend(pool[:count])
    dev_ids = {row["id"] for row in dev}
    test = [row for row in primary if row["id"] not in dev_ids]
    groups = {"development": dev, "holdout": test, "stress": stress}
    manifest = {
        "annotation_status": "unverified: existing labels preserved; human authorship not yet confirmed",
        "source_sha256": {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths},
        "split_rule": "sha256(arbiter-v1:<id>), within reference action; 15 allow + 4 review + 1 remove development",
        "protocol": [
            "Freeze labels and split before any predictions; no policy/prompt/threshold tuning on holdout.",
            "Compare configurations, not a causal estimate of agent count: routing and context differ.",
            "Single-call GPT baseline chosen before inference: it serves five of six routed categories.",
            "Human confidence gate counts as review; never resume with gold answers.",
            "Run stress set separately; it is source-enriched, not 30 gold removal cases.",
            "Report all completed arms, failures, counts, paired corrections/regressions and measured latency.",
            "Do not claim statistically established gains from the very small removal class.",
            "Do not evaluate full_system until independent human precedents are available.",
        ],
        "groups": {},
    }
    for name, rows in groups.items():
        rows = sorted(rows, key=lambda row: row["id"])
        content = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
        freeze(DESTINATION / f"{name}.jsonl", content)
        manifest["groups"][name] = {"n": len(rows),
            "reference_actions": dict(Counter(row["gold_action"] for row in rows)),
            "sha256": hashlib.sha256(content.encode()).hexdigest(), "ids": [row["id"] for row in rows]}
    freeze(DESTINATION / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({name: row["reference_actions"] for name, row in manifest["groups"].items()}, indent=2))


if __name__ == "__main__":
    main()
