"""印章读字：只报看清的，读不出就说读不出。

MinerU 把印章框出来但不读字——线上那份许可证的印章 `name` 是空的，
界面只能显示「有一枚章，请自己看图」。监检确认「盖章了没有」靠的是章上的
单位名，所以这一步必须补上。

## 为什么宁可空着也不能猜

印章识别错一个字，可能就是把「贵州化工建设」认成另一家单位——
而这份判定会进正式审查意见。空着只是少一条证据，认错是造一条假证据。
所以 legible=false 或 text 为空时，一律不写值。
"""

from __future__ import annotations

import json

from libs import seal_vision


class FakeClient:
    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls: list[dict] = []

    def chat_sync(self, messages, model="default-chat", **kwargs):
        self.calls.append({"messages": messages, "model": model})
        return {"reply": self.replies.pop(0) if self.replies else ""}

    @staticmethod
    def first_message_text(response):
        return response.get("reply", "")


def _seal(seal_id: str = "S1", image_path: str = "images/seal-1.png") -> dict:
    return {"sealId": seal_id, "imagePath": image_path, "pageNo": 1, "bbox": [1, 2, 3, 4]}


IMAGES = {"images/seal-1.png": b"\x89PNG\r\n\x1a\n fake"}


def test_读得出也只作未核对的候选():
    seals = [_seal()]
    client = FakeClient(
        [json.dumps({"text": "贵州化工建设有限责任公司", "sealType": "公章", "legible": True})]
    )
    summary = seal_vision.read_seal_texts(seals, IMAGES, client=client)

    assert summary["recognized"] == 1
    assert seals[0]["sealName"] == "贵州化工建设有限责任公司"
    assert seals[0]["text"] == "贵州化工建设有限责任公司"
    assert seals[0]["sealType"] == "公章"
    assert seals[0]["recognitionSource"] == "vision_model"
    # 云端读数**不算已识别**。线上实测（射线检测报告 2026-08-16）：
    # 封面写明出具单位是「广州声华科技股份有限公司」，同一枚检测专用章
    # 在四页上被读成山东华科／华科技／广州迪华／杭州科科技——四个城市、
    # 四个公司名，模型在编。文字照给，但必须挂上「未核对」，
    # 否则编造的单位名会以「已识别」的身份进入审查证据。
    assert seals[0]["recognized"] is False
    assert seals[0]["requiresHumanConfirmation"] is True
    assert "未经核对" in seals[0]["recognitionNote"]
    assert seals[0]["sealEvidenceLevel"] == "model_read_unverified"


def test_读不清就不写值():
    seals = [_seal()]
    client = FakeClient([json.dumps({"text": None, "sealType": None, "legible": False})])
    summary = seal_vision.read_seal_texts(seals, IMAGES, client=client)

    assert summary["illegible"] == 1
    assert not seals[0].get("sealName")
    assert seals[0]["recognized"] is False


def test_模型说看清了却给空字符串也不算():
    """legible=true 但 text 为空——自相矛盾的回答，按读不出处理。"""
    seals = [_seal()]
    client = FakeClient([json.dumps({"text": "   ", "legible": True})])
    summary = seal_vision.read_seal_texts(seals, IMAGES, client=client)

    assert summary["illegible"] == 1
    assert not seals[0].get("sealName")


def test_围栏包裹的_json_也要认():
    seals = [_seal()]
    client = FakeClient(['```json\n{"text": "某某质检章", "legible": true}\n```'])
    seal_vision.read_seal_texts(seals, IMAGES, client=client)
    assert seals[0]["sealName"] == "某某质检章"


def test_模型报错不抛出去():
    """读不到字只是印章少个属性，不该让整份资料识别失败。"""

    class Boom(FakeClient):
        def chat_sync(self, *args, **kwargs):
            raise RuntimeError("模型不可用")

    seals = [_seal()]
    summary = seal_vision.read_seal_texts(seals, IMAGES, client=Boom([]))
    assert summary["failed"] == 1
    assert not seals[0].get("sealName")


def test_已有文字的章不重复调用():
    seals = [{**_seal(), "sealName": "已经认出来了", "text": "已经认出来了"}]
    client = FakeClient([])
    summary = seal_vision.read_seal_texts(seals, IMAGES, client=client)
    assert summary["attempted"] == 0
    assert client.calls == []


def test_找不到裁图就跳过():
    seals = [_seal(image_path="images/不存在.png")]
    client = FakeClient([])
    summary = seal_vision.read_seal_texts(seals, IMAGES, client=client)
    assert summary["skipped"] == 1
    assert client.calls == []


def test_开关关掉就整体不跑():
    seals = [_seal()]
    client = FakeClient([])
    summary = seal_vision.read_seal_texts(
        seals, IMAGES, client=client, env={"AICHECK_ENABLE_VISION_SEAL_READING": "false"}
    )
    assert summary["skipped"] == 1
    assert client.calls == []


def test_单份资料有调用上限():
    """一份几十页的资料可能有几十枚章，逐枚调模型会把一次识别拖成几分钟。"""
    seals = [_seal(f"S{i}") for i in range(20)]
    client = FakeClient([json.dumps({"text": f"章{i}", "legible": True}) for i in range(20)])
    summary = seal_vision.read_seal_texts(seals, IMAGES, client=client)
    assert summary["attempted"] == seal_vision.MAX_SEALS_PER_DOCUMENT
    assert len(client.calls) == seal_vision.MAX_SEALS_PER_DOCUMENT


def test_提示词明确禁止猜测():
    """这条是本模块存在的前提，被人「优化」掉时要有测试拦住。"""
    assert "不要推断" in seal_vision._SEAL_PROMPT
    assert "null" in seal_vision._SEAL_PROMPT
