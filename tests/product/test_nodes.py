from arbiter.classify.schema import ClassifyResult, Severity
from arbiter.product.context import ContextFlags
from arbiter.product.nodes import make_specialist_node, make_context_node, aggregator_node

TABLE = {"insult": {"model": "deepseek-chat", "threshold": 1},
         "threat": {"model": "gpt-4o-mini", "threshold": 1}}


def _fake_classify(model, comment, categories):
    cat = categories[0]
    return ClassifyResult(verdicts={cat: {"severity": Severity.medium, "reason": "r", "span": "idiot"}})


def test_specialist_node_emits_raw_verdict_and_routing():
    node = make_specialist_node("insult", TABLE, classify_fn=_fake_classify)
    out = node({"comment": "you idiot"})
    assert out["raw_verdicts"]["insult"]["severity"] == 2
    assert out["raw_verdicts"]["insult"]["span"] == "idiot"
    assert out["routing_snapshot"]["insult"] == "deepseek-chat"


def test_specialist_node_uses_routed_model_per_category():
    node = make_specialist_node("threat", TABLE, classify_fn=_fake_classify)
    out = node({"comment": "x"})
    assert out["routing_snapshot"]["threat"] == "gpt-4o-mini"


def test_context_node_emits_flags_dict():
    def fake_detect(comment):
        return ContextFlags(sarcasm=True, note="joke")
    node = make_context_node(detect_fn=fake_detect)
    out = node({"comment": "I'll kill you 😂"})
    assert out["context_flags"]["sarcasm"] is True
    assert out["context_flags"]["note"] == "joke"


def test_aggregator_node_runs_the_policy():
    state = {
        "raw_verdicts": {"insult": {"severity": 2, "reason": "r", "span": "idiot"}},
        "context_flags": {"sarcasm": True, "quotation": False, "reclaimed_slur": False,
                          "direct_threat": False, "ambiguity": False, "note": None},
    }
    out = aggregator_node(state)
    assert out["effective_verdicts"]["insult"] == 2
    assert out["action"] == "human-review"
