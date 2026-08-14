from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.ocr_100_corpus import (
    SCENARIO_COLLECTION_HINTS,
    SCENARIO_PROFILE_DEFAULTS,
    expected_annotation_checklist,
)
from scripts.ocr_eval_set import write_text_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an OCR 100 real-sample intake directory and manifest template from a closure plan.")
    parser.add_argument("closure_plan", help="ocr_100_closure_plan JSON path.")
    parser.add_argument("--output-dir", required=True, help="Directory where intake folders and templates are written.")
    parser.add_argument("--queue-output", default="ocr_eval/reports/new_sample_queue.json", help="Suggested output path for ocr_100_ingest_samples.py.")
    parser.add_argument("--copy-to", default="ocr_eval/real_samples", help="Suggested copy-to path for ingested samples.")
    args = parser.parse_args()

    report = build_collection_intake(
        Path(args.closure_plan),
        output_dir=Path(args.output_dir),
        queue_output=args.queue_output,
        copy_to=args.copy_to,
    )
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 1


def build_collection_intake(
    closure_plan_path: Path,
    *,
    output_dir: Path,
    queue_output: str,
    copy_to: str,
) -> dict[str, Any]:
    closure_plan_path = closure_plan_path.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    closure = json.loads(closure_plan_path.read_text(encoding="utf-8"))
    scenario_plan = closure.get("scenarioPlan") if isinstance(closure.get("scenarioPlan"), dict) else {}
    output_dir.mkdir(parents=True, exist_ok=True)
    samples_dir = output_dir / "samples"
    samples_dir.mkdir(parents=True, exist_ok=True)
    slots: list[dict[str, Any]] = []
    scenario_items: list[dict[str, Any]] = []
    for scenario in sorted(scenario_plan):
        item = scenario_plan.get(scenario)
        if not isinstance(item, dict):
            continue
        missing = safe_int(item.get("collectionMissingCases"))
        if missing <= 0:
            continue
        profile_id, document_type = SCENARIO_PROFILE_DEFAULTS.get(scenario, ("", ""))
        scenario_dir = samples_dir / scenario
        scenario_dir.mkdir(parents=True, exist_ok=True)
        write_text_file(scenario_dir / ".gitkeep", "")
        checklist = expected_annotation_checklist(scenario)
        scenario_items.append(
            {
                "scenario": scenario,
                "profileId": profile_id,
                "documentType": document_type,
                "targetCases": safe_int(item.get("targetCases")),
                "queuedCases": safe_int(item.get("queuedCases")),
                "readyForEval": safe_int(item.get("readyForEval")),
                "collectionMissingCases": missing,
                "dropDirectory": relative_to(output_dir, scenario_dir),
                "collectionHint": item.get("collectionHint") or SCENARIO_COLLECTION_HINTS.get(scenario, ""),
                "minimumExpectedAnnotations": checklist,
            }
        )
        for index in range(1, missing + 1):
            slot_id = f"{scenario}-{index:03d}"
            slots.append(
                {
                    "slotId": slot_id,
                    "scenario": scenario,
                    "profileId": profile_id,
                    "documentType": document_type,
                    "dropDirectory": relative_to(output_dir, scenario_dir),
                    "fileName": f"replace-with-{slot_id}.pdf",
                    "notes": item.get("collectionHint") or SCENARIO_COLLECTION_HINTS.get(scenario, ""),
                    "tags": ["ocr100", scenario],
                    "recommendedAnnotations": checklist,
                }
            )
        write_text_file(scenario_dir / "README.md", scenario_readme(scenario_items[-1], output_dir=output_dir, queue_output=queue_output, copy_to=copy_to))
    manifest = {
        "schemaVersion": "aicheck-ocr-100-intake-manifest-template-v1",
        "generatedAt": datetime.now(UTC).isoformat(),
        "sourceClosurePlan": str(closure_plan_path),
        "instructions": [
            "Put real customer/field documents into each slot's dropDirectory.",
            "Run autofillManifest or replace fileName placeholders with the actual file names before running ingest.",
            "Do not use standards/specification PDFs as OCR 100 certification samples unless they are the target business document.",
            "After ingest, build annotation previews, prelabel, then human-review labels before OCR 100 certification.",
        ],
        "samples": slots,
    }
    commands = {
        "scanDroppedCandidates": (
            "python scripts/ocr_100_collection_candidates.py "
            f"{relative_to(Path.cwd(), samples_dir)} "
            "--existing-queue ocr_eval/reports/scan_sample_queue.json "
            f"--existing-queue {queue_output} "
            f"--intake-dir {relative_to(Path.cwd(), output_dir)} "
            f"--output {relative_to(Path.cwd(), output_dir / 'collection_candidates.json')} "
            f"--markdown-output {relative_to(Path.cwd(), output_dir / 'collection_candidates.md')}"
        ),
        "actionBoard": (
            "python scripts/ocr_100_action_board.py "
            f"--closure-plan {relative_to(Path.cwd(), closure_plan_path)} "
            "--annotation-tasks ocr_eval/reports/scan_annotation_pack/prelabelled_tasks_retry_merged_after_batch6_dedupe.json "
            f"--candidates {relative_to(Path.cwd(), output_dir / 'collection_candidates.json')} "
            "--output ocr_eval/reports/ocr_100_action_board.json "
            "--markdown-output ocr_eval/reports/ocr_100_action_board.md "
            "--csv-output ocr_eval/reports/ocr_100_action_board.csv "
            "--handoff-output-dir ocr_eval/reports/ocr_100_action_handoff"
        ),
        "autofillManifest": (
            "python scripts/ocr_100_collection_intake_autofill.py "
            f"{relative_to(Path.cwd(), output_dir)} "
            "--output-manifest manifest_autofilled.json "
            f"--output {relative_to(Path.cwd(), output_dir / 'autofill.json')} "
            f"--markdown-output {relative_to(Path.cwd(), output_dir / 'autofill.md')}"
        ),
        "verifyAutofilledManifest": (
            "python scripts/ocr_100_collection_intake_verify.py "
            f"{relative_to(Path.cwd(), output_dir)} "
            "--manifest manifest_autofilled.json --strict "
            f"--output {relative_to(Path.cwd(), output_dir / 'verify_autofilled.json')} "
            f"--markdown-output {relative_to(Path.cwd(), output_dir / 'verify_autofilled.md')}"
        ),
        "pipelineDryRun": (
            "python scripts/ocr_100_collection_intake_pipeline.py "
            f"{relative_to(Path.cwd(), output_dir)} "
            "--output "
            f"{relative_to(Path.cwd(), output_dir / 'pipeline.json')} "
            "--markdown-output "
            f"{relative_to(Path.cwd(), output_dir / 'pipeline.md')}"
        ),
        "pipelineExecute": (
            "python scripts/ocr_100_collection_intake_pipeline.py "
            f"{relative_to(Path.cwd(), output_dir)} "
            "--execute --render-previews "
            f"--queue-output {queue_output} "
            "--annotation-output-dir ocr_eval/reports/new_annotation_pack "
            "--ocr-result-dir ocr_eval/reports/new_ocr_results "
            f"--copy-to {copy_to} "
            "--output "
            f"{relative_to(Path.cwd(), output_dir / 'pipeline_execute.json')} "
            "--markdown-output "
            f"{relative_to(Path.cwd(), output_dir / 'pipeline_execute.md')}"
        ),
        "ingestAll": (
            "python scripts/ocr_100_ingest_samples.py "
            f"{relative_to(Path.cwd(), samples_dir)} "
            f"--manifest {relative_to(Path.cwd(), output_dir / 'manifest_autofilled.json')} "
            f"--base-dir . --copy-to {copy_to} --output {queue_output}"
        ),
        "buildAnnotationPack": (
            "python scripts/ocr_100_annotation_pack.py "
            f"{queue_output} --output-dir ocr_eval/reports/new_annotation_pack --render-previews"
        ),
        "prelabel": (
            "python scripts/ocr_100_annotation_prelabel.py "
            "ocr_eval/reports/new_annotation_pack/annotation_tasks.json "
            "--output ocr_eval/reports/new_annotation_pack/prelabelled_tasks.json "
            "--source-base-dir . --run-ocr --auto-discover-runtime --save-result-dir ocr_eval/reports/new_ocr_results"
        ),
        "reviewedLabelGate": (
            "python scripts/ocr_100_reviewed_label_gate.py "
            "ocr_eval/reports/new_annotation_pack/prelabelled_tasks.json "
            "--label-studio-export <label-studio-export.json> "
            "--output-dir ocr_eval/reports/reviewed_label_gate "
            "--sample-summary ocr_eval/reports/img6509_sample_probe_summary.json "
            "--strict"
        ),
    }
    summary = {
        "schemaVersion": "aicheck-ocr-100-collection-intake-v1",
        "generatedAt": datetime.now(UTC).isoformat(),
        "sourceClosurePlan": str(closure_plan_path),
        "outputDir": str(output_dir),
        "scenarios": len(scenario_items),
        "slots": len(slots),
        "scenarioItems": scenario_items,
        "manifest": str(output_dir / "manifest_template.json"),
        "commands": commands,
    }
    write_text_file(output_dir / "manifest_template.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    write_text_file(output_dir / "README.md", intake_readme(summary))
    write_text_file(output_dir / "commands.json", json.dumps(commands, ensure_ascii=False, indent=2))
    write_text_file(output_dir / "summary.json", json.dumps(summary, ensure_ascii=False, indent=2))
    return {"ok": True, "summary": summary, "manifest": manifest, "commands": commands}


def intake_readme(summary: dict[str, Any]) -> str:
    lines = [
        "# OCR 100 Sample Intake",
        "",
        f"- Source closure plan: {summary.get('sourceClosurePlan')}",
        f"- Missing sample slots: {summary.get('slots')}",
        f"- Scenario folders: {summary.get('scenarios')}",
        "",
        "## Workflow",
        "",
        "1. Put real PDF/image samples into the matching `samples/<scenario>/` folder.",
        "2. Run `autofillManifest` from `commands.json`, or edit `manifest_template.json` manually and replace each `fileName` placeholder.",
        "3. Run `verifyAutofilledManifest` from `commands.json` until it passes.",
        "4. Run `pipelineDryRun` to inspect the exact ingest/annotation steps.",
        "5. Run `pipelineExecute` to ingest and build the annotation pack.",
        "6. Build previews, prelabel, then send the annotation pack to human review.",
        "7. After Label Studio export, run `reviewedLabelGate` to import reviewed labels, export the release eval set, and gate scorecard readiness.",
        "",
        "## Scenario Gaps",
        "",
        "| Scenario | Missing | Folder | Required Annotation Checklist |",
        "| --- | ---: | --- | --- |",
    ]
    for item in summary.get("scenarioItems") or []:
        lines.append(
            f"| {item.get('scenario')} | {item.get('collectionMissingCases')} | {item.get('dropDirectory')} | "
            f"{'; '.join(str(value) for value in item.get('minimumExpectedAnnotations') or [])} |"
        )
    lines.extend(["", "## Commands", ""])
    for name, command in (summary.get("commands") or {}).items():
        lines.extend([f"### {name}", "", f"```bash\n{command}\n```", ""])
    return "\n".join(lines)


def scenario_readme(item: dict[str, Any], *, output_dir: Path, queue_output: str, copy_to: str) -> str:
    scenario = str(item.get("scenario") or "")
    command = (
        "python scripts/ocr_100_ingest_samples.py "
        f"{relative_to(Path.cwd(), output_dir / item.get('dropDirectory', ''))} "
        f"--manifest {relative_to(Path.cwd(), output_dir / 'manifest_template.json')} "
        f"--base-dir . --copy-to {copy_to} --output {queue_output} --scenario {scenario}"
    )
    return "\n".join(
        [
            f"# {scenario}",
            "",
            f"- Missing samples: {item.get('collectionMissingCases')}",
            f"- Profile: {item.get('profileId')}",
            f"- Document type: {item.get('documentType')}",
            f"- Hint: {item.get('collectionHint')}",
            "",
            "## Minimum Expected Annotations",
            "",
            *[f"- {value}" for value in item.get("minimumExpectedAnnotations") or []],
            "",
            "## Scenario-only Ingest Command",
            "",
            f"```bash\n{command}\n```",
            "",
        ]
    )


def relative_to(base: Path, path: Path | str) -> str:
    path = Path(path)
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except Exception:
        return str(path)


def safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
