"""Blind human review packets. Never promote assistant/reference labels to gold."""
import hashlib
import html
import json
from datetime import datetime
from pathlib import Path

from arbiter.classify import ALL_6
from arbiter.moderation_policy import ACTION_GUIDE, CATEGORY_RULES, POLICY_VERSION, validate_action_severity


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def text_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _validate_label(action, severity, categories, rationale):
    if type(severity) is not int:
        raise ValueError("Integer severity required")
    validate_action_severity(action, severity)
    if (not isinstance(categories, list) or any(c not in ALL_6 for c in categories)
            or len(set(categories)) != len(categories)):
        raise ValueError("Invalid reviewed categories")
    if (severity > 0) != bool(categories):
        raise ValueError("Nonzero harm needs at least one category; severity 0 needs none")
    if not isinstance(rationale, str) or not rationale.strip():
        raise ValueError("Policy rationale required")


def validate_ai_draft(packet, draft):
    """AI suggestions are separate from human exports, even when fully populated."""
    if packet.get("packet_id") != digest({k: v for k, v in packet.items() if k != "packet_id"}):
        raise ValueError("Review packet was modified after freezing")
    if draft.get("packet_id") != packet["packet_id"] or draft.get("policy_version") != packet["policy_version"]:
        raise ValueError("AI draft belongs to a different packet or policy")
    if draft.get("source") != "ai_preannotation" or draft.get("attested_human_review") is not False:
        raise ValueError("AI draft must remain explicitly non-human")
    if not isinstance(draft.get("annotator"), str) or not draft["annotator"].strip():
        raise ValueError("AI annotator required")
    if "draft_id" in draft and draft["draft_id"] != digest({k: v for k, v in draft.items() if k != "draft_id"}):
        raise ValueError("AI draft was modified after freezing")
    originals = {c["id"]: c for c in packet["cases"]}
    seen = set()
    for row in draft.get("labels", []):
        case_id = row.get("id")
        if case_id not in originals or case_id in seen:
            raise ValueError("Unknown or duplicate AI draft ID")
        seen.add(case_id)
        original = originals[case_id]
        if row.get("text_sha256") != original["text_sha256"] or text_hash(original["text"]) != original["text_sha256"]:
            raise ValueError("AI draft text hash mismatch")
        _validate_label(row.get("action"), row.get("severity"), row.get("categories"), row.get("rationale"))
        evidence = row.get("evidence_span")
        if not isinstance(evidence, str) or not evidence.strip() or evidence not in original["text"]:
            raise ValueError("AI draft evidence must be an exact nonempty source span")
        if type(row.get("needs_attention")) is not bool or not isinstance(row.get("uncertainty"), str):
            raise ValueError("AI draft uncertainty fields required")
        if row["needs_attention"] and not row["uncertainty"].strip():
            raise ValueError("Flagged AI draft needs an uncertainty note")
    if seen != set(originals):
        raise ValueError("AI draft must cover every packet case exactly once")
    return draft


def make_packet(cases, purpose, *, provenance=None):
    """Whitelist fields so predictions, reference answers and rationales stay hidden."""
    rows = [{"id": c["id"], "text": c.get("text", c.get("comment")),
             "split": c.get("split", "diagnostic") } for c in cases]
    if len({c["id"] for c in rows}) != len(rows):
        raise ValueError("Duplicate case IDs")
    if not rows or any(not isinstance(c["text"], str) or not c["text"].strip() for c in rows):
        raise ValueError("Packet requires nonempty cases")
    for c in rows:
        c["text_sha256"] = text_hash(c["text"])
    packet = {"policy_version": POLICY_VERSION, "purpose": purpose,
              "provenance": provenance or {}, "cases": rows}
    return {**packet, "packet_id": digest(packet)}


def validate_review_export(packet, exported, *, require_complete=False):
    if packet.get("packet_id") != digest({k: v for k, v in packet.items() if k != "packet_id"}):
        raise ValueError("Review packet was modified after freezing")
    if exported.get("packet_id") != packet["packet_id"] or exported.get("policy_version") != packet["policy_version"]:
        raise ValueError("Review export belongs to a different packet or policy")
    if exported.get("source") != "human_review" or exported.get("attested_human_review") is not True:
        raise ValueError("Explicit human review attestation required")
    reviewer = exported.get("reviewer")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError("Reviewer name or identifier required")
    originals = {c["id"]: c for c in packet["cases"]}
    labels, seen = [], set()
    for row in exported.get("labels", []):
        case_id = row.get("id")
        if case_id not in originals or case_id in seen:
            raise ValueError("Unknown or duplicate reviewed ID")
        seen.add(case_id)
        original = originals[case_id]
        if (row.get("text_sha256") != original["text_sha256"]
                or text_hash(original["text"]) != original["text_sha256"]):
            raise ValueError("Reviewed text hash mismatch")
        action, severity = row.get("gold_action"), row.get("gold_severity")
        categories = row.get("gold_categories")
        rationale = row.get("rationale")
        _validate_label(action, severity, categories, rationale)
        try:
            timestamp = datetime.fromisoformat(row["reviewed_at"].replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                raise ValueError("Review timestamp needs timezone")
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValueError("Review timestamp required") from exc
        labels.append({**original, "gold_action": action, "gold_severity": severity,
                       "gold_categories": categories, "rationale": rationale.strip(),
                       "reviewer": reviewer.strip(), "reviewed_at": row["reviewed_at"],
                       "annotation_source": "human_review", "policy_version": packet["policy_version"],
                       "packet_id": packet["packet_id"],
                       "annotation_method": packet.get("provenance", {}).get("annotation_method", "blind_review"),
                       "ai_draft_id": packet.get("provenance", {}).get("ai_draft_id")})
    if require_complete and seen != set(originals):
        raise ValueError(f"Review incomplete: {len(seen)}/{len(originals)}")
    if not labels:
        raise ValueError("No reviewed labels")
    return labels


def render_review_html(packet, *, ai_draft=None):
    if packet["policy_version"] != POLICY_VERSION:
        raise ValueError("Cannot render a frozen packet using a different policy")
    if packet.get("provenance", {}).get("annotation_method") == "ai_assisted" and ai_draft is None:
        raise ValueError("Assisted review requires its AI draft")
    template = Path(__file__).with_name("review_template.html").read_text(encoding="utf-8")
    guide = "<pre>" + html.escape(ACTION_GUIDE) + "</pre><dl>" + "".join(
        f"<dt>{html.escape(category)}</dt><dd>{html.escape(rule)}</dd>"
        for category, rule in CATEGORY_RULES.items()) + "</dl>"
    if ai_draft is not None:
        # Assisted review uses its own packet ID/storage namespace. The draft stays
        # attached to the original packet, whose text must match this derived view.
        provenance = packet.get("provenance", {})
        if (ai_draft.get("source") != "ai_preannotation" or ai_draft.get("attested_human_review") is not False
                or ai_draft.get("draft_id") != digest({k: v for k, v in ai_draft.items() if k != "draft_id"})
                or provenance.get("annotation_method") != "ai_assisted"
                or provenance.get("original_packet_id") != ai_draft["packet_id"]
                or provenance.get("ai_draft_id") != ai_draft.get("draft_id")
                or packet["policy_version"] != ai_draft["policy_version"]):
            raise ValueError("Assisted review packet and draft provenance differ")
        rows = {r["id"]: r["text_sha256"] for r in ai_draft["labels"]}
        if rows != {c["id"]: c["text_sha256"] for c in packet["cases"]}:
            raise ValueError("Assisted review text differs from the AI draft")
    # Untrusted comments and AI rationales cannot terminate a JSON script element.
    safe_json = json.dumps(packet, ensure_ascii=False).replace("<", "\\u003c").replace("&", "\\u0026")
    safe_ai = json.dumps(ai_draft, ensure_ascii=False).replace("<", "\\u003c").replace("&", "\\u0026")
    return template.replace("__POLICY_GUIDE__", guide).replace("__AI_DRAFT_JSON__", safe_ai).replace("__PACKET_JSON__", safe_json)


def write_packet(packet, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("packet.json", "review.html"):
        if (directory / name).exists():
            raise ValueError("Refusing to overwrite an existing review packet")
    rendered = render_review_html(packet)
    (directory / "packet.json").write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (directory / "review.html").write_text(rendered, encoding="utf-8")
