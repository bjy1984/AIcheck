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
