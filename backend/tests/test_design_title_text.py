"""整本施工图的图签行被 OCR 还原成文字片段（整份只剩一张表）时，也要能按页分出文件类型。

2026-10-30 生产 ECD202 节点 4：34 页只有 1 张表，title_block_name 只看表格，每页都找不到图名，
整本一直按首页认成「图纸目录」，文件齐全性把管道特性表、布置图、材料表、强度计算书都报成没上传。"""
from __future__ import annotations

from libs.review_orchestrator.design_facts import (
    build_design_business_facts,
    bundled_design_sections,
    set_member_types,
    title_block_name,
)
from libs.review_tools.business_tools import check_document_set_completeness

REQUIRED = ["drawing_catalog", "design_specification", "pipeline_data_sheet", "pipeline_layout_drawing",
            "pipeline_material_list", "straight_pipe_strength_calculation"]


def row(page_no: int, drawing_name: str, extra: str = "") -> dict:
    return {"pageNo": page_no, "text": f"图名DWG NAME {drawing_name} {extra}设计分项UNIT 地上甲类储罐区2(含泵区) 项目名称PROJ. 珠海海瑞德制药有限公司"}


def body(page_no: int, text: str) -> dict:
    return {"pageNo": page_no, "text": text}


def ecd202_like_bundle() -> dict:
    fragments = [
        row(1, "图纸目录"), row(2, "图纸目录"),
        row(3, "安装设计说明"), body(4, "设计说明续页：管道特性表见 S301"), row(5, "管道材料设计说明"),
        row(6, "管道等级索引表"), row(7, "管道分支表", "图号DWG NO. HZ026Y-112-02-S014 "),
        row(8, "管道平面图EL±0.000mm~EL+1000mm平面"), body(9, "轴测图 OCR 没读出"),
        row(10, "管道特性表"), row(11, "综合材料表"), row(12, "管道强度计算书"), body(13, "计算书续页"),
    ]
    return {"documentVersionId": "DV-DRAWING", "status": "success", "tables": [], "fragments": fragments}


def test_title_comes_from_the_title_block_row_when_there_is_no_table():
    assert title_block_name({"tables": [], "fragments": [row(1, "管道特性表")]}) == "管道特性表"
    assert title_block_name({"tables": [], "fragments": [row(2, "管道分支表", "图号DWG NO. HZ026Y-112-02-S014 ")]}) == "管道分支表"
    assert title_block_name({"tables": [], "fragments": [row(3, "管道平面图EL±0.000mm~EL+1000mm平面")]}).startswith("管道平面图")


def test_words_in_body_text_and_catalog_headers_are_not_titles():
    assert title_block_name({"tables": [], "fragments": [body(1, "详见图名为管道特性表的图纸")]}) == ""
    assert title_block_name({"tables": [], "fragments": [body(1, "序号 图名 图号 页数 备注")]}) == ""
    assert title_block_name({"tables": [], "fragments": [body(1, "图名 图号 页数 设计分项")]}) == ""


def test_title_block_table_still_wins_over_text():
    from apps.ocr_service.engines import html_table_to_structure
    table = html_table_to_structure("<table><tr><td>图名DWG NAME</td><td>管道特性表</td></tr></table>")
    page = {"tables": [{"pageNo": 1, **table}], "fragments": [row(1, "安装设计说明")]}
    assert title_block_name(page) == "管道特性表"


def test_bundle_without_tables_is_split_by_the_text_title_rows():
    sections = bundled_design_sections(ecd202_like_bundle())
    assert sections["drawing_catalog"] == [1, 2]
    assert sections["design_specification"] == [3, 4, 5], "没有图名的续页跟前一页；管道材料设计说明也是设计说明"
    assert sections["pipeline_data_sheet"] == [10]
    assert sections["pipeline_material_list"] == [11]
    assert sections["strength_calculation"] == [12, 13]
    assert sections["pipeline_layout_drawing"] == [8, 9]
    assert 6 not in {page for pages in sections.values() for page in pages}, "认不出类型的页（管道等级索引表）不归任何一份"


def test_pipe_strength_calculation_sheet_counts_for_the_straight_pipe_requirement_only_in_the_set():
    assert set_member_types("strength_calculation", "管道强度计算书") == ["strength_calculation", "straight_pipe_strength_calculation"]
    assert set_member_types("strength_calculation", "L-101强度计算书.pdf") == ["strength_calculation"]
    assert set_member_types("pipeline_data_sheet", "管道特性表") == ["pipeline_data_sheet"]


def test_ecd202_like_bundle_passes_the_document_set_completeness_check():
    state = {
        "documents": [{"id": "D-1", "projectId": "P-1", "currentVersionId": "DV-DRAWING", "fileName": "施工图.pdf", "materialTypeCode": "design_document"}],
        "versions": [], "ocr_parse_results": [ecd202_like_bundle()],
    }
    run = {"projectId": "P-1", "nodeId": 4, "inputDocumentVersionIds": ["DV-DRAWING"]}
    document_set = build_design_business_facts(state, run)["designDocumentSet"]
    assert set(REQUIRED) <= set(document_set["uploadedDocumentTypes"])
    outcome = check_document_set_completeness({"requiredDocumentTypes": REQUIRED, **{k: document_set[k] for k in ("uploadedDocumentTypes", "parseableDocumentTypes")}})
    assert outcome["result"] == "passed"
    documents = build_design_business_facts(state, run)["designDocuments"]["documents"]
    assert {item["documentType"] for item in documents} >= {"strength_calculation"}, "文件本身的类型不改，R06 照旧按 strength_calculation 找它"


def test_whole_drawing_still_reported_as_a_catalog_when_no_page_has_a_title():
    plain = {"documentVersionId": "DV-X", "status": "success", "tables": [], "fragments": [body(1, "图纸目录 1 安装设计说明"), body(2, "续页")]}
    assert bundled_design_sections(plain) == {}


def test_unclassified_documents_turn_a_missing_type_into_insufficient_evidence_not_failed():
    """GDLNG 节点 4：7 张照片里 5 张认不出是什么文件，清单里的管道特性表等「没传」其实是没看出来。"""
    base = {"requiredDocumentTypes": REQUIRED, "uploadedDocumentTypes": ["drawing_catalog", "design_specification"],
            "parseableDocumentTypes": ["drawing_catalog", "design_specification"]}
    assert check_document_set_completeness(base)["result"] == "failed", "全都认得出而确实缺类型，照旧是不符合"
    with_unknown = check_document_set_completeness({**base, "unclassifiedDocumentCount": 5})
    assert with_unknown["result"] == "evidence_insufficient"
    assert all(item.get("reason") == "unclassified_documents_may_contain_it" for item in with_unknown["checks"] if not item["passed"])
    complete = check_document_set_completeness({"requiredDocumentTypes": REQUIRED, "uploadedDocumentTypes": REQUIRED,
                                                "parseableDocumentTypes": REQUIRED, "unclassifiedDocumentCount": 5})
    assert complete["result"] == "passed", "该有的都有，有认不出的文件也不影响通过"


def test_executor_hands_the_unclassified_count_to_the_completeness_tool():
    from libs.review_tools.executor import build_tool_arguments

    facts = {"designDocumentSet": {"uploadedDocumentTypes": ["drawing_catalog"], "parseableDocumentTypes": ["drawing_catalog"],
                                   "unclassified": [{"documentVersionId": "V-1"}, {"documentVersionId": "V-2"}]}}
    arguments = build_tool_arguments("check_document_set_completeness", {"parameters": {"requiredDocumentTypes": REQUIRED}},
                                     facts=facts, explicit={}, document_version_ids=[], evidence_facts=[], evidence_refs=[])
    assert arguments["unclassifiedDocumentCount"] == 2
