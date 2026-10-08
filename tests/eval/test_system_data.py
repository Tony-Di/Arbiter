import csv
import json

import pytest

from arbiter.eval.system_data import (
    ANNOTATION_FIELDS,
    DATASET_ID,
    InsufficientSamplesError,
    SystemEvalDataError,
    load_annotations,
    sample_civil_comments,
    sample_high_risk_civil_comments,
    validate_annotation,
    write_candidate_files,
)


def _row(index: int, toxicity: float, **scores: float) -> dict:
    row = {
        "text": f"Civil comment number {index} with enough text for sampling.",
        "toxicity": toxicity,
        "severe_toxicity": 0.0,
        "obscene": 0.0,
        "threat": 0.0,
        "insult": 0.0,
        "identity_attack": 0.0,
    }
    row.update(scores)
    return row


def _rows() -> list[dict]:
    rows = []
    for index in range(20):
        rows.append(_row(index, 0.05))
    for index in range(20, 50):
        rows.append(_row(index, 0.5, insult=0.6))
    for index in range(50, 70):
        rows.append(_row(index, 0.95, severe_toxicity=0.8))
    return rows


def test_streaming_sampler_meets_quotas_and_maps_source_scores():
    sample = sample_civil_comments(_rows(), safe=3, gray=4, harmful=2, seed=7)
    assert [row["slice"] for row in sample].count("safe") == 3
    assert [row["slice"] for row in sample].count("gray") == 4
    assert [row["slice"] for row in sample].count("harmful") == 2
    gray = next(row for row in sample if row["slice"] == "gray")
    assert gray["source_scores"]["insult"] == 0.6
    assert gray["source"] == DATASET_ID


def test_sampler_preserves_public_source_id_when_available():
    row = _row(1, 0.05)
    row["id"] = "public-123"
    sample = sample_civil_comments([row], safe=1, gray=0, harmful=0, seed=7)
    assert sample[0]["id"] == "civil-comments-public-123"


def test_sampler_is_reproducible_and_seed_changes_reservoir():
    first = sample_civil_comments(_rows(), safe=4, gray=4, harmful=4, seed=9)
    repeat = sample_civil_comments(iter(_rows()), safe=4, gray=4, harmful=4, seed=9)
    changed = sample_civil_comments(_rows(), safe=4, gray=4, harmful=4, seed=10)
    assert first == repeat
    assert [row["id"] for row in first] != [row["id"] for row in changed]


def test_sampler_deduplicates_and_reports_shortfall():
    duplicate_rows = [_row(1, 0.05), _row(1, 0.05)]
    with pytest.raises(InsufficientSamplesError, match="safe=1"):
        sample_civil_comments(duplicate_rows, safe=2, gray=0, harmful=0, seed=1)


def test_high_risk_sampler_uses_priority_and_excludes_existing_ids():
    excluded = _row(1, 0.95, threat=0.9)
    excluded["id"] = "already-annotated"
    overlap = _row(
        2,
        0.95,
        threat=0.9,
        identity_attack=0.9,
        severe_toxicity=0.9,
    )
    overlap["id"] = "overlap"
    identity = _row(3, 0.95, identity_attack=0.9)
    identity["id"] = "identity"
    severe = _row(4, 0.95, severe_toxicity=0.3)
    severe["id"] = "severe"

    sample = sample_high_risk_civil_comments(
        [excluded, overlap, identity, severe],
        threat=1,
        identity_hate=1,
        severe_toxic=1,
        exclude_ids={"civil-comments-already-annotated"},
    )

    assert [row["id"] for row in sample] == [
        "civil-comments-overlap",
        "civil-comments-identity",
        "civil-comments-severe",
    ]
    assert len({row["id"] for row in sample}) == 3


def test_high_risk_sampler_is_reproducible_and_seeded_per_stratum():
    rows = [_row(index, 0.95, threat=0.8) for index in range(30)]
    first = sample_high_risk_civil_comments(
        rows, threat=5, identity_hate=0, severe_toxic=0, seed=9
    )
    repeat = sample_high_risk_civil_comments(
        iter(rows), threat=5, identity_hate=0, severe_toxic=0, seed=9
    )
    changed = sample_high_risk_civil_comments(
        rows, threat=5, identity_hate=0, severe_toxic=0, seed=10
    )
    assert first == repeat
    assert [row["id"] for row in first] != [row["id"] for row in changed]


def test_high_risk_sampler_validates_thresholds_and_reports_shortfall():
    with pytest.raises(SystemEvalDataError, match="threat_min"):
        sample_high_risk_civil_comments(
            [_row(1, 0.95, threat=0.9)],
            threat=1,
            identity_hate=0,
            severe_toxic=0,
            threat_min=1.1,
        )
    with pytest.raises(InsufficientSamplesError, match="identity_hate=1"):
        sample_high_risk_civil_comments(
            [_row(1, 0.95, threat=0.9)],
            threat=1,
            identity_hate=1,
            severe_toxic=0,
        )


def test_writers_create_jsonl_and_blank_annotation_template(tmp_path):
    sample = sample_civil_comments(_rows(), safe=1, gray=1, harmful=1, seed=2)
    jsonl_path, csv_path = write_candidate_files(sample, tmp_path)

    payloads = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines()]
    assert len(payloads) == 3
    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert tuple(rows[0]) == ANNOTATION_FIELDS
    assert all(row["gold_action"] == row["gold_severity"] == "" for row in rows)


def _valid_annotation(**overrides: str) -> dict[str, str]:
    row = {
        "id": "case-1",
        "text": "A direct and credible threat towards another person.",
        "source": DATASET_ID,
        "source_score": "0.95",
        "gold_action": "remove",
        "gold_categories": "toxic;threat",
        "gold_severity": "3",
        "slice": "harmful",
        "rationale": "The speaker directly threatens physical harm.",
    }
    row.update(overrides)
    return row


def test_validate_annotation_normalizes_typed_values():
    result = validate_annotation(_valid_annotation(gold_categories="threat;toxic"))
    assert result["gold_categories"] == ["toxic", "threat"]
    assert result["gold_severity"] == 3
    assert result["source_score"] == 0.95


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"gold_action": ""}, "incomplete"),
        ({"gold_categories": "violence"}, "unknown gold_categories"),
        ({"gold_severity": "2"}, "requires gold_severity 3"),
        ({"slice": "gray"}, "slice does not match"),
    ],
)
def test_validate_annotation_rejects_invalid_or_incomplete_rows(change, message):
    with pytest.raises(SystemEvalDataError, match=message):
        validate_annotation(_valid_annotation(**change))


def test_load_annotations_requires_completed_unique_rows(tmp_path):
    path = tmp_path / "annotation.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ANNOTATION_FIELDS)
        writer.writeheader()
        writer.writerow(_valid_annotation())
    loaded = load_annotations(path)
    assert loaded[0]["gold_action"] == "remove"

    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ANNOTATION_FIELDS)
        writer.writerow(_valid_annotation())
    with pytest.raises(SystemEvalDataError, match="duplicate id"):
        load_annotations(path)
