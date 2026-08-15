"""用本地印章模型读章上的字。

## 为什么是本地优先

印章图会带着单位名，属于最不该随便出内网的那类内容。本地那套
（PaddleX seal_recognition：版面检测 → 印章检测 → 印章文字识别）
部署在 ocr-service 容器里，图片不出机器。

## 实测（2026-08-16，服务器上直接跑管线）

    layout_det_res: label=seal score=0.940
    rec_texts: ["中华人共和国国家质量监督检验检疫总局"]  rec_scores: [0.978]

**注意那个 0.978 里漏了一个「民」字。** 本地模型给的分数是它自己的置信度，
不代表逐字都对；同一枚章云端视觉模型读出的是完整的「中华人民共和国…」。
所以本地结果照样只作候选证据，要人工过目——分数高不等于字对。

## 三个坑（都是实测踩出来的）

1. paddlex 启动时要在缓存目录下建 temp，**模型目录只读挂载会让它导入就炸**，
   报的是 PermissionError: '/models/temp'，看起来像模型有问题。
   缓存目录必须单独给一个可写卷。
2. 印章引擎需要五个模型（版面/方向/纠偏/印章检测/印章识别），少一个就
   available=False，而 doctor 只说 "unavailable"，不说少哪个。
3. 直接把**已裁好的印章图**丢给整份文档的解析接口没用——那条路要先有
   「印章用途」的候选切图才会把活派给印章引擎，否则一路 skipped，
   理由写的是 no_routed_variant。这里绕开路由，直接调管线。
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

LOGGER = logging.getLogger(__name__)

_MIN_SEAL_SCORE = 0.5


def local_seal_reading_enabled(env: Mapping[str, str] | None = None) -> bool:
    source = env if env is not None else os.environ
    return str(
        source.get("AICHECK_ENABLE_LOCAL_SEAL_READING", "true")
    ).strip().lower() not in {"false", "0", "no"}


def _pipeline():
    """按需创建管线。模型加载约 20 秒，进程内缓存一份。"""
    global _PIPELINE
    if _PIPELINE is None:
        from apps.ocr_service.engines import (  # 延迟导入：API 进程里没有 paddlex
            paddle_predictor_options,
            seal_model_dirs,
            seal_pipeline_config,
        )
        from paddlex import create_pipeline

        _PIPELINE = create_pipeline(
            config=seal_pipeline_config(seal_model_dirs()),
            **paddle_predictor_options(),
        )
    return _PIPELINE


_PIPELINE: Any = None


def read_seal_image(payload: bytes, *, suffix: str = ".jpg") -> dict[str, Any]:
    """读一张印章图。返回 {text, score, ok}；读不出就 ok=False，不猜。"""
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            prefix="aicheck-seal-", suffix=suffix, delete=False
        ) as tmp:
            tmp.write(payload)
            tmp_path = tmp.name
        texts: list[str] = []
        scores: list[float] = []
        for result in _pipeline().predict(tmp_path):
            data = result.json.get("res", {}) if hasattr(result, "json") else (result or {})
            for item in data.get("seal_res_list") or []:
                for text, score in zip(
                    item.get("rec_texts") or [], item.get("rec_scores") or []
                ):
                    if str(text).strip():
                        texts.append(str(text).strip())
                        scores.append(float(score))
        if not texts:
            return {"ok": False, "text": "", "score": 0.0}
        best = max(range(len(texts)), key=lambda i: scores[i])
        if scores[best] < _MIN_SEAL_SCORE:
            # 分数太低时宁可空着。印章认错一个单位名，比没认出来危险得多。
            return {"ok": False, "text": "", "score": scores[best]}
        return {"ok": True, "text": texts[best], "score": scores[best]}
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)


def read_seal_image_via_service(payload: bytes, *, suffix: str = ".jpg") -> dict[str, Any]:
    """从 worker 侧调 ocr-service 读印章。

    模型只装在 ocr-service 镜像里（2.4 GB，带 paddle）。worker 用的是 API 镜像，
    里面没有 paddlex——所以不能直接 import，必须走 HTTP。
    这不是绕远路：模型只在一处加载，也就只在一处占内存。
    """
    import json
    import urllib.request

    base = str(os.getenv("AICHECK_OCR_BASE_URL") or "http://ocr-service:8010").rstrip("/")
    request = urllib.request.Request(
        f"{base}/internal/ocr/seal-read",
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/octet-stream",
            "X-AICheck-Seal-Suffix": suffix,
        },
    )
    with urllib.request.urlopen(request, timeout=float(os.getenv("AICHECK_SEAL_READ_TIMEOUT", "180"))) as response:
        body = json.loads(response.read().decode() or "{}")
    if int(body.get("code") or 0) != 0:
        raise RuntimeError(str(body.get("message") or "印章识别失败"))
    return body.get("data") or {"ok": False, "text": "", "score": 0.0}


def read_seal_texts_locally(
    seals: list[dict[str, Any]],
    images: Mapping[str, bytes],
    *,
    reader: Any = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """就地补齐 seals 的文字，返回统计。失败只记，不抛。"""
    summary = {"attempted": 0, "recognized": 0, "illegible": 0, "failed": 0, "skipped": 0}
    if not seals or not local_seal_reading_enabled(env):
        summary["skipped"] = len(seals or [])
        return summary
    for seal in seals:
        if str(seal.get("sealName") or seal.get("text") or "").strip():
            summary["skipped"] += 1
            continue
        image_path = str(seal.get("imagePath") or "")
        payload = images.get(image_path)
        if payload is None and image_path:
            base = image_path.rsplit("/", 1)[-1]
            payload = next(
                (
                    data
                    for name, data in images.items()
                    if base and name.rsplit("/", 1)[-1] == base
                ),
                None,
            )
        if not payload:
            summary["skipped"] += 1
            continue
        summary["attempted"] += 1
        try:
            outcome = (reader or read_seal_image_via_service)(
                payload, suffix=Path(image_path or "seal.jpg").suffix or ".jpg"
            )
        except Exception:
            LOGGER.exception("本地印章读字失败 sealId=%s", seal.get("sealId"))
            summary["failed"] += 1
            continue
        if not outcome["ok"]:
            seal["recognized"] = False
            seal["recognitionSource"] = "local_seal_model"
            seal["recognitionNote"] = "本地模型未能读出印章文字"
            summary["illegible"] += 1
            continue
        seal["sealName"] = outcome["text"]
        seal["name"] = outcome["text"]
        seal["text"] = outcome["text"]
        seal["recognized"] = True
        seal["recognitionSource"] = "local_seal_model"
        # 这是模型自报的置信度，不是逐字正确率——实测 0.978 的那次漏了一个字。
        seal["ocrConfidence"] = outcome["score"]
        seal["sealEvidenceLevel"] = seal.get("sealEvidenceLevel") or "model_read"
        summary["recognized"] += 1
    return summary
