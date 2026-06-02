"""Manual smoke test: a real DeepSeek call. Needs DEEPSEEK_API_KEY in .env.

Not part of the pytest suite (it costs money + needs a key). Run by hand:
    python scripts/smoke_classify.py
"""

from dotenv import load_dotenv

from arbiter.classify import ALL_6, classify

load_dotenv()

CASES = [
    "I will find you and kill you.",          # expect threat-ish
    "Thanks so much, this really helped!",    # expect all none
    "oh great, ANOTHER genius idea",          # gray: sarcasm
]

for text in CASES:
    print("\n" + "=" * 60)
    print("COMMENT:", text)
    r = classify("deepseek-chat", text, ALL_6)
    for cat, v in r.verdicts.items():
        if v.severity > 0:
            print(f"  {cat:14} sev={v.severity.name:6} span={v.span!r}  {v.reason}")
    if all(v.severity == 0 for v in r.verdicts.values()):
        print("  (all none)")
