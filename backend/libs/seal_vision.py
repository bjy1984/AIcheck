"""读印章上的字。

MinerU 能把印章**框出来**（`content_list` 里 `type=image, sub_type=seal`），
但不读上面的字：返回的 seal 只有 bbox 和一张裁图，`name` 是空的。
而监检确认「盖章了没有」靠的正是章上的单位名——只知道「这里有个圆形图案」，
对业务等于没有。

本地印章模型（PaddleX seal pipeline）需要 3.5 GB 模型和一个常驻容器，
服务器上没有；这里改走已经打通的视觉模型：把 MinerU 裁好的那张印章图
送过去读字。裁图是 MinerU 给的，不用重新渲染 PDF，也就不会引入
坐标换算这一层新的出错机会。

## 三条约束

1. **看不清就说看不清。** 提示词明确要求读不出时返回 null，不许猜。
   印章识别错一个字，可能就是把「贵州化工建设」认成另一家单位——
   这种错比空着危险得多。
2. **失败不阻断。** 读不到字只是印章少个属性，不该让整份资料识别失败。
3. **留痕。** 识别出的内容标注 `recognitionSource=vision_model` 和模型名，
   事后能分清哪些章是模型读的、哪些是人工填的。
"""

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any, Mapping

LOGGER = logging.getLogger(__name__)

MAX_SEALS_PER_DOCUMENT = 12
_SEAL_PROMPT = (
    "这是一张从工程资料上裁下来的印章图片。请读出印章上的文字。\n"
    "要求：\n"
    "1. 只输出你**确实看清**的字。任何一个字看不清，就把 text 设为 null，"
    "不要根据常见单位名补全、不要推断。\n"
    "2. sealType 从「公章/合同章/质量检验章/骑缝章/个人名章/其它」中选，"
    "判断不了填 null。\n"
    "3. 严格输出 JSON，不要加解释文字：\n"
    '{"text": "印章文字或 null", "sealType": "类型或 null", "legible": true 或 false}'
)


def seal_vision_enabled(env: Mapping[str, str] | None = None) -> bool:
    source = env if env is not None else os.environ
    return str(source.get("AICHECK_ENABLE_VISION_SEAL_READING", "true")).strip().lower() not in {
        "false",
        "0",
        "no",
    }


def _image_data_url(payload: bytes, name: str) -> str:
    suffix = (name.rsplit(".", 1)[-1] if "." in name else "png").lower()
    mime = "image/jpeg" if suffix in {"jpg", "jpeg"} else f"image/{suffix or 'png'}"
    return f"data:{mime};base64," + base64.b64encode(payload).decode("ascii")


def parse_seal_response(text: str) -> dict[str, Any]:
    """模型回的 JSON。带 ```json 围栏是常见形态，先剥掉再解析。"""
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned[: -3]
        cleaned = cleaned.strip()
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        parsed = json.loads(cleaned)
    except (ValueError, TypeError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed


def read_seal_texts(
    seals: list[dict[str, Any]],
    images: Mapping[str, bytes],
    *,
    client: Any,
    model_role: str = "qwen-vision-review",
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """就地补齐 seals 里的文字。返回一份统计，供诊断信息使用。

    `images` 是 zip 内路径 → 图片字节；MinerU 的 seal 用 `imagePath` 指过来。
    """
    summary = {"attempted": 0, "recognized": 0, "illegible": 0, "failed": 0, "skipped": 0}
    if not seals or not seal_vision_enabled(env):
        summary["skipped"] = len(seals or [])
        return summary
    for seal in seals[:MAX_SEALS_PER_DOCUMENT]:
        if str(seal.get("name") or seal.get("text") or "").strip():
            summary["skipped"] += 1
            continue
        image_path = str(seal.get("imagePath") or "")
        payload = images.get(image_path) if image_path else None
        if payload is None:
            # 路径可能带目录前缀差异，退一步按文件名找。
            base = image_path.rsplit("/", 1)[-1]
            payload = next(
                (data for name, data in images.items() if name.rsplit("/", 1)[-1] == base and base),
                None,
            )
        if not payload:
            summary["skipped"] += 1
            continue
        summary["attempted"] += 1
        try:
            response = client.chat_sync(
                [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": _SEAL_PROMPT},
                            {
                                "type": "image_url",
                                "image_url": {"url": _image_data_url(payload, image_path)},
                            },
                        ],
                    }
                ],
                model=model_role,
                timeout=60,
            )
            parsed = parse_seal_response(client.first_message_text(response))
        except Exception:
            # 读不到字只是印章少个属性，不该让整份资料识别失败。
            LOGGER.exception("印章读字失败 sealId=%s", seal.get("sealId"))
            summary["failed"] += 1
            continue
        text = parsed.get("text")
        legible = bool(parsed.get("legible")) and bool(str(text or "").strip())
        if not legible:
            seal["recognized"] = False
            seal["recognitionSource"] = "vision_model"
            seal["recognitionNote"] = "模型未能看清印章文字"
            summary["illegible"] += 1
            continue
        # 字段名跟 structured_seals 的读法对齐：它读 sealName / text。
        # 只写 name 会「看起来写了」而界面上一个字都不显示——这种错不会报警。
        # **云端读数一律标为未核对。**
        #
        # 线上实测（射线检测报告，2026-08-16）：封面写明出具单位是
        # 「广州声华科技股份有限公司」，而同一枚检测专用章在四页上被读成
        #     p2 山东华科科技胶粘有限公司…
        #     p3 华科技股份有限公司…
        #     p4 广州迪华科技股份有限公司…
        #     p5 杭州科科技股份有限公司…
        # 四个城市、四个公司名——**模型在编**。印泥不匀、压字、弧形排布之下，
        # 视觉模型会给出「读起来很像那么回事」的名字。
        #
        # 对一个出具审查结论的系统，编造的单位名比空白危险得多：空白会让人去看图，
        # 编造会让人直接采信。所以文字照样给出来供人参考，但：
        #   - recognized 保持 False：不计入「已识别」，不满足「必须盖章」
        #   - 明确标注来源与「需人工核对」，让界面能把这件事说出来
        seal["sealName"] = str(text).strip()
        seal["name"] = str(text).strip()
        seal["text"] = str(text).strip()
        seal["sealType"] = str(parsed.get("sealType") or "").strip() or seal.get("sealType") or ""
        seal["recognized"] = False
        seal["requiresHumanConfirmation"] = True
        seal["recognitionNote"] = "云端模型读数，未经核对，请对照原图确认单位名"
        seal["recognitionSource"] = "vision_model"
        # 模型不给逐字置信度。写 0.0 会被下游当成「低置信度」——那是另一个坑，
        # 这里如实标注来源，由复核环节按来源判断可信程度。
        seal["sealEvidenceLevel"] = "model_read_unverified"
        summary["recognized"] += 1
    if len(seals) > MAX_SEALS_PER_DOCUMENT:
        summary["skipped"] += len(seals) - MAX_SEALS_PER_DOCUMENT
    return summary
