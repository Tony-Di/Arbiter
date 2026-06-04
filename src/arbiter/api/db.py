"""SQLAlchemy persistence — product runtime only (spec §11).

DATABASE_URL: default local SQLite (zero setup); prod sets postgresql+psycopg://...
make_engine handles the SQLite threading + in-memory-sharing gotchas for you.

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
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


# Module-level engine/session for the running app (tests build their own).
engine = make_engine()
SessionLocal = make_session_factory(engine)


def init_db():
    Base.metadata.create_all(engine)


def save_verdict(db, comment: str, state: dict) -> "Submission":
    sub = Submission(comment_text=comment)
    db.add(sub)
    db.flush()
    v = Verdict(submission_id=sub.id, overall_severity=state["overall_severity"], action=state["action"], raw_verdicts=state["raw_verdicts"], context_flags=state["context_flags"], effective_verdicts=state["effective_verdicts"], routing_snapshot=state["routing_snapshot"])
    db.add(v)
    db.commit()
    db.refresh(sub)
    return sub
