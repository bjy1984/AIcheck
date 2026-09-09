"""Count page recognition separately from document quality and rendering."""


def recognition_page_coverage(selected_pages, page_results):
    selected = sorted(set(selected_pages))
    completed = []
    for page in selected:
        calls = [row for row in page_results.get(page, []) if row.get("task") == "advanced_recognition" and not row.get("roiColor")]
        full = [row for row in calls if not row.get("tileRecovery") and not row.get("outputTruncated") and not row.get("supersededByTiles")]
        recovered = False
        for base in calls:
            expected = base.get("recoveryTileCount")
            if not base.get("supersededByTiles") or type(expected) is not int or expected < 1:
                continue
            tiles = [row for row in calls if row.get("tileRecovery") and not row.get("outputTruncated")]
            boxes = {tuple(row["roiBbox"]) for row in tiles if isinstance(row.get("roiBbox"), list) and len(row["roiBbox"]) == 4}
            recovered = len(boxes) == expected
        if full or recovered:
            completed.append(page)
    return {"scope": "page_recognition", "selectedPageNos": selected, "completedPageNos": completed,
            "unprocessedPageNos": sorted(set(selected) - set(completed)), "complete": len(completed) == len(selected)}


def final_page_progress(result):
    metadata = result.get("metadata") or {}
    coverage = metadata.get("recognitionPageCoverage")
    outcome = result.get("outcomeStatus")
    if result.get("status") not in {"success", "succeeded", "completed"}:
        status = "failed"
    elif outcome == "completed":
        status = "completed"
    else:
        status = "partial"
    if isinstance(coverage, dict):
        selected = set(coverage.get("selectedPageNos") or [])
        completed = selected & set(coverage.get("completedPageNos") or [])
        if len(completed) < len(selected) and status == "completed":
            status = "partial"
    else:
        selected = {row["pageNo"] for row in result.get("pages", []) if isinstance(row, dict) and type(row.get("pageNo")) is int}
        completed = selected if status == "completed" else set()
    return {"completed": len(completed), "total": len(selected), "currentPage": None, "status": status}
