"""Stratified sampling — pick a subset that doesn't starve rare categories.

Check:  python -m pytest tests/eval/test_sample.py -v   (goal: 3 passed)
"""
import random

from arbiter.classify import ALL_6


def stratified_select(rows: list[dict], n_target: int, min_per_category: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    chosen = {}
    for cat in ALL_6:
        positives = [r for r in rows if r["labels"][cat] == 1]
        rng.shuffle(positives)
        for r in positives[:min_per_category]: chosen[r["id"]] = r
    negatives = [r for r in rows if all(v == 0 for v in r["labels"].values())]
    rng.shuffle(negatives)
    for r in negatives:
        if len(chosen) >= n_target: break
        chosen[r["id"]] = r
    return list(chosen.values())