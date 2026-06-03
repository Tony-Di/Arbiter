# Product Pipeline (LangGraph) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **For the author:** scaffold-only, **tests are your target** (red → green). You hand-write every implementation body; I give signatures, specs, and full tests. The LangGraph wiring (Task 1 + 6) gets fuller hints because the framework is new to this repo. Ping me when stuck. Every `git` Commit is **run by you** — messages provided.

**Goal:** Build the run-time product pipeline (spec §9) — a LangGraph DAG that fans out 6 specialist `classify` calls in parallel + a context/sarcasm node emitting modifier flags, then a **deterministic** aggregator turns raw verdicts + flags into an overall severity + action — and prove it end-to-end on DeepSeek.

**Architecture:** A new `src/arbiter/product/` package sitting on top of `classify` and consuming the committed `routing_table.json`. **LLMs judge; code decides policy** (spec §9): the 6 specialists and the context node are the only LLM calls; the aggregator is pure deterministic Python (no LLM), so the product never silently diverges from the eval numbers. The graph is built by a factory that accepts injectable `classify_fn` / `detect_fn`, so the whole pipeline is unit-testable with **zero network**.

**Tech Stack:** Python 3.14 · **LangGraph** (new dep) · `pydantic` (already in) · `pytest`. The aggregator + routing use stdlib only.

**Scope (this plan):** the `product/` package = `state` / `routing` / `aggregator` / `context` / `nodes` / `graph`, plus a DeepSeek end-to-end smoke. **Deferred to P5 (NOT this plan):** FastAPI (`api/main.py`), Postgres persistence (`api/db.py`, spec §11), and the Next.js frontend (spec §13). This plan's deliverable is a compiled graph you can `.invoke({"comment": ...})` and get a verdict back.

---

## Open decisions resolved in this plan (confirm during review)

The spec left these to "the implementation plan" — defaults chosen, easy to change:

1. **`threshold` from `routing_table.json` is NOT used to gate the product in v1.** Spec §6.5 says whether the product uses the eval threshold "vs. acting on the raw ordinal" is deferred here. **Decision:** the product acts on the **raw ordinal severity** (spec §5.1: "the same ordinal *is* the displayed severity"). `threshold` is read and kept in `routing_snapshot` for provenance/auditing, but the aggregator's `high/medium` action rule runs on the raw (then modifier-adjusted) ordinal. Simpler, and keeps product severity == displayed severity.
2. **Context/sarcasm node uses `CONTEXT_MODEL = "deepseek-chat"`** (the only paid model on the budget plan). Kept as a module constant so a stronger reasoning model can be swapped in later (the "optional design note" in NOTES.md) with a one-line change.
3. **Downgrade set is exactly `{toxic, obscene, insult, identity_hate}`** per spec §9(c) — note `severe_toxic` and `threat` are deliberately NOT downgraded by sarcasm/quotation/reclaimed-slur flags.

---

## Data contracts (every module agrees on these)

**`routing_table.json`** (already committed, produced by the eval plan):
```json
{"toxic": {"model": "deepseek-chat", "threshold": 1}, "...": {}}
```

**LangGraph state** — `ModerationState` (a `TypedDict`); parallel writers need a reducer:
```python
{
  "comment": "you are an idiot",
  "raw_verdicts": {"toxic": {"severity": 2, "reason": "...", "span": "idiot"}, "...": {}},  # written by the 6 specialists (parallel -> reducer)
  "routing_snapshot": {"toxic": "deepseek-chat", "...": "..."},                              # written by the 6 specialists (parallel -> reducer)
  "context_flags": {"sarcasm": false, "quotation": false, "reclaimed_slur": false,
                    "direct_threat": false, "ambiguity": false, "note": null},              # written by the context node (single writer)
  "effective_verdicts": {"toxic": 1, "...": 0},                                             # per-category severity AFTER deterministic adjustment (aggregator)
  "overall_severity": 1,                                                                    # max across effective (aggregator)
  "action": "human-review"                                                                  # remove | human-review | allow (aggregator)
}
```

**`ContextFlags`** (Pydantic, the context node's structured output):
```json
{"sarcasm": false, "quotation": false, "reclaimed_slur": false,
 "direct_threat": false, "ambiguity": false, "note": null}
```

---

## What I give vs. what you write

| I give | 🔨 You implement |
|---|---|
| this plan + all module skeletons | `routing.py` — `load_routing_table`, `model_for` |
| **all test files** (your red→green targets) | `aggregator.py` — `adjust_severities`, `decide_action`, `overall_severity`, `aggregate` |
| `pyproject.toml` dep line + install command | `context.py` — `build_context_prompt`, `detect_context` |
| the LangGraph wiring spelled out as hints | `nodes.py` — `make_specialist_node`, `make_context_node`, `aggregator_node` |
| the DeepSeek smoke script shell | `state.py` + `graph.py` — `merge_verdicts`, `build_graph` (you type the wiring from the hints) |

---

## File structure (this plan)

```
arbiter/
  pyproject.toml                       # +langgraph dependency
  src/arbiter/product/
    __init__.py                        # I give (re-exports build_graph)
    state.py                           # 🔨 ModerationState + merge_verdicts reducer
    routing.py                         # 🔨 load_routing_table, model_for
    aggregator.py                      # 🔨 the deterministic policy (the heart)
    context.py                         # 🔨 ContextFlags + detect_context (LLM)
    nodes.py                           # 🔨 specialist / context / aggregator node funcs
    graph.py                           # 🔨 build_graph factory (LangGraph wiring)
  tests/product/                       # I give ALL
    __init__.py
    test_state.py  test_routing.py  test_aggregator.py
    test_context.py  test_nodes.py  test_graph.py
  scripts/smoke_moderate.py            # I give shell; you fill the 🔨 glue
```

---

## Task 0: add LangGraph + scaffold the `product` package

**Files:** Modify `pyproject.toml`; Create `src/arbiter/product/__init__.py`, `tests/product/__init__.py`.

- [ ] **Step 1: add the dependency** to `pyproject.toml` (the `dependencies` list):
```toml
dependencies = ["pydantic>=2.7", "openai>=1.40", "python-dotenv>=1.0", "langgraph>=0.2"]
```

- [ ] **Step 2: install it into the venv**

Run: `.\.venv\Scripts\python.exe -m pip install -e ".[dev]"`
Expected: resolves and installs `langgraph` (+ its `langchain-core` dependency).

> ⚠️ **Python 3.14 wheel risk.** LangGraph pulls in `langchain-core`. If either fails to build/install on 3.14, first try upgrading (`pip install -U langgraph`) — a newer release usually has 3.14 wheels. Do **not** silently drop LangGraph for plain `asyncio`: the spec locks LangGraph as the orchestration résumé signal. If genuinely blocked, stop and tell me — that's a real decision, not a workaround.

- [ ] **Step 3: create the two `__init__.py`**

`src/arbiter/product/__init__.py` (re-export added in Task 6 — start empty):
```python
# Re-export added in Task 6.
```
`tests/product/__init__.py`: empty.

- [ ] **Step 4: confirm the existing suite still collects + passes**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: the existing **34** tests still pass (20 classify + 14 eval); the new empty `tests/product/` collects nothing yet. *(Already verified: langgraph 1.2.4 installs cleanly on 3.14 and the 34-test baseline is green.)*

- [ ] **Step 5: Commit** *(you run)*
```
git add pyproject.toml src/arbiter/product/__init__.py tests/product/__init__.py
git commit -m "chore(product): add langgraph dep + scaffold product package"
```

---

## Task 1: 🔨 `state.py` — graph state + parallel-write reducer

**Files:** Create `src/arbiter/product/state.py` 🔨 · Test (given): `tests/product/test_state.py`

> The #1 LangGraph gotcha: when **multiple nodes run in parallel and write the same state key**, LangGraph raises `InvalidUpdateError` unless that key has a **reducer**. Our 6 specialist nodes all write `raw_verdicts` and `routing_snapshot` in parallel, so those two keys are annotated with a dict-merge reducer. This test doubles as a smoke test that the installed LangGraph's `StateGraph` / `START` / `END` / reducer API behaves as the rest of the plan assumes.

**Spec — export `merge_verdicts`, `ModerationState`, `initial_state`:**
- `merge_verdicts(a: dict, b: dict) -> dict` → a new dict merging both (`{**a, **b}`); `b` wins key conflicts.
- `ModerationState` = a `TypedDict` with the fields below; `raw_verdicts` and `routing_snapshot` are `Annotated[dict, merge_verdicts]`, the rest are plain.
- `initial_state(comment: str) -> dict` → `{"comment": comment, "raw_verdicts": {}, "routing_snapshot": {}}`. **Why:** verified on the installed `langgraph 1.2.4` that seeding the reducer channels is **not strictly required** (`invoke({"comment": ...})` works) — but `initial_state()` keeps caller intent explicit, matches LangGraph's documented fan-out/fan-in pattern, and stays robust if the reducer or version changes. Callers (tests, the smoke script, P5's FastAPI) use `graph.invoke(initial_state(comment))`.

- [ ] **Step 1: the test is given — run, watch it fail**
```python
# tests/product/test_state.py
from typing import Annotated, TypedDict

from langgraph.graph import START, END, StateGraph

from arbiter.product.state import ModerationState, merge_verdicts


def test_merge_verdicts_unions_and_b_wins_conflicts():
    assert merge_verdicts({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}
    assert merge_verdicts({"a": 1}, {"a": 9}) == {"a": 9}


def test_merge_verdicts_does_not_mutate_inputs():
    a = {"a": 1}
    merge_verdicts(a, {"b": 2})
    assert a == {"a": 1}


def test_parallel_nodes_merge_into_one_dict():
    # Two nodes fan out from START in parallel, each writing ONE key into the same
    # reducer-annotated dict. Without the reducer this raises InvalidUpdateError.
    class S(TypedDict):
        bag: Annotated[dict, merge_verdicts]

    def node_a(state):
        return {"bag": {"a": 1}}

    def node_b(state):
        return {"bag": {"b": 2}}

    g = StateGraph(S)
    g.add_node("a", node_a)
    g.add_node("b", node_b)
    g.add_edge(START, "a")
    g.add_edge(START, "b")
    g.add_edge("a", END)
    g.add_edge("b", END)
    out = g.compile().invoke({"bag": {}})
    assert out["bag"] == {"a": 1, "b": 2}


def test_state_has_expected_keys():
    assert set(ModerationState.__annotations__) == {
        "comment", "raw_verdicts", "routing_snapshot",
        "context_flags", "effective_verdicts", "overall_severity", "action",
    }


def test_initial_state_seeds_reducer_channels():
    from arbiter.product.state import initial_state
    s = initial_state("hello")
    assert s == {"comment": "hello", "raw_verdicts": {}, "routing_snapshot": {}}
```
Run: `.\.venv\Scripts\python.exe -m pytest tests/product/test_state.py -v`
Expected: FAIL (`ModuleNotFoundError: arbiter.product.state`).

- [ ] **Step 2: 🔨 implement `state.py`.** Skeleton to fill:
```python
"""Graph state for the product pipeline + the reducer parallel writers need.

Fill the TODOs (spec: plan Task 1).
Check:  .\.venv\Scripts\python.exe -m pytest tests/product/test_state.py -v   (goal: 4 passed)
"""
from typing import Annotated, TypedDict


def merge_verdicts(a: dict, b: dict) -> dict:
    # 🔨 TODO: return a NEW dict merging a and b; b wins on key conflicts.
    #   Hint: {**a, **b}  (do NOT mutate a or b)
    ...


class ModerationState(TypedDict, total=False):
    # 🔨 TODO: declare the fields. The two written by parallel specialist nodes
    #   MUST use the reducer; the rest are plain:
    #     comment: str
    #     raw_verdicts: Annotated[dict, merge_verdicts]
    #     routing_snapshot: Annotated[dict, merge_verdicts]
    #     context_flags: dict
    #     effective_verdicts: dict
    #     overall_severity: int
    #     action: str
    ...


def initial_state(comment: str) -> dict:
    # 🔨 TODO: seed the reducer channels so callers don't have to:
    #   return {"comment": comment, "raw_verdicts": {}, "routing_snapshot": {}}
    ...
```

- [ ] **Step 3: run → green** (5 passed). If `test_parallel_nodes_merge_into_one_dict` raises `InvalidUpdateError`, your reducer annotation isn't being applied — re-check the `Annotated[dict, merge_verdicts]` on `bag`/`raw_verdicts`.

- [ ] **Step 4: Commit** *(you run)*
```
git add src/arbiter/product/state.py tests/product/test_state.py
git commit -m "feat(product): graph state + parallel-write reducer"
```

---

## Task 2: 🔨 `routing.py` — load the routing table

**Files:** Create `src/arbiter/product/routing.py` 🔨 · Test (given): `tests/product/test_routing.py`

**Spec — two functions:**
- `load_routing_table(path: str = "routing_table.json") -> dict` → read the JSON file, return the dict `{category: {"model": str, "threshold": int}}`.
- `model_for(table: dict, category: str) -> str` → `table[category]["model"]` (plain lookup; `KeyError` on an unknown category is fine — it signals a missing routing entry loudly).

- [ ] **Step 1: the test is given — run, watch it fail**
```python
# tests/product/test_routing.py
import json

from arbiter.classify import ALL_6
from arbiter.product.routing import load_routing_table, model_for


def test_load_real_committed_table_has_all_6():
    table = load_routing_table("routing_table.json")
    assert set(table) == set(ALL_6)
    for cat in ALL_6:
        assert "model" in table[cat] and "threshold" in table[cat]


def test_model_for_returns_routed_model(tmp_path):
    p = tmp_path / "rt.json"
    p.write_text(json.dumps({"toxic": {"model": "gpt-4o-mini", "threshold": 2}}), encoding="utf-8")
    table = load_routing_table(str(p))
    assert model_for(table, "toxic") == "gpt-4o-mini"
```

Run: `.\.venv\Scripts\python.exe -m pytest tests/product/test_routing.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 2: 🔨 implement `routing.py`.** Skeleton:
```python
"""Load routing_table.json — the only artifact crossing eval -> product.

Fill the TODOs (spec: plan Task 2).
Check:  .\.venv\Scripts\python.exe -m pytest tests/product/test_routing.py -v   (goal: 2 passed)
"""
import json


def load_routing_table(path: str = "routing_table.json") -> dict:
    # 🔨 TODO: open(path) -> json.load -> return the dict.
    ...


def model_for(table: dict, category: str) -> str:
    # 🔨 TODO: return table[category]["model"]
    ...
```

- [ ] **Step 3: run → green** (2 passed).

- [ ] **Step 4: Commit** *(you run)*
```
git add src/arbiter/product/routing.py tests/product/test_routing.py
git commit -m "feat(product): load routing table"
```

---

## Task 3: 🔨 `aggregator.py` — the deterministic policy (the heart)

**Files:** Create `src/arbiter/product/aggregator.py` 🔨 · Test (given): `tests/product/test_aggregator.py`

> This is the most important module: **policy in code, no LLM** (spec §9c). It must be a pure function of `(raw severities, context flags)` so the product's deviation from the raw classifier is fully explainable. Spec §9(c) is the exact source of truth for every rule below.

**Spec — four functions:**

- `adjust_severities(raw_sev: dict[str, int], flags: dict) -> dict[str, int]`
  Returns a NEW dict of adjusted severities. Rules (spec §9c step 1):
  - `DOWNGRADE_CATS = {"toxic", "obscene", "insult", "identity_hate"}` (module constant).
  - If `flags.get("sarcasm") or flags.get("quotation") or flags.get("reclaimed_slur")`: for each category in `DOWNGRADE_CATS`, `new = max(0, raw_sev[cat] - 1)` (floor at `none`/0).
  - If `flags.get("direct_threat")`: `threat = max(raw_sev.get("threat", 0), 3)` (upgrade to at least `high`).
  - Every other category / no-flag → severity unchanged.
  - (Apply the downgrade first, then the threat upgrade. They touch disjoint categories, so order is safe — but be explicit.)

- `decide_action(effective: dict[str, int], flags: dict) -> str`
  On the **adjusted** severities (spec §9c step 2):
  - any value `>= 3` → `"remove"`
  - else any value `>= 2` → `"human-review"`
  - else → `"allow"`
  - **Safety override:** if `flags.get("ambiguity")` AND any value `>= 1` AND the action so far is `"allow"` → return `"human-review"` (never auto-allow a flagged gray case).

- `overall_severity(effective: dict[str, int]) -> int`
  `max(effective.values())` (return `0` if empty).

- `aggregate(raw_verdicts: dict, flags: dict) -> dict`
  Top-level entry point the aggregator node calls:
  1. `raw_sev = {cat: v["severity"] for cat, v in raw_verdicts.items()}`
  2. `eff = adjust_severities(raw_sev, flags)`
  3. return `{"effective_verdicts": eff, "overall_severity": overall_severity(eff), "action": decide_action(eff, flags)}`

- [ ] **Step 1: the test is given — run, watch it fail**
```python
# tests/product/test_aggregator.py
from arbiter.product.aggregator import (
    adjust_severities,
    decide_action,
    overall_severity,
    aggregate,
)

NO_FLAGS = {"sarcasm": False, "quotation": False, "reclaimed_slur": False,
            "direct_threat": False, "ambiguity": False, "note": None}


def _sev(**kw):
    base = {"toxic": 0, "severe_toxic": 0, "obscene": 0, "threat": 0, "insult": 0, "identity_hate": 0}
    base.update(kw)
    return base


# --- adjust_severities ---

def test_sarcasm_downgrades_the_four_but_not_severe_or_threat():
    raw = _sev(toxic=2, obscene=2, insult=2, identity_hate=2, severe_toxic=2, threat=2)
    eff = adjust_severities(raw, {**NO_FLAGS, "sarcasm": True})
    assert eff["toxic"] == 1 and eff["obscene"] == 1 and eff["insult"] == 1 and eff["identity_hate"] == 1
    assert eff["severe_toxic"] == 2  # NOT in the downgrade set
    assert eff["threat"] == 2        # NOT in the downgrade set


def test_downgrade_floors_at_zero():
    raw = _sev(toxic=0)
    eff = adjust_severities(raw, {**NO_FLAGS, "quotation": True})
    assert eff["toxic"] == 0


def test_direct_threat_upgrades_threat_to_high():
    raw = _sev(threat=1)
    eff = adjust_severities(raw, {**NO_FLAGS, "direct_threat": True})
    assert eff["threat"] == 3


def test_no_flags_leaves_severities_unchanged():
    raw = _sev(toxic=2, threat=1)
    assert adjust_severities(raw, NO_FLAGS) == raw


# --- decide_action ---

def test_action_remove_when_any_high():
    assert decide_action(_sev(threat=3), NO_FLAGS) == "remove"


def test_action_human_review_when_max_medium():
    assert decide_action(_sev(insult=2), NO_FLAGS) == "human-review"


def test_action_allow_when_all_low_or_none():
    assert decide_action(_sev(toxic=1), NO_FLAGS) == "allow"


def test_ambiguity_override_escalates_allow_to_human_review():
    # toxic=1 -> would be "allow"; ambiguity set + a flagged (>=low) category -> escalate
    assert decide_action(_sev(toxic=1), {**NO_FLAGS, "ambiguity": True}) == "human-review"


def test_ambiguity_override_does_not_fire_when_nothing_flagged():
    assert decide_action(_sev(), {**NO_FLAGS, "ambiguity": True}) == "allow"


# --- overall_severity ---

def test_overall_is_max():
    assert overall_severity(_sev(toxic=1, threat=3, insult=2)) == 3


def test_overall_empty_is_zero():
    assert overall_severity({}) == 0


# --- aggregate (end-to-end of the deterministic policy) ---

def test_aggregate_sarcastic_insult_is_allowed():
    raw_verdicts = {
        "insult": {"severity": 2, "reason": "name-calling", "span": "idiot"},
        "toxic": {"severity": 1, "reason": "rude", "span": None},
    }
    out = aggregate(raw_verdicts, {**NO_FLAGS, "sarcasm": True})
    # insult 2->1, toxic 1->0 ; max severity 1 ; action allow
    assert out["effective_verdicts"]["insult"] == 1
    assert out["overall_severity"] == 1
    assert out["action"] == "allow"


def test_aggregate_direct_threat_forces_remove():
    raw_verdicts = {"threat": {"severity": 1, "reason": "maybe hyperbole", "span": "kill"}}
    out = aggregate(raw_verdicts, {**NO_FLAGS, "direct_threat": True})
    assert out["effective_verdicts"]["threat"] == 3
    assert out["action"] == "remove"
```

Run: `.\.venv\Scripts\python.exe -m pytest tests/product/test_aggregator.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 2: 🔨 implement `aggregator.py`.** Skeleton:
```python
"""Deterministic aggregator — policy in code, NO LLM (spec §9c).

Turns raw per-category severities + context flags into effective severities,
an overall severity, and an action. Pure functions -> trivially testable +
fully auditable (this is the policy deliberately kept OUT of classify).

Fill the TODOs (spec: plan Task 3).
Check:  .\.venv\Scripts\python.exe -m pytest tests/product/test_aggregator.py -v   (goal: 13 passed)
"""

DOWNGRADE_CATS = {"toxic", "obscene", "insult", "identity_hate"}


def adjust_severities(raw_sev: dict, flags: dict) -> dict:
    # 🔨 TODO (return a NEW dict; don't mutate raw_sev):
    #   eff = dict(raw_sev)
    #   if sarcasm OR quotation OR reclaimed_slur:
    #       for cat in DOWNGRADE_CATS that are present: eff[cat] = max(0, eff[cat] - 1)
    #   if direct_threat: eff["threat"] = max(eff.get("threat", 0), 3)
    #   return eff
    ...


def decide_action(effective: dict, flags: dict) -> str:
    # 🔨 TODO:
    #   sevs = effective.values()
    #   action = "remove" if any(s>=3) else "human-review" if any(s>=2) else "allow"
    #   if flags.get("ambiguity") and any(s>=1) and action == "allow": action = "human-review"
    #   return action
    ...


def overall_severity(effective: dict) -> int:
    # 🔨 TODO: max(effective.values()) or 0 if empty.
    ...


def aggregate(raw_verdicts: dict, flags: dict) -> dict:
    # 🔨 TODO:
    #   raw_sev = {cat: v["severity"] for cat, v in raw_verdicts.items()}
    #   eff = adjust_severities(raw_sev, flags)
    #   return {"effective_verdicts": eff,
    #           "overall_severity": overall_severity(eff),
    #           "action": decide_action(eff, flags)}
    ...
```

- [ ] **Step 3: run → green** (13 passed).

- [ ] **Step 4: Commit** *(you run)*
```
git add src/arbiter/product/aggregator.py tests/product/test_aggregator.py
git commit -m "feat(product): deterministic aggregator (modifiers + action rules)"
```

---

## Task 4: 🔨 `context.py` — context/sarcasm node (LLM, modifiers only)

**Files:** Create `src/arbiter/product/context.py` 🔨 · Test (given): `tests/product/test_context.py`

> The context node emits **modifier flags only** — it does NOT re-score severity (spec §9b). `detect_context` mirrors `classify`'s shape exactly: `get_adapter` → `complete(prompt, ContextFlags)` → validate → retry once. The test mocks `get_adapter` in this module's namespace with a scripted adapter (same technique as `tests/classify/test_core.py`).

**Spec:**
- `ContextFlags(BaseModel)` with fields: `sarcasm: bool = False`, `quotation: bool = False`, `reclaimed_slur: bool = False`, `direct_threat: bool = False`, `ambiguity: bool = False`, `note: str | None = None`.
- `CONTEXT_MODEL = "deepseek-chat"` (module constant; swappable later).
- `build_context_prompt(comment: str) -> str` → one string instructing the model to read the comment and decide the 5 booleans (definitions below) + an optional one-line `note`, returning **JSON** shaped like `ContextFlags`. The word **"json"** MUST appear (DeepSeek's `json_object` mode requires it). Flag definitions to embed verbatim:
  - `sarcasm` — the harmful-looking text is a joke / not literal.
  - `quotation` — the slur/threat is quoted, not asserted by the author.
  - `reclaimed_slur` — an in-group reclaimed term, not an attack.
  - `direct_threat` — a credible, directed threat (not hyperbole).
  - `ambiguity` — genuinely unclear; needs a human.
- `detect_context(comment: str, model: str = CONTEXT_MODEL) -> ContextFlags`:
  - `adapter = get_adapter(model)`; `prompt = build_context_prompt(comment)`.
  - Try up to **twice**: `raw = adapter.complete(prompt, ContextFlags)`; `return ContextFlags.model_validate(raw)`. On exception, remember it and retry once; after the second failure, `raise` the remembered error. (Same retry shape as `classify`.)

- [ ] **Step 1: the test is given — run, watch it fail**
```python
# tests/product/test_context.py
from unittest.mock import patch

import pytest

from arbiter.product.context import ContextFlags, build_context_prompt, detect_context


class _ScriptedAdapter:
    def __init__(self, *payloads):
        self._q = list(payloads)

    def complete(self, prompt, schema):
        item = self._q.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_prompt_mentions_json_and_the_comment():
    p = build_context_prompt("I'll kill you 😂")
    assert "json" in p.lower()
    assert "I'll kill you 😂" in p


def test_context_flags_defaults_are_false_none():
    f = ContextFlags()
    assert f.sarcasm is False and f.ambiguity is False and f.note is None


def test_detect_context_returns_validated_flags():
    payload = {"sarcasm": True, "quotation": False, "reclaimed_slur": False,
               "direct_threat": False, "ambiguity": False, "note": "joke between friends"}
    with patch("arbiter.product.context.get_adapter", return_value=_ScriptedAdapter(payload)):
        f = detect_context("I'll kill you 😂")
    assert isinstance(f, ContextFlags) and f.sarcasm is True and f.note == "joke between friends"


def test_detect_context_retries_once_then_succeeds():
    bad = {"sarcasm": "not-a-bool"}  # fails validation
    good = {"sarcasm": True}
    with patch("arbiter.product.context.get_adapter", return_value=_ScriptedAdapter(bad, good)):
        f = detect_context("whatever")
    assert f.sarcasm is True


def test_detect_context_raises_after_two_failures():
    bad = {"sarcasm": "not-a-bool"}
    with patch("arbiter.product.context.get_adapter", return_value=_ScriptedAdapter(bad, bad)):
        with pytest.raises(Exception):
            detect_context("whatever")
```

Run: `.\.venv\Scripts\python.exe -m pytest tests/product/test_context.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 2: 🔨 implement `context.py`.** Skeleton:
```python
"""Context/sarcasm node — emits MODIFIER FLAGS only, never re-scores (spec §9b).

Mirrors classify's shape: get_adapter -> complete(prompt, ContextFlags) -> validate,
retry once. The aggregator (deterministic) is what acts on these flags.

Fill the TODOs (spec: plan Task 4).
Check:  .\.venv\Scripts\python.exe -m pytest tests/product/test_context.py -v   (goal: 5 passed)
"""
from pydantic import BaseModel

from arbiter.classify.registry import get_adapter  # patched in tests

CONTEXT_MODEL = "deepseek-chat"


class ContextFlags(BaseModel):
    # 🔨 TODO: 5 bool fields (default False) + note: str | None = None
    #   sarcasm, quotation, reclaimed_slur, direct_threat, ambiguity
    ...


def build_context_prompt(comment: str) -> str:
    # 🔨 TODO: return ONE string that (1) explains each of the 5 flags (verbatim
    #   definitions from the spec), (2) says output JSON shaped like ContextFlags,
    #   (3) includes the comment. The word "json" MUST appear.
    ...


def detect_context(comment: str, model: str = CONTEXT_MODEL) -> ContextFlags:
    # 🔨 TODO: same retry-once shape as classify:
    #   adapter = get_adapter(model); prompt = build_context_prompt(comment)
    #   for _ in range(2): try: return ContextFlags.model_validate(adapter.complete(prompt, ContextFlags))
    #                      except Exception as e: error = e
    #   raise error
    ...
```

- [ ] **Step 3: run → green** (5 passed).

- [ ] **Step 4: Commit** *(you run)*
```
git add src/arbiter/product/context.py tests/product/test_context.py
git commit -m "feat(product): context/sarcasm node (modifier flags only)"
```

---

## Task 5: 🔨 `nodes.py` — the three node functions

**Files:** Create `src/arbiter/product/nodes.py` 🔨 · Test (given): `tests/product/test_nodes.py`

> LangGraph nodes are plain functions `state -> partial_state_update`. We make the LLM calls **injectable** (`classify_fn`, `detect_fn`) so the nodes — and later the whole graph — test with fakes, no network (same DI idea as `eval/collect.py`). The specialist factory is parameterized per category.

**Spec — three callables:**

- `make_specialist_node(category: str, table: dict, classify_fn=classify)` → returns a node function `node(state) -> dict`:
  - `model = model_for(table, category)`
  - `result = classify_fn(model, state["comment"], [category])`  *(a `ClassifyResult`)*
  - `verdict = result.verdicts[category]`
  - returns `{"raw_verdicts": {category: verdict.model_dump(mode="json")}, "routing_snapshot": {category: model}}`

- `make_context_node(detect_fn=detect_context)` → returns `node(state) -> dict`:
  - returns `{"context_flags": detect_fn(state["comment"]).model_dump()}`

- `aggregator_node(state) -> dict`:
  - returns `aggregate(state["raw_verdicts"], state["context_flags"])`  *(the dict from Task 3: `effective_verdicts` / `overall_severity` / `action`)*

- [ ] **Step 1: the test is given — run, watch it fail**
```python
# tests/product/test_nodes.py
from arbiter.classify.schema import ClassifyResult, Severity
from arbiter.product.context import ContextFlags
from arbiter.product.nodes import make_specialist_node, make_context_node, aggregator_node

TABLE = {"insult": {"model": "deepseek-chat", "threshold": 1},
         "threat": {"model": "gpt-4o-mini", "threshold": 1}}


def _fake_classify(model, comment, categories):
    cat = categories[0]
    return ClassifyResult(verdicts={cat: {"severity": Severity.medium, "reason": "r", "span": "idiot"}})


def test_specialist_node_emits_raw_verdict_and_routing():
    node = make_specialist_node("insult", TABLE, classify_fn=_fake_classify)
    out = node({"comment": "you idiot"})
    assert out["raw_verdicts"]["insult"]["severity"] == 2
    assert out["raw_verdicts"]["insult"]["span"] == "idiot"
    assert out["routing_snapshot"]["insult"] == "deepseek-chat"


def test_specialist_node_uses_routed_model_per_category():
    node = make_specialist_node("threat", TABLE, classify_fn=_fake_classify)
    out = node({"comment": "x"})
    assert out["routing_snapshot"]["threat"] == "gpt-4o-mini"


def test_context_node_emits_flags_dict():
    def fake_detect(comment):
        return ContextFlags(sarcasm=True, note="joke")
    node = make_context_node(detect_fn=fake_detect)
    out = node({"comment": "I'll kill you 😂"})
    assert out["context_flags"]["sarcasm"] is True
    assert out["context_flags"]["note"] == "joke"


def test_aggregator_node_runs_the_policy():
    state = {
        "raw_verdicts": {"insult": {"severity": 2, "reason": "r", "span": "idiot"}},
        "context_flags": {"sarcasm": True, "quotation": False, "reclaimed_slur": False,
                          "direct_threat": False, "ambiguity": False, "note": None},
    }
    out = aggregator_node(state)
    # insult 2 -> 1 under sarcasm; action allow
    assert out["effective_verdicts"]["insult"] == 1
    assert out["action"] == "allow"
```

Run: `.\.venv\Scripts\python.exe -m pytest tests/product/test_nodes.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 2: 🔨 implement `nodes.py`.** Skeleton:
```python
"""LangGraph node functions: 6 specialists (parallel) + context + aggregator.

Each node is `state -> partial state update`. LLM calls are injected
(classify_fn / detect_fn) so nodes + graph test with fakes, no network.

Fill the TODOs (spec: plan Task 5).
Check:  .\.venv\Scripts\python.exe -m pytest tests/product/test_nodes.py -v   (goal: 4 passed)
"""
from arbiter.classify import classify
from arbiter.product.aggregator import aggregate
from arbiter.product.context import detect_context
from arbiter.product.routing import model_for


def make_specialist_node(category: str, table: dict, classify_fn=classify):
    # 🔨 TODO: return a function node(state) that:
    #   model = model_for(table, category)
    #   result = classify_fn(model, state["comment"], [category])
    #   verdict = result.verdicts[category]
    #   return {"raw_verdicts": {category: verdict.model_dump(mode="json")},
    #           "routing_snapshot": {category: model}}
    ...


def make_context_node(detect_fn=detect_context):
    # 🔨 TODO: return node(state) -> {"context_flags": detect_fn(state["comment"]).model_dump()}
    ...


def aggregator_node(state) -> dict:
    # 🔨 TODO: return aggregate(state["raw_verdicts"], state["context_flags"])
    ...
```

- [ ] **Step 3: run → green** (4 passed).

- [ ] **Step 4: Commit** *(you run)*
```
git add src/arbiter/product/nodes.py tests/product/test_nodes.py
git commit -m "feat(product): specialist / context / aggregator node functions"
```

---

## Task 6: 🔨 `graph.py` — wire the LangGraph DAG

**Files:** Create `src/arbiter/product/graph.py` 🔨; Modify `src/arbiter/product/__init__.py` · Test (given): `tests/product/test_graph.py`

> The wiring (spec §9 / §10): **START fans out to all 6 specialist nodes + the context node in parallel**; all 7 feed the single **aggregator** node (LangGraph runs it as a barrier — it waits for every incoming edge); aggregator → END. `build_graph` takes injectable `classify_fn` / `detect_fn` so `test_graph.py` drives the entire pipeline with fakes (no network).

**Spec — `build_graph(table, classify_fn=classify, detect_fn=detect_context)` returns a compiled graph:**
1. `g = StateGraph(ModerationState)`
2. add the 6 specialist nodes: for `cat in ALL_6`, `g.add_node(f"specialist_{cat}", make_specialist_node(cat, table, classify_fn))`
3. add `g.add_node("context", make_context_node(detect_fn))` and `g.add_node("aggregator", aggregator_node)`
4. edges: for each `cat`, `g.add_edge(START, f"specialist_{cat}")` and `g.add_edge(f"specialist_{cat}", "aggregator")`; plus `g.add_edge(START, "context")` and `g.add_edge("context", "aggregator")`; plus `g.add_edge("aggregator", END)`
5. `return g.compile()`

- [ ] **Step 1: the test is given — run, watch it fail**
```python
# tests/product/test_graph.py
from arbiter.classify import ALL_6
from arbiter.classify.schema import ClassifyResult, Severity
from arbiter.product.context import ContextFlags
from arbiter.product.graph import build_graph
from arbiter.product.state import initial_state

TABLE = {c: {"model": "deepseek-chat", "threshold": 1} for c in ALL_6}


def _fake_classify(model, comment, categories):
    cat = categories[0]
    # mark only `insult` as medium; everything else none
    sev = Severity.medium if cat == "insult" else Severity.none
    return ClassifyResult(verdicts={cat: {"severity": sev, "reason": "r", "span": None}})


def _fake_detect_clean(comment):
    return ContextFlags()  # all flags false


def test_graph_runs_end_to_end_with_fakes():
    graph = build_graph(TABLE, classify_fn=_fake_classify, detect_fn=_fake_detect_clean)
    out = graph.invoke(initial_state("you idiot"))
    # all 6 specialists ran (parallel) and merged into one dict
    assert set(out["raw_verdicts"]) == set(ALL_6)
    assert out["raw_verdicts"]["insult"]["severity"] == 2
    # insult=2, no flags -> human-review; overall severity 2
    assert out["action"] == "human-review"
    assert out["overall_severity"] == 2
    assert out["context_flags"]["sarcasm"] is False


def test_graph_sarcasm_flag_downgrades_to_allow():
    def fake_detect_sarcasm(comment):
        return ContextFlags(sarcasm=True)
    graph = build_graph(TABLE, classify_fn=_fake_classify, detect_fn=fake_detect_sarcasm)
    out = graph.invoke(initial_state("you idiot (jk)"))
    # insult 2 -> 1 under sarcasm -> action allow
    assert out["effective_verdicts"]["insult"] == 1
    assert out["action"] == "allow"
```

Run: `.\.venv\Scripts\python.exe -m pytest tests/product/test_graph.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 2: 🔨 implement `graph.py`.** Skeleton:
```python
"""Build the LangGraph product pipeline (spec §9/§10).

START -> [6 specialist nodes + context node] in parallel -> aggregator -> END.
classify_fn / detect_fn are injectable so the whole graph tests with fakes.

Fill the TODOs (spec: plan Task 6).
Check:  .\.venv\Scripts\python.exe -m pytest tests/product/test_graph.py -v   (goal: 2 passed)
"""
from langgraph.graph import START, END, StateGraph

from arbiter.classify import ALL_6, classify
from arbiter.product.context import detect_context
from arbiter.product.nodes import make_specialist_node, make_context_node, aggregator_node
from arbiter.product.state import ModerationState


def build_graph(table: dict, classify_fn=classify, detect_fn=detect_context):
    # 🔨 TODO: follow the 5 wiring steps in the plan spec above.
    #   - g = StateGraph(ModerationState)
    #   - add 6 specialist nodes (one per ALL_6) + "context" + "aggregator"
    #   - edges: START->each specialist; each specialist->aggregator
    #            START->context; context->aggregator; aggregator->END
    #   - return g.compile()
    ...
```

- [ ] **Step 3: 🔨 update `src/arbiter/product/__init__.py`** to re-export:
```python
from .graph import build_graph
__all__ = ["build_graph"]
```

- [ ] **Step 4: run → green** (2 passed). Then the whole product suite:
Run: `.\.venv\Scripts\python.exe -m pytest tests/product -v`
Expected: all green (state 5 + routing 2 + aggregator 13 + context 5 + nodes 4 + graph 2 = 31).

- [ ] **Step 5: Commit** *(you run)*
```
git add src/arbiter/product/graph.py src/arbiter/product/__init__.py tests/product/test_graph.py
git commit -m "feat(product): wire LangGraph pipeline (6 specialists + context + aggregator)"
```

---

## Task 7: end-to-end smoke on DeepSeek (real call)

**Files:** I give the shell of `scripts/smoke_moderate.py` (you fill the 🔨 glue). Needs `DEEPSEEK_API_KEY` in `.env`.

> Proves the real pipeline: load `routing_table.json` → build the graph with the **real** `classify` + `detect_context` → run a couple of comments through actual DeepSeek calls → print the verdict. Mirrors `scripts/smoke_classify.py`.

- [ ] **Step 1: I provide the shell of `scripts/smoke_moderate.py`:**
```python
"""Smoke-test the product pipeline end-to-end on DeepSeek.

Loads routing_table.json, builds the real LangGraph pipeline, runs a few comments.
Needs DEEPSEEK_API_KEY in .env.  Run:  python scripts/smoke_moderate.py
"""
import json

from dotenv import load_dotenv

from arbiter.product.graph import build_graph
from arbiter.product.routing import load_routing_table
from arbiter.product.state import initial_state

load_dotenv()

COMMENTS = [
    "Have a great day, everyone!",          # expect: allow
    "You are an absolute idiot and I hate you.",  # expect: human-review / remove
    "I'll kill you 😂",                      # gray: context node should flag sarcasm
]


def main():
    table = load_routing_table("routing_table.json")
    graph = build_graph(table)  # real classify + detect_context
    for c in COMMENTS:
        # 🔨 TODO: out = graph.invoke(initial_state(c))
        #   print the comment, out["action"], out["overall_severity"],
        #   out["context_flags"], and out["effective_verdicts"].
        ...


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 🔨 fill the glue** in the loop (the `graph.invoke` + prints).

- [ ] **Step 3: run it** (needs `DEEPSEEK_API_KEY` in `.env`)
```
.\.venv\Scripts\python.exe scripts/smoke_moderate.py
```
Expected: for each comment, a printed `action` + `overall_severity` + `context_flags` + `effective_verdicts`. The benign one → `allow`; the insult → `human-review` or `remove`; the `"I'll kill you 😂"` case exercises the context/sarcasm path (flags shown).

- [ ] **Step 4: Commit** *(you run)*
```
git add scripts/smoke_moderate.py
git commit -m "feat(product): end-to-end pipeline smoke on DeepSeek"
```

---

## Definition of done (this plan)
- `.\.venv\Scripts\python.exe -m pytest tests/product -v` fully green (31 tests, no network).
- `.\.venv\Scripts\python.exe -m pytest -q` → the full suite (34 existing + 31 new = 65) green.
- `scripts/smoke_moderate.py` runs the real LangGraph pipeline on DeepSeek and prints a verdict per comment.

## Next increments (P5, NOT this plan)
- **FastAPI** (`api/main.py`): `POST /api/moderate` → `build_graph(...).invoke({comment})` → return the verdict (spec §12). Routing table + compiled graph loaded **once** at startup.
- **Postgres** (`api/db.py`): persist `submissions` + `verdicts` (raw / flags / effective side by side, spec §11).
- **Next.js + Tailwind** frontend (spec §13): textarea → verdict card with per-category rows, highlighted spans, and context-flag chips.
- Deploy: Vercel (frontend) + Railway/Render (backend). Live demo URL.
- *(Later, when budget allows — P3:* real Jigsaw sampling + the other 3 model families → a real, non-degenerate `routing_table.json`. Swapping it in is zero rework — it's the only eval→product artifact.)
```
