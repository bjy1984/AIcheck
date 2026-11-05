"""Public projection of finalized OCR evidence, independent of engineering records."""
from copy import deepcopy

CONTENT_KEYS = ("pages", "fragments", "fields", "tables", "layoutBlocks", "seals", "signatures")
METADATA_KEYS = ("provider", "model", "providerMode", "requestedProfileId", "detectedProfileId",
                 "profileRouteReason", "profileRoutingVersion", "coordinateContract", "postProcessing", "fallback")


def project_ocr_result(parsed: dict, *, page_no: int | None = None) -> dict:
    """Page filters must not silently discard fields whose evidence is document-level."""
    content = {key: deepcopy([row for row in parsed.get(key) or [] if isinstance(row, dict)
                              and (page_no is None or row.get("pageNo") == page_no)])
               for key in CONTENT_KEYS}
    unlocated = {key: deepcopy([row for row in parsed.get(key) or []
                               if isinstance(row, dict) and row.get("pageNo") is None])
                 for key in CONTENT_KEYS if key != "pages"}
    metadata = parsed.get("metadata") or {}
    return {
        **content,
        "documentFields": unlocated.pop("fields"),
        "unlocatedContent": unlocated,
        "resultKind": "processed_ocr",
        "scope": {"pageNo": page_no, "quality": "document", "documentFields": "document"},
        **{key: deepcopy(parsed.get(key)) for key in ("profileId", "documentType", "parserVersion",
           "profilePostprocessVersion", "engineVersion", "outcomeStatus", "formalEvidenceReady", "quality")},
        "processing": {"rawProviderOutput": False,
                       "provenanceAvailable": bool(metadata.get("postProcessing")),
                       **{key: deepcopy(metadata[key]) for key in METADATA_KEYS if key in metadata}},
        "diagnostics": [{key: deepcopy(row[key]) for key in ("code", "level", "stage", "pageNo", "retryable") if key in row}
                        for row in parsed.get("diagnostics") or [] if isinstance(row, dict)
                        and (page_no is None or row.get("pageNo") in (None, page_no))],
    }


# 节点审计 skill 只复用这两种引擎出的结果：它的阅读口径（表格展开、印章、签名）和评测都是按 MinerU
# （排队超时由千问兜底）做的。导入的测试场景用的是本机 OCR（macos_vision_ocr_v1，没有表格和印章），
# 复用它会让审计变差，skill 遇到别的引擎照旧上传重识别（2026-11-04）。
REUSABLE_OCR_PROVIDERS = ("mineru", "qwen")


def parse_result_provider(parsed: dict) -> str:
    """这份识别结果是哪个引擎出的：mineru、qwen，或者别的引擎名（engineVersion / parserVersion）。"""
    result_id = str(parsed.get("parseResultId") or parsed.get("id") or "")
    engine_version = str(parsed.get("engineVersion") or "")
    if engine_version == "aliyun-qwen-ocr" or result_id.startswith("PARSE-QWEN-"):
        return "qwen"
    runs = [run for run in parsed.get("engineRuns") or [] if isinstance(run, dict)]
    if str(parsed.get("parserVersion") or "").startswith("mineru") or any(
        str(run.get("provider") or "") == "mineru" or str(run.get("engine") or "").startswith("mineru") for run in runs
    ):
        return "mineru"
    return engine_version or str(parsed.get("parserVersion") or "") or "unknown"


def latest_version_parse_result(parse_results: list, document_version_id: str) -> dict | None:
    """这一版资料最近一次完成的识别结果；流水线中间阶段（结构、印章、融合）只是候选，和审查读取口径一致。"""
    matches = [item for item in parse_results or [] if isinstance(item, dict)
               and str(item.get("documentVersionId") or "") == str(document_version_id) and not item.get("pipelineStage")]
    return max(matches, key=lambda item: str(item.get("finishedAt") or item.get("createdAt") or "")) if matches else None


def document_version_ocr_payload(parsed: dict | None, *, document_id: str, document_version_id: str) -> dict:
    """GET /projects/{p}/documents/{d}/versions/{v}/ocr-result 的返回：和 MinerU 任务的 /result 同一个形状，
    加上是哪个引擎出的、能不能给 skill 复用。"""
    base = {"documentId": document_id, "documentVersionId": document_version_id}
    if not parsed:
        return {**base, "resultAvailable": False}
    provider = parse_result_provider(parsed)
    pages = parsed.get("pages") or []
    page_count = max([int(p.get("pageNo") or 0) for p in pages if isinstance(p, dict)] or [0])
    return {**base, "resultAvailable": True, "parseResultId": parsed.get("parseResultId") or parsed.get("id"),
            "ocrProvider": provider, "reusable": provider in REUSABLE_OCR_PROVIDERS,
            "finishedAt": parsed.get("finishedAt") or parsed.get("createdAt"), "pageCount": page_count,
            **project_ocr_result(parsed)}
