"""PrecedentStore -- add / cosine search / tool formatting. Zero-network
(embed_fn injected, same DI pattern as classify_fn / detect_fn).

Check:  python -m pytest tests/test_precedents.py -v   (goal: 6 passed)
"""
from arbiter.api.db import Base, make_engine, make_session_factory
from arbiter.precedents import PrecedentStore, format_precedents


def _fake_embed(texts):
    # deterministic 3-dim "embeddings": cat / dog / other axes
    def vec(t):
        if "cat" in t:
            return [1.0, 0.0, 0.0]
        if "dog" in t:
            return [0.0, 1.0, 0.0]
        return [0.0, 0.0, 1.0]
    return [vec(t) for t in texts]


def _store():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    return PrecedentStore(make_session_factory(engine), embed_fn=_fake_embed)


def test_add_and_search_ranks_by_similarity():
    s = _store()
    s.add("the cat insult", "remove", 2, "feline abuse")
    s.add("the dog praise", "allow", 0, "fine")
    hits = s.search("another cat comment", k=2)
    assert hits[0]["comment_text"] == "the cat insult"
    assert hits[0]["action"] == "remove"
    assert hits[0]["overall_severity"] == 2


def test_search_truncates_to_k():
    s = _store()
    for i in range(5):
        s.add(f"cat number {i}", "allow", 0, "n")
    assert len(s.search("cat", k=3)) == 3


def test_empty_store_returns_empty_list():
    assert _store().search("anything") == []


def test_add_defaults_source_human():
    s = _store()
    s.add("cat", "allow", 0, "n")
    assert s.search("cat")[0]["source"] == "human"


def test_format_wraps_in_precedent_tags():
    txt = format_precedents([{"comment_text": "x", "action": "remove",
                              "overall_severity": 2, "note": "n", "source": "human"}])
    assert txt.startswith("<precedent>")
    assert "</precedent>" in txt
    assert "remove" in txt


def test_format_empty_store_message():
    assert format_precedents([]) == "no precedents on file"
