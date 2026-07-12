from __future__ import annotations

import os
from typing import Any

from libs.material_review_assets import material_review_asset_status
from libs.aliyun_ocr import official_ocr_circuit_breaker
from libs.ocr_runtime import ocr_runtime_config, ocr_runtime_public_config
from scripts.setup_langgraph_checkpoint import REQUIRED_TABLES, verify_checkpoint_schema


def workflow_schema_status() -> dict[str, Any]:
    orchestration = os.getenv("AICHECK_REVIEW_ORCHESTRATION", "legacy").strip().lower()
    checkpoint_disabled = os.getenv("AICHECK_LANGGRAPH_CHECKPOINT_DISABLE", "false").strip().lower() == "true"
    if orchestration != "temporal" or checkpoint_disabled:
        return {"ready": True, "required": False, "tableCount": 0, "missingTables": []}
    dsn = os.getenv("LANGGRAPH_CHECKPOINT_DSN", "").strip()
    if not dsn:
        return {
            "ready": False,
            "required": True,
            "tableCount": 0,
            "missingTables": sorted(REQUIRED_TABLES),
            "reason": "LANGGRAPH_CHECKPOINT_DSN is not configured",
        }
    try:
        found = verify_checkpoint_schema(dsn)
    except Exception as exc:
        return {
            "ready": False,
            "required": True,
            "tableCount": 0,
            "missingTables": sorted(REQUIRED_TABLES),
            "reason": f"{exc.__class__.__name__}: checkpoint schema probe failed",
        }
    missing = sorted(REQUIRED_TABLES - found)
    return {
        "ready": not missing,
        "required": True,
        "tableCount": len(found),
        "missingTables": missing,
    }


def audit_service_configuration_status() -> dict[str, Any]:
    qwen_mode = os.getenv("AICHECK_QWEN_CALL_MODE", "server").strip().lower()
    ocr_runtime = ocr_runtime_config()
    ocr_public = ocr_runtime_public_config()
    official_mode = ocr_runtime["mode"] in {"official", "hybrid_auto"}
    ocr_configured = (
        bool(ocr_public.get("configured"))
        if official_mode
        else bool(os.getenv("AICHECK_OCR_BASE_URL", "").strip())
    )
    return {
        "ocr": {
            "configured": ocr_configured,
            "executionBoundary": "official_api_with_local_light" if official_mode else "remote_service_only",
            "providerMode": ocr_public.get("mode"),
            "provider": ocr_public.get("provider"),
            "model": ocr_public.get("primaryModel"),
            "maxLongSide": ocr_public.get("maxLongSide"),
            "localHeavyFallbackEnabled": ocr_public.get("allowLocalHeavyFallback"),
            "silentFallbackEnabled": ocr_public.get("allowSilentProviderFallback"),
            "circuitBreaker": official_ocr_circuit_breaker(ocr_runtime).public_status(),
        },
        "qwen": {
            "configured": bool(os.getenv("QWEN_API_KEY", "").strip()) if qwen_mode == "official_api" else True,
            "mode": qwen_mode,
            "fallbackEnabled": os.getenv("AICHECK_QWEN_ALLOW_SERVER_FALLBACK", "false").strip().lower() == "true",
        },
        "embedding": {
            "configured": bool(os.getenv("AICHECK_EMBEDDING_API_BASE", "").strip()),
            "provider": os.getenv("AICHECK_EMBEDDING_PROVIDER", "local").strip().lower(),
        },
        "temporal": {
            "configured": bool(os.getenv("TEMPORAL_ADDRESS", "").strip()),
            "mode": os.getenv("AICHECK_REVIEW_ORCHESTRATION", "legacy").strip().lower(),
        },
    }


def production_runtime_status() -> dict[str, Any]:
    workflow = workflow_schema_status()
    material = material_review_asset_status()
    services = audit_service_configuration_status()
    required_service_keys = ["ocr", "qwen", "embedding", "temporal"]
    services_ready = all(bool(services[key].get("configured")) for key in required_service_keys)
    runtime_ready = bool(workflow.get("ready")) and bool(material.get("ready"))
    if os.getenv("AICHECK_STRICT_PRODUCTION", "false").strip().lower() == "true":
        runtime_ready = runtime_ready and services_ready
    return {
        "runtimeReady": runtime_ready,
        "workflowSchemaReady": bool(workflow.get("ready")),
        "workflowSchema": workflow,
        "materialMappingReady": bool(material.get("ready")),
        "materialMappingVersion": material.get("version"),
        "materialMappingCount": material.get("itemCount"),
        "materialMappingHash": material.get("sourceSha256"),
        "serviceReadiness": services,
    }
