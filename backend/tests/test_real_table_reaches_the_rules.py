"""生產庫裡真實的、沒有 businessSchema 的表，要能一路走到規則手上。

表格內容原樣取自生產庫 ocr_parse_results（2026-09-10 抽出），不是造的。
"""

from copy import deepcopy

from libs.review_document_scope import freeze_document_scope
from libs.review_orchestrator.installation_domain_facts import build_r43_business_facts
from libs.review_orchestrator.ndt_table_facts import read_ndt_tables

CERTIFICATE_ROWS = [
    {
        "厂家": "河北圣天管件集团有限公司",
        "序号": "2",
        "元件名称": "不锈钢工业弯头",
        "材质/标准": "材质:S30408标准:HG/T20592-2009",
        "规格/炉批号": "规格:1.5D-90° Φ89*3.0",
        "制造许可证编号": "TS2713486-2026",
        "型式试验证书编号": "TSX71001920232199",
        "产品质量证明书编号": "ST202604061300001",
    },
    {
        "厂家": "福建宁德正上管业科技有限公司",
        "序号": "1",
        "元件名称": "不锈钢无缝钢管",
        "材质/标准": "材质:S30408标准:GB/T14976-2025",
        "规格/炉批号": "规格: Φ89×3.0 钢号:06Cr19Ni10(304)",
        "制造许可证编号": "TS2735332-2030",
        "型式试验证书编号": "TSX71101004320260043",
        "产品质量证明书编号": "20260213951",
    }
]


# 生产库 DV-D66DB781-V1 那张表的 html（2026-09-10 抽出，截到本文用到的两行）。
CERTIFICATE_HTML = (
    "<table><tr><td>序号</td><td>元件名称</td><td>材质/标准</td><td>规格/炉批号</td><td>厂家</td>"
    "<td>制造许可证编号</td><td>型式试验证书编号</td><td>监督检验证书编号</td><td>产品质量证明书编号</td></tr>"
    "<tr><td>1</td><td>不锈钢无缝钢管</td><td>材质:S30408标准:GB/T14976-2025</td>"
    "<td>规格: $\\Phi 89\\times 3.0$ 钢号:06Cr19Ni10(304)</td><td>福建宁德正上管业科技有限公司</td>"
    "<td>TS2735332-2030</td><td>TSX71101004320260043</td><td></td><td>20260213951</td></tr>"
    "<tr><td>2</td><td>不锈钢工业弯头</td><td>材质:S30408标准:HG/T20592-2009</td>"
    "<td>规格:1.5D-90° $\\Phi 89*3.0$</td><td>河北圣天管件集团有限公司</td>"
    "<td>TS2713486-2026</td><td>TSX71001920232199</td><td></td><td>ST202604061300001</td></tr></table>"
)


def state_and_run(rows=None, business_schema=None):
    table = {
        "tableId": "MINERU-TABLE-3DCDFCCFEC2D4D1C",
        "pageNo": 1,
        "bbox": [0, 0, 100, 100],
        "structureConfidence": 0.9,
        "normalizedRows": deepcopy(CERTIFICATE_ROWS if rows is None else rows),
        # 真实的 MinerU 表没有 contentMarkdown，只有引擎记录的 html；判据侧的引用
        # 引的就是它。fixture 不带这一项，等于造了一张现实中不存在的表。
        "html": CERTIFICATE_HTML if rows is None else None,
    }
    if business_schema:
        table["businessSchema"] = business_schema
    state = {
        "documents": [{"id": "MAT", "projectId": "P1", "tenantId": "T1"}],
        "versions": [{"id": "MAT-V1", "documentId": "MAT", "tenantId": "T1"}],
        "ocr_parse_results": [
            {"documentVersionId": "MAT-V1", "tenantId": "T1", "tables": [table]}
        ],
    }
    run = {"projectId": "P1", "tenantId": "T1", "nodeId": 43, "inputDocumentVersionIds": ["MAT-V1"]}
    run["documentScopeSnapshot"] = freeze_document_scope(run, state)
    return state, run


def test_an_unlabelled_real_table_is_recognised_at_read_time():
    state, run = state_and_run()
    run["selectedObjectIds"] = ["20260213951"]
    rows = read_ndt_tables(state, run, {"material_certificate_domains": "domains"}, node_id=43)["domains"]
    assert len(rows) == 1
    assert rows[0]["objectId"] == "20260213951"
    assert rows[0]["certificate"]["documentNo"] == "20260213951"
    assert rows[0]["certificate"]["materialGrade"] == "S30408"
    assert rows[0]["recordVersionId"] == "MAT-V1"
    assert rows[0]["evidenceRefs"][0]["documentVersionId"] == "MAT-V1"


def test_the_real_row_reaches_r43_as_a_scoped_domain():
    state, run = state_and_run()
    run["selectedObjectIds"] = ["20260213951"]
    facts = build_r43_business_facts(state, run)["r43"]["materialCertificate"]
    assert facts["scope"]["objectId"] == "20260213951"
    assert facts["domains"][0]["certificate"]["materialGrade"] == "S30408"
    assert facts["standardRules"]["domains"]["materialCertificate"]["checks"]


def test_a_table_ocr_already_labelled_is_left_alone():
    """既有分類優先；簽名只補 OCR 沒認出來的表，不覆蓋既有結論。"""
    state, run = state_and_run(business_schema="material_certificate_domains")
    rows = read_ndt_tables(state, run, {"material_certificate_domains": "domains"}, node_id=43)["domains"]
    # 走既有分類時原樣讀取，中文列名保留，不經簽名對映。
    assert {row["产品质量证明书编号"] for row in rows} == {"ST202604061300001", "20260213951"}


def test_an_unrelated_real_table_is_not_dragged_in():
    unrelated = [{"序号": "1", "核查项目": "设计/安装资质", "见证资料": "TS证", "完成状态(√/×)": "√"}]
    state, run = state_and_run(rows=unrelated)
    rows = read_ndt_tables(state, run, {"material_certificate_domains": "domains"}, node_id=43)["domains"]
    assert rows == []


def test_an_agent_judgment_completes_the_row_without_calling_a_model():
    """第 3 层的产出是记在 state 里的证据；事实构建只读它，不调模型。"""
    from libs.review_orchestrator.domain_judgment_store import COLLECTION

    state, run = state_and_run()
    state[COLLECTION] = [
        {
            "projectId": "P1", "nodeId": 43, "domain": "materialCertificate",
            "objectId": "20260213951", "recordVersionId": "MAT-V1",
            "values": {
                "certificate.certificatesAndMarksReviewed": True,
                "certificate.gradeMatchesSpecification": True,
            },
            "evidenceRefs": [{"documentVersionId": "MAT-V1", "pageNo": 1, "quotedText": "已审阅"}],
            "rejected": [],
        }
    ]
    run["selectedObjectIds"] = ["20260213951"]
    facts = build_r43_business_facts(state, run)["r43"]["materialCertificate"]
    certificate = facts["domains"][0]["certificate"]
    # 表格给的值仍在，agent 给的判断补上了。
    assert certificate["documentNo"] == "20260213951"
    assert certificate["materialGrade"] == "S30408"
    assert certificate["certificatesAndMarksReviewed"] is True


def test_a_multi_row_real_table_is_ambiguous_until_an_object_is_selected():
    """真实的核查记录一张表列全部元件；构建器不替人挑，工位要写明审哪一个。"""
    state, run = state_and_run()
    facts = build_r43_business_facts(state, run)["r43"]["materialCertificate"]
    assert facts["scope"] is None
    assert facts["domains"] == []
    assert "r43_source_object_conflict" in facts["sourceIssues"]


def test_selecting_one_object_narrows_the_real_table_to_that_row():
    state, run = state_and_run()
    run["selectedObjectIds"] = ["20260213951"]
    facts = build_r43_business_facts(state, run)["r43"]["materialCertificate"]
    assert facts["scope"]["objectId"] == "20260213951"
    assert len(facts["domains"]) == 1
    assert facts["domains"][0]["certificate"]["materialGrade"] == "S30408"
    assert "sourceIssues" not in facts


def test_selecting_an_object_that_is_not_in_the_table_yields_nothing_not_a_guess():
    state, run = state_and_run()
    run["selectedObjectIds"] = ["NOT-IN-TABLE"]
    facts = build_r43_business_facts(state, run)["r43"]["materialCertificate"]
    assert facts["domains"] == [] and facts["scope"] is None
    # 选了个不存在的对象不是"来源含糊"，是没有资料；两者的处置不同。
    assert "sourceIssues" not in facts


def test_the_real_row_reaches_the_frozen_criteria_not_just_the_facts():
    """之前只断言到 facts，执行计划这一步从没跑过——生产上正是这一步断的。"""
    from libs.business_pack import load_business_pack
    from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool, runtime_tool_catalog
    from libs.review_tools import compile_node_tool_plan, execute_node_tool_plan

    state, run = state_and_run()
    run["selectedObjectIds"] = ["20260213951"]
    facts = build_r43_business_facts(state, run)
    plan = compile_node_tool_plan(load_business_pack("engineering_inspection_v1"), "R43",
                                  available_tools={item["name"] for item in runtime_tool_catalog()})
    judgment = facts.get("judgment") or {}
    output = execute_node_tool_plan(
        plan, facts=facts, document_version_ids=run["inputDocumentVersionIds"],
        evidence_facts=judgment.get("claimedFacts") or [], evidence_refs=judgment.get("evidenceRefs") or [],
        tool_runner=lambda name, args: dispatch_runtime_tool(state, name, args, context={"reviewRun": run}),
    )
    frozen = next(tr for atomic in output["atomicResults"] for tr in atomic["toolResults"]
                  if tr.get("toolName") == "evaluate_r43_material_certificate")
    checks = {row["code"].lower(): row["result"] for row in frozen["facts"]["processChecks"]}
    # 1) 线接上了：没有 scope/domains 缺失
    assert not [c for c in checks if c.endswith("_scope_missing") or c.endswith("_domains_missing")], checks
    # 2) 表格给的两个必填项过了
    assert [r for c, r in checks.items() if "documentno" in c] == ["passed"], checks
    assert [r for c, r in checks.items() if "materialgrade" in c] == ["passed"], checks
    # 3) 三个判断布林没人填，判据如实报缺证据——这是第 3 层（agent）该补的，不是这里的 bug
    for judgment_code in ("certificates_and_marks_reviewed", "material_grade_matches_specification",
                          "required_heat_treatment_inspection_and_tests_done"):
        hits = [r for c, r in checks.items() if judgment_code in c]
        assert hits == ["evidence_insufficient"], (judgment_code, checks)
    assert output["result"] == "evidence_insufficient"


def test_the_reference_quotes_the_recorded_table_text_not_the_fields():
    state, run = state_and_run()
    run["selectedObjectIds"] = ["20260213951"]
    rows = read_ndt_tables(state, run, {"material_certificate_domains": "domains"}, node_id=43)["domains"]
    quote = rows[0]["evidenceRefs"][0]["quotedText"]
    assert quote.startswith("序号 | 元件名称 | 材质/标准")
    assert "20260213951" in quote and "<" not in quote
    # 映射后的字段名（certificate.documentNo 之类）不是原文，不该出现在引文里。
    assert "documentNo" not in quote and "materialGrade" not in quote
