"""锚定门发「引擎没给分」时，原子项怎么定。

validate_evidence_grounding 原来只会发 passed / evidence_insufficient。2026-09-11 起，
引擎不报置信度（MinerU VLM 通道，生产 59% 的字段）而证据位置齐、引文在时，它发
human_review_required。这个状态若混进 business_results，会排在业务工具的
evidence_insufficient 前面——生产实测节点 1：check_all_equal「比不了」、
check_date_covers「缺施工起止日期」的原子项全被抬成「请人判断」。

口径：锚定门只回答证据能不能落地。业务工具全部通过时它才有资格把 passed 降成
human_review_required；业务工具说不清的，还是说不清。
"""
from __future__ import annotations

from libs.review_tools.executor import aggregate_tool_results


def _g(result: str) -> dict:
    return {"toolName": "validate_evidence_grounding", "result": result}


def _t(name: str, result: str) -> dict:
    return {"toolName": name, "result": result}


def test_业务通过_证据没分_交人判断():
    assert aggregate_tool_results([_t("check_design_license_scope", "passed"), _g("human_review_required")]) == "human_review_required"


def test_业务通过_证据有分_照旧通过():
    assert aggregate_tool_results([_t("check_design_license_scope", "passed"), _g("passed")]) == "passed"


def test_业务说不清_证据没分_仍是说不清():
    """节点 1 实测的三种：比不了 / 缺日期 / 缺级别。没分不能把它们抬成「请人判断」。"""
    for tool in ("check_all_equal", "check_date_covers", "check_design_license_scope"):
        assert aggregate_tool_results([_t(tool, "evidence_insufficient"), _g("human_review_required")]) == "evidence_insufficient", tool


def test_业务不符合_证据没分_仍是不符合():
    assert aggregate_tool_results([_t("check_date_covers", "failed"), _g("human_review_required")]) == "failed"


def test_锚定门证据不足仍一票否决():
    """既有口径不变：grounding 不通过时 passed 也不可靠。"""
    assert aggregate_tool_results([_t("check_design_license_scope", "passed"), _g("evidence_insufficient")]) == "evidence_insufficient"
    assert aggregate_tool_results([_t("check_design_license_scope", "failed"), _g("evidence_insufficient")]) == "evidence_insufficient"


def test_只有锚定门的原子项_门说什么就是什么():
    """AC-R01-05 这类 evidence_gate：没有业务工具，结果就是门的结果。"""
    assert aggregate_tool_results([_t("locate_evidence_fragment", ""), _g("human_review_required")]) == "human_review_required"
    assert aggregate_tool_results([_t("locate_evidence_fragment", ""), _g("passed")]) == "passed"
    assert aggregate_tool_results([_t("locate_evidence_fragment", ""), _g("evidence_insufficient")]) == "evidence_insufficient"


def test_业务工具自己发的human_review_required不受影响():
    """R19 等业务工具本来就会发这个状态，优先级照旧在 evidence_insufficient 之前。"""
    assert aggregate_tool_results([_t("r19_judge", "human_review_required"), _t("other", "evidence_insufficient")]) == "human_review_required"
