from __future__ import annotations

import logging
import os
import socket
import threading
from typing import Any

from apps.mineru_worker.queue import (
    ClaimedKnowledgeTask,
    ClaimedMinerUJob,
    claim_knowledge_tasks,
    claim_jobs,
    fail_knowledge_claim,
    finish_knowledge_claim,
    finish_claim,
    reschedule_knowledge_claim,
    reschedule_claim,
    write_heartbeat,
)
from apps.worker.tasks import (
    MinerUPostgresRetry,
    execute_mineru_postgres_job,
    execute_postgres_knowledge_task,
)


logger = logging.getLogger(__name__)


class MinerUPostgresWorker:
    def __init__(
        self,
        dsn: str,
        *,
        worker_id: str | None = None,
        batch_size: int = 1,
        lease_seconds: int = 120,
        poll_seconds: float = 1.0,
    ) -> None:
        self.dsn = dsn
        self.worker_id = worker_id or f"{socket.gethostname()}-{os.getpid()}"
        self.batch_size = max(1, min(int(batch_size), 20))
        self.lease_seconds = max(5, int(lease_seconds))
        self.poll_seconds = max(0.1, float(poll_seconds))
        self.stop_event = threading.Event()
        self.last_error: str | None = None

    def heartbeat(self, *, active_count: int) -> None:
        write_heartbeat(
            self.dsn,
            self.worker_id,
            {
                "activeCount": max(0, int(active_count)),
                "batchSize": self.batch_size,
                "leaseSeconds": self.lease_seconds,
                "lastError": self.last_error,
            },
        )

    def run_once(self) -> int:
        claims = claim_jobs(
            self.dsn,
            self.worker_id,
            limit=self.batch_size,
            lease_seconds=self.lease_seconds,
        )
        if not claims:
            knowledge_claims = claim_knowledge_tasks(
                self.dsn,
                self.worker_id,
                limit=self.batch_size,
                lease_seconds=self.lease_seconds,
            )
            if not knowledge_claims:
                self.last_error = None
                self.heartbeat(active_count=0)
                return 0
            return self._execute_knowledge_claims(knowledge_claims)
        active_count = len(claims)
        self.heartbeat(active_count=active_count)
        for claim in claims:
            try:
                self._execute(claim)
                self.last_error = None
            except Exception as exc:
                self.last_error = type(exc).__name__
                self.heartbeat(active_count=active_count)
                raise
            finally:
                active_count -= 1
                self.heartbeat(active_count=active_count)
        return len(claims)

    def _execute_knowledge_claims(
        self,
        claims: list[ClaimedKnowledgeTask],
    ) -> int:
        active_count = len(claims)
        self.heartbeat(active_count=active_count)
        for claim in claims:
            try:
                execute_postgres_knowledge_task(
                    claim.task_type,
                    claim.target_id,
                    tenant_id=claim.tenant_id,
                )
                finish_knowledge_claim(self.dsn, claim)
                self.last_error = None
            except Exception as exc:  # noqa: BLE001 - durable worker retry boundary
                delay = (10, 30, 90)[min(claim.attempts, 2)]
                self.last_error = type(exc).__name__
                if claim.attempts >= 3:
                    fail_knowledge_claim(
                        self.dsn,
                        claim,
                        error_message=self.last_error,
                    )
                else:
                    reschedule_knowledge_claim(
                        self.dsn,
                        claim,
                        error_message=self.last_error,
                        delay_seconds=delay,
                    )
            finally:
                active_count -= 1
                self.heartbeat(active_count=active_count)
        return len(claims)

    def _execute(self, claim: ClaimedMinerUJob) -> dict[str, Any] | None:
        try:
            result = execute_mineru_postgres_job(
                claim.job_id,
                tenant_id=claim.tenant_id,
                retry_index=claim.attempts,
            )
        except MinerUPostgresRetry as retry:
            reschedule_claim(
                self.dsn,
                claim,
                diagnostics=retry.diagnostics,
                delay_seconds=retry.countdown,
            )
            self.last_error = str(
                (retry.diagnostics[0] if retry.diagnostics else {}).get("code")
                or "MINERU_RETRY"
            )
            return None
        finish_claim(self.dsn, claim)
        return result

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                processed = self.run_once()
            except Exception:
                logger.exception("MinerU worker iteration failed")
                processed = 0
            if processed == 0:
                self.stop_event.wait(self.poll_seconds)

    def stop(self) -> None:
        self.stop_event.set()
