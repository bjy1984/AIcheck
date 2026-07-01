from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4

from apps.ocr_service.engines import local_engines
from apps.ocr_service.fusion import fuse_parse_result, missing_required_tables
from apps.ocr_service.jobs import DocumentParseJobStore
from apps.ocr_service.pages import public_document_pages, render_document_pages
from apps.ocr_service.preprocess import generate_image_variants, requested_variant_names
from apps.ocr_service.profiles import profile_for
from apps.ocr_service.quality import probe_page_quality
from apps.ocr_service.result_cache import (
    build_engine_result_cache_key,
    build_result_cache_key,
    load_engine_result_cache,
    load_result_cache,
    rehydrate_cached_result,
    save_engine_result_cache,
    save_result_cache,
)
from apps.ocr_service.routing import route_engine_variants
from apps.ocr_service.runtime_doctor import build_runtime_doctor
from libs.contracts.responses import server_time
from libs.integrations.storage import object_storage, parse_storage_url


AGENTDESIGN_BACKEND = Path(
    os.getenv("AICHECK_AGENTDESIGN_BACKEND", "/Volumes/Volume/project/agentdesign/mvp-system/backend")
)
if AGENTDESIGN_BACKEND.exists() and str(AGENTDESIGN_BACKEND) not in sys.path:
    sys.path.append(str(AGENTDESIGN_BACKEND))


MODEL_ROOT_ENV_KEYS = {
    "PADDLEOCR_MODEL_DIR": "/models/paddleocr",
    "PADDLEX_MODEL_DIR": "/models/paddlex",
    "PADDLEOCR_VL_MODEL_DIR": "/models/paddleocr-vl",
    "DOCLING_ARTIFACTS_PATH": "/models/docling",
}

REQUIRED_MODEL_ENV_KEYS = {
    "AICHECK_PADDLEOCR_DET_MODEL_DIR": "/models/paddleocr/PP-OCRv6_medium_det",
    "AICHECK_PADDLEOCR_REC_MODEL_DIR": "/models/paddleocr/PP-OCRv6_medium_rec",
}

OPTIONAL_MODEL_ENV_KEYS = {
    "AICHECK_PPSTRUCTURE_LAYOUT_MODEL_DIR": "/models/paddlex/PP-DocLayout-L",
    "AICHECK_PPSTRUCTURE_WIRED_TABLE_STRUCTURE_MODEL_DIR": "/models/paddlex/SLANeXt_wired",
    "AICHECK_PPSTRUCTURE_WIRED_TABLE_CELLS_MODEL_DIR": "/models/paddlex/RT-DETR-L_wired_table_cell_det",
    "AICHECK_PPSTRUCTURE_WIRELESS_TABLE_STRUCTURE_MODEL_DIR": "/models/paddlex/SLANeXt_wireless",
    "AICHECK_PPSTRUCTURE_WIRELESS_TABLE_CELLS_MODEL_DIR": "/models/paddlex/RT-DETR-L_wireless_table_cell_det",
    "AICHECK_SEAL_DET_MODEL_DIR": "/models/paddlex/PP-OCRv4_server_seal_det",
    "AICHECK_SEAL_REC_MODEL_DIR": "/models/paddleocr/PP-OCRv4_server_rec",
}

MODEL_ENV_KEYS = {
    **MODEL_ROOT_ENV_KEYS,
    **REQUIRED_MODEL_ENV_KEYS,
    **OPTIONAL_MODEL_ENV_KEYS,
}


PIPE_CODE_RE = re.compile(r"\b(?:PL|VT)\d{3,5}\b", re.IGNORECASE)
DRAWING_NO_RE = re.compile(r"\b[A-Z]{1,4}\d{6,}[A-Z0-9.-]*\b")
DESIGN_PHASE_RE = re.compile(r"(施工图|初步设计|详细设计|竣工图)")
DN_RE = re.compile(r"\bDN\s*\d+\b", re.IGNORECASE)
PIPE_SIZE_RE = re.compile(r"[Φ①]?\s*\d{2,4}\s*[x×]\s*\d+(?:\.\d+)?", re.IGNORECASE)
PID_RE = re.compile(r"\b[A-Z]-\d+\b", re.IGNORECASE)
NUMBER_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
DATE_CN_RE = re.compile(r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日")
STANDARD_NO_RE = re.compile(r"\b(?:GB|HG|NB|JB|SH|SY|TSG)\s*/?\s*T?\s*[\d.-]+(?:-\d{4})?\b", re.IGNORECASE)

REMEDIATION_TRIGGER_REASONS = {
    "REQUIRED_FIELD_MISSING",
    "REQUIRED_TABLE_MISSING",
    "TABLE_STRUCTURE_LOW_CONFIDENCE",
    "SEAL_TEXT_LOW_CONFIDENCE",
    "SEAL_NOT_FOUND",
    "EXPECTED_SEAL_TYPE_MISSING",
}

TABLE_REMEDIATION_REASONS = {"REQUIRED_TABLE_MISSING", "TABLE_STRUCTURE_LOW_CONFIDENCE"}
TEXT_REMEDIATION_REASONS = {"REQUIRED_FIELD_MISSING"}
SEAL_REMEDIATION_REASONS = {"SEAL_TEXT_LOW_CONFIDENCE", "SEAL_NOT_FOUND", "EXPECTED_SEAL_TYPE_MISSING"}


class OcrService:
    def __init__(self) -> None:
        self.pipeline = self._load_pipeline()
        self.engines = local_engines()
        self.jobs = DocumentParseJobStore()

    def _load_pipeline(self) -> Any | None:
        if os.getenv("AICHECK_ENABLE_AGENTDESIGN_PIPELINE", "false").lower() not in {"1", "true", "yes", "on"}:
            return None
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
            for key, default in REQUIRED_MODEL_ENV_KEYS.items():
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

    def runtime_doctor_payload(self) -> dict[str, Any]:
        return build_runtime_doctor(
            engine_status=self.engine_status(),
            model_manifest=self.model_manifest(),
            offline_only=self.offline_only,
            network_disabled=self.disable_network,
            placeholder_allowed=self.placeholder_allowed,
        )

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
        for key, default in MODEL_ROOT_ENV_KEYS.items():
            self._add_model_manifest_dir(manifest, key, default, category="root", required=False)
        for key, default in REQUIRED_MODEL_ENV_KEYS.items():
            self._add_model_manifest_dir(manifest, key, default, category="required", required=True)
        for key, default in OPTIONAL_MODEL_ENV_KEYS.items():
            self._add_model_manifest_dir(manifest, key, default, category="optional", required=False)
        manifest["engineConfig"] = {
            "AICHECK_OCR_SUBPROCESS_PYTHON": os.getenv("AICHECK_OCR_SUBPROCESS_PYTHON"),
            "AICHECK_ENABLE_PADDLEX_SEAL_PIPELINE": os.getenv("AICHECK_ENABLE_PADDLEX_SEAL_PIPELINE", "auto"),
            "AICHECK_ENABLE_OPENCV_TABLE_GRID": os.getenv("AICHECK_ENABLE_OPENCV_TABLE_GRID", "true"),
            "AICHECK_OPENCV_TABLE_GRID_MAX_CELLS": os.getenv("AICHECK_OPENCV_TABLE_GRID_MAX_CELLS", "1800"),
            "AICHECK_ENABLE_AGENTDESIGN_SEAL_OCR": os.getenv("AICHECK_ENABLE_AGENTDESIGN_SEAL_OCR", "false"),
            "AICHECK_AGENTDESIGN_SEAL_MAX_CANDIDATES": os.getenv("AICHECK_AGENTDESIGN_SEAL_MAX_CANDIDATES", "6"),
            "AICHECK_AGENTDESIGN_SEAL_MAX_OCR_CANDIDATES": os.getenv(
                "AICHECK_AGENTDESIGN_SEAL_MAX_OCR_CANDIDATES", "3"
            ),
            "AICHECK_AGENTDESIGN_SEAL_PAGE_SUBJECT": os.getenv("AICHECK_AGENTDESIGN_SEAL_PAGE_SUBJECT", "false"),
            "AICHECK_AGENTDESIGN_SEAL_ENABLE_PPOCR5": os.getenv("AICHECK_AGENTDESIGN_SEAL_ENABLE_PPOCR5", "false"),
        }
        return manifest

    def _add_model_manifest_dir(
        self,
        manifest: dict[str, Any],
        key: str,
        default: str,
        *,
        category: str,
        required: bool,
    ) -> None:
        path = Path(os.getenv(key, default))
        manifest["modelDirs"][key] = {
            "path": str(path),
            "exists": path.exists(),
            "hash": directory_fingerprint(path) if path.exists() else None,
            "category": category,
            "required": required,
        }

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
        candidate_results: list[dict[str, Any]] = []
        if self.pipeline is not None:
            try:
                if callable(self.pipeline):
                    result = self.pipeline(source_path)  # type: ignore[misc]
                else:
                    result = self.pipeline.run(str(source_path))  # type: ignore[attr-defined]
                normalized = normalize_ocr_result(result, storage_key, file_name)
                if has_parse_content(normalized):
                    attach_candidate_engine_metadata(normalized, "agentdesign_pipeline")
                    candidate_results.append(normalized)
                    pipeline_error = ""
                else:
                    pipeline_error = "agentdesign OCR pipeline returned no parseable text, fields, tables, or seals."
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
            candidate_results=candidate_results,
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
        normalized["diagnostics"] = normalize_diagnostics(diagnostics)
        return normalized

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
        candidate_results: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        model_manifest = self.model_manifest()
        has_external_candidates = bool(candidate_results)
        result_cache_key = build_result_cache_key(
            source_path,
            profile=profile,
            model_manifest=model_manifest,
            options=options,
        )
        cached_result = None if has_external_candidates else load_result_cache(result_cache_key)
        if cached_result is not None and result_cache_key is not None:
            return rehydrate_cached_result(
                cached_result,
                cache_key=result_cache_key,
                storage_key=storage_key,
                file_name=file_name,
                document_version_id=document_version_id,
                business_pack_id=business_pack_id,
            )
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
        document_pages = render_document_pages(source_path, profile=profile)
        merged["pages"] = public_document_pages(document_pages)
        page_quality = probe_page_quality(source_path, profile=profile)
        requested_variants = requested_variant_names(profile, page_quality, options=options)
        variants = generate_image_variants(source_path, profile=profile, page_quality=page_quality, options=options)
        generated_variant_names = variant_names(variants)
        missing_variants = [
            name
            for name in requested_variants
            if name != "original" and name not in generated_variant_names
        ]
        merged["pageQuality"] = page_quality
        merged["imageVariants"] = public_variants(variants)
        merged["preprocessStatus"] = {
            "requestedVariants": requested_variants,
            "generatedVariants": sorted(generated_variant_names),
            "missingVariants": missing_variants,
            "dependencyHint": None,
        }
        if missing_variants:
            merged["preprocessStatus"]["dependencyHint"] = (
                "Install opencv-python-headless in the OCR runtime or set AICHECK_OCR_SUBPROCESS_PYTHON "
                "to a local Python environment with cv2/numpy."
            )
            merged["diagnostics"].append(
                diagnostic(
                    "PREPROCESS_VARIANT_GENERATION_UNAVAILABLE",
                    "部分预处理候选图未生成，OCR 会退回原图；请检查本地 OpenCV 依赖或 OCR subprocess Python 配置。",
                    level="warning",
                    missingVariants=missing_variants,
                )
            )
        for candidate in candidate_results or []:
            merge_parse_result(merged, candidate)
            merged["engineRuns"].append(
                {
                    "engine": "agentdesign_pipeline",
                    "version": candidate.get("engineVersion") or "agentdesign@local",
                    "available": True,
                    "status": "success" if candidate.get("status") == "success" else "failed",
                    "durationMs": 0,
                    "variantId": "agentdesign_pipeline",
                    "workerMode": "inprocess",
                    "qualityScore": 0.86,
                }
            )
        for engine in self.engines:
            engine_status = engine.status()
            if not engine.available():
                merged["engineRuns"].append({**engine_status, "status": "unavailable", "durationMs": 0})
                continue
            routed_variants = route_engine_variants(
                engine.name,
                variants,
                profile=profile,
                page_quality=page_quality,
                options=options,
            )
            if not routed_variants:
                merged["engineRuns"].append({**engine_status, "status": "skipped", "durationMs": 0})
                continue
            for variant in routed_variants:
                started = monotonic_ms()
                try:
                    engine_cache_key = build_engine_result_cache_key(
                        source_path,
                        engine_status=engine_status,
                        variant=variant,
                        profile=profile,
                        model_manifest=model_manifest,
                        options=options,
                    )
                    raw = load_engine_result_cache(engine_cache_key)
                    engine_cache_hit = raw is not None
                    if raw is None:
                        raw = engine.parse(source_path, file_name=file_name, profile=profile, variant=variant)
                        if isinstance(raw, dict):
                            save_engine_result_cache(engine_cache_key, raw)
                    normalized = normalize_ocr_result(raw, storage_key, file_name)
                    attach_variant_metadata(normalized, engine.name, variant)
                    merge_parse_result(merged, normalized)
                    merged["engineRuns"].append(
                        {
                            **engine_status,
                            "status": "success" if normalized.get("status") == "success" else "failed",
                            "durationMs": max(monotonic_ms() - started, 0),
                            "variantId": variant.get("variantId"),
                            "preprocessChain": variant.get("preprocessChain") or [],
                            "purpose": variant.get("purpose"),
                            "variantCacheHit": bool(variant.get("cacheHit")),
                            "engineCacheHit": engine_cache_hit,
                            "workerMode": raw.get("workerMode") if isinstance(raw, dict) else None,
                            "qualityScore": variant_quality_score(variant, page_quality),
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
                            **engine_status,
                            "status": "failed",
                            "durationMs": max(monotonic_ms() - started, 0),
                            "errorCode": exc.__class__.__name__,
                            "variantId": variant.get("variantId"),
                            "preprocessChain": variant.get("preprocessChain") or [],
                            "purpose": variant.get("purpose"),
                            "variantCacheHit": bool(variant.get("cacheHit")),
                        }
                    )
        if has_parse_content(merged):
            merged["status"] = "success"
        else:
            merged["diagnostics"].append(
                diagnostic("NO_LOCAL_OCR_RESULT", "No local OCR engine produced parseable content.", level="error")
            )
        enriched = enrich_parse_result(
            merged,
            profile=profile,
            document_version_id=document_version_id,
            business_pack_id=business_pack_id,
            model_manifest=model_manifest,
        )
        enriched = self.run_remediation_pass(
            enriched,
            source_path=source_path,
            storage_key=storage_key,
            file_name=file_name,
            profile=profile,
            variants=variants,
            page_quality=page_quality,
            model_manifest=model_manifest,
            document_version_id=document_version_id,
            business_pack_id=business_pack_id,
            options=options,
        )
        if not has_external_candidates:
            save_result_cache(result_cache_key, enriched)
        return enriched

    def run_remediation_pass(
        self,
        result: dict[str, Any],
        *,
        source_path: Path,
        storage_key: str,
        file_name: str | None,
        profile: dict[str, Any],
        variants: list[dict[str, Any]],
        page_quality: list[dict[str, Any]],
        model_manifest: dict[str, Any],
        document_version_id: str | None,
        business_pack_id: str | None,
        options: dict[str, Any],
    ) -> dict[str, Any]:
        if bool(options.get("disableRemediation")):
            return result
        reasons = {str(item) for item in ((result.get("quality") or {}).get("reasons") or [])}
        if not reasons.intersection(REMEDIATION_TRIGGER_REASONS):
            result.setdefault("remediationRuns", [])
            return result
        remediated = deepcopy(result)
        remediated["remediationRuns"] = []
        for engine in self.engines:
            if not engine_should_remediate(engine.name, reasons):
                continue
            engine_status = engine.status()
            if not engine.available():
                remediated["remediationRuns"].append({**engine_status, "status": "unavailable", "durationMs": 0})
                continue
            remediation_options = {**options, "remediationReasons": sorted(reasons), "runRemediation": True}
            routed_variants = route_engine_variants(
                engine.name,
                variants,
                profile=profile,
                page_quality=page_quality,
                options=remediation_options,
            )
            if not routed_variants:
                remediated["remediationRuns"].append({**engine_status, "status": "skipped", "durationMs": 0})
                continue
            for variant in routed_variants:
                started = monotonic_ms()
                try:
                    engine_cache_key = build_engine_result_cache_key(
                        source_path,
                        engine_status=engine_status,
                        variant=variant,
                        profile=profile,
                        model_manifest=model_manifest,
                        options=remediation_options,
                    )
                    raw = load_engine_result_cache(engine_cache_key)
                    engine_cache_hit = raw is not None
                    if raw is None:
                        raw = engine.parse(source_path, file_name=file_name, profile=profile, variant=variant)
                        if isinstance(raw, dict):
                            save_engine_result_cache(engine_cache_key, raw)
                    normalized = normalize_ocr_result(raw, storage_key, file_name)
                    attach_variant_metadata(normalized, engine.name, variant)
                    merge_parse_result(remediated, normalized)
                    remediated["remediationRuns"].append(
                        {
                            **engine_status,
                            "status": "success" if normalized.get("status") == "success" else "failed",
                            "durationMs": max(monotonic_ms() - started, 0),
                            "variantId": variant.get("variantId"),
                            "preprocessChain": variant.get("preprocessChain") or [],
                            "purpose": variant.get("purpose"),
                            "triggerReasons": sorted(reasons),
                            "engineCacheHit": engine_cache_hit,
                        }
                    )
                except Exception as exc:
                    remediated["remediationRuns"].append(
                        {
                            **engine_status,
                            "status": "failed",
                            "durationMs": max(monotonic_ms() - started, 0),
                            "errorCode": exc.__class__.__name__,
                            "variantId": variant.get("variantId"),
                            "triggerReasons": sorted(reasons),
                        }
                    )
        if any(run.get("status") == "success" for run in remediated.get("remediationRuns") or []):
            remediated = enrich_parse_result(
                remediated,
                profile=profile,
                document_version_id=document_version_id,
                business_pack_id=business_pack_id,
                model_manifest=model_manifest,
            )
        return remediated

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
    direct = Path(storage_key)
    if direct.is_file() and direct_path_allowed(direct):
        return direct
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
            downloaded = object_storage.download_to_temp("documents", storage_key, suffix=Path(file_name or storage_key).suffix)
            if downloaded:
                return downloaded
        except Exception:
            pass
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
        raw_code = first_present(raw, "fieldCode", "code", "key", "field")
        field_code = canonical_field_code(raw_code or name)
        normalized.append(
            {
                "fieldCode": field_code,
                "fieldName": str(name),
                "fieldValue": str(value),
                "pageNo": page_no_from(raw),
                "bbox": first_present(raw, "bbox", "polygon", "box"),
                "confidence": first_present(raw, "confidence", "calibrated_confidence", "score", default=0.0),
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
        if "visual_candidate_only" in (seal.get("qualityFlags") or []):
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
                            "fieldCode": canonical_field_code(name),
                            "fieldName": seal_field_label(str(name)),
                            "fieldValue": str(value),
                            "pageNo": page_no,
                            "bbox": first_present(item, "bbox", default=polygon),
                            "confidence": first_present(item, "confidence", "ocrConfidence", default=0.0),
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
                    "fieldCode": canonical_field_code(key),
                    "fieldName": seal_field_label(key),
                    "fieldValue": str(field_value),
                    "pageNo": page_no,
                    "bbox": polygon,
                    "confidence": first_present(value, "calibrated_confidence", "visual_confidence", "confidence", default=0.0),
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
                "pageWidth": seal.get("pageWidth"),
                "pageHeight": seal.get("pageHeight"),
                "visualColor": seal.get("visualColor"),
                "cropObjectKey": seal.get("cropObjectKey"),
                "visualConfidence": first_present(seal, "visualConfidence", "visual_confidence", "det_score", "score", default=0.0),
                "ocrConfidence": first_present(seal, "ocrConfidence", "ocr_confidence", "rec_score", "score", default=0.0),
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


def canonical_field_code(value: Any) -> str:
    raw = str(value or "").strip()
    normalized = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "_", raw.lower()).strip("_")
    aliases = {
        "管线号": "pipe_no",
        "管道号": "pipe_no",
        "管道代号": "pipe_no",
        "pipeline_no": "pipe_no",
        "line_no": "pipe_no",
        "pipe_no": "pipe_no",
        "图纸编号": "drawing_no",
        "图纸号": "drawing_no",
        "dwg_no": "drawing_no",
        "drawing_no": "drawing_no",
        "项目名称": "project_name",
        "project_name": "project_name",
        "证书编号": "certificate_no",
        "certificate_no": "certificate_no",
        "报告编号": "report_no",
        "report_no": "report_no",
        "单位名称": "organization_name",
        "organization_name": "organization_name",
        "印章名称": "seal_text",
        "seal_text": "seal_text",
    }
    return aliases.get(normalized, normalized or raw)


def normalize_fragments(raw: Any, text: str | None) -> list[dict[str, Any]]:
    if isinstance(raw, dict) and isinstance(raw.get("fragments"), list):
        return [item for item in raw["fragments"] if isinstance(item, dict)]
    value = text or ""
    return [{"pageNo": 1, "text": value, "bbox": None, "confidence": 0.0}] if value else []


def merge_parse_result(target: dict[str, Any], incoming: dict[str, Any]) -> None:
    for key in ["pages", "fragments", "layoutBlocks", "fields", "tables", "seals", "signatures", "diagnostics"]:
        target.setdefault(key, [])
        target[key].extend(deepcopy(incoming.get(key) or []))
    if isinstance(incoming.get("quality"), dict):
        target.setdefault("quality", {}).update(incoming["quality"])


def attach_candidate_engine_metadata(result: dict[str, Any], engine_name: str) -> None:
    for key in ["fragments", "fields", "tables", "seals", "layoutBlocks"]:
        for item in result.get(key) or []:
            if not isinstance(item, dict):
                continue
            item.setdefault("sourceEngine", engine_name)
            item.setdefault("variantId", engine_name)
            item.setdefault("selectedVariantId", item.get("variantId"))


def engine_should_remediate(engine_name: str, reasons: set[str]) -> bool:
    if engine_name == "paddleocr_vl_1_6":
        return True
    if engine_name in {"pp_structure_v3", "opencv_table_grid_subprocess"}:
        return bool(reasons.intersection(TABLE_REMEDIATION_REASONS))
    if engine_name in {"paddle_ocr_subprocess", "paddle_ocr_v6"}:
        return bool(reasons.intersection(TEXT_REMEDIATION_REASONS))
    if engine_name in {"paddlex_seal_recognition", "agentdesign_seal_ocr_subprocess"}:
        return bool(reasons.intersection(SEAL_REMEDIATION_REASONS))
    return False


def has_parse_content(result: dict[str, Any]) -> bool:
    return any(result.get(key) for key in ["fragments", "fields", "tables", "seals", "layoutBlocks"])


def public_variants(variants: list[dict[str, Any]]) -> list[dict[str, Any]]:
    public = []
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        public.append(
            {
                "variantId": variant.get("variantId"),
                "pageNo": variant.get("pageNo"),
                "preprocessChain": variant.get("preprocessChain") or [],
                "imageHash": variant.get("imageHash"),
                "purpose": variant.get("purpose"),
                "source": variant.get("source"),
                "cacheHit": bool(variant.get("cacheHit")),
                "coordinateTransformStatus": variant.get("coordinateTransformStatus"),
            }
        )
    return public


def variant_names(variants: list[dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        variant_id = str(variant.get("variantId") or "")
        match = re.match(r"page_\d+_(.+)", variant_id)
        if match:
            names.add(match.group(1))
    return names


def attach_variant_metadata(result: dict[str, Any], engine_name: str, variant: dict[str, Any]) -> None:
    variant_id = variant.get("variantId")
    chain = variant.get("preprocessChain") or []
    page_no = int(variant.get("pageNo") or 1)
    for key in ["fragments", "fields", "tables", "seals", "layoutBlocks"]:
        for item in result.get(key) or []:
            if not isinstance(item, dict):
                continue
            item.setdefault("sourceEngine", engine_name)
            item["variantId"] = variant_id
            item["selectedVariantId"] = variant_id
            item["preprocessChain"] = chain
            item["pageNo"] = page_no
            if variant.get("coordinateTransformStatus") and variant.get("coordinateTransformStatus") != "identity":
                flags = {str(flag) for flag in item.get("qualityFlags") or []}
                flags.add("coordinate_transform_unmapped")
                item["qualityFlags"] = sorted(flags)
                item["coordinateTransformStatus"] = variant.get("coordinateTransformStatus")


def variant_quality_score(variant: dict[str, Any], page_quality: list[dict[str, Any]]) -> float:
    page_no = int(variant.get("pageNo") or 1)
    quality = next(
        (
            item.get("quality") or {}
            for item in page_quality
            if isinstance(item, dict) and int(item.get("pageNo") or 1) == page_no
        ),
        (page_quality[0].get("quality") if page_quality else {}) or {},
    )
    base = 0.75
    if variant.get("source") == "original":
        base += 0.05
    if variant.get("purpose") == "table" and quality.get("hasTableCandidate"):
        base += 0.08
    if variant.get("purpose") == "seal" and quality.get("hasSealCandidate"):
        base += 0.08
    if variant.get("purpose") == "text" and quality.get("isLowQuality"):
        base += 0.05
    return round(min(base, 0.99), 4)


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
    enriched["profilePostprocessVersion"] = profile.get("postprocessVersion") or "v1"
    enriched["engineVersion"] = "local-paddle-doc-intel-v1"
    enriched["profileId"] = profile.get("profileId")
    enriched["documentType"] = profile.get("documentType")
    enriched["businessPackId"] = business_pack_id
    enriched["documentVersionId"] = document_version_id
    enriched["modelManifest"] = model_manifest
    enriched.setdefault("createdAt", server_time())
    apply_profile_postprocessing(enriched, profile)
    return fuse_parse_result(enriched, profile=profile)


def apply_profile_postprocessing(result: dict[str, Any], profile: dict[str, Any]) -> None:
    if is_piping_characteristic_profile(result, profile):
        inferred_tables = infer_piping_tables(result.get("fragments") or [])
        grid_table = best_opencv_grid_table(result.get("tables") or [])
        if inferred_tables and grid_table:
            aligned_table = align_piping_text_table_with_grid(inferred_tables[0], grid_table)
            result.setdefault("tables", []).append(aligned_table)
            result.setdefault("diagnostics", []).append(
                diagnostic(
                    "OPENCV_GRID_TABLE_ALIGNED",
                    "已用本地 OpenCV 表格网格结构对齐 OCR 文本行，作为 PP-StructureV3 缺失时的本地结构化表格结果。",
                    level="info",
                    tableId=aligned_table["tableId"],
                )
            )
        elif inferred_tables and not result.get("tables"):
            result["tables"] = inferred_tables
            result.setdefault("diagnostics", []).append(
                diagnostic(
                    "HEURISTIC_TABLE_INFERRED",
                    "基于 OCR 文本坐标重建管道特性表；建议后续用 PP-StructureV3 表格模型复核。",
                    level="info",
                    tableIds=[table["tableId"] for table in inferred_tables],
                )
            )
        normalize_piping_tables(result)
        extract_piping_fields(result)
        add_profile_quality_diagnostics(result, profile)
        return
    if is_quality_certificate_profile(result, profile):
        tag_quality_certificate_tables(result)
        extract_quality_certificate_fields(result)
        add_profile_quality_diagnostics(result, profile)
        return
    if is_welding_record_profile(result, profile):
        tag_welding_record_tables(result)
        extract_welding_record_fields(result)
        add_profile_quality_diagnostics(result, profile)
        return


def best_opencv_grid_table(tables: list[Any]) -> dict[str, Any] | None:
    candidates = [
        table
        for table in tables
        if isinstance(table, dict) and str(table.get("sourceEngine") or "") == "opencv_table_grid_subprocess"
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda table: (int(table.get("gridCellCount") or 0), float(table.get("structureConfidence") or 0.0)))


def align_piping_text_table_with_grid(text_table: dict[str, Any], grid_table: dict[str, Any]) -> dict[str, Any]:
    aligned = deepcopy(text_table)
    aligned["tableId"] = "piping_characteristic_table_1"
    aligned["sourceEngine"] = "opencv_grid_text_aligned"
    aligned["bbox"] = grid_table.get("bbox") or aligned.get("bbox")
    aligned["rows"] = max(int(aligned.get("rows") or 0), int(grid_table.get("rows") or 0))
    aligned["columns"] = max(int(aligned.get("columns") or 0), int(grid_table.get("columns") or 0))
    aligned["structureConfidence"] = round(piping_alignment_confidence(aligned, grid_table), 4)
    flags = {str(flag) for flag in aligned.get("qualityFlags") or []}
    flags.discard("heuristic_table_fallback")
    flags.update({"opencv_grid_structure", "ocr_text_aligned"})
    aligned["qualityFlags"] = sorted(flags)
    aligned["gridEvidence"] = {
        "tableId": grid_table.get("tableId"),
        "rows": grid_table.get("rows"),
        "columns": grid_table.get("columns"),
        "gridCellCount": grid_table.get("gridCellCount"),
        "gridLineXs": grid_table.get("gridLineXs"),
        "gridLineYs": grid_table.get("gridLineYs"),
        "structureConfidence": grid_table.get("structureConfidence"),
    }
    return aligned


def piping_alignment_confidence(aligned: dict[str, Any], grid_table: dict[str, Any]) -> float:
    base = max(float(aligned.get("structureConfidence") or 0.0), float(grid_table.get("structureConfidence") or 0.0))
    rows = max(int(aligned.get("rows") or 0), 1)
    columns = max(int(aligned.get("columns") or 0), 1)
    normalized_rows = [row for row in aligned.get("normalizedRows") or [] if isinstance(row, dict)]
    fill_values = [value for row in normalized_rows for value in row.values()]
    fill_rate = len([value for value in fill_values if str(value or "").strip()]) / max(len(fill_values), 1)
    header_codes = {piping_header_code(str(key)) for row in normalized_rows[:2] for key in row.keys() if isinstance(row, dict)}
    header_codes.discard(None)
    header_score = min(len(header_codes) / 8.0, 1.0)
    grid_score = min((rows * columns) / 160.0, 1.0)
    return min(max(base * 0.45 + fill_rate * 0.2 + header_score * 0.25 + grid_score * 0.1, 0.35), 0.96)


def is_piping_characteristic_profile(result: dict[str, Any], profile: dict[str, Any]) -> bool:
    profile_id = str(profile.get("profileId") or result.get("profileId") or "")
    document_type = str(profile.get("documentType") or result.get("documentType") or "")
    if profile_id == "piping_characteristic_list_v1" or document_type == "engineering_table_photo":
        return True
    all_text = "\n".join(
        str(item.get("text") or "") for item in result.get("fragments") or [] if isinstance(item, dict)
    )
    return "管道特性表" in all_text or "PIPING CHARACTERISTIC LIST" in all_text.upper()


def infer_piping_tables(fragments: list[Any]) -> list[dict[str, Any]]:
    candidates = []
    for fragment in fragments:
        if not isinstance(fragment, dict):
            continue
        text = str(fragment.get("text") or "").strip()
        bbox = rect_from_bbox(fragment.get("bbox"))
        if not text or bbox is None:
            continue
        candidates.append(
            {
                "text": text,
                "bbox": bbox,
                "pageNo": page_no_from(fragment),
                "confidence": float(first_present(fragment, "confidence", default=0.0) or 0.0),
                "sourceEngine": fragment.get("sourceEngine"),
            }
        )
    if len(candidates) < 12:
        return []
    tables = []
    for page_no in sorted({int(item["pageNo"]) for item in candidates}):
        page_items = [item for item in candidates if int(item["pageNo"]) == page_no]
        page_tables = infer_piping_tables_for_page(page_items, page_no)
        tables.extend(page_tables)
    return tables


def infer_piping_tables_for_page(items: list[dict[str, Any]], page_no: int) -> list[dict[str, Any]]:
    heights = [max(1.0, item["bbox"][3] - item["bbox"][1]) for item in items]
    tolerance = max(18.0, sorted(heights)[len(heights) // 2] * 0.85) if heights else 22.0
    rows: list[list[dict[str, Any]]] = []
    for item in sorted(items, key=lambda value: ((value["bbox"][1] + value["bbox"][3]) / 2, value["bbox"][0])):
        center_y = (item["bbox"][1] + item["bbox"][3]) / 2
        matched = False
        for row in rows:
            row_center = sum((cell["bbox"][1] + cell["bbox"][3]) / 2 for cell in row) / len(row)
            if abs(center_y - row_center) <= tolerance:
                row.append(item)
                matched = True
                break
        if not matched:
            rows.append([item])

    table_rows: list[list[dict[str, Any]]] = []
    for row in rows:
        ordered = sorted(row, key=lambda value: value["bbox"][0])
        span = max(cell["bbox"][2] for cell in ordered) - min(cell["bbox"][0] for cell in ordered)
        row_text = " ".join(cell["text"] for cell in ordered)
        if len(ordered) >= 4 and span >= 400:
            table_rows.append(ordered)
        elif table_rows and (PIPE_CODE_RE.search(row_text) or len(ordered) >= 3):
            table_rows.append(ordered)

    data_rows = [row for row in table_rows if any(PIPE_CODE_RE.search(cell["text"]) for cell in row)]
    if len(data_rows) < 2:
        return []
    x0 = min(cell["bbox"][0] for row in table_rows for cell in row)
    y0 = min(cell["bbox"][1] for row in table_rows for cell in row)
    x1 = max(cell["bbox"][2] for row in table_rows for cell in row)
    y1 = max(cell["bbox"][3] for row in table_rows for cell in row)
    cells = []
    normalized_rows = []
    current_pipe_no: str | None = None
    for row_index, row in enumerate(table_rows):
        for col_index, cell in enumerate(row):
            cells.append(
                {
                    "cellId": f"cell_{row_index + 1}_{col_index + 1}",
                    "row": row_index,
                    "col": col_index,
                    "rowspan": 1,
                    "colspan": 1,
                    "text": cell["text"],
                    "bbox": cell["bbox"],
                    "confidence": cell["confidence"],
                    "isHeader": row_index == 0,
                }
            )
        pipe_cell = next((cell for cell in row if PIPE_CODE_RE.search(cell["text"])), None)
        pipe_match = PIPE_CODE_RE.search(pipe_cell["text"]) if pipe_cell else None
        if pipe_cell and pipe_match:
            current_pipe_no = pipe_match.group(0).upper()
            normalized_rows.append(
                {
                    "pipeNo": current_pipe_no,
                    "rawCells": [cell["text"] for cell in row],
                    "sourceRowIndex": row_index,
                }
            )
        elif current_pipe_no and row_looks_like_piping_continuation(row):
            normalized_rows.append(
                {
                    "pipeNo": current_pipe_no,
                    "rawCells": [cell["text"] for cell in row],
                    "sourceRowIndex": row_index,
                    "isContinuation": True,
                }
            )
    structure_confidence = min(0.9, 0.58 + min(len(data_rows), 10) * 0.025)
    return [
        {
            "tableId": "piping_characteristic_table_1",
            "pageNo": page_no,
            "bbox": [x0, y0, x1, y1],
            "rows": len(table_rows),
            "columns": max(len(row) for row in table_rows),
            "structureConfidence": round(structure_confidence, 4),
            "cells": cells,
            "normalizedRows": normalized_rows,
            "sourceEngine": "heuristic_table_from_ocr_fragments",
            "qualityFlags": ["heuristic_table_fallback"],
        }
    ]


def normalize_piping_tables(result: dict[str, Any]) -> None:
    for table in result.get("tables") or []:
        if not isinstance(table, dict):
            continue
        business_rows = piping_business_rows_from_table(table)
        if not business_rows:
            continue
        table["businessRows"] = business_rows
        normalized_rows = [row for row in table.get("normalizedRows") or [] if isinstance(row, dict)]
        if normalized_rows:
            for index, row in enumerate(normalized_rows):
                if index < len(business_rows):
                    row.update({key: value for key, value in business_rows[index].items() if value})
        else:
            table["normalizedRows"] = business_rows
        table.setdefault("businessSchema", "piping_characteristic_table_v1")


def piping_business_rows_from_table(table: dict[str, Any]) -> list[dict[str, str]]:
    normalized_rows = [row for row in table.get("normalizedRows") or [] if isinstance(row, dict)]
    if normalized_rows:
        mapped = [map_piping_row(row) for row in normalized_rows]
        return [row for row in mapped if row.get("pipeNo")]
    cells = [cell for cell in table.get("cells") or [] if isinstance(cell, dict)]
    if not cells:
        return []
    header_by_col = {
        int(cell.get("col") or 0): str(cell.get("text") or "")
        for cell in cells
        if cell.get("isHeader") and str(cell.get("text") or "").strip()
    }
    if not header_by_col:
        header_row_no = min(int(cell.get("row") or 0) for cell in cells)
        header_by_col = {
            int(cell.get("col") or 0): str(cell.get("text") or "")
            for cell in cells
            if int(cell.get("row") or 0) == header_row_no and str(cell.get("text") or "").strip()
        }
    data_rows = []
    header_rows = {int(cell.get("row") or 0) for cell in cells if cell.get("isHeader")}
    for row_no in sorted({int(cell.get("row") or 0) for cell in cells if int(cell.get("row") or 0) not in header_rows}):
        raw = {
            header_by_col.get(int(cell.get("col") or 0), f"col_{int(cell.get('col') or 0) + 1}"): str(cell.get("text") or "")
            for cell in cells
            if int(cell.get("row") or 0) == row_no and str(cell.get("text") or "").strip()
        }
        mapped = map_piping_row(raw)
        if mapped.get("pipeNo"):
            data_rows.append(mapped)
    return data_rows


def map_piping_row(row: dict[str, Any]) -> dict[str, str]:
    output: dict[str, str] = {}
    raw_cells = row.get("rawCells")
    if isinstance(raw_cells, list):
        output.update(infer_piping_row_from_raw_cells(raw_cells))
    if row.get("isContinuation"):
        inherited_pipe_no = str(row.get("pipeNo") or output.get("pipeNo") or "").upper()
        if inherited_pipe_no:
            output["pipeNo"] = inherited_pipe_no
            output["isContinuation"] = "true"
        if row.get("sourceRowIndex") is not None:
            output["sourceRowIndex"] = str(row.get("sourceRowIndex"))
    for key, value in row.items():
        canonical = piping_header_code(str(key))
        text = str(value or "").strip()
        if not canonical or not text:
            continue
        if canonical == "pipeNo":
            match = PIPE_CODE_RE.search(text)
            output[canonical] = match.group(0).upper() if match else text.upper()
            continue
        output[canonical] = text
    return output


def infer_piping_row_from_raw_cells(raw_cells: list[Any]) -> dict[str, str]:
    cells = [clean_piping_cell_text(item) for item in raw_cells]
    cells = [item for item in cells if item]
    pipe_index = next((index for index, text in enumerate(cells) if PIPE_CODE_RE.search(text)), None)
    output: dict[str, str] = {}
    if pipe_index is not None:
        output["pipeNo"] = PIPE_CODE_RE.search(cells[pipe_index]).group(0).upper()  # type: ignore[union-attr]
        tail = cells[pipe_index + 1 :]
    else:
        tail = cells[1:] if cells and NUMBER_RE.fullmatch(cells[0]) else cells
    assign_first_match(output, "nominalDiameter", tail[:8], DN_RE)
    assign_first_match(output, "outerDiameterThickness", tail[:10], PIPE_SIZE_RE)
    pipe_class = first_token(tail[:8], lambda text: text.upper() in {"MIB", "M1B", "MIIB", "M2B"})
    if pipe_class:
        output["pipeClass"] = normalize_pipe_class(pipe_class)
    pressure_level = first_token(tail[:10], lambda text: re.fullmatch(r"GC\d+", text.upper()) is not None)
    if pressure_level:
        output["pressureLevel"] = pressure_level.upper()

    pid_index = next((index for index, text in enumerate(cells) if PID_RE.search(text)), None)
    if pid_index is not None:
        output["pAndId"] = PID_RE.search(cells[pid_index]).group(0).upper()  # type: ignore[union-attr]

    medium_start = first_index_after(cells, pipe_index or 0, lambda text: "化工品" in text or "物料" in text)
    if medium_start is not None:
        medium_parts = [cells[medium_start]]
        if medium_start + 1 < len(cells) and re.search(r"[（(].+|丙醇|液化|油|气|水", cells[medium_start + 1]):
            medium_parts.append(cells[medium_start + 1])
        output["mediumName"] = "".join(medium_parts).replace("( ", "(")

    content_end = pid_index if pid_index is not None else len(cells)
    before_pid = cells[(pipe_index + 1) if pipe_index is not None else 0 : content_end]
    state = first_token(before_pid, lambda text: text in {"液体", "气相", "气体", "水", "空气"})
    if state:
        output["mediumState"] = state
    prop_index = next((index for index, text in enumerate(cells[:content_end]) if "易燃" in text or "易爆" in text), None)
    if prop_index is not None:
        output["mediumProperty"] = cells[prop_index]
    start_end = infer_start_end(cells, pipe_index=pipe_index or 0, pid_index=pid_index, prop_index=prop_index)
    output.update(start_end)

    if pid_index is not None:
        operation = infer_temperature_pressure(cells[pid_index + 1 :])
        output.update(operation)
        tests = infer_test_and_weld_columns(cells[pid_index + 1 :])
        output.update(tests)
    return {key: value for key, value in output.items() if value}


def row_looks_like_piping_continuation(row: list[dict[str, Any]]) -> bool:
    texts = [clean_piping_cell_text(cell.get("text")) for cell in row]
    texts = [text for text in texts if text]
    if any(PIPE_CODE_RE.search(text) for text in texts):
        return False
    if not any(DN_RE.search(text) for text in texts):
        return False
    if row_looks_like_header_tokens(texts):
        return False
    signal_count = sum(
        1
        for text in texts
        if PIPE_SIZE_RE.search(text)
        or PID_RE.search(text)
        or text in {"液体", "气相", "气体", "水", "空气", "常温"}
        or text.upper() in {"RT", "UT", "MT", "PT"}
        or "易燃" in text
        or "化工品" in text
    )
    return signal_count >= 3


def row_looks_like_header_tokens(texts: list[str]) -> bool:
    header_tokens = {
        "name",
        "名称",
        "state",
        "状态",
        "property",
        "特性",
        "start",
        "end",
        "p&id",
        "no.",
        "t.(c)",
        "p.(mpag)",
        "检测方法",
        "检测数量",
        "合格等级",
        "技术等级",
    }
    normalized = {text.lower() for text in texts}
    return len(normalized & header_tokens) >= 5


def clean_piping_cell_text(value: Any) -> str:
    text = str(value or "").strip()
    text = text.replace("①", "Φ").replace("φ", "Φ").replace("×", "x")
    return re.sub(r"\s+", "", text)


def assign_first_match(output: dict[str, str], key: str, cells: list[str], pattern: re.Pattern[str]) -> None:
    match = first_token(cells, lambda text: pattern.search(text) is not None)
    if match:
        value = pattern.search(match).group(0).replace(" ", "")  # type: ignore[union-attr]
        output[key] = normalize_pipe_size(value) if key == "outerDiameterThickness" else value


def normalize_pipe_size(value: str) -> str:
    text = str(value or "").replace("×", "x").replace("①", "Φ").strip()
    match = re.fullmatch(r"([01])(\d{2,3}x\d+(?:\.\d+)?)", text, flags=re.IGNORECASE)
    if match:
        return f"Φ{match.group(2)}"
    if re.fullmatch(r"\d{2,3}x\d+(?:\.\d+)?", text, flags=re.IGNORECASE):
        return f"Φ{text}"
    return text


def first_token(cells: list[str], predicate) -> str | None:
    return next((text for text in cells if predicate(text)), None)


def first_index_after(cells: list[str], start: int, predicate) -> int | None:
    return next((index for index in range(start + 1, len(cells)) if predicate(cells[index])), None)


def normalize_pipe_class(value: str) -> str:
    return value.upper().replace("1", "I").replace("2", "II")


def infer_start_end(
    cells: list[str],
    *,
    pipe_index: int,
    pid_index: int | None,
    prop_index: int | None,
) -> dict[str, str]:
    if pid_index is None:
        return {}
    start_index = (prop_index + 1) if prop_index is not None else pipe_index + 1
    candidates = [
        text
        for text in cells[start_index:pid_index]
        if not DN_RE.search(text)
        and not PIPE_SIZE_RE.search(text)
        and text.upper() not in {"MIB", "M1B", "MIIB", "M2B"}
        and not re.fullmatch(r"GC\d+", text.upper())
        and text not in {"液体", "气相", "气体", "水", "空气", "化工品", "(丙醇", "丙醇"}
        and "易燃" not in text
        and "易爆" not in text
    ]
    candidates = [text for text in candidates if not NUMBER_RE.fullmatch(text)]
    if not candidates:
        return {}
    if len(candidates) == 1:
        return {"startPoint": candidates[0]}
    return {"startPoint": " ".join(candidates[:-1]), "endPoint": candidates[-1]}


def infer_temperature_pressure(cells: list[str]) -> dict[str, str]:
    values = collapse_consecutive_duplicates([
        text
        for text in cells
        if text in {"常温", "室温"} or NUMBER_RE.fullmatch(text)
    ])
    if len(values) < 4:
        return {}
    return {
        "operatingTemperature": values[0],
        "operatingPressure": values[1],
        "designTemperature": values[2],
        "designPressure": values[3],
    }


def collapse_consecutive_duplicates(values: list[str]) -> list[str]:
    collapsed: list[str] = []
    for value in values:
        if collapsed and collapsed[-1] == value:
            continue
        collapsed.append(value)
    return collapsed


def infer_test_and_weld_columns(cells: list[str]) -> dict[str, str]:
    output: dict[str, str] = {}
    method_index = next((index for index, text in enumerate(cells) if text.upper() in {"RT", "UT", "MT", "PT"}), None)
    if method_index is None:
        return output
    output["weldDetectionMethod"] = cells[method_index].upper()
    scale = first_token(cells[method_index + 1 : method_index + 5], lambda text: text.endswith("%"))
    if scale:
        output["weldDetectionScale"] = scale
    eligible = first_token(cells[method_index + 1 : method_index + 8], lambda text: text.upper() in {"I", "II", "III", "IV"})
    if eligible:
        output["eligibleLevel"] = eligible.upper()
    ranking = first_token(cells[method_index + 1 : method_index + 10], lambda text: text.upper() in {"A", "B", "C", "AB"})
    if ranking:
        output["ranking"] = ranking.upper()

    before_method = cells[:method_index]
    media = [(index, text) for index, text in enumerate(before_method) if text in {"水", "空气"}]
    for media_index, (index, medium) in enumerate(media[-2:]):
        pressure = first_token(before_method[index + 1 : index + 4], lambda text: NUMBER_RE.fullmatch(text) is not None)
        if media_index == 0:
            output["strengthTestMedium"] = medium
            if pressure:
                output["strengthTestPressure"] = pressure
        else:
            output["tightnessTestMedium"] = medium
            if pressure:
                output["tightnessTestPressure"] = pressure
    return output


def piping_header_code(header: str) -> str | None:
    compact = "".join(str(header or "").lower().replace("_", "").split()).strip("：:")
    if not compact:
        return None
    aliases = [
        ("pipeNo", ["管道代号", "管线号", "管道编号", "pipeno", "pipelineno", "lineno"]),
        ("nominalDiameter", ["公称直径", "公称管径", "dn", "nps", "diameter"]),
        ("pipeClass", ["管道等级", "class", "pipeclass"]),
        ("pressureLevel", ["压力管道级别", "压力等级", "级别", "pressurelevel"]),
        ("outerDiameterThickness", ["外径×壁厚", "外径壁厚", "外径", "壁厚", "odthk", "size"]),
        ("mediumName", ["介质名称", "名称name", "mediumname", "name"]),
        ("mediumState", ["状态state", "state"]),
        ("mediumProperty", ["特性property", "property"]),
        ("startPoint", ["起点", "start"]),
        ("endPoint", ["终点", "end"]),
        ("pAndId", ["流程图号", "pid", "p&id", "pandid"]),
        ("operatingTemperature", ["操作温度", "operationdatatc", "operationtemperature"]),
        ("operatingPressure", ["操作压力", "operationdatapmpag", "operationpressure"]),
        ("designTemperature", ["设计温度", "designdatatc", "designtemperature"]),
        ("designPressure", ["设计压力", "designdatapmpag", "designpressure"]),
        ("insulationCode", ["隔热参数代号", "code"]),
        ("material", ["主要材料", "material"]),
        ("insulationThickness", ["厚度", "thickness"]),
        ("strengthTestMedium", ["强度试验介质", "强度试验", "strengthtestmedium"]),
        ("strengthTestPressure", ["强度试验压力", "strengthtestpressure"]),
        ("tightnessTestMedium", ["严密性试验介质", "tightnesstestmedium"]),
        ("tightnessTestPressure", ["严密性试验压力", "tightnesstestpressure"]),
        ("weldDetectionMethod", ["焊缝检测检测方法", "检测方法", "d.method", "method"]),
        ("weldDetectionScale", ["检测数量", "检测比例", "d.scale", "scale"]),
        ("eligibleLevel", ["合格等级", "eligiblel", "eligiblelevel"]),
        ("ranking", ["技术等级", "ranking"]),
    ]
    for canonical, candidates in aliases:
        if any(candidate in compact for candidate in candidates):
            return canonical
    return None


def extract_piping_fields(result: dict[str, Any]) -> None:
    fragments = [item for item in result.get("fragments") or [] if isinstance(item, dict)]
    text_items = [(str(item.get("text") or "").strip(), item) for item in fragments if str(item.get("text") or "").strip()]
    joined = "\n".join(text for text, _ in text_items)
    add_field_if_missing(
        result,
        "document_title",
        "文件标题",
        find_text_fragment(text_items, ["管道特性表", "PIPING CHARACTERISTIC LIST"]),
    )
    add_field_if_missing(result, "company_name", "公司名称", find_text_fragment(text_items, ["广东星燃石化设计院有限公司"]))
    project_fragment = find_project_fragment(text_items)
    add_field_if_missing(result, "project_name", "项目名称", project_fragment)
    drawing_match = DRAWING_NO_RE.search(joined)
    if drawing_match:
        add_field_if_missing(result, "drawing_no", "图纸编号", match_to_fragment(text_items, drawing_match.group(0)))
    phase_match = DESIGN_PHASE_RE.search(joined)
    if phase_match:
        add_field_if_missing(result, "design_phase", "设计阶段", match_to_fragment(text_items, phase_match.group(0)))
    pipe_values = []
    pipe_bbox = None
    for text, fragment in text_items:
        for match in PIPE_CODE_RE.finditer(text):
            value = match.group(0).upper()
            if value not in pipe_values:
                pipe_values.append(value)
                pipe_bbox = pipe_bbox or rect_from_bbox(fragment.get("bbox"))
    for table in result.get("tables") or []:
        if not isinstance(table, dict):
            continue
        for row in table.get("businessRows") or []:
            if not isinstance(row, dict):
                continue
            value = str(row.get("pipeNo") or "").upper()
            if value and value not in pipe_values:
                pipe_values.append(value)
    if pipe_values:
        add_field_if_missing(
            result,
            "pipe_no",
            "管道代号",
            {
                "text": ",".join(pipe_values[:20]),
                "fragment": {
                    "bbox": pipe_bbox,
                    "pageNo": 1,
                    "confidence": 0.74 if pipe_bbox else 0.52,
                    "sourceEngine": "profile_regex",
                },
            },
        )


def is_quality_certificate_profile(result: dict[str, Any], profile: dict[str, Any]) -> bool:
    return str(profile.get("profileId") or result.get("profileId") or "") == "quality_certificate_v1"


def is_welding_record_profile(result: dict[str, Any], profile: dict[str, Any]) -> bool:
    return str(profile.get("profileId") or result.get("profileId") or "") == "welding_record_v1"


def quality_certificate_evidence_text(text_items: list[tuple[str, dict[str, Any]]]) -> str:
    joined = "\n".join(text for text, _ in text_items)
    if "质量证明" in joined or "合格证" in joined or "质检专用章" in joined:
        return joined
    if "化学成分" in joined and "材质" in joined and ("执行标准" in joined or "检验合格" in joined):
        return joined
    return ""


def extract_quality_certificate_fields(result: dict[str, Any]) -> None:
    fragments = [item for item in result.get("fragments") or [] if isinstance(item, dict)]
    text_items = [(str(item.get("text") or "").strip(), item) for item in fragments if str(item.get("text") or "").strip()]
    joined = quality_certificate_evidence_text(text_items)
    if not joined:
        return
    add_field_if_missing(result, "manufacturer", "生产厂家", quality_certificate_manufacturer(text_items))
    add_field_if_missing(
        result,
        "material_grade",
        "材料牌号",
        next_value_after_label(text_items, ["材质", "材料牌号", "牌号"], max_steps=4),
    )
    add_field_if_missing(result, "specification", "规格型号", quality_certificate_specification(text_items))
    add_field_if_missing(result, "standard_no", "标准号", regex_field_candidate(text_items, STANDARD_NO_RE))
    add_field_if_missing(result, "inspection_conclusion", "检验结论", quality_certificate_conclusion(text_items))
    add_field_if_missing(result, "issue_date", "出厂日期", regex_field_candidate(text_items, DATE_CN_RE))
    add_field_if_missing(
        result,
        "batch_no",
        "炉批号",
        next_value_after_label(text_items, ["炉批号", "批号", "批次号"], max_steps=4),
    )
    add_field_if_missing(
        result,
        "certificate_no",
        "质量证明书编号",
        next_value_after_label(text_items, ["证书编号", "证明书编号", "编号"], max_steps=4),
    )


def tag_quality_certificate_tables(result: dict[str, Any]) -> None:
    tables = [table for table in result.get("tables") or [] if isinstance(table, dict)]
    for table in tables:
        text = table_text(table)
        schemas = set(str(item) for item in table.get("businessSchemas") or [] if item)
        if quality_table_has_chemical_composition(text):
            schemas.add("material_chemical_composition_table")
        if quality_table_has_mechanical_property(text):
            schemas.add("mechanical_property_table")
        if schemas:
            table["businessSchemas"] = sorted(schemas)
            if not table.get("businessSchema"):
                table["businessSchema"] = sorted(schemas)[0]
            flags = {str(flag) for flag in table.get("qualityFlags") or []}
            flags.add("quality_certificate_schema_match")
            table["qualityFlags"] = sorted(flags)


def quality_table_has_chemical_composition(text: str) -> bool:
    compact = text.lower().replace(" ", "")
    return "化学成分" in compact or sum(token in compact for token in ["碳c", "锰mn", "硅si", "硫s", "磷p"]) >= 3


def quality_table_has_mechanical_property(text: str) -> bool:
    compact = text.lower().replace(" ", "")
    return any(token in compact for token in ["屈服点", "抗拉强度", "延伸率", "力学性能", "硬度"])


def extract_welding_record_fields(result: dict[str, Any]) -> None:
    fragments = [item for item in result.get("fragments") or [] if isinstance(item, dict)]
    text_items = [(str(item.get("text") or "").strip(), item) for item in fragments if str(item.get("text") or "").strip()]
    joined = "\n".join(text for text, _ in text_items)
    if not welding_record_evidence_text(joined):
        return
    add_field_if_missing(
        result,
        "record_no",
        "记录编号",
        next_value_after_label(text_items, ["编号", "记录编号", "报告编号"], max_steps=3),
    )
    add_field_if_missing(result, "welding_date", "焊接日期", regex_field_candidate(text_items, DATE_CN_RE))
    add_field_if_missing(
        result,
        "weld_no",
        "焊口编号",
        next_value_after_label(text_items, ["焊口编号", "焊缝编号", "焊口号"], max_steps=4),
    )
    add_field_if_missing(
        result,
        "welder_name",
        "焊工姓名",
        next_value_after_label(text_items, ["焊工", "焊工姓名", "施焊人"], max_steps=4),
    )
    add_field_if_missing(
        result,
        "welder_cert_no",
        "焊工资格证号",
        next_value_after_label(text_items, ["焊工证号", "资格证号", "证书编号"], max_steps=4),
    )


def welding_record_evidence_text(joined: str) -> str:
    if any(token in joined for token in ["焊接工艺评定", "焊接记录", "焊口编号", "焊工"]):
        return joined
    return ""


def tag_welding_record_tables(result: dict[str, Any]) -> None:
    tables = [table for table in result.get("tables") or [] if isinstance(table, dict)]
    for table in tables:
        text = table_text(table)
        compact = text.replace(" ", "")
        if not any(token in compact for token in ["焊口编号", "焊工", "焊接日期", "焊缝编号", "工艺评定"]):
            continue
        schemas = set(str(item) for item in table.get("businessSchemas") or [] if item)
        schemas.add("welding_record_table")
        table["businessSchemas"] = sorted(schemas)
        if not table.get("businessSchema"):
            table["businessSchema"] = "welding_record_table"
        flags = {str(flag) for flag in table.get("qualityFlags") or []}
        flags.add("welding_record_schema_match")
        table["qualityFlags"] = sorted(flags)


def table_text(table: dict[str, Any]) -> str:
    values: list[str] = []
    for cell in table.get("cells") or []:
        if isinstance(cell, dict) and str(cell.get("text") or "").strip():
            values.append(str(cell.get("text") or ""))
    for row in table.get("normalizedRows") or []:
        if isinstance(row, dict):
            values.extend(str(key) for key in row.keys())
            values.extend(str(value) for value in row.values())
    return " ".join(values)


def quality_certificate_manufacturer(text_items: list[tuple[str, dict[str, Any]]]) -> dict[str, Any] | None:
    for text, fragment in text_items[:30]:
        if "有限公司" in text and not any(token in text for token in ["项目", "单位名称", "业务范围"]):
            return {"text": text, "fragment": fragment}
    return None


def quality_certificate_specification(text_items: list[tuple[str, dict[str, Any]]]) -> dict[str, Any] | None:
    for text, fragment in text_items:
        normalized = text.replace(" ", "")
        if re.search(r"\b(?:WN|DN|NPS)\s*\d+", text, flags=re.I) or PIPE_SIZE_RE.search(text) or "S=" in normalized:
            return {"text": text, "fragment": fragment}
    return next_value_after_label(text_items, ["规格", "规格型号"], max_steps=8)


def quality_certificate_conclusion(text_items: list[tuple[str, dict[str, Any]]]) -> dict[str, Any] | None:
    for text, fragment in text_items:
        if "检验合格" in text or text == "合格":
            return {"text": "检验合格" if "检验合格" in text else text, "fragment": fragment}
    return next_value_after_label(text_items, ["结论", "检验结论"], max_steps=4)


def next_value_after_label(
    text_items: list[tuple[str, dict[str, Any]]],
    labels: list[str],
    *,
    max_steps: int = 5,
) -> dict[str, Any] | None:
    label_set = set(labels)
    reject_tokens = {
        "产品名称",
        "规格",
        "数量",
        "执行标准",
        "化学成分%",
        "化学成分",
        "结论",
        "质检专用章",
        "收货单位",
    }
    for index, (text, _) in enumerate(text_items):
        compact = text.strip(" ：:")
        if compact not in label_set and not any(label in compact and len(compact) <= len(label) + 2 for label in labels):
            continue
        for value_text, value_fragment in text_items[index + 1 : index + 1 + max_steps]:
            value = value_text.strip(" ：:")
            if not value or value in reject_tokens or value in label_set:
                continue
            if len(value) > 80:
                continue
            return {"text": value, "fragment": value_fragment}
    return None


def regex_field_candidate(text_items: list[tuple[str, dict[str, Any]]], pattern: re.Pattern[str]) -> dict[str, Any] | None:
    for text, fragment in text_items:
        match = pattern.search(text)
        if match:
            return {"text": match.group(0).replace(" ", ""), "fragment": fragment}
    return None


def add_profile_quality_diagnostics(result: dict[str, Any], profile: dict[str, Any]) -> None:
    diagnostics = result.setdefault("diagnostics", [])
    if (profile.get("sealRules") or {}).get("required") and not result.get("seals"):
        diagnostics.append(diagnostic("SEAL_NOT_FOUND", "当前 Profile 要求印章，但未检测到印章候选。", level="warning"))
    required_fields = profile.get("requiredFields") or []
    field_codes = {str(item.get("fieldCode") or "") for item in result.get("fields") or [] if isinstance(item, dict)}
    missing_fields = [field for field in required_fields if field != "seal" and field not in field_codes]
    if missing_fields:
        diagnostics.append(
            diagnostic(
                "REQUIRED_FIELD_MISSING",
                "Profile 必抽字段仍有缺失。",
                level="warning",
                missingFields=missing_fields,
            )
        )
    required_tables = [str(table) for table in profile.get("requiredTables") or []]
    tables = [table for table in result.get("tables") or [] if isinstance(table, dict)]
    missing_tables = missing_required_tables(tables, required_tables)
    if missing_tables:
        diagnostics.append(
            diagnostic(
                "REQUIRED_TABLE_MISSING",
                "Profile 必需表格仍有缺失。",
                level="warning",
                missingTables=missing_tables,
            )
        )
    min_table_confidence = float((profile.get("qualityRules") or {}).get("minTableStructureConfidence") or 0)
    for table in result.get("tables") or []:
        if not isinstance(table, dict):
            continue
        confidence = float(table.get("structureConfidence") or 0)
        if min_table_confidence and confidence < min_table_confidence:
            diagnostics.append(
                diagnostic(
                    "TABLE_STRUCTURE_LOW_CONFIDENCE",
                    "表格结构置信度低于 Profile 阈值。",
                    level="warning",
                    tableId=table.get("tableId"),
                    confidence=confidence,
                    threshold=min_table_confidence,
                )
            )


def add_field_if_missing(result: dict[str, Any], field_code: str, field_name: str, candidate: Any) -> None:
    if not candidate:
        return
    fields = result.setdefault("fields", [])
    if any(isinstance(item, dict) and item.get("fieldCode") == field_code for item in fields):
        return
    text = candidate.get("text") if isinstance(candidate, dict) else None
    fragment = candidate.get("fragment") if isinstance(candidate, dict) else None
    if not text or not isinstance(fragment, dict):
        return
    fields.append(
        {
            "fieldCode": field_code,
            "fieldName": field_name,
            "fieldValue": str(text),
            "pageNo": page_no_from(fragment),
            "bbox": rect_from_bbox(fragment.get("bbox")),
            "confidence": first_present(fragment, "confidence", default=0.0),
            "extractionMethod": "profile_heuristic",
            "sourceEngine": first_present(fragment, "sourceEngine", default="profile_postprocessor"),
        }
    )


def find_text_fragment(text_items: list[tuple[str, dict[str, Any]]], needles: list[str]) -> dict[str, Any] | None:
    for needle in needles:
        for text, fragment in text_items:
            if needle in text or needle.upper() in text.upper():
                return {"text": needle if needle in text else text, "fragment": fragment}
    return None


def find_project_fragment(text_items: list[tuple[str, dict[str, Any]]]) -> dict[str, Any] | None:
    for text, fragment in text_items:
        if "项目名称" in text or "PROJECT" in text.upper():
            cleaned = text.replace("项目名称", "").replace("PROJECT", "").strip(" ：:")
            if cleaned:
                return {"text": cleaned, "fragment": fragment}
    for text, fragment in text_items:
        if "有限公司" in text and ("项目" in text or "新增" in text):
            return {"text": text, "fragment": fragment}
    return None


def match_to_fragment(text_items: list[tuple[str, dict[str, Any]]], value: str) -> dict[str, Any] | None:
    for text, fragment in text_items:
        if value in text:
            return {"text": value, "fragment": fragment}
    return {
        "text": value,
        "fragment": {"pageNo": 1, "bbox": None, "confidence": 0.78, "sourceEngine": "profile_regex"},
    }


def rect_from_bbox(raw_bbox: Any) -> list[float] | None:
    if not isinstance(raw_bbox, list) or not raw_bbox:
        return None
    if len(raw_bbox) == 4 and all(isinstance(value, (int, float)) for value in raw_bbox):
        x0, y0, x1, y1 = [float(value) for value in raw_bbox]
        return [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]
    points = []
    for point in raw_bbox:
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            try:
                points.append((float(point[0]), float(point[1])))
            except (TypeError, ValueError):
                continue
    if not points:
        return None
    return [min(x for x, _ in points), min(y for _, y in points), max(x for x, _ in points), max(y for _, y in points)]


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
