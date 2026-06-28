from __future__ import annotations

from copy import deepcopy
from typing import Any

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

PROJECT_ID = "P-2026-HDCP-001"
DEFAULT_BUSINESS_PACK = default_business_pack()

ROLE_ACTIONS = role_actions_map(DEFAULT_BUSINESS_PACK)
ROLE_NODE_MAP = role_default_node_map(DEFAULT_BUSINESS_PACK)
for pack_summary in list_business_packs():
    pack = load_business_pack(pack_summary["id"])
    ROLE_ACTIONS.update({key: value for key, value in role_actions_map(pack).items() if key not in ROLE_ACTIONS})
    ROLE_NODE_MAP.update({key: value for key, value in role_default_node_map(pack).items() if key not in ROLE_NODE_MAP})

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
            "fde:business-pack:validate",
            "fde:business-pack:install",
            "fde:capability-bundle:manage",
            "fde:release:submit",
            "fde:release:shadow",
            "fde:release:canary",
            "fde:release:rollback",
            "fde:incident:manage",
            "fde:security:manage",
        ],
    }
)
ROLE_NODE_MAP.update({role: DEFAULT_BUSINESS_PACK["nodeTemplates"][0]["nodeId"] for role in FDE_ROLES})


def business_pack_project_fields(pack: dict[str, Any] | None = None) -> dict[str, Any]:
    source = pack or DEFAULT_BUSINESS_PACK
    return {
        "businessPackId": source["id"],
        "businessPackVersion": source["version"],
        "domainType": source["domainType"],
        "businessPackSnapshotHash": source["snapshotHash"],
        "businessPackSnapshot": business_pack_snapshot(source),
    }


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
        "currentNodeId": 68,
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
                "inputSummary": "证书编号、姓名、有效期、持证项目",
                "action": "OCR 字段与规则库比对",
                "conclusion": "待人工确认",
                "evidenceLinkIds": ["EV-24-001"],
            }
        ],
        "suggestion": {
            "id": "AIS-24-20260625-01",
            "result": "需人工确认",
            "opinionDraft": "焊工王建国证书编号、有效期和持证项目与焊接工艺要求匹配，建议人工确认外部查询截图来源后通过。",
            "risks": ["外部查询截图来源需确认"],
            "rectificationSuggestion": "补充资格网站查询截图来源说明。",
            "confidence": 0.88,
            "manualConfirmItems": ["资格网站查询截图来源"],
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
    opinion["kbRefs"] = [{"kbDocId": "KS-STANDARD-TSG", "clause": opinion.get("basis")}]

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
        "tenantId": "demo",
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
        "tenantId": "demo",
        "scope": "tenant",
        "status": "active",
        "overrides": {"reportTemplate": "TPL-PIPE-2026.06"},
        "updatedAt": "2026-06-26 12:06:00",
    }
]

COST_BUDGETS = [
    {
        "id": "BUDGET-DEMO-AI-202606",
        "tenantId": "demo",
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
        "method": "RT",
        "testDate": "2026-06-25",
        "evaluationLevel": "II",
        "defectCode": "",
        "status": "待审查",
        "actions": ["ndt:film-create", "ndt:submit"],
    },
    {
        "id": "FILM-RT-002",
        "projectId": PROJECT_ID,
        "filmNo": "RT-20260626-002",
        "weldNo": "W-41-RT-020",
        "pipelineNo": "PL-HD-04",
        "method": "RT",
        "testDate": "2026-06-26",
        "evaluationLevel": "II",
        "defectCode": "疑似夹渣",
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
        "method": "RT",
        "testDate": "2026-06-25",
        "evaluatorName": "王工",
        "result": "合格",
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
        "method": "RT",
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
        "method": "UT",
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
    {
        "id": "KS-STANDARD-TSG",
        "name": "TSG D7005 工业管道监督检验规则",
        "sourceType": "standard",
        "version": "std-v2026.06",
        "status": "启用",
        "fileCount": 8,
        "chunkCount": 1420,
        "vectorStatus": "已向量化",
        "updatedAt": "2026-06-26 09:10:00",
        "actions": ["knowledge:view", "knowledge:manage", "knowledge:reindex"],
    },
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
    {
        "id": "KS-RULE-PROMPT",
        "name": "AI 审查规则与 Prompt",
        "sourceType": "rule",
        "version": "rule-v2026.06",
        "status": "待复核",
        "fileCount": 12,
        "chunkCount": 384,
        "vectorStatus": "已向量化",
        "updatedAt": "2026-06-24 18:00:00",
        "actions": ["knowledge:view", "knowledge:manage"],
    },
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

RULE_VERSIONS = [
    {
        "id": "RULE-WELDER-202606",
        "name": "焊工资格核验规则",
        "ruleKey": "welder-qualification",
        "version": "Welder-Qualification-B-v2.1",
        "status": "已发布",
        "nodeIds": [24, 25, 27, 28],
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
        "promptVersion": "prompt-ndt-v1.4",
        "outputSchemaVersion": "schema-ndt-v1.1",
        "description": "核验底片、检测比例、评片结论、返修闭环和报告签章。",
        "updatedAt": "2026-06-26 10:05:00",
        "actions": ["knowledge:view", "knowledge:manage"],
    },
]

RULE_VERSIONS = [
    {
        "id": rule["id"],
        "name": rule["name"],
        "ruleKey": rule["ruleKey"],
        "version": rule["version"],
        "status": rule["status"],
        "nodeIds": rule["nodeIds"],
        "promptVersion": rule.get("promptVersion"),
        "outputSchemaVersion": rule.get("outputSchemaVersion"),
        "description": rule.get("description"),
        "businessPackId": DEFAULT_BUSINESS_PACK_ID,
        "businessPackVersion": DEFAULT_BUSINESS_PACK["version"],
        "publishedAt": "2026-06-26 09:12:00" if rule["status"] == "已发布" else None,
        "updatedAt": "2026-06-26 09:12:00",
        "actions": ["knowledge:view", "knowledge:manage"],
        "revision": 1,
    }
    for rule in DEFAULT_BUSINESS_PACK["ruleSets"]
]

KNOWLEDGE_CONFIG = {
    "embeddingModel": "embedding-default",
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
]

ADMIN_CONFIG = {
    "orgUnits": [
        {"id": "ORG-OWNER-001", "name": "华东管网建设公司", "type": "owner", "contactName": "赵经理", "contactPhone": "13800000001", "status": "启用", "projectCount": 1},
        {"id": "ORG-CONTRACTOR-001", "name": "中石化安装有限公司", "type": "contractor", "contactName": "李工", "contactPhone": "13800000002", "status": "启用", "projectCount": 1},
        {"id": "ORG-NDT-001", "name": "华测检测有限公司", "type": "ndt", "contactName": "王工", "contactPhone": "13800000003", "status": "启用", "projectCount": 1},
        {"id": "ORG-INSPECTION-001", "name": "省特检院一部", "type": "inspection", "contactName": "张工", "contactPhone": "13800000004", "status": "启用", "projectCount": 1},
        {"id": "ORG-FDE-001", "name": "AI 交付治理组", "type": "fde", "contactName": "FDE", "contactPhone": "13800000061", "status": "启用", "projectCount": 0},
    ],
    "users": [
        {"id": "USER-INSPECTION-001", "name": "张工", "orgName": "省特检院一部", "role": "inspection", "mobile": "13800000004", "status": "启用", "lastLoginAt": "2026-06-26 09:05:00"},
        {"id": "USER-CONTRACTOR-001", "name": "李工", "orgName": "中石化安装有限公司", "role": "contractor", "mobile": "13800000002", "status": "启用", "lastLoginAt": "2026-06-26 08:50:00"},
        {"id": "USER-NDT-001", "name": "王工", "orgName": "华测检测有限公司", "role": "ndt", "mobile": "13800000003", "status": "启用", "lastLoginAt": "2026-06-25 17:10:00"},
        {"id": "USER-OWNER-001", "name": "赵经理", "orgName": "华东管网建设公司", "role": "owner", "mobile": "13800000001", "status": "启用", "lastLoginAt": "2026-06-25 16:40:00"},
        {"id": "USER-ADMIN-001", "name": "系统管理员", "orgName": "省特检院平台组", "role": "admin", "mobile": "13800000000", "status": "启用", "lastLoginAt": "2026-06-26 10:00:00"},
        {"id": "USER-FDE-001", "name": "FDE 工程师", "orgName": "AI 交付治理组", "role": "fde", "mobile": "13800000061", "status": "启用", "lastLoginAt": "2026-06-26 10:30:00"},
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
    state = {
        "projects": deepcopy(PROJECTS),
        "tree_nodes": tree_nodes,
        "requirements": requirements,
        "documents": deepcopy(DOCUMENTS),
        "versions": deepcopy(VERSIONS),
        "bindings": deepcopy(BINDINGS),
        "evidence_links": deepcopy(EVIDENCE_LINKS),
        "extracted_fields": deepcopy(EXTRACTED_FIELDS),
        "ai_runs": deepcopy(AI_RUNS),
        "review_opinions": deepcopy(REVIEW_OPINIONS),
        "review_findings": deepcopy(REVIEW_FINDINGS),
        "ai_feedback": deepcopy(AI_FEEDBACK),
        "access_grants": deepcopy(ACCESS_GRANTS),
        "ai_trace_steps": deepcopy(AI_TRACE_STEPS),
        "ai_run_replays": deepcopy(AI_RUN_REPLAYS),
        "feedback_triage": deepcopy(FEEDBACK_TRIAGE),
        "evaluation_sets": deepcopy(EVALUATION_SETS),
        "evaluation_cases": deepcopy(EVALUATION_CASES),
        "evaluation_runs": deepcopy(EVALUATION_RUNS),
        "evaluation_metrics": deepcopy(EVALUATION_METRICS),
        "evaluation_reports": deepcopy(EVALUATION_REPORTS),
        "agent_versions": deepcopy(AGENT_VERSIONS),
        "prompt_versions": deepcopy(PROMPT_VERSIONS),
        "model_route_versions": deepcopy(MODEL_ROUTE_VERSIONS),
        "ocr_profile_versions": deepcopy(OCR_PROFILE_VERSIONS),
        "capability_bundles": deepcopy(CAPABILITY_BUNDLES),
        "release_plans": deepcopy(RELEASE_PLANS),
        "release_approvals": deepcopy(RELEASE_APPROVALS),
        "release_gates": deepcopy(RELEASE_GATES),
        "incidents": deepcopy(INCIDENTS),
        "incident_rca": deepcopy(INCIDENT_RCA),
        "business_pack_installations": deepcopy(BUSINESS_PACK_INSTALLATIONS),
        "business_pack_overrides": deepcopy(BUSINESS_PACK_OVERRIDES),
        "cost_budgets": deepcopy(COST_BUDGETS),
        "data_exports": deepcopy(DATA_EXPORTS),
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
        "knowledge_files": knowledge_files,
        "knowledge_tasks": deepcopy(KNOWLEDGE_TASKS),
        "knowledge_chunks": [],
        "rule_versions": deepcopy(RULE_VERSIONS),
        "knowledge_config": deepcopy(KNOWLEDGE_CONFIG),
        "llm_compare_runs": deepcopy(LLM_COMPARE_RUNS),
        "project_members": deepcopy(PROJECT_MEMBERS),
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
    state["admin_config"]["ruleVersions"] = deepcopy(RULE_VERSIONS)
    return state
