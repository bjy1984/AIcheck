from __future__ import annotations

from typing import Any

from libs.review_orchestrator.material_facts import (
    build_material_judgment,
    deduplicate,
    extract_material_design_items,
    extract_material_ndt_reports,
    extract_material_retest_reports,
    iter_requested_parse_results,
    material_document_kind,
)


R18_NODE_ID = 18


def build_r18_business_facts(state: dict[str, Any], review_run: dict[str, Any]) -> dict[str, Any]:
    design_items = extract_material_design_items(state, review_run, namespace="R18")
    retest_reports: list[dict[str, Any]] = []
    ndt_reports: list[dict[str, Any]] = []
    for parse_result in iter_requested_parse_results(state, review_run):
        kind = material_document_kind(state, parse_result)
        if kind == "material_retest_report":
            retest_reports.extend(extract_material_retest_reports(state, parse_result))
        elif kind == "material_ndt_report":
            ndt_reports.extend(extract_material_ndt_reports(state, parse_result))
    retest_reports = deduplicate(retest_reports, "reportId")
    ndt_reports = deduplicate(ndt_reports, "reportId")
    judgment = build_material_judgment(
        [
            ("r18-design-item", design_items, ("productName", "batchNo")),
            ("r18-retest-report", retest_reports, ("reportNo", "sampleNo")),
            ("r18-material-ndt-report", ndt_reports, ("reportNo", "batchNo")),
        ]
    )
    return {"r18": {"designItems": design_items, "retestReports": retest_reports, "materialNdtReports": ndt_reports}, **judgment}
