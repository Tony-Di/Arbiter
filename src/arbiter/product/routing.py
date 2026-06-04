"""Load routing_table.json — the only artifact crossing eval -> product.

The product reads this at startup; each specialist node looks up which model
judges its category. (The `threshold` field is eval's operating point; the v1
product acts on the raw ordinal severity, so threshold is provenance only.)

Check:  python -m pytest tests/product/test_routing.py -v   (goal: 2 passed)
"""
import json


def load_routing_table(path: str = "routing_table.json") -> dict:
    with open(path, "r") as f:
        return json.load(f)

def model_for(table: dict, category: str) -> str:
    return table[category]["model"]
