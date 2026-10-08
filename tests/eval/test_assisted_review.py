"""AI proposals must never silently count as independently reviewed human labels."""
import copy
import json
from pathlib import Path
import runpy
import sys

import pytest

from arbiter.eval.review_packets import (
    digest, make_packet, render_review_html, validate_ai_draft, validate_review_export,
)


def packet_and_draft():
    packet = make_packet([{"id": "a", "text": "neutral synthetic comment"}], "unit test")
    draft = {"packet_id": packet["packet_id"], "policy_version": packet["policy_version"],
             "source": "ai_preannotation", "attested_human_review": False, "annotator": "synthetic AI",
             "labels": [{"id": "a", "text_sha256": packet["cases"][0]["text_sha256"],
                         "action": "allow", "severity": 0, "categories": [], "evidence_span": "neutral",
                         "rationale": "Synthetic rationale", "needs_attention": False, "uncertainty": ""}]}
    return packet, draft


def assisted_packet(packet, draft):
    return make_packet(packet["cases"], "assisted unit test", provenance={
        "annotation_method": "ai_assisted", "original_packet_id": packet["packet_id"],
        "ai_draft_id": draft["draft_id"]})


def test_complete_ai_draft_cannot_be_imported_as_human_labels():
    packet, draft = packet_and_draft()
    assert validate_ai_draft(packet, draft) == draft
    with pytest.raises(ValueError, match="human review attestation"):
        validate_review_export(packet, draft, require_complete=True)


@pytest.mark.parametrize("problem", ["attestation", "packet", "evidence", "severity", "hash", "duplicate", "missing"])
def test_ai_notes_reject_wrong_provenance_or_unsupported_labels(problem):
    packet, draft = packet_and_draft()
    row = draft["labels"][0]
    if problem == "attestation":
        draft["attested_human_review"] = True
    elif problem == "packet":
        draft["packet_id"] = "different"
    elif problem == "evidence":
        row["evidence_span"] = "fabricated quotation"
    elif problem == "severity":
        row["severity"] = 3
    elif problem == "hash":
        row["text_sha256"] = "different"
    elif problem == "duplicate":
        draft["labels"].append(copy.deepcopy(row))
    else:
        draft["labels"] = []
    with pytest.raises(ValueError):
        validate_ai_draft(packet, draft)


def test_assisted_packet_retains_method_even_if_export_omits_ai_fields():
    packet, draft = packet_and_draft()
    draft["draft_id"] = digest(draft)
    assisted = assisted_packet(packet, draft)
    assert assisted["packet_id"] != packet["packet_id"]
    exported = {"packet_id": assisted["packet_id"], "policy_version": assisted["policy_version"],
                "source": "human_review", "attested_human_review": True, "reviewer": "unit-test-fixture",
                "labels": [{"id": "a", "text_sha256": packet["cases"][0]["text_sha256"],
                            "gold_action": "allow", "gold_severity": 0, "gold_categories": [],
                            "rationale": "Synthetic review", "reviewed_at": "2026-09-22T12:00:00Z"}]}
    normalized = validate_review_export(assisted, exported, require_complete=True)
    assert normalized[0]["annotation_method"] == "ai_assisted"
    assert normalized[0]["ai_draft_id"] == draft["draft_id"]
    with pytest.raises(ValueError, match="different packet"):
        validate_review_export(packet, exported)


def test_assisted_render_requires_matching_draft_and_escapes_rationale():
    packet, draft = packet_and_draft()
    draft["labels"][0]["rationale"] = '</script><script>alert("x")</script>'
    draft["draft_id"] = digest(draft)
    assisted = assisted_packet(packet, draft)
    page = render_review_html(assisted, ai_draft=draft)
    assert '</script><script>alert("x")' not in page
    assert "\\u003c/script>" in page
    with pytest.raises(ValueError, match="requires its AI draft"):
        render_review_html(assisted)
    draft["labels"][0]["action"] = "remove"
    with pytest.raises(ValueError, match="provenance differ"):
        render_review_html(assisted, ai_draft=draft)


def test_prepare_command_preserves_original_and_creates_zero_human_labels(tmp_path, monkeypatch):
    packet, draft = packet_and_draft()
    packet_path, notes_path, out = tmp_path / "packet.json", tmp_path / "notes.json", tmp_path / "assisted"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    notes_path.write_text(json.dumps(draft), encoding="utf-8")
    original_bytes = packet_path.read_bytes()
    script = Path(__file__).resolve().parents[2] / "scripts" / "prepare_assisted_review.py"
    monkeypatch.setattr(sys, "argv", [str(script), "--packet", str(packet_path),
                        "--notes", str(notes_path), "--output-dir", str(out)])
    runpy.run_path(str(script), run_name="__main__")
    summary = json.loads((out / "summary.json").read_text())
    assert summary["n_ai_labels"] == 1 and summary["human_labels_completed"] == 0
    assert summary["not_human_gold"] is True
    assert packet_path.read_bytes() == original_bytes
    generated = json.loads((out / "ai-preannotations.json").read_text())
    validate_ai_draft(packet, generated)
    with pytest.raises(ValueError, match="overwrite"):
        runpy.run_path(str(script), run_name="__main__")
