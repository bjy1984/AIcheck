from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.openapi_contract import (
    FRONTEND_OPERATION_MAP_PATH,
    INDEX_PATH,
    OpenApiContractError,
    build_contract_index,
    render_frontend_operation_map,
    validate_operation,
)


def test_openapi_contract_fragments_are_codegen_ready() -> None:
    index = build_contract_index()

    assert index["entrypoint"] == "openapi/aicheck.yaml"
    assert index["operationCount"] >= 20
    operation_ids = {item["operationId"] for item in index["operations"]}
    assert {
        "reports_get_detail",
        "reports_update_draft",
        "archive_create_package",
        "archive_create_evidence_package",
        "exports_get_task",
    }.issubset(operation_ids)
    assert index["codegenTargets"][0]["target"] == "frontend/src/api/aicheck/generated/operation-map.ts"


def test_openapi_contract_index_is_current() -> None:
    generated = build_contract_index()
    stored = json.loads(INDEX_PATH.read_text(encoding="utf-8"))

    assert stored == generated


def test_openapi_frontend_operation_map_is_current() -> None:
    generated = render_frontend_operation_map(build_contract_index())
    stored = FRONTEND_OPERATION_MAP_PATH.read_text(encoding="utf-8")

    assert stored == generated


def test_openapi_validator_rejects_missing_request_and_response_schemas() -> None:
    operation = {
        "operationId": "review_runs_update_decision",
        "security": [{"bearerAuth": []}],
        "parameters": [{"name": "reviewRunId"}, {"name": "Idempotency-Key"}],
        "requestBody": {"required": True, "content": {"application/json": {"example": {"decision": "accept"}}}},
        "responses": {
            code: {
                "content": {
                    "application/json": {
                        "example": {"code": 0 if code == "200" else 400, "data": {}}
                    }
                }
            }
            for code in ["200", "400", "401", "403", "404", "409"]
        },
    }

    with pytest.raises(OpenApiContractError, match="requestBody must declare"):
        validate_operation("/api/review-runs/{reviewRunId}/human-decision", "post", operation)


def test_contract_declares_nothing_the_implementation_lacks() -> None:
    """契约里不能有实现侧不存在的操作（issue #10 / A-4）。

    「文档说 A、实现是 B」比「文档没写」更糟——调用方按文档写代码，撞上 404
    才发现。发现时实测有两条：契约写 /admin/config/overview 而实现是
    /admin/config-overview；/submissions/submit 实现里根本不存在。
    行为快照式的契约测试发现不了这类差异，只能靠这条结构对比。
    """
    from scripts.openapi_route_coverage import coverage_report

    report = coverage_report()
    assert report["staleContractOperations"] == [], (
        f"这些操作契约里有、实现里没有：{report['staleContractOperations']}"
    )


def test_contract_coverage_does_not_regress() -> None:
    """覆盖率棘轮：只许涨不许跌。

    手工契约当前只覆盖实现的一小部分（发现时 6.6%）。一次补全 355 条不现实，
    但必须防止边补边掉。每补一批就把这个下限往上调。
    """
    from scripts.openapi_route_coverage import coverage_report

    minimum_covered_operations = 25
    report = coverage_report()
    assert report["coveredOperationCount"] >= minimum_covered_operations, (
        f"契约覆盖的操作数从 {minimum_covered_operations} 掉到了 "
        f"{report['coveredOperationCount']}——契约与实现正在反向漂移。"
    )
