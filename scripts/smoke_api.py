"""Smoke-test the HTTP API end-to-end on DeepSeek (in-process TestClient).

Needs DEEPSEEK_API_KEY in .env.  Run:  python scripts/smoke_api.py
On CN-Windows, run with:  $env:PYTHONIOENCODING="utf-8"; python scripts/smoke_api.py
"""
from dotenv import load_dotenv
from fastapi.testclient import TestClient

from arbiter.api.main import app

load_dotenv()

COMMENTS = ["Have a great day, everyone!", "You are an absolute idiot and I hate you."]


def main():
    with TestClient(app) as client:   # `with` triggers lifespan -> builds the real graph
        print("health:", client.get("/api/health").json())
        for c in COMMENTS:
            # 🔨 TODO: r = client.post("/api/moderate", json={"comment": c})
            #          print c and r.json()["action"] / ["overall_severity"] / ["categories"]
            r = client.post("/api/moderate", json={"comment": c})
            print(c)
            print(r.json()["action"])
            print(r.json()["overall_severity"])
            print(r.json()["categories"])


if __name__ == "__main__":
    main()
