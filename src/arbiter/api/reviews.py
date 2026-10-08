"""Recoverable bridge between LangGraph checkpoints and the application database.

The two SQLite databases cannot share a transaction. Persist the human choice
first, then resume the graph, then atomically save verdict + outbox + completion.
A retry recovers a completed checkpoint after a crash between those last steps.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException
from langgraph.types import Command
from sqlalchemy import or_, update

from arbiter.api.db import PrecedentOutbox, ReviewCase, save_verdict


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def resolve_case(db, graph, case_id: str, decision: dict) -> dict:
    case = db.query(ReviewCase).filter_by(case_id=case_id).first()
    if case is None:
        raise HTTPException(404, "Review case not found")
    if case.decision is not None and case.decision != decision:
        raise HTTPException(409, "A different human decision has already been submitted")
    if case.status == "resolved":
        if case.final_state is not None:
            return case.final_state
        raise HTTPException(409, "Case already resolved")
    if decision["action"] == "confirm" and case.recommendation["recommended_action"] not in {"allow", "remove"}:
        raise HTTPException(422, "Choose allow or remove to resolve a human-review recommendation")
    comment = case.comment_text
    now, token = utcnow(), str(uuid4())
    claimed = db.execute(update(ReviewCase).where(
        ReviewCase.case_id == case_id, ReviewCase.status == case.status,
        or_(ReviewCase.lease_until.is_(None), ReviewCase.lease_until <= now),
    ).values(status="resolving", decision=decision, lease_token=token,
             lease_until=now + timedelta(seconds=120)))
    if claimed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "This decision is being saved; retry shortly")
    db.commit()
    cfg = {"configurable": {"thread_id": case_id}}
    try:
        snapshot = graph.get_state(cfg)
        if not snapshot.values:
            raise RuntimeError("Review checkpoint is missing")
        final = snapshot.values
        if not (final.get("adjudication", {}).get("human") and not snapshot.next):
            final = graph.invoke(Command(resume=decision), config=cfg)
        if final.get("__interrupt__") or not final.get("adjudication", {}).get("human"):
            raise RuntimeError("Review checkpoint did not finish")
        # Exclude the working transcript; preserve raw/effective verdicts and audit.
        final = {k: v for k, v in final.items() if k not in {"adj_messages", "__interrupt__"}}
        # Fencing token prevents a worker whose lease expired from committing.
        completed = db.execute(update(ReviewCase).where(
            ReviewCase.case_id == case_id, ReviewCase.lease_token == token,
            ReviewCase.status == "resolving",
        ).values(status="resolved", resolved_at=utcnow(), final_state=final,
                 lease_token=None, lease_until=None))
        if completed.rowcount != 1:
            raise RuntimeError("Review lease was replaced; retry the saved decision")
        save_verdict(db, comment, final, commit=False)
        db.add(PrecedentOutbox(case_id=case_id, payload={
            "comment_text": comment, "action": final["action"],
            "overall_severity": final["overall_severity"],
            "note": decision.get("note") or final["adjudication"].get("note") or "Human ruling",
            "source": "human"}))
        db.commit()
        return final
    except Exception:
        db.rollback()
        db.execute(update(ReviewCase).where(ReviewCase.case_id == case_id,
                                           ReviewCase.lease_token == token)
                   .values(lease_token=None, lease_until=None))
        db.commit()
        raise
