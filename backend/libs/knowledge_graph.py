from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from typing import Any

KNOWLEDGE_NETWORK_SCHEMA_VERSION = "knowledge-network@1.0.0"

NODE_TYPE_LABELS = {
    "business_pack": "业务知识库",
    "domain_module": "业务模块",
    "inspection_node": "监检节点",
    "material_type": "资料类型",
    "rule": "业务规则",
    "atomic_check": "原子检查",
    "required_fact": "事实定义",
    "tool": "确定性工具",
    "standard": "标准规范",
    "standard_clause": "标准条款",
    "clause_package": "条款包",
    "knowledge_source": "知识源",
    "knowledge_file": "知识文件",
    "thinking_mode": "思考模式",
    "agent": "Agent",
    "project": "项目实例",
}

NODE_TYPE_FAMILIES = {
    "business_pack": "business",
    "domain_module": "business",
    "inspection_node": "business",
    "project": "business",
    "material_type": "evidence",
    "knowledge_source": "evidence",
    "knowledge_file": "evidence",
    "rule": "rule",
    "atomic_check": "rule",
    "clause_package": "rule",
    "required_fact": "semantic",
    "standard": "standard",
    "standard_clause": "standard",
    "tool": "execution",
    "thinking_mode": "execution",
    "agent": "execution",
}

EDGE_TYPE_LABELS = {
    "HAS_MODULE": "包含模块",
    "HAS_NODE": "包含节点",
    "HAS_PROJECT": "包含项目",
    "USES_BUSINESS_PACK": "使用业务包",
    "REQUIRES_MATERIAL": "需要资料",
    "EVALUATED_BY": "由规则审查",
    "DECOMPOSED_INTO": "分解为",
    "REQUIRES_FACT": "需要事实",
    "INVOKES_TOOL": "调用工具",
    "USES_THINKING_MODE": "使用思考模式",
    "HAS_AGENT": "配置 Agent",
    "ALLOWS_TOOL": "允许工具",
    "BINDS_CLAUSE_PACKAGE": "绑定条款包",
    "GOVERNED_BY": "依据条款包",
    "CONTAINS_CHECK": "包含检查",
    "CONTAINS_CLAUSE": "包含条款",
    "HAS_CLAUSE": "包含条款",
    "FROM_STANDARD": "来源标准",
    "HAS_SOURCE_FILE": "对应知识文件",
    "LOCATED_IN": "定位于文件",
    "HAS_KNOWLEDGE_FILE": "包含知识文件",
    "BELONGS_TO_PROJECT": "属于项目",
}


def _stable_digest(*values: Any, length: int = 16) -> str:
    raw = "\x1f".join(str(value or "") for value in values)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:length]


def _compact_text(value: Any, limit: int = 800) -> str | None:
    text = " ".join(str(value or "").split())
    if not text:
        return None
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def _clean_metadata(value: dict[str, Any] | None) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, item in (value or {}).items():
        if item is None or item == "" or item == [] or item == {}:
            continue
        if isinstance(item, str):
            cleaned[key] = _compact_text(item)
        elif isinstance(item, list):
            cleaned[key] = [
                _compact_text(entry, 240) if isinstance(entry, str) else entry
                for entry in item[:100]
            ]
        elif isinstance(item, dict):
            cleaned[key] = _clean_metadata(item)
        else:
            cleaned[key] = item
    return cleaned


class KnowledgeNetworkBuilder:
    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: dict[tuple[str, str, str], dict[str, Any]] = {}

    def add_node(
        self,
        node_id: str,
        node_type: str,
        label: str,
        *,
        description: Any = None,
        group: str | None = None,
        status: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        existing = self.nodes.get(node_id)
        payload = {
            "id": node_id,
            "type": node_type,
            "typeLabel": NODE_TYPE_LABELS.get(node_type, node_type),
            "family": NODE_TYPE_FAMILIES.get(node_type, "semantic"),
            "label": str(label or node_id),
            "description": _compact_text(description),
            "group": group,
            "status": status,
            "metadata": _clean_metadata(metadata),
        }
        payload = {
            key: value
            for key, value in payload.items()
            if value is not None and value != ""
        }
        if existing:
            merged_metadata = {**existing.get("metadata", {}), **payload.get("metadata", {})}
            existing.update({key: value for key, value in payload.items() if key != "metadata"})
            existing["metadata"] = merged_metadata
        else:
            self.nodes[node_id] = payload
        return node_id

    def add_edge(
        self,
        source: str,
        target: str,
        edge_type: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not source or not target or source == target:
            return
        key = (source, target, edge_type)
        if key in self.edges:
            return
        self.edges[key] = {
            "id": f"edge:{_stable_digest(source, edge_type, target)}",
            "source": source,
            "target": target,
            "type": edge_type,
            "label": EDGE_TYPE_LABELS.get(edge_type, edge_type),
            "metadata": _clean_metadata(metadata),
        }

    def payload(self, *, pack: dict[str, Any]) -> dict[str, Any]:
        nodes = sorted(self.nodes.values(), key=lambda item: (item["type"], item["id"]))
        edges = sorted(
            self.edges.values(),
            key=lambda item: (item["type"], item["source"], item["target"]),
        )
        node_type_counts = Counter(item["type"] for item in nodes)
        edge_type_counts = Counter(item["type"] for item in edges)
        checksum_payload = {
            "schemaVersion": KNOWLEDGE_NETWORK_SCHEMA_VERSION,
            "businessPackId": pack.get("id"),
            "businessPackVersion": pack.get("version"),
            "nodes": nodes,
            "edges": edges,
        }
        checksum = "sha256:" + hashlib.sha256(
            json.dumps(
                checksum_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return {
            "schemaVersion": KNOWLEDGE_NETWORK_SCHEMA_VERSION,
            "graphId": f"knowledge-network:{pack.get('id')}",
            "name": f"{pack.get('name') or pack.get('id')}知识网络",
            "businessPackId": pack.get("id"),
            "businessPackVersion": pack.get("version"),
            "sourceSnapshotHash": pack.get("snapshotHash"),
            "checksum": checksum,
            "generatedAt": datetime.now(UTC).isoformat(),
            "summary": {
                "nodeCount": len(nodes),
                "edgeCount": len(edges),
                "nodeTypeCounts": dict(sorted(node_type_counts.items())),
                "edgeTypeCounts": dict(sorted(edge_type_counts.items())),
            },
            "nodeTypes": [
                {
                    "type": node_type,
                    "label": NODE_TYPE_LABELS.get(node_type, node_type),
                    "family": NODE_TYPE_FAMILIES.get(node_type, "semantic"),
                    "count": node_type_counts.get(node_type, 0),
                }
                for node_type in NODE_TYPE_LABELS
                if node_type_counts.get(node_type, 0)
            ],
            "edgeTypes": [
                {
                    "type": edge_type,
                    "label": EDGE_TYPE_LABELS.get(edge_type, edge_type),
                    "count": edge_type_counts.get(edge_type, 0),
                }
                for edge_type in EDGE_TYPE_LABELS
                if edge_type_counts.get(edge_type, 0)
            ],
            "nodes": nodes,
            "edges": edges,
        }


def build_business_pack_knowledge_network(
    pack: dict[str, Any],
    *,
    runtime_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    builder = KnowledgeNetworkBuilder()
    pack_id = str(pack.get("id") or "business-pack")
    root_id = f"business-pack:{pack_id}"
    builder.add_node(
        root_id,
        "business_pack",
        str(pack.get("name") or pack_id),
        description=pack.get("description") or pack.get("scopeDescription"),
        status=pack.get("status"),
        metadata={
            "version": pack.get("version"),
            "domainType": pack.get("domainType"),
            "pipelineTypeCode": pack.get("pipelineTypeCode"),
            "pipelineTypeName": pack.get("pipelineTypeName"),
            "projectType": pack.get("projectType"),
        },
    )

    node_templates = [item for item in pack.get("nodeTemplates") or [] if isinstance(item, dict)]
    material_types = [item for item in pack.get("materialTypes") or [] if isinstance(item, dict)]
    rules = [item for item in pack.get("ruleSets") or [] if isinstance(item, dict)]
    atomic_checks = [item for item in pack.get("atomicChecks") or [] if isinstance(item, dict)]
    tool_bindings = [
        item for item in pack.get("atomicCheckToolBindings") or [] if isinstance(item, dict)
    ]
    standards = [item for item in pack.get("standardCatalog") or [] if isinstance(item, dict)]
    clause_bindings = [
        item for item in pack.get("standardClauseBindings") or [] if isinstance(item, dict)
    ]
    clause_packages = [
        item for item in pack.get("standardClausePackages") or [] if isinstance(item, dict)
    ]

    groups: dict[str, str] = {}
    for node in node_templates:
        group_name = str(node.get("groupName") or "其他")
        group_id = groups.setdefault(group_name, f"module:{_stable_digest(group_name)}")
        builder.add_node(group_id, "domain_module", group_name, group=group_name)
        builder.add_edge(root_id, group_id, "HAS_MODULE")

    material_ids: dict[str, str] = {}
    for material in material_types:
        code = str(material.get("code") or "")
        if not code:
            continue
        material_id = f"material:{code}"
        material_ids[code] = material_id
        builder.add_node(
            material_id,
            "material_type",
            str(material.get("name") or code),
            description=material.get("note"),
            status=material.get("requiredType"),
            metadata={
                "code": code,
                "requiredType": material.get("requiredType"),
                "requiredFields": material.get("requiredFields"),
                "ocrFieldMappings": material.get("ocrFieldMappings"),
                "evidenceRequired": material.get("evidenceRequired"),
            },
        )

    node_ids: dict[int, str] = {}
    for node in node_templates:
        node_id_value = int(node.get("nodeId") or 0)
        if not node_id_value:
            continue
        node_id = f"inspection-node:{node_id_value}"
        node_ids[node_id_value] = node_id
        group_name = str(node.get("groupName") or "其他")
        builder.add_node(
            node_id,
            "inspection_node",
            f"R{node_id_value:02d} {node.get('name') or node_id_value}",
            group=group_name,
            status=node.get("defaultStatus"),
            metadata={
                "nodeId": node_id_value,
                "code": node.get("code"),
                "inspectionType": node.get("inspectionType"),
                "requiredMaterialCount": len(node.get("requiredMaterials") or []),
            },
        )
        builder.add_edge(groups[group_name], node_id, "HAS_NODE")
        for requirement in node.get("requiredMaterials") or []:
            material_code = str(requirement.get("materialTypeCode") or "")
            material_id = material_ids.get(material_code)
            if material_id:
                builder.add_edge(
                    node_id,
                    material_id,
                    "REQUIRES_MATERIAL",
                    metadata={
                        "requiredType": requirement.get("requiredType"),
                        "responsibleParty": requirement.get("responsibleParty"),
                        "applicability": requirement.get("applicability"),
                    },
                )

    standard_ids: dict[str, str] = {}
    logical_file_ids: dict[str, str] = {}
    for standard in standards:
        standard_code = str(standard.get("id") or standard.get("code") or "")
        if not standard_code:
            continue
        standard_id = f"standard:{standard_code}"
        standard_ids[standard_code] = standard_id
        builder.add_node(
            standard_id,
            "standard",
            str(standard.get("code") or standard.get("name") or standard_code),
            description=standard.get("name"),
            metadata={
                "catalogId": standard_code,
                "name": standard.get("name"),
                "sourceFile": standard.get("sourceFile"),
                "verificationMethod": standard.get("verificationMethod"),
                "documentVersionId": standard.get("documentVersionId"),
            },
        )
        knowledge_file_id = str(standard.get("knowledgeFileId") or "")
        if knowledge_file_id:
            file_node_id = f"knowledge-file:{knowledge_file_id}"
            logical_file_ids[knowledge_file_id] = file_node_id
            builder.add_node(
                file_node_id,
                "knowledge_file",
                str(standard.get("name") or standard.get("sourceFile") or knowledge_file_id),
                description=standard.get("sourceFile"),
                metadata={
                    "knowledgeFileId": knowledge_file_id,
                    "documentVersionId": standard.get("documentVersionId"),
                    "sourceRelativePath": standard.get("sourceFile"),
                },
            )
            builder.add_edge(standard_id, file_node_id, "HAS_SOURCE_FILE")

    thinking_mode_ids: dict[str, str] = {}
    for mode in pack.get("thinkingModeCatalog") or []:
        mode_code = str(mode.get("id") or "")
        if not mode_code:
            continue
        mode_id = f"thinking-mode:{mode_code}"
        thinking_mode_ids[mode_code] = mode_id
        builder.add_node(
            mode_id,
            "thinking_mode",
            str(mode.get("name") or mode_code),
            description=mode.get("appliesTo"),
            metadata={"code": mode_code},
        )

    tool_catalog = {
        str(item.get("id") or ""): item
        for item in pack.get("toolCatalog") or []
        if isinstance(item, dict)
    }
    tool_by_runtime_name = {
        str(item.get("runtimeTool") or ""): item for item in tool_catalog.values() if item.get("runtimeTool")
    }
    tool_names = {
        str(tool)
        for binding in tool_bindings
        for tool in binding.get("tools") or []
        if tool
    }
    tool_names.update(tool_by_runtime_name)
    tool_ids: dict[str, str] = {}
    for tool_name in sorted(tool_names):
        tool_id = f"tool:{tool_name}"
        tool_ids[tool_name] = tool_id
        descriptor = tool_by_runtime_name.get(tool_name) or {}
        builder.add_node(
            tool_id,
            "tool",
            str(descriptor.get("name") or tool_name),
            description=descriptor.get("capability"),
            metadata={
                "runtimeTool": tool_name,
                "toolCatalogId": descriptor.get("id"),
            },
        )

    for agent in pack.get("agentSops") or []:
        agent_code = str(agent.get("id") or "")
        if not agent_code:
            continue
        agent_id = f"agent:{agent_code}"
        builder.add_node(
            agent_id,
            "agent",
            str(agent.get("name") or agent_code),
            status="human_confirmation_required" if agent.get("humanConfirmationRequired") else None,
            metadata={
                "version": agent.get("version"),
                "taskType": agent.get("taskType"),
                "inputSchema": agent.get("inputSchema"),
                "outputSchema": agent.get("outputSchema"),
            },
        )
        builder.add_edge(root_id, agent_id, "HAS_AGENT")
        for tool_name in agent.get("allowedTools") or []:
            if tool_name not in tool_ids:
                tool_ids[tool_name] = f"tool:{tool_name}"
                builder.add_node(tool_ids[tool_name], "tool", str(tool_name))
            builder.add_edge(agent_id, tool_ids[tool_name], "ALLOWS_TOOL")

    rules_by_source = {str(rule.get("sourceRuleId") or ""): rule for rule in rules}
    rule_ids: dict[str, str] = {}
    for rule in rules:
        rule_code = str(rule.get("id") or rule.get("ruleKey") or "")
        if not rule_code:
            continue
        rule_id = f"rule:{rule_code}"
        rule_ids[rule_code] = rule_id
        source_rule_id = str(rule.get("sourceRuleId") or "")
        builder.add_node(
            rule_id,
            "rule",
            str(rule.get("name") or source_rule_id or rule_code),
            description=rule.get("criteria") or rule.get("standardText"),
            group=rule.get("businessModule") or rule.get("inspectionCategory"),
            status=rule.get("status"),
            metadata={
                "ruleId": rule_code,
                "sourceRuleId": source_rule_id,
                "version": rule.get("version"),
                "severity": rule.get("severity"),
                "inspectionClass": rule.get("inspectionClass"),
                "promptVersion": rule.get("promptVersion"),
                "outputSchemaVersion": rule.get("outputSchemaVersion"),
            },
        )
        for node_id_value in rule.get("nodeIds") or []:
            node_id = node_ids.get(int(node_id_value))
            if node_id:
                builder.add_edge(node_id, rule_id, "EVALUATED_BY")
        for mode_code in rule.get("thinkingModeIds") or []:
            if str(mode_code) in thinking_mode_ids:
                builder.add_edge(rule_id, thinking_mode_ids[str(mode_code)], "USES_THINKING_MODE")
        for tool_code in rule.get("toolIds") or []:
            descriptor = tool_catalog.get(str(tool_code)) or {}
            runtime_tool = str(descriptor.get("runtimeTool") or "")
            if runtime_tool and runtime_tool in tool_ids:
                builder.add_edge(rule_id, tool_ids[runtime_tool], "INVOKES_TOOL")

    checks_by_id: dict[str, dict[str, Any]] = {}
    check_ids: dict[str, str] = {}
    for check in atomic_checks:
        check_code = str(check.get("id") or "")
        if not check_code:
            continue
        checks_by_id[check_code] = check
        check_id = f"atomic-check:{check_code}"
        check_ids[check_code] = check_id
        builder.add_node(
            check_id,
            "atomic_check",
            str(check.get("name") or check_code),
            description=check.get("instruction"),
            metadata={
                "atomicCheckId": check_code,
                "sourceRuleId": check.get("sourceRuleId"),
                "checkType": check.get("checkType"),
                "evidenceRequired": check.get("evidenceRequired"),
                "failurePolicy": check.get("failurePolicy"),
            },
        )
        rule_code = str(check.get("ruleId") or "")
        if rule_code in rule_ids:
            builder.add_edge(rule_ids[rule_code], check_id, "DECOMPOSED_INTO")

    for binding in tool_bindings:
        check_code = str(binding.get("atomicCheckId") or "")
        check_id = check_ids.get(check_code)
        if not check_id:
            continue
        for fact_code in binding.get("requiredFacts") or []:
            fact_code = str(fact_code)
            fact_id = f"fact:{fact_code}"
            subject_path = fact_code.split(".", 1)[0]
            builder.add_node(
                fact_id,
                "required_fact",
                fact_code,
                group=subject_path,
                status="required",
                metadata={
                    "factCode": fact_code,
                    "subjectPath": subject_path,
                    "bindingStatus": binding.get("implementationStatus"),
                },
            )
            builder.add_edge(check_id, fact_id, "REQUIRES_FACT")
        for tool_name in binding.get("tools") or []:
            tool_name = str(tool_name)
            if tool_name not in tool_ids:
                tool_ids[tool_name] = f"tool:{tool_name}"
                builder.add_node(tool_ids[tool_name], "tool", tool_name)
            builder.add_edge(
                check_id,
                tool_ids[tool_name],
                "INVOKES_TOOL",
                metadata={"implementationStatus": binding.get("implementationStatus")},
            )

    def ensure_standard(standard_ref: str) -> str:
        if standard_ref in standard_ids:
            return standard_ids[standard_ref]
        standard_id = f"standard:{standard_ref}"
        standard_ids[standard_ref] = standard_id
        builder.add_node(standard_id, "standard", standard_ref, status="referenced")
        return standard_id

    def ensure_clause(clause: dict[str, Any]) -> str:
        standard_ref = str(clause.get("standardRef") or "UNKNOWN-STANDARD")
        clause_no = str(clause.get("clauseNo") or "未编号条款")
        locator_id = str(clause.get("sourceLocatorId") or "")
        clause_id = f"clause:{_stable_digest(standard_ref, clause_no, locator_id)}"
        standard_id = ensure_standard(standard_ref)
        builder.add_node(
            clause_id,
            "standard_clause",
            f"{clause_no} · {builder.nodes[standard_id]['label']}",
            description=clause.get("text") or clause.get("summary"),
            status=clause.get("verificationStatus") or clause.get("lifecycleStatus"),
            metadata={
                "standardRef": standard_ref,
                "clauseNo": clause_no,
                "bindingRole": clause.get("bindingRole"),
                "sourcePage": clause.get("sourcePage"),
                "startPage": clause.get("startPage"),
                "endPage": clause.get("endPage"),
                "sourceLocatorId": locator_id,
                "knowledgeFileId": clause.get("knowledgeFileId"),
                "documentVersionId": clause.get("documentVersionId"),
            },
        )
        builder.add_edge(standard_id, clause_id, "HAS_CLAUSE")
        knowledge_file_id = str(clause.get("knowledgeFileId") or "")
        if knowledge_file_id:
            file_node_id = logical_file_ids.get(knowledge_file_id) or f"knowledge-file:{knowledge_file_id}"
            logical_file_ids[knowledge_file_id] = file_node_id
            builder.add_node(
                file_node_id,
                "knowledge_file",
                knowledge_file_id,
                metadata={
                    "knowledgeFileId": knowledge_file_id,
                    "documentVersionId": clause.get("documentVersionId"),
                },
            )
            builder.add_edge(clause_id, file_node_id, "LOCATED_IN")
        return clause_id

    primary_bindings_by_source = {
        str(item.get("sourceRuleId") or ""): item for item in clause_bindings
    }
    for package in clause_packages:
        package_code = str(package.get("packageId") or "")
        source_rule_id = str(package.get("sourceRuleId") or "")
        if not package_code:
            continue
        package_id = f"clause-package:{package_code}"
        builder.add_node(
            package_id,
            "clause_package",
            str(package.get("nodeName") or source_rule_id or package_code),
            description=(package.get("applicability") or {}).get("expression"),
            status=package.get("lifecycleStatus"),
            metadata={
                "packageId": package_code,
                "sourceRuleId": source_rule_id,
                "nodeId": package.get("nodeId"),
                "applicability": package.get("applicability"),
                "decisionModel": package.get("decisionModel"),
            },
        )
        node_id = node_ids.get(int(package.get("nodeId") or 0))
        if node_id:
            builder.add_edge(node_id, package_id, "BINDS_CLAUSE_PACKAGE")
        rule = rules_by_source.get(source_rule_id)
        rule_code = str((rule or {}).get("id") or "")
        if rule_code in rule_ids:
            builder.add_edge(rule_ids[rule_code], package_id, "GOVERNED_BY")
        for check_code in package.get("atomicCheckIds") or []:
            if str(check_code) in check_ids:
                builder.add_edge(package_id, check_ids[str(check_code)], "CONTAINS_CHECK")
        primary = primary_bindings_by_source.get(source_rule_id)
        clauses = ([primary] if primary else []) + [
            item for item in package.get("professionalClauses") or [] if isinstance(item, dict)
        ]
        for clause in clauses:
            clause_id = ensure_clause(clause)
            builder.add_edge(package_id, clause_id, "CONTAINS_CLAUSE")

    state = runtime_state or {}
    source_node_ids: dict[str, str] = {}
    for source in state.get("knowledge_sources") or []:
        if not isinstance(source, dict) or not source.get("id"):
            continue
        source_code = str(source["id"])
        source_id = f"knowledge-source:{source_code}"
        source_node_ids[source_code] = source_id
        builder.add_node(
            source_id,
            "knowledge_source",
            str(source.get("name") or source_code),
            status=source.get("status"),
            metadata={
                "sourceId": source_code,
                "sourceType": source.get("sourceType"),
                "version": source.get("version"),
                "vectorStatus": source.get("vectorStatus"),
            },
        )

    project_node_ids: dict[str, str] = {}
    for project in state.get("projects") or []:
        if not isinstance(project, dict) or not project.get("id"):
            continue
        project_code = str(project["id"])
        project_id = f"project:{project_code}"
        project_node_ids[project_code] = project_id
        builder.add_node(
            project_id,
            "project",
            str(project.get("name") or project.get("code") or project_code),
            status=project.get("status"),
            metadata={
                "projectId": project_code,
                "code": project.get("code"),
                "pipelineGrade": project.get("pipelineGrade"),
                "businessPackId": project.get("businessPackId"),
            },
        )
        if str(project.get("businessPackId") or pack_id) == pack_id:
            builder.add_edge(root_id, project_id, "HAS_PROJECT")
            builder.add_edge(project_id, root_id, "USES_BUSINESS_PACK")

    for file in state.get("knowledge_files") or []:
        if not isinstance(file, dict) or not file.get("id"):
            continue
        file_code = str(file["id"])
        file_node_id = f"knowledge-file:{file_code}"
        logical_file_ids[file_code] = file_node_id
        builder.add_node(
            file_node_id,
            "knowledge_file",
            str(file.get("fileName") or file.get("originalFileName") or file_code),
            description=file.get("contextDescription") or file.get("sourceRelativePath"),
            status=file.get("vectorStatus") or file.get("ocrStatus"),
            metadata={
                "knowledgeFileId": file_code,
                "sourceId": file.get("sourceId"),
                "projectId": file.get("projectId"),
                "nodeId": file.get("nodeId"),
                "documentVersionId": file.get("documentVersionId"),
                "ocrStatus": file.get("ocrStatus"),
                "sliceStatus": file.get("sliceStatus"),
                "vectorStatus": file.get("vectorStatus"),
                "chunkCount": file.get("chunkCount"),
            },
        )
        source_id = source_node_ids.get(str(file.get("sourceId") or ""))
        if source_id:
            builder.add_edge(source_id, file_node_id, "HAS_KNOWLEDGE_FILE")
        project_id = project_node_ids.get(str(file.get("projectId") or ""))
        if project_id:
            builder.add_edge(file_node_id, project_id, "BELONGS_TO_PROJECT")

    return builder.payload(pack=pack)
