from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from apps.ocr_service.profiles import profile_for
from libs.contracts.responses import server_time
from libs.db.repository import flush_state_records, load_state, repo
from libs.integrations import task_dispatcher
from libs.integrations.storage import object_storage
from libs.ocr_accuracy_pipeline import pipeline_version


TERMINAL_STATUSES = {"completed", "partial", "failed", "canceled"}
SCENARIO_TAG = "ocr-accuracy-regression-v2"
EXPECTED_STAGE_ENGINES = {
    "structure_scan": "pp_structure_v3",
    "seal_signature_scan": "paddlex_seal_recognition",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dispatch and summarize server-side OCR accuracy regression runs.")
    parser.add_argument("--manifest", default=str(BACKEND_ROOT / "ocr_eval" / "scan_regression_manifest_v2.json"))
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--limit", type=int, choices=[2, 10, 30], default=30)
    parser.add_argument("--timeout-seconds", type=int, default=43_200)
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--output")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_id(prefix: str, value: str) -> str:
    return f"{prefix}-{hashlib.sha256(value.encode('utf-8')).hexdigest()[:14].upper()}"


def safe_campaign(value: str) -> str:
    normalized = re.sub(r"[^0-9A-Za-z._-]+", "-", value.strip()).strip("-.")
    if not normalized:
        raise ValueError("campaign must contain at least one safe character")
    return normalized[:80]


def require_server_runtime() -> None:
    if task_dispatcher.dispatch_mode() != "celery":
        raise RuntimeError("OCR regression requires AICHECK_TASK_DISPATCH=celery")
    if not str(os.getenv("AICHECK_OCR_BASE_URL") or "").strip():
        raise RuntimeError("OCR regression requires the server OCR service URL")
    if not object_storage.enabled:
        raise RuntimeError("OCR regression requires MinIO object storage")


def select_cases(cases: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if limit >= len(cases):
        return cases
    cold = [item for item in cases if item.get("coldProbe")]
    normal = [item for item in cases if not item.get("coldProbe")]
    if limit == 2:
        return cold[:2]
    return [*cold, *normal][:limit]


def load_cases(manifest_path: Path, source_root: Path, limit: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    all_cases = [item for item in manifest.get("cases") or [] if isinstance(item, dict)]
    cases = select_cases(all_cases, limit)
    for case in cases:
        source = source_root / str(case.get("path") or "")
        if not source.is_file():
            raise FileNotFoundError(source)
        actual = sha256_file(source)
        if actual != str(case.get("sha256") or ""):
            raise RuntimeError(f"source hash mismatch for {case.get('caseId')}: {actual}")
        case["sourcePath"] = str(source)
    return manifest, cases


def register_state_record(collection: str, record: dict[str, Any], *, id_field: str = "id") -> None:
    records = repo.state.setdefault(collection, [])
    record_id = str(record.get(id_field) or "")
    existing_index = next(
        (
            index
            for index, item in enumerate(records)
            if isinstance(item, dict) and str(item.get(id_field) or "") == record_id
        ),
        None,
    )
    if existing_index is None:
        records.insert(0, record)
    else:
        records[existing_index] = record


def ensure_case_records(case: dict[str, Any], campaign: str) -> tuple[dict[str, Any], dict[str, Any]]:
    case_id = str(case["caseId"])
    source_path = Path(str(case["sourcePath"]))
    profile = profile_for(str(case["expectedProfileId"]))
    document_id = stable_id("DOC-OCRREG", f"{campaign}:{case_id}")
    version_id = stable_id("DV-OCRREG", f"{campaign}:{case_id}")
    knowledge_file_id = f"KF-{document_id}"
    bucket = "documents"
    object_name = f"ocr-regression/{safe_campaign(campaign)}/{case_id}/{source_path.name}"
    storage_url = object_storage.put_bytes(
        bucket,
        object_name,
        source_path.read_bytes(),
        content_type=mimetypes.guess_type(source_path.name)[0] or "application/octet-stream",
    )
    if not storage_url:
        raise RuntimeError(f"failed to upload {case_id} to MinIO")
    now = server_time()
    document = repo.find_one("documents", document_id) or {
        "id": document_id,
        "createdAt": now,
    }
    document.update(
        {
            "fileName": source_path.name,
            "fileType": mimetypes.guess_type(source_path.name)[0] or "application/octet-stream",
            "currentVersionId": version_id,
            "currentOcrStatus": "排队中",
            "fileStatus": "已上传",
            "ocrProfileId": profile.get("profileId"),
            "documentType": profile.get("documentType"),
            "scenarioTag": SCENARIO_TAG,
            "regressionCampaign": campaign,
            "updatedAt": now,
        }
    )
    version = repo.find_one("versions", version_id) or {
        "id": version_id,
        "documentId": document_id,
        "versionNo": "V1",
        "createdAt": now,
    }
    version.update(
        {
            "storageKey": storage_url,
            "storageBucket": "documents",
            "fileName": source_path.name,
            "fileSize": source_path.stat().st_size,
            "hash": f"sha256-{case['sha256']}",
            "ocrStatus": "排队中",
            "ocrProfileId": profile.get("profileId"),
            "documentType": profile.get("documentType"),
            "ocrOptions": {
                "disableResultCache": bool(case.get("coldProbe")),
                "disableEngineResultCache": bool(case.get("coldProbe")),
                "disableVariantCache": bool(case.get("coldProbe")),
            },
            "scenarioTag": SCENARIO_TAG,
            "regressionCampaign": campaign,
            "updatedAt": now,
        }
    )
    knowledge_file = repo.find_one("knowledge_files", knowledge_file_id) or {
        "id": knowledge_file_id,
        "sourceId": "KS-OCR-REGRESSION",
        "sourceName": "OCR 回归资料",
        "documentId": document_id,
        "documentVersionId": version_id,
        "createdAt": now,
    }
    knowledge_file.update(
        {
            "fileName": source_path.name,
            "ocrStatus": "排队中",
            "scenarioTag": SCENARIO_TAG,
            "regressionCampaign": campaign,
            "updatedAt": now,
        }
    )
    task = repo.upsert_knowledge_task(
        task_type="ocr",
        target_id=knowledge_file_id,
        target_name=source_path.name,
        document_id=document_id,
        version_id=version_id,
        status="排队中",
        progress=0,
    )
    task["scenarioTag"] = SCENARIO_TAG
    task["regressionCampaign"] = campaign
    register_state_record("documents", document)
    register_state_record("versions", version)
    register_state_record("knowledge_files", knowledge_file)
    register_state_record("knowledge_tasks", task)
    version["storageBucket"] = bucket
    flush_state_records(
        {
            "documents": [document],
            "versions": [version],
            "knowledge_files": [knowledge_file],
            "knowledge_tasks": [task],
        }
    )
    return document, version


def runs_for_version(version_id: str) -> list[dict[str, Any]]:
    return [
        item
        for item in repo.state.get("ocr_pipeline_runs", [])
        if str(item.get("documentVersionId") or "") == version_id
        and str(item.get("pipelineVersion") or "") == pipeline_version()
    ]


def dispatch_case(case: dict[str, Any], campaign: str) -> dict[str, Any]:
    document, version = ensure_case_records(case, campaign)
    existing = runs_for_version(str(version["id"]))
    terminal = next((item for item in existing if item.get("status") in TERMINAL_STATUSES), None)
    if terminal:
        return {"caseId": case["caseId"], "pipelineRunId": terminal.get("id"), "reused": True}
    dispatched = task_dispatcher.dispatch_parse_document(
        str(document["id"]),
        str(version["id"]),
        str(version["storageKey"]),
        str(document["fileName"]),
    )
    return {"caseId": case["caseId"], "taskId": dispatched.get("taskId"), "reused": False}


def stage_map(run_id: str) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("stage")): item
        for item in repo.state.get("ocr_stage_runs", [])
        if str(item.get("pipelineRunId") or "") == run_id
    }


def duplicate_stage_count(run_id: str) -> int:
    counts: dict[str, int] = {}
    for item in repo.state.get("ocr_stage_runs", []):
        if str(item.get("pipelineRunId") or "") != run_id:
            continue
        stage = str(item.get("stage") or "")
        counts[stage] = counts.get(stage, 0) + 1
    return sum(max(0, count - 1) for count in counts.values())


def stage_engine_gate(
    stage: dict[str, Any],
    *,
    expected: bool,
    expected_engine: str,
    cold_probe: bool,
) -> dict[str, Any]:
    if not expected:
        return {"applicable": False, "passed": stage.get("status") == "skipped"}
    engine_status = stage.get("engineStatus") if isinstance(stage.get("engineStatus"), dict) else {}
    executed = {str(item) for item in engine_status.get("engineExecuted") or []}
    succeeded = {str(item) for item in engine_status.get("engineSucceeded") or []}
    runs = [item for item in engine_status.get("runs") or [] if isinstance(item, dict)]
    matching_runs = [item for item in runs if str(item.get("engine") or "") == expected_engine]
    engine_succeeded = expected_engine in succeeded or any(
        str(item.get("status") or "").lower() == "success" for item in matching_runs
    )
    positive_duration = any(
        int(item.get("durationMs") or 0) > 0 and not bool(item.get("engineCacheHit"))
        for item in matching_runs
    )
    return {
        "applicable": True,
        "passed": expected_engine in executed and engine_succeeded and (not cold_probe or positive_duration),
        "expectedEngine": expected_engine,
        "engineExecuted": expected_engine in executed,
        "engineSucceeded": engine_succeeded,
        "positiveDuration": positive_duration,
        "cacheSourceRunIds": engine_status.get("cacheSourceRunIds") or [],
        "stageStatus": stage.get("status"),
    }


def summarize_case(case: dict[str, Any], campaign: str, capabilities: dict[str, Any]) -> dict[str, Any]:
    version_id = stable_id("DV-OCRREG", f"{campaign}:{case['caseId']}")
    runs = runs_for_version(version_id)
    run = sorted(runs, key=lambda item: str(item.get("updatedAt") or ""), reverse=True)[0] if runs else {}
    stages = stage_map(str(run.get("id") or "")) if run else {}
    attempts = [
        item
        for item in repo.state.get("model_call_attempts", [])
        if str(item.get("pipelineRunId") or "") == str(run.get("id") or "")
    ]
    parse_result = repo.find_one(
        "ocr_parse_results",
        str(run.get("fusedParseResultId") or run.get("baselineParseResultId") or ""),
        id_field="parseResultId",
    ) or {}
    structure_expected = bool(capabilities.get("structure"))
    seal_expected = bool(capabilities.get("seal"))
    stage_engine_gates = {
        "structure_scan": stage_engine_gate(
            stages.get("structure_scan") or {},
            expected=structure_expected,
            expected_engine=EXPECTED_STAGE_ENGINES["structure_scan"],
            cold_probe=bool(case.get("coldProbe")),
        ),
        "seal_signature_scan": stage_engine_gate(
            stages.get("seal_signature_scan") or {},
            expected=seal_expected,
            expected_engine=EXPECTED_STAGE_ENGINES["seal_signature_scan"],
            cold_probe=bool(case.get("coldProbe")),
        ),
    }
    applicable_failures = [
        name
        for name, gate in stage_engine_gates.items()
        if gate.get("applicable") and not gate.get("passed")
    ]
    return {
        "caseId": case["caseId"],
        "source": case["path"],
        "sha256": case["sha256"],
        "expectedProfileId": case["expectedProfileId"],
        "detectedProfileId": run.get("detectedProfileId") or run.get("profileId"),
        "profileMatched": str(run.get("detectedProfileId") or run.get("profileId") or "")
        == str(case["expectedProfileId"]),
        "pipelineRunId": run.get("id"),
        "status": run.get("status") or "not_started",
        "stages": {name: item.get("status") for name, item in stages.items()},
        "stageElapsedSeconds": {
            name: item.get("elapsedSeconds")
            for name, item in stages.items()
            if item.get("elapsedSeconds") is not None
        },
        "engineStatus": {name: item.get("engineStatus") or {} for name, item in stages.items()},
        "stageEngineGates": stage_engine_gates,
        "applicableEngineFailures": applicable_failures,
        "invalidCandidateIdCount": int(((run.get("groundingValidation") or {}).get("invalidCandidateIdCount") or 0)),
        "unsupportedAttributionCount": int(((run.get("groundingValidation") or {}).get("unsupportedAttributionCount") or 0)),
        "droppedUnsupportedAttributionCount": int(
            ((run.get("groundingValidation") or {}).get("droppedUnsupportedAttributionCount") or 0)
        ),
        "candidateRepairCount": int(((run.get("groundingValidation") or {}).get("candidateRepairCount") or 0)),
        "formalEvidenceReady": bool(run.get("formalEvidenceReady")),
        "resultCounts": {
            "fields": len(parse_result.get("fields") or []),
            "fragments": len(parse_result.get("fragments") or []),
            "tables": len(parse_result.get("tables") or []),
            "seals": len(parse_result.get("seals") or []),
        },
        "qwenUsage": run.get("qwenUsage") or {},
        "estimatedCostCny": round(sum(float(item.get("estimatedCostCny") or 0) for item in attempts), 6),
        "modelCallAttempts": len(attempts),
        "duplicatePipelineRunCount": max(0, len(runs) - 1),
        "duplicateStageRunCount": duplicate_stage_count(str(run.get("id") or "")),
    }


def build_report(manifest: dict[str, Any], cases: list[dict[str, Any]], campaign: str) -> dict[str, Any]:
    load_state({"ocr_pipeline_runs", "ocr_stage_runs", "ocr_parse_results", "model_call_attempts"})
    capabilities = manifest.get("profileCapabilities") or {}
    items = [summarize_case(case, campaign, capabilities.get(case["expectedProfileId"]) or {}) for case in cases]
    terminal = [item for item in items if item["status"] in TERMINAL_STATUSES]
    return {
        "schemaVersion": "aicheck-ocr-accuracy-regression-report@2",
        "generatedAt": server_time(),
        "campaign": campaign,
        "pipelineVersion": pipeline_version(),
        "mode": "shadow",
        "summary": {
            "cases": len(items),
            "terminal": len(terminal),
            "systemFailures": len([item for item in items if item["status"] == "failed"]),
            "profileMismatchCount": len([item for item in items if not item["profileMatched"]]),
            "applicableEngineFailureCount": sum(len(item["applicableEngineFailures"]) for item in items),
            "duplicatePipelineRunCount": sum(item["duplicatePipelineRunCount"] for item in items),
            "duplicateStageRunCount": sum(item["duplicateStageRunCount"] for item in items),
            "invalidCandidateIdCount": sum(item["invalidCandidateIdCount"] for item in items),
            "unsupportedAttributionCount": sum(item["unsupportedAttributionCount"] for item in items),
            "droppedUnsupportedAttributionCount": sum(
                item["droppedUnsupportedAttributionCount"] for item in items
            ),
            "candidateRepairCount": sum(item["candidateRepairCount"] for item in items),
            "formalEvidenceReadyCount": len([item for item in items if item["formalEvidenceReady"]]),
            "estimatedCostCny": round(sum(item["estimatedCostCny"] for item in items), 6),
        },
        "items": items,
    }


def main() -> int:
    args = parse_args()
    args.campaign = safe_campaign(args.campaign)
    manifest, cases = load_cases(Path(args.manifest), Path(args.source_root), args.limit)
    if args.dry_run:
        print(json.dumps({"ok": True, "cases": len(cases), "campaign": args.campaign}, ensure_ascii=False))
        return 0
    require_server_runtime()
    load_state()
    dispatches = [dispatch_case(case, args.campaign) for case in cases]
    deadline = time.monotonic() + max(1, args.timeout_seconds)
    report = build_report(manifest, cases, args.campaign)
    while report["summary"]["terminal"] < len(cases) and time.monotonic() < deadline:
        time.sleep(max(0.5, args.poll_seconds))
        report = build_report(manifest, cases, args.campaign)
    report["dispatches"] = dispatches
    report["timedOut"] = report["summary"]["terminal"] < len(cases)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    summary = report["summary"]
    failed_gates = [
        report["timedOut"],
        summary["terminal"] != len(cases),
        summary["systemFailures"] != 0,
        summary["profileMismatchCount"] != 0,
        summary["applicableEngineFailureCount"] != 0,
        summary["duplicatePipelineRunCount"] != 0,
        summary["duplicateStageRunCount"] != 0,
        summary["invalidCandidateIdCount"] != 0,
        summary["unsupportedAttributionCount"] != 0,
        summary["formalEvidenceReadyCount"] != 0,
    ]
    return 1 if any(failed_gates) else 0


if __name__ == "__main__":
    raise SystemExit(main())
