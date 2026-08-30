from __future__ import annotations

import json

from libs.db.repository import repo
from libs.review_orchestrator.execution import (
    apply_review_human_input_for_review_run,
    create_review_run_from_ai_run,
    execute_review_run_inline,
    plan_r19_semantic_review,
)
from libs.review_orchestrator.r19_agent import (
    R19_REVIEW_QUESTIONS,
    apply_r19_human_input,
    build_r19_agent_context,
    ensure_r19_human_input_task,
    validate_r19_semantic_submission,
)


def r19_state() -> dict:
    return {
        "versions": [{"id": "DV-R19-1", "fileName": "境外牌号材料资料.pdf"}],
        "documents": [],
        "ocr_parse_results": [
            {
                "documentVersionId": "DV-R19-1",
                "documentType": "quality_certificate",
                "fields": [
                    {
                        "fieldCode": "material_grade",
                        "fieldValue": "ASTM A312 TP316L",
                        "pageNo": 1,
                        "bbox": [10, 20, 210, 45],
                        "confidence": 0.98,
                    }
                ],
                "fragments": [
                    {
                        "text": "材料牌号 ASTM A312 TP316L；炉号 H-2026-01；化学成分和力学性能见附表。",
                        "pageNo": 1,
                        "bbox": [10, 50, 500, 90],
                        "confidence": 0.97,
                    }
                ],
                "tables": [
                    {
                        "tableId": "T-R19-1",
                        "pageNo": 1,
                        "businessSchema": "material_test_results",
                        "normalizedRows": [{"heatNo": "H-2026-01", "result": "合格"}],
                    }
                ],
            }
        ],
    }


def review_run(review_run_id: str = "RRUN-R19-UNIT") -> dict:
    return {
        "id": review_run_id,
        "reviewRunId": review_run_id,
        "aiRunId": "AIRUN-R19-UNIT",
        "projectId": "P-2026-HDCP-001",
        "nodeId": 19,
        "reviewMode": "formal",
        "advisoryOnly": False,
        "inputHash": "sha256:r19-input",
        "inputDocumentVersionIds": ["DV-R19-1"],
        "modelAlias": "review-chat",
        "humanInputTasks": [],
        "revision": 1,
    }


def semantic_payload(evidence_ref_id: str, *, failed_id: str | None = None) -> dict:
    judgments = []
    for question in R19_REVIEW_QUESTIONS:
        atomic_id = question["questionId"]
        judgments.append(
            {
                "atomicCheckId": atomic_id,
                "result": "failed" if atomic_id == failed_id else "passed",
                "explanation": f"根据已定位文件证据完成 {atomic_id} 判断。",
                "reasonCodes": ["R19_EVIDENCE_REVIEWED"],
                "evidenceRefIds": [evidence_ref_id],
                "clauseRefs": question["clauseRefs"],
                "missingFacts": [],
                "recommendedAction": "由监检人员复核。",
                "confidence": 0.88,
            }
        )
    return {"atomicJudgments": judgments, "summary": "R19 八个原子项已完成。"}


def test_r19_context_builds_stable_evidence_for_open_format_documents() -> None:
    run = review_run()
    first = build_r19_agent_context(r19_state(), run)
    second = build_r19_agent_context(r19_state(), run)

    assert first["executionMode"] == "llm_semantic_primary"
    assert first["documentCount"] == 1
    assert len(first["reviewQuestions"]) == 8
    assert first["evidenceRefIds"] == second["evidenceRefIds"]
    evidence = next(iter(first["evidenceIndex"].values()))
    assert evidence["documentVersionId"] == "DV-R19-1"
    assert evidence["pageNo"] == 1
    assert evidence["quotedText"]


def test_r19_semantic_submission_requires_all_questions_and_registered_evidence() -> None:
    context = build_r19_agent_context(r19_state(), review_run())
    evidence_id = context["evidenceRefIds"][0]

    valid = validate_r19_semantic_submission(
        semantic_payload(evidence_id, failed_id="AC-R19-04"),
        known_evidence_ref_ids=set(context["evidenceRefIds"]),
    )
    unknown = validate_r19_semantic_submission(
        semantic_payload("EV-UNKNOWN"),
        known_evidence_ref_ids=set(context["evidenceRefIds"]),
    )
    missing_evidence = semantic_payload(evidence_id)
    missing_evidence["atomicJudgments"][0]["evidenceRefIds"] = []
    insufficient = validate_r19_semantic_submission(
        missing_evidence,
        known_evidence_ref_ids=set(context["evidenceRefIds"]),
    )
    low_confidence_index = {
        **context["evidenceIndex"],
        evidence_id: {**context["evidenceIndex"][evidence_id], "confidence": 0.4},
    }
    low_confidence = validate_r19_semantic_submission(
        semantic_payload(evidence_id),
        known_evidence_ref_ids=set(context["evidenceRefIds"]),
        evidence_index=low_confidence_index,
    )
    invented_clause_payload = semantic_payload(evidence_id)
    invented_clause_payload["atomicJudgments"][0]["clauseRefs"] = ["模型自创条款 9.9"]
    invented_clause = validate_r19_semantic_submission(
        invented_clause_payload,
        known_evidence_ref_ids=set(context["evidenceRefIds"]),
    )

    assert valid["status"] == "valid"
    assert valid["result"] == "failed"
    assert unknown["status"] == "invalid_input"
    assert any("evidence_ref_unknown" in item for item in unknown["errors"])
    assert insufficient["status"] == "invalid_input"
    assert any("evidence_required_for_passed" in item for item in insufficient["errors"])
    assert low_confidence["status"] == "invalid_input"
    assert any("evidence_confidence_too_low" in item for item in low_confidence["errors"])
    assert invented_clause["status"] == "invalid_input"
    assert any("clause_ref_not_fixed" in item for item in invented_clause["errors"])


def test_r19_agent_submits_evidence_bound_atomic_judgments_and_preserves_reasoning(monkeypatch) -> None:
    run = review_run("RRUN-R19-AGENT")
    context = build_r19_agent_context(r19_state(), run)
    evidence_id = context["evidenceRefIds"][0]
    response = {
        "id": "chat-r19-agent",
        "choices": [
            {
                "message": {
                    "content": "",
                    "reasoning_content": "先核对固定八项，再引用已登记证据提交语义判断。",
                    "tool_calls": [
                        {
                            "id": "call-inspect",
                            "function": {"name": "inspect_r19_review_context", "arguments": "{}"},
                        },
                        {
                            "id": "call-submit",
                            "function": {
                                "name": "submit_r19_semantic_review",
                                "arguments": json.dumps(semantic_payload(evidence_id), ensure_ascii=False),
                            },
                        },
                    ],
                }
            }
        ],
    }

    class FakeClient:
        def chat_sync(self, messages, model, **kwargs):
            assert kwargs["tools"]
            assert kwargs["tool_choice"] == "auto"
            return response

    monkeypatch.setenv("AICHECK_REVIEW_LLM_EXECUTION", "litellm")
    # 规划器住在 rule_planners（execution.py 拆分时搬出去的），
    # patch 必须打在它实际解析的那个模块上——patch execution 的同名
    # re-export 不会影响 rule_planners 里的绑定。
    monkeypatch.setattr("libs.review_orchestrator.rule_planners.qwen_runtime_client", lambda: FakeClient())

    trace = plan_r19_semantic_review(run, context)

    assert trace["submitted"] is True
    assert trace["requestedHumanInput"] is False
    assert trace["result"] == "passed"
    assert len(trace["atomicJudgments"]) == 8
    assert "已登记证据" in trace["reasoningContent"]
    reasoning_event = next(
        item
        for item in repo.state["review_events"]
        if item.get("reviewRunId") == "RRUN-R19-AGENT" and item.get("eventType") == "agent.reasoning.delta"
    )
    assert reasoning_event["details"]["sourceField"] == "reasoning_content"
    assert reasoning_event["details"]["content"] == trace["reasoningContent"]


def test_r19_agent_uses_blocking_human_guard_when_llm_is_disabled(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_REVIEW_LLM_EXECUTION", "deterministic")
    run = review_run("RRUN-R19-GUARD")
    context = build_r19_agent_context(r19_state(), run)

    trace = plan_r19_semantic_review(run, context)
    task = ensure_r19_human_input_task(
        run,
        trace["humanInputRequest"],
        requested_by="workflow_guard",
        agent_trace=trace,
        agent_context=context,
    )

    assert trace["requestedHumanInput"] is True
    assert task is not None
    assert task["taskType"] == "r19_semantic_evidence_confirmation"
    assert task["questionCount"] == 8
    assert task["evidenceCandidateCount"] > 0


def test_r19_human_task_validates_applies_and_dispatches_by_task_type() -> None:
    run = review_run("RRUN-R19-HUMAN")
    task = ensure_r19_human_input_task(
        run,
        {"questionIds": ["AC-R19-05"], "reason": "首次使用状态无法从文件确认。"},
        requested_by="llm_agent",
    )
    assert task is not None
    run["status"] = "waiting_human_input"
    payload = {
        "answers": [
            {
                "questionId": "AC-R19-05",
                "outcome": "confirmed",
                "value": {"firstUse": True},
                "comment": "监检人员确认本单位首次使用该材料。",
                "sourceRefs": [
                    {
                        "type": "record",
                        "reference": "项目材料首次使用确认记录 R19-2026-001",
                    }
                ],
                "attested": True,
            }
        ]
    }

    direct = apply_r19_human_input(
        run,
        task["taskId"],
        payload,
        actor_id="U-R19",
        actor_name="监检员",
    )
    assert direct["status"] == "applied"
    rebuilt = build_r19_agent_context(r19_state(), run)
    assert rebuilt["humanConfirmations"][0]["questionId"] == "AC-R19-05"
    assert rebuilt["humanConfirmations"][0]["evidenceRefId"].startswith("R19HUM-")

    dispatch_run = review_run("RRUN-R19-DISPATCH")
    dispatch_task = ensure_r19_human_input_task(
        dispatch_run,
        {"questionIds": ["AC-R19-05"], "reason": "首次使用状态无法从文件确认。"},
        requested_by="llm_agent",
    )
    dispatch_run["status"] = "waiting_human_input"
    repo.state.setdefault("review_runs", []).insert(0, dispatch_run)
    validation = apply_review_human_input_for_review_run(
        dispatch_run["reviewRunId"],
        dispatch_task["taskId"],
        payload,
        actor_id="U-R19",
        actor_name="监检员",
        commit=False,
    )
    assert validation["status"] == "valid"


def test_r19_human_task_deduplicates_free_text_reason_and_requires_traceable_source() -> None:
    run = review_run("RRUN-R19-DEDUPE")
    context = build_r19_agent_context(r19_state(), run)
    first = ensure_r19_human_input_task(
        run,
        {"questionIds": ["AC-R19-05"], "reason": "首次使用状态无法确认。"},
        requested_by="llm_agent",
        agent_context=context,
    )
    assert first is not None
    run["status"] = "waiting_human_input"
    comment_only = {
        "answers": [
            {
                "questionId": "AC-R19-05",
                "outcome": "confirmed",
                "comment": "仅有说明，没有来源。",
                "attested": True,
            }
        ]
    }
    rejected = apply_r19_human_input(
        run,
        first["taskId"],
        comment_only,
        actor_id="U-R19",
        actor_name="监检员",
    )
    assert rejected["status"] == "invalid_input"
    assert "answer_1_source_required" in rejected["errors"]

    accepted = apply_r19_human_input(
        run,
        first["taskId"],
        {
            "answers": [
                {
                    **comment_only["answers"][0],
                    "sourceRefs": [{"type": "url", "url": "https://example.test/r19-confirmation"}],
                }
            ]
        },
        actor_id="U-R19",
        actor_name="监检员",
    )
    assert accepted["status"] == "applied"
    duplicate = ensure_r19_human_input_task(
        run,
        {"questionIds": ["AC-R19-05"], "reason": "模型换了一种说法，但问题未变化。"},
        requested_by="llm_agent",
        agent_context=context,
    )
    assert duplicate is None


def test_r19_inline_run_pauses_resumes_and_uses_fixed_semantic_aggregation(monkeypatch) -> None:
    state = r19_state()
    repo.state.setdefault("versions", []).insert(0, state["versions"][0])
    repo.state.setdefault("ocr_parse_results", []).insert(0, state["ocr_parse_results"][0])
    ai_run = {
        "id": "AIRUN-R19-INLINE",
        "projectId": "P-2026-HDCP-001",
        "nodeId": 19,
        "subject": "R19 暂停恢复与固定聚合测试",
        "model": "review-chat",
        "reviewMode": "formal",
        "advisoryOnly": False,
        "previousNodeStatus": "待审查",
        "auditInputMode": "ocr_llm",
        "suggestion": {"id": "AIS-R19-INLINE", "confidence": 0, "manualConfirmItems": []},
        "evidenceLinks": [],
        "inputDocumentVersionIds": ["DV-R19-1"],
    }
    repo.state.setdefault("ai_runs", []).insert(0, ai_run)
    monkeypatch.setenv("AICHECK_REVIEW_LLM_EXECUTION", "deterministic")
    run = create_review_run_from_ai_run(ai_run, mode="inline")

    paused = execute_review_run_inline(run["reviewRunId"])

    assert paused["status"] == "waiting_human_input"
    task = run["humanInputTasks"][0]
    assert task["evidenceCandidateCount"] > 0
    applied = apply_review_human_input_for_review_run(
        run["reviewRunId"],
        task["taskId"],
        {
            "answers": [
                {
                    "questionId": question["questionId"],
                    "outcome": "unknown",
                    "comment": "现有资料仍不能由人工可靠确认。",
                    "attested": True,
                }
                for question in task["questions"]
            ]
        },
        actor_id="U-R19",
        actor_name="监检员",
    )
    assert applied["status"] == "applied"

    def fake_semantic_plan(review_run, agent_context):
        evidence_id = next(
            item
            for item in agent_context["evidenceRefIds"]
            if item.startswith("R19EV-")
        )
        validation = validate_r19_semantic_submission(
            semantic_payload(evidence_id, failed_id="AC-R19-04"),
            evidence_index=agent_context["evidenceIndex"],
        )
        assert validation["status"] == "valid"
        return {
            "controlMode": "llm_semantic_primary",
            "llmCalled": True,
            "requestedHumanInput": False,
            "submitted": True,
            "knownEvidenceRefIds": agent_context["evidenceRefIds"],
            **validation,
        }

    def fake_graph(review_run, context, **kwargs):
        step_runner = kwargs["run_step"]
        step_runner(review_run, "load_context", context)
        step_runner(review_run, "load_ocr_result", context)
        rule_details = step_runner(review_run, "run_rule_engine", context)
        assert rule_details["result"] == "failed"
        review_run["findingDrafts"] = [{"description": "R19 固定聚合结果为不符合", "confidence": 0.88}]
        return {"runner": "manual", "checkpointer": "none", "nodeCount": 3}

    monkeypatch.setattr("libs.review_orchestrator.execution.plan_r19_semantic_review", fake_semantic_plan)
    monkeypatch.setattr("libs.review_orchestrator.graph.execute_review_graph", fake_graph)
    resumed = execute_review_run_inline(run["reviewRunId"])

    assert resumed["status"] == "waiting_human_review"
    assert run["r19SemanticReview"]["result"] == "failed"
    result = next(
        item
        for item in reversed(repo.state["rule_check_results"])
        if item.get("reviewRunId") == run["reviewRunId"]
    )
    assert result["result"] == "failed"
    assert len(result["atomicCheckResults"]) == 8
    assert result["toolExecutionSummary"]["nodeResultSource"] == "fixed_aggregator_over_llm_semantic_judgments"
