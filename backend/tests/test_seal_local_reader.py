"""本地印章读字：宁可空着，不许猜。

## 线上实测（2026-08-16，服务器直接跑管线）

    layout_det_res: label=seal score=0.940
    rec_texts: ["中华人共和国国家质量监督检验检疫总局"]  rec_scores: [0.978]

**那个 0.978 里漏了一个「民」字。** 模型自报的置信度是它对自己的评价，
不是逐字正确率——同一枚章云端读出的是完整的「中华人民共和国…」。
所以本地识别结果照样只作候选证据，分数高不等于字对，这条要写在数据里
（recognitionSource / ocrConfidence），不能只留一个孤零零的名字。

## 判据

- 分数低于阈值宁可空着：印章认错一个单位名，比没认出来危险得多
- 服务调不通只记不抛：读不出字只是印章少个属性，不该让整份资料识别失败
- 字段名要和 structured_seals 的读法对齐（sealName / text），
  只写 name 会「看起来写了」而界面一个字都不显示
"""

from __future__ import annotations

from libs import seal_local_reader

IMAGES = {"images/seal-1.jpg": b"\xff\xd8\xff fake-jpeg"}


def _seal(**extra):
    return {"sealId": "S1", "imagePath": "images/seal-1.jpg", "pageNo": 1, **extra}


def test_读出来就写进印章并标注来源():
    seals = [_seal()]
    summary = seal_local_reader.read_seal_texts_locally(
        seals,
        IMAGES,
        reader=lambda payload, suffix=".jpg": {
            "ok": True,
            "text": "贵州化工建设有限责任公司",
            "score": 0.93,
        },
    )
    assert summary["recognized"] == 1
    assert seals[0]["sealName"] == "贵州化工建设有限责任公司"
    assert seals[0]["text"] == seals[0]["sealName"], "structured_seals 读的是 sealName/text"
    assert seals[0]["recognized"] is True
    assert seals[0]["recognitionSource"] == "local_seal_model"
    assert seals[0]["ocrConfidence"] == 0.93


def test_读不出就空着():
    seals = [_seal()]
    summary = seal_local_reader.read_seal_texts_locally(
        seals, IMAGES, reader=lambda payload, suffix=".jpg": {"ok": False, "text": "", "score": 0.1}
    )
    assert summary["illegible"] == 1
    assert not seals[0].get("sealName")
    assert seals[0]["recognized"] is False


def test_服务不通只记不抛():
    """读不出字只是印章少个属性，不该让整份资料识别失败。"""

    def boom(payload, suffix=".jpg"):
        raise RuntimeError("ocr-service 不可达")

    seals = [_seal()]
    summary = seal_local_reader.read_seal_texts_locally(seals, IMAGES, reader=boom)
    assert summary["failed"] == 1
    assert not seals[0].get("sealName")


def test_已有文字的章不重复读():
    seals = [_seal(sealName="已经认出来了", text="已经认出来了")]
    calls = []
    seal_local_reader.read_seal_texts_locally(
        seals, IMAGES, reader=lambda p, suffix=".jpg": calls.append(1) or {"ok": True, "text": "x", "score": 1}
    )
    assert calls == []


def test_找不到裁图就跳过():
    seals = [_seal(imagePath="images/不存在.jpg")]
    calls = []
    summary = seal_local_reader.read_seal_texts_locally(
        seals, IMAGES, reader=lambda p, suffix=".jpg": calls.append(1) or {"ok": True, "text": "x", "score": 1}
    )
    assert summary["skipped"] == 1 and calls == []


def test_开关关掉整体不跑():
    seals = [_seal()]
    summary = seal_local_reader.read_seal_texts_locally(
        seals,
        IMAGES,
        reader=lambda p, suffix=".jpg": {"ok": True, "text": "x", "score": 1},
        env={"AICHECK_ENABLE_LOCAL_SEAL_READING": "false"},
    )
    assert summary["skipped"] == 1
    assert not seals[0].get("sealName")


def test_低分不写值():
    """分数太低宁可空着——认错一个单位名比没认出来危险得多。"""
    import inspect

    source = inspect.getsource(seal_local_reader.read_seal_image)
    assert "_MIN_SEAL_SCORE" in source, "没有置信度下限，低分结果会被当成事实写进证据"
    assert seal_local_reader._MIN_SEAL_SCORE > 0


def test_编号碎片不算印章文字():
    """线上实测：射线检测报告第 4 页读出 "C33520"、分数 0.963。

    那是印章底弧上的编号被单独框出来了，不是单位名。**高分不等于内容对**——
    监检看到这一条既核不出单位，也不会怀疑它错，因为它带着 0.96 的分数。
    """
    seals = [_seal()]
    summary = seal_local_reader.read_seal_texts_locally(
        seals,
        IMAGES,
        reader=lambda p, suffix=".jpg": {
            "ok": False,
            "text": "",
            "score": 0.963,
            "rejected": "C33520",
            "reason": "seal_text_not_a_name",
        },
    )
    assert summary["illegible"] == 1
    assert not seals[0].get("sealName")
    assert "C33520" in seals[0]["recognitionNote"], "要说清模型读到了什么却没采用"


def test_像单位名的才算():
    assert seal_local_reader.looks_like_seal_name("贵州化工建设有限责任公司")
    assert seal_local_reader.looks_like_seal_name("国家市场监督管理总局")
    assert not seal_local_reader.looks_like_seal_name("C33520")
    assert not seal_local_reader.looks_like_seal_name("2021")
    assert not seal_local_reader.looks_like_seal_name("章")
    assert not seal_local_reader.looks_like_seal_name("")


def test_读不出的章要逐枚登记():
    """云端兜底要按枚补，不能因为同一份里有一枚读出来就放弃其余的。"""
    seals = [_seal(), {**_seal(), "sealId": "S2"}]
    summary = seal_local_reader.read_seal_texts_locally(
        seals,
        IMAGES,
        reader=lambda p, suffix=".jpg": {"ok": False, "text": "", "score": 0.1},
    )
    assert summary["illegible"] == 2
    assert len(summary.get("pendingSealIds") or []) == 2


def test_逐页扫描按页判重():
    """两条链路坐标系不同（MinerU 归一化到 1000 vs 渲染像素），
    拿 bbox 比大小会得出看似精确实则无意义的结论。按页判重，宁可少补一枚。"""
    seals = [{"sealId": "MINERU-1", "pageNo": 2, "sealName": "已有的章"}]
    scanned = [
        {"pageNo": 2, "text": "重复的章", "score": 0.9, "bbox": [1, 2, 3, 4]},
        {"pageNo": 1, "text": "封面漏掉的章", "score": 0.88, "bbox": [5, 6, 7, 8]},
        {"pageNo": 5, "text": "", "score": 0.0, "bbox": [9, 9, 9, 9]},
    ]
    summary = seal_local_reader.merge_scanned_seals(seals, scanned)

    assert summary["added"] == 2, "第 2 页已有章，不该重复添加"
    assert summary["recognizedByScan"] == 1
    pages = sorted(int(x["pageNo"]) for x in seals)
    assert pages == [1, 2, 5]
    added = next(x for x in seals if x["pageNo"] == 1)
    assert added["sealName"] == "封面漏掉的章"
    assert added["recognitionSource"] == "local_seal_model"
    blank = next(x for x in seals if x["pageNo"] == 5)
    assert blank["recognized"] is False
    assert "请对照原图确认" in blank["recognitionNote"], "检出但没读出也要说清楚"
    assert blank["canSatisfyRequiredSeal"] is False


def test_扫描出来的章不能自动满足必盖章要求():
    seals: list = []
    seal_local_reader.merge_scanned_seals(
        seals, [{"pageNo": 1, "text": "某某公司公章", "score": 0.99, "bbox": [1, 1, 2, 2]}]
    )
    assert seals[0]["canSatisfyRequiredSeal"] is False
    assert seals[0]["candidateOnly"] is True


def test_触发判据看可信识别而不是有没有文字():
    """云端兜底会写 sealName 但 recognized=False。

    按「有没有文字」判，封面漏检的那份文档正好不会触发逐页扫描——
    而它恰恰是最需要扫的那一份。
    """
    import inspect
    from apps.worker import tasks

    source = inspect.getsource(tasks._scan_missed_seal_pages)
    assert 'item.get("recognized") is True' in source, "要按可信识别判，不能按有没有文字判"
    assert "seal_scan_enabled" in source, "要能关掉——每页几秒 CPU"
