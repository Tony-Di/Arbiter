from typing import Annotated, TypedDict

from langgraph.graph import START, END, StateGraph

from arbiter.product.state import ModerationState, merge_verdicts


def test_merge_verdicts_unions_and_b_wins_conflicts():
    assert merge_verdicts({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}
    assert merge_verdicts({"a": 1}, {"a": 9}) == {"a": 9}


def test_merge_verdicts_does_not_mutate_inputs():
    a = {"a": 1}
    merge_verdicts(a, {"b": 2})
    assert a == {"a": 1}


def test_parallel_nodes_merge_into_one_dict():
    # Two nodes fan out from START in parallel, each writing ONE key into the same
    # reducer-annotated dict. Without the reducer this raises InvalidUpdateError.
    class S(TypedDict):
        bag: Annotated[dict, merge_verdicts]

    def node_a(state):
        return {"bag": {"a": 1}}

    def node_b(state):
        return {"bag": {"b": 2}}

    g = StateGraph(S)
    g.add_node("a", node_a)
    g.add_node("b", node_b)
    g.add_edge(START, "a")
    g.add_edge(START, "b")
    g.add_edge("a", END)
    g.add_edge("b", END)
    out = g.compile().invoke({"bag": {}})
    assert out["bag"] == {"a": 1, "b": 2}


def test_state_has_expected_keys():
    assert set(ModerationState.__annotations__) == {
        "comment", "raw_verdicts", "routing_snapshot",
        "context_flags", "effective_verdicts", "overall_severity", "action",
        # escalation channels (spec 2026-06-08 §6)
        "escalated", "adj_messages", "adj_steps", "adjudication",
    }


def test_initial_state_seeds_reducer_channels():
    from arbiter.product.state import initial_state
    s = initial_state("hello")
    assert s == {"comment": "hello", "raw_verdicts": {}, "routing_snapshot": {},
                 "escalated": False, "adj_messages": [], "adj_steps": 0}
