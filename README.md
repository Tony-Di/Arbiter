<div align="center">

# Arbiter

**Multi-agent content moderation that escalates its hard cases to a tool-using AI adjudicator — and picks the model per harm category by evaluation.**

*It judges content. You judge the judges.*

[**Live Demo**](#) · [Architecture](#architecture) · [Quick Start](#run-it-locally) · [Design Notes](./NOTES.md)

![LangGraph](https://img.shields.io/badge/LangGraph-agents-1C3C3C?style=for-the-badge)
![Python](https://img.shields.io/badge/Python-3.14-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-19-61DAFB?style=for-the-badge&logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=for-the-badge&logo=typescript&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)
![tests](https://img.shields.io/badge/tests-91%20passing-brightgreen?style=for-the-badge)

</div>

Paste a comment and Arbiter tells you whether it's harmful, in which ways, how
severe, and what to do about it (remove / human-review / allow) — with the
reasoning and the offending span highlighted. Easy cases are decided by a fast
parallel panel; genuinely ambiguous cases are escalated to an **adjudicator
agent** that consults written policy via a tool call before ruling.

---

## Why it's interesting

Most "toxicity classifier" projects are a single model call. Arbiter is built as a
real **agentic system** with a measurement layer underneath it:

- **Dynamic control flow, not a static pipeline.** The graph decides its own path
  per comment — clear cases finish fast; gray cases trigger a deeper, tool-using
  agent loop.
- **A tool-using adjudicator agent.** On hard cases it calls a `get_policy(category)`
  tool in a ReAct loop (a real cycle in the LangGraph graph), then commits a final
  ruling — and can override the rule-based verdict.
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
                                          (auto-decide)            (tentative human-review
                                              │                       or ambiguity flag)
                                              │                              ▼
                                              │                   ┌─►  adjudicator agent
                                              │                   │     (LLM + tools)
                                              │            get_policy?  │
                                              │              ┌──────────┴─────────┐
                                              │            tool                 done
                                              │              ▼                    │
                                              │         policy_tool ──────────────┘   ◄─ the cycle
                                              ▼                                    │
                                            final verdict ◄────────── submit_decision
```

- **Specialists + context** fan out in parallel from `START` (LangGraph runs the
  synchronous nodes on a thread pool; the blocking HTTP calls overlap).
- **Aggregator** turns per-category severities + context flags into an overall
  severity and an action using auditable rules in code — deliberately *not* an LLM,
  so the policy never silently drifts.
- **Escalation** only fires for cases the rules can't confidently auto-decide. The
  adjudicator may call `get_policy` several times (bounded by a step cap), then ends
  by calling `submit_decision`; on model failure or the cap it safely degrades to the
  rule-based verdict.
- **Injection-hardened:** the untrusted comment is always wrapped in
  `<comment></comment>` and treated as data, never instructions.

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
| Persistence | **SQLAlchemy** — SQLite (dev) / **PostgreSQL** (prod) via `DATABASE_URL` |
| Frontend | **Vite · React · TypeScript · Ant Design** (verdict card, span highlighting, escalation trace) |
| Eval | self-built harness (`sample · collect · score · route`) |
| Deploy | Vercel (frontend) + Railway/Render (backend + Postgres) |

## Run it locally

**Backend** (Python 3.14):

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows ;  source .venv/bin/activate on macOS/Linux
pip install -e ".[dev]"

# Keys are loaded from a .env file. The eval-derived routing table uses GPT for
# most categories + DeepSeek; create .env with:
#   DEEPSEEK_API_KEY=...        (required)
#   OPENAI_API_KEY=...          (for the real routing table)
# To run on just a DeepSeek key, point at the all-DeepSeek dev table ($0):
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

**Tests** (91, zero-network — every LLM call is injected, fakes only):

```bash
.venv\Scripts\python -m pytest -q
```

## Status

Core complete: classify primitive, eval harness + a real 2-model run, the LangGraph
product pipeline with the escalation agent, FastAPI backend with persistence, and the
React UI. **91 tests green.** Next: live deployment, then a model-comparison view.

See [`NOTES.md`](./NOTES.md) for the full design record and
[`docs/superpowers/specs/`](./docs/superpowers/specs/) for the specifications.
