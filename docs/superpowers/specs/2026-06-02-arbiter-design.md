# Arbiter — Design Specification

**Status:** Approved design (2026-06-02), revised after spec review (2026-06-02).
This is the authoritative spec. `NOTES.md` is the decision record / rationale; this
document is the consolidated, implementation-ready design the implementation plan is
derived from.

> Tagline: *"It judges content. You judge the judges."*

---

## 1. Overview

Arbiter is a multi-agent **AI content-moderation** analyzer with an empirical
**cross-model LLM evaluation** layer.

- **Product:** paste a comment → per-category harm labels, a severity, a suggested
  action (remove / human-review / allow), and a short reason citing the offending
  span.
- **Differentiator (the résumé centerpiece):** benchmark **4 model families
  (GPT / Claude / Gemini / DeepSeek)** on a public labeled dataset (Jigsaw) for both
  **accuracy** and **demographic fairness**, then route each harm category to the
  model that scores best and fairest on it. (Narratively: three frontier labs +
  DeepSeek as the cheap, OpenAI-compatible dev/runner contestant.)

**This is NOT "a toxicity classifier."** The value is *evaluating which model
moderates best and most fairly*, plus handling sarcasm / quoted-slur gray areas via
a multi-agent design.

### 🚨 No model training
LLMs are pre-trained and called via API. The labeled dataset is the **answer key**
used to *score* models — never training fuel. The product runs with zero dataset
(models are pre-trained); the dataset only powers the eval layer.

---

## 2. Goals & non-goals

**Goals (MVP / v1):**
- A shared `classify` primitive both layers call.
- A self-built eval harness producing per-category P/R/F1 + a fairness slice + a
  committed `routing_table.json`.
- A LangGraph product pipeline that reuses `classify` and the routing table.
- A thin FastAPI + Next.js demo deployed to a live URL.
- English-only.

**Non-goals (explicitly out of scope for v1):**
- No fine-tuning / training (a fine-tuned 4th contestant is a rejected stretch).
- **No harm categories beyond the Jigsaw 6.** No self-harm, sexual-content-involving-
  minors, spam, CSAM, etc. in v1 — each new category requires a matching public
  benchmark or a hand-labeled set first (see §4).
- No file-upload path (paste-text only; file upload is v1.1).
- No pgvector / RAG / "find similar past cases" (kept out to stay differentiated
  from DocSense).
- No Chinese-moderation numbers (Jigsaw is English; Chinese needs COLD/ToxiCN —
  future).
- No full Jigsaw bias-AUC (Subgroup/BPSN/BNSP); v1 uses the simpler FPR-gap metric.
- No Postgres dependency in the eval layer (eval is file-based).

---

## 3. Architecture: three layers, built eval-core first

```
classify (shared primitive)
   ├── eval harness  → routing_table.json   [BUILD TIME, offline]
   └── product pipeline (LangGraph)          [RUN TIME, per request]
            reads routing_table.json
```

**Build order:**
1. `classify(model, comment, categories=ALL_6)` — the primitive everything sits on.
2. Eval harness on top of it → P/R/F1 + fairness tables + `routing_table.json`.
3. Product pipeline (LangGraph) that reuses `classify` + consumes the routing table.
4. Thin FastAPI + Next.js demo.

The harness lives in the `eval/` package only and **never runs in production**.
The **only** artifact crossing eval → product is `routing_table.json`.

### Category set (locked)
All **6 Jigsaw labels**, so the eval maps 1:1 to the benchmark:

`toxic · severe_toxic · obscene · threat · insult · identity_hate`

→ 6 specialist agents + 1 context/sarcasm agent + 1 aggregator. This same 6-label set
is the canonical category set everywhere in code and eval — see §4 for how the product
UI relates to it.

---

## 4. Product taxonomy vs benchmark taxonomy

The product and the eval share **one** category set, so every product label has an
eval number behind it. This is the core promise — *"you judge the judges."*

- **Canonical set = the 6 Jigsaw labels** (`toxic, severe_toxic, obscene, threat,
  insult, identity_hate`) everywhere in code and eval.
- **The UI may use productized display names** (e.g. "Hate / identity attack" for
  `identity_hate`, "Threats" for `threat`), but each maps **1:1** to a Jigsaw label —
  no invented categories.
- **No full Trust & Safety policy claim.** Arbiter does NOT claim to cover a complete
  platform moderation taxonomy (self-harm, sexual content involving minors, spam,
  CSAM, …). It covers exactly what the benchmark labels, and says so.
- **Every product category MUST have an eval number behind it.** A category with no
  labeled benchmark has no F1, no fairness slice, and no routing basis → it does not
  ship.
- **v1.1+ extension rule:** new real-platform categories may be added **only** paired
  with a matching public benchmark or a hand-labeled set. This is what lets you answer
  *"where does your self-harm F1 come from?"* with *"we don't claim one — it's not in
  v1; adding it requires a labeled set first."*

---

## 5. The `classify` primitive

The shared function both the eval harness and the product pipeline call.

```
classify(model: str, comment: str, categories: list[str] = ALL_6)
    -> { category: {severity, reason, span} }   # one entry per requested category
```

**Decisions (locked):**

1. **Return contract = graded ordinal per category.** Each category gets a severity
   ordinal: `none / low / medium / high` (→ 0/1/2/3).
   - Eval: threshold the ordinal to binary (0/1) and compare to Jigsaw's 0/1 gold
     labels. The ordinal lets the eval sweep thresholds → precision/recall curves.
   - Product: the same ordinal *is* the displayed severity (computed once).
   - *Rejected:* plain binary (no sweep); calibrated 0–1 float (LLMs aren't
     well-calibrated → defends worse than a clean ordinal).

2. **Call shape = category-subset param.** `categories` defaults to all 6.
   - Eval: pass all 6 → **1 call per comment per model** (keeps the budget).
   - Product: each specialist node calls the same function scoped to its **one**
     category, on that category's routed model (~6 calls/comment — fine at demo
     volume).

3. **Boundary = pure judgment only.** `classify` returns per-category
   `{severity, reason, span}`. It does **NOT** decide overall severity or the
   remove/review/allow action — those are policy roll-ups the **aggregator**
   (product-only) computes. This keeps the cross-model eval measuring *detection*
   only (clean F1), and keeps the action rule in our own auditable code.
   - `span` = verbatim offending substring (nullable); the frontend highlights by
     string-match.

4. **Structured output = each provider's native structured-output feature + one
   shared Pydantic schema.** The schema is defined once (single source of truth) and
   validates every response regardless of provider. Plumbing differs per provider
   (OpenAI `json_schema` / Gemini `response_schema` / Anthropic structured-outputs
   or forced tool-use); **the prompt body stays identical across providers** so the
   comparison is fair. Retry once on a validation failure.
   - *Rejected:* prompt-and-parse (fragile → wasted eval samples nick headline F1).

5. **Model abstraction = registry + adapter.** A registry maps a model-id string
   (`"gpt-4o-mini"`, `"deepseek-chat"`, …) → `{adapter, base_url, api_key_env,
   real_model_name}`. Each adapter implements one method,
   ~`complete(prompt, schema) -> dict`. Domestic OpenAI-compatible models (DeepSeek,
   Qwen, Kimi, GLM…) reuse **one** OpenAI-compatible adapter; Gemini and Anthropic
   get their own. **Adding a model = one registry line.**

### Shared schema (Pydantic, single source of truth)

```python
class Severity(IntEnum):  # ordinal
    none = 0; low = 1; medium = 2; high = 3

class CategoryVerdict(BaseModel):
    severity: Severity
    reason: str            # short justification
    span: str | None       # verbatim offending substring, nullable

class ClassifyResult(BaseModel):
    # one CategoryVerdict per requested category, keyed by Jigsaw label
    verdicts: dict[str, CategoryVerdict]
```

### Severity rubric (anchored in the shared prompt)
The four levels get **explicit definitions baked verbatim into the shared prompt**, so
all 4 model families score against one rubric — not their own intuition. This both
stabilizes the threshold sweep and strengthens cross-model fairness (same ruler for
everyone). Applied **per category**:

- **none (0):** no policy-relevant harm for this category.
- **low (1):** mild or ambiguous — borderline toxicity, a weak/uncertain insult,
  plausibly-but-not-clearly harmful.
- **medium (2):** clear harmful content in this category; a likely human-review
  candidate.
- **high (3):** severe — a credible direct threat, an explicit identity attack, or
  severe abuse; an explicit removal candidate.

Each category instantiates the rubric (e.g. `threat` high = a credible, directed
threat of violence; `identity_hate` high = an explicit dehumanizing attack on a
protected group). The rubric text is part of `PROMPT_VERSION`.

### Prompt versioning
The shared prompt template carries a `PROMPT_VERSION`; the schema carries a
`SCHEMA_VERSION`. Both feed the eval cache key (§6.1) so changing either (including the
rubric wording) auto-invalidates stale cached predictions.

---

## 6. Eval harness

Sits on top of `classify`. Job: run the contestants over a frozen Jigsaw sample →
per-category P/R/F1 + fairness slice + the routing table. File-based; no DB.

**Contestants (locked):** **4 model families — GPT, Claude, Gemini, DeepSeek.** All at
each provider's **cheapest same-class small-chat tier** (gpt-4o-mini / claude-haiku /
gemini-flash / deepseek-chat). ⚠️ Same-tier is mandatory — a "pro"/reasoning model vs
everyone else's mini is a tier artifact, not a real finding. Exact ids are swappable
config. (Qwen optional — one registry line anytime; not in MVP.)

### 6.1 Collect ≠ score, with a cache (two-phase)
- **Collect:** for each contestant, run `classify` over the frozen sample and write
  raw per-comment / per-category outputs to a **JSONL cache**. Already-cached items
  are skipped → resumable; a mid-run crash doesn't re-spend.
  - **Cache key = model id + PROMPT_VERSION + SCHEMA_VERSION.** Change the prompt or
    schema → stale entries auto-invalidate and re-run.
- **Score:** read the cache, compute everything. **No API calls.** Re-scoring (new
  metric, threshold, bug fix, nicer table) is free and instant.
- *Rejected:* one-pass (re-spends every time you touch scoring; loses progress on
  crash; no auditable raw record).

**Dev workflow this enables:** prove the whole pipeline on DeepSeek + a tiny sample
(or a `$0` mock adapter) → 4-model smoke test (~10 comments each, catches
provider-specific parse fails cheaply) → one full run. Adding the 3 expensive models
later only pays for *their* calls; DeepSeek's cached predictions stay. Keep the
prompt provider-neutral so it isn't overfit to DeepSeek.

### 6.2 Threshold = sweep, not fixed
The ordinal has 4 levels → 3 cutoffs (`≥low` / `≥med` / `≥high`). Try all 3 per
category, offline on cached data (free). Pick a per-category operating point that
reflects asymmetric cost (loosen for high-cost-to-miss categories). Report **one
headline F1 per category** at the chosen point (clean table) plus a small
precision/recall-tradeoff chart from the sweep.

### 6.3 Fairness = per-group false-positive rate + the gap (Route A)
On **benign** comments (gold = not toxic) from the Unintended-Bias subset, split by
mentioned identity group, compute each group's over-flag (false-positive) rate, then
compare across groups. Headline = "which groups get over-flagged, by how much, per
model" — tells the `"I am a gay man"` over-flagging story. It's just counting →
trivial to compute and explain.
- *Rejected for MVP:* full Jigsaw bias-AUC (Subgroup/BPSN/BNSP generalized mean) —
  more rigorous but heavy and not legible; a later stretch.

### 6.4 Routing rule = F1 baseline + 2 documented overrides
Per category:
1. Default to the highest-F1 model.
2. **High-risk override** (`threat`, `identity_hate`): prefer higher **recall**
   among the top models (missing these is the costly error).
3. **Near-tie tiebreak:** break by **fairness** (lower over-flag gap).

This makes the asymmetric-cost + fairness analyses actually *feed* routing, not just
decorate the report. All offline.

### 6.5 Storage
- `routing_table.json` (category → `{model, threshold}`) — **committed to the repo**;
  the **only** artifact crossing eval → product. The product reads it at startup
  (small, versioned, git-diffable). NOTE: the `threshold` field records the eval's
  chosen operating point per category; whether the product also uses it to gate "is
  this category flagged" vs. acting on the raw ordinal is a small detail deferred to
  the implementation plan.
- Full metrics → per-run files under `eval/results/<date>/` (JSON/CSV); the report
  reads those.
- **Postgres = product runtime only.** Eval is file-first; pushing metrics into
  Postgres is deferred until a queryable dashboard needs it (YAGNI).

---

## 7. Datasets & sampling

- **Accuracy:** Jigsaw Toxic Comment Classification (~160k comments, the 6 labels,
  multi-label).
- **Fairness:** Jigsaw Unintended-Bias in Toxicity Classification (~1.8M comments
  with identity annotations).
- **Sample (locked):** a **stratified** sample — ~2–3k comments for accuracy,
  ensuring **≥~150–200 positives per category** (incl. rare `threat` /
  `identity_hate`), + ~1–2k for the fairness identity slice. ~12–15k cheap-tier calls
  total. **Stratified is mandatory** — random sampling starves the rare categories.
- The frozen sample is written to a file so every model sees identical comments
  (fair + reproducible).
- Raw Jigsaw CSVs live under `data/` and are **gitignored** (large, licensed).

---

## 8. Benchmark limitations & eval credibility

Stated up front — signalling eval maturity (knowing a benchmark's limits) beats
blindly reporting F1.

- This is a **comparative product eval**, not a novel academic benchmark. The claim is
  *"model X moderates category Y better/fairer than model Z on this data,"* not *"here
  is a new SOTA benchmark."*
- **Contamination is possible.** Jigsaw is public and may be in the models' pretraining
  data, so absolute F1 may be optimistic. The **relative** comparison across same-tier
  contestants is the load-bearing result, and contamination hits all contestants
  similarly.
- The durable value is the **harness, routing logic, threshold sweep, and fairness
  analysis** — the engineering and the method — not the headline F1 number.
- **Future hardening (out of v1, recorded):** a small **private, hand-labeled holdout**
  (a few hundred items) to (a) sanity-check against contamination and (b) include items
  closer to a real moderation queue. This is the credibility-upgrade path, paired with
  the v1.1 taxonomy-extension rule in §4.

---

## 9. Product pipeline (LangGraph) — approved 2026-06-02, refined in review

**Principle: LLMs judge; code decides policy.** Three node types:

```
user pastes comment → Next.js → POST → FastAPI → LangGraph:
  (a) 6 specialist nodes IN PARALLEL  → RAW per-category {severity, reason, span}
  (b) context/sarcasm node            → MODIFIERS (flags) only, NO re-scoring
  (c) aggregator node (deterministic) → adjust severities by flags → action
```

**(a) Specialist nodes — 6, in parallel.** Each = `classify(routed_model_for_cat,
comment, [that_category])` with the model read from `routing_table.json`. They produce
**raw verdicts only**. Clean multi-agent DAG, best to explain. *Micro-opt (later):* if
several categories route to the same model, batch them into one call; keep 6 separate
nodes for the MVP demo.

**(b) Context/sarcasm node — runs on every comment, emits MODIFIERS only.** It does
**NOT** re-score severity. Output = `context_flags` (booleans) + an optional one-line
note:
- `sarcasm` — the harmful-looking text is a joke / not literal
- `quotation` — the slur/threat is quoted, not asserted by the author
- `reclaimed_slur` — an in-group reclaimed term, not an attack
- `direct_threat` — a credible, directed threat (not hyperbole)
- `ambiguity` — genuinely unclear; needs a human

This is where the multi-agent design earns its keep (gray-area reasoning) **without**
letting an LLM silently overwrite the measured classifier output. *Demo cadence:* every
comment (tiny volume → effectively free). *Future upgrade:* run only on gray cases (≥1
non-`none` verdict, or emoji/quotes/negation present) via a LangGraph conditional edge.

**(c) Aggregator node — pure deterministic code (NO LLM).** Takes the 6 raw verdicts +
`context_flags` → effective verdict + action, in two steps:

1. **Modifier adjustments (explicit rules only):**
   - `sarcasm OR quotation OR reclaimed_slur` → downgrade `toxic / obscene / insult /
     identity_hate` by **one** level (floor = `none`).
   - `direct_threat` → upgrade `threat` to at least `high`.
   - no flag → severity unchanged.
2. **Action rule table (on the adjusted severities):**
   - any category `high` → **remove**
   - else any category `medium` → **human-review**
   - else (all `none`/`low`) → **allow**
   - **Safety override:** if `ambiguity` is set AND any category ≥ `low` AND the action
     would be `allow` → escalate to **human-review** (never auto-allow a flagged gray
     case).
   - **overall severity = max across categories** (`threat` / `identity_hate` may be
     weighted heavier). All thresholds/rules live in our own auditable code.

**Why this shape:** `classify` measures detection (clean F1 — exactly what the eval
scores), while the product's deviation from the raw classifier is **fully deterministic
and explainable**. No magic LLM re-judging that would make product behavior diverge from
the eval numbers in an unmeasurable way. (This is decision §5.3 — "policy in code" —
applied end-to-end.)

---

## 10. End-to-end flow (both phases)

```
═══ PHASE 1 — BUILD TIME (offline) → produces the routing table ═══
 Jigsaw datasets
   │ ① prep: frozen stratified sample (≥150–200 pos/cat) + fairness subset
   ▼
 [frozen sample file]
   │ ② collect: 4 models each run classify(model, comment, ALL_6) → ordinals
   ▼
 [raw cache .jsonl]      ← paid ONCE; re-scoring never re-calls APIs
   │ ③ score: threshold sweep → per-cat P/R/F1; fairness FPR-gap; pick op points
   ▼
 [metrics report] + ④ route: F1 baseline + recall/fairness overrides
   ▼
 ★ routing_table.json (category → {model, threshold})  ← committed to repo
        │  (the ONLY thing crossing eval → product)
        ▼
═══ PHASE 2 — RUN TIME (product, per request) ═══
 paste comment → Next.js → POST → FastAPI → LangGraph
   ├─ (a) 6 specialist nodes in parallel → RAW verdicts
   ├─ (b) context/sarcasm node          → context_flags (modifiers only)
   └─ (c) aggregator (deterministic)    → adjust by flags → overall severity + action
   ▼
 FastAPI stores input + raw + flags + effective verdict in Postgres → returns verdict
   ▼
 UI: per-category labels + severity + highlighted spans + reasons + action
```

---

## 11. Data model (product runtime, Postgres)

Minimal — product runtime only.

- `submissions`: `id, comment_text, created_at`
- `verdicts`: `id, submission_id (fk), overall_severity, action,
  raw_verdicts (jsonb: per-category {severity, reason, span} from the specialists),
  context_flags (jsonb: the modifier booleans + note),
  effective_verdicts (jsonb: per-category severity after deterministic adjustment),
  routing_snapshot (jsonb: which model judged each category), created_at`

Storing raw + flags + effective side by side keeps the aggregator's deterministic
adjustment fully auditable after the fact. (Eval results are **not** stored here —
they're files under `eval/results/`.)

---

## 12. API surface (FastAPI) — thin/standard

- `POST /api/moderate` → `{ comment }` → runs the LangGraph pipeline → returns
  `{ overall_severity, action, categories: [{name, severity, reason, span}],
  context_flags }`; persists the submission + verdict.
- `GET /api/health` → liveness.
- (optional) `GET /api/history` → recent submissions for the dashboard.

Routing table loaded once at startup.

---

## 13. Frontend (Next.js + Tailwind) — thin/standard

- A textarea → submit → a verdict card: overall action badge + per-category rows
  (label, severity chip, reason) + the comment with offending **spans highlighted**
  (string-match on `span`). Context flags (sarcasm/quotation/…) shown as small chips
  so the gray-area reasoning is visible.
- Optional: a small "how the judges scored" page rendering the eval comparison table
  (static, from a committed metrics file) — cheap way to surface the differentiator.

---

## 14. Tech stack (locked)

| Layer | Choice |
|---|---|
| Backend | Python + FastAPI |
| Agent orchestration | LangGraph |
| LLMs | GPT + Claude + Gemini + DeepSeek (cheapest same-class tier) |
| Benchmark data | Jigsaw Toxic Comment + Jigsaw Unintended-Bias |
| Eval | lightweight self-built harness (~few hundred lines) |
| DB | PostgreSQL (product runtime only) |
| Frontend | Next.js + Tailwind |
| Deploy | Vercel (frontend) + Railway/Render (backend + Postgres) |

Python 3.14 (matches DocSense) unless a wheel fails. Provider plumbing differs;
prompt body is identical across providers.

---

## 15. Proposed repository structure

```
arbiter/
  pyproject.toml
  routing_table.json            # committed artifact (eval → product)
  data/                         # gitignored: raw Jigsaw CSVs
  src/arbiter/
    classify/
      schema.py                 # Pydantic: Severity, CategoryVerdict, ClassifyResult
      core.py                   # classify(model, comment, categories=ALL_6)
      registry.py               # model-id -> {adapter, base_url, api_key_env, name}
      prompt.py                 # shared template + rubric + PROMPT_VERSION
      adapters/
        base.py                 # Adapter protocol: complete(prompt, schema) -> dict
        openai_compat.py        # reused: OpenAI + DeepSeek + Qwen + ...
        gemini.py
        anthropic.py
    eval/
      sample.py                 # build frozen stratified sample
      collect.py                # run classify over sample -> JSONL cache (resumable)
      score.py                  # threshold sweep, P/R/F1
      fairness.py               # per-group FPR + gap
      route.py                  # build routing_table.json
      report.py                 # render comparison tables
      results/<date>/           # per-run metrics (json/csv)
    product/
      graph.py                  # LangGraph pipeline (6 specialists + context + agg)
      nodes.py                  # node implementations
      context.py                # context/sarcasm node — emits modifier flags
      aggregator.py             # deterministic policy: flags + verdicts -> action
      routing.py                # load routing_table.json
    api/
      main.py                   # FastAPI app
      db.py                     # Postgres models / session
  web/                          # Next.js + Tailwind
```

---

## 16. Cost

~$10–15 per full eval run (cheap tiers + sampled split); ~$30–80 across the project
with dev re-runs. Mitigations: dev against one provider / mock the rest; Gemini free
tier; or an aggregator (e.g. OpenRouter) = one balance + one OpenAI-compatible
endpoint to reach all contestants. The two-phase cache means API money is spent once.

---

## 17. Future stretches (out of v1, recorded so they're not lost)

- Conditional context/sarcasm node (run only on gray cases).
- Batch same-routed categories into one product call.
- Full Jigsaw bias-AUC (Subgroup/BPSN/BNSP).
- A small private hand-labeled holdout set (contamination check + realistic items).
- New harm categories (self-harm, sexual-minors, spam, …) — **only** with a matching
  benchmark or hand-labeled set (§4 extension rule).
- File-upload path (`unstructured`).
- Chinese moderation via a Chinese labeled set (COLD / ToxiCN).
- Fine-tuned small open model as a 4th eval contestant.
- pgvector "find similar past cases" (explicitly de-prioritized to stay distinct
  from DocSense).
- Push eval metrics into Postgres for a queryable dashboard.

---

## 18. Working preferences (carry-over)

- **The author writes the implementation code.** Claude scaffolds, explains, and
  smoke-tests, but does not ghost-write core feature modules.
- **Claude never runs `git commit` / `add` / `push`** — it proposes the message; the
  author runs git.
- US-facing repo → README and user-facing copy in product/impact English.
