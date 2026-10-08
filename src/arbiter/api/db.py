"""SQLAlchemy persistence — product runtime only (spec §11).

DATABASE_URL: default local SQLite (zero setup); prod sets postgresql+psycopg://...
make_engine handles the SQLite threading + in-memory-sharing gotchas for you.

Check:  python -m pytest tests/api/test_db.py -v   (goal: 2 passed)
"""
import os
from datetime import datetime

from dotenv import load_dotenv
from sqlalchemy import JSON, ForeignKey, create_engine, func, inspect, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

load_dotenv()
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
    id: Mapped[int] = mapped_column(primary_key=True)
    comment_text: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Verdict(Base):
    __tablename__ = "verdicts"
    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"))
    overall_severity: Mapped[int]
    action: Mapped[str]
    raw_verdicts: Mapped[dict] = mapped_column(JSON)
    context_flags: Mapped[dict] = mapped_column(JSON)
    effective_verdicts: Mapped[dict] = mapped_column(JSON)
    routing_snapshot: Mapped[dict] = mapped_column(JSON)
    escalated: Mapped[bool] = mapped_column(default=False)
    adjudication: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
    audit: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Precedent(Base):
    """A past HUMAN ruling, retrievable by the adjudicator (HITL spec 2026-06-09 §5).
    source is always "human" -- AI rulings never enter (contamination guard)."""
    __tablename__ = "precedents"
    id: Mapped[int] = mapped_column(primary_key=True)
    comment_text: Mapped[str]
    embedding: Mapped[list] = mapped_column(JSON)
    action: Mapped[str]
    overall_severity: Mapped[int]
    note: Mapped[str]
    source: Mapped[str] = mapped_column(default="human")
    review_case_id: Mapped[str | None] = mapped_column(nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ReviewCase(Base):
    """A paused (interrupted) moderation case awaiting a human ruling (HITL §7)."""
    __tablename__ = "review_cases"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(unique=True, index=True)   # graph thread_id
    comment_text: Mapped[str]
    recommendation: Mapped[dict] = mapped_column(JSON)              # interrupt payload
    status: Mapped[str] = mapped_column(default="pending")  # pending | resolving | resolved
    decision: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    final_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    lease_token: Mapped[str | None] = mapped_column(nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(nullable=True, default=None)


class PrecedentOutbox(Base):
    """Durable embedding work, inserted atomically with the human verdict."""
    __tablename__ = "precedent_outbox"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(unique=True)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(default="pending")
    attempts: Mapped[int] = mapped_column(default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(nullable=True)
    lease_token: Mapped[str | None] = mapped_column(nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(nullable=True)
    last_error: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


# Module-level engine/session for the running app (tests build their own).
engine = make_engine()
SessionLocal = make_session_factory(engine)


def init_db(bind=None):
    """Additive local migrations: retain existing cases, checkpoints and verdicts."""
    bind = bind if bind is not None else engine
    Base.metadata.create_all(bind)
    additions = {
        "verdicts": {"escalated": "BOOLEAN DEFAULT 0", "adjudication": "JSON", "audit": "JSON"},
        "precedents": {"review_case_id": "VARCHAR"},
        "review_cases": {"decision": "JSON", "final_state": "JSON", "lease_token": "VARCHAR", "lease_until": "TIMESTAMP"},
    }
    with bind.begin() as conn:
        for table, columns in additions.items():
            existing = {c["name"] for c in inspect(conn).get_columns(table)}
            for name, sql_type in columns.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_precedent_review_case ON precedents (review_case_id)"))


def save_verdict(db, comment: str, state: dict, *, commit: bool = True) -> "Submission":
    sub = Submission(comment_text=comment)
    db.add(sub)
    db.flush()
    v = Verdict(submission_id=sub.id, overall_severity=state["overall_severity"], action=state["action"], raw_verdicts=state["raw_verdicts"], context_flags=state["context_flags"], effective_verdicts=state["effective_verdicts"], routing_snapshot=state["routing_snapshot"], escalated=state.get("escalated", False), adjudication=state.get("adjudication"), audit=state.get("audit"))
    db.add(v)
    if commit:
        db.commit()
        db.refresh(sub)
    return sub
