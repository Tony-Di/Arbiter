"""LangGraph node functions: 6 specialists (parallel) + context + aggregator.

Each node is `state -> partial state update`. LLM calls are INJECTED
(classify_fn / detect_fn) so nodes + the whole graph test with fakes, no network
(same DI idea as eval/collect.py).

Check:  python -m pytest tests/product/test_nodes.py -v   (goal: 4 passed)
"""
from arbiter.classify import classify
from arbiter.product.aggregator import aggregate
from arbiter.product.context import detect_context
from arbiter.product.routing import model_for


def make_specialist_node(category: str, table: dict, classify_fn=classify):
    def node(state):
        model = model_for(table, category)
        result = classify_fn(model, state["comment"], [category])
        verdict = result.verdicts[category]
        return {"raw_verdicts": {category: verdict.model_dump(mode="json")},
                "routing_snapshot": {category: model}}
    return node

def make_context_node(detect_fn=detect_context):
    def node(state):
        return {"context_flags": detect_fn(state["comment"]).model_dump()}
    return node


def aggregator_node(state) -> dict:
    return aggregate(state["raw_verdicts"], state["context_flags"])
