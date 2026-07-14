from __future__ import annotations

from typing import Any, Callable


ToolRunner = Callable[[str, dict[str, Any]], dict[str, Any]]


def compile_node_tool_plan(
    pack: dict[str, Any],
    source_rule_id: str,
    *,
    available_tools: set[str],
    require_published: bool = False,
) -> list[dict[str, Any]]:
    binding_set = pack.get("atomicCheckToolBindingSet") or {}
    lifecycle_status = str(binding_set.get("lifecycleStatus") or "draft").lower()
    if require_published and lifecycle_status != "published":
        raise ValueError(
            f"Formal review requires published atomic check tool bindings; current status is {lifecycle_status}."
        )
    bindings = [
        item
        for item in pack.get("atomicCheckToolBindings") or []
        if isinstance(item, dict) and str(item.get("sourceRuleId")) == source_rule_id
    ]
    plan = []
    for binding in bindings:
        tools = [str(item) for item in binding.get("tools") or []]
        missing = [item for item in tools if item not in available_tools]
        plan.append(
            {
                "atomicCheckId": binding.get("atomicCheckId"),
                "sourceRuleId": source_rule_id,
                "requiredFacts": list(binding.get("requiredFacts") or []),
                "tools": tools,
                "parameters": dict(binding.get("parameters") or {}),
                "outputSchema": binding.get("outputSchema"),
                "implementationStatus": binding.get("implementationStatus"),
                "bindingSetVersion": binding_set.get("version"),
                "bindingSetLifecycleStatus": lifecycle_status,
                "compilable": not missing,
                "missingTools": missing,
            }
        )
    return plan


def execute_node_tool_plan(
    plan: list[dict[str, Any]],
    *,
    tool_runner: ToolRunner,
    facts: dict[str, Any] | None = None,
    tool_arguments: dict[str, dict[str, Any]] | None = None,
    document_version_ids: list[str] | None = None,
    evidence_facts: list[dict[str, Any]] | None = None,
    evidence_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    facts = facts or {}
    tool_arguments = tool_arguments or {}
    document_version_ids = document_version_ids or []
    atomic_results = []
    for item in plan:
        if not item.get("compilable"):
            atomic_results.append(
                {
                    "atomicCheckId": item.get("atomicCheckId"),
                    "result": "evidence_insufficient",
                    "toolResults": [],
                    "warnings": [f"unregistered_tools:{','.join(item.get('missingTools') or [])}"],
                }
            )
            continue
        outputs = []
        for tool_name in item.get("tools") or []:
            arguments = build_tool_arguments(
                tool_name,
                item,
                facts=facts,
                explicit=tool_arguments.get(tool_name) or {},
                document_version_ids=document_version_ids,
                evidence_facts=evidence_facts or [],
                evidence_refs=evidence_refs or [],
            )
            outputs.append(tool_runner(tool_name, arguments))
        atomic_results.append(
            {
                "atomicCheckId": item.get("atomicCheckId"),
                "result": aggregate_tool_results(outputs),
                "toolResults": outputs,
                "warnings": [],
            }
        )
    return {
        "result": aggregate_atomic_results(atomic_results),
        "atomicResults": atomic_results,
        "summary": summarize(atomic_results),
    }


def build_tool_arguments(
    tool_name: str,
    binding: dict[str, Any],
    *,
    facts: dict[str, Any],
    explicit: dict[str, Any],
    document_version_ids: list[str],
    evidence_facts: list[dict[str, Any]],
    evidence_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    arguments = {**dict(binding.get("parameters") or {}), **explicit}
    if tool_name in {
        "get_document_ocr_result",
        "extract_document_fields",
        "extract_table_records",
        "recognize_signatures_and_seals",
        "locate_evidence_fragment",
        "extract_welder_certificate",
    }:
        arguments.setdefault("documentVersionIds", document_version_ids)
    if tool_name == "validate_evidence_grounding":
        arguments.setdefault("facts", evidence_facts)
        arguments.setdefault("evidenceRefs", evidence_refs)
        return arguments
    arguments.setdefault("facts", facts)
    if tool_name == "check_required":
        arguments.setdefault("requiredFields", binding.get("requiredFacts") or [])
    return arguments


def aggregate_tool_results(outputs: list[dict[str, Any]]) -> str:
    business_results = [str(item.get("result")) for item in outputs if item.get("result")]
    execution_failed = any(item.get("status") in {"rejected", "failed", "error"} for item in outputs)
    if execution_failed:
        return "evidence_insufficient"
    if "failed" in business_results:
        return "failed"
    if any(item in {"evidence_insufficient", "human_review_required"} for item in business_results):
        return "evidence_insufficient"
    applicable = [item for item in business_results if item != "not_applicable"]
    if business_results and not applicable:
        return "not_applicable"
    if applicable and all(item == "passed" for item in applicable):
        return "passed"
    return "evidence_insufficient"


def aggregate_atomic_results(items: list[dict[str, Any]]) -> str:
    results = [str(item.get("result")) for item in items]
    if "failed" in results:
        return "failed"
    if not results or any(item == "evidence_insufficient" for item in results):
        return "evidence_insufficient"
    applicable = [item for item in results if item != "not_applicable"]
    if not applicable:
        return "not_applicable"
    return "passed" if all(item == "passed" for item in applicable) else "evidence_insufficient"


def summarize(items: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "atomicCheckCount": len(items),
        "passedCount": sum(1 for item in items if item.get("result") == "passed"),
        "failedCount": sum(1 for item in items if item.get("result") == "failed"),
        "evidenceInsufficientCount": sum(1 for item in items if item.get("result") == "evidence_insufficient"),
        "notApplicableCount": sum(1 for item in items if item.get("result") == "not_applicable"),
    }
