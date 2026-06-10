# Arbiter — Project Notes & Decision Record

> Portable context/handoff doc (NOT the final spec). Captures what was decided
> during the 2026-06-01 brainstorm so a fresh session — opened in *this* repo —
> has the full picture. The original discussion happened in a DocSense session;
> Claude memory does not auto-carry across repos, so this file is the anchor.

**Status (2026-06-10):** built. Classify primitive + eval harness (real 2-model
run → `routing_table.json`), LangGraph pipeline with the tool-using adjudicator
(escalation, 2026-06-08), **precedent memory + human-in-the-loop review**
(2026-06-10, live-verified — see the design record at the bottom), FastAPI + React
with the review docket. 122 zero-network tests green. Sections below are in
chronological order: the 2026-06-01 design-phase notes first (kept as the record
of *why*), build-phase design records appended at the end.

---

## TL;DR

**Arbiter** = a multi-agent **AI content-moderation** analyzer with an empirical
**cross-model evaluation** layer.

> Tagline: *"It judges content. You judge the judges."*

Two identities in one project:
- **Product:** paste a text/comment → it tells you whether it's harmful, in which
  ways, how severe, and what to do (remove / send to human review / allow), with
  reasoning.
- **Research / résumé centerpiece:** it benchmarks GPT / Claude / Gemini / DeepSeek (4 model families) to prove
  *which model moderates best — and most fairly — per harm category*, then routes
  accordingly.

---

## What it is — three layers

1. **Product layer (what a user sees).** Input a comment/post → per-category
   labels + severity + suggested action + a short reason, each citing the
   offending span. A simple moderation dashboard. → *full-stack + demoable signal.*
2. **Multi-agent layer (engineering core).** Not one classifier — several
   specialist agents run in parallel, one per harm category, plus a
   context/sarcasm agent for the gray areas, plus an aggregator that decides the
   final action. Orchestrated with **LangGraph**. → *agent-orchestration signal.*
3. **Evaluation layer (the differentiator).** Benchmark 4 model families (GPT /
   Claude / Gemini + DeepSeek) against
   a public labeled dataset → per-category precision/recall/F1 + a fairness slice
   → decide which model to route each category to. → *LLM-eval depth signal.*

---

## Multi-agent design (draft)

- One specialist agent per harm category: **hate**, **harassment/threats**,
  **sexual / minors**, **self-harm** (category set ≈ Jigsaw's labels; trim for MVP).
- A **context & sarcasm agent** for the hard cases: `"I'll kill you 😂"` between
  friends vs a real threat; a quoted/reclaimed slur used to *condemn* abuse vs to
  commit it. This is where the multi-agent + LLM-reasoning approach earns its keep.
- An **aggregator agent** combines the specialist verdicts → final action +
  confidence.

---

## Evaluation — the centerpiece (read this carefully)

- **Benchmarks:** **Jigsaw Toxic Comment Classification** (≈160k comments, 6 harm
  labels, multi-label) for accuracy; **Jigsaw Unintended-Bias in Toxicity
  Classification** (≈1.8M comments with identity annotations) for **demographic
  fairness** — i.e. does a model over-flag benign sentences that merely *mention*
  an identity (`"I am a gay man"`)? Measuring + reducing this bias is a standout
  interview story almost nobody puts in a portfolio.
- **What we measure:** per-category precision/recall/F1 across the 3 models, with
  attention to the **asymmetric costs** (missing a real threat ≫ over-censoring a
  joke) and a **bias slice** across identity groups.
- **Routing:** category X → whichever model scored best/fairest on X. This is just
  a lookup table derived from the eval results — no training.
- **The harness:** a lightweight, **self-built** eval runner (~a few hundred
  lines). Mental model: it's like `pytest`, except instead of "does this function
  return the right value" it scores "is the model's answer right" against the gold
  labels, then tallies F1 and prints a model-comparison table. Decided to build
  this ourselves (not a framework like Inspect/DeepEval/promptfoo) so every line is
  explainable in interviews and there's no framework-learning overhead. (This is
  the same eval skill from all-in-rag chapter C6, applied to moderation.)

### ⚠️ Key concept: NO model training
We **do not train any model.** GPT/Claude/Gemini are pre-trained; we call them via
API (same as DocSense calls DeepSeek). The labeled dataset is the **"answer key"**
used to *score* the models — **not** training fuel. Without a labeled answer key
you can't produce a credible "X% F1" number. (The product itself runs with zero
dataset, since the models are pre-trained; the dataset only powers the eval layer.)
An *optional, not-recommended* stretch would be fine-tuning a small open model as a
4th contestant in the eval — out of scope for the MVP.

### Differentiator framing (do not lose this)
This is **NOT** "I built a toxicity classifier" (a solved, worthless résumé item).
It is **"multi-agent moderation + cross-model evaluation + bias/fairness analysis
+ handling sarcasm/quoted-slur gray areas."** The value is in *evaluating which AI
moderates best and most fairly*, not in detecting toxicity.

---

## Tech stack (locked)

| Layer | Choice | Notes |
|---|---|---|
| Backend | **Python + FastAPI** | LangGraph is Python-first; reuses DocSense skills |
| Agent orchestration | **LangGraph** | parallel specialist agents + aggregator |
| LLMs | **OpenAI + Anthropic + Gemini + DeepSeek** | cross-model A/B is the point; cheap small-chat tier, **same class** across all (gpt-4o-mini / claude-haiku / gemini-flash / deepseek-chat) + sampled split to control cost. Qwen optional. Domestic models = **English-moderation** numbers only (Jigsaw is English). |
| Benchmark data | **Jigsaw Toxic Comment** + **Jigsaw Unintended-Bias** | public, labeled; the "answer key" |
| Eval | **lightweight self-built harness** | ~few hundred lines; pytest-for-models |
| Database | **PostgreSQL** | **product runtime only**: user inputs + verdicts. Eval results are file-based (JSON/CSV); load into Postgres later only if a queryable dashboard needs it |
| (optional stretch) | pgvector | "find similar past cases" — **NOT core**, kept out to stay differentiated from DocSense's RAG |
| Doc parsing | `unstructured` (reuse from DocSense) | only for an optional "upload a file" path |
| Frontend | **Next.js + Tailwind** | SSR + one-click Vercel deploy → the live demo link |
| Deploy | **Vercel** (frontend) + **Railway/Render** (backend + Postgres) | deliverable = a live demo URL |

**Dropped vs the earlier CodeReview idea:** tree-sitter (code AST) and the GitHub App.

---

## Domains considered this session

| Domain | Benchmark | Verdict |
|---|---|---|
| Contracts | CUAD (clean, 41 clause types) | strong + cleanest numbers, but **dry** |
| Privacy policy / ToS | OPP-115 | great alt (name idea: "FinePrint") |
| **Content moderation** | **Jigsaw (+ Unintended-Bias)** | **CHOSEN** — hottest fit for Trust&Safety/eval angle; clean benchmark; unique fairness story |
| Financial filings (10-K risk) | — | **rejected**: no clean labeled benchmark for risk-classification → eval numbers would be self-made/soft |
| Resume screener | — | fun to dogfood, but no clean benchmark → eval too soft |

Common recipe (so the domain is swappable): *text → splits into well-defined
categories → has a public, human-labeled dataset as the answer key.*

---

## Why this project / career framing

- Target (confirmed): **US new-grad full-stack, AI-specialized** (CN NG as fallback).
  Applications open ~late Aug 2026. T-shaped: AI depth now, infra later.
- Arbiter's job in the portfolio: showcase **agent orchestration + rigorous LLM
  evaluation** — the differentiating "AI specialty" signal — on **one demoable,
  live-linked product** (which is what US recruiters click).
- "Eval" depth maps to Trust & Safety / responsible-AI / LLM-eval-leaning roles
  (Anthropic, OpenAI evals, Patronus, Snorkel, etc.), but the *primary* target is
  full-stack-with-AI, not "be a full-time evaluator." The eval is the spice, the
  demoable product is the dish.
- Funnel reminder (how the author thinks about it): the **project gets the resume
  seen** (top of funnel); **LeetCode converts interviews to offers**; a third leg
  is market-specific (**US: behavioral + system design; CN: 八股**). Keep this
  project's scope **tight enough to finish + demo** — a shipped small project beats
  an unfinished big one, *because its whole job is to be seen.*

---

## How it relates to the author's other projects

- **VidInsight-AI** (Java/Spring): a **video-analysis pipeline** (FFmpeg → ASR → LLM
  summary), MQ/Redis/S3/JWT/WebSocket. **NOT RAG.** → backend/infra + AI-pipeline pillar.
- **DocSense** (Python): a **RAG** multi-format document Q&A system (pgvector, hybrid
  retrieval, reranker). → retrieval pillar. *(Was an internship project, since cut;
  continued solo as portfolio.)*
- **Arbiter** (Python): **agent orchestration + LLM evaluation** pillar.

Three projects, three distinct pillars — deliberately so.

---

## Working preferences (how Claude should work with the author here)

These live in the DocSense session's memory and will NOT auto-load in this repo —
recorded here so they carry over:

- **The author writes the implementation code themselves.** Claude scaffolds,
  explains, and smoke-tests, but does **not** ghost-write core feature modules.
  Point + explain + stop.
- **Never run `git commit` / `git add` / `git push`.** Claude signals a commit
  point and proposes the message; the author runs git.
- **Python** is the chosen language. (DocSense pinned 3.14; same is fine here unless
  a wheel fails to install.)
- US-facing repo → README in product/impact English; avoid CN-style framing.

---

## Status & next steps

- [x] Domain locked: content moderation
- [x] Name locked: **Arbiter** (repo: `Arbiter`)
- [x] Tech stack locked
- [x] MVP decisions resolved (see "Decisions locked 2026-06-01" below)
- [x] Architecture approach chosen: eval-core first, product wraps it
- [~] Walking through the design section by section: architecture spine ✓,
      `classify` interface ✓, eval harness ✓, product pipeline drafted (PROPOSED,
      awaiting approval) → next: approve pipeline → quick demo sketch → spec
- [ ] Write the formal design spec (`docs/superpowers/specs/<date>-arbiter-design.md`)
- [ ] writing-plans → implementation plan

## Decisions locked 2026-06-01 (brainstorm cont.)

1. **Harm categories:** ALL 6 Jigsaw labels — toxic / severe_toxic / obscene /
   threat / insult / identity_hate. (Eval table then maps 1:1 to the benchmark.)
   → 6 specialist agents + a context/sarcasm agent + an aggregator.
2. **Eval scope:** medium **stratified** sample — ~2–3k comments for accuracy
   (ensure ≥~150–200 positives per category, incl. the rare threat / identity_hate),
   + ~1–2k for the fairness identity slice. ~12–15k cheap-tier calls total.
   Stratified is mandatory: random sampling starves the rare categories.
3. **Demo input:** paste-text only for MVP; file-upload path deferred to v1.1.
4. **Fairness/bias eval:** lightweight but IN v1 — identity slice on a sampled
   subset of the Unintended-Bias dataset (tells the over-flagging story without
   the full-volume cost). Full-depth fairness = later.
5. **Language:** English-only MVP. Datasets are English ⇒ eval (the F1/fairness
   numbers — the differentiator) is English-only. Product models are multilingual
   so they *could* judge other languages, but we don't claim numbers we can't back.
   Chinese = future stretch, and only via a Chinese labeled set (e.g. COLD/ToxiCN),
   NOT an unmeasured bilingual demo.

### Architecture approach (locked): eval-core first
Build order: (1) shared `classify(model, comment, categories=ALL_6) → per-category {severity, reason, span}`
primitive (full contract locked below in "`classify` interface") → (2) eval harness on top of it → produces P/R/F1 + bias tables AND the
routing table (category → best model) → (3) product pipeline (LangGraph) that reuses
`classify` and consumes the routing table → (4) thin FastAPI + Next.js demo. The
harness wraps `classify`; it lives in eval only (e.g. an `eval/` package) and never
runs in production — only its output (the routing table) crosses into product.

---

## `classify` interface — locked 2026-06-01 (design walkthrough §1)

The shared primitive everything sits on (eval harness AND product pipeline both call
it). Signature:

    classify(model, comment, categories=ALL_6) → { per-category: {severity, reason, span} }

**Five locked decisions:**

1. **Return contract = graded ordinal per category.** Each category gets a severity
   ordinal — none/low/medium/high (→ 0/1/2/3). For scoring, threshold it to a binary
   (0/1) and compare to Jigsaw's 0/1 gold labels. The ordinal lets the eval sweep
   thresholds → precision/recall curves → tells the asymmetric-cost story (missing a
   real threat ≫ over-censoring a joke) and pick a per-category operating point. The
   SAME ordinal doubles as the product's severity (compute it once). *Rejected:* plain
   binary (no threshold sweep); calibrated 0–1 float (LLMs aren't well-calibrated →
   defends worse than a clean ordinal).

2. **Call shape = category-subset param.** `categories` defaults to all 6.
   - Eval: pass all 6 → 1 cheap call/comment/model (the ~12–15k-call budget holds).
   - Product: each specialist agent calls the SAME function scoped to its one category,
     on that category's routed model (~6 calls/comment — fine at demo volume).
   One primitive, both layers; eval stays cheap, product honors per-category routing.

3. **Boundary = pure judgment only.** classify returns per-category
   {severity, reason, span}. It does NOT decide overall severity or the
   remove/human-review/allow action — those are policy roll-ups the **aggregator**
   (product-only) computes from the per-category verdicts. Keeps the cross-model eval
   measuring *detection* only (clean F1); the action rule stays in our own auditable,
   tunable code, not baked into the model call. span = verbatim offending substring
   (nullable); frontend highlights by string-match.

4. **Structured output = each provider's native structured-output feature + one shared
   Pydantic schema.** Schema defined once (Pydantic) = single source of truth, validates
   every response regardless of provider. Plumbing differs per provider (OpenAI
   `json_schema` / Gemini `response_schema` / Anthropic structured-outputs or forced
   tool-use); the prompt body stays identical across all three so the comparison is fair
   (each model in its native best-practice structured mode). Retry once on a validation
   failure. *Rejected:* prompt-and-parse (more fragile → wasted eval samples nick the
   headline F1).

5. **Model abstraction = registry + adapter.** A registry maps a model-id string
   (e.g. `"gpt-4o-mini"`, `"deepseek-chat"`) → {adapter, base_url, api_key env, real
   model name}. Each adapter implements one method, ~`complete(prompt, schema) → dict`.
   Many domestic models are OpenAI-compatible (DeepSeek, Qwen/DashScope, Kimi, GLM…),
   so ONE OpenAI-compatible adapter is reused for them — adding DeepSeek = one registry
   line, no new adapter. Gemini + Anthropic get their own adapters. Adding a model = one
   registry line; switching = swap a string; "run all contestants" = loop the id list.

### Eval contestants + tier + cost (locked 2026-06-01)
- **Roster:** GPT + Claude + Gemini + **DeepSeek** (4). Qwen optional — one registry
  line anytime; not in MVP.
- **Tier:** each provider's cheapest small-chat tier, **same class** across all
  (gpt-4o-mini / claude-haiku / gemini-flash / deepseek-chat). ⚠️ Contestants MUST be
  same-tier — a "pro"/reasoning model vs everyone else's mini = an unfair, non-credible
  comparison (a tier artifact, not a real finding). Exact ids are swappable config (each
  provider's API calling convention is stable, so the id is just a string).
- **Why domestic models are ~free to add:** OpenAI-compatible → adapter reuse; cheap +
  RMB-payable + China-accessible. ⚠️ FRAMING: Jigsaw is English, so these are
  **English-moderation** numbers, NOT Chinese-moderation. Chinese needs a Chinese
  labeled set (COLD / ToxiCN) — future, per the locked English-only MVP.
- **Cost reality:** ~$10–15 per full eval run (cheap tiers + sampled split); ~$30–80
  across the whole project with dev re-runs. Mitigations: dev against one provider /
  mock the rest first; Gemini free tier; an aggregator (e.g. OpenRouter) = one balance +
  one OpenAI-compatible endpoint to reach all of them without funding each separately.
- **Optional design note:** bulk `classify` uses the cheap tier; the product's
  context/sarcasm agent MAY optionally use a stronger/reasoning model (reasoning is too
  slow/expensive for bulk, but worth it on the hard gray cases). The cross-model EVAL
  itself stays same-tier.

---

## Eval harness — locked 2026-06-01 (design walkthrough §2)

Sits on top of `classify`. Job: run the contestants over the frozen Jigsaw sample →
per-category P/R/F1 + fairness slice + the routing table. Lives in eval only; never
runs in production (only `routing_table.json` crosses into the product).

**Five locked decisions:**

1. **Collect ≠ score, with a cache (two-phase).**
   - *Collect:* freeze the stratified sample to a file (every model sees identical
     comments → fair + reproducible). For each contestant, run `classify` over the
     sample and write the raw per-comment / per-category outputs to a cache (JSONL).
     Already-cached items are skipped → resumable; a mid-run crash doesn't re-spend.
   - *Score:* read the cache, compute everything. NO API calls.
   - Cache key = model id + **prompt version + schema version** → change the prompt or
     schema and stale entries auto-invalidate & re-run (the one gotcha A must handle).
   - Payoff: API money is spent ONCE; re-scoring (new metric, threshold, bug fix, nicer
     table) is free + instant. *Rejected:* one-pass (re-spends every time you touch
     scoring; loses progress on crash; no auditable raw record).
   - **Dev workflow this enables:** prove the whole pipeline on DeepSeek + a tiny sample
     (or a mock adapter, $0) → 4-model smoke test ~10 comments each (catch provider-
     specific parse fails cheaply) → one full run. Adding the 3 expensive models later
     only pays for their calls (DeepSeek's cached predictions stay). Keep the prompt
     provider-neutral so it isn't overfit to DeepSeek.

2. **Threshold = sweep, not fixed.** The ordinal has 4 levels → only 3 cutoffs
   (≥low / ≥med / ≥high). "Sweep" = try those 3 per category (offline on cached data →
   free). Pick a per-category operating point reflecting asymmetric cost (loosen for
   high-cost-to-miss categories). Still report ONE headline F1 per category at the
   chosen point, so the table stays clean; the sweep also yields a small precision /
   recall-tradeoff chart. This is the whole reason decision #1 (ordinal) was made.

3. **Fairness = per-group false-positive rate + the gap (Route A).** On benign comments
   (gold = not toxic) from the Unintended-Bias subset, split by mentioned identity
   group, compute each group's over-flag (false-positive) rate, then compare across
   groups. Headline = "which groups get over-flagged, by how much, per model" — tells
   the "I am a gay man" over-flagging story; it's just counting → trivial to compute and
   explain. *Rejected for MVP:* the full Jigsaw bias-AUC (Subgroup / BPSN / BNSP
   generalized mean) — more rigorous but heavy and not legible; a later stretch.

4. **Routing rule = F1 baseline + 2 documented overrides.** Per category, default to the
   highest-F1 model; for high-risk categories (threat, identity_hate) prefer higher
   recall among the top models (missing these is the costly error); break near-ties by
   fairness (lower over-flag gap). Offline. This is what makes the asymmetric-cost +
   fairness work actually FEED the routing, not just decorate the report. *Rejected:*
   pure-F1 (leaves those analyses unused).

5. **Storage.** `routing_table.json` committed to the repo = the ONLY artifact crossing
   eval → product; the product reads it at startup (small, versioned, git-diffable).
   Full metrics → per-run result files (JSON/CSV) under `eval/results/<date>/`; the
   report reads those. **Postgres = product runtime only** (user-submitted comments +
   the verdicts the product returns); the eval itself is file-based, no DB dependency.
   *Refinement vs the earlier stack note* (which lumped eval-run results into Postgres):
   eval is file-first; pushing metrics into Postgres is deferred until a queryable
   dashboard actually needs it (YAGNI).

---

## End-to-end flow (whole system) + product pipeline — PROPOSED 2026-06-01

⚠️ Below = the locked layers 1–2 stitched together + the **PROPOSED** layer-3 design
(product pipeline). The 3 product-pipeline choices are awaiting the author's approval
(author was tired — to review when fresh) before they're locked and the spec is written.

### The complete flow

    ═══ PHASE 1 — BUILD TIME (offline) → produces the routing table ═══
     Jigsaw datasets
       │ ① prep: frozen stratified sample (≥150–200 pos/category) + fairness subset
       ▼
     [frozen sample file]
       │ ② collect: 4 models (GPT/Claude/Gemini/DeepSeek, cheap tier) each run
       │    classify(model, comment, ALL_6) → per-comment/per-category ordinals
       ▼
     [raw cache .jsonl]   ← paid ONCE; re-scoring never re-calls APIs
       │ ③ score: threshold sweep (3 cutoffs) → per-cat P/R/F1; fairness FPR-gap; pick op points
       ▼
     [metrics report]  + ④ route: F1 baseline + recall/fairness overrides
       ▼
     ★ routing_table.json  (category → model + threshold)   ← committed to repo
            │  (the ONLY thing crossing eval → product)
            ▼
    ═══ PHASE 2 — RUN TIME (product, per request) ═══
     user pastes a comment → Next.js → POST → FastAPI
       ▼
     LangGraph pipeline:
       ├─ (a) 6 specialist agents in parallel: each classify(routed_model, comment, [cat])
       │        → per-category {severity, reason, span}
       ├─ (b) context/sarcasm agent: gray cases (jokes, quoted/reclaimed slurs) → refine
       └─ (c) aggregator: all verdicts → overall severity + action (remove/review/allow)
       ▼
     FastAPI stores input+verdict in Postgres → returns verdict
       ▼
     UI: per-category labels + severity + highlighted spans + reasons + suggested action

### Product pipeline (layer 3) — 3 PROPOSED choices (awaiting approval)

1. **Context/sarcasm agent cadence → PROPOSED: run on every comment** (demo volume is
   tiny → the extra call is free; simple + predictable). Upgrade later: run only on gray
   cases (≥1 non-"none" verdict, or emoji/quotes/negation present) via a LangGraph
   conditional edge — a nice optimization + interview story, not needed for MVP.
2. **Aggregator policy (per-category severity → overall severity + action) → PROPOSED
   simple rule table:** any category `high` → **remove**; any `medium` → **human-review**;
   all `none/low` → **allow**. Overall severity = max across categories (threat /
   identity_hate may be weighted heavier). Thresholds tunable; lives in our own auditable
   code (this is the policy deliberately kept OUT of `classify`).
3. **Specialist agents → PROPOSED: 6 real parallel nodes**, one per category, each =
   `classify(routed_model_for_cat, comment, [that category])` with the model read from
   `routing_table.json`. Clean multi-agent DAG, best to explain. Micro-opt (later): if
   several categories route to the same model, batch them into one call; keep 6 separate
   nodes for the MVP demo.

When approved → quick demo-layer sketch (FastAPI + Next.js, thin/standard) → write the
formal spec to `docs/superpowers/specs/2026-06-01-arbiter-design.md`.

---

## Precedent memory + human-in-the-loop — design record (built 2026-06-10)

Spec: `docs/superpowers/specs/2026-06-09-precedent-hitl-design.md`. The adjudicator
gained a second tool (`search_precedents` over past human rulings), a calibrated
`confidence` field in `submit_decision`, and a confidence gate that `interrupt()`s
the checkpointed graph into a human review queue; resolving a case writes the human
decision back as a precedent. Decisions worth remembering:

1. **Precedents are human-only** (`source="human"`, enforced at the two write
   sites: review resolution + the seed script). AI rulings never enter the store —
   otherwise the agent would retrieve its own past guesses as "case law" and
   self-reinforce. The contamination guard is the whole point of the design.

2. **Similarity = OpenAI embeddings + cosine in pure Python**, all rows scanned per
   query. The store is seeded with 12 rulings and grows by one per human decision —
   hundreds of rows at most. A vector DB here would be resume-driven engineering;
   the honest version is 10 lines of math. (Also keeps Arbiter differentiated from
   DocSense's RAG — deliberate.)

3. **Confidence gating, and what live calibration taught us.** The gate is
   `confidence < CONFIDENCE_THRESHOLD → human` (strict less-than; at-threshold
   finalizes). Three live findings (n=8 probe, 2026-06-10), each a small lesson in
   LLM-agent ops:
   - **Self-reports cluster high.** DeepSeek reported 0.8–0.95 even on genuine gray
     cases; the spec's threshold of 0.7 would never have queued anything. Raised to
     0.95 — which the data shows is *discriminating*, not flooding: the one
     policy-clear case (quoted abuse, explicitly exempt) came back at exactly 0.95
     and auto-finalized; the genuinely contested ones (0.8–0.9) queued.
   - **Don't tell the model the cutoff.** The tool schema originally said "below
     0.7 a human will review it" — an anchor that invites reporting a safe score
     just above the line. The hint was removed; the field now asks for honest,
     calibrated confidence with no number.
   - **The step cap interacts with the gate.** At `MAX_TOOL_STEPS = 4` (sized for
     the single-tool era), 3 of 8 probes burned every step on policy/precedent
     queries and degraded into the queue with *no* recommendation. Raised to 6 (≈3
     policy lookups + 2 precedent searches + the submit turn) so queued cases carry
     a real AI recommendation for the reviewer.
   - Production note: self-reported confidence is a demo-grade signal; the real
     version is logprob- or sampling-agreement-based calibration. Recorded here so
     the interview answer is "I measured, found the overconfidence pattern, and
     know what the production fix is."

4. **Degrade path subtlety: `adjudication.get("confidence", 1.0)`.** When the
   adjudicator API fails twice (or hits the step cap without submitting), the kept
   rule-based verdict carries **no confidence key**. Defaulting the missing key to
   1.0 means only the *action* decides for degraded rulings: a degraded
   human-review still queues (correct — the agent couldn't help, a human should
   look), while a degraded allow/remove finalizes as it did pre-HITL. Defaulting to
   0.0 instead would have silently routed every API hiccup into the human queue.

5. **HITL is opt-in by construction.** `interrupt()` requires a checkpointer, so
   `build_graph(..., checkpointer=None)` (the default, and what every pre-HITL test
   builds) routes the gate's "human" exit to END — pre-existing behavior, zero test
   churn. Same pattern as "escalation only wires when adjudicate_fn is injected".
   The app passes `SqliteSaver` (`checkpoints.db`), so paused cases survive server
   restarts; `POST /api/review/{case_id}` resumes the thread by `thread_id` with
   `Command(resume=...)`.
