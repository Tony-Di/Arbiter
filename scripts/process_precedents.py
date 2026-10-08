"""Process up to 10 due local embedding jobs; the app also retries every 5 seconds."""
import json

from arbiter.api.db import PrecedentOutbox, SessionLocal, init_db
from arbiter.api.outbox import drain_outbox
from arbiter.precedents import PrecedentStore


if __name__ == "__main__":
    init_db()
    result = drain_outbox(SessionLocal, PrecedentStore(SessionLocal))
    with SessionLocal() as db:
        result["pending"] = db.query(PrecedentOutbox).filter_by(status="pending").count()
        result["processing"] = db.query(PrecedentOutbox).filter_by(status="processing").count()
    print(json.dumps(result))
