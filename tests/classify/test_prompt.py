from arbiter.classify.prompt import PROMPT_VERSION, build_prompt
from arbiter.classify.schema import ALL_6


def test_prompt_version_present():
    assert isinstance(PROMPT_VERSION, str) and PROMPT_VERSION


def test_prompt_lists_only_requested_categories():
    p = build_prompt("some comment", ["toxic", "threat"])
    assert "toxic" in p and "threat" in p and "obscene" not in p


def test_prompt_includes_comment_and_rubric_levels():
    p = build_prompt("you are an idiot", ALL_6)
    assert "you are an idiot" in p
    for level in ("none", "low", "medium", "high"):
        assert level in p
