from apps.ocr_service.service import enrich_parse_result
from libs.ocr.profiles import profile_for, validate_profiles
from libs.ocr.welder_certificate_tool import extract_welder_certificate_from_ocr_result


def test_extract_welder_certificate_identity_and_qualified_items() -> None:
    text = """
    中华人民共和国特种设备安全管理和作业人员证
    姓名 赵俊祥
    证件编号 510602197603143578
    档案编号 TS2100000099937
    发证机关 沈阳市市场监督管理局
    作业项目代号 批准日期 有效日期
    GTAW-FeⅡ-6G-3/159-FefS-02/11/12 2019.07.25 2023.07.24
    SMAW-FeⅡ-6G(K)-12/159-FeF4J 2019.07.25 2023.07.24
    """

    result = extract_welder_certificate_from_ocr_result(
        {"fragments": [{"pageNo": 1, "text": text, "confidence": 0.86}]}
    )

    assert result["fields"]["certificateNo"]["value"] == "510602197603143578"
    assert result["fields"]["archiveNo"]["value"] == "TS2100000099937"
    assert result["fields"]["issuingAuthority"]["value"] == "沈阳市市场监督管理局"
    assert result["qualifiedItems"][0]["operationItemCodes"] == [
        "GTAW-FeⅡ-6G-3/159-FefS-02/11/12"
    ]
    assert result["qualifiedItems"][0]["approvalDate"] == "2019.07.25"
    assert result["qualifiedItems"][0]["validUntil"] == "2023.07.24"
    assert result["verificationSignals"]["hasCertificateNo"] is True
    assert result["verificationSignals"]["hasArchiveNo"] is True
    assert result["verificationSignals"]["hasIssuingAuthority"] is True


def test_welder_certificate_profile_enrichment_adds_fields_and_table() -> None:
    text = """
    姓名 缪柏鑫
    证件编号 430524198608135291
    档案编号 430524198608135291
    发证机关 柳州市行政审批局
    GTAW-FeⅣ-6G-6/42-FefS-02/10/12 2017.09.22 2021.09.22
    """
    raw = {
        "status": "success",
        "fragments": [{"pageNo": 3, "text": text, "confidence": 0.81}],
        "fields": [],
        "tables": [],
        "seals": [],
        "diagnostics": [],
    }

    enriched = enrich_parse_result(
        raw,
        profile=profile_for("welder_certificate_v1"),
        document_version_id=None,
        business_pack_id=None,
        model_manifest={},
    )

    fields = {field["fieldCode"]: field["fieldValue"] for field in enriched["fields"]}
    schemas = {
        table.get("businessSchema")
        for table in enriched["tables"]
        if isinstance(table, dict)
    }
    assert fields["welder_certificate_no"] == "430524198608135291"
    assert fields["welder_archive_no"] == "430524198608135291"
    assert fields["issuing_authority"] == "柳州市行政审批局"
    assert fields["welder_operation_item_code"] == "GTAW-FeⅣ-6G-6/42-FefS-02/10/12"
    assert "welder_qualified_item_table" in schemas
    assert (enriched.get("quality") or {}).get("missingFields") in (None, [])
    assert (enriched.get("quality") or {}).get("missingTables") in (None, [])


def test_welder_certificate_profile_is_valid() -> None:
    failures = [
        item
        for item in validate_profiles()
        if item.get("profileId") == "welder_certificate_v1"
    ]
    assert failures == []


def _items(*lines: str) -> list[tuple[str, str] | str]:
    result = extract_welder_certificate_from_ocr_result({"fragments": [{"pageNo": 1, "text": "\n".join(lines)}]})
    return ["conflict" if item.get("dateConflict") else (item["approvalDate"], item["validUntil"])
            for item in result["qualifiedItems"]]


C1 = "GTAW-FeⅡ-6G-3/159-FefS-02/11/12"
C2 = "SMAW-FeⅡ-6G(K)-12/159-Fef3J"


def test_card_validity_written_as_month_range_ends_on_the_last_day_of_the_month() -> None:
    # TSG Z6002 证卡：项目代号 | 有效期「自 A 至 B」| 发证机关 | 批准日期。实测旧版一项也抽不出。
    assert _items("项目代号 有效期 发证机关(章)", "批准日期",
                  f"{C1} 自 2024年11月至 2028年10月 示例市市场监督管理局 2024年11月13日") == [("2024.11.13", "2028.10.31")]
    assert _items("项目代号 有效期 发证机关(章)", "批准日期", C1, "自 2024年11月至 2028年10月",
                  "示例市市场监督管理局 2024年11月13日") == [("2024.11.13", "2028.10.31")]


def test_each_row_keeps_its_own_dates_and_header_order_decides_columns() -> None:
    # 旧版把下一行的批准日期当成上一行的截止日。
    assert _items("项目代号 有效期 发证机关(章) 批准日期",
                  f"{C1} 自 2024年11月 至 2028年10月 示例局 2024年11月13日",
                  f"{C2} 自 2023年4月 至 2027年4月 示例局 2023年2月17日") == [
        ("2024.11.13", "2028.10.31"), ("2023.02.17", "2027.04.30")]
    # 旧版按出现顺序把有效期当成批准日期。
    assert _items("作业项目代号 有效期至 批准日期", f"{C1} 2028.10.31 2024.11.13") == [("2024.11.13", "2028.10.31")]


def test_welder_list_rows_are_not_merged_across_people() -> None:
    assert _items("序号 姓名 持证项目 有效期限 发证单位", f"1 张三 {C1} 2027-04-30 示例局",
                  f"2 李四 {C2} 2025-06-30 示例局") == [("", "2027.04.30"), ("", "2025.06.30")]
    assert _items("序号 姓名 合格位置 发证日期 有效期", f"1 王五 {C1} 2024-11 2028-10") == [("2024.11.01", "2028.10.31")]


def test_blank_template_rows_and_contradictory_dates_give_no_validity() -> None:
    assert _items("项目代号 有效期 发证机关(章)", "批准日期", "自 年 月至 年 月 年 月 日") == []
    assert _items("作业项目代号 批准日期 有效日期", f"{C1} 2027.04.30 2027.04.20") == ["conflict"]
