from __future__ import annotations

from copy import deepcopy
from typing import Any

from libs.business_rule_generation import (
    STANDARD_VERSION as GENERATED_STANDARD_RULES_VERSION,
    build_standard_knowledge_seed,
    list_standard_files,
    repo_root_from_backend,
)
from libs.business_pack import (
    DEFAULT_BUSINESS_PACK_ID,
    business_pack_fixtures,
    build_project_requirements,
    build_project_tree,
    business_pack_snapshot,
    default_business_pack,
    list_business_packs,
    load_business_pack,
    role_actions_map,
    role_default_node_map,
)
from libs.business_pack.clause_store import (
    CLAUSE_STATE_COLLECTIONS,
    bind_project_node_clause_packages,
    publish_standard_clause_release,
)
from libs.material_targeting import load_review_points_from_mapping_doc
from libs.material_review_assets import load_material_review_asset

PROJECT_ID = "P-2026-HDCP-001"
DEFAULT_BUSINESS_PACK = default_business_pack()
STANDARD_RULES_SOURCE_ID = "KS-STANDARD-RULES"
STANDARD_RULES_VERSION = GENERATED_STANDARD_RULES_VERSION

ROLE_ACTIONS = role_actions_map(DEFAULT_BUSINESS_PACK)
ROLE_NODE_MAP = role_default_node_map(DEFAULT_BUSINESS_PACK)
for pack_summary in list_business_packs():
    pack = load_business_pack(pack_summary["id"])
    ROLE_ACTIONS.update({key: value for key, value in role_actions_map(pack).items() if key not in ROLE_ACTIONS})
    ROLE_NODE_MAP.update({key: value for key, value in role_default_node_map(pack).items() if key not in ROLE_NODE_MAP})
ROLE_ACTIONS["ndt"] = list(
    dict.fromkeys([*ROLE_ACTIONS.get("ndt", []), "file:upload", "file:bind"])
)

WORKSPACE_ROOT = repo_root_from_backend()
RULES_STANDARDS_ROOT = WORKSPACE_ROOT / "rules" / "standards"
MATERIAL_MAPPING_DOC = WORKSPACE_ROOT / "docs" / "工程监检资料映射表.md"
STANDARD_RULE_FILES = list_standard_files(RULES_STANDARDS_ROOT, workspace_root=WORKSPACE_ROOT)
STANDARD_KNOWLEDGE_SEED = build_standard_knowledge_seed(STANDARD_RULE_FILES, DEFAULT_BUSINESS_PACK["ruleSets"])
MATERIAL_REVIEW_ASSET = load_material_review_asset()
DEFAULT_MATERIAL_REVIEW_POINTS = deepcopy(MATERIAL_REVIEW_ASSET.get("items") or [])
if not DEFAULT_MATERIAL_REVIEW_POINTS:
    DEFAULT_MATERIAL_REVIEW_POINTS = load_review_points_from_mapping_doc(
        MATERIAL_MAPPING_DOC,
        business_pack_id=DEFAULT_BUSINESS_PACK_ID,
    )

FDE_ROLES = ("fde",)
FDE_ROLE_LABELS = {"fde": "FDE"}

FDE_BASE_ACTIONS = [
    "fde:dashboard:view",
    "fde:ai-run:view-masked",
    "fde:feedback:view",
    "fde:evaluation:view",
    "fde:business-pack:view",
    "fde:release:view",
    "fde:ocr-quality:view",
    "fde:vector-quality:view",
    "fde:vector-quality:review",
    "fde:vector-quality:apply",
]

ROLE_ACTIONS.update(
    {
        "fde": [
            *FDE_BASE_ACTIONS,
            "fde:ai-run:replay",
            "fde:feedback:triage",
            "fde:evaluation:manage",
            "fde:evaluation:run",
            "fde:config:draft",
            "fde:ocr-annotation:manage",
            "fde:business-pack:validate",
            "fde:business-pack:install",
            "fde:capability-bundle:manage",
            "fde:release:submit",
            "fde:release:shadow",
            "fde:release:canary",
            "fde:release:rollback",
            "fde:incident:manage",
            "fde:security:manage",
            "fde:cost:manage",
        ],
    }
)
ROLE_NODE_MAP.update({role: DEFAULT_BUSINESS_PACK["nodeTemplates"][0]["nodeId"] for role in FDE_ROLES})


DEFAULT_NODE_NAME_BY_ID = {
    int(template["nodeId"]): str(template.get("name") or "").strip()
    for template in DEFAULT_BUSINESS_PACK["nodeTemplates"]
    if template.get("nodeId") is not None
}


def rule_name_from_node_ids(node_ids: list[int] | None, fallback: str = "") -> str:
    names: list[str] = []
    for node_id in node_ids or []:
        name = DEFAULT_NODE_NAME_BY_ID.get(int(node_id), "").strip()
        if name and name not in names:
            names.append(name)
    if not names:
        return fallback
    if len(names) == 1:
        return names[0]
    return f"{names[0]}等 {len(names)} 个节点"


def business_pack_project_fields(pack: dict[str, Any] | None = None) -> dict[str, Any]:
    source = pack or DEFAULT_BUSINESS_PACK
    return {
        "businessPackId": source["id"],
        "businessPackVersion": source["version"],
        "domainType": source["domainType"],
        "businessPackSnapshotHash": source["snapshotHash"],
        "businessPackSnapshot": business_pack_snapshot(source),
    }


def report_template_seed() -> list[dict[str, Any]]:
    templates: list[dict[str, Any]] = []
    for summary in list_business_packs():
        pack = load_business_pack(summary["id"])
        for template in pack.get("reportTemplates") or []:
            templates.append(
                {
                    **deepcopy(template),
                    "businessPackId": pack["id"],
                    "businessPackVersion": pack["version"],
                    "status": "production",
                    "createdAt": "2026-06-26 08:00:00",
                    "updatedAt": "2026-06-26 08:00:00",
                    "revision": 1,
                }
            )
    return templates


def build_tree(project_id: str = PROJECT_ID) -> list[dict[str, Any]]:
    project = next((item for item in PROJECTS if item.get("id") == project_id), None)
    pack = load_business_pack(project.get("businessPackId")) if project and project.get("businessPackId") else DEFAULT_BUSINESS_PACK
    return build_project_tree(project_id, pack)


def pack_for_project_id(project_id: str) -> dict[str, Any]:
    project = next((item for item in PROJECTS if item.get("id") == project_id), None)
    if project and project.get("businessPackId"):
        return load_business_pack(project["businessPackId"])
    return DEFAULT_BUSINESS_PACK


def fixture_projects() -> list[dict[str, Any]]:
    existing_ids = {project["id"] for project in PROJECTS}
    projects: list[dict[str, Any]] = []
    for pack_summary in list_business_packs():
        pack = load_business_pack(pack_summary["id"])
        fixtures = business_pack_fixtures(pack)
        for fixture in fixtures["projects"]:
            project_id = fixture.get("id") or fixture.get("code")
            if not project_id or project_id in existing_ids:
                continue
            project = {
                "id": project_id,
                "code": fixture.get("code") or project_id,
                "name": fixture.get("name") or f"{pack['name']}示例项目",
                "type": fixture.get("type") or pack["name"],
                "region": fixture.get("region") or "默认区域",
                "ownerOrgName": fixture.get("ownerOrgName") or "观察单位",
                "contractorOrgName": fixture.get("contractorOrgName") or "提交单位",
                "ndtOrgName": fixture.get("ndtOrgName") or "专项资料单位",
                "inspectionOrgName": fixture.get("inspectionOrgName") or "审核机构",
                "status": fixture.get("status") or "资料提交中",
                "todoCount": int(fixture.get("todoCount") or 0),
                "messageCount": int(fixture.get("messageCount") or 0),
                "currentNodeId": int(fixture.get("currentNodeId") or pack["nodeTemplates"][0]["nodeId"]),
                "updatedAt": fixture.get("updatedAt") or "2026-06-26 09:30:00",
                "actions": role_actions_map(pack).get("admin", ["project:view"]),
                "revision": 1,
            }
            project.update(business_pack_project_fields(pack))
            projects.append(project)
            existing_ids.add(project_id)
    return projects


PROJECTS = [
    {
        "id": PROJECT_ID,
        "code": PROJECT_ID,
        "name": "华东成品油管道改造工程",
        "type": "工业管道改造",
        "region": "华东",
        "ownerOrgName": "华东管网建设公司",
        "contractorOrgName": "中石化安装有限公司",
        "ndtOrgName": "华测检测有限公司",
        "inspectionOrgName": "省特检院一部",
        "status": "监检审查中",
        "todoCount": 12,
        "messageCount": 7,
        "currentNodeId": 24,
        "updatedAt": "2026-06-26 09:30:00",
        "actions": ROLE_ACTIONS["inspection"],
        "revision": 1,
    },
    {
        "id": "P-2026-GDLNG-002",
        "code": "P-2026-GDLNG-002",
        "name": "广东 LNG 支线改造工程",
        "type": "燃气管道扩建",
        "region": "华南",
        "ownerOrgName": "南方能源管网公司",
        "contractorOrgName": "粤海安装工程有限公司",
        "ndtOrgName": "粤检无损检测",
        "inspectionOrgName": "省特检院三部",
        "status": "退回补正中",
        "todoCount": 9,
        "messageCount": 4,
        "currentNodeId": 16,
        "updatedAt": "2026-06-26 11:10:00",
        "actions": ["project:view", "rectification:submit"],
        "revision": 1,
    },
    {
        "id": "P-2025-CQARCH-007",
        "code": "P-2025-CQARCH-007",
        "name": "重庆老厂酸碱管线整改工程",
        "type": "工业管道整改",
        "region": "西南",
        "ownerOrgName": "渝江化工资产公司",
        "contractorOrgName": "重庆工业设备安装公司",
        "ndtOrgName": "西南无损检测",
        "inspectionOrgName": "市特检院二部",
        "status": "已归档",
        "todoCount": 0,
        "messageCount": 2,
        "currentNodeId": 69,
        "updatedAt": "2026-06-18 15:40:00",
        "actions": ["project:view", "archive:view", "archive:download"],
        "revision": 1,
    },
]

PROJECTS.extend(fixture_projects())

for project in PROJECTS:
    pack = load_business_pack(project.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID)
    project.update(business_pack_project_fields(pack))

REQUIREMENTS = build_project_requirements(DEFAULT_BUSINESS_PACK, project_id=PROJECT_ID)

DOCUMENTS = [
    {
        "id": "DOC-20260625-001",
        "projectId": PROJECT_ID,
        "fileName": "焊工资格证-王建国.pdf",
        "fileType": "pdf",
        "sourceOrgName": "中石化安装有限公司",
        "uploaderName": "李工",
        "currentVersionId": "DV-20260625-001-V2",
        "fileStatus": "已上传",
        "currentOcrStatus": "已识别",
        "updatedAt": "2026-06-25 10:30:00",
        "actions": ["file:view", "file:bind", "file:preview", "file:download"],
    },
    {
        "id": "DOC-20260625-002",
        "projectId": PROJECT_ID,
        "fileName": "焊工名册.xlsx",
        "fileType": "xlsx",
        "sourceOrgName": "中石化安装有限公司",
        "uploaderName": "李工",
        "currentVersionId": "DV-20260625-002-V1",
        "fileStatus": "已上传",
        "currentOcrStatus": "已识别",
        "updatedAt": "2026-06-25 10:40:00",
        "actions": ["file:view", "file:bind", "file:preview", "file:download"],
    },
    {
        "id": "DOC-20260625-003",
        "projectId": PROJECT_ID,
        "fileName": "钢管质量证明书.pdf",
        "fileType": "pdf",
        "sourceOrgName": "中石化安装有限公司",
        "uploaderName": "李工",
        "currentVersionId": "DV-20260625-003-V2",
        "fileStatus": "已上传",
        "currentOcrStatus": "人工修正",
        "updatedAt": "2026-06-25 11:20:00",
        "actions": ["file:view", "file:bind", "file:preview", "file:download"],
    },
    {
        "id": "DOC-20260625-004",
        "projectId": PROJECT_ID,
        "fileName": "RT检测报告R2.pdf",
        "fileType": "pdf",
        "sourceOrgName": "华测检测有限公司",
        "uploaderName": "王工",
        "currentVersionId": "DV-20260625-004-V1",
        "fileStatus": "已上传",
        "currentOcrStatus": "识别中",
        "updatedAt": "2026-06-25 14:10:00",
        "actions": ["file:view", "file:bind", "file:preview", "file:download"],
    },
    {
        "id": "DOC-20260625-005",
        "projectId": PROJECT_ID,
        "fileName": "UT检测报告U1.pdf",
        "fileType": "pdf",
        "sourceOrgName": "华测检测有限公司",
        "uploaderName": "王工",
        "currentVersionId": "DV-20260625-005-V1",
        "fileStatus": "已上传",
        "currentOcrStatus": "已识别",
        "updatedAt": "2026-06-25 15:20:00",
        "actions": ["file:view", "file:bind", "file:preview", "file:download"],
    },
]


def fixture_documents() -> list[dict[str, Any]]:
    existing_ids = {document["id"] for document in DOCUMENTS}
    documents: list[dict[str, Any]] = []
    projects_by_id = {project["id"]: project for project in PROJECTS}
    for pack_summary in list_business_packs():
        pack = load_business_pack(pack_summary["id"])
        for fixture in business_pack_fixtures(pack)["documents"]:
            document_id = fixture.get("id")
            if not document_id or document_id in existing_ids:
                continue
            project_id = fixture.get("projectId")
            project = projects_by_id.get(project_id or "")
            version_seed = document_id.removeprefix("DOC-")
            documents.append(
                {
                    "id": document_id,
                    "projectId": project_id,
                    "businessPackId": pack["id"],
                    "materialTypeCode": fixture.get("materialTypeCode") or "generic_review_material",
                    "fileName": fixture.get("fileName") or f"{document_id}.pdf",
                    "fileType": fixture.get("fileType") or str(fixture.get("fileName") or "file.pdf").rsplit(".", 1)[-1],
                    "sourceOrgName": fixture.get("sourceOrgName") or (project or {}).get("contractorOrgName") or "提交单位",
                    "uploaderName": fixture.get("uploaderName") or "系统样例",
                    "currentVersionId": fixture.get("currentVersionId") or f"DV-{version_seed}-V1",
                    "fileStatus": fixture.get("fileStatus") or "已上传",
                    "currentOcrStatus": fixture.get("currentOcrStatus") or "已识别",
                    "updatedAt": fixture.get("updatedAt") or "2026-06-26 09:30:00",
                    "actions": fixture.get("actions") or ["file:view", "file:bind", "file:preview", "file:download"],
                }
            )
            existing_ids.add(document_id)
    return documents


DOCUMENTS.extend(fixture_documents())

for document in DOCUMENTS:
    project_pack = pack_for_project_id(document["projectId"])
    document.setdefault("businessPackId", project_pack["id"])
    if document.get("materialTypeCode"):
        continue
    if "焊工" in document["fileName"]:
        document["materialTypeCode"] = "welder_certificate"
    elif "质量证明" in document["fileName"]:
        document["materialTypeCode"] = "quality_certificate"
    elif "检测报告" in document["fileName"]:
        document["materialTypeCode"] = "ndt_report"
    else:
        document["materialTypeCode"] = "generic_review_material"

VERSIONS = [
    {
        "id": doc["currentVersionId"],
        "documentId": doc["id"],
        "versionNo": "V2" if doc["currentVersionId"].endswith("V2") else "V1",
        "hash": f"mock-sha256-{doc['id']}",
        "fileSize": 245760,
        "storageKey": f"documents/{doc['projectId']}/{doc['currentVersionId']}",
        "ocrStatus": doc["currentOcrStatus"],
        "sliceStatus": "切片中" if doc["currentOcrStatus"] == "识别中" else "已切片",
        "vectorStatus": "向量化中" if doc["currentOcrStatus"] == "识别中" else "已向量化",
        "uploaderName": doc["uploaderName"],
        "uploadTime": doc["updatedAt"],
        "isCurrent": True,
    }
    for doc in DOCUMENTS
]

BINDINGS = [
    {
        "id": "BIND-24-001",
        "projectId": PROJECT_ID,
        "nodeId": 24,
        "requirementId": "REQ-24-01",
        "requirementName": "焊工资格证",
        "documentId": "DOC-20260625-001",
        "documentVersionId": "DV-20260625-001-V2",
        "fileName": "焊工资格证-王建国.pdf",
        "versionNo": "V2",
        "usage": "原始提交",
        "sourceOrgName": "中石化安装有限公司",
        "bindingStatus": "已提交",
        "boundByName": "李工",
        "boundAt": "2026-06-25 10:45:00",
        "actions": ["review:save", "review:return-correction"],
    },
    {
        "id": "BIND-24-002",
        "projectId": PROJECT_ID,
        "nodeId": 24,
        "requirementId": "REQ-24-02",
        "requirementName": "焊工名册",
        "documentId": "DOC-20260625-002",
        "documentVersionId": "DV-20260625-002-V1",
        "fileName": "焊工名册.xlsx",
        "versionNo": "V1",
        "usage": "原始提交",
        "sourceOrgName": "中石化安装有限公司",
        "bindingStatus": "草稿挂载",
        "boundByName": "李工",
        "boundAt": "2026-06-25 10:50:00",
        "actions": ["submission:submit", "submission:withdraw"],
    },
    {
        "id": "BIND-16-001",
        "projectId": PROJECT_ID,
        "nodeId": 16,
        "requirementId": "REQ-16-01",
        "requirementName": "产品质量证明书",
        "documentId": "DOC-20260625-003",
        "documentVersionId": "DV-20260625-003-V2",
        "fileName": "钢管质量证明书.pdf",
        "versionNo": "V2",
        "usage": "补正附件",
        "sourceOrgName": "中石化安装有限公司",
        "bindingStatus": "需补正",
        "boundByName": "李工",
        "boundAt": "2026-06-25 11:30:00",
        "actions": ["rectification:submit", "submission:submit", "submission:withdraw"],
    },
    {
        "id": "BIND-40-001",
        "projectId": PROJECT_ID,
        "nodeId": 40,
        "requirementId": "REQ-40-01",
        "requirementName": "无损检测报告",
        "documentId": "DOC-20260625-004",
        "documentVersionId": "DV-20260625-004-V1",
        "fileName": "RT检测报告R2.pdf",
        "versionNo": "V1",
        "usage": "检测报告",
        "sourceOrgName": "华测检测有限公司",
        "bindingStatus": "已提交",
        "boundByName": "王工",
        "boundAt": "2026-06-25 14:30:00",
        "actions": ["ndt:submit"],
    },
]


def fixture_bindings() -> list[dict[str, Any]]:
    existing_ids = {binding["id"] for binding in BINDINGS}
    documents_by_id = {document["id"]: document for document in DOCUMENTS}
    requirements_by_key = {
        (requirement.get("projectId"), requirement["id"]): requirement
        for project in PROJECTS
        for requirement in build_project_requirements(pack_for_project_id(project["id"]), project_id=project["id"])
    }
    bindings: list[dict[str, Any]] = []
    for pack_summary in list_business_packs():
        pack = load_business_pack(pack_summary["id"])
        for fixture in business_pack_fixtures(pack)["bindings"]:
            binding_id = fixture.get("id")
            if not binding_id or binding_id in existing_ids:
                continue
            document = documents_by_id.get(fixture.get("documentId"))
            requirement = requirements_by_key.get((fixture.get("projectId"), fixture.get("requirementId"))) or {}
            bindings.append(
                {
                    "id": binding_id,
                    "projectId": fixture.get("projectId"),
                    "nodeId": int(fixture.get("nodeId") or 1),
                    "requirementId": fixture.get("requirementId"),
                    "requirementName": fixture.get("requirementName") or requirement.get("name"),
                    "documentId": fixture.get("documentId"),
                    "documentVersionId": fixture.get("documentVersionId") or (document or {}).get("currentVersionId"),
                    "fileName": fixture.get("fileName") or (document or {}).get("fileName") or "fixture.pdf",
                    "versionNo": fixture.get("versionNo") or "V1",
                    "usage": fixture.get("usage") or "原始提交",
                    "sourceOrgName": fixture.get("sourceOrgName") or (document or {}).get("sourceOrgName") or "提交单位",
                    "bindingStatus": fixture.get("bindingStatus") or "已提交",
                    "boundByName": fixture.get("boundByName") or "系统样例",
                    "boundAt": fixture.get("boundAt") or "2026-06-26 09:30:00",
                    "actions": fixture.get("actions") or ["review:save", "review:return-correction"],
                }
            )
            existing_ids.add(binding_id)
    return bindings


BINDINGS.extend(fixture_bindings())

EVIDENCE_LINKS = [
    {
        "id": "EV-24-001",
        "objectType": "documentVersion",
        "objectId": "DV-20260625-001-V2",
        "documentId": "DOC-20260625-001",
        "documentVersionId": "DV-20260625-001-V2",
        "fileName": "焊工资格证-王建国.pdf",
        "pageNo": 1,
        "fieldName": "证书编号",
        "quotedText": "TS6J-2024-03158",
        "confidence": 0.96,
    },
    {
        "id": "EV-24-002",
        "objectType": "knowledgeClause",
        "objectId": "TSG-Z6002-3.2",
        "quotedText": "焊工持证项目应覆盖实际焊接方法。",
        "confidence": 0.92,
    },
    {
        "id": "EV-16-001",
        "objectType": "extractedField",
        "objectId": "FIELD-16-001",
        "documentId": "DOC-20260625-003",
        "documentVersionId": "DV-20260625-003-V2",
        "fileName": "钢管质量证明书.pdf",
        "pageNo": 1,
        "fieldName": "炉批号",
        "quotedText": "H240315A07",
        "confidence": 0.66,
    },
]


def fixture_evidence_links() -> list[dict[str, Any]]:
    existing_ids = {link["id"] for link in EVIDENCE_LINKS}
    version_by_id = {version["id"]: version for version in VERSIONS}
    document_by_id = {document["id"]: document for document in DOCUMENTS}
    links: list[dict[str, Any]] = []
    for pack_summary in list_business_packs():
        pack = load_business_pack(pack_summary["id"])
        for fixture in business_pack_fixtures(pack)["evidenceLinks"]:
            link_id = fixture.get("id")
            if not link_id or link_id in existing_ids:
                continue
            object_id = fixture.get("objectId")
            version = version_by_id.get(object_id or "")
            document = document_by_id.get((version or {}).get("documentId"))
            links.append(
                {
                    "id": link_id,
                    "projectId": fixture.get("projectId"),
                    "objectType": fixture.get("objectType") or "documentVersion",
                    "objectId": object_id,
                    "documentId": fixture.get("documentId") or (document or {}).get("id"),
                    "documentVersionId": fixture.get("documentVersionId") or object_id,
                    "fileName": fixture.get("fileName") or (document or {}).get("fileName"),
                    "pageNo": int(fixture.get("pageNo") or 1),
                    "fieldName": fixture.get("fieldName") or "关键字段",
                    "quotedText": fixture.get("quotedText") or "业务包样例证据",
                    "confidence": float(fixture.get("confidence") or 0.86),
                }
            )
            existing_ids.add(link_id)
    return links


EVIDENCE_LINKS.extend(fixture_evidence_links())

EXTRACTED_FIELDS = [
    {
        "id": "FIELD-16-001",
        "documentVersionId": "DV-20260625-003-V2",
        "fieldName": "炉批号",
        "fieldValue": "H240315A07",
        "pageNo": 1,
        "confidence": 0.66,
        "extractionMethod": "PaddleOCR+rule",
        "reviewStatus": "低置信度",
        "evidenceLinkId": "EV-16-001",
    },
    {
        "id": "FIELD-24-001",
        "documentVersionId": "DV-20260625-001-V2",
        "fieldName": "证书编号",
        "fieldValue": "TS6J-2024-03158",
        "pageNo": 1,
        "confidence": 0.96,
        "extractionMethod": "PaddleOCR+seal",
        "reviewStatus": "已确认",
        "evidenceLinkId": "EV-24-001",
    },
]

AI_RUNS = [
    {
        "id": "AIRUN-24-20260625-01",
        "projectId": PROJECT_ID,
        "nodeId": 24,
        "subject": "焊工资格证及持证合格项目",
        "model": "review-chat",
        "promptVersion": "24-焊工资格-v1.5",
        "ruleVersion": "Welder-Qualification-B-v2.1",
        "inputDocumentVersionIds": ["DV-20260625-001-V2", "DV-20260625-002-V1"],
        "status": "完成",
        "startedAt": "2026-06-25 15:08:00",
        "finishedAt": "2026-06-25 15:10:00",
        "steps": [
            {
                "id": "STEP-24-001",
                "title": "证书字段核验",
                "inputSummary": "证书编号；姓名、有效期、持证项目未形成 OCR 证据",
                "action": "OCR 字段与规则库比对",
                "conclusion": "待人工确认",
                "evidenceLinkIds": ["EV-24-001"],
            }
        ],
        "suggestion": {
            "id": "AIS-24-20260625-01",
            "result": "需人工确认",
            "opinionDraft": "仅识别到证书编号 TS6J-2024-03158；未识别到姓名、有效期、持证项目等支撑字段，不能判断证书与焊接作业要求是否匹配，需人工核对原件和外部查询截图。",
            "risks": ["姓名、有效期、持证项目缺少 OCR 证据", "外部查询截图来源需确认"],
            "rectificationSuggestion": "补充或重新识别姓名、有效期、持证项目，并补充资格网站查询截图来源说明。",
            "confidence": 0.5,
            "manualConfirmItems": ["姓名", "有效期", "持证项目", "资格网站查询截图来源"],
        },
        "evidenceLinks": EVIDENCE_LINKS[:2],
    }
]

for run in AI_RUNS:
    run["businessPackId"] = DEFAULT_BUSINESS_PACK_ID
    run["businessPackVersion"] = DEFAULT_BUSINESS_PACK["version"]
    run["businessPackSnapshotHash"] = DEFAULT_BUSINESS_PACK["snapshotHash"]
    run["agentId"] = "compliance_review_agent"
    run["agentVersion"] = "1.0.0"
    run["llmConversationId"] = "chatcmpl-aicheck-demo-24-001"
    run["promptAudit"] = {
        "promptVersion": run["promptVersion"],
        "promptTemplateId": "PTPL-review-202606",
        "promptTemplateName": "工程监检审查 Prompt 模板",
        "promptTemplateVersion": "2026.06",
        "messagesHash": "sha256:prompt-demo-node24",
        "systemPrompt": (
            "You are 资料合规复核员 for business pack engineering_inspection_v1 version "
            f"{DEFAULT_BUSINESS_PACK['version']}. Return evidence-backed review suggestions only. "
            "Do not approve final business state."
        ),
        "userPrompt": (
            "{\"businessPack\":{\"id\":\"engineering_inspection_v1\",\"name\":\"工业管道\"},"
            "\"node\":{\"id\":24,\"name\":\"焊工资格证及持证合格项目\"},"
            "\"rule\":{\"id\":\"RULE-ENG-INSP-R24\",\"inspectionItem\":\"焊工资格证及持证合格项目 (B类)\"},"
            "\"ocrFields\":[{\"id\":\"FIELD-24-001\",\"fieldName\":\"证书编号\",\"fieldValue\":\"TS6J-2024-03158\"}]}\n\n"
            "{\"task\":\"Generate ReviewFindingDraftList JSON only.\",\"groundingStatus\":\"insufficient_evidence\","
            "\"requirements\":[\"Do not infer names, dates, validity or project coverage that are not present in OCR evidence.\"],"
            "\"evidenceLinkIds\":[\"EV-24-001\",\"EV-24-002\"]}"
        ),
        "plannerPrompt": "Use the fixed AIcheck review graph plan and keep final business decisions under human confirmation.",
        "criticPrompt": "Check evidence, rule, and kb references before returning review drafts.",
        "payloadPolicy": "full_prompt_stored_for_audit",
    }
    run["llmMetadata"] = {
        "llmExecution": "litellm",
        "llmCalled": True,
        "conversationId": run["llmConversationId"],
        "modelAlias": run["model"],
        "promptVersion": run["promptVersion"],
        "promptTemplateId": "PTPL-review-202606",
        "promptHash": "sha256:prompt-demo-node24",
        "responseHash": "sha256:llm-output-demo",
        "usage": {"prompt_tokens": 1620, "completion_tokens": 210, "total_tokens": 1830},
        "groundingStatus": "insufficient_evidence",
        "unsupportedClaims": [],
        "groundingInputSummary": {"fieldCount": 1, "evidenceLinkCount": 2, "missingBusinessFacts": ["姓名", "有效期", "持证项目"]},
        "reasoningProcess": "公开推理摘要：仅读取到证书编号字段；姓名、有效期、持证项目未形成 OCR 证据，因此只能输出待人工确认。",
        "resultText": run["suggestion"]["opinionDraft"],
    }
    run["reasoningProcess"] = run["llmMetadata"]["reasoningProcess"]
    run["llmResultText"] = run["llmMetadata"]["resultText"]

REVIEW_OPINIONS = [
    {
        "id": "OPN-24-001",
        "projectId": PROJECT_ID,
        "nodeId": 24,
        "result": "满足要求",
        "opinion": "焊工资格证书真实有效，持证项目和项目焊接作业要求匹配。",
        "basis": "TSG Z6002",
        "riskLevel": "低",
        "closeStatus": "未关闭",
        "evidenceLinkIds": ["EV-24-001", "EV-24-002"],
        "reviewerName": "张工",
        "createdAt": "2026-06-26 09:12:00",
    }
]

for opinion in REVIEW_OPINIONS:
    opinion["findingType"] = "rule_passed"
    opinion["ruleRefs"] = [{"ruleSetId": "RULE-WELDER-202606", "ruleCode": "welder-qualification"}]
    opinion["kbRefs"] = [{"kbDocId": STANDARD_RULES_SOURCE_ID, "clause": opinion.get("basis")}]

def fixture_review_findings() -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for pack_summary in list_business_packs():
        pack = load_business_pack(pack_summary["id"])
        for fixture in business_pack_fixtures(pack)["reviewFindings"]:
            findings.append(
                {
                    "id": fixture.get("id") or f"FND-{pack['id']}",
                    "projectId": fixture.get("projectId"),
                    "nodeId": int(fixture.get("nodeId") or pack["nodeTemplates"][0]["nodeId"]),
                    "businessPackId": pack["id"],
                    "businessPackVersion": pack["version"],
                    "businessPackSnapshotHash": pack["snapshotHash"],
                    "agentId": (default_agent := next(iter(pack.get("agentSops") or []), {})).get("id"),
                    "agentVersion": default_agent.get("version"),
                    "findingType": fixture.get("findingType") or "manual_review",
                    "severity": fixture.get("severity") or "medium",
                    "title": fixture.get("title") or "审查发现",
                    "description": fixture.get("description") or fixture.get("title") or "请人工确认该发现。",
                    "evidenceLinkIds": fixture.get("evidenceLinkIds") or [],
                    "ruleRefs": fixture.get("ruleRefs") or [],
                    "kbRefs": fixture.get("kbRefs") or [],
                    "confidence": float(fixture.get("confidence") or 0.82),
                    "suggestedAction": fixture.get("suggestedAction") or "human_confirm",
                    "status": fixture.get("status") or "draft",
                    "source": fixture.get("source") or "ai",
                    "humanStatus": fixture.get("humanStatus") or "pending_human_review",
                    "createdAt": fixture.get("createdAt") or "2026-06-26 09:30:00",
                    "revision": 1,
                }
            )
    return findings


REVIEW_FINDINGS: list[dict[str, Any]] = fixture_review_findings()
AI_FEEDBACK: list[dict[str, Any]] = [
    {
        "id": "AIFB-24-001",
        "aiRunId": "AIRUN-24-20260625-01",
        "projectId": PROJECT_ID,
        "nodeId": 24,
        "agentId": "compliance_review_agent",
        "agentVersion": "1.0.0",
        "businessPackId": DEFAULT_BUSINESS_PACK_ID,
        "businessPackVersion": DEFAULT_BUSINESS_PACK["version"],
        "feedbackType": "edited",
        "accepted": True,
        "comment": "AI 结论方向正确，人工补充外部查询截图来源说明。",
        "correctedOutput": {"manualConfirmItems": ["资格网站查询截图来源"]},
        "shouldEnterEvaluationSet": True,
        "status": "created",
        "rootCause": "prompt_error",
        "createdAt": "2026-06-26 10:10:00",
    }
]

ACCESS_GRANTS: list[dict[str, Any]] = []
AI_TRACE_STEPS = [
    {
        "id": "TRACE-AIRUN-24-001-01",
        "aiRunId": "AIRUN-24-20260625-01",
        "traceId": "TRACE-AIRUN-24-20260625-01",
        "sequence": 1,
        "stepType": "ocr_context",
        "name": "读取 OCR 和字段抽取结果",
        "status": "completed",
        "latencyMs": 420,
        "inputHash": "sha256:ocr-input-demo",
        "outputHash": "sha256:ocr-output-demo",
        "createdAt": "2026-06-25 09:01:00",
    },
    {
        "id": "TRACE-AIRUN-24-001-02",
        "aiRunId": "AIRUN-24-20260625-01",
        "traceId": "TRACE-AIRUN-24-20260625-01",
        "sequence": 2,
        "stepType": "rule_engine",
        "name": "执行资料规则和节点状态校验",
        "status": "completed",
        "latencyMs": 180,
        "inputHash": "sha256:rule-input-demo",
        "outputHash": "sha256:rule-output-demo",
        "createdAt": "2026-06-25 09:01:01",
    },
    {
        "id": "TRACE-AIRUN-24-001-03",
        "aiRunId": "AIRUN-24-20260625-01",
        "traceId": "TRACE-AIRUN-24-20260625-01",
        "sequence": 3,
        "stepType": "llm_review",
        "name": "生成证据化审查建议",
        "status": "completed",
        "latencyMs": 8700,
        "inputHash": "sha256:llm-input-demo",
        "outputHash": "sha256:llm-output-demo",
        "conversationId": "chatcmpl-aicheck-demo-24-001",
        "promptHash": "sha256:prompt-demo-node24",
        "responseHash": "sha256:llm-output-demo",
        "reasoningProcess": "公开推理摘要：仅读取到证书编号字段；姓名、有效期、持证项目未形成 OCR 证据，因此只能输出待人工确认。",
        "resultText": "仅识别到证书编号 TS6J-2024-03158；未识别到姓名、有效期、持证项目等支撑字段，不能判断证书与焊接作业要求是否匹配，需人工核对原件和外部查询截图。",
        "createdAt": "2026-06-25 09:01:10",
    },
]
AI_RUN_REPLAYS: list[dict[str, Any]] = []
FEEDBACK_TRIAGE = [
    {
        "id": "FBT-24-001",
        "feedbackId": "AIFB-24-001",
        "status": "triaged",
        "rootCause": "prompt_error",
        "dataSensitivity": "masked",
        "canUseForEval": True,
        "canUseForTraining": False,
        "createdAt": "2026-06-26 10:20:00",
    }
]

EVALUATION_SETS = [
    {
        "id": "ESET-GOLDEN-ENGINEERING-001",
        "name": "工程监检金标评估集",
        "setType": "golden",
        "businessPackId": DEFAULT_BUSINESS_PACK_ID,
        "caseCount": 1,
        "riskLevel": "high",
        "status": "active",
        "createdAt": "2026-06-26 10:30:00",
    },
    {
        "id": "ESET-RISK-PROMPT-INJECTION-001",
        "name": "Prompt 注入与错误依据风险集",
        "setType": "risk",
        "businessPackId": DEFAULT_BUSINESS_PACK_ID,
        "caseCount": 1,
        "riskLevel": "high",
        "status": "active",
        "createdAt": "2026-06-26 10:35:00",
    },
]

EVALUATION_CASES = [
    {
        "id": "ECASE-24-001",
        "evaluationSetId": "ESET-GOLDEN-ENGINEERING-001",
        "businessPackId": DEFAULT_BUSINESS_PACK_ID,
        "nodeId": 24,
        "materialTypeCode": "welder_certificate",
        "inputDocumentVersionIds": ["DV-20260625-001-V2"],
        "expectedFindings": ["资格网站查询截图来源需人工确认"],
        "expectedEvidenceLinkIds": ["EV-24-001"],
        "retrievalQuery": "焊工资格证有效期如何校验？",
        "expectedClauseIds": ["TSG-Z6002-3.2"],
        "expectedRoute": "hybrid_review_basis_search",
        "riskLevel": "medium",
        "source": "human_feedback",
        "dataSensitivity": "masked",
        "canUseForTraining": False,
        "canUseForEval": True,
    }
]

EVALUATION_RUNS = [
    {
        "id": "ERUN-20260626-001",
        "evaluationSetId": "ESET-GOLDEN-ENGINEERING-001",
        "capabilityBundleId": "BUNDLE-REVIEW-202606",
        "status": "completed",
        "startedAt": "2026-06-26 11:00:00",
        "finishedAt": "2026-06-26 11:02:00",
        "metrics": {
            "humanAcceptanceRate": 0.86,
            "evidenceHitRate": 0.92,
            "hallucinationRate": 0.0,
            "highRiskMissRate": 0.0,
            "averageLatencyMs": 9300,
        },
    }
]

EVALUATION_METRICS = [
    {
        "id": "EMET-20260626-001",
        "evaluationRunId": "ERUN-20260626-001",
        "metric": "evidence_hit_rate",
        "value": 0.92,
        "threshold": 0.9,
        "passed": True,
    }
]

EVALUATION_CASE_RESULTS: list[dict[str, Any]] = []

EVALUATION_REPORTS = [
    {
        "id": "EREPORT-20260626-001",
        "evaluationRunId": "ERUN-20260626-001",
        "capabilityBundleId": "BUNDLE-REVIEW-202606",
        "businessPackId": DEFAULT_BUSINESS_PACK_ID,
        "status": "passed",
        "summary": "Golden Set 和 Risk Set 通过，证据命中率、幻觉率和高风险漏检率满足上线门槛。",
        "metrics": {
            "humanAcceptanceRate": 0.86,
            "evidenceHitRate": 0.92,
            "hallucinationRate": 0.0,
            "highRiskMissRate": 0.0,
            "schemaPassRate": 1.0,
            "retrievalRecall": 0.94,
            "wrongReferenceRate": 0.0,
        },
        "caseSummary": {
            "casePassRate": 1.0,
            "findingRecall": 0.92,
            "evidenceCoverage": 0.95,
            "retrievalRecall": 0.94,
            "wrongReferenceRate": 0.0,
        },
        "gateResults": [
            {"gate": "golden_set", "passed": True},
            {"gate": "risk_set", "passed": True},
            {"gate": "rollback_plan", "passed": True},
        ],
        "createdAt": "2026-06-26 11:03:00",
    }
]

AGENT_VERSIONS = [
    {
        "id": "AGENT-compliance_review_agent-1.0.0",
        "agentId": "compliance_review_agent",
        "name": "资料合规复核员",
        "version": "1.0.0",
        "owner": "ai_quality_team",
        "riskLevel": "high",
        "status": "production",
        "allowedTools": ["get_project_context", "get_ocr_result", "search_knowledge_base", "run_rule_engine"],
        "forbiddenActions": ["approve_review", "issue_correction", "archive_project", "delete_file", "change_project_status"],
        "promotionGate": {"humanAcceptanceRate": ">=0.85", "hallucinationRate": "<=0.01", "evidenceHitRate": ">=0.90"},
    }
]

PROMPT_VERSIONS = [
    {
        "id": "PROMPT-review-202606",
        "promptKey": "review_prompt",
        "version": "2026.06",
        "status": "production",
        "riskLevel": "high",
        "businessPackId": DEFAULT_BUSINESS_PACK_ID,
        "updatedAt": "2026-06-26 10:00:00",
    }
]

PROMPT_TEMPLATES = [
    {
        "id": "PTPL-review-202606",
        "name": "工程监检审查 Prompt 模板",
        "promptKey": "review_prompt",
        "version": "2026.06",
        "status": "production",
        "riskLevel": "high",
        "businessPackId": DEFAULT_BUSINESS_PACK_ID,
        "agentId": "compliance_review_agent",
        "promptVersionId": "PROMPT-review-202606",
        "systemPrompt": (
            "You are {{agentName}} for business pack {{businessPackId}} version {{businessPackVersion}}. "
            "Return evidence-backed review suggestions only. Do not approve final business state."
        ),
        "userPromptTemplate": "{{basePromptJson}}\n\n{{reviewTaskJson}}",
        "plannerPromptTemplate": (
            "Use the fixed AIcheck review graph plan: load project context, load OCR evidence, run deterministic rules, "
            "retrieve knowledge clauses, build prompt, generate finding drafts, validate schema/evidence/references, "
            "run critic review, evaluate quality gate, then persist drafts. Do not skip human confirmation."
        ),
        "criticPromptTemplate": (
            "Check whether each finding is evidence-backed, references only supplied rule/kb IDs, and keeps all final "
            "business decisions under human control."
        ),
        "outputSchema": {
            "type": "ReviewFindingDraftList",
            "fields": [
                "findingType",
                "severity",
                "title",
                "description",
                "confidence",
                "suggestedAction",
                "evidenceRefs",
                "ruleRefs",
                "kbRefs",
            ],
        },
        "variables": [
            "agentName",
            "businessPackId",
            "businessPackVersion",
            "basePromptJson",
            "reviewTaskJson",
        ],
        "createdAt": "2026-06-26 10:00:00",
        "updatedAt": "2026-06-26 10:00:00",
        "revision": 1,
    }
]

MODEL_ROUTE_VERSIONS = [
    {
        "id": "MODELROUTE-review-chat-202606",
        "modelAlias": "review-chat",
        "version": "2026.06",
        "status": "production",
        "fallbackAliases": ["default-chat"],
        "budgetPolicy": {"maxCostPerRun": 2.0, "maxLatencyMs": 30000},
    }
]

OCR_PROFILE_VERSIONS = [
    {
        "id": "OCRPROFILE-paddle-seal-202606",
        "profileKey": "paddle_seal_profile",
        "version": "2026.06",
        "status": "production",
        "fieldAccuracy": 0.93,
        "sealAccuracy": 0.89,
    }
]

CAPABILITY_BUNDLES = [
    {
        "id": "BUNDLE-REVIEW-202606",
        "name": "工程监检资料复核生产组合",
        "businessPackId": DEFAULT_BUSINESS_PACK_ID,
        "agentVersionId": "AGENT-compliance_review_agent-1.0.0",
        "promptVersionId": "PROMPT-review-202606",
        "modelRouteVersionId": "MODELROUTE-review-chat-202606",
        "ruleSetVersion": "Welder-Qualification-B-v2.1",
        "knowledgeBaseVersion": "proj-v2026.06.26",
        "ocrProfileVersionId": "OCRPROFILE-paddle-seal-202606",
        "schemaVersion": "ReviewFindingDraftList@1.0.0",
        "riskLevel": "high",
        "status": "production",
        "createdAt": "2026-06-26 10:45:00",
    }
]

RELEASE_PLANS = [
    {
        "id": "REL-REVIEW-202606-001",
        "releaseType": "capability_bundle",
        "capabilityBundleId": "BUNDLE-REVIEW-202606",
        "riskLevel": "high",
        "status": "production_approved",
        "targetScope": {"tenantIds": ["demo"], "businessPackIds": [DEFAULT_BUSINESS_PACK_ID], "projectIds": [PROJECT_ID]},
        "changeSummary": "资料合规复核员生产组合基线发布。",
        "evaluationReportId": "ERUN-20260626-001",
        "rollbackPlanId": "ROLLBACK-BUNDLE-202606",
        "createdByRole": "fde",
        "createdAt": "2026-06-26 11:10:00",
    }
]

RELEASE_APPROVALS = [
    {
        "id": "RAPP-REVIEW-202606-001",
        "releasePlanId": "REL-REVIEW-202606-001",
        "role": "ai_owner",
        "status": "approved",
        "comment": "评估集和风险集通过，允许生产基线。",
        "approvedAt": "2026-06-26 11:20:00",
    }
]

RELEASE_GATES = [
    {
        "id": "RGATE-REVIEW-202606-001",
        "releasePlanId": "REL-REVIEW-202606-001",
        "gate": "evaluation_report",
        "passed": True,
        "message": "评估报告已通过。",
        "checkedAt": "2026-06-26 11:12:00",
    },
    {
        "id": "RGATE-REVIEW-202606-002",
        "releasePlanId": "REL-REVIEW-202606-001",
        "gate": "rollback_plan",
        "passed": True,
        "message": "已绑定回滚计划。",
        "checkedAt": "2026-06-26 11:12:00",
    },
]

INCIDENTS = [
    {
        "id": "INC-AI-20260626-001",
        "title": "OCR 低置信度字段集中升高",
        "severity": "medium",
        "status": "monitoring",
        "rootCause": "low_quality_scan",
        "relatedAiRunIds": ["AIRUN-24-20260625-01"],
        "createdAt": "2026-06-26 11:30:00",
    }
]

INCIDENT_RCA = [
    {
        "id": "RCA-AI-20260626-001",
        "incidentId": "INC-AI-20260626-001",
        "status": "open",
        "rootCause": "low_quality_scan",
        "impactScope": {"projectIds": [PROJECT_ID], "aiRunIds": ["AIRUN-24-20260625-01"]},
        "temporaryAction": "对低置信度字段增加人工复核提醒。",
        "longTermAction": "优化 OCR Profile 的低清晰度扫描件预处理参数。",
        "owner": "FDE 工程师",
        "updatedAt": "2026-06-26 11:45:00",
    }
]

BUSINESS_PACK_INSTALLATIONS = [
    {
        "id": "BPINST-ENGINEERING-DEMO-001",
        "businessPackId": DEFAULT_BUSINESS_PACK_ID,
        "businessPackVersion": DEFAULT_BUSINESS_PACK["version"],
        "status": "production",
        "installedByRole": "fde",
        "installedAt": "2026-06-26 12:05:00",
        "rollbackToVersion": "2026.06.01",
        "validationStatus": "passed",
    }
]

BUSINESS_PACK_OVERRIDES = [
    {
        "id": "BPOVR-ENGINEERING-DEMO-001",
        "businessPackId": DEFAULT_BUSINESS_PACK_ID,
        "scope": "tenant",
        "status": "active",
        "overrides": {"reportTemplate": "TPL-PIPE-2026.06"},
        "updatedAt": "2026-06-26 12:06:00",
    }
]

COST_BUDGETS = [
    {
        "id": "BUDGET-DEMO-AI-202606",
        "scopeType": "tenant",
        "scopeId": "demo",
        "monthlyBudget": 5000,
        "usedAmount": 128.4,
        "currency": "CNY",
        "status": "normal",
        "updatedAt": "2026-06-26 12:10:00",
    }
]

DATA_EXPORTS: list[dict[str, Any]] = []

DELIVERY_ACCEPTANCE_REPORTS = [
    {
        "id": "DAR-ENGINEERING-202606",
        "businessPackId": DEFAULT_BUSINESS_PACK_ID,
        "status": "accepted",
        "acceptanceSetId": "ESET-GOLDEN-ENGINEERING-001",
        "metrics": {"evidenceHitRate": 0.92, "humanAcceptanceRate": 0.86},
        "confirmedBy": "客户管理员",
        "confirmedAt": "2026-06-26 12:00:00",
    }
]

REPORTS = [
    {
        "id": "RPT-20260625-001",
        "projectId": PROJECT_ID,
        "reportNo": "GDJ-JJ-2026-001",
        "versionNo": "V3",
        "title": "华东成品油管道改造工程监督检验报告",
        "status": "复核中",
        "scope": "project",
        "nodeIds": [16, 24, 40, 59],
        "templateVersion": "TPL-PIPE-2026.06",
        "generatedAt": "2026-06-26 09:40:00",
        "generatedByName": "张工",
        "reviewerName": "张工",
        "dataSnapshotId": "SNAP-RPT-20260625-001",
        "previewUrl": "mock://preview/reports/RPT-20260625-001",
        "exportUrl": "mock://download/reports/RPT-20260625-001.pdf",
        "actions": ["report:view", "report:export", "report:archive"],
    },
    {
        "id": "RPT-20250618-007",
        "projectId": "P-2025-CQARCH-007",
        "reportNo": "GDJ-JJ-2025-007",
        "versionNo": "V4",
        "title": "重庆老厂酸碱管线整改工程监督检验报告",
        "status": "已归档",
        "scope": "project",
        "nodeIds": [16, 24, 40, 68],
        "templateVersion": "TPL-PIPE-2025.12",
        "generatedAt": "2026-06-18 14:10:00",
        "generatedByName": "陈工",
        "reviewerName": "陈工",
        "dataSnapshotId": "SNAP-RPT-20250618-007",
        "previewUrl": "mock://preview/reports/RPT-20250618-007",
        "exportUrl": "mock://download/reports/RPT-20250618-007.pdf",
        "actions": ["report:view", "archive:view", "archive:download"],
    },
]

ARCHIVE_ITEMS = [
    {
        "id": "ARCH-RPT-001",
        "projectId": PROJECT_ID,
        "name": "监督检验报告 GDJ-JJ-2026-001.pdf",
        "type": "report",
        "nodeId": 24,
        "sourceOrgName": "省特检院一部",
        "status": "复核中",
        "updatedAt": "2026-06-26 09:40:00",
        "downloadUrl": "mock://download/reports/RPT-20260625-001.pdf",
    },
    {
        "id": "ARCH-EV-024",
        "projectId": PROJECT_ID,
        "name": "节点 24 证据定位包.zip",
        "type": "evidence",
        "nodeId": 24,
        "sourceOrgName": "系统生成",
        "status": "可下载",
        "updatedAt": "2026-06-26 09:45:00",
        "downloadUrl": "mock://download/archive/P-2026-HDCP-001-node24-evidence.zip",
    },
]

EXPORT_TASKS = [
    {
        "id": "EXP-RPT-20260625-001",
        "projectId": PROJECT_ID,
        "exportType": "report",
        "status": "可下载",
        "progress": 100,
        "fileName": "监督检验报告 GDJ-JJ-2026-001.pdf",
        "fileSize": 2097152,
        "downloadUrl": "mock://download/reports/RPT-20260625-001.pdf",
        "createdAt": "2026-06-26 09:44:00",
        "finishedAt": "2026-06-26 09:45:00",
        "expiresAt": "2026-06-27 09:45:00",
    },
    {
        "id": "EXP-ARCHIVE-QUEUE-001",
        "projectId": PROJECT_ID,
        "exportType": "archive-package",
        "status": "排队中",
        "progress": 12,
        "fileName": "P-2026-HDCP-001-归档资料包.zip",
        "fileSize": 4194304,
        "createdAt": "2026-06-26 09:50:00",
        "expiresAt": "2026-06-27 09:50:00",
    },
]

NDT_FILMS = [
    {
        "id": "FILM-RT-001",
        "projectId": PROJECT_ID,
        "filmNo": "RT-20260625-001",
        "weldNo": "W-24-RT-018",
        "pipelineNo": "PL-HD-02",
        "reportNo": "RT-R2-20260625",
        "entrustNo": "WT-NDT-20260625-01",
        "filmPackageNo": "FILM-PKG-20260625-01",
        "imageFileName": "RT-20260625-001.dcm",
        "method": "RT",
        "testDate": "2026-06-25",
        "detectionRatio": "10%",
        "standardCode": "NB/T 47013.2-2015",
        "imageQualityIndicator": "Fe 10",
        "sensitivity": "2.0%",
        "density": "2.8",
        "geometricUnsharpness": "0.2mm",
        "evaluationLevel": "II",
        "defectCode": "",
        "defectLocation": "",
        "evaluatorName": "王工",
        "reviewerName": "赵工",
        "status": "待审查",
        "actions": ["ndt:film-create", "ndt:submit"],
    },
    {
        "id": "FILM-RT-002",
        "projectId": PROJECT_ID,
        "filmNo": "RT-20260626-002",
        "weldNo": "W-41-RT-020",
        "pipelineNo": "PL-HD-04",
        "reportNo": "RT-R2-20260626",
        "entrustNo": "WT-NDT-20260626-01",
        "filmPackageNo": "FILM-PKG-20260626-01",
        "imageFileName": "RT-20260626-002.dcm",
        "method": "RT",
        "testDate": "2026-06-26",
        "detectionRatio": "10%",
        "standardCode": "NB/T 47013.2-2015",
        "imageQualityIndicator": "Fe 10",
        "sensitivity": "2.0%",
        "density": "2.6",
        "geometricUnsharpness": "0.2mm",
        "evaluationLevel": "II",
        "defectCode": "疑似夹渣",
        "defectLocation": "W-41 12 点方向",
        "evaluatorName": "王工",
        "reviewerName": "赵工",
        "status": "需补正",
        "actions": ["ndt:submit", "rectification:submit"],
    },
]

NDT_RECORDS = [
    {
        "id": "NDT-REC-001",
        "projectId": PROJECT_ID,
        "nodeId": 40,
        "recordNo": "REC-RT-20260625-001",
        "filmId": "FILM-RT-001",
        "reportId": "NDT-RPT-001",
        "weldNo": "W-24-RT-018",
        "pipelineNo": "PL-HD-02",
        "entrustNo": "WT-NDT-20260625-01",
        "reportNo": "RT-R2-20260625",
        "techniqueNo": "NDT-WI-RT-2026-01",
        "equipmentNo": "XRY-2505",
        "personnelCertificateNo": "RT-II-2026-001",
        "detectionRatio": "10%",
        "standardCode": "NB/T 47013.2-2015",
        "method": "RT",
        "testDate": "2026-06-25",
        "evaluatorName": "王工",
        "reviewerName": "赵工",
        "result": "合格",
        "evaluationLevel": "II",
        "signatureStatus": "已签字",
        "stampStatus": "已盖章",
        "sampleStatus": "已抽查",
        "conclusion": "底片黑度、像质计和缺陷评定记录齐全。",
        "importedAt": "2026-06-25 15:00:00",
        "actions": ["ndt:record-import"],
    }
]

NDT_REPORTS = [
    {
        "id": "NDT-RPT-001",
        "projectId": PROJECT_ID,
        "reportNo": "RT-R2-20260625",
        "entrustNo": "WT-NDT-20260625-01",
        "method": "RT",
        "detectionRatio": "10%",
        "standardCode": "NB/T 47013.2-2015",
        "evaluatorName": "王工",
        "reviewerName": "赵工",
        "fileId": "DOC-20260625-004",
        "relatedFilmIds": ["FILM-RT-001"],
        "status": "待提交",
        "conclusion": "RT II 级合格，需提交原始底片包。",
        "uploadedAt": "2026-06-25 14:30:00",
        "actions": ["ndt:report-upload", "ndt:submit"],
    },
    {
        "id": "NDT-RPT-002",
        "projectId": PROJECT_ID,
        "reportNo": "UT-U1-20260625",
        "entrustNo": "WT-NDT-20260625-02",
        "method": "UT",
        "detectionRatio": "20%",
        "standardCode": "NB/T 47013.3-2015",
        "evaluatorName": "王工",
        "reviewerName": "赵工",
        "fileId": "DOC-20260625-005",
        "relatedFilmIds": ["FILM-RT-002"],
        "status": "待审查",
        "conclusion": "UT I 级合格，等待监检确认。",
        "uploadedAt": "2026-06-25 15:20:00",
        "actions": ["ndt:submit"],
    },
]

NDT_FEEDBACK = [
    {
        "id": "NDT-FB-001",
        "projectId": PROJECT_ID,
        "nodeId": 40,
        "title": "底片包索引缺少原始编号页",
        "description": "请补充 RT-20260626-002 原始编号页并重新提交。",
        "status": "待反馈",
        "relatedReportIds": ["NDT-RPT-001"],
        "relatedFilmIds": ["FILM-RT-002"],
        "createdAt": "2026-06-26 09:20:00",
        "deadline": "2026-06-28 18:00:00",
    }
]

TODOS = [
    {
        "id": "TODO-001",
        "title": "节点 24 焊工资格证待人工确认",
        "projectId": PROJECT_ID,
        "nodeId": 24,
        "targetType": "node",
        "targetId": "24",
        "status": "待处理",
        "priority": "高",
        "deadline": "2026-06-27 18:00:00",
        "assigneeName": "张工",
        "actions": ["review:save", "ai:recheck"],
    },
    {
        "id": "TODO-002",
        "title": "节点 16 炉批号差异说明待补正",
        "projectId": PROJECT_ID,
        "nodeId": 16,
        "targetType": "rectification",
        "targetId": "REC-16-001",
        "status": "待处理",
        "priority": "中",
        "deadline": "2026-06-28 18:00:00",
        "assigneeName": "李工",
        "actions": ["rectification:submit"],
    },
]

MESSAGES = [
    {
        "id": "MSG-001",
        "title": "AI 审查完成",
        "content": "节点 24 焊工资格证 AI 审查已完成，请人工确认。",
        "projectId": PROJECT_ID,
        "targetType": "node",
        "targetId": "24",
        "read": False,
        "createdAt": "2026-06-26 09:12:00",
    },
    {
        "id": "MSG-002",
        "title": "退回补正提醒",
        "content": "节点 16 炉批号差异说明待补正。",
        "projectId": PROJECT_ID,
        "targetType": "rectification",
        "targetId": "REC-16-001",
        "read": False,
        "createdAt": "2026-06-25 18:21:00",
    },
]


def build_knowledge_files(documents: list[dict[str, Any]], bindings: list[dict[str, Any]], nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    chunk_counts = [18, 10, 24, 15]
    for index, doc in enumerate(documents):
        binding = next((item for item in bindings if item["documentId"] == doc["id"]), None)
        node = next((item for item in nodes if binding and item["nodeId"] == binding["nodeId"]), None)
        vector_status = "向量化中" if doc["currentOcrStatus"] == "识别中" else "已向量化"
        chunk_count = chunk_counts[index] if index < len(chunk_counts) else 8
        files.append(
            {
                "id": f"KF-{doc['id']}",
                "fileName": doc["fileName"],
                "sourceId": "KS-PROJECT-FILE",
                "sourceName": "项目文件知识库",
                "projectId": doc["projectId"],
                "projectName": "华东成品油管道改造工程",
                "nodeId": binding["nodeId"] if binding else None,
                "nodeName": node["name"] if node else None,
                "documentId": doc["id"],
                "documentVersionId": doc["currentVersionId"],
                "ocrStatus": doc["currentOcrStatus"],
                "sliceStatus": "切片中" if doc["currentOcrStatus"] == "识别中" else "已切片",
                "vectorStatus": vector_status,
                "chunkCount": chunk_count,
                "vectorCount": chunk_count if vector_status == "已向量化" else max(0, chunk_count - 6),
                "updatedAt": doc["updatedAt"],
                "actions": ["knowledge:view", "knowledge:reindex"],
            }
        )
    return files


KNOWLEDGE_SOURCES = [
    STANDARD_KNOWLEDGE_SEED["source"],
    {
        "id": "KS-PROJECT-FILE",
        "name": "项目文件知识库",
        "sourceType": "project-file",
        "version": "proj-v2026.06.26",
        "status": "启用",
        "fileCount": len(DOCUMENTS),
        "chunkCount": 67,
        "vectorStatus": "向量化中",
        "updatedAt": "2026-06-26 09:31:00",
        "actions": ["knowledge:view", "knowledge:manage", "knowledge:reindex"],
    },
]

KNOWLEDGE_CLAUSES = [
    {
        "id": "KC-TSG-Z6002-3.2",
        "clauseId": "TSG-Z6002-3.2",
        "kbDocId": STANDARD_RULES_SOURCE_ID,
        "kbVersion": STANDARD_RULES_VERSION,
        "clauseNo": "3.2",
        "title": "焊工资格覆盖要求",
        "text": "焊工持证项目应覆盖实际焊接方法，证书编号、有效期和持证项目应与施工记录一致。",
        "pageNo": 32,
        "bbox": [120, 260, 980, 420],
        "sectionPath": ["TSG Z6002-2010 焊接人员考核细则", "3 焊工考试与合格项目", "3.2 资格覆盖"],
        "scope": {
            "businessPackId": DEFAULT_BUSINESS_PACK_ID,
            "nodeIds": [24, 25, 27, 28],
            "materialTypes": ["welder_certificate", "welding_record"],
        },
        "tags": ["焊工", "资格证", "持证项目", "有效期"],
        "status": "effective",
    },
    {
        "id": "KC-TSG-D7006-D2.4.1",
        "clauseId": "TSG-D7006-D2.4.1",
        "kbDocId": STANDARD_RULES_SOURCE_ID,
        "kbVersion": STANDARD_RULES_VERSION,
        "clauseNo": "D2.4.1",
        "title": "质量证明文件审查要求",
        "text": "质量证明文件应包含材料牌号、炉批号、规格、生产厂家、检验结论及有效签章。",
        "pageNo": 42,
        "bbox": [100, 200, 1200, 800],
        "sectionPath": ["TSG D7006-2020 压力管道监督检验规则", "附件 D", "D2.4.1 压力管道元件及安全附件"],
        "scope": {
            "businessPackId": DEFAULT_BUSINESS_PACK_ID,
            "nodeIds": [16, 17, 18],
            "materialTypes": ["quality_certificate"],
        },
        "tags": ["质量证明书", "材料牌号", "炉批号", "盖章"],
        "status": "effective",
    },
    {
        "id": "KC-NB-T-47013-NDT-REPORT",
        "clauseId": "NB-T-47013-NDT-REPORT",
        "kbDocId": STANDARD_RULES_SOURCE_ID,
        "kbVersion": STANDARD_RULES_VERSION,
        "clauseNo": "报告",
        "title": "无损检测报告审查要求",
        "text": "无损检测报告应核验报告编号、检测比例、焊口编号、检测日期、评定级别、检测结论和检测单位签章。",
        "pageNo": 78,
        "bbox": [96, 220, 1180, 760],
        "sectionPath": ["NB/T 47013 承压设备无损检测", "检测记录与报告", "报告关键字段"],
        "scope": {
            "businessPackId": DEFAULT_BUSINESS_PACK_ID,
            "nodeIds": [35, 36, 40, 41, 42],
            "materialTypes": ["ndt_report", "rt_report", "ut_report"],
        },
        "tags": ["NDT", "检测报告", "焊口编号", "签章"],
        "status": "effective",
    },
]

KNOWLEDGE_PAGE_INDEX_NODES = [
    {
        "id": "PIN-RULE-STANDARDS-ROOT",
        "pageIndexNodeId": "PIN-RULE-STANDARDS-ROOT",
        "kbDocId": STANDARD_RULES_SOURCE_ID,
        "kbVersion": STANDARD_RULES_VERSION,
        "nodeId": "root",
        "parentNodeId": None,
        "title": "业务规则引用标准规范总览",
        "summary": "覆盖业务规则引用的 TSG、GB、NB/T、JB/T、SY/T 标准规范及公告文件。",
        "startPage": 1,
        "endPage": 90,
        "sectionPath": ["业务规则引用标准规范库"],
        "children": ["PIN-TSG-Z6002-3", "PIN-TSG-D7006-D2", "PIN-NB-T-47013-NDT"],
        "linkedClauseIds": ["TSG-Z6002-3.2", "TSG-D7006-D2.4.1", "NB-T-47013-NDT-REPORT"],
        "businessPackId": DEFAULT_BUSINESS_PACK_ID,
        "nodeTypes": ["inspection_review"],
        "materialTypes": ["welder_certificate", "quality_certificate", "ndt_report"],
        "tags": ["监督检验", "资料审查", "正文", "附录", "跨章节"],
        "status": "effective",
    },
    {
        "id": "PIN-TSG-Z6002-3",
        "pageIndexNodeId": "PIN-TSG-Z6002-3",
        "kbDocId": STANDARD_RULES_SOURCE_ID,
        "kbVersion": STANDARD_RULES_VERSION,
        "nodeId": "3",
        "parentNodeId": "root",
        "title": "TSG Z6002 焊工资格覆盖",
        "summary": "焊工资格证、有效期、持证项目与施工记录一致性审查。",
        "startPage": 28,
        "endPage": 36,
        "sectionPath": ["TSG Z6002-2010 焊接人员考核细则", "3 焊工考试与合格项目"],
        "children": [],
        "linkedClauseIds": ["TSG-Z6002-3.2"],
        "businessPackId": DEFAULT_BUSINESS_PACK_ID,
        "nodeTypes": ["welder_certificate_review"],
        "materialTypes": ["welder_certificate", "welding_record"],
        "tags": ["焊工", "资格证", "有效期", "持证项目"],
        "status": "effective",
    },
    {
        "id": "PIN-TSG-D7006-D2",
        "pageIndexNodeId": "PIN-TSG-D7006-D2",
        "kbDocId": STANDARD_RULES_SOURCE_ID,
        "kbVersion": STANDARD_RULES_VERSION,
        "nodeId": "D2",
        "parentNodeId": "root",
        "title": "TSG D7006 压力管道元件资料",
        "summary": "质量证明文件应核对材料牌号、炉批号、规格、生产厂家、检验结论和有效签章。",
        "startPage": 40,
        "endPage": 46,
        "sectionPath": ["TSG D7006-2020 压力管道监督检验规则", "附件 D"],
        "children": [],
        "linkedClauseIds": ["TSG-D7006-D2.4.1"],
        "businessPackId": DEFAULT_BUSINESS_PACK_ID,
        "nodeTypes": ["material_review"],
        "materialTypes": ["quality_certificate"],
        "tags": ["质量证明书", "材料牌号", "炉批号", "盖章"],
        "status": "effective",
    },
    {
        "id": "PIN-NB-T-47013-NDT",
        "pageIndexNodeId": "PIN-NB-T-47013-NDT",
        "kbDocId": STANDARD_RULES_SOURCE_ID,
        "kbVersion": STANDARD_RULES_VERSION,
        "nodeId": "NDT",
        "parentNodeId": "root",
        "title": "NB/T 47013 无损检测报告",
        "summary": "跨章节核验正文、附录、无损检测报告、检测比例、焊口编号、检测单位签章要求。",
        "startPage": 70,
        "endPage": 82,
        "sectionPath": ["NB/T 47013 承压设备无损检测", "检测记录与报告"],
        "children": [],
        "linkedClauseIds": ["NB-T-47013-NDT-REPORT"],
        "businessPackId": DEFAULT_BUSINESS_PACK_ID,
        "nodeTypes": ["ndt_review"],
        "materialTypes": ["ndt_report", "rt_report", "ut_report"],
        "tags": ["无损检测", "检测报告", "签章", "附录", "跨章节"],
        "status": "effective",
    },
]

RETRIEVAL_TRACES = [
    {
        "id": "RTR-KB-SCORECARD-001",
        "retrievalTraceId": "RTR-KB-SCORECARD-001",
        "reviewRunId": "RRUN-KB-SCORECARD-SEED",
        "query": "焊工资格证有效期如何校验？",
        "queryType": "knowledge_scorecard_seed",
        "routerVersion": "knowledge-router-v1",
        "selectedRoute": "hybrid_review_basis_search",
        "routerSignals": {
            "exactClauseRefs": [],
            "needsPageIndex": False,
            "tokenCount": 4,
            "queryLength": 13,
        },
        "queryRouter": {
            "selectedRoute": "hybrid_review_basis_search",
            "signals": {
                "exactClauseRefs": [],
                "needsPageIndex": False,
                "tokenCount": 4,
                "queryLength": 13,
            },
            "fallbackRoute": "hybrid_review_basis_search",
        },
        "filters": {
            "businessPackId": DEFAULT_BUSINESS_PACK_ID,
            "nodeId": 24,
            "effectiveAt": "2026-06-26 11:02:30",
        },
        "retrievers": [
            {"type": "exact_clause_lookup", "enabled": False, "clauseRefs": []},
            {"type": "clause_index", "topK": 3, "candidateCount": 3},
            {"type": "hybrid_bm25_dense", "topK": 3, "implementation": "local_token_overlap_until_vector_index"},
            {
                "type": "pageindex_tree",
                "enabled": False,
                "implementation": "local_page_index_nodes",
                "candidateNodeCount": 4,
                "selectedNodeCount": 0,
            },
        ],
        "pageIndexTree": {
            "candidateNodeCount": 4,
            "selectedNodes": [],
            "linkedClauseIds": [],
            "treeSearchPath": [],
        },
        "selectedClauses": [
            {
                "clauseId": "TSG-Z6002-3.2",
                "kbDocId": STANDARD_RULES_SOURCE_ID,
                "kbVersion": STANDARD_RULES_VERSION,
                "clauseNo": "3.2",
                "title": "焊工资格覆盖要求",
                "text": "焊工持证项目应覆盖实际焊接方法，证书编号、有效期和持证项目应与施工记录一致。",
                "pageNo": 32,
                "bbox": [120, 260, 980, 420],
                "score": 2.0,
                "retrievalMode": "hybrid_bm25_dense_local",
                "pageIndexNodeIds": [],
                "sourceEvidenceLinkId": None,
            }
        ],
        "kbVersion": STANDARD_RULES_VERSION,
        "createdAt": "2026-06-26 11:02:30",
    }
]

KNOWLEDGE_TASKS = [
    {
        "id": "KT-20260626-001",
        "taskType": "vector",
        "targetType": "file",
        "targetId": "KF-DOC-20260625-004",
        "targetName": "RT检测报告R2.pdf",
        "status": "运行中",
        "progress": 64,
        "createdAt": "2026-06-26 09:28:00",
        "actions": [],
    },
    {
        "id": "KT-20260626-002",
        "taskType": "ocr",
        "targetType": "file",
        "targetId": "KF-DOC-20260625-003",
        "targetName": "钢管质量证明书.pdf",
        "status": "失败",
        "progress": 38,
        "errorMessage": "第 2 页表格识别置信度低于阈值，需重试或人工修正。",
        "createdAt": "2026-06-26 08:52:00",
        "finishedAt": "2026-06-26 08:55:00",
        "actions": ["knowledge:task-retry"],
    },
    {
        "id": "KT-20260626-003",
        "taskType": "reindex",
        "targetType": "source",
        "targetId": "KS-PROJECT-FILE",
        "targetName": "项目文件知识库",
        "status": "排队中",
        "progress": 0,
        "createdAt": "2026-06-26 10:12:00",
        "actions": ["knowledge:task-retry"],
    },
]

CORE_RULE_VERSIONS = [
    {
        "id": "RULE-WELDER-202606",
        "name": "焊工资格核验规则",
        "ruleKey": "welder-qualification",
        "version": "Welder-Qualification-B-v2.1",
        "status": "已发布",
        "nodeIds": [24, 25, 27, 28],
        "sourceRuleId": "R24",
        "promptVersion": "prompt-welder-v2.1",
        "outputSchemaVersion": "schema-review-v1.3",
        "description": "核验焊工资格证、持证项目、有效期与施工焊接方法覆盖关系。",
        "publishedAt": "2026-06-26 09:12:00",
        "updatedAt": "2026-06-26 09:12:00",
        "actions": ["knowledge:view", "knowledge:manage"],
    },
    {
        "id": "RULE-NDT-202606",
        "name": "无损检测报告核验规则",
        "ruleKey": "ndt-report",
        "version": "NDT-Report-C-v1.4",
        "status": "待发布",
        "nodeIds": [35, 36, 40, 41, 42],
        "sourceRuleId": "R40",
        "promptVersion": "prompt-ndt-v1.4",
        "outputSchemaVersion": "schema-ndt-v1.1",
        "description": "核验底片、检测比例、评片结论、返修闭环和报告签章。",
        "standardText": "标准规范：NB/T 47013《承压设备无损检测》、TSG D7005 监督检验资料审查要求，以及项目设计文件中关于检测方法、检测比例、验收等级和报告签章的要求。",
        "witnessText": "工作见证：需提供无损检测报告、检测委托单、检测底片或记录、返修及复检闭环资料、检测人员资格信息和检测单位签章。",
        "updatedAt": "2026-06-26 10:05:00",
        "actions": ["knowledge:view", "knowledge:manage"],
    },
]


CORE_RULE_VERSION_OVERRIDES_BY_SOURCE_ID = {
    rule["sourceRuleId"]: rule
    for rule in CORE_RULE_VERSIONS
    if rule.get("sourceRuleId")
}
BUSINESS_PACK_RULES_BY_SOURCE_ID = {
    rule.get("sourceRuleId"): rule
    for rule in DEFAULT_BUSINESS_PACK["ruleSets"]
    if rule.get("sourceRuleId")
}
RULE_VERSION_SOURCE_ORDER = [
    *CORE_RULE_VERSION_OVERRIDES_BY_SOURCE_ID.keys(),
    *[
        rule.get("sourceRuleId")
        for rule in DEFAULT_BUSINESS_PACK["ruleSets"]
        if rule.get("sourceRuleId") not in CORE_RULE_VERSION_OVERRIDES_BY_SOURCE_ID
    ],
]


def build_rule_version(
    rule: dict[str, Any],
    *,
    source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_rule = source or rule
    criteria = (
        source_rule.get("standardText")
        or source_rule.get("criteria")
        or rule.get("standardText")
        or rule.get("criteria")
        or ""
    )
    check_method = (
        source_rule.get("witnessText")
        or source_rule.get("checkMethod")
        or rule.get("witnessText")
        or rule.get("checkMethod")
        or ""
    )
    inspection_item = (
        source_rule.get("inspectionItem")
        or source_rule.get("name")
        or rule.get("inspectionItem")
        or rule.get("name")
    )
    node_ids = [
        int(item)
        for item in (rule.get("nodeIds") or source_rule.get("nodeIds") or [])
        if str(item).isdigit()
    ]
    display_name = rule_name_from_node_ids(node_ids, inspection_item)
    inspection_class = (
        source_rule.get("inspectionClass")
        or source_rule.get("reviewClass")
        or rule.get("inspectionClass")
        or rule.get("reviewClass")
        or ""
    )
    record = {
        **source_rule,
        **rule,
        "businessPackId": DEFAULT_BUSINESS_PACK_ID,
        "businessPackVersion": DEFAULT_BUSINESS_PACK["version"],
        "sourceRuleId": source_rule.get("sourceRuleId") or rule.get("sourceRuleId"),
        "sourceDocument": source_rule.get("sourceDocument") or rule.get("sourceDocument"),
        "sourceSequence": source_rule.get("sourceSequence") or rule.get("sourceSequence"),
        "businessModule": source_rule.get("businessModule") or rule.get("businessModule"),
        "inspectionCategory": (
            source_rule.get("inspectionCategory")
            or source_rule.get("businessModule")
            or rule.get("inspectionCategory")
            or rule.get("businessModule")
            or ""
        ),
        "inspectionItem": inspection_item,
        "name": display_name,
        "inspectionClass": inspection_class,
        "reviewClass": inspection_class,
        "criteria": criteria,
        "standardText": criteria,
        "checkMethod": check_method,
        "witnessText": check_method,
        "publishedAt": rule.get("publishedAt")
        or ("2026-06-26 09:12:00" if rule.get("status") == "已发布" else None),
        "updatedAt": rule.get("updatedAt") or "2026-06-26 09:12:00",
        "actions": rule.get("actions") or ["knowledge:view", "knowledge:manage"],
        "revision": rule.get("revision", 1),
    }
    if not record.get("description"):
        record["description"] = check_method or criteria or inspection_item
    generated_ai_execution = source_rule.get("aiExecution") or rule.get("aiExecution")
    record["aiExecution"] = deepcopy(generated_ai_execution) if generated_ai_execution else {
        "schemaVersion": "business-rule-execution-v1",
        "sourceFields": {
            "sequence": record.get("sourceSequence"),
            "inspectionCategory": record.get("inspectionCategory"),
            "inspectionItem": record.get("inspectionItem"),
            "inspectionClass": record.get("inspectionClass"),
            "standardText": criteria,
            "witnessText": check_method,
        },
        "promptContext": "\n".join(
            [
                f"监检项目：{record.get('inspectionItem') or record.get('name')}",
                f"类别：{record.get('inspectionClass') or '-'}",
                f"判断准则/标准规范：{criteria or '-'}",
                f"方法及内容/工作见证：{check_method or '-'}",
            ]
        ),
    }
    return record


RULE_VERSIONS = [
    build_rule_version(
        CORE_RULE_VERSION_OVERRIDES_BY_SOURCE_ID.get(source_rule_id)
        or BUSINESS_PACK_RULES_BY_SOURCE_ID[source_rule_id],
        source=BUSINESS_PACK_RULES_BY_SOURCE_ID[source_rule_id],
    )
    for source_rule_id in RULE_VERSION_SOURCE_ORDER
]

KNOWLEDGE_CONFIG = {
    "embeddingModel": "embedding-default",
    "embeddingModelId": "Qwen/Qwen3-Embedding-0.6B",
    "embeddingProvider": "Infinity",
    "embeddingServedModelName": "embedding-default",
    "dimensions": 1024,
    "embeddingHotSwapEnabled": True,
    "chunkSize": 900,
    "chunkOverlap": 120,
    "topKDefault": 5,
    "rerankEnabled": True,
    "evidenceStrictMode": True,
    "autoReindex": True,
    "retentionDays": 180,
    "updatedBy": "张工",
    "updatedAt": "2026-06-26 09:45:00",
}

LLM_COMPARE_RUNS = [
    {
        "runId": "CMP-20260626-001",
        "question": "焊工资格证与持证项目是否覆盖本项目焊接方法？",
        "modelCodes": ["default-chat", "compare-fast"],
        "createdAt": "2026-06-26 09:40:00",
        "projectId": PROJECT_ID,
        "nodeId": 24,
        "results": [
            {
                "modelCode": "default-chat",
                "answer": "证书编号和持证项目基本匹配，建议人工确认外部查询截图来源后通过。",
                "confidence": 0.88,
                "evidenceLinkIds": ["EV-24-001", "EV-24-002"],
                "latencyMs": 1240,
            },
            {
                "modelCode": "compare-fast",
                "answer": "持证项目覆盖焊接方法，但外部核验资料仍需补充来源说明。",
                "confidence": 0.82,
                "evidenceLinkIds": ["EV-24-001"],
                "latencyMs": 1580,
            },
        ],
    }
]

PROJECT_MEMBERS = [
    {
        "id": "PM-OWNER-001",
        "projectId": PROJECT_ID,
        "userId": "USER-OWNER-001",
        "name": "赵经理",
        "orgName": "华东管网建设公司",
        "role": "owner",
        "nodeScope": [1, 16, 24, 40, 59, 68],
        "actions": ROLE_ACTIONS["owner"],
        "status": "启用",
        "updatedAt": "2026-06-26 09:30:00",
    },
    {
        "id": "PM-INSPECTION-001",
        "projectId": PROJECT_ID,
        "userId": "USER-INSPECTION-001",
        "name": "张工",
        "orgName": "省特检院一部",
        "role": "inspection",
        "nodeScope": [16, 24, 40, 59],
        "actions": ROLE_ACTIONS["inspection"],
        "status": "启用",
        "updatedAt": "2026-06-26 09:30:00",
    },
    {
        "id": "PM-NDT-001",
        "projectId": PROJECT_ID,
        "userId": "USER-NDT-001",
        "name": "王工",
        "orgName": "华测检测有限公司",
        "role": "ndt",
        "nodeScope": [35, 36, 40, 41, 42],
        "actions": ROLE_ACTIONS["ndt"],
        "status": "启用",
        "updatedAt": "2026-06-26 09:30:00",
    },
    {
        "id": "PM-CONTRACTOR-001",
        "projectId": PROJECT_ID,
        "userId": "USER-CONTRACTOR-001",
        "name": "李工",
        "orgName": "中石化安装有限公司",
        "role": "contractor",
        "nodeScope": [16, 24, 25],
        "actions": ROLE_ACTIONS["contractor"],
        "status": "启用",
        "updatedAt": "2026-06-26 09:30:00",
    },
    {
        "id": "PM-CONTRACTOR-GDLNG-002",
        "projectId": "P-2026-GDLNG-002",
        "userId": "USER-CONTRACTOR-001",
        "name": "李工",
        "orgName": "粤海安装工程有限公司",
        "role": "contractor",
        "nodeScope": [16, 24, 25],
        "actions": ROLE_ACTIONS["contractor"],
        "status": "启用",
        "updatedAt": "2026-06-26 11:10:00",
    },
]

INSPECTION_TEST_USER_ID = "USER-INSPECTION-001"
INSPECTION_TEST_USER_NAME = "张工"
INSPECTION_TEST_ORG_NAME = "省特检院一部"


def _stable_inspection_member_id(project_id: str, used_ids: set[str]) -> str:
    suffix = "".join(char if char.isalnum() else "-" for char in project_id).strip("-").upper()
    candidate = f"PM-INSPECTION-{suffix or 'PROJECT'}"
    if candidate not in used_ids:
        return candidate
    index = 2
    while f"{candidate}-{index}" in used_ids:
        index += 1
    return f"{candidate}-{index}"


def _inspection_actions_for_project(project: dict[str, Any]) -> list[str]:
    pack = load_business_pack(project.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID)
    return role_actions_map(pack).get("inspection") or ROLE_ACTIONS["inspection"]


def _inspection_node_scope_for_project(
    project: dict[str, Any],
    tree_nodes_by_project: dict[str, list[int]] | None = None,
) -> list[int]:
    project_id = str(project.get("id") or "")
    node_ids = list((tree_nodes_by_project or {}).get(project_id) or [])
    if not node_ids and project_id:
        pack = load_business_pack(project.get("businessPackId") or DEFAULT_BUSINESS_PACK_ID)
        node_ids = [int(node["nodeId"]) for node in build_project_tree(project_id, pack)]
    if project.get("currentNodeId") is not None:
        node_ids.append(int(project["currentNodeId"]))
    return list(dict.fromkeys(node_ids))


def ensure_inspection_project_members(
    projects: list[dict[str, Any]],
    project_members: list[dict[str, Any]],
    tree_nodes: list[dict[str, Any]] | None = None,
) -> bool:
    """Test data rule: the default inspection account can review every test project."""
    changed = False
    used_ids = {str(member.get("id")) for member in project_members if member.get("id")}
    tree_nodes_by_project: dict[str, list[int]] = {}
    for node in tree_nodes or []:
        project_id = str(node.get("projectId") or "")
        node_id = node.get("nodeId")
        if not project_id or node_id is None:
            continue
        tree_nodes_by_project.setdefault(project_id, []).append(int(node_id))

    members_by_project = {
        str(member.get("projectId")): member
        for member in project_members
        if member.get("userId") == INSPECTION_TEST_USER_ID
        and member.get("role") == "inspection"
        and member.get("projectId")
    }
    for project in projects:
        project_id = str(project.get("id") or "")
        if not project_id:
            continue
        node_scope = _inspection_node_scope_for_project(project, tree_nodes_by_project)
        actions = _inspection_actions_for_project(project)
        member = members_by_project.get(project_id)
        if member is None:
            member_id = _stable_inspection_member_id(project_id, used_ids)
            used_ids.add(member_id)
            project_members.append(
                {
                    "id": member_id,
                    "projectId": project_id,
                    "userId": INSPECTION_TEST_USER_ID,
                    "name": INSPECTION_TEST_USER_NAME,
                    "orgName": project.get("inspectionOrgName") or INSPECTION_TEST_ORG_NAME,
                    "role": "inspection",
                    "nodeScope": node_scope,
                    "actions": actions,
                    "status": "启用",
                    "updatedAt": project.get("updatedAt") or "2026-06-26 09:30:00",
                }
            )
            changed = True
            continue

        desired_fields = {
            "userId": INSPECTION_TEST_USER_ID,
            "name": member.get("name") or INSPECTION_TEST_USER_NAME,
            "orgName": member.get("orgName") or project.get("inspectionOrgName") or INSPECTION_TEST_ORG_NAME,
            "role": "inspection",
            "status": "启用",
        }
        existing_scope = [int(node_id) for node_id in member.get("nodeScope") or []]
        desired_fields["nodeScope"] = list(dict.fromkeys([*existing_scope, *node_scope]))
        desired_fields["actions"] = list(dict.fromkeys([*actions, *(member.get("actions") or [])]))
        for key, value in desired_fields.items():
            if member.get(key) != value:
                member[key] = value
                changed = True
    return changed

ADMIN_CONFIG = {
    "orgUnits": [
        {"id": "ORG-OWNER-001", "name": "华东管网建设公司", "type": "owner", "contactName": "赵经理", "contactPhone": "13800000001", "status": "启用", "projectCount": 1},
        {"id": "ORG-CONTRACTOR-001", "name": "中石化安装有限公司", "type": "contractor", "contactName": "李工", "contactPhone": "13800000002", "status": "启用", "projectCount": 1},
        {"id": "ORG-NDT-001", "name": "华测检测有限公司", "type": "ndt", "contactName": "王工", "contactPhone": "13800000003", "status": "启用", "projectCount": 1},
        {"id": "ORG-INSPECTION-001", "name": "省特检院一部", "type": "inspection", "contactName": "张工", "contactPhone": "13800000004", "status": "启用", "projectCount": 1},
        {"id": "ORG-FDE-001", "name": "AI 交付治理组", "type": "fde", "contactName": "FDE", "contactPhone": "13800000061", "status": "启用", "projectCount": 0},
    ],
    "users": [
        {"id": "USER-INSPECTION-001", "username": "inspection", "name": "张工", "orgName": "省特检院一部", "role": "inspection", "mobile": "13800000004", "status": "启用", "lastLoginAt": "2026-06-26 09:05:00"},
        {"id": "USER-CONTRACTOR-001", "username": "contractor", "name": "李工", "orgName": "中石化安装有限公司", "role": "contractor", "mobile": "13800000002", "status": "启用", "lastLoginAt": "2026-06-26 08:50:00"},
        {"id": "USER-NDT-001", "username": "ndt", "name": "王工", "orgName": "华测检测有限公司", "role": "ndt", "mobile": "13800000003", "status": "启用", "lastLoginAt": "2026-06-25 17:10:00"},
        {"id": "USER-OWNER-001", "username": "owner", "name": "赵经理", "orgName": "华东管网建设公司", "role": "owner", "mobile": "13800000001", "status": "启用", "lastLoginAt": "2026-06-25 16:40:00"},
        {"id": "USER-ADMIN-001", "username": "admin", "name": "系统管理员", "orgName": "省特检院平台组", "role": "admin", "mobile": "13800000000", "status": "启用", "lastLoginAt": "2026-06-26 10:00:00"},
        {"id": "USER-FDE-001", "username": "fde", "name": "FDE 工程师", "orgName": "AI 交付治理组", "role": "fde", "mobile": "13800000061", "status": "启用", "lastLoginAt": "2026-06-26 10:30:00"},
        {"id": "USER-TEST-001", "username": "test", "name": "测试用户", "orgName": "联调测试组", "role": "inspection", "mobile": "13800000062", "status": "启用", "lastLoginAt": "2026-06-26 10:35:00"},
    ],
    "permissionMatrix": [
        {"role": role, "label": label, "projectScope": "授权项目", "nodeScope": "授权节点", "actions": actions, "readonly": role == "owner"}
        for role, label, actions in [
            ("inspection", "监检人员", ROLE_ACTIONS["inspection"]),
            ("contractor", "施工方", ROLE_ACTIONS["contractor"]),
            ("ndt", "无损检测", ROLE_ACTIONS["ndt"]),
            ("owner", "建设方", ROLE_ACTIONS["owner"]),
            ("admin", "系统管理员", ROLE_ACTIONS["admin"]),
            ("fde", "FDE", ROLE_ACTIONS["fde"]),
        ]
    ],
    "nodeTemplates": [{"id": "NT-PIPE-69", "version": "2026.06", "groupName": "压力管道监督检验 69 节点", "nodeCount": 69, "requiredCount": 42, "status": "已发布", "updatedAt": "2026-06-26 08:00:00"}],
    "workflowStateMachines": [{"id": "WF-PIPE-2026", "name": "压力管道资料审查状态机", "version": "2026.06", "states": 12, "transitions": 28, "status": "启用", "updatedAt": "2026-06-26 08:30:00"}],
    "todoRules": [{"id": "TR-001", "name": "退回补正待办", "triggerStatus": "需补正", "assigneeRole": "contractor", "deadlineHours": 48, "enabled": True, "updatedAt": "2026-06-26 08:30:00"}],
    "messageTemplates": [{"id": "MT-001", "scene": "AI审查完成", "channel": "站内信", "titleTemplate": "{nodeName} AI审查完成", "contentTemplate": "请处理 {nodeName} 的 AI 审查结果。", "enabled": True, "updatedAt": "2026-06-26 08:30:00"}],
    "toolSources": [{"id": "TS-OCR-001", "name": "PaddleOCR 文档识别", "toolType": "ocr", "endpoint": "ocr-service:8010", "authMode": "token", "status": "启用", "updatedAt": "2026-06-26 08:30:00"}],
    "fieldMappings": [{"id": "FM-001", "nodeId": 24, "fieldName": "证书编号", "sourceField": "ocr.certificate_no", "targetField": "welder.certificateNo", "required": True, "confidenceThreshold": 0.85, "updatedAt": "2026-06-26 08:30:00"}],
    "materialReviewPoints": deepcopy(DEFAULT_MATERIAL_REVIEW_POINTS),
    "materialReviewPointsAsset": {
        key: MATERIAL_REVIEW_ASSET.get(key)
        for key in ("schemaVersion", "version", "source", "sourceSha256", "itemCount")
    },
}
ADMIN_CONFIG["businessPacks"] = list_business_packs()
ADMIN_CONFIG["nodeTemplates"] = [
    {
        "id": f"NT-{DEFAULT_BUSINESS_PACK_ID}",
        "version": DEFAULT_BUSINESS_PACK["version"],
        "groupName": f"{DEFAULT_BUSINESS_PACK['name']}节点模板",
        "nodeCount": len(DEFAULT_BUSINESS_PACK["nodeTemplates"]),
        "requiredCount": len(REQUIREMENTS),
        "status": "已发布",
        "updatedAt": "2026-06-26 08:00:00",
    }
]
ADMIN_CONFIG["workflowStateMachines"] = [
    {
        "id": workflow["id"],
        "name": workflow["name"],
        "version": workflow.get("version"),
        "states": len(workflow.get("states") or []),
        "transitions": len(workflow.get("transitions") or []),
        "status": "启用",
        "updatedAt": "2026-06-26 08:30:00",
    }
    for workflow in DEFAULT_BUSINESS_PACK["workflowStateMachines"]
]

AUDIT_LOGS = [
    {
        "id": "AUD-001",
        "actorId": "USER-INSPECTION-001",
        "actorName": "张工",
        "actorOrgName": "省特检院一部",
        "action": "保存审查意见",
        "objectType": "ReviewOpinion",
        "objectId": "OPN-24-001",
        "result": "成功",
        "createdAt": "2026-06-26 09:12:00",
    }
]

SUBMISSION_DRAFTS: list[dict[str, Any]] = []
SUBMISSIONS: list[dict[str, Any]] = []
RECTIFICATIONS = [
    {
        "id": "REC-16-001",
        "projectId": PROJECT_ID,
        "nodeId": 16,
        "status": "待反馈",
        "comment": "请补充炉批号差异说明。",
        "createdAt": "2026-06-25 18:20:00",
    }
]


def fresh_state() -> dict[str, Any]:
    tree_nodes = []
    requirements = []
    for project in PROJECTS:
        pack = pack_for_project_id(project["id"])
        tree_nodes.extend(build_tree(project["id"]))
        requirements.extend(build_project_requirements(pack, project_id=project["id"]))
    knowledge_files = build_knowledge_files(DOCUMENTS, BINDINGS, tree_nodes)
    standard_documents = deepcopy(STANDARD_KNOWLEDGE_SEED["documents"])
    standard_versions = deepcopy(STANDARD_KNOWLEDGE_SEED["versions"])
    standard_knowledge_files = deepcopy(STANDARD_KNOWLEDGE_SEED["knowledgeFiles"])
    standard_knowledge_tasks = deepcopy(STANDARD_KNOWLEDGE_SEED["knowledgeTasks"])
    project_members = deepcopy(PROJECT_MEMBERS)
    ensure_inspection_project_members(PROJECTS, project_members, tree_nodes)
    state = {
        "projects": deepcopy(PROJECTS),
        "tree_nodes": tree_nodes,
        "requirements": requirements,
        "documents": [*deepcopy(DOCUMENTS), *standard_documents],
        "versions": [*deepcopy(VERSIONS), *standard_versions],
        "bindings": deepcopy(BINDINGS),
        "evidence_links": deepcopy(EVIDENCE_LINKS),
        "node_evidence_links": [],
        "material_targeting_runs": [],
        "extracted_fields": deepcopy(EXTRACTED_FIELDS),
        "ai_runs": deepcopy(AI_RUNS),
        "review_runs": [],
        "review_step_runs": [],
        "review_graph_nodes": [],
        "review_tool_calls": [],
        "review_events": [],
        "review_sessions": [],
        "review_messages": [],
        "review_session_events": [],
        "retrieval_traces": deepcopy(STANDARD_KNOWLEDGE_SEED["retrievalTraces"]),
        "rule_check_results": [],
        "review_opinions": deepcopy(REVIEW_OPINIONS),
        "review_findings": deepcopy(REVIEW_FINDINGS),
        "ai_feedback": deepcopy(AI_FEEDBACK),
        "access_grants": deepcopy(ACCESS_GRANTS),
        "ai_trace_steps": deepcopy(AI_TRACE_STEPS),
        "ai_run_replays": deepcopy(AI_RUN_REPLAYS),
        "feedback_triage": deepcopy(FEEDBACK_TRIAGE),
        "evaluation_sets": deepcopy(EVALUATION_SETS),
        "evaluation_cases": deepcopy(EVALUATION_CASES),
        "evaluation_case_results": deepcopy(EVALUATION_CASE_RESULTS),
        "evaluation_runs": deepcopy(EVALUATION_RUNS),
        "evaluation_metrics": deepcopy(EVALUATION_METRICS),
        "evaluation_reports": deepcopy(EVALUATION_REPORTS),
        "agent_versions": deepcopy(AGENT_VERSIONS),
        "prompt_versions": deepcopy(PROMPT_VERSIONS),
        "prompt_templates": deepcopy(PROMPT_TEMPLATES),
        "report_templates": report_template_seed(),
        "model_route_versions": deepcopy(MODEL_ROUTE_VERSIONS),
        "ocr_profile_versions": deepcopy(OCR_PROFILE_VERSIONS),
        "ocr_jobs": [],
        "ocr_parse_results": [],
        "ocr_corrections": [],
        "ocr_eval_runs": [],
        "ocr_annotation_tasks": [
            {
                "taskId": "ANNO-SEED-PIPING-001",
                "caseId": "real-piping_table_profile-seed-001",
                "scenario": "piping_table_profile",
                "profileId": "piping_characteristic_list_v1",
                "documentType": "engineering_table_photo",
                "sourcePath": "Scan/IMG_6509.heic",
                "collectionStatus": "needs_labeling",
                "pageCount": 1,
                "expectedTemplate": {
                    "qualityStatus": "auto_usable|needs_human_review|failed",
                    "minEvidenceCompleteness": 0.95,
                    "fields": [{"fieldCode": "replace-with-core-field", "value": "replace-with-label", "bbox": [0, 0, 0, 0]}],
                    "tables": [{"businessSchema": "replace-with-table-schema", "bbox": [0, 0, 0, 0]}],
                },
                "suggestedExpected": {
                    "qualityStatus": "needs_human_review",
                    "fields": [{"fieldCode": "pipe_no", "value": "PL8301", "bbox": [120, 260, 220, 300], "pageNo": 1}],
                    "tables": [
                        {
                            "businessSchema": "piping_characteristic_table_v1",
                            "bbox": [70, 230, 1800, 1120],
                            "minRows": 10,
                            "minColumns": 12,
                            "pageNo": 1,
                        }
                    ],
                },
                "certificationBlockers": ["placeholder_labels", "zero_area_bbox"],
            }
        ],
        "ocr_annotation_imports": [],
        "fde_capability_test_upload_sessions": [],
        "fde_capability_test_runs": [],
        "capability_bundles": deepcopy(CAPABILITY_BUNDLES),
        "release_plans": deepcopy(RELEASE_PLANS),
        "release_approvals": deepcopy(RELEASE_APPROVALS),
        "release_gates": deepcopy(RELEASE_GATES),
        "incidents": deepcopy(INCIDENTS),
        "incident_rca": deepcopy(INCIDENT_RCA),
        "business_pack_installations": deepcopy(BUSINESS_PACK_INSTALLATIONS),
        "business_pack_overrides": deepcopy(BUSINESS_PACK_OVERRIDES),
        "cost_budgets": deepcopy(COST_BUDGETS),
        "cost_budget_change_requests": [],
        "data_exports": deepcopy(DATA_EXPORTS),
        "masking_policies": [],
        "delivery_acceptance_reports": deepcopy(DELIVERY_ACCEPTANCE_REPORTS),
        "reports": deepcopy(REPORTS),
        "archive_items": deepcopy(ARCHIVE_ITEMS),
        "export_tasks": deepcopy(EXPORT_TASKS),
        "ndt_films": deepcopy(NDT_FILMS),
        "ndt_records": deepcopy(NDT_RECORDS),
        "ndt_reports": deepcopy(NDT_REPORTS),
        "ndt_feedback": deepcopy(NDT_FEEDBACK),
        "todos": deepcopy(TODOS),
        "messages": deepcopy(MESSAGES),
        "knowledge_sources": deepcopy(KNOWLEDGE_SOURCES),
        "knowledge_files": [*standard_knowledge_files, *knowledge_files],
        "knowledge_tasks": [*standard_knowledge_tasks, *deepcopy(KNOWLEDGE_TASKS)],
        "knowledge_chunks": [],
        "knowledge_vectors": [],
        "knowledge_clauses": deepcopy(STANDARD_KNOWLEDGE_SEED["clauses"]),
        "knowledge_page_index_nodes": deepcopy(STANDARD_KNOWLEDGE_SEED["pageIndexNodes"]),
        "knowledge_vector_corrections": [],
        "rule_versions": deepcopy(RULE_VERSIONS),
        "knowledge_config": deepcopy(KNOWLEDGE_CONFIG),
        "llm_compare_runs": deepcopy(LLM_COMPARE_RUNS),
        "project_members": project_members,
        "users": [],
        "roles": [],
        "business_packs": list_business_packs(),
        "admin_config": deepcopy(ADMIN_CONFIG),
        "audit_logs": deepcopy(AUDIT_LOGS),
        "submission_drafts": deepcopy(SUBMISSION_DRAFTS),
        "submissions": deepcopy(SUBMISSIONS),
        "rectifications": deepcopy(RECTIFICATIONS),
        "upload_sessions": [],
        "idempotency": {},
    }
    for collection in CLAUSE_STATE_COLLECTIONS:
        state.setdefault(collection, [])
    for summary in list_business_packs():
        pack = load_business_pack(summary["id"])
        if not pack.get("standardClausePackages"):
            continue
        publish_standard_clause_release(state, pack)
        for project in state["projects"]:
            if project.get("businessPackId") != pack["id"]:
                continue
            if project.get("businessPackVersion") not in {None, "", pack["version"]}:
                continue
            bind_project_node_clause_packages(state, project, pack, bound_at=project.get("updatedAt"))
    state["admin_config"]["ruleVersions"] = deepcopy(RULE_VERSIONS)
    return state
