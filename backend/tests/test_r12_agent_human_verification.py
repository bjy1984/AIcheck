from __future__ import annotations

from libs.db.repository import repo
from libs.review_orchestrator.execution import (
    apply_r12_human_input_for_review_run,
    create_review_run_from_ai_run,
    execute_review_run_inline,
    plan_r12_human_verification,
)
from libs.review_orchestrator.r12_agent import (
    apply_r12_human_input,
    ensure_r12_human_input_task,
    extract_r12_component_items,
    extract_r12_license_candidates,
)
from libs.review_tools.business_tools import dispatch_business_tool


def manufacturing_parse_result(version_id: str, *, page_no: int, license_no: str, organization: str, scope: str) -> dict:
    return {
        "id": f"OCR-{version_id}",
        "documentVersionId": version_id,
        "status": "success",
        "fragments": [
            {
                "text": "中华人民共和国特种设备生产许可证",
                "pageNo": page_no,
                "bbox": [10, 10, 300, 30],
                "confidence": 0.98,
            },
            {
                "text": f"许可证编号：{license_no}",
                "pageNo": page_no,
                "bbox": [10, 40, 260, 60],
                "confidence": 0.97,
            },
            {
                "text": f"单位名称：{organization}",
                "pageNo": page_no,
                "bbox": [10, 70, 300, 90],
                "confidence": 0.96,
            },
            {
                "text": f"许可项目：压力管道元件制造 {scope}",
                "pageNo": page_no,
                "bbox": [10, 100, 400, 120],
                "confidence": 0.95,
            },
        ],
        "fields": [
            {"fieldCode": "certificate_no", "fieldValue": license_no, "pageNo": page_no, "confidence": 0.97},
            {"fieldCode": "organization_name", "fieldValue": organization, "pageNo": page_no, "confidence": 0.96},
            {
                "fieldCode": "license_scope",
                "fieldValue": f"压力管道元件制造 {scope}",
                "pageNo": page_no,
                "confidence": 0.95,
            },
        ],
    }


def test_r12_candidate_extraction_excludes_personnel_and_installation_pages() -> None:
    state = {
        "ocr_parse_results": [
            manufacturing_parse_result(
                "VER-MANUFACTURING-1",
                page_no=1,
                license_no="TS2710504-2027",
                organization="河北管件有限公司",
                scope="非焊接管件、锻制法兰",
            ),
            manufacturing_parse_result(
                "VER-MANUFACTURING-2",
                page_no=1,
                license_no="TS2710692-2027",
                organization="广东钢管有限公司",
                scope="无缝钢管",
            ),
            {
                "documentVersionId": "VER-WELDER",
                "fragments": [
                    {"text": "特种设备作业人员证 焊工证 作业项目代号", "pageNo": 1, "confidence": 0.99}
                ],
            },
            {
                "documentVersionId": "VER-INSTALLATION",
                "fragments": [
                    {
                        "text": "中华人民共和国特种设备生产许可证 压力管道安装 GC1",
                        "pageNo": 1,
                        "confidence": 0.99,
                    }
                ],
            },
        ],
        "versions": [],
        "documents": [],
    }
    review_run = {
        "nodeId": 12,
        "inputDocumentVersionIds": [
            "VER-MANUFACTURING-1",
            "VER-MANUFACTURING-2",
            "VER-WELDER",
            "VER-INSTALLATION",
        ],
    }

    candidates = extract_r12_license_candidates(state, review_run)

    assert [item["licenseNo"] for item in candidates] == ["TS2710504-2027", "TS2710692-2027"]


def test_r12_human_task_requires_one_attested_response_per_candidate() -> None:
    state = {
        "ocr_parse_results": [
            manufacturing_parse_result(
                "VER-R12-TASK",
                page_no=1,
                license_no="TS2710504-2027",
                organization="河北管件有限公司",
                scope="非焊接管件、锻制法兰",
            )
        ],
        "versions": [],
        "documents": [],
    }
    review_run = {
        "reviewRunId": "RRUN-R12-TASK",
        "nodeId": 12,
        "reviewMode": "formal",
        "advisoryOnly": False,
        "inputHash": "sha256:input",
        "inputDocumentVersionIds": ["VER-R12-TASK"],
        "humanInputTasks": [],
    }
    task = ensure_r12_human_input_task(state, review_run, requested_by="llm_agent")
    assert task is not None
    review_run["status"] = "waiting_human_input"

    invalid = apply_r12_human_input(
        review_run,
        task["taskId"],
        {"verifications": []},
        actor_id="U-1",
        actor_name="监检员",
    )
    assert invalid["status"] == "invalid_input"

    candidate = task["candidates"][0]
    applied = apply_r12_human_input(
        review_run,
        task["taskId"],
        {
            "verifications": [
                {
                    "candidateId": candidate["candidateId"],
                    "outcome": "verified_match",
                    "registryLicenseNo": candidate["licenseNo"],
                    "registryOrganizationName": candidate["organizationName"],
                    "registryStatus": "active",
                    "registryScopeRaw": "非焊接管件、锻制法兰",
                    "sourceUrl": "https://example.test/registry",
                    "attested": True,
                }
            ]
        },
        actor_id="U-1",
        actor_name="监检员",
    )
    assert applied["status"] == "applied"
    assert review_run["status"] == "resuming"
    assert task["status"] == "completed"


def test_r12_fact_builder_links_material_row_to_quality_certificate_manufacturer() -> None:
    state = {
        "ocr_parse_results": [
            {
                "documentVersionId": "DV-MATERIAL-LIST",
                "tables": [
                    {
                        "tableId": "MAT-1",
                        "businessSchemas": ["comprehensive_material_list"],
                        "pageNo": 2,
                        "normalizedRows": [
                            {
                                "materialName": "带颈对焊法兰",
                                "specification": "WN100(B)-16 RF S=5",
                                "materialGrade": "20#",
                            }
                        ],
                    }
                ],
            },
            {
                "documentVersionId": "DV-QUALITY-CERT",
                "documentType": "quality_certificate",
                "fields": [
                    {"fieldCode": "manufacturer", "fieldValue": "河北广浩管件有限公司", "pageNo": 1},
                    {"fieldCode": "specification", "fieldValue": "WN100(B)-16 RF S=5", "pageNo": 1},
                    {"fieldCode": "material_grade", "fieldValue": "20#", "pageNo": 1},
                ],
                "fragments": [],
            },
        ]
    }
    review_run = {
        "inputDocumentVersionIds": ["DV-MATERIAL-LIST", "DV-QUALITY-CERT"],
    }

    items = extract_r12_component_items(state, review_run)

    assert len(items) == 1
    assert items[0]["componentType"] == "带颈对焊法兰"
    assert items[0]["manufacturerName"] == "河北广浩管件有限公司"
    assert items[0]["qualityCertificateDocumentVersionId"] == "DV-QUALITY-CERT"


def test_r12_registry_and_component_scope_tools_form_deterministic_conclusion() -> None:
    candidates = [
        {
            "candidateId": "LIC-1",
            "licenseNo": "TS2710504-2027",
            "organizationName": "河北管件有限公司",
        }
    ]
    verifications = [
        {
            "candidateId": "LIC-1",
            "outcome": "verified_match",
            "registryLicenseNo": "TS2710504-2027",
            "registryOrganizationName": "河北管件有限公司",
            "registryStatus": "active",
            "registryScopeRaw": "压力管道元件制造：非焊接管件、锻制法兰",
        }
    ]
    registry_result = dispatch_business_tool(
        "check_license_registry_match",
        {"licenseCandidates": candidates, "registryVerifications": verifications},
    )
    assert registry_result["result"] == "passed"

    coverage_result = dispatch_business_tool(
        "evaluate_component_manufacturer_scope",
        {
            "licenseCandidates": candidates,
            "registryVerifications": verifications,
            "componentItems": [
                {
                    "componentItemId": "ITEM-1",
                    "componentType": "90°无缝弯头",
                    "manufacturerName": "河北管件有限公司",
                },
                {
                    "componentItemId": "ITEM-2",
                    "componentType": "锻制法兰",
                    "manufacturerName": "河北管件有限公司",
                },
            ],
        },
    )
    assert coverage_result["result"] == "passed"
    assert len(coverage_result["facts"]["componentCoverageMatrix"]) == 2

    uncovered = dispatch_business_tool(
        "evaluate_component_manufacturer_scope",
        {
            "licenseCandidates": candidates,
            "registryVerifications": verifications,
            "componentItems": [
                {
                    "componentItemId": "ITEM-3",
                    "componentType": "安全阀",
                    "manufacturerName": "河北管件有限公司",
                }
            ],
        },
    )
    assert uncovered["result"] == "failed"


def test_r12_inline_review_pauses_and_resumes_after_human_input(monkeypatch) -> None:
    version_id = "VER-R12-INLINE"
    parse_result = manufacturing_parse_result(
        version_id,
        page_no=1,
        license_no="TS2710504-2027",
        organization="河北管件有限公司",
        scope="非焊接管件",
    )
    repo.state.setdefault("ocr_parse_results", []).insert(0, parse_result)
    ai_run = {
        "id": "AIRUN-R12-INLINE",
        "projectId": "P-2026-HDCP-001",
        "nodeId": 12,
        "subject": "R12 暂停恢复测试",
        "model": "review-chat",
        "reviewMode": "formal",
        "advisoryOnly": False,
        "previousNodeStatus": "待审查",
        "auditInputMode": "ocr_llm",
        "suggestion": {"id": "AIS-R12-INLINE", "confidence": 0, "manualConfirmItems": []},
        "evidenceLinks": [],
        "inputDocumentVersionIds": [version_id],
    }
    repo.state.setdefault("ai_runs", []).insert(0, ai_run)
    monkeypatch.setenv("AICHECK_REVIEW_LLM_EXECUTION", "deterministic")
    run = create_review_run_from_ai_run(ai_run, mode="inline")

    paused = execute_review_run_inline(run["reviewRunId"])

    assert paused["status"] == "waiting_human_input"
    task = run["humanInputTasks"][0]
    candidate = task["candidates"][0]
    applied = apply_r12_human_input_for_review_run(
        run["reviewRunId"],
        task["taskId"],
        {
            "verifications": [
                {
                    "candidateId": candidate["candidateId"],
                    "outcome": "verified_match",
                    "registryLicenseNo": candidate["licenseNo"],
                    "registryOrganizationName": candidate["organizationName"],
                    "registryStatus": "active",
                    "registryScopeRaw": "非焊接管件",
                    "sourceUrl": "https://example.test/registry",
                    "attested": True,
                }
            ]
        },
        actor_id="U-1",
        actor_name="监检员",
    )
    assert applied["status"] == "applied"

    def fake_graph(review_run, context, **kwargs):
        review_run["findingDrafts"] = [{"description": "R12 已复核", "confidence": 0.8}]
        return {"runner": "langgraph", "checkpointer": "postgres", "nodeCount": 12}

    monkeypatch.setattr("libs.review_orchestrator.graph.execute_review_graph", fake_graph)
    resumed = execute_review_run_inline(run["reviewRunId"])

    assert resumed["status"] == "waiting_human_review"
    assert len(run["humanInputTasks"]) == 1


def test_r12_llm_agent_uses_tool_calls_and_preserves_reasoning_content(monkeypatch) -> None:
    candidate = {
        "candidateId": "R12LIC-AGENT",
        "licenseNo": "TS2710504-2027",
        "organizationName": "河北管件有限公司",
    }
    responses = iter(
        [
            {
                "id": "chat-r12-1",
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "reasoning_content": "先读取许可证候选。",
                            "tool_calls": [
                                {
                                    "id": "call-inspect",
                                    "function": {
                                        "name": "inspect_r12_license_candidates",
                                        "arguments": "{}",
                                    },
                                }
                            ],
                        }
                    }
                ],
            },
            {
                "id": "chat-r12-2",
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "reasoning_content": "官网核验必须等待监检人员输入。",
                            "tool_calls": [
                                {
                                    "id": "call-request",
                                    "function": {
                                        "name": "request_official_registry_verification",
                                        "arguments": '{"candidateIds":["R12LIC-AGENT"],"reason":"官网人工核验"}',
                                    },
                                }
                            ],
                        }
                    }
                ],
            },
        ]
    )

    class FakeClient:
        def chat_sync(self, messages, model, **kwargs):
            assert kwargs["tools"]
            assert kwargs["tool_choice"] == "auto"
            return next(responses)

    monkeypatch.setenv("AICHECK_REVIEW_LLM_EXECUTION", "litellm")
    # 规划器住在 rule_planners（execution.py 拆分时搬出去的），
    # patch 必须打在它实际解析的那个模块上——patch execution 的同名
    # re-export 不会影响 rule_planners 里的绑定。
    monkeypatch.setattr("libs.review_orchestrator.rule_planners.qwen_runtime_client", lambda: FakeClient())
    review_run = {
        "reviewRunId": "RRUN-R12-AGENT",
        "aiRunId": "AIRUN-R12-AGENT",
        "projectId": "P-2026-HDCP-001",
        "nodeId": 12,
        "modelAlias": "review-chat",
    }

    requested_by, trace = plan_r12_human_verification(review_run, [candidate])

    assert requested_by == "llm_agent"
    assert trace["requestedHumanInput"] is True
    assert [item["toolName"] for item in trace["toolCalls"]] == [
        "inspect_r12_license_candidates",
        "request_official_registry_verification",
    ]
    assert "官网核验必须等待监检人员输入" in trace["reasoningContent"]
    attempt = next(
        item
        for item in repo.state["model_call_attempts"]
        if item.get("reviewRunId") == "RRUN-R12-AGENT"
    )
    assert attempt["status"] == "succeeded"
    assert attempt["reasoningContent"] == trace["reasoningContent"]
