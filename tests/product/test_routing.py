import json

from arbiter.classify import ALL_6
from arbiter.product.routing import load_routing_table, model_for


def test_load_real_committed_table_has_all_6():
    table = load_routing_table("routing_table.json")
    assert set(table) == set(ALL_6)
    for cat in ALL_6:
        assert "model" in table[cat] and "threshold" in table[cat]


def test_model_for_returns_routed_model(tmp_path):
    p = tmp_path / "rt.json"
    p.write_text(json.dumps({"toxic": {"model": "gpt-4o-mini", "threshold": 2}}), encoding="utf-8")
    table = load_routing_table(str(p))
    assert model_for(table, "toxic") == "gpt-4o-mini"
