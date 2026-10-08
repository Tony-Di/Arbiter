"""Behavior regressions from the v1 mechanism audit; these are not new holdouts."""
import json

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from arbiter.classify import ALL_6
from arbiter.classify.schema import ClassifyResult
from arbiter.moderation_policy import ACTION_GUIDE, POLICY_VERSION
from arbiter.product.adjudicator import make_adjudicate_node, make_tools_node, needs_human
from arbiter.product.aggregator import aggregate
from arbiter.product.context import ContextFlags, ground_context
from arbiter.product.graph import build_graph
from arbiter.product.state import initial_state


def _raw(**severity):
    return {c: {"severity": severity.get(c, 0), "reason": "test", "span": None} for c in ALL_6}


@pytest.mark.parametrize("use", ["endorsing", "direct_attack", "none", "unclear"])
def test_quote_presence_cannot_discount_endorsement_or_unknown_intent(use):
    comment = 'I agree with "people like you are disgusting".'
    flags = ground_context(ContextFlags(quotation=True, language_use=use,
        evidence_span="I agree", note="quoted phrase", mitigation_categories=["toxic"]), comment)
    out = aggregate(_raw(toxic=2), flags.model_dump())
    assert out["effective_verdicts"]["toxic"] == 2
    assert out["action"] == "human-review"


@pytest.mark.parametrize("evidence", [None, "", " ", "invented evidence"])
def test_unverifiable_context_evidence_cannot_discount(evidence):
    flags = ground_context(ContextFlags(quotation=True, language_use="condemning",
        evidence_span=evidence, note="condemnation", mitigation_categories=["insult"]), 'They wrote "idiot".')
    assert flags.mitigation_categories == [] and flags.ambiguity


def test_grounded_condemnation_only_changes_named_categories():
    comment = 'Calling someone "idiot" is unacceptable.'
    flags = ground_context(ContextFlags(quotation=True, language_use="condemning",
        evidence_span="is unacceptable", note="opposes the insult", mitigation_categories=["insult"]), comment)
    out = aggregate(_raw(insult=2, toxic=2, threat=2, severe_toxic=2), flags.model_dump())
    assert out["effective_verdicts"] == {c: v["severity"] for c, v in _raw(insult=1, toxic=2, threat=2, severe_toxic=2).items()}


def test_direct_threat_survives_supported_mitigation():
    flags = ContextFlags(language_use="reporting", note="report", evidence_span="report",
                         direct_threat=True, mitigation_categories=["toxic"])
    out = aggregate(_raw(toxic=2, threat=1), flags.model_dump())
    assert out["action"] == "remove" and out["effective_verdicts"]["threat"] == 3


def test_clear_medium_insult_queues_without_calling_adjudicator():
    def classify(model, comment, categories):
        return ClassifyResult(verdicts={c: _raw(insult=2)[c] for c in categories})
    def forbidden(*_):
        raise AssertionError("No context ambiguity; adjudicator must not run")
    graph = build_graph({c: {"model": "fake", "threshold": 1} for c in ALL_6},
        classify_fn=classify, detect_fn=lambda _: ContextFlags(language_use="direct_attack"),
        adjudicate_fn=forbidden, checkpointer=InMemorySaver())
    out = graph.invoke(initial_state("you idiot"), {"configurable": {"thread_id": "ordinary-insult"}})
    assert out["__interrupt__"][0].value["recommended_action"] == "human-review"
    assert out["escalated"] is False


def _decision(**changes):
    return {"action": "allow", "overall_severity": 1, "note": "resolved",
            "confidence": 0.99, "policy_category": "insult", "evidence_span": "you", **changes}


@pytest.mark.parametrize("arguments", [
    "{bad json", "[]", json.dumps(_decision(action="remove", overall_severity=2)),
    json.dumps(_decision(confidence=None)), json.dumps(_decision(confidence=True)),
    json.dumps(_decision(confidence="0.99")), json.dumps(_decision(confidence=1.1)),
    json.dumps(_decision(confidence=float("nan"))), json.dumps(_decision(policy_category="made-up")),
    json.dumps(_decision(evidence_span="not present")), json.dumps(_decision(note=" ")),
    json.dumps({k: v for k, v in _decision().items() if k != "confidence"}),
])
def test_invalid_decision_always_becomes_review(arguments):
    state = {**initial_state("you idiot"), "action": "allow", "overall_severity": 1,
             "context_flags": {"ambiguity": True}, "effective_verdicts": {"insult": 1}}
    msg = {"role": "assistant", "tool_calls": [{"id": "1", "function": {
        "name": "submit_decision", "arguments": arguments}}]}
    out = make_adjudicate_node(lambda *_: msg)(state)
    assert out["action"] == "human-review"
    assert needs_human(out) == "human"


def test_mixed_submit_and_query_is_not_accepted_as_a_final_ruling():
    state = {**initial_state("you idiot"), "action": "human-review", "overall_severity": 2,
             "context_flags": {}, "effective_verdicts": {"insult": 2}}
    msg = {"role": "assistant", "tool_calls": [
        {"id": "1", "function": {"name": "submit_decision", "arguments": json.dumps(_decision())}},
        {"id": "2", "function": {"name": "get_policy", "arguments": '{"category":"insult"}'}}]}
    assert make_adjudicate_node(lambda *_: msg)(state)["action"] == "human-review"


def test_malformed_query_receives_tool_error_and_preserves_call_id():
    state = {"adj_messages": [{"role": "assistant", "tool_calls": [{"id": "bad-json",
        "function": {"name": "get_policy", "arguments": "{"}}]}]}
    reply = make_tools_node(None)(state)["adj_messages"][-1]
    assert reply["tool_call_id"] == "bad-json" and "Invalid tool arguments" in reply["content"]


def test_shared_policy_reaches_both_model_roles_and_audit():
    from arbiter.classify.prompt import build_prompt
    from arbiter.moderation_policy import CATEGORY_RULES
    from arbiter.product.context import build_context_prompt
    from arbiter.product.policy import get_policy
    assert ACTION_GUIDE in build_context_prompt("x")
    assert ACTION_GUIDE in get_policy("insult")
    assert initial_state("x")["audit"]["policy_version"] == POLICY_VERSION
    for category in ALL_6:
        assert CATEGORY_RULES[category] in build_prompt("x", [category])
        assert CATEGORY_RULES[category] in get_policy(category)
