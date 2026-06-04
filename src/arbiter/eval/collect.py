"""Two-phase collect — call classify over a sample, cache raw outputs (resumable).

Check:  python -m pytest tests/eval/test_collect.py -v   (goal: 3 passed)
"""
import json
import os
from arbiter.classify import ALL_6, classify


def cache_path(cache_dir: str, model_id: str, prompt_version: str, schema_version: str) -> str:
    return f"{cache_dir}/{model_id}__p{prompt_version}__s{schema_version}.jsonl"


def load_done_ids(path: str) -> set:
    if not os.path.exists(path):
        return set()
    with open(path, "r") as f:
        return set(json.loads(line)["id"] for line in f)


def collect(sample_path: str, out_path: str, model_id: str, classify_fn=classify, categories=ALL_6) -> int:
    with open(sample_path, "r") as f:
        sample_rows = [json.loads(line) for line in f]
    done = load_done_ids(out_path)
    new = 0
    for row in sample_rows:
        if row["id"] not in done:
            result = classify_fn(model_id, row["comment"], categories)
            with open(out_path, "a") as f:
                f.write(json.dumps({"id": row["id"], "verdicts": result.model_dump(mode="json")["verdicts"]}) + "\n")
            new += 1
    return new