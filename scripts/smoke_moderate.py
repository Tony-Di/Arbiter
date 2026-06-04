"""Smoke-test the product pipeline end-to-end on DeepSeek.

Loads routing_table.json, builds the real LangGraph pipeline, runs a few comments.
Needs DEEPSEEK_API_KEY in .env.  Run:  python scripts/smoke_moderate.py
"""
import json

from dotenv import load_dotenv

from arbiter.product.graph import build_graph
from arbiter.product.routing import load_routing_table
from arbiter.product.state import initial_state

load_dotenv()

COMMENTS = [
    "Have a great day, everyone!",                 # expect: allow
    "You are an absolute idiot and I hate you.",   # expect: human-review / remove
    "I'll kill you 😂",                            # gray: context node should flag sarcasm
]


def main():
    table = load_routing_table("routing_table.json")
    graph = build_graph(table)  # real classify + detect_context
    for c in COMMENTS:
        out = graph.invoke(initial_state(c))
        print(f"\n[{c}]\n  action={out['action']}  severity={out['overall_severity']}")
        print(f"  flags={out['context_flags']}")
        print(f"  effective={out['effective_verdicts']}")



if __name__ == "__main__":
    main()
