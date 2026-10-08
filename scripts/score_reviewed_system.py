"""Rescore saved system-ablation predictions against a reviewed export; makes no model calls."""
import argparse
import csv
import json
from pathlib import Path

from arbiter.eval.review_packets import digest, validate_review_export
from arbiter.eval.system_runner import load_cached_predictions, load_cases, text_fingerprint
from arbiter.eval.system_score import compare_variants, score_variants


STAGE_PREFIX = "previously_seen_"


def _label(action, severity, categories):
    return action, severity, sorted(categories)


def compare_with_ai_draft(packet, labels, draft):
    """Count accepted suggestions; an edited label must not keep the AI's rationale."""
    if packet.get("provenance", {}).get("annotation_method") != "ai_assisted":
        return {}, []
    if (draft is None or draft.get("draft_id") != packet["provenance"].get("ai_draft_id")
            or draft["draft_id"] != digest({k: v for k, v in draft.items() if k != "draft_id"})):
        raise ValueError("AI-assisted labels need the exact AI draft recorded in the packet")
    suggestions = {row["id"]: row for row in draft["labels"]}
    changed = []
    for row in labels:
        ai = suggestions[row["id"]]
        if _label(ai["action"], ai["severity"], ai["categories"]) != _label(
                row["gold_action"], row["gold_severity"], row["gold_categories"]):
            if row["rationale"] == ai["rationale"].strip():
                raise ValueError(f"{row['id']}: label differs from the AI draft but keeps its rationale")
            changed.append(row["id"])
    return suggestions, changed


def load_saved_predictions(labels, experiment_dir, results_dir, cache_path):
    """Select the exact cached rows behind each stage report, with full coverage."""
    stage_of = {}
    for row in labels:
        if not row["split"].startswith(STAGE_PREFIX):
            raise ValueError(f"{row['id']}: split {row['split']!r} is not a saved experiment stage")
        stage_of[row["id"]] = row["split"][len(STAGE_PREFIX):]
    cache = load_cached_predictions(cache_path)
    references, selected, stages, variants = {}, {}, {}, None
    for stage in dict.fromkeys(stage_of.values()):
        frozen = {case["id"]: case for case in load_cases(Path(experiment_dir) / f"{stage}.jsonl")}
        report = json.loads((Path(results_dir) / f"{stage}.json").read_text(encoding="utf-8"))
        if variants is not None and report["variants"] != variants:
            raise ValueError("Stage reports compare different variants")
        variants = report["variants"]
        stages[stage] = {"n_cases": sum(s == stage for s in stage_of.values()),
                         "config_fingerprint": report["config_fingerprint"],
                         "cache_version": report["cache_version"],
                         "finished_at_utc": report["run_metadata"].get("finished_at_utc"),
                         "models": sorted(({report["run_metadata"].get(key) for key in
                                            ("single_model", "context_model", "adjudicator_model")}
                                           | {r["model"] for r in report["run_metadata"].get("routing_table", {}).values()})
                                          - {None})}
        for row in labels:
            if stage_of[row["id"]] != stage:
                continue
            if row["id"] not in frozen or frozen[row["id"]]["comment"] != row["text"]:
                raise ValueError(f"{row['id']}: reviewed text differs from the frozen {stage} case")
            references[row["id"]] = frozen[row["id"]]["gold_action"]
        for prediction in cache:
            case_id = prediction["case_id"]
            if (stage_of.get(case_id) == stage and prediction["variant"] in variants
                    and prediction["config_fingerprint"] == report["config_fingerprint"]
                    and prediction["cache_version"] == report["cache_version"]
                    and prediction["text_sha256"] == text_fingerprint(frozen[case_id]["comment"])):
                selected[(case_id, prediction["variant"])] = prediction
    missing = [f"{row['id']}/{v}" for row in labels for v in variants if (row["id"], v) not in selected]
    if missing:
        raise ValueError(f"Missing saved prediction for {', '.join(missing)}")
    return stage_of, references, selected, variants, stages


def write_markdown(path, report, variants):
    labels, n = report["labels"], report["n_cases"]
    assisted = labels["annotation_method"] == "ai_assisted"
    models = sorted({m for stage in report["predictions"]["stages"].values() for m in stage["models"]})
    lines = [f"# {n} 条复核标签对照已保存的消融预测", "",
             "本报告只重放已保存的预测，不调用模型。由 `scripts/score_reviewed_system.py` 生成。", "",
             "## 解读限制", "",
             "- 这批案例按旧实验的方案分歧优先挑选，并非随机样本；数字只用于诊断，不代表总体准确率。",
             f"- 标签为 `{labels['annotation_method']}`" + ("：复核人确认时能看到 AI 建议，不属于独立盲审。" if assisted else "。"),
             f"- 预测来自 {', '.join(report['predictions']['stages'])} 阶段的受控实验缓存（模型：{', '.join(models)}），"
             f"生成于政策 {report['policy_version']} 定稿之前；反映旧系统判断与新标签的差异，不评估当前代码。",
             "- stress 阶段为高风险富集样本。", "",
             "## 标签来源", "",
             f"- 复核人：`{labels['reviewer']}`；{n} 条全部完成。",
             *([f"- 与 AI 草稿完全一致 {labels['accepted_ai_draft_unchanged']} 条；"
                f"修改 {len(labels['changed_from_ai_draft_ids'])} 条：{', '.join(labels['changed_from_ai_draft_ids']) or '无'}。"]
               if assisted else []),
             f"- 旧参考标签与复核标签动作一致 {n - len(report['old_reference']['overturned_ids'])}/{n}。"]
    for revision in labels["revisions"]:
        lines.append(f"- 导出修订 `{revision['id']}`：{revision.get('reviewer_note', revision['reason'])}")
    lines += ["", "## 各方案", "",
              "| 方案 | 与复核动作一致 | Action macro-F1 | 漏放（应审/删却允许） | 误删 | 交人工 |",
              "|---|---:|---:|---:|---:|---:|"]
    for variant in variants:
        m = report["metrics"][variant]
        agree = sum(m["action_confusion"][a][a] for a in m["action_confusion"])
        lines.append(f"| {variant} | {agree}/{m['n_scored']} | {m['action_macro_f1']:.3f} | "
                     f"{m['unsafe_auto_allow_count']}/{m['unsafe_auto_allow_denominator']} | "
                     f"{m['over_remove_count']}/{m['over_remove_denominator']} | "
                     f"{m['human_review_count']}/{m['n_scored']} |")
    lines += ["", "相邻方案的配对变化（按复核标签计算，不是显著性检验）：", ""]
    for pair in report["paired_comparisons"]:
        lines.append(f"- `{pair['before']}` → `{pair['after']}`：纠正 {pair['n_corrected']}，"
                     f"改错 {pair['n_regressed']}，动作变化 {pair['n_changed']}。")
    lines += ["", "逐条结果见同目录 `cases.csv`。", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", required=True)
    parser.add_argument("--reviewed", required=True)
    parser.add_argument("--ai-draft", help="Defaults to ai-preannotations.json beside an assisted packet")
    parser.add_argument("--experiment-dir", default="eval/experiments/system-ablation-v1")
    parser.add_argument("--results-dir", default="eval/results/system-ablation-controlled-v1")
    parser.add_argument("--cache", default="eval_cache/system-ablation-controlled-v1.jsonl")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    packet_path = Path(args.packet)
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    exported = json.loads(Path(args.reviewed).read_text(encoding="utf-8-sig"))
    labels = validate_review_export(packet, exported, require_complete=True)
    draft_path = Path(args.ai_draft) if args.ai_draft else packet_path.with_name("ai-preannotations.json")
    draft = json.loads(draft_path.read_text(encoding="utf-8")) if draft_path.exists() else None
    suggestions, changed = compare_with_ai_draft(packet, labels, draft)
    stage_of, references, selected, variants, stages = load_saved_predictions(
        labels, args.experiment_dir, args.results_dir, args.cache)
    predictions = list(selected.values())
    report = {
        "packet_id": packet["packet_id"], "policy_version": packet["policy_version"], "n_cases": len(labels),
        "variants": variants, "model_calls": 0,
        "scope": "Disagreement-prioritized diagnostic cases rescored from saved predictions; not a population estimate.",
        "labels": {"annotation_method": labels[0]["annotation_method"], "reviewer": labels[0]["reviewer"],
                   "ai_draft_id": labels[0]["ai_draft_id"],
                   "accepted_ai_draft_unchanged": len(labels) - len(changed) if suggestions else None,
                   "changed_from_ai_draft_ids": changed, "revisions": exported.get("revisions", [])},
        "old_reference": {"overturned_ids": [r["id"] for r in labels if references[r["id"]] != r["gold_action"]]},
        "predictions": {"cache": str(args.cache), "stages": stages},
        "metrics": score_variants(labels, predictions, variants),
        "paired_comparisons": [compare_variants(labels, predictions, before, after)
                               for before, after in zip(variants, variants[1:])],
    }
    out = Path(args.output_dir)
    out.mkdir(parents=True)
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fields = ["id", "stage", "human_action", "human_severity", "human_categories", "ai_draft_action",
              "changed_from_ai_draft", "old_reference_action", *variants, "rationale", "text"]
    with (out / "cases.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in labels:
            writer.writerow({"id": row["id"], "stage": stage_of[row["id"]], "human_action": row["gold_action"],
                             "human_severity": row["gold_severity"],
                             "human_categories": ";".join(row["gold_categories"]),
                             "ai_draft_action": suggestions.get(row["id"], {}).get("action", ""),
                             "changed_from_ai_draft": row["id"] in changed,
                             "old_reference_action": references[row["id"]],
                             **{v: selected[(row["id"], v)]["action"] for v in variants},
                             "rationale": row["rationale"], "text": row["text"]})
    write_markdown(out / "REPORT.zh-CN.md", report, variants)
    print(json.dumps({v: f"{sum(m['action_confusion'][a][a] for a in m['action_confusion'])}/{m['n_scored']}"
                      for v, m in report["metrics"].items()}))


if __name__ == "__main__":
    main()
