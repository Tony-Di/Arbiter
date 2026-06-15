"""Persist an eval run as a committable artifact (the thing you screenshot / cite).

run_eval.py computes model_metrics (per-model, per-category P/R/F1 sweeps) + the
routing table, but only PRINTS them — the numbers die with the process. This dumps
them under eval/results/<date>/ so a run survives, diffs in git, and backs the
README table + the resume bullet. The committed routing_table.json stays the only
artifact that crosses into the product; this is eval-side reporting only.

Check:  python -m pytest tests/eval/test_report.py -v   (write these — e.g. 2 passed)
"""
import csv
import datetime
import json
import os

from arbiter.classify import ALL_6
from arbiter.eval.route import pick_operating_point

# the fields we keep from a chosen operating point (score_category's output)
_KEYS = ("precision", "recall", "f1", "cutoff", "tp", "fp", "fn")


def _op(sweep: dict, prefer_recall: bool) -> dict:
    """The chosen operating point, floats rounded for a clean diff."""
    point = pick_operating_point(sweep, prefer_recall)
    return {k: round(point[k], 4) if isinstance(point[k], float) else point[k] for k in _KEYS}


def dump_run(
    model_metrics: dict,
    table: dict,
    high_risk: set,
    n_scored: dict,
    results_root: str = "eval/results",
) -> str:
    """Write one run's metrics to eval/results/<today>/{metrics.json,metrics.csv}.

    Returns the metrics.json path. n_scored = {model_id: comments scored} — recorded
    so the "identical comments" claim is auditable: identical_comments is True only
    when every contestant was scored on the same count.
    """
    date = datetime.date.today().isoformat()
    out_dir = os.path.join(results_root, date)
    os.makedirs(out_dir, exist_ok=True)

    categories = {}
    for cat in ALL_6:
        categories[cat] = {
            "routed_to": table[cat]["model"],
            "threshold": table[cat]["threshold"],
            "models": {m: _op(model_metrics[m][cat], cat in high_risk) for m in model_metrics},
        }

    report = {
        "date": date,
        "n_scored": n_scored,
        "identical_comments": len(set(n_scored.values())) == 1,
        "categories": categories,
        "routing": table,
    }

    json_path = os.path.join(out_dir, "metrics.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    # flat one-row-per-(model, category) CSV — paste straight into the README table
    csv_path = os.path.join(out_dir, "metrics.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["category", "model", "precision", "recall", "f1", "cutoff", "routed"])
        for cat in ALL_6:
            for m, op in categories[cat]["models"].items():
                w.writerow([cat, m, op["precision"], op["recall"], op["f1"], op["cutoff"],
                            "yes" if m == table[cat]["model"] else ""])

    return json_path
