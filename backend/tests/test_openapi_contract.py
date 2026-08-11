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


def test_generated_contract_artifact_is_current() -> None:
    """openapi/generated/openapi.json 必须与实现零漂移（issue #10 的最终形态）。

    审计的建议就是「从 FastAPI 自动导出 openapi 作为唯一契约源 + CI diff 检查」。
    这个工件覆盖实现侧全部 652 个路径，前端/外部集成方对齐时以它为准；
    手工 fragment 文件继续存在，用于给高频端点补充人写的说明与示例。

    实现一变、忘了重新导出 → 本测试失败。重新导出：
        python -m scripts.openapi_route_coverage --export ../openapi/generated/openapi.json
    """
    import json
    from pathlib import Path

    from apps.api.main import app

    artifact_path = Path(__file__).resolve().parents[2] / "openapi" / "generated" / "openapi.json"
    assert artifact_path.exists(), "缺少生成的契约工件，先跑 --export 生成"

    committed = json.loads(artifact_path.read_text(encoding="utf-8"))
    live = json.loads(json.dumps(app.openapi(), ensure_ascii=False, sort_keys=True, default=str))

    def business_paths(document: dict) -> set[str]:
        # mock 路由只在兼容模式下挂载，不属于业务契约，两侧都排除
        return {
            path
            for path in (document.get("paths") or {})
            if not path.startswith(("/mock/", "/api/mock/"))
        }

    committed_paths = business_paths(committed)
    live_paths = business_paths(live)
    only_committed = sorted(committed_paths - live_paths)[:10]
    only_live = sorted(live_paths - committed_paths)[:10]
    assert committed_paths == live_paths, (
        f"契约工件与实现的路径集合不一致。工件独有: {only_committed}；实现独有: {only_live}。"
        "重新导出：python -m scripts.openapi_route_coverage --export ../openapi/generated/openapi.json"
    )

    # 路径集合一致之外，每个路径的方法集合也要一致（比全文比较稳定，不受 schema 序列化细节影响）
    for path in sorted(live_paths):
        committed_methods = {k for k in (committed["paths"][path] or {}) if k in {"get", "post", "put", "patch", "delete"}}
        live_methods = {k for k in (live["paths"][path] or {}) if k in {"get", "post", "put", "patch", "delete"}}
        assert committed_methods == live_methods, (
            f"{path} 的方法集合漂移：工件 {sorted(committed_methods)} vs 实现 {sorted(live_methods)}"
        )
