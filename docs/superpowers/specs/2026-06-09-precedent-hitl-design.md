# Arbiter — Precedent Memory + Human-in-the-Loop Design Specification

**Status:** Approved design (2026-06-09), brainstormed this session. This is the
authoritative spec for the precedent/HITL feature; the implementation plan is derived
from it. Builds on the escalation spec
(`docs/superpowers/specs/2026-06-08-escalation-edge-design.md`).

> One line: the adjudicator gains **case-law memory** — it retrieves similar past
> *human* rulings via semantic search — and **defers low-confidence rulings to a real
> human review queue** (LangGraph `interrupt`/resume); human decisions become new
> precedents, closing a self-improving loop with zero model training.

---

## 1. Why (motivation)

Today the system is fully automatic: `POST /api/moderate` runs the graph synchronously
and the AI's verdict is always final. The `"human-review"` action
(`aggregator.py:29`) is only a *label* — nothing actually waits for a human. And the
adjudicator's only knowledge source is the static written policy; it has no memory of
how similar cases were decided before.

This spec fixes both, as one coherent loop:

1. **`search_precedents` tool** — the adjudicator consults past human rulings
   (semantic search over a precedent store), like a judge consulting case law.
2. **Real HITL** — escalated cases the adjudicator is *not confident* about pause via
   LangGraph `interrupt()` + a checkpointer, land in a review queue, and resume when a
   human rules.
3. **Feedback loop** — every human ruling is written back as a precedent, retrievable
   by the adjudicator on future cases. The system improves with use, no training.

Portfolio framing (the reason this feature exists — see `project-career-and-portfolio`
memory): Arbiter's job is to demonstrate **agent engineering**. This adds the three
hottest interview topics in one feature: agent memory/RAG-lite, HITL with
checkpointing, and a self-improving loop. VidInsight covers data-pipeline engineering;
Arbiter deliberately stays the agent showcase — so the review UI is minimal, and the
narrative centers on the agent loop, not the workbench.

## 2. Goals & non-goals

**Goals (this spec):**
- A second adjudicator tool, `search_precedents(query)`, returning top-k similar past
  human rulings from a precedent store (embedding + cosine, plain columns, no vector DB).
- Confidence-gated HITL: `submit_decision` gains a `confidence` field; low-confidence
  (or human-review) rulings `interrupt()` into a persisted review queue; a human
  decision resumes the graph from its checkpoint.
- Human rulings (only) written back as precedents — clean "human case law," no
  AI-feeding-AI contamination.
- A minimal review page in the existing React app (list + AI recommendation + two
  buttons). Demo-able, not a workbench.
- Zero-breakage: existing 91 tests stay green; the no-checkpointer graph behaves
  byte-identically to today.
- Same discipline: injected LLM/embedding calls, zero-network tests, bounded loops.

**Non-goals (deferred):**
- Vector database / pgvector — the store is hundreds of rows; cosine in Python on JSON
  columns is the deliberately-boring right answer. Revisit only if the store grows.
- AI rulings as precedents — excluded on purpose (contamination; see §5).
- Reviewer auth/roles, multi-reviewer workflows, SLAs — out of scope for a demo queue.
- Streaming the adjudicator transcript — separate concern, unchanged.
- Retraining/fine-tuning of any kind.

## 3. Decisions locked (brainstorming 2026-06-09)

1. **Direction = deepen the agent story** (1–2 week budget). *Rejected:* debate panel
   (flashy but contested gains; would demand its own eval to defend in interviews —
   possible later as an add-on, debates could even be stored as precedents);
   tool-rich investigator (low narrative ceiling, fake user-history data invites
   awkward interview questions).
2. **Precedents = human rulings only.** The interview-proof answer to "doesn't
   feeding outputs back degrade it?" is "AI rulings never enter the store."
   Cold start via a seed script (~12 hand-labeled gray cases).
3. **HITL trigger = confidence-gated, not all-or-nothing.** The adjudicator always
   produces a recommendation + confidence; only `final action == "human-review"` OR
   `confidence < CONFIDENCE_THRESHOLD` actually pauses. Demo stays snappy; truly gray
   cases showcase the queue. *Rejected:* pausing every human-review case (demo turns
   into "please wait for a human" too often).
4. **Embeddings = OpenAI `text-embedding-3-small`** (DeepSeek has no embedding API;
   the OpenAI key already exists for the routing table). Injected `embed_fn` keeps
   tests offline.
5. **Checkpointer = opt-in parameter.** `build_graph(..., checkpointer=None)` default
   compiles exactly as today (no thread_id needed) — this is what keeps the existing
   suite green. The app passes a SQLite checkpointer; HITL tests pass an in-memory one.
6. **Working protocol:** Claude writes the spec, tests, file skeletons, and TODOs;
   the author implements the core code; the author runs all git operations.

## 4. Architecture — topology & control flow

```
START ─ [6 specialists + context] ─► aggregator (tentative)
                                          │
                                 should_escalate?            (unchanged)
                               ┌──────────┴───────────┐
                            "done"                "escalate"
                               │                      ▼
                               │                ┌─► adjudicate ──┐
                               │                │       │        │
                               │         after_adjudicate?       │
                               │          ┌─────┴─────┐          │
                               │       "tool"      "done"        │
                               │          ▼            │         │
                               │     tools_node ───────┘         │   ◄─ the cycle
                               │   (get_policy | search_precedents)
                               │                        │
                               │                 needs_human?         (NEW)
                               │              ┌─────────┴─────────┐
                               │         "finalize"          "human"
                               │              │                   ▼
                               │              │            human_review node
                               │              │            interrupt(payload) ◄─ graph pauses,
                               │              │                   │              checkpoint saved
                               │              │       (resume: human decision)
                               │              │                   │
                               ▼              ▼                   ▼
                              END ◄───────────┴───────────────────┘
```

**Changed:** the former `policy_tool` node becomes a generic **`tools_node`** that
dispatches each batched tool call by name (`get_policy` → policy text,
`search_precedents` → formatted precedent list), each reply carrying its
`tool_call_id` (the DeepSeek-batches lesson from the escalation spec carries over).

**New:** after the adjudicator submits ("done"), a conditional edge **`needs_human`**:

```
"human"     if final action == "human-review"
            or adjudication.confidence < CONFIDENCE_THRESHOLD
"finalize"  otherwise
```

The **`human_review` node** calls `interrupt(payload)` where payload = the AI's
recommendation (`{recommended_action, overall_severity, note, confidence,
policies_consulted, precedents_consulted}`). On resume it receives the human decision
`{action, note}`, overwrites `action`, marks
`adjudication.human = {action, note}`, and the graph runs to END.

**Degrade path interaction:** if the adjudicator is unavailable (existing
twice-failed degrade), the kept rule-based verdict carries **no `confidence` key**;
`needs_human` reads `adjudication.get("confidence", 1.0)`, so only the *action*
decides: a degraded human-review verdict queues (correct: the agent couldn't help, a
human should), while a degraded allow/remove still finalizes directly, as today.

**No-pause guarantee:** `interrupt()` is only reachable on the escalated branch.
Clean cases never pause and never need a checkpoint round-trip.

**Constants:** `CONFIDENCE_THRESHOLD = 0.7` (tune after live smoke);
`MAX_TOOL_STEPS` now covers both tools — confirm at plan time whether 3 still
suffices or becomes 4.

## 5. The precedent store (`src/arbiter/precedents.py` — new, top-level)

Sits between product and api layers (both use it), so it lives at package top level.

```python
class PrecedentStore:
    def __init__(self, session_factory, embed_fn=default_embed_fn): ...
    def add(self, comment, action, overall_severity, note, source="human") -> None
    def search(self, query_text, k=3) -> list[dict]   # cosine top-k, [] if empty store
```

- **Model:** `Precedent` joins the existing declarative `Base` in `api/db.py`
  (single metadata, one `create_all`): `id, comment_text, embedding (JSON list[float]),
  action, overall_severity, note, source ("human"), created_at`.
- **`default_embed_fn(texts) -> list[list[float]]`** calls OpenAI
  `text-embedding-3-small` (`EMBED_MODEL` const). Tests inject a deterministic fake.
- **Similarity:** cosine in pure Python over all rows (hundreds at most — measured
  non-problem; this "boring on purpose" call goes in NOTES).
- **Write policy:** ONLY human rulings enter (`source="human"` enforced at the two
  call sites: review resolution + seed script). AI rulings never written.
- **Tool formatting:** `search_precedents` returns each hit as
  `"<precedent> comment: ...; ruling: action=..., severity=...; rationale: ...</precedent>"`
  — precedent text is also untrusted user content, so it gets the same data-not-
  instructions framing as `<comment>`.
- **Failure:** embedding call fails → tool returns
  `"precedent search unavailable"` (string, never an exception); empty store →
  `"no precedents on file"`. The agent continues either way.

## 6. Adjudicator changes (`adjudicator.py`)

- **New tool schema** `SEARCH_PRECEDENTS_TOOL`: `search_precedents(query: string)` —
  "Find how similar past comments were ruled by human moderators. Call this when
  written policy alone doesn't settle the case."
- **`submit_decision` gains `confidence`** (number, 0–1, required): "Your calibrated
  confidence that this ruling is correct. Below {threshold} a human will review it."
- **System prompt** updated: may consult written policy (`get_policy`) AND prior human
  rulings (`search_precedents`); must end with `submit_decision`.
- `make_adjudicate_node` parses + stores `confidence` into `adjudication`;
  `precedents_consulted` collected for the UI trace like `policies_consulted`.
- `policy_tool_node` → `make_tools_node(store)` factory (store injected, same pattern
  as `classify_fn`): dispatches each tool_call by name, one tool reply per call id.
- New `human_review_node` (the `interrupt()` site) + `needs_human(state)` router —
  both pure-glue, fully testable with fakes.
- State (`state.py`): `adjudication` dict gains `confidence` and (post-resume)
  `human`; no new channels expected — confirm at plan time.

## 7. API changes (`api/main.py`, `api/schemas.py`, `api/db.py`)

- **Graph compile:** `build_graph(..., checkpointer=...)`; the app passes
  `SqliteSaver` (new dep `langgraph-checkpoint-sqlite`; connection created with
  `check_same_thread=False` — FastAPI sync endpoints run on a thread pool).
- **`POST /api/moderate`:** generates `case_id` (uuid4) → `thread_id`. Invoke result:
  - no interrupt → behavior identical to today, response gains `status: "final"`.
  - interrupt present → persist a `ReviewCase` row, return
    `{status: "pending", case_id, comment, recommendation}` (no verdict yet;
    `save_verdict` is NOT called for pending cases).
- **New table `ReviewCase`:** `case_id (uuid, unique), comment_text,
  recommendation (JSON — the interrupt payload), status ("pending"/"resolved"),
  created_at, resolved_at`.
- **`GET /api/review-queue`:** pending cases, newest first.
- **`POST /api/review/{case_id}`** body `{action: "allow"|"remove"|"confirm", note?}`:
  1. look up the case (404 unknown, 409 already resolved),
  2. resume: `graph.invoke(Command(resume={action, note}), config={thread_id})`,
  3. `save_verdict` on the final state,
  4. `store.add(..., source="human")` — the feedback loop's write,
  5. mark the case resolved; return the final verdict.
  Steps 3–5 in one DB transaction.
- `ModerateResponse` gains optional `status` / `case_id`; new
  `ReviewCaseOut` / `ReviewDecision` schemas.

## 8. UI (minimal — the agent loop is the star, not the workbench)

- `web/src/lib/types.ts`: `status`/`case_id` on `Verdict`; `ReviewCase` type.
- New route `/review` → `web/src/pages/Review.tsx`: antd Table of pending cases;
  expanding a row shows the comment, the AI recommendation (action + confidence +
  note + which policies/precedents it consulted — reuse Ruling card pieces), and
  buttons **Confirm AI** / **Allow** / **Remove** with an optional note.
- Moderate page: a pending response renders a "Sent to human review" card with the AI
  recommendation and a link to `/review`.
- Offline mock (`engine.ts`): one gray sample returns `status: "pending"` and the
  review page shows it from a local mock list, so the full loop demos with no backend.

## 9. Error handling / safety

- Embedding failure / empty store → informative tool strings, never exceptions (§5).
- Resume of unknown `case_id` → 404; already-resolved → 409 (no double-resume; resume
  idempotency is guarded by the `status` check before invoking the graph).
- Server restart with pending cases → checkpoints live in the SQLite checkpointer DB,
  `ReviewCase` rows in the main DB; the queue survives restarts. (Checkpointer file
  gitignored like `arbiter.db`.)
- Precedent text rendered to the adjudicator is wrapped in `<precedent>` data-framing
  (same injection posture as `<comment>`).
- `create_all` won't ALTER existing tables — same dev note as the escalation spec:
  delete the gitignored `arbiter.db` once after pulling this change.

## 10. Testing (zero-network, fakes; 91 → ~110)

New/changed, all offline (`embed_fn`, `adjudicate_fn`, checkpointer all injected;
HITL tests use `InMemorySaver`):

- **`tests/test_precedents.py`** — add + search ranking with deterministic fake
  vectors; k-truncation; empty store message; embed-failure message; human-only
  source enforced.
- **`tests/product/test_adjudicator.py`** (extended) — `search_precedents` dispatch in
  the tools node (incl. batched mixed `get_policy` + `search_precedents` calls, one
  reply per tool_call_id); `confidence` parsed from `submit_decision`; `needs_human`
  routing table (low conf → human; high conf → finalize; human-review action → human;
  degrade → human only when tentative is human-review).
- **`tests/product/test_hitl.py`** — full-graph with `InMemorySaver`: low-confidence
  fake adjudicator → invoke returns interrupt (graph paused, state checkpointed);
  resume with `Command(resume=...)` → END, human decision in final state; confident
  fake → no pause, identical to pre-HITL behavior.
- **`tests/api/test_review_api.py`** — moderate→pending response shape; queue listing;
  resolve→final verdict + precedent row written + case marked resolved; 404/409.
- **Regression:** entire existing suite green with `checkpointer=None` (default) —
  the compatibility guarantee is itself a test.
- **Live smokes** (`scripts/`): `seed_precedents.py` (~12 hand-labeled gray-case
  precedents, one cheap embedding run), `smoke_hitl.py` (one real
  pause→resume→precedent round-trip).

## 11. File list (blast radius)

**New (7):**
- `src/arbiter/precedents.py` — store + default embed_fn + cosine + tool formatting
- `tests/test_precedents.py`
- `tests/product/test_hitl.py`
- `tests/api/test_review_api.py`
- `scripts/seed_precedents.py`
- `scripts/smoke_hitl.py`
- `web/src/pages/Review.tsx`

**Modified (10):**
- `src/arbiter/product/adjudicator.py` — new tool schema; `confidence`; tools_node
  factory; `human_review_node`; `needs_human`
- `src/arbiter/product/graph.py` — `checkpointer` param; `needs_human` edge;
  `human_review` node; store injection
- `src/arbiter/product/state.py` — `adjudication` shape (confirm: likely no new channel)
- `src/arbiter/api/db.py` — `Precedent` + `ReviewCase` models
- `src/arbiter/api/main.py` — thread_id, interrupt handling, 2 new endpoints, store/
  checkpointer wiring
- `src/arbiter/api/schemas.py` — `status`/`case_id`; review schemas
- `pyproject.toml` — `langgraph-checkpoint-sqlite`
- `web/src/lib/types.ts` · `web/src/lib/api.ts` — types + 2 calls
- `web/src/App.tsx` (or router entry) — `/review` route
- `web/src/lib/engine.ts` — offline mock pending sample

**Follow-ups after merge (not this spec's code):** README architecture diagram +
"why it's interesting" bullet; NOTES design-record entry; resume bullet ("agent
retrieves human precedents via semantic search and defers low-confidence rulings to a
human review loop whose decisions become new precedents — self-improving, zero
training").

## 12. Open items to confirm at plan time

- Installed `langgraph` version supports `interrupt()` / `Command(resume=...)`
  (needs ≥ 0.2.31; check `pip show langgraph`) and the exact interrupt shape on a
  sync `invoke` (`__interrupt__` key) — pin the assertion in `test_hitl.py` to what
  the installed version actually returns.
- `MAX_TOOL_STEPS`: 3 → 4 now that two query tools share the cap?
- Whether the reviewer may also override `overall_severity` or only `action`
  (lean: action only — severity stays the specialists'/adjudicator's).
- `CONFIDENCE_THRESHOLD = 0.7` starting value — sanity-check against the live smoke
  (DeepSeek's self-reported confidence calibration is unknown).
- Postgres checkpointer (`langgraph-checkpoint-postgres`) for the prod deploy —
  decide when doing the deployment task, not here.
