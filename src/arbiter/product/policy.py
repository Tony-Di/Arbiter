"""Deterministic policy tool sharing category boundaries with the classifiers."""
from arbiter.classify import ALL_6
from arbiter.moderation_policy import ACTION_GUIDE, CATEGORY_RULES

POLICIES = CATEGORY_RULES
_UNKNOWN = "No policy exists for that category. Valid categories: " + ", ".join(ALL_6) + "."


def get_policy(category: str) -> str:
    return f"{ACTION_GUIDE}\nCategory: {category}\n{POLICIES[category]}" if category in POLICIES else _UNKNOWN
