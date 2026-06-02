"""Run the accuracy eval pipeline end-to-end on DeepSeek over the tiny fixture.

Ties together the functions you wrote:  collect -> sweep_category -> build_routing_table.
Produces routing_table.json + prints a per-category P/R/F1 table.

Needs DEEPSEEK_API_KEY in .env.  Run:  python scripts/run_eval.py
"""
import json
import os

from dotenv import load_dotenv

from arbiter.classify import ALL_6
from arbiter.classify.prompt import PROMPT_VERSION
from arbiter.classify.schema import SCHEMA_VERSION
from arbiter.eval.collect import cache_path, collect
from arbiter.eval.route import build_routing_table
from arbiter.eval.score import sweep_category

load_dotenv()

MODEL = "deepseek-chat"
SAMPLE = "tests/eval/fixtures/tiny_sample.jsonl"
CACHE_DIR = "eval_cache"
HIGH_RISK = {"threat", "identity_hate"}


def _read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def main():
    # 1. COLLECT: call classify over every sample comment, cache raw outputs.
    #    Resumable — rerun and it re-uses the cache (no new API spend).
    os.makedirs(CACHE_DIR, exist_ok=True)
    out = cache_path(CACHE_DIR, MODEL, PROMPT_VERSION, SCHEMA_VERSION)
    n = collect(SAMPLE, out, MODEL)
    print(f"collected {n} new predictions -> {out}")

    # 2. Load gold labels (sample) and predictions (cache), keyed by id.
    sample = _read_jsonl(SAMPLE)
    preds = {row["id"]: row["verdicts"] for row in _read_jsonl(out)}

    # 3. SCORE: per category, line up gold (0/1) with predicted severity (0-3),
    #    then sweep the 3 thresholds.
    sweeps = {}
    for cat in ALL_6:
        gold, pred_sev = [], []
        for row in sample:
            if row["id"] in preds:
                gold.append(row["labels"][cat])
                pred_sev.append(preds[row["id"]][cat]["severity"])
        sweeps[cat] = sweep_category(gold, pred_sev)

    # 4. ROUTE: one model here, so it wins every category — but the machinery runs
    #    and writes the artifact the product will read.
    table = build_routing_table({MODEL: sweeps}, HIGH_RISK)
    with open("routing_table.json", "w", encoding="utf-8") as f:
        json.dump(table, f, indent=2)
    print("wrote routing_table.json")

    # 5. Print the per-category P/R/F1 at each category's chosen threshold.
    print(f"\n{'category':16}{'thr':>4}{'P':>7}{'R':>7}{'F1':>7}")
    for cat in ALL_6:
        thr = table[cat]["threshold"]
        m = sweeps[cat][thr]
        print(f"{cat:16}{thr:>4}{m['precision']:>7.2f}{m['recall']:>7.2f}{m['f1']:>7.2f}")


if __name__ == "__main__":
    main()
