"""Build the LangGraph product pipeline (spec §9/§10 + escalation spec 2026-06-08).

Base graph:   START -> [6 specialist nodes + context node] in parallel -> aggregator
Escalation:   aggregator --(should_escalate)--> adjudicate <-> policy_tool (the cycle)
              -> END.  The policy_tool -> adjudicate edge is the visible agentic loop.

classify_fn / detect_fn / adjudicate_fn are injectable so the whole graph tests with
fakes (no network). When adjudicate_fn is None the escalation branch is NOT wired and
the graph behaves exactly as the pre-escalation pipeline -- this is what keeps the
existing suite green; escalation activates only when an adjudicator is injected.

Check:  python -m pytest tests/product/test_graph.py -v
"""
from langgraph.graph import START, END, StateGraph

from arbiter.classify import ALL_6, classify
from arbiter.product.adjudicator import (
    after_adjudicate,
    make_adjudicate_node,
    policy_tool_node,
    should_escalate,
)
from arbiter.product.context import detect_context
from arbiter.product.nodes import aggregator_node, make_context_node, make_specialist_node
from arbiter.product.state import ModerationState


def build_graph(table: dict, classify_fn=classify, detect_fn=detect_context,
                adjudicate_fn=None):
    g = StateGraph(ModerationState)
    for cat in ALL_6:
        g.add_node(f"specialist_{cat}", make_specialist_node(cat, table, classify_fn))
    g.add_node("context", make_context_node(detect_fn))
    g.add_node("aggregator", aggregator_node)
    for cat in ALL_6:
        g.add_edge(START, f"specialist_{cat}")
        g.add_edge(f"specialist_{cat}", "aggregator")
    g.add_edge(START, "context")
    g.add_edge("context", "aggregator")

    if adjudicate_fn is None:
        # No adjudicator wired -> the aggregator's verdict is final (pre-escalation
        # behavior). Keeps existing call sites + tests unchanged.
        g.add_edge("aggregator", END)
        return g.compile()

    # --- escalation branch (Approach A: the ReAct loop is a cycle in the graph) ---
    g.add_node("adjudicate", make_adjudicate_node(adjudicate_fn))
    g.add_node("policy_tool", policy_tool_node)
    # aggregator's verdict is now TENTATIVE: gray cases route to the adjudicator.
    g.add_conditional_edges("aggregator", should_escalate,
                            {"escalate": "adjudicate", "done": END})
    # the adjudicator drives its own loop: ask for policy, or submit & finish.
    g.add_conditional_edges("adjudicate", after_adjudicate,
                            {"tool": "policy_tool", "done": END})
    g.add_edge("policy_tool", "adjudicate")  # <-- the visible cycle
    return g.compile()
