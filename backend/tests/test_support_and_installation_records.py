"""R55 支吊架（每個支架一個對象）、R53 管道安裝記錄、R44 防腐記錄：交了記錄即適用，缺的欄位交人工不判不符合。

版面取自 GDLNG 交工資料第 15 頁（正向）、第 14 與 19 頁（豎排）的真實片段座標，各留兩條記錄。
"""
from __future__ import annotations

from collections import Counter

from libs.review_orchestrator.ndt_fact_builders import NDT_FACT_BUILDERS
from libs.review_tools.installation_domain_rules import (
    evaluate_r44_coating_construction,
    evaluate_r53_installation_connections,
    evaluate_r55_supports,
)


def _frag(text, x0, y0, x1, y1, confidence=1.0, page=15):
    return {"id": f"F-{page}-{x0}-{y0}-{text}", "pageNo": page, "text": text, "bbox": [x0, y0, x1, y1],
            "confidence": confidence}


SUPPORT_PAGE = [
    _frag("表A.0.9管道支吊架的安装记录", 194, 73, 403, 92, 0.5), _frag("工程编号：/", 95, 116, 145, 129, 0.5),
    _frag("坐标位移值偏差 （mm）", 277, 139, 363, 151, 0.5), _frag("管道标高偏差", 392, 133, 446, 145),
    _frag("弹簧", 463, 138, 483, 151, 0.5), _frag("管线编号 管架编号", 79, 149, 156, 160, 0.5),
    _frag("结构型式、型号、规格", 169, 149, 257, 161), _frag("（mm）", 408, 146, 429, 154, 0.3),
    _frag("备注", 495, 149, 515, 160), _frag("允许值", 271, 161, 302, 172), _frag("实测值", 334, 161, 361, 172),
    _frag("允许值 实测值", 387, 160, 452, 173, 0.3), _frag("调整值", 460, 160, 488, 172),
    _frag("PL8303", 82, 180, 114, 192, 0.5), _frag("PS-1", 127, 180, 150, 192),
    _frag("GI,T形支架，EL2.1m", 172, 182, 253, 195, 0.3), _frag("士5", 281, 182, 297, 193, 0.3),
    _frag("/", 343, 182, 351, 192, 0.5), _frag("士10", 391, 181, 413, 193, 0.5), _frag("6", 436, 182, 442, 191),
    _frag("/", 471, 182, 478, 192, 0.5),
    _frag("PL8306", 83, 284, 112, 294), _frag("PS-1", 127, 284, 149, 295, 0.5),
    _frag("G1,T形支架，BL.2.1m", 172, 284, 254, 296, 0.3), _frag("士5", 281, 283, 298, 296, 0.3),
    _frag("/", 342, 285, 352, 296, 0.3), _frag("士10", 391, 284, 412, 296, 0.3), _frag("5", 436, 284, 442, 294),
    _frag("/", 469, 284, 479, 296, 0.3),
    _frag("质量检查员： 王起 施工人员：万解 2021年4月1目", 90, 720, 520, 740, 0.3),
]

INSTALLATION_PAGE = [
    _frag("表A.0.6管道安装记录", 66, 346, 86, 496, page=14), _frag("序号", 137, 745, 148, 763, page=14),
    _frag("管线编号", 137, 692, 148, 728, page=14), _frag("管道等级", 137, 640, 148, 675, page=14),
    _frag("管道规格", 137, 590, 148, 625, page=14), _frag("焊接连接", 128, 520, 138, 557, page=14),
    _frag("转动口数 固定口数", 147, 495, 158, 575, 0.5, page=14), _frag("法兰连接", 128, 423, 139, 459, page=14),
    _frag("压力等级", 147, 454, 158, 497, 0.5, page=14), _frag("垫片材质", 147, 399, 158, 436, page=14),
    _frag("其他连接形式", 128, 317, 138, 372, page=14), _frag("机械接口", 147, 346, 158, 382, 0.5, page=14),
    _frag("坐标", 147, 267, 158, 286, page=14), _frag("标高", 147, 220, 156, 239, page=14),
    _frag("平直度", 147, 168, 156, 196, page=14), _frag("铅垂度", 147, 120, 156, 148, page=14),
    _frag("坡度", 145, 82, 156, 102, page=14),
    _frag("PL-8303-100", 165, 684, 175, 736, 0.5, page=14), _frag("MIB", 166, 650, 175, 667, 0.3, page=14),
    _frag("¢108x5.0", 165, 586, 175, 626, 0.5, page=14), _frag("14", 166, 508, 175, 521, page=14),
    _frag("PN16", 166, 461, 175, 482, 0.5, page=14), _frag("缠绕垫片", 165, 399, 176, 436, page=14),
    _frag("1.5", 165, 174, 176, 190, page=14),
    _frag("PL-8306-100", 183, 684, 194, 738, page=14), _frag("M1B", 185, 650, 193, 667, 0.3, page=14),
    _frag("¢108x5.0", 183, 586, 194, 626, 0.5, page=14), _frag("12", 183, 506, 196, 521, page=14),
    _frag("PN16", 183, 460, 196, 482, 0.5, page=14), _frag("缠绕垫片", 183, 399, 194, 436, page=14),
    _frag("1.6", 183, 174, 194, 190, page=14), _frag("2.2", 183, 126, 193, 142, page=14),
]


def _run(node, fragments, selected=None):
    state = {"documents": [{"id": "D", "projectId": "P", "tenantId": "T", "fileName": "交工资料.pdf"}],
             "versions": [{"id": "V", "documentId": "D", "tenantId": "T"}],
             "ocr_parse_results": [{"id": "O", "documentVersionId": "V", "tenantId": "T", "status": "success",
                                    "fragments": fragments, "tables": []}]}
    run = {"projectId": "P", "tenantId": "T", "nodeId": node, "reviewMode": "formal",
           "inputDocumentVersionIds": ["V"], "reviewRunId": "RUN", **({"selectedObjectIds": [selected]} if selected else {})}
    return NDT_FACT_BUILDERS[node](state, run)


def _results(tool, block):
    output = tool({"projectId": "P", **{key: block[key] for key in ("scope", "standardRules", "domains", "selectionIssues")}})
    return Counter(row["result"] for row in output["facts"]["processChecks"])


def test_each_support_is_its_own_object_named_by_line_and_support_number():
    block = _run(55, SUPPORT_PAGE)["r55"]["supports"]
    assert block["sourceIssues"] == ["r55_source_object_conflict"]
    assert [item["objectId"] for item in block["candidateObjects"]] == ["PL8303/PS-1", "PL8306/PS-1"]


def test_a_selected_support_is_applicable_and_only_its_written_type_passes():
    block = _run(55, SUPPORT_PAGE, "PL8306/PS-1")["r55"]["supports"]
    (domain,) = block["domains"]
    assert domain["applicable"] is True and domain["support"] == {"type": "G1,T形支架，BL.2.1m"}
    results = _results(evaluate_r55_supports, block)
    assert results["passed"] == 1 and "failed" not in results


def test_an_installation_record_with_a_flange_rating_opens_the_flange_checks_without_failing_them():
    block = _run(53, INSTALLATION_PAGE, "PL-8303-100")["r53"]["installationConnections"]
    (domain,) = block["domains"]
    assert domain["applicable"] is True and domain["installation"] == {"flangeJointPresent": True}
    output = evaluate_r53_installation_connections(
        {"projectId": "P", **{key: block[key] for key in ("scope", "standardRules", "domains", "selectionIssues")}})
    results = {row["code"]: row["result"] for row in output["facts"]["processChecks"]}
    # 法兰平行度、螺栓孔偏移要实测值，记录表上没有：未抽取交人工，不因空值判不符合。
    assert results["installationconnections_flange_parallelism_within_limit_not_extracted"] == "evidence_insufficient"
    assert "failed" not in results.values()



COATING_PAGE = [
    _frag("管道防腐施工及验收记录", 69, 334, 89, 505, page=19), _frag("基层表面处理", 182, 596, 194, 658, page=19),
    _frag("防腐面层", 183, 246, 197, 289, 0.5, page=19), _frag("隔离层", 183, 447, 194, 478, page=19),
    _frag("质量评定", 207, 104, 219, 146, page=19), _frag("检查结果", 211, 559, 226, 602, 0.5, page=19),
    _frag("管线号", 216, 712, 230, 744, page=19), _frag("层数或厚度 检验结果", 218, 170, 230, 270, 0.5, page=19),
    _frag("名称", 218, 310, 231, 333, page=19), _frag("检验结果", 218, 373, 231, 416, page=19),
    _frag("层数或厚度", 218, 428, 231, 482, page=19), _frag("名称", 218, 511, 231, 533, page=19),
    _frag("处理方法", 218, 630, 229, 672, page=19), _frag("（等级）", 224, 564, 235, 598, 0.5, page=19),
    _frag("PL8303-100", 251, 700, 265, 756, page=19), _frag("环氧富锌底漆", 252, 492, 266, 555, page=19),
    _frag("St3.0级", 252, 562, 265, 601, 0.5, page=19), _frag("喷砂除锈", 252, 630, 264, 672, page=19),
    _frag("符合施工质量要求", 253, 84, 265, 168, page=19), _frag("合格", 253, 180, 266, 202, page=19),
    _frag("二层/80 m", 253, 218, 264, 270, 0.3, page=19), _frag("丙烯酸聚氨脂面漆", 253, 280, 266, 363, 0.5, page=19),
    _frag("合格", 253, 383, 266, 406, page=19), _frag("二层/80 m", 253, 428, 264, 481, 0.3, page=19),
    _frag("PL8306-100", 274, 700, 288, 756, page=19), _frag("环氧富锌底漆", 274, 492, 288, 555, page=19),
    _frag("St3.0级", 274, 562, 288, 601, 0.5, page=19), _frag("喷砂除锈", 275, 629, 288, 672, page=19),
    _frag("丙烯酸聚氨脂面漆", 275, 280, 290, 363, page=19), _frag("合格", 275, 383, 290, 406, page=19),
    _frag("二层/80um", 275, 428, 287, 482, 0.5, page=19), _frag("合格", 276, 179, 290, 202, page=19),
    _frag("二层/80 m", 276, 218, 287, 272, 0.3, page=19), _frag("符合施工质量要求", 275, 84, 288, 166, page=19),
    _frag("质检员：王趁", 502, 265, 526, 358, 0.3, page=19),
]


def test_a_coating_record_names_its_topcoat_and_leaves_the_record_number_to_a_human():
    block = _run(44, COATING_PAGE, "PL8306-100")["r44"]["coatingConstruction"]
    (domain,) = block["domains"]
    assert domain["applicable"] is True and domain["coating"] == {"coatingType": "丙烯酸聚氨脂面漆"}
    output = evaluate_r44_coating_construction(
        {"projectId": "P", **{key: block[key] for key in ("scope", "standardRules", "domains", "selectionIssues")}})
    results = {row["code"]: row["result"] for row in output["facts"]["processChecks"]}
    assert results["coatingconstruction_coating_coatingtype"] == "passed"
    assert results["coatingconstruction_coating_recordno_not_extracted"] == "evidence_insufficient"
    assert "failed" not in results.values()
