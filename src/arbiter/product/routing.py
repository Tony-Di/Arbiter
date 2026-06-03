"""Load routing_table.json — the only artifact crossing eval -> product.

The product reads this at startup; each specialist node looks up which model
judges its category. (The `threshold` field is eval's operating point; the v1
product acts on the raw ordinal severity, so threshold is provenance only.)

Fill the TODOs (spec: plan Task 2).
Check:  python -m pytest tests/product/test_routing.py -v   (goal: 2 passed)
"""
import json


def load_routing_table(path: str = "routing_table.json") -> dict:
    # 🔨 TODO: open(path) -> json.load -> return the dict
    #   {category: {"model": str, "threshold": int}}.
    
    with open(path, "r") as f:
        return json.load(f)

def model_for(table: dict, category: str) -> str:
    # 🔨 TODO: return table[category]["model"]
    #   (a plain lookup; KeyError on an unknown category is fine — it signals a
    #    missing routing entry loudly.)
    return table[category]["model"]
