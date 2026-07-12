from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REQUIRED_FAULT_COMPONENTS = {
    "redis",
    "worker",
    "temporal",
    "ocr",
    "qwen",
    "embedding",
    "minio",
    "postgresql",
    "api",
}


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def build_ocr_98_release_gate(
    *,
    annotation_readiness: dict[str, Any],
    evaluation_report: dict[str, Any],
    pipeline_evidence: dict[str, Any],
    fault_injection: dict[str, Any],
    user_acceptance: dict[str, Any],
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, actual: Any, expected: str) -> None:
        checks.append(
            {
                "name": name,
                "status": "pass" if passed else "fail",
                "actual": actual,
                "expected": expected,
            }
        )

    annotation_summary = annotation_readiness.get("summary") or {}
    human_labeled = int(annotation_summary.get("humanLabeled") or 0)
    ready_for_eval = int(annotation_summary.get("readyForEval") or 0)
    check("annotations.human-labeled", human_labeled >= 50, human_labeled, ">= 50")
    check("annotations.ready-for-eval", ready_for_eval >= 50, ready_for_eval, ">= 50")

    evaluation_summary = evaluation_report.get("summary") or {}
    metrics = evaluation_report.get("metrics") or {}
    cases = int(evaluation_summary.get("cases") or 0)
    check("evaluation.real-cases", cases >= 50, cases, ">= 50")
    derived_cases = [
        item
        for item in evaluation_report.get("cases") or []
        if isinstance(item, dict)
        and (item.get("bootstrapGenerated") or item.get("fixtureDerived") or item.get("collectionStatus") == "needs_real_sample_replacement")
    ]
    check("evaluation.no-derived-cases", not derived_cases, len(derived_cases), "0")
    check("evaluation.field-value-accuracy", float(metrics.get("fieldValueAccuracy") or 0) >= 0.98, metrics.get("fieldValueAccuracy"), ">= 0.98")
    check("evaluation.field-bbox-coverage", float(metrics.get("fieldBboxHitRate") or 0) >= 0.98, metrics.get("fieldBboxHitRate"), ">= 0.98")
    table_accuracy = float(pipeline_evidence.get("tableRowStructureAccuracy") or 0)
    check("evaluation.table-row-structure", table_accuracy >= 0.97, table_accuracy, ">= 0.97")

    ai_error_value = pipeline_evidence.get("aiStandardReferenceErrorRate")
    ai_error_rate = float(ai_error_value if ai_error_value is not None else 1)
    check("pipeline.ai-reference-error", ai_error_rate <= 0.01, ai_error_rate, "<= 0.01")
    check(
        "pipeline.wrong-expiry-reference",
        int(pipeline_evidence.get("wrongExpiryReferenceCount") or 0) == 0,
        pipeline_evidence.get("wrongExpiryReferenceCount"),
        "0",
    )
    check(
        "pipeline.formal-without-confirmed-evidence",
        int(pipeline_evidence.get("formalConclusionWithoutConfirmedEvidenceCount") or 0) == 0,
        pipeline_evidence.get("formalConclusionWithoutConfirmedEvidenceCount"),
        "0",
    )
    workflow_rate = float(pipeline_evidence.get("criticalWorkflowPassRate") or 0)
    check("pipeline.critical-workflow-pass-rate", workflow_rate >= 1, workflow_rate, "1.0")
    check("pipeline.release-probe-skips", int(pipeline_evidence.get("releaseProbeSkipCount") or 0) == 0, pipeline_evidence.get("releaseProbeSkipCount"), "0")

    components = fault_injection.get("components") or {}
    passed_components = {
        str(name)
        for name, result in components.items()
        if isinstance(result, dict) and result.get("status") == "pass" and not result.get("skipped")
    }
    missing_components = sorted(REQUIRED_FAULT_COMPONENTS - passed_components)
    check("reliability.fault-injection", not missing_components, missing_components, "all required components pass without skip")
    check("reliability.duplicate-records", int(fault_injection.get("duplicateRecordCount") or 0) == 0, fault_injection.get("duplicateRecordCount"), "0")
    check("reliability.hanging-business-states", int(fault_injection.get("hangingBusinessStateCount") or 0) == 0, fault_injection.get("hangingBusinessStateCount"), "0")

    participants = int(user_acceptance.get("participants") or 0)
    task_success = float(user_acceptance.get("taskSuccessRate") or 0)
    sus = float(user_acceptance.get("sus") or 0)
    check("acceptance.participants", participants >= 5, participants, ">= 5")
    check("acceptance.task-success", task_success >= 1, task_success, "1.0")
    check("acceptance.sus", sus >= 85, sus, ">= 85")

    failures = [item for item in checks if item["status"] == "fail"]
    return {
        "schemaVersion": "aicheck-ocr-98-release-gate-v1",
        "generatedAt": datetime.now(UTC).isoformat(),
        "ok": not failures,
        "scoreBand": "98-99" if not failures else "below-98-or-unverified",
        "checks": checks,
        "failures": failures,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate OCR and audit-pipeline evidence required for a real 98+ release.")
    parser.add_argument("--annotation-readiness", required=True)
    parser.add_argument("--evaluation-report", required=True)
    parser.add_argument("--pipeline-evidence", required=True)
    parser.add_argument("--fault-injection", required=True)
    parser.add_argument("--user-acceptance", required=True)
    parser.add_argument("--output")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_ocr_98_release_gate(
        annotation_readiness=load_json(Path(args.annotation_readiness)),
        evaluation_report=load_json(Path(args.evaluation_report)),
        pipeline_evidence=load_json(Path(args.pipeline_evidence)),
        fault_injection=load_json(Path(args.fault_injection)),
        user_acceptance=load_json(Path(args.user_acceptance)),
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
