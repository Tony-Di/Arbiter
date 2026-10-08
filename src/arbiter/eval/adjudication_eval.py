"""Paired adjudication and threshold diagnostics on identical upstream evidence."""
from copy import deepcopy
import math
import time

from arbiter.eval.system_score import compare_variants, score_predictions
from arbiter.product.adjudicator import (CONFIDENCE_THRESHOLD, MAX_TOOL_STEPS, after_adjudicate,
    make_adjudicate_node, make_tools_node, should_escalate)


def valid_confidence(value):
    return type(value) in (float, int) and math.isfinite(value) and 0 <= value <= 1


def gated_action(row, threshold=CONFIDENCE_THRESHOLD):
    """Counterfactual gate; un-escalated decisions never change with the threshold."""
    if not row.get("escalated"):
        return row["action"]
    adj = row.get("adjudication") or {}
    action = row.get("ai_recommended_action", adj.get("final_action", row["action"]))
    confidence = adj.get("confidence")
    if (action not in {"allow", "remove"} or not valid_confidence(confidence)
            or confidence < threshold or adj.get("status") == "needs_review"):
        return "human-review"
    return action


def adjudicate_snapshot(upstream, adjudicate_fn, *, force=False, store=None, clock=time.perf_counter):
    """Reuse the SAME raw/context evidence. Forced calls are explicitly component tests."""
    state = deepcopy(upstream)
    state.update(adj_messages=[], adj_steps=0, escalated=False)
    state.pop("adjudication", None)
    baseline = state["action"]
    natural_route = should_escalate(state)
    calls, call_ms = 0, 0.0
    def timed(messages, tools):
        nonlocal calls, call_ms
        calls += 1
        started = clock()
        try:
            return adjudicate_fn(messages, tools)
        finally:
            call_ms += (clock() - started) * 1000
    started = clock()
    if force or natural_route == "escalate":
        node, tools_node = make_adjudicate_node(timed), make_tools_node(store)
        for _ in range(MAX_TOOL_STEPS):
            state.update(node(state))
            if after_adjudicate(state) != "tool":
                break
            state.update(tools_node(state))
    added_ms = (clock() - started) * 1000 if state.get("escalated") else 0.0
    state["ai_recommended_action"] = state["action"]
    state["action"] = gated_action(state)
    return {"baseline_action": baseline, "natural_route": natural_route,
            "forced_component_call": force, "added_latency_ms": added_ms,
            "api_attempts": calls, "api_latency_ms": call_ms, "prediction": state}


def threshold_sweep(cases, rows, *, thresholds=(0.5, 0.7, 0.8, 0.85, 0.9, 0.95, 0.97, 0.99, 1.0),
                    label_status="unreviewed_reference"):
    if any(not valid_confidence(t) for t in thresholds):
        raise ValueError("Thresholds must be finite numbers between 0 and 1")
    report = {"label_status": label_status, "threshold_selected": None,
              "production_threshold_changed": False, "rows": []}
    baseline = [{**r, "action": gated_action(r), "variant": "gate_0.95"} for r in rows]
    for threshold in thresholds:
        gated = [{**r, "action": gated_action(r, threshold), "variant": "candidate"} for r in rows]
        entry = {"threshold": threshold, "n_cases": len(rows),
                 "n_escalated": sum(bool(r.get("escalated")) for r in rows),
                 "n_escalated_auto": sum(bool(r.get("escalated")) and r["action"] != "human-review" for r in gated),
                 "n_human_review": sum(r["action"] == "human-review" for r in gated),
                 "quality_metrics": None, "paired_vs_0.95": None}
        if cases is not None:
            entry["quality_metrics"] = score_predictions(cases, gated)
            entry["paired_vs_0.95"] = compare_variants(cases, baseline + gated, "gate_0.95", "candidate")
        report["rows"].append(entry)
    report["note"] = ("Gate replay on saved recommendations only; it does not save already incurred adjudication latency. "
                      "No threshold is selected. Unreviewed reference labels cannot establish calibration or accuracy.")
    return report
