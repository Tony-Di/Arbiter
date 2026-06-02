# Eval Harness (accuracy pipeline) — Implementation Plan

> **For the author:** scaffold-only, **tests are your target** (red → green). You hand-write every implementation body; I give signatures, specs, and full tests. Ping me when stuck.

**Goal:** Build the accuracy half of the eval harness — `sample → collect → score → route` — and prove it end-to-end on DeepSeek with a tiny sample, producing `routing_table.json`.

**Architecture:** A `src/arbiter/eval/` package of small, pure-where-possible functions sitting on top of `classify`. Two-phase: **collect** (call `classify` over a frozen sample, cache raw outputs to JSONL, resumable) then **score** (read cache, compute P/R/F1 via a threshold sweep — no API calls). **route** turns the per-model/per-category metrics into `routing_table.json`.

**Tech Stack:** Python 3.14 · stdlib only (`csv`, `json`, `random`) · `pytest`. **No new dependencies** (self-built, every line explainable — that's the selling point).

**Scope (this plan):** accuracy pipeline on DeepSeek, tiny sample. **Deferred to later plans:** fairness (FPR-gap on the Unintended-Bias subset), report polish, the full-size real-Jigsaw run, and the other 3 model families.

---

## Data contracts (every module agrees on these)

**Frozen sample** — `sample.jsonl`, one JSON object per line:
```json
{"id": "abc123", "comment": "you are an idiot", "labels": {"toxic": 1, "severe_toxic": 0, "obscene": 0, "threat": 0, "insult": 1, "identity_hate": 0}}
```
(`labels` = the Jigsaw 0/1 gold labels, one per category in `ALL_6`.)

**Predictions cache** — `eval_cache/<model_id>__p<PROMPT_VERSION>__s<SCHEMA_VERSION>.jsonl`, one per line:
```json
{"id": "abc123", "verdicts": {"toxic": {"severity": 2, "reason": "...", "span": "idiot"}, "...": {}}}
```

**Routing table** — `routing_table.json`:
```json
{"toxic": {"model": "deepseek-chat", "threshold": 2}, "...": {}}
```
`threshold` = the severity cutoff (1=≥low, 2=≥med, 3=≥high) chosen for that category.

---

## What I give vs. what you write

| I give | 🔨 You implement |
|---|---|
| eval package skeletons + this plan | `sample.py` — `stratified_select` |
| **All test files** (your targets) | `collect.py` — `cache_path`, `load_done_ids`, `collect` |
| tiny fixtures + the end-to-end runner shell | `score.py` — `binarize`, `prf`, `score_category`, `sweep_category` |
| `.gitignore` additions | `route.py` — `pick_operating_point`, `build_routing_table` |

git: every Commit is **run by you**. Messages provided.

---

## File structure (this plan)

```
arbiter/
  .gitignore                          # append: eval_cache/, routing_table.json? (NO — routing_table is committed)
  routing_table.json                  # produced by Task 5 (committed)
  src/arbiter/eval/
    __init__.py                       # I give (empty)
    sample.py                         # 🔨 you
    collect.py                        # 🔨 you
    score.py                          # 🔨 you
    route.py                          # 🔨 you
  tests/eval/                         # I give ALL
    __init__.py
    test_sample.py  test_collect.py  test_score.py  test_route.py
    fixtures/tiny_sample.jsonl        # I give (for the end-to-end run)
  scripts/run_eval.py                 # I give the shell; you fill the glue marked 🔨
```

---

## Task 0: eval package + gitignore

**Files:** Create `src/arbiter/eval/__init__.py` (empty), `tests/eval/__init__.py` (empty); append to `.gitignore`.

- [ ] **Step 1: create the two empty `__init__.py`**

- [ ] **Step 2: append to `.gitignore`**
```
eval_cache/
```
(Do NOT gitignore `routing_table.json` — it's the committed artifact that crosses eval → product.)

- [ ] **Step 3: confirm collection still works**
Run: `pytest -q`
Expected: the existing 20 classify tests still pass; new empty test dir collects nothing yet.

- [ ] **Step 4: Commit** *(you run)*
```
git add src/arbiter/eval tests/eval .gitignore
git commit -m "chore(eval): scaffold eval package"
```

---

## Task 1: 🔨 `sample.py` — stratified selection

**Files:** Create `src/arbiter/eval/sample.py` 🔨 · Test (given): `tests/eval/test_sample.py`

**Spec — export `stratified_select(rows, n_target, min_per_category, seed) -> list[dict]`:**
- `rows`: list of `{"id", "comment", "labels": {cat: 0|1}}`.
- Goal: a subset that guarantees **enough positives for every category** (rare ones like `threat` won't be starved), padded with negatives up to ~`n_target`.
- Algorithm:
  1. `import random; rng = random.Random(seed)` (deterministic).
  2. For each category in `ALL_6`: gather rows where `labels[cat] == 1`; shuffle with `rng`; take up to `min_per_category` of them. Collect all these into a set of chosen ids (a row positive for 2 categories counts once).
  3. Negatives = rows where every label is 0. Shuffle; add until `len(chosen) >= n_target` (or negatives run out).
  4. Return the chosen rows (dedup by `id`), as a list.
- Import `ALL_6` from `arbiter.classify`.

- [ ] **Step 1: the test is given — run, watch it fail**
```python
# tests/eval/test_sample.py
from arbiter.classify import ALL_6
from arbiter.eval.sample import stratified_select


def _row(i, **pos):
    labels = {c: 0 for c in ALL_6}
    for c in pos:
        labels[c] = 1
    return {"id": str(i), "comment": f"c{i}", "labels": labels}


def _make_rows():
    rows = []
    # 3 threats, 3 identity_hate, 40 toxic, 100 clean
    for i in range(3):
        rows.append(_row(f"thr{i}", threat=1))
    for i in range(3):
        rows.append(_row(f"idh{i}", identity_hate=1))
    for i in range(40):
        rows.append(_row(f"tox{i}", toxic=1))
    for i in range(100):
        rows.append(_row(f"clean{i}"))
    return rows


def test_rare_categories_are_not_starved():
    rows = _make_rows()
    sel = stratified_select(rows, n_target=50, min_per_category=2, seed=1)
    chosen = {r["id"] for r in sel}
    # every category with positives available must contribute >= min(available, 2)
    threat_pos = sum(1 for r in sel if r["labels"]["threat"] == 1)
    idh_pos = sum(1 for r in sel if r["labels"]["identity_hate"] == 1)
    assert threat_pos >= 2 and idh_pos >= 2


def test_is_deterministic_for_a_seed():
    rows = _make_rows()
    a = [r["id"] for r in stratified_select(rows, 50, 2, seed=7)]
    b = [r["id"] for r in stratified_select(rows, 50, 2, seed=7)]
    assert a == b


def test_no_duplicate_ids():
    rows = _make_rows()
    sel = stratified_select(rows, 50, 2, seed=1)
    ids = [r["id"] for r in sel]
    assert len(ids) == len(set(ids))
```
Run: `pytest tests/eval/test_sample.py -v` → Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 2: 🔨 implement `stratified_select`** to the spec + tests.

- [ ] **Step 3: run → green** (3 passed).

- [ ] **Step 4: Commit** *(you run)*
```
git add src/arbiter/eval/sample.py tests/eval/test_sample.py
git commit -m "feat(eval): stratified_select (no rare-category starvation)"
```

> The CSV loader (`freeze_sample(csv_path, out_path, ...)` that reads real Jigsaw `train.csv` and writes `sample.jsonl`) is a thin I/O wrapper around `stratified_select` — you'll add it when you have the Kaggle download. Not needed for the pipeline dev below (Task 5 uses a tiny fixture).

---

## Task 2: 🔨 `collect.py` — run classify → resumable JSONL cache

**Files:** Create `src/arbiter/eval/collect.py` 🔨 · Test (given): `tests/eval/test_collect.py`

**Spec — three functions:**
- `cache_path(cache_dir: str, model_id: str, prompt_version: str, schema_version: str) -> str`
  returns `f"{cache_dir}/{model_id}__p{prompt_version}__s{schema_version}.jsonl"`.
  (Versions in the name → change the prompt/schema and stale caches auto-separate.)
- `load_done_ids(path: str) -> set[str]`
  read the JSONL at `path`, return the set of `"id"` values already present. **Missing file → empty set** (don't crash).
- `collect(sample_path: str, out_path: str, model_id: str, classify_fn, categories=ALL_6) -> int`
  1. read the sample rows (JSONL).
  2. `done = load_done_ids(out_path)`.
  3. for each row whose `id` not in `done`: `result = classify_fn(model_id, row["comment"], categories)`; **append** one line `{"id": row["id"], "verdicts": result.model_dump(mode="json")["verdicts"]}` to `out_path`.
  4. return how many NEW predictions were written.
  - Inject `classify_fn` as a parameter (default `from arbiter.classify import classify`) so tests pass a fake — no network.
  - Import `ALL_6` from `arbiter.classify`.

- [ ] **Step 1: the test is given — run, watch it fail**
```python
# tests/eval/test_collect.py
import json
from arbiter.classify import ALL_6
from arbiter.classify.schema import ClassifyResult, Severity
from arbiter.eval.collect import cache_path, load_done_ids, collect


def _write_jsonl(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _fake_result():
    return ClassifyResult(verdicts={c: {"severity": Severity.none, "reason": "x", "span": None} for c in ALL_6})


def test_cache_path_encodes_versions():
    p = cache_path("eval_cache", "deepseek-chat", "1", "1")
    assert p == "eval_cache/deepseek-chat__p1__s1.jsonl"


def test_load_done_ids_missing_file_is_empty(tmp_path):
    assert load_done_ids(str(tmp_path / "nope.jsonl")) == set()


def test_collect_is_resumable(tmp_path):
    sample = tmp_path / "sample.jsonl"
    _write_jsonl(sample, [
        {"id": "a", "comment": "hi", "labels": {c: 0 for c in ALL_6}},
        {"id": "b", "comment": "yo", "labels": {c: 0 for c in ALL_6}},
    ])
    out = tmp_path / "out.jsonl"

    calls = []
    def fake_classify(model, comment, categories):
        calls.append(comment)
        return _fake_result()

    n1 = collect(str(sample), str(out), "deepseek-chat", fake_classify)
    assert n1 == 2 and len(calls) == 2

    n2 = collect(str(sample), str(out), "deepseek-chat", fake_classify)
    assert n2 == 0 and len(calls) == 2  # nothing re-called

    assert load_done_ids(str(out)) == {"a", "b"}
```
Run: `pytest tests/eval/test_collect.py -v` → Expected: FAIL.

- [ ] **Step 2: 🔨 implement `collect.py`** to the spec + tests.

- [ ] **Step 3: run → green** (3 passed).

- [ ] **Step 4: Commit** *(you run)*
```
git add src/arbiter/eval/collect.py tests/eval/test_collect.py
git commit -m "feat(eval): resumable collect with versioned cache"
```

---

## Task 3: 🔨 `score.py` — binarize + P/R/F1 + threshold sweep

**Files:** Create `src/arbiter/eval/score.py` 🔨 · Test (given): `tests/eval/test_score.py`

**Spec — four functions:**
- `binarize(severity: int, cutoff: int) -> int` → `1` if `severity >= cutoff` else `0`.
- `prf(tp: int, fp: int, fn: int) -> dict` → `{"precision": p, "recall": r, "f1": f}`, each a float; **any zero denominator → 0.0** (never divide by zero).
  - precision = tp/(tp+fp); recall = tp/(tp+fn); f1 = 2·tp/(2·tp+fp+fn).
- `score_category(gold: list[int], pred_sev: list[int], cutoff: int) -> dict`:
  binarize each `pred_sev` at `cutoff`; over the aligned `gold`/pred pairs count tp/fp/fn; return `{"cutoff": cutoff, "tp":, "fp":, "fn":, "precision":, "recall":, "f1":}`.
- `sweep_category(gold: list[int], pred_sev: list[int]) -> dict[int, dict]`:
  `{c: score_category(gold, pred_sev, c) for c in (1, 2, 3)}`.

- [ ] **Step 1: the test is given — run, watch it fail**
```python
# tests/eval/test_score.py
import pytest
from arbiter.eval.score import binarize, prf, score_category, sweep_category


def test_binarize():
    assert binarize(3, 2) == 1 and binarize(2, 2) == 1 and binarize(1, 2) == 0


def test_prf_zero_division_is_zero():
    assert prf(0, 0, 0) == {"precision": 0.0, "recall": 0.0, "f1": 0.0}


def test_score_category_hand_computed():
    gold = [1, 1, 0, 0, 1]
    pred_sev = [3, 1, 2, 0, 0]
    s = score_category(gold, pred_sev, cutoff=2)
    # pred binary at >=2: [1,0,1,0,0]; tp=1, fp=1, fn=2
    assert s["tp"] == 1 and s["fp"] == 1 and s["fn"] == 2
    assert s["precision"] == 0.5
    assert s["recall"] == pytest.approx(1 / 3)
    assert s["f1"] == pytest.approx(0.4)


def test_sweep_has_three_cutoffs():
    s = sweep_category([1, 0], [3, 0])
    assert set(s.keys()) == {1, 2, 3}
```
Run: `pytest tests/eval/test_score.py -v` → Expected: FAIL.

- [ ] **Step 2: 🔨 implement `score.py`** to the spec + tests.

- [ ] **Step 3: run → green** (4 passed).

- [ ] **Step 4: Commit** *(you run)*
```
git add src/arbiter/eval/score.py tests/eval/test_score.py
git commit -m "feat(eval): P/R/F1 scoring + threshold sweep"
```

---

## Task 4: 🔨 `route.py` — build the routing table

**Files:** Create `src/arbiter/eval/route.py` 🔨 · Test (given): `tests/eval/test_route.py`

**Spec — two functions:**
- `pick_operating_point(sweep: dict[int, dict], prefer_recall: bool) -> dict`:
  from a category's `sweep` (`{cutoff: metrics}`), pick ONE entry.
  - `prefer_recall=False`: the entry with the **highest f1** (tie → higher recall).
  - `prefer_recall=True`: the entry with the **highest recall** (tie → higher f1).
  - return that metrics dict (it already contains its `cutoff`).
- `build_routing_table(model_metrics: dict, high_risk: set[str]) -> dict`:
  `model_metrics` = `{model_id: {category: sweep}}`. For each category (use the keys of any model's metrics):
  1. for each model, `op = pick_operating_point(sweep, prefer_recall=(category in high_risk))`.
  2. choose the winning model: if `category in high_risk` → highest `op["recall"]`; else highest `op["f1"]`.
  3. record `{category: {"model": winner_id, "threshold": winner_op["cutoff"]}}`.
  return the full dict.

- [ ] **Step 1: the test is given — run, watch it fail**
```python
# tests/eval/test_route.py
from arbiter.eval.route import pick_operating_point, build_routing_table


def _m(cutoff, f1, recall):
    return {"cutoff": cutoff, "f1": f1, "recall": recall, "precision": 0.0, "tp": 0, "fp": 0, "fn": 0}


def test_pick_default_is_max_f1():
    sweep = {1: _m(1, 0.6, 0.9), 2: _m(2, 0.7, 0.6), 3: _m(3, 0.5, 0.3)}
    assert pick_operating_point(sweep, prefer_recall=False)["cutoff"] == 2


def test_pick_prefer_recall_is_max_recall():
    sweep = {1: _m(1, 0.6, 0.9), 2: _m(2, 0.7, 0.6), 3: _m(3, 0.5, 0.3)}
    assert pick_operating_point(sweep, prefer_recall=True)["cutoff"] == 1


def test_routing_default_picks_higher_f1_model():
    metrics = {
        "A": {"insult": {1: _m(1, 0.6, 0.9), 2: _m(2, 0.70, 0.6), 3: _m(3, 0.5, 0.3)}},
        "B": {"insult": {1: _m(1, 0.65, 0.95), 2: _m(2, 0.72, 0.5), 3: _m(3, 0.5, 0.3)}},
    }
    table = build_routing_table(metrics, high_risk=set())
    assert table["insult"] == {"model": "B", "threshold": 2}


def test_routing_high_risk_prefers_recall_over_f1():
    metrics = {
        "A": {"threat": {1: _m(1, 0.80, 0.85), 2: _m(2, 0.82, 0.70), 3: _m(3, 0.5, 0.3)}},
        "B": {"threat": {1: _m(1, 0.70, 0.95), 2: _m(2, 0.75, 0.80), 3: _m(3, 0.5, 0.3)}},
    }
    table = build_routing_table(metrics, high_risk={"threat"})
    # A has higher f1, but threat is high-risk -> B wins on recall (0.95 > 0.85)
    assert table["threat"] == {"model": "B", "threshold": 1}
```
Run: `pytest tests/eval/test_route.py -v` → Expected: FAIL.

- [ ] **Step 2: 🔨 implement `route.py`** to the spec + tests.

- [ ] **Step 3: run → green** (4 passed). Then the whole eval suite:
Run: `pytest tests/eval -v` → Expected: all green.

- [ ] **Step 4: Commit** *(you run)*
```
git add src/arbiter/eval/route.py tests/eval/test_route.py
git commit -m "feat(eval): routing table (F1 baseline + high-risk recall override)"
```

---

## Task 5: end-to-end run on DeepSeek (tiny sample)

**Files:** I give `tests/eval/fixtures/tiny_sample.jsonl` and the shell of `scripts/run_eval.py` (you fill the 🔨 glue).

> Proves the whole pipeline produces `routing_table.json` from real DeepSeek calls — without needing the Kaggle download. With one model, routing is degenerate (DeepSeek wins everything); the point is the machinery + a real artifact.

- [ ] **Step 1: I provide `tests/eval/fixtures/tiny_sample.jsonl`** — ~12 hand-labeled comments (a few clear positives per a few categories + clear negatives). (Ask me to drop this in when you reach this task.)

- [ ] **Step 2: fill the 🔨 glue in `scripts/run_eval.py`** (shell provided): load the fixture sample → `collect("deepseek-chat", ...)` → for each category gather `gold` + `pred_sev` across the sample → `sweep_category` → `build_routing_table({"deepseek-chat": {...}}, high_risk={"threat","identity_hate"})` → write `routing_table.json` + print a per-category P/R/F1 table.

- [ ] **Step 3: run it** (needs `DEEPSEEK_API_KEY` in `.env`)
```powershell
.\.venv\Scripts\python.exe scripts/run_eval.py
```
Expected: a printed per-category table + a `routing_table.json` at repo root mapping each category → `{"model": "deepseek-chat", "threshold": N}`.

- [ ] **Step 4: Commit** *(you run)*
```
git add scripts/run_eval.py tests/eval/fixtures/tiny_sample.jsonl routing_table.json
git commit -m "feat(eval): end-to-end accuracy pipeline on DeepSeek (tiny sample)"
```

---

## Definition of done (this plan)
- `pytest tests/eval -v` fully green (no network).
- `python scripts/run_eval.py` produces `routing_table.json` from real DeepSeek calls on the tiny sample.

## Next increments (NOT this plan)
- `freeze_sample()` from the real Jigsaw `train.csv` (Kaggle) → real-size stratified sample → real numbers.
- Add Gemini (compat endpoint) + Claude (own `anthropic.py` adapter) → re-`collect` → meaningful cross-model routing.
- **Fairness** (`fairness.py`): per-identity-group FPR + gap on the Unintended-Bias subset.
- `report.py`: render the model-comparison table for the README / demo page.
