"""Build the frozen, stratified eval sample from the raw Jigsaw train.csv.

    train.csv  --load-->  rows {id, comment, labels}
               --stratified_select (YOUR fn)-->  ~N rows that don't starve rare cats
               --write-->  data/jigsaw/sample.jsonl   (the frozen sample run_eval reads)

Same comments for every model => a fair, reproducible comparison. Re-run with the
same SEED to reproduce it byte-for-byte.  Run:  python scripts/build_sample.py
"""
import csv
import json

from arbiter.classify import ALL_6
from arbiter.eval.sample import stratified_select

SRC = "data/jigsaw/train.csv"
OUT = "data/jigsaw/sample.jsonl"

# Cost / quality knobs — bigger = better stats but more API $ and time to collect.
N_TARGET = 600          # total comments in the sample
MIN_PER_CATEGORY = 100  # force >= this many positives per category (so rare 'threat' isn't starved)
SEED = 42               # fix the draw -> reproducible


def load_rows(path):
    """Jigsaw CSV -> [{id, comment, labels:{cat:0/1}}]. labels = the gold answer key."""
    rows = []
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append({
                "id": r["id"],
                "comment": r["comment_text"],
                "labels": {cat: int(r[cat]) for cat in ALL_6},
            })
    return rows


def main():
    rows = load_rows(SRC)
    print(f"loaded {len(rows)} rows from {SRC}")

    sample = stratified_select(rows, n_target=N_TARGET, min_per_category=MIN_PER_CATEGORY, seed=SEED)

    # ensure_ascii=True keeps the file pure-ASCII so collect.py (which open()s without an
    # explicit encoding) reads it safely on Windows.
    with open(OUT, "w", encoding="utf-8") as f:
        for row in sample:
            f.write(json.dumps(row) + "\n")
    print(f"wrote {len(sample)} comments -> {OUT}")

    print("\npositives per category in the frozen sample:")
    for cat in ALL_6:
        p = sum(1 for r in sample if r["labels"][cat] == 1)
        print(f"  {cat:14} {p}")


if __name__ == "__main__":
    main()
