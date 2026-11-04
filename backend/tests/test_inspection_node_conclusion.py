"""监检总览按工位分组：节点落到哪一组（2026-11-03 用户确认的口径）。"""
from __future__ import annotations

from libs.inspection_node_conclusion import node_conclusion, station_groups


def _run(*results: str, status: str = "waiting_human_review") -> dict:
    return {"reviewRunId": "RRUN-1", "status": status, "atomicCheckOutcomes": [
        {"atomicCheckId": f"AC-R09-0{index}", "result": result, "reason": "",
         "checks": [{"code": f"check_{index}", "passed": result == "passed"}]}
        for index, result in enumerate(results, 1)]}


def test_不符合优先_其次证据不足_其次需人工():
    assert node_conclusion(_run("passed", "evidence_insufficient", "failed"), None)["group"] == "failed"
    assert node_conclusion(_run("human_review_required", "evidence_insufficient"), None)["group"] == "needs_materials"
    assert node_conclusion(_run("passed", "human_review_required"), None)["group"] == "needs_human"


def test_失败原因带原子项和不过的检查码():
    reason = node_conclusion(_run("passed", "failed"), None)["reason"]
    assert reason == {"atomicCheckId": "AC-R09-02", "result": "failed", "reasonCode": None, "checkCodes": ["check_2"]}


def test_全部符合是AI判定待确认_全部不适用标不适用():
    passed = node_conclusion(_run("passed", "not_applicable"), None)
    assert passed["group"] == "passed" and passed["confirmed"] is False and passed["notApplicable"] is False
    assert node_conclusion(_run("not_applicable", "not_applicable"), None)["notApplicable"] is True


def test_人工结论优先于AI():
    confirmed = node_conclusion(_run("failed"), {"result": "满足要求"})
    assert confirmed["group"] == "passed" and confirmed["confirmed"] is True
    rejected = node_conclusion(_run("passed"), {"result": "需补正", "opinion": "壁厚表缺第 1 页"})
    assert rejected["group"] == "failed" and rejected["reason"] == {"humanOpinion": "壁厚表缺第 1 页"}


def test_没跑过或还在跑或失败都算未开始审核_并标出原因():
    assert node_conclusion(None, None) == {"reviewRunId": None, "atomicCounts": {}, "humanResult": None,
                                           "group": "not_started", "confirmed": False, "reason": None, "runState": None}
    assert node_conclusion(_run("passed", status="running"), None)["runState"] == "running"
    assert node_conclusion(_run("passed", status="failed_to_start"), None)["runState"] == "failed"


def test_工位清单固定A到I_覆盖69个节点():
    stations = station_groups()
    assert [item["stationId"] for item in stations] == list("ABCDEFGHI")
    nodes = [node for item in stations for node in item["nodeIds"]]
    assert len(nodes) == len(set(nodes)) == 69
