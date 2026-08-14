from __future__ import annotations

import os
from typing import Any

from libs.material_review_assets import material_review_asset_status
from libs.aliyun_ocr import official_ocr_circuit_breaker
from libs.ocr_runtime import ocr_runtime_config, ocr_runtime_public_config
from libs.official_ocr_control import official_ocr_control_status
from libs.qwen_runtime import redact_url, server_mode_base_url
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


def qwen_configuration_status(qwen_mode: str) -> dict[str, Any]:
    """模型链路是否真的配好了。

    ## 这里原来写的是 `True`

        "configured": bool(os.getenv("QWEN_API_KEY")) if mode == "official_api" else True,

    server 模式（也是 defaultMode）下无条件返回 True，不看地址、不看密钥。
    而 production_runtime_status 取值用的是 `get("ready", get("configured"))`，
    qwen 没有 ready 键，于是一路读到这个恒真的 configured。

    代价：2026-08-10 到 08-14，线上没有任何模型可用——litellm 容器从未创建过，
    LITELLM_BASE_URL 也没配，调用一律打向解析不了的 `litellm-service:4000`。
    这四天里生产就绪报告始终显示 qwen 正常。**一个恒真的健康检查比没有健康检查更坏**，
    因为它会让人停止怀疑。

    ## 判定口径

    server 模式：要有一个明确配置过的地址。LiteLLMClient 的缺省值
    `http://litellm-service:4000` 是 compose 内部主机名，脱离 compose 必然解析失败，
    因此「没配地址」等价于「没配好」，不能算就绪。

    official_api 模式：要有 QWEN_API_KEY。

    这里只做配置层判定，**不发网络探测**——就绪接口会被健康检查高频调用，
    在里面打外部请求会把模型的抖动变成本服务的抖动。真实可达性由调用侧的
    失败原因回报（见 libs/review_conversation_fallback）。
    """
    mode = str(qwen_mode or "").strip().lower()
    if mode == "official_api":
        configured = bool(os.getenv("QWEN_API_KEY", "").strip())
        reason = "" if configured else "QWEN_API_KEY 未配置"
        base_url = os.getenv("QWEN_API_BASE", "").strip()
    else:
        base_url = server_mode_base_url()
        configured = bool(base_url)
        reason = (
            ""
            if configured
            else "server 模式未配置模型网关地址（AICHECK_QWEN_SERVER_BASE_URL 或 LITELLM_BASE_URL）"
        )
    return {
        "configured": configured,
        # 显式给出 ready，不再让上游回退到 configured——两者含义相同时也要写出来，
        # 省得下一个人再踩「没有 ready 键就读 configured」这条隐式规则。
        "ready": configured,
        "mode": mode,
        "baseUrl": redact_url(base_url),
        "reason": reason,
        "fallbackEnabled": os.getenv("AICHECK_QWEN_ALLOW_SERVER_FALLBACK", "false").strip().lower() == "true",
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
    control_status = official_ocr_control_status(ocr_runtime) if official_mode else {
        "ready": True,
        "distributed": False,
    }
    circuit_status = official_ocr_circuit_breaker(ocr_runtime).public_status()
    return {
        "ocr": {
            "configured": ocr_configured,
            "ready": bool(ocr_configured and control_status.get("ready") and not circuit_status.get("open")),
            "executionBoundary": "official_api_with_local_light" if official_mode else "remote_service_only",
            "providerMode": ocr_public.get("mode"),
            "provider": ocr_public.get("provider"),
            "model": ocr_public.get("primaryModel"),
            "maxLongSide": ocr_public.get("maxLongSide"),
            "localHeavyFallbackEnabled": ocr_public.get("allowLocalHeavyFallback"),
            "silentFallbackEnabled": ocr_public.get("allowSilentProviderFallback"),
            "circuitBreaker": circuit_status,
            "capacityControl": control_status,
            "formalReadinessProfileAllowlist": ocr_public.get("formalReadinessProfileAllowlist") or [],
        },
        "qwen": qwen_configuration_status(qwen_mode),
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
    services_ready = all(
        bool(services[key].get("ready", services[key].get("configured")))
        for key in required_service_keys
    )
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
