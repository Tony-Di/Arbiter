# Independent precedent review needed

The current local precedent table contains no rows. The following entries are
existing drafts from `scripts/seed_precedents.py`, not confirmed human decisions.
They have not been inserted into the database or used to claim full-system gains.

A moderator should confirm or edit the action, severity, and reason for every
case before import. In particular, drafts 8, 10 and 11 say **remove at severity
2**, while the current annotation guide requires severity 3 for remove. Resolve
the policy interpretation explicitly rather than mechanically copying labels.

| # | Comment | Draft action | Draft severity | Review status |
|---|---|---|---:|---|
| 1 | I'd literally kill for tickets to that show | allow | 0 | Unreviewed |
| 2 | He called me a 'worthless idiot' — can you believe that? | allow | 0 | Unreviewed |
| 3 | ur team got destroyed lol, absolute trash | allow | 1 | Unreviewed |
| 4 | people like you should not exist | remove | 3 | Unreviewed |
| 5 | as a queer person, us queers can joke about this | allow | 0 | Unreviewed |
| 6 | what a brilliant idea... said no one ever | allow | 1 | Unreviewed |
| 7 | go back to where you came from | remove | 3 | Unreviewed |
| 8 | I hope your house burns down | remove | 2 | Unreviewed |
| 9 | this is so stupid | allow | 0 | Unreviewed |
| 10 | you're a clown and everyone laughs at you | remove | 2 | Unreviewed |
| 11 | delete your account before someone makes you | remove | 2 | Unreviewed |
| 12 | OP is being a bit naive here imo | allow | 0 | Unreviewed |

Store approved cases in a separate, fixed benchmark precedent database. Check
exact and near-duplicate overlap with every evaluation split. Never write test
answers back as precedents while measuring the system.

The seed script now requires `--confirm-human-review` and validates every
action/severity pair before any API or database write. The current drafts still
contain incompatible remove/2 pairs, so the command intentionally refuses them
until a human edits the rulings. Routine reviewed cases enter via the review API
and its durable embedding outbox instead.
