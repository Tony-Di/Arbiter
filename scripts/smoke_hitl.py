"""Live HITL smoke — pause -> queue -> resolve -> final, against a RUNNING server
with real keys. Exits nonzero if any step's shape is wrong.

Run (CN-Windows GBK console needs the encoding override):
  $env:PYTHONIOENCODING="utf-8"; .venv\\Scripts\\python scripts/smoke_hitl.py

Steps (each prints what it got; assert the marked invariants):
  1. POST {BASE}/api/moderate  {"comment": GRAY_COMMENT}
     -> expect status "pending" (if DeepSeek is confident and it comes back
        "final", print the confidence and exit 2 -- that's the threshold-tuning
        signal from plan §7.3, not a code failure)
     -> keep case_id; assert recommendation has recommended_action + confidence
  2. GET  {BASE}/api/review-queue
     -> assert our case_id is listed with the same comment
  3. POST {BASE}/api/review/{case_id}  {"action": "remove", "note": "smoke"}
     -> assert response action == "remove" and status == "final"
  4. POST the same resolve again -> assert 409 (double-resolve guard)
  5. print("HITL smoke OK"); exit 0

TODO(author): implement with urllib.request or httpx (httpx ships with fastapi's
test deps; urllib keeps it stdlib). ~40 lines.
"""
import sys

BASE = "http://127.0.0.1:8000"

# Gray on purpose: a DIRECT personal insult (specialists should hit severity 2
# -> action human-review -> escalates) but no slur/threat (so not a straight
# remove). Live-verified 2026-06-10: the milder "people like you are why this
# forum is going downhill" came back all-LOW and never escalated.
GRAY_COMMENT = "you're a pathetic clown and everyone in this forum secretly laughs at you"


def main() -> int:
    raise NotImplementedError("TODO(author): steps 1-5 in the module docstring")


if __name__ == "__main__":
    sys.exit(main())
