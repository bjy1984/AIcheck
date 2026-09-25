"""证书类节点的事实构建：从 OCR 字段与正文里抽出「谁的证、什么证、有效到几时、许可什么」。

## 为什么必须有

2026-09-03 审计：规则版本对齐后，节点 24/38 的规则引擎确实调了焊工证、检测人员
资格的核验工具，却全部返回 evidence_insufficient——业务事实里 certificates 为空、
validUntil/workDate 都是 null。工具在，喂给它的事实是空的。节点 1/2/3/38 更是根本
没有 fact builder。证书有效性核验卡在事实抽取层，不在路由层。

## 做什么

按节点 profile（CERTIFICATE_NODE_PROFILES）挑出本次输入版本里的证书类资料，
从三处取值，先到先得、后者补缺：
1. OCR 结构化字段（parse_result.fields，按 fieldCode / fieldName 别名匹配）；
2. 焊工证专用抽取器（extract_welder_certificate_from_ocr_result，合格项目带各自有效期）；
3. OCR 正文正则回退（"有效期至 2028年1月17日" 之类）。

每张证一条 CertificateFact：holder / certificateNo / issuer / validFrom / validUntil /
scopes / evidence（documentVersionId、fileName、pageNo、quotedText）。同时按旧绑定表
的命名把关键字段镜像到 designLicense.* / installationLicense.* / ndtAgency.* /
ndtPersonnel.*，让已有的 check_date_covers / check_*_scope 绑定也能拿到参数。

判断本身不在这里做：这里只产事实，判定交给 deterministic_tools.check_certificate_validity。
"""

from __future__ import annotations

import re
from copy import deepcopy
from datetime import date, timedelta
from typing import Any

from libs.contracts.responses import business_today
from libs.ocr.welder_certificate_tool import (
    extract_welder_certificate_from_ocr_result,
    split_welder_cards,
)
from libs.review_input_data import latest_usable_selected_parses
from libs.review_orchestrator.r12_agent import stable_payload_hash

from .deterministic_tools import parse_date as _iso_parse_date


def parse_date(value: Any, *, month_end: bool = False) -> date | None:
    """比 deterministic_tools.parse_date 多两步：中文日期不补零（2028年1月17日）也要认；
    只到月的（2028年10月 / 2028-10）按月初、month_end=True 时按月末——证书有效期常只写到月。"""
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    match = re.search(r"(\d{4})\s*[年.\-/]\s*(\d{1,2})\s*[月.\-/]\s*(\d{1,2})", text)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None
    match = re.search(r"(\d{4})\s*[年.\-/]\s*(\d{1,2})\s*月?(?!\s*[\d日])", text)
    if match:
        try:
            year, month = int(match.group(1)), int(match.group(2))
            if not 1 <= month <= 12:
                return None
            if month_end:
                return date(year + (month == 12), 1 if month == 12 else month + 1, 1) - timedelta(days=1)
            return date(year, month, 1)
        except ValueError:
            return None
    return _iso_parse_date(text)


# 节点 → 证书 profile。materialTypeCodes 是打靶/分类给出的资料类型；
# kindMarkers 用来在没有类型标注时按文件名/正文识别。
CERTIFICATE_NODE_PROFILES: dict[int, dict[str, Any]] = {
    1: {
        "certificateType": "design_license",
        "label": "设计单位许可证",
        "materialTypeCodes": ("design_license",),
        "kindMarkers": ("设计许可", "设计资质", "压力管道设计"),
        "legacyNamespace": "designLicense",
        "holderFactKey": "holderName",
        "scopeFactKey": "scopeCodes",
        "expectedHolderProjectField": "designOrgName",
    },
    2: {
        "certificateType": "installation_license",
        "label": "安装（施工）单位许可证",
        "materialTypeCodes": ("construction_license", "installation_license"),
        "kindMarkers": ("安装许可", "施工许可", "安装资质", "特种设备安装"),
        "legacyNamespace": "installationLicense",
        "holderFactKey": "holderName",
        "scopeFactKey": "scopeCodes",
        "expectedHolderProjectField": "contractorOrgName",
    },
    3: {
        "certificateType": "ndt_agency_approval",
        "label": "无损检测机构核准证",
        "materialTypeCodes": ("ndt_org_certificate", "ndt_agency_approval"),
        "kindMarkers": ("无损检测机构", "检测机构核准", "核准证"),
        "legacyNamespace": "ndtAgency",
        "holderFactKey": "organizationName",
        "scopeFactKey": "approvalItemCodes",
        "expectedHolderProjectField": "ndtOrgName",
    },
    24: {
        "certificateType": "welder_certificate",
        "label": "焊工资格证",
        "materialTypeCodes": ("welder_certificate",),
        "kindMarkers": ("焊工证", "焊工资格", "焊接操作人员"),
        "legacyNamespace": "welderCertificate",
        "holderFactKey": "welderName",
        "scopeFactKey": "qualificationCodes",
        "expectedHolderProjectField": None,
    },
    38: {
        "certificateType": "ndt_personnel_certificate",
        "label": "无损检测人员资格证",
        "materialTypeCodes": ("ndt_person_certificate", "ndt_personnel_certificate"),
        "kindMarkers": ("检测人员资质", "检测人员资格", "无损检测人员", "NDT人员"),
        "legacyNamespace": "ndtPersonnel",
        "holderFactKey": "name",
        "scopeFactKey": "qualificationCodes",
        "expectedHolderProjectField": None,
    },
}

# 字段别名：fieldCode（snake_case，OCR profile 给的）与 fieldName（中文标签）都认。
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "holder": (
        "organization_name", "holder", "holder_name", "unit_name", "manufacturer", "name", "welder_name", "person_name",
        "单位名称", "机构名称", "持证单位", "获证单位", "企业名称", "施工单位", "安装单位", "设计单位", "检测机构",
        "姓名", "持证人", "焊工姓名",
    ),
    "certificateNo": (
        "certificate_no", "license_no", "welder_certificate_no", "registration_no",
        "证书编号", "许可证编号", "许可证号", "证号", "编号", "资格证编号", "焊工证号", "执业注册编号", "注册编号",
    ),
    "issuer": ("issuer", "issuing_authority", "发证机关", "发证单位", "颁发机关", "核准机关", "批准机关"),
    "validFrom": ("valid_from", "issue_date", "approval_date", "有效期起", "有效期自", "发证日期", "批准日期", "签发日期"),
    "validUntil": ("valid_until", "expiry_date", "valid_to", "有效期至", "有效期止", "有效期限", "有效日期", "有效期", "截止日期"),
    "scope": (
        "license_scope", "approved_items", "qualified_items", "product_scope", "welder_operation_item_code",
        "许可范围", "许可项目", "许可子项目", "核准项目", "核准范围", "合格项目", "持证合格项目", "项目代号", "类别级别", "许可级别",
    ),
}

_DATE_TEXT = r"(\d{4}\s*[年.\-/]\s*\d{1,2}\s*[月.\-/]\s*\d{1,2}\s*日?)"
_MONTH_TEXT = r"(\d{4}\s*[年.\-/]\s*\d{1,2}\s*月?)(?![\d日])"
_TEXT_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "validUntil": [
        re.compile(r"有效期(?:限)?(?:至|止|到)\s*[:：]?\s*" + _DATE_TEXT),
        re.compile(r"有效(?:期|日期)(?:限)?\s*[:：]?\s*(?:自|从)?\s*" + _DATE_TEXT + r"\s*(?:至|到|—|–|-|~|～)\s*" + _DATE_TEXT),
        re.compile(r"(?:至|到)\s*" + _DATE_TEXT + r"\s*(?:止|有效)"),
        re.compile(r"有效期(?:限)?(?:至|止|到)\s*[:：]?\s*" + _MONTH_TEXT),
        re.compile(r"有效期(?:限)?\s*[:：]?\s*(?:自)?\s*" + _MONTH_TEXT + r"\s*(?:至|到|—|-|~)\s*" + _MONTH_TEXT),
        re.compile(r"自\s*" + _MONTH_TEXT + r"\s*(?:至|到)\s*" + _MONTH_TEXT),
    ],
    "validFrom": [
        re.compile(r"有效期(?:自|起|从)\s*[:：]?\s*" + _DATE_TEXT),
        re.compile(r"(?:发证|批准|签发|颁发)日期\s*[:：]?\s*" + _DATE_TEXT),
    ],
    "certificateNo": [
        re.compile(r"(?<!注册)(?:证书|资格证|证件)编号\s*[:：]?\s*(\d{14,17}[0-9X])"),
        re.compile(r"(?:许可证|证书|资格证)编号\s*[:：]?\s*([A-Z]{1,4}[A-Z0-9\-—–/]{4,})"),
        re.compile(r"\b(TS\d{7}-\d{4})\b"),
        re.compile(r"(?:注册证书|注册)编号\s*[:：]?\s*([A-Z]{1,6}\d{6,})"),
    ],
    "issuer": [
        re.compile(r"(?:发证|颁发|核准|批准)(?:机关|单位)\s*[:：]?\s*([一-龥（）()]{4,40}(?:局|委员会|协会|中心|学会|总局))"),
    ],
}


def certificate_profile_for_node(node_id: int) -> dict[str, Any] | None:
    return deepcopy(CERTIFICATE_NODE_PROFILES.get(int(node_id or 0)))


def project_certificate_period(project: dict[str, Any] | None) -> dict[str, Any]:
    """证书应覆盖的业务期间。项目没填施工起止时返回空，交给工具按今日判断并告警。"""
    project = project or {}
    start = parse_date(project.get("constructionStart") or project.get("plannedConstructionStart"))
    end_candidates = [
        parse_date(project.get("changeClarificationEnd")),
        parse_date(project.get("actualConstructionEnd")),
        parse_date(project.get("plannedConstructionEnd")),
        parse_date(project.get("constructionEnd")),
    ]
    end = max((item for item in end_candidates if item), default=None)
    return {
        "periodStart": start.isoformat() if start else None,
        "periodEnd": end.isoformat() if end else None,
        "referenceDate": business_today().isoformat(),
        # 当日只是没有施工期时的兜底，不是业务核验日期：有效期工具据此把「当日已过期」交人工
        "referenceDateSource": "business_today",
    }


# 原文写明的有效期区间。OCR 字段常把「A 至 B」的起始日 A 填进「有效期至」，
# 已落库的旧解析结果也是这样，所以区间要在规则侧再对一次，不能只靠 OCR 服务。
_VALIDITY_RANGE_PATTERNS = (
    re.compile(r"有效(?:期|日期)(?:限)?\s*[:：]?\s*(?:自|从)?\s*" + _DATE_TEXT
               + r"\s*(?:至|到|—|–|-|~|～)\s*" + _DATE_TEXT),
    re.compile(_DATE_TEXT + r"\s*(?:至|到)\s*" + _DATE_TEXT + r"\s*(?:止|有效)"),
)
# 特种设备许可证编号的类别位：TS1 设计、TS3 安装改造修理、TS7 检验检测机构核准。
# 资质合订本和告知书里常同时出现几张证的编号（管理体系认证 CTC…、设计单位 TS1…），
# 2026-09-23 真实 OCR 上 Jev 核对抓到过：检测机构核准证取成了质量体系证书号，
# 安装许可证取成了告知书里设计单位的 TS1 号。
_EXPECTED_NUMBER_PREFIX = {"design_license": "TS1", "installation_license": "TS3", "ndt_agency_approval": "TS7"}
_TS_NUMBER_RE = re.compile(r"TS\s*(\d)\s*(\d{6})\s*[-—–]\s*(\d{4})", re.IGNORECASE)
# 字段名按子串认别名时，「有效期起」会被当成「有效期」命中截止日，反之亦然。
_OPPOSITE_NAME_MARKERS = {
    "validUntil": ("起", "自", "从", "发证", "签发", "批准"),
    "validFrom": ("至", "止", "截止"),
}


def build_certificate_facts(
    state: dict[str, Any],
    project_id: str,
    node_id: int,
    document_version_ids: list[str] | set[str] | tuple[str, ...],
    *,
    review_run: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """返回 {"certificateFacts": {...}, "<legacyNamespace>": {...}, "project": {...}}。"""
    profile = certificate_profile_for_node(node_id)
    if not profile:
        return {}
    requested = {str(item) for item in document_version_ids or [] if item}
    if review_run is not None and (str(review_run.get("projectId")) != project_id
            or int(review_run.get("nodeId") or 0) != node_id
            or requested != set(review_run.get("inputDocumentVersionIds") or [])):
        raise ValueError("certificate_review_scope_mismatch")
    source_run = review_run if review_run is not None else {
        "projectId": project_id, "nodeId": node_id, "inputDocumentVersionIds": sorted(requested)}
    documents = _documents_by_version(state, project_id)
    items: list[dict[str, Any]] = []
    considered: list[dict[str, Any]] = []
    for parse_result in latest_usable_selected_parses(state, source_run, requested):
        version_id = str(parse_result.get("documentVersionId") or "")
        if not version_id or version_id not in documents:
            continue
        document = documents.get(version_id) or {}
        if not _matches_profile(profile, parse_result, document):
            continue
        considered.append({"documentVersionId": version_id, "fileName": document.get("fileName")})
        items.extend(_extract_certificates(profile, parse_result, document))
    # 同一证书编号只留一条（同一份资料上传了两次的情况）
    unique: dict[str, dict[str, Any]] = {}
    for item in items:
        key = str(item.get("certificateNo") or "") or f"{item.get('documentVersionId')}:{item.get('holder')}"
        if key not in unique:
            unique[key] = item
    certificates = list(unique.values())
    # 平台侧：按许可证编号 / 身份证号到公示平台核对，核得上的用登记原文补强 OCR 值。
    from libs.review_orchestrator.certificate_platform_verify import verify_certificate_records

    certificates = verify_certificate_records(state, profile, certificates, review_run=review_run)
    project = _project_record(state, project_id)
    period = project_certificate_period(project)
    expected_holder = None
    if profile.get("expectedHolderProjectField"):
        expected_holder = str(project.get(profile["expectedHolderProjectField"]) or "").strip() or None
    facts: dict[str, Any] = {
        "certificateFacts": {
            "nodeId": int(node_id),
            "certificateType": profile["certificateType"],
            "label": profile["label"],
            "certificates": certificates,
            "expectedHolder": expected_holder,
            "period": period,
            "consideredDocuments": considered,
            "extractionWarnings": _warnings(certificates, considered),
        },
        "project": {
            "constructionStart": period["periodStart"],
            "plannedConstructionEnd": period["periodEnd"],
            profile["expectedHolderProjectField"] or "_": expected_holder,
        },
    }
    facts[profile["legacyNamespace"]] = _legacy_namespace(profile, certificates)
    facts["judgment"] = _certificate_judgment(certificates)
    return facts


def _certificate_judgment(certificates: list[dict[str, Any]]) -> dict[str, Any]:
    """把证书事实登记成 grounding 能核的形状（与 material_facts.build_material_judgment 同构）。

    2026-09-11 全节点扫描：证书节点（1/2/3/24/38）的 businessFacts 从没有 judgment，
    execution.load_ocr_result 于是把 evidenceFacts 建成空列表，validate_evidence_grounding
    看到 factCount=0，整个原子项一律证据不足——业务工具明明已经 passed 也翻不过来。
    """
    claimed: list[dict[str, Any]] = []
    refs: dict[str, dict[str, Any]] = {}
    for index, record in enumerate(certificates, 1):
        evidence = [item for item in record.get("evidence") or [] if isinstance(item, dict) and item.get("evidenceRefId")]
        for item in evidence:
            refs.setdefault(str(item["evidenceRefId"]), item)
        scored = [item["confidence"] for item in evidence if isinstance(item.get("confidence"), (int, float))]
        unavailable = bool(evidence) and all(item.get("confidenceUnavailable") for item in evidence)
        claimed.append(
            {
                "factId": f"certificate-{index}",
                "label": f"{CERTIFICATE_TYPE_NAMES.get(str(record.get('certificateType') or ''), '证书')} {record.get('certificateNo') or ''}".strip(),
                "value": record.get("certificateNo") or record.get("holder"),
                # 去重键：同一张证可能同时由 r24 焊工 builder 和证书链各产一条事实。
                "certificateNo": record.get("certificateNo"),
                "documentVersionId": record.get("documentVersionId"),
                # 界面「核对无误」要落到具体的抽取字段上：这里列出这条事实引用了哪些字段
                "fields": [
                    {"fieldName": item.get("fieldName"), "documentVersionId": item.get("documentVersionId"),
                     # 界面按 documentId 拉 ocr-fields 再定位 fieldId，这里把 documentId 一并带上
                     "documentId": record.get("documentId") or None,
                     "quotedText": item.get("quotedText"), "humanCorrected": bool(item.get("humanCorrected"))}
                    for item in evidence if item.get("fieldName")
                ],
                "evidenceRefIds": [str(item["evidenceRefId"]) for item in evidence],
                # 有分取最低的那一处（证据链以最弱一环计）；引擎没给分就如实标「不可用」。
                "confidence": min(scored) if scored else None,
                "confidenceUnavailable": unavailable,
                "conflicted": False,
            }
        )
    return {"claimedFacts": claimed, "evidenceRefs": list(refs.values())}


def _legacy_namespace(profile: dict[str, Any], certificates: list[dict[str, Any]]) -> dict[str, Any]:
    """按旧绑定表的 requiredFacts 命名镜像一份，让既有 check_date_covers 等绑定可用。"""
    first = certificates[0] if certificates else {}
    scopes = list(dict.fromkeys(code for item in certificates for code in item.get("scopes") or []))
    namespace: dict[str, Any] = {
        profile["holderFactKey"]: first.get("holder"),
        "certificateNo": first.get("certificateNo"),
        "issuer": first.get("issuer"),
        "validFrom": first.get("validFrom"),
        "validUntil": first.get("validUntil"),
        profile["scopeFactKey"]: scopes,
        "certificates": deepcopy(certificates),
    }
    if profile["certificateType"] == "ndt_personnel_certificate":
        namespace["roster"] = [
            {"name": item.get("holder"), "certificateNo": item.get("certificateNo"), "validUntil": item.get("validUntil")}
            for item in certificates
        ]
        namespace["qualificationCodes"] = scopes
        namespace["registration"] = [item.get("certificateNo") for item in certificates if item.get("certificateNo")]
    return namespace


def _documents_by_version(state: dict[str, Any], project_id: str) -> dict[str, dict[str, Any]]:
    """本工程文档的 版本号 → 文档。第二个循环补的是非当前版本，**同样要按工程过滤**。

    2026-09-11 全节点扫描实测：三个项目各自调用都返回 316 个版本（全库），交集也是 316。
    第一个循环按 projectId 过滤了，第二个循环却把全库版本无条件补进来，把过滤抵消掉。
    `pipeline_facts.build_project_pipelines` 与 `design_facts` 是**全工程扫描**（管道特性表
    挂在设计节点、不在当前节点输入里），拿到的于是是别的工程的资料；
    `certificate_facts` 那处被 selected_parse_results 的运行级范围兜住，没漏出去。
    projectId 为空的文档（生产有 60 份）不属于任何工程，不该出现在每个工程里。
    """
    by_id = {
        str(document.get("id") or ""): document
        for document in state.get("documents") or []
        if isinstance(document, dict) and str(document.get("projectId") or "") == str(project_id)
    }
    mapping: dict[str, dict[str, Any]] = {}
    for document in by_id.values():
        version_id = str(document.get("currentVersionId") or "")
        if version_id:
            mapping[version_id] = document
    for version in state.get("versions") or []:
        if not isinstance(version, dict):
            continue
        version_id = str(version.get("id") or version.get("documentVersionId") or "")
        document = by_id.get(str(version.get("documentId") or ""))
        if version_id and document and version_id not in mapping:
            mapping[version_id] = document
    return mapping


def _project_record(state: dict[str, Any], project_id: str) -> dict[str, Any]:
    for project in state.get("projects") or []:
        if isinstance(project, dict) and str(project.get("id") or "") == str(project_id):
            return project
    return {}


# 词典分类分不清许可证的「种类」：设计/安装单位拿的都叫「特种设备生产许可证」，
# 只有正文里「获准从事下列压力管道的安装/设计」才说明是哪一种。2026-09-03 审计：
# 测试项目3 节点 2 人工挂上的安装许可证被分类成 manufacturing_license，profile 直接
# 判「明确是别的类型」，OCR 字段里明明有 TS3832083-2026 / 有效期至 2026年12月25日。
# 这些许可证族代码视为未定，交给 kindMarkers 按正文再判。
AMBIGUOUS_TYPE_CODES = frozenset(
    {
        "",
        "generic_document",
        "generic_review_material",
        "unclassified_material",
        "qualification_certificate",
        "manufacturing_license",
        "design_license",
        "construction_license",
        "installation_license",
        "special_equipment_license",
        "license",
    }
)


def _matches_profile(profile: dict[str, Any], parse_result: dict[str, Any], document: dict[str, Any]) -> bool:
    metadata = parse_result.get("metadata") if isinstance(parse_result.get("metadata"), dict) else {}
    type_codes = {
        str(document.get("materialTypeCode") or ""),
        str(metadata.get("materialTypeCode") or ""),
        str(parse_result.get("documentType") or ""),
    }
    if type_codes & set(profile["materialTypeCodes"]):
        return True
    if type_codes - AMBIGUOUS_TYPE_CODES:
        # 已经明确是别的类型，不再按关键词猜
        return False
    hint = " ".join(
        [
            str(document.get("fileName") or ""),
            str(parse_result.get("fileName") or ""),
            _full_text(parse_result)[:2000],
        ]
    )
    return any(marker in hint for marker in profile["kindMarkers"])


def _full_text(parse_result: dict[str, Any]) -> str:
    parts: list[str] = []
    for fragment in parse_result.get("fragments") or []:
        if isinstance(fragment, dict):
            parts.append(str(fragment.get("text") or fragment.get("fullText") or ""))
    if not parts:
        parts.append(str(parse_result.get("fullText") or parse_result.get("text") or ""))
    return "\n".join(part for part in parts if part)


def _extract_certificates(
    profile: dict[str, Any], parse_result: dict[str, Any], document: dict[str, Any]
) -> list[dict[str, Any]]:
    version_id = str(parse_result.get("documentVersionId") or "")
    file_name = str(document.get("fileName") or parse_result.get("fileName") or "")
    if profile["certificateType"] == "welder_certificate":
        welder = _welder_certificates(parse_result, version_id, file_name)
        if welder:
            return welder
    fields = _field_values(parse_result)
    text = _full_text(parse_result)
    unavailable = _confidence_unavailable(parse_result)
    segments = _person_segments(text) if profile["certificateType"] == "ndt_personnel_certificate" else []
    if len(segments) > 1:
        records = []
        for segment in segments:
            record = _record_from_text(profile, segment, parse_result, document, version_id, file_name)
            if record:
                records.append(record)
        if records:
            return records
    record: dict[str, Any] = {
        "certificateType": profile["certificateType"],
        "documentVersionId": version_id,
        "documentId": str(document.get("id") or ""),
        "fileName": file_name,
        "holder": None,
        "certificateNo": None,
        "issuer": None,
        "validFrom": None,
        "validUntil": None,
        "scopes": [],
        "evidence": [],
        "sources": {},
    }
    human_corrected: set[str] = set()
    for key in ("holder", "certificateNo", "issuer", "validFrom", "validUntil"):
        hit = _first_field(fields, FIELD_ALIASES[key], exclude_name_markers=_OPPOSITE_NAME_MARKERS.get(key, ()))
        if key == "holder" and profile["certificateType"] in {
            "design_license", "installation_license", "ndt_agency_approval"
        }:
            candidates = list(_all_fields(fields, FIELD_ALIASES[key]))
            hit = next((candidate for candidate in candidates if not _organization_field_is_sentence(candidate["value"])), None)
            if hit is None and candidates:
                # OCR 有时把「你单位被评定为 A 级机构。」的后半句填入单位名称。
                record["holderFieldRejected"] = candidates[0]["value"]
        if hit is not None:
            value = hit["value"]
            if key in {"validFrom", "validUntil"}:
                parsed = parse_date(value)
                value = parsed.isoformat() if parsed else None
            if value:
                record[key] = value
                record["sources"][key] = "ocr_field"
                if hit.get("humanCorrected"):
                    human_corrected.add(key)
                record["evidence"].append(_evidence(version_id, file_name, hit.get("pageNo"), hit.get("bbox"), hit.get("raw"),
                                                    confidence=hit.get("confidence"), confidence_unavailable=unavailable,
                                                    field_name=hit.get("name"), human_corrected=bool(hit.get("humanCorrected"))))
    scope_hits = [hit for hit in _all_fields(fields, FIELD_ALIASES["scope"])]
    for hit in scope_hits:
        for code in _split_scopes(hit["value"]):
            if code not in record["scopes"]:
                record["scopes"].append(code)
        record["evidence"].append(_evidence(version_id, file_name, hit.get("pageNo"), hit.get("bbox"), hit.get("raw"),
                                            confidence=hit.get("confidence"), confidence_unavailable=unavailable,
                                            field_name=hit.get("name"), human_corrected=bool(hit.get("humanCorrected"))))
    if scope_hits:
        record["sources"]["scopes"] = "ocr_field"
    _fill_from_text(record, text, parse_result, version_id, file_name,
                    allow_person_holder=profile["certificateType"] not in {
                        "design_license", "installation_license", "ndt_agency_approval"
                    })
    _reconcile_validity_range(record, text, parse_result, version_id, file_name, protected=human_corrected)
    _reconcile_certificate_number(record, text, profile["certificateType"], protected=human_corrected,
                                  parse_result=parse_result, version_id=version_id, file_name=file_name)
    if not any(record.get(key) for key in ("certificateNo", "validUntil", "holder")):
        return []
    return [record]


def _reconcile_certificate_number(record: dict[str, Any], text: str, certificate_type: str, *,
                                  protected: set[str], parse_result: dict[str, Any] | None = None,
                                  version_id: str = "", file_name: str = "") -> None:
    """编号类别位与证书类型不符时，改用原文里唯一一个类别位相符的编号；多个或没有就不猜，只记警告。

    换了编号就要换证据：原字段引的是另一张证的号（TS1…），留着它，grounding 会拿那个
    高置信字段替新编号作证，界面也会指着 TS1 那一处说「这是 TS3 的出处」。
    """
    expected = _EXPECTED_NUMBER_PREFIX.get(certificate_type)
    number = re.sub(r"\s+", "", str(record.get("certificateNo") or "")).upper()
    if not expected or not number or number.startswith(expected) or "certificateNo" in protected:
        return
    candidates: dict[str, re.Match[str]] = {}
    for match in _TS_NUMBER_RE.finditer(text):
        if f"TS{match.group(1)}" == expected:
            candidates.setdefault(f"TS{match.group(1)}{match.group(2)}-{match.group(3)}", match)
    if len(candidates) != 1:
        record.setdefault("extractionWarnings", []).append(
            "certificate_no_type_mismatch" if not candidates else "certificate_no_ambiguous")
        return
    replacement, match = next(iter(candidates.items()))
    record.setdefault("replacedByNumberType", {})["certificateNo"] = record["certificateNo"]
    record["certificateNo"] = replacement
    record.setdefault("sources", {})["certificateNo"] = "ocr_text_number_type"
    record["evidence"] = [
        item for item in record.get("evidence") or []
        if not (isinstance(item, dict) and number in re.sub(r"\s+", "", str(item.get("quotedText") or "")).upper())
    ]
    parse_result = parse_result or {}
    page_no, quoted, fragment_confidence = _locate_text(parse_result, match.group(0))
    # 新编号落不到具体片段（跨片段拼出来的）就给 0 分：宁可交人工，也不让别的字段替它作证。
    record["evidence"].append(_evidence(
        version_id, file_name, page_no, None, quoted,
        confidence=fragment_confidence if page_no is not None else 0.0,
        confidence_unavailable=page_no is not None and _confidence_unavailable(parse_result)))


def _reconcile_validity_range(
    record: dict[str, Any], text: str, parse_result: dict[str, Any], version_id: str, file_name: str, *,
    protected: set[str],
) -> None:
    """按原文里与截止日同属一个「有效期 A 至 B」的区间校正起止日。

    OCR 字段把起始日 A 当成截止日时改回 B；起始日缺失或取的是发证日期时改为 A。
    只认与当前截止日对得上的区间：资质合订本里常有好几张证书，别的区间属于别的
    证书，不能拿来覆盖。人工修正过的值不动，被替换的原值留痕。
    """
    until = record.get("validUntil")
    if not until or "validUntil" in protected:
        return
    for pattern in _VALIDITY_RANGE_PATTERNS:
        for match in pattern.finditer(text):
            start = parse_date(re.sub(r"\s+", "", match.group(1)))
            end = parse_date(re.sub(r"\s+", "", match.group(2)), month_end=True)
            if not start or not end or end <= start:
                continue
            sources = record.setdefault("sources", {})
            replaced: dict[str, Any] = {}
            if until == start.isoformat() and sources.get("validUntil") == "ocr_field":
                replaced["validUntil"] = until
                record["validUntil"] = end.isoformat()
                sources["validUntil"] = "ocr_text_range"
            elif until != end.isoformat():
                continue
            # 发证日期不等于生效日；同一区间的起始日才是有效期起点。
            if ("validFrom" not in protected and record.get("validFrom") != start.isoformat()
                    and sources.get("validFrom") in {None, "ocr_field"}):
                if record.get("validFrom"):
                    replaced["validFrom"] = record["validFrom"]
                record["validFrom"] = start.isoformat()
                sources["validFrom"] = "ocr_text_range"
            if replaced:
                record["replacedByValidityRange"] = replaced
            page_no, quoted, fragment_confidence = _locate_text(parse_result, match.group(0))
            record.setdefault("evidence", []).append(_evidence(
                version_id, file_name, page_no, None, quoted,
                confidence=fragment_confidence, confidence_unavailable=_confidence_unavailable(parse_result)))
            return


def _organization_field_is_sentence(value: str) -> bool:
    text = str(value or "").strip()
    return "被评定为" in text or "被评为" in text or "你单位" in text or text.endswith(("。", "！", "!", "；", ";"))


_PERSON_SPLIT = re.compile(r"(?=特种设备检验检测人员证)")


def _person_segments(text: str) -> list[str]:
    """一份 PDF 里常装着多个人的资格证：按证书抬头切段，每段一个人。"""
    parts = [part.strip() for part in _PERSON_SPLIT.split(text) if part and "证书编号" in part]
    return parts


def _record_from_text(
    profile: dict[str, Any],
    text: str,
    parse_result: dict[str, Any],
    document: dict[str, Any],
    version_id: str,
    file_name: str,
) -> dict[str, Any] | None:
    record: dict[str, Any] = {
        "certificateType": profile["certificateType"],
        "documentVersionId": version_id,
        "documentId": str(document.get("id") or ""),
        "fileName": file_name,
        "holder": None,
        "certificateNo": None,
        "issuer": None,
        "validFrom": None,
        "validUntil": None,
        "scopes": [],
        "evidence": [],
        "sources": {},
    }
    name = re.search(r"姓名\s*[:：]?\s*([一-龥·]{2,6})", text)
    if name:
        record["holder"] = name.group(1)
        record["sources"]["holder"] = "ocr_text"
    _fill_from_text(record, text, parse_result, version_id, file_name)
    if not any(record.get(key) for key in ("certificateNo", "validUntil", "holder")):
        return None
    return record


def _fill_from_text(
    record: dict[str, Any], text: str, parse_result: dict[str, Any], version_id: str, file_name: str, *,
    allow_person_holder: bool = True,
) -> None:
    """按正文正则补缺（持证人、编号、发证机关、有效期起止、范围代号）。"""
    if allow_person_holder and not record.get("holder"):
        name = re.search(r"姓\s*名\s*[:：]?\s*([一-龥·]{2,6})", text)
        if name:
            record["holder"] = name.group(1)
            record.setdefault("sources", {})["holder"] = "ocr_text"
    for key, patterns in _TEXT_PATTERNS.items():
        if record.get(key):
            continue
        for pattern in patterns:
            match = pattern.search(text)
            if not match:
                continue
            raw = match.group(match.lastindex or 1)
            value: Any = raw
            if key in {"validFrom", "validUntil"}:
                if key == "validUntil" and match.lastindex and match.lastindex >= 2:
                    raw = match.group(2)
                    if not record.get("validFrom"):
                        parsed_from = parse_date(re.sub(r"\s+", "", match.group(1)))
                        if parsed_from:
                            record["validFrom"] = parsed_from.isoformat()
                            record.setdefault("sources", {})["validFrom"] = "ocr_text"
                parsed = parse_date(re.sub(r"\s+", "", raw), month_end=(key == "validUntil"))
                value = parsed.isoformat() if parsed else None
            if value:
                record[key] = value
                record.setdefault("sources", {})[key] = "ocr_text"
                page_no, quoted, fragment_confidence = _locate_text(parse_result, match.group(0))
                record.setdefault("evidence", []).append(_evidence(
                    version_id, file_name, page_no, None, quoted,
                    confidence=fragment_confidence, confidence_unavailable=_confidence_unavailable(parse_result)))
                break
    if not record.get("scopes"):
        codes = [f"{m.group(1).upper()}-{_roman(m.group(2))}" for m in re.finditer(r"\b(RT|UT|MT|PT|ET|TOFD|PAUT|VT|AE)\s*[\(（]?\s*(I{1,3}|Ⅰ|Ⅱ|Ⅲ|1|2|3)\b", text)]
        codes += _scope_codes_from_text(text)
        record["scopes"] = list(dict.fromkeys(codes))
        if record["scopes"]:
            record.setdefault("sources", {})["scopes"] = "ocr_text"


def _roman(value: str) -> str:
    return {"I": "I", "II": "II", "III": "III", "Ⅰ": "I", "Ⅱ": "II", "Ⅲ": "III", "1": "I", "2": "II", "3": "III"}.get(value, value)


def _welder_certificates(parse_result: dict[str, Any], version_id: str, file_name: str) -> list[dict[str, Any]]:
    # 几个焊工的证合订成一份时按「某某焊工证」分段，每人一条；不分段会把甲的姓名配上乙的证号。
    fragments = [item for item in parse_result.get("fragments") or [] if isinstance(item, dict)]
    segments = split_welder_cards(fragments) if fragments else [fragments]
    parts = [parse_result] if len(segments) == 1 else [{**parse_result, "fragments": segment} for segment in segments]
    records = []
    for part in parts:
        found = _welder_certificate(part, version_id, file_name)
        if found:
            # 正文补缺只用这个人自己那一段，不能从合订本别人的证上补。
            _fill_from_text(found[0], _full_text(part), part, version_id, file_name)
        records.extend(found)
    return records


def _welder_certificate(parse_result: dict[str, Any], version_id: str, file_name: str) -> list[dict[str, Any]]:
    try:
        extraction = extract_welder_certificate_from_ocr_result(parse_result)
    except Exception:  # noqa: BLE001 - 抽取器失败就退回通用路径
        return []
    fields = extraction.get("fields") if isinstance(extraction.get("fields"), dict) else {}
    qualified = [item for item in extraction.get("qualifiedItems") or [] if isinstance(item, dict)]
    name = _field_obj_value(fields.get("welderName"))
    certificate_no = _field_obj_value(fields.get("certificateNo"))
    if not name and not certificate_no and not qualified:
        return []
    # 日期自相矛盾（批准日晚于截止日）的项不参与有效期判断。
    qualified_dated = [item for item in qualified if not item.get("dateConflict")]
    valid_until_dates = [parse_date(item.get("validUntil")) for item in qualified_dated]
    valid_until_dates = [item for item in valid_until_dates if item]
    approval_dates = [parse_date(item.get("approvalDate")) for item in qualified_dated]
    approval_dates = [item for item in approval_dates if item]
    record = {
        "certificateType": "welder_certificate",
        "documentVersionId": version_id,
        "documentId": "",
        "fileName": file_name,
        "holder": name,
        "certificateNo": certificate_no,
        "issuer": _field_obj_value(fields.get("issuingAuthority")),
        # 焊工证的有效期按合格项目各自计；证级别取最早到期的那一项，最严格
        "validFrom": min(approval_dates).isoformat() if approval_dates else None,
        "validUntil": min(valid_until_dates).isoformat() if valid_until_dates else None,
        "scopes": [str(item.get("operationItemCode") or "") for item in qualified if item.get("operationItemCode")],
        "qualifiedItems": [
            {
                "operationItemCode": item.get("operationItemCode"),
                "approvalDate": (parse_date(item.get("approvalDate")) or "") and parse_date(item.get("approvalDate")).isoformat(),
                "validUntil": (parse_date(item.get("validUntil")) or "") and parse_date(item.get("validUntil")).isoformat(),
            }
            for item in qualified
        ],
        "evidence": [],
        "sources": {"extractor": extraction.get("toolVersion")},
    }
    for field_name in ("welderName", "certificateNo", "issuingAuthority"):
        obj = fields.get(field_name) if isinstance(fields.get(field_name), dict) else None
        evidence = (obj or {}).get("evidence") if isinstance((obj or {}).get("evidence"), dict) else {}
        if obj and obj.get("value"):
            record["evidence"].append(_evidence(
                version_id, file_name, evidence.get("pageNo"), evidence.get("bbox"), obj.get("value"),
                confidence=obj.get("confidence", evidence.get("confidence")),
                confidence_unavailable=_confidence_unavailable(parse_result)))
    return [record]


def _field_obj_value(obj: Any) -> str | None:
    if isinstance(obj, dict):
        value = obj.get("value")
        return str(value).strip() if value not in (None, "") else None
    if obj in (None, ""):
        return None
    return str(obj).strip()


def _field_values(parse_result: dict[str, Any]) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for field in parse_result.get("fields") or []:
        if not isinstance(field, dict):
            continue
        value = field.get("fieldValue")
        if value in (None, ""):
            value = field.get("value")
        if value in (None, ""):
            continue
        values.append(
            {
                "code": str(field.get("fieldCode") or field.get("key") or "").strip().lower(),
                "name": str(field.get("fieldName") or field.get("label") or "").strip(),
                "value": str(value).strip(),
                "pageNo": field.get("pageNo"),
                "bbox": field.get("bbox"),
                # 原来这里把 confidence 丢了，证据链到 grounding 时只能是 None。
                "confidence": field.get("confidence"),
                "humanCorrected": bool(field.get("humanCorrected")),
                "raw": str(value).strip(),
            }
        )
    return values


def _first_field(fields: list[dict[str, Any]], aliases: tuple[str, ...], *,
                 exclude_name_markers: tuple[str, ...] = ()) -> dict[str, Any] | None:
    for hit in _all_fields(fields, aliases):
        if hit["name"] and any(marker in hit["name"] for marker in exclude_name_markers):
            continue
        return hit
    return None


def _all_fields(fields: list[dict[str, Any]], aliases: tuple[str, ...]):
    alias_set = {alias.lower() for alias in aliases}
    for field in fields:
        code = field["code"]
        name = field["name"]
        if code in alias_set or name in alias_set or any(alias in name for alias in alias_set if len(alias) >= 3 and not alias.isascii()):
            yield field


def _split_scopes(value: str) -> list[str]:
    parts = [item.strip() for item in re.split(r"[,，;；、\n/|]", str(value or "")) if item.strip()]
    codes: list[str] = []
    for part in parts:
        for code in re.findall(r"\b(?:GC[1-3]|GCD|GB[1-2]|GD[1-2]|GA[1-2]|[A-Z]{1,2}[0-9ⅠⅡⅢ]{1,2}(?:-[0-9]+)?)\b", part.upper()):
            if code not in codes:
                codes.append(code)
        if not re.search(r"\b(?:GC[1-3]|GCD|GB[1-2]|GD[1-2]|GA[1-2])\b", part.upper()) and part not in codes and len(part) <= 40:
            codes.append(part)
    return codes


def _scope_codes_from_text(text: str) -> list[str]:
    found = re.findall(r"\b(GC[1-3]|GCD|GB[1-2]|GD[1-2]|GA[1-2])\b", text.upper())
    return list(dict.fromkeys(found))


def _locate_text(parse_result: dict[str, Any], needle: str) -> tuple[int | None, str, Any]:
    """返回 (页码, 引文, 该片段的 confidence)。找不到片段时 confidence 为 None。"""
    compact = re.sub(r"\s+", "", needle)
    for fragment in parse_result.get("fragments") or []:
        if not isinstance(fragment, dict):
            continue
        body = str(fragment.get("text") or fragment.get("fullText") or "")
        if compact and compact in re.sub(r"\s+", "", body):
            return fragment.get("pageNo"), needle.strip(), fragment.get("confidence")
    return None, needle.strip(), None


def _evidence(
    version_id: str, file_name: str, page_no: Any, bbox: Any, quoted: Any,
    *, confidence: Any = None, confidence_unavailable: bool = False,
    field_name: str | None = None, human_corrected: bool = False,
) -> dict[str, Any]:
    """一条可被 grounding 引用的证据。

    evidenceRefId 由位置与引文决定（同一处证据两次抽到得同一个 id），
    validate_evidence_grounding 靠它把 claimedFact 与 evidenceRef 对上。

    confidence 如实带出：MinerU 的 VLM 通道逐片不给分，适配层写 0.0 并标
    provider_confidence_unavailable——那是「没分」，不是「零分」。这里把标记一起带上，
    让下游能按 libs/field_confidence 的三态口径处理，而不是把 0.0 当低置信度一票否决。
    """
    quoted_text = str(quoted or "")[:200]
    normalized_page = int(page_no) if isinstance(page_no, (int, float)) and page_no else page_no
    evidence_id = "CERTEV-" + stable_payload_hash(
        {"v": version_id, "p": normalized_page, "b": bbox, "q": quoted_text}
    )[7:19].upper()
    score: float | None
    try:
        score = float(confidence) if confidence is not None else None
    except (TypeError, ValueError):
        score = None
    if confidence_unavailable:
        score = None
    if human_corrected:
        # 人核过的字段：值可信、有分，不再受「引擎不报置信度」影响。
        score, confidence_unavailable = 1.0, False
    return {
        "id": evidence_id,
        "fieldName": field_name,
        "humanCorrected": bool(human_corrected),
        "evidenceRefId": evidence_id,
        "documentVersionId": version_id,
        "fileName": file_name,
        "pageNo": normalized_page,
        "bbox": bbox,
        "quotedText": quoted_text,
        "confidence": score,
        "confidenceUnavailable": bool(confidence_unavailable),
    }


def _confidence_unavailable(parse_result: dict[str, Any]) -> bool:
    """适配层是否声明了「引擎不报置信度」（quality.reasons 里的 provider_confidence_unavailable）。"""
    quality = parse_result.get("quality") if isinstance(parse_result.get("quality"), dict) else {}
    return "provider_confidence_unavailable" in (quality.get("reasons") or [])


def _warnings(certificates: list[dict[str, Any]], considered: list[dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    if not considered:
        warnings.append("no_certificate_document_in_input")
    elif not certificates:
        warnings.append("certificate_document_present_but_fields_unextracted")
    for item in certificates:
        if item.get("holderFieldRejected"):
            warnings.append(f"holder_field_rejected:{item.get('certificateNo') or item.get('fileName')}")
        if not item.get("validUntil"):
            warnings.append(f"valid_until_missing:{item.get('certificateNo') or item.get('fileName')}")
        if not item.get("holder"):
            warnings.append(f"holder_missing:{item.get('certificateNo') or item.get('fileName')}")
    return warnings


def with_certificate_fact_builders(builders: dict[int, Any]) -> dict[int, Any]:
    """给证书类节点的 fact builder 套上证书事实（没有 builder 的节点直接用证书事实）。

    对话正式判定的分发表与 execution.load_context 要保持一致，这里是同一份逻辑的
    可复用形式：先跑节点自己的 builder，再把 certificateFacts / project / 旧命名空间补进去。
    """
    result = dict(builders)
    for node_id in CERTIFICATE_NODE_PROFILES:
        base_builder = builders.get(node_id)

        def build(state: dict[str, Any], review_run: dict[str, Any], *, _base=base_builder) -> dict[str, Any]:
            facts = _base(state, review_run) if _base else {}
            return merge_certificate_facts(state, review_run, facts)

        result[node_id] = build
    return result


CERTIFICATE_VERIFICATION_REQUIREMENT = (
    "certificateVerification is the deterministic result of certificate validity checks "
    "(validity period, holder, scope). Explain and cite it; never contradict or upgrade it: "
    "failed stays failed, evidence_insufficient stays insufficient. "
    "Write findings for inspectors in business language (服务端证照核验通过/未通过/证据不足); "
    "do not put field names or enum values such as certificateVerification, result or "
    "evidence_insufficient into title/description."
)


#: 证书类型代号 → 证书名。事实标签直接印代号，界面上就是「design_license TS1844171-2028」
#: （2026-09-13 线上巡检抓到）。
CERTIFICATE_TYPE_NAMES = {
    "design_license": "设计单位许可证",
    "installation_license": "安装单位许可证",
    "ndt_agency_approval": "无损检测机构核准证",
    "ndt_personnel_certificate": "无损检测人员资格证",
    "welder_certificate": "焊工资格证",
    "quality_certificate": "产品质量证明书",
    "type_test_report": "型式试验证书",
    "manufacturing_license": "制造许可证",
}


def _dedupe_claimed_facts(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """同一张证只留一条事实。

    节点 24 有两条链在产证书事实：r24 的焊工 builder 和这里的证书链。2026-09-13
    线上实测：合并之后界面上「焊工证 姜军」和「welder_certificate 511621198504208836」
    是同一张证的两条，监检看不出它们是一回事。按证号（没有就按取值）去重，
    先到的留下——r24 那条带中文标签和平台核验，排在前面。
    """
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        # 只按证号去重。按 value 去重会误伤：节点 1 的「图签设计单位」与「设计章单位」
        # 值本来就相同（就是要比它们一致），去掉一条 check_all_equal 就只剩两处可比。
        key = str(fact.get("certificateNo") or "").strip().upper()
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        output.append(fact)
    return output


def merge_certificate_facts(
    state: dict[str, Any], review_run: dict[str, Any], business_facts: Any
) -> dict[str, Any]:
    """证书类节点（1/2/3/24/38）：把证书事实并进业务事实；非证书节点原样返回。

    节点 24 已有焊工证 builder，这里只补 certificateFacts 与 project 期间；其余节点
    此前根本没有 fact builder，绑定的 check_date_covers 等工具拿到空事实恒为证据不足。
    """
    scoped = "documentScopeSnapshot" in review_run
    merged = deepcopy(business_facts) if scoped and isinstance(business_facts, dict) else business_facts
    merged = merged if isinstance(merged, dict) else {}
    node_id = int(review_run.get("nodeId") or 0)
    if not certificate_profile_for_node(node_id):
        return merged
    certificate_facts = build_certificate_facts(
        state,
        str(review_run.get("projectId") or ""),
        node_id,
        list(review_run.get("inputDocumentVersionIds") or []),
        review_run=review_run,
    )
    if node_id == 1:
        # 节点 1 要拿许可证持证单位和设计文件图签/设计章比一致性（AC-R01-01），
        # 另一侧的事实在这里补齐；它的证据也并进 judgment，让 grounding 能核。
        from libs.review_orchestrator.design_org_facts import build_design_org_facts

        design_org = build_design_org_facts(state, review_run)
        if design_org:
            certificate_facts.update(design_org)
            judgment = certificate_facts.setdefault("judgment", {"claimedFacts": [], "evidenceRefs": []})
            for index, (key, label) in enumerate((("titleBlockOrganization", "图签设计单位"), ("designSealOrganization", "设计章单位")), 1):
                value = design_org["designDocument"].get(key)
                source = design_org["designDocument"].get("sources", {}).get(key)
                if not value or not source:
                    continue
                evidence = source["evidence"]
                judgment["claimedFacts"].append(
                    {
                        "factId": f"design-org-{index}",
                        "label": label,
                        "value": value,
                        "documentVersionId": evidence.get("documentVersionId"),
                        # 没有字段可指的事实（设计章）按 factPath 确认；界面据此给按钮。
                        "factPath": source.get("factPath"),
                        "evidenceRefIds": [evidence["evidenceRefId"]],
                        "confidence": evidence.get("confidence"),
                        "confidenceUnavailable": bool(evidence.get("confidenceUnavailable")),
                        "conflicted": False,
                        # 界面「核对无误」按字段回写；印章没有 fieldName，这里就没有可核的条目。
                        "fields": [
                            {
                                "fieldName": evidence["fieldName"],
                                "documentVersionId": evidence.get("documentVersionId"),
                                "documentId": source["documentId"],
                                "quotedText": evidence.get("quotedText"),
                                "humanCorrected": bool(evidence.get("humanCorrected")),
                            }
                        ] if evidence.get("fieldName") else [],
                    }
                )
                if evidence["evidenceRefId"] not in {r["evidenceRefId"] for r in judgment["evidenceRefs"]}:
                    judgment["evidenceRefs"].append(evidence)
            for source in design_org["designDocument"].get("gradeSources") or []:
                evidence = source["evidence"]
                judgment["claimedFacts"].append({
                    "factId": f"design-grade-{evidence['documentVersionId']}",
                    "label": "设计文件管道级别", "value": source["value"],
                    "documentVersionId": evidence["documentVersionId"],
                    "factPath": "designDocument.pipelineGrades",
                    "evidenceRefIds": [evidence["evidenceRefId"]],
                    "confidence": evidence.get("confidence"),
                    "confidenceUnavailable": bool(evidence.get("confidenceUnavailable")),
                    "conflicted": False,
                    "fields": [{"fieldName": evidence["fieldName"],
                                "documentVersionId": evidence["documentVersionId"],
                                "documentId": source["documentId"],
                                "quotedText": evidence.get("quotedText"),
                                "humanCorrected": bool(evidence.get("humanCorrected"))}]
                    if evidence.get("fieldName") else [],
                })
                if evidence["evidenceRefId"] not in {r["evidenceRefId"] for r in judgment["evidenceRefs"]}:
                    judgment["evidenceRefs"].append(evidence)
    for key, value in certificate_facts.items():
        if key == "judgment":
            # 节点 24 的焊工 builder 已经产 judgment；证书事实要并进去，不能互相覆盖。
            existing = merged.get("judgment") if isinstance(merged.get("judgment"), dict) else {}
            merged["judgment"] = {
                "claimedFacts": _dedupe_claimed_facts(
                    [*(existing.get("claimedFacts") or []), *(value.get("claimedFacts") or [])]
                ),
                "evidenceRefs": [*(existing.get("evidenceRefs") or []), *(value.get("evidenceRefs") or [])],
                **{k: v for k, v in existing.items() if k not in {"claimedFacts", "evidenceRefs"}},
            }
            continue
        if scoped:
            merged[key] = {**merged[key], **value} if isinstance(value, dict) and isinstance(merged.get(key), dict) else value
        elif isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**value, **{k: v for k, v in merged[key].items() if v not in (None, [], {})}}
        else:
            merged.setdefault(key, value)
    return merged


def certificate_verification_from_tool_execution(tool_execution: dict[str, Any] | None) -> dict[str, Any] | None:
    """从规则引擎的原子结果里拎出 check_certificate_validity 的输出（没有就 None）。"""
    for atomic in (tool_execution or {}).get("atomicResults") or []:
        for output in atomic.get("toolResults") or []:
            if isinstance(output, dict) and output.get("toolName") == "check_certificate_validity":
                facts = output.get("facts") or {}
                return {
                    "atomicCheckId": atomic.get("atomicCheckId"),
                    "result": output.get("result"),
                    "ruleVersion": output.get("ruleVersion"),
                    "certificateType": facts.get("certificateType"),
                    "period": {"start": facts.get("periodStart"), "end": facts.get("periodEnd"), "referenceDate": facts.get("referenceDate")},
                    "expectedHolder": facts.get("expectedHolder"),
                    "requiredScopes": facts.get("requiredScopes"),
                    "certificates": facts.get("certificates") or [],
                    "warnings": output.get("warnings") or [],
                }
    return None




def certificate_evidence_links(verification: dict[str, Any] | None) -> list[dict[str, Any]]:
    """把证书核验结论里的证据位置登记成可引用的 evidenceLink（id 形如 EVL-CERT-…）。

    锚定守卫只认提示词里登记过的 evidenceLinkId；证书证据来自字段/正文定位，
    没有登记就引不到——模型正确引用了核验结论，finding 仍被整条丢弃（2026-09-03
    节点 1 实测）。
    """
    links: list[dict[str, Any]] = []
    for cert_index, cert in enumerate((verification or {}).get("certificates") or []):
        label = str(cert.get("certificateNo") or cert.get("label") or f"cert{cert_index + 1}")
        for ref_index, ref in enumerate(cert.get("evidenceRefs") or []):
            if not isinstance(ref, dict) or not ref.get("documentVersionId"):
                continue
            links.append(
                {
                    "id": f"EVL-CERT-{cert_index + 1}-{ref_index + 1}",
                    "objectType": "certificate",
                    "objectId": label,
                    "documentId": ref.get("documentId"),
                    "documentVersionId": ref.get("documentVersionId"),
                    "fileName": ref.get("fileName"),
                    "pageNo": ref.get("pageNo"),
                    "fieldName": "certificateVerification",
                    "quotedText": ref.get("quotedText"),
                    "bbox": ref.get("bbox"),
                    "confidence": 1.0,
                    # 公示平台登记记录没有页码与 bbox：带上来源与登记页地址，锚定守卫据此认它。
                    **{key: ref[key] for key in ("source", "sourceUrl") if ref.get(key)},
                }
            )
    return links


def certificate_claim_texts(verification: dict[str, Any] | None) -> list[str]:
    """核验结论里模型会原样引用的值（ISO 日期、编号、主体、范围），补进比对语料。"""
    texts: list[str] = []
    period = (verification or {}).get("period") or {}
    for value in (period.get("start"), period.get("end"), period.get("referenceDate")):
        texts.extend(_date_renderings(value))
    for cert in (verification or {}).get("certificates") or []:
        for key in ("certificateNo", "holder", "issuer", "label"):
            if cert.get(key):
                texts.append(str(cert[key]))
        for key in ("validFrom", "validUntil"):
            texts.extend(_date_renderings(cert.get(key)))
        texts.extend(str(item) for item in cert.get("scopes") or [] if item)
        for check_item in cert.get("checks") or []:
            for key in ("actual", "expected"):
                value = check_item.get(key)
                if value not in (None, "", [], {}):
                    texts.append(str(value))
                    texts.extend(_date_renderings(value))
        for ref in cert.get("evidenceRefs") or []:
            for key in ("documentVersionId", "documentId", "fileName", "quotedText"):
                if isinstance(ref, dict) and ref.get(key):
                    texts.append(str(ref[key]))
    return list(dict.fromkeys(item for item in texts if item))


def _date_renderings(value: Any) -> list[str]:
    """同一个日期模型可能写成 2028-01-17 / 2028年1月17日 / 2028年01月17日 / 2028.1.17，都算引用了它。"""
    parsed = parse_date(value)
    if not parsed:
        return [str(value)] if value else []
    y, m, d = parsed.year, parsed.month, parsed.day
    return [
        parsed.isoformat(),
        f"{y}年{m}月{d}日",
        f"{y}年{m:02d}月{d:02d}日",
        f"{y}.{m}.{d}",
        f"{y}.{m:02d}.{d:02d}",
        f"{y}/{m}/{d}",
        f"{y}-{m}-{d}",
        # 证书常只写到月，模型也会只引到月
        f"{y}年{m}月",
        f"{y}年{m:02d}月",
        f"{y}年{m:02d}",
        f"{y}-{m:02d}",
        f"{y}.{m:02d}",
    ]


def attach_certificate_evidence(context: dict[str, Any]) -> None:
    """把证书证据链与可引用文本挂进本次运行的上下文（提示词与守卫共用）。"""
    verification = context.get("certificateVerification")
    if not verification:
        return
    links = certificate_evidence_links(verification)
    # 把登记的 id 回写进核验结论里的证据项：模型照抄 evidenceLinkId 才能被守卫认下
    cursor = 0
    for cert in verification.get("certificates") or []:
        for ref in cert.get("evidenceRefs") or []:
            if isinstance(ref, dict) and ref.get("documentVersionId") and cursor < len(links):
                ref["evidenceLinkId"] = links[cursor]["id"]
                cursor += 1
    # 可重复调用：证据预算裁剪会整体重建 groundingInput（evidenceLinks / evidenceTextCorpus
    # 都从字段片段重算），裁剪后必须再挂一次，否则守卫又看不到证书证据。
    _extend_unique(context.setdefault("evidenceLinks", []), links, key="id")
    grounding_input = context.get("groundingInput") if isinstance(context.get("groundingInput"), dict) else None
    if grounding_input is not None:
        _extend_unique(grounding_input.setdefault("evidenceLinks", []), links, key="id")
        corpus = grounding_input.setdefault("evidenceTextCorpus", [])
        for text in certificate_claim_texts(verification):
            if text not in corpus:
                corpus.append(text)


def _extend_unique(target: list[dict[str, Any]], items: list[dict[str, Any]], *, key: str) -> None:
    seen = {str(row.get(key)) for row in target if isinstance(row, dict)}
    for item in items:
        if str(item.get(key)) not in seen:
            target.append(item)
            seen.add(str(item.get(key)))
