import copy
import json

import pytest

from arbiter.eval.adjudication_eval import adjudicate_snapshot, gated_action, threshold_sweep
from arbiter.product.state import initial_state


def state():
    return {**initial_state("you idiot"), "action": "human-review", "overall_severity": 2,
            "context_flags": {"ambiguity": True}, "effective_verdicts": {"insult": 2}}


def submit(confidence=0.9):
    return {"role": "assistant", "tool_calls": [{"id": "submit", "function": {
        "name": "submit_decision", "arguments": json.dumps({"action": "allow", "overall_severity": 1,
        "note": "test", "policy_category": "insult", "evidence_span": "you", "confidence": confidence})}}]}


def test_paired_evidence_is_preserved_and_api_attempts_include_retries():
    original = state()
    preserved = copy.deepcopy(original)
    calls = []
    def fn(*_):
        calls.append(1)
        if len(calls) == 1:
            raise TimeoutError()
        return submit()
    result = adjudicate_snapshot(original, fn)
    assert original == preserved
    assert result["baseline_action"] == "human-review"
    assert result["prediction"]["action"] == "human-review"
    assert result["prediction"]["ai_recommended_action"] == "allow"
    assert result["api_attempts"] == 2


def test_natural_clear_case_skips_calls_but_explicit_component_probe_runs():
    original = state()
    original["context_flags"] = {}
    calls = []
    def fn(*_):
        calls.append(1)
        return submit()
    assert adjudicate_snapshot(original, fn)["api_attempts"] == 0
    component = adjudicate_snapshot(original, fn, force=True)
    assert component["forced_component_call"] is True
    assert component["natural_route"] == "human"
    assert len(calls) == 1


def test_live_loop_executes_policy_tool_and_records_trace():
    calls = []
    def fn(messages, tools):
        calls.append(messages)
        if len(calls) == 1:
            return {"role": "assistant", "tool_calls": [{"id": "p", "function": {
                "name": "get_policy", "arguments": '{"category":"insult"}'}}]}
        assert messages[-1]["role"] == "tool" and messages[-1]["tool_call_id"] == "p"
        return submit(0.97)
    result = adjudicate_snapshot(state(), fn)
    assert result["prediction"]["action"] == "allow"
    assert result["prediction"]["adjudication"]["policies_consulted"] == ["insult"]


@pytest.mark.parametrize("confidence", [None, True, "0.99", float("nan"), float("inf"), -1, 2])
def test_invalid_confidence_cannot_auto_decide_in_sweep(confidence):
    assert gated_action({"action": "allow", "escalated": True,
                         "adjudication": {"confidence": confidence}}, 0.0) == "human-review"


def test_threshold_changes_only_escalated_decisions_and_reports_tradeoff():
    cases = [{"id": "a", "gold_action": "allow"}, {"id": "b", "gold_action": "human-review"}]
    rows = [{"case_id": "a", "action": "human-review", "escalated": True,
             "ai_recommended_action": "allow", "adjudication": {"confidence": .90}},
            {"case_id": "b", "action": "human-review", "escalated": True,
             "ai_recommended_action": "remove", "adjudication": {"confidence": .90}}]
    result = threshold_sweep(cases, rows, thresholds=(.9, .95))
    assert result["threshold_selected"] is None
    low, high = result["rows"]
    assert low["n_escalated_auto"] == 2 and high["n_escalated_auto"] == 0
    assert low["paired_vs_0.95"]["n_corrected"] == low["paired_vs_0.95"]["n_regressed"] == 1
    assert gated_action({"action": "remove", "escalated": False}, 1) == "remove"
    assert threshold_sweep(None, rows)["rows"][0]["quality_metrics"] is None


def test_fallback_is_not_released_by_lower_threshold():
    assert gated_action({"action": "human-review", "escalated": True,
        "ai_recommended_action": "allow", "adjudication": {"confidence": .99, "status": "needs_review"}}, .5) == "human-review"
