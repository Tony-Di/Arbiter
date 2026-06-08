# Arbiter — Escalation Edge Design Specification

**Status:** Approved design (2026-06-08), brainstormed this session. This is the
authoritative spec for the escalation feature; the implementation plan is derived
from it. Builds on the v1 design (`docs/superpowers/specs/2026-06-02-arbiter-design.md`)
and the architecture review (`docs/2026-06-04-architecture-review.md` §D3).

> One line: turn the static product DAG into a graph that *decides its own path* —
> hard cases route through a tool-using adjudicator agent before the verdict is final.

---

## 1. Why (motivation)

The product pipeline today is a **fully static DAG**:

```
START → [6 specialists + context] (parallel) → aggregator → END
```

Every comment runs the same 7 LLM calls + the deterministic aggregator, same path
every time. No node decides anything. For an **AI/Agent-Engineer** target (see
`project-career-and-portfolio` memory), this is the weak spot: the project's headline
is supposed to be agent orchestration, but a static fan-out shows none of the
recognizable agentic tells — **dynamic control flow, tool use, or loops**. The
architecture review flagged the conditional escalation edge as the fix and promoted it
from stretch to core.

This spec adds exactly that: a **conditional escalation edge** plus a **tool-using
adjudicator agent with a visible reasoning loop**, built as nodes/edges in the same
LangGraph so the agentic control flow is real *and shown* (demoable in one screenshot).

## 2. Goals & non-goals

**Goals (this spec):**
- A conditional edge: only genuinely gray cases escalate; easy cases cost what they do
  today (no extra call).
- An adjudicator that is a real agent: it calls a tool (`get_policy`) in a loop it
  drives itself, then submits a final decision.
- The loop is a **cycle in the LangGraph graph** (not hidden in a Python `while`), so
  it is the visible agentic artifact (Approach A from brainstorming).
- Minimal UI surfacing so escalation is visible in the demo (a badge + a one-line
  trace). No streaming.
- Same engineering discipline as the existing code: injected LLM calls, zero-network
  tests, injection-hardened prompts, bounded retries/cost.

**Non-goals (deferred):**
- SSE / per-agent streaming visualization (§D2) — separate spec.
- A second real model tier for the adjudicator — DeepSeek now, swappable via one const.
- RAG / vector policy lookup — `get_policy` is a static local dict, deliberately not
  retrieval (stay differentiated from DocSense).
- Rewriting per-category specialist verdicts — the adjudicator only adjusts the policy
  roll-up (overall severity + action), keeping the cross-model eval's detection numbers
  clean.
- Triage-first / cost routing (skipping the full panel on benign input) — possible
  later; out of scope here.

## 3. Decisions locked (brainstorming 2026-06-08)

1. **Primary goal = agent signal** (not pure quality, not cost). → depth-escalation
   topology: always run the cheap pass, escalate only gray cases. *Quality gain is a
   bonus, not the driver.*
2. **Escalation node = tool-using adjudicator agent** (ReAct loop, `get_policy` tool).
   *Rejected:* reflection-loop-only (no tool — leaves the tool gap open); single
   stronger-model re-judgment (no loop, no tool — weakest agentic content).
3. **Trigger = the would-be-human-review cases:** tentative `action == "human-review"`
   **or** `context_flags.ambiguity`. *Rejected:* threshold/disagreement metric (needs a
   new "disagreement" definition); union-of-everything (escalates too often → cost).
4. **Scope = backend + minimal UI surfacing.** *Rejected:* backend-only (agent work
   invisible in the demo — defeats the "agent signal" goal); full streaming (too big
   for one spec).
5. **Build style = Approach A** (loop as graph nodes/edges). *Rejected:* hand-rolled
   loop inside one node (loop hidden → weaker LangGraph story); prebuilt
   `create_react_agent` (opaque, clashes with the raw-adapter registry, against the
   self-built/explainable ethos).

## 4. Architecture — topology & control flow

The aggregator's verdict becomes **tentative**; a conditional edge decides whether a
hard case goes to the adjudicator loop before finalizing.

```
START ─┬─ specialist_toxic ──┐
       ├─ ... (6 total) ──────┤
       └─ context ────────────┴─→ aggregator (tentative)
                                       │
                              should_escalate?
                            ┌──────────┴───────────┐
                         "done"                 "escalate"
                            │                       ▼
                            │                  ┌─→ adjudicate ──┐   (LLM + tools)
                            │                  │       │         │
                            │           after_adjudicate?        │
                            │            ┌──────┴──────┐         │
                            │         "tool"        "done"       │
                            │            ▼             │         │
                            │       policy_tool ───────┘  ← the cycle (policy_tool → adjudicate)
                            │       (executes get_policy, appends result)
                            ▼                          │
                           END ←───────────────────────┘
```

**New nodes** (added to the existing `StateGraph`): `adjudicate`, `policy_tool`.
The edge `policy_tool → adjudicate` is the visible loop.

**Edges changed/added:**
- `aggregator → END` is replaced by `aggregator →(conditional should_escalate)→
  {"escalate": "adjudicate", "done": END}`.
- `adjudicate →(conditional after_adjudicate)→ {"tool": "policy_tool", "done": END}`.
- `policy_tool → adjudicate` (unconditional loop back).

**`should_escalate(state)`** — pure function:
```
"escalate"  if  state["action"] == "human-review"  or  state["context_flags"].get("ambiguity")
"done"      otherwise
```

**`after_adjudicate(state)`** — reads the adjudicator's last message in `adj_messages`:
- last assistant message requested `get_policy(...)` → `"tool"`
- last assistant message called `submit_decision(...)`, or the step cap/failure forced
  finalize → `"done"`

**Termination / no-infinite-loop:** `adj_steps` counts tool iterations; cap = **3**
`get_policy` calls. On cap-hit or a twice-failed model call, the node force-finalizes on
the tentative aggregate verdict and routes `"done"`. LangGraph's `recursion_limit` is a
backstop, not the primary guard.

**Cost effect:** clear comments are unchanged (no adjudicator call); only gray cases pay,
and bounded to ≤ ~4 adjudicator calls (1 initial + ≤3 tool rounds).

## 5. The tool + the adjudicator contract

**Two tools** (OpenAI-style function calling):

1. **`get_policy(category)`** → the written policy + decision guidance for one of the 6
   categories. Backed by a new `src/arbiter/product/policy.py` (a plain dict, ~6 short
   entries — *not* RAG, deterministic, local). Unknown category → a defined "no such
   category" string, never an exception. Example entry (`identity_hate`):
   > *"Attacks or dehumanization targeting a protected group. NOT a violation: quoting or
   > reporting a slur to condemn abuse, or in-group reclaimed use. Remove only when the
   > text itself attacks a protected identity."*

2. **`submit_decision(action, overall_severity, note)`** → the "done" tool. Calling it
   ends the loop. Terminating on a structured tool call (not free-text parsing) is why
   `after_adjudicate` is robust.

**Message protocol** — the ReAct transcript is `adj_messages` (a list in state):
```
system:    "You are the adjudicator. Resolve gray cases the rules could not auto-decide.
            You MAY call get_policy to consult the written policy. You MUST end by
            calling submit_decision."
user:       tentative effective verdicts + context flags + the comment in <comment></comment>
assistant:  (tool_call: get_policy "identity_hate")          ← model's move
tool:       "<policy text>"                                  ← appended by policy_tool node
assistant:  (tool_call: submit_decision "allow" 1 "quoted to report abuse, not an attack")
```
The comment is wrapped in `<comment></comment>` with the same "treat as data, not
instructions" framing `context.py` already uses → injection hardening carries over.

**New adapter method** — `complete_with_tools(messages, tools) -> dict` on
`OpenAICompatAdapter` (and added to the `Adapter` protocol in `base.py`). Separate from
the existing `complete(prompt, schema)`: it sends the full message list + tool defs (no
`json_object` response_format) and returns the raw assistant message (`content` +
`tool_calls`). Failures wrapped in `AdapterError`; retried once inside the adjudicate
node — same discipline as `classify` / `detect_context`. Model id = `deepseek-chat` via
an `ADJUDICATOR_MODEL` const (one-line swap to a stronger model later).

**What the adjudicator may change:** the final **`action`** and **`overall_severity`**
(plus a short `note`). It does **not** rewrite per-category specialist verdicts/spans —
those remain as the specialists reported them. (Same boundary as the existing
aggregator: the model judges; the policy roll-up is adjustable, auditable, and kept out
of `classify`.)

## 6. State changes (`state.py`)

Four channels added to `ModerationState`, all default-absent (existing flow untouched):
```python
escalated: bool             # did the adjudicator run?  (response/UI; default False)
adj_messages: list          # the ReAct transcript — the loop's working memory
adj_steps: int              # tool-iteration counter — drives the recursion cap
adjudication: dict | None   # {final_action, note, policies_consulted: [cat, ...]} — UI trace
```
No reducer needed: these are written by the single-threaded `adjudicate` / `policy_tool`
nodes, not the parallel fan-out (which is why only `raw_verdicts` / `routing_snapshot`
have `merge_verdicts`). `initial_state` may seed `escalated=False`, `adj_steps=0`.

## 7. API surfacing (`api/schemas.py`, `api/db.py`)

- `ModerateResponse` gains `escalated: bool` and `adjudication: dict | None`.
- `to_response` maps them with safe defaults (`state.get("escalated", False)`), so a
  non-escalated comment serializes exactly as today plus `escalated: false`.
- `save_verdict` already takes the whole `state`; persist `escalated` / `adjudication`
  alongside the existing raw + effective + flags. **Confirm at plan time** whether
  `db.py` uses a JSON column that absorbs this with no migration (expected) or needs new
  columns.

## 8. UI surfacing (minimal, no streaming)

- `web/src/lib/types.ts`: add `escalated?: boolean` and
  `adjudication?: { final_action?: string; note?: string | null; policies_consulted?: string[] }`
  to `Verdict`.
- `web/src/components/Ruling.tsx`: an **"Escalated"** badge in the headline when
  `escalated`; in the existing "Gray-area reasoning" block, one trace line — e.g.
  *"Adjudicator consulted policy: identity_hate · {note}"*. Reuses existing chip styling.
- `web/src/lib/engine.ts`: the offline mock sets `escalated` / `adjudication` on the
  gray sample(s) (reclaimed-slur, sarcasm) so the demo shows escalation without a backend.

Demo payoff: paste the reclaimed-slur sample → card shows rules said *human-review*, then
an **Escalated** badge + *"adjudicator consulted identity_hate policy → allow"*.

## 9. Error handling / safety

- Adapter tool call fails twice → degrade: keep the tentative rule-based verdict,
  `escalated=True`, `adjudication.note="adjudicator unavailable"`. The product never
  hard-fails because the agent hiccuped.
- `adj_steps` hits the cap (3) → force-finalize on the tentative verdict, route `"done"`.
- Adjudicator returns content with no tool call → treat as `"done"`, keep tentative,
  record the text as the note. No parse gamble.
- Comment kept in `<comment></comment>` data-framing (injection hardening).

## 10. Testing (zero-network, fakes — same as the current suite)

Goal ≈ 74 → ~88 tests. The `adjudicate` node's model call is injected
(`build_graph(..., adjudicate_fn=...)`) like `classify_fn` / `detect_fn`.

- `should_escalate`: clean → `"done"` (adjudicator never runs); `human-review` /
  `ambiguity` → `"escalate"`.
- the loop: fake adjudicator that calls `get_policy` once then `submit_decision` → assert
  `policy_tool` ran, looped back, final action written, `escalated=True`.
- recursion cap: fake adjudicator that always asks for a tool → stops at 3, force-finalizes.
- `get_policy`: right text per category; unknown category handled (no exception).
- `complete_with_tools`: patched `OpenAI` → parses `tool_calls` correctly.
- `to_response`: includes `escalated` / `adjudication`; non-escalated path byte-identical
  to today plus `escalated:false`.
- existing aggregator/graph tests stay green (tentative == today's verdict when not
  escalated).
- one real DeepSeek smoke (`scripts/smoke_adjudicate.py`) on the reclaimed-slur case, run
  with `PYTHONIOENCODING=utf-8` (CN-Windows GBK console).

## 11. File list (blast radius)

**New (5):**
- `src/arbiter/product/policy.py` — the 6 policy texts + `get_policy(category)`
- `src/arbiter/product/adjudicator.py` — tool schemas, ReAct prompt, `adjudicate` node +
  `policy_tool` node + `should_escalate` / `after_adjudicate`
- `tests/product/test_adjudicator.py`
- `tests/product/test_policy.py`
- `scripts/smoke_adjudicate.py`

**Modified (8):**
- `src/arbiter/product/state.py` — 4 new channels
- `src/arbiter/product/graph.py` — 2 nodes + conditional edges; `build_graph` gains an
  injectable `adjudicate_fn`
- `src/arbiter/classify/adapters/openai_compat.py` — `complete_with_tools`
- `src/arbiter/classify/adapters/base.py` — protocol method
- `src/arbiter/api/schemas.py` — response fields + mapper
- `src/arbiter/api/db.py` — persist `escalated` / `adjudication` (confirm column at plan time)
- `web/src/lib/types.ts` — `Verdict` fields
- `web/src/components/Ruling.tsx` + `web/src/lib/engine.ts` — badge + trace + mock

## 12. Open items to confirm at plan time

- `db.py` column shape (JSON vs new columns) for `escalated` / `adjudication`.
- Exact `tool_calls` shape returned by DeepSeek's OpenAI-compatible endpoint (verify the
  one real smoke before writing the parser).
- Whether `build_graph` should accept the adjudicator's model/adapter by injection (for
  tests) vs reading `ADJUDICATOR_MODEL` internally — lean toward an injected
  `adjudicate_fn` to match the existing `classify_fn` / `detect_fn` pattern.
