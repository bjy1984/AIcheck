from __future__ import annotations

import json


def test_prepare_persists_queued_phase_before_dispatching_model(monkeypatch) -> None:
    from apps.worker import tasks

    run = {
        "projectAnalysisRunId": "PARUN-ORDER",
        "phase": "preparing_snapshot",
        "status": "preparing_snapshot",
        "includedNodeCount": 2,
        "uniqueFileCount": 1,
    }
    calls: list[str] = []

    monkeypatch.setattr(tasks, "load_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tasks, "_project_analysis_run", lambda _run_id: run)

    def advance(_state, current, phase, **updates):
        current.update(updates)
        current["phase"] = phase
        current["status"] = phase
        return current

    monkeypatch.setattr(tasks, "advance_project_analysis_phase", advance)
    monkeypatch.setattr(tasks, "flush_state", lambda *_args, **_kwargs: calls.append("flush"))

    def dispatch(_task_name: str, _run_id: str, *, task_id: str | None = None) -> dict:
        calls.append("dispatch")
        return {"mode": "celery", "taskId": task_id or "TASK-MODEL"}

    monkeypatch.setattr(tasks, "_dispatch_project_analysis_task", dispatch)

    tasks.project_analysis_prepare.run("PARUN-ORDER")

    assert calls[:2] == ["flush", "dispatch"]
    assert run["phase"] == "queued"
    assert run["queueTaskId"] == "TASK-MODEL"


def test_project_analysis_executes_exactly_one_large_model_call(monkeypatch) -> None:
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
    snapshot["request"] = preview["request"]
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
        "maxContextTokens": 131072,
        "reservedOutputTokens": 24000,
        "modelAlias": "project-review-large",
        "revision": 1,
    }
    state["project_analysis_runs"].append(run)
    calls: list[dict] = []
    monkeypatch.setenv("AICHECK_PROJECT_ANALYSIS_MODEL_TIMEOUT_SECONDS", "420")
    monkeypatch.setenv("AICHECK_PROJECT_ANALYSIS_MAX_OUTPUT_TOKENS", "48000")

    class FakeClient:
        def chat_sync(self, messages, **kwargs):
            calls.append({"messages": messages, **kwargs})
            kwargs["stream_handler"]("reasoning", "delta")
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
    assert calls[0]["timeout"] == 420
    assert callable(calls[0]["stream_handler"])
    assert calls[0]["max_tokens"] == 48000
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


def test_model_execution_uses_persisted_snapshot_request_after_live_ocr_changes() -> None:
    from test_project_analysis_prompt import _route, _state

    from libs.project_analysis.execution import execute_project_analysis_model
    from libs.project_analysis.prompt import project_analysis_preview

    state = _state()
    state.update(
        {
            "project_analysis_snapshots": [],
            "project_analysis_runs": [],
            "project_analysis_events": [],
            "model_call_attempts": [],
        }
    )
    preview = project_analysis_preview(state, "P-1", model_route=_route())
    snapshot = {**preview["snapshot"], "request": preview["request"]}
    state["project_analysis_snapshots"].append(snapshot)
    state["project_analysis_runs"].append(
        {
            "projectAnalysisRunId": "PARUN-FROZEN",
            "projectAnalysisSnapshotId": snapshot["projectAnalysisSnapshotId"],
            "tenantId": "TENANT-1",
            "projectId": "P-1",
            "phase": "queued",
            "status": "queued",
            "modelAlias": "project-review-large",
            "reservedOutputTokens": 24000,
            "revision": 1,
        }
    )
    state["ocr_parse_results"][1]["fragments"][0]["text"] = "运行开始后的 OCR 变化"
    calls: list[list[dict]] = []

    class FakeClient:
        def chat_sync(self, messages, **_kwargs):
            calls.append(messages)
            return {
                "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}],
                "usage": {},
            }

    execute_project_analysis_model(state, "PARUN-FROZEN", client=FakeClient())

    prompt = calls[0][1]["content"]
    assert "许可证编号 | TS-001" in prompt
    assert "运行开始后的 OCR 变化" not in prompt


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


def test_model_running_phase_is_persisted_before_the_model_call(monkeypatch) -> None:
    """model_running 必须在调用模型前落库。

    实测：模型调用 220 秒，DB 全程停在 queued，前端分不清排队和执行。
    同时覆盖重试路径：相位已是 model_running 时不再原地推进（相位校验
    不允许 model_running → model_running），补心跳即可。
    """
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
    snapshot["request"] = preview["request"]
    state["project_analysis_snapshots"].append(snapshot)
    run = {
        "id": "PARUN-VIS",
        "projectAnalysisRunId": "PARUN-VIS",
        "projectAnalysisSnapshotId": snapshot["projectAnalysisSnapshotId"],
        "tenantId": "TENANT-1",
        "projectId": "P-1",
        "phase": "queued",
        "status": "queued",
        "estimatedInputTokens": preview["estimatedInputTokens"],
        "maxContextTokens": 131072,
        "reservedOutputTokens": 24000,
        "modelAlias": "project-review-large",
        "revision": 1,
    }
    state["project_analysis_runs"].append(run)
    phase_seen_by_flush: list[str] = []

    class FakeClient:
        def chat_sync(self, messages, **kwargs):
            # 断言在模型调用发生时，落库回调已经带着 model_running 执行过
            assert phase_seen_by_flush == ["model_running"]
            return {
                "id": "RESP-VIS",
                "model": "deepseek-v4-pro",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"nodeReviews": []}'},
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            }

    execute_project_analysis_model(
        state,
        "PARUN-VIS",
        client=FakeClient(),
        on_model_running=lambda: phase_seen_by_flush.append(str(run["phase"])),
    )
    assert run["phase"] == "validating_output"

    # 重试路径：DB 已是 model_running（上一跳落库后崩溃/超时），不得抛相位错误
    run.update({"phase": "model_running", "status": "model_running", "modelAttemptId": None})
    run.pop("rawModelOutput", None)
    phase_seen_by_flush.clear()
    execute_project_analysis_model(
        state,
        "PARUN-VIS",
        client=FakeClient(),
        on_model_running=lambda: phase_seen_by_flush.append(str(run["phase"])),
    )
    assert run["phase"] == "validating_output"


def test_streaming_model_call_emits_heartbeats(monkeypatch) -> None:
    """流式调用期间要打心跳，否则 15 分钟无活动就被收敛器当僵尸落 failed（2026-09-03 险些）。"""
    from test_project_analysis_prompt import _route, _state

    from libs.project_analysis.execution import execute_project_analysis_model
    from libs.project_analysis.prompt import build_project_analysis_snapshot, project_analysis_preview

    state = _state()
    state.update({"project_analysis_snapshots": [], "project_analysis_runs": [], "project_analysis_events": [], "model_call_attempts": []})
    route = _route()
    preview = project_analysis_preview(state, "P-1", model_route=route)
    snapshot = build_project_analysis_snapshot(
        state, "P-1", business_pack_id="engineering_inspection_v1", prompt_version="project-monolithic-analysis@1.0.0", model_route=route
    )
    snapshot["request"] = preview["request"]
    state["project_analysis_snapshots"].append(snapshot)
    run = {
        "id": "PARUN-HB", "projectAnalysisRunId": "PARUN-HB", "projectAnalysisSnapshotId": snapshot["projectAnalysisSnapshotId"],
        "tenantId": "TENANT-1", "projectId": "P-1", "phase": "queued", "status": "queued", "includedNodeCount": 2,
        "uniqueFileCount": 2, "fileReferenceCount": 3, "estimatedInputTokens": preview["estimatedInputTokens"],
        "maxContextTokens": 131072, "reservedOutputTokens": 24000, "modelAlias": "project-review-large", "revision": 1,
    }
    state["project_analysis_runs"].append(run)
    beats: list[str] = []

    class FakeClient:
        def chat_sync(self, messages, **kwargs):
            for _ in range(3):
                kwargs["stream_handler"]("content", "chunk")
            return {"id": "RESP-HB", "model": "qwen3.8-max", "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}], "usage": {}}

    execute_project_analysis_model(
        state, "PARUN-HB", client=FakeClient(),
        on_heartbeat=lambda current: beats.append(current["lastHeartbeatAt"]),
        heartbeat_interval_seconds=0,
    )
    assert len(beats) == 3, "每块到点都应打一次心跳（间隔 0 时每块一次）"
    assert run["lastHeartbeatAt"] == beats[-1]
