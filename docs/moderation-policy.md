# Moderation policy 2026-09-22.2

The source contract is `src/arbiter/moderation_policy.py`. The classifier severity
prompt, context prompt, adjudicator policy tool and annotation validator share it.
The six harm categories describe the content. Check each category's defining
criteria before scoring; evidence of one harm does not establish all other harms.
The final action also depends on
whether harmful intent remains unresolved.

| Severity | Meaning | Action |
|---|---|---|
| 0 | No policy-relevant harm | allow |
| 1 | Mild or weak harm without clear targeted abuse | allow; human-review if potentially harmful intent is unresolved |
| 2 | Clear ordinary targeted abuse or insult | human-review |
| 3 | Severe abuse, explicit protected-identity attack, or credible direct threat | remove when clear; human-review if intent is unresolved |

An ordinary insult is not an automatic removal at severity 2. A quoted attack is
not automatically exempt. Examine whether the author reports, condemns, endorses
or independently repeats the attack. Sarcastic personal abuse remains abuse.
Do not assume consent or harmlessness from `lol`, emoji, quotation marks or irony.
Do not infer a definite physical attack from unspecified adverse consequences;
potentially harmful intent that remains unclear requires review.

The context model must supply a purpose, exact original-text evidence, a rationale,
and the specific affected categories to request a one-level discount. Reporting,
condemning, reclaimed and non-targeted uses are eligible; unclear or endorsed
attacks are not. Missing/invalid evidence removes the discount and marks ambiguity.
The graph verifies literal evidence membership; semantic correctness still requires
evaluation. Threat and severe-toxicity scores are never discounted by this mechanism.

Clear severity-2 cases go directly to humans. The adjudicator handles unresolved
potentially harmful context and must submit an action/severity pair, policy category,
exact evidence and finite numeric confidence. Invalid output, exhausted tool budget,
or repeated provider failure requires human review. The 0.95 confidence threshold
is a conservative heuristic, not a calibrated probability.

Human reviewers must resolve a case to allow or remove. The final overall severity
is reconciled to that decision (allow: at most 1; remove: 3). Original category scores,
AI recommendation and the human action remain preserved separately for audit.

For annotations, record `gold_action`, `gold_categories`, `gold_severity` and a short
policy rationale. Reference labels used in the v1 experiment have **unconfirmed
human provenance**; do not describe them as independently human-verified or silently
rewrite them to fit this revision. Never put evaluation labels or unreviewed seed
drafts into the human precedent store.
