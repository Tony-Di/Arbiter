"""Precedent store -- the adjudicator's case-law memory (HITL spec 2026-06-09 §5).

Human rulings only (enforced at the two call sites: review resolution + seed
script). Embeddings via OpenAI text-embedding-3-small; similarity = cosine in
pure Python over all rows (the store is hundreds of rows at most -- deliberately
no vector DB; see NOTES).

embed_fn is injected (tests pass a deterministic fake) -- same DI pattern as
classify_fn / detect_fn / adjudicate_fn.

Check:  python -m pytest tests/test_precedents.py -v   (goal: 6 passed)
"""
import math
import os
from openai import OpenAI
from arbiter.api.db import Precedent

EMBED_MODEL = "text-embedding-3-small"


def default_embed_fn(texts: list[str]) -> list[list[float]]:
    """Embed texts via the OpenAI embeddings API (needs OPENAI_API_KEY).

    TODO(author): OpenAI(api_key=os.environ["OPENAI_API_KEY"]).embeddings
    .create(model=EMBED_MODEL, input=texts) -> [d.embedding for d in resp.data]
    (import OpenAI lazily inside the function so importing this module never
    requires a key -- tests inject a fake and must stay zero-network).
    """
    openai = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    resp = openai.embeddings.create(model=EMBED_MODEL, input=texts)
    return [d.embedding for d in resp.data]


def _cosine(a: list[float], b: list[float]) -> float:
    """dot(a,b) / (norm(a)*norm(b)); return 0.0 if either norm is 0."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def format_precedents(hits: list[dict]) -> str:
    """Render search hits for the adjudicator transcript.

    Each hit -> "<precedent>comment: ...; ruling: action=..., severity=...;
    rationale: ...</precedent>", hits joined by newlines. Precedent text is
    untrusted user content -> the <precedent> wrapper is the same
    data-not-instructions framing as <comment>. Empty list -> exactly
    "no precedents on file".

    TODO(author): implement.
    """
    formatted_hits = []
    if not hits:
        return "no precedents on file"
    for hit in hits:
        formatted_hits.append(f"<precedent>comment: {hit['comment_text']}; ruling: action={hit['action']}, severity={hit['overall_severity']}; rationale: {hit['note']}</precedent>")
    return "\n".join(formatted_hits)


class PrecedentStore:
    """add() human rulings; search() top-k similar past rulings."""

    def __init__(self, session_factory, embed_fn=default_embed_fn):
        self._sessions = session_factory
        self._embed = embed_fn

    def add(self, comment_text: str, action: str, overall_severity: int,
            note: str, source: str = "human") -> None:
        """TODO(author): embed comment_text (self._embed([comment_text])[0]),
        insert a Precedent row with all fields, commit. Session via
        self._sessions() (close it -- with-block or try/finally)."""
        embedding = self._embed([comment_text])[0]
        precedent = Precedent(comment_text=comment_text, embedding=embedding, action=action, overall_severity=overall_severity, note=note, source=source)
        session = self._sessions()
        try:
            session.add(precedent)
            session.commit()
        finally:
            session.close()

    def search(self, query_text: str, k: int = 3) -> list[dict]:
        """TODO(author): embed the query, load all Precedent rows, rank by
        _cosine desc, return the top-k as plain dicts (comment_text, action,
        overall_severity, note, source). Empty store -> []. Let embed_fn
        exceptions propagate -- the tools node catches them and turns them
        into the "precedent search unavailable" string."""
        session = self._sessions()
        try:
            embedding = self._embed([query_text])[0]
            precedents = session.query(Precedent).all() # type: ignore
            precedents_with_similarity = [(precedent, _cosine(embedding, precedent.embedding)) for precedent in precedents]
        finally:
            session.close()
        precedents_with_similarity.sort(key=lambda x: x[1], reverse=True)
        return [{"comment_text": precedent.comment_text, "action": precedent.action, "overall_severity": precedent.overall_severity, "note": precedent.note, "source": precedent.source} for precedent, similarity in precedents_with_similarity[:k]]