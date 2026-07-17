from __future__ import annotations

from typing import Any

from libs.review_orchestrator.material_facts import (
    build_material_judgment,
    deduplicate,
    extract_arrival_acceptance_records,
    extract_material_design_items,
    extract_material_retest_reports,
    extract_sampling_witness_records,
    iter_requested_parse_results,
    material_document_kind,
)


R17_NODE_ID = 17


def build_r17_business_facts(state: dict[str, Any], review_run: dict[str, Any]) -> dict[str, Any]:
    design_items = extract_material_design_items(state, review_run, namespace="R17")
    acceptance_records: list[dict[str, Any]] = []
    witness_records: list[dict[str, Any]] = []
    retest_reports: list[dict[str, Any]] = []
    for parse_result in iter_requested_parse_results(state, review_run):
        kind = material_document_kind(state, parse_result)
        if kind == "arrival_acceptance_record":
            acceptance_records.extend(extract_arrival_acceptance_records(state, parse_result))
        elif kind == "sampling_witness_record":
            witness_records.extend(extract_sampling_witness_records(state, parse_result))
        elif kind == "material_retest_report":
            retest_reports.extend(extract_material_retest_reports(state, parse_result))
    acceptance_records = deduplicate(acceptance_records, "recordId")
    witness_records = deduplicate(witness_records, "recordId")
    retest_reports = deduplicate(retest_reports, "reportId")
    judgment = build_material_judgment(
        [
            ("r17-design-item", design_items, ("productName", "batchNo")),
            ("r17-acceptance-record", acceptance_records, ("recordNo", "batchNo")),
            ("r17-witness-record", witness_records, ("recordNo", "sampleNo")),
            ("r17-retest-report", retest_reports, ("reportNo", "sampleNo")),
        ]
    )
    return {
        "r17": {
            "designItems": design_items,
            "acceptanceRecords": acceptance_records,
            "witnessRecords": witness_records,
            "samplingRetestReports": retest_reports,
            "samplingRules": list(review_run.get("samplingRules") or []),
        },
        **judgment,
    }
