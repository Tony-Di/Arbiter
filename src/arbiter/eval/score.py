"""Scoring — binarize the ordinal at a cutoff, compute P/R/F1, sweep the 3 cutoffs.

Fill the four functions (spec: plan Task 3).
Check:  python -m pytest tests/eval/test_score.py -v   (goal: 4 passed)
"""


def binarize(severity: int, cutoff: int) -> int:
    # 🔨 TODO: 1 if severity >= cutoff else 0
    return 1 if severity >= cutoff else 0


def prf(tp: int, fp: int, fn: int) -> dict:
    # 🔨 TODO: precision = tp/(tp+fp), recall = tp/(tp+fn), f1 = 2*tp/(2*tp+fp+fn)
    #          ANY zero denominator -> that value is 0.0 (never raise ZeroDivisionError)
    #          return {"precision": ..., "recall": ..., "f1": ...}
    
    precision = tp / (tp + fp) if tp + fp > 0 else 0.0
    recall = tp / (tp + fn) if tp + fn > 0 else 0.0
    f1 = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn > 0 else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def score_category(gold: list[int], pred_sev: list[int], cutoff: int) -> dict:
    # 🔨 TODO: binarize each pred_sev at cutoff; count tp/fp/fn against gold;
    #          return {"cutoff": cutoff, "tp": tp, "fp": fp, "fn": fn, **prf(tp, fp, fn)}
    
    pred_binary = [binarize(s, cutoff) for s in pred_sev]
    tp = sum(1 for g, p in zip(gold, pred_binary) if g == 1 and p == 1)
    fp = sum(1 for g, p in zip(gold, pred_binary) if g == 0 and p == 1)
    fn = sum(1 for g, p in zip(gold, pred_binary) if g == 1 and p == 0)
    return {"cutoff": cutoff, "tp": tp, "fp": fp, "fn": fn, **prf(tp, fp, fn)}

def sweep_category(gold: list[int], pred_sev: list[int]) -> dict:
    # 🔨 TODO: {c: score_category(gold, pred_sev, c) for c in (1, 2, 3)}
    return {c: score_category(gold, pred_sev, c) for c in (1, 2, 3)}
