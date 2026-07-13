from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

import yaml


CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "ocr_runtime.yaml"
SUPPORTED_MODES = {"local", "official", "hybrid_auto"}
DEFAULT_MAX_LONG_SIDE = 1920


def _env_bool(source: Mapping[str, str], name: str, default: bool) -> bool:
    value = source.get(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def load_ocr_runtime_config(path: Path | None = None) -> dict[str, Any]:
    with (path or CONFIG_PATH).open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise RuntimeError("OCR runtime config must be a mapping")
    return payload


def ocr_runtime_config(
    path: Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
    validate: bool = False,
) -> dict[str, Any]:
    source = env if env is not None else os.environ
    config = load_ocr_runtime_config(path)
    mode_env = str(config.get("modeEnv") or "AICHECK_OCR_PROVIDER_MODE")
    mode = str(source.get(mode_env) or config.get("defaultMode") or "hybrid_auto").strip().lower()
    if mode not in SUPPORTED_MODES:
        raise RuntimeError(f"Unsupported OCR provider mode: {mode}")

    providers = config.get("providers") if isinstance(config.get("providers"), dict) else {}
    aliyun = providers.get("aliyun_official") if isinstance(providers.get("aliyun_official"), dict) else {}
    local = providers.get("local") if isinstance(providers.get("local"), dict) else {}
    render = config.get("render") if isinstance(config.get("render"), dict) else {}
    fallback = config.get("fallback") if isinstance(config.get("fallback"), dict) else {}
    routing = config.get("routing") if isinstance(config.get("routing"), dict) else {}

    base_url_env = str(aliyun.get("baseUrlEnv") or "AICHECK_ALIYUN_OCR_BASE_URL")
    api_key_env = str(aliyun.get("apiKeyEnv") or "AICHECK_ALIYUN_OCR_API_KEY")
    base_url = str(source.get(base_url_env) or aliyun.get("defaultBaseUrl") or "").rstrip("/")
    api_key = str(source.get(api_key_env) or "")

    requested_max = source.get("AICHECK_OCR_MAX_LONG_SIDE") or render.get("maxLongSide") or DEFAULT_MAX_LONG_SIDE
    try:
        max_long_side = max(800, min(int(requested_max), DEFAULT_MAX_LONG_SIDE))
    except (TypeError, ValueError):
        max_long_side = DEFAULT_MAX_LONG_SIDE
    try:
        qwen_max_long_side = max(
            800,
            min(int(render.get("qwenMaxLongSide") or max_long_side), max_long_side),
        )
    except (TypeError, ValueError):
        qwen_max_long_side = max_long_side
    try:
        max_pages_per_batch = max(
            1,
            min(
                int(
                    source.get("AICHECK_ALIYUN_OCR_MAX_PAGES_PER_BATCH")
                    or render.get("maxPagesPerBatch")
                    or render.get("maxPages")
                    or 30
                ),
                30,
            ),
        )
    except (TypeError, ValueError):
        max_pages_per_batch = 30
    try:
        max_document_pages = max(
            max_pages_per_batch,
            min(
                int(
                    source.get("AICHECK_ALIYUN_OCR_MAX_DOCUMENT_PAGES")
                    or render.get("maxDocumentPages")
                    or 200
                ),
                200,
            ),
        )
    except (TypeError, ValueError):
        max_document_pages = 200
    try:
        max_cost_cny = max(
            0.01,
            min(
                float(
                    source.get("AICHECK_ALIYUN_OCR_MAX_COST_CNY_PER_DOCUMENT")
                    or render.get("maxCostCnyPerDocument")
                    or 5.0
                ),
                100.0,
            ),
        )
    except (TypeError, ValueError):
        max_cost_cny = 5.0

    def bounded_int(name: str, configured: Any, default: int, minimum: int, maximum: int) -> int:
        try:
            return max(minimum, min(int(source.get(name) or configured or default), maximum))
        except (TypeError, ValueError):
            return default

    formal_allowlist = {
        item.strip()
        for item in str(source.get("AICHECK_OCR_FORMAL_READINESS_PROFILE_ALLOWLIST") or "").split(",")
        if item.strip()
    }

    allow_local_heavy = _env_bool(
        source,
        "AICHECK_OCR_ALLOW_LOCAL_HEAVY_FALLBACK",
        bool(fallback.get("allowLocalHeavyFallback") or local.get("heavyFallbackEnabled")),
    )
    runtime = {
        "schemaVersion": str(config.get("schemaVersion") or "aicheck-ocr-runtime@1"),
        "mode": mode,
        "modeEnv": mode_env,
        "officialRequired": mode in {"official", "hybrid_auto"},
        "official": {
            "provider": "aliyun_model_studio",
            "baseUrl": base_url,
            "baseUrlRedacted": base_url.split("?", 1)[0],
            "baseUrlEnv": base_url_env,
            "apiKeyEnv": api_key_env,
            "apiKey": api_key,
            "apiKeyConfigured": bool(api_key),
            "primaryModel": str(
                source.get("AICHECK_ALIYUN_OCR_MODEL")
                or aliyun.get("primaryModel")
                or "qwen3.5-ocr"
            ),
            "comparisonModel": str(
                source.get("AICHECK_ALIYUN_OCR_COMPARISON_MODEL")
                or aliyun.get("comparisonModel")
                or "qwen-vl-ocr-2025-11-20"
            ),
            "timeoutSeconds": float(
                source.get("AICHECK_ALIYUN_OCR_TIMEOUT_SECONDS")
                or aliyun.get("timeoutSeconds")
                or 60
            ),
            "circuitFailureThreshold": int(aliyun.get("circuitFailureThreshold") or 3),
            "circuitOpenSeconds": int(aliyun.get("circuitOpenSeconds") or 60),
            "maxAttempts": int(aliyun.get("maxAttempts") or 3),
            "maxOutputTokens": max(
                1,
                min(
                    int(
                        source.get("AICHECK_ALIYUN_OCR_MAX_OUTPUT_TOKENS")
                        or aliyun.get("maxOutputTokens")
                        or 16384
                    ),
                    16384,
                ),
            ),
            "taskMaxOutputTokens": {
                "advanced_recognition": bounded_int(
                    "AICHECK_ALIYUN_OCR_ADVANCED_MAX_OUTPUT_TOKENS",
                    aliyun.get("advancedMaxOutputTokens"),
                    4096,
                    512,
                    8192,
                ),
                "key_information_extraction": bounded_int(
                    "AICHECK_ALIYUN_OCR_KIE_MAX_OUTPUT_TOKENS",
                    aliyun.get("kieMaxOutputTokens"),
                    2048,
                    256,
                    4096,
                ),
                "table_parsing": bounded_int(
                    "AICHECK_ALIYUN_OCR_TABLE_MAX_OUTPUT_TOKENS",
                    aliyun.get("tableMaxOutputTokens"),
                    8192,
                    1024,
                    16384,
                ),
            },
        },
        "render": {
            "maxLongSide": max_long_side,
            "qwenMaxLongSide": qwen_max_long_side,
            "jpegQuality": int(render.get("jpegQuality") or 90),
            "maxPages": max_pages_per_batch,
            "maxPagesPerBatch": max_pages_per_batch,
            "maxDocumentPages": max_document_pages,
            "maxCostCnyPerDocument": max_cost_cny,
            "structuredPageLimit": bounded_int(
                "AICHECK_OCR_STRUCTURED_PAGE_LIMIT",
                render.get("structuredPageLimit"),
                6,
                1,
                30,
            ),
            "sealRoiLimitPerDocument": bounded_int(
                "AICHECK_OCR_SEAL_ROI_LIMIT_PER_DOCUMENT",
                render.get("sealRoiLimitPerDocument"),
                6,
                1,
                30,
            ),
        },
        "control": {
            "globalCallConcurrency": bounded_int(
                "AICHECK_OCR_GLOBAL_CALL_CONCURRENCY", None, 4, 1, 32
            ),
            "globalDocumentConcurrency": bounded_int(
                "AICHECK_OCR_GLOBAL_DOCUMENT_CONCURRENCY", None, 2, 1, 16
            ),
            "capacityWaitSeconds": bounded_int(
                "AICHECK_OCR_CAPACITY_WAIT_SECONDS", None, 5, 0, 120
            ),
            "callLeaseSeconds": bounded_int(
                "AICHECK_OCR_CALL_LEASE_SECONDS", None, 180, 30, 600
            ),
            "documentLeaseSeconds": bounded_int(
                "AICHECK_OCR_DOCUMENT_LEASE_SECONDS", None, 300, 60, 1800
            ),
        },
        "routing": deepcopy(routing),
        "formalReadinessProfileAllowlist": sorted(formal_allowlist),
        "allowLocalHeavyFallback": allow_local_heavy,
        "allowSilentProviderFallback": _env_bool(
            source,
            "AICHECK_OCR_ALLOW_SILENT_PROVIDER_FALLBACK",
            bool(fallback.get("allowSilentProviderFallback")),
        ),
    }
    if validate and runtime["officialRequired"]:
        if not base_url:
            raise RuntimeError(f"{base_url_env} is required for OCR mode {mode}")
        if not api_key:
            raise RuntimeError(f"{api_key_env} is required for OCR mode {mode}")
        if runtime["allowSilentProviderFallback"]:
            raise RuntimeError("Silent OCR provider fallback is forbidden in official modes")
    return runtime


def ocr_runtime_public_config(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    runtime = ocr_runtime_config(env=env)
    official = runtime["official"]
    configured = bool(official["baseUrl"] and official["apiKeyConfigured"])
    return {
        "schemaVersion": runtime["schemaVersion"],
        "mode": runtime["mode"],
        "modeEnv": runtime["modeEnv"],
        "configured": configured if runtime["officialRequired"] else True,
        "officialRequired": runtime["officialRequired"],
        "provider": official["provider"] if runtime["officialRequired"] else "local",
        "baseUrl": official["baseUrlRedacted"],
        "baseUrlEnv": official["baseUrlEnv"],
        "apiKeyEnv": official["apiKeyEnv"],
        "apiKeyConfigured": official["apiKeyConfigured"],
        "primaryModel": official["primaryModel"],
        "comparisonModel": official["comparisonModel"],
        "maxLongSide": runtime["render"]["maxLongSide"],
        "qwenMaxLongSide": runtime["render"]["qwenMaxLongSide"],
        "maxPagesPerBatch": runtime["render"]["maxPagesPerBatch"],
        "maxDocumentPages": runtime["render"]["maxDocumentPages"],
        "maxCostCnyPerDocument": runtime["render"]["maxCostCnyPerDocument"],
        "structuredPageLimit": runtime["render"]["structuredPageLimit"],
        "sealRoiLimitPerDocument": runtime["render"]["sealRoiLimitPerDocument"],
        "taskMaxOutputTokens": official["taskMaxOutputTokens"],
        "control": runtime["control"],
        "formalReadinessProfileAllowlist": runtime["formalReadinessProfileAllowlist"],
        "allowLocalHeavyFallback": runtime["allowLocalHeavyFallback"],
        "allowSilentProviderFallback": runtime["allowSilentProviderFallback"],
    }


def official_ocr_enabled(runtime: dict[str, Any] | None = None) -> bool:
    current = runtime or ocr_runtime_config()
    return str(current.get("mode") or "") in {"official", "hybrid_auto"}


def official_ocr_primary_enabled(
    pipeline_mode: str,
    runtime: dict[str, Any] | None = None,
) -> bool:
    return official_ocr_enabled(runtime) and str(pipeline_mode).strip().lower() == "active"


def local_heavy_ocr_enabled(runtime: dict[str, Any] | None = None) -> bool:
    current = runtime or ocr_runtime_config()
    return str(current.get("mode") or "") == "local" or bool(current.get("allowLocalHeavyFallback"))


def page_render_max_long_side() -> int:
    return int(ocr_runtime_config()["render"]["maxLongSide"])


def qwen_render_max_long_side() -> int:
    return int(ocr_runtime_config()["render"]["qwenMaxLongSide"])
