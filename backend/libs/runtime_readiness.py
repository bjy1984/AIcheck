from __future__ import annotations

import asyncio
import math
import os
import threading
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor, wait
from copy import deepcopy
from typing import Any

from libs.aliyun_ocr import official_ocr_circuit_breaker
from libs.material_review_assets import material_review_asset_status
from libs.ocr_runtime import ocr_runtime_config, ocr_runtime_public_config
from libs.official_ocr_control import official_ocr_control_status
from libs.qwen_runtime import qwen_runtime_config, redact_url, server_mode_base_url
from scripts.setup_langgraph_checkpoint import REQUIRED_TABLES


ReviewDependencyProvider = Callable[[], Mapping[str, Any]]
WorkerHeartbeatRowsProvider = Callable[[], list[Mapping[str, Any]]]
_TEMPORAL_DEPENDENCY_REASON_CODES = {
    "service": "temporal_service_unavailable",
    "schema": "temporal_schema_unavailable",
    "workerHeartbeat": "temporal_worker_unavailable",
}
_review_readiness_cache: tuple[tuple[str, ...], float, dict[str, Any]] | None = None
_review_readiness_cache_lock = threading.Lock()
_review_readiness_refresh_lock = threading.Lock()


def _probe_timeout_seconds() -> float:
    try:
        return min(2.0, max(0.1, float(os.getenv("AICHECK_REVIEW_READINESS_PROBE_TIMEOUT_SECONDS", "0.75"))))
    except ValueError:
        return 0.75


def _cache_ttl_seconds() -> float:
    try:
        return min(30.0, max(1.0, float(os.getenv("AICHECK_REVIEW_READINESS_TTL_SECONDS", "5"))))
    except ValueError:
        return 5.0


def _postgres_probe_kwargs() -> dict[str, Any]:
    timeout = _probe_timeout_seconds()
    return {
        "connect_timeout": max(1, math.ceil(timeout)),
        "options": f"-c statement_timeout={max(100, math.ceil(timeout * 1000))}",
    }


def _readiness_cache_key() -> tuple[str, ...]:
    return (
        os.getenv("AICHECK_REVIEW_ORCHESTRATION", "legacy").strip().lower() or "legacy",
        os.getenv("AICHECK_TASK_DISPATCH", "disabled").strip().lower() or "disabled",
        os.getenv("AICHECK_STRICT_PRODUCTION", "false").strip().lower(),
        os.getenv("TEMPORAL_ADDRESS", "localhost:7233").strip(),
        os.getenv("TEMPORAL_NAMESPACE", "default").strip(),
        os.getenv("LANGGRAPH_CHECKPOINT_DSN", "").strip(),
        str(os.getenv("AICHECK_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip(),
        os.getenv("AICHECK_LANGGRAPH_CHECKPOINT_DISABLE", "false").strip().lower(),
    )


def temporal_service_connectivity_status() -> dict[str, Any]:
    """Perform the same bounded Temporal protocol handshake used for dispatch readiness."""
    address = os.getenv("TEMPORAL_ADDRESS", "localhost:7233").strip() or "localhost:7233"
    namespace = os.getenv("TEMPORAL_NAMESPACE", "default").strip() or "default"

    async def connect() -> None:
        from temporalio.client import Client

        await Client.connect(address, namespace=namespace)

    try:
        asyncio.run(asyncio.wait_for(connect(), timeout=_probe_timeout_seconds()))
    except Exception as exc:
        return {
            "configured": True,
            "ready": False,
            "address": address,
            "namespace": namespace,
            "errorType": type(exc).__name__,
        }
    return {
        "configured": True,
        "ready": True,
        "address": address,
        "namespace": namespace,
    }


def review_worker_heartbeat_status(
    rows_provider: WorkerHeartbeatRowsProvider | None = None,
) -> dict[str, Any]:
    """Require every fresh review worker to poll the API's Temporal deployment identity."""
    expected_task_queue = os.getenv("AICHECK_REVIEW_WORKFLOW_TASK_QUEUE", "review.workflow").strip()
    expected_temporal_address = os.getenv("TEMPORAL_ADDRESS", "localhost:7233").strip() or "localhost:7233"
    expected_temporal_namespace = os.getenv("TEMPORAL_NAMESPACE", "default").strip() or "default"
    try:
        max_age_seconds = max(
            1,
            int(os.getenv("AICHECK_REVIEW_WORKER_HEARTBEAT_MAX_AGE_SECONDS", "30")),
        )
    except ValueError:
        max_age_seconds = 30
    if rows_provider is not None:
        rows = list(rows_provider())
    else:
        dsn = os.getenv("AICHECK_DATABASE_URL") or os.getenv("DATABASE_URL")
        if not dsn:
            return {
                "ready": False,
                "activeCount": 0,
                "lastSeenAt": None,
                "statusReason": "review_worker_heartbeat_database_unavailable",
                "reasonCodes": ["review_worker_heartbeat_database_unavailable"],
                "expectedTaskQueue": expected_task_queue,
                "expectedTemporalAddress": expected_temporal_address,
                "expectedTemporalNamespace": expected_temporal_namespace,
            }
        try:
            import psycopg

            with psycopg.connect(dsn, **_postgres_probe_kwargs()) as connection:
                database_rows = connection.execute(
                    """
                    SELECT payload, last_seen_at
                    FROM service_heartbeats
                    WHERE service_role = 'review-worker'
                      AND last_seen_at >= now() - (%s * interval '1 second')
                    ORDER BY last_seen_at DESC
                    """,
                    (max_age_seconds,),
                ).fetchall()
                connection.rollback()
            rows = [
                {"payload": row[0], "lastSeenAt": row[1]}
                for row in database_rows
            ]
        except Exception as exc:
            return {
                "ready": False,
                "activeCount": 0,
                "lastSeenAt": None,
                "statusReason": "review_worker_heartbeat_probe_failed",
                "reasonCodes": ["review_worker_heartbeat_probe_failed"],
                "expectedTaskQueue": expected_task_queue,
                "expectedTemporalAddress": expected_temporal_address,
                "expectedTemporalNamespace": expected_temporal_namespace,
                "errorType": type(exc).__name__,
            }
    if not rows:
        return {
            "ready": False,
            "activeCount": 0,
            "lastSeenAt": None,
            "statusReason": "review_worker_heartbeat_unavailable",
            "reasonCodes": ["review_worker_heartbeat_unavailable"],
            "expectedTaskQueue": expected_task_queue,
            "expectedTemporalAddress": expected_temporal_address,
            "expectedTemporalNamespace": expected_temporal_namespace,
            "observedTaskQueues": [],
            "observedTemporalAddresses": [],
            "observedTemporalNamespaces": [],
            "missingIdentityCount": 0,
            "maxAgeSeconds": max_age_seconds,
        }

    payloads = [row.get("payload") if isinstance(row, Mapping) else None for row in rows]
    valid_payloads = [dict(payload) for payload in payloads if isinstance(payload, Mapping)]
    missing_identity_count = sum(
        1
        for payload in payloads
        if not isinstance(payload, Mapping)
        or not str(payload.get("taskQueue") or "").strip()
        or not str(payload.get("temporalAddress") or "").strip()
        or not str(payload.get("temporalNamespace") or "").strip()
    )
    observed_task_queues = sorted(
        {str(payload.get("taskQueue") or "").strip() for payload in valid_payloads}
        - {""}
    )
    observed_temporal_addresses = sorted(
        {str(payload.get("temporalAddress") or "").strip() for payload in valid_payloads}
        - {""}
    )
    observed_temporal_namespaces = sorted(
        {str(payload.get("temporalNamespace") or "").strip() for payload in valid_payloads}
        - {""}
    )
    reason_codes: list[str] = []
    if missing_identity_count:
        reason_codes.append("review_worker_identity_missing")
    if any(queue != expected_task_queue for queue in observed_task_queues):
        reason_codes.append("review_worker_task_queue_mismatch")
    if any(address != expected_temporal_address for address in observed_temporal_addresses):
        reason_codes.append("review_worker_temporal_address_mismatch")
    if any(namespace != expected_temporal_namespace for namespace in observed_temporal_namespaces):
        reason_codes.append("review_worker_temporal_namespace_mismatch")
    last_seen_values = [
        row.get("lastSeenAt")
        for row in rows
        if isinstance(row, Mapping) and row.get("lastSeenAt") is not None
    ]
    last_seen_at = max((str(value) for value in last_seen_values), default=None)
    return {
        "ready": not reason_codes,
        "activeCount": len(rows),
        "lastSeenAt": last_seen_at,
        "statusReason": reason_codes[0] if reason_codes else "review_worker_heartbeat_ready",
        "reasonCodes": reason_codes,
        "expectedTaskQueue": expected_task_queue,
        "expectedTemporalAddress": expected_temporal_address,
        "expectedTemporalNamespace": expected_temporal_namespace,
        "observedTaskQueues": observed_task_queues,
        "observedTemporalAddresses": observed_temporal_addresses,
        "observedTemporalNamespaces": observed_temporal_namespaces,
        "missingIdentityCount": missing_identity_count,
        "maxAgeSeconds": max_age_seconds,
    }


def live_review_runtime_dependencies() -> dict[str, dict[str, Any]]:
    """Collect bounded read-only probes concurrently for health-driven refreshes."""
    probes = {
        "service": temporal_service_connectivity_status,
        "schema": workflow_schema_status,
        "workerHeartbeat": review_worker_heartbeat_status,
    }
    executor = ThreadPoolExecutor(max_workers=len(probes), thread_name_prefix="review-readiness")
    futures = {key: executor.submit(probe) for key, probe in probes.items()}
    done, pending = wait(futures.values(), timeout=_probe_timeout_seconds() + 0.25)
    results: dict[str, dict[str, Any]] = {}
    for key, future in futures.items():
        if future in done:
            try:
                results[key] = future.result()
            except Exception as exc:
                results[key] = {"ready": False, "errorType": type(exc).__name__}
        else:
            results[key] = {"ready": False, "errorType": "ReadinessProbeTimeout"}
    for future in pending:
        future.cancel()
    executor.shutdown(wait=False, cancel_futures=True)
    return results


def review_runtime_dependency_snapshot(
    dependency_provider: ReviewDependencyProvider | None = None,
) -> dict[str, Any]:
    """Normalize live or injected dependency probes into one stable readiness contract."""
    raw = dict((dependency_provider or live_review_runtime_dependencies)())
    dependency_details: dict[str, dict[str, Any]] = {}
    dependencies: dict[str, bool] = {}
    for key in _TEMPORAL_DEPENDENCY_REASON_CODES:
        value = raw.get(key, False)
        if isinstance(value, Mapping):
            detail = dict(value)
            ready = bool(detail.get("ready"))
        else:
            ready = bool(value)
            detail = {"ready": ready}
        dependencies[key] = ready
        dependency_details[key] = detail
    reason_codes = [
        reason_code
        for key, reason_code in _TEMPORAL_DEPENDENCY_REASON_CODES.items()
        if not dependencies[key]
    ]
    ready = not reason_codes
    # A missing worker is the most immediate dispatch blocker, followed by its
    # schema and then transport. reasonCodes still reports every failed probe.
    status_reason = "temporal_dependencies_ready"
    for key in ("workerHeartbeat", "schema", "service"):
        if not dependencies[key]:
            status_reason = _TEMPORAL_DEPENDENCY_REASON_CODES[key]
            break
    return {
        "ready": ready,
        "mode": "temporal",
        "orchestrationMode": "temporal",
        "statusReason": status_reason,
        "reasonCodes": reason_codes,
        "dependencies": dependencies,
        "dependencyDetails": dependency_details,
    }


def _mode_aware_review_dispatch_readiness(
    dependency_provider: ReviewDependencyProvider | None = None,
) -> dict[str, Any]:
    orchestration_mode = os.getenv("AICHECK_REVIEW_ORCHESTRATION", "legacy").strip().lower() or "legacy"
    strict = os.getenv("AICHECK_STRICT_PRODUCTION", "false").strip().lower() == "true"
    if orchestration_mode == "temporal":
        return review_runtime_dependency_snapshot(dependency_provider)
    if orchestration_mode == "inline":
        return {
            "ready": not strict,
            "mode": "inline",
            "orchestrationMode": "inline",
            "statusReason": "inline_local_development_only" if strict else "inline_local_development_enabled",
            "deploymentScope": "local_development",
        }
    dispatch_mode = os.getenv("AICHECK_TASK_DISPATCH", "disabled").strip().lower() or "disabled"
    if dispatch_mode == "celery":
        return {
            "ready": True,
            "mode": "celery",
            "orchestrationMode": orchestration_mode,
            "statusReason": "task_dispatch_enabled",
        }
    if dispatch_mode == "inline":
        return {
            "ready": not strict,
            "mode": "inline",
            "orchestrationMode": orchestration_mode,
            "statusReason": "inline_local_development_only" if strict else "task_dispatch_enabled",
            "deploymentScope": "local_development",
        }
    return {
        "ready": False,
        "mode": dispatch_mode,
        "orchestrationMode": orchestration_mode,
        "statusReason": "task_dispatch_disabled",
    }


def _uncached_temporal_snapshot(reason: str, *, stale: bool) -> dict[str, Any]:
    return {
        "ready": False,
        "mode": "temporal",
        "orchestrationMode": "temporal",
        "statusReason": reason,
        "reasonCodes": [reason],
        "dependencies": {"service": False, "schema": False, "workerHeartbeat": False},
        "dependencyDetails": {},
        "cache": {
            "fresh": False,
            "stale": stale,
            "ttlSeconds": _cache_ttl_seconds(),
        },
    }


def cached_review_dispatch_readiness(
    *,
    refresh_if_stale: bool = False,
    dependency_provider: ReviewDependencyProvider | None = None,
) -> dict[str, Any]:
    """Return the mode-aware readiness contract; only health callers may refresh live probes."""
    global _review_readiness_cache

    orchestration_mode = os.getenv("AICHECK_REVIEW_ORCHESTRATION", "legacy").strip().lower() or "legacy"
    if orchestration_mode != "temporal":
        return _mode_aware_review_dispatch_readiness(dependency_provider)
    if dependency_provider is not None:
        return _mode_aware_review_dispatch_readiness(dependency_provider)

    key = _readiness_cache_key()
    ttl = _cache_ttl_seconds()
    now = time.monotonic()
    with _review_readiness_cache_lock:
        cached = _review_readiness_cache
    if cached and cached[0] == key and now - cached[1] <= ttl:
        return deepcopy(cached[2])
    if not refresh_if_stale:
        return _uncached_temporal_snapshot(
            "temporal_readiness_snapshot_stale" if cached and cached[0] == key else "temporal_readiness_snapshot_unavailable",
            stale=bool(cached and cached[0] == key),
        )

    with _review_readiness_refresh_lock:
        now = time.monotonic()
        with _review_readiness_cache_lock:
            cached = _review_readiness_cache
        if cached and cached[0] == key and now - cached[1] <= ttl:
            return deepcopy(cached[2])
        refreshed = _mode_aware_review_dispatch_readiness()
        completed_at = time.monotonic()
        refreshed["cache"] = {
            "fresh": True,
            "stale": False,
            "ttlSeconds": ttl,
            "observedAtEpoch": time.time(),
        }
        with _review_readiness_cache_lock:
            _review_readiness_cache = (key, completed_at, refreshed)
        return deepcopy(refreshed)


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
        import psycopg

        with psycopg.connect(dsn, **_postgres_probe_kwargs()) as connection:
            rows = connection.execute(
                "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'public'"
            ).fetchall()
            connection.rollback()
        found = {str(row[0]) for row in rows} & REQUIRED_TABLES
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


def qwen_configuration_status() -> dict[str, Any]:
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

    official_api 模式：要有地址和密钥（AICHECK_LLM_API_BASE / AICHECK_LLM_API_KEY，
    旧名 QWEN_API_BASE / QWEN_API_KEY 仍可用）。

    这里只做配置层判定，**不发网络探测**——就绪接口会被健康检查高频调用，
    在里面打外部请求会把模型的抖动变成本服务的抖动。真实可达性由调用侧的
    失败原因回报（见 libs/review_conversation_fallback）。
    """
    # 模式只从 runtime 配置取一次。此前调用方另外读一遍 AICHECK_QWEN_CALL_MODE
    # 再传进来，两个来源可以不一致——这轮排查里反复出现的就是这类「两个数字互相
    # 打脸、但都不报错」。
    runtime = qwen_runtime_config()
    mode = str(runtime.get("mode") or "").strip().lower()
    if mode == "official_api":
        # 走 runtime 配置而不是直接读 QWEN_API_KEY：通用变量 AICHECK_LLM_API_KEY
        # 优先，直接读旧变量会把配好的部署误判成没配。
        base_url = str(runtime.get("baseUrl") or "")
        configured = bool(runtime.get("apiKeyConfigured")) and bool(base_url)
        if configured:
            reason = ""
        elif not base_url:
            reason = "official_api 模式未配置模型地址（AICHECK_LLM_API_BASE 或 QWEN_API_BASE）"
        else:
            reason = "模型密钥未配置（AICHECK_LLM_API_KEY 或 QWEN_API_KEY）"
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
        # 报实际供应商，不报模式意图——地址指着 DeepSeek 就不该写 DashScope
        "provider": runtime.get("provider"),
        "reason": reason,
        "fallbackEnabled": os.getenv("AICHECK_QWEN_ALLOW_SERVER_FALLBACK", "false").strip().lower() == "true",
    }


def audit_service_configuration_status() -> dict[str, Any]:
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
        "qwen": qwen_configuration_status(),
        "embedding": {
            "configured": bool(os.getenv("AICHECK_EMBEDDING_API_BASE", "").strip()),
            "provider": os.getenv("AICHECK_EMBEDDING_PROVIDER", "local").strip().lower(),
        },
        "temporal": {
            "configured": bool(os.getenv("TEMPORAL_ADDRESS", "").strip()),
            "mode": os.getenv("AICHECK_REVIEW_ORCHESTRATION", "legacy").strip().lower(),
        },
    }


def production_runtime_status(
    *,
    review_dependency_provider: ReviewDependencyProvider | None = None,
    refresh_review_readiness: bool = False,
) -> dict[str, Any]:
    orchestration_mode = os.getenv("AICHECK_REVIEW_ORCHESTRATION", "legacy").strip().lower() or "legacy"
    strict = os.getenv("AICHECK_STRICT_PRODUCTION", "false").strip().lower() == "true"
    review_readiness = cached_review_dispatch_readiness(
        refresh_if_stale=refresh_review_readiness,
        dependency_provider=review_dependency_provider,
    )
    if orchestration_mode == "temporal":
        workflow = dict((review_readiness.get("dependencyDetails") or {}).get("schema") or {"ready": False})
        temporal_readiness = dict(
            (review_readiness.get("dependencyDetails") or {}).get("service") or {"ready": False}
        )
        temporal_readiness.update(
            {
                "serviceConnected": bool(temporal_readiness.get("ready")),
                "ready": bool(review_readiness["ready"]),
                "mode": "temporal",
                "statusReason": review_readiness["statusReason"],
            }
        )
    else:
        workflow = workflow_schema_status()
        temporal_readiness = {
            "ready": bool(review_readiness["ready"]),
            "mode": orchestration_mode,
            "configured": False,
            "required": False,
            "statusReason": review_readiness["statusReason"],
        }
    material = material_review_asset_status()
    services = audit_service_configuration_status()
    temporal_service = services.setdefault("temporal", {})
    temporal_service.update(
        {
            "ready": bool(temporal_readiness["ready"]),
            "required": orchestration_mode == "temporal",
            "statusReason": review_readiness["statusReason"],
        }
    )
    required_service_keys = ["ocr", "qwen", "embedding", "temporal"]
    services_ready = all(
        bool(services[key].get("ready", services[key].get("configured")))
        for key in required_service_keys
    )
    runtime_ready = (
        bool(workflow.get("ready"))
        and bool(material.get("ready"))
        and bool(review_readiness["ready"])
    )
    if strict:
        runtime_ready = runtime_ready and services_ready
    return {
        "runtimeReady": runtime_ready,
        "workflowReady": bool(review_readiness["ready"]),
        "workflowSchemaReady": bool(workflow.get("ready")),
        "workflowSchema": workflow,
        "reviewDispatchReadiness": review_readiness,
        "temporalReadiness": temporal_readiness,
        "materialMappingReady": bool(material.get("ready")),
        "materialMappingVersion": material.get("version"),
        "materialMappingCount": material.get("itemCount"),
        "materialMappingHash": material.get("sourceSha256"),
        "serviceReadiness": services,
    }
