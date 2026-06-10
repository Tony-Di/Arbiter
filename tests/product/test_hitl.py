"""HITL through the full graph: pause on low confidence, resume with the human
decision. Zero-network (fake classify/detect/adjudicate; InMemorySaver).

Check:  python -m pytest tests/product/test_hitl.py -v
"""
import json

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from arbiter.classify import ALL_6
from arbiter.classify.schema import ClassifyResult, Severity
from arbiter.product.context import ContextFlags
from arbiter.product.graph import build_graph
from arbiter.product.state import initial_state

TABLE = {c: {"model": "deepseek-chat", "threshold": 1} for c in ALL_6}
CFG = {"configurable": {"thread_id": "case-1"}}


def _fake_classify(model, comment, categories):
    cat = categories[0]
    sev = Severity.medium if cat == "insult" else Severity.none
    return ClassifyResult(verdicts={cat: {"severity": sev, "reason": "r", "span": None}})


def _fake_detect(comment):
    return ContextFlags()


def _submitting(confidence, action="allow"):
    def fn(messages, tools):
        return {"role": "assistant", "content": None, "tool_calls": [
            {"id": "1", "function": {"name": "submit_decision",
                "arguments": json.dumps({"action": action, "overall_severity": 1,
                                         "note": "n", "confidence": confidence})}}]}
    return fn


def _graph(adjudicate_fn):
    return build_graph(TABLE, classify_fn=_fake_classify, detect_fn=_fake_detect,
                       adjudicate_fn=adjudicate_fn, checkpointer=InMemorySaver())


def test_low_confidence_pauses_with_recommendation():
    result = _graph(_submitting(0.3)).invoke(initial_state("you idiot"), config=CFG)
    assert "__interrupt__" in result
    payload = result["__interrupt__"][0].value
    assert payload["recommended_action"] == "allow"
    assert payload["confidence"] == 0.3


def test_resume_applies_human_decision():
    g = _graph(_submitting(0.3))
    g.invoke(initial_state("you idiot"), config=CFG)
    final = g.invoke(Command(resume={"action": "remove", "note": "clear attack"}),
                     config=CFG)
    assert final["action"] == "remove"
    assert final["adjudication"]["human"] == {"action": "remove", "note": "clear attack"}


def test_resume_confirm_keeps_recommendation():
    g = _graph(_submitting(0.3))
    g.invoke(initial_state("you idiot"), config=CFG)
    final = g.invoke(Command(resume={"action": "confirm", "note": None}), config=CFG)
    assert final["action"] == "allow"          # the AI's recommendation


def test_high_confidence_does_not_pause():
    result = _graph(_submitting(0.95)).invoke(initial_state("you idiot"), config=CFG)
    assert "__interrupt__" not in result
    assert result["action"] == "allow"


def test_clean_case_never_pauses():
    def all_clean(model, comment, categories):
        cat = categories[0]
        return ClassifyResult(verdicts={cat: {"severity": Severity.none,
                                              "reason": "r", "span": None}})
    g = build_graph(TABLE, classify_fn=all_clean, detect_fn=_fake_detect,
                    adjudicate_fn=_submitting(0.0), checkpointer=InMemorySaver())
    result = g.invoke(initial_state("nice day"), config=CFG)
    assert "__interrupt__" not in result and result["action"] == "allow"


def test_no_checkpointer_default_is_unchanged():
    g = build_graph(TABLE, classify_fn=_fake_classify, detect_fn=_fake_detect)
    result = g.invoke(initial_state("you idiot"))   # no thread_id, as today
    assert result["action"] == "human-review"
