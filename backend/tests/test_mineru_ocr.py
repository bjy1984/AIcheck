from __future__ import annotations

import io
import json
import stat
import zipfile

import pytest

from libs import mineru_ocr
from libs.mineru_ocr import MinerUNormalizationError, normalize_mineru_zip


def _zip_bytes(
    *,
    content: list[dict[str, object]] | None = None,
    middle: dict[str, object] | None = None,
    markdown: str | None = "# 压力管道安装记录",
    extra_members: dict[str, bytes] | None = None,
) -> bytes:
    content = content if content is not None else [
        {
            "type": "text",
            "text": "压力管道安装记录",
            "text_level": 1,
            "bbox": [100, 200, 900, 260],
            "page_idx": 0,
        },
        {
            "type": "table",
            "table_body": (
                "<table><tr><th>管线号</th><th>规格</th></tr>"
                "<tr><td>PL001</td><td>DN100</td></tr></table>"
            ),
            "bbox": [100, 300, 900, 700],
            "page_idx": 0,
        },
        {
            "type": "image",
            "sub_type": "seal",
            "img_path": "images/seal.png",
            "bbox": [700, 750, 900, 950],
            "page_idx": 0,
        },
    ]
    middle = middle if middle is not None else {
        "pdf_info": [{"page_idx": 0, "page_size": [1200, 1800]}],
        "_backend": "vlm",
        "_version_name": "3.0",
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        if markdown is not None:
            archive.writestr("nested/full.md", markdown)
        archive.writestr(
            "nested/document_content_list.json",
            json.dumps(content, ensure_ascii=False),
        )
        archive.writestr(
            "nested/document_middle.json",
            json.dumps(middle, ensure_ascii=False),
        )
        archive.writestr("nested/images/seal.png", b"png")
        for name, data in (extra_members or {}).items():
            archive.writestr(name, data)
    return output.getvalue()


def _normalize(data: bytes):
    return normalize_mineru_zip(
        data,
        storage_key="minio://documents/doc.pdf",
        file_name="doc.pdf",
        profile_id="generic_document_v1",
        document_type="generic_document",
        provider_task_id="TASK-1",
    )


def test_normalizes_mineru_vlm_into_local_ocr_contract() -> None:
    bundle = _normalize(_zip_bytes())

    result = bundle.result
    assert result["status"] == "success"
    assert result["parserVersion"] == "mineru-vlm-adapter@1"
    assert result["pages"][0] == {
        "pageNo": 1,
        "width": 1200.0,
        "height": 1800.0,
        "coordinateSystem": "rendered_pixels",
        "sourceCoordinateSystem": "mineru_normalized_1000",
    }
    assert result["fragments"][0]["bbox"] == [
        120.0,
        360.0,
        1080.0,
        468.0,
    ]
    assert result["fragments"][0]["coordinateSystem"] == "rendered_pixels"
    assert (
        result["fragments"][0]["sourceCoordinateSystem"]
        == "mineru_normalized_1000"
    )
    assert result["tables"][0]["rows"] == 2
    assert result["tables"][0]["columns"] == 2
    assert result["tables"][0]["normalizedRows"][0]["管线号"] == "PL001"
    assert result["seals"][0]["candidateOnly"] is True
    assert result["seals"][0]["canSatisfyRequiredSeal"] is False
    assert "provider_confidence_unavailable" in result["quality"]["reasons"]
    assert bundle.artifacts["markdown"].data.startswith(b"#")
    assert set(bundle.artifacts) == {
        "original_zip",
        "markdown",
        "content_list",
        "middle_json",
        "normalized_json",
    }


def test_maps_supported_content_types_in_stable_reading_order() -> None:
    content = [
        {
            "type": kind,
            "text": text,
            "bbox": [10, index * 50, 900, index * 50 + 40],
            "page_idx": 0,
        }
        for index, (kind, text) in enumerate(
            [
                ("title", "标题"),
                ("text", "正文"),
                ("equation", "E=mc^2"),
                ("code", "print('ok')"),
                ("list", "第一项"),
                ("image_caption", "图一"),
                ("header", "页眉"),
                ("page_footnote", "脚注"),
            ],
            start=1,
        )
    ]

    first = _normalize(_zip_bytes(content=content)).result
    second = _normalize(_zip_bytes(content=content)).result

    assert [item["text"] for item in first["fragments"]] == [
        "标题",
        "正文",
        "E=mc^2",
        "print('ok')",
        "第一项",
        "图一",
        "页眉",
        "脚注",
    ]
    assert [item["readingOrder"] for item in first["fragments"]] == list(
        range(1, 9)
    )
    assert [item["candidateId"] for item in first["fragments"]] == [
        item["candidateId"] for item in second["fragments"]
    ]
    assert {item["blockType"] for item in first["layoutBlocks"]} >= {
        "title",
        "text",
        "equation",
        "code",
        "list",
        "caption",
        "header",
        "footnote",
    }


def test_multiple_pages_use_one_based_page_numbers() -> None:
    result = _normalize(
        _zip_bytes(
            content=[
                {
                    "type": "text",
                    "text": "第一页",
                    "bbox": [0, 0, 1000, 100],
                    "page_idx": 0,
                },
                {
                    "type": "text",
                    "text": "第二页",
                    "bbox": [0, 0, 1000, 100],
                    "page_idx": 1,
                },
            ],
            middle={
                "pdf_info": [
                    {"page_idx": 0, "page_size": [1000, 2000]},
                    {"page_idx": 1, "page_size": [800, 1200]},
                ]
            },
        )
    ).result

    assert [page["pageNo"] for page in result["pages"]] == [1, 2]
    assert [item["pageNo"] for item in result["fragments"]] == [1, 2]
    assert result["fragments"][1]["bbox"] == [0.0, 0.0, 800.0, 120.0]


def test_unmappable_bbox_is_flagged_without_fabricated_pixels() -> None:
    result = _normalize(
        _zip_bytes(
            content=[
                {
                    "type": "text",
                    "text": "未知页面",
                    "bbox": [100, 200, 300, 400],
                    "page_idx": 2,
                }
            ]
        )
    ).result

    fragment = result["fragments"][0]
    assert fragment["bbox"] is None
    assert fragment["coordinateSystem"] is None
    assert "coordinate_transform_unmapped" in result["quality"]["reasons"]
    assert any(
        item["code"] == "coordinate_transform_unmapped"
        for item in result["diagnostics"]
    )


def test_empty_table_is_preserved_as_candidate_with_diagnostic() -> None:
    result = _normalize(
        _zip_bytes(
            content=[
                {
                    "type": "table",
                    "table_body": "<table><tr></tr></table>",
                    "bbox": [0, 0, 1000, 1000],
                    "page_idx": 0,
                }
            ]
        )
    ).result

    assert len(result["tables"]) == 1
    assert result["tables"][0]["candidateOnly"] is True
    assert result["tables"][0]["rows"] == 0
    assert any(
        item["code"] == "table_structure_unavailable"
        for item in result["diagnostics"]
    )


def test_missing_markdown_is_non_blocking_diagnostic() -> None:
    bundle = _normalize(_zip_bytes(markdown=None))

    assert bundle.result["status"] == "success"
    assert "markdown" not in bundle.artifacts
    assert any(
        item["code"] == "mineru_markdown_missing"
        for item in bundle.result["diagnostics"]
    )


def test_missing_content_list_is_rejected() -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(
            "document_middle.json",
            json.dumps({"pdf_info": []}),
        )

    with pytest.raises(MinerUNormalizationError) as raised:
        _normalize(output.getvalue())

    assert raised.value.code == "MINERU_CONTENT_LIST_MISSING"


@pytest.mark.parametrize("member_name", ["../escape.json", "/absolute.json"])
def test_zip_paths_cannot_escape_archive_root(member_name: str) -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(member_name, b"{}")

    with pytest.raises(MinerUNormalizationError) as raised:
        _normalize(output.getvalue())

    assert raised.value.code == "MINERU_ZIP_UNSAFE_PATH"


def test_zip_symlinks_are_rejected() -> None:
    output = io.BytesIO()
    info = zipfile.ZipInfo("linked.json")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(info, "../secret")

    with pytest.raises(MinerUNormalizationError) as raised:
        _normalize(output.getvalue())

    assert raised.value.code == "MINERU_ZIP_SYMLINK"


def test_zip_member_count_and_expansion_limits_are_enforced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mineru_ocr, "MAX_ZIP_MEMBERS", 2)
    with pytest.raises(MinerUNormalizationError) as too_many:
        _normalize(_zip_bytes())
    assert too_many.value.code == "MINERU_ZIP_TOO_MANY_MEMBERS"

    monkeypatch.setattr(mineru_ocr, "MAX_ZIP_MEMBERS", 100)
    monkeypatch.setattr(mineru_ocr, "MAX_ZIP_MEMBER_BYTES", 2)
    with pytest.raises(MinerUNormalizationError) as too_large:
        _normalize(_zip_bytes())
    assert too_large.value.code == "MINERU_ZIP_MEMBER_TOO_LARGE"

    monkeypatch.setattr(mineru_ocr, "MAX_ZIP_MEMBER_BYTES", 10_000)
    monkeypatch.setattr(mineru_ocr, "MAX_ZIP_TOTAL_BYTES", 10)
    with pytest.raises(MinerUNormalizationError) as expanded:
        _normalize(_zip_bytes())
    assert expanded.value.code == "MINERU_ZIP_EXPANSION_TOO_LARGE"

