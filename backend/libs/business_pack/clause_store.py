from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from typing import Any
from urllib.parse import quote

CLAUSE_STATE_COLLECTIONS = (
    "standard_document_versions",
    "standard_clause_references",
    "standard_clause_locators",
    "standard_clause_packages_db",
    "standard_clause_package_items",
    "project_node_clause_packages",
    "review_run_clause_snapshots",
)


def _stable_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _stable_id(prefix: str, *parts: object) -> str:
    raw = "|".join(str(part) for part in parts)
    return f"{prefix}-{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16].upper()}"


def _release_id(pack: dict[str, Any]) -> str:
    return f"{pack['id']}@{pack['version']}"


def ensure_clause_state(state: dict[str, Any]) -> None:
    for key in CLAUSE_STATE_COLLECTIONS:
        state.setdefault(key, [])


def compile_standard_clause_release(pack: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Compile one immutable business-pack release into database logical rows."""
    result = {key: [] for key in CLAUSE_STATE_COLLECTIONS if key not in {"project_node_clause_packages", "review_run_clause_snapshots"}}
    packages = pack.get("standardClausePackages") or []
    if not packages:
        return result

    release_id = _release_id(pack)
    catalog = pack.get("standardCatalog") or []
    catalog_by_id = {item["id"]: item for item in catalog}
    bindings = pack.get("standardClauseBindings") or []
    binding_by_id = {item["bindingId"]: item for item in bindings}

    for item in catalog:
        result["standard_document_versions"].append(
            {
                "id": f"SDOC-{release_id}-{item['id']}",
                "releaseId": release_id,
                "businessPackId": pack["id"],
                "businessPackVersion": pack["version"],
                "standardRef": item["id"],
                "code": item.get("code"),
                "name": item.get("name"),
                "knowledgeFileId": item.get("knowledgeFileId"),
                "documentVersionId": item.get("documentVersionId"),
                "sourceFile": item.get("sourceFile"),
                "verificationMethod": item.get("verificationMethod"),
                "lifecycleStatus": "published",
            }
        )

    references: dict[tuple[str, str], dict[str, Any]] = {}
    locators: dict[str, dict[str, Any]] = {}
    package_items: list[dict[str, Any]] = []
    package_rows: list[dict[str, Any]] = []

    def clause_reference(raw: dict[str, Any]) -> dict[str, Any]:
        standard_ref = str(raw["standardRef"])
        clause_no = str(raw["clauseNo"])
        key = (standard_ref, clause_no)
        existing = references.get(key)
        if existing:
            return existing
        catalog_item = catalog_by_id[standard_ref]
        reference_id = _stable_id("CREF", release_id, standard_ref, catalog_item.get("documentVersionId"), clause_no)
        reference = {
            "id": reference_id,
            "releaseId": release_id,
            "businessPackId": pack["id"],
            "businessPackVersion": pack["version"],
            "standardRef": standard_ref,
            "clauseNo": clause_no,
            "knowledgeFileId": raw.get("knowledgeFileId") or catalog_item.get("knowledgeFileId"),
            "documentVersionId": raw.get("documentVersionId") or catalog_item.get("documentVersionId"),
            "verificationStatus": raw.get("verificationStatus"),
            "sourcePage": raw.get("sourcePage"),
            "startPage": raw.get("startPage"),
            "endPage": raw.get("endPage"),
            "sourceLocatorId": raw.get("sourceLocatorId"),
            "locatorPrecision": raw.get("locatorPrecision"),
            "locatorIds": [],
            "lifecycleStatus": "published",
        }
        source_locators = raw.get("locators") or []
        if not source_locators:
            raise ValueError(f"{standard_ref} {clause_no} has no source locators")
        for raw_locator in source_locators:
            locator_id = str(raw_locator["locatorId"])
            storage_id = f"{release_id}:{locator_id}"
            locator = {
                "id": storage_id,
                "locatorId": locator_id,
                "releaseId": release_id,
                "businessPackId": pack["id"],
                "businessPackVersion": pack["version"],
                "standardRef": standard_ref,
                "clauseNo": raw_locator.get("clauseNo") or clause_no,
                "knowledgeFileId": reference["knowledgeFileId"],
                "documentVersionId": reference["documentVersionId"],
                "sourcePage": raw_locator.get("sourcePage") or raw_locator.get("startPage"),
                "startPage": raw_locator.get("startPage"),
                "endPage": raw_locator.get("endPage"),
                "precision": raw_locator.get("precision"),
                "verificationStatus": raw_locator.get("verificationStatus"),
                "bbox": raw_locator.get("bbox"),
                "chunkId": raw_locator.get("chunkId"),
            }
            previous = locators.get(storage_id)
            if previous and previous != locator:
                raise ValueError(f"conflicting locator definition: {storage_id}")
            locators[storage_id] = locator
            reference["locatorIds"].append(storage_id)
        references[key] = reference
        return reference

    for package in packages:
        primary = binding_by_id[package["primaryBindingId"]]
        compiled_clauses: list[dict[str, Any]] = []
        raw_items = [(primary, "primary", str(package.get("nodeName") or "直接监检依据"))]
        raw_items.extend(
            (item, "professional", str(item.get("purpose") or "专业执行条款"))
            for item in package.get("professionalClauses") or []
        )
        package_storage_id = f"{release_id}:{package['packageId']}"
        for sort_order, (raw, binding_role, purpose) in enumerate(raw_items, start=1):
            reference = clause_reference(raw)
            binding_id = (
                str(raw.get("bindingId"))
                if binding_role == "primary"
                else _stable_id("PKGBIND", package_storage_id, binding_role, sort_order, reference["id"])
            )
            package_items.append(
                {
                    "id": f"{release_id}:{binding_id}",
                    "bindingId": binding_id,
                    "releaseId": release_id,
                    "businessPackId": pack["id"],
                    "businessPackVersion": pack["version"],
                    "packageId": package_storage_id,
                    "sourceRuleId": package["sourceRuleId"],
                    "nodeId": int(package["nodeId"]),
                    "clauseReferenceId": reference["id"],
                    "bindingRole": binding_role,
                    "purpose": purpose,
                    "applicability": deepcopy(raw.get("applicability") or package.get("applicability")),
                    "sortOrder": sort_order,
                    "lifecycleStatus": "published",
                }
            )
            catalog_item = catalog_by_id[raw["standardRef"]]
            compiled = deepcopy(raw)
            compiled.update(
                {
                    "bindingId": binding_id,
                    "clauseReferenceId": reference["id"],
                    "referenceRole": binding_role,
                    "fixedBinding": True,
                    "purpose": purpose,
                    "standardName": " ".join(
                        value for value in [str(catalog_item.get("code") or ""), str(catalog_item.get("name") or "")] if value
                    ),
                    "sourceFile": catalog_item.get("sourceFile"),
                }
            )
            knowledge_file_id = str(compiled.get("knowledgeFileId") or "")
            for locator in compiled.get("locators") or []:
                page_no = locator.get("sourcePage") or locator.get("startPage")
                locator["previewUrl"] = (
                    f"/api/knowledge/files/{quote(knowledge_file_id, safe='')}/original"
                    f"?disposition=inline#page={int(page_no)}"
                )
            if compiled.get("sourcePage"):
                compiled["previewUrl"] = (
                    f"/api/knowledge/files/{quote(knowledge_file_id, safe='')}/original"
                    f"?disposition=inline#page={int(compiled['sourcePage'])}"
                )
            compiled_clauses.append(compiled)

        compiled_payload = {
            "schemaVersion": "StandardClausePackageSnapshot@1.0.0",
            "releaseId": release_id,
            "businessPackId": pack["id"],
            "businessPackVersion": pack["version"],
            "packageId": package["packageId"],
            "packageStorageId": package_storage_id,
            "sourceRuleId": package["sourceRuleId"],
            "ruleId": package["ruleId"],
            "nodeId": int(package["nodeId"]),
            "nodeName": package.get("nodeName"),
            "applicability": deepcopy(package.get("applicability") or {}),
            "atomicCheckIds": deepcopy(package.get("atomicCheckIds") or []),
            "decisionModel": deepcopy(package.get("decisionModel") or {}),
            "clauses": compiled_clauses,
        }
        snapshot_hash = _stable_hash(compiled_payload)
        compiled_payload["snapshotHash"] = snapshot_hash
        package_rows.append(
            {
                "id": package_storage_id,
                "packageId": package["packageId"],
                "releaseId": release_id,
                "businessPackId": pack["id"],
                "businessPackVersion": pack["version"],
                "sourceRuleId": package["sourceRuleId"],
                "ruleId": package["ruleId"],
                "nodeId": int(package["nodeId"]),
                "nodeName": package.get("nodeName"),
                "snapshotHash": snapshot_hash,
                "compiledPayload": compiled_payload,
                "lifecycleStatus": package.get("lifecycleStatus") or "published",
            }
        )

    result["standard_clause_references"] = list(references.values())
    result["standard_clause_locators"] = list(locators.values())
    result["standard_clause_packages_db"] = package_rows
    result["standard_clause_package_items"] = package_items
    return result


def publish_standard_clause_release(state: dict[str, Any], pack: dict[str, Any]) -> dict[str, int]:
    """Idempotently replace one business-pack release while preserving older releases."""
    ensure_clause_state(state)
    compiled = compile_standard_clause_release(pack)
    release_id = _release_id(pack)
    for key, rows in compiled.items():
        retained = [item for item in state.get(key, []) if item.get("releaseId") != release_id]
        state[key] = retained + deepcopy(rows)
    return {key: len(rows) for key, rows in compiled.items()}


def clause_rule_number(rule_id: Any) -> int | None:
    """R24 -> 24。取不出编号就返回 None，交由调用方按「无法判定」处理。"""
    match = re.match(r"^R(\d+)$", str(rule_id or "").strip())
    return int(match.group(1)) if match else None


def clause_binding_inconsistencies(state: dict[str, Any]) -> list[dict[str, Any]]:
    """找出「内容对、标签错」的项目条款绑定。

    规则重编号后，旧 release 的 packageId/sourceRuleId 用旧编号，而 nodeId 与条款
    内容已是新编号口径——同一条记录里两个编号指向不同规则。判定结果不受影响
    （条款内容是对的），但事后核查无法凭 clausePackageId 定位到真正使用的条款，
    而可溯源正是这个系统的核心价值。

    注意这里判的是「记录自相矛盾」，不是「版本旧」。钉在旧版本但自洽的项目是
    合法的业务选择（业务方明确「标准换版暂不考虑」），不能一并冲掉。
    """
    findings: list[dict[str, Any]] = []
    for item in state.get("project_node_clause_packages") or []:
        if not isinstance(item, dict):
            continue
        node_id = item.get("nodeId")
        try:
            node_number = int(node_id)
        except (TypeError, ValueError):
            continue
        rule_number = clause_rule_number(item.get("sourceRuleId"))
        if rule_number is None or rule_number == node_number:
            continue
        findings.append(
            {
                "projectId": str(item.get("projectId") or ""),
                "nodeId": node_number,
                "sourceRuleId": str(item.get("sourceRuleId") or ""),
                "sourcePackageId": str(item.get("sourcePackageId") or ""),
                "businessPackVersion": str(item.get("businessPackVersion") or ""),
            }
        )
    return findings


def bind_project_node_clause_packages(
    state: dict[str, Any],
    project: dict[str, Any],
    pack: dict[str, Any],
    *,
    bound_at: str | None = None,
) -> int:
    ensure_clause_state(state)
    publish_standard_clause_release(state, pack)
    release_id = _release_id(pack)
    packages = [
        item
        for item in state["standard_clause_packages_db"]
        if item.get("releaseId") == release_id and item.get("lifecycleStatus") == "published"
    ]
    if not packages:
        project_id = str(project["id"])
        state["project_node_clause_packages"] = [
            item
            for item in state["project_node_clause_packages"]
            if item.get("projectId") != project_id
        ]
        return 0
    project_id = str(project["id"])
    existing_by_node = {
        int(item["nodeId"]): item
        for item in state["project_node_clause_packages"]
        if item.get("projectId") == project_id
    }
    active_node_ids: set[int] = set()
    for package in packages:
        node_id = int(package["nodeId"])
        active_node_ids.add(node_id)
        record = {
            "id": f"PNCP-{project_id}-{node_id}",
            "projectId": project_id,
            "nodeId": node_id,
            "packageId": package["id"],
            "sourcePackageId": package["packageId"],
            "sourceRuleId": package["sourceRuleId"],
            "businessPackId": pack["id"],
            "businessPackVersion": pack["version"],
            "packageSnapshotHash": package["snapshotHash"],
            "boundAt": bound_at or project.get("updatedAt"),
            "lifecycleStatus": "active",
        }
        existing = existing_by_node.get(node_id)
        if existing:
            existing.clear()
            existing.update(record)
        else:
            state["project_node_clause_packages"].append(record)
    state["project_node_clause_packages"] = [
        item
        for item in state["project_node_clause_packages"]
        if item.get("projectId") != project_id
        or int(item.get("nodeId") or 0) in active_node_ids
    ]
    return len(packages)


def resolve_project_node_clause_package(
    state: dict[str, Any], project_id: str, node_id: int
) -> dict[str, Any] | None:
    ensure_clause_state(state)
    binding = next(
        (
            item
            for item in state["project_node_clause_packages"]
            if item.get("projectId") == project_id
            and int(item.get("nodeId") or 0) == int(node_id)
            and item.get("lifecycleStatus") == "active"
        ),
        None,
    )
    if not binding:
        return None
    package = next(
        (item for item in state["standard_clause_packages_db"] if item.get("id") == binding.get("packageId")),
        None,
    )
    if not package or package.get("snapshotHash") != binding.get("packageSnapshotHash"):
        return None
    return deepcopy(package)


def clause_package_snapshot_for_project_node(
    state: dict[str, Any], project_id: str, node_id: int
) -> dict[str, Any] | None:
    package = resolve_project_node_clause_package(state, project_id, node_id)
    return deepcopy(package.get("compiledPayload")) if package else None


def freeze_review_run_clause_snapshot(
    state: dict[str, Any],
    *,
    review_run_id: str,
    project_id: str,
    node_id: int,
    snapshot: dict[str, Any] | None = None,
    created_at: str | None = None,
) -> dict[str, Any] | None:
    ensure_clause_state(state)
    existing = next(
        (item for item in state["review_run_clause_snapshots"] if item.get("reviewRunId") == review_run_id),
        None,
    )
    if existing:
        return existing
    payload = deepcopy(snapshot) if snapshot else clause_package_snapshot_for_project_node(state, project_id, node_id)
    if not payload:
        return None
    record = {
        "id": f"RRCS-{review_run_id}",
        "reviewRunId": review_run_id,
        "projectId": project_id,
        "nodeId": int(node_id),
        "packageId": payload.get("packageStorageId"),
        "sourcePackageId": payload.get("packageId"),
        "businessPackId": payload.get("businessPackId"),
        "businessPackVersion": payload.get("businessPackVersion"),
        "packageSnapshotHash": payload.get("snapshotHash") or _stable_hash(payload),
        "snapshotPayload": payload,
        "createdAt": created_at,
    }
    state["review_run_clause_snapshots"].append(record)
    return record


def review_run_clause_snapshot(state: dict[str, Any], review_run_id: str) -> dict[str, Any] | None:
    ensure_clause_state(state)
    record = next(
        (item for item in state["review_run_clause_snapshots"] if item.get("reviewRunId") == review_run_id),
        None,
    )
    return deepcopy(record.get("snapshotPayload")) if record else None
