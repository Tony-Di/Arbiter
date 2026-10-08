# Arbiter system ablation — real API experiment

This report is generated from saved API predictions, not simulated outputs.

## Interpretation limits

- Existing reference labels are frozen unchanged. Their human authorship is unverified unless a run explicitly records human-confirmed status.
- The held-out split was fixed before this experiment. It is a held-out subset of an existing custom benchmark, not a previously unseen public test benchmark.
- Candidates were deliberately stratified by source toxicity scores. Review and error rates on this sample do not estimate live-traffic prevalence or production reviewer workload.
- Mixed-provider diagnostic: GPT single call; routed specialists + DeepSeek context; panel + DeepSeek policy adjudicator. Differences cannot all be attributed to agent count.
- Low-confidence recommendations count as human-review, matching the product. Human answers are never fed to prediction functions.
- A removal label occurs only twice in holdout and once in stress. Removal-class estimates are too sparse for strong safety claims.
- Latency includes each complete variant, measured under 2 concurrent benchmark requests. It excludes human response time and is not a production load test.
- Arms execute independently at temperature zero; residual response variation remains. This is one run, without repeated-run confidence intervals.
- The product policy, 0.95 confidence threshold and six-step cap were unchanged. The threshold has not been calibrated for GPT.
- Logical model turns exclude retries, failed attempts and embeddings. Token usage and dollar cost were not measured.
- The local precedent store was empty. The human-precedent arm is pending independent reviewed data; it is not represented by a fake empty-store run.

## Development (20 cases)

Annotation status: `unverified`. Failed predictions: 1.

| Variant | Completed | Action macro-F1 | Unsafe allows | Over-removes | Human review | P50 seconds | P95 seconds |
|---|---:|---:|---:|---:|---:|---:|---:|
| single_call | 20/20 | 0.686 | 0/5 | 1/19 | 7/20 | 2.47 | 3.34 |
| specialist_panel | 19/20 | 0.476 | 0/4 | 2/19 | 4/19 | 19.59 | 34.03 |
| policy_agent | 20/20 | 0.719 | 0/5 | 1/19 | 6/20 | 23.37 | 187.47 |

Paired changes count exact matches against the frozen reference actions; they are not statistical significance tests.

- `single_call` → `specialist_panel`: 19 common cases; 2 corrected, 1 regressed, 3 changed.
- `specialist_panel` → `policy_agent`: 19 common cases; 1 corrected, 1 regressed, 2 changed.
- `single_call`: 0 fallback decisions after adjudicator unavailability or step limit.
- `specialist_panel`: 0 fallback decisions after adjudicator unavailability or step limit.
- `policy_agent`: 0 fallback decisions after adjudicator unavailability or step limit.

Configuration fingerprint: `f6fb8b684faf50de3e61bbdb4d2d75a17c22354f368890d1758dba0d6271fec0`.
Benchmark fingerprint: `879ebf1d518a26f534dbeb5af32beb0c518af49eda5812d2ec1cfcd36da68179`.

## Reproducibility

Frozen cases and manifests: `eval/experiments/system-ablation-v1/`.
Raw resumable cache: `eval_cache/system-ablation-v1.jsonl` (local, ignored by Git).
Regenerate this report with `python scripts/summarize_system_experiment.py` (add `--mixed` for the mixed-provider pilot); it makes no model calls.
