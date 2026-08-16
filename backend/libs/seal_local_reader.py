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


def looks_like_seal_name(text: str) -> bool:
    """像不像一个单位名/印章名。

    印章上通常是「XX有限公司」「XX监督管理局」这类中文名，中间可能夹编号。
    只有字母数字的碎片（"C33520"、"2021"）是底弧上的编号被单独框出来了，
    不能当成印章文字——它对核验没有用，却会让人以为这枚章已经认出来了。
    """
    value = str(text or "").strip()
    if len(value) < 4:
        return False
    han = sum(1 for ch in value if "\u4e00" <= ch <= "\u9fff")
    return han >= 4


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
        if not looks_like_seal_name(texts[best]):
            # **高分不等于内容对。** 线上实测：射线检测报告第 4 页的章读出
            # "C33520"、分数 0.963——那是印章底弧上的编号碎片，不是单位名，
            # 却会以「印章文字」的身份进入证据链。监检看到这一条，
            # 既核不出单位，也不会怀疑它是错的，因为它带着 0.96 的分数。
            # 认不出全名就交回人工，别拿碎片充数。
            return {
                "ok": False,
                "text": "",
                "score": scores[best],
                "rejected": texts[best],
                "reason": "seal_text_not_a_name",
            }
        return {"ok": True, "text": texts[best], "score": scores[best]}
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)


MAX_SCAN_PAGES = 30


def scan_pdf_for_seals(payload: bytes, *, dpi: int = 150) -> list[dict[str, Any]]:
    """逐页渲染 PDF，用本地印章管线自己找章。

    为什么需要这条：MinerU 会漏检。线上实测射线检测报告封面那枚红章压在
    「二零二一年四月」上，MinerU 的 content_list 里 page_idx 0 一个图片条目都没有
    ——**没有裁图，后面读字的一切都无从谈起**。

    这条路不依赖 MinerU 的判断：把整页交给版面检测，它自己框印章区域再读字。
    代价是每页几秒 CPU，所以设了页数上限，并且只在需要时调用。

    返回 [{pageNo, text, score, bbox}]，读不出字的章也返回（text 为空），
    因为「这里有一枚章」本身就是监检要的信息。
    """
    import fitz  # ocr-service 镜像里有；worker 侧不会走到这条

    found: list[dict[str, Any]] = []
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(prefix="aicheck-sealscan-", suffix=".pdf", delete=False) as tmp:
            tmp.write(payload)
            tmp_path = tmp.name
        document = fitz.open(tmp_path)
        try:
            for index, page in enumerate(document):
                if index >= MAX_SCAN_PAGES:
                    break
                image = page.get_pixmap(dpi=dpi).tobytes("png")
                for item in _detect_seals_on_image(image):
                    found.append({**item, "pageNo": index + 1})
        finally:
            document.close()
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)
    return found


def _detect_seals_on_image(payload: bytes) -> list[dict[str, Any]]:
    """一页图里的所有印章。检出但读不出的也返回，text 留空。"""
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(prefix="aicheck-sealpage-", suffix=".png", delete=False) as tmp:
            tmp.write(payload)
            tmp_path = tmp.name
        results: list[dict[str, Any]] = []
        for result in _pipeline().predict(tmp_path):
            data = result.json.get("res", {}) if hasattr(result, "json") else (result or {})
            boxes = ((data.get("layout_det_res") or {}).get("boxes")) or []
            seal_boxes = [b for b in boxes if str(b.get("label") or "").lower() == "seal"]
            seal_texts = data.get("seal_res_list") or []
            for position, box in enumerate(seal_boxes):
                text, score = "", 0.0
                if position < len(seal_texts):
                    item = seal_texts[position]
                    pairs = list(zip(item.get("rec_texts") or [], item.get("rec_scores") or []))
                    named = [(t, float(sc)) for t, sc in pairs if looks_like_seal_name(str(t))]
                    if named:
                        text, score = max(named, key=lambda pair: pair[1])
                results.append(
                    {
                        "text": str(text).strip(),
                        "score": float(score),
                        "bbox": box.get("coordinate"),
                        "detectionScore": float(box.get("score") or 0),
                    }
                )
        return results
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


def scan_document_seals_via_service(payload: bytes, *, dpi: int = 150) -> list[dict[str, Any]]:
    """worker 侧调 ocr-service 做整份印章扫描。模型只在那个容器里。"""
    import json
    import urllib.request

    base = str(os.getenv("AICHECK_OCR_BASE_URL") or "http://ocr-service:8010").rstrip("/")
    request = urllib.request.Request(
        f"{base}/internal/ocr/seal-scan",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/octet-stream", "X-AICheck-Seal-Dpi": str(dpi)},
    )
    timeout = float(os.getenv("AICHECK_SEAL_SCAN_TIMEOUT", "900"))
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read().decode() or "{}")
    if int(body.get("code") or 0) != 0:
        raise RuntimeError(str(body.get("message") or "印章扫描失败"))
    return list((body.get("data") or {}).get("seals") or [])


def merge_scanned_seals(
    seals: list[dict[str, Any]],
    scanned: list[dict[str, Any]],
) -> dict[str, Any]:
    """把逐页扫出来的章并进现有列表。

    同一页已经有章就不重复添加——判重按页码，不按 bbox：两条链路的坐标系
    不一样（MinerU 归一化到 1000，这里是渲染像素），拿它们比大小会得出
    看似精确实则无意义的结论。宁可少补一枚，也不制造重影。
    """
    summary = {"added": 0, "recognizedByScan": 0}
    pages_with_seal = {int(item.get("pageNo") or 0) for item in seals if item.get("pageNo")}
    for index, item in enumerate(scanned):
        page_no = int(item.get("pageNo") or 0)
        if not page_no or page_no in pages_with_seal:
            continue
        text = str(item.get("text") or "").strip()
        seal = {
            "sealId": f"LOCALSCAN-SEAL-{page_no}-{index}",
            "pageNo": page_no,
            "bbox": item.get("bbox"),
            "sourceEngine": "paddlex_seal_recognition",
            "coordinateSystem": "rendered_pixels",
            "candidateOnly": True,
            "canSatisfyRequiredSeal": False,
            "recognitionSource": "local_seal_model",
            "detectionScore": item.get("detectionScore"),
        }
        if text:
            seal.update(
                {
                    "sealName": text,
                    "name": text,
                    "text": text,
                    "recognized": True,
                    "ocrConfidence": item.get("score"),
                    "sealEvidenceLevel": "model_read",
                }
            )
            summary["recognizedByScan"] += 1
        else:
            seal.update(
                {
                    "recognized": False,
                    "recognitionNote": "逐页扫描检出印章，文字未读出，请对照原图确认",
                }
            )
        seals.append(seal)
        pages_with_seal.add(page_no)
        summary["added"] += 1
    return summary


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
            seal["recognitionNote"] = (
                f"本地模型读到「{outcome['rejected']}」，不像单位名，未采用"
                if outcome.get("rejected")
                else "本地模型未能读出印章文字"
            )
            summary["illegible"] += 1
            # 逐枚记下来，供云端兜底只补这些——原先是「整份一枚都没读出才兜底」，
            # 于是一份 4 枚章的报告里只要有 1 枚读出来，另外 3 枚就再没机会。
            summary.setdefault("pendingSealIds", []).append(str(seal.get("sealId") or ""))
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
