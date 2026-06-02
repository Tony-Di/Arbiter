# Arbiter

**Multi-agent AI content moderation — and the benchmark that decides which model judges best.**

> *It judges content. You judge the judges.*

Arbiter reads a piece of text (a comment, a post, a message) and decides whether
it's harmful, in what ways, how severe, and what to do about it — then backs that
up with an empirical comparison of how well leading LLMs handle the job.

It has two sides:

- **The product** — paste text and get per-category harm labels (hate,
  harassment/threats, sexual, self-harm), a severity score, a suggested action
  (remove / human-review / allow), and the reasoning behind it. A team of
  specialized agents reviews each dimension in parallel, with a dedicated agent for
  the hard, context-dependent cases (sarcasm, quoted/reclaimed slurs).
- **The evaluation** — Arbiter benchmarks **GPT, Claude, and Gemini** on public
  labeled data (the Jigsaw toxicity datasets), measuring not just accuracy but
  **demographic fairness**, then routes each harm category to the model that scores
  best and fairest on it.

## Stack

Python · FastAPI · LangGraph · OpenAI + Anthropic + Gemini · PostgreSQL ·
Next.js + Tailwind · deployed on Vercel + Railway.

No model training — the LLMs are used via API; the labeled datasets are the
"answer key" for the evaluation layer.

## Status

🚧 Early WIP — design phase. See [`NOTES.md`](./NOTES.md) for the full concept,
architecture, evaluation plan, and decision record.
