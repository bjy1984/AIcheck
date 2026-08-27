from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from libs.db.seed import PROJECT_ID
from libs.security.auth import SHARED_TEST_PASSWORD

HUMAN_REVIEW_STATUSES = {"waiting_human_review", "accepted_by_human", "edited_by_human", "rejected_by_human"}
REQUIRED_SCORECARD_SECTIONS = {"workflow", "graph", "evidence", "governance"}


class ProbeFailure(RuntimeError):
    def __init__(self, message: str, *, data: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.data = data or {}


@dataclass(frozen=True)
class ProbeConfig:
    api_base: str
    project_id: str
    node_id: int
    wait_seconds: float
    poll_seconds: float
    timeout_seconds: float
    decision: str


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify local ReviewRun orchestration reaches a real 100/100 scorecard.")
    parser.add_argument("--api-base", default=os.getenv("AICHECK_API_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--project-id", default=os.getenv("AICHECK_DEFAULT_PROJECT_ID", PROJECT_ID))
    parser.add_argument("--node-id", type=int, default=int(os.getenv("AICHECK_REVIEW_100_NODE_ID", "24")))
    parser.add_argument("--wait-seconds", type=float, default=float(os.getenv("AICHECK_REVIEW_100_WAIT_SECONDS", "60")))
    parser.add_argument("--poll-seconds", type=float, default=float(os.getenv("AICHECK_REVIEW_100_POLL_SECONDS", "2")))
    parser.add_argument("--timeout", type=float, default=float(os.getenv("AICHECK_REVIEW_100_HTTP_TIMEOUT", "10")))
    parser.add_argument("--decision", default="accept", choices=["accept", "edit", "reject"])
    parser.add_argument("--json", action="store_true", help="Print the full probe report as JSON.")
    args = parser.parse_args()

    config = ProbeConfig(
        api_base=args.api_base.rstrip("/"),
        project_id=args.project_id,
        node_id=args.node_id,
        wait_seconds=max(1.0, float(args.wait_seconds)),
        poll_seconds=max(0.2, float(args.poll_seconds)),
        timeout_seconds=max(1.0, float(args.timeout)),
        decision=args.decision,
    )
    try:
        with httpx.Client(base_url=config.api_base, timeout=config.timeout_seconds) as client:
            report = ReviewOrchestration100Probe(client, config).run()
    except ProbeFailure as exc:
        payload = {"ok": False, "error": str(exc), "data": exc.data}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(report if args.json else report["summary"], ensure_ascii=False, indent=2))
    return 0


class ReviewOrchestration100Probe:
    def __init__(self, client: httpx.Client, config: ProbeConfig) -> None:
        self.client = client
        self.config = config
        self.tokens: dict[str, str] = {}

    def run(self) -> dict[str, Any]:
        self.tokens["inspection"] = self.login("inspection")
        self.tokens["fde"] = self.login("fde")
        suffix = uuid4().hex[:8]
        created = self.request_envelope(
            "POST",
            f"/api/projects/{self.config.project_id}/inspection/nodes/{self.config.node_id}/ai-recheck",
            role="inspection",
            headers={"Idempotency-Key": f"review100-create-{suffix}"},
        )
        dispatch = created.get("dispatch") if isinstance(created.get("dispatch"), dict) else {}
        review_run_id = str(dispatch.get("reviewRunId") or "")
        if not review_run_id:
            raise ProbeFailure("ai-recheck did not return dispatch.reviewRunId", data={"created": created})
        if dispatch.get("mode") != "temporal":
            raise ProbeFailure("ReviewRun 100 requires Temporal dispatch.", data={"dispatch": dispatch})
        if dispatch.get("status") in {"failed_to_start", "missing"}:
            raise ProbeFailure("Temporal workflow failed to start.", data={"dispatch": dispatch})

        snapshot = self.wait_for_scorecard(review_run_id)
        decision = self.request_envelope(
            "POST",
            f"/api/review-runs/{review_run_id}/human-decision",
            role="inspection",
            headers={"Idempotency-Key": f"review100-decision-{suffix}"},
            json={"decision": self.config.decision, "comment": "review orchestration 100 probe human confirmation"},
        )
        decision_run = decision.get("reviewRun") if isinstance(decision.get("reviewRun"), dict) else {}
        if decision_run.get("status") not in {"accepted_by_human", "edited_by_human", "rejected_by_human"}:
            raise ProbeFailure("Human decision did not move ReviewRun into a human decision state.", data={"decision": decision})
        temporal_signal = decision.get("temporalSignal") if isinstance(decision.get("temporalSignal"), dict) else {}
        if temporal_signal.get("status") != "sent":
            raise ProbeFailure("Human decision was not sent to Temporal workflow.", data={"temporalSignal": temporal_signal})

        final_fde = self.request_envelope("GET", f"/api/fde/review-runs/{review_run_id}", role="fde")
        self.assert_scorecard_100(final_fde, review_run_id=review_run_id)
        summary = {
            "ok": True,
            "reviewRunId": review_run_id,
            "dispatchMode": dispatch.get("mode"),
            "workflowEngine": final_fde.get("run", {}).get("workflowEngine"),
            "graphEngine": final_fde.get("run", {}).get("graphEngine"),
            "graphRunner": final_fde.get("run", {}).get("graphRunner"),
            "checkpointer": (final_fde.get("run", {}).get("graphExecution") or {}).get("checkpointer"),
            "scorecardScore": final_fde.get("scorecard", {}).get("score"),
            "scorecardOk": final_fde.get("scorecard", {}).get("ok"),
            "humanDecisionStatus": decision_run.get("status"),
            "temporalSignalStatus": temporal_signal.get("status"),
        }
        return {
            "schemaVersion": "aicheck-review-orchestration-100-probe-v1",
            "summary": summary,
            "initialScorecard": snapshot.get("fde", {}).get("scorecard"),
            "finalScorecard": final_fde.get("scorecard"),
        }

    def login(self, role: str) -> str:
        response = self.client.post(
            "/api/auth/login",
            json={"username": role, "password": role_password(role)},
        )
        payload = response_json(response)
        if response.status_code != 200 or not isinstance(payload, dict) or payload.get("code") != 0:
            raise ProbeFailure(f"Login failed for role {role}.", data={"status": response.status_code, "payload": payload})
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        token = data.get("token")
        if not token:
            raise ProbeFailure(f"Login for role {role} did not return a token.", data={"payload": payload})
        return str(token)

    def wait_for_scorecard(self, review_run_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.config.wait_seconds
        latest: dict[str, Any] = {}
        while True:
            detail = self.request_envelope("GET", f"/api/review-runs/{review_run_id}", role="inspection")
            graph = self.request_envelope("GET", f"/api/review-runs/{review_run_id}/graph", role="inspection")
            timeline = self.request_envelope("GET", f"/api/review-runs/{review_run_id}/timeline", role="inspection")
            fde = self.request_envelope("GET", f"/api/fde/review-runs/{review_run_id}", role="fde")
            latest = {"detail": detail, "graph": graph, "timeline": timeline, "fde": fde}
            try:
                self.assert_runtime_shape(detail, graph, timeline, fde, review_run_id=review_run_id)
                self.assert_scorecard_100(fde, review_run_id=review_run_id)
                return latest
            except ProbeFailure as exc:
                if time.monotonic() >= deadline:
                    raise ProbeFailure(
                        f"ReviewRun did not reach local orchestration 100 within {self.config.wait_seconds:g}s: {exc}",
                        data={"last": latest, "failure": exc.data},
                    ) from exc
            time.sleep(min(self.config.poll_seconds, max(0.0, deadline - time.monotonic())))

    def assert_runtime_shape(
        self,
        detail: dict[str, Any],
        graph: dict[str, Any],
        timeline: dict[str, Any],
        fde: dict[str, Any],
        *,
        review_run_id: str,
    ) -> None:
        run = detail.get("run") if isinstance(detail.get("run"), dict) else {}
        if run.get("reviewRunId") != review_run_id:
            raise ProbeFailure("ReviewRun detail id mismatch.", data={"run": run})
        if run.get("workflowEngine") != "temporal":
            raise ProbeFailure("ReviewRun workflowEngine must be temporal.", data={"workflowEngine": run.get("workflowEngine")})
        if run.get("graphEngine") != "langgraph":
            raise ProbeFailure("ReviewRun graphEngine must be langgraph.", data={"graphEngine": run.get("graphEngine")})
        if run.get("graphRunner") != "langgraph":
            raise ProbeFailure("ReviewRun graphRunner must be langgraph.", data={"graphRunner": run.get("graphRunner")})
        if (run.get("graphExecution") or {}).get("checkpointer") != "postgres":
            raise ProbeFailure("LangGraph Postgres checkpointer must be active.", data={"graphExecution": run.get("graphExecution")})
        if run.get("modelGateway") != "qwen_runtime":
            raise ProbeFailure("ReviewRun modelGateway must be qwen_runtime.", data={"modelGateway": run.get("modelGateway")})
        if run.get("status") not in HUMAN_REVIEW_STATUSES:
            raise ProbeFailure("ReviewRun has not reached a human-review state.", data={"status": run.get("status")})
        nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
        edges = graph.get("edges") if isinstance(graph.get("edges"), list) else []
        if not nodes or any(not isinstance(node, dict) or node.get("status") != "succeeded" for node in nodes):
            raise ProbeFailure("All ReviewRun graph nodes must be succeeded.", data={"nodeStatuses": [node.get("status") for node in nodes if isinstance(node, dict)]})
        if len(edges) < max(0, len(nodes) - 1):
            raise ProbeFailure("ReviewRun graph edges are incomplete.", data={"nodeCount": len(nodes), "edgeCount": len(edges)})
        if not isinstance(timeline.get("events"), list) or not timeline["events"]:
            raise ProbeFailure("ReviewRun timeline returned no events.", data={"timeline": timeline})
        temporal = fde.get("temporal") if isinstance(fde.get("temporal"), dict) else {}
        if temporal.get("workflowType") != "ReviewRunWorkflow" or temporal.get("workflowEngine") != "temporal":
            raise ProbeFailure("FDE temporal summary is not a real ReviewRunWorkflow.", data={"temporal": temporal})
        if temporal.get("historyPolicy") != "ids_hashes_versions_only" or temporal.get("payloadCodecRequired") is not True:
            raise ProbeFailure("Temporal payload/history policy is not strict.", data={"temporal": temporal})

    def assert_scorecard_100(self, fde_detail: dict[str, Any], *, review_run_id: str) -> None:
        scorecard = fde_detail.get("scorecard") if isinstance(fde_detail.get("scorecard"), dict) else {}
        section_names = {str(item.get("name")) for item in scorecard.get("sections") or [] if isinstance(item, dict)}
        if REQUIRED_SCORECARD_SECTIONS - section_names:
            raise ProbeFailure("FDE scorecard is missing required sections.", data={"scorecard": scorecard})
        if scorecard.get("targetScore") != 100 or scorecard.get("ok") is not True or float(scorecard.get("score") or 0) < 100:
            raise ProbeFailure("FDE orchestration scorecard is not 100/100.", data={"reviewRunId": review_run_id, "scorecard": scorecard})
        if scorecard.get("blockers"):
            raise ProbeFailure("FDE orchestration scorecard still has blockers.", data={"reviewRunId": review_run_id, "scorecard": scorecard})

    def request_envelope(self, method: str, path: str, *, role: str, **kwargs: Any) -> dict[str, Any]:
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.setdefault("Authorization", f"Bearer {self.tokens[role]}")
        response = self.client.request(method, path, headers=headers, **kwargs)
        payload = response_json(response)
        if response.status_code != 200 or not isinstance(payload, dict) or payload.get("code") != 0:
            raise ProbeFailure(f"{method} {path} returned an unexpected response.", data={"status": response.status_code, "payload": payload})
        data = payload.get("data")
        return data if isinstance(data, dict) else {}


def role_password(role: str) -> str:
    normalized = role.upper().replace("-", "_")
    return (
        os.getenv(f"AICHECK_VERIFY_PASSWORD_{normalized}")
        or os.getenv(f"AICHECK_BOOTSTRAP_PASSWORD_{normalized}")
        or SHARED_TEST_PASSWORD
    )


def response_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except Exception:
        return response.text


if __name__ == "__main__":
    raise SystemExit(main())
