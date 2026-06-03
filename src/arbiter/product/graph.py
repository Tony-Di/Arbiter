"""Build the LangGraph product pipeline (spec §9/§10).

START -> [6 specialist nodes + context node] in parallel -> aggregator -> END.
classify_fn / detect_fn are injectable so the whole graph tests with fakes.

Fill the TODOs (spec: plan Task 6).
Check:  python -m pytest tests/product/test_graph.py -v   (goal: 2 passed)
"""
from langgraph.graph import START, END, StateGraph

from arbiter.classify import ALL_6, classify
from arbiter.product.context import detect_context
from arbiter.product.nodes import aggregator_node, make_context_node, make_specialist_node
from arbiter.product.state import ModerationState


def build_graph(table: dict, classify_fn=classify, detect_fn=detect_context):
    # 🔨 TODO: wire the DAG, then `return g.compile()`:
    #   g = StateGraph(ModerationState)
    #   # nodes
    #   for cat in ALL_6:
    #       g.add_node(f"specialist_{cat}", make_specialist_node(cat, table, classify_fn))
    #   g.add_node("context", make_context_node(detect_fn))
    #   g.add_node("aggregator", aggregator_node)
    #   # edges: START fans out to all 7; all 7 feed the aggregator; aggregator -> END
    #   for cat in ALL_6:
    #       g.add_edge(START, f"specialist_{cat}")
    #       g.add_edge(f"specialist_{cat}", "aggregator")
    #   g.add_edge(START, "context")
    #   g.add_edge("context", "aggregator")
    #   g.add_edge("aggregator", END)
    #   return g.compile()
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
    g.add_edge("aggregator", END)
    return g.compile()
