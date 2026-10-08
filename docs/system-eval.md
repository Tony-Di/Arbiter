# System-level ablation benchmark

This benchmark measures the final moderation action, rather than only the six
category classifiers. It is designed to answer the resume/interview question:
"what does the multi-agent system add over one model call?"

**Label provenance update (2026-09-22):** the user confirmed that the existing
160 reference labels were model-generated or have not been individually
human-reviewed. Historical scores remain diagnostics against those references,
not validated accuracy. Use the [new blind review workflow](./human-evaluation.zh-CN.md)
for human annotation and the frozen 20/40 fresh calibration/holdout candidates.
Do not mark an old reference file `human-confirmed` just by changing this CLI flag.

## 1. Build the candidate set

Install the optional data dependency, then stream a reproducible Civil Comments
sample:

```powershell
python -m pip install -e ".[dev,eval]"
python scripts/build_system_eval.py --safe 30 --gray 70 --harmful 30
```

Outputs (gitignored):

- `data/system_eval/candidates.jsonl`: source scores and provenance.
- `data/system_eval/annotation.csv`: the human-review worksheet.
- `data/system_eval/manifest.json`: immutable dataset revision, seed, quotas, and
  slice thresholds.

The sampler deliberately excludes the score gaps `(0.10, 0.30)` and
`(0.70, 0.90)`. It uses independent seeded reservoirs for safe, gray, and
harmful slices, so the same input revision and seed produce the same sample.

The primary sample may contain too few true removal cases to measure safety
recall reliably. Build a separate, disjoint high-risk stress set without
changing or overwriting the primary sample:

```powershell
python scripts/build_system_eval.py --mode high-risk
```

This writes 30 additional cases to `data/system_eval/high_risk_addendum/`: 12
source-enriched threat cases, 10 identity-attack cases, and 8 severe-toxicity
cases. Assignment uses stable priority `threat -> identity_hate ->
severe_toxic`, excludes all IDs in the primary set, and records the fixed
dataset revision, thresholds, quotas, and exclusion count in its manifest.
Source enrichment is only a sampling strategy; it is not a gold label.

## 2. Complete the human annotations

For every row in `annotation.csv`, fill:

- `gold_action`: `allow`, `human-review`, or `remove`.
- `gold_categories`: zero or more categories separated by semicolons, for
  example `toxic;insult`.
- `gold_severity`: `0` through `3`.
- `rationale`: one short policy-grounded reason.

Use [the shared annotation policy](./moderation-policy.md) and
`src/arbiter/moderation_policy.py` as the labeling guide. The source toxicity
score selects candidates; it is not the Arbiter gold label. Quotation, reporting,
reclaimed language, hyperbole, and missing context therefore require a human
decision.

Validate the completed sheet without making any model call:

```powershell
python scripts/run_system_eval.py --cases data/system_eval/annotation.csv --validate-only
python scripts/run_system_eval.py `
  --cases data/system_eval/high_risk_addendum/annotation.csv `
  --validate-only
```

## 3. Run the ablation

The real routing table requires both `OPENAI_API_KEY` and `DEEPSEEK_API_KEY` in
`.env`. Run the first three variants before precedent review is ready:

```powershell
python scripts/run_system_eval.py `
  --cases data/system_eval/annotation.csv `
  --variants single_call specialist_panel policy_agent
```

The variants are:

1. `single_call`: one model judges all six categories in one call; no context
   modifier or adjudicator.
2. `specialist_panel`: six routed specialists plus the context node and
   deterministic aggregator.
3. `policy_agent`: the panel plus a ReAct adjudicator that can call policy, but
   cannot see the precedent tool or precedent prompt.
4. `full_system`: the policy agent plus a fixed, human-only precedent store.

For `full_system`, use a non-empty precedent database containing only separately
reviewed seed cases. Never seed it from benchmark test cases. The runner refuses
an empty database or a non-human row.

```powershell
python scripts/run_system_eval.py `
  --cases data/system_eval/annotation.csv `
  --variants single_call specialist_panel policy_agent full_system `
  --precedent-db-url sqlite:///./arbiter.db
```

Predictions append to `eval_cache/system_eval.jsonl`. A cache hit requires the
same case text, variant, cache version, and configuration fingerprint. The
fingerprint covers prompt/schema material, provider model IDs, routing content,
policy/tool settings, confidence/step limits, embedding model, and precedent
corpus. Failed calls are not cached and are retried on the next run.

## 4. Interpret the report

Reports are written to `eval/results/system_eval/` as JSON and CSV. Primary
metrics:

- `action_macro_f1`: balanced three-action performance.
- `unsafe_auto_allow_rate`: gold review/remove cases automatically allowed.
- `over_remove_rate`: gold allow/review cases automatically removed.
- `human_review_rate`: predicted reviewer workload.
- `auto_decision_accuracy`: correctness among automatic allow/remove decisions.
- `high_risk_recall`: high-risk cases caught by review or removal.
- `p50_latency_ms`, `p95_latency_ms`: wall-clock latency.
- `coverage`: completed predictions / benchmark cases.

Do not report dollar cost yet: the current provider adapter does not preserve
token usage. Report latency, completed calls, failures, and cache reuse instead.

Keep the headline action metrics on the 130-case primary benchmark. Report the
30-case addendum separately as a targeted safety stress test, especially for
unsafe-auto-allow rate and high-risk recall; combining the enriched cases into
the primary score would distort the natural action distribution.

When writing the resume bullet, compare measured variants and use only numbers
from the generated report. Treat this as a configuration ablation: the single
call and specialist panel differ in call count, routing, and context, so their
difference cannot be attributed to one component alone.

## 5. Frozen controlled experiment (September 2026)

`scripts/prepare_system_experiment.py` preserves the existing labels and freezes
20 development cases, 110 held-out cases, and the separate 30-case stress set in
`eval/experiments/system-ablation-v1/`. The initial source hashes, IDs and action
counts are recorded. Existing labels are **reference labels confirmed not to have
been individually human-reviewed**, not newly verified human annotations.

The mixed-provider development diagnostic is separate from the controlled run.
For the controlled run every role uses GPT, with the original policy, confidence
threshold and step cap unchanged. The extra `specialists_only` arm makes it
possible to distinguish splitting classification from adding context. This does
not change the production routing table or the default DeepSeek roles.

```powershell
.venv/Scripts/python.exe scripts/run_system_eval.py `
  --cases eval/experiments/system-ablation-v1/holdout.jsonl `
  --routing-table eval/experiments/system-ablation-v1/routing.gpt.json `
  --single-model gpt-5.4-mini --context-model gpt-5.4-mini `
  --adjudicator-model gpt-5.4-mini `
  --variants single_call specialists_only specialist_panel policy_agent `
  --workers 4 --cache eval_cache/system-ablation-controlled-v1.jsonl `
  --output-dir eval/results/system-ablation-controlled-v1 --report-name holdout
```

Use `development.jsonl`/`development` or `stress.jsonl`/`stress` for the other
stages. `--limit` is only for smoke tests. `--annotation-status human-confirmed`
must only be used after actual human review is confirmed. Running the same
command resumes existing predictions; worker count is part of the fingerprint
because it can affect latency.

The runner now applies the product's `needs_human` confidence gate even without
a checkpointer. A low-confidence allow/remove recommendation is scored as
`human-review`; the original recommendation is retained in the trace. Prediction
functions receive only ID and text, never gold labels or rationales. Cache v2
invalidates old results that used the wrong gate semantics. Source-code hashes
also invalidate stale behavior, while adding/removing another requested arm does
not invalidate a completed arm.

Reports include counts and denominators, confusion matrices, logical model turns,
and paired corrections/regressions. Logical turns are **not billed API calls**:
retries, failed attempts and embeddings are excluded. Every arm runs independently,
so one-run differences also contain residual model variation.

```powershell
.venv/Scripts/python.exe scripts/summarize_system_experiment.py
```

The summary command makes no model calls. See
`eval/results/system-ablation-controlled-v1/REPORT.md` and the case-level CSVs.
Only two held-out and one stress reference cases are labeled remove, so report
counts and do not present these as strong estimates of safety performance.

The local precedent database was empty when the experiment started. Do not seed
it automatically from `scripts/seed_precedents.py`: those entries are explicitly
drafts. The full-system arm remains pending independently reviewed precedents,
with no overlap with development, holdout, or stress cases.
