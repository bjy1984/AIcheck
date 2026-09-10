"""Validate each selected version and preserve page-scoped OCR coverage gaps."""
from libs.ocr.page_coverage import review_coverage_gap
from libs.review_input_data import selected_parse_results


def selected_source_issues(state, run, *, node_id):
    issues = []
    parses = selected_parse_results(state, {}, context={"reviewRun": run})
    for version_id in sorted(set(run.get("inputDocumentVersionIds") or [])):
        versions = [row for row in state.get("versions", []) if row.get("id") == version_id
                    and row.get("tenantId") == run["tenantId"]]
        documents = [row for row in state.get("documents", []) if len(versions) == 1
                     and row.get("id") == versions[0].get("documentId") and row.get("tenantId") == run["tenantId"]
                     and row.get("projectId") == run["projectId"]]
        candidates = [row for row in parses if row.get("documentVersionId") == version_id
                      and row.get("tenantId") == run["tenantId"]]
        if len(versions) != 1 or len(documents) != 1 or len(candidates) != 1:
            issues.append({"code": f"r{node_id}_selected_source_missing_or_ambiguous", "documentVersionId": version_id})
            continue
        gap = review_coverage_gap(candidates[0])
        if gap:
            issues.append({**gap, "code": f"r{node_id}_selected_pages_incomplete", "documentVersionId": version_id})
    return issues
