from __future__ import annotations

import argparse
import json
import struct
import sys
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.ocr_100_annotation_export import resolve_tasks_path
from scripts.ocr_eval_set import write_text_file

LABEL_STUDIO_LABELS = {
    "fields": ("Field", "#2563eb"),
    "tables": ("Table", "#16a34a"),
    "seals": ("Seal", "#dc2626"),
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Export OCR 100 annotation tasks to Label Studio import files.")
    parser.add_argument("annotation_tasks", help="annotation_tasks.json, prelabelled tasks JSON, or annotation pack directory.")
    parser.add_argument("--output-dir", required=True, help="Directory for label_config.xml, label_studio_tasks.json, and summary JSON.")
    parser.add_argument(
        "--local-files-root",
        help="Label Studio local files document root. Defaults to the annotation pack directory.",
    )
    parser.add_argument(
        "--preview-base-dir",
        help="Base directory for relative previewPaths. Defaults to the annotation tasks directory.",
    )
    parser.add_argument(
        "--image-url-prefix",
        default="/data/local-files/?d=",
        help="Prefix used for image URLs in Label Studio tasks.",
    )
    parser.add_argument("--include-without-image", action="store_true", help="Include tasks without preview image references.")
    parser.add_argument("--allow-skipped", action="store_true", help="Allow the export to succeed when some tasks are skipped. Use only for partial draft annotation batches.")
    args = parser.parse_args()

    report = export_label_studio_pack(
        Path(args.annotation_tasks),
        output_dir=Path(args.output_dir),
        local_files_root=Path(args.local_files_root) if args.local_files_root else None,
        preview_base_dir=Path(args.preview_base_dir) if args.preview_base_dir else None,
        image_url_prefix=args.image_url_prefix,
        include_without_image=bool(args.include_without_image),
        allow_skipped=bool(args.allow_skipped),
    )
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def export_label_studio_pack(
    annotation_tasks: Path,
    *,
    output_dir: Path,
    local_files_root: Path | None = None,
    preview_base_dir: Path | None = None,
    image_url_prefix: str = "/data/local-files/?d=",
    include_without_image: bool = False,
    allow_skipped: bool = False,
) -> dict[str, Any]:
    tasks_path = resolve_tasks_path(annotation_tasks)
    payload = json.loads(tasks_path.read_text(encoding="utf-8"))
    tasks = payload.get("tasks") if isinstance(payload, dict) else payload
    if not isinstance(tasks, list):
        raise ValueError("annotation tasks must be a JSON object with tasks[] or a raw task list.")
    pack_dir = tasks_path.parent
    preview_base_dir = (preview_base_dir or pack_dir).expanduser().resolve()
    local_files_root = (local_files_root or preview_base_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    label_studio_tasks: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        converted, skip_reason = label_studio_task(
            task,
            preview_base_dir=preview_base_dir,
            local_files_root=local_files_root,
            image_url_prefix=image_url_prefix,
        )
        if converted is None:
            skipped.append({"caseId": task.get("caseId"), "reason": skip_reason})
            if not include_without_image:
                continue
            converted = label_studio_task_without_image(task, reason=skip_reason)
        label_studio_tasks.append(converted)

    write_text_file(output_dir / "label_config.xml", label_config_xml())
    write_text_file(output_dir / "label_studio_tasks.json", json.dumps(label_studio_tasks, ensure_ascii=False, indent=2))
    summary = {
        "schemaVersion": "aicheck-ocr-100-label-studio-export-v1",
        "generatedAt": datetime.now(UTC).isoformat(),
        "source": str(tasks_path),
        "tasks": len(label_studio_tasks),
        "sourceTasks": len(tasks),
        "skipped": len(skipped),
        "predictionTasks": len([task for task in label_studio_tasks if task.get("predictions")]),
        "localFilesRoot": str(local_files_root),
        "previewBaseDir": str(preview_base_dir),
        "imageUrlPrefix": image_url_prefix,
        "includeWithoutImage": bool(include_without_image),
        "allowSkipped": bool(allow_skipped),
        "skippedItems": skipped[:50],
    }
    write_text_file(output_dir / "label_studio_summary.json", json.dumps(summary, ensure_ascii=False, indent=2))
    ok = bool(label_studio_tasks) and (allow_skipped or include_without_image or not skipped)
    return {"ok": ok, "summary": summary, "tasks": label_studio_tasks}


def label_studio_task(
    task: dict[str, Any],
    *,
    preview_base_dir: Path,
    local_files_root: Path,
    image_url_prefix: str,
) -> tuple[dict[str, Any] | None, str | None]:
    image_path = first_preview_path(task, preview_base_dir=preview_base_dir)
    if image_path is None:
        return None, "missing_preview"
    if not image_path.exists():
        return None, "preview_missing"
    image_size = read_image_size(image_path)
    if image_size is None:
        return None, "image_size_unavailable"
    image_url = image_url_for(image_path, local_files_root=local_files_root, image_url_prefix=image_url_prefix)
    page_no = int(task.get("pageNo") or 1)
    task_payload = {
        "data": {
            "image": image_url,
            "case_id": task.get("caseId"),
            "page_no": page_no,
            "scenario": task.get("scenario"),
            "profile_id": task.get("profileId"),
            "document_type": task.get("documentType"),
            "source_path": task.get("sourcePath"),
            "notes": task.get("notes") or "",
            "checklist": "; ".join(str(item) for item in task.get("checklist") or []),
            "expected_template": json.dumps(task.get("expectedTemplate") or {}, ensure_ascii=False),
            "suggested_expected": json.dumps(task.get("suggestedExpected") or {}, ensure_ascii=False),
            "labeling_instructions": "\n".join(str(item) for item in task.get("labelingInstructions") or []),
        },
        "meta": {
            "taskId": task.get("taskId"),
            "parentTaskId": task.get("parentTaskId"),
            "collectionStatus": task.get("collectionStatus"),
            "prelabelStatus": task.get("prelabelStatus"),
            "pageNo": page_no,
            "imageWidth": image_size[0],
            "imageHeight": image_size[1],
        },
    }
    predictions = prediction_results(
        task.get("suggestedExpected") if isinstance(task.get("suggestedExpected"), dict) else {},
        image_size=image_size,
        page_no=page_no if task.get("pageNo") else None,
    )
    if predictions:
        task_payload["predictions"] = [
            {
                "model_version": "aicheck-machine-prelabel",
                "score": prediction_score(task),
                "result": predictions,
            }
        ]
    return task_payload, None


def label_studio_task_without_image(task: dict[str, Any], *, reason: str | None) -> dict[str, Any]:
    return {
        "data": {
            "image": "",
            "case_id": task.get("caseId"),
            "scenario": task.get("scenario"),
            "source_path": task.get("sourcePath"),
            "notes": f"{task.get('notes') or ''}\nNo preview image: {reason or 'unknown'}".strip(),
            "expected_template": json.dumps(task.get("expectedTemplate") or {}, ensure_ascii=False),
            "suggested_expected": json.dumps(task.get("suggestedExpected") or {}, ensure_ascii=False),
        },
        "meta": {"taskId": task.get("taskId"), "skipReason": reason},
    }


def first_preview_path(task: dict[str, Any], *, preview_base_dir: Path) -> Path | None:
    previews = [item for item in task.get("previewPaths") or [] if isinstance(item, str) and item.strip()]
    if not previews:
        return None
    path = Path(previews[0]).expanduser()
    return path if path.is_absolute() else (preview_base_dir / path).resolve()


def image_url_for(path: Path, *, local_files_root: Path, image_url_prefix: str) -> str:
    try:
        relative = path.resolve().relative_to(local_files_root)
        return image_url_prefix + str(relative).replace("\\", "/")
    except ValueError:
        return image_url_prefix + str(path.resolve()).replace("\\", "/")


def prediction_results(expected: dict[str, Any], *, image_size: tuple[int, int], page_no: int | None = None) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for bucket in ["fields", "tables", "seals"]:
        label, _color = LABEL_STUDIO_LABELS[bucket]
        for index, item in enumerate(expected.get(bucket) or []):
            if not isinstance(item, dict):
                continue
            if page_no is not None and item.get("pageNo") is not None and int(item.get("pageNo") or 0) != page_no:
                continue
            bbox = item.get("bbox")
            if not bbox_valid(bbox):
                continue
            results.append(
                {
                    "id": f"{bucket}-{index}",
                    "from_name": "bbox",
                    "to_name": "image",
                    "type": "rectanglelabels",
                    "value": bbox_to_percent(bbox, image_size=image_size, label=label),
                    "meta": {
                        "bucket": bucket,
                        "fieldCode": item.get("fieldCode"),
                        "value": item.get("value"),
                        "businessSchema": item.get("businessSchema"),
                        "nameContains": item.get("nameContains"),
                        "sealType": item.get("sealType"),
                        "sourceEngine": item.get("sourceEngine"),
                        "reviewStatus": item.get("reviewStatus"),
                        "pageNo": item.get("pageNo") or page_no,
                    },
                }
            )
    return results


def bbox_valid(value: Any) -> bool:
    if not isinstance(value, list) or len(value) < 4:
        return False
    try:
        x1, y1, x2, y2 = [float(item) for item in value[:4]]
    except (TypeError, ValueError):
        return False
    return x2 > x1 and y2 > y1


def bbox_to_percent(value: list[Any], *, image_size: tuple[int, int], label: str) -> dict[str, Any]:
    width, height = image_size
    x1, y1, x2, y2 = [float(item) for item in value[:4]]
    return {
        "x": clamp_percent(x1 / width * 100),
        "y": clamp_percent(y1 / height * 100),
        "width": clamp_percent((x2 - x1) / width * 100),
        "height": clamp_percent((y2 - y1) / height * 100),
        "rotation": 0,
        "rectanglelabels": [label],
    }


def clamp_percent(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 4)


def prediction_score(task: dict[str, Any]) -> float:
    summary = task.get("prelabelSummary") if isinstance(task.get("prelabelSummary"), dict) else {}
    blockers = summary.get("blockers") if isinstance(summary.get("blockers"), list) else []
    if blockers:
        return 0.55
    return 0.75 if task.get("prelabelStatus") == "suggested" else 0.5


def read_image_size(path: Path) -> tuple[int, int] | None:
    try:
        with path.open("rb") as handle:
            header = handle.read(32)
            if header.startswith(b"\x89PNG\r\n\x1a\n") and len(header) >= 24:
                width, height = struct.unpack(">II", header[16:24])
                return int(width), int(height)
            if header.startswith(b"\xff\xd8"):
                return read_jpeg_size(path)
    except Exception:
        return None
    return None


def read_jpeg_size(path: Path) -> tuple[int, int] | None:
    try:
        data = path.read_bytes()
    except Exception:
        return None
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        index += 2
        if marker in {0xD8, 0xD9}:
            continue
        if index + 2 > len(data):
            break
        segment_length = int.from_bytes(data[index:index + 2], "big")
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            if index + 7 <= len(data):
                height = int.from_bytes(data[index + 3:index + 5], "big")
                width = int.from_bytes(data[index + 5:index + 7], "big")
                return width, height
            return None
        index += max(segment_length, 2)
    return None


def label_config_xml() -> str:
    labels = "\n".join(
        f'    <Label value="{escape(label)}" background="{color}"/>'
        for label, color in LABEL_STUDIO_LABELS.values()
    )
    return f"""<View>
  <Style>
    .aicheck-meta {{ font-size: 13px; line-height: 1.45; color: #334155; }}
  </Style>
  <Header value="$case_id"/>
  <View className="aicheck-meta">
    <Text name="page" value="Page: $page_no"/>
    <Text name="scenario" value="Scenario: $scenario"/>
    <Text name="profile" value="Profile: $profile_id"/>
    <Text name="notes" value="$notes"/>
    <Text name="checklist" value="$checklist"/>
  </View>
  <Image name="image" value="$image" zoom="true" rotateControl="true"/>
  <RectangleLabels name="bbox" toName="image">
{labels}
  </RectangleLabels>
  <Choices name="quality_status" toName="image" choice="single-radio">
    <Choice value="auto_usable"/>
    <Choice value="needs_human_review"/>
    <Choice value="failed"/>
  </Choices>
  <TextArea name="label_json" toName="image" rows="8" editable="true" value="$suggested_expected"/>
  <TextArea name="instructions" toName="image" rows="5" editable="false" value="$labeling_instructions"/>
</View>
"""


if __name__ == "__main__":
    raise SystemExit(main())
