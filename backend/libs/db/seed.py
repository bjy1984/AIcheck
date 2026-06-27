from __future__ import annotations

from copy import deepcopy
from typing import Any

PROJECT_ID = "P-2026-HDCP-001"

ROLE_NODE_MAP = {
    "inspection": 24,
    "contractor": 16,
    "ndt": 40,
    "owner": 24,
    "admin": 24,
}

ROLE_ACTIONS = {
    "inspection": [
        "project:view",
        "file:view",
        "file:upload",
        "file:bind",
        "file:preview",
        "file:download",
        "review:save",
        "review:return-correction",
        "ai:recheck",
        "ai:adopt",
        "ai:reject",
        "report:generate",
        "report:review",
        "report:export",
        "report:archive",
        "report:view",
        "archive:view",
        "archive:download",
    ],
    "contractor": [
        "project:view",
        "file:view",
        "file:upload",
        "file:bind",
        "file:preview",
        "file:download",
        "file:withdraw",
        "submission:draft",
        "submission:submit",
        "submission:withdraw",
        "rectification:submit",
    ],
    "ndt": [
        "project:view",
        "file:view",
        "file:preview",
        "file:download",
        "ndt:film-create",
        "ndt:record-import",
        "ndt:report-upload",
        "ndt:submit",
        "rectification:submit",
    ],
    "owner": ["project:view", "file:view", "file:preview", "report:view", "archive:view", "archive:download"],
    "admin": ["project:view", "project:authorize-member", "knowledge:view", "knowledge:manage", "admin:config", "admin:export", "audit:view"],
}

GROUP_DEFINITIONS: list[tuple[str, list[tuple[int, str, str]]]] = [
    ("受检单位资质", [(1, "设计单位许可资质", "C"), (2, "施工单位许可资质", "C"), (3, "无损检测机构核准资质", "C")]),
    (
        "设计文件",
        [
            (4, "设计文件的批准程序", "C"),
            (5, "施工图审查手续", "C"),
            (6, "强度计算书、管道应力分析计算书的审批手续", "C"),
            (7, "设计变更的书面批准文件", "C"),
            (8, "设计采用的安全技术规范以及相关标准、压力管道元件的材料标准的版本", "C"),
            (9, "设计文件上注明的无损检测、防腐、耐压试验和泄漏试验要求", "C"),
            (10, "采用其他标准时的符合性申明及比照表", "需确认"),
        ],
    ),
    ("施工组织设计", [(11, "施工组织设计", "C")]),
    (
        "材料",
        [
            (12, "压力管道元件及安全附件制造单位的许可资质", "C"),
            (13, "需制造监检或有型式试验要求的压力管道元件的监检证书、型式试验报告", "C"),
            (14, "不需制造许可、监检、型式试验的管道组成件的出厂检验报告", "C/B"),
            (15, "境外制造的压力管道元件、安全附件的型式试验证书及制造许可证资质", "C"),
            (16, "压力管道元件以及安全附件产品质量证明文件", "C"),
            (17, "压力管道元件以及安全附件产品验收的见证资料、抽样复验", "C"),
            (18, "材料复验报告、无损检测报告", "C"),
            (19, "使用境外牌号材料制造的压力管道元件以及安全附件，验证性复验结果", "C"),
            (20, "新材料制造的压力管道元件以及安全附件的型式试验报告、技术评审、批准手续", "C"),
            (21, "材料标志移植", "B"),
            (22, "材料代用", "C"),
        ],
    ),
    ("阀门", [(23, "阀门的施工资料和耐压试验记录（报告）", "C")]),
    (
        "焊接（粘接）",
        [
            (24, "焊工资格证及持证合格项目", "B"),
            (25, "焊接（粘接）工艺文件", "C"),
            (26, "焊接材料质量证明文件", "C"),
            (27, "焊接材料的验收、保管、发放、使用和回收的管理", "B"),
            (28, "管道组对", "C"),
            (29, "施焊参数、施焊记录、焊缝标识", "B"),
            (30, "焊接接头外观质量", "B"),
            (31, "焊缝返修", "C"),
        ],
    ),
    ("热处理", [(32, "焊接接头焊后热处理工艺文件", "C"), (33, "热处理设备用测温记录仪表", "C"), (34, "热处理记录、报告曲线、硬度检测报告", "C")]),
    (
        "无损检测",
        [
            (35, "无损检测机构施工现场质量保证体系的实施", "B"),
            (36, "无损检测方案", "C"),
            (37, "检测过程中发现问题的处理", "C"),
            (38, "无损检测人员资格证、执业注册证及持证合格项目", "B"),
            (39, "无损检测工艺文件", "C"),
            (40, "无损检测记录、报告", "C"),
            (41, "射线检测底片抽查", "B"),
            (42, "射线检测现场抽查", "B"),
        ],
    ),
    (
        "防腐、保温",
        [
            (43, "防腐及保温材料质量证明文件", "C"),
            (44, "防腐、补口、补伤及保温", "C"),
            (45, "防腐层电火花检测", "C"),
            (46, "牺牲阳极、外加电流阴极保护、杂散电流排流装置", "C"),
            (47, "静电接地", "C"),
        ],
    ),
    ("穿跨越工程", [(48, "穿跨越工程的管道结构、焊缝布置", "C"), (49, "穿跨越工程施工", "C"), (50, "套管防腐绝缘", "C"), (51, "绝缘支撑", "C")]),
    ("管道现场制作（预制）", [(52, "管道现场制作（预制）", "B")]),
    ("管道安装", [(53, "管道布管与连接方式、穿跨越", "C/B"), (54, "补偿装置", "C/B"), (55, "支撑件", "C/B")]),
    ("安全附件", [(56, "安全阀、爆破片和紧急切断阀的安装位置、规格和型号", "B"), (57, "安全阀校验报告", "C"), (58, "紧急切断阀性能测试报告", "C")]),
    ("耐压试验", [(59, "耐压试验方案", "A"), (60, "试验用压力表、试验介质、介质温度、环境温度", "A"), (61, "耐压试验压力、保压时间及结果", "A"), (62, "耐压试验记录（报告）", "A")]),
    ("耐压试验免除或替代", [(63, "管道系统的柔性(应力)分析", "A"), (64, "现场检查替代性试验的过程", "A"), (65, "无损检测报告和底片", "A")]),
    ("泄漏试验", [(66, "试验用压力表、试验介质、介质温度、环境温度、试验压力", "B"), (67, "泄漏试验方法和试验报告", "C")]),
    ("吹扫、清洗", [(68, "吹扫、清洗", "C")]),
    ("施工单位质量保证体系实施状况的评价", [(69, "施工单位质量保证体系实施状况的评价", "需确认")]),
]


def build_tree(project_id: str = PROJECT_ID) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for group_name, rows in GROUP_DEFINITIONS:
        for node_id, name, inspection_type in rows:
            status = "待提交"
            if node_id == 16:
                status = "需补正"
            elif node_id == 24:
                status = "待人工确认"
            elif node_id == 40:
                status = "待审查"
            nodes.append(
                {
                    "id": f"{project_id}-{node_id}",
                    "projectId": project_id,
                    "nodeId": node_id,
                    "code": str(node_id).zfill(2),
                    "name": name,
                    "groupName": group_name,
                    "inspectionType": inspection_type,
                    "status": status,
                    "fileCount": 4 if node_id in {16, 24, 40} else node_id % 5,
                    "requiredProgress": {
                        "done": 4 if node_id in {16, 24, 40} else node_id % 3,
                        "total": 5,
                    },
                    "actions": ["project:view", "file:bind"],
                    "revision": 1,
                }
            )
    return nodes


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

REQUIREMENTS = [
    {"id": "REQ-16-01", "nodeId": 16, "name": "产品质量证明书", "requiredType": "必传"},
    {"id": "REQ-16-02", "nodeId": 16, "name": "材料复验报告", "requiredType": "条件必传"},
    {"id": "REQ-24-01", "nodeId": 24, "name": "焊工资格证", "requiredType": "必传"},
    {"id": "REQ-24-02", "nodeId": 24, "name": "焊工名册", "requiredType": "必传"},
    {"id": "REQ-24-03", "nodeId": 24, "name": "外部查询截图", "requiredType": "条件必传"},
    {"id": "REQ-40-01", "nodeId": 40, "name": "无损检测报告", "requiredType": "必传"},
]

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
    ],
    "users": [
        {"id": "USER-INSPECTION-001", "name": "张工", "orgName": "省特检院一部", "role": "inspection", "mobile": "13800000004", "status": "启用", "lastLoginAt": "2026-06-26 09:05:00"},
        {"id": "USER-CONTRACTOR-001", "name": "李工", "orgName": "中石化安装有限公司", "role": "contractor", "mobile": "13800000002", "status": "启用", "lastLoginAt": "2026-06-26 08:50:00"},
        {"id": "USER-NDT-001", "name": "王工", "orgName": "华测检测有限公司", "role": "ndt", "mobile": "13800000003", "status": "启用", "lastLoginAt": "2026-06-25 17:10:00"},
        {"id": "USER-OWNER-001", "name": "赵经理", "orgName": "华东管网建设公司", "role": "owner", "mobile": "13800000001", "status": "启用", "lastLoginAt": "2026-06-25 16:40:00"},
        {"id": "USER-ADMIN-001", "name": "系统管理员", "orgName": "省特检院平台组", "role": "admin", "mobile": "13800000000", "status": "启用", "lastLoginAt": "2026-06-26 10:00:00"},
    ],
    "permissionMatrix": [
        {"role": role, "label": label, "projectScope": "授权项目", "nodeScope": "授权节点", "actions": actions, "readonly": role == "owner"}
        for role, label, actions in [
            ("inspection", "监检人员", ROLE_ACTIONS["inspection"]),
            ("contractor", "施工方", ROLE_ACTIONS["contractor"]),
            ("ndt", "无损检测", ROLE_ACTIONS["ndt"]),
            ("owner", "建设方", ROLE_ACTIONS["owner"]),
            ("admin", "系统管理员", ROLE_ACTIONS["admin"]),
        ]
    ],
    "nodeTemplates": [{"id": "NT-PIPE-69", "version": "2026.06", "groupName": "压力管道监督检验 69 节点", "nodeCount": 69, "requiredCount": 42, "status": "已发布", "updatedAt": "2026-06-26 08:00:00"}],
    "workflowStateMachines": [{"id": "WF-PIPE-2026", "name": "压力管道资料审查状态机", "version": "2026.06", "states": 12, "transitions": 28, "status": "启用", "updatedAt": "2026-06-26 08:30:00"}],
    "todoRules": [{"id": "TR-001", "name": "退回补正待办", "triggerStatus": "需补正", "assigneeRole": "contractor", "deadlineHours": 48, "enabled": True, "updatedAt": "2026-06-26 08:30:00"}],
    "messageTemplates": [{"id": "MT-001", "scene": "AI审查完成", "channel": "站内信", "titleTemplate": "{nodeName} AI审查完成", "contentTemplate": "请处理 {nodeName} 的 AI 审查结果。", "enabled": True, "updatedAt": "2026-06-26 08:30:00"}],
    "toolSources": [{"id": "TS-OCR-001", "name": "PaddleOCR 文档识别", "toolType": "ocr", "endpoint": "ocr-service:8010", "authMode": "token", "status": "启用", "updatedAt": "2026-06-26 08:30:00"}],
    "fieldMappings": [{"id": "FM-001", "nodeId": 24, "fieldName": "证书编号", "sourceField": "ocr.certificate_no", "targetField": "welder.certificateNo", "required": True, "confidenceThreshold": 0.85, "updatedAt": "2026-06-26 08:30:00"}],
}

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
    tree_nodes = build_tree(PROJECT_ID)
    knowledge_files = build_knowledge_files(DOCUMENTS, BINDINGS, tree_nodes)
    state = {
        "projects": deepcopy(PROJECTS),
        "tree_nodes": tree_nodes,
        "requirements": deepcopy(REQUIREMENTS),
        "documents": deepcopy(DOCUMENTS),
        "versions": deepcopy(VERSIONS),
        "bindings": deepcopy(BINDINGS),
        "evidence_links": deepcopy(EVIDENCE_LINKS),
        "extracted_fields": deepcopy(EXTRACTED_FIELDS),
        "ai_runs": deepcopy(AI_RUNS),
        "review_opinions": deepcopy(REVIEW_OPINIONS),
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
