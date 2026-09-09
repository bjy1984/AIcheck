"""Load only the frozen handoff dependency graph for a review worker."""
from __future__ import annotations


def load_handoff_rows(connection, run, tenant_id):
    if "handoffInputsSnapshot" not in run:
        return [], {}, set()
    pending = [run]
    seen_runs = {run.get("reviewRunId") or run.get("id")}
    seen_handoffs = set()
    rows = []
    versions = set(run.get("inputDocumentVersionIds") or [])
    for _ in range(64):
        if not pending:
            break
        selections = [item for current in pending for item in (current.get("handoffInputsSnapshot") or {}).get("items", [])]
        handoffs = {item["handoffId"] for item in selections} - seen_handoffs
        runs = {item[key] for item in selections for key in ("sourceRunId", "originalTargetRunId")} - seen_runs
        seen_handoffs.update(handoffs)
        seen_runs.update(runs)
        if not handoffs and not runs:
            break
        fetched = connection.execute("""
            SELECT collection, object_id, payload FROM aicheck_state
            WHERE tenant_id = %s AND (
                (collection = 'review_handoffs' AND object_id = ANY(%s)) OR
                (collection = 'review_runs' AND object_id = ANY(%s)))
            ORDER BY collection, object_id
        """, (tenant_id, sorted(handoffs), sorted(runs))).fetchall()
        rows.extend(fetched)
        pending = [payload for collection, _, payload in fetched if collection == "review_runs"]
        for current in pending:
            versions.update(current.get("inputDocumentVersionIds") or [])
    else:
        raise ValueError("handoff_input_dependency_depth")
    rows.extend(connection.execute("""
        SELECT collection, object_id, payload FROM aicheck_state
        WHERE tenant_id = %s AND collection = ANY(%s)
          AND payload ->> 'documentVersionId' = ANY(%s)
        ORDER BY collection, object_id
    """, (tenant_id, ["ocr_parse_results", "fact_corrections", "extracted_fields", "evidence_links"], sorted(versions))).fetchall())
    return rows, {"review_runs": seen_runs - {run.get("reviewRunId") or run.get("id")},
                  "review_handoffs": seen_handoffs}, versions
