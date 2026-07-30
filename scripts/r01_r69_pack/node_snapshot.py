from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
from typing import Any


@dataclass(frozen=True)
class NodeRecord:
    code: int
    name: str
    group_name: str
    inspection_type: str
    workflow_only: bool


@dataclass(frozen=True)
class RequirementRecord:
    node: int
    node_name: str
    inspection_type: str
    requirement_id: str
    material_type_code: str
    material_name: str
    required_type: str
    responsible_party: str
    status: str
    logical_document_id: str
    locator: str
    rationale: str


@dataclass(frozen=True)
class NodeSnapshot:
    nodes: tuple[NodeRecord, ...]
    requirements: tuple[RequirementRecord, ...]

    def requirements_for_node(self, code: int) -> list[RequirementRecord]:
        return [row for row in self.requirements if row.node == code]


def _backend_python(source: Path) -> Path:
    workspace = source.resolve().parents[3]
    local_candidate = workspace / "backend/.venv/bin/python"
    if local_candidate.exists():
        return local_candidate
    common_repo = Path(
        subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=workspace,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    ).parent
    candidate = common_repo / "backend/.venv/bin/python"
    if not candidate.exists():
        raise FileNotFoundError("找不到包含PyYAML的backend/.venv/bin/python")
    return candidate


def _load_yaml_with_backend_python(source: Path) -> dict[str, Any]:
    script = (
        "import json, pathlib, sys, yaml;"
        "p=pathlib.Path(sys.argv[1]);"
        "print(json.dumps(yaml.safe_load(p.read_text(encoding='utf-8')),"
        "ensure_ascii=False))"
    )
    completed = subprocess.run(
        [str(_backend_python(source)), "-c", script, str(source)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _document_for(node: int, material_type: str) -> str:
    if node <= 3:
        return "B00-QUAL-001"
    if node <= 9:
        return "M00-STD-001" if "standard" in material_type else "B00-DESIGN-001"
    if node == 10:
        return "B00-CONSTRUCTION-001"
    if node <= 14:
        return "B00-MATERIAL-001"
    if node <= 21:
        mapping = {
            15: "S01-FOREIGN-001",
            16: "S01-FOREIGN-001",
            17: "S01-MATERIAL-001",
            18: "S01-RETEST-001",
            19: "S01-RETEST-001",
            20: "S01-REVIEW-001",
            21: "S01-ACCEPT-001",
        }
        return mapping[node]
    if node == 22:
        return "S02-APPROVAL-001"
    if node == 23:
        return "B00-VALVE-001"
    if node <= 30:
        return "B00-WELD-001" if node <= 27 else "B00-WELD-LEDGER-001"
    if node == 31:
        return "S03-REPAIR-001"
    if node <= 34:
        return "S03-PWHT-001"
    if node <= 39:
        return "B00-NDT-001"
    if node <= 45:
        return "B00-INSTALL-001"
    if node <= 55:
        return "S04-CP-001" if node <= 47 else "S04-INSTALL-001"
    if node <= 58:
        return "S05-ACCESSORY-001"
    if node <= 62:
        return "B00-TEST-001"
    if node <= 65:
        return "S06-ALTERNATIVE-001"
    if node <= 67:
        return "S06-FINAL-001"
    return "B00-INSTALL-001"


def snapshot_nodes(source: Path, output: Path) -> dict[str, Any]:
    payload = _load_yaml_with_backend_python(source)
    nodes: list[dict[str, Any]] = []
    requirements: list[dict[str, Any]] = []
    for raw_node in payload["nodeTemplates"]:
        code = int(raw_node["nodeId"])
        node_record = {
            "code": code,
            "name": raw_node["name"],
            "groupName": raw_node["groupName"],
            "inspectionType": raw_node["inspectionType"],
            "workflowOnly": not raw_node.get("requiredMaterials"),
        }
        nodes.append(node_record)
        for requirement in raw_node.get("requiredMaterials", []):
            logical_document_id = _document_for(
                code, requirement["materialTypeCode"]
            )
            requirements.append(
                {
                    "node": code,
                    "nodeName": raw_node["name"],
                    "inspectionType": raw_node["inspectionType"],
                    "requirementId": requirement["id"],
                    "materialTypeCode": requirement["materialTypeCode"],
                    "materialName": requirement["name"],
                    "requiredType": requirement["requiredType"],
                    "responsibleParty": requirement.get(
                        "responsibleParty", "施工方上传"
                    ),
                    "status": "已提供",
                    "logicalDocumentId": logical_document_id,
                    "locator": f"{logical_document_id}#{requirement['id']}",
                    "rationale": "",
                }
            )
    normalized = {
        "schemaVersion": "r01-r69-requirement-map@1",
        "source": str(source),
        "nodeCount": len(nodes),
        "requirementCount": len(requirements),
        "nodes": nodes,
        "requirements": requirements,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return normalized


def load_node_snapshot(path: Path) -> NodeSnapshot:
    payload = json.loads(path.read_text(encoding="utf-8"))
    nodes = tuple(
        NodeRecord(
            code=int(row["code"]),
            name=row["name"],
            group_name=row["groupName"],
            inspection_type=row["inspectionType"],
            workflow_only=bool(row["workflowOnly"]),
        )
        for row in payload["nodes"]
    )
    requirements = tuple(
        RequirementRecord(
            node=int(row["node"]),
            node_name=row["nodeName"],
            inspection_type=row["inspectionType"],
            requirement_id=row["requirementId"],
            material_type_code=row["materialTypeCode"],
            material_name=row["materialName"],
            required_type=row["requiredType"],
            responsible_party=row["responsibleParty"],
            status=row["status"],
            logical_document_id=row["logicalDocumentId"],
            locator=row["locator"],
            rationale=row["rationale"],
        )
        for row in payload["requirements"]
    )
    return NodeSnapshot(nodes=nodes, requirements=requirements)


def main() -> int:
    workspace = Path(__file__).resolve().parents[2]
    source = workspace / "backend/business_packs/engineering_inspection_v1/nodes.yaml"
    output = Path(__file__).parent / "data/requirement_map.json"
    normalized = snapshot_nodes(source, output)
    print(
        f"nodes={normalized['nodeCount']} "
        f"requirements={normalized['requirementCount']} output={output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
