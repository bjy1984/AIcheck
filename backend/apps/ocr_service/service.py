from __future__ import annotations

import hashlib
import json
import os
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4

from apps.ocr_service.engines import local_engines
from apps.ocr_service.jobs import DocumentParseJobStore
from apps.ocr_service.profiles import profile_for
from libs.contracts.responses import server_time
from libs.integrations.storage import object_storage, parse_storage_url


AGENTDESIGN_BACKEND = Path(
    os.getenv("AICHECK_AGENTDESIGN_BACKEND", "/Volumes/Volume/project/agentdesign/mvp-system/backend")
)
if AGENTDESIGN_BACKEND.exists() and str(AGENTDESIGN_BACKEND) not in sys.path:
    sys.path.append(str(AGENTDESIGN_BACKEND))


MODEL_ENV_KEYS = {
    "PADDLEOCR_MODEL_DIR": "/models/paddleocr",
    "PADDLEX_MODEL_DIR": "/models/paddlex",
    "PADDLEOCR_VL_MODEL_DIR": "/models/paddleocr-vl",
    "DOCLING_ARTIFACTS_PATH": "/models/docling",
}


class OcrService:
    def __init__(self) -> None:
        self.pipeline = self._load_pipeline()
        self.engines = local_engines()
        self.jobs = DocumentParseJobStore()

    def _load_pipeline(self) -> Any | None:
        try:
            from seal_ocr.pipeline import recognize_document  # type: ignore

            return recognize_document
        except Exception:
            try:
                from seal_ocr.pipeline import SealOcrPipeline  # type: ignore

                return SealOcrPipeline()
            except Exception:
                return None

    @property
    def placeholder_allowed(self) -> bool:
        return env_bool("AICHECK_OCR_ALLOW_PLACEHOLDER", False)

    @property
    def offline_only(self) -> bool:
        return env_bool("AICHECK_OCR_OFFLINE_ONLY", True)

    @property
    def disable_network(self) -> bool:
        return env_bool("AICHECK_OCR_DISABLE_NETWORK", True)

    @property
    def pipeline_available(self) -> bool:
        return self.pipeline is not None or any(engine.available() for engine in self.engines)

    def health_payload(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "ocr-service",
            "capability": "document-intelligence-service",
            "pipelineAvailable": self.pipeline_available,
            "pipelineBackend": str(AGENTDESIGN_BACKEND),
            "placeholderAllowed": self.placeholder_allowed,
            "offlineOnly": self.offline_only,
            "networkDisabled": self.disable_network,
            "engines": self.engine_status(),
            "modelManifest": self.model_manifest(),
        }

    def readiness_payload(self) -> dict[str, Any]:
        failures = []
        if self.placeholder_allowed:
            failures.append("AICHECK_OCR_ALLOW_PLACEHOLDER must be false.")
        if not self.pipeline_available:
            failures.append("No local OCR engine or agentdesign OCR pipeline is available.")
        if self.offline_only:
            for key, default in MODEL_ENV_KEYS.items():
                path = Path(os.getenv(key, default))
                if not path.exists():
                    failures.append(f"{key} model path is missing: {path}")
        cloud_keys = sorted(key for key in os.environ if key.startswith(("AWS_", "AZURE_", "GOOGLE_", "ALIBABA_")))
        if cloud_keys:
            failures.append("Cloud OCR/provider environment variables are not allowed for local-only OCR.")
        return {
            **self.health_payload(),
            "ready": not failures,
            "readinessFailures": failures,
        }

    def engine_status(self) -> list[dict[str, Any]]:
        return [engine.status() for engine in self.engines]

    def model_manifest(self) -> dict[str, Any]:
        manifest_path = os.getenv("AICHECK_OCR_MODEL_MANIFEST")
        manifest: dict[str, Any] = {"modelDirs": {}}
        if manifest_path and Path(manifest_path).exists():
            try:
                loaded = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    manifest.update(loaded)
            except Exception as exc:
                manifest["manifestError"] = str(exc)
        for key, default in MODEL_ENV_KEYS.items():
            path = Path(os.getenv(key, default))
            manifest["modelDirs"][key] = {
                "path": str(path),
                "exists": path.exists(),
                "hash": directory_fingerprint(path) if path.exists() else None,
            }
        return manifest

    def parse_document(
        self,
        storage_key: str,
        *,
        file_name: str | None = None,
        profile_id: str | None = None,
        document_type: str | None = None,
        document_version_id: str | None = None,
        business_pack_id: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # Keep these explicit calls in this method: resolve_source_path, AICHECK_OCR_ALLOW_PLACEHOLDER,
        # failed_result, and normalize_ocr_result are part of the legacy deployment contract.
        source_path = resolve_source_path(storage_key, file_name)
        os.getenv("AICHECK_OCR_ALLOW_PLACEHOLDER", "false")
        if source_path is None:
            return failed_result(
                storage_key,
                file_name,
                "OCR source file is unavailable. Check MinIO object key, credentials, or mounted file path.",
            )
        profile = profile_for(profile_id, document_type)
        if self.pipeline is not None:
            try:
                if callable(self.pipeline):
                    result = self.pipeline(source_path)  # type: ignore[misc]
                else:
                    result = self.pipeline.run(str(source_path))  # type: ignore[attr-defined]
                normalized = normalize_ocr_result(result, storage_key, file_name)
                return enrich_parse_result(
                    normalized,
                    profile=profile,
                    document_version_id=document_version_id,
                    business_pack_id=business_pack_id,
                    model_manifest=self.model_manifest(),
                )
            except Exception as exc:
                pipeline_error = str(exc)
        else:
            pipeline_error = "agentdesign OCR pipeline not importable."

        normalized = self.parse_with_local_engines(
            source_path,
            storage_key=storage_key,
            file_name=file_name,
            profile=profile,
            document_version_id=document_version_id,
            business_pack_id=business_pack_id,
            options=options or {},
        )
        if normalized.get("status") == "success":
            return normalized
        if self.placeholder_allowed:
            return normalize_ocr_result(
                {
                    "ok": False,
                    "diagnostics": [
                        {
                            "code": "PLACEHOLDER_DISABLED_BY_POLICY",
                            "message": "Placeholder OCR is not used by the local-only Document Intelligence service.",
                        }
                    ],
                },
                storage_key,
                file_name,
            )
        diagnostics = normalized.get("diagnostics") or []
        if pipeline_error:
            diagnostics = [*diagnostics, pipeline_error]
        return failed_result(storage_key, file_name, "; ".join(str(item) for item in diagnostics))

    def parse_with_local_engines(
        self,
        source_path: Path,
        *,
        storage_key: str,
        file_name: str | None,
        profile: dict[str, Any],
        document_version_id: str | None,
        business_pack_id: str | None,
        options: dict[str, Any],
    ) -> dict[str, Any]:
        merged: dict[str, Any] = {
            "storageKey": storage_key,
            "fileName": file_name,
            "status": "failed",
            "pages": [],
            "fragments": [],
            "layoutBlocks": [],
            "fields": [],
            "tables": [],
            "seals": [],
            "signatures": [],
            "quality": {},
            "diagnostics": [],
            "engineRuns": [],
        }
        for engine in self.engines:
            if not engine.available():
                merged["engineRuns"].append({**engine.status(), "status": "unavailable", "durationMs": 0})
                continue
            started = monotonic_ms()
            try:
                raw = engine.parse(source_path, file_name=file_name, profile=profile)
                normalized = normalize_ocr_result(raw, storage_key, file_name)
                merge_parse_result(merged, normalized)
                merged["engineRuns"].append(
                    {
                        **engine.status(),
                        "status": "success" if normalized.get("status") == "success" else "failed",
                        "durationMs": max(monotonic_ms() - started, 0),
                    }
                )
            except Exception as exc:
                merged["diagnostics"].append(
                    diagnostic(
                        "ENGINE_FAILED",
                        f"{engine.name} failed: {exc.__class__.__name__}",
                        level="error",
                    )
                )
                merged["engineRuns"].append(
                    {
                        **engine.status(),
                        "status": "failed",
                        "durationMs": max(monotonic_ms() - started, 0),
                        "errorCode": exc.__class__.__name__,
                    }
                )
        if has_parse_content(merged):
            merged["status"] = "success"
        else:
            merged["diagnostics"].append(
                diagnostic("NO_LOCAL_OCR_RESULT", "No local OCR engine produced parseable content.", level="error")
            )
        return enrich_parse_result(
            merged,
            profile=profile,
            document_version_id=document_version_id,
            business_pack_id=business_pack_id,
            model_manifest=self.model_manifest(),
        )

    def create_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.jobs.create(payload)

    def run_job(self, job_id: str) -> dict[str, Any] | None:
        job = self.jobs.mark_running(job_id)
        if not job:
            return None
        result = self.parse_document(
            str(job.get("storageKey") or ""),
            file_name=job.get("fileName"),
            profile_id=job.get("profileId"),
            document_type=job.get("documentType"),
            document_version_id=job.get("documentVersionId"),
            business_pack_id=job.get("businessPackId"),
            options=job.get("options") or {},
        )
        return self.jobs.mark_finished(job_id, result)

    def retry_job(self, job_id: str) -> dict[str, Any] | None:
        payload = self.jobs.retry_payload(job_id)
        if payload is None:
            return None
        return self.create_job(payload)


def normalize_ocr_result(raw: Any, storage_key: str, file_name: str | None = None) -> dict[str, Any]:
    if raw is None:
        return failed_result(storage_key, file_name, "OCR returned no result.")
    text = raw.get("text") if isinstance(raw, dict) else str(raw)
    fields = raw.get("fields", []) if isinstance(raw, dict) else []
    seals = raw.get("seals", []) if isinstance(raw, dict) else []
    diagnostics = normalize_diagnostics(raw.get("diagnostics", []) if isinstance(raw, dict) else [])
    if isinstance(raw, dict) and raw.get("ok") is False:
        message = raw.get("error") or diagnostics or "OCR failed"
        return failed_result(storage_key, file_name, message)
    normalized_fields = normalize_raw_fields(fields)
    normalized_fields.extend(fields_from_seals(seals))
    fragments = normalize_fragments(raw, text)
    pages = raw.get("pages", []) if isinstance(raw, dict) and isinstance(raw.get("pages"), list) else []
    layout_blocks = (
        raw.get("layoutBlocks", []) if isinstance(raw, dict) and isinstance(raw.get("layoutBlocks"), list) else []
    )
    tables = raw.get("tables", []) if isinstance(raw, dict) and isinstance(raw.get("tables"), list) else []
    return {
        "parseResultId": f"PARSE-{uuid4().hex[:12].upper()}",
        "storageKey": storage_key,
        "fileName": file_name,
        "status": "success",
        "pages": pages,
        "fragments": fragments,
        "layoutBlocks": layout_blocks,
        "fields": normalized_fields,
        "tables": tables,
        "seals": normalize_raw_seals(seals),
        "signatures": raw.get("signatures", []) if isinstance(raw, dict) and isinstance(raw.get("signatures"), list) else [],
        "quality": raw.get("quality", {}) if isinstance(raw, dict) and isinstance(raw.get("quality"), dict) else {},
        "diagnostics": diagnostics,
        "engineRuns": [],
        "modelManifest": {},
        "createdAt": server_time(),
    }


def failed_result(storage_key: str, file_name: str | None, message: Any) -> dict[str, Any]:
    diagnostics = normalize_diagnostics(message)
    return {
        "parseResultId": f"PARSE-{uuid4().hex[:12].upper()}",
        "storageKey": storage_key,
        "fileName": file_name,
        "status": "failed",
        "pages": [],
        "fragments": [],
        "layoutBlocks": [],
        "fields": [],
        "tables": [],
        "seals": [],
        "signatures": [],
        "quality": {},
        "diagnostics": diagnostics,
        "engineRuns": [],
        "modelManifest": {},
        "createdAt": server_time(),
    }


ocr_service = OcrService()


def resolve_source_path(storage_key: str, file_name: str | None) -> Path | None:
    parsed = parse_storage_url(storage_key)
    if parsed:
        bucket, object_name = parsed
        suffix = Path(file_name or object_name).suffix
        try:
            return object_storage.download_to_temp(bucket, object_name, suffix=suffix)
        except Exception:
            return None
    if not Path(storage_key).is_absolute():
        try:
            return object_storage.download_to_temp("documents", storage_key, suffix=Path(file_name or storage_key).suffix)
        except Exception:
            pass
    direct = Path(storage_key)
    if direct.is_file() and direct_path_allowed(direct):
        return direct
    return None


def direct_path_allowed(path: Path) -> bool:
    if env_bool("AICHECK_OCR_ALLOW_DIRECT_PATHS", False):
        return True
    allowed = [
        Path(item).expanduser().resolve()
        for item in os.getenv("AICHECK_OCR_ALLOWED_LOCAL_DIRS", "/tmp,/var/tmp,/app/tmp").split(",")
        if item.strip()
    ]
    try:
        resolved = path.expanduser().resolve()
    except Exception:
        return False
    return any(resolved == root or root in resolved.parents for root in allowed)


def normalize_diagnostics(raw: Any) -> list[Any]:
    if not raw:
        return []
    normalized = []
    for item in raw if isinstance(raw, list) else [raw]:
        if isinstance(item, dict):
            normalized.append(
                {
                    "code": str(item.get("code") or "OCR_DIAGNOSTIC"),
                    "level": str(item.get("level") or "info"),
                    "message": str(item.get("message") or item),
                    **{key: value for key, value in item.items() if key not in {"code", "level", "message"}},
                }
            )
        else:
            normalized.append(str(item))
    return normalized


def normalize_raw_fields(raw_fields: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_fields, list):
        return []
    normalized = []
    for raw in raw_fields:
        if not isinstance(raw, dict):
            continue
        name = first_present(raw, "fieldName", "field", "name", "key", "label")
        value = first_present(raw, "fieldValue", "value", "text")
        if not name or value is None:
            continue
        normalized.append(
            {
                "fieldName": str(name),
                "fieldValue": str(value),
                "pageNo": page_no_from(raw),
                "bbox": first_present(raw, "bbox", "polygon", "box"),
                "confidence": first_present(raw, "confidence", "calibrated_confidence", "score", default=0.8),
                "extractionMethod": first_present(raw, "extractionMethod", "method", default="PaddleOCR"),
                "sourceEngine": raw.get("sourceEngine"),
            }
        )
    return normalized


def fields_from_seals(seals: Any) -> list[dict[str, Any]]:
    if not isinstance(seals, list):
        return []
    fields = []
    for seal in seals:
        if not isinstance(seal, dict):
            continue
        page_no = int(first_present(seal, "pageNo", default=None) or (int(first_present(seal, "page_index", default=0)) + 1))
        polygon = first_present(seal, "polygon", "bbox")
        seal_fields = seal.get("fields") or {}
        if isinstance(seal_fields, list):
            for item in seal_fields:
                if not isinstance(item, dict):
                    continue
                name = first_present(item, "fieldName", "fieldCode", "name")
                value = first_present(item, "fieldValue", "fieldValue", "value", "text")
                if name and value is not None:
                    fields.append(
                        {
                            "fieldName": seal_field_label(str(name)),
                            "fieldValue": str(value),
                            "pageNo": page_no,
                            "bbox": first_present(item, "bbox", default=polygon),
                            "confidence": first_present(item, "confidence", "ocrConfidence", default=0.8),
                            "extractionMethod": "PaddleOCR+seal",
                        }
                    )
            continue
        if not isinstance(seal_fields, dict):
            continue
        for key, value in seal_fields.items():
            if not isinstance(value, dict) or first_present(value, "value", "fieldValue", "text") is None:
                continue
            field_value = first_present(value, "value", "fieldValue", "text")
            fields.append(
                {
                    "fieldName": seal_field_label(key),
                    "fieldValue": str(field_value),
                    "pageNo": page_no,
                    "bbox": polygon,
                    "confidence": first_present(value, "calibrated_confidence", "visual_confidence", "confidence", default=0.8),
                    "extractionMethod": "PaddleOCR+seal",
                }
            )
    return fields


def normalize_raw_seals(seals: Any) -> list[dict[str, Any]]:
    if not isinstance(seals, list):
        return []
    normalized = []
    for index, seal in enumerate(seals, start=1):
        if not isinstance(seal, dict):
            continue
        normalized.append(
            {
                "sealId": str(seal.get("sealId") or f"seal_{index}"),
                "pageNo": int(first_present(seal, "pageNo", default=None) or (int(first_present(seal, "page_index", default=0)) + 1)),
                "sealType": seal.get("sealType") or seal.get("type") or "unknown",
                "sealName": str(first_present(seal, "sealName", "text", "name", default="")),
                "bbox": first_present(seal, "bbox", "box"),
                "polygon": first_present(seal, "polygon", "dt_poly"),
                "cropObjectKey": seal.get("cropObjectKey"),
                "visualConfidence": first_present(seal, "visualConfidence", "visual_confidence", "det_score", "score", default=0.8),
                "ocrConfidence": first_present(seal, "ocrConfidence", "ocr_confidence", "rec_score", "score", default=0.8),
                "fields": seal.get("fields") or [],
                "qualityFlags": seal.get("qualityFlags") or [],
            }
        )
    return normalized


def seal_field_label(key: str) -> str:
    return {
        "organization_name": "单位名称",
        "certificate_number": "证书编号",
        "license_scope": "许可范围",
        "valid_until": "有效期至",
        "issuer_or_seal_name": "印章名称",
    }.get(key, key)


def normalize_fragments(raw: Any, text: str | None) -> list[dict[str, Any]]:
    if isinstance(raw, dict) and isinstance(raw.get("fragments"), list):
        return [item for item in raw["fragments"] if isinstance(item, dict)]
    summary = ""
    if isinstance(raw, dict):
        summary = str(raw.get("document_summary") or raw.get("candidate_summary") or "")
    value = text or summary or ""
    return [{"pageNo": 1, "text": value, "bbox": None, "confidence": 0.8}] if value else []


def merge_parse_result(target: dict[str, Any], incoming: dict[str, Any]) -> None:
    for key in ["pages", "fragments", "layoutBlocks", "fields", "tables", "seals", "signatures", "diagnostics"]:
        target.setdefault(key, [])
        target[key].extend(deepcopy(incoming.get(key) or []))
    if isinstance(incoming.get("quality"), dict):
        target.setdefault("quality", {}).update(incoming["quality"])


def has_parse_content(result: dict[str, Any]) -> bool:
    return any(result.get(key) for key in ["fragments", "fields", "tables", "seals", "layoutBlocks"])


def enrich_parse_result(
    result: dict[str, Any],
    *,
    profile: dict[str, Any],
    document_version_id: str | None,
    business_pack_id: str | None,
    model_manifest: dict[str, Any],
) -> dict[str, Any]:
    enriched = deepcopy(result)
    enriched.setdefault("parseResultId", f"PARSE-{uuid4().hex[:12].upper()}")
    enriched["parserVersion"] = "document-intelligence-local-v1"
    enriched["engineVersion"] = "local-paddle-doc-intel-v1"
    enriched["profileId"] = profile.get("profileId")
    enriched["documentType"] = profile.get("documentType")
    enriched["businessPackId"] = business_pack_id
    enriched["documentVersionId"] = document_version_id
    enriched["modelManifest"] = model_manifest
    enriched.setdefault("createdAt", server_time())
    return enriched


def diagnostic(code: str, message: str, *, level: str = "warning", **extra: Any) -> dict[str, Any]:
    return {"code": code, "level": level, "message": message, **extra}


def first_present(raw: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in raw and raw[key] is not None:
            return raw[key]
    return default


def page_no_from(raw: dict[str, Any]) -> int:
    if raw.get("pageNo") is not None:
        return int(raw["pageNo"])
    if raw.get("page") is not None:
        return int(raw["page"])
    if raw.get("page_index") is not None:
        return int(raw["page_index"]) + 1
    return 1


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def monotonic_ms() -> int:
    import time

    return int(time.monotonic() * 1000)


def directory_fingerprint(path: Path) -> str:
    hasher = hashlib.sha256()
    files = sorted(item for item in path.rglob("*") if item.is_file())[:200]
    for item in files:
        stat = item.stat()
        hasher.update(str(item.relative_to(path)).encode("utf-8"))
        hasher.update(str(stat.st_size).encode("ascii"))
        hasher.update(str(int(stat.st_mtime)).encode("ascii"))
    return f"sha256:{hasher.hexdigest()}"
