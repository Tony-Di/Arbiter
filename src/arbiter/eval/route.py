"""Routing — turn per-model / per-category sweeps into routing_table.json.

Check:  python -m pytest tests/eval/test_route.py -v   (goal: 4 passed)
"""


def pick_operating_point(sweep: dict, prefer_recall: bool) -> dict:
    if prefer_recall:
        return max(sweep.values(), key=lambda m: (m["recall"], m["f1"]))
    else:
        return max(sweep.values(), key=lambda m: (m["f1"], m["recall"]))


def build_routing_table(model_metrics: dict, high_risk: set) -> dict:
    table = {}
    for category in model_metrics[list(model_metrics.keys())[0]]:
        ops = {model_id: pick_operating_point(model_metrics[model_id][category], category in high_risk) for model_id in model_metrics}
        if category in high_risk:
            winner = max(ops, key=lambda m: ops[m]["recall"])
        else:
            winner = max(ops, key=lambda m: ops[m]["f1"])
        table[category] = {"model": winner, "threshold": ops[winner]["cutoff"]}
    return table