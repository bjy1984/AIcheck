"""OCR 标签抽取：起始日不当截止日，供方不当制造单位；拿不准就留空，交给规则报证据不足。"""

from apps.ocr_service.service import (
    extract_qualification_certificate_fields,
    qualification_valid_until_candidate,
    quality_certificate_manufacturer,
)


def _until(text: str):
    found = qualification_valid_until_candidate([(text, {"pageNo": 1})])
    return found["text"] if found else None


def test_multiline_fragment_with_start_only_validity_has_no_valid_until():
    # MinerU 整份文档一个片段：只有「有效期起」没有截止日时，旧版把起始日当截止日，有效证书被判过期。
    assert _until("特种设备生产许可证\n有效期起：2024年9月7日\n发证机关：示例局") is None
    assert _until("特种设备生产许可证\n有效期自 2024年9月7日\n发证机关：示例局") is None
    result = {"fragments": [{"pageNo": 1, "text": "中华人民共和国特种设备生产许可证\n许可证编号：TS3841999-2028\n"
                                                  "有效期起：2024年9月7日\n发证机关：示例局"}], "fields": []}
    extract_qualification_certificate_fields(result)
    assert "valid_until" not in {item["fieldCode"] for item in result["fields"]}


def test_multiline_fragment_still_reads_an_explicit_end_date():
    assert _until("特种设备生产许可证\n有效期起：2024年9月7日\n有效期至：2028年9月6日") == "2028年9月6日"
    assert _until("特种设备生产许可证\n有效期起：2024年9月7日 有效期至 2028年9月6日") == "2028年9月6日"
    assert _until("特种设备生产许可证\n有效期：2024年9月7日至2028年9月6日") == "2028年9月6日"


def test_supplier_labels_are_not_the_manufacturer():
    assert quality_certificate_manufacturer([("产品质量证明书", {}), ("供方：示例钢材贸易有限公司", {})]) is None
    assert quality_certificate_manufacturer([("供货单位：示例钢材贸易有限公司", {}), ("产品质量证明书", {})]) is None
    # 供货单位写在前面，也不能压过后面的生产厂家标签。
    assert quality_certificate_manufacturer([("供货单位：示例钢材贸易有限公司", {}),
                                             ("生产厂家：示例钢管制造有限公司", {})])["text"] == "示例钢管制造有限公司"
    # 无标签兜底跳过供方那一行，仍取独立的厂名行。
    assert quality_certificate_manufacturer([("示例钢管制造有限公司", {}),
                                             ("供方：示例钢材贸易有限公司", {})])["text"] == "示例钢管制造有限公司"
