"""Run the accuracy eval across ALL contestant models, end-to-end.

Ties together the functions you wrote: collect -> sweep_category -> build_routing_table.
Loops every model in MODELS, scores each against the gold sample, then routes each
category to the best contestant. Produces routing_table.json + a per-model F1
comparison table.

Needs each contestant's API key in .env.  Run:  python scripts/run_eval.py
"""
import json
import os

from dotenv import load_dotenv

from arbiter.classify import ALL_6
from arbiter.classify.prompt import PROMPT_VERSION
from arbiter.classify.schema import SCHEMA_VERSION
from arbiter.eval.collect import cache_path, collect
from arbiter.eval.report import dump_run
from arbiter.eval.route import build_routing_table, pick_operating_point
from arbiter.eval.score import sweep_category

load_dotenv()

MODELS = ["deepseek-chat", "gpt-5.4-mini"]  # gemini dropped for now (free-tier 5 req/min); deepseek slow but works
SAMPLE = "data/jigsaw/sample.jsonl"  # the frozen 600-comment stratified Jigsaw sample
CACHE_DIR = "eval_cache"
HIGH_RISK = {"threat", "identity_hate"}


def _read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def sweeps_for(model: str, sample: list) -> tuple:
    """COLLECT (cached, resumable) + SCORE one model -> ({category: sweep}, n_scored)."""
    out = cache_path(CACHE_DIR, model, PROMPT_VERSION, SCHEMA_VERSION)
    n = collect(SAMPLE, out, model)
    print(f"  {model:14} collected {n} new predictions -> {out}")
    preds = {row["id"]: row["verdicts"] for row in _read_jsonl(out)}
    sweeps = {}
    for cat in ALL_6:
        gold, pred_sev = [], []
        for row in sample:
            if row["id"] in preds:
                gold.append(row["labels"][cat])
                # a model may omit a category -> treat a missing one as none (0)
                pred_sev.append(preds[row["id"]].get(cat, {"severity": 0})["severity"])
        sweeps[cat] = sweep_category(gold, pred_sev)
    n_scored = sum(1 for row in sample if row["id"] in preds)
    return sweeps, n_scored


def main():
    os.makedirs(CACHE_DIR, exist_ok=True)
    sample = _read_jsonl(SAMPLE)

    # 1. COLLECT + SCORE every contestant (cached -> re-runs cost no new API calls).
    print("collect + score:")
    collected = {m: sweeps_for(m, sample) for m in MODELS}
    model_metrics = {m: sw for m, (sw, _) in collected.items()}
    n_scored = {m: n for m, (_, n) in collected.items()}

    # 2. ROUTE: per category, pick the best contestant (recall for high-risk, else F1).
    table = build_routing_table(model_metrics, HIGH_RISK)
    with open("routing_table.json", "w", encoding="utf-8") as f:
        json.dump(table, f, indent=2)
    print("\nwrote routing_table.json")
    print(f"wrote {dump_run(model_metrics, table, HIGH_RISK, n_scored)}")

    # 3. Comparison: each model's F1 at its own chosen operating point; winner = routed model.
    print(f"\n{'category':15}" + "".join(f"{m:>15}" for m in MODELS) + f"{'-> routed':>15}")
    for cat in ALL_6:
        cells = "".join(
            f"{pick_operating_point(model_metrics[m][cat], cat in HIGH_RISK)['f1']:>15.2f}"
            for m in MODELS
        )
        print(f"{cat:15}{cells}{table[cat]['model']:>15}")


if __name__ == "__main__":
    main()
