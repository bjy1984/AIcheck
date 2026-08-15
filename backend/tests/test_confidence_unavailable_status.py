"""引擎不报置信度 ≠ 置信度低。

## 线上实测（2026-08-15）

MinerU 通了之后，第一份真实许可证识别成功，5 个字段全部落成「低置信度」。
不是识别得差——MinerU 的 VLM 通道逐片就不给分数，适配层自己记了
`provider_confidence_unavailable`，数值仍是 0.0，落库时被
`confidence >= 0.85` 一刀切成「低置信度」。

代价不在这一份文件，在标记的可信度：审查员看到满屏「低置信度」，
要么逐条白费工核对，要么开始无视这个标记——而它本来是给真正可疑的字段
留的。**一个总是亮着的警告灯，等于没有警告灯。**

前端其实早就发现了不对（FileDetailDialog 里那段注释：189 条低置信度里
97 条压根没有数值），但只能在展示层补救。这次从源头改。

## 判据

- 引擎报了低分 → 低置信度（原行为不变）
- 引擎不报分数 → 置信度未知
- 两者都仍然进人工复核队列——**不能因为改了名字就放行**
"""

from __future__ import annotations

from libs.db.repository import repo


def _parse_result(*, reasons: list[str]) -> dict:
    return {
        "status": "success",
        "fragments": [
            {
                "fragmentId": "F1",
                "text": "中华人民共和国 特种设备安装改造维修许可证",
                "pageNo": 1,
                "bbox": [1, 2, 3, 4],
            }
        ],
        "tables": [],
        "fields": [
            {
                "fieldName": "许可证编号",
                "fieldValue": "TS2731234-2028",
                "pageNo": 1,
                "bbox": [1, 2, 3, 4],
                "confidence": 0.0,
                "extractionMethod": "mineru_vlm",
            }
        ],
        "quality": {"status": "usable", "reasons": reasons, "blockingReasons": []},
    }


def _apply(version_id: str, result: dict) -> list[dict]:
    document = {"id": f"DOC-{version_id}", "fileName": "许可证.pdf", "projectId": "P-TEST"}
    repo.state.setdefault("documents", []).append(document)
    repo.state.setdefault("extracted_fields", [])
    repo.state.setdefault("evidence_links", [])
    repo.apply_ocr_result(document["id"], version_id, result)
    return [
        item
        for item in repo.state["extracted_fields"]
        if item.get("documentVersionId") == version_id
    ]


def test_引擎不报分数标为置信度未知():
    fields = _apply("DV-UNKNOWN-V1", _parse_result(reasons=["provider_confidence_unavailable"]))
    assert fields, "字段没落库"
    assert fields[0]["reviewStatus"] == "置信度未知"


def test_引擎报了低分仍是低置信度():
    fields = _apply("DV-LOW-V1", _parse_result(reasons=[]))
    assert fields[0]["reviewStatus"] == "低置信度"


def test_两种状态都要进复核队列():
    """改名字不能顺手放行——门槛按数值判，两者数值都低于 0.85。"""
    from apps.api import routes

    source = routes.__dict__
    assert "置信度未知" in open(routes.__file__, encoding="utf-8").read(), (
        "路由侧没认这个状态，会漏掉一整类待复核字段"
    )
    assert source is not None
