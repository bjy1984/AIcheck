from __future__ import annotations

from libs.business_pack import load_business_pack
from libs.review_orchestrator.runtime_tools import dispatch_runtime_tool, runtime_tool_catalog
from libs.review_tools import compile_node_tool_plan, execute_node_tool_plan


def test_all_engineering_node_plans_compile_against_runtime_catalog() -> None:
    pack = load_business_pack("engineering_inspection_v1")
    available = {item["name"] for item in runtime_tool_catalog()}
    plans = [compile_node_tool_plan(pack, f"R{node_id:02d}", available_tools=available) for node_id in range(1, 69)]

    assert sum(len(plan) for plan in plans) == 171
    assert all(item["compilable"] for plan in plans for item in plan)
    assert all(not item["missingTools"] for plan in plans for item in plan)
    assert {item["implementationStatus"] for plan in plans for item in plan} <= {
        "implemented",
        "pilot_implemented",
    }


def test_fixed_plan_runs_all_bound_tools_and_fails_closed_on_missing_facts() -> None:
    pack = load_business_pack("engineering_inspection_v1")
    available = {item["name"] for item in runtime_tool_catalog()}
    plan = compile_node_tool_plan(pack, "R02", available_tools=available)
    called: list[str] = []

    def runner(name: str, arguments: dict) -> dict:
        called.append(name)
        return dispatch_runtime_tool({}, name, arguments)

    output = execute_node_tool_plan(plan, tool_runner=runner, document_version_ids=[])

    assert output["result"] in {"failed", "evidence_insufficient"}
    assert output["result"] != "passed"
    assert output["summary"]["atomicCheckCount"] == len(plan)
    assert called == [tool for item in plan for tool in item["tools"]]


def test_aggregation_never_turns_failed_or_insufficient_into_passed() -> None:
    plan = [
        {
            "atomicCheckId": "AC-X-1",
            "sourceRuleId": "RX",
            "requiredFacts": ["x"],
            "tools": ["check_required"],
            "parameters": {},
            "compilable": True,
            "missingTools": [],
        }
    ]

    passed = execute_node_tool_plan(
        plan,
        facts={"x": 1},
        tool_runner=lambda name, args: dispatch_runtime_tool({}, name, args),
    )
    insufficient = execute_node_tool_plan(
        plan,
        facts={},
        tool_runner=lambda name, args: dispatch_runtime_tool({}, name, args),
    )

    assert passed["result"] == "passed"
    assert insufficient["result"] == "failed"
