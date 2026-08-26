from __future__ import annotations

import json


def test_project_analysis_executes_exactly_one_large_model_call() -> None:
    from test_project_analysis_prompt import _route, _state

    from libs.project_analysis.execution import execute_project_analysis_model
    from libs.project_analysis.prompt import (
        build_project_analysis_snapshot,
        project_analysis_preview,
    )

    state = _state()
    state.update(
        {
            "project_analysis_snapshots": [],
            "project_analysis_runs": [],
            "project_analysis_events": [],
            "model_call_attempts": [],
        }
    )
    route = _route()
    preview = project_analysis_preview(state, "P-1", model_route=route)
    snapshot = build_project_analysis_snapshot(
        state,
        "P-1",
        business_pack_id="engineering_inspection_v1",
        prompt_version="project-monolithic-analysis@1.0.0",
        model_route=route,
    )
    state["project_analysis_snapshots"].append(snapshot)
    run = {
        "id": "PARUN-1",
        "projectAnalysisRunId": "PARUN-1",
        "projectAnalysisSnapshotId": snapshot["projectAnalysisSnapshotId"],
        "tenantId": "TENANT-1",
        "projectId": "P-1",
        "phase": "queued",
        "status": "queued",
        "includedNodeCount": 2,
        "uniqueFileCount": 2,
        "fileReferenceCount": 3,
        "estimatedInputTokens": preview["estimatedInputTokens"],
        "modelAlias": "project-review-large",
        "revision": 1,
    }
    state["project_analysis_runs"].append(run)
    calls: list[dict] = []

    class FakeClient:
        def chat_sync(self, messages, **kwargs):
            calls.append({"messages": messages, **kwargs})
            return {
                "id": "RESP-PROJECT-1",
                "model": "qwen3.7-plus",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "schemaVersion": "AIAllReviewResult@2.0.0",
                                    "projectId": "P-1",
                                    "projectCode": "P-1",
                                    "projectName": "单体分析测试工程",
                                    "nodeReviews": [],
                                    "projectSummary": {},
                                    "disclaimer": "以上内容仅作为监检审查提示，不替代最终人工结论。",
                                },
                                ensure_ascii=False,
                            )
                        },
                    }
                ],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 100},
            }

    result = execute_project_analysis_model(state, "PARUN-1", client=FakeClient())

    assert len(calls) == 1
    assert calls[0]["model"] == "project-review-large"
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert result["phase"] == "validating_output"
    assert result["lastHeartbeatAt"]
    assert result["modelAttemptId"]
    assert result["rawModelOutput"]
    attempt = state["model_call_attempts"][0]
    assert attempt["callKind"] == "project_analysis"
    assert attempt["status"] == "success"
    assert attempt["promptHash"].startswith("sha256:")
    assert attempt["responseHash"].startswith("sha256:")
    assert attempt["usageNormalized"]["totalTokens"] == 1100


def test_completed_model_attempt_is_not_called_twice() -> None:
    from libs.project_analysis.execution import execute_project_analysis_model

    state = {
        "project_analysis_runs": [
            {
                "projectAnalysisRunId": "PARUN-1",
                "phase": "validating_output",
                "modelAttemptId": "MCALL-1",
            }
        ],
        "model_call_attempts": [{"id": "MCALL-1", "status": "success"}],
    }

    class ExplodingClient:
        def chat_sync(self, *_args, **_kwargs):
            raise AssertionError("completed project analysis must not call model twice")

    result = execute_project_analysis_model(state, "PARUN-1", client=ExplodingClient())
    assert result["modelAttemptId"] == "MCALL-1"
