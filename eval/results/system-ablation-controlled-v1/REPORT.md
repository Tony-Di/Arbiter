# Arbiter system ablation — real API experiment

This report is generated from saved API predictions, not simulated outputs.

## Interpretation limits

- Existing reference labels are frozen unchanged. Their human authorship is unverified unless a run explicitly records human-confirmed status.
- The held-out split was fixed before this experiment. It is a held-out subset of an existing custom benchmark, not a previously unseen public test benchmark.
- Candidates were deliberately stratified by source toxicity scores. Review and error rates on this sample do not estimate live-traffic prevalence or production reviewer workload.
- Controlled experiment: all roles use gpt-5.4-mini. Four arms isolate joint versus split classification, adding context interpretation, then adding conditional policy adjudication. This is NOT the production mixed-model routing configuration.
- Low-confidence recommendations count as human-review, matching the product. Human answers are never fed to prediction functions.
- A removal label occurs only twice in holdout and once in stress. Removal-class estimates are too sparse for strong safety claims.
- Latency includes each complete variant, measured under 4 concurrent benchmark requests. It excludes human response time and is not a production load test.
- The mixed-provider diagnostic and controlled development/holdout overlapped in wall-clock time; these are observed service latencies with background load, not isolated microbenchmarks.
- Arms execute independently at temperature zero; residual response variation remains. This is one run, without repeated-run confidence intervals.
- The product policy, 0.95 confidence threshold and six-step cap were unchanged. The threshold has not been calibrated for GPT.
- Logical model turns exclude retries, failed attempts and embeddings. Token usage and dollar cost were not measured.
- The local precedent store was empty. The human-precedent arm is pending independent reviewed data; it is not represented by a fake empty-store run.

## Development (20 cases)

Annotation status: `unverified`. Failed predictions: 0.

| Variant | Completed | Action macro-F1 | Unsafe allows | Over-removes | Human review | P50 seconds | P95 seconds |
|---|---:|---:|---:|---:|---:|---:|---:|
| single_call | 20/20 | 0.656 | 0/5 | 1/19 | 8/20 | 3.00 | 3.98 |
| specialists_only | 20/20 | 0.643 | 0/5 | 2/19 | 4/20 | 2.53 | 3.21 |
| specialist_panel | 20/20 | 0.643 | 0/5 | 2/19 | 4/20 | 2.68 | 3.18 |
| policy_agent | 20/20 | 0.392 | 0/5 | 5/19 | 2/20 | 2.76 | 6.65 |

Paired changes count exact matches against the frozen reference actions; they are not statistical significance tests.

- `single_call` → `specialists_only`: 20 common cases; 3 corrected, 1 regressed, 4 changed.
- `specialists_only` → `specialist_panel`: 20 common cases; 0 corrected, 0 regressed, 0 changed.
- `specialist_panel` → `policy_agent`: 20 common cases; 0 corrected, 3 regressed, 4 changed.
- `single_call`: 0 fallback decisions after adjudicator unavailability or step limit.
- `specialists_only`: 0 fallback decisions after adjudicator unavailability or step limit.
- `specialist_panel`: 0 fallback decisions after adjudicator unavailability or step limit.
- `policy_agent`: 0 fallback decisions after adjudicator unavailability or step limit.

Configuration fingerprint: `7c29ac54e4919fc9473447895e1490fb92069124b229b5b1136049b6e9c2a25e`.
Benchmark fingerprint: `879ebf1d518a26f534dbeb5af32beb0c518af49eda5812d2ec1cfcd36da68179`.

## Holdout (110 cases)

Annotation status: `unverified`. Failed predictions: 0.

| Variant | Completed | Action macro-F1 | Unsafe allows | Over-removes | Human review | P50 seconds | P95 seconds |
|---|---:|---:|---:|---:|---:|---:|---:|
| single_call | 110/110 | 0.498 | 1/26 | 6/108 | 50/110 | 2.96 | 3.61 |
| specialists_only | 110/110 | 0.637 | 1/26 | 4/108 | 42/110 | 2.49 | 3.80 |
| specialist_panel | 110/110 | 0.544 | 3/26 | 7/108 | 40/110 | 2.64 | 3.36 |
| policy_agent | 110/110 | 0.505 | 2/26 | 13/108 | 37/110 | 2.92 | 8.46 |

Paired changes count exact matches against the frozen reference actions; they are not statistical significance tests.

- `single_call` → `specialists_only`: 110 common cases; 11 corrected, 1 regressed, 14 changed.
- `specialists_only` → `specialist_panel`: 110 common cases; 2 corrected, 9 regressed, 12 changed.
- `specialist_panel` → `policy_agent`: 110 common cases; 5 corrected, 7 regressed, 17 changed.
- `single_call`: 0 fallback decisions after adjudicator unavailability or step limit.
- `specialists_only`: 0 fallback decisions after adjudicator unavailability or step limit.
- `specialist_panel`: 0 fallback decisions after adjudicator unavailability or step limit.
- `policy_agent`: 0 fallback decisions after adjudicator unavailability or step limit.

Configuration fingerprint: `7c29ac54e4919fc9473447895e1490fb92069124b229b5b1136049b6e9c2a25e`.
Benchmark fingerprint: `6122016bc9eb37ecbb376ffceaf09c56b25397b55e7641fa855b4983e7005880`.

## Stress (30 cases)

Annotation status: `unverified`. Failed predictions: 0.

| Variant | Completed | Action macro-F1 | Unsafe allows | Over-removes | Human review | P50 seconds | P95 seconds |
|---|---:|---:|---:|---:|---:|---:|---:|
| single_call | 30/30 | 0.505 | 0/11 | 4/29 | 16/30 | 3.04 | 3.75 |
| specialists_only | 30/30 | 0.414 | 0/11 | 6/29 | 15/30 | 2.69 | 3.14 |
| specialist_panel | 30/30 | 0.410 | 0/11 | 7/29 | 14/30 | 2.67 | 3.04 |
| policy_agent | 30/30 | 0.349 | 0/11 | 9/29 | 12/30 | 4.97 | 11.16 |

Paired changes count exact matches against the frozen reference actions; they are not statistical significance tests.

- `single_call` → `specialists_only`: 30 common cases; 1 corrected, 4 regressed, 7 changed.
- `specialists_only` → `specialist_panel`: 30 common cases; 1 corrected, 1 regressed, 3 changed.
- `specialist_panel` → `policy_agent`: 30 common cases; 1 corrected, 3 regressed, 4 changed.
- `single_call`: 0 fallback decisions after adjudicator unavailability or step limit.
- `specialists_only`: 0 fallback decisions after adjudicator unavailability or step limit.
- `specialist_panel`: 0 fallback decisions after adjudicator unavailability or step limit.
- `policy_agent`: 0 fallback decisions after adjudicator unavailability or step limit.

Configuration fingerprint: `7c29ac54e4919fc9473447895e1490fb92069124b229b5b1136049b6e9c2a25e`.
Benchmark fingerprint: `cc39e086cf0d06e4a0da67fe6cc2499419d8154c74edc69c6a40c1676338b564`.

## Reproducibility

Frozen cases and manifests: `eval/experiments/system-ablation-v1/`.
Raw resumable cache: `eval_cache/system-ablation-controlled-v1.jsonl` (local, ignored by Git).
Regenerate this report with `python scripts/summarize_system_experiment.py` (add `--mixed` for the mixed-provider pilot); it makes no model calls.
