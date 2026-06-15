"""Bench: parallel specialist fan-out vs the naive sequential baseline.

Turns the resume claim "collapses 6 sequential LLM calls into 1 parallel round-trip"
into a real measured number. The product graph (product/graph.py) fans the 6
specialists out in parallel from START on a thread pool; the honest baseline is the
SAME 6 classify() calls run back-to-back. Same model + same endpoint for both arms,
so the ONLY variable is concurrency.

Methodology (bake these in so the number survives an interview):
  - Use a US-reachable, stable model (GPT) -- NOT SiliconFlow DeepSeek, or the China
    round-trip noise swamps the concurrency effect you're trying to isolate.
  - One warm-up comment first, discarded -- cold TLS/DNS skews the first call.
  - Interleave seq/par per comment (not all-seq-then-all-par) so any network drift
    over the run hits both arms equally.
  - Report the MEDIAN per-comment wall-clock (LLM latency is long-tailed; mean lies).
  - Record N. Expected shape: a ~6x ceiling minus overhead, bounded by the slowest
    of the 6 concurrent calls. Don't claim more than you measured.

Run:  .venv\\Scripts\\python scripts\\bench_latency.py
"""
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv

from arbiter.classify import ALL_6, classify

load_dotenv()

MODEL = "gpt-5.4-mini"          # reliable US endpoint; the one variable is concurrency
N = 20                          # comments to time after the warm-up; bump for a tighter median
SAMPLE = "data/jigsaw/sample.jsonl"


def sequential(comment: str) -> float:
    """Time the 6 specialist classify() calls run one after another. Return seconds."""
    t0 = time.perf_counter()
    for cat in ALL_6:
        classify(MODEL, comment, [cat])
    return time.perf_counter() - t0


def parallel(comment: str) -> float:
    """Time the 6 specialist classify() calls run concurrently -- mirrors graph.py's
    fan-out (same ThreadPoolExecutor idea as eval/collect.py). Return seconds."""
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=6) as ex:
        list(ex.map(lambda cat: classify(MODEL, comment, [cat]), ALL_6))
    return time.perf_counter() - t0


def main():
    with open(SAMPLE, encoding="utf-8") as f:
        comments = [json.loads(line)["comment"] for line in f][: N + 1]

    print(f"model={MODEL}  n={N}  (warming up, discarded)...")
    parallel(comments[0])  # cold TLS/DNS -- throw the first one away

    seq_times, par_times = [], []
    for i, c in enumerate(comments[1:], 1):
        s = sequential(c)        # interleaved: same comment, both arms, same drift
        p = parallel(c)
        seq_times.append(s)
        par_times.append(p)
        print(f"  [{i:>2}/{N}]  sequential {s:5.2f}s   parallel {p:5.2f}s")

    seq = statistics.median(seq_times)
    par = statistics.median(par_times)
    print(f"\nn={N}  median sequential {seq:.2f}s   parallel {par:.2f}s   ->   {seq / par:.1f}x faster")


if __name__ == "__main__":
    main()
