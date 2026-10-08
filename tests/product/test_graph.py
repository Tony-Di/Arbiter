from arbiter.classify import ALL_6
from arbiter.classify.schema import ClassifyResult, Severity
from arbiter.product.context import ContextFlags
from arbiter.product.graph import build_graph
from arbiter.product.state import initial_state

TABLE = {c: {"model": "deepseek-chat", "threshold": 1} for c in ALL_6}


def _fake_classify(model, comment, categories):
    cat = categories[0]
    # mark only `insult` as medium; everything else none
    sev = Severity.medium if cat == "insult" else Severity.none
    return ClassifyResult(verdicts={cat: {"severity": sev, "reason": "r", "span": None}})


def _fake_detect_clean(comment):
    return ContextFlags()  # all flags false


def test_graph_runs_end_to_end_with_fakes():
    graph = build_graph(TABLE, classify_fn=_fake_classify, detect_fn=_fake_detect_clean)
    out = graph.invoke(initial_state("you idiot"))
    # all 6 specialists ran (parallel) and merged into one dict
    assert set(out["raw_verdicts"]) == set(ALL_6)
    assert out["raw_verdicts"]["insult"]["severity"] == 2
    # insult=2, no flags -> human-review; overall severity 2
    assert out["action"] == "human-review"
    assert out["overall_severity"] == 2
    assert out["context_flags"]["sarcasm"] is False


def test_graph_sarcasm_flag_alone_does_not_downgrade():
    def fake_detect_sarcasm(comment):
        return ContextFlags(sarcasm=True)
    graph = build_graph(TABLE, classify_fn=_fake_classify, detect_fn=fake_detect_sarcasm)
    out = graph.invoke(initial_state("you idiot (jk)"))
    assert out["effective_verdicts"]["insult"] == 2
    assert out["action"] == "human-review"
