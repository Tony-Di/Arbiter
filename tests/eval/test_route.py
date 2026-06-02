from arbiter.eval.route import build_routing_table, pick_operating_point


def _m(cutoff, f1, recall):
    return {"cutoff": cutoff, "f1": f1, "recall": recall, "precision": 0.0, "tp": 0, "fp": 0, "fn": 0}


def test_pick_default_is_max_f1():
    sweep = {1: _m(1, 0.6, 0.9), 2: _m(2, 0.7, 0.6), 3: _m(3, 0.5, 0.3)}
    assert pick_operating_point(sweep, prefer_recall=False)["cutoff"] == 2


def test_pick_prefer_recall_is_max_recall():
    sweep = {1: _m(1, 0.6, 0.9), 2: _m(2, 0.7, 0.6), 3: _m(3, 0.5, 0.3)}
    assert pick_operating_point(sweep, prefer_recall=True)["cutoff"] == 1


def test_routing_default_picks_higher_f1_model():
    metrics = {
        "A": {"insult": {1: _m(1, 0.6, 0.9), 2: _m(2, 0.70, 0.6), 3: _m(3, 0.5, 0.3)}},
        "B": {"insult": {1: _m(1, 0.65, 0.95), 2: _m(2, 0.72, 0.5), 3: _m(3, 0.5, 0.3)}},
    }
    table = build_routing_table(metrics, high_risk=set())
    assert table["insult"] == {"model": "B", "threshold": 2}


def test_routing_high_risk_prefers_recall_over_f1():
    metrics = {
        "A": {"threat": {1: _m(1, 0.80, 0.85), 2: _m(2, 0.82, 0.70), 3: _m(3, 0.5, 0.3)}},
        "B": {"threat": {1: _m(1, 0.70, 0.95), 2: _m(2, 0.75, 0.80), 3: _m(3, 0.5, 0.3)}},
    }
    table = build_routing_table(metrics, high_risk={"threat"})
    # A has higher f1, but threat is high-risk -> B wins on recall (0.95 > 0.85)
    assert table["threat"] == {"model": "B", "threshold": 1}
