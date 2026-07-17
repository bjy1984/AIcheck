from __future__ import annotations

from libs.db.repository import repo
from libs.review_orchestrator.execution import plan_r13_tool_review, plan_r15_tool_review


def test_r13_llm_agent_calls_fact_and_deterministic_tools_and_preserves_reasoning(monkeypatch) -> None:
    tool_names = [
        "inspect_r13_review_facts",
        "classify_r13_component_requirements",
        "evaluate_r13_supervision_certificate_completeness",
        "evaluate_r13_type_test_coverage",
    ]
    response = {
        "id": "chat-r13-agent",
        "choices": [
            {
                "message": {
                    "content": "",
                    "reasoning_content": "先读取事实，再依次使用确定性工具核对R13。",
                    "tool_calls": [
                        {"id": f"call-{index}", "function": {"name": name, "arguments": "{}"}}
                        for index, name in enumerate(tool_names, 1)
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
    monkeypatch.setattr("libs.review_orchestrator.execution.qwen_runtime_client", lambda: FakeClient())
    review_run = {
        "reviewRunId": "RRUN-R13-AGENT",
        "aiRunId": "AIRUN-R13-AGENT",
        "projectId": "P-2026-HDCP-001",
        "nodeId": 13,
        "modelAlias": "review-chat",
    }
    facts = {
        "r13": {
            "designItems": [{"componentItemId": "I-BOLT", "componentType": "高强螺栓"}],
            "supervisionCertificates": [],
            "typeTestReports": [],
        }
    }

    trace = plan_r13_tool_review(review_run, facts)

    assert trace["controlMode"] == "llm_tool_call_guarded"
    assert trace["missingRequiredTools"] == []
    assert [item["toolName"] for item in trace["toolCalls"]] == tool_names
    assert "确定性工具核对R13" in trace["reasoningContent"]
    attempt = next(
        item for item in repo.state["model_call_attempts"] if item.get("reviewRunId") == "RRUN-R13-AGENT"
    )
    assert attempt["status"] == "succeeded"
    assert attempt["reasoningContent"] == trace["reasoningContent"]


def test_r13_agent_uses_deterministic_workflow_guard_when_llm_is_disabled(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_REVIEW_LLM_EXECUTION", "deterministic")
    trace = plan_r13_tool_review(
        {"reviewRunId": "RRUN-R13-GUARD", "nodeId": 13},
        {"r13": {"designItems": [], "supervisionCertificates": [], "typeTestReports": []}},
    )

    assert trace["controlMode"] == "deterministic_workflow_guard"
    assert trace["llmCalled"] is False
    assert "classify_r13_component_requirements" in trace["missingRequiredTools"]


def test_r15_llm_agent_calls_all_guarded_business_tools(monkeypatch) -> None:
    tool_names = [
        "inspect_r15_review_facts",
        "classify_r15_foreign_manufacturing_applicability",
        "classify_r15_regulatory_requirements",
        "evaluate_r15_manufacturing_license_coverage",
        "evaluate_r15_type_test_coverage",
        "evaluate_r15_manufacturing_inspection_route",
    ]
    response = {
        "id": "chat-r15-agent",
        "choices": [
            {
                "message": {
                    "content": "",
                    "reasoning_content": "先确认境外制造，再核对许可、型式试验和制造监检路径。",
                    "tool_calls": [
                        {"id": f"call-r15-{index}", "function": {"name": name, "arguments": "{}"}}
                        for index, name in enumerate(tool_names, 1)
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
    monkeypatch.setattr("libs.review_orchestrator.execution.qwen_runtime_client", lambda: FakeClient())
    review_run = {
        "reviewRunId": "RRUN-R15-AGENT",
        "aiRunId": "AIRUN-R15-AGENT",
        "projectId": "P-2026-HDCP-001",
        "nodeId": 15,
        "modelAlias": "review-chat",
    }
    facts = {
        "r15": {
            "designItems": [{"componentItemId": "I-R15", "componentType": "金属阀门"}],
            "manufacturingLicenseCandidates": [],
            "manualRegistryVerifications": [],
            "supervisionCertificates": [],
            "typeTestReports": [],
            "arrivalInspectionRecords": [],
            "completeMachineInspectionRecords": [],
        }
    }

    trace = plan_r15_tool_review(review_run, facts)

    assert trace["controlMode"] == "llm_tool_call_guarded"
    assert trace["missingRequiredTools"] == []
    assert [item["toolName"] for item in trace["toolCalls"]] == tool_names
    assert "制造监检路径" in trace["reasoningContent"]
