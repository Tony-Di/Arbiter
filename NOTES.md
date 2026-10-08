# Arbiter — Project Notes & Decision Record

> Portable context/handoff doc (NOT the final spec). Captures what was decided
> during the 2026-06-01 brainstorm so a fresh session — opened in *this* repo —
> has the full picture. The original discussion happened in a DocSense session;
> Claude memory does not auto-carry across repos, so this file is the anchor.

**Status (2026-06-10):** built. Classify primitive + eval harness (real 2-model
run → `routing_table.json`), LangGraph pipeline with the tool-using adjudicator
(escalation, 2026-06-08), **precedent memory + human-in-the-loop review**
(2026-06-10, live-verified — see the design record at the bottom), FastAPI + React
with the review docket. Validation at that date: 157 zero-network tests green. Latest
validation (2026-09-22): 241 offline tests; see the final entries. Sections below are in
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

---

## Eval metrics + the clean 600/600 run — design record (built 2026-06-15)

The first committed routing table came from an *unclean* run: DeepSeek timed out on
122/600 from the US, so it wasn't an identical-comments comparison and no F1 was
citeable. Now fixed, and the numbers are a committed artifact. This record is the
"what the numbers mean + how they feed the design" cheat-sheet so it's interview-ready
cold — and so the résumé framing doesn't overclaim.

### The clean run
- **Root cause of the timeouts.** `deepseek-chat` routes through SiliconFlow
  (`api.siliconflow.cn`, China-hosted); DeepSeek-V4-Pro in thinking mode exceeds the
  default 30s HTTP timeout from the US (I'm US-based — slowness to a service ⇒ it's
  China-hosted, not a proxy problem). The adapter already exposes `ARBITER_LLM_TIMEOUT`
  (env, default 30) for exactly this — bumped to 120 and re-ran. `collect()` is
  resumable (`load_done_ids`), so only the 37 missing DeepSeek predictions re-fetched;
  GPT (600/600, US endpoint) cost $0. Both now 600/600.
- **Why it's clean, not mixed.** All 600 DeepSeek predictions come from the *same*
  SiliconFlow config at `temperature=0`; a larger timeout only means "waited long
  enough to receive the answer," it doesn't change the model's output. No
  mixed-endpoint contamination — so the head-to-head is honest.
- **Artifact.** `report.dump_run` (`eval/report.py`) writes
  `eval/results/<date>/metrics.json` + a flat `metrics.csv` (README-pasteable). It
  records `n_scored` per model and an `identical_comments` flag (True iff every
  contestant was scored on the same count) — so "identical comments" is *auditable,
  not asserted*. `eval/results/` is committed (not gitignored); `eval_cache/` stays
  ignored. Re-running `run_eval` is $0/instant (all cached → re-score only).

### What the numbers mean (glossary, grounded in this run)
Per category, each model's verdict is compared to the Jigsaw gold label → tp/fp/fn:
- **tp** = flagged harmful, really is (correct catch); **fp** = flagged, actually fine
  (over-flag / false alarm); **fn** = passed, actually harmful (miss).
- **precision = tp/(tp+fp)** — "of what it flagged, how much was real" (low ⇒ it
  over-censors). **recall = tp/(tp+fn)** — "of the real harm, how much it caught"
  (low ⇒ it lets harm through). **F1 = 2·tp/(2·tp+fp+fn)** — harmonic mean; only high
  when *both* are decent, so one lopsided number tanks it.
- **cutoff / threshold** — `classify` returns an ordinal severity (0/1/2/3 =
  none/low/med/high); binarizing at cutoff=1 (≥low) is aggressive (recall↑, precision↓),
  cutoff=2 (≥med) is stricter (precision↑, recall↓). `score.py` sweeps 1/2/3 and picks
  the operating point; `routing_table`'s `threshold` is the chosen cut (e.g. GPT/insult
  landed on cutoff=2).

### The findings (the actual story to tell)
- **GPT vs DeepSeek run neck-and-neck:** avg F1 ≈ **0.807 (GPT) vs 0.793 (DeepSeek)** —
  a ~0.015 gap. At full precision GPT edges 5/6 categories, **but four of those by
  <0.01 F1** (toxic +0.004, threat +0.008, insult +0.005, obscene −0.008 → DeepSeek
  wins it) — i.e. noise at n=600. The only *meaningful* per-category gaps are
  **identity_hate (+0.042)** and **severe_toxic (+0.033)**, both to GPT. Takeaway: no
  model dominates ⇒ **per-category routing is empirically justified** (the whole point
  of the eval layer); a cheap open model matching GPT on English moderation is itself
  the finding. (Don't call toxic/threat/insult "wins" — they're ties within noise.)
- **severe_toxic is systematically over-flagged by both:** recall ~0.88–0.94 but
  precision only ~0.36–0.38 (GPT fp=273 vs tp=167) → its F1 ≈ 0.5 is a *precision*
  problem, not a recall one. Lesson: a rare, fuzzy category needs a precision-oriented
  operating point / higher threshold before it's shippable.
- **High-risk categories route by recall, not F1:** for `threat` + `identity_hate`,
  missing harm (fn) is the costly error, so `build_routing_table` prefers the
  higher-recall model there. This is what makes the asymmetric-cost framing actually
  *feed* routing instead of decorating the report.

### Résumé framing (do NOT overclaim)
- ❌ "GPT beat DeepSeek by X%" — the gap is ~1.5% avg with most categories tied within
  noise; it reads as spin the moment an interviewer sees the table.
- ✅ "Benchmarked GPT vs DeepSeek on an identical 600-comment Jigsaw sample across 6
  categories; within ~0.015 avg F1, no model won every category, so the system routes
  each to its measured-best model." The defensible claims are the **per-category
  routing justification** and the **severe_toxic over-flagging diagnosis** (high recall
  / low precision) — both show you actually read the numbers.

---

## Latency: parallel fan-out vs sequential — measured 2026-06-15

`scripts/bench_latency.py`. Substantiates the "parallel specialist fan-out" claim
with a real number instead of a structural hand-wave.

- **Result (n=20, gpt-5.4-mini):** median per-comment latency **9.3s sequential →
  2.2s parallel ≈ 4.3× faster** for the 6 specialist `classify()` calls.
- **Method (so it survives an interview).** Same model + US endpoint for both arms
  (concurrency is the only variable); one warm-up comment discarded (cold TLS/DNS);
  seq/par *interleaved* per comment so network drift hits both equally; report the
  **median** — the sequential arm is long-tailed (one comment hit 28s), so the mean
  would lie. The parallel arm uses a `ThreadPoolExecutor(6)`, which mirrors what
  LangGraph does in `graph.py` (it runs the 6 sync specialist nodes on a thread pool,
  so the blocking HTTP calls overlap) — a faithful proxy for the real graph.
- **Why 4.3×, not 6×.** The parallel arm is bounded by the *slowest of the 6
  concurrent* calls (the categories aren't equal-latency), plus thread-pool +
  provider-side concurrency overhead. The honest claim is "~4.3× on this run," not
  "6× because there are 6 calls."
- **Scope honesty.** This times the specialist fan-out only (the dominant cost: 6 LLM
  calls), not full end-to-end request latency (aggregator/context/FastAPI overhead is
  small but not measured here). The bench prints; it isn't a committed artifact (the
  reproducible script is — re-run anytime).

## Controlled system ablation — measured 2026-09-21

The September experiment fixes an evaluation bug: without a checkpointer,
low-confidence allow/remove recommendations used to be scored as automatic
decisions instead of human-review. Cache v2, a regression against the real
checkpointed graph, and an explicit input boundary (ID/text only, no gold labels)
now keep the benchmark aligned with the product.

Frozen data: 20 development, 110 held-out, and 30 separate stress cases. Existing
labels were preserved, but human authorship has not been confirmed. The primary
holdout contains only two remove labels, and the stress set only one.

The controlled GPT run compares a single joint classification call, six separate
classifiers, adding context, and adding policy adjudication. All 640 predictions
completed. Held-out macro-F1: 0.498 / 0.637 / 0.544 / 0.505. Stress macro-F1:
0.505 / 0.414 / 0.410 / 0.349. Thus neither specialist superiority across slices
nor adjudicator quality gains are established. Keep this negative evidence.

Replaying the deterministic transitions on the same saved intermediate outputs
avoids attributing upstream model variation to the later stage: on holdout,
context corrected 3 and regressed 6 reference decisions; adjudication plus the
confidence gate corrected 0 and regressed 4. Of 43 adjudicated holdout cases,
35 substantive model recommendations were still sent to human review.

The mixed-provider development diagnostic completed 59/60 predictions. It is
separate from the controlled experiment and includes one adapter failure; its
latencies are not comparable to the old six-classifier-only microbenchmark.
The local precedent store was empty, so the human-precedent comparison was not
fabricated using unreviewed draft seeds.

Artifacts: `eval/experiments/system-ablation-v1/` (frozen cases and protocols),
`eval/results/system-ablation-controlled-v1/` (reports, case predictions and
mechanism audit), `eval/results/system-ablation-v1/` (mixed-provider diagnostic).
No production routing, prompts, confidence thresholds or step caps were changed.

## Local policy and review reliability — 2026-09-22

Implemented shared policy 2026-09-22.2, category-specific criteria, grounded
context mitigation and validated adjudicator submissions. Ordinary medium abuse
now queues directly for a human; unresolved harmful context takes the tool loop.
Confidence remains a heuristic at 0.95 and the tool-step budget remains 6.

Human review now persists its decision before resuming the checkpoint, then commits
verdict + completion + embedding outbox together. Retries reuse completed graph
state after an interrupted SQL save. A lease/fencing token protects concurrent
resolvers; identical requests return the saved result and conflicting choices fail.
Embedding retries are independent and unique by review case. Additive local
migrations preserve existing data. Startup/shutdown and the background worker are
tested with file SQLite; no hosted deployment was performed.

Validation: 193 offline tests pass; TypeScript/Vite build passes. Two 12-case live
GPT mechanism probes each met 11/12 AI-authored case expectations. Category
criteria corrected cross-category contamination on the failed threat example,
but the context model still over-removed it. No case triggered live adjudication;
this probe does not establish adjudicator gains or independent accuracy. Preserve
both runs in eval/results/policy-v2-probe{,-followup}/. Full report and limitations:
eval/results/policy-v2-probe-followup/REPORT.md.

Existing benchmark labels remain unconfirmed by a human. Seed drafts were not
inserted; the seed script now requires human-review confirmation and rejects
incompatible action/severity pairs before writes. Historical v1 results and the
existing routing table are preserved; they do not describe the revised prompts.

## Real adjudication and human evaluation preparation — 2026-09-22

The old 160 reference labels are confirmed to be model-generated or not
individually human-reviewed. No AI annotations were promoted to human gold. Blind packets contain only input text, IDs and policy/provenance metadata;
the review UI embeds the same complete policy and category rules used in prompts.
Exports require a reviewer, rationale and explicit human attestation. Import checks
packet integrity, text hashes, policy, coverage and action/severity consistency.

Historical cache-only analysis found 57 cross-variant action disagreements and
83 cases where at least one variant differs from the unreviewed reference. A first
20-case blind packet is prioritized for review. Threshold sweeps preserve 0.95:
unreviewed labels cannot justify calibration, and a post-call gate saves no LLM time.

Eight newly authored diagnostic inputs reused identical GPT upstream outputs before
and after adjudication. Five naturally triggered the tool loop; all submitted valid
decisions, all remained human-review, and incremental latency P50/P95 was 2.53/2.91s.
Six constructed component states yielded 6/6 valid GPT submissions and 1/6 valid
DeepSeek submissions; the other five fell back after provider call failures under
the probe's 20-second per-call timeout. These are execution observations, not quality
gains. Raw tool transcripts, manifests and the Chinese report are preserved in
eval/results/adjudicator-v2-probe/. No precedents were loaded or created.

Sixty new Civil Comments candidates were frozen into 20 calibration and 40 holdout
items at the existing pinned source revision, excluding old cases and applying
normalized-text/trigram deduplication. Source scores determine sampling strata,
not moderation answers. Human labels and model predictions are both still pending.
Use docs/human-evaluation.zh-CN.md; freeze choices before evaluating the fresh holdout.

Validation: 230 offline tests pass, including synthetic CLI integration tests for
annotation imports, corrections/regressions, and mismatched prediction rejection.
The blind review UI was opened and checked locally without submitting human labels.
No production threshold, model routing or deployment changes in this follow-up.

## AI preannotation for the first 20 — 2026-09-22

AI preannotations were completed for the current 20-case packet only: 5 allow,
14 human-review, 1 remove, with 5 explicit uncertainty flags. Each includes a
Chinese rationale and an exact source span. These are AI-generated suggestions,
not human gold or independent labels. No new provider inference, production
writes, or fresh holdout annotation.

The separate first-20/ai-assisted/ page prefills editable suggestions while keeping
human confirmation at zero. Its packet ID and local storage differ from the blind
packet. Human-confirmed imports retain ai_assisted provenance and the draft hash,
even if export-level method fields are omitted. AI drafts cannot enter the human
import path. Tests cover those distinctions, mismatched evidence, and preservation
of original packets; 241 offline tests passed. The page was checked without making
any human confirmations or attestations.

## Review completion feedback fix — 2026-09-22

The last review row used to clamp navigation to the final index and immediately
clear save feedback, even when earlier rows remained unconfirmed. Confirmation now
advances to the next pending row with wraparound, reports what was saved, and
exposes remaining count/navigation. A completed batch shows an explicit export
prompt, without auto-attestation or download. Reload resumes the first pending row;
existing packet IDs and saved labels are preserved. Verified on the live review page
after refresh without submitting a new label. Five synthetic UI-handler regression
tests and 36 related Python tests passed.

## First-20 assisted review imported and rescored — 2026-09-22

The reviewer confirmed all 20 AI-assisted labels: 19 unchanged, 1 changed (the
Chinese-eatery odor-complaint case, allow -> human-review/1/identity_hate; no
context, intent unclear). The first export kept the AI's "allow" rationale on that
row; it is preserved as reviewed-export.initial.json and unused. The final export
records the rewrite under `revisions`; imported labels are in
eval/experiments/human-review-v2/first20-human-assisted.jsonl (ai_assisted
provenance and draft hash retained). The review page now blocks confirming an
edited label whose rationale still equals the AI draft; the offline rescoring
script rejects the same inconsistency. All six review pages were re-rendered from
the current template; frozen packets are byte-identical.

scripts/score_reviewed_system.py rescored the saved controlled-v1 predictions
(gpt-5.4-mini, no model calls) against these labels: action agreement single_call
13/20, specialists_only 8/20, specialist_panel 8/20, policy_agent 6/20; unsafe
auto-allows 2/16, 8/16, 7/16, 8/16. Old reference actions matched only 9/20.
Scope: disagreement-prioritized cases, AI-assisted rather than blind, predictions
made before policy 2026-09-22.2 — a diagnostic of the old system's gap to the new
labels, not an accuracy claim for the current code. Report:
eval/results/human-review-v2-first20/. 248 Python and 7 UI tests pass.

Current code was then rerun on the same 20 labels (80 real gpt-5.4-mini variant
runs, 0 failures, cache eval_cache/first20-current-v1.jsonl). Action agreement:
single_call 14/20, specialists_only 13/20, specialist_panel 13/20, policy_agent
11/20 (old 13/8/8/6); unsafe auto-allows 4/3/6/7 of 16. Replaying on identical
upstream outputs: context changed 2 (1 corrected, 1 regressed); adjudication plus
gate changed 0 (2 escalations, both submitted human-review), so panel vs agent is
run-to-run variance. The only remove case (quoted "debased mind" about gay people)
was removed by no arm; identity_hate scored it 1, which policy auto-allows. These
20 cases are now seen; any prompt/policy change based on them must be validated on
the fresh calibration/holdout. Report:
eval/results/human-review-v2-first20/CURRENT-CODE.zh-CN.md.
