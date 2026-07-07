from apps.ocr_service.profiles import profile_for, validate_profiles
from apps.ocr_service.service import enrich_parse_result
from apps.ocr_service.welder_certificate_tool import extract_welder_certificate_from_ocr_result


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
