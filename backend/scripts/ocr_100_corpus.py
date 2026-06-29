from __future__ import annotations

import argparse
import csv
import json
import sys
from io import StringIO
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.ocr_service.evaluation import OCR_100_REQUIRED_SCENARIOS, ocr_100_thresholds
from scripts.ocr_eval_set import write_text_file

OCR_100_SCENARIO_TARGETS = {
    "piping_table_profile": 12,
    "quality_certificate_profile": 10,
    "ndt_rt_profile": 10,
    "ndt_ut_profile": 8,
    "construction_record_profile": 10,
    "welding_record_profile": 10,
    "qualification_certificate_profile": 8,
    "seal_text_profile": 8,
    "fragment_seal_profile": 8,
    "evidence_profile": 8,
    "quality_gate_profile": 8,
}

SCENARIO_COLLECTION_HINTS = {
    "piping_table_profile": "Collect dense piping characteristic list photos/PDFs with table grid, drawing number, and weld-detection columns.",
    "quality_certificate_profile": "Collect material/product quality certificates with certificate number, heat/batch number, material grade, tables, and stamps.",
    "ndt_rt_profile": "Collect real radiographic testing reports, including report cover/main table, weld numbers, RT method, conclusion, and testing seal.",
    "ndt_ut_profile": "Collect real ultrasonic testing reports, including report number, weld/part number, UT method, probe/level fields, result table, and testing seal.",
    "construction_record_profile": "Collect construction/handover records with project metadata, tabular construction records, signatures, and stamps.",
    "welding_record_profile": "Collect welding procedure qualification or welding record documents with WPS/PQR identifiers, weld fields, result tables, and signatures.",
    "qualification_certificate_profile": "Collect qualification/license certificates with organization name, certificate number, validity period, issuing authority, and official seal.",
    "seal_text_profile": "Collect close-up or full-page stamped documents where the seal text must be read and localized.",
    "fragment_seal_profile": "Collect stamped drawings or low-contrast documents where seal text may require OCR fragment fusion rather than a clean seal crop.",
    "evidence_profile": "Collect documents where fields/tables/seals need explicit page bbox/polygon evidence for traceability.",
    "quality_gate_profile": "Collect low-quality, folded, skewed, blurry, low-contrast, or partially occluded documents that should trigger needs_human_review diagnostics.",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and validate an AIcheck OCR 100 release evaluation corpus.")
    parser.add_argument("inputs", nargs="+", help="Eval set JSON files or directories containing eval set JSON files.")
    parser.add_argument("--output", help="Optional combined eval set JSON output path.")
    parser.add_argument("--report-output", help="Optional corpus validation report JSON path.")
    parser.add_argument("--collection-plan-output", help="Optional JSON output path for the real-sample collection plan.")
    parser.add_argument("--collection-todo-output", help="Optional CSV output path for missing real-sample collection tasks.")
    parser.add_argument("--bootstrap-to-targets", action="store_true", help="Expand provided template cases into the 100-case target distribution. Use only to create a collection skeleton.")
    parser.add_argument("--require-real-samples", action="store_true", help="Fail if any case is bootstrap-generated, fixture-derived, or marked as needing real sample replacement.")
    parser.add_argument("--allow-missing-expected-evidence", action="store_true", help="Do not fail when expected fields/tables/seals lack bbox or polygon evidence.")
    parser.add_argument("--json", action="store_true", help="Print the full validation report instead of a compact summary.")
    args = parser.parse_args()

    report = build_corpus_report(
        args.inputs,
        bootstrap_to_targets=bool(args.bootstrap_to_targets),
        require_real_samples=bool(args.require_real_samples),
        allow_missing_expected_evidence=bool(args.allow_missing_expected_evidence),
    )
    if args.output:
        write_text_file(
            Path(args.output),
            json.dumps(
                {
                    "name": "aicheck_ocr_100_release_set",
                    "thresholds": ocr_100_thresholds(),
                    "bootstrap": report["bootstrap"],
                    "cases": report["cases"],
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    public_report = {key: value for key, value in report.items() if key != "cases"}
    if args.report_output:
        write_text_file(Path(args.report_output), json.dumps(public_report, ensure_ascii=False, indent=2))
    if args.collection_plan_output:
        write_text_file(Path(args.collection_plan_output), json.dumps(report["collectionPlan"], ensure_ascii=False, indent=2))
    if args.collection_todo_output:
        write_text_file(Path(args.collection_todo_output), collection_todo_csv(report["collectionPlan"]))
    print(json.dumps(public_report if args.json else public_report["summary"], ensure_ascii=False, indent=2))
    return 0 if public_report["ok"] else 1


def build_corpus_report(
    inputs: list[str | Path],
    *,
    bootstrap_to_targets: bool = False,
    require_real_samples: bool = False,
    allow_missing_expected_evidence: bool = False,
) -> dict[str, Any]:
    files = eval_set_files(inputs)
    cases: list[dict[str, Any]] = []
    input_failures: list[str] = []
    for path in files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            input_failures.append(f"{path}: load failed: {exc.__class__.__name__}")
            continue
        loaded = payload.get("cases") if isinstance(payload, dict) else payload
        if not isinstance(loaded, list):
            input_failures.append(f"{path}: missing cases[]")
            continue
        for index, case in enumerate(loaded):
            if not isinstance(case, dict):
                input_failures.append(f"{path}: case[{index}] is not an object")
                continue
            normalized = dict(case)
            normalized.setdefault("sourceEvalSet", str(path))
            cases.append(normalized)
    bootstrap = {"enabled": bool(bootstrap_to_targets), "derivedCases": 0, "sourceCases": len(cases)}
    if bootstrap_to_targets and cases:
        cases = bootstrap_cases_to_targets(cases)
        bootstrap["derivedCases"] = len([case for case in cases if case.get("fixtureDerived")])
    failures = corpus_failures(
        cases,
        input_failures,
        require_real_samples=require_real_samples,
        allow_missing_expected_evidence=allow_missing_expected_evidence,
    )
    scenario_counts = count_scenarios(cases)
    target_gaps = scenario_target_gaps(scenario_counts)
    summary = {
        "inputFiles": len(files),
        "cases": len(cases),
        "requiredCases": int(ocr_100_thresholds()["minCases"]),
        "scenarioCounts": scenario_counts,
        "requiredScenarios": OCR_100_REQUIRED_SCENARIOS,
        "scenarioTargets": OCR_100_SCENARIO_TARGETS,
        "scenarioTargetGaps": target_gaps,
        "missingScenarios": [scenario for scenario in OCR_100_REQUIRED_SCENARIOS if scenario_counts.get(scenario, 0) < 1],
        "failureCount": len(failures),
        "requireRealSamples": bool(require_real_samples),
    }
    return {
        "schemaVersion": "aicheck-ocr-100-corpus-report-v1",
        "ok": not failures,
        "summary": summary,
        "bootstrap": bootstrap,
        "collectionPlan": build_collection_plan(scenario_counts),
        "failures": failures,
        "cases": cases,
    }


SCENARIO_PROFILE_DEFAULTS = {
    "piping_table_profile": ("piping_characteristic_list_v1", "engineering_table_photo"),
    "quality_certificate_profile": ("quality_certificate_v1", "quality_certificate"),
    "ndt_rt_profile": ("ndt_rt_report_v1", "ndt_report"),
    "ndt_ut_profile": ("ndt_ut_report_v1", "ndt_report"),
    "construction_record_profile": ("construction_record_v1", "construction_record"),
    "welding_record_profile": ("welding_record_v1", "welding_record"),
    "qualification_certificate_profile": ("qualification_certificate_v1", "qualification_certificate"),
    "seal_text_profile": ("seal_text_v1", "sealed_document"),
    "fragment_seal_profile": ("fragment_seal_v1", "sealed_document"),
    "evidence_profile": ("evidence_trace_v1", "document_parse_result"),
    "quality_gate_profile": ("quality_gate_v1", "document_parse_result"),
}


def bootstrap_cases_to_targets(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not cases:
        return []
    by_scenario: dict[str, list[dict[str, Any]]] = {}
    for case in cases:
        by_scenario.setdefault(str(case.get("scenario") or "unspecified"), []).append(case)
    used_ids: set[str] = set()
    bootstrapped: list[dict[str, Any]] = []
    for scenario, target in OCR_100_SCENARIO_TARGETS.items():
        templates = by_scenario.get(scenario) or cases
        profile_id, document_type = SCENARIO_PROFILE_DEFAULTS[scenario]
        for index in range(target):
            template = templates[index % len(templates)]
            case = json.loads(json.dumps(template, ensure_ascii=False))
            source_case_id = str(template.get("caseId") or template.get("id") or f"template-{index}")
            case_id = f"ocr100-{scenario}-{index + 1:03d}"
            while case_id in used_ids:
                case_id = f"ocr100-{scenario}-{index + 1:03d}-{len(used_ids)}"
            used_ids.add(case_id)
            case["caseId"] = case_id
            case["scenario"] = scenario
            case["sourceCaseId"] = source_case_id
            case["bootstrapGenerated"] = True
            case["fixtureDerived"] = scenario != str(template.get("scenario") or "")
            if case["fixtureDerived"] or not case.get("profileId"):
                case["profileId"] = profile_id
            if case["fixtureDerived"] or not case.get("documentType"):
                case["documentType"] = document_type
            case["collectionStatus"] = "needs_real_sample_replacement" if case["fixtureDerived"] else case.get("collectionStatus", "template_reused")
            bootstrapped.append(case)
    return bootstrapped


def eval_set_files(inputs: list[str | Path]) -> list[Path]:
    files: list[Path] = []
    for raw in inputs:
        path = Path(raw).expanduser()
        if path.is_dir():
            files.extend(sorted(item for item in path.rglob("*.json") if item.is_file()))
        elif path.is_file():
            files.append(path)
        else:
            files.append(path)
    return files


def corpus_failures(
    cases: list[dict[str, Any]],
    input_failures: list[str],
    *,
    require_real_samples: bool,
    allow_missing_expected_evidence: bool,
) -> list[dict[str, Any]]:
    failures = [{"code": "OCR_100_CORPUS_INPUT_INVALID", "message": message} for message in input_failures]
    thresholds = ocr_100_thresholds()
    min_cases = int(thresholds["minCases"])
    if len(cases) < min_cases:
        failures.append(
            {
                "code": "OCR_100_CORPUS_TOO_SMALL",
                "message": f"Corpus has {len(cases)} cases; {min_cases} are required.",
                "actual": len(cases),
                "expected": min_cases,
            }
        )
    scenario_counts = count_scenarios(cases)
    for scenario in OCR_100_REQUIRED_SCENARIOS:
        if scenario_counts.get(scenario, 0) < 1:
            failures.append(
                {
                    "code": "OCR_100_CORPUS_SCENARIO_MISSING",
                    "message": f"Required OCR 100 scenario is missing: {scenario}",
                    "scenario": scenario,
                }
            )
    for scenario, gap in scenario_target_gaps(scenario_counts).items():
        if gap > 0:
            failures.append(
                {
                    "code": "OCR_100_CORPUS_SCENARIO_TARGET_MISSING",
                    "message": f"OCR 100 scenario {scenario} is short by {gap} cases.",
                    "scenario": scenario,
                    "missing": gap,
                    "target": OCR_100_SCENARIO_TARGETS[scenario],
                    "actual": scenario_counts.get(scenario, 0),
                }
            )
    seen: dict[str, str] = {}
    for index, case in enumerate(cases):
        case_id = str(case.get("caseId") or "").strip()
        source = str(case.get("sourceEvalSet") or "unknown")
        if not case_id:
            failures.append({"code": "OCR_100_CORPUS_CASE_ID_MISSING", "message": f"case[{index}] is missing caseId.", "source": source})
        elif case_id in seen:
            failures.append({"code": "OCR_100_CORPUS_CASE_ID_DUPLICATE", "message": f"Duplicate caseId: {case_id}", "caseId": case_id, "sources": [seen[case_id], source]})
        else:
            seen[case_id] = source
        if not str(case.get("scenario") or "").strip():
            failures.append({"code": "OCR_100_CORPUS_SCENARIO_MISSING_ON_CASE", "message": f"{case_id or index}: scenario is required.", "caseId": case_id, "source": source})
        if not isinstance(case.get("expected"), dict):
            failures.append({"code": "OCR_100_CORPUS_EXPECTED_MISSING", "message": f"{case_id or index}: expected object is required.", "caseId": case_id, "source": source})
        if not any(case.get(key) for key in ["result", "resultPath", "source"]):
            failures.append({"code": "OCR_100_CORPUS_RESULT_MISSING", "message": f"{case_id or index}: result, resultPath, or source is required.", "caseId": case_id, "source": source})
        if require_real_samples:
            if case.get("bootstrapGenerated") is True or case.get("fixtureDerived") is True:
                failures.append(
                    {
                        "code": "OCR_100_CORPUS_SYNTHETIC_CASE",
                        "message": f"{case_id or index}: bootstrap or fixture-derived cases cannot certify OCR 100.",
                        "caseId": case_id,
                        "source": source,
                    }
                )
            if str(case.get("collectionStatus") or "") == "needs_real_sample_replacement":
                failures.append(
                    {
                        "code": "OCR_100_CORPUS_NEEDS_REAL_SAMPLE_REPLACEMENT",
                        "message": f"{case_id or index}: case must be replaced by a real labelled sample.",
                        "caseId": case_id,
                        "source": source,
                    }
                )
        if not allow_missing_expected_evidence:
            failures.extend(expected_evidence_failures(case, case_id=case_id or str(index), source=source))
    return failures


def build_collection_plan(scenario_counts: dict[str, int]) -> dict[str, Any]:
    items = []
    case_templates = []
    for scenario, target in OCR_100_SCENARIO_TARGETS.items():
        actual = int(scenario_counts.get(scenario, 0))
        profile_id, document_type = SCENARIO_PROFILE_DEFAULTS[scenario]
        missing = max(0, target - actual)
        items.append(
            {
                "scenario": scenario,
                "profileId": profile_id,
                "documentType": document_type,
                "targetCases": target,
                "currentCases": actual,
                "missingCases": missing,
                "minimumExpectedAnnotations": expected_annotation_checklist(scenario),
                "collectionHint": SCENARIO_COLLECTION_HINTS.get(scenario, ""),
                "sourceRequirements": [
                    "real customer or field document",
                    "labelled expected fields/tables/seals with bbox or polygon evidence",
                    "non-bootstrapGenerated",
                    "non-fixtureDerived",
                    "collectionStatus must not be needs_real_sample_replacement",
                ],
            }
        )
        for index in range(missing):
            case_templates.append(annotation_case_template(scenario, actual + index + 1))
    return {
        "schemaVersion": "aicheck-ocr-100-collection-plan-v1",
        "totalTargetCases": sum(OCR_100_SCENARIO_TARGETS.values()),
        "totalCurrentCases": sum(int(scenario_counts.get(scenario, 0)) for scenario in OCR_100_SCENARIO_TARGETS),
        "totalMissingCases": sum(max(0, target - int(scenario_counts.get(scenario, 0))) for scenario, target in OCR_100_SCENARIO_TARGETS.items()),
        "items": items,
        "caseTemplates": case_templates,
    }


def collection_todo_csv(collection_plan: dict[str, Any]) -> str:
    rows: list[dict[str, Any]] = []
    items_by_scenario = {
        str(item.get("scenario")): item
        for item in collection_plan.get("items", [])
        if isinstance(item, dict)
    }
    for template in collection_plan.get("caseTemplates", []):
        if not isinstance(template, dict):
            continue
        scenario = str(template.get("scenario") or "")
        item = items_by_scenario.get(scenario, {})
        rows.append(
            {
                "caseId": template.get("caseId"),
                "scenario": scenario,
                "profileId": template.get("profileId"),
                "documentType": template.get("documentType"),
                "targetCases": item.get("targetCases"),
                "currentCases": item.get("currentCases"),
                "missingCases": item.get("missingCases"),
                "minimumExpectedAnnotations": "; ".join(str(value) for value in item.get("minimumExpectedAnnotations") or []),
                "sourceRequirements": "; ".join(str(value) for value in item.get("sourceRequirements") or []),
                "collectionHint": item.get("collectionHint") or SCENARIO_COLLECTION_HINTS.get(scenario, ""),
                "sourcePath": (template.get("source") if isinstance(template.get("source"), dict) else {}).get("path"),
                "collectionStatus": template.get("collectionStatus"),
            }
        )
    handle = StringIO()
    fieldnames = [
        "caseId",
        "scenario",
        "profileId",
        "documentType",
        "targetCases",
        "currentCases",
        "missingCases",
        "minimumExpectedAnnotations",
        "sourceRequirements",
        "collectionHint",
        "sourcePath",
        "collectionStatus",
    ]
    writer = csv.DictWriter(handle, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return handle.getvalue()


def annotation_case_template(scenario: str, sequence: int) -> dict[str, Any]:
    profile_id, document_type = SCENARIO_PROFILE_DEFAULTS[scenario]
    return {
        "caseId": f"real-{scenario}-{sequence:03d}",
        "scenario": scenario,
        "profileId": profile_id,
        "documentType": document_type,
        "collectionStatus": "needs_labeling",
        "source": {
            "path": "replace-with-real-sample-path",
            "documentVersionId": "replace-after-import",
            "notes": "Use a real field/customer document. Do not use generated, fixture, or bootstrap data.",
        },
        "expected": expected_template_for_scenario(scenario),
    }


def expected_template_for_scenario(scenario: str) -> dict[str, Any]:
    base: dict[str, Any] = {
        "qualityStatus": "auto_usable|needs_human_review|failed",
        "minEvidenceCompleteness": 0.95,
    }
    if scenario in {"piping_table_profile", "ndt_rt_profile", "ndt_ut_profile", "construction_record_profile", "welding_record_profile", "quality_certificate_profile"}:
        base["fields"] = [{"fieldCode": "replace-with-core-field", "value": "replace-with-label", "bbox": [0, 0, 0, 0]}]
        base["tables"] = [{"businessSchema": "replace-with-table-schema", "bbox": [0, 0, 0, 0]}]
    elif scenario in {"seal_text_profile", "fragment_seal_profile"}:
        base["seals"] = [{"nameContains": "replace-with-seal-text", "bbox": [0, 0, 0, 0]}]
    elif scenario == "qualification_certificate_profile":
        base["fields"] = [
            {"fieldCode": "certificate_no", "value": "replace-with-label", "bbox": [0, 0, 0, 0]},
            {"fieldCode": "organization_name", "value": "replace-with-label", "bbox": [0, 0, 0, 0]},
            {"fieldCode": "valid_until", "value": "replace-with-label", "bbox": [0, 0, 0, 0]},
        ]
        base["seals"] = [{"nameContains": "replace-with-seal-text", "bbox": [0, 0, 0, 0]}]
    elif scenario == "evidence_profile":
        base["fields"] = [{"fieldCode": "replace-with-evidence-field", "value": "replace-with-label", "bbox": [0, 0, 0, 0]}]
    elif scenario == "quality_gate_profile":
        base["diagnostics"] = [{"code": "replace-with-diagnostic-code", "level": "warning|error"}]
    return base


def expected_annotation_checklist(scenario: str) -> list[str]:
    common = ["documentVersionId or source path", "expected quality status", "page-level evidence coordinates"]
    if scenario in {"piping_table_profile", "ndt_rt_profile", "ndt_ut_profile", "construction_record_profile", "welding_record_profile", "quality_certificate_profile"}:
        return common + ["core fields", "primary table bbox", "normalized rows or business schema"]
    if scenario in {"seal_text_profile", "fragment_seal_profile"}:
        return common + ["seal bbox or polygon", "seal text/name expectation", "seal confidence expectation"]
    if scenario == "qualification_certificate_profile":
        return common + ["certificate number", "organization name", "validity period", "issuing authority", "seal evidence"]
    if scenario == "evidence_profile":
        return common + ["field evidence bbox", "table or fragment evidence link", "sourceEngine expectation"]
    if scenario == "quality_gate_profile":
        return common + ["quality status", "diagnostic code expectation", "human review trigger expectation"]
    return common


def expected_evidence_failures(case: dict[str, Any], *, case_id: str, source: str) -> list[dict[str, Any]]:
    expected = case.get("expected") if isinstance(case.get("expected"), dict) else {}
    failures: list[dict[str, Any]] = []
    for bucket in ["fields", "tables", "seals"]:
        values = expected.get(bucket) if isinstance(expected.get(bucket), list) else []
        for index, item in enumerate(values):
            if not isinstance(item, dict):
                continue
            if has_evidence(item):
                continue
            failures.append(
                {
                    "code": "OCR_100_CORPUS_EXPECTED_EVIDENCE_MISSING",
                    "message": f"{case_id}: expected.{bucket}[{index}] lacks bbox or polygon.",
                    "caseId": case_id,
                    "bucket": bucket,
                    "index": index,
                    "source": source,
                }
            )
    return failures


def has_evidence(item: dict[str, Any]) -> bool:
    return bbox_has_positive_area(item.get("bbox")) or polygon_has_positive_area(item.get("polygon"))


def bbox_has_positive_area(value: Any) -> bool:
    if not isinstance(value, list) or len(value) < 4:
        return False
    try:
        x1, y1, x2, y2 = [float(item) for item in value[:4]]
    except (TypeError, ValueError):
        return False
    return x2 > x1 and y2 > y1


def polygon_has_positive_area(value: Any) -> bool:
    if not isinstance(value, list) or len(value) < 3:
        return False
    points: list[tuple[float, float]] = []
    for point in value:
        if not isinstance(point, list | tuple) or len(point) < 2:
            return False
        try:
            points.append((float(point[0]), float(point[1])))
        except (TypeError, ValueError):
            return False
    area = 0.0
    for index, (x1, y1) in enumerate(points):
        x2, y2 = points[(index + 1) % len(points)]
        area += x1 * y2 - x2 * y1
    return abs(area) > 0.0


def count_scenarios(cases: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for case in cases:
        scenario = str(case.get("scenario") or "unspecified")
        counts[scenario] = counts.get(scenario, 0) + 1
    return dict(sorted(counts.items()))


def scenario_target_gaps(scenario_counts: dict[str, int]) -> dict[str, int]:
    return {
        scenario: max(0, target - int(scenario_counts.get(scenario, 0)))
        for scenario, target in OCR_100_SCENARIO_TARGETS.items()
    }


if __name__ == "__main__":
    raise SystemExit(main())
