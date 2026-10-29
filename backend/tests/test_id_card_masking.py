"""入库前身份证号脱敏。

2026-10-29 生产审计：项目资料向量的 metadata 里有 41 行未脱敏身份证号，检索测试接口
原样返回。脱敏规则：18 位且校验位正确才改，保留前 4 位和后 4 位，中间 10 个 *。
"""

from __future__ import annotations

import copy

from apps.worker import tasks
from libs.db.repository import repo
from libs.knowledge_indexing import build_chunks_for_file, mask_id_card_numbers

# GB 11643 里的示例号码，校验位正确，不是真实个人
SAMPLE_ID = "11010519491231002X"
MASKED_ID = "1101**********002X"


def test_masks_only_valid_18_digit_numbers() -> None:
    assert mask_id_card_numbers(f"证书编号：{SAMPLE_ID}，有效期至 2027-01-01") == f"证书编号：{MASKED_ID}，有效期至 2027-01-01"
    assert mask_id_card_numbers(SAMPLE_ID.lower()) == "1101**********002x"
    # 校验位不对、位数不对、嵌在更长的数字里，都不动——标准里的长编号不能被误伤
    wrong_check = SAMPLE_ID[:-1] + "3"
    assert mask_id_card_numbers(wrong_check) == wrong_check
    assert mask_id_card_numbers(SAMPLE_ID[:-1]) == SAMPLE_ID[:-1]
    assert mask_id_card_numbers("9" + SAMPLE_ID) == "9" + SAMPLE_ID
    assert mask_id_card_numbers("GB/T 20801.1-2025 第 6.3.2 条") == "GB/T 20801.1-2025 第 6.3.2 条"
    assert mask_id_card_numbers(None) is None
    assert len(MASKED_ID) == 18


def test_masks_nested_values_without_mutating_input() -> None:
    original = {"text": SAMPLE_ID, "rows": [{"身份证号": SAMPLE_ID}], "pageNo": 3, "bbox": [1, 2, 3, 4]}
    snapshot = copy.deepcopy(original)

    masked = mask_id_card_numbers(original)

    assert masked == {"text": MASKED_ID, "rows": [{"身份证号": MASKED_ID}], "pageNo": 3, "bbox": [1, 2, 3, 4]}
    assert original == snapshot


def test_build_chunks_masks_text_and_table_structure() -> None:
    file = {"id": "KF-PF-1", "sourceId": "KS-PROJECT-FILE", "fileName": "焊工证.pdf", "contextType": "project_material"}
    units = [
        {"pageNo": 1, "text": f"焊工 张三 身份证号 {SAMPLE_ID} 持证项目 SMAW-FeII-6G", "sourceMethod": "remote_ocr"},
        {
            "pageNo": 2,
            "blockType": "table",
            "text": f"姓名 身份证号 张三 {SAMPLE_ID}",
            "tableHtml": f"<table><tr><td>姓名</td><td>身份证号</td></tr><tr><td>张三</td><td>{SAMPLE_ID}</td></tr></table>",
            "caption": f"持证人 {SAMPLE_ID}",
            "sourceMethod": "remote_ocr",
        },
    ]

    chunks = build_chunks_for_file(file, units)

    assert len(chunks) == 2
    assert all(SAMPLE_ID not in repr(chunk) for chunk in chunks)
    assert MASKED_ID in chunks[0]["text"]
    assert MASKED_ID in chunks[1]["tableHtml"] and MASKED_ID in chunks[1]["caption"]
    assert any(MASKED_ID in str(row) for row in chunks[1]["tableRows"])


def test_worker_fragments_are_masked_but_parse_result_is_untouched() -> None:
    assert tasks.split_text_fragments(f"身份证 {SAMPLE_ID}", page_no=4)[0]["text"] == f"身份证 {MASKED_ID}"

    repo.reset()
    parse_result = {
        "id": "OPR-1", "documentVersionId": "VER-1", "status": "success", "finishedAt": "2026-10-29T00:00:00",
        "fragments": [
            {"id": "F1", "pageNo": 1, "text": f"焊工身份证号 {SAMPLE_ID}", "bbox": [0, 0, 10, 10]},
            {"id": "F2", "pageNo": 1, "text": "持证项目 GTAW-FeII-5G", "bbox": [0, 10, 10, 20]},
        ],
    }
    repo.state["ocr_parse_results"] = [parse_result]
    stored = copy.deepcopy(parse_result)

    fragments = tasks.knowledge_slice_fragments_from_ocr({"id": "KF-PF-1", "documentVersionId": "VER-1"})

    assert fragments and all(SAMPLE_ID not in repr(item) for item in fragments)
    assert any(MASKED_ID in item["text"] for item in fragments)
    # OCR 框里的文字同样进库，也要脱敏
    assert any(MASKED_ID in box["text"] for item in fragments for box in item["roi"]["boxes"])
    # 解析结果本身还要拿去核证件，不能被改
    assert repo.state["ocr_parse_results"][0] == stored
