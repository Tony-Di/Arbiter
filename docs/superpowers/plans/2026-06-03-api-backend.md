# API Backend (FastAPI + Postgres) — Implementation Plan  [P5a]

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **For the author:** scaffold-only, **tests are your target** (red → green). I give skeletons + full test files; you write the 🔨 bodies. Framework/infra wiring (FastAPI app, SQLAlchemy engine) gets fuller hints because it's new to this repo. Every `git` commit is **run by you** — messages provided.

**Goal:** Wrap the working LangGraph pipeline in a thin FastAPI service — `POST /api/moderate` runs the graph and persists the submission + verdict to a database — so the product is callable over HTTP (spec §11–12). This is **P5a**; the Next.js frontend (P5b) and deploy (P5c) are separate plans.

**Architecture:** A new `src/arbiter/api/` package. The compiled graph and routing table are loaded **once at startup** (FastAPI lifespan); each request calls `graph.invoke(initial_state(comment))`, maps the result to a response model, and saves it. Persistence uses **SQLAlchemy 2.0** with a `DATABASE_URL` — defaulting to **local SQLite (zero setup)** and switching to **Postgres in prod** by env var alone. The graph and DB session are **FastAPI dependencies**, so tests override them with the P4 fakes + an in-memory DB → the whole API tests with **zero network**.

**Tech Stack:** Python 3.14 · **FastAPI** + **uvicorn** + **SQLAlchemy>=2** (new deps) · `pydantic` (already in) · `httpx`/`TestClient` (httpx already installed via openai) · `pytest`.

**Scope (this plan):** `schemas` (request/response + mapper) · `db` (engine/session/models + persist helper) · `main` (app + lifespan + 2 endpoints) + a real DeepSeek HTTP smoke. **Deferred:** Next.js frontend (P5b), Vercel/Railway deploy (P5c), `GET /api/history` (optional, noted), auth/rate-limiting (not in v1).

---

## Open decisions resolved in this plan (confirm during review)

1. **Per-category `severity` in the response = the EFFECTIVE (post-adjustment) severity; `reason`/`span` = the RAW LLM verdict.** Rationale: the UI shows the verdict the product stands behind (e.g. a sarcastic insult displays `insult=1` after downgrade, spec §5.1/§9), but the *justification* and the offending substring come from the specialist's raw output. The DB stores raw + effective + flags side by side (spec §11) so nothing is lost.
2. **DB portability via SQLAlchemy generic `JSON` columns** (not PG-specific `JSONB`) so the same models run on SQLite (dev) and Postgres (prod). Swapping to `JSONB` for Postgres-only indexing is a deferred optimization.
3. **`DATABASE_URL` env var**, default `sqlite:///./arbiter.db`. Local dev needs no database install; prod sets `DATABASE_URL=postgresql+psycopg://…`.

---

## Data contracts

**Pipeline output** (`graph.invoke(initial_state(comment))` returns the final `ModerationState`):
```python
{
  "comment": "you idiot",
  "raw_verdicts": {"insult": {"severity": 2, "reason": "name-calling", "span": "idiot"}, ...},  # all 6
  "routing_snapshot": {"insult": "deepseek-chat", ...},
  "context_flags": {"sarcasm": False, ..., "ambiguity": False, "note": None},
  "effective_verdicts": {"insult": 2, ...},   # per-category int AFTER adjustment
  "overall_severity": 2,
  "action": "human-review",
}
```

**`POST /api/moderate`** (spec §12):
```
request : {"comment": "you idiot"}
response: {
  "overall_severity": 2,
  "action": "human-review",
  "categories": [{"name": "toxic", "severity": 0, "reason": "...", "span": null}, ...],  # 6, in ALL_6 order
  "context_flags": {"sarcasm": false, ..., "note": null}
}
```

**DB tables** (spec §11):
- `submissions(id, comment_text, created_at)`
- `verdicts(id, submission_id→submissions.id, overall_severity, action, raw_verdicts JSON, context_flags JSON, effective_verdicts JSON, routing_snapshot JSON, created_at)`

---

## What I give vs. what you write

| I give | 🔨 You implement |
|---|---|
| this plan + all module skeletons | `schemas.py` — `to_response()` mapper |
| **all test files** (your targets) | `db.py` — the two models + `save_verdict()` |
| `make_engine()` (the SQLite-threading/in-memory gotcha) | `main.py` — the `/api/moderate` handler body |
| FastAPI app + lifespan + dependency wiring | the smoke glue |
| `pyproject.toml` dep line + install command | |

---

## File structure (this plan)

```
arbiter/
  pyproject.toml                       # +fastapi, +uvicorn, +sqlalchemy
  .gitignore                           # +*.db (local sqlite)
  src/arbiter/api/
    __init__.py                        # I give (empty)
    schemas.py                         # 🔨 request/response models + to_response()
    db.py                              # 🔨 models + save_verdict (make_engine given)
    main.py                            # 🔨 the /api/moderate handler body (app wiring given)
  tests/api/                           # I give ALL
    __init__.py
    test_schemas.py  test_db.py  test_api.py
  scripts/smoke_api.py                 # I give the shell; you fill the 🔨 glue
```

---

## Task 0: add deps + scaffold the `api` package

**Files:** Modify `pyproject.toml`, `.gitignore`; Create `src/arbiter/api/__init__.py`, `tests/api/__init__.py`.

- [ ] **Step 1: add deps** to `pyproject.toml` `dependencies`:
```toml
dependencies = ["pydantic>=2.7", "openai>=1.40", "python-dotenv>=1.0", "langgraph>=0.2", "fastapi>=0.115", "uvicorn>=0.30", "sqlalchemy>=2.0"]
```

- [ ] **Step 2: install**

Run: `.\.venv\Scripts\python.exe -m pip install -e ".[dev]"`
Expected: installs fastapi, uvicorn, sqlalchemy. *(If a wheel fails on 3.14, try `pip install -U <pkg>`; stop and flag me if genuinely blocked.)*

> Note: `httpx` (needed by `fastapi.testclient.TestClient`) is already installed via `openai`. For **prod Postgres** you'll later add `psycopg[binary]` and set `DATABASE_URL` — not needed for local SQLite dev.

- [ ] **Step 3: gitignore the local sqlite file** — append to `.gitignore`:
```
*.db
```

- [ ] **Step 4: create the two `__init__.py`** (both empty): `src/arbiter/api/__init__.py`, `tests/api/__init__.py`.

- [ ] **Step 5: confirm baseline still green**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: the existing **65** tests still pass; new empty `tests/api/` collects nothing.

- [ ] **Step 6: Commit** *(you run)*
```
git add pyproject.toml .gitignore src/arbiter/api/__init__.py tests/api/__init__.py
git commit -m "chore(api): add fastapi/sqlalchemy deps + scaffold api package"
```

---

## Task 1: 🔨 `schemas.py` — request/response models + mapper

**Files:** Create `src/arbiter/api/schemas.py` 🔨 · Test (given): `tests/api/test_schemas.py`

**Spec:**
- `ModerateRequest(BaseModel)`: `comment: str` (use `Field(min_length=1)` so empty input is a 422).
- `CategoryOut(BaseModel)`: `name: str`, `severity: int`, `reason: str`, `span: str | None`.
- `ModerateResponse(BaseModel)`: `overall_severity: int`, `action: str`, `categories: list[CategoryOut]`, `context_flags: dict`.
- `to_response(state: dict) -> ModerateResponse`: build `categories` for each `cat in ALL_6` (stable order) with `severity = state["effective_verdicts"][cat]`, `reason`/`span` from `state["raw_verdicts"][cat]`; copy `overall_severity`, `action`, `context_flags` straight through.

- [ ] **Step 1: the test is given — run, watch it fail**
```python
# tests/api/test_schemas.py
from arbiter.classify import ALL_6
from arbiter.api.schemas import to_response, ModerateResponse


def _state():
    raw = {c: {"severity": 0, "reason": f"r-{c}", "span": None} for c in ALL_6}
    raw["insult"] = {"severity": 2, "reason": "name-calling", "span": "idiot"}
    eff = {c: 0 for c in ALL_6}
    eff["insult"] = 2
    return {
        "comment": "you idiot",
        "raw_verdicts": raw,
        "routing_snapshot": {c: "deepseek-chat" for c in ALL_6},
        "context_flags": {"sarcasm": False, "quotation": False, "reclaimed_slur": False,
                          "direct_threat": False, "ambiguity": False, "note": None},
        "effective_verdicts": eff,
        "overall_severity": 2,
        "action": "human-review",
    }


def test_to_response_top_level_fields():
    r = to_response(_state())
    assert isinstance(r, ModerateResponse)
    assert r.overall_severity == 2
    assert r.action == "human-review"
    assert r.context_flags["sarcasm"] is False


def test_to_response_has_all_6_categories_in_order():
    r = to_response(_state())
    assert [c.name for c in r.categories] == ALL_6


def test_to_response_category_uses_effective_severity_and_raw_reason_span():
    by = {c.name: c for c in to_response(_state()).categories}
    assert by["insult"].severity == 2          # EFFECTIVE
    assert by["insult"].reason == "name-calling"  # from RAW
    assert by["insult"].span == "idiot"
    assert by["toxic"].severity == 0
    assert by["toxic"].span is None
```
Run: `.\.venv\Scripts\python.exe -m pytest tests/api/test_schemas.py -v` → Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 2: 🔨 implement `schemas.py`.** Skeleton:
```python
"""Request/response models for the moderate endpoint + the state->response mapper.

Fill the TODOs (spec: plan Task 1).
Check:  python -m pytest tests/api/test_schemas.py -v   (goal: 3 passed)
"""
from pydantic import BaseModel, Field

from arbiter.classify import ALL_6


class ModerateRequest(BaseModel):
    comment: str = Field(min_length=1)


class CategoryOut(BaseModel):
    # 🔨 TODO: name: str ; severity: int ; reason: str ; span: str | None
    ...


class ModerateResponse(BaseModel):
    # 🔨 TODO: overall_severity: int ; action: str ;
    #          categories: list[CategoryOut] ; context_flags: dict
    ...


def to_response(state: dict) -> ModerateResponse:
    # 🔨 TODO:
    #   categories = [CategoryOut(name=c,
    #                             severity=state["effective_verdicts"][c],
    #                             reason=state["raw_verdicts"][c]["reason"],
    #                             span=state["raw_verdicts"][c]["span"]) for c in ALL_6]
    #   return ModerateResponse(overall_severity=state["overall_severity"],
    #                           action=state["action"],
    #                           categories=categories,
    #                           context_flags=state["context_flags"])
    ...
```

- [ ] **Step 3: run → green** (3 passed).

- [ ] **Step 4: Commit** *(you run)*
```
git add src/arbiter/api/schemas.py tests/api/test_schemas.py
git commit -m "feat(api): request/response schemas + state->response mapper"
```

---

## Task 2: 🔨 `db.py` — models + persist helper

**Files:** Create `src/arbiter/api/db.py` 🔨 · Test (given): `tests/api/test_db.py`

> I give `make_engine` because it hides a real SQLite gotcha: file-SQLite needs `check_same_thread=False` (TestClient/uvicorn use a worker thread), and in-memory `sqlite://` needs a `StaticPool` or each connection gets its own empty DB. You write the two models + `save_verdict`.

**Spec — you implement:**
- `class Submission(Base)` → table `submissions`: `id` (int pk), `comment_text` (str), `created_at` (datetime, `server_default=func.now()`).
- `class Verdict(Base)` → table `verdicts`: `id` (int pk), `submission_id` (int, FK→`submissions.id`), `overall_severity` (int), `action` (str), `raw_verdicts`/`context_flags`/`effective_verdicts`/`routing_snapshot` (each `mapped_column(JSON)`), `created_at` (datetime, `server_default=func.now()`).
- `save_verdict(db, comment: str, state: dict) -> Submission`:
  1. `sub = Submission(comment_text=comment)`; `db.add(sub)`; `db.flush()` (to get `sub.id`).
  2. `db.add(Verdict(submission_id=sub.id, overall_severity=state["overall_severity"], action=state["action"], raw_verdicts=state["raw_verdicts"], context_flags=state["context_flags"], effective_verdicts=state["effective_verdicts"], routing_snapshot=state["routing_snapshot"]))`.
  3. `db.commit()`; `db.refresh(sub)`; `return sub`.

- [ ] **Step 1: the test is given — run, watch it fail**
```python
# tests/api/test_db.py
from arbiter.classify import ALL_6
from arbiter.api.db import Base, make_engine, make_session_factory, save_verdict, Submission, Verdict


def _state():
    raw = {c: {"severity": 0, "reason": "r", "span": None} for c in ALL_6}
    raw["insult"] = {"severity": 2, "reason": "name-calling", "span": "idiot"}
    return {
        "raw_verdicts": raw,
        "routing_snapshot": {c: "deepseek-chat" for c in ALL_6},
        "context_flags": {"sarcasm": False, "ambiguity": False, "note": None},
        "effective_verdicts": {**{c: 0 for c in ALL_6}, "insult": 2},
        "overall_severity": 2,
        "action": "human-review",
    }


def _session():
    engine = make_engine("sqlite://")          # in-memory, StaticPool -> shared
    Base.metadata.create_all(engine)
    return make_session_factory(engine)()


def test_save_verdict_persists_both_rows():
    db = _session()
    sub = save_verdict(db, "you idiot", _state())
    assert sub.id is not None
    assert db.query(Submission).count() == 1
    assert db.query(Submission).one().comment_text == "you idiot"
    v = db.query(Verdict).one()
    assert v.submission_id == sub.id
    assert v.action == "human-review"
    assert v.overall_severity == 2


def test_save_verdict_roundtrips_json_columns():
    db = _session()
    save_verdict(db, "you idiot", _state())
    v = db.query(Verdict).one()
    assert v.raw_verdicts["insult"]["span"] == "idiot"          # JSON column round-trips
    assert v.effective_verdicts["insult"] == 2
    assert v.routing_snapshot["insult"] == "deepseek-chat"
```
Run: `.\.venv\Scripts\python.exe -m pytest tests/api/test_db.py -v` → Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 2: 🔨 implement `db.py`.** Skeleton (`make_engine`/factories/`init_db` given; fill the models + `save_verdict`):
```python
"""SQLAlchemy persistence — product runtime only (spec §11).

DATABASE_URL: default local SQLite (zero setup); prod sets postgresql+psycopg://...
make_engine handles the SQLite threading + in-memory-sharing gotchas for you.

Fill the TODOs (spec: plan Task 2).
Check:  python -m pytest tests/api/test_db.py -v   (goal: 2 passed)
"""
import os
from datetime import datetime

from sqlalchemy import JSON, ForeignKey, create_engine, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./arbiter.db")


def make_engine(url: str = DATABASE_URL):
    """Engine that works for file-SQLite, in-memory SQLite, and Postgres."""
    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
        # in-memory needs StaticPool so every connection shares the one DB
        kw = {"poolclass": StaticPool} if url in ("sqlite://", "sqlite:///:memory:") else {}
        return create_engine(url, connect_args=connect_args, **kw)
    return create_engine(url)


def make_session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Submission(Base):
    __tablename__ = "submissions"
    id: Mapped[int] = mapped_column(primary_key=True)   # given: a PK is required or the model won't import
    # 🔨 TODO: add the rest:
    #   comment_text: Mapped[str]
    #   created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Verdict(Base):
    __tablename__ = "verdicts"
    id: Mapped[int] = mapped_column(primary_key=True)   # given: a PK is required or the model won't import
    # 🔨 TODO: add the rest:
    #   submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"))
    #   overall_severity: Mapped[int]
    #   action: Mapped[str]
    #   raw_verdicts: Mapped[dict] = mapped_column(JSON)
    #   context_flags: Mapped[dict] = mapped_column(JSON)
    #   effective_verdicts: Mapped[dict] = mapped_column(JSON)
    #   routing_snapshot: Mapped[dict] = mapped_column(JSON)
    #   created_at: Mapped[datetime] = mapped_column(server_default=func.now())


# Module-level engine/session for the running app (tests build their own).
engine = make_engine()
SessionLocal = make_session_factory(engine)


def init_db():
    Base.metadata.create_all(engine)


def save_verdict(db, comment: str, state: dict) -> "Submission":
    # 🔨 TODO: add Submission -> flush (get id) -> add Verdict -> commit -> refresh -> return sub
    ...
```

- [ ] **Step 3: run → green** (2 passed).

- [ ] **Step 4: Commit** *(you run)*
```
git add src/arbiter/api/db.py tests/api/test_db.py
git commit -m "feat(api): sqlalchemy models + save_verdict (sqlite dev / postgres prod)"
```

---

## Task 3: 🔨 `main.py` — FastAPI app + endpoints

**Files:** Create `src/arbiter/api/main.py` 🔨 · Test (given): `tests/api/test_api.py`

> I give the app, lifespan (build the graph once), and the `get_graph`/`get_db` dependencies. You write the **3-line `/api/moderate` handler body**. Tests override both dependencies with the P4 fakes + an in-memory DB → the endpoint runs end-to-end with **zero network**.

**Spec — you implement the handler body of `moderate`:**
```python
state = graph.invoke(initial_state(req.comment))
save_verdict(db, req.comment, state)
return to_response(state)
```

- [ ] **Step 1: the test is given — run, watch it fail**
```python
# tests/api/test_api.py
from fastapi.testclient import TestClient

from arbiter.classify import ALL_6
from arbiter.classify.schema import ClassifyResult, Severity
from arbiter.product.context import ContextFlags
from arbiter.product.graph import build_graph
from arbiter.api.main import app, get_graph, get_db
from arbiter.api.db import Base, make_engine, make_session_factory, Submission

TABLE = {c: {"model": "deepseek-chat", "threshold": 1} for c in ALL_6}


def _fake_classify(model, comment, categories):
    cat = categories[0]
    sev = Severity.medium if cat == "insult" else Severity.none
    return ClassifyResult(verdicts={cat: {"severity": sev, "reason": "r", "span": None}})


def _fake_detect(comment):
    return ContextFlags()


def _client():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    TestSession = make_session_factory(engine)
    fake_graph = build_graph(TABLE, classify_fn=_fake_classify, detect_fn=_fake_detect)

    def _get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_graph] = lambda: fake_graph
    app.dependency_overrides[get_db] = _get_db
    return TestClient(app), TestSession


def test_health():
    client, _ = _client()
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_moderate_returns_verdict():
    client, _ = _client()
    r = client.post("/api/moderate", json={"comment": "you idiot"})
    assert r.status_code == 200
    body = r.json()
    assert body["action"] == "human-review"
    assert body["overall_severity"] == 2
    insult = next(c for c in body["categories"] if c["name"] == "insult")
    assert insult["severity"] == 2
    assert len(body["categories"]) == 6


def test_moderate_persists_a_submission():
    client, TestSession = _client()
    client.post("/api/moderate", json={"comment": "you idiot"})
    db = TestSession()
    assert db.query(Submission).count() == 1


def test_empty_comment_is_422():
    client, _ = _client()
    r = client.post("/api/moderate", json={"comment": ""})
    assert r.status_code == 422


def teardown_function():
    app.dependency_overrides.clear()
```
Run: `.\.venv\Scripts\python.exe -m pytest tests/api/test_api.py -v` → Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 2: 🔨 implement `main.py`** — fill ONLY the handler body (the rest is given):
```python
"""FastAPI app — wraps the LangGraph pipeline (spec §12).

Graph + routing table are built ONCE at startup (lifespan). The graph and DB
session are dependencies so tests override them (fakes + in-memory DB, no network).

Fill the 🔨 handler body (spec: plan Task 3).
Check:  python -m pytest tests/api/test_api.py -v   (goal: 4 passed)
"""
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from arbiter.product.graph import build_graph
from arbiter.product.routing import load_routing_table
from arbiter.product.state import initial_state
from arbiter.api.db import SessionLocal, init_db, save_verdict
from arbiter.api.schemas import ModerateRequest, ModerateResponse, to_response

_graph = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _graph
    init_db()
    _graph = build_graph(load_routing_table("routing_table.json"))
    yield


app = FastAPI(title="Arbiter", lifespan=lifespan)


def get_graph():
    return _graph


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/moderate", response_model=ModerateResponse)
def moderate(req: ModerateRequest, graph=Depends(get_graph), db=Depends(get_db)):
    # 🔨 TODO (3 lines):
    #   state = graph.invoke(initial_state(req.comment))
    #   save_verdict(db, req.comment, state)
    #   return to_response(state)
    ...
```

- [ ] **Step 3: run → green** (4 passed). Then the whole api suite + full suite:
Run: `.\.venv\Scripts\python.exe -m pytest tests/api -v` → Expected: all green (schemas 3 + db 2 + api 4 = 9).
Run: `.\.venv\Scripts\python.exe -m pytest -q` → Expected: 65 + 9 = **74** green.

- [ ] **Step 4: Commit** *(you run)*
```
git add src/arbiter/api/main.py tests/api/test_api.py
git commit -m "feat(api): POST /api/moderate + health endpoint (graph + db wired)"
```

---

## Task 4: real DeepSeek HTTP smoke

**Files:** I give the shell of `scripts/smoke_api.py` (you fill the 🔨 glue). Needs `DEEPSEEK_API_KEY` in `.env`.

> Boots the app in-process with the REAL graph (no dependency overrides) and posts a couple of comments via `TestClient` — proves the HTTP layer + persistence work against live DeepSeek without needing uvicorn/curl in a second terminal.

- [ ] **Step 1: I provide `scripts/smoke_api.py`:**
```python
"""Smoke-test the HTTP API end-to-end on DeepSeek (in-process TestClient).

Needs DEEPSEEK_API_KEY in .env.  Run:  python scripts/smoke_api.py
On CN-Windows, run with:  $env:PYTHONIOENCODING="utf-8"; python scripts/smoke_api.py
"""
from dotenv import load_dotenv
from fastapi.testclient import TestClient

from arbiter.api.main import app

load_dotenv()

COMMENTS = ["Have a great day, everyone!", "You are an absolute idiot and I hate you."]


def main():
    with TestClient(app) as client:   # `with` triggers lifespan -> builds the real graph
        print("health:", client.get("/api/health").json())
        for c in COMMENTS:
            # 🔨 TODO: r = client.post("/api/moderate", json={"comment": c})
            #          print c and r.json()["action"] / ["overall_severity"] / ["categories"]
            ...


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 🔨 fill the glue** (the POST + prints).

- [ ] **Step 3: run it** (needs `DEEPSEEK_API_KEY`)
```
.\.venv\Scripts\python.exe scripts/smoke_api.py
```
Expected: `health: {'status': 'ok'}`, then per comment a printed action + severity. A local `arbiter.db` SQLite file appears (gitignored).

- [ ] **Step 4: Commit** *(you run)*
```
git add scripts/smoke_api.py
git commit -m "feat(api): in-process HTTP smoke on DeepSeek"
```

---

## Definition of done (this plan)
- `.\.venv\Scripts\python.exe -m pytest tests/api -v` fully green (9 tests, no network).
- `.\.venv\Scripts\python.exe -m pytest -q` → full suite (65 + 9 = **74**) green.
- `scripts/smoke_api.py` returns real verdicts over HTTP and writes a row to SQLite.

## Next increments (NOT this plan)
- **P5b — Next.js + Tailwind frontend** (spec §13): textarea → verdict card (action badge + per-category rows + span highlight + flag chips) → calls `POST /api/moderate`.
- **P5c — deploy**: Vercel (frontend) + Railway/Render (backend + Postgres); set `DATABASE_URL` + `DEEPSEEK_API_KEY`; add `psycopg[binary]`. Live demo URL.
- (optional) `GET /api/history` for a dashboard; CORS middleware for the deployed frontend origin.
```
