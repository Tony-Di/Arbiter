"""Seed the precedent store with hand-labeled gray-case rulings (one cheap
embedding run; needs OPENAI_API_KEY in .env).

The labels below are DRAFTS — the author is the moderator of record: review and
edit them before running; that's what makes them human precedents.

Run:  .venv\\Scripts\\python scripts/seed_precedents.py
"""
import argparse
from dotenv import load_dotenv

from arbiter.api.db import SessionLocal, init_db
from arbiter.precedents import PrecedentStore
from arbiter.moderation_policy import validate_action_severity

SEEDS = [
    ("I'd literally kill for tickets to that show", "allow", 0,
     "hyperbolic idiom, no target — not a threat"),
    ("He called me a 'worthless idiot' — can you believe that?", "allow", 0,
     "quoting abuse to report it, not committing it"),
    ("ur team got destroyed lol, absolute trash", "allow", 1,
     "sports trash talk aimed at a team, not a person's identity"),
    ("people like you should not exist", "remove", 3,
     "dehumanizing a person — severe even without slurs"),
    ("as a queer person, us queers can joke about this", "allow", 0,
     "in-group reclaimed use, no attack"),
    ("what a brilliant idea... said no one ever", "allow", 1,
     "sarcastic criticism of an idea, not a person"),
    ("go back to where you came from", "remove", 3,
     "xenophobic trope targeting national origin"),
    ("I hope your house burns down", "remove", 2,
     "targeted wish of harm — threat-adjacent"),
    ("this is so stupid", "allow", 0,
     "criticizes the content, not its author"),
    ("you're a clown and everyone laughs at you", "remove", 2,
     "direct personal insult, sustained ridicule"),
    ("delete your account before someone makes you", "remove", 2,
     "veiled threat dressed as advice"),
    ("OP is being a bit naive here imo", "allow", 0,
     "mild criticism within civil bounds"),
]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-human-review", action="store_true",
                        help="Confirm you independently reviewed and edited every draft ruling")
    args = parser.parse_args()
    if not args.confirm_human_review:
        raise SystemExit("Drafts are not human precedents. Review/edit every row before using --confirm-human-review.")
    for comment, action, severity, note in SEEDS:
        validate_action_severity(action, severity)
        if action not in {"allow", "remove"}:
            raise SystemExit("A precedent requires a resolved allow/remove human decision.")
    load_dotenv()
    init_db()
    store = PrecedentStore(SessionLocal)
    for comment, action, severity, note in SEEDS:
        store.add(comment, action, severity, note, source="human")
        print(f"seeded: {action:6s}  {comment[:50]}")
    print(f"\n{len(SEEDS)} precedents seeded.")
