"""Smoke-test the HTTP API end-to-end on DeepSeek (in-process TestClient).

Needs DEEPSEEK_API_KEY in .env.  Run:  python scripts/smoke_api.py
On CN-Windows, run with:  $env:PYTHONIOENCODING="utf-8"; python scripts/smoke_api.py
"""
from dotenv import load_dotenv
from fastapi.testclient import TestClient

from arbiter.api.main import app

load_dotenv()

COMMENTS = [
    "Have a great day, everyone!",
    "You are an absolute idiot and I hate you.",
    # a gray case -> should escalate to the adjudicator
    "I'm reporting a comment — someone replied to my post quoting a slur back at me to mock me.",
]


def main():
    with TestClient(app) as client:   # `with` triggers lifespan -> builds the graph
        print("health:", client.get("/api/health").json())
        for c in COMMENTS:
            r = client.post("/api/moderate", json={"comment": c}).json()
            print("\n" + c)
            print(f"  action={r['action']}  severity={r['overall_severity']}  escalated={r['escalated']}")
            if r.get("adjudication"):
                print(f"  adjudication={r['adjudication']}")


if __name__ == "__main__":
    main()
