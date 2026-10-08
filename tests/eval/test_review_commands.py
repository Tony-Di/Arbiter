"""CLI integration with synthetic fixtures; these are not human benchmark labels."""
import json
from pathlib import Path
import runpy
import sys

import pytest

from arbiter.eval.review_packets import make_packet


ROOT = Path(__file__).resolve().parents[2]


def fixture_files(tmp_path):
    packet = make_packet([{"id": "a", "text": "Synthetic input A"},
                          {"id": "b", "text": "Synthetic input B"}], "unit test only")
    export = {"packet_id": packet["packet_id"], "policy_version": packet["policy_version"],
              "source": "human_review", "attested_human_review": True, "reviewer": "test-fixture",
              "labels": [{"id": c["id"], "text_sha256": c["text_sha256"], "gold_action": "allow",
                          "gold_severity": 0, "gold_categories": [], "rationale": "Synthetic test expectation",
                          "reviewed_at": "2026-09-22T12:00:00Z"} for c in packet["cases"]]}
    rows = [{"id": c["id"], "kind": "natural", "model": "test-model", "added_latency_ms": 10 + i * 10,
             "baseline_action": "human-review" if i == 0 else "allow",
             "prediction": {"comment": c["text"], "action": "allow" if i == 0 else "remove",
                            "overall_severity": 0 if i == 0 else 3, "escalated": True,
                            "adjudication": {"confidence": .97},
                            "audit": {"policy_version": packet["policy_version"]}}}
            for i, c in enumerate(packet["cases"])]
    files = {key: tmp_path / name for key, name in
             [("packet", "packet.json"), ("reviewed", "export.json"), ("decisions", "decisions.jsonl")]}
    files["packet"].write_text(json.dumps(packet), encoding="utf-8")
    files["reviewed"].write_text(json.dumps(export), encoding="utf-8-sig")
    files["decisions"].write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return files, rows


def run_command(monkeypatch, script, *args):
    path = ROOT / "scripts" / script
    monkeypatch.setattr(sys, "argv", [str(path), *map(str, args)])
    runpy.run_path(str(path), run_name="__main__")


def test_import_keeps_provenance_and_never_overwrites_reviewed_labels(tmp_path, monkeypatch):
    files, _ = fixture_files(tmp_path)
    output = tmp_path / "labels.jsonl"
    args = ["--packet", files["packet"], "--reviewed", files["reviewed"],
            "--output", output, "--require-complete"]
    run_command(monkeypatch, "import_review_labels.py", *args)
    accepted = [json.loads(line) for line in output.read_text().splitlines()]
    assert len(accepted) == 2
    assert all(r["annotation_source"] == "human_review" and r["reviewer"] == "test-fixture" for r in accepted)
    with pytest.raises(FileExistsError):
        run_command(monkeypatch, "import_review_labels.py", *args)


def test_score_actual_paired_rows_counts_corrections_and_regressions(tmp_path, monkeypatch):
    files, _ = fixture_files(tmp_path)
    output = tmp_path / "score.json"
    run_command(monkeypatch, "score_reviewed_adjudication.py",
                *[value for key, path in files.items() for value in ("--" + key, path)],
                "--model", "test-model", "--output", output)
    result = json.loads(output.read_text())
    assert result["paired"]["n_corrected"] == result["paired"]["n_regressed"] == 1
    assert result["paired"]["n_paired"] == 2
    assert result["added_latency_p50_ms"] == 15
    assert result["thresholds"]["label_status"] == "attested_human_review"
    assert result["thresholds"]["threshold_selected"] is None


@pytest.mark.parametrize("problem", ["text", "policy", "duplicate", "missing"])
def test_score_rejects_mismatched_prediction_evidence(tmp_path, monkeypatch, problem):
    files, rows = fixture_files(tmp_path)
    if problem == "text":
        rows[0]["prediction"]["comment"] = "different source"
    elif problem == "policy":
        rows[0]["prediction"]["audit"]["policy_version"] = "other-policy"
    elif problem == "duplicate":
        rows.append(rows[0])
    else:
        rows.pop()
    files["decisions"].write_text("".join(json.dumps(r) + "\n" for r in rows))
    output = tmp_path / "score.json"
    with pytest.raises(ValueError):
        run_command(monkeypatch, "score_reviewed_adjudication.py",
                    *[value for key, path in files.items() for value in ("--" + key, path)],
                    "--model", "test-model", "--output", output)
    assert not output.exists()
