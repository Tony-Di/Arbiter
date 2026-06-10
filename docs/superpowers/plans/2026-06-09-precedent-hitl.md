# Precedent Memory + Human-in-the-Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **PROJECT-SPECIFIC PROTOCOL (overrides the default executor):** steps are owner-tagged.
> **(Claude)** = Claude writes it (tests, skeletons, schemas, scaffolding).
> **(Author)** = the human author writes it (core implementation bodies, all `git` commands).
> Claude NEVER runs `git add/commit/push` and NEVER fills in a body marked
> `TODO(author)`. Tests are written first and define the contract; the author
> implements until green.

**Goal:** The adjudicator gains a `search_precedents` tool (semantic search over human
rulings) plus confidence-gated escalation to a real human review queue (LangGraph
`interrupt` + checkpointer); human decisions are written back as precedents.

**Architecture:** New top-level `PrecedentStore` (embedding + pure-Python cosine over a
JSON column). `policy_tool` node generalizes to a `tools_node` dispatching both tools.
After `submit_decision`, a `needs_human` gate routes low-confidence rulings to a
`human_review` node that `interrupt()`s; `POST /api/review/{case_id}` resumes the
checkpointed graph and writes the human ruling back as a precedent.

**Tech Stack:** LangGraph 1.2.4 (`interrupt`/`Command`/`InMemorySaver` verified
available), `langgraph-checkpoint-sqlite` (new dep), OpenAI `text-embedding-3-small`,
SQLAlchemy, FastAPI, React + antd (no router — view switch in `App.tsx`).

**Spec:** `docs/superpowers/specs/2026-06-09-precedent-hitl-design.md`

**Open items resolved at plan time (spec §12):**
- langgraph 1.2.4 supports `interrupt()` / `Command(resume=...)` / `InMemorySaver` ✔
  (verified in-venv). `langgraph-checkpoint-sqlite` NOT installed → Task 0.
- `MAX_TOOL_STEPS`: 3 → **4** (two query tools share the cap).
- Reviewer overrides **action only** (severity stays the adjudicator's/specialists').
- `CONFIDENCE_THRESHOLD = 0.7`; gate is `confidence < threshold` (exactly 0.7 finalizes);
  degrade path has no confidence key → `get("confidence", 1.0)` → only the action queues.
- `after_adjudicate`'s `"done"` branch becomes a composed router
  `route_after_adjudicate` → `"tool" | "human" | "done"` (LangGraph wants one router per
  node; `needs_human` stays a separately testable pure function).
- Frontend has no router → Review is a second view behind an antd `Segmented` toggle.

---

### Task 0: Dependency + dev DB reset

**Files:**
- Modify: `pyproject.toml` (dependencies list)
- Modify: `.gitignore` (add `checkpoints.db`)

- [x] **Step 0.1 (Claude): add the dep + gitignore entry** *(`.gitignore` already has `*.db` — covers `checkpoints.db`, no edit needed)*

In `pyproject.toml` `[project] dependencies`, add:

```toml
"langgraph-checkpoint-sqlite",
```

In `.gitignore`, next to `arbiter.db`, add:

```
checkpoints.db
```

- [x] **Step 0.2 (Author): install + verify**

```powershell
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\python -c "from langgraph.checkpoint.sqlite import SqliteSaver; print('ok')"
```

Expected: `ok`

- [x] **Step 0.3 (Author): delete the dev DB once** (`create_all` won't ALTER existing
  tables; new `precedents` / `review_cases` tables + this is the same note as the
  escalation spec):

```powershell
Remove-Item arbiter.db -ErrorAction SilentlyContinue
```

- [ ] **Step 0.4 (Author): commit**

```
chore: add langgraph-checkpoint-sqlite dep for HITL checkpointing
```

---

### Task 1: Precedent store

**Files:**
- Create: `src/arbiter/precedents.py`
- Create: `tests/test_precedents.py`
- Modify: `src/arbiter/api/db.py` (add `Precedent` model)

- [x] **Step 1.1 (Claude): `Precedent` model in `db.py`** (schema = scaffolding; goes
  right below `Verdict`):

```python
class Precedent(Base):
    """A past HUMAN ruling, retrievable by the adjudicator (HITL spec §5).
    source is always "human" — AI rulings never enter (contamination guard)."""
    __tablename__ = "precedents"
    id: Mapped[int] = mapped_column(primary_key=True)
    comment_text: Mapped[str]
    embedding: Mapped[list] = mapped_column(JSON)
    action: Mapped[str]
    overall_severity: Mapped[int]
    note: Mapped[str]
    source: Mapped[str] = mapped_column(default="human")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
```

- [x] **Step 1.2 (Claude): write the failing tests** — `tests/test_precedents.py`:

```python
"""PrecedentStore — add / cosine search / tool formatting. Zero-network
(embed_fn injected).

Check:  python -m pytest tests/test_precedents.py -v
"""
from arbiter.api.db import Base, make_engine, make_session_factory
from arbiter.precedents import PrecedentStore, format_precedents


def _fake_embed(texts):
    # deterministic 3-dim "embeddings": cat / dog / other axes
    def vec(t):
        if "cat" in t:
            return [1.0, 0.0, 0.0]
        if "dog" in t:
            return [0.0, 1.0, 0.0]
        return [0.0, 0.0, 1.0]
    return [vec(t) for t in texts]


def _store():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    return PrecedentStore(make_session_factory(engine), embed_fn=_fake_embed)


def test_add_and_search_ranks_by_similarity():
    s = _store()
    s.add("the cat insult", "remove", 2, "feline abuse")
    s.add("the dog praise", "allow", 0, "fine")
    hits = s.search("another cat comment", k=2)
    assert hits[0]["comment_text"] == "the cat insult"
    assert hits[0]["action"] == "remove"
    assert hits[0]["overall_severity"] == 2


def test_search_truncates_to_k():
    s = _store()
    for i in range(5):
        s.add(f"cat number {i}", "allow", 0, "n")
    assert len(s.search("cat", k=3)) == 3


def test_empty_store_returns_empty_list():
    assert _store().search("anything") == []


def test_add_defaults_source_human():
    s = _store()
    s.add("cat", "allow", 0, "n")
    assert s.search("cat")[0]["source"] == "human"


def test_format_wraps_in_precedent_tags():
    txt = format_precedents([{"comment_text": "x", "action": "remove",
                              "overall_severity": 2, "note": "n", "source": "human"}])
    assert txt.startswith("<precedent>")
    assert "</precedent>" in txt
    assert "remove" in txt


def test_format_empty_store_message():
    assert format_precedents([]) == "no precedents on file"
```

- [x] **Step 1.3 (Claude): skeleton `src/arbiter/precedents.py`**:

```python
"""Precedent store — the adjudicator's case-law memory (HITL spec §5).

Human rulings only (enforced at the two call sites: review resolution + seed
script). Embeddings via OpenAI text-embedding-3-small; similarity = cosine in
pure Python over all rows (store is hundreds of rows at most — deliberately no
vector DB; see NOTES).

embed_fn is injected (tests pass a deterministic fake) — same DI pattern as
classify_fn / detect_fn / adjudicate_fn.

Check:  python -m pytest tests/test_precedents.py -v
"""
import os

from arbiter.api.db import Precedent

EMBED_MODEL = "text-embedding-3-small"


def default_embed_fn(texts: list[str]) -> list[list[float]]:
    """Embed texts via the OpenAI embeddings API (needs OPENAI_API_KEY).

    TODO(author): OpenAI(api_key=os.environ["OPENAI_API_KEY"]).embeddings
    .create(model=EMBED_MODEL, input=texts) -> [d.embedding for d in resp.data]
    """
    raise NotImplementedError


def _cosine(a: list[float], b: list[float]) -> float:
    """TODO(author): dot(a,b) / (norm(a)*norm(b)); return 0.0 if either norm is 0."""
    raise NotImplementedError


def format_precedents(hits: list[dict]) -> str:
    """Render search hits for the adjudicator transcript.

    Each hit -> "<precedent>comment: ...; ruling: action=..., severity=...;
    rationale: ...</precedent>" joined by newlines. Precedent text is untrusted
    user content -> the <precedent> wrapper is the same data-not-instructions
    framing as <comment>. Empty list -> "no precedents on file".

    TODO(author): implement.
    """
    raise NotImplementedError


class PrecedentStore:
    """add() human rulings; search() top-k similar past rulings."""

    def __init__(self, session_factory, embed_fn=default_embed_fn):
        self._sessions = session_factory
        self._embed = embed_fn

    def add(self, comment_text: str, action: str, overall_severity: int,
            note: str, source: str = "human") -> None:
        """TODO(author): embed comment_text (self._embed([comment_text])[0]),
        insert a Precedent row, commit. Session via self._sessions()."""
        raise NotImplementedError

    def search(self, query_text: str, k: int = 3) -> list[dict]:
        """TODO(author): embed the query, load all Precedent rows, rank by
        _cosine desc, return top-k as dicts (comment_text, action,
        overall_severity, note, source). Empty store -> []. Let embed
        exceptions propagate (the tools node catches them)."""
        raise NotImplementedError
```

- [x] **Step 1.4 (Author): run tests, verify they fail**

```powershell
.venv\Scripts\python -m pytest tests/test_precedents.py -v
```

Expected: 6 failed with `NotImplementedError`.

- [x] **Step 1.5 (Author): implement** `default_embed_fn`, `_cosine`,
  `format_precedents`, `add`, `search` until:

```powershell
.venv\Scripts\python -m pytest tests/test_precedents.py -v
```

Expected: **6 passed**. Then the full suite: `.venv\Scripts\python -m pytest -q`
→ 91 + 6 passed.

- [ ] **Step 1.6 (Author): commit**

```
feat(precedents): PrecedentStore — embedding + cosine case-law memory
```

---

### Task 2: Adjudicator — `search_precedents` tool, `confidence`, generic tools node

**Files:**
- Modify: `src/arbiter/product/adjudicator.py`
- Modify: `src/arbiter/product/graph.py` (`store=` param, `tools_node` wiring)
- Modify: `tests/product/test_adjudicator.py` (extend)

- [x] **Step 2.1 (Claude): extend tests** — append to `tests/product/test_adjudicator.py`:

```python
# --- HITL spec 2026-06-09: search_precedents tool + confidence -------------------
from arbiter.product.adjudicator import make_tools_node


class FakeStore:
    def __init__(self, hits=None, fail=False):
        self.hits, self.fail = hits or [], fail

    def search(self, query, k=3):
        if self.fail:
            raise RuntimeError("embed down")
        return self.hits


def _state_with_calls(calls):
    return {"adj_messages": [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u"},
        {"role": "assistant", "content": None, "tool_calls": calls}]}


def test_tools_node_answers_mixed_batch_one_reply_per_call_id():
    calls = [
        {"id": "a", "function": {"name": "get_policy",
                                 "arguments": json.dumps({"category": "insult"})}},
        {"id": "b", "function": {"name": "search_precedents",
                                 "arguments": json.dumps({"query": "you idiot"})}},
    ]
    hits = [{"comment_text": "u r dumb", "action": "remove",
             "overall_severity": 2, "note": "direct insult", "source": "human"}]
    out = make_tools_node(FakeStore(hits))(_state_with_calls(calls))
    tool_msgs = out["adj_messages"][-2:]
    assert [m["tool_call_id"] for m in tool_msgs] == ["a", "b"]
    assert all(m["role"] == "tool" for m in tool_msgs)
    assert "<precedent>" in tool_msgs[1]["content"]


def test_tools_node_search_failure_is_a_string_not_an_exception():
    calls = [{"id": "a", "function": {"name": "search_precedents",
                                      "arguments": json.dumps({"query": "x"})}}]
    out = make_tools_node(FakeStore(fail=True))(_state_with_calls(calls))
    assert out["adj_messages"][-1]["content"] == "precedent search unavailable"


def test_tools_node_without_store_degrades_the_same_way():
    calls = [{"id": "a", "function": {"name": "search_precedents",
                                      "arguments": json.dumps({"query": "x"})}}]
    out = make_tools_node(None)(_state_with_calls(calls))
    assert out["adj_messages"][-1]["content"] == "precedent search unavailable"


def test_submit_decision_confidence_lands_in_adjudication():
    def fake(messages, tools):
        return {"role": "assistant", "content": None, "tool_calls": [
            {"id": "1", "function": {"name": "submit_decision",
                "arguments": json.dumps({"action": "allow", "overall_severity": 0,
                                         "note": "ok", "confidence": 0.92})}}]}
    out = make_adjudicate_node(fake)({"comment": "c", "action": "human-review",
                                      "overall_severity": 2, "effective_verdicts": {},
                                      "context_flags": {}, "adj_messages": [],
                                      "adj_steps": 0})
    assert out["adjudication"]["confidence"] == 0.92
```

(`json` and `make_adjudicate_node` are already imported at the top of this test file.)

- [x] **Step 2.2 (Claude): skeleton changes in `adjudicator.py`**

1. `MAX_TOOL_STEPS = 3` → `MAX_TOOL_STEPS = 4` (two query tools share the cap).
2. New tool schema (below `GET_POLICY_TOOL`):

```python
SEARCH_PRECEDENTS_TOOL = {
    "type": "function",
    "function": {
        "name": "search_precedents",
        "description": "Find how similar past comments were ruled by HUMAN "
                       "moderators. Call this when written policy alone does not "
                       "settle the case.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string",
                                     "description": "The comment or phrase to match."}},
            "required": ["query"],
        },
    },
}
```

3. `SUBMIT_DECISION_TOOL` parameters gain (and `required` gains `"confidence"`):

```python
"confidence": {"type": "number", "minimum": 0, "maximum": 1,
               "description": "Your calibrated confidence this ruling is correct. "
                              "Below 0.7 a human will review it."},
```

4. `TOOLS = [GET_POLICY_TOOL, SEARCH_PRECEDENTS_TOOL, SUBMIT_DECISION_TOOL]`
5. System prompt (in `build_adjudicator_messages`) becomes:

```
You are the adjudicator. Resolve gray cases the rules could not auto-decide.
You MAY call get_policy to consult the written policy and search_precedents to
see how human moderators ruled similar comments. You MUST end by calling
submit_decision.
```

6. Replace `policy_tool_node` with a factory (keep the graph node name
   `"policy_tool"` — renaming the node would churn the escalation tests for nothing):

```python
def make_tools_node(store):
    """Factory -> the tools node. Executes EVERY batched tool call by name
    (one tool reply per tool_call_id — the DeepSeek-batches lesson), appends
    results to the transcript, loops back.

    get_policy          -> get_policy(category)            (as before)
    search_precedents   -> format_precedents(store.search(query))
                           store is None OR store.search raises
                           -> "precedent search unavailable"

    TODO(author): implement the dispatch loop (start from the old
    policy_tool_node body, generalize the per-call branch).
    """
    def node(state: dict) -> dict:
        raise NotImplementedError
    return node
```

7. In `make_adjudicate_node`, the `submit_decision` branch (step 4b) also reads
   `confidence`:

```python
# TODO(author): args["confidence"] -> include as "confidence" in the
# adjudication dict (alongside final_action / note / policies_consulted).
```

- [x] **Step 2.3 (Claude): thread `store` through `graph.py`** (wiring scaffold):

```python
def build_graph(table: dict, classify_fn=classify, detect_fn=detect_context,
                adjudicate_fn=None, store=None):
    ...
    g.add_node("policy_tool", make_tools_node(store))   # was: policy_tool_node
```

(import `make_tools_node` instead of `policy_tool_node`; everything else unchanged
in this task — `checkpointer` comes in Task 4.)

- [x] **Step 2.4 (Author): run the new tests, verify they fail**

```powershell
.venv\Scripts\python -m pytest tests/product/test_adjudicator.py -v
```

Expected: the 4 new tests fail (`NotImplementedError` / missing key); pre-existing
tests still pass — EXCEPT any that assume the old 3-step cap or 2-element TOOLS
list. If one fails on the cap change, update its expectation to `MAX_TOOL_STEPS`
(the constant, not a literal).

- [x] **Step 2.5 (Author): implement** the tools-node dispatch + confidence capture
  until:

```powershell
.venv\Scripts\python -m pytest -q
```

Expected: full suite green (97 + 4 = 101).

- [ ] **Step 2.6 (Author): commit**

```
feat(adjudicator): search_precedents tool + confidence in submit_decision
```

---

### Task 3: `needs_human` gate + `human_review` node

**Files:**
- Modify: `src/arbiter/product/adjudicator.py`
- Modify: `tests/product/test_adjudicator.py` (extend)

- [x] **Step 3.1 (Claude): tests for the pure router** — append:

```python
# --- HITL spec 2026-06-09: confidence gate ----------------------------------------
from arbiter.product.adjudicator import needs_human, route_after_adjudicate


def test_low_confidence_goes_human():
    assert needs_human({"action": "allow",
                        "adjudication": {"confidence": 0.3}}) == "human"


def test_high_confidence_finalizes():
    assert needs_human({"action": "remove",
                        "adjudication": {"confidence": 0.95}}) == "finalize"


def test_exactly_threshold_finalizes():
    assert needs_human({"action": "allow",
                        "adjudication": {"confidence": 0.7}}) == "finalize"


def test_human_review_action_always_queues():
    assert needs_human({"action": "human-review",
                        "adjudication": {"confidence": 0.99}}) == "human"


def test_degrade_without_confidence_only_queues_on_action():
    # degrade path writes no confidence key -> default 1.0; only the action decides
    deg = {"note": "adjudicator unavailable, kept rule-based verdict",
           "policies_consulted": []}
    assert needs_human({"action": "allow", "adjudication": deg}) == "finalize"
    assert needs_human({"action": "human-review", "adjudication": deg}) == "human"


def test_route_after_adjudicate_composes_tool_and_gate():
    # mid-loop (asking for a tool) -> "tool"
    assert route_after_adjudicate(
        {"adj_messages": [_getpolicy_msg("toxic")], "adj_steps": 1}) == "tool"
    # submitted, low confidence -> "human"
    submitted = {"adj_messages": [{"role": "assistant", "content": None,
                                   "tool_calls": [{"id": "1", "function": {
                                       "name": "submit_decision", "arguments": "{}"}}]}],
                 "adj_steps": 1, "action": "allow",
                 "adjudication": {"confidence": 0.2}}
    assert route_after_adjudicate(submitted) == "human"
    # submitted, confident -> "done"
    submitted["adjudication"] = {"confidence": 0.9}
    assert route_after_adjudicate(submitted) == "done"
```

(`_getpolicy_msg` is an existing helper in this test file.)

- [x] **Step 3.2 (Claude): skeletons in `adjudicator.py`**:

```python
CONFIDENCE_THRESHOLD = 0.7   # below this, a human reviews (tune after live smoke)


def needs_human(state: dict) -> str:
    """Gate after submit_decision (HITL spec §4): "human" if the final action is
    human-review OR adjudication confidence < CONFIDENCE_THRESHOLD; else
    "finalize". Degrade rulings carry no confidence key -> default 1.0 (only the
    action queues them).

    TODO(author): implement (2 lines).
    """
    raise NotImplementedError


def route_after_adjudicate(state: dict) -> str:
    """The single router LangGraph needs on the adjudicate node:
    after_adjudicate says "tool" -> "tool"; otherwise map needs_human:
    "human" -> "human", "finalize" -> "done".

    TODO(author): implement by composing after_adjudicate + needs_human.
    """
    raise NotImplementedError


def human_review_node(state: dict) -> dict:
    """The interrupt site (HITL spec §4). Pauses the graph with the AI's
    recommendation; on resume applies the human decision.

        payload  = {"recommended_action": state["action"],
                    "overall_severity":  state["overall_severity"],
                    "note" / "confidence" / "policies_consulted": from state["adjudication"]}
        decision = interrupt(payload)        # {"action": "allow"|"remove"|"confirm",
                                             #  "note": str | None}
        "confirm" keeps recommended_action; otherwise decision["action"] wins.
        Return {"action": final, "adjudication": {**state["adjudication"],
                "human": {"action": final, "note": decision.get("note")}}}

    TODO(author): implement (import `interrupt` from langgraph.types).
    """
    raise NotImplementedError
```

- [x] **Step 3.3 (Author): run tests, verify the 6 new ones fail; implement
  `needs_human` + `route_after_adjudicate` + `human_review_node`; re-run:**

```powershell
.venv\Scripts\python -m pytest tests/product/test_adjudicator.py -v
```

Expected: all pass (`human_review_node` is only exercised in Task 4 — `interrupt()`
needs a running graph).

- [ ] **Step 3.4 (Author): commit**

```
feat(adjudicator): confidence gate (needs_human) + human_review interrupt node
```

---

### Task 4: Graph wiring — checkpointer + HITL cycle, full-graph tests

**Files:**
- Modify: `src/arbiter/product/graph.py`
- Create: `tests/product/test_hitl.py`

- [x] **Step 4.1 (Claude): write the failing full-graph tests** —
  `tests/product/test_hitl.py`:

```python
"""HITL through the full graph: pause on low confidence, resume with the human
decision. Zero-network (fake classify/detect/adjudicate; InMemorySaver).

Check:  python -m pytest tests/product/test_hitl.py -v
"""
import json

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from arbiter.classify import ALL_6
from arbiter.classify.schema import ClassifyResult, Severity
from arbiter.product.context import ContextFlags
from arbiter.product.graph import build_graph
from arbiter.product.state import initial_state

TABLE = {c: {"model": "deepseek-chat", "threshold": 1} for c in ALL_6}
CFG = {"configurable": {"thread_id": "case-1"}}


def _fake_classify(model, comment, categories):
    cat = categories[0]
    sev = Severity.medium if cat == "insult" else Severity.none
    return ClassifyResult(verdicts={cat: {"severity": sev, "reason": "r", "span": None}})


def _fake_detect(comment):
    return ContextFlags()


def _submitting(confidence, action="allow"):
    def fn(messages, tools):
        return {"role": "assistant", "content": None, "tool_calls": [
            {"id": "1", "function": {"name": "submit_decision",
                "arguments": json.dumps({"action": action, "overall_severity": 1,
                                         "note": "n", "confidence": confidence})}}]}
    return fn


def _graph(adjudicate_fn):
    return build_graph(TABLE, classify_fn=_fake_classify, detect_fn=_fake_detect,
                       adjudicate_fn=adjudicate_fn, checkpointer=InMemorySaver())


def test_low_confidence_pauses_with_recommendation():
    result = _graph(_submitting(0.3)).invoke(initial_state("you idiot"), config=CFG)
    assert "__interrupt__" in result
    payload = result["__interrupt__"][0].value
    assert payload["recommended_action"] == "allow"
    assert payload["confidence"] == 0.3


def test_resume_applies_human_decision():
    g = _graph(_submitting(0.3))
    g.invoke(initial_state("you idiot"), config=CFG)
    final = g.invoke(Command(resume={"action": "remove", "note": "clear attack"}),
                     config=CFG)
    assert final["action"] == "remove"
    assert final["adjudication"]["human"] == {"action": "remove", "note": "clear attack"}


def test_resume_confirm_keeps_recommendation():
    g = _graph(_submitting(0.3))
    g.invoke(initial_state("you idiot"), config=CFG)
    final = g.invoke(Command(resume={"action": "confirm", "note": None}), config=CFG)
    assert final["action"] == "allow"          # the AI's recommendation


def test_high_confidence_does_not_pause():
    result = _graph(_submitting(0.95)).invoke(initial_state("you idiot"), config=CFG)
    assert "__interrupt__" not in result
    assert result["action"] == "allow"


def test_clean_case_never_pauses():
    def all_clean(model, comment, categories):
        cat = categories[0]
        return ClassifyResult(verdicts={cat: {"severity": Severity.none,
                                              "reason": "r", "span": None}})
    result = _graph(_submitting(0.0)).invoke(initial_state("nice day"), config=CFG)
    assert "__interrupt__" not in result and result["action"] == "allow"


def test_no_checkpointer_default_is_unchanged():
    g = build_graph(TABLE, classify_fn=_fake_classify, detect_fn=_fake_detect)
    result = g.invoke(initial_state("you idiot"))   # no thread_id, as today
    assert result["action"] == "human-review"
```

  *(Note `test_clean_case_never_pauses` builds `_graph(...)` with the default
  `_fake_classify` via `_submitting(0.0)` but classifies clean — wire `all_clean`
  in: `build_graph(TABLE, classify_fn=all_clean, detect_fn=_fake_detect,
  adjudicate_fn=_submitting(0.0), checkpointer=InMemorySaver())`. Claude fixes
  this when creating the file — flagged here so the intent is unambiguous.)*

- [x] **Step 4.2 (Claude): graph wiring scaffold** — `build_graph` final shape:

```python
def build_graph(table: dict, classify_fn=classify, detect_fn=detect_context,
                adjudicate_fn=None, store=None, checkpointer=None):
    ...
    if adjudicate_fn is None:
        g.add_edge("aggregator", END)
        return g.compile(checkpointer=checkpointer)

    g.add_node("adjudicate", make_adjudicate_node(adjudicate_fn))
    g.add_node("policy_tool", make_tools_node(store))
    # HITL only activates WITH a checkpointer -- interrupt() requires one. Without
    # it, "human" falls through to END (pre-HITL behavior: human-review stays a
    # label). Same opt-in pattern as "escalation only wired when adjudicate_fn
    # is injected" -- this is what keeps the existing escalation tests green
    # (they build graphs with no checkpointer and expect no pause).
    human_target = END
    if checkpointer is not None:
        g.add_node("human_review", human_review_node)
        g.add_edge("human_review", END)
        human_target = "human_review"
    g.add_conditional_edges("aggregator", should_escalate,
                            {"escalate": "adjudicate", "done": END})
    # one router, three exits: keep looping, queue for a human, or finalize
    g.add_conditional_edges("adjudicate", route_after_adjudicate,
                            {"tool": "policy_tool", "human": human_target,
                             "done": END})
    g.add_edge("policy_tool", "adjudicate")     # the cycle (unchanged)
    return g.compile(checkpointer=checkpointer)
```

(imports: `route_after_adjudicate`, `human_review_node` from adjudicator;
`after_adjudicate` import can go.)

- [x] **Step 4.3 (Author): run + fix until the whole suite is green** *(green on first run — Task 3 implementations were already complete; 116 passed)*

```powershell
.venv\Scripts\python -m pytest tests/product/test_hitl.py -v
.venv\Scripts\python -m pytest -q
```

Expected: 6 new passed; full suite green. If the `__interrupt__` access pattern
differs in this langgraph version, probe with a one-off
`print(result["__interrupt__"])` and pin the tests to reality — then keep the
pinned form.

- [ ] **Step 4.4 (Author): commit**

```
feat(graph): checkpointer param + human_review interrupt wired into the cycle
```

---

### Task 5: API — review queue endpoints + persistence

**Files:**
- Modify: `src/arbiter/api/db.py` (add `ReviewCase`)
- Modify: `src/arbiter/api/schemas.py`
- Modify: `src/arbiter/api/main.py`
- Create: `tests/api/test_review_api.py`

- [x] **Step 5.1 (Claude): `ReviewCase` model in `db.py`**:

```python
class ReviewCase(Base):
    """A paused (interrupted) moderation case awaiting a human ruling (HITL §7)."""
    __tablename__ = "review_cases"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(unique=True, index=True)   # graph thread_id
    comment_text: Mapped[str]
    recommendation: Mapped[dict] = mapped_column(JSON)              # interrupt payload
    status: Mapped[str] = mapped_column(default="pending")          # pending | resolved
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(nullable=True, default=None)
```

- [x] **Step 5.2 (Claude): schema additions in `schemas.py`**:

```python
from datetime import datetime
from typing import Literal


class PendingOut(BaseModel):
    """Returned by /api/moderate when the case paused for human review."""
    status: Literal["pending"] = "pending"
    case_id: str
    comment: str
    recommendation: dict


class ReviewCaseOut(BaseModel):
    case_id: str
    comment: str
    recommendation: dict
    created_at: datetime


class ReviewDecision(BaseModel):
    action: Literal["allow", "remove", "confirm"]
    note: str | None = None
```

and `ModerateResponse` gains (default-safe, old clients unaffected):

```python
    status: Literal["final"] = "final"
    case_id: str | None = None
```

- [x] **Step 5.3 (Claude): write the failing API tests** —
  `tests/api/test_review_api.py`:

```python
"""Review-queue API: pending moderate responses, queue listing, resolution +
precedent write-back. Zero-network (fakes + InMemorySaver + in-memory DB).

Check:  python -m pytest tests/api/test_review_api.py -v
"""
import json

from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from arbiter.classify import ALL_6
from arbiter.classify.schema import ClassifyResult, Severity
from arbiter.product.context import ContextFlags
from arbiter.product.graph import build_graph
from arbiter.api.main import app, get_graph, get_db, get_store
from arbiter.api.db import Base, ReviewCase, Verdict, make_engine, make_session_factory

TABLE = {c: {"model": "deepseek-chat", "threshold": 1} for c in ALL_6}


def _fake_classify(model, comment, categories):
    cat = categories[0]
    sev = Severity.medium if cat == "insult" else Severity.none
    return ClassifyResult(verdicts={cat: {"severity": sev, "reason": "r", "span": None}})


def _fake_detect(comment):
    return ContextFlags()


def _submitting(confidence, action="allow"):
    def fn(messages, tools):
        return {"role": "assistant", "content": None, "tool_calls": [
            {"id": "1", "function": {"name": "submit_decision",
                "arguments": json.dumps({"action": action, "overall_severity": 1,
                                         "note": "n", "confidence": confidence})}}]}
    return fn


class RecordingStore:
    def __init__(self):
        self.added = []

    def add(self, comment_text, action, overall_severity, note, source="human"):
        self.added.append({"comment_text": comment_text, "action": action,
                           "overall_severity": overall_severity, "note": note,
                           "source": source})

    def search(self, query, k=3):
        return []


def _client(confidence=0.3):
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    TestSession = make_session_factory(engine)
    store = RecordingStore()
    fake_graph = build_graph(TABLE, classify_fn=_fake_classify, detect_fn=_fake_detect,
                             adjudicate_fn=_submitting(confidence), store=store,
                             checkpointer=InMemorySaver())

    def _get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_graph] = lambda: fake_graph
    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_store] = lambda: store
    return TestClient(app), TestSession, store


def teardown_function():
    app.dependency_overrides.clear()


def test_low_confidence_moderate_goes_pending():
    client, TestSession, _ = _client(confidence=0.3)
    r = client.post("/api/moderate", json={"comment": "you idiot"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "pending"
    assert body["case_id"]
    assert body["recommendation"]["recommended_action"] == "allow"
    db = TestSession()
    assert db.query(ReviewCase).filter_by(status="pending").count() == 1
    assert db.query(Verdict).count() == 0          # no verdict until a human rules


def test_high_confidence_moderate_stays_final():
    client, TestSession, _ = _client(confidence=0.95)
    r = client.post("/api/moderate", json={"comment": "you idiot"})
    body = r.json()
    assert body["status"] == "final"
    assert body["action"] == "allow"
    assert TestSession().query(Verdict).count() == 1


def test_review_queue_lists_pending_cases():
    client, _, _ = _client()
    client.post("/api/moderate", json={"comment": "you idiot"})
    r = client.get("/api/review-queue")
    assert r.status_code == 200
    cases = r.json()
    assert len(cases) == 1
    assert cases[0]["comment"] == "you idiot"
    assert cases[0]["recommendation"]["confidence"] == 0.3


def test_resolve_finalizes_persists_and_writes_precedent():
    client, TestSession, store = _client()
    case_id = client.post("/api/moderate",
                          json={"comment": "you idiot"}).json()["case_id"]
    r = client.post(f"/api/review/{case_id}",
                    json={"action": "remove", "note": "clear attack"})
    assert r.status_code == 200
    assert r.json()["action"] == "remove"
    db = TestSession()
    assert db.query(Verdict).count() == 1
    assert db.query(ReviewCase).filter_by(status="resolved").count() == 1
    assert store.added == [{"comment_text": "you idiot", "action": "remove",
                            "overall_severity": 1, "note": "clear attack",
                            "source": "human"}]


def test_resolve_unknown_case_is_404():
    client, _, _ = _client()
    assert client.post("/api/review/nope", json={"action": "remove"}).status_code == 404


def test_double_resolve_is_409():
    client, _, _ = _client()
    case_id = client.post("/api/moderate",
                          json={"comment": "you idiot"}).json()["case_id"]
    client.post(f"/api/review/{case_id}", json={"action": "remove"})
    assert client.post(f"/api/review/{case_id}",
                       json={"action": "allow"}).status_code == 409
```

- [x] **Step 5.4 (Claude): `main.py` skeleton changes**:

```python
import sqlite3
from uuid import uuid4

from fastapi import HTTPException
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from arbiter.precedents import PrecedentStore
from arbiter.api.db import ReviewCase
from arbiter.api.schemas import PendingOut, ReviewCaseOut, ReviewDecision

_store = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _graph, _store
    init_db()
    _store = PrecedentStore(SessionLocal)
    table_path = os.environ.get("ROUTING_TABLE", "routing_table.json")
    # checkpoints.db: the graph's pause/resume state (gitignored, like arbiter.db).
    # check_same_thread=False: FastAPI sync endpoints run on a thread pool.
    conn = sqlite3.connect("checkpoints.db", check_same_thread=False)
    _graph = build_graph(load_routing_table(table_path),
                         adjudicate_fn=default_adjudicate_fn,
                         store=_store, checkpointer=SqliteSaver(conn))
    yield


def get_store():
    return _store


@app.post("/api/moderate", response_model=ModerateResponse | PendingOut)
def moderate(req: ModerateRequest, graph=Depends(get_graph), db=Depends(get_db)):
    """TODO(author):
    1. case_id = str(uuid4()); cfg = {"configurable": {"thread_id": case_id}}
    2. state = graph.invoke(initial_state(req.comment), config=cfg)
    3. if "__interrupt__" in state: persist ReviewCase(case_id, comment,
       recommendation=state["__interrupt__"][0].value), commit,
       return PendingOut(case_id=..., comment=..., recommendation=...)
    4. else: save_verdict + to_response as today (response gains case_id).
    """
    raise NotImplementedError


@app.get("/api/review-queue", response_model=list[ReviewCaseOut])
def review_queue(db=Depends(get_db)):
    """TODO(author): pending ReviewCase rows, newest first, mapped to ReviewCaseOut."""
    raise NotImplementedError


@app.post("/api/review/{case_id}", response_model=ModerateResponse)
def resolve_review(case_id: str, decision: ReviewDecision,
                   graph=Depends(get_graph), db=Depends(get_db),
                   store=Depends(get_store)):
    """TODO(author):
    1. case = db.query(ReviewCase).filter_by(case_id=case_id).first()
       -> None: raise HTTPException(404); status=="resolved": raise HTTPException(409)
    2. final = graph.invoke(Command(resume={"action": decision.action,
                                            "note": decision.note}),
                            config={"configurable": {"thread_id": case_id}})
    3. one transaction: save_verdict(db, case.comment_text, final);
       store.add(case.comment_text, final["action"], final["overall_severity"],
                 decision.note or final["adjudication"]["note"], source="human");
       case.status = "resolved"; case.resolved_at = now; db.commit()
    4. return to_response(final)
    """
    raise NotImplementedError
```

(`to_response` gains an optional `case_id=None` passthrough — one-line change in
`schemas.py`.)

- [x] **Step 5.5 (Author): run tests (fail) → implement the three endpoint bodies →
  full suite green:** *(122 passed)*

```powershell
.venv\Scripts\python -m pytest tests/api/test_review_api.py -v
.venv\Scripts\python -m pytest -q
```

Expected: 6 new passed; total ≈ 113 passed.

- [ ] **Step 5.6 (Author): commit**

```
feat(api): review queue — pending moderate, resolve endpoint, precedent write-back
```

---

### Task 6: Frontend — Review view (minimal)

**Files:**
- Create: `web/src/pages/Review.tsx`
- Modify: `web/src/lib/types.ts`, `web/src/lib/engine.ts`, `web/src/App.tsx`

No frontend test infra exists — verification is the manual walkthrough in 6.4.

- [x] **Step 6.1 (Claude): types** — add to `web/src/lib/types.ts`:

```ts
/** /api/moderate now returns a verdict (status "final") OR a pending case. */
export interface PendingCase {
  status: "pending";
  case_id: string;
  comment: string;
  recommendation: {
    recommended_action: string;
    overall_severity: number;
    note?: string;
    confidence?: number;
    policies_consulted?: string[];
  };
}

export interface ReviewCase {
  case_id: string;
  comment: string;
  recommendation: PendingCase["recommendation"];
  created_at: string;
}

export type ReviewAction = "allow" | "remove" | "confirm";
```

(and `Verdict` gains optional `status?: "final"` / `case_id?: string`.)

- [x] **Step 6.2 (Claude): skeletons** — *(compile-green: tsc + vite build pass; the
  Segmented toggle + table shell are wired, fetch bodies / expanded row / pending
  flow are the TODO(author)s)*

`web/src/pages/Review.tsx` (TODO(author) bodies): antd `Table` of cases from
`GET /api/review-queue`; expanded row shows comment + AI recommendation
(action/confidence/note/policies) and three buttons — **Confirm AI / Allow /
Remove** — each `POST /api/review/{case_id}` then refetch; empty state =
"No cases waiting for review."

`web/src/App.tsx`: antd `Segmented` ("Moderate" | "Review") above the existing
content; "Review" renders `<Review/>` — plain `useState`, no router.

`web/src/lib/engine.ts`: the `moderate()` wrapper's return type widens to
`Verdict | PendingCase`; the offline mock marks ONE gray sample as pending so
the demo shows the queue with no backend (TODO(author)).

- [x] **Step 6.3 (Author): implement the TODOs.** *(delegated to Claude by the
  author — frontend is glue, not the learning-focus core; tsc + vite build green)*

- [ ] **Step 6.4 (Author): manual verification** — backend + `npm run dev`:
  1. Paste a clearly toxic comment → instant final verdict (unchanged).
  2. Paste a gray comment (e.g. the reclaimed-slur sample) with the fake-low-confidence
     path or a real low-confidence ruling → "Sent to human review" card.
  3. Switch to Review → the case is listed → click **Remove** → verdict appears;
     re-resolving is rejected.

- [ ] **Step 6.5 (Author): commit**

```
feat(web): review queue view — pending cases, confirm/allow/remove
```

---

### Task 7: Seed + live smoke scripts

**Files:**
- Create: `scripts/seed_precedents.py`
- Create: `scripts/smoke_hitl.py`

- [x] **Step 7.1 (Claude): `scripts/seed_precedents.py`** — full script with the 12
  draft seed rulings as data (author = the moderator of record: **review/edit the
  labels before running**, that's what makes them human precedents):

```python
"""Seed the precedent store with hand-labeled gray-case rulings (one cheap
embedding run; needs OPENAI_API_KEY in .env).

Run:  .venv\\Scripts\\python scripts/seed_precedents.py
"""
from dotenv import load_dotenv

from arbiter.api.db import SessionLocal, init_db
from arbiter.precedents import PrecedentStore

SEEDS = [
    ("I'd literally kill for tickets to that show", "allow", 0,
     "hyperbolic idiom, no target — not a threat"),
    ("He called me a 'worthless idiot' — can you believe that?", "allow", 0,
     "quoting abuse to report it, not committing it"),
    ("ur team got destroyed lol, absolute trash", "allow", 1,
     "sports trash talk aimed at a team, not a person's identity"),
    ("people like you should not exist", "remove", 3,
     "dehumanizing a person — severe even without slurs"),
    ("as a queer person, us queers can joke about this", "allow", 0,
     "in-group reclaimed use, no attack"),
    ("what a brilliant idea... said no one ever", "allow", 1,
     "sarcastic criticism of an idea, not a person"),
    ("go back to where you came from", "remove", 3,
     "xenophobic trope targeting national origin"),
    ("I hope your house burns down", "remove", 2,
     "targeted wish of harm — threat-adjacent"),
    ("this is so stupid", "allow", 0,
     "criticizes the content, not its author"),
    ("you're a clown and everyone laughs at you", "remove", 2,
     "direct personal insult, sustained ridicule"),
    ("delete your account before someone makes you", "remove", 2,
     "veiled threat dressed as advice"),
    ("OP is being a bit naive here imo", "allow", 0,
     "mild criticism within civil bounds"),
]

if __name__ == "__main__":
    load_dotenv()
    init_db()
    store = PrecedentStore(SessionLocal)
    for comment, action, severity, note in SEEDS:
        store.add(comment, action, severity, note, source="human")
        print(f"seeded: {action:6s}  {comment[:50]}")
    print(f"\n{len(SEEDS)} precedents seeded.")
```

- [x] **Step 7.2 (Claude): `scripts/smoke_hitl.py`** — skeleton: POST a gray comment
  to a running server, print the pending payload, GET the queue, POST a resolve,
  print the final verdict; exits nonzero if any step's shape is wrong.
  (TODO(author) body; run with `PYTHONIOENCODING=utf-8` — CN-Windows GBK console.)

- [ ] **Step 7.3 (Author): review the 12 seed labels, edit to taste, run the seed,
  then the live smoke** (server running, real keys):

```powershell
.venv\Scripts\python scripts/seed_precedents.py
$env:PYTHONIOENCODING="utf-8"; .venv\Scripts\python scripts/smoke_hitl.py
```

Expected: 12 seeded; smoke prints pause → queue → resolve → final, exit 0. Sanity-check
DeepSeek's self-reported confidence against `CONFIDENCE_THRESHOLD = 0.7` here — if it
always says 0.9+, lower the threshold (one const).

- [ ] **Step 7.4 (Author): commit**

```
feat(scripts): precedent seeds + HITL live smoke
```

---

### Task 8: Docs

- [x] **Step 8.1 (Claude): README** — architecture diagram gains the
  `needs_human → review queue` branch + `search_precedents`; "Why it's interesting"
  gains the case-law/HITL bullet; test badge count updated.
- [x] **Step 8.2 (Claude): NOTES.md** — design-record entry: why human-only
  precedents, why cosine-in-Python, why confidence gating, the
  `get("confidence", 1.0)` degrade subtlety.
- [ ] **Step 8.3 (Author): review docs, commit**

```
docs: precedent memory + HITL — README architecture + NOTES design record
```

---

## Self-review (done at plan time)

- **Spec coverage:** §5 store → Task 1; §6 adjudicator → Tasks 2–3; §4 topology +
  checkpointer → Task 4; §7 API → Task 5; §8 UI → Task 6; §10 seeds/smokes → Task 7;
  follow-up docs → Task 8. Gap check: spec's `precedents_consulted` trace in
  `adjudication` — covered by Task 2 Step 2.2 item 7's TODO scope? **Added:** author
  collects `search_precedents` queries into `adjudication["precedents_consulted"]`
  exactly like `policies_consulted` (same loop, second tool name) — part of Step 2.5.
- **Type consistency:** `make_tools_node(store)` (Tasks 2/4/5), `needs_human` /
  `route_after_adjudicate` (Tasks 3/4), `PendingOut.recommendation` keys =
  `human_review_node` payload keys (Tasks 3/5/6), `RecordingStore.add` signature =
  `PrecedentStore.add` (Tasks 1/5). Checked.
- **Placeholders:** every `TODO(author)` carries the exact contract (inputs, outputs,
  failure strings) and a test pinning it — intentional under the project protocol,
  not plan gaps.
