"""Bounded real-provider smoke check; never print credentials or raw responses."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from dotenv import load_dotenv

from arbiter.classify.registry import get_adapter, REGISTRY


def main() -> None:
    load_dotenv()
    results = []
    for model in ("gpt-5.4-mini", "deepseek-chat"):
        row = {"model": model, "provider_model": REGISTRY[model]["model"]}
        try:
            adapter = get_adapter(model)
            response = adapter.client.with_options(timeout=45, max_retries=0).chat.completions.create(
                model=adapter.model,
                messages=[{"role": "user", "content": 'Return only JSON: {"ready": true}'}],
                response_format={"type": "json_object"},
                temperature=0,
            )
            row["ready"] = json.loads(response.choices[0].message.content).get("ready") is True
        except Exception as exc:
            row.update(ready=False, error_type=type(exc).__name__,
                       status_code=getattr(exc, "status_code", None))
            body = getattr(exc, "body", None)
            if isinstance(body, dict):
                error = body.get("error", body)
                if isinstance(error, dict):
                    row["error_code"] = error.get("code")
        results.append(row)
        print(json.dumps(row), flush=True)
    destination = Path("eval/results/system_eval/readiness.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    with sqlite3.connect("file:arbiter.db?mode=ro", uri=True) as connection:
        print("precedent_sources:", connection.execute(
            "SELECT source, COUNT(*) FROM precedents GROUP BY source"
        ).fetchall())
    if not all(row["ready"] for row in results):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
