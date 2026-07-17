from __future__ import annotations

from typing import Any

from libs.review_orchestrator.material_facts import (
    build_material_judgment,
    deduplicate,
    extract_material_design_items,
    extract_quality_certificates,
    iter_requested_parse_results,
    material_document_kind,
)


R16_NODE_ID = 16


def build_r16_business_facts(state: dict[str, Any], review_run: dict[str, Any]) -> dict[str, Any]:
    design_items = extract_material_design_items(state, review_run, namespace="R16")
    certificates: list[dict[str, Any]] = []
    for parse_result in iter_requested_parse_results(state, review_run):
        if material_document_kind(state, parse_result) == "quality_certificate":
            certificates.extend(extract_quality_certificates(state, parse_result))
    certificates = deduplicate(certificates, "certificateId")
    judgment = build_material_judgment(
        [
            ("r16-design-item", design_items, ("productName", "standardRef")),
            ("r16-quality-certificate", certificates, ("certificateNo", "batchNo")),
        ]
    )
    return {"r16": {"designItems": design_items, "qualityCertificates": certificates}, **judgment}
