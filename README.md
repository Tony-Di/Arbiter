<div align="center">

# Arbiter

**Multi-agent content moderation that escalates its hard cases to a tool-using AI adjudicator — and picks the model per harm category by evaluation.**

*It judges content. You judge the judges.*

[Architecture](#architecture) · [Local Setup](#run-it-locally) · [Local Improvements](./docs/local-improvements.zh-CN.md) · [Design Notes](./NOTES.md)

![LangGraph](https://img.shields.io/badge/LangGraph-agents-1C3C3C?style=for-the-badge)
![Python](https://img.shields.io/badge/Python-3.13+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-18-61DAFB?style=for-the-badge&logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=for-the-badge&logo=typescript&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-local-003B57?style=for-the-badge&logo=sqlite&logoColor=white)

</div>

Paste a comment and Arbiter tells you whether it's harmful, in which ways, how
severe, and what to do about it (remove / human-review / allow) — with the
reasoning and the offending span highlighted. Easy cases are decided by a fast
parallel panel; genuinely ambiguous cases are escalated to an **adjudicator
agent** that consults written policy and **past human rulings** via tool calls
before ruling — and when even the agent isn't confident, the case pauses into a
**human review queue**, and the human's decision is written back as a precedent
the agent can cite next time.

---

## Why it's interesting

Most "toxicity classifier" projects are a single model call. Arbiter is built as a
real **agentic system** with a measurement layer underneath it:

- **Dynamic control flow, not a static pipeline.** The graph decides its own path
  per comment — clear cases finish fast; gray cases trigger a deeper, tool-using
  agent loop.
- **A tool-using adjudicator agent.** On hard cases it calls `get_policy(category)`
  and `search_precedents(query)` tools in a ReAct loop (a real cycle in the LangGraph
  graph), then commits a final ruling — and can override the rule-based verdict.
- **Human-in-the-loop with case-law memory.** The agent reports a self-assessed
  confidence with every ruling; low-confidence cases `interrupt()` the checkpointed
  graph into a review queue, and each human decision is embedded and stored as a
  **precedent** — searchable by the agent on future cases. Humans only see what the
  AI routes for review, and future cases can retrieve those human rulings.
- **Evidence-grounded context and reliable local review.** Quotation and sarcasm
  alone cannot lower severity. Context adjustments require intent and exact text
  evidence. Human verdicts and embedding jobs commit together; an idempotent outbox
  retries indexing independently, and checkpoints recover interrupted review saves.
- **Model routing by evaluation.** Each harm category is judged by whichever model
  scored best on a public benchmark; the routing table is produced by a self-built
  eval harness, not hand-picked.

---

## Architecture

```
 comment
   │
   ├─► 6 specialist agents (one per harm category, parallel) ─┐
   │     each runs on its eval-routed model                   │
   └─► context / sarcasm agent ───────────────────────────────┤
                                                              ▼
                                              aggregator  (deterministic policy
                                                           in code — no LLM)
                                                              │
                                                     should_escalate?
                                              ┌───────────────┴───────────────┐
                                          clear case                      gray case
                                          (auto-decide)            (unresolved harmful
                                              │                          context)
                                              │                              ▼
                                              │                   ┌─►  adjudicator agent
                                              │                   │     (LLM + tools)
                                              │                   │          │
                                              │              ┌────┴──────────┼──────────────┐
                                              │            tool        submit_decision      │
                                              │              ▼               │              │
                                              │         tools node ──────────┤              │
                                              │      (get_policy ·           │              │
                                              │       search_precedents)     ▼              │
                                              │          ▲             confident?           │
                                              │          │           ┌───────┴────────┐     │
                                              │     precedent      yes               no     │
                                              │       store          │                ▼     │
                                              ▼     (case law)       │       human review queue
                                            final verdict ◄──────────┘       (graph interrupt()s,
                                                  ▲                           checkpointed)
                                                  │                                  │
                                                  └──── human rules; decision ◄──────┘
                                                        written back as precedent ──► store
```

- **Specialists + context** fan out in parallel from `START` (LangGraph runs the
  synchronous nodes on a thread pool; the blocking HTTP calls overlap).
- **Aggregator** turns per-category severities + context flags into an overall
  severity and an action using auditable rules in code — deliberately *not* an LLM,
  so the policy never silently drifts.
- **Direct human route:** ordinary severity-2 abuse without context ambiguity goes
  from the aggregator straight to the review queue, without an adjudicator call.
- **Escalation** handles unresolved potentially harmful context. The
  adjudicator may call `get_policy` / `search_precedents` several times (bounded by a
  step cap), then ends by calling `submit_decision`; on model failure or the cap it
  requires human review. A final decision must include a valid action/severity,
  policy category, exact comment evidence and finite confidence.
- **Human-in-the-loop** uses LangGraph's `interrupt()` + a SQLite checkpointer: a
  low-confidence ruling pauses the graph mid-flight, the case lands in a review
  queue (`GET /api/review-queue`), and `POST /api/review/{case_id}` resumes the
  checkpointed graph with the human's decision. The 0.95 gate is an uncalibrated
  heuristic based on a small earlier probe. Identical human submissions are
  idempotent; conflicting decisions are rejected. Verdict, completion and embedding
  job are saved atomically, and a completed checkpoint can recover a failed SQL save.
- **Precedents are human-only.** The case-law store only ever ingests human rulings
  (independently reviewed seeds + review write-backs) — AI verdicts never feed back into it, so the agent
  can't launder its own mistakes into "precedent". Similarity = embeddings + cosine
  in pure Python for a small local store. Indexing retries in the background and
  enforces one precedent per review case. Seed drafts require explicit human review.
- **Untrusted-input framing:** the comment is wrapped in
  `<comment></comment>` (and precedents in `<precedent></precedent>`) and treated
  as data in the prompts. Output validation checks structure and literal evidence;
  these safeguards do not prove semantic correctness or eliminate prompt injection.

## The evaluation layer

A lightweight, self-built harness (no framework) benchmarks the contestant models on
the **Jigsaw Toxic Comment** dataset across the 6 labels —
`toxic · severe_toxic · obscene · threat · insult · identity_hate`:

1. **freeze** a stratified sample (every model sees identical comments),
2. **collect** predictions concurrently into a resumable, versioned cache (paid once),
3. **score** per-category precision / recall / F1 with a threshold sweep,
4. **route** each category to the best model → `routing_table.json`.

The routing table is the **only** artifact that crosses from eval into the product,
so adding or swapping a contestant later is zero-rework. Current contestants:
**DeepSeek** and **GPT** (the registry is OpenAI-compatible, so adding Gemini /
Claude / Qwen is one line — or one OpenRouter key).

> No model training. The LLMs are called via API; the labeled dataset is the
> *answer key* used to score them, never training fuel.

## Stack

| Layer | Tech |
|---|---|
| Agent orchestration | **LangGraph** (parallel specialists + conditional escalation cycle) |
| Backend | **Python · FastAPI** |
| Models | **DeepSeek + GPT** via one OpenAI-compatible adapter + a model registry |
| Persistence | **SQLAlchemy + SQLite** — additive local migrations, checkpoints, leased embedding outbox |
| Frontend | **Vite · React · TypeScript · Ant Design** (verdict card, span highlighting, escalation trace) |
| Eval | self-built harness (`sample · collect · score · route`) |
| Runtime | Local FastAPI + Vite; no hosted deployment |

## Run it locally

**Backend** (Python 3.13+):

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows ;  source .venv/bin/activate on macOS/Linux
pip install -e ".[dev]"

# Keys are loaded from a .env file. The eval-derived routing table uses GPT for
# most categories + DeepSeek; create .env with:
#   DEEPSEEK_API_KEY=...        (required)
#   OPENAI_API_KEY=...          (for the real routing table)
# For DeepSeek-only classifiers, use the all-DeepSeek table (provider calls are billed):
#   ROUTING_TABLE=routing_table.deepseek.json

uvicorn arbiter.api.main:app --reload           # http://localhost:8000
```

**Frontend:**

```bash
cd web
npm install
npm run dev                        # http://localhost:5173
```

The UI calls `POST /api/moderate`, and falls back to a deterministic mock when the
backend is offline — so the demo works even with no keys.

**Tests** (248 Python + 7 UI, zero-network — every LLM call is injected, fakes only):

```bash
.venv\Scripts\python -m pytest -q
node --test tests/eval/review_ui.test.cjs
```

The seven-case UI regression suite checks skipped-case navigation, completion/export
feedback, invalid choices, AI-label edits, storage failures and the text-backup export.

## Status

Core complete: classify primitive, eval harness + a real 2-model run, the LangGraph
product pipeline with the escalation agent + precedent memory + human-in-the-loop
review (live-verified end to end), FastAPI backend with persistence, and the React
UI with the review docket. **248 offline tests pass**, including restart recovery,
concurrent review ownership, embedding retries, migration, policy regressions,
blind annotation imports and paired adjudication scoring.
The frontend TypeScript/Vite build passes. The current shared policy is
`2026-09-22.2`; see the [annotation policy](./docs/moderation-policy.md) and
[local walkthrough](./docs/local-improvements.zh-CN.md).

The preserved **v1** controlled GPT
experiment produced **640 predictions** across four configurations on 20
development, 110 held-out, and 30 separately reported stress cases. Held-out
action macro-F1 was 0.498 (single call), 0.637 (six specialists), 0.544 (adding
context), and 0.505 (adding policy adjudication). The specialist advantage did
not repeat on the stress set; additional agent stages did not show consistent
benefit. These reference labels are model-generated or have not been individually
human-reviewed. Scores against them are diagnostic,
with very few reference removal cases; they do not establish calibrated accuracy.
These historical scores and the existing routing table predate the new shared
policy/prompts. They are not accuracy claims for the revised system. The separate
12-case live mechanism probe uses AI-authored expectations, not human gold.
Both initial and follow-up runs met 11/12 case expectations; an ambiguous threat
was still over-removed. See the [probe report](./eval/results/policy-v2-probe-followup/REPORT.md).

A subsequent 8-case diagnostic exercised the real adjudicator on identical saved
upstream evidence: 5 cases triggered GPT adjudication, all submitted valid decisions,
and all remained human-review (additional latency P50 2.53s / P95 2.91s). Constructed
component probes completed 6/6 valid GPT submissions and 1/6 DeepSeek submissions;
the other five DeepSeek cases fell back to review after provider call failures.
This validates execution, not quality gains. The 0.95 confidence gate remains a heuristic.
See the [adjudicator report](./eval/results/adjudicator-v2-probe/REPORT.zh-CN.md).

Local blind review pages now cover the existing 160 cases, a prioritized first 20,
and 60 new unlabelled candidates split into 20 calibration / 40 holdout cases.
The fresh cases have no model predictions yet. Start with the
[human evaluation workflow](./docs/human-evaluation.zh-CN.md); annotations require
actual human review before quality scoring or threshold selection.

The prioritized 20 cases also have an
[AI-assisted review page](./eval/experiments/human-review-v2/first-20/ai-assisted/review.html)
with suggested labels, exact evidence spans and Chinese rationales. These are
explicitly AI preannotations, not human gold. Assisted review uses a separate
packet/storage namespace and retains its method when human-confirmed exports
are imported; the original blind packets and fresh holdout remain unchanged.

The experiment uses one model for every role, independently of the unchanged
production mixed-model routing. A separate mixed-provider development run
records 59/60 completed predictions and substantial latency. The human-precedent
arm awaits independently reviewed cases: the local precedent table is empty.
See the [experiment report](./eval/results/system-ablation-controlled-v1/REPORT.md),
[Chinese analysis](./eval/results/system-ablation-controlled-v1/ANALYSIS.zh-CN.md),
and [reproduction guide](./docs/system-eval.md).

See [`NOTES.md`](./NOTES.md) for the full design record and
[`docs/superpowers/specs/`](./docs/superpowers/specs/) for the specifications.
