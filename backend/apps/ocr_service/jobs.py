from __future__ import annotations

from copy import deepcopy
from threading import Lock
from typing import Any
from uuid import uuid4

from libs.contracts.responses import server_time


class DocumentParseJobStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._results: dict[str, dict[str, Any]] = {}

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = server_time()
        job = {
            "jobId": f"OCRJOB-{uuid4().hex[:12].upper()}",
            "status": "queued",
            "tenantId": payload.get("tenantId"),
            "projectId": payload.get("projectId"),
            "documentId": payload.get("documentId"),
            "documentVersionId": payload.get("documentVersionId"),
            "businessPackId": payload.get("businessPackId"),
            "documentType": payload.get("documentType"),
            "profileId": payload.get("profileId"),
            "storageKey": payload.get("storageKey"),
            "fileName": payload.get("fileName"),
            "options": payload.get("options") or {},
            "engineRuns": [],
            "diagnostics": [],
            "createdAt": now,
            "updatedAt": now,
            "startedAt": None,
            "finishedAt": None,
            "parseResultId": None,
            "parentJobId": payload.get("parentJobId"),
            "retryOfJobId": payload.get("retryOfJobId"),
        }
        with self._lock:
            self._jobs[job["jobId"]] = job
        return deepcopy(job)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return deepcopy(job) if job else None

    def get_result(self, result_id: str) -> dict[str, Any] | None:
        with self._lock:
            result = self._results.get(result_id)
            return deepcopy(result) if result else None

    def mark_running(self, job_id: str) -> dict[str, Any] | None:
        now = server_time()
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            job["status"] = "running"
            job["startedAt"] = job.get("startedAt") or now
            job["updatedAt"] = now
            return deepcopy(job)

    def mark_finished(self, job_id: str, result: dict[str, Any]) -> dict[str, Any] | None:
        now = server_time()
        result_id = result.get("parseResultId") or f"PARSE-{uuid4().hex[:12].upper()}"
        result["parseResultId"] = result_id
        result["finishedAt"] = result.get("finishedAt") or now
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            self._results[result_id] = deepcopy(result)
            job["status"] = "success" if result.get("status") == "success" else "failed"
            job["parseResultId"] = result_id
            job["finishedAt"] = now
            job["updatedAt"] = now
            job["engineRuns"] = result.get("engineRuns") or []
            job["diagnostics"] = result.get("diagnostics") or []
            return deepcopy(job)

    def retry_payload(self, job_id: str) -> dict[str, Any] | None:
        job = self.get_job(job_id)
        if not job:
            return None
        return {
            "tenantId": job.get("tenantId"),
            "projectId": job.get("projectId"),
            "documentId": job.get("documentId"),
            "documentVersionId": job.get("documentVersionId"),
            "businessPackId": job.get("businessPackId"),
            "documentType": job.get("documentType"),
            "profileId": job.get("profileId"),
            "storageKey": job.get("storageKey"),
            "fileName": job.get("fileName"),
            "options": job.get("options") or {},
            "retryOfJobId": job_id,
            "parentJobId": job.get("parentJobId") or job_id,
        }
