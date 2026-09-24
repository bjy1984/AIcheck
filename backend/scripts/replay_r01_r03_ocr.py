"""Replay the two known certificate defects from a scoped, local OCR snapshot.

The input is an exported JSON object containing one project's projects,
documents, versions, OCR parses, two frozen review runs (nodes 1 and 3), and
their recorded CNSE cache entries. The script never queries CNSE or Jev and
prints only verdicts and coverage metadata, not OCR text or personal data.
Do not commit a raw fixture built from production OCR.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from libs.business_pack.loader import DEFAULT_BUSINESS_PACK_ID, load_business_pack
from libs.contracts.responses import SERVER_TZ
from libs.integrations import external_registry_queries as registry
from libs.review_orchestrator import certificate_platform_verify as platform
from libs.review_orchestrator.certificate_facts import (
    build_certificate_facts,
    merge_certificate_facts,
)
from libs.review_orchestrator.deterministic_tools import (
    check_certificate_validity,
    check_design_license_scope,
)
from libs.review_orchestrator.pipeline_facts import merge_project_pipelines
from libs.review_tools.executor import build_tool_arguments

CHECKS = {
    "AC-R01-02": check_design_license_scope,
    "AC-R01-03": check_certificate_validity,
    "AC-R01-04": check_design_license_scope,
}


def _frozen_cache_time(state: dict) -> datetime:
    entries = state.get("cnse_lookup_cache") or []
    if len(entries) != 2 or any(row.get("kind") != "org_license" or row.get("error") or not row.get("result")
                                for row in entries):
        raise ValueError("two_recorded_org_license_lookups_required")
    timestamps = [datetime.strptime(str(row["queriedAt"]), "%Y-%m-%d %H:%M:%S").replace(tzinfo=SERVER_TZ)
                  for row in entries]
    if max(timestamps) - min(timestamps) >= timedelta(hours=24):
        raise ValueError("recorded_lookups_outside_cache_window")
    return max(timestamps) + timedelta(minutes=1)


def _r01_outputs(state: dict, run: dict) -> dict:
    facts = merge_project_pipelines(state, run, merge_certificate_facts(state, run, {}))
    old = {row["atomicCheckId"]: row for row in run["atomicCheckToolBindingsSnapshot"]}
    current = {row["atomicCheckId"]: row for row in load_business_pack(DEFAULT_BUSINESS_PACK_ID)["atomicCheckToolBindings"]}
    output: dict[str, dict] = {}
    for label, bindings in (("frozenOld", old), ("currentPack", current)):
        output[label] = {}
        for atomic_id, tool in CHECKS.items():
            binding = bindings[atomic_id]
            name = tool.__name__
            if name not in binding.get("tools", []):
                raise ValueError("r01_tool_binding_mismatch")
            arguments = build_tool_arguments(
                name, binding, facts=facts, explicit={},
                document_version_ids=run["inputDocumentVersionIds"], evidence_facts=[], evidence_refs=[],
            )
            verdict = tool(arguments)
            output[label][atomic_id] = {
                "result": verdict["result"],
                "scopeProfile": arguments.get("scopeProfile") or "design-license-scope-cn-v1",
                "requiredGrades": arguments.get("requiredPipelineGrades") or arguments.get("requiredScopes") or [],
            }
    return output


def replay(state: dict) -> dict:
    if state.get("source") != "read_only_production_ocr_snapshot":
        raise ValueError("scoped_production_ocr_snapshot_required")
    runs = {int(row["nodeId"]): row for row in state.get("review_runs") or []}
    if set(runs) != {1, 3} or len(state.get("review_runs") or []) != 2:
        raise ValueError("one_r01_and_one_r03_run_required")
    project_ids = {str(row.get("projectId")) for row in runs.values()}
    if len(project_ids) != 1 or len(state.get("projects") or []) != 1:
        raise ValueError("single_project_required")
    project_id = next(iter(project_ids))
    if str(state["projects"][0].get("id")) != project_id:
        raise ValueError("run_project_mismatch")
    if any(str(run.get("businessPackId")) != DEFAULT_BUSINESS_PACK_ID for run in runs.values()):
        raise ValueError("unexpected_business_pack")
    requested_versions = {str(version) for run in runs.values()
                          for version in run.get("inputDocumentVersionIds") or []}
    versions = {str(row.get("id") or row.get("documentVersionId")): row
                for row in state.get("versions") or []}
    documents = {str(row.get("id")): row for row in state.get("documents") or []}
    parsed_versions = {str(row.get("documentVersionId")) for row in state.get("ocr_parse_results") or []}
    if (set(versions) != requested_versions or parsed_versions != requested_versions
            or any(str(version.get("documentId")) not in documents for version in versions.values())
            or any(str(document.get("projectId")) != project_id for document in documents.values())):
        raise ValueError("ocr_snapshot_scope_mismatch")
    frozen_now = _frozen_cache_time(state)
    forbidden_query = Mock(side_effect=AssertionError("outbound_registry_call_forbidden"))
    with (patch.dict(os.environ, {"AICHECK_CERT_PLATFORM_VERIFY": "on"}),
          patch.object(platform, "_now", return_value=frozen_now),
          patch.object(registry, "query_cnse_organization_license", forbidden_query)):
        r01 = _r01_outputs(state, runs[1])
        run = runs[3]
        facts = build_certificate_facts(
            state, str(run["projectId"]), 3, run["inputDocumentVersionIds"], review_run=run,
        )
        certificates = facts["certificateFacts"]["certificates"]
        if len(certificates) != 1:
            raise ValueError("one_r03_certificate_required")
        certificate = certificates[0]
        r03 = {
            "holderPresent": bool(certificate.get("holder")),
            "unreliableHolderRejected": bool(certificate.get("holderFieldRejected")),
            "platformOutcome": (certificate.get("platformVerification") or {}).get("outcome"),
            "certificateVerdict": check_certificate_validity({
                "certificates": certificates, "referenceDate": "2026-09-13",
            })["result"],
        }
    report = {
        "schemaVersion": "r01-r03-ocr-replay-v1",
        "inputRunIds": {str(node): str(run.get("reviewRunId")) for node, run in runs.items()},
        "ocrVersions": len(state.get("ocr_parse_results") or []),
        "registrySource": "recorded_cache_only",
        "outboundRegistryCalls": forbidden_query.call_count,
        "r01": r01,
        "r03": r03,
    }
    report["acceptanceMet"] = (
        forbidden_query.call_count == 0
        and all(r01[label][atomic]["result"] == "passed" for label in ("frozenOld", "currentPack")
                for atomic in CHECKS)
        and r03["unreliableHolderRejected"] and not r03["holderPresent"]
        and r03["platformOutcome"] == "unable_to_verify"
        and r03["certificateVerdict"] == "evidence_insufficient"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path, help="Private, scoped JSON export; never commit raw OCR")
    args = parser.parse_args()
    report = replay(json.loads(args.fixture.read_text(encoding="utf-8")))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["acceptanceMet"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
