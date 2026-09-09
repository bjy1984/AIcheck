"""Expose bounded local PDF rendering without claiming full visual coverage."""

CODE = "OCR_PAGE_COVERAGE_INCOMPLETE"


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
