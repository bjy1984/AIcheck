"""2026-08-07 深度审计修复的回归测试。

覆盖 GitHub issues：
- #3  字段缺失 → evidence_insufficient（不再误判 failed）
- #4  human_review_required 在聚合层保留；人工结论支持「证据不足」
- #5  save_review_opinion 留痕 + AI 结论关联
- #6  聚合器优先级：grounding 一票否决；执行故障不掩盖 failed、不伪装业务结论
- #13 「不适用」结论不再把节点置为「需补正」
- #14 suggestion.result 携带确定性判定
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

import libs.review_orchestrator  # noqa: F401  # 先初始化，规避 review_tools 循环导入
from apps.api.main import app
from libs.db.repository import repo
from libs.review_orchestrator.execution import SUGGESTION_RESULT_LABELS
from libs.review_tools import dispatch_business_tool
from libs.review_tools.executor import aggregate_atomic_results, aggregate_tool_results

client = TestClient(app)


def setup_function() -> None:
    repo.reset()
    repo.postgres_enabled = False
    repo.sync_postgres = None
    repo.postgres_dsn = None
    repo.sqlite_enabled = False
    repo.sqlite_path = None


def assert_ok(response):
    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0
    return payload["data"]


# ---------------------------------------------------------------- issue #3


def test_missing_fact_fields_are_evidence_insufficient_not_failed() -> None:
    empty = dispatch_business_tool("check_required", {"requiredFields": ["a.b"], "facts": {}})
    partial = dispatch_business_tool(
        "check_required", {"requiredFields": ["a.b", "a.c"], "facts": {"a": {"b": "X"}}}
    )
    assert empty["result"] == "evidence_insufficient"
    assert partial["result"] == "evidence_insufficient"


def test_verdicts_are_correct_in_all_three_directions() -> None:
    """R-1 的修复必须三向都对：合规→passed、有值不合规→failed、缺值→evidence_insufficient。

    只测「缺值」会漏掉改过头的风险——把真实不符合项也放宽成证据不足，等于漏报。
    """
    from libs.db.repository import repo
    from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool

    def run(tool, args):
        return dispatch_runtime_tool(repo.state, tool, args).get("result")

    covering = {"validFrom": "2023-01-01", "validUntil": "2025-12-01",
                "periodStart": "2024-02-01", "periodEnd": "2024-12-01"}
    lapsed = {**covering, "validUntil": "2024-06-01", "validFrom": "2024-01-01"}

    assert run("check_date_covers", covering) == "passed"
    assert run("check_date_covers", lapsed) == "failed"
    assert run("check_date_covers", {"validFrom": "2023-01-01"}) == "evidence_insufficient"

    assert run("check_design_license_scope",
               {"licenseScopes": ["GC1"], "requiredPipelineGrades": ["GC2"]}) == "passed"
    assert run("check_design_license_scope",
               {"licenseScopes": ["GC3"], "requiredPipelineGrades": ["GC1"]}) == "failed"
    assert run("check_design_license_scope", {}) == "evidence_insufficient"


def test_business_tools_stay_strict_on_noncompliant_values() -> None:
    """确保 R-1 没有把「有值但不满足」一并放宽。"""
    cases = [
        ("check_scope_coverage",
         {"grantedScopes": ["GC3"], "requiredScopes": ["GC1"], "coverageMap": {"GC1": ["GC1"]}}),
        ("check_signature_completeness",
         {"actualRoles": ["设计", "校核"], "requiredRoles": ["设计", "校核", "审核", "审定"]}),
        ("check_cross_document_match",
         {"comparisons": [{"code": "pressure", "values": [10, 12], "tolerance": 0.01}]}),
        ("check_document_set_completeness",
         {"requiredDocumentTypes": ["a", "b"], "uploadedDocumentTypes": ["a"], "parseableDocumentTypes": ["a"]}),
    ]
    for tool, args in cases:
        assert dispatch_business_tool(tool, args)["result"] == "failed", f"{tool} 应判不符合"


def test_present_but_noncompliant_value_is_still_failed() -> None:
    scope = dispatch_business_tool(
        "check_scope_coverage",
        {"grantedScopes": ["GC3"], "requiredScopes": ["GC1"], "coverageMap": {"GC1": ["GC1"]}},
    )
    assert scope["result"] == "failed"


def test_missing_document_body_is_still_failed() -> None:
    documents = dispatch_business_tool(
        "check_document_set_completeness",
        {
            "requiredDocumentTypes": ["drawing_index", "stress_calculation"],
            "uploadedDocumentTypes": ["drawing_index"],
            "parseableDocumentTypes": ["drawing_index"],
        },
    )
    assert documents["result"] == "failed"


# ------------------------------------------------------------ issues #4 #6


def test_aggregator_preserves_human_review_required() -> None:
    assert aggregate_tool_results([{"toolName": "a", "result": "human_review_required"}]) == "human_review_required"
    assert aggregate_atomic_results([{"result": "human_review_required"}]) == "human_review_required"


def test_execution_error_does_not_mask_confirmed_failure() -> None:
    outputs = [
        {"toolName": "a", "result": "failed"},
        {"toolName": "b", "status": "failed"},
    ]
    assert aggregate_tool_results(outputs) == "failed"


def test_execution_error_alone_is_not_a_business_conclusion() -> None:
    outputs = [
        {"toolName": "a", "result": "passed"},
        {"toolName": "b", "status": "error"},
    ]
    assert aggregate_tool_results(outputs) == "execution_error"
    assert aggregate_atomic_results([{"result": "execution_error"}, {"result": "passed"}]) == "execution_error"


def test_grounding_failure_vetoes_failed_conclusion() -> None:
    outputs = [
        {"toolName": "validate_evidence_grounding", "result": "evidence_insufficient"},
        {"toolName": "check_required", "result": "failed"},
    ]
    assert aggregate_tool_results(outputs) == "evidence_insufficient"


def test_failed_takes_priority_over_human_review_and_insufficient() -> None:
    outputs = [
        {"toolName": "a", "result": "failed"},
        {"toolName": "b", "result": "human_review_required"},
        {"toolName": "c", "result": "evidence_insufficient"},
    ]
    assert aggregate_tool_results(outputs) == "failed"


# ------------------------------------------------------- issues #5 #13 #14


def test_not_applicable_opinion_does_not_demand_rectification() -> None:
    saved = assert_ok(
        client.post(
            "/projects/P-2026-HDCP-001/inspection/nodes/24/review-opinions",
            json={"result": "不适用", "opinion": "本节点对该项目不适用。", "evidenceLinkIds": []},
        )
    )
    assert saved["nextStatus"] == "不适用"
    assert repo.node("P-2026-HDCP-001", 24)["status"] == "不适用"


def test_insufficient_evidence_opinion_keeps_node_pending() -> None:
    saved = assert_ok(
        client.post(
            "/projects/P-2026-HDCP-001/inspection/nodes/24/review-opinions",
            json={"result": "证据不足", "opinion": "资料不足，待补件后复核。", "evidenceLinkIds": []},
        )
    )
    assert saved["nextStatus"] == "待审查"


def test_review_opinion_records_audit_and_ai_linkage() -> None:
    repo.state["ai_runs"].insert(
        0,
        {
            "id": "AI-TEST-1",
            "projectId": "P-2026-HDCP-001",
            "nodeId": 24,
            "suggestion": {"id": "SUG-1", "result": "需补正"},
        },
    )
    saved = assert_ok(
        client.post(
            "/projects/P-2026-HDCP-001/inspection/nodes/24/review-opinions",
            json={"result": "不适用", "opinion": "人工推翻 AI 建议。", "evidenceLinkIds": []},
        )
    )
    opinion = saved["opinion"]
    assert saved["auditLogId"]
    assert opinion["aiRunId"] == "AI-TEST-1"
    assert opinion["aiSuggestedResult"] == "需补正"
    assert opinion["overriddenFromAi"] is True
    audit = repo.find_one("audit_logs", saved["auditLogId"])
    assert audit is not None


def test_graph_execution_preserves_context_for_callers() -> None:
    """LangGraph 节点回写的 state["context"] 常与传入对象同一；
    execute_review_graph 结尾若直接 clear()+update() 会把数据抹掉，
    导致图执行后 ruleResults / evidenceLinks / promptShape 全部丢失。"""
    from libs.review_orchestrator.graph import execute_review_graph

    context: dict = {}
    steps = [{"key": "step_one"}, {"key": "step_two"}]

    def run_step(review_run, node_key, ctx):
        ctx.setdefault("visited", []).append(node_key)
        if node_key == "step_two":
            ctx["ruleResults"] = [{"result": "evidence_insufficient"}]
            ctx["evidenceLinks"] = [{"id": "EV-1"}]
        return {"nodeKey": node_key}

    execute_review_graph(
        {"reviewRunId": "RRUN-TEST"},
        context,
        steps=steps,
        run_step=run_step,
        mark_graph_node=lambda *args, **kwargs: {},
    )

    assert context.get("visited") == ["step_one", "step_two"]
    assert context.get("ruleResults") == [{"result": "evidence_insufficient"}]
    assert context.get("evidenceLinks") == [{"id": "EV-1"}]


def test_clause_package_binding_is_self_consistent() -> None:
    """节点→条款包绑定必须自洽：sourceRuleId / nodeId / packageId 三者一致。

    业务包升版（含规则重编号）后若不重绑，存量项目会继续指向旧 release 的包，
    产生 nodeId=24 却记 sourceRuleId=R12 这类自相矛盾的审计记录。
    """
    from libs.business_pack import load_business_pack
    from libs.business_pack.clause_store import (
        bind_project_node_clause_packages,
        ensure_clause_state,
    )

    pack = load_business_pack("engineering_inspection_v1")
    state: dict = {}
    ensure_clause_state(state)
    project = {"id": "P-TEST-1", "businessPackId": pack["id"], "businessPackVersion": pack["version"]}
    bind_project_node_clause_packages(state, project, pack)

    bindings = state["project_node_clause_packages"]
    assert bindings, "应产生节点绑定"
    mismatched = [
        (b["nodeId"], b.get("sourcePackageId"), b.get("sourceRuleId"))
        for b in bindings
        if b.get("sourcePackageId") != f"CLAUSE-PKG-R{int(b['nodeId']):02d}"
        or b.get("sourceRuleId") != f"R{int(b['nodeId']):02d}"
    ]
    assert not mismatched, f"绑定与节点号不一致: {mismatched[:5]}"


def test_review_run_clause_snapshot_matches_its_node() -> None:
    """冻结快照内部必须自洽——曾出现 nodeId=24 / sourceRuleId=R12 / nodeName 为 R24 的记录。"""
    from libs.business_pack import load_business_pack
    from libs.business_pack.clause_store import (
        bind_project_node_clause_packages,
        clause_package_snapshot_for_project_node,
        ensure_clause_state,
    )

    pack = load_business_pack("engineering_inspection_v1")
    state: dict = {}
    ensure_clause_state(state)
    project = {"id": "P-TEST-2", "businessPackId": pack["id"], "businessPackVersion": pack["version"]}
    bind_project_node_clause_packages(state, project, pack)

    for node_id in (12, 24, 25, 40):
        payload = clause_package_snapshot_for_project_node(state, "P-TEST-2", node_id)
        assert payload, f"节点 {node_id} 应有条款快照"
        assert payload["nodeId"] == node_id
        assert payload["sourceRuleId"] == f"R{node_id:02d}", (
            f"节点 {node_id} 快照 sourceRuleId={payload['sourceRuleId']}"
        )
        assert payload["packageId"] == f"CLAUSE-PKG-R{node_id:02d}"


def test_override_detection_covers_every_ai_verdict() -> None:
    """AI 建议用展示词、人工结论用业务词；不先归一就只有同名的「证据不足」能被判为推翻，
    最典型的「AI 判不符合 / 人工判满足要求」反而会记成未推翻。"""
    from apps.api.routes import AI_SUGGESTION_TO_OPINION_RESULT, REVIEW_OPINION_NODE_STATUS
    from libs.review_orchestrator.execution import SUGGESTION_RESULT_LABELS

    def overridden(ai_label: str, human_result: str) -> bool:
        equivalent = AI_SUGGESTION_TO_OPINION_RESULT.get(ai_label, ai_label)
        return bool(equivalent and equivalent in REVIEW_OPINION_NODE_STATUS and equivalent != human_result)

    assert overridden("建议不符合", "满足要求") is True
    assert overridden("建议满足要求", "需补正") is True
    assert overridden("建议不适用", "需补正") is True
    assert overridden("证据不足", "不适用") is True
    # 一致时不算推翻
    assert overridden("建议不符合", "需补正") is False
    assert overridden("建议满足要求", "满足要求") is False
    # 无法映射的建议（需专业判断/执行故障）不主张推翻
    assert overridden("需专业判断", "需补正") is False

    mappable = [v for v in SUGGESTION_RESULT_LABELS.values() if v in AI_SUGGESTION_TO_OPINION_RESULT]
    assert len(mappable) >= 4, "多数 AI 结论应能映射到人工结论词"


def test_field_correction_reaches_ocr_reading_tools() -> None:
    """字段级修正必须穿透到读 OCR 的确定性工具。

    最初的实现只覆盖 businessFacts，而 OCR 抽取值（如「证书编号」）由工具直接从
    解析结果读取，修正因此完全不生效——记录存下来了，判定却没变。
    """
    from libs.review_orchestrator.runtime_tools import apply_field_corrections_to_parse_results

    state = {
        "fact_corrections": [
            {
                "id": "FCOR-1",
                "projectId": "P-1",
                "nodeId": 24,
                "fieldId": "FIELD-24-001",
                "fieldName": "证书编号",
                "documentVersionId": "DV-1",
                "correctedValue": "TS6J-2024-99999",
                "status": "active",
            },
            {  # 其他节点的修正不得串入
                "id": "FCOR-2",
                "projectId": "P-1",
                "nodeId": 25,
                "fieldId": "FIELD-25-001",
                "fieldName": "证书编号",
                "documentVersionId": "DV-1",
                "correctedValue": "串入的值",
                "status": "active",
            },
        ]
    }
    results = [
        {
            "documentVersionId": "DV-1",
            "fields": [
                {"fieldName": "证书编号", "value": "TS6J-2024-03158"},
                {"fieldName": "姓名", "value": "王建国"},
            ],
        }
    ]
    patched = apply_field_corrections_to_parse_results(
        state, results, context={"reviewRun": {"projectId": "P-1", "nodeId": 24}}
    )
    fields = {f["fieldName"]: f for f in patched[0]["fields"]}
    assert fields["证书编号"]["value"] == "TS6J-2024-99999"
    assert fields["证书编号"]["originalValue"] == "TS6J-2024-03158"
    assert fields["证书编号"]["humanCorrected"] is True
    assert fields["姓名"]["value"] == "王建国", "未修正的字段不应被改动"
    assert results[0]["fields"][0]["value"] == "TS6J-2024-03158", "不得改动持久化状态"


def test_field_correction_does_not_leak_across_nodes() -> None:
    from libs.review_orchestrator.runtime_tools import apply_field_corrections_to_parse_results

    state = {
        "fact_corrections": [
            {
                "id": "FCOR-1",
                "projectId": "P-1",
                "nodeId": 24,
                "fieldId": "FIELD-1",
                "fieldName": "证书编号",
                "documentVersionId": "DV-1",
                "correctedValue": "改过的",
                "status": "active",
            }
        ]
    }
    results = [{"documentVersionId": "DV-1", "fields": [{"fieldName": "证书编号", "value": "原值"}]}]
    other = apply_field_corrections_to_parse_results(
        state, results, context={"reviewRun": {"projectId": "P-1", "nodeId": 25}}
    )
    assert other[0]["fields"][0]["value"] == "原值", "节点独立：其他节点不应受影响"

    revoked = apply_field_corrections_to_parse_results(
        {"fact_corrections": [{**state["fact_corrections"][0], "status": "revoked"}]},
        results,
        context={"reviewRun": {"projectId": "P-1", "nodeId": 24}},
    )
    assert revoked[0]["fields"][0]["value"] == "原值", "已撤销的修正不应生效"


def test_disabled_seal_detection_is_not_reported_as_no_seal(monkeypatch) -> None:
    """印章检测管线全关时，找不到印章说明的是「没查」而不是「没有」。

    印章是监检判定的关键证据；若此时仍返回 succeeded + sealCount 0，
    判定链会据此认为资料缺章，把未检测直接变成不符合。
    """
    from libs.review_orchestrator.runtime_tools import (
        recognize_document_seals,
        seal_detection_capability,
    )

    monkeypatch.setenv("AICHECK_ENABLE_PADDLEX_SEAL_PIPELINE", "false")
    monkeypatch.setenv("AICHECK_ENABLE_AGENTDESIGN_SEAL_OCR", "false")
    assert seal_detection_capability()["enabled"] is False

    result = recognize_document_seals({"ocr_parse_results": []}, {}, context={})
    assert result["status"] == "capability_disabled"
    assert result["sealCount"] is None, "不能报 0，那会被读成「确认没有印章」"
    assert any("seal_detection_disabled" in item for item in result["warnings"])

    monkeypatch.setenv("AICHECK_ENABLE_PADDLEX_SEAL_PIPELINE", "true")
    enabled = recognize_document_seals({"ocr_parse_results": []}, {}, context={})
    assert enabled["status"] == "succeeded"
    assert enabled["sealCount"] == 0, "管线启用时 0 是可信的结论"


def test_capability_disabled_is_not_overridden_by_other_passes() -> None:
    """未启用的检测维度不能被其他工具的 passed 盖过去。"""
    assert (
        aggregate_tool_results(
            [
                {"toolName": "recognize_signatures_and_seals", "status": "capability_disabled"},
                {"toolName": "check_required", "result": "passed"},
            ]
        )
        == "evidence_insufficient"
    )
    # 真实不符合仍优先于「没查」
    assert (
        aggregate_tool_results(
            [
                {"toolName": "recognize_signatures_and_seals", "status": "capability_disabled"},
                {"toolName": "check_required", "result": "failed"},
            ]
        )
        == "failed"
    )


def test_document_body_check_relies_on_content_hash_not_file_status() -> None:
    """空壳资料（建了记录但从未上传内容）不得被挂载或提交。

    fileStatus 在建档时就被写成「已上传」，对空壳同样成立，因此不能作为判据；
    版本上的内容哈希由 complete 阶段按对象存储实际字节算出，文件没落盘就没有值。
    """
    from apps.api.routes import document_body_uploaded

    shell_doc = {"id": "DOC-SHELL", "fileStatus": "已上传"}
    assert document_body_uploaded(shell_doc, {"id": "DV-SHELL", "hash": None}) is False
    assert document_body_uploaded(shell_doc, {"id": "DV-SHELL"}) is False
    assert document_body_uploaded(None, None) is False

    real_doc = {"id": "DOC-REAL", "fileStatus": "已上传"}
    assert document_body_uploaded(real_doc, {"id": "DV-REAL", "hash": "sha256-abc"}) is True
    # 即便 fileStatus 缺失，只要内容哈希在就算已上传
    assert document_body_uploaded({"id": "DOC-REAL"}, {"id": "DV", "hash": "sha256-abc"}) is True


def test_unuploaded_document_error_names_the_offending_files() -> None:
    """拒绝时要告诉用户是哪几份资料没传上去，否则无从下手。"""
    from apps.api.routes import unuploaded_document_error

    response = unuploaded_document_error(
        _request_stub(),
        [
            ({"id": "DOC-1", "fileName": "焊工证.pdf"}, {"hash": "sha256-ok"}),
            ({"id": "DOC-2", "fileName": "射线检测报告.pdf"}, {"hash": None}),
        ],
    )
    assert response is not None
    payload = json.loads(bytes(response.body).decode())
    assert payload["data"]["reason"] == "DOCUMENT_BODY_MISSING"
    assert "射线检测报告.pdf" in payload["message"]
    assert "焊工证.pdf" not in payload["message"], "已上传成功的资料不应被列为问题项"
    assert [item["documentId"] for item in payload["data"]["missingDocuments"]] == ["DOC-2"]

    assert unuploaded_document_error(_request_stub(), [({"id": "DOC-1"}, {"hash": "sha256-ok"})]) is None


def _request_stub():
    from starlette.datastructures import Headers

    class _Stub:
        url = type("U", (), {"path": "/api/test"})()
        headers = Headers({})
        method = "POST"
        state = type("S", (), {})()

    return _Stub()


def test_role_action_matrix_declares_report_view_only_for_intended_roles() -> None:
    """角色动作表是权限意图的声明；读端点当前不校验它，二者的差距需要显式可见。

    inspection/owner/admin 声明了 report:view；contractor/ndt 没有。
    若未来给 contractor 加上 report:view，应是有意为之而非顺手添加。
    """
    from libs.business_pack import load_business_pack

    pack = load_business_pack("engineering_inspection_v1")
    actions = {r["code"]: set(r.get("actions") or []) for r in pack["roles"]}

    assert "report:view" in actions["inspection"]
    assert "report:view" in actions["owner"]
    assert "report:view" not in actions["contractor"], "施工方不应声明报告查看权"
    assert "report:view" not in actions["ndt"], "无损检测机构不应声明报告查看权"


def test_suggestion_result_labels_cover_all_aggregate_values() -> None:
    for value in ("passed", "failed", "evidence_insufficient", "not_applicable", "human_review_required", "execution_error"):
        assert value in SUGGESTION_RESULT_LABELS


# ------------------------------------------------------------ issue #5 D-1


def test_fact_correction_lifecycle_with_audit() -> None:
    saved = assert_ok(
        client.post(
            "/projects/P-2026-HDCP-001/inspection/nodes/24/fact-corrections",
            json={
                "factPath": "welderCertificate.certificateNo",
                "originalValue": "T2026-O01",
                "correctedValue": "TS2026-001",
                "reason": "OCR 把 S 识别成 5。",
            },
        )
    )
    correction = saved["correction"]
    assert saved["auditLogId"]
    assert correction["status"] == "active"
    assert correction["correctedBy"]
    assert repo.find_one("audit_logs", saved["auditLogId"]) is not None

    # 同 factPath 再次修正 → 旧记录被 supersede
    second = assert_ok(
        client.post(
            "/projects/P-2026-HDCP-001/inspection/nodes/24/fact-corrections",
            json={"factPath": "welderCertificate.certificateNo", "correctedValue": "TS2026-002"},
        )
    )
    assert correction["id"] in second["correction"]["supersedes"]
    listed = assert_ok(client.get("/projects/P-2026-HDCP-001/inspection/nodes/24/fact-corrections?status=active"))
    assert [item["id"] for item in listed] == [second["correction"]["id"]]

    # 撤销
    revoked = assert_ok(
        client.post(
            f"/projects/P-2026-HDCP-001/inspection/nodes/24/fact-corrections/{second['correction']['id']}/revoke",
            json={},
        )
    )
    assert revoked["correction"]["status"] == "revoked"


def test_fact_correction_rejects_invalid_path() -> None:
    response = client.post(
        "/projects/P-2026-HDCP-001/inspection/nodes/24/fact-corrections",
        json={"factPath": "a..b; drop", "correctedValue": "x"},
    )
    assert response.json()["code"] != 0


def test_fact_corrections_overlay_only_target_node() -> None:
    from libs.review_orchestrator.execution import apply_node_fact_corrections

    state = {
        "fact_corrections": [
            {
                "id": "FCOR-1",
                "projectId": "P-1",
                "nodeId": 24,
                "factPath": "welderCertificate.certificateNo",
                "correctedValue": "TS2026-001",
                "status": "active",
                "createdAt": "2026-08-07T00:00:00Z",
            },
            {
                "id": "FCOR-2",
                "projectId": "P-1",
                "nodeId": 25,
                "factPath": "weldingProcedure.wpsNo",
                "correctedValue": "WPS-9",
                "status": "active",
                "createdAt": "2026-08-07T00:00:00Z",
            },
            {
                "id": "FCOR-3",
                "projectId": "P-1",
                "nodeId": 24,
                "factPath": "welderCertificate.validUntil",
                "correctedValue": "2027-01-01",
                "status": "revoked",
                "createdAt": "2026-08-07T00:00:00Z",
            },
        ]
    }
    facts = {"welderCertificate": {"certificateNo": "T2026-O01"}}
    applied = apply_node_fact_corrections(state, "P-1", 24, facts)

    # 仅本节点、仅 active 的修正生效（节点独立原则）
    assert facts["welderCertificate"]["certificateNo"] == "TS2026-001"
    assert "validUntil" not in facts["welderCertificate"]
    assert "weldingProcedure" not in facts
    assert [item["correctionId"] for item in applied] == ["FCOR-1"]


# ---- M-12：建设方「总体进度」曾写死 42% ----


def test_m12_owner_progress_reflects_real_node_settlement() -> None:
    """总体进度必须来自节点办结情况，而不是常量。

    建设方看板上这是唯一的核心指标，写死意味着无论项目实际办到哪一步都显示同一个数。
    口径与 project_overview 的 nodeSummary 一致：已通过 / 不适用 记为已办结，停用不参与统计。
    """
    from apps.api.routes import project_progress_display, project_progress_percent

    # 全部办结
    assert project_progress_percent([{"status": "已通过"}, {"status": "不适用"}]) == 100
    # 一项未办结
    assert project_progress_percent([{"status": "已通过"}, {"status": "需补正"}]) == 50
    # 一项未办
    assert project_progress_percent([{"status": "待审查"}, {"status": "待提交"}]) == 0
    # 停用节点不拉低分母
    assert project_progress_percent([{"status": "已通过"}, {"status": "停用"}]) == 100
    # 没有可统计节点时不得显示 0%——那会被读成「一项没办」
    assert project_progress_percent([]) is None
    assert project_progress_percent([{"status": "停用"}]) is None
    assert project_progress_display([]) == "—"
    assert project_progress_display([{"status": "已通过"}, {"status": "需补正"}]) == "50%"

    # 端到端：进度必须随节点办结情况变化，而不是恒定值
    project_id = "P-2026-HDCP-001"
    headers = {"X-Dev-Role": "owner", "X-Dev-User": "USR-OWNER-001"}

    def read_progress() -> str:
        response = client.get(
            f"/api/projects/{project_id}/workbench/summary",
            params={"role": "owner"},
            headers=headers,
        )
        assert response.status_code == 200
        return {item["key"]: item["value"] for item in response.json()["data"]["metrics"]}["progress"]

    nodes = [item for item in repo.state["tree_nodes"] if item.get("projectId") == project_id]
    assert nodes, "演示项目应有监检节点，否则本用例无法验证进度随办结变化"
    before = read_progress()

    target = next(item for item in nodes if item.get("status") != "已通过")
    original_status = target.get("status")
    try:
        target["status"] = "已通过"
        after = read_progress()
    finally:
        target["status"] = original_status

    assert before != after, "办结一个节点后进度必须变化——恒定值说明又被写死了"
    assert after.endswith("%")
    settled = len([item for item in nodes if item.get("status") in {"已通过", "不适用"}]) + 1
    assert after == f"{round(settled / len(nodes) * 100)}%"
    assert read_progress() == before


# ---- U-5 补漏：台账行（projectFiles）此前不带本体标记 ----


def test_u5_project_file_rows_carry_body_uploaded_flag() -> None:
    """节点包里的台账行必须带 bodyUploaded。

    此前只有 bindings 带这个标记，台账行没有，于是一份从未上传成功的资料
    在施工方台账里永远显示「上传中」——看不出该重传，只有点了提交才会撞到
    DOCUMENT_BODY_MISSING。前端的「上传失败 / 重新上传 / 禁用提交」全部依赖这个字段。
    """
    headers = {"X-Dev-Role": "contractor", "X-Dev-User": "USER-CONTRACTOR-001"}
    project_id = "P-2026-HDCP-001"

    session = client.post(
        f"/api/projects/{project_id}/documents/upload-session",
        headers={**headers, "Idempotency-Key": "u5-projectfile-flag"},
        json={
            "files": [
                {
                    "fileName": "从未上传成功的资料.pdf",
                    "fileSize": 1024,
                    "contentType": "application/pdf",
                }
            ]
        },
    )
    assert session.status_code == 200, session.text
    # 故意不 PUT 任何内容：只有记录，没有本体。
    empty_document_id = session.json()["data"]["uploadUrls"][0]["documentId"]

    node_id = next(
        item
        for item in repo.state["tree_nodes"]
        if item.get("projectId") == project_id
    )["nodeId"]
    package = client.get(
        f"/api/projects/{project_id}/nodes/{node_id}/package",
        headers=headers,
    )
    assert package.status_code == 200, package.text
    project_files = package.json()["data"]["projectFiles"]

    rows = {str(item["id"]): item for item in project_files}
    assert empty_document_id in rows, "新建的资料应出现在施工方台账里"
    assert "bodyUploaded" in rows[empty_document_id]
    assert rows[empty_document_id]["bodyUploaded"] is False

    # 其余每一行都必须带上该字段，不能只在空壳这一行出现
    assert all("bodyUploaded" in item for item in project_files)


# ---- #18：建设方只能读已定稿的监检报告 ----


def _owner_headers() -> dict[str, str]:
    return {"X-Dev-Role": "owner", "X-Dev-User": "USER-OWNER-001", "X-Role": "owner"}


def _inspection_headers() -> dict[str, str]:
    return {"X-Dev-Role": "inspection", "X-Dev-User": "USER-INSPECTION-001", "X-Role": "inspection"}


def test_issue18_owner_only_reads_settled_reports() -> None:
    """报告在签发前是监检机构的内部工作稿，可能被推翻，不应对建设方开放。

    覆盖全部读取入口——只堵列表不堵详情等于没堵，因为正文在详情端点上。
    """
    project_id = "P-2026-HDCP-001"
    reports = [item for item in repo.state["reports"] if item.get("projectId") == project_id]
    assert reports, "演示项目应有报告，否则本用例验不到任何东西"

    draft = reports[0]
    draft["status"] = "复核中"
    settled_id = None
    if len(reports) > 1:
        reports[1]["status"] = "已签发"
        settled_id = reports[1]["id"]

    def ids(response) -> set[str]:
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        items = data if isinstance(data, list) else data.get("reports") or []
        return {str(item["id"]) for item in items}

    owner_listed = ids(client.get(f"/api/projects/{project_id}/reports", headers=_owner_headers()))
    assert draft["id"] not in owner_listed
    if settled_id:
        assert settled_id in owner_listed

    owner_dashboard = ids(
        client.get(f"/api/projects/{project_id}/owner/reports", headers=_owner_headers())
    )
    assert draft["id"] not in owner_dashboard

    archive = ids(
        client.get(f"/api/projects/{project_id}/archive/package", headers=_owner_headers())
    )
    assert draft["id"] not in archive

    # 正文端点：未定稿报告对建设方按不存在处理（403 会确认「有一份尚未签发的报告」）
    detail = client.get(
        f"/api/projects/{project_id}/reports/{draft['id']}", headers=_owner_headers()
    )
    assert detail.status_code == 200
    assert detail.json()["code"] == 40404, detail.text

    # 监检自己仍然读得到——这是他们的工作稿
    inspection_listed = ids(
        client.get(f"/api/projects/{project_id}/reports", headers=_inspection_headers())
    )
    assert draft["id"] in inspection_listed
    inspection_detail = client.get(
        f"/api/projects/{project_id}/reports/{draft['id']}", headers=_inspection_headers()
    )
    assert inspection_detail.json()["code"] == 0


def test_issue18_settled_report_stays_readable_for_owner() -> None:
    """别把建设方彻底挡在报告之外：已签发/已归档必须照常可读。"""
    project_id = "P-2026-HDCP-001"
    report = next(item for item in repo.state["reports"] if item.get("projectId") == project_id)
    for status in ("已签发", "已归档"):
        report["status"] = status
        detail = client.get(
            f"/api/projects/{project_id}/reports/{report['id']}", headers=_owner_headers()
        )
        assert detail.json()["code"] == 0, f"{status} 应对建设方可读"


# ---- #11：认证默认值必须是「开启」 ----


def test_issue11_auth_is_required_by_default(monkeypatch) -> None:
    """漏配 AICHECK_REQUIRE_AUTH 时必须表现为「登不进去」，不能是「谁都能进」。

    关闭认证会连带使项目隔离、节点范围、角色校验全部失效——authorized_node_scope
    与 member_node_scope_error 在无登录身份时直接放行，任何客户端都能用
    X-Role/X-User-Id 请求头冒充任意身份。默认值一旦是 false，一次漏配就是全量越权。
    """
    from libs.security.auth import authentication_enforced

    monkeypatch.delenv("AICHECK_REQUIRE_AUTH", raising=False)
    assert authentication_enforced() is True, "未配置时必须默认要求认证"

    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "false")
    assert authentication_enforced() is False, "本地开发显式关闭仍要生效"

    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")
    assert authentication_enforced() is True


def test_issue11_no_module_reads_require_auth_with_false_default() -> None:
    """默认值只允许有一处。

    改之前这个开关散在 7 个地方各写一遍 os.getenv(..., "false")，翻转默认值必须
    七处同改、漏一处就留一个后门。现在统一走 authentication_enforced()，此用例防止回流。
    """
    import pathlib

    backend = pathlib.Path(__file__).resolve().parent.parent
    offenders = [
        str(path.relative_to(backend))
        for directory in ("apps", "libs")
        for path in (backend / directory).rglob("*.py")
        if 'AICHECK_REQUIRE_AUTH", "false"' in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"这些文件仍在自带 false 默认值，应改用 authentication_enforced()：{offenders}"


# ---- #18 真身：施工方/无损检测机构本就不该读监检报告 ----


def test_issue18_roles_without_report_view_cannot_read_reports() -> None:
    """roles.yaml 只给 inspection / owner 发了 report:view，接口必须照此执行。

    改之前：报告与归档的「读」完全不进动作检查——只有 PATCH/POST 被推断出动作码，
    GET 直接放行。施工方能 GET 到监检报告全文、检验结论和证据链。
    这不是新增业务规则，是让实现追上早就写好的角色动作表。
    """
    project_id = "P-2026-HDCP-001"
    report_id = next(
        item["id"] for item in repo.state["reports"] if item.get("projectId") == project_id
    )

    def headers(role: str, user: str) -> dict[str, str]:
        return {"X-Dev-Role": role, "X-Dev-User": user, "X-Role": role}

    for role, user in (("contractor", "USER-CONTRACTOR-001"), ("ndt", "USER-NDT-001")):
        actions = set(repo.role_actions(role))
        assert "report:view" not in actions, f"{role} 的动作表若已授予 report:view，本用例前提失效"

        listed = client.get(f"/api/projects/{project_id}/reports", headers=headers(role, user))
        assert listed.json()["code"] == 403, f"{role} 不应读到报告列表：{listed.text}"

        detail = client.get(
            f"/api/projects/{project_id}/reports/{report_id}", headers=headers(role, user)
        )
        assert detail.json()["code"] == 403, f"{role} 不应读到报告正文：{detail.text}"

        archive = client.get(
            f"/api/projects/{project_id}/archive/package", headers=headers(role, user)
        )
        assert archive.json()["code"] == 403, f"{role} 不应读到归档包：{archive.text}"

    # 监检自己必须照常读得到，别把拦截做过头
    inspection = client.get(
        f"/api/projects/{project_id}/reports",
        headers=headers("inspection", "USER-INSPECTION-001"),
    )
    assert inspection.json()["code"] == 0
