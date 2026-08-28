from __future__ import annotations


def test_project_analysis_tasks_are_routed_by_phase() -> None:
    from apps.worker.celery_app import celery_app

    routes = dict(celery_app.conf.task_routes)

    assert routes["apps.worker.tasks.project_analysis_prepare"]["queue"] == "business.light"
    assert routes["apps.worker.tasks.project_analysis_execute_model"]["queue"] == "llm.remote"
    assert routes["apps.worker.tasks.project_analysis_validate_output"]["queue"] == "business.light"
    assert routes["apps.worker.tasks.project_analysis_persist_results"]["queue"] == "business.light"


def test_project_analysis_prepare_advances_verified_counts_without_model_call(monkeypatch) -> None:
    from apps.worker import tasks

    run = {
        "projectAnalysisRunId": "PARUN-1",
        "projectAnalysisSnapshotId": "PASNAP-1",
        "phase": "preparing_snapshot",
        "includedNodeCount": 2,
        "uniqueFileCount": 3,
        "revision": 1,
    }
    tasks.repo.state["project_analysis_runs"] = [run]
    tasks.repo.state["project_analysis_events"] = []
    monkeypatch.setattr(tasks, "load_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tasks, "flush_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tasks, "_dispatch_project_analysis_task", lambda *_args, **_kwargs: {"taskId": "NEXT"})

    result = tasks.project_analysis_prepare.run("PARUN-1")

    assert result["phase"] == "queued"
    assert result["preparedNodeCount"] == 2
    assert result["loadedFileCount"] == 3
    assert result["queueTaskId"] == "NEXT"


def test_invalid_project_analysis_output_enters_failed_phase_instead_of_stalling(monkeypatch) -> None:
    from apps.worker import tasks

    run = {
        "projectAnalysisRunId": "PARUN-INVALID",
        "projectAnalysisSnapshotId": "PASNAP-INVALID",
        "projectId": "P-1",
        "phase": "validating_output",
        "status": "validating_output",
        "rawModelOutput": '{"nodeReviews": [',
        "revision": 1,
    }
    tasks.repo.state["project_analysis_runs"] = [run]
    tasks.repo.state["project_analysis_events"] = []
    tasks.repo.state["project_analysis_snapshots"] = [
        {
            "projectAnalysisSnapshotId": "PASNAP-INVALID",
            "projectId": "P-1",
            "nodes": [],
            "request": {
                "messages": [
                    {"role": "system", "content": "system"},
                    {
                        "role": "user",
                        "content": '{"project":{"projectId":"P-1","nodes":[],"fileCorpus":{}}}',
                    },
                ]
            },
        }
    ]
    flushed: list[str] = []
    dispatched: list[str] = []
    monkeypatch.setattr(tasks, "load_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tasks, "flush_state", lambda *_args, **_kwargs: flushed.append("flush"))
    monkeypatch.setattr(
        tasks,
        "_dispatch_project_analysis_task",
        lambda task_name, _run_id: dispatched.append(task_name),
    )

    result = tasks.project_analysis_validate_output.run("PARUN-INVALID")

    assert result["phase"] == "failed"
    assert result["status"] == "failed"
    assert result["errorCode"] == "LLM_OUTPUT_INVALID_JSON"
    assert result["failedFromPhase"] == "validating_output"
    assert result["errorMessage"] == "模型输出不是合法 JSON，未生成可供人工审查的结果。"
    assert flushed == ["flush"]
    assert dispatched == []


def test_exhausted_model_retries_flush_failed_state(monkeypatch) -> None:
    """模型调用连续失败时，failed 终态必须落库，且只在重试耗尽的最后一次落。

    实测缺陷：PROJECT_REVIEW 模型名配错 → 三次 HTTP 400 → 异常越过任务末尾的
    flush_state()，DB 里的 run 永远停在 queued，前端无限转圈。
    """
    import pytest

    from apps.worker import tasks

    run = {
        "projectAnalysisRunId": "PARUN-EXHAUST",
        "projectAnalysisSnapshotId": "PASNAP-EXHAUST",
        "projectId": "P-1",
        "phase": "queued",
        "status": "queued",
        "revision": 1,
    }
    tasks.repo.state["project_analysis_runs"] = [run]
    tasks.repo.state["project_analysis_events"] = []
    flushed: list[str] = []
    monkeypatch.setattr(tasks, "load_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tasks, "flush_state", lambda *_args, **_kwargs: flushed.append("flush"))

    def boom(*_args, **_kwargs):
        raise RuntimeError("Qwen official API chat.completions failed: HTTP 400")

    monkeypatch.setattr(tasks, "execute_project_analysis_model", boom)
    task = tasks.project_analysis_execute_model

    # 中途重试：不落库。落了下一次重试会从终态 failed 起步、被相位校验挡住。
    task.push_request(retries=0)
    try:
        with pytest.raises(RuntimeError):
            task.run("PARUN-EXHAUST")
    finally:
        task.pop_request()
    assert flushed == []
    assert run["phase"] == "queued"

    # 重试耗尽的最后一次：failed 必须落库，否则前端永远看到 queued。
    task.push_request(retries=2)
    try:
        with pytest.raises(RuntimeError):
            task.run("PARUN-EXHAUST")
    finally:
        task.pop_request()
    assert run["phase"] == "failed"
    assert run["status"] == "failed"
    assert run["errorCode"] == "RuntimeError"
    assert flushed == ["flush"]


def test_prepare_writes_deterministic_queue_task_id_before_dispatch(monkeypatch) -> None:
    """celery 模式下 queueTaskId 必须在派发前落库。

    原来是派发后回填再第二次落库：execute 首跳读到中间版本，落库撞
    ConcurrentPersistenceError（实测必败，白烧一次重试）。taskId 改确定性
    之后可以先写后发，run 行在派发后不再变化。
    """
    from apps.worker import tasks
    from libs.integrations import task_dispatcher

    run = {
        "projectAnalysisRunId": "PARUN-QID",
        "projectAnalysisSnapshotId": "PASNAP-QID",
        "phase": "preparing_snapshot",
        "includedNodeCount": 1,
        "uniqueFileCount": 1,
        "revision": 1,
    }
    tasks.repo.state["project_analysis_runs"] = [run]
    tasks.repo.state["project_analysis_events"] = []
    monkeypatch.setenv("AICHECK_TASK_DISPATCH", "celery")
    events: list[tuple[str, object]] = []
    monkeypatch.setattr(tasks, "load_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        tasks, "flush_state", lambda *_args, **_kwargs: events.append(("flush", run.get("queueTaskId")))
    )

    def fake_dispatch(task_name, run_id, *, task_id=None):
        events.append(("dispatch", task_id))
        return {"mode": "celery", "taskId": task_id}

    monkeypatch.setattr(tasks, "_dispatch_project_analysis_task", fake_dispatch)

    result = tasks.project_analysis_prepare.run("PARUN-QID")

    expected = task_dispatcher.deterministic_task_id("project-analysis-execute", "PARUN-QID")
    assert result["queueTaskId"] == expected
    # 落库那一刻 queueTaskId 已是最终值；派发用同一个 id；之后没有第二次落库
    assert events == [("flush", expected), ("dispatch", expected)]
