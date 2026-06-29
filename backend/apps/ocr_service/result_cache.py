from __future__ import annotations

import hashlib
import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4

from libs.contracts.responses import server_time


RESULT_CACHE_SCHEMA = "aicheck-ocr-parse-result-cache-v3"
ENGINE_RESULT_CACHE_SCHEMA = "aicheck-ocr-engine-result-cache-v1"


def result_cache_enabled(options: dict[str, Any] | None = None) -> bool:
    if bool((options or {}).get("disableResultCache")):
        return False
    return os.getenv("AICHECK_OCR_DISABLE_RESULT_CACHE") != "true"


def result_cache_dir() -> Path:
    return Path(os.getenv("AICHECK_OCR_RESULT_CACHE_DIR") or (Path(tempfile.gettempdir()) / "aicheck-ocr-result-cache"))


def engine_result_cache_enabled(options: dict[str, Any] | None = None) -> bool:
    if bool((options or {}).get("disableEngineResultCache")):
        return False
    if bool((options or {}).get("disableEngineCache")):
        return False
    return os.getenv("AICHECK_OCR_DISABLE_ENGINE_RESULT_CACHE") != "true"


def engine_result_cache_dir() -> Path:
    return Path(
        os.getenv("AICHECK_OCR_ENGINE_RESULT_CACHE_DIR")
        or (Path(tempfile.gettempdir()) / "aicheck-ocr-engine-result-cache")
    )


def build_result_cache_key(
    source_path: Path,
    *,
    profile: dict[str, Any],
    model_manifest: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> str | None:
    if not result_cache_enabled(options) or not source_path.exists():
        return None
    payload = {
        "schemaVersion": RESULT_CACHE_SCHEMA,
        "sourceHash": file_hash(source_path),
        "profileId": profile.get("profileId"),
        "documentType": profile.get("documentType"),
        "postprocessVersion": profile.get("postprocessVersion") or "v1",
        "preprocessPolicy": profile.get("preprocessPolicy") or {},
        "modelManifestHash": stable_hash(model_manifest),
        "engineOptions": cache_relevant_options(options or {}),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def build_engine_result_cache_key(
    source_path: Path,
    *,
    engine_status: dict[str, Any],
    variant: dict[str, Any],
    profile: dict[str, Any],
    model_manifest: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> str | None:
    if not engine_result_cache_enabled(options) or not source_path.exists():
        return None
    payload = {
        "schemaVersion": ENGINE_RESULT_CACHE_SCHEMA,
        "sourceHash": file_hash(source_path),
        "engine": cacheable_engine_status(engine_status),
        "variant": cacheable_variant(variant),
        "profile": {
            "profileId": profile.get("profileId"),
            "documentType": profile.get("documentType"),
            "preprocessPolicy": profile.get("preprocessPolicy") or {},
        },
        "modelManifestHash": stable_hash(model_manifest),
        "engineOptions": cache_relevant_options(options or {}),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def load_result_cache(cache_key: str | None) -> dict[str, Any] | None:
    if not cache_key:
        return None
    cache_path = result_cache_dir() / f"{cache_key}.json"
    if not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("schemaVersion") != RESULT_CACHE_SCHEMA:
        return None
    result = payload.get("result")
    return deepcopy(result) if isinstance(result, dict) and result.get("status") == "success" else None


def load_engine_result_cache(cache_key: str | None) -> dict[str, Any] | None:
    if not cache_key:
        return None
    cache_path = engine_result_cache_dir() / f"{cache_key}.json"
    if not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("schemaVersion") != ENGINE_RESULT_CACHE_SCHEMA:
        return None
    raw = payload.get("raw")
    return deepcopy(raw) if isinstance(raw, dict) else None


def save_result_cache(cache_key: str | None, result: dict[str, Any]) -> None:
    if not cache_key or result.get("status") != "success":
        return
    result_cache_dir().mkdir(parents=True, exist_ok=True)
    payload = {
        "schemaVersion": RESULT_CACHE_SCHEMA,
        "savedAt": server_time(),
        "result": sanitized_cached_result(result),
    }
    try:
        (result_cache_dir() / f"{cache_key}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        return


def save_engine_result_cache(cache_key: str | None, raw: dict[str, Any]) -> None:
    if not cache_key or not engine_raw_is_cacheable(raw):
        return
    engine_result_cache_dir().mkdir(parents=True, exist_ok=True)
    payload = {
        "schemaVersion": ENGINE_RESULT_CACHE_SCHEMA,
        "savedAt": server_time(),
        "raw": deepcopy(raw),
    }
    try:
        (engine_result_cache_dir() / f"{cache_key}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        return


def rehydrate_cached_result(
    cached: dict[str, Any],
    *,
    cache_key: str,
    storage_key: str,
    file_name: str | None,
    document_version_id: str | None,
    business_pack_id: str | None,
) -> dict[str, Any]:
    result = deepcopy(cached)
    source_parse_result_id = result.get("parseResultId")
    result["parseResultId"] = f"PARSE-{uuid4().hex[:12].upper()}"
    result["storageKey"] = storage_key
    result["fileName"] = file_name
    result["documentVersionId"] = document_version_id
    result["businessPackId"] = business_pack_id
    result["createdAt"] = server_time()
    result["resultCacheHit"] = True
    result["resultCacheKey"] = cache_key
    result["sourceParseResultId"] = source_parse_result_id
    result.setdefault("diagnostics", []).append(
        {
            "code": "OCR_RESULT_CACHE_HIT",
            "level": "info",
            "message": "命中本地 OCR 解析结果缓存，跳过 OCR 引擎重跑。",
            "sourceParseResultId": source_parse_result_id,
        }
    )
    result.setdefault("engineRuns", []).append(
        {
            "engine": "ocr_result_cache",
            "status": "success",
            "available": True,
            "durationMs": 0,
            "resultCacheHit": True,
        }
    )
    return result


def sanitized_cached_result(result: dict[str, Any]) -> dict[str, Any]:
    cached = deepcopy(result)
    cached.pop("resultCacheHit", None)
    cached.pop("resultCacheKey", None)
    cached.pop("sourceParseResultId", None)
    return cached


def cache_relevant_options(options: dict[str, Any]) -> dict[str, Any]:
    ignored = {
        "disableEngineCache",
        "disableEngineResultCache",
        "disableResultCache",
        "disableVariantCache",
    }
    return {key: value for key, value in options.items() if key not in ignored}


def cacheable_engine_status(status: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in status.items()
        if key
        in {
            "engine",
            "version",
            "python",
            "enabled",
            "detModelDir",
            "recModelDir",
            "sealDetModelDir",
            "sealRecModelDir",
            "layoutModelDir",
            "wiredTableStructureModelDir",
            "wiredTableCellsModelDir",
            "wirelessTableStructureModelDir",
            "wirelessTableCellsModelDir",
        }
    }


def cacheable_variant(variant: dict[str, Any]) -> dict[str, Any]:
    return {
        "variantId": variant.get("variantId"),
        "imageHash": variant.get("imageHash"),
        "preprocessChain": variant.get("preprocessChain") or [],
        "purpose": variant.get("purpose"),
        "source": variant.get("source"),
    }


def engine_raw_is_cacheable(raw: dict[str, Any]) -> bool:
    if not isinstance(raw, dict) or raw.get("ok") is False:
        return False
    return any(
        raw.get(key)
        for key in [
            "fields",
            "fragments",
            "layoutBlocks",
            "pages",
            "seals",
            "signatures",
            "tables",
            "text",
        ]
    )


def stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def file_hash(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return f"sha256:{hasher.hexdigest()}"
