"""Offline execution of retained NDT source fixtures; never publishes or approves."""

from __future__ import annotations

import argparse
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from libs.business_pack import load_business_pack
from libs.review_orchestrator.ndt_fact_builders import NDT_FACT_BUILDERS
from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool, runtime_tool_catalog
from libs.review_tools import compile_node_tool_plan, execute_node_tool_plan

if __package__:
    from .review_acceptance_gate import STATES, canonical_input_hash, source_digest
else:
    from review_acceptance_gate import STATES, canonical_input_hash, source_digest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
# Explicit local read/decision tools: future registrations are not silently offline-safe.
OFFLINE_TOOLS = {
    "get_document_ocr_result",
    "extract_document_fields",
    "extract_table_records",
    "locate_evidence_fragment",
    "validate_evidence_grounding",
    "evaluate_ndt_quality_system",
    "evaluate_r36_ndt_plan",
    "evaluate_ndt_nonconformance",
    "evaluate_r37_defect_closure",
}


def replay_fixture(
    fixture: dict[str, Any], pack: dict[str, Any], *, binding_sha256: str, code_sha256: str
) -> dict[str, Any]:
    frozen = fixture.get("frozenInput")
    if not isinstance(frozen, dict):
        raise TypeError("replay_frozen_input_missing")
    digest = canonical_input_hash(frozen)
    if fixture.get("fixtureInputSha256") != digest:
        raise ValueError("replay_fixture_hash_mismatch")
    run, state = deepcopy(frozen.get("reviewRun")), deepcopy(frozen.get("state"))
    if not isinstance(run, dict) or not isinstance(state, dict):
        raise TypeError("replay_source_state_and_run_required")
    node = run.get("nodeId")
    if type(node) is not int or node not in NDT_FACT_BUILDERS:
        raise ValueError("replay_fact_builder_not_supported")
    rule = f"R{node:02d}"
    if fixture.get("ruleId") != rule:
        raise ValueError("replay_rule_node_mismatch")
    versions = frozen.get("inputDocumentVersionIds")
    if not isinstance(versions, list) or versions != run.get("inputDocumentVersionIds"):
        raise ValueError("replay_document_scope_mismatch")
    if not isinstance(run.get("documentScopeSnapshot"), dict):
        raise TypeError("replay_frozen_scope_required")
    if fixture.get("expectedResult") not in STATES.values():
        raise ValueError("replay_expected_result_invalid")
    plan = compile_node_tool_plan(
        pack, rule, available_tools={item["name"] for item in runtime_tool_catalog()}
    )
    if not plan or any(not item["compilable"] for item in plan):
        raise ValueError("replay_plan_missing_or_unregistered")
    unsupported = {tool for item in plan for tool in item["tools"]} - OFFLINE_TOOLS
    if unsupported:
        raise ValueError("replay_nonlocal_or_unsupported_tools:" + ",".join(sorted(unsupported)))
    facts = NDT_FACT_BUILDERS[node](state, run)
    judgment = facts.get("judgment") or {}
    output = execute_node_tool_plan(
        plan,
        facts=facts,
        document_version_ids=versions,
        evidence_facts=judgment.get("claimedFacts") or [],
        evidence_refs=judgment.get("evidenceRefs") or [],
        tool_runner=lambda name, args: dispatch_runtime_tool(
            state, name, args, context={"reviewRun": run}
        ),
    )
    return {
        **output,
        "ruleId": rule,
        "fixtureInputSha256": digest,
        "bindingSha256": binding_sha256,
        "sourceSha256": code_sha256,
        "evidenceRefs": deepcopy(judgment.get("evidenceRefs") or []),
        "executionMode": "offline_frozen_ndt_sources",
        "matchesExpected": output["result"] == fixture["expectedResult"],
        "businessAcceptance": "not_reviewed",
    }


def semantic_result(output: dict[str, Any]) -> dict[str, Any]:
    """Ignore only runtime call identifiers, retaining all decision/evidence fields."""

    def clean(value):
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items() if key != "toolCallId"}
        if isinstance(value, list):
            return [clean(item) for item in value]
        return value

    return clean(output)


def export_replay(
    fixture_path: Path, output_dir: Path, *, pack_id: str = "engineering_inspection_v1"
) -> dict[str, Any]:
    source = fixture_path.read_bytes()
    fixture = json.loads(source)
    if not isinstance(fixture, dict):
        raise TypeError("replay_fixture_must_be_object")
    # Loading through the business-pack registry validates pack identity before reading its file.
    pack = load_business_pack(pack_id)
    binding_path = BACKEND_ROOT / "business_packs" / pack_id / "atomic_check_tool_bindings.yaml"
    binding_hash = hashlib.sha256(binding_path.read_bytes()).hexdigest()
    code_hash = source_digest(BACKEND_ROOT)
    output = replay_fixture(fixture, pack, binding_sha256=binding_hash, code_sha256=code_hash)
    if (
        source_digest(BACKEND_ROOT) != code_hash
        or hashlib.sha256(binding_path.read_bytes()).hexdigest() != binding_hash
    ):
        raise RuntimeError("replay_sources_changed")
    # A fresh directory prevents overwriting earlier acceptance evidence.
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "fixture.json").write_bytes(source)
    result_bytes = (
        json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode()
    (output_dir / "output.json").write_bytes(result_bytes)
    report = {
        "schemaVersion": "review-replay-report-v1",
        "ruleId": output["ruleId"],
        "matchesExpected": output["matchesExpected"],
        "businessAcceptance": "not_reviewed",
        "fixture": {"path": "fixture.json", "sha256": hashlib.sha256(source).hexdigest()},
        "output": {"path": "output.json", "sha256": hashlib.sha256(result_bytes).hexdigest()},
        "bindingSha256": binding_hash,
        "sourceSha256": code_hash,
    }
    (output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--pack-id", default="engineering_inspection_v1")
    args = parser.parse_args()
    report = export_replay(args.fixture, args.output_dir, pack_id=args.pack_id)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["matchesExpected"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
