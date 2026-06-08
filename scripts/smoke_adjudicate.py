"""Smoke: confirm DeepSeek's tool_calls shape + the adjudicator loop runs end-to-end.

Bypasses the 6 specialists (those route to gpt-5.4-mini and would need an OpenAI key);
feeds a constructed gray state straight into the adjudicator loop -> DeepSeek only.

Run (CN-Windows: force utf-8 so emoji/quotes don't crash the GBK console):
    $env:PYTHONIOENCODING="utf-8"; .\.venv\Scripts\python.exe scripts\smoke_adjudicate.py

Needs DEEPSEEK_API_KEY in .env. Makes a couple of cheap DeepSeek calls.
"""
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")  # CN-Windows GBK console safety
from dotenv import load_dotenv

load_dotenv()

from arbiter.product.adjudicator import (  # noqa: E402
    TOOLS,
    after_adjudicate,
    default_adjudicate_fn,
    make_adjudicate_node,
    policy_tool_node,
    should_escalate,
)
from arbiter.product.state import initial_state  # noqa: E402

COMMENT = "People like you don't belong in this country."

# 1) raw shape check -- print exactly what complete_with_tools returns so we can
#    verify calls[0]["function"]["name"]/["arguments"]/["id"] match the node code.
print("=== raw assistant message (verify tool_calls shape) ===")
probe = [
    {"role": "system", "content": "You moderate comments. Call get_policy for the most "
                                  "relevant category, then call submit_decision."},
    {"role": "user", "content": f"<comment>\n{COMMENT}\n</comment>"},
]
assistant = default_adjudicate_fn(probe, TOOLS)
print(json.dumps(assistant, indent=2, ensure_ascii=False))

# 2) drive the real loop on a constructed gray state (mirrors the graph's edges).
state = initial_state(COMMENT)
state.update({
    "context_flags": {"sarcasm": False, "quotation": False, "reclaimed_slur": False,
                      "direct_threat": False, "ambiguity": True, "note": "borderline"},
    "effective_verdicts": {"identity_hate": 2, "toxic": 2, "severe_toxic": 0,
                           "obscene": 0, "threat": 0, "insult": 1},
    "overall_severity": 2,
    "action": "human-review",
})
print("\nshould_escalate ->", should_escalate(state))

node = make_adjudicate_node(default_adjudicate_fn)
for _ in range(MAX := 6):  # hard outer bound so a bug can't loop forever
    state.update(node(state))
    if after_adjudicate(state) == "tool":
        state.update(policy_tool_node(state))
    else:
        break

print("\n=== final state ===")
print("escalated:        ", state.get("escalated"))
print("action:           ", state.get("action"))
print("overall_severity: ", state.get("overall_severity"))
print("adjudication:     ", state.get("adjudication"))
print("adj_steps:        ", state.get("adj_steps"))
