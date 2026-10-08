import json

import pytest

from arbiter.eval.review_packets import make_packet, render_review_html, validate_review_export, write_packet
from arbiter.moderation_policy import ACTION_GUIDE, CATEGORY_RULES


def packet_and_export():
    packet = make_packet([{"id": "a", "text": "civil disagreement", "gold_action": "remove",
                           "rationale": "old model answer", "predictions": {"model": "remove"}}], "test")
    exported = {"packet_id": packet["packet_id"], "policy_version": packet["policy_version"],
        "source": "human_review", "attested_human_review": True, "reviewer": "reviewer-1",
        "labels": [{"id": "a", "text_sha256": packet["cases"][0]["text_sha256"],
                    "gold_action": "allow", "gold_severity": 0, "gold_categories": [],
                    "rationale": "No targeted harm", "reviewed_at": "2026-09-22T12:00:00Z"}]}
    return packet, exported


def test_blind_packet_excludes_answers_and_predictions():
    packet, _ = packet_and_export()
    dumped = json.dumps(packet)
    assert "gold_action" not in dumped and "old model answer" not in dumped and "predictions" not in dumped


def test_human_export_retains_provenance_and_original_text():
    packet, exported = packet_and_export()
    accepted = validate_review_export(packet, exported, require_complete=True)
    assert accepted[0]["text"] == "civil disagreement"
    assert accepted[0]["annotation_source"] == "human_review"
    assert accepted[0]["reviewer"] == "reviewer-1"


def test_modified_packet_cannot_silently_change_reviewed_text():
    packet, exported = packet_and_export()
    packet["cases"][0]["text"] = "modified"
    with pytest.raises(ValueError, match="modified"):
        validate_review_export(packet, exported)


@pytest.mark.parametrize("field,value", [("packet_id", "different"), ("source", "assistant"),
    ("attested_human_review", False), ("reviewer", ""), ("policy_version", "old")])
def test_reject_unattested_or_mismatched_exports(field, value):
    packet, exported = packet_and_export()
    exported[field] = value
    with pytest.raises(ValueError):
        validate_review_export(packet, exported)


@pytest.mark.parametrize("field,value", [("id", "unknown"), ("text_sha256", "edited"),
    ("gold_action", "remove"), ("gold_severity", True), ("gold_categories", ["toxic"]),
    ("gold_categories", ["invented"]), ("rationale", " "), ("reviewed_at", "no-date")])
def test_reject_invalid_annotation_rows(field, value):
    packet, exported = packet_and_export()
    exported["labels"][0][field] = value
    with pytest.raises(ValueError):
        validate_review_export(packet, exported)


def test_duplicate_or_incomplete_reviews_cannot_be_promoted():
    packet, exported = packet_and_export()
    exported["labels"] *= 2
    with pytest.raises(ValueError):
        validate_review_export(packet, exported)
    packet = make_packet([{"id": "a", "text": "civil disagreement"}, {"id": "b", "text": "other"}], "test")
    exported["labels"] = exported["labels"][:1]
    exported["packet_id"] = packet["packet_id"]
    assert len(validate_review_export(packet, exported)) == 1
    with pytest.raises(ValueError, match="incomplete"):
        validate_review_export(packet, exported, require_complete=True)


def test_review_html_escapes_untrusted_script_content_and_refuses_overwrite(tmp_path):
    packet = make_packet([{"id": "a", "text": '</script><script>alert("x")</script>'}], "test")
    write_packet(packet, tmp_path)
    html = (tmp_path / "review.html").read_text(encoding="utf-8")
    assert '</script><script>alert("x")' not in html
    assert "\\u003c/script>" in html
    with pytest.raises(ValueError):
        write_packet(packet, tmp_path)


def test_annotation_guide_uses_shared_policy_and_refuses_policy_mismatch():
    import html
    packet, _ = packet_and_export()
    rendered = render_review_html(packet)
    assert html.escape(ACTION_GUIDE) in rendered
    assert all(html.escape(rule) in rendered for rule in CATEGORY_RULES.values())
    packet["policy_version"] = "older-policy"
    with pytest.raises(ValueError, match="different policy"):
        render_review_html(packet)
