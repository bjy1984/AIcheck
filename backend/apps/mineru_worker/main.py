from __future__ import annotations

import logging
import os
import signal

from apps.mineru_worker.worker import MinerUPostgresWorker


logger = logging.getLogger(__name__)


def database_url() -> str:
    dsn = str(
        os.getenv("AICHECK_DATABASE_URL")
        or os.getenv("DATABASE_URL")
        or ""
    ).strip()
    if not dsn:
        raise RuntimeError(
            "AICHECK_DATABASE_URL is required for the MinerU PostgreSQL worker."
        )
    return dsn


def build_worker() -> MinerUPostgresWorker:
    return MinerUPostgresWorker(
        database_url(),
        worker_id=os.getenv("AICHECK_MINERU_WORKER_ID"),
        batch_size=int(os.getenv("AICHECK_MINERU_WORKER_BATCH_SIZE", "1")),
        lease_seconds=int(os.getenv("AICHECK_MINERU_WORKER_LEASE_SECONDS", "120")),
        poll_seconds=float(os.getenv("AICHECK_MINERU_WORKER_POLL_SECONDS", "1")),
    )


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    worker = build_worker()
    logger.info(
        "MinerU PostgreSQL worker ready: instance_id=%s",
        worker.worker_id,
    )

    def stop_worker(_signum, _frame) -> None:
        worker.stop()

    signal.signal(signal.SIGINT, stop_worker)
    signal.signal(signal.SIGTERM, stop_worker)
    worker.run()


if __name__ == "__main__":
    main()
