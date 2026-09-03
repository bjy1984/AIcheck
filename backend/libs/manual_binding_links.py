"""人工挂载的资料也要有证据链接，AI 审查才看得见。

## 为什么必须有

2026-09-03 审计（测试项目3 节点 2「施工单位许可资质」）：节点页显示已提交文件 3 份，
一键分析和节点 AI 复核只用了自动打靶挂上的两份施工图，真正的许可证
（江苏三江压力管道资质.jpg，施工方在界面上「选择环节 + 提交」）被忽略。

根因：审查读的是 node_evidence_links（自动打靶产物），人工挂载只写 node_bindings；
`active_node_document_versions` / 一键分析快照只在**整个项目一条链接都没有**时才回落到
bindings。项目里只要有一份资料被自动打靶过，所有人工挂载就从审查视野里消失。

## 做什么

- `upsert_manual_binding_evidence_links`：已提交（已提交/需补正/已通过）的人工挂载，
  按 (项目, 节点, 资料版本) 补一条 source=manual_binding 的证据链接；同位置已有未驳回的
  链接（自动打靶或更早的人工链接）就不重复建。提交、补正回传、已提交资料改挂节点时调用。
- `submitted_binding_document_versions`：审查上下文按「链接 ∪ 已提交挂载」取活跃资料版本，
  即便老数据没回填链接也不会再漏。
- `document_already_submitted`：资料已进入审查视野时，改挂到别的节点直接继承「已提交」，
  不再退回「草稿挂载」让施工方重新提交（审计的第二个问题）。

人工链接没有页码/bbox（人选的是整份文件），evidence_link_is_locatable 会把它算进
unlocatableConfirmedLinkCount——正式审查引用证据仍需监检从 OCR 字段里选，这是既有语义。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from libs.contracts.responses import server_time

SUBMITTED_BINDING_STATUSES = frozenset({"已提交", "需补正", "已通过"})
REJECTED_BINDING_STATUSES = frozenset({"rejected", "驳回", "已撤回", "已作废", "已删除"})
MANUAL_BINDING_SOURCE = "manual_binding"


def _records(state: dict[str, Any], primary: str, fallback: str | None = None) -> list[dict[str, Any]]:
    rows = state.get(primary)
    if not isinstance(rows, list) and fallback:
        rows = state.get(fallback)
    return [row for row in rows or [] if isinstance(row, dict)]


def _bindings(state: dict[str, Any]) -> list[dict[str, Any]]:
    return _records(state, "bindings", "node_bindings")


def binding_is_submitted(binding: dict[str, Any]) -> bool:
    return str(binding.get("bindingStatus") or "") in SUBMITTED_BINDING_STATUSES


def manual_binding_link_id(project_id: str, node_id: int, document_version_id: str) -> str:
    raw = json.dumps([str(project_id), int(node_id), str(document_version_id)], ensure_ascii=False)
    return "NEL-MB-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12].upper()


def submitted_binding_document_versions(
    state: dict[str, Any], project_id: str, node_id: int
) -> list[dict[str, Any]]:
    """节点上已提交、且指向资料当前版本的人工挂载 → 与证据链接同形状的活跃版本条目。"""
    documents = {
        str(row.get("id") or ""): row
        for row in _records(state, "documents")
        if str(row.get("projectId") or "") == str(project_id)
    }
    active: dict[str, dict[str, Any]] = {}
    for binding in _bindings(state):
        if (
            str(binding.get("projectId") or "") != str(project_id)
            or int(binding.get("nodeId") or 0) != int(node_id)
            or not binding_is_submitted(binding)
        ):
            continue
        document = documents.get(str(binding.get("documentId") or ""))
        if not document:
            continue
        version_id = str(binding.get("documentVersionId") or document.get("currentVersionId") or "")
        if not version_id or str(document.get("currentVersionId") or version_id) != version_id:
            continue
        entry = active.setdefault(
            version_id,
            {
                "documentId": str(document.get("id") or ""),
                "documentVersionId": version_id,
                "mountLinkIds": [],
                "mountRevision": 0,
            },
        )
        binding_id = str(binding.get("id") or "")
        if binding_id and binding_id not in entry["mountLinkIds"]:
            entry["mountLinkIds"].append(binding_id)
        entry["mountRevision"] = max(int(entry["mountRevision"]), int(binding.get("revision") or 0))
    for entry in active.values():
        entry["mountLinkIds"].sort()
    return sorted(active.values(), key=lambda row: row["documentVersionId"])


def document_already_submitted(state: dict[str, Any], project_id: str, document_id: str) -> bool:
    """资料已进入审查视野：资料池已提交，或在任一节点上有已提交的挂载。"""
    document = next(
        (
            row
            for row in _records(state, "documents")
            if str(row.get("id") or "") == str(document_id) and str(row.get("projectId") or "") == str(project_id)
        ),
        None,
    )
    if document and str(document.get("poolSubmissionStatus") or "") == "已提交":
        return True
    return any(
        str(binding.get("projectId") or "") == str(project_id)
        and str(binding.get("documentId") or "") == str(document_id)
        and binding_is_submitted(binding)
        for binding in _bindings(state)
    )


def _review_points(state: dict[str, Any], project_id: str, node_id: int) -> list[dict[str, Any]]:
    admin = state.get("admin_config") if isinstance(state.get("admin_config"), dict) else {}
    project = next(
        (row for row in _records(state, "projects") if str(row.get("id") or "") == str(project_id)),
        {},
    )
    pack_id = str(project.get("businessPackId") or "engineering_inspection_v1")
    return [
        row
        for row in (admin.get("materialReviewPoints") or [])
        if isinstance(row, dict)
        and row.get("enabled", True)
        and int(row.get("nodeId") or 0) == int(node_id)
        and str(row.get("businessPackId") or pack_id) == pack_id
    ]


def resolve_manual_binding_review_point(
    state: dict[str, Any], project_id: str, binding: dict[str, Any], document: dict[str, Any]
) -> dict[str, Any] | None:
    """人工挂载对应的审查要点：先按挂载时选的资料要求（requirementId → 资料类型），
    再按资料自身的分类找同类型要点。要点表（materialReviewPoints）的 id 与旧的
    REQ-xx-xx 不是一套编号，链接只有挂到要点 id 上，资料要求汇总才认。"""
    node_id = int(binding.get("nodeId") or 0)
    points = _review_points(state, project_id, node_id)
    if not points:
        return None
    requirement_id = str(binding.get("requirementId") or "").strip()
    codes: list[str] = []
    if requirement_id:
        for row in _records(state, "requirements", "node_requirements"):
            rid = str(row.get("id") or "")
            if (rid == requirement_id or rid.endswith(":" + requirement_id)) and str(row.get("projectId") or project_id) == str(project_id):
                if row.get("materialTypeCode"):
                    codes.append(str(row["materialTypeCode"]))
                break
    if document.get("materialTypeCode"):
        codes.append(str(document["materialTypeCode"]))
    for code in codes:
        for point in points:
            if str(point.get("materialTypeCode") or "") == code:
                return point
    return None


def _apply_review_point(link: dict[str, Any], point: dict[str, Any] | None, binding: dict[str, Any], document: dict[str, Any]) -> None:
    # 资料要求汇总的 supportStatus 只认「命中/待人工确认/未命中」：人工挂载已确认但没定位，
    # 记「待人工确认」而不是 unmatched，否则要求行显示「未命中」却又列着这份文件。
    link["supportStatus"] = "待人工确认"
    if point:
        link.update(
            {
                "reviewPointId": point.get("id"),
                "reviewContent": point.get("reviewContent") or binding.get("requirementName"),
                "materialTypeCode": point.get("materialTypeCode") or document.get("materialTypeCode"),
                "materialTypeName": point.get("materialTypeName") or document.get("materialTypeName"),
                "materialCategory": point.get("materialCategory") or document.get("materialCategory"),
                "requiredType": point.get("requiredType"),
                "responsibleParty": point.get("responsibleParty"),
            }
        )
    else:
        link.update(
            {
                "reviewPointId": binding.get("requirementId"),
                "reviewContent": binding.get("requirementName") or link.get("nodeName"),
                "materialTypeCode": document.get("materialTypeCode"),
                "materialTypeName": document.get("materialTypeName"),
                "materialCategory": document.get("materialCategory"),
            }
        )


def upsert_manual_binding_evidence_links(
    state: dict[str, Any],
    project_id: str,
    bindings: list[dict[str, Any]],
    *,
    actor_name: str = "人工挂载",
) -> list[dict[str, Any]]:
    """给已提交的人工挂载补证据链接；返回本次新建的链接。幂等。"""
    documents = {
        str(row.get("id") or ""): row
        for row in _records(state, "documents")
        if str(row.get("projectId") or "") == str(project_id)
    }
    nodes = {
        int(row.get("nodeId") or 0): row
        for row in _records(state, "tree_nodes", "project_nodes")
        if str(row.get("projectId") or "") == str(project_id)
    }
    links = state.setdefault("node_evidence_links", [])
    covered: set[tuple[int, str]] = set()
    by_id: dict[str, dict[str, Any]] = {}
    for link in links:
        if not isinstance(link, dict) or str(link.get("projectId") or "") != str(project_id):
            continue
        by_id[str(link.get("id") or "")] = link
        if str(link.get("manualStatus") or "").lower() != "rejected":
            covered.add((int(link.get("nodeId") or 0), str(link.get("documentVersionId") or "")))
    created: list[dict[str, Any]] = []
    now = server_time()
    for binding in bindings:
        if not isinstance(binding, dict) or not binding_is_submitted(binding):
            continue
        if str(binding.get("projectId") or project_id) != str(project_id):
            continue
        node_id = int(binding.get("nodeId") or 0)
        document = documents.get(str(binding.get("documentId") or ""))
        if node_id <= 0 or not document:
            continue
        version_id = str(binding.get("documentVersionId") or document.get("currentVersionId") or "")
        if not version_id or (node_id, version_id) in covered:
            continue
        if str(document.get("currentVersionId") or version_id) != version_id:
            continue  # 挂的是旧版本：审查只看当前版本，链接也不建
        link_id = manual_binding_link_id(project_id, node_id, version_id)
        existing = by_id.get(link_id)
        if existing is not None:
            # 只可能是被驳回过的同一条：人再次提交/挂载即视为重新确认
            existing.update(
                {
                    "manualStatus": "confirmed",
                    "manualStatusLabel": "已确认",
                    "confirmedByName": actor_name,
                    "confirmedAt": now,
                    "manualUpdatedAt": now,
                    "bindingId": binding.get("id"),
                }
            )
            existing.pop("rejectedByName", None)
            existing.pop("rejectedAt", None)
            existing.pop("manualComment", None)
            covered.add((node_id, version_id))
            created.append(existing)
            continue
        node = nodes.get(node_id) or {}
        link = {
            "id": link_id,
            "projectId": str(project_id),
            "businessPackId": node.get("businessPackId"),
            "nodeId": node_id,
            "nodeName": node.get("name") or node.get("nodeName"),
            "ruleId": node.get("ruleId"),
            "reviewPointId": None,
            "reviewContent": None,
            "materialTypeCode": None,
            "materialTypeName": None,
            "materialCategory": None,
            "requiredType": None,
            "responsibleParty": None,
            "documentId": str(document.get("id") or ""),
            "documentVersionId": version_id,
            "fileName": document.get("fileName") or binding.get("fileName"),
            "pageNo": None,
            "bbox": None,
            "fieldName": None,
            "fieldId": None,
            "quotedText": None,
            "matchedEvidenceItems": [],
            "evidenceCoverage": None,
            "supportStatus": "待人工确认",
            "confidence": 1.0,
            "score": None,
            "scoreReasons": ["人工在界面上把整份资料挂到本节点"],
            "evidenceFacts": [],
            "formalEvidenceFactCount": 0,
            # 人选的整份资料算正式证据（否则只是 advisory，资料要求汇总看不见它）；
            # 没有页码/bbox，汇总里记成「已确认但不可定位」，正式引用仍要监检定位字段。
            "formalEvidenceEligible": True,
            "evidenceTier": "manual",
            "manualStatus": "confirmed",
            "manualStatusLabel": "已确认",
            "confirmedByName": actor_name,
            "confirmedAt": now,
            "source": MANUAL_BINDING_SOURCE,
            "bindingId": binding.get("id"),
            "createdAt": now,
        }
        _apply_review_point(link, resolve_manual_binding_review_point(state, project_id, binding, document), binding, document)
        links.insert(0, link)
        by_id[link_id] = link
        covered.add((node_id, version_id))
        created.append(link)
    return created


def refresh_manual_binding_links(state: dict[str, Any], project_id: str | None = None) -> list[dict[str, Any]]:
    """把已有人工链接的审查要点字段按当前要点表重算（回填/要点表变更后用）。"""
    documents = {str(row.get("id") or ""): row for row in _records(state, "documents") if row.get("id")}
    bindings = {str(row.get("id") or ""): row for row in _bindings(state) if row.get("id")}
    changed: list[dict[str, Any]] = []
    for link in _records(state, "node_evidence_links"):
        if link.get("source") != MANUAL_BINDING_SOURCE:
            continue
        pid = str(link.get("projectId") or "")
        if project_id is not None and pid != str(project_id):
            continue
        binding = bindings.get(str(link.get("bindingId") or "")) or {"nodeId": link.get("nodeId")}
        document = documents.get(str(link.get("documentId") or "")) or {}
        before = {key: link.get(key) for key in ("reviewPointId", "materialTypeCode", "formalEvidenceEligible", "supportStatus")}
        link["formalEvidenceEligible"] = True
        _apply_review_point(link, resolve_manual_binding_review_point(state, pid, binding, document), binding, document)
        after = {key: link.get(key) for key in ("reviewPointId", "materialTypeCode", "formalEvidenceEligible", "supportStatus")}
        if before != after:
            link["updatedAt"] = server_time()
            changed.append(link)
    return changed


def bindings_missing_evidence_links(state: dict[str, Any], project_id: str | None = None) -> list[dict[str, Any]]:
    """回填用：已提交、指向当前版本、却没有任何未驳回链接的人工挂载。"""
    documents = {
        str(row.get("id") or ""): row for row in _records(state, "documents") if row.get("id")
    }
    covered: set[tuple[str, int, str]] = {
        (str(link.get("projectId") or ""), int(link.get("nodeId") or 0), str(link.get("documentVersionId") or ""))
        for link in _records(state, "node_evidence_links")
        if str(link.get("manualStatus") or "").lower() != "rejected"
    }
    missing: list[dict[str, Any]] = []
    for binding in _bindings(state):
        pid = str(binding.get("projectId") or "")
        if project_id is not None and pid != str(project_id):
            continue
        if not binding_is_submitted(binding):
            continue
        document = documents.get(str(binding.get("documentId") or ""))
        if not document:
            continue
        version_id = str(binding.get("documentVersionId") or document.get("currentVersionId") or "")
        if not version_id or str(document.get("currentVersionId") or version_id) != version_id:
            continue
        if (pid, int(binding.get("nodeId") or 0), version_id) in covered:
            continue
        missing.append(binding)
    return missing
