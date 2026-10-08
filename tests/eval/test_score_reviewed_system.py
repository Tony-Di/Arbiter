"""Offline rescoring of saved ablation predictions; synthetic fixtures, not benchmark labels."""
import csv
import json
from pathlib import Path
import runpy
import sys

import pytest

from arbiter.eval.review_packets import digest, make_packet
from arbiter.eval.system_runner import text_fingerprint


ROOT = Path(__file__).resolve().parents[2]
VARIANTS = ["single_call", "policy_agent"]
CASES = [{"id": "a", "text": "Synthetic input A", "split": "previously_seen_holdout"},
         {"id": "b", "text": "Synthetic input B", "split": "previously_seen_stress"}]


def fixture_files(tmp_path):
    original = make_packet(CASES, "unit test only")
    draft = {"source": "ai_preannotation", "annotator": "test-fixture", "attested_human_review": False,
             "policy_version": original["policy_version"], "packet_id": original["packet_id"],
             "labels": [{"id": c["id"], "text_sha256": c["text_sha256"], "action": "allow", "severity": 0,
                         "categories": [], "evidence_span": c["text"], "rationale": "AI says allow " + c["id"],
                         "needs_attention": False, "uncertainty": ""} for c in original["cases"]]}
    draft["draft_id"] = digest(draft)
    packet = make_packet(CASES, "assisted unit test", provenance={
        "annotation_method": "ai_assisted", "original_packet_id": original["packet_id"],
        "ai_draft_id": draft["draft_id"]})
    by_id = {c["id"]: c for c in packet["cases"]}
    labels = [{"id": "a", "gold_action": "allow", "gold_severity": 0, "gold_categories": [],
               "rationale": "AI says allow a"},
              {"id": "b", "gold_action": "human-review", "gold_severity": 2, "gold_categories": ["insult"],
               "rationale": "Reviewer: targeted insult"}]
    export = {"packet_id": packet["packet_id"], "policy_version": packet["policy_version"],
              "source": "human_review", "attested_human_review": True, "reviewer": "test-fixture",
              "labels": [{**row, "text_sha256": by_id[row["id"]]["text_sha256"],
                          "reviewed_at": "2026-09-22T12:00:00Z"} for row in labels]}
    experiment, results = tmp_path / "experiment", tmp_path / "results"
    experiment.mkdir()
    results.mkdir()
    reports = {}
    for stage, case in [("holdout", CASES[0]), ("stress", CASES[1])]:
        reference = {"id": case["id"], "text": case["text"], "gold_action": "allow",
                     "gold_categories": [], "gold_severity": 0, "rationale": "old reference"}
        (experiment / f"{stage}.jsonl").write_text(json.dumps(reference) + "\n", encoding="utf-8")
        reports[stage] = {"config_fingerprint": "fp-" + stage, "cache_version": "2", "variants": VARIANTS,
                          "run_metadata": {"finished_at_utc": "2026-09-22T01:00:00+00:00"}}
        (results / f"{stage}.json").write_text(json.dumps(reports[stage]), encoding="utf-8")
    actions = {("a", "single_call"): "allow", ("a", "policy_agent"): "allow",
               ("b", "single_call"): "allow", ("b", "policy_agent"): "human-review"}
    stage_of = {"a": "holdout", "b": "stress"}
    predictions = [{"case_id": cid, "variant": variant, "action": action, "latency_ms": 10.0,
                    "text_sha256": text_fingerprint(by_id[cid]["text"]),
                    "config_fingerprint": reports[stage_of[cid]]["config_fingerprint"], "cache_version": "2"}
                   for (cid, variant), action in actions.items()]
    files = {"packet": tmp_path / "packet.json", "reviewed": tmp_path / "export.json",
             "ai-draft": tmp_path / "ai-preannotations.json", "cache": tmp_path / "cache.jsonl",
             "experiment-dir": experiment, "results-dir": results}
    files["packet"].write_text(json.dumps(packet), encoding="utf-8")
    files["ai-draft"].write_text(json.dumps(draft), encoding="utf-8")
    write_export(files, export)
    write_cache(files, predictions)
    return files, export, predictions


def write_export(files, export):
    files["reviewed"].write_text(json.dumps(export), encoding="utf-8-sig")


def write_cache(files, predictions):
    files["cache"].write_text("".join(json.dumps(p) + "\n" for p in predictions), encoding="utf-8")


def run_score(monkeypatch, files, output):
    path = ROOT / "scripts" / "score_reviewed_system.py"
    args = [value for key, file in files.items() for value in ("--" + key, file)]
    monkeypatch.setattr(sys, "argv", [str(path), *map(str, args), "--output-dir", str(output)])
    runpy.run_path(str(path), run_name="__main__")


def test_rescoring_uses_reviewed_labels_and_records_provenance(tmp_path, monkeypatch):
    files, _, _ = fixture_files(tmp_path)
    output = tmp_path / "out"
    run_score(monkeypatch, files, output)
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert report["n_cases"] == 2 and report["variants"] == VARIANTS
    assert report["labels"]["annotation_method"] == "ai_assisted"
    assert report["labels"]["accepted_ai_draft_unchanged"] == 1
    assert report["labels"]["changed_from_ai_draft_ids"] == ["b"]
    assert report["old_reference"]["overturned_ids"] == ["b"]
    assert report["metrics"]["single_call"]["unsafe_auto_allow_count"] == 1
    assert report["metrics"]["policy_agent"]["unsafe_auto_allow_count"] == 0
    assert report["paired_comparisons"][0]["corrected_ids"] == ["b"]
    assert report["predictions"]["stages"]["stress"]["config_fingerprint"] == "fp-stress"
    with (output / "cases.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [(r["id"], r["stage"], r["human_action"], r["ai_draft_action"], r["old_reference_action"],
             r["single_call"], r["policy_agent"]) for r in rows] == [
        ("a", "holdout", "allow", "allow", "allow", "allow", "allow"),
        ("b", "stress", "human-review", "allow", "allow", "allow", "human-review")]
    assert (output / "REPORT.zh-CN.md").exists()


def test_rejects_label_edit_that_keeps_the_ai_rationale(tmp_path, monkeypatch):
    files, export, _ = fixture_files(tmp_path)
    export["labels"][1]["rationale"] = "AI says allow b"
    write_export(files, export)
    with pytest.raises(ValueError, match="rationale"):
        run_score(monkeypatch, files, tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("problem", ["missing", "fingerprint", "text"])
def test_requires_exact_saved_prediction_for_every_case_and_variant(tmp_path, monkeypatch, problem):
    files, _, predictions = fixture_files(tmp_path)
    if problem == "missing":
        predictions.pop()
    elif problem == "fingerprint":
        predictions[-1]["config_fingerprint"] = "some-other-run"
    else:
        predictions[-1]["text_sha256"] = text_fingerprint("different text")
    write_cache(files, predictions)
    with pytest.raises(ValueError, match="prediction"):
        run_score(monkeypatch, files, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_rejects_reviewed_text_that_differs_from_the_frozen_experiment(tmp_path, monkeypatch):
    files, _, _ = fixture_files(tmp_path)
    stress = files["experiment-dir"] / "stress.jsonl"
    row = json.loads(stress.read_text(encoding="utf-8"))
    stress.write_text(json.dumps({**row, "text": "Edited input B"}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="text"):
        run_score(monkeypatch, files, tmp_path / "out")


def test_never_overwrites_an_existing_report(tmp_path, monkeypatch):
    files, _, _ = fixture_files(tmp_path)
    output = tmp_path / "out"
    run_score(monkeypatch, files, output)
    with pytest.raises(FileExistsError):
        run_score(monkeypatch, files, output)
