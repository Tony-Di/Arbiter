import pytest

from arbiter.eval.system_score import percentile, score_predictions


def _case(case_id, action, **extra):
    return {"id": case_id, "comment": case_id, "gold_action": action, **extra}


def test_scores_action_safety_workload_and_latency_metrics():
    cases = [
        _case("a", "allow", gold_high_risk=False),
        _case("b", "human-review", gold_high_risk=False),
        _case("c", "remove", gold_categories=["threat"]),
        _case("d", "remove", gold_severity=3),
    ]
    predictions = [
        {"case_id": "a", "action": "allow", "latency_ms": 10},
        {"case_id": "b", "action": "allow", "latency_ms": 20},
        {"case_id": "c", "action": "human-review", "latency_ms": 30},
        {"case_id": "d", "action": "remove", "latency_ms": 40},
    ]

    metrics = score_predictions(cases, predictions)

    assert metrics["action_macro_f1"] == pytest.approx(4 / 9)
    assert metrics["unsafe_auto_allow_rate"] == pytest.approx(1 / 3)
    assert metrics["over_remove_rate"] == 0
    assert metrics["human_review_rate"] == pytest.approx(1 / 4)
    assert metrics["auto_decision_accuracy"] == pytest.approx(2 / 3)
    assert metrics["high_risk_recall"] == 1
    assert metrics["p50_latency_ms"] == 25
    assert metrics["p95_latency_ms"] == pytest.approx(38.5)
    assert metrics["coverage"] == 1
    assert metrics["n_auto_decisions"] == 3
    assert metrics["n_high_risk"] == 2


def test_partial_predictions_score_completed_rows_and_report_coverage():
    cases = [_case("a", "allow"), _case("b", "remove")]
    metrics = score_predictions(cases, {"a": "allow"})

    assert metrics["n_cases"] == 2
    assert metrics["n_scored"] == 1
    assert metrics["coverage"] == 0.5
    assert metrics["p50_latency_ms"] is None
    assert metrics["p95_latency_ms"] is None


def test_explicit_high_risk_false_overrides_remove_inference():
    cases = [_case("a", "remove", gold_high_risk=False)]
    metrics = score_predictions(cases, [{"case_id": "a", "action": "allow"}])
    assert metrics["n_high_risk"] == 0
    assert metrics["high_risk_recall"] == 0


def test_invalid_prediction_action_is_rejected():
    with pytest.raises(ValueError, match="unsupported action"):
        score_predictions(
            [_case("a", "allow")],
            [{"case_id": "a", "action": "maybe"}],
        )


def test_percentile_handles_singletons_and_validates_quantile():
    assert percentile([7], 0.95) == 7
    assert percentile([], 0.5) is None
    with pytest.raises(ValueError, match="between 0 and 1"):
        percentile([1], 1.1)
def test_paired_comparison_excludes_missing_and_tracks_both_directions():
    from arbiter.eval.system_score import compare_variants
    cases = [{"id": key, "gold_action": "allow"} for key in "abcd"]
    predictions = [
        {"case_id": "a", "variant": "before", "action": "remove"},
        {"case_id": "a", "variant": "after", "action": "allow"},
        {"case_id": "b", "variant": "before", "action": "allow"},
        {"case_id": "b", "variant": "after", "action": "human-review"},
        {"case_id": "c", "variant": "before", "action": "allow"},
        {"case_id": "c", "variant": "after", "action": "allow"},
        {"case_id": "d", "variant": "after", "action": "allow"},
    ]
    result = compare_variants(cases, predictions, "before", "after")
    assert result["n_paired"] == 3
    assert result["corrected_ids"] == ["a"]
    assert result["regressed_ids"] == ["b"]
