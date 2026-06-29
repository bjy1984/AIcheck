from __future__ import annotations

import json

import pytest

from scripts.ocr_100_annotation_pack import build_annotation_pack, existing_pdf_previews


def test_ocr_100_annotation_pack_writes_tasks_without_rendering(tmp_path) -> None:
    source = tmp_path / "Scan" / "IMG_6509.heic"
    source.parent.mkdir()
    source.write_bytes(b"heic")
    queue = tmp_path / "queue.json"
    queue.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "caseId": "real-piping_table_profile-001",
                        "scenario": "piping_table_profile",
                        "profileId": "piping_characteristic_list_v1",
                        "documentType": "engineering_table_photo",
                        "collectionStatus": "needs_labeling",
                        "source": {"path": "Scan/IMG_6509.heic", "fileName": "IMG_6509.heic", "notes": "piping list"},
                        "expected": {
                            "fields": [{"fieldCode": "replace-with-core-field", "value": "replace-with-label", "bbox": [0, 0, 0, 0]}],
                            "tables": [{"businessSchema": "replace-with-table-schema", "bbox": [0, 0, 0, 0]}],
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    pack = build_annotation_pack(queue, output_dir=tmp_path / "pack", source_base_dir=tmp_path)
    task = pack["tasks"][0]

    assert pack["summary"]["tasks"] == 1
    assert task["sourcePathResolved"] == str(source.resolve())
    assert task["previewStatus"] == "not_requested"
    assert task["certificationBlockers"] == ["placeholder_labels", "zero_area_bbox"]
    assert "core fields" in task["checklist"]
    assert (tmp_path / "pack" / "annotation_tasks.json").exists()
    assert "real-piping_table_profile-001" in (tmp_path / "pack" / "README.md").read_text(encoding="utf-8")


def test_ocr_100_annotation_pack_copies_image_preview(tmp_path) -> None:
    source = tmp_path / "sample.png"
    source.write_bytes(b"png")
    queue = tmp_path / "queue.json"
    queue.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "caseId": "real-seal_text_profile-001",
                        "scenario": "seal_text_profile",
                        "profileId": "seal_text_v1",
                        "documentType": "sealed_document",
                        "collectionStatus": "needs_labeling",
                        "source": {"path": "sample.png", "fileName": "sample.png"},
                        "expected": {"seals": [{"nameContains": "replace-with-seal-text", "bbox": [0, 0, 0, 0]}]},
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    pack = build_annotation_pack(queue, output_dir=tmp_path / "pack", source_base_dir=tmp_path, render_previews=True)
    task = pack["tasks"][0]

    assert task["previewStatus"] == "rendered"
    assert task["previewPaths"] == ["previews/real-seal_text_profile-001_image.png"]
    assert (tmp_path / "pack" / task["previewPaths"][0]).read_bytes() == b"png"


def test_existing_pdf_previews_reuses_matching_pages(tmp_path) -> None:
    preview_dir = tmp_path / "previews"
    preview_dir.mkdir()
    (preview_dir / "real-case_p1.png").write_bytes(b"p1")
    (preview_dir / "real-case_p2.png").write_bytes(b"p2")

    previews = existing_pdf_previews(preview_dir=preview_dir, case_id="real-case", max_pages=2)

    assert previews == [preview_dir / "real-case_p1.png", preview_dir / "real-case_p2.png"]


def test_ocr_100_annotation_pack_can_split_page_level_tasks(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"%PDF")
    queue = tmp_path / "queue.json"
    queue.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "caseId": "real-multipage-001",
                        "scenario": "piping_table_profile",
                        "profileId": "piping_characteristic_list_v1",
                        "documentType": "engineering_table_pdf",
                        "collectionStatus": "needs_labeling",
                        "source": {"path": "sample.pdf", "fileName": "sample.pdf", "pageCount": 2},
                        "expected": {
                            "fields": [{"fieldCode": "pipe_no", "value": "replace-with-label", "bbox": [0, 0, 0, 0]}],
                            "tables": [{"businessSchema": "replace-with-table-schema", "bbox": [0, 0, 0, 0]}],
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fake_render(*_args, preview_dir, case_id, **_kwargs):
        first = preview_dir / f"{case_id}_p1.png"
        second = preview_dir / f"{case_id}_p2.png"
        return [first, second], [{"status": "rendered"}, {"status": "rendered"}]

    monkeypatch.setattr("scripts.ocr_100_annotation_pack.render_case_previews", fake_render)

    pack = build_annotation_pack(
        queue,
        output_dir=tmp_path / "pack",
        source_base_dir=tmp_path,
        render_previews=True,
        page_level_tasks=True,
    )

    assert pack["summary"]["tasks"] == 2
    assert pack["summary"]["pageLevelTasks"] is True
    assert [task["pageNo"] for task in pack["tasks"]] == [1, 2]
    assert [task["parentTaskId"] for task in pack["tasks"]] == ["label-real-multipage-001", "label-real-multipage-001"]
    assert pack["tasks"][0]["previewPaths"] == ["previews/real-multipage-001_p1.png"]
