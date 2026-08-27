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
