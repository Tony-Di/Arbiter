"""Two-phase collect — call classify over a sample, cache raw outputs (resumable).

Fill the three functions (spec: plan Task 2).
Check:  python -m pytest tests/eval/test_collect.py -v   (goal: 3 passed)
"""
import json
import os
from arbiter.classify import ALL_6, classify


def cache_path(cache_dir: str, model_id: str, prompt_version: str, schema_version: str) -> str:
    # 🔨 TODO: return f"{cache_dir}/{model_id}__p{prompt_version}__s{schema_version}.jsonl"
    
    return f"{cache_dir}/{model_id}__p{prompt_version}__s{schema_version}.jsonl"


def load_done_ids(path: str) -> set:
    # 🔨 TODO: read the JSONL at `path`; return the set of obj["id"] for every line.
    #          If the file does not exist -> return set()  (don't crash).
    if not os.path.exists(path):
        return set()
    with open(path, "r") as f:
        return set(json.loads(line)["id"] for line in f)


def collect(sample_path: str, out_path: str, model_id: str, classify_fn=classify, categories=ALL_6) -> int:
    # 🔨 TODO:
    #   1. read sample rows (one JSON object per line of sample_path)
    #   2. done = load_done_ids(out_path)
    #   3. new = 0
    #      for each row whose row["id"] not in done:
    #          result = classify_fn(model_id, row["comment"], categories)
    #          append ONE line to out_path:
    #              {"id": row["id"], "verdicts": result.model_dump(mode="json")["verdicts"]}
    #          new += 1
    #   4. return new
    
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