"""Tests for the get_policy tool (escalation spec §5). Zero network."""
from arbiter.classify import ALL_6
from arbiter.product.policy import POLICIES, get_policy


def test_all_six_categories_have_real_policies():
    for c in ALL_6:
        assert c in POLICIES
        assert POLICIES[c] and POLICIES[c] != "TODO"


def test_get_policy_returns_text_for_known_category():
    text = get_policy("identity_hate")
    assert isinstance(text, str) and "protected" in text.lower()


def test_get_policy_unknown_category_degrades_not_raises():
    text = get_policy("does_not_exist")
    assert "No policy" in text
    assert "identity_hate" in text  # lists the valid categories
