"""Tests for the tool-using adjudicator (escalation spec §4/§5/§9). Zero network.

All model calls are injected fakes: a fake adjudicate_fn(messages, tools) returns an
API-shaped assistant message, so the whole loop runs offline.
"""
import json

from arbiter.classify import ALL_6
from arbiter.classify.schema import ClassifyResult, Severity
from arbiter.product.adjudicator import (
    MAX_TOOL_STEPS,
    after_adjudicate,
    make_adjudicate_node,
    make_tools_node,
    should_escalate,
)
from arbiter.product.context import ContextFlags
from arbiter.product.graph import build_graph
from arbiter.product.state import initial_state


# --- fakes / helpers --------------------------------------------------------------
def _getpolicy_msg(category, call_id="c1"):
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": call_id, "type": "function",
         "function": {"name": "get_policy", "arguments": json.dumps({"category": category})}}]}


def _submit_msg(action, sev, note, call_id="c2", confidence=0.9):
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": call_id, "type": "function",
         "function": {"name": "submit_decision",
                      "arguments": json.dumps({"action": action, "overall_severity": sev,
                                               "note": note, "confidence": confidence})}}]}


def _searchprec_msg(query, call_id="c3"):
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": call_id, "type": "function",
         "function": {"name": "search_precedents", "arguments": json.dumps({"query": query})}}]}


def _gray_state(comment="People like you don't belong here."):
    s = initial_state(comment)
    s.update({"action": "human-review", "overall_severity": 2,
              "effective_verdicts": {c: 0 for c in ALL_6},
              "context_flags": {"ambiguity": True}})
    return s


def _fake_classify(model, comment, categories):
    cat = categories[0]
    sev = Severity.medium if cat == "insult" else Severity.none
    return ClassifyResult(verdicts={cat: {"severity": sev, "reason": "r", "span": None}})


# --- should_escalate (trigger) ----------------------------------------------------
def test_should_escalate_on_human_review():
    assert should_escalate({"action": "human-review", "context_flags": {}}) == "escalate"


def test_should_escalate_on_ambiguity():
    assert should_escalate({"action": "allow", "context_flags": {"ambiguity": True}}) == "escalate"


def test_should_not_escalate_clean_case():
    assert should_escalate({"action": "allow", "context_flags": {}}) == "done"


# --- after_adjudicate (loop routing) ----------------------------------------------
def test_after_routes_tool_for_getpolicy_under_cap():
    assert after_adjudicate({"adj_messages": [_getpolicy_msg("toxic")], "adj_steps": 1}) == "tool"


def test_after_routes_done_for_submit():
    assert after_adjudicate({"adj_messages": [_submit_msg("allow", 1, "ok")], "adj_steps": 1}) == "done"


def test_after_routes_done_at_step_cap():
    assert after_adjudicate({"adj_messages": [_getpolicy_msg("toxic")], "adj_steps": MAX_TOOL_STEPS}) == "done"


# --- the tools node (get_policy + search_precedents; HITL spec 2026-06-09 §6) ------
class FakeStore:
    def __init__(self, hits=None, fail=False):
        self.hits, self.fail = hits or [], fail

    def search(self, query, k=3):
        if self.fail:
            raise RuntimeError("embed down")
        return self.hits


def test_tools_node_appends_tool_message_with_matching_id():
    state = _gray_state()
    state["adj_messages"] = [_getpolicy_msg("identity_hate", call_id="abc")]
    upd = make_tools_node(None)(state)
    last = upd["adj_messages"][-1]
    assert last["role"] == "tool"
    assert last["tool_call_id"] == "abc"
    assert "protected" in last["content"].lower()


def test_tools_node_answers_every_batched_call():
    # DeepSeek batches multiple get_policy in one assistant message -> all must be answered
    state = _gray_state()
    state["adj_messages"] = [{"role": "assistant", "content": "", "tool_calls": [
        {"id": "a", "type": "function",
         "function": {"name": "get_policy", "arguments": json.dumps({"category": "toxic"})}},
        {"id": "b", "type": "function",
         "function": {"name": "get_policy", "arguments": json.dumps({"category": "insult"})}},
    ]}]
    upd = make_tools_node(None)(state)
    tool_msgs = upd["adj_messages"][-2:]
    assert [m["tool_call_id"] for m in tool_msgs] == ["a", "b"]
    assert all(m["role"] == "tool" for m in tool_msgs)


def test_tools_node_answers_mixed_batch_one_reply_per_call_id():
    state = _gray_state()
    state["adj_messages"] = [{"role": "assistant", "content": "", "tool_calls": [
        {"id": "a", "type": "function",
         "function": {"name": "get_policy", "arguments": json.dumps({"category": "insult"})}},
        {"id": "b", "type": "function",
         "function": {"name": "search_precedents", "arguments": json.dumps({"query": "you idiot"})}},
    ]}]
    hits = [{"comment_text": "u r dumb", "action": "remove",
             "overall_severity": 2, "note": "direct insult", "source": "human"}]
    upd = make_tools_node(FakeStore(hits))(state)
    tool_msgs = upd["adj_messages"][-2:]
    assert [m["tool_call_id"] for m in tool_msgs] == ["a", "b"]
    assert all(m["role"] == "tool" for m in tool_msgs)
    assert "<precedent>" in tool_msgs[1]["content"]


def test_tools_node_search_failure_is_a_string_not_an_exception():
    state = _gray_state()
    state["adj_messages"] = [_searchprec_msg("x")]
    upd = make_tools_node(FakeStore(fail=True))(state)
    assert upd["adj_messages"][-1]["content"] == "precedent search unavailable"


def test_tools_node_without_store_degrades_the_same_way():
    state = _gray_state()
    state["adj_messages"] = [_searchprec_msg("x")]
    upd = make_tools_node(None)(state)
    assert upd["adj_messages"][-1]["content"] == "precedent search unavailable"


# --- the adjudicate node ----------------------------------------------------------
def test_node_finalizes_on_submit():
    upd = make_adjudicate_node(lambda m, t: _submit_msg("remove", 3, "bad"))(_gray_state())
    assert upd["escalated"] is True
    assert upd["action"] == "remove"
    assert upd["overall_severity"] == 3
    assert upd["adjudication"]["final_action"] == "remove"
    assert upd["adjudication"]["note"] == "bad"
    assert upd["adj_steps"] == 1


def test_node_continues_on_getpolicy_and_keeps_system_user():
    upd = make_adjudicate_node(lambda m, t: _getpolicy_msg("toxic"))(_gray_state())
    assert "action" not in upd  # did NOT finalize
    assert upd["adj_steps"] == 1
    # the system + user prompt must survive the first turn (regression: it got dropped once)
    assert [m["role"] for m in upd["adj_messages"]] == ["system", "user", "assistant"]


def test_node_degrades_on_repeated_failure_without_crashing():
    # Regression for the first-turn-degrade IndexError: degrade MUST populate adj_messages
    def boom(m, t):
        raise RuntimeError("deepseek timeout")
    upd = make_adjudicate_node(boom)(_gray_state())
    assert upd["escalated"] is True
    assert upd["adj_messages"]                      # non-empty -> after_adjudicate won't IndexError
    assert "unavailable" in upd["adjudication"]["note"].lower()
    assert "action" not in upd                      # tentative verdict kept


# --- full loop through the graph (offline) ----------------------------------------
def _stateful_adjudicator():
    """Turn 1 asks for a policy, turn 2 submits the decision."""
    n = {"i": 0}

    def fn(messages, tools):
        n["i"] += 1
        return _getpolicy_msg("identity_hate") if n["i"] == 1 else _submit_msg("allow", 1, "resolved")
    return fn


def test_graph_escalates_gray_case_through_adjudicator():
    table = {c: {"model": "x", "threshold": 1} for c in ALL_6}
    graph = build_graph(table, classify_fn=_fake_classify,
                        detect_fn=lambda c: ContextFlags(ambiguity=True),
                        adjudicate_fn=_stateful_adjudicator())
    out = graph.invoke(initial_state("you idiot"))
    assert out["escalated"] is True
    assert out["action"] == "allow"            # adjudicator overrode the tentative human-review
    assert out["overall_severity"] == 1
    assert out["adjudication"]["policies_consulted"] == ["identity_hate"]


def test_graph_clean_case_skips_adjudicator():
    table = {c: {"model": "x", "threshold": 1} for c in ALL_6}
    calls = {"i": 0}

    def counting(messages, tools):
        calls["i"] += 1
        return _submit_msg("allow", 0, "x")

    def all_clean(model, comment, categories):
        return ClassifyResult(verdicts={categories[0]: {"severity": Severity.none, "reason": "r", "span": None}})

    graph = build_graph(table, classify_fn=all_clean,
                        detect_fn=lambda c: ContextFlags(),
                        adjudicate_fn=counting)
    out = graph.invoke(initial_state("thanks, this was helpful"))
    assert out.get("escalated") is False       # never escalated
    assert calls["i"] == 0                      # adjudicator never ran


def test_graph_first_turn_degrade_does_not_crash():
    # End-to-end regression: gray case escalates, adjudicate_fn fails twice on the
    # very first turn -> must degrade to the rule-based verdict, not IndexError.
    table = {c: {"model": "x", "threshold": 1} for c in ALL_6}

    def boom(messages, tools):
        raise RuntimeError("deepseek timeout")

    graph = build_graph(table, classify_fn=_fake_classify,
                        detect_fn=lambda c: ContextFlags(ambiguity=True),
                        adjudicate_fn=boom)
    out = graph.invoke(initial_state("you idiot"))
    assert out["escalated"] is True
    assert out["action"] == "human-review"     # tentative rule-based verdict kept


# --- search_precedents drives the loop too (HITL spec 2026-06-09 §6) ---------------
def test_after_routes_tool_for_search_precedents_under_cap():
    assert after_adjudicate({"adj_messages": [_searchprec_msg("x")], "adj_steps": 1}) == "tool"


def test_node_continues_on_search_precedents():
    upd = make_adjudicate_node(lambda m, t: _searchprec_msg("you idiot"))(_gray_state())
    assert "action" not in upd                 # did NOT finalize
    assert upd["adj_steps"] == 1


def test_submit_decision_confidence_lands_in_adjudication():
    upd = make_adjudicate_node(
        lambda m, t: _submit_msg("allow", 0, "ok", confidence=0.92))(_gray_state())
    assert upd["adjudication"]["confidence"] == 0.92


def test_graph_collects_precedents_consulted():
    # search_precedents then submit -> the queries land in the adjudication trace
    table = {c: {"model": "x", "threshold": 1} for c in ALL_6}
    n = {"i": 0}

    def fn(messages, tools):
        n["i"] += 1
        return _searchprec_msg("you idiot") if n["i"] == 1 else _submit_msg("allow", 1, "precedent says fine")

    hits = [{"comment_text": "u r dumb", "action": "allow",
             "overall_severity": 1, "note": "trash talk", "source": "human"}]
    graph = build_graph(table, classify_fn=_fake_classify,
                        detect_fn=lambda c: ContextFlags(ambiguity=True),
                        adjudicate_fn=fn, store=FakeStore(hits))
    out = graph.invoke(initial_state("you idiot"))
    assert out["action"] == "allow"
    assert out["adjudication"]["precedents_consulted"] == ["you idiot"]


# --- HITL spec 2026-06-09: confidence gate ----------------------------------------
from arbiter.product.adjudicator import needs_human, route_after_adjudicate


def test_low_confidence_goes_human():
    assert needs_human({"action": "allow",
                        "adjudication": {"confidence": 0.3}}) == "human"


def test_high_confidence_finalizes():
    assert needs_human({"action": "remove",
                        "adjudication": {"confidence": 0.95}}) == "finalize"


def test_exactly_threshold_finalizes():
    assert needs_human({"action": "allow",
                        "adjudication": {"confidence": 0.7}}) == "finalize"


def test_human_review_action_always_queues():
    assert needs_human({"action": "human-review",
                        "adjudication": {"confidence": 0.99}}) == "human"


def test_degrade_without_confidence_only_queues_on_action():
    # degrade path writes no confidence key -> default 1.0; only the action decides
    deg = {"note": "adjudicator unavailable, kept rule-based verdict",
           "policies_consulted": []}
    assert needs_human({"action": "allow", "adjudication": deg}) == "finalize"
    assert needs_human({"action": "human-review", "adjudication": deg}) == "human"


def test_route_after_adjudicate_composes_tool_and_gate():
    # mid-loop (asking for a tool) -> "tool"
    assert route_after_adjudicate(
        {"adj_messages": [_getpolicy_msg("toxic")], "adj_steps": 1}) == "tool"
    # submitted, low confidence -> "human"
    submitted = {"adj_messages": [{"role": "assistant", "content": None,
                                   "tool_calls": [{"id": "1", "function": {
                                       "name": "submit_decision", "arguments": "{}"}}]}],
                 "adj_steps": 1, "action": "allow",
                 "adjudication": {"confidence": 0.2}}
    assert route_after_adjudicate(submitted) == "human"
    # submitted, confident -> "done"
    submitted["adjudication"] = {"confidence": 0.9}
    assert route_after_adjudicate(submitted) == "done"
