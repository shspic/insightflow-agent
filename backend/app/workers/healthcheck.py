from datetime import datetime, timedelta

from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.operations import WorkerStatus


def main() -> int:
    stale_after = datetime.utcnow() - timedelta(
        seconds=max(1, settings.worker_stale_seconds)
    )
    with SessionLocal() as db:
        worker = db.scalar(
            select(WorkerStatus).order_by(WorkerStatus.last_heartbeat_at.desc())
        )
    if worker is None or worker.last_heartbeat_at < stale_after:
        print("Worker 心跳过期或不存在")
        return 1
    print(f"Worker 心跳正常：worker_id={worker.worker_id} status={worker.status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
