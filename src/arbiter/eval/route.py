"""Routing — turn per-model / per-category sweeps into routing_table.json.

Fill the two functions (spec: plan Task 4).
Check:  python -m pytest tests/eval/test_route.py -v   (goal: 4 passed)
"""


def pick_operating_point(sweep: dict, prefer_recall: bool) -> dict:
    # 🔨 TODO: sweep is {cutoff: metrics}. Return ONE metrics dict.
    #   prefer_recall=False -> highest f1   (tie -> higher recall)
    #   prefer_recall=True  -> highest recall (tie -> higher f1)
    #   Hint: max(sweep.values(), key=lambda m: (m["f1"], m["recall"]))
    #         and the recall-first variant for prefer_recall=True.
    
    if prefer_recall:
        return max(sweep.values(), key=lambda m: (m["recall"], m["f1"]))
    else:
        return max(sweep.values(), key=lambda m: (m["f1"], m["recall"]))


def build_routing_table(model_metrics: dict, high_risk: set) -> dict:
    # 🔨 TODO: model_metrics = {model_id: {category: sweep}}
    #   table = {}
    #   for each category (the keys of any model's metrics):
    #     ops = {model_id: pick_operating_point(sweep, prefer_recall=(category in high_risk))}
    #     if category in high_risk: winner = model_id with max ops[m]["recall"]
    #     else:                     winner = model_id with max ops[m]["f1"]
    #     table[category] = {"model": winner, "threshold": ops[winner]["cutoff"]}
    #   return table
    
    table = {}
    for category in model_metrics[list(model_metrics.keys())[0]]:
        ops = {model_id: pick_operating_point(model_metrics[model_id][category], category in high_risk) for model_id in model_metrics}
        if category in high_risk:
            winner = max(ops, key=lambda m: ops[m]["recall"])
        else:
            winner = max(ops, key=lambda m: ops[m]["f1"])
        table[category] = {"model": winner, "threshold": ops[winner]["cutoff"]}
    return table