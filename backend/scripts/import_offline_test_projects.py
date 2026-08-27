from __future__ import annotations

import hashlib
import json
import mimetypes
import argparse
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from libs.business_pack import business_pack_snapshot
from libs.business_pack.clause_store import bind_project_node_clause_packages
from libs.business_pack.loader import build_project_requirements, build_project_tree
from libs.business_pack import load_business_pack
from libs.db.repository import flush_state, load_state, postgres_persistence_configured, repo


PROJECTS = {
    "test": {
        "projectId": "P-TEST-OCR-001",
        "projectName": "TEST项目一｜珠海海瑞德制药压力管道安装",
        "ocrDirectory": "output/test_qwen_classification_20260824/ocr",
    },
    "test2": {
        "projectId": "P-TEST-OCR-002",
        "projectName": "TEST项目二｜珠海新建化工区管道气站",
        "ocrDirectory": "output/two_project_node_eval_20260824/test2/ocr",
    },
}


@dataclass(frozen=True)
class ImportFile:
    file_id: str
    document_id: str
    version_id: str
    relative_path: str
    material_type_codes: tuple[str, ...]
    uploader_user_id: str
    uploader_name: str
    uploader_org: str
    source_path: Path
    ocr_path: Path


@dataclass(frozen=True)
class ImportBinding:
    binding_id: str
    project_id: str
    node_id: int
    node_name: str
    file_id: str
    document_id: str
    version_id: str
    material_type_codes: tuple[str, ...]
    evidence_tier: str


@dataclass(frozen=True)
class ProjectImportPlan:
    repo_root: Path
    project_id: str
    project_name: str
    nodes: tuple[dict, ...]
    files: tuple[ImportFile, ...]
    bindings: tuple[ImportBinding, ...]


def build_project_import_plan(repo_root: Path, project_code: str) -> ProjectImportPlan:
    repo_root = Path(repo_root).resolve()
    if project_code not in PROJECTS:
        raise ValueError(f"unsupported project code: {project_code}")
    metadata = PROJECTS[project_code]
    review_input = json.loads(
        (repo_root / "output/two_project_ai_review_20260825/review_input.json").read_text(
            encoding="utf-8"
        )
    )
    project_input = next(
        (item for item in review_input.get("projects") or [] if item.get("project") == project_code),
        None,
    )
    if not project_input:
        raise ValueError(f"project input is missing: {project_code}")
    targeting = json.loads(
        (
            repo_root
            / "output/two_project_node_eval_20260824/node_targeting_results.json"
        ).read_text(encoding="utf-8")
    )
    targeting_project = next(
        (item for item in targeting.get("projects") or [] if item.get("project") == project_code),
        None,
    )
    if not targeting_project:
        raise ValueError(f"file manifest is missing: {project_code}")

    material_codes_by_file: dict[str, set[str]] = {}
    bindings: list[ImportBinding] = []
    for node in project_input.get("nodes") or []:
        node_id = int(node["nodeId"])
        for index, linked in enumerate(node.get("linkedFiles") or [], start=1):
            file_id = str(linked["fileId"])
            material_codes = tuple(sorted(str(code) for code in linked.get("materialTypeCodes") or []))
            material_codes_by_file.setdefault(file_id, set()).update(material_codes)
            digest = hashlib.sha256(f"{project_code}:{node_id}:{file_id}:{index}".encode()).hexdigest()[:16].upper()
            bindings.append(
                ImportBinding(
                    binding_id=f"BIND-OFFLINE-{digest}",
                    project_id=str(metadata["projectId"]),
                    node_id=node_id,
                    node_name=str(node.get("nodeName") or f"节点 {node_id}"),
                    file_id=file_id,
                    document_id=f"DOC-OFFLINE-{file_id}",
                    version_id=f"DV-OFFLINE-{file_id}-V1",
                    material_type_codes=material_codes,
                    evidence_tier=str(linked.get("tier") or "advisory"),
                )
            )

    ocr_root = repo_root / str(metadata["ocrDirectory"])
    files: list[ImportFile] = []
    for item in targeting_project.get("files") or []:
        file_id = str(item["caseId"])
        relative_path = str(item.get("relativePath") or file_id)
        source_path = repo_root / project_code / relative_path
        ocr_path = ocr_root / f"{file_id}.md"
        local_storage_key(repo_root, source_path)
        local_storage_key(repo_root, ocr_path)
        material_codes = set(str(code) for code in item.get("predictedMaterialTypeCodes") or [])
        material_codes.update(material_codes_by_file.get(file_id, set()))
        is_ndt = (
            relative_path.startswith("10、")
            or relative_path.startswith("11.")
            or "检测方案" in relative_path
            or any(code.startswith("ndt_") for code in material_codes)
        )
        files.append(
            ImportFile(
                file_id=file_id,
                document_id=f"DOC-OFFLINE-{file_id}",
                version_id=f"DV-OFFLINE-{file_id}-V1",
                relative_path=relative_path,
                material_type_codes=tuple(sorted(material_codes)),
                uploader_user_id="USER-NDT-001" if is_ndt else "USER-CONTRACTOR-001",
                uploader_name="王工" if is_ndt else "李工",
                uploader_org="粤检无损检测" if is_ndt else "粤海安装工程有限公司",
                source_path=source_path,
                ocr_path=ocr_path,
            )
        )

    return ProjectImportPlan(
        repo_root=repo_root,
        project_id=str(metadata["projectId"]),
        project_name=str(metadata["projectName"]),
        nodes=tuple(project_input.get("nodes") or []),
        files=tuple(files),
        bindings=tuple(bindings),
    )


def local_storage_key(repo_root: Path, source_path: Path) -> str:
    root = Path(repo_root).resolve()
    source = Path(source_path).resolve()
    try:
        relative = source.relative_to(root)
    except ValueError as error:
        raise ValueError(f"source path is outside repository root: {source}") from error
    return f"local://{relative.as_posix()}"


def require_postgres_persistence(configured: bool) -> None:
    if not configured:
        raise RuntimeError("PostgreSQL persistence is required for offline test project import")


def apply_project_import_plan(
    state: dict[str, list[dict[str, Any]]],
    plan: ProjectImportPlan,
    pack: dict[str, Any],
) -> dict[str, int]:
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    collection_names = (
        "projects",
        "tree_nodes",
        "requirements",
        "project_members",
        "project_node_clause_packages",
        "documents",
        "versions",
        "ocr_parse_results",
        "bindings",
        "node_evidence_links",
        "knowledge_files",
        "knowledge_tasks",
    )
    for name in collection_names:
        state.setdefault(name, [])
    stale_document_ids = {
        str(row.get("id") or "")
        for row in state["documents"]
        if str(row.get("projectId") or "") == plan.project_id
        and row.get("scenarioTag") == "offline-test-projects-v1"
    }
    for name in collection_names:
        if name == "project_node_clause_packages":
            continue
        state[name][:] = [
            row
            for row in state[name]
            if not (
                str(row.get("projectId") or row.get("id") or "") == plan.project_id
                and row.get("scenarioTag") == "offline-test-projects-v1"
            )
        ]
    state["versions"][:] = [
        row
        for row in state["versions"]
        if not (
            str(row.get("documentId") or "") in stale_document_ids
            and row.get("scenarioTag") == "offline-test-projects-v1"
        )
    ]

    def upsert(collection: str, item: dict[str, Any]) -> None:
        rows = state[collection]
        rows[:] = [
            row
            for row in rows
            if not (
                str(row.get("id") or "") == str(item["id"])
                and (
                    collection != "requirements"
                    or str(row.get("projectId") or "") == str(item.get("projectId") or "")
                )
            )
        ]
        rows.append(item)

    project = {
        "id": plan.project_id,
        "code": plan.project_id,
        "name": plan.project_name,
        "type": str(pack.get("projectType") or pack.get("name") or "工业管道"),
        "region": "珠海",
        "ownerOrgName": "测试建设单位",
        "contractorOrgName": "粤海安装工程有限公司",
        "ndtOrgName": "粤检无损检测",
        "inspectionOrgName": "省特检院一部",
        "businessPackId": pack["id"],
        "businessPackVersion": pack["version"],
        "domainType": pack["domainType"],
        "businessPackSnapshotHash": pack["snapshotHash"],
        "businessPackSnapshot": business_pack_snapshot(pack),
        "status": "AI 预审中",
        "todoCount": 0,
        "messageCount": 0,
        "currentNodeId": 24,
        "updatedAt": now,
        "actions": ["project:view", "project:authorize-member"],
        "revision": 1,
        "scenarioTag": "offline-test-projects-v1",
    }
    upsert("projects", project)

    project_nodes = build_project_tree(plan.project_id, pack)
    requirements = build_project_requirements(pack, project_id=plan.project_id)
    counts_by_node: dict[int, set[str]] = {}
    for binding in plan.bindings:
        counts_by_node.setdefault(binding.node_id, set()).add(binding.document_id)
    for node in project_nodes:
        node_id = int(node["nodeId"])
        node.update(
            {
                "status": "待人工确认" if counts_by_node.get(node_id) else "待提交",
                "fileCount": len(counts_by_node.get(node_id, set())),
                "updatedAt": now,
                "scenarioTag": "offline-test-projects-v1",
            }
        )
        upsert("tree_nodes", node)
    for requirement in requirements:
        requirement.update({"updatedAt": now, "scenarioTag": "offline-test-projects-v1"})
        upsert("requirements", requirement)
    bind_project_node_clause_packages(state, project, pack, bound_at=now)

    roles = {
        "inspection": ("USER-INSPECTION-001", "张工", "省特检院一部"),
        "contractor": ("USER-CONTRACTOR-001", "李工", "粤海安装工程有限公司"),
        "ndt": ("USER-NDT-001", "王工", "粤检无损检测"),
        "owner": ("USER-OWNER-001", "赵经理", "测试建设单位"),
    }
    node_scope = [int(node["nodeId"]) for node in pack["nodeTemplates"]]
    role_definitions = {str(role["code"]): role for role in pack["roles"]}
    for role, (user_id, name, org_name) in roles.items():
        upsert(
            "project_members",
            {
                "id": f"PM-{role.upper()}-{plan.project_id}",
                "projectId": plan.project_id,
                "userId": user_id,
                "name": name,
                "orgName": org_name,
                "role": role,
                "nodeScope": node_scope,
                "actions": list(role_definitions[role]["actions"]),
                "status": "启用",
                "updatedAt": now,
                "revision": 1,
                "scenarioTag": "offline-test-projects-v1",
            },
        )

    requirement_by_node_and_type: dict[tuple[int, str], dict[str, Any]] = {}
    for requirement in requirements:
        key = (int(requirement.get("nodeId") or 0), str(requirement.get("materialTypeCode") or ""))
        requirement_by_node_and_type.setdefault(key, requirement)

    file_by_id = {item.file_id: item for item in plan.files}
    for item in plan.files:
        storage_key = local_storage_key(plan.repo_root, item.source_path)
        local_storage_key(plan.repo_root, item.ocr_path)
        raw = item.source_path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        ocr_text = item.ocr_path.read_text(encoding="utf-8")
        material_type = item.material_type_codes[0] if item.material_type_codes else "generic_review_material"
        upsert(
            "documents",
            {
                "id": item.document_id,
                "projectId": plan.project_id,
                "businessPackId": pack["id"],
                "fileName": Path(item.relative_path).name,
                "originalFileName": Path(item.relative_path).name,
                "fileType": mimetypes.guess_type(item.source_path.name)[0] or "application/octet-stream",
                "fileSize": len(raw),
                "sourceOrgName": item.uploader_org,
                "uploaderName": item.uploader_name,
                "uploaderUserId": item.uploader_user_id,
                "currentVersionId": item.version_id,
                "currentOcrStatus": "已完成",
                "fileStatus": "已提交",
                "materialTypeCode": material_type,
                "materialCategory": material_type,
                "storageKey": storage_key,
                "bodyUploaded": True,
                "sourceRelativePath": item.relative_path,
                "updatedAt": now,
                "actions": ["file:view", "file:bind", "file:preview", "file:download"],
                "scenarioTag": "offline-test-projects-v1",
            },
        )
        upsert(
            "versions",
            {
                "id": item.version_id,
                "documentId": item.document_id,
                "versionNo": "V1",
                "hash": f"sha256-{digest}",
                "contentHash": f"sha256:{digest}",
                "fileSize": len(raw),
                "storageKey": storage_key,
                "storageBucket": "local",
                "ocrStatus": "已完成",
                "sliceStatus": "未切片",
                "vectorStatus": "未向量化",
                "uploaderName": item.uploader_name,
                "uploadTime": now,
                "isCurrent": True,
                "scenarioTag": "offline-test-projects-v1",
            },
        )
        parse_id = f"OCR-OFFLINE-{item.file_id}"
        upsert(
            "ocr_parse_results",
            {
                "id": parse_id,
                "parseResultId": parse_id,
                "projectId": plan.project_id,
                "documentId": item.document_id,
                "documentVersionId": item.version_id,
                "storageKey": storage_key,
                "fileName": Path(item.relative_path).name,
                "status": "success",
                "profileId": "offline_full_markdown_v1",
                "engineVersion": "offline-evaluation-import-v1",
                "fields": [],
                "tables": [],
                "seals": [],
                "fragments": [
                    {
                        "id": f"FRAGMENT-OFFLINE-{item.file_id}",
                        "pageNo": 1,
                        "text": ocr_text,
                        "source": "full_mineru_markdown",
                        "confidence": 1.0,
                    }
                ],
                "createdAt": now,
                "updatedAt": now,
                "scenarioTag": "offline-test-projects-v1",
            },
        )
        upsert(
            "knowledge_files",
            {
                "id": f"KF-{item.document_id}",
                "fileName": Path(item.relative_path).name,
                "sourceId": "KS-PROJECT-FILE",
                "sourceName": "项目文件知识库",
                "projectId": plan.project_id,
                "projectName": plan.project_name,
                "documentId": item.document_id,
                "documentVersionId": item.version_id,
                "materialCategory": material_type,
                "ocrStatus": "已完成",
                "sliceStatus": "未切片",
                "vectorStatus": "未向量化",
                "chunkCount": 0,
                "vectorCount": 0,
                "updatedAt": now,
                "scenarioTag": "offline-test-projects-v1",
                "actions": ["knowledge:view", "knowledge:reindex"],
            },
        )

    for item in plan.bindings:
        file_item = file_by_id[item.file_id]
        primary_type = item.material_type_codes[0] if item.material_type_codes else "generic_review_material"
        requirement = requirement_by_node_and_type.get((item.node_id, primary_type))
        binding = {
            "id": item.binding_id,
            "projectId": plan.project_id,
            "nodeId": item.node_id,
            "nodeName": item.node_name,
            "documentId": item.document_id,
            "documentVersionId": item.version_id,
            "fileName": Path(file_item.relative_path).name,
            "versionNo": "V1",
            "usage": "离线测试资料完整导入",
            "sourceOrgName": file_item.uploader_org,
            "bindingStatus": "已提交",
            "boundByName": file_item.uploader_name,
            "boundAt": now,
            "materialTypeCode": primary_type,
            "requirementId": (requirement or {}).get("id"),
            "requirementName": (requirement or {}).get("materialTypeName") or (requirement or {}).get("name"),
            "actions": ["file:view", "file:preview", "file:download"],
            "scenarioTag": "offline-test-projects-v1",
        }
        upsert("bindings", binding)
        upsert(
            "node_evidence_links",
            {
                **binding,
                "id": f"NEL-{item.binding_id}",
                "evidenceTier": item.evidence_tier,
                "manualStatus": "confirmed",
                "manualStatusLabel": "已确认",
                "supportStatus": "已确认",
                "confidence": 1.0,
                "quotedText": "已导入完整 OCR 文本，供监检人员复核。",
                "formalEvidenceEligible": item.evidence_tier == "formal",
                "revision": 1,
            },
        )

    return {
        "projectCount": 1,
        "nodeCount": len(project_nodes),
        "requirementCount": len(requirements),
        "fileCount": len(plan.files),
        "bindingCount": len(plan.bindings),
        "memberCount": len(roles),
    }


IMPORT_STATE_KEYS = {
    "projects",
    "tree_nodes",
    "requirements",
    "project_members",
    "project_node_clause_packages",
    "documents",
    "versions",
    "ocr_parse_results",
    "bindings",
    "node_evidence_links",
    "knowledge_files",
    "knowledge_tasks",
}


def import_projects(repo_root: Path, project_codes: list[str], *, apply: bool) -> list[dict[str, Any]]:
    plans = [build_project_import_plan(repo_root, code) for code in project_codes]
    if not apply:
        return [
            {
                "projectCode": code,
                "projectId": plan.project_id,
                "projectName": plan.project_name,
                "nodeCount": len(plan.nodes),
                "fileCount": len(plan.files),
                "bindingCount": len(plan.bindings),
                "mode": "dry-run",
            }
            for code, plan in zip(project_codes, plans, strict=True)
        ]
    require_postgres_persistence(postgres_persistence_configured())
    load_state()
    pack = load_business_pack("engineering_inspection_v1")
    results = []
    for code, plan in zip(project_codes, plans, strict=True):
        result = apply_project_import_plan(repo.state, plan, pack)
        results.append(
            {
                "projectCode": code,
                "projectId": plan.project_id,
                "projectName": plan.project_name,
                **result,
                "mode": "applied",
            }
        )
    flush_state(selected_state_keys=IMPORT_STATE_KEYS)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import the complete test/test2 offline corpus into the live workbench."
    )
    parser.add_argument(
        "--project-code",
        action="append",
        choices=sorted(PROJECTS),
        help="Project code to import. Repeat to import both; defaults to both.",
    )
    parser.add_argument("--repo-root", type=Path, default=WORKSPACE_ROOT)
    parser.add_argument("--apply", action="store_true", help="Persist the import. Default is dry-run.")
    args = parser.parse_args()
    codes = args.project_code or sorted(PROJECTS)
    result = import_projects(args.repo_root, codes, apply=args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
