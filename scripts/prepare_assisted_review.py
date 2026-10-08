"""Validate assistant-authored draft notes and build a separate assisted review page."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path

from arbiter.eval.review_packets import digest, make_packet, render_review_html, validate_ai_draft


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", required=True)
    parser.add_argument("--notes", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    out = Path(args.output_dir)
    if out.exists():
        raise ValueError("Refusing to overwrite an existing assisted review")
    original = json.loads(Path(args.packet).read_text(encoding="utf-8"))
    draft = json.loads(Path(args.notes).read_text(encoding="utf-8"))
    cases = {c["id"]: c for c in original["cases"]}
    for row in draft["labels"]:
        row["text_sha256"] = cases[row["id"]]["text_sha256"]
    draft["created_at"] = datetime.now(timezone.utc).isoformat()
    draft["draft_id"] = digest(draft)
    validate_ai_draft(original, draft)
    packet = make_packet(original["cases"], "首批 20 条：AI 预标注已完成，等待用户逐条确认或修改。",
        provenance={"annotation_method": "ai_assisted", "original_packet_id": original["packet_id"],
                    "ai_draft_id": draft["draft_id"], "human_review_status": "pending"})
    page = render_review_html(packet, ai_draft=draft)
    summary = {"source": "ai_preannotation", "n_ai_labels": len(draft["labels"]),
               "human_labels_completed": 0, "action_counts": dict(Counter(r["action"] for r in draft["labels"])),
               "needs_attention_ids": [r["id"] for r in draft["labels"] if r["needs_attention"]],
               "not_human_gold": True, "independent_blind_review": False, "production_data_changed": False}
    out.mkdir(parents=True)
    for name, value in [("packet.json", packet), ("ai-preannotations.json", draft), ("summary.json", summary)]:
        (out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "review.html").write_text(page, encoding="utf-8")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
