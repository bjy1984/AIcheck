from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.openapi_contract import (
    FRONTEND_OPERATION_MAP_PATH,
    INDEX_PATH,
    build_contract_index,
    render_frontend_operation_map,
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
