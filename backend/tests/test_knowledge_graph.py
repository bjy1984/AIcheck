from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.main import app
from libs.business_pack import load_business_pack
from libs.db.repository import repo
from libs.knowledge_graph import (
    KNOWLEDGE_NETWORK_SCHEMA_VERSION,
    build_business_pack_knowledge_network,
)


client = TestClient(app)


def setup_function() -> None:
    repo.reset()


def assert_ok(response):
    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0
    return payload["data"]


def test_engineering_business_pack_compiles_to_deterministic_knowledge_network() -> None:
    pack = load_business_pack("engineering_inspection_v1")

    first = build_business_pack_knowledge_network(pack)
    second = build_business_pack_knowledge_network(pack)

    assert first["schemaVersion"] == KNOWLEDGE_NETWORK_SCHEMA_VERSION
    assert first["checksum"] == second["checksum"]
    assert first["businessPackId"] == "engineering_inspection_v1"
    node_counts = first["summary"]["nodeTypeCounts"]
    edge_counts = first["summary"]["edgeTypeCounts"]
    bindings = pack["atomicCheckToolBindings"]
    required_facts = {
        str(fact)
        for binding in bindings
        for fact in binding.get("requiredFacts") or []
        if fact
    }
    required_fact_edges = {
        (str(binding.get("atomicCheckId")), str(fact))
        for binding in bindings
        for fact in binding.get("requiredFacts") or []
        if binding.get("atomicCheckId") and fact
    }
    bound_tool_edges = {
        (str(binding.get("atomicCheckId")), str(tool))
        for binding in bindings
        for tool in binding.get("tools") or []
        if binding.get("atomicCheckId") and tool
    }

    assert node_counts["business_pack"] == 1
    assert node_counts["inspection_node"] == len(pack["nodeTemplates"])
    assert node_counts["material_type"] == len(pack["materialTypes"])
    assert node_counts["rule"] == len(pack["ruleSets"])
    assert node_counts["atomic_check"] == len(pack["atomicChecks"])
    assert node_counts["clause_package"] == len(pack["standardClausePackages"])
    assert node_counts["required_fact"] == len(required_facts)
    assert node_counts["standard"] >= len(pack["standardCatalog"])
    assert edge_counts["REQUIRES_FACT"] == len(required_fact_edges)
    assert edge_counts["INVOKES_TOOL"] >= len(bound_tool_edges)

    node_ids = {item["id"] for item in first["nodes"]}
    assert {
        "business-pack:engineering_inspection_v1",
        "inspection-node:1",
        "rule:RULE-ENG-INSP-R01",
        "atomic-check:AC-R01-01",
        "fact:designLicense.holderName",
        "tool:check_all_equal",
        "standard:STD-TSG-D7006-2020",
    } <= node_ids

    edge_keys = {(item["source"], item["type"], item["target"]) for item in first["edges"]}
    assert (
        "inspection-node:1",
        "EVALUATED_BY",
        "rule:RULE-ENG-INSP-R01",
    ) in edge_keys
    assert (
        "atomic-check:AC-R01-01",
        "REQUIRES_FACT",
        "fact:designLicense.holderName",
    ) in edge_keys
    assert (
        "atomic-check:AC-R01-01",
        "INVOKES_TOOL",
        "tool:check_all_equal",
    ) in edge_keys


def test_knowledge_network_api_exposes_compiled_graph() -> None:
    graph = assert_ok(
        client.get(
            "/api/knowledge/network",
            params={"businessPackId": "engineering_inspection_v1", "includeRuntime": "false"},
        )
    )

    assert graph["schemaVersion"] == KNOWLEDGE_NETWORK_SCHEMA_VERSION
    assert graph["summary"]["nodeCount"] == len(graph["nodes"])
    assert graph["summary"]["edgeCount"] == len(graph["edges"])
    assert graph["checksum"].startswith("sha256:")
    assert any(item["type"] == "required_fact" for item in graph["nodeTypes"])
    assert any(item["type"] == "REQUIRES_FACT" for item in graph["edgeTypes"])


def test_runtime_projects_sources_and_files_are_joined_to_the_network() -> None:
    pack = load_business_pack("engineering_inspection_v1")
    graph = build_business_pack_knowledge_network(
        pack,
        runtime_state={
            "knowledge_sources": [
                {"id": "SRC-TEST", "name": "项目资料源", "sourceType": "project-file"}
            ],
            "projects": [
                {
                    "id": "PRJ-TEST",
                    "name": "测试项目",
                    "businessPackId": "engineering_inspection_v1",
                }
            ],
            "knowledge_files": [
                {
                    "id": "KF-TEST",
                    "fileName": "设计文件.pdf",
                    "sourceId": "SRC-TEST",
                    "projectId": "PRJ-TEST",
                }
            ],
        },
    )

    node_ids = {item["id"] for item in graph["nodes"]}
    edge_keys = {(item["source"], item["type"], item["target"]) for item in graph["edges"]}
    assert {
        "knowledge-source:SRC-TEST",
        "project:PRJ-TEST",
        "knowledge-file:KF-TEST",
    } <= node_ids
    assert (
        "business-pack:engineering_inspection_v1",
        "HAS_PROJECT",
        "project:PRJ-TEST",
    ) in edge_keys
    assert (
        "knowledge-source:SRC-TEST",
        "HAS_KNOWLEDGE_FILE",
        "knowledge-file:KF-TEST",
    ) in edge_keys
    assert (
        "knowledge-file:KF-TEST",
        "BELONGS_TO_PROJECT",
        "project:PRJ-TEST",
    ) in edge_keys


def test_knowledge_network_api_rejects_unknown_business_pack() -> None:
    response = client.get(
        "/api/knowledge/network",
        params={"businessPackId": "missing_business_pack"},
    )

    assert response.status_code == 200
    assert response.json()["code"] != 0
