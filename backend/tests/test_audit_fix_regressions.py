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


# ---- #16：LangGraph 图执行后 context 被自赋值清空 ----


def test_issue16_graph_execution_preserves_context_written_by_nodes() -> None:
    """图跑完后，节点写进 context 的证据链与判定结果必须还在。

    LangGraph 节点返回的 state["context"] 通常就是传进去的同一个对象。
    原实现先 context.clear() 再 update(output_state["context"])，两者同源，
    clear() 把待回写的数据一并抹掉——调用方拿到空 context，整条审查的证据链、
    规则结果、工具输出全部丢失，且不报错。
    """
    from libs.review_orchestrator.graph import execute_review_graph

    review_run = {"reviewRunId": "RRUN-ISSUE16"}
    context: dict[str, object] = {"initial": "kept"}
    steps = [{"key": "collect"}, {"key": "judge"}]

    def run_step(run, step_key, ctx):
        # 真实节点就是这样直接写传入的 context 对象
        ctx.setdefault("ruleResults", []).append(f"{step_key}:done")
        ctx[f"{step_key}Evidence"] = ["EV-1"]
        return {"status": "succeeded", "stepKey": step_key}

    def mark_graph_node(*_args, **_kwargs):
        return {}

    result = execute_review_graph(
        review_run,
        context,
        steps=steps,
        run_step=run_step,
        mark_graph_node=mark_graph_node,
    )

    assert result.get("runner") in {"langgraph", "manual"}
    assert context.get("initial") == "kept", "图执行不应抹掉调用方原有的 context"
    assert context.get("ruleResults") == ["collect:done", "judge:done"], (
        f"节点写入的判定结果丢失：{context!r}"
    )
    assert context.get("collectEvidence") == ["EV-1"]
    assert context.get("judgeEvidence") == ["EV-1"]


# ---- M-9 / M-11：建设方（observer）读端点全开 ----


def test_m9_owner_cannot_read_review_process_data() -> None:
    """建设方在角色表里是 observer，审查过程不在其动作表内。

    改之前 owner 能读到：AI 逐条判定理由、监检人工结论、施工方被打回的整改往返。
    这些既不在动作表内，也让审查过程失去独立性。看结论（已签发报告、归档）才是其定位。
    """
    project_id = "P-2026-HDCP-001"
    owner = {"X-Dev-Role": "owner", "X-Dev-User": "USER-OWNER-001", "X-Role": "owner"}
    inspection = {
        "X-Dev-Role": "inspection",
        "X-Dev-User": "USER-INSPECTION-001",
        "X-Role": "inspection",
    }
    node_id = 24

    blocked = [
        (f"/api/projects/{project_id}/rectifications", "整改往返"),
        (f"/api/projects/{project_id}/inspection/nodes/{node_id}/ai-runs", "AI 运行记录"),
        (f"/api/projects/{project_id}/inspection/nodes/{node_id}/review-opinions", "人工结论"),
    ]
    for url, label in blocked:
        owner_response = client.get(url, headers=owner)
        assert owner_response.json()["code"] == 403, f"建设方不应读到{label}：{owner_response.text}"
        # 监检自己必须照常读得到，别把拦截做过头
        assert client.get(url, headers=inspection).json()["code"] == 0, f"监检应能读到{label}"

    # 节点包里同样不能夹带——只堵独立端点、节点包照漏等于没堵
    package = client.get(f"/api/projects/{project_id}/nodes/{node_id}/package", headers=owner)
    assert package.status_code == 200, package.text
    data = package.json()["data"]
    assert data["aiRuns"] == []
    assert data["aiRunTotal"] == 0
    assert data["reviewOpinions"] == []
    assert data["rectifications"] == []

    inspection_package = client.get(
        f"/api/projects/{project_id}/nodes/{node_id}/package", headers=inspection
    )
    assert inspection_package.status_code == 200


def test_m11_owner_cannot_see_unsubmitted_contractor_drafts() -> None:
    """施工方在正式提交前应有整理、替换、撤回的空间。

    改之前建设方看到的资料比监检还多，包含施工方挂上去但尚未提交的草稿。
    与监检同一口径：只有进入审查视野（已提交/需补正/已通过）的资料才对出资方可见。
    """
    project_id = "P-2026-HDCP-001"
    owner = {"X-Dev-Role": "owner", "X-Dev-User": "USER-OWNER-001", "X-Role": "owner"}
    contractor = {
        "X-Dev-Role": "contractor",
        "X-Dev-User": "USER-CONTRACTOR-001",
        "X-Role": "contractor",
    }

    session = client.post(
        f"/api/projects/{project_id}/documents/upload-session",
        headers={**contractor, "Idempotency-Key": "m11-draft-doc"},
        json={"files": [{"fileName": "施工方的草稿资料.pdf", "fileSize": 2048, "contentType": "application/pdf"}]},
    )
    assert session.status_code == 200, session.text
    draft_document_id = session.json()["data"]["uploadUrls"][0]["documentId"]

    def visible_ids(headers: dict[str, str]) -> set[str]:
        response = client.get(f"/api/projects/{project_id}/documents", headers=headers)
        assert response.status_code == 200, response.text
        return {str(item["id"]) for item in response.json()["data"]["items"]}

    assert draft_document_id in visible_ids(contractor), "施工方应看得到自己的草稿"
    assert draft_document_id not in visible_ids(owner), "建设方不应看到尚未提交的草稿"

    # 建设方仍应看到已进入审查视野的资料，别把台账清空
    submitted = [
        item
        for item in repo.state["documents"]
        if item.get("projectId") == project_id
        and str(item.get("poolSubmissionStatus") or "") == "已提交"
    ]
    if submitted:
        assert str(submitted[0]["id"]) in visible_ids(owner)


# ---- M-8：上传时声明的资料类型与归属节点被静默丢弃 ----


def test_m8_declared_material_type_and_nodes_are_persisted() -> None:
    """上传时声明的 materialTypeCode / nodeIds 必须落库。

    改之前：会话响应正常回显这两个字段，落库时 nodeId 为 None、materialTypeName 为
    None——资料仍是游离状态，上传方以为已归属、实际还要再手工挂一次。
    NDT 专用路径本就做对了（会话建好后回填 nodeId、按类型填名称），通用路径没接上，
    同一份资料从两条路进来长得不一样。
    """
    headers = {
        "X-Dev-Role": "contractor",
        "X-Dev-User": "USER-CONTRACTOR-001",
        "X-Role": "contractor",
    }
    project_id = "P-2026-HDCP-001"

    def upload(code: str, node_id: int, key: str) -> dict:
        response = client.post(
            f"/api/projects/{project_id}/documents/upload-session",
            headers={**headers, "Idempotency-Key": key},
            json={
                "files": [
                    {
                        "fileName": f"{key}.pdf",
                        "fileSize": 4096,
                        "contentType": "application/pdf",
                        "materialTypeCode": code,
                        "nodeIds": [node_id],
                    }
                ]
            },
        )
        assert response.status_code == 200, response.text
        document_id = response.json()["data"]["uploadUrls"][0]["documentId"]
        return repo.find_one("documents", document_id) or {}

    welder = upload("welder_certificate", 24, "m8-welder")
    assert welder["materialTypeCode"] == "welder_certificate"
    assert welder["materialTypeName"] == "焊工资格证", "类型名称应按业务包的 materialTypes 解析"
    assert welder["nodeId"] == 24, "声明的归属节点必须落库，否则资料仍是游离状态"

    ndt = upload("ndt_report", 40, "m8-ndt")
    assert ndt["materialTypeName"] == "无损检测报告"
    assert ndt["nodeId"] == 40

    # 业务包里没有的类型码不许瞎猜出名称
    unknown = upload("这个码不存在", 16, "m8-unknown")
    assert unknown["materialTypeName"] is None
    assert unknown["nodeId"] == 16


# ---- M-7 / M-10：说明文字传错字段名时静默丢弃 ----


def test_m7_explanation_alias_guard_only_fires_when_text_would_be_lost() -> None:
    """守卫只在「文本会丢」时开火，不能变成挑刺。

    传了正确字段（哪怕同时多带别名）就放行；一个都没传时不归本守卫管，
    必填与否由各端点自己定。
    """
    from apps.api.routes import unrecognized_explanation_field_error

    headers = {
        "X-Dev-Role": "inspection",
        "X-Dev-User": "USER-INSPECTION-001",
        "X-Role": "inspection",
    }

    def post_correction(payload: dict, key: str):
        return client.post(
            "/api/projects/P-2026-HDCP-001/inspection/nodes/24/fact-corrections",
            headers={**headers, "Idempotency-Key": key},
            json={
                "factPath": "welderCertificate.certificateNo",
                "correctedValue": "TS2026-888",
                **payload,
            },
        )

    # 正确字段 → 放行
    assert post_correction({"reason": "OCR 识别有误。"}, "m7-ok").json()["code"] == 0
    # 同时传了正确字段和别名 → 放行
    assert post_correction({"reason": "OCR 识别有误。", "note": "附注"}, "m7-both").json()["code"] == 0
    # 一个都没传 → 不被本守卫拦（该端点 reason 非必填）
    assert post_correction({}, "m7-none").json()["code"] == 0

    assert unrecognized_explanation_field_error is not None


def test_m7_rectification_endpoint_rejects_alias_end_to_end() -> None:
    headers = {
        "X-Dev-Role": "contractor",
        "X-Dev-User": "USER-CONTRACTOR-001",
        "X-Role": "contractor",
    }
    response = client.post(
        "/api/projects/P-2026-HDCP-001/rectifications",
        headers={**headers, "Idempotency-Key": "m7-alias"},
        json={"nodeId": 24, "bindingIds": [], "feedback": "已补充覆盖本工程焊接方法的焊工证。"},
    )
    assert response.json()["code"] == 40001, response.text
    assert "comment" in response.json()["message"]


def test_m10_fact_correction_reason_alias_is_rejected() -> None:
    """fact-corrections 是我自己新增的接口，同样有这个毛病，一并堵上。"""
    headers = {
        "X-Dev-Role": "inspection",
        "X-Dev-User": "USER-INSPECTION-001",
        "X-Role": "inspection",
    }
    response = client.post(
        "/api/projects/P-2026-HDCP-001/inspection/nodes/24/fact-corrections",
        headers={**headers, "Idempotency-Key": "m10-alias"},
        json={
            "factPath": "welderCertificate.certificateNo",
            "correctedValue": "TS2026-999",
            "note": "OCR 把 0 认成 O 了。",
        },
    )
    assert response.json()["code"] == 40001, response.text
    assert "reason" in response.json()["message"]


# ---- M-4 / M-5：空壳记录无可视区分；重复上传无去重提示 ----


def _upload_with_body(project_id: str, file_name: str, payload: bytes, key: str) -> str:
    headers = {
        "X-Dev-Role": "contractor",
        "X-Dev-User": "USER-CONTRACTOR-001",
        "X-Role": "contractor",
    }
    session = client.post(
        f"/api/projects/{project_id}/documents/upload-session",
        headers={**headers, "Idempotency-Key": f"{key}-session"},
        json={"files": [{"fileName": file_name, "fileSize": len(payload), "contentType": "application/pdf"}]},
    )
    assert session.status_code == 200, session.text
    target = session.json()["data"]["uploadUrls"][0]
    put = client.put(
        target["url"].removeprefix("/api"),
        headers={**headers, **target["headers"]},
        content=payload,
    )
    assert put.json()["code"] == 0, put.text
    import hashlib

    complete = client.post(
        f"/api/projects/{project_id}/documents/upload-session/{session.json()['data']['uploadSessionId']}/complete",
        headers={**headers, "Idempotency-Key": f"{key}-complete"},
        json={
            "completedFiles": [
                {
                    "documentVersionId": target["documentVersionId"],
                    "fileSize": len(payload),
                    "contentHash": hashlib.sha256(payload).hexdigest(),
                }
            ]
        },
    )
    assert complete.json()["code"] == 0, complete.text
    return complete.json()["data"]


def test_m4_document_ledger_marks_empty_shell_records() -> None:
    """只建会话、从不 PUT 内容的空壳记录，在台账里必须能一眼看出来。

    改之前它与真实资料在列表中无可视区分——业务红线写着「目录中列出文件不能等同于
    文件本体已上传」。
    """
    headers = {
        "X-Dev-Role": "contractor",
        "X-Dev-User": "USER-CONTRACTOR-001",
        "X-Role": "contractor",
    }
    project_id = "P-2026-HDCP-001"
    session = client.post(
        f"/api/projects/{project_id}/documents/upload-session",
        headers={**headers, "Idempotency-Key": "m4-shell"},
        json={"files": [{"fileName": "从未上传的文件.pdf", "fileSize": 1024, "contentType": "application/pdf"}]},
    )
    shell_id = session.json()["data"]["uploadUrls"][0]["documentId"]

    listing = client.get(f"/api/projects/{project_id}/documents", headers=headers)
    assert listing.status_code == 200, listing.text
    rows = {str(item["id"]): item for item in listing.json()["data"]["items"]}
    assert shell_id in rows
    assert rows[shell_id]["bodyUploaded"] is False
    assert all("bodyUploaded" in item for item in rows.values()), "每一行都要带标记，不能只标空壳那行"


def test_m5_repeated_upload_of_same_content_is_flagged() -> None:
    """同一份文件重复上传要提示，但不阻断——换版、补拍都是合法业务。"""
    project_id = "P-2026-HDCP-001"
    payload = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"

    first = _upload_with_body(project_id, "焊工证.pdf", payload, "m5-first")
    assert first["duplicates"] == [], "首次上传不应报重复"

    second = _upload_with_body(project_id, "焊工证-再传一次.pdf", payload, "m5-second")
    assert second["duplicates"], "内容相同的第二次上传应被标出"
    duplicate = second["duplicates"][0]
    assert duplicate["existingDocuments"], "应指出项目内已存在的同内容资料"
    assert "已存在" in duplicate["message"]

    # 内容不同则不报重复
    other = _upload_with_body(project_id, "另一份资料.pdf", payload + b"different", "m5-other")
    assert other["duplicates"] == []


# ---- M-6：打回后无法用新上传的资料补正 ----


def test_m6_rectification_accepts_newly_uploaded_material() -> None:
    """监检打回的典型理由就是「资料不对/不全，请补充」——施工方本应上传新资料。

    改之前：补正提交要求每个 binding 自身状态必须是「需补正」，而新上传并挂载的
    资料是「草稿挂载」，于是永远无法作为补正材料提交。施工方只能就原文件再提交
    一次（内容没变），或绕过整改单走普通提交，整改单与实际补正的资料就此脱钩。
    """
    contractor = {
        "X-Dev-Role": "contractor",
        "X-Dev-User": "USER-CONTRACTOR-001",
        "X-Role": "contractor",
    }
    inspection = {
        "X-Dev-Role": "inspection",
        "X-Dev-User": "USER-INSPECTION-001",
        "X-Role": "inspection",
    }
    project_id = "P-2026-HDCP-001"
    node_id = 24

    # 找一条本节点已被退回的绑定，并确认存在待反馈的补正单
    rectification = next(
        (
            item
            for item in repo.state["rectifications"]
            if item.get("projectId") == project_id
            and int(item.get("nodeId") or 0) == node_id
            and item.get("status") == "待反馈"
        ),
        None,
    )
    if rectification is None:
        # 走真实链路造出待反馈补正单：施工方挂载并提交 → 监检按该次提交退回。
        seed_session = client.post(
            f"/api/projects/{project_id}/documents/upload-session",
            headers={**contractor, "Idempotency-Key": "m6-seed-upload"},
            json={"files": [{"fileName": "待被打回的焊工证.pdf", "fileSize": 2048, "contentType": "application/pdf"}]},
        )
        seed_target = seed_session.json()["data"]["uploadUrls"][0]
        seed_payload = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
        assert client.put(
            seed_target["url"].removeprefix("/api"),
            headers={**contractor, **seed_target["headers"]},
            content=seed_payload,
        ).json()["code"] == 0
        assert client.post(
            f"/api/projects/{project_id}/documents/bindings",
            headers={**contractor, "Idempotency-Key": "m6-seed-bind"},
            json={"bindings": [{"documentId": seed_target["documentId"], "nodeId": node_id}]},
        ).json()["code"] == 0
        seed_binding_id = next(
            str(item["id"])
            for item in repo.state["bindings"]
            if str(item.get("documentId") or "") == seed_target["documentId"]
        )
        submitted = client.post(
            f"/api/projects/{project_id}/submissions",
            headers={**contractor, "Idempotency-Key": "m6-seed-submit"},
            json={"nodeIds": [node_id], "bindingIds": [seed_binding_id], "batchName": "M-6 打回前置提交"},
        )
        assert submitted.json()["code"] == 0, submitted.text
        returned = client.post(
            f"/api/projects/{project_id}/inspection/nodes/{node_id}/actions/return-correction",
            headers={**inspection, "Idempotency-Key": "m6-return"},
            json={
                "reason": "焊工证持证项目未覆盖本工程焊接方法，请补充。",
                "bindingIds": [seed_binding_id],
            },
        )
        assert returned.json()["code"] == 0, returned.text
        rectification = next(
            item
            for item in repo.state["rectifications"]
            if item.get("projectId") == project_id
            and int(item.get("nodeId") or 0) == node_id
            and item.get("status") == "待反馈"
        )

    # 施工方上传一份新资料并挂到同一节点——这就是「补充」的真实动作
    session = client.post(
        f"/api/projects/{project_id}/documents/upload-session",
        headers={**contractor, "Idempotency-Key": "m6-new-material"},
        json={
            "files": [
                {
                    "fileName": "补充的焊工证（覆盖本工程焊接方法）.pdf",
                    "fileSize": 4096,
                    "contentType": "application/pdf",
                }
            ]
        },
    )
    assert session.status_code == 200, session.text
    new_document_id = session.json()["data"]["uploadUrls"][0]["documentId"]
    target = session.json()["data"]["uploadUrls"][0]
    payload = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
    put = client.put(
        target["url"].removeprefix("/api"),
        headers={**contractor, **target["headers"]},
        content=payload,
    )
    assert put.json()["code"] == 0, put.text

    bind = client.post(
        f"/api/projects/{project_id}/documents/bindings",
        headers={**contractor, "Idempotency-Key": "m6-bind"},
        json={"bindings": [{"documentId": new_document_id, "nodeId": node_id}]},
    )
    assert bind.json()["code"] == 0, bind.text
    new_binding_id = next(
        str(item["id"])
        for item in repo.state["bindings"]
        if str(item.get("documentId") or "") == new_document_id
    )
    assert repo.find_one("bindings", new_binding_id)["bindingStatus"] == "草稿挂载"

    submitted = client.post(
        f"/api/projects/{project_id}/rectifications",
        headers={**contractor, "Idempotency-Key": "m6-submit"},
        json={
            "nodeId": node_id,
            "rectificationId": rectification["id"],
            "bindingIds": [new_binding_id],
            "comment": "已补充覆盖本工程焊接方法的焊工证。",
        },
    )
    assert submitted.json()["code"] == 0, f"新上传的资料应能作为补正材料提交：{submitted.text}"

    updated = repo.find_one("rectifications", rectification["id"])
    assert new_binding_id in (updated.get("bindingIds") or [])
    # 留痕：能追溯出这次补的是新资料而非原文件重提
    assert new_binding_id in (updated.get("replacementBindingIds") or [])
    assert updated["feedbackComment"] == "已补充覆盖本工程焊接方法的焊工证。"
    assert repo.find_one("bindings", new_binding_id)["bindingStatus"] == "已提交"


def test_m6_already_reviewed_material_still_cannot_be_resubmitted() -> None:
    """别把口径放得太宽：已在审查中或已通过的资料重复提交没有业务含义，仍要拒绝。"""
    contractor = {
        "X-Dev-Role": "contractor",
        "X-Dev-User": "USER-CONTRACTOR-001",
        "X-Role": "contractor",
    }
    project_id = "P-2026-HDCP-001"
    node_id = 24
    rectification = next(
        (
            item
            for item in repo.state["rectifications"]
            if item.get("projectId") == project_id
            and int(item.get("nodeId") or 0) == node_id
            and item.get("status") == "待反馈"
        ),
        None,
    )
    if rectification is None:
        return

    passed_binding = next(
        (
            item
            for item in repo.state["bindings"]
            if int(item.get("nodeId") or 0) == node_id and item.get("projectId") == project_id
        ),
        None,
    )
    if passed_binding is None:
        return
    original_status = passed_binding["bindingStatus"]
    try:
        passed_binding["bindingStatus"] = "已通过"
        response = client.post(
            f"/api/projects/{project_id}/rectifications",
            headers={**contractor, "Idempotency-Key": "m6-passed"},
            json={
                "nodeId": node_id,
                "rectificationId": rectification["id"],
                "bindingIds": [str(passed_binding["id"])],
                "comment": "试图重复提交已通过的资料。",
            },
        )
        assert response.json()["code"] == 40900, response.text
        assert "已通过" in response.json()["message"]
    finally:
        passed_binding["bindingStatus"] = original_status


# ---- 新发现：挂载时逐条声明的 nodeId 被忽略，全部落到默认节点 16 ----


def test_binding_honors_per_item_node_id() -> None:
    """每条 binding 自带的 nodeId 必须生效。

    改之前只看 body 顶层的 nodeId/nodeIds，逐条声明的节点被静默忽略，全部落到
    施工方的默认节点 16——调用方在界面上选了节点、资料却挂到别处，且请求返回成功。
    这也是审计里「大量资料都归到节点 16」这一现象的成因之一。
    """
    contractor = {
        "X-Dev-Role": "contractor",
        "X-Dev-User": "USER-CONTRACTOR-001",
        "X-Role": "contractor",
    }
    project_id = "P-2026-HDCP-001"
    payload = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"

    declared = []
    for index, node_id in enumerate((24, 25, 40)):
        session = client.post(
            f"/api/projects/{project_id}/documents/upload-session",
            headers={**contractor, "Idempotency-Key": f"bind-node-{index}"},
            json={"files": [{"fileName": f"资料-{node_id}.pdf", "fileSize": len(payload), "contentType": "application/pdf"}]},
        )
        target = session.json()["data"]["uploadUrls"][0]
        assert client.put(
            target["url"].removeprefix("/api"),
            headers={**contractor, **target["headers"]},
            content=payload,
        ).json()["code"] == 0
        declared.append((target["documentId"], node_id))

    response = client.post(
        f"/api/projects/{project_id}/documents/bindings",
        headers={**contractor, "Idempotency-Key": "bind-node-all"},
        json={"bindings": [{"documentId": document_id, "nodeId": node_id} for document_id, node_id in declared]},
    )
    assert response.json()["code"] == 0, response.text

    for document_id, node_id in declared:
        bound_nodes = [
            int(item["nodeId"])
            for item in repo.state["bindings"]
            if str(item.get("documentId") or "") == document_id
        ]
        assert bound_nodes == [node_id], (
            f"声明 nodeId={node_id} 的资料应且只应挂到该节点，实际 {bound_nodes}"
        )


# ---- M-1：资料自动分类准确率约 21% ----


def test_m1_classification_uses_business_pack_instead_of_hardcoded_stub() -> None:
    """分类必须来自业务包的节点资料要求，而不是「文件名含焊工→24，否则16」。

    原 stub 在真实素材下准确率约 21%（14 份里 11 份被归到节点 16），置信度恒为 0.82。
    按业务规模（单项目几千页），监检人员实际要手工重挂几乎全部资料。
    """
    from apps.api.routes import classify_document_to_nodes

    project_id = "P-2026-HDCP-001"
    # 审计当时用的真实素材文件名与其应归节点
    cases = [
        ("射线检测报告.pdf", 40),
        ("焊接工艺评定报告.pdf", 25),
        ("特种设备制造许可证-河北广浩.pdf", 12),
        ("特种设备安装改造维修许可证.pdf", 2),
        ("压力管道强度计算书.png", 6),
        ("产品质量证明part1.pdf", 16),
        ("焊工证.pdf", 24),
    ]
    for file_name, expected_node in cases:
        result = classify_document_to_nodes(project_id, {"id": "D", "fileName": file_name})
        assert expected_node in result["suggestedNodeIds"], (
            f"{file_name} 应能归到节点 {expected_node}，实际 {result['suggestedNodeIds']}"
        )
        assert result["confidence"] > 0.2

    # 认不出来时不许硬猜——猜错会把资料挂到错误节点，未分类只是让人工来定
    unknown = classify_document_to_nodes(project_id, {"id": "D", "fileName": "随手拍的现场照片.jpg"})
    assert unknown["suggestedNodeIds"] == []
    assert unknown["confidence"] == 0.2
    assert unknown["basis"] == "unclassified"

    # 上传时已声明类型码是明示，不是猜的，置信度应更高
    declared = classify_document_to_nodes(
        project_id, {"id": "D", "fileName": "随便什么名字.pdf", "materialTypeCode": "welder_certificate"}
    )
    assert 24 in declared["suggestedNodeIds"]
    assert declared["confidence"] == 0.95
    assert declared["basis"] == "declared_material_type"

    # 落库默认值不算明示声明
    generic = classify_document_to_nodes(
        project_id, {"id": "D", "fileName": "焊工证.pdf", "materialTypeCode": "generic_review_material"}
    )
    assert generic["basis"] == "file_name_match"


def test_m1_batch_classify_endpoint_no_longer_returns_constant_confidence() -> None:
    headers = {
        "X-Dev-Role": "contractor",
        "X-Dev-User": "USER-CONTRACTOR-001",
        "X-Role": "contractor",
    }
    response = client.post(
        "/api/projects/P-2026-HDCP-001/documents/batch-classify",
        headers={**headers, "Idempotency-Key": "m1-batch"},
        json={},
    )
    assert response.status_code == 200, response.text
    suggestions = response.json()["data"]["suggestions"]
    assert suggestions, "演示项目应有资料可分类"
    assert not all(item["confidence"] == 0.82 for item in suggestions), "置信度不应再是常量"
    assert all("basis" in item for item in suggestions), "每条建议都要说明依据"
    # 不再是「非 24 即 16」
    assert {node for item in suggestions for node in item["suggestedNodeIds"]} - {16, 24}


# ---- N-4：节点状态机无转移校验 ----


def test_n4_settled_node_cannot_be_dragged_back_to_the_start() -> None:
    """已办结的节点不能被无声改回流程起点。

    改之前 set_node_status 没有任何前置状态校验，15 个调用点互不知晓——
    已通过的节点可以被任意改回「待提交」，监检的终审结论就这么被推翻。
    """
    from libs.db.repository import IllegalNodeStatusTransition

    project_id = "P-2026-HDCP-001"
    node_id = 24
    node = repo.node(project_id, node_id)
    original = node["status"]
    try:
        for settled in ("已通过", "不适用"):
            node["status"] = settled
            for forbidden in ("待提交", "部分提交", "需补正"):
                try:
                    repo.set_node_status(project_id, node_id, forbidden)
                except IllegalNodeStatusTransition as error:
                    assert settled in str(error) and forbidden in str(error)
                else:
                    raise AssertionError(f"{settled} → {forbidden} 不应被允许")
                assert repo.node(project_id, node_id)["status"] == settled, "被拒后状态不能被改动"

            # 复审与 AI 重跑是显式的审查动作，必须仍然放行
            for reopenable in ("复审中", "业务核验中"):
                node["status"] = settled
                repo.set_node_status(project_id, node_id, reopenable)
                assert repo.node(project_id, node_id)["status"] == reopenable

        # 正常推进不受影响
        node["status"] = "待提交"
        repo.set_node_status(project_id, node_id, "待审查")
        assert repo.node(project_id, node_id)["status"] == "待审查"
        repo.set_node_status(project_id, node_id, "已通过")
        assert repo.node(project_id, node_id)["status"] == "已通过"
    finally:
        node["status"] = original


# ---- N-6：If-Match 缺省即放行 ----


def test_n6_high_risk_writes_require_if_match_by_default(monkeypatch) -> None:
    """不发 If-Match 就绕过乐观锁，并发写会无声推翻别人的结论。

    对「保存审查结论 / 打回补正 / 正式提交 / 归档」强制要求该头；默认开启，
    存量调用方迁移期可用 AICHECK_REQUIRE_IF_MATCH=false 暂时关闭。
    """
    from apps.api.routes import if_match_enforced, requires_if_match

    monkeypatch.delenv("AICHECK_REQUIRE_IF_MATCH", raising=False)
    assert if_match_enforced() is True, "默认必须是强制，漏配要 fail closed"

    class _Request:
        def __init__(self, method: str, path: str) -> None:
            self.method = method
            self.url = type("_Url", (), {"path": path})()

    high_risk = [
        "/api/projects/P1/inspection/nodes/24/review-opinions",
        "/api/projects/P1/inspection/nodes/24/actions/return-correction",
        "/api/projects/P1/submissions",
        "/api/projects/P1/reports/RPT-1/archive",
    ]
    for path in high_risk:
        assert requires_if_match(_Request("POST", path)) is True, path
        assert requires_if_match(_Request("GET", path)) is False, f"读操作不该被拦：{path}"

    # 名单之外的写端点保持缺省放行，避免一次性打破所有既有调用方
    assert requires_if_match(_Request("POST", "/api/projects/P1/documents/bindings")) is False

    monkeypatch.setenv("AICHECK_REQUIRE_IF_MATCH", "false")
    assert if_match_enforced() is False
    assert requires_if_match(_Request("POST", high_risk[0])) is False


def test_n6_missing_if_match_is_rejected_end_to_end(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_REQUIRE_IF_MATCH", "true")
    headers = {
        "X-Dev-Role": "inspection",
        "X-Dev-User": "USER-INSPECTION-001",
        "X-Role": "inspection",
    }
    body = {"result": "满足要求", "opinion": "资料齐全。", "evidenceLinkIds": []}

    without = client.post(
        "/api/projects/P-2026-HDCP-001/inspection/nodes/24/review-opinions",
        headers={**headers, "Idempotency-Key": "n6-without"},
        json=body,
    )
    assert without.json()["code"] == 40001, without.text
    assert without.json()["data"]["reason"] == "IF_MATCH_REQUIRED"

    # 带上就放行（"*" 是合法的 If-Match）
    with_header = client.post(
        "/api/projects/P-2026-HDCP-001/inspection/nodes/24/review-opinions",
        headers={**headers, "Idempotency-Key": "n6-with", "If-Match": "*"},
        json=body,
    )
    assert with_header.json()["code"] != 40001 or with_header.json()["data"].get("reason") != "IF_MATCH_REQUIRED"


# ---- issue #8 / D-2：哈希伪向量可静默混入知识索引 ----


def test_issue8_hash_pseudo_vectors_cannot_enter_the_index_silently(monkeypatch) -> None:
    """embedding 服务没配好时，不能悄悄用字符哈希伪向量顶上。

    哈希向量与真语义向量同表同维存储，仅索引版本不同——配置错误时系统照常运行，
    检索结果近似随机，使用方无从察觉。现在把它当配置错误：要用必须显式声明。
    """
    from apps.worker import tasks

    chunks = [{"text": "焊工资格证有效期覆盖施工周期。"}]

    class _DisabledClient:
        enabled = False
        model_id = ""
        index_version = ""
        dimensions = 0

    monkeypatch.setattr(tasks, "EmbeddingClient", lambda *a, **k: _DisabledClient())
    monkeypatch.delenv("AICHECK_EMBEDDING_FORCE_OFFLINE_HASH", raising=False)
    monkeypatch.delenv("AICHECK_EMBEDDING_ALLOW_HASH_FALLBACK", raising=False)

    try:
        tasks.embedding_batches_for_chunks(chunks)
    except RuntimeError as error:
        assert "embedding_client_not_configured" in str(error)
        assert "AICHECK_EMBEDDING_FORCE_OFFLINE_HASH" in str(error), "错误信息要告诉运维怎么办"
    else:
        raise AssertionError("未配置 embedding 服务时不应静默落哈希伪向量")

    # 显式声明离线自测 → 放行，但必须留下降级标记，否则索引里的哈希向量依旧不可辨认
    monkeypatch.setenv("AICHECK_EMBEDDING_FORCE_OFFLINE_HASH", "true")
    vectors, model, index_version, dimensions, fallback_reason = tasks.embedding_batches_for_chunks(chunks)
    assert vectors and dimensions > 0 and index_version
    assert fallback_reason == "forced_offline_hash_embedding"

    monkeypatch.delenv("AICHECK_EMBEDDING_FORCE_OFFLINE_HASH", raising=False)
    monkeypatch.setenv("AICHECK_EMBEDDING_ALLOW_HASH_FALLBACK", "true")
    _, _, _, _, fallback_reason = tasks.embedding_batches_for_chunks(chunks)
    assert fallback_reason == "embedding_client_disabled_hash_fallback"


def test_issue8_knowledge_overview_surfaces_degraded_vector_ratio() -> None:
    """知识管理页要能看出索引里有多少降级向量，否则问题永远不会被发现。"""
    headers = {"X-Dev-Role": "admin", "X-Dev-User": "USER-ADMIN-001", "X-Role": "admin"}
    response = client.get("/api/knowledge/overview", headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()["data"]

    quality = data["vectorQuality"]
    assert {"degradedFileCount", "vectorizedFileCount", "degradedRatio", "degradedFiles"} <= set(quality)
    assert {item["key"] for item in data["metrics"]} >= {"degradedVector"}

    # 造一个降级文件，占比要跟着变
    files = repo.state.get("knowledge_files") or []
    if not files:
        return
    target = files[0]
    original_status, original_reason = target.get("vectorStatus"), target.get("vectorStatusReason")
    try:
        target["vectorStatus"] = "已向量化"
        target["vectorStatusReason"] = "embedding_client_disabled_hash_fallback"
        refreshed = client.get("/api/knowledge/overview", headers=headers).json()["data"]
        assert refreshed["vectorQuality"]["degradedFileCount"] >= 1
        assert refreshed["vectorQuality"]["degradedRatio"] > 0
        assert any(
            item["fileId"] == target["id"] for item in refreshed["vectorQuality"]["degradedFiles"]
        )
    finally:
        target["vectorStatus"] = original_status
        target["vectorStatusReason"] = original_reason
