from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from libs.project_analysis.prompt import clean_project_ocr_text
from libs.review_evidence import build_review_evidence_package

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


GENERIC_PROMPT = """# 单工程 AI 全审查编排 Prompt

本 Prompt 用于编排一个工程的节点级无损证据审查。每次模型调用只处理一个业务节点的一个 EvidenceShard；不得把整个工程压入单次上下文，不得跳过 manifest 中列出的 shard。

## 强制规则

1. 项目 manifest 是本次审查范围的权威清单。
2. 每个节点必须读取其 node manifest 和全部 shard。
3. 节点输入必须包含该节点截至 EvidenceSnapshot 的全部当前有效历史挂接资料，不能只审最后上传的文件。
4. shard 大小只控制模型调用次数，不能删除 OCR 原文、表格、字段、印章或证据链接。
5. 只有节点 coveragePassed=true 且全部 shard 执行成功后，才能聚合节点结果。
6. FindingDraft 必须保留 projectId、nodeId、reviewRunId 和 evidenceRefs，并始终 requiresHumanConfirmation=true。
7. 所有结果仅为监检审查草稿，不得自动改变正式业务状态。
"""


MEGA_REVIEW_SYSTEM_PROMPT = """你是压力管道安装工程监督检验 AI 审查代理。

你将收到一个工程中所有有挂接资料业务节点的审查规则、资料要求、节点—文件引用，以及项目级唯一 OCR 文件语料库。请在同一次模型调用中完成全部节点审查，但必须保持各节点证据边界，禁止把仅由其他节点引用的文件用于当前节点结论。

强制要求：
1. Resolve every node.fileRefs[].fileId against project.fileCorpus before reviewing that node. Only use the resolved fileCorpus.fullOcrText, node rules and material requirements; do not invent document content, organizations, people, dates, identifiers, scopes, grades, parameters, seals or conclusions.
2. criteria、checkMethod 和 configuredRequirements 是审查依据，不是已被证据证明的事实。
3. 后上传资料与此前资料已经共同包含在当前节点 fileRefs 中，必须解析全部引用后整体判断。
4. 每条 Finding 都必须保留 projectId、nodeId、findingType、severity、title、description、confidence、suggestedAction、evidenceRefs、ruleRefs、groundingStatus、unsupportedClaims 和 requiresHumanConfirmation。
5. evidenceRefs 只能引用当前节点 fileRefs 中真实存在并能在 project.fileCorpus 解析到的 fileId、documentVersionId、fileName；quotedText 必须逐字存在于解析后的 fullOcrText。
6. 没有直接证据时 evidenceRefs 使用空数组，groundingStatus 必须为 insufficient_evidence，suggestedAction 必须为 human_confirm。
7. 不得自动批准、退回、下发整改、关闭整改、归档或改变正式业务状态；所有结果都必须 requiresHumanConfirmation=true。
8. 只输出一个符合 outputSchema 的合法 JSON 对象，不输出 Markdown 围栏、前言、解释或结尾。
"""


MEGA_REVIEW_OUTPUT_SCHEMA = {
    "schemaVersion": "AIAllReviewResult@2.0.0",
    "projectId": "string",
    "projectCode": "string",
    "projectName": "string",
    "nodeReviews": [
        {
            "nodeId": "number",
            "nodeName": "string",
            "reviewResult": "supported|partially_supported|insufficient_evidence|conflict|mismatch",
            "supportSummary": "string",
            "missingEvidence": ["string"],
            "conflicts": ["string"],
            "risks": ["string"],
            "recommendations": ["string"],
            "findings": [
                {
                    "findingType": "stable_short_english_category",
                    "severity": "low|medium|high|critical",
                    "title": "string",
                    "description": "string",
                    "confidence": "0..1",
                    "suggestedAction": "human_confirm|request_correction",
                    "evidenceRefs": [
                        {
                            "fileId": "current_node_linked_file_id",
                            "documentVersionId": "current_node_document_version_id",
                            "fileName": "current_node_file_name",
                            "pageNo": "number_or_null",
                            "quotedText": "verbatim_text_from_fullOcrText",
                        }
                    ],
                    "ruleRefs": [
                        {"source": "criteria|checkMethod", "text": "verbatim_rule_text"}
                    ],
                    "kbRefs": [],
                    "groundingStatus": "grounded|insufficient_evidence",
                    "unsupportedClaims": ["string"],
                    "requiresHumanConfirmation": True,
                }
            ],
        }
    ],
    "projectSummary": {
        "supportedNodeCount": "number",
        "partialNodeCount": "number",
        "insufficientNodeCount": "number",
        "conflictNodeCount": "number",
        "mismatchNodeCount": "number",
        "humanReviewNodeCount": "number",
        "priorityRisks": ["string"],
        "priorityManualActions": ["string"],
    },
    "disclaimer": "以上内容仅作为监检审查提示，不替代最终人工结论。",
}


def _json_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _without_volatile_times(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_volatile_times(nested)
            for key, nested in value.items()
            if key not in {"createdAt", "updatedAt"}
        }
    if isinstance(value, list):
        return [_without_volatile_times(item) for item in value]
    return value


def _project_input(repo_root: Path, project_code: str) -> dict[str, Any]:
    review_input = _read_json(
        repo_root / "output/two_project_ai_review_20260825/review_input.json"
    )
    project = next(
        (row for row in review_input.get("projects") or [] if row.get("project") == project_code),
        None,
    )
    if not project:
        raise ValueError(f"Unknown project in review_input.json: {project_code}")
    return project


def _file_names(repo_root: Path, project_code: str) -> dict[str, str]:
    targeting = _read_json(
        repo_root / "output/two_project_node_eval_20260824/node_targeting_results.json"
    )
    project = next(
        (row for row in targeting.get("projects") or [] if row.get("project") == project_code),
        None,
    )
    if not project:
        return {}
    return {
        str(row.get("caseId")): str(row.get("relativePath") or row.get("caseId"))
        for row in project.get("files") or []
        if row.get("caseId")
    }


def _linked_nodes_with_full_ocr(
    repo_root: Path, project_code: str
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    project = _project_input(repo_root, project_code)
    file_names = _file_names(repo_root, project_code)
    ocr_directory = repo_root / str(PROJECTS[project_code]["ocrDirectory"])
    nodes: list[dict[str, Any]] = []
    file_corpus: dict[str, dict[str, Any]] = {}
    for source_node in project.get("nodes") or []:
        source_files = source_node.get("linkedFiles")
        if not isinstance(source_files, list) or not source_files:
            continue
        node = {
            key: _without_volatile_times(value)
            for key, value in source_node.items()
            if key != "linkedFiles"
        }
        file_refs: list[dict[str, Any]] = []
        for source_file in source_files:
            file_id = str(source_file.get("fileId") or "")
            ocr_path = ocr_directory / f"{file_id}.md"
            if not ocr_path.exists():
                raise FileNotFoundError(f"Full OCR markdown is missing: {ocr_path}")
            source_text = ocr_path.read_text(encoding="utf-8")
            cleaned_text = clean_project_ocr_text(source_text)
            metadata = {
                "fileId": file_id,
                "documentVersionId": f"DV-OFFLINE-{file_id}-V1",
                "fileName": file_names.get(file_id) or file_id,
                "materialTypeCodes": source_file.get("materialTypeCodes") or [],
                "tier": source_file.get("tier") or "advisory",
            }
            file_refs.append(metadata)
            if file_id not in file_corpus:
                file_corpus[file_id] = {
                    **metadata,
                    "sourceContentHash": "sha256:"
                    + hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
                    "cleanedContentHash": "sha256:"
                    + hashlib.sha256(cleaned_text.encode("utf-8")).hexdigest(),
                    "fullOcrText": cleaned_text,
                }
        node["fileRefs"] = file_refs
        nodes.append(node)
    return nodes, file_corpus


def build_project_mega_request(
    *, repo_root: Path, project_code: str
) -> dict[str, Any]:
    if project_code not in PROJECTS:
        raise ValueError(f"Unsupported project code: {project_code}")
    repo_root = Path(repo_root).resolve()
    metadata = PROJECTS[project_code]
    nodes, file_corpus = _linked_nodes_with_full_ocr(repo_root, project_code)
    payload = {
        "task": "Review every included business node in this project in one response.",
        "requirements": [
            "nodeReviews must contain exactly one result for every project.nodes item and no other node.",
            "Use only fileCorpus entries referenced by the current node.fileRefs.",
            "Resolve every node.fileRefs[].fileId against project.fileCorpus before reviewing the node.",
            "Read every resolved fileCorpus.fullOcrText completely; do not use evidenceExcerpts or omit trailing content.",
            "Preserve distinct findings and explicit conflicts; do not collapse minority findings.",
            "Every finding requires human confirmation and cannot change formal business status.",
        ],
        "project": {
            "projectCode": project_code,
            "projectId": metadata["projectId"],
            "projectName": metadata["projectName"],
            "includedNodeCount": len(nodes),
            "nodes": nodes,
            "fileCorpus": file_corpus,
        },
        "outputSchema": MEGA_REVIEW_OUTPUT_SCHEMA,
    }
    return {
        "model": "review-chat",
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": MEGA_REVIEW_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            },
        ],
    }


def export_project_mega_prompt(
    *, repo_root: Path, project_code: str, output_root: Path
) -> dict[str, Any]:
    request = build_project_mega_request(
        repo_root=repo_root,
        project_code=project_code,
    )
    output_root = Path(output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    metadata = PROJECTS[project_code]
    request_json = json.dumps(request, ensure_ascii=False, indent=2)
    output_path = output_root / f"llm_mega_prompt_{project_code}.md"
    output_path.write_text(
        "\n".join(
            [
                f"# {project_code} 工程 AI 全审查 Prompt",
                "",
                f"工程：{metadata['projectName']}",
                "",
                f"工程 ID：{metadata['projectId']}",
                "",
                "## LLM 请求",
                "",
                "`````json",
                request_json,
                "`````",
                "",
            ]
        ),
        encoding="utf-8",
    )
    payload = json.loads(request["messages"][1]["content"])
    unique_file_ids = {
        file_ref["fileId"]
        for node in payload["project"]["nodes"]
        for file_ref in node["fileRefs"]
    }
    file_reference_count = sum(
        len(node["fileRefs"]) for node in payload["project"]["nodes"]
    )
    return {
        "projectCode": project_code,
        "projectId": metadata["projectId"],
        "includedNodeCount": payload["project"]["includedNodeCount"],
        "uniqueFileCount": len(unique_file_ids),
        "fileReferenceCount": file_reference_count,
        "estimatedInputTokens": max(
            1,
            sum(len(message["content"]) for message in request["messages"]) // 4,
        ),
        "promptPath": str(output_path),
        "request": request,
    }


def _offline_state(repo_root: Path, project_code: str, project: dict[str, Any]) -> dict[str, Any]:
    metadata = PROJECTS[project_code]
    ocr_directory = repo_root / str(metadata["ocrDirectory"])
    file_names = _file_names(repo_root, project_code)
    linked_nodes = [
        node
        for node in project.get("nodes") or []
        if isinstance(node.get("linkedFiles"), list) and node.get("linkedFiles")
    ]
    linked_file_ids = sorted(
        {
            str(file_row.get("fileId"))
            for node in linked_nodes
            for file_row in node.get("linkedFiles") or []
            if file_row.get("fileId")
        }
    )
    state: dict[str, Any] = {
        "documents": [],
        "document_versions": [],
        "versions": [],
        "node_evidence_links": [],
        "ocr_parse_results": [],
        "extracted_fields": [],
        "evidence_links": [],
    }
    for file_id in linked_file_ids:
        markdown_path = ocr_directory / f"{file_id}.md"
        if not markdown_path.exists():
            raise FileNotFoundError(f"Full OCR markdown is missing: {markdown_path}")
        markdown = markdown_path.read_text(encoding="utf-8")
        document_id = f"DOC-OFFLINE-{file_id}"
        version_id = f"DV-OFFLINE-{file_id}-V1"
        content_hash = "sha256:" + hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        document = {
            "id": document_id,
            "projectId": metadata["projectId"],
            "fileName": file_names.get(file_id) or file_id,
            "currentVersionId": version_id,
        }
        version = {
            "id": version_id,
            "documentId": document_id,
            "contentHash": content_hash,
        }
        state["documents"].append(document)
        state["document_versions"].append(version)
        state["versions"].append(version)
        state["ocr_parse_results"].append(
            {
                "id": f"OCR-OFFLINE-{file_id}",
                "parseResultId": f"OCR-OFFLINE-{file_id}",
                "documentVersionId": version_id,
                "artifactHash": content_hash,
                "status": "success",
                "fields": [],
                "tables": [],
                "seals": [],
                "fragments": [
                    {
                        "id": f"FRAGMENT-OFFLINE-{file_id}",
                        "pageNo": 1,
                        "text": markdown,
                        "source": "full_mineru_markdown",
                        "confidence": 1.0,
                    }
                ],
            }
        )
    documents_by_file_id = {
        row["id"].removeprefix("DOC-OFFLINE-"): row for row in state["documents"]
    }
    for node in linked_nodes:
        for index, file_row in enumerate(node.get("linkedFiles") or [], start=1):
            file_id = str(file_row.get("fileId") or "")
            document = documents_by_file_id[file_id]
            state["node_evidence_links"].append(
                {
                    "id": f"NEL-OFFLINE-{project_code}-{int(node['nodeId']):02d}-{index:03d}",
                    "projectId": metadata["projectId"],
                    "nodeId": int(node["nodeId"]),
                    "nodeName": node.get("nodeName"),
                    "documentId": document["id"],
                    "documentVersionId": document["currentVersionId"],
                    "fileName": document["fileName"],
                    "materialTypeCodes": file_row.get("materialTypeCodes") or [],
                    "evidenceTier": file_row.get("tier") or "advisory",
                    "manualStatus": "confirmed",
                    "revision": 1,
                }
            )
    return state


def _entry_prompt(project_code: str, project_id: str, project_name: str) -> str:
    return f"""# {project_code} 工程 AI 全审查入口

工程：{project_name}

工程 ID：{project_id}

本工程必须按照 `ai_full_review_prompt.md` 执行。项目清单位于：

`evidence_shards/{project_code}/manifest.json`

一次只处理一个业务节点的一个 EvidenceShard。每个节点的输入范围是 EvidenceSnapshot 中的全部当前有效历史挂接资料；后上传资料不得脱离此前资料单独判断。

执行完成条件：项目 manifest 中每个节点的全部 shard 都已处理，节点 coveragePassed=true，节点 FindingDraft 已通过 projectId/nodeId/reviewRunId 回挂，且所有结果等待人工确认。
"""


def export_project_review_package(
    *,
    repo_root: Path,
    project_code: str,
    output_root: Path,
    max_shard_estimated_tokens: int = 12000,
) -> dict[str, Any]:
    if project_code not in PROJECTS:
        raise ValueError(f"Unsupported project code: {project_code}")
    repo_root = Path(repo_root).resolve()
    output_root = Path(output_root).resolve()
    project = _project_input(repo_root, project_code)
    metadata = PROJECTS[project_code]
    state = _offline_state(repo_root, project_code, project)
    linked_nodes = [
        node
        for node in project.get("nodes") or []
        if isinstance(node.get("linkedFiles"), list) and node.get("linkedFiles")
    ]
    package_root = output_root / "evidence_shards" / project_code
    package_root.mkdir(parents=True, exist_ok=True)
    node_entries: list[dict[str, Any]] = []
    for node in linked_nodes:
        node_id = int(node["nodeId"])
        package = build_review_evidence_package(
            state,
            str(metadata["projectId"]),
            node_id,
            rule_version=f"offline-node-{node_id}-rule-v1",
            clause_package_version="offline-clauses-v1",
            prompt_version="project-auto-review-v1",
            strategy_version="node-review-strategy-v1",
            max_shard_estimated_tokens=max_shard_estimated_tokens,
        )
        node_root = package_root / f"node_{node_id:02d}"
        node_root.mkdir(parents=True, exist_ok=True)
        manifest = _without_volatile_times(package["manifest"])
        (node_root / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        shard_paths: list[str] = []
        for shard in package["shards"]:
            relative_path = Path(f"node_{node_id:02d}") / f"shard_{int(shard['shardIndex']):03d}.json"
            (package_root / relative_path).write_text(
                json.dumps(_without_volatile_times(shard), ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            shard_paths.append(str(relative_path))
        node_entries.append(
            {
                "nodeId": node_id,
                "nodeName": node.get("nodeName"),
                "criteria": node.get("criteria"),
                "checkMethod": node.get("checkMethod"),
                "configuredRequirements": node.get("configuredRequirements") or [],
                "evidenceSnapshotId": package["snapshot"]["evidenceSnapshotId"],
                "evidenceSnapshotHash": package["snapshot"]["snapshotHash"],
                "nodeManifestPath": f"node_{node_id:02d}/manifest.json",
                "shardPaths": shard_paths,
                "coverage": package["coverage"],
            }
        )
    project_manifest = {
        "schemaVersion": "OfflineProjectEvidencePackage@1.0.0",
        "projectCode": project_code,
        "projectId": metadata["projectId"],
        "projectName": metadata["projectName"],
        "includedNodeCount": len(node_entries),
        "nodes": node_entries,
    }
    project_manifest["packageHash"] = _json_hash(project_manifest)
    project_manifest["packageCoveragePassed"] = all(
        row["coverage"]["structuralCoveragePassed"] for row in node_entries
    )
    project_manifest["coveragePassed"] = False
    (package_root / "manifest.json").write_text(
        json.dumps(project_manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "ai_full_review_prompt.md").write_text(GENERIC_PROMPT, encoding="utf-8")
    (output_root / f"ai_full_review_prompt_{project_code}.md").write_text(
        _entry_prompt(project_code, str(metadata["projectId"]), str(metadata["projectName"])),
        encoding="utf-8",
    )
    return {
        "projectCode": project_code,
        "projectId": metadata["projectId"],
        "includedNodeCount": len(node_entries),
        "packageCoveragePassed": project_manifest["packageCoveragePassed"],
        "coveragePassed": project_manifest["coveragePassed"],
        "manifestPath": str(package_root / "manifest.json"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-code", choices=sorted(PROJECTS), required=True)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-shard-estimated-tokens", type=int, default=12000)
    args = parser.parse_args()
    result = export_project_review_package(
        repo_root=args.repo_root,
        project_code=args.project_code,
        output_root=args.output,
        max_shard_estimated_tokens=args.max_shard_estimated_tokens,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
