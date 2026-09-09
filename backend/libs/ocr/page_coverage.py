"""Expose bounded local PDF rendering without claiming full visual coverage."""

CODE = "OCR_PAGE_COVERAGE_INCOMPLETE"


def review_coverage_gap(result, bounds=None):
    """Keep only page-gap metadata relevant to the frozen review range."""
    metadata = result.get("metadata") or {}
    coverage = metadata.get("recognitionPageCoverage") or metadata.get("localRenderCoverage") or {}
    if "reviewCoverageGap" in result:
        gap = result["reviewCoverageGap"]
        if gap is None:
            return None
        coverage = {"complete": False, "unprocessedPageNos": gap.get("pageNos")}
    if CODE not in ((result.get("quality") or {}).get("reasons") or []) and coverage.get("complete") is not False:
        return None
    raw = coverage.get("unprocessedPageNos", coverage.get("unrenderedPageNos", []))
    located = isinstance(raw, list) and bool(raw) and all(type(page) is int and page > 0 for page in raw)
    pages = sorted(set(raw)) if located else []
    if bounds is not None and located:
        pages = [page for page in pages if bounds["start"] <= page <= bounds["end"]]
        if not pages:
            return None
    return {"code": CODE, "pageNos": pages, "gapLocationKnown": located}


def render_coverage_issue(result, document_id):
    metadata = result.get("metadata") or {}
    coverage = metadata.get("recognitionPageCoverage") or metadata.get("localRenderCoverage") or {}
    pages = sorted({page for page in coverage.get("unprocessedPageNos", coverage.get("unrenderedPageNos", [])) if type(page) is int and page > 0})
    ranges = []
    for page in pages:
        if ranges and page == ranges[-1][1] + 1:
            ranges[-1][1] = page
        else:
            ranges.append([page, page])
    labels = [str(start) if start == end else f"{start}–{end}" for start, end in ranges]
    summary = "、".join(labels[:8]) + ("等" if len(labels) > 8 else "")
    message = f"第 {summary} 页还没完成辨识。" if summary else "这份文件还有页面未完成辨识。"
    return {"code": CODE, "message": message + "已读到的内容会保留，请先核对剩余页的原文。",
            "pageNos": pages, "actionKey": "review_ocr", "targetId": document_id}


def attach_render_coverage(result):
    pages = [row for row in result.get("pages", []) if isinstance(row, dict)]
    bounded = [row for row in pages if row.get("truncated") is True]
    if not bounded:
        return
    totals = {row.get("totalPages") for row in bounded if type(row.get("totalPages")) is int and row["totalPages"] > 0}
    rendered = sorted({row["pageNo"] for row in pages if type(row.get("pageNo")) is int and row["pageNo"] > 0
                       and type(row.get("totalPages")) is int and isinstance(row.get("renderedPages"), list)})
    missing = sorted(set(range(1, next(iter(totals)) + 1)) - set(rendered)) if len(totals) == 1 else []
    coverage = {"scope": "local_visual_rendering", "renderedPageNos": rendered,
                "unrenderedPageNos": missing, "complete": False}
    result.setdefault("metadata", {})["localRenderCoverage"] = coverage
    diagnostics = result.setdefault("diagnostics", [])
    if not any(row.get("code") == CODE for row in diagnostics if isinstance(row, dict)):
        diagnostics.append({"code": CODE, "level": "warning",
                            "message": "这份文件还有页面未进入完整辨识，请核对剩余页面。", "pageNos": missing})
    quality = result.setdefault("quality", {})
    quality["reasons"] = sorted({*(quality.get("reasons") or []), CODE})
    blockers = quality.setdefault("blockingReasons", [])
    if not any(row.get("code") == CODE for row in blockers if isinstance(row, dict)):
        blockers.append({"code": CODE, "pageNos": missing})
    if quality.get("status") != "failed":
        quality["status"] = "needs_human_review"
    if result.get("status") in {"success", "succeeded", "completed"} and result.get("outcomeStatus") != "failed":
        result["outcomeStatus"] = "partial"
