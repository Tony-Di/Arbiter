"""Leased, idempotent embedding delivery; failures never undo human rulings."""
import asyncio
import logging
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import and_, or_, update

from arbiter.api.db import Precedent, PrecedentOutbox
from arbiter.api.reviews import utcnow

logger = logging.getLogger(__name__)


def _ready(now):
    return or_(
        and_(PrecedentOutbox.status == "pending", or_(PrecedentOutbox.next_attempt_at.is_(None),
                                                       PrecedentOutbox.next_attempt_at <= now)),
        and_(PrecedentOutbox.status == "processing", PrecedentOutbox.lease_until <= now),
    )


def drain_outbox(sessions, store, *, limit=10):
    counts = {"completed": 0, "failed": 0}
    for _ in range(limit):
        now, token = utcnow(), str(uuid4())
        with sessions() as db:
            item = db.query(PrecedentOutbox).filter(_ready(now)).order_by(PrecedentOutbox.id).first()
            if item is None:
                break
            item_id, case_id, payload = item.id, item.case_id, item.payload
            claimed = db.execute(update(PrecedentOutbox).where(PrecedentOutbox.id == item_id, _ready(now))
                                 .values(status="processing", lease_token=token,
                                         lease_until=now + timedelta(seconds=120),
                                         attempts=PrecedentOutbox.attempts + 1))
            db.commit()
            if claimed.rowcount != 1:
                continue
        try:
            embedding = store.embed_for_index(payload["comment_text"])
            with sessions() as db:
                finished = db.execute(update(PrecedentOutbox).where(
                    PrecedentOutbox.id == item_id, PrecedentOutbox.lease_token == token,
                ).values(status="done", lease_token=None, lease_until=None, last_error=None,
                         next_attempt_at=None))
                if finished.rowcount != 1:
                    db.rollback()
                    continue
                if db.query(Precedent).filter_by(review_case_id=case_id).first() is None:
                    if payload["source"] != "human":
                        raise ValueError("Only human decisions may be indexed")
                    db.add(Precedent(**payload, embedding=embedding, review_case_id=case_id))
                db.commit()
                counts["completed"] += 1
        except Exception as exc:
            with sessions() as db:
                item = db.query(PrecedentOutbox).filter_by(id=item_id, lease_token=token).first()
                if item is not None:
                    item.status, item.lease_token, item.lease_until = "pending", None, None
                    # Keep error type only: provider messages can contain sensitive data.
                    item.last_error = type(exc).__name__
                    item.next_attempt_at = utcnow() + timedelta(seconds=min(3600, 5 * 2 ** min(item.attempts, 9)))
                    db.commit()
            counts["failed"] += 1
    return counts


async def run_outbox_worker(sessions, store, stop: asyncio.Event):
    while not stop.is_set():
        try:
            await asyncio.to_thread(drain_outbox, sessions, store, limit=1)
        except Exception:
            logger.exception("Local precedent worker failed; retrying")
        try:
            await asyncio.wait_for(stop.wait(), timeout=5)
        except TimeoutError:
            pass
