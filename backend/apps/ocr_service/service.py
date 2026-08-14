from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import threading
import time
import zipfile
from copy import deepcopy
from functools import wraps
from pathlib import Path
from typing import Any
from uuid import uuid4
from xml.etree import ElementTree

from apps.ocr_service.engines import local_engines
from apps.ocr_service.fusion import (
    fuse_parse_result,
    missing_required_tables,
    normalize_field_key,
    table_cell_evidence_score,
    validate_business_field_value,
)
from apps.ocr_service.jobs import DocumentParseJobStore
from apps.ocr_service.pages import (
    public_document_pages,
    render_document_pages,
    render_pdf_page_preview,
)
from apps.ocr_service.preprocess import generate_image_variants, requested_variant_names
from apps.ocr_service.quality import probe_page_quality
from apps.ocr_service.result_cache import (
    EVIDENCE_CONTRACT_VERSION,
    PAGE_SELECTION_VERSION,
    REMEDIATION_VERSION,
    build_engine_result_cache_key,
    build_result_cache_key,
    engine_result_cache_dir,
    load_engine_result_cache,
    load_result_cache,
    rehydrate_cached_result,
    result_cache_dir,
    save_engine_result_cache,
    save_result_cache,
)
from apps.ocr_service.routing import route_engine_variants
from apps.ocr_service.runtime_doctor import build_runtime_doctor
from libs.capacity_guard import disk_capacity_status
from libs.contracts.responses import server_time
from libs.integrations.storage import object_storage, parse_storage_url
from libs.ocr.profiles import profile_for
from libs.ocr.utils import parse_bool
from libs.ocr.welder_certificate_tool import (
    extract_welder_certificate_from_ocr_result,
    welder_certificate_ocr_fields,
    welder_certificate_ocr_tables,
)
from libs.ocr.welder_certificate_tool import (
    extraction_metadata as welder_certificate_extraction_metadata,
)

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


def ocr_cache_readiness_payload() -> dict[str, Any]:
    paths = {
        "preprocess": Path(
            os.getenv("AICHECK_OCR_PREPROCESS_CACHE_DIR")
            or (Path(tempfile.gettempdir()) / "aicheck-ocr-preprocess-cache")
        ),
        "results": result_cache_dir(),
        "engines": engine_result_cache_dir(),
    }
    statuses: dict[str, dict[str, Any]] = {}
    for name, path in paths.items():
        writable = False
        error_code = None
        probe_path: Path | None = None
        try:
            path.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(prefix=".aicheck-ready-", dir=path, delete=False) as probe:
                probe.write(b"ok")
                probe_path = Path(probe.name)
            writable = True
        except OSError as exc:
            error_code = exc.__class__.__name__
        finally:
            if probe_path is not None:
                probe_path.unlink(missing_ok=True)
        statuses[name] = {"path": str(path), "writable": writable, "errorCode": error_code}
    return {"writable": all(item["writable"] for item in statuses.values()), "paths": statuses}


PIPE_CODE_RE = re.compile(r"\b(?:PL|VT)\d{3,5}\b", re.IGNORECASE)
DRAWING_NO_RE = re.compile(r"\b[A-Z]{1,4}\d{6,}[A-Z0-9.-]*\b")
ENGINEERING_DRAWING_NO_RE = re.compile(r"\b[A-Z]{1,6}\d{4,}[A-Z0-9]*(?:[-.][A-Z0-9]+){2,}\b", re.IGNORECASE)
DESIGN_PHASE_RE = re.compile(r"(施工图|初步设计|详细设计|竣工图)")
DRAWING_LIST_SEQUENCE_RE = re.compile(r"\b[A-Z]{1,4}\d{6,}[A-Z0-9-]*-\d{2}\b", re.IGNORECASE)
DN_RE = re.compile(r"\bDN\s*\d+\b", re.IGNORECASE)
PIPE_SIZE_RE = re.compile(r"[Φ①]?\s*\d{2,4}\s*[x×]\s*\d+(?:\.\d+)?", re.IGNORECASE)
PID_RE = re.compile(r"\b[A-Z]-\d+\b", re.IGNORECASE)
NUMBER_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
DATE_CN_RE = re.compile(r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日")
STANDARD_NO_RE = re.compile(r"\b(?:GB|HG|NB|JB|SH|SY|TSG)\s*/?\s*T?\s*[\d.-]+(?:-\d{4})?\b", re.IGNORECASE)
LICENSE_NO_RE = re.compile(r"\b(?:TS|A)\s*[A-Z0-9]{6,12}(?:-\d{4})?\b", re.IGNORECASE)
CHINESE_TEXT_RE = re.compile(r"[\u4e00-\u9fff]")

REMEDIATION_TRIGGER_REASONS = {
    "REQUIRED_FIELD_MISSING",
    "FIELD_LOW_CONFIDENCE",
    "FIELD_FORMAT_INVALID",
    "FIELD_EVIDENCE_MISSING",
    "FIELD_VALUE_CONFLICT",
    "REQUIRED_TABLE_MISSING",
    "TABLE_STRUCTURE_LOW_CONFIDENCE",
    "TABLE_CELL_EVIDENCE_LOW",
    "TABLE_CONTENT_SPARSE",
    "TABLE_EVIDENCE_MISSING",
    "TABLE_ENGINE_CONFLICT",
    "SEAL_TEXT_LOW_CONFIDENCE",
    "SEAL_NOT_FOUND",
    "SEAL_EVIDENCE_MISSING",
    "EXPECTED_SEAL_TYPE_MISSING",
}

ENGINEERING_DRAWING_PROFILE_IDS = {
    "piping_characteristic_list_v1",
    "engineering_drawing_list_v1",
    "drawing_material_list_v1",
    "process_flow_diagram_v1",
    "strength_calculation_v1",
    "design_specification_v1",
    "equipment_list_v1",
    "paint_insulation_list_v1",
    "comprehensive_material_list_v1",
    "site_layout_drawing_v1",
}
ENGINEERING_DRAWING_DOCUMENT_TYPES = {
    "engineering_table_photo",
    "engineering_drawing_list",
    "drawing_material_list",
    "process_flow_diagram",
    "strength_calculation",
    "design_specification",
    "equipment_list",
    "paint_insulation_list",
    "comprehensive_material_list",
    "site_layout_drawing",
}
GENERIC_PROFILE_IDS = {"", "generic_document", "generic_document_v1"}
GENERIC_DOCUMENT_TYPES = {"", "generic_document"}
R24_R34_BUSINESS_PROFILE_IDS = {
    "pipeline_summary_v1",
    "welding_consumable_certificate_v1",
    "welding_consumable_management_v1",
    "pipe_fit_up_record_v1",
    "weld_appearance_record_v1",
    "weld_repair_record_v1",
    "heat_treatment_procedure_v1",
    "heat_treatment_instrument_v1",
    "heat_treatment_record_v1",
    "hardness_report_v1",
}
R24_R34_BUSINESS_DOCUMENT_TYPES = {item.removesuffix("_v1") for item in R24_R34_BUSINESS_PROFILE_IDS}
AUTO_ROUTE_PROFILE_IDS = {
    *ENGINEERING_DRAWING_PROFILE_IDS,
    "quality_certificate_v1",
    "manufacturing_supervision_certificate_v1",
    "type_test_report_v1",
    "technical_review_approval_v1",
    "new_material_data_v1",
    "material_mark_transfer_record_v1",
    "material_substitution_approval_v1",
    "valve_test_report_v1",
    "factory_inspection_report_v1",
    "material_retest_report_v1",
    "acceptance_witness_record_v1",
    "sampling_witness_record_v1",
    "material_ndt_report_v1",
    "ndt_rt_report_v1",
    "ndt_ut_report_v1",
    "qualification_certificate_v1",
    "construction_plan_v1",
    "welding_record_v1",
    "welding_procedure_qualification_v1",
    "welder_certificate_v1",
}
BUSINESS_PDF_DEEP_SCAN_PROFILE_IDS = {
    *R24_R34_BUSINESS_PROFILE_IDS,
    "quality_certificate_v1",
    "manufacturing_supervision_certificate_v1",
    "type_test_report_v1",
    "technical_review_approval_v1",
    "new_material_data_v1",
    "material_mark_transfer_record_v1",
    "material_substitution_approval_v1",
    "valve_test_report_v1",
    "factory_inspection_report_v1",
    "material_retest_report_v1",
    "acceptance_witness_record_v1",
    "sampling_witness_record_v1",
    "material_ndt_report_v1",
    "ndt_rt_report_v1",
    "ndt_ut_report_v1",
    "qualification_certificate_v1",
    "welding_procedure_qualification_v1",
    "welder_certificate_v1",
}
BUSINESS_PDF_DEEP_SCAN_DOCUMENT_TYPES = {
    *R24_R34_BUSINESS_DOCUMENT_TYPES,
    "quality_certificate",
    "manufacturing_supervision_certificate",
    "type_test_report",
    "technical_review_approval",
    "new_material_data",
    "material_mark_transfer_record",
    "material_substitution_approval",
    "valve_test_report",
    "factory_inspection_report",
    "material_retest_report",
    "acceptance_witness_record",
    "sampling_witness_record",
    "material_ndt_report",
    "ndt_report",
    "qualification_certificate",
    "welding_procedure_qualification",
    "welder_certificate",
}
BUSINESS_PDF_DEEP_SCAN_DEFAULT_MAX_PAGES = {
    **{profile_id: 12 for profile_id in R24_R34_BUSINESS_PROFILE_IDS},
    "qualification_certificate_v1": 2,
    "quality_certificate_v1": 6,
    "manufacturing_supervision_certificate_v1": 6,
    "type_test_report_v1": 8,
    "technical_review_approval_v1": 8,
    "new_material_data_v1": 10,
    "material_mark_transfer_record_v1": 8,
    "material_substitution_approval_v1": 8,
    "valve_test_report_v1": 10,
    "factory_inspection_report_v1": 8,
    "material_retest_report_v1": 8,
    "acceptance_witness_record_v1": 8,
    "sampling_witness_record_v1": 8,
    "material_ndt_report_v1": 8,
    "ndt_rt_report_v1": 4,
    "ndt_ut_report_v1": 4,
    "welder_certificate_v1": 4,
    "welding_procedure_qualification_v1": 6,
}
PDF_DEEP_SCAN_PRIMARY_OPTION_KEYS = {
    "fullOcr",
    "deepScan",
    "deepScanPdf",
    "forceVisualOcr",
    "disablePdfTextLayerFastPath",
    "textLayerOnly",
}
FAST_FIRST_PROFILE_IDS = set(ENGINEERING_DRAWING_PROFILE_IDS)
FAST_FIRST_DOCUMENT_TYPES = set(ENGINEERING_DRAWING_DOCUMENT_TYPES)
FAST_FIRST_DEFERRED_ENGINES = {
    "pp_structure_v3",
    "opencv_table_grid_subprocess",
    "paddlex_seal_recognition",
    "agentdesign_seal_ocr_subprocess",
    "visual_seal_candidate_subprocess",
    "paddleocr_vl_1_6",
    "docling_local",
}

TABLE_REMEDIATION_REASONS = {
    "REQUIRED_TABLE_MISSING",
    "TABLE_STRUCTURE_LOW_CONFIDENCE",
    "TABLE_CELL_EVIDENCE_LOW",
    "TABLE_CONTENT_SPARSE",
    "TABLE_EVIDENCE_MISSING",
    "TABLE_ENGINE_CONFLICT",
}

TEXT_DOCUMENT_SUFFIXES = {".md", ".markdown", ".txt", ".csv", ".json", ".yaml", ".yml"}
OFFICE_TEXT_DOCUMENT_SUFFIXES = {".docx"}
TEXT_REMEDIATION_REASONS = {
    "REQUIRED_FIELD_MISSING",
    "FIELD_LOW_CONFIDENCE",
    "FIELD_FORMAT_INVALID",
    "FIELD_EVIDENCE_MISSING",
    "FIELD_VALUE_CONFLICT",
}
SEAL_REMEDIATION_REASONS = {
    "SEAL_TEXT_LOW_CONFIDENCE",
    "SEAL_NOT_FOUND",
    "SEAL_EVIDENCE_MISSING",
    "EXPECTED_SEAL_TYPE_MISSING",
}


def pdf_deep_scan_requested(options: dict[str, Any]) -> bool:
    return any(
        parse_bool(options.get(key), False) is True
        for key in [
            "fullOcr",
            "deepScan",
            "deepScanPdf",
            "forceVisualOcr",
            "forceTableOcr",
            "forceSealOcr",
            "disablePdfTextLayerFastPath",
        ]
    )


def pdf_text_layer_fast_path_enabled(options: dict[str, Any]) -> bool:
    if parse_bool(os.getenv("AICHECK_OCR_PDF_TEXT_LAYER_FAST_PATH", "true"), True) is not True:
        return False
    if pdf_deep_scan_requested(options):
        return False
    return True


def apply_business_pdf_deep_scan_default_options(
    options: dict[str, Any],
    profile: dict[str, Any],
    *,
    suffix: str,
) -> dict[str, Any]:
    if suffix != ".pdf":
        return options
    if parse_bool(options.get("disablePdfDeepScanDefault"), False) is True:
        return options
    if any(key in options for key in PDF_DEEP_SCAN_PRIMARY_OPTION_KEYS):
        return options
    if str(options.get("standardIndexingStrategy") or "") or parse_bool(options.get("preferTextLayer"), False) is True:
        return options
    profile_id = str(profile.get("profileId") or "")
    document_type = str(profile.get("documentType") or "")
    if profile_id not in BUSINESS_PDF_DEEP_SCAN_PROFILE_IDS and document_type not in BUSINESS_PDF_DEEP_SCAN_DOCUMENT_TYPES:
        return options

    adjusted = deepcopy(options)
    adjusted.setdefault("deepScanPdf", True)
    adjusted.setdefault("disablePdfTextLayerFastPath", True)
    adjusted.setdefault("enableFallback", True)
    adjusted.setdefault("enableSealCropEvidence", True)
    adjusted.setdefault("pageCoverageMode", "deep_scan")
    adjusted.setdefault("deepScanDefaultReason", f"business_pdf_profile:{profile_id or document_type}")
    if adjusted.get("maxPages") is None:
        adjusted["maxPages"] = BUSINESS_PDF_DEEP_SCAN_DEFAULT_MAX_PAGES.get(profile_id, 4)
    if profile_id == "qualification_certificate_v1":
        adjusted.setdefault("enablePaddlexSeal", False)
        adjusted.setdefault("enableSealTextRecognition", False)
        adjusted.setdefault("enableRasterTextOcr", False)
        adjusted.setdefault("enableTables", False)
        adjusted.setdefault("forceFallbackOcr", True)
        adjusted.setdefault("disableRemediation", False)
        adjusted.setdefault("enableVlLayoutTextRemediation", True)
        adjusted.setdefault("engineBudgetSeconds", 120)
        adjusted.setdefault("renderDpi", 250)
        adjusted.setdefault("maxLongSide", 1800)
        adjusted.setdefault("textDetLimitSideLen", 1800)
        adjusted.setdefault("variants", ["original"])

    if profile.get("requiredTables") and parse_bool(adjusted.get("enableTables"), True) is not False:
        adjusted.setdefault("fullOcr", True)
        adjusted.setdefault("enableTables", True)
        adjusted.setdefault("forceTableOcr", True)
    seal_required = parse_bool((profile.get("sealRules") or {}).get("required"), False) is True
    if seal_required and parse_bool(adjusted.get("enableSeals"), True) is not False:
        adjusted.setdefault("enableSeals", True)
        adjusted.setdefault("forceSealOcr", True)
    return adjusted


def serialized_parse(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._parse_lock:
            return method(self, *args, **kwargs)

    return wrapped


def memory_headroom_payload() -> dict[str, Any]:
    try:
        current = int(Path("/sys/fs/cgroup/memory.current").read_text(encoding="utf-8").strip())
        maximum_raw = Path("/sys/fs/cgroup/memory.max").read_text(encoding="utf-8").strip()
        if maximum_raw != "max":
            maximum = int(maximum_raw)
            available = max(maximum - current, 0)
            return {
                "source": "cgroup_v2",
                "currentBytes": current,
                "limitBytes": maximum,
                "availableBytes": available,
                "availableMb": round(available / 1024 / 1024, 1),
            }
    except (OSError, ValueError):
        pass
    try:
        current = int(Path("/sys/fs/cgroup/memory/memory.usage_in_bytes").read_text(encoding="utf-8").strip())
        maximum = int(Path("/sys/fs/cgroup/memory/memory.limit_in_bytes").read_text(encoding="utf-8").strip())
        available = max(maximum - current, 0)
        return {
            "source": "cgroup_v1",
            "currentBytes": current,
            "limitBytes": maximum,
            "availableBytes": available,
            "availableMb": round(available / 1024 / 1024, 1),
        }
    except (OSError, ValueError):
        pass
    try:
        values = {}
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, _, raw = line.partition(":")
            values[key] = int(raw.strip().split()[0]) * 1024
        available = int(values.get("MemAvailable") or 0)
        return {
            "source": "proc_meminfo",
            "currentBytes": None,
            "limitBytes": int(values.get("MemTotal") or 0),
            "availableBytes": available,
            "availableMb": round(available / 1024 / 1024, 1),
        }
    except (OSError, ValueError):
        return {"source": "unavailable", "availableBytes": 0, "availableMb": 0.0}


class OcrService:
    def __init__(self) -> None:
        self.pipeline = self._load_pipeline()
        self.engines = local_engines()
        self.jobs = DocumentParseJobStore()
        self._parse_lock = threading.Lock()
        self._readiness_probe_lock = threading.Lock()
        self._last_inference: dict[str, Any] = {
            "inferenceStatus": "not_run",
            "lastSuccessfulInferenceAt": None,
            "lastInferenceAttemptAt": None,
            "lastInferenceDurationMs": None,
            "lastInferenceErrorCode": None,
        }

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
        engines = self.engine_status()
        capacity = memory_headroom_payload()
        disk_capacity = disk_capacity_status()
        cache = ocr_cache_readiness_payload()
        minimum_headroom_mb = int(os.getenv("AICHECK_OCR_MIN_MEMORY_HEADROOM_MB", "2048"))
        memory_ready = float(capacity.get("availableMb") or 0) >= minimum_headroom_mb
        disk_gate_enabled = env_bool("AICHECK_OCR_DISK_READINESS_GATE", False)
        storage_ready = not disk_gate_enabled or bool(disk_capacity["readinessReady"])
        return {
            "status": "ok",
            "service": "ocr-service",
            "capability": "document-intelligence-service",
            "pipelineAvailable": self.pipeline_available,
            "pipelineBackend": str(AGENTDESIGN_BACKEND),
            "placeholderAllowed": self.placeholder_allowed,
            "offlineOnly": self.offline_only,
            "networkDisabled": self.disable_network,
            "engines": engines,
            "modelManifest": self.model_manifest(),
            "executable": any(bool(engine.get("executable")) for engine in engines),
            "warmedUp": any(bool(engine.get("warmedUp")) for engine in engines),
            "capacityReady": memory_ready and storage_ready,
            "memoryCapacityReady": memory_ready,
            "storageCapacityReady": storage_ready,
            "diskCapacityGateEnabled": disk_gate_enabled,
            "memoryHeadroom": capacity,
            "diskCapacity": disk_capacity,
            "cacheWritable": cache["writable"],
            "cachePaths": cache["paths"],
            "inferenceStatus": self._last_inference.get("inferenceStatus"),
            "lastSuccessfulInferenceAt": self._last_inference.get("lastSuccessfulInferenceAt"),
            "lastInferenceAttemptAt": self._last_inference.get("lastInferenceAttemptAt"),
            "lastInferenceDurationMs": self._last_inference.get("lastInferenceDurationMs"),
            "lastInferenceErrorCode": self._last_inference.get("lastInferenceErrorCode"),
        }

    def readiness_payload(self) -> dict[str, Any]:
        failures = []
        if self.placeholder_allowed:
            failures.append("AICHECK_OCR_ALLOW_PLACEHOLDER must be false.")
        if not self.pipeline_available:
            failures.append("No local OCR engine or agentdesign OCR pipeline is available.")
        health = self.health_payload()
        if not health["executable"]:
            failures.append("No OCR engine is executable in the current runtime.")
        if not health["memoryCapacityReady"]:
            failures.append("OCR memory headroom is below the configured minimum.")
        if not health["storageCapacityReady"]:
            failures.append("OCR host disk capacity has reached the readiness failure threshold.")
        if not health["cacheWritable"]:
            failures.append("OCR cache directories are not writable.")
        if env_bool("AICHECK_OCR_DEEP_READY_PROBE", False) and self._last_inference.get("inferenceStatus") != "success":
            failures.append("OCR deep readiness probe has not succeeded.")
        if self.offline_only:
            for key, default in REQUIRED_MODEL_ENV_KEYS.items():
                path = Path(os.getenv(key, default))
                if not path.exists():
                    failures.append(f"{key} model path is missing: {path}")
        cloud_keys = sorted(key for key in os.environ if key.startswith(("AWS_", "AZURE_", "GOOGLE_", "ALIBABA_")))
        if cloud_keys:
            failures.append("Cloud OCR/provider environment variables are not allowed for local-only OCR.")
        return {
            **health,
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

    def render_page_preview(
        self,
        storage_key: str,
        *,
        file_name: str | None = None,
        profile_id: str | None = None,
        document_type: str | None = None,
        options: dict[str, Any] | None = None,
        page_no: int = 1,
    ) -> dict[str, Any] | None:
        source_path = resolve_source_path(storage_key, file_name)
        if source_path is None:
            return None
        profile = apply_parse_options_to_profile(profile_for(profile_id, document_type), options or {})
        policy = profile.get("preprocessPolicy") or {}
        dpi = int(policy.get("renderDpi") or 180)
        max_long_side = int(policy.get("maxLongSide") or 1600)
        if source_path.suffix.lower() == ".pdf":
            return render_pdf_page_preview(
                source_path,
                page_no=page_no,
                dpi=dpi,
                max_long_side=max_long_side,
            )
        pages = render_document_pages(source_path, profile=profile)
        return pages[0] if pages else None

    def engine_status(self) -> list[dict[str, Any]]:
        statuses = []
        for engine in self.engines:
            status = engine.status()
            execution_mode = str(status.get("executionMode") or "")
            status["executable"] = bool(status.get("available")) and execution_mode not in {"disabled", "unavailable"}
            status.setdefault("warmedUp", False)
            statuses.append(status)
        return statuses

    def run_readiness_probe(self) -> dict[str, Any]:
        with self._readiness_probe_lock:
            started = time.monotonic()
            target: Path | None = None
            self._last_inference.update(
                {
                    "inferenceStatus": "running",
                    "lastInferenceAttemptAt": server_time(),
                    "lastInferenceDurationMs": None,
                    "lastInferenceErrorCode": None,
                }
            )
            try:
                from PIL import Image, ImageDraw, ImageFont

                with tempfile.NamedTemporaryFile(prefix="aicheck-ocr-ready-", suffix=".png", delete=False) as handle:
                    target = Path(handle.name)
                image = Image.new("RGB", (640, 160), "white")
                font = ImageFont.load_default(size=48)
                ImageDraw.Draw(image).text((32, 48), "AICHECK OCR 2026", fill="black", font=font)
                image.save(target)
                engine = next(
                    (item for item in self.engines if item.name == "paddle_ocr_subprocess" and item.available()),
                    None,
                )
                if engine is None:
                    raise RuntimeError("PADDLE_OCR_ENGINE_UNAVAILABLE")
                raw = engine.parse(target, file_name=target.name, profile=profile_for("generic_document_v1"))
                normalized = normalize_ocr_result(raw, str(target), target.name)
                if not has_parse_content(normalized):
                    raise RuntimeError("PADDLE_OCR_PROBE_EMPTY")
                self._last_inference.update(
                    {
                        "inferenceStatus": "success",
                        "lastSuccessfulInferenceAt": server_time(),
                        "lastInferenceDurationMs": round((time.monotonic() - started) * 1000),
                        "lastInferenceErrorCode": None,
                    }
                )
            except Exception as exc:
                self._last_inference.update(
                    {
                        "inferenceStatus": "failed",
                        "lastInferenceDurationMs": round((time.monotonic() - started) * 1000),
                        "lastInferenceErrorCode": exc.__class__.__name__,
                    }
                )
            finally:
                if target is not None:
                    target.unlink(missing_ok=True)
            return dict(self._last_inference)

    def record_parse_result(
        self,
        result: dict[str, Any],
        *,
        update_readiness: bool = True,
    ) -> dict[str, Any]:
        if not update_readiness:
            return result
        outcome = str(result.get("outcomeStatus") or result.get("status") or "failed")
        succeeded = outcome in {"success", "completed"}
        self._last_inference.update(
            {
                "inferenceStatus": "success" if succeeded else "failed",
                "lastInferenceAttemptAt": server_time(),
                "lastSuccessfulInferenceAt": server_time() if succeeded else self._last_inference.get("lastSuccessfulInferenceAt"),
                "lastInferenceErrorCode": None if succeeded else "OCR_RESULT_NOT_USABLE",
            }
        )
        return result

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

    @serialized_parse
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
        options = options or {}
        update_readiness = not (
            str(options.get("baselineParseResultId") or "").strip()
            or engine_allowlist(options) is not None
        )
        source_path = resolve_source_path(storage_key, file_name)
        os.getenv("AICHECK_OCR_ALLOW_PLACEHOLDER", "false")
        if source_path is None:
            return self.record_parse_result(
                failed_result(
                    storage_key,
                    file_name,
                    "OCR source file is unavailable. Check MinIO object key, credentials, or mounted file path.",
                ),
                update_readiness=update_readiness,
            )
        suffix = source_path.suffix.lower()
        if suffix in TEXT_DOCUMENT_SUFFIXES:
            return self.record_parse_result(
                parse_text_document(source_path, storage_key, file_name),
                update_readiness=update_readiness,
            )
        if suffix in OFFICE_TEXT_DOCUMENT_SUFFIXES:
            return self.record_parse_result(
                parse_docx_document(source_path, storage_key, file_name),
                update_readiness=update_readiness,
            )
        base_profile = profile_for(profile_id, document_type)
        options = apply_business_pdf_deep_scan_default_options(options, base_profile, suffix=suffix)
        options = apply_fast_first_default_options(options, base_profile)
        profile = apply_parse_options_to_profile(base_profile, options)
        if suffix == ".pdf" and pdf_text_layer_fast_path_enabled(options):
            fast_result = self.parse_pdf_text_layer_fast_path(
                source_path,
                storage_key=storage_key,
                file_name=file_name,
                profile=profile,
                document_version_id=document_version_id,
                business_pack_id=business_pack_id,
            )
            if fast_result is not None:
                return self.record_parse_result(fast_result, update_readiness=update_readiness)
            if parse_bool(options.get("textLayerOnly"), False):
                return self.record_parse_result(
                    failed_result(
                        storage_key,
                        file_name,
                        diagnostic(
                            "PDF_TEXT_LAYER_UNAVAILABLE",
                            "PDF 未检测到可抽取文本层，标准规范库已跳过高内存视觉 OCR。",
                            level="error",
                        ),
                    ),
                    update_readiness=update_readiness,
                )
        candidate_results: list[dict[str, Any]] = []
        if suffix == ".pdf" and pdf_deep_scan_requested(options):
            candidate_results.append(
                {
                    "ok": True,
                    "status": "success",
                    "metadata": {
                        "deepScanMode": "requested",
                        "pageCoverageMode": "deep_scan",
                        "pdfTextLayerFastPathSkipped": True,
                        "deepScanDefaultReason": options.get("deepScanDefaultReason"),
                        "rasterTextOcrEnabled": parse_bool(options.get("enableRasterTextOcr"), True) is True,
                        "fallbackOcrForced": parse_bool(options.get("forceFallbackOcr"), False) is True,
                    },
                    "diagnostics": [
                        diagnostic(
                            "PDF_TEXT_LAYER_FAST_PATH_SKIPPED",
                            "已按请求跳过 PDF 文本层 fast path，继续执行 OCR/表格/印章深扫。",
                            level="info",
                        )
                    ],
                }
            )
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
            options=options,
            candidate_results=candidate_results,
        )
        if normalized.get("status") == "success":
            return self.record_parse_result(normalized, update_readiness=update_readiness)
        if self.placeholder_allowed:
            return self.record_parse_result(
                normalize_ocr_result(
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
                ),
                update_readiness=update_readiness,
            )
        diagnostics = normalized.get("diagnostics") or []
        if pipeline_error:
            diagnostics = [*diagnostics, pipeline_error]
        normalized["diagnostics"] = normalize_diagnostics(diagnostics)
        return self.record_parse_result(normalized, update_readiness=update_readiness)

    def parse_pdf_text_layer_fast_path(
        self,
        source_path: Path,
        *,
        storage_key: str,
        file_name: str | None,
        profile: dict[str, Any],
        document_version_id: str | None,
        business_pack_id: str | None,
    ) -> dict[str, Any] | None:
        engine = next((item for item in self.engines if item.name == "pymupdf_text_layer" and item.available()), None)
        if engine is None:
            return None
        started = monotonic_ms()
        try:
            raw = engine.parse(
                source_path,
                file_name=file_name,
                profile=profile,
                variant={"variantId": "pdf_text_layer_fast_path", "documentPath": str(source_path)},
            )
        except Exception:
            return None
        normalized = normalize_ocr_result(raw, storage_key, file_name)
        if not has_parse_content(normalized):
            return None
        attach_candidate_engine_metadata(normalized, engine.name)
        normalized["engineRuns"] = [
            {
                **engine.status(),
                "status": "success",
                "durationMs": max(monotonic_ms() - started, 0),
                "variantId": "pdf_text_layer_fast_path",
                "workerMode": "inprocess",
                "qualityScore": 0.9,
            }
        ]
        normalized.setdefault("diagnostics", []).append(
            diagnostic(
                "PDF_TEXT_LAYER_FAST_PATH",
                "PDF 文本层已直接抽取，跳过视觉 OCR。",
                level="info",
            )
        )
        enriched = enrich_parse_result(
            normalized,
            profile=profile,
            document_version_id=document_version_id,
            business_pack_id=business_pack_id,
            model_manifest=self.model_manifest(),
        )
        apply_contract_metadata(enriched)
        attach_observability_metrics(enriched, before_remediation=deepcopy(enriched))
        return enriched

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
        baseline_parse_result_id = str(options.get("baselineParseResultId") or "").strip()
        if baseline_parse_result_id:
            merged.setdefault("metadata", {})["baselineParseResultId"] = baseline_parse_result_id
        request_started_ms = monotonic_ms()
        fast_first_mode = parse_bool(options.get("fastFirstMode"), False) is True
        if fast_first_mode:
            merged.setdefault("metadata", {})["fastFirstMode"] = True
            merged.setdefault("metadata", {})["fastFirstPolicy"] = "text-first-defer-heavy-engines"
        document_pages = render_document_pages(source_path, profile=profile)
        merged["pages"] = public_document_pages(document_pages)
        if not document_pages and source_path.suffix.lower() == ".pdf":
            merged["diagnostics"].append(
                diagnostic(
                    "PDF_RENDER_FAILED",
                    "PDF 页面渲染失败，OCR 页级预处理和证据定位无法继续。",
                    level="error",
                )
            )
        page_quality = call_probe_page_quality(source_path, profile=profile, pages=document_pages)
        requested_variants = requested_variant_names(profile, page_quality, options=options)
        variants = call_generate_image_variants(
            source_path,
            profile=profile,
            page_quality=page_quality,
            pages=document_pages,
            options=options,
        )
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
            allowed_engines = engine_allowlist(options)
            if allowed_engines is not None and engine.name not in allowed_engines:
                merged["engineRuns"].append(
                    {
                        **engine_status,
                        "status": "skipped",
                        "durationMs": 0,
                        "reason": "engine_not_allowlisted",
                    }
                )
                continue
            if request_budget_exceeded(options, request_started_ms):
                merged["engineRuns"].append(
                    {
                        **engine_status,
                        "status": "skipped",
                        "durationMs": 0,
                        "reason": "request_budget_exceeded",
                    }
                )
                continue
            if not engine.available():
                merged["engineRuns"].append({**engine_status, "status": "unavailable", "durationMs": 0})
                continue
            if engine.name == "tesseract_cli" and tesseract_fallback_satisfied(
                merged,
                profile=profile,
                options=options,
            ):
                merged["engineRuns"].append(
                    {
                        **engine_status,
                        "status": "skipped",
                        "durationMs": 0,
                        "reason": "paddle_text_primary_evidence_sufficient",
                    }
                )
                continue
            if should_defer_heavy_engine(engine.name, merged, profile=profile, options=options):
                merged["engineRuns"].append(
                    {
                        **engine_status,
                        "status": "skipped",
                        "durationMs": 0,
                        "reason": "fast_first_text_primary_evidence_available",
                    }
                )
                continue
            if (
                parse_bool(options.get("quickMode"), False) is True
                and engine.name in {"paddle_ocr_subprocess", "paddle_ocr_v6"}
                and text_layer_content_sufficient(merged)
            ):
                merged["engineRuns"].append(
                    {
                        **engine_status,
                        "status": "skipped",
                        "durationMs": 0,
                        "reason": "quick_mode_text_layer_sufficient",
                    }
                )
                continue
            routed_variants = route_engine_variants(
                engine.name,
                variants,
                profile=profile,
                page_quality=page_quality,
                options={**options, "documentPath": str(source_path)},
            )
            if not routed_variants:
                merged["engineRuns"].append({**engine_status, "status": "skipped", "durationMs": 0})
                continue
            for variant in routed_variants:
                if request_budget_exceeded(options, request_started_ms):
                    merged["engineRuns"].append(
                        {
                            **engine_status,
                            "status": "skipped",
                            "durationMs": 0,
                            "reason": "request_budget_exceeded",
                            "variantId": variant.get("variantId"),
                            "preprocessChain": variant.get("preprocessChain") or [],
                            "purpose": variant.get("purpose"),
                        }
                    )
                    continue
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
                    attach_variant_metadata(normalized, engine.name, variant, document_pages=document_pages)
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
                            "engineCacheKey": engine_cache_key,
                            "cacheSourceRunId": f"engine-cache:{engine_cache_key}" if engine_cache_hit and engine_cache_key else None,
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
        attach_engine_execution_metadata(merged)
        if has_parse_content(merged):
            merged["status"] = "success"
            if fast_first_mode:
                heavy_skipped = [
                    item
                    for item in merged.get("engineRuns") or []
                    if item.get("status") == "skipped"
                    and str(item.get("reason") or "").startswith("fast_first_")
                ]
                if heavy_skipped:
                    merged.setdefault("metadata", {})["partialResult"] = True
                    merged.setdefault("metadata", {})["deferredHeavyEngineCount"] = len(heavy_skipped)
                    merged.setdefault("diagnostics", []).append(
                        diagnostic(
                            "FAST_FIRST_PARTIAL_RESULT",
                            "工程图照片已优先返回 OCR 文本主证据，整页重型表格/印章引擎已延后到 ROI 或人工复核阶段。",
                            level="info",
                            deferredEngines=sorted({str(item.get("engine") or "") for item in heavy_skipped}),
                        )
                    )
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
        enriched = self.run_fast_first_seal_crop_pass(
            enriched,
            source_path=source_path,
            storage_key=storage_key,
            file_name=file_name,
            profile=profile,
            variants=variants,
            model_manifest=model_manifest,
            document_version_id=document_version_id,
            business_pack_id=business_pack_id,
            options=options,
            document_pages=document_pages,
        )
        before_remediation = deepcopy(enriched)
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
            document_pages=document_pages,
        )
        apply_contract_metadata(enriched)
        attach_observability_metrics(enriched, before_remediation=before_remediation)
        if not has_external_candidates:
            save_result_cache(result_cache_key, enriched)
        return enriched

    def run_fast_first_seal_crop_pass(
        self,
        result: dict[str, Any],
        *,
        source_path: Path,
        storage_key: str,
        file_name: str | None,
        profile: dict[str, Any],
        variants: list[dict[str, Any]],
        model_manifest: dict[str, Any],
        document_version_id: str | None,
        business_pack_id: str | None,
        options: dict[str, Any],
        document_pages: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if parse_bool(options.get("enableSealCropEvidence"), True) is not True:
            return result
        if parse_bool(options.get("fastFirstMode"), False) is not True and not result.get("seals"):
            return result
        if any(
            isinstance(seal, dict) and seal.get("sealEvidenceLevel") == "visual_plus_seal_crop_ocr"
            for seal in result.get("seals") or []
        ):
            return result
        seal_targets = [
            seal
            for seal in result.get("seals") or []
            if isinstance(seal, dict)
            and seal.get("bbox")
            and seal.get("coordinateSystem") == "rendered_pixels"
        ]
        if not seal_targets:
            return result
        seal_policy = (profile.get("preprocessPolicy") or {}).get("seal") or {}
        try:
            padding_ratio = float(seal_policy.get("cropPaddingRatio") or 0.16)
        except (TypeError, ValueError):
            padding_ratio = 0.16
        crop_variants = build_crop_variants(
            seal_targets,
            variants,
            target_type="seal",
            purpose="seal",
            padding_ratio=padding_ratio,
            max_items=6,
            reasons={"SEAL_CROP_EVIDENCE"},
        )
        crop_variants = [variant for variant in crop_variants if variant.get("source") == "remediation_crop"]
        if not crop_variants:
            return result
        engine = self.first_available_crop_text_engine()
        if engine is None:
            enriched = deepcopy(result)
            enriched.setdefault("diagnostics", []).append(
                diagnostic(
                    "SEAL_CROP_OCR_ENGINE_UNAVAILABLE",
                    "已生成印章 ROI 裁剪候选，但没有可用文本 OCR 引擎执行 crop OCR。",
                    level="warning",
                )
            )
            return enriched
        cropped = deepcopy(result)
        cropped.setdefault("sealCropEvidenceRuns", [])
        for variant in crop_variants:
            started = monotonic_ms()
            try:
                raw = engine.parse(source_path, file_name=file_name, profile=profile, variant=variant)
                normalized = normalize_ocr_result(raw, storage_key, file_name)
                attach_variant_metadata(normalized, engine.name, variant, document_pages=document_pages)
                merge_parse_result(cropped, normalized)
                cropped["sealCropEvidenceRuns"].append(
                    {
                        **engine.status(),
                        "status": "success" if normalized.get("status") == "success" else "failed",
                        "durationMs": max(monotonic_ms() - started, 0),
                        "variantId": variant.get("variantId"),
                        "cropSourceTargetId": variant.get("cropSourceTargetId"),
                        "cropBbox": variant.get("cropSourceBbox"),
                    }
                )
            except Exception as exc:
                cropped["sealCropEvidenceRuns"].append(
                    {
                        **engine.status(),
                        "status": "failed",
                        "durationMs": max(monotonic_ms() - started, 0),
                        "errorCode": exc.__class__.__name__,
                        "variantId": variant.get("variantId"),
                        "cropSourceTargetId": variant.get("cropSourceTargetId"),
                        "cropBbox": variant.get("cropSourceBbox"),
                    }
                )
        if any(run.get("status") == "success" for run in cropped.get("sealCropEvidenceRuns") or []):
            cropped.setdefault("metadata", {})["sealCropEvidencePass"] = True
            cropped.setdefault("metadata", {})["sealCropEvidenceVariantCount"] = len(crop_variants)
            return enrich_parse_result(
                cropped,
                profile=profile,
                document_version_id=document_version_id,
                business_pack_id=business_pack_id,
                model_manifest=model_manifest,
            )
        return cropped

    def first_available_crop_text_engine(self):
        preferred = ["paddle_ocr_subprocess", "paddle_ocr_v6", "tesseract_cli"]
        for name in preferred:
            engine = next((item for item in self.engines if item.name == name and item.available()), None)
            if engine is not None:
                return engine
        return None

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
        document_pages: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if bool(options.get("disableRemediation")):
            return result
        reasons = {str(item) for item in ((result.get("quality") or {}).get("reasons") or [])}
        if not reasons.intersection(REMEDIATION_TRIGGER_REASONS):
            result.setdefault("remediationRuns", [])
            return result
        remediated = deepcopy(result)
        remediated["remediationRuns"] = []
        base_remediation_variants = remediation_variants_for_reasons(remediated, variants, reasons, profile=profile)
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
                base_remediation_variants,
                profile=profile,
                page_quality=page_quality,
                options={**remediation_options, "documentPath": str(source_path)},
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
                    attach_variant_metadata(normalized, engine.name, variant, document_pages=document_pages)
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
        if not job or job.get("status") == "canceled":
            return job
        self.jobs.heartbeat(job_id, stage="parse", progress=5)
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
        "metadata": raw.get("metadata", {}) if isinstance(raw, dict) and isinstance(raw.get("metadata"), dict) else {},
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


def parse_text_document(source_path: Path, storage_key: str, file_name: str | None) -> dict[str, Any]:
    try:
        text = source_path.read_text(encoding="utf-8", errors="ignore").strip()
    except OSError as exc:
        return failed_result(storage_key, file_name, f"Text document read failed: {exc.__class__.__name__}")
    if not text:
        return failed_result(storage_key, file_name, "Text document is empty.")
    return normalize_ocr_result(
        {
            "text": text,
            "pages": [
                {
                    "pageNo": 1,
                    "sourceType": source_path.suffix.lower().lstrip(".") or "text",
                    "coordinateSystem": "text",
                }
            ],
            "diagnostics": [
                diagnostic(
                    "TEXT_DOCUMENT_DIRECT_PARSE",
                    "文本类资料已直接抽取，无需视觉 OCR。",
                    level="info",
                )
            ],
            "metadata": {"textDocument": True},
        },
        storage_key,
        file_name,
    )


def parse_docx_document(source_path: Path, storage_key: str, file_name: str | None) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(source_path) as archive:
            document_xml = archive.read("word/document.xml")
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        return failed_result(storage_key, file_name, f"DOCX text read failed: {exc.__class__.__name__}")
    try:
        root = ElementTree.fromstring(document_xml)
    except ElementTree.ParseError as exc:
        return failed_result(storage_key, file_name, f"DOCX XML parse failed: {exc.__class__.__name__}")
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", namespace):
        text = "".join(node.text or "" for node in paragraph.findall(".//w:t", namespace)).strip()
        if text:
            paragraphs.append(text)
    content = "\n".join(paragraphs).strip()
    if not content:
        return failed_result(storage_key, file_name, "DOCX document has no extractable text.")
    return normalize_ocr_result(
        {
            "text": content,
            "pages": [
                {
                    "pageNo": 1,
                    "sourceType": "docx",
                    "coordinateSystem": "text",
                }
            ],
            "diagnostics": [
                diagnostic(
                    "DOCX_TEXT_DIRECT_PARSE",
                    "Word 文档已直接抽取文本，无需视觉 OCR。",
                    level="info",
                )
            ],
            "metadata": {"officeTextDocument": True},
        },
        storage_key,
        file_name,
    )


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
            drop_none_fields(
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
        )
    return normalized


def fields_from_seals(seals: Any) -> list[dict[str, Any]]:
    if not isinstance(seals, list):
        return []
    fields = []
    for seal in seals:
        if not isinstance(seal, dict):
            continue
        if seal_is_candidate_only(seal):
            continue
        page_no = page_no_from(seal)
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
                            "coordinateSystem": item.get("coordinateSystem") or seal.get("coordinateSystem"),
                            "sourceCoordinateSystem": item.get("sourceCoordinateSystem") or seal.get("sourceCoordinateSystem"),
                            "coordinateTransformStatus": item.get("coordinateTransformStatus") or seal.get("coordinateTransformStatus"),
                            "qualityFlags": item.get("qualityFlags") or seal.get("qualityFlags") or [],
                            "confidence": first_present(item, "confidence", "ocrConfidence", default=0.0),
                            "extractionMethod": "PaddleOCR+seal",
                            "sourceEngine": item.get("sourceEngine") or seal.get("sourceEngine"),
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
                    "coordinateSystem": seal.get("coordinateSystem"),
                    "sourceCoordinateSystem": seal.get("sourceCoordinateSystem"),
                    "coordinateTransformStatus": seal.get("coordinateTransformStatus"),
                    "qualityFlags": seal.get("qualityFlags") or [],
                    "confidence": first_present(value, "calibrated_confidence", "visual_confidence", "confidence", default=0.0),
                    "extractionMethod": "PaddleOCR+seal",
                    "sourceEngine": seal.get("sourceEngine"),
                }
            )
    return fields


def seal_is_candidate_only(seal: dict[str, Any]) -> bool:
    flags = {str(flag) for flag in seal.get("qualityFlags") or []}
    if parse_bool(seal.get("candidateOnly"), False) is True:
        return True
    if parse_bool(seal.get("canSatisfyRequiredSeal"), None) is False:
        return True
    return bool({"text_only_seal_candidate", "visual_candidate_only", "requires_seal_ocr_text"}.intersection(flags))


def normalize_raw_seals(seals: Any) -> list[dict[str, Any]]:
    if not isinstance(seals, list):
        return []
    normalized = []
    for index, seal in enumerate(seals, start=1):
        if not isinstance(seal, dict):
            continue
        normalized.append(
            drop_none_fields(
                {
                    "sealId": str(seal.get("sealId") or f"seal_{index}"),
                    "pageNo": page_no_from(seal),
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
                    "candidateOnly": parse_bool(seal.get("candidateOnly"), False),
                    "canSatisfyRequiredSeal": parse_bool(seal.get("canSatisfyRequiredSeal"), None),
                    "sealEvidenceLevel": seal.get("sealEvidenceLevel"),
                    "coordinateSystem": seal.get("coordinateSystem"),
                    "sourceCoordinateSystem": seal.get("sourceCoordinateSystem"),
                    "coordinateTransform": seal.get("coordinateTransform"),
                    "coordinateTransformStatus": seal.get("coordinateTransformStatus"),
                    "sourceEngine": seal.get("sourceEngine"),
                }
            )
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
    target.setdefault("metadata", {})
    if isinstance(incoming.get("metadata"), dict):
        for key, value in incoming["metadata"].items():
            if key == "enginePageInfo":
                continue
            target["metadata"].setdefault(key, deepcopy(value))
    if incoming.get("pages"):
        target["metadata"].setdefault("enginePageInfo", []).extend(deepcopy(incoming.get("pages") or []))
    for key in ["fragments", "layoutBlocks", "fields", "tables", "seals", "signatures", "diagnostics"]:
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


def apply_contract_metadata(result: dict[str, Any]) -> None:
    result["evidenceContractVersion"] = EVIDENCE_CONTRACT_VERSION
    result["pageSelectionVersion"] = PAGE_SELECTION_VERSION
    result["remediationVersion"] = REMEDIATION_VERSION


def attach_observability_metrics(
    result: dict[str, Any],
    *,
    before_remediation: dict[str, Any] | None = None,
) -> None:
    result["observabilityMetrics"] = build_observability_metrics(result, before_remediation=before_remediation)


def build_observability_metrics(
    result: dict[str, Any],
    *,
    before_remediation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    before = before_remediation if isinstance(before_remediation, dict) else result
    before_reasons = quality_reason_set(before)
    after_reasons = quality_reason_set(result)
    fields = dict_items(result.get("fields"))
    tables = dict_items(result.get("tables"))
    seals = dict_items(result.get("seals"))
    pages = dict_items(result.get("pages"))
    image_variants = dict_items(result.get("imageVariants"))
    engine_runs = dict_items(result.get("engineRuns"))
    remediation_runs = dict_items(result.get("remediationRuns"))

    field_remediation_succeeded = [
        field
        for field in fields
        if field.get("extractionMethod") == "remediation_field_crop_ocr"
        and parse_bool(field.get("remediationCandidateOnly"), False) is not True
    ]
    seal_crop_runs = [run for run in remediation_runs if "_seal_crop_" in str(run.get("variantId") or "")]
    visual_seal_crop_ocr = [
        seal
        for seal in seals
        if seal.get("sealEvidenceLevel") == "visual_plus_seal_crop_ocr"
        and parse_bool(seal.get("candidateOnly"), False) is not True
    ]
    generic_crop_seals = [seal for seal in seals if seal.get("sealEvidenceLevel") == "generic_region_seal_crop_ocr"]
    generic_candidate_only = [
        seal
        for seal in generic_crop_seals
        if parse_bool(seal.get("candidateOnly"), False) is True
        or parse_bool(seal.get("canSatisfyRequiredSeal"), False) is not True
    ]
    satisfying_seals = [seal for seal in seals if parse_bool(seal.get("canSatisfyRequiredSeal"), False) is True]
    unsafe_required_satisfying = [seal for seal in satisfying_seals if not seal_has_required_visual_source(seal)]
    table_crop_succeeded = [
        table
        for table in tables
        if "_table_crop_" in str(table.get("variantId") or table.get("selectedVariantId") or "")
        and table_cell_evidence_score(table) > 0
    ]
    cache_runs = [run for run in [*engine_runs, *remediation_runs] if "engineCacheHit" in run]
    variant_cache_items = [item for item in [*engine_runs, *image_variants] if "variantCacheHit" in item or "cacheHit" in item]
    remediation_latencies = [safe_float(run.get("durationMs")) for run in remediation_runs if safe_float(run.get("durationMs")) is not None]
    run_latencies = [
        safe_float(run.get("durationMs"))
        for run in [*engine_runs, *remediation_runs]
        if safe_float(run.get("durationMs")) is not None
    ]

    return {
        "profileId": result.get("profileId"),
        "documentType": result.get("documentType"),
        "fieldCropRemediationTriggered": bool(before_reasons.intersection(TEXT_REMEDIATION_REASONS)),
        "fieldCropRemediationSucceeded": len(field_remediation_succeeded),
        "fieldCropFalseFillRate": None,
        "sealNotFoundTriggered": "SEAL_NOT_FOUND" in before_reasons,
        "sealCropGenerated": len(seal_crop_runs),
        "visualSealCropOcrSucceeded": len(visual_seal_crop_ocr),
        "genericSealCropCandidateOnlyRate": ratio(len(generic_candidate_only), len(generic_crop_seals)),
        "requiredSealFalsePassRate": ratio(len(unsafe_required_satisfying), len(satisfying_seals)),
        "tableCellEvidenceLowTriggered": "TABLE_CELL_EVIDENCE_LOW" in before_reasons,
        "tableCropRemediationSucceeded": len(table_crop_succeeded),
        "tableCellEvidenceCoverageBefore": table_cell_evidence_coverage(before),
        "tableCellEvidenceCoverageAfter": table_cell_evidence_coverage(result),
        "pymupdfTextLayerBBoxValidRate": pymupdf_text_layer_bbox_valid_rate(result),
        "rotatedPdfDetectedCount": rotated_pdf_detected_count(pages),
        "rotatedPdfOverlayErrorRate": rotated_pdf_overlay_error_rate(result),
        "cacheHitRate": ratio(
            len([run for run in cache_runs if parse_bool(run.get("engineCacheHit"), False) is True]),
            len(cache_runs),
        ),
        "pageRenderCacheHitRate": ratio(
            len(
                [
                    item
                    for item in variant_cache_items
                    if parse_bool(item.get("variantCacheHit", item.get("cacheHit")), False) is True
                ]
            ),
            len(variant_cache_items),
        ),
        "remediationPassLatency": sum(remediation_latencies) if remediation_latencies else 0.0,
        "P95Latency": percentile(run_latencies, 0.95) if len(run_latencies) >= 2 else None,
        "qualityReasonsBefore": sorted(before_reasons),
        "qualityReasonsAfter": sorted(after_reasons),
    }


def quality_reason_set(result: dict[str, Any]) -> set[str]:
    quality = result.get("quality") if isinstance(result.get("quality"), dict) else {}
    return {str(reason) for reason in quality.get("reasons") or [] if str(reason).strip()}


def dict_items(value: Any) -> list[dict[str, Any]]:
    return [item for item in value or [] if isinstance(item, dict)]


def safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 6)


def percentile(values: list[float], percentile_value: float) -> float | None:
    clean = sorted(value for value in values if value >= 0)
    if not clean:
        return None
    index = min(max(int(round((len(clean) - 1) * percentile_value)), 0), len(clean) - 1)
    return round(clean[index], 3)


def table_cell_evidence_coverage(result: dict[str, Any]) -> float | None:
    tables = dict_items(result.get("tables"))
    if not tables:
        return None
    scores = [table_cell_evidence_score(table) for table in tables]
    return round(sum(scores) / len(scores), 6)


def pymupdf_text_layer_bbox_valid_rate(result: dict[str, Any]) -> float | None:
    candidates = [
        item
        for item in [*dict_items(result.get("fragments")), *dict_items(result.get("fields"))]
        if is_pymupdf_text_layer_item(item)
    ]
    if not candidates:
        return None
    valid = [
        item
        for item in candidates
        if item.get("coordinateSystem") == "rendered_pixels"
        and rect_from_bbox(item.get("bbox") or item.get("polygon")) is not None
        and "coordinate_transform_unmapped" not in {str(flag) for flag in item.get("qualityFlags") or []}
    ]
    return ratio(len(valid), len(candidates))


def is_pymupdf_text_layer_item(item: dict[str, Any]) -> bool:
    source = str(item.get("sourceEngine") or item.get("source") or "").lower()
    status = str(item.get("coordinateTransformStatus") or "")
    return (
        "pymupdf" in source
        or item.get("sourceCoordinateSystem") == "pdf_points"
        or status == "mapped_from_pdf_points"
    )


def rotated_pdf_detected_count(pages: list[dict[str, Any]]) -> int:
    count = 0
    for page in pages:
        rotation = safe_float(page.get("rotation") or page.get("pageRotation") or page.get("sourceRotation"))
        if rotation is not None and int(rotation) % 360 != 0:
            count += 1
    return count


def rotated_pdf_overlay_error_rate(result: dict[str, Any]) -> float | None:
    rotated_pages = {
        int(page.get("pageNo") or 0)
        for page in dict_items(result.get("pages"))
        if (safe_float(page.get("rotation") or page.get("pageRotation") or page.get("sourceRotation")) or 0) % 360 != 0
    }
    if not rotated_pages:
        return None
    candidates = [
        item
        for item in [*dict_items(result.get("fragments")), *dict_items(result.get("fields"))]
        if int(item.get("pageNo") or 0) in rotated_pages and is_pymupdf_text_layer_item(item)
    ]
    if not candidates:
        return None
    invalid = [
        item
        for item in candidates
        if rect_from_bbox(item.get("bbox") or item.get("polygon")) is None
        or "coordinate_transform_unmapped" in {str(flag) for flag in item.get("qualityFlags") or []}
    ]
    return ratio(len(invalid), len(candidates))


def seal_has_required_visual_source(seal: dict[str, Any]) -> bool:
    if seal.get("sealEvidenceLevel") in {"visual_candidate", "visual_plus_seal_crop", "visual_plus_seal_crop_ocr"}:
        return True
    target = seal.get("remediationTarget") if isinstance(seal.get("remediationTarget"), dict) else {}
    return seal_crop_has_visual_source(target) or seal_crop_has_visual_source(seal)


def engine_should_remediate(engine_name: str, reasons: set[str]) -> bool:
    if engine_name == "paddleocr_vl_1_6":
        return True
    if engine_name in {"pp_structure_v3", "opencv_table_grid_subprocess"}:
        return bool(reasons.intersection(TABLE_REMEDIATION_REASONS))
    if engine_name in {"paddle_ocr_subprocess", "paddle_ocr_v6"}:
        return bool(reasons.intersection(TEXT_REMEDIATION_REASONS | SEAL_REMEDIATION_REASONS))
    if engine_name in {"paddlex_seal_recognition", "agentdesign_seal_ocr_subprocess", "visual_seal_candidate_subprocess"}:
        return bool(reasons.intersection(SEAL_REMEDIATION_REASONS))
    return False


def has_parse_content(result: dict[str, Any]) -> bool:
    return any(result.get(key) for key in ["fragments", "fields", "tables", "seals", "layoutBlocks"])


def text_layer_content_sufficient(result: dict[str, Any]) -> bool:
    fragments = [
        item
        for item in result.get("fragments") or []
        if isinstance(item, dict)
        and str(item.get("sourceEngine") or "") == "pymupdf_text_layer"
        and str(item.get("text") or "").strip()
    ]
    if not fragments:
        return False
    try:
        min_fragments = int(os.getenv("AICHECK_QUICK_TEXT_LAYER_MIN_FRAGMENTS", "20"))
    except (TypeError, ValueError):
        min_fragments = 20
    try:
        min_chars = int(os.getenv("AICHECK_QUICK_TEXT_LAYER_MIN_CHARS", "400"))
    except (TypeError, ValueError):
        min_chars = 400
    total_chars = sum(len(str(item.get("text") or "").strip()) for item in fragments)
    return len(fragments) >= max(min_fragments, 1) or total_chars >= max(min_chars, 1)


def remediation_variants_for_reasons(
    result: dict[str, Any],
    variants: list[dict[str, Any]],
    reasons: set[str],
    *,
    profile: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    crop_variants: list[dict[str, Any]] = []
    if reasons.intersection(TEXT_REMEDIATION_REASONS):
        crop_variants.extend(
            build_crop_variants(
                field_remediation_targets(result, profile or {}),
                variants,
                target_type="field",
                purpose="field",
                padding_ratio=0.35,
                max_items=6,
                reasons=reasons,
            )
        )
    if reasons.intersection(TABLE_REMEDIATION_REASONS):
        crop_variants.extend(
            build_crop_variants(
                [
                    *sparse_table_remediation_targets(result),
                    *(result.get("tables") or []),
                    *missing_table_remediation_targets(result, variants, profile or {}, reasons=reasons),
                ],
                variants,
                target_type="table",
                purpose="table",
                padding_ratio=0.08,
                max_items=8,
                reasons=reasons,
            )
        )
    if reasons.intersection(SEAL_REMEDIATION_REASONS):
        crop_variants.extend(
            build_crop_variants(
                [
                    *(result.get("seals") or []),
                    *missing_seal_remediation_targets(result, variants, profile or {}, reasons=reasons),
                ],
                variants,
                target_type="seal",
                purpose="seal",
                padding_ratio=0.22,
                max_items=8,
                reasons=reasons,
            )
        )
    return [*crop_variants, *variants] if crop_variants else variants


def field_remediation_targets(result: dict[str, Any], profile: dict[str, Any]) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    missing_fields = [str(item) for item in ((result.get("quality") or {}).get("missingFields") or []) if str(item).strip()]
    fragments = [fragment for fragment in result.get("fragments") or [] if isinstance(fragment, dict)]
    for field_code in missing_fields:
        target = missing_field_label_target(field_code, fragments)
        if target:
            targets.append(target)
    if missing_fields:
        vl_max_items = 3 if str((profile or {}).get("profileId") or "") == "qualification_certificate_v1" else 10
        targets.extend(vl_layout_text_remediation_targets(result, profile, max_items=max(vl_max_items - len(targets), 0)))
    fields = [field for field in result.get("fields") or [] if isinstance(field, dict) and (field.get("bbox") or field.get("polygon"))]
    quality = result.get("quality") if isinstance(result.get("quality"), dict) else {}
    low_confidence = {str(item.get("fieldCode") or item.get("fieldName") or "") for item in quality.get("lowConfidenceFields") or [] if isinstance(item, dict)}
    invalid = {str(item.get("fieldCode") or item.get("fieldName") or "") for item in quality.get("invalidFields") or [] if isinstance(item, dict)}
    missing_evidence = {
        str(item.get("targetCode") or item.get("fieldCode") or item.get("targetName") or "")
        for item in quality.get("missingEvidence") or []
        if isinstance(item, dict) and item.get("targetType") == "field"
    }

    def field_priority(field: dict[str, Any]) -> tuple[int, str]:
        code = str(field.get("fieldCode") or field.get("fieldName") or "")
        if code in low_confidence:
            return (0, code)
        if code in invalid:
            return (1, code)
        if code in missing_evidence:
            return (2, code)
        if "field_value_conflict" in {str(flag) for flag in field.get("qualityFlags") or []}:
            return (3, code)
        return (9, code)

    targets.extend(sorted(fields, key=field_priority))
    return dedupe_crop_targets(targets)


def vl_layout_text_remediation_targets(
    result: dict[str, Any],
    profile: dict[str, Any],
    *,
    max_items: int,
) -> list[dict[str, Any]]:
    if max_items <= 0:
        return []
    if str((profile or {}).get("profileId") or "") != "qualification_certificate_v1":
        return []
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    if parse_bool(metadata.get("enableVlLayoutTextRemediation"), True) is False:
        return []
    candidates: list[dict[str, Any]] = []
    for block in result.get("layoutBlocks") or []:
        if not isinstance(block, dict):
            continue
        if str(block.get("sourceEngine") or "") != "paddleocr_vl_1_6":
            continue
        if str(block.get("text") or "").strip():
            continue
        if not can_use_as_crop_target(block):
            continue
        block_type = str(block.get("blockType") or block.get("type") or "").lower()
        if not any(token in block_type for token in ("text", "title", "table")):
            continue
        target = deepcopy(block)
        target["fieldId"] = str(block.get("blockId") or f"vl_layout_block_{len(candidates) + 1}")
        target["fieldCode"] = None
        target["fieldName"] = "vl_layout_text_block"
        target["ocrRuntimeOverrides"] = {
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_textline_orientation": False,
            "text_det_limit_side_len": 960,
        }
        flags = {*map(str, target.get("qualityFlags") or []), "vl_layout_text_crop"}
        target["qualityFlags"] = sorted(flags)
        candidates.append(target)
    return sorted(candidates, key=vl_layout_crop_priority)[:max_items]


def vl_layout_crop_priority(block: dict[str, Any]) -> tuple[int, float, float]:
    block_type = str(block.get("blockType") or block.get("type") or "").lower()
    bbox = rect_from_bbox(block.get("bbox") or block.get("polygon")) or [0.0, 0.0, 0.0, 0.0]
    type_priority = 0 if "title" in block_type else 1 if "text" in block_type else 2
    return (type_priority, float(bbox[1]), float(bbox[0]))


def missing_table_remediation_targets(
    result: dict[str, Any],
    variants: list[dict[str, Any]],
    profile: dict[str, Any],
    *,
    reasons: set[str] | None = None,
) -> list[dict[str, Any]]:
    quality = result.get("quality") if isinstance(result.get("quality"), dict) else {}
    reason_set = {str(item) for item in (reasons or set())} | {str(item) for item in quality.get("reasons") or []}
    if "REQUIRED_TABLE_MISSING" not in reason_set and result.get("tables"):
        return []
    targets = []
    required = [str(item) for item in (profile.get("requiredTables") or quality.get("missingTables") or []) if str(item).strip()]
    for variant in ranked_table_remediation_pages(result, variants, required)[:4]:
        dims = variant_dimensions(variant)
        if not dims:
            continue
        width, height = dims
        targets.append(
            {
                "tableId": f"missing_required_table_page_{variant_page_no(variant)}",
                "requiredTables": required,
                "pageNo": variant_page_no(variant),
                "bbox": [width * 0.04, height * 0.12, width * 0.96, height * 0.88],
                "coordinateSystem": "rendered_pixels",
                "coordinateTransformStatus": "original",
                "qualityFlags": ["missing_required_table_region_crop"],
            }
        )
    return targets


def sparse_table_remediation_targets(result: dict[str, Any]) -> list[dict[str, Any]]:
    quality = result.get("quality") if isinstance(result.get("quality"), dict) else {}
    sparse_ids = {
        str(item.get("tableId") or "")
        for item in quality.get("sparseContentTables") or []
        if isinstance(item, dict) and item.get("tableId")
    }
    if not sparse_ids:
        return []
    targets: list[dict[str, Any]] = []
    for table in result.get("tables") or []:
        if not isinstance(table, dict):
            continue
        table_id = str(table.get("tableId") or table.get("id") or "")
        if table_id not in sparse_ids:
            continue
        bbox = rect_from_bbox(table.get("bbox") or table.get("polygon"))
        if not bbox:
            continue
        for index, tile_bbox in enumerate(split_bbox_along_long_axis(bbox, max_tiles=4, overlap_ratio=0.1), start=1):
            targets.append(
                {
                    **table,
                    "tableId": f"{table_id}_sparse_tile_{index}",
                    "bbox": tile_bbox,
                    "coordinateSystem": table.get("coordinateSystem") or "rendered_pixels",
                    "qualityFlags": sorted({*map(str, table.get("qualityFlags") or []), "table_content_sparse_tile"}),
                    "ocrRuntimeOverrides": {
                        "use_doc_orientation_classify": True,
                        "use_doc_unwarping": False,
                        "use_textline_orientation": True,
                    },
                }
            )
    return targets


def split_bbox_along_long_axis(
    bbox: list[float],
    *,
    max_tiles: int,
    overlap_ratio: float,
) -> list[list[float]]:
    x0, y0, x1, y1 = [float(value) for value in bbox[:4]]
    width, height = x1 - x0, y1 - y0
    tile_count = max(1, min(int(max_tiles), 4))
    horizontal = width >= height
    length = width if horizontal else height
    if length <= 0 or tile_count == 1:
        return [[x0, y0, x1, y1]]
    tile_length = length / (tile_count - (tile_count - 1) * overlap_ratio)
    stride = tile_length * (1 - overlap_ratio)
    output = []
    for index in range(tile_count):
        start = (x0 if horizontal else y0) + index * stride
        end = min(x1 if horizontal else y1, start + tile_length)
        start = max(x0 if horizontal else y0, end - tile_length)
        output.append([start, y0, end, y1] if horizontal else [x0, start, x1, end])
    return output


def missing_seal_remediation_targets(
    result: dict[str, Any],
    variants: list[dict[str, Any]],
    profile: dict[str, Any],
    *,
    reasons: set[str] | None = None,
) -> list[dict[str, Any]]:
    quality = result.get("quality") if isinstance(result.get("quality"), dict) else {}
    reason_set = {str(item) for item in (reasons or set())} | {str(item) for item in quality.get("reasons") or []}
    required_seal = parse_bool((profile.get("sealRules") or {}).get("required"), False) is True
    if result.get("seals") and "SEAL_NOT_FOUND" not in reason_set:
        return []
    if not required_seal and "SEAL_NOT_FOUND" not in reason_set:
        return []
    originals = original_page_variants(variants)
    if not originals:
        return []
    originals_by_page = {variant_page_no(variant): variant for variant in originals}
    candidate_pages = seal_remediation_page_order(result, variants, originals)
    targets = []
    for page_no in candidate_pages:
        variant = originals_by_page.get(page_no)
        if variant is None:
            continue
        dims = variant_dimensions(variant)
        if not dims:
            continue
        width, height = dims
        for region_name, bbox in seal_region_bboxes_for_page(page_no, width, height, result, variants, candidate_pages):
            source_kind, visual_confidence, quality_flags = seal_region_source_metadata(region_name)
            targets.append(
                {
                    "sealId": f"missing_seal_{region_name}_page_{page_no}",
                    "pageNo": page_no,
                    "bbox": bbox,
                    "coordinateSystem": "rendered_pixels",
                    "coordinateTransformStatus": "original",
                    "sourceKind": source_kind,
                    "visualConfidence": visual_confidence,
                    "qualityFlags": quality_flags,
                }
            )
    return targets


SEAL_REMEDIATION_KEYWORDS = ["盖章", "签发", "批准", "单位", "日期", "审核", "经办", "负责人", "签章", "印章"]


def seal_region_source_metadata(region_name: str) -> tuple[str, float, list[str]]:
    if str(region_name or "").startswith("visual_"):
        return (
            "visual_seal_candidate",
            0.65,
            ["missing_required_seal_region_crop", "visual_candidate_only"],
        )
    return (
        "generic_signature_region",
        0.0,
        ["missing_required_seal_region_crop", "generic_seal_region_crop"],
    )


def seal_remediation_page_order(
    result: dict[str, Any],
    variants: list[dict[str, Any]],
    originals: list[dict[str, Any]],
) -> list[int]:
    original_pages = [variant_page_no(variant) for variant in originals]
    if not original_pages:
        return []
    visual_pages = {
        variant_page_no(variant)
        for variant in variants
        if isinstance(variant, dict) and str(variant.get("purpose") or "") == "seal"
    }
    for page_quality in result.get("pageQuality") or []:
        quality = page_quality.get("quality") if isinstance(page_quality, dict) else {}
        if isinstance(quality, dict) and quality.get("hasVisualSealCandidate"):
            visual_pages.add(page_no_from(page_quality))
    keyword_pages = {
        page_no_from(fragment)
        for fragment in result.get("fragments") or []
        if isinstance(fragment, dict) and any(keyword in str(fragment.get("text") or "") for keyword in SEAL_REMEDIATION_KEYWORDS)
    }
    edge_pages = [original_pages[0], original_pages[-1]]
    if len(original_pages) >= 2:
        edge_pages.append(original_pages[-2])
    ordered = [
        *sorted(visual_pages),
        *sorted(keyword_pages),
        *edge_pages,
    ]
    available = set(original_pages)
    return [page for page in dict.fromkeys(ordered) if page in available]


def seal_region_bboxes_for_page(
    page_no: int,
    width: float,
    height: float,
    result: dict[str, Any],
    variants: list[dict[str, Any]],
    candidate_pages: list[int],
) -> list[tuple[str, list[float]]]:
    visual_pages = {
        variant_page_no(variant)
        for variant in variants
        if isinstance(variant, dict) and str(variant.get("purpose") or "") == "seal"
    }
    keyword_pages = {
        page_no_from(fragment)
        for fragment in result.get("fragments") or []
        if isinstance(fragment, dict) and any(keyword in str(fragment.get("text") or "") for keyword in SEAL_REMEDIATION_KEYWORDS)
    }
    if page_no in visual_pages:
        return [
            ("visual_full", [width * 0.05, height * 0.05, width * 0.95, height * 0.95]),
            ("visual_top_right", [width * 0.48, height * 0.02, width * 0.98, height * 0.52]),
            ("visual_bottom_right", [width * 0.48, height * 0.48, width * 0.98, height * 0.98]),
        ]
    if page_no in keyword_pages:
        return [
            ("keyword_signature_band", [width * 0.20, height * 0.30, width * 0.98, height * 0.96]),
            ("keyword_right_half", [width * 0.48, height * 0.10, width * 0.98, height * 0.96]),
            ("keyword_bottom_band", [width * 0.02, height * 0.58, width * 0.98, height * 0.98]),
        ]
    return [
        ("bottom_right", [width * 0.48, height * 0.52, width * 0.98, height * 0.96]),
        ("bottom_left", [width * 0.02, height * 0.52, width * 0.52, height * 0.96]),
        ("top_right", [width * 0.48, height * 0.02, width * 0.98, height * 0.46]),
    ]


TABLE_REMEDIATION_KEYWORDS = {
    "piping_characteristic_table": ["管道特性", "管道代号", "管线号", "PIPING", "CHARACTERISTIC"],
    "weld_detection_result_table": ["焊口编号", "检测方法", "评定级别", "RT", "UT", "检测比例"],
    "material_chemical_composition_table": ["化学成分", "碳", "锰", "硅", "C", "Mn", "Si"],
    "mechanical_property_table": ["力学性能", "抗拉强度", "屈服", "延伸率"],
    "construction_record_table": ["施工记录", "施工日期", "施工内容", "检查结果"],
    "welding_record_table": ["焊接记录", "焊口编号", "焊工", "焊接日期"],
}


def ranked_table_remediation_pages(
    result: dict[str, Any],
    variants: list[dict[str, Any]],
    required_tables: list[str],
) -> list[dict[str, Any]]:
    originals = original_page_variants(variants)
    if not originals:
        return []
    table_variant_pages = {variant_page_no(variant) for variant in variants if variant.get("purpose") == "table"}
    layout_table_pages = {
        page_no_from(block)
        for block in result.get("layoutBlocks") or []
        if isinstance(block, dict) and "table" in str(block.get("blockType") or block.get("type") or "").lower()
    }
    fragments_by_page: dict[int, list[str]] = {}
    for fragment in result.get("fragments") or []:
        if isinstance(fragment, dict):
            fragments_by_page.setdefault(page_no_from(fragment), []).append(str(fragment.get("text") or ""))
    keywords = table_keywords(required_tables)
    first_page = variant_page_no(originals[0])
    last_page = variant_page_no(originals[-1])

    def rank(variant: dict[str, Any]) -> tuple[float, int]:
        page_no = variant_page_no(variant)
        text_blob = " ".join(fragments_by_page.get(page_no, []))
        score = 0.0
        if page_no in table_variant_pages:
            score += 6.0
        if page_no in layout_table_pages:
            score += 5.0
        score += min(sum(1 for keyword in keywords if keyword and keyword.lower() in text_blob.lower()), 8) * 1.25
        if page_no in {first_page, last_page}:
            score += 0.5
        return (-score, page_no)

    return sorted(originals, key=rank)


def table_keywords(required_tables: list[str]) -> list[str]:
    keywords: list[str] = []
    for required in required_tables:
        key = re.sub(r"_v\d+$", "", str(required or "").strip().lower())
        keywords.extend(TABLE_REMEDIATION_KEYWORDS.get(key, []))
    return list(dict.fromkeys([keyword for keyword in keywords if keyword]))


def dedupe_crop_targets(targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    output = []
    for target in targets:
        key = (
            target.get("fieldCode") or target.get("fieldName") or target.get("tableId") or target.get("sealId"),
            page_no_from(target),
            tuple(rect_from_bbox(target.get("bbox") or target.get("polygon")) or []),
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(target)
    return output


def original_page_variants(variants: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        variant
        for variant in variants
        if isinstance(variant, dict)
        and str(variant.get("variantId") or "").endswith("_original")
        and variant.get("path")
    ]


def dedupe_by_page(variants: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    output = []
    for variant in variants:
        page_no = variant_page_no(variant)
        if page_no in seen:
            continue
        seen.add(page_no)
        output.append(variant)
    return output


def variant_page_no(variant: dict[str, Any]) -> int:
    return int(variant.get("pageNo") or 1)


def variant_dimensions(variant: dict[str, Any]) -> tuple[float, float] | None:
    width = float(variant.get("pageWidth") or variant.get("sourcePageWidth") or 0)
    height = float(variant.get("pageHeight") or variant.get("sourcePageHeight") or 0)
    if width > 0 and height > 0:
        return width, height
    path = Path(str(variant.get("path") or ""))
    if not path.exists():
        return None
    try:
        from PIL import Image  # type: ignore

        with Image.open(str(path)) as image:
            width, height = image.size
        return float(width), float(height)
    except Exception:
        return None


FIELD_LABEL_ALIASES = {
    "report_no": ["报告编号", "报告号", "Report No", "Report No."],
    "certificate_no": ["证书编号", "质量证明书编号", "Certificate No"],
    "project_name": ["项目名称", "Project"],
    "pipe_no": ["管道代号", "管线号", "管道号", "Line No", "Pipeline No"],
    "weld_no": ["焊口编号", "焊口号", "Weld No"],
    "detection_date": ["检测日期", "Date"],
    "issue_date": ["签发日期", "出厂日期", "日期"],
    "manufacturer": ["生产厂家", "制造单位", "厂家"],
    "product_name": ["产品名称", "品名", "元件名称", "Product Name"],
    "dealer_name": ["经营单位", "供货单位", "经销单位"],
    "material_grade": ["材料牌号", "材质", "牌号"],
    "batch_no": ["炉批号", "批号", "Heat No"],
    "heat_no": ["炉号", "Heat No"],
    "quantity": ["数量", "供货数量", "Quantity"],
    "delivery_condition": ["交货状态", "供货状态", "Delivery Condition"],
    "document_form": ["文件形式", "原件/复印件", "正副本"],
    "inspection_items": ["检验项目", "试验项目", "检测项目"],
    "test_results": ["试验结果", "检验结果", "检测结果"],
    "standard_no": ["标准号", "执行标准"],
    "inspection_unit": ["检测单位", "检验单位"],
}

SEAL_CROP_TEXT_ENGINES = {"paddle_ocr_subprocess", "paddle_ocr_v6", "paddleocr_vl_1_6"}
FIELD_CODES_WITH_STRONG_VALIDATORS = {
    "report_no",
    "certificate_no",
    "record_no",
    "drawing_no",
    "welder_cert_no",
    "batch_no",
    "standard_no",
    "issue_date",
    "valid_until",
    "detection_date",
    "construction_date",
    "welding_date",
    "pipe_no",
    "weld_no",
    "design_pressure",
    "test_pressure",
    "pressure",
    "detection_method",
    "evaluation_level",
    "conclusion",
    "inspection_conclusion",
}


def missing_field_label_target(field_code: str, fragments: list[dict[str, Any]]) -> dict[str, Any] | None:
    aliases = FIELD_LABEL_ALIASES.get(field_code, [field_code])
    for fragment in fragments:
        text = str(fragment.get("text") or "")
        if not text:
            continue
        if any(alias and alias.lower() in text.lower() for alias in aliases):
            bbox = rect_from_bbox(fragment.get("bbox") or fragment.get("polygon"))
            if not bbox:
                continue
            page_width = float(fragment.get("pageWidth") or 0)
            page_height = float(fragment.get("pageHeight") or 0)
            x0, y0, x1, y1 = bbox
            width = max(x1 - x0, 80.0)
            height = max(y1 - y0, 32.0)
            crop_bbox = [
                x0,
                max(0.0, y0 - height * 0.8),
                x1 + width * 8.0,
                y1 + height * 1.8,
            ]
            if page_width > 0:
                crop_bbox[2] = min(crop_bbox[2], page_width)
            if page_height > 0:
                crop_bbox[3] = min(crop_bbox[3], page_height)
            return {
                "fieldId": field_code,
                "fieldCode": field_code,
                "bbox": crop_bbox,
                "pageNo": page_no_from(fragment),
                "coordinateSystem": fragment.get("coordinateSystem"),
                "sourceCoordinateSystem": fragment.get("sourceCoordinateSystem"),
                "coordinateTransformStatus": fragment.get("coordinateTransformStatus"),
                "qualityFlags": sorted({*map(str, fragment.get("qualityFlags") or []), "missing_field_label_crop"}),
            }
    return None


def build_crop_variants(
    items: list[Any],
    variants: list[dict[str, Any]],
    *,
    target_type: str,
    purpose: str,
    padding_ratio: float,
    max_items: int,
    reasons: set[str] | None = None,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in items:
        if len(output) >= max_items:
            break
        if not isinstance(item, dict):
            continue
        if not can_use_as_crop_target(item):
            continue
        bbox = rect_from_bbox(item.get("bbox") or item.get("polygon"))
        if bbox is None:
            continue
        page_no = page_no_from(item)
        source_variant = original_variant_for_page(variants, page_no)
        if source_variant is None:
            continue
        crop = crop_variant_image(
            Path(str(source_variant.get("path") or "")),
            bbox,
            padding_ratio=padding_ratio,
            purpose=purpose,
        )
        if crop is None:
            continue
        crop_path = Path(str(crop["path"]))
        target_id = str(
            item.get(f"{target_type}Id")
            or item.get("fieldCode")
            or item.get("fieldName")
            or item.get("tableId")
            or item.get("sealId")
            or len(output) + 1
        )
        bbox_token = short_hash({"bbox": bbox, "targetId": target_id, "purpose": purpose})
        variant_id = f"page_{page_no}_{purpose}_crop_{safe_variant_token(target_id)}_{bbox_token}"
        reason_list = sorted(str(reason) for reason in (reasons or set()) if str(reason).strip())
        variant_payload = {
                "variantId": variant_id,
                "pageNo": page_no,
                "path": str(crop_path),
                "documentPath": source_variant.get("documentPath"),
                "sourceType": source_variant.get("sourceType"),
                "coordinateSystem": "crop_pixels",
                "sourceCoordinateSystem": "rendered_pixels",
                "preprocessChain": [purpose, "crop"],
                "imageHash": file_sha256(crop_path),
                "purpose": purpose,
                "source": "remediation_crop",
                "engineScope": "crop",
                "cropSourceVariantId": source_variant.get("variantId"),
                "cropSourceTargetType": target_type,
                "cropSourceTargetId": target_id,
                "cropSourceBbox": bbox,
                "cropOffsetX": crop["cropOffsetX"],
                "cropOffsetY": crop["cropOffsetY"],
                "cropWidth": crop["cropWidth"],
                "cropHeight": crop["cropHeight"],
                "sourcePageWidth": crop["sourcePageWidth"],
                "sourcePageHeight": crop["sourcePageHeight"],
                "remediationTarget": {
                    "type": target_type,
                    "id": target_id,
                    "fieldCode": item.get("fieldCode"),
                    "fieldName": item.get("fieldName"),
                    "reason": reason_list[0] if len(reason_list) == 1 else "remediation_crop",
                    "reasons": reason_list,
                    "sourceKind": crop_target_source_kind(item, target_type),
                    "sourceVisualConfidence": item.get("visualConfidence"),
                    "sourceQualityFlags": list(item.get("qualityFlags") or []),
                    "sourceSealEvidenceLevel": item.get("sealEvidenceLevel"),
                    "sourceSealType": item.get("sealType"),
                },
                "coordinateTransformStatus": "crop_local",
        }
        if isinstance(item.get("ocrRuntimeOverrides"), dict):
            variant_payload["ocrRuntimeOverrides"] = deepcopy(item["ocrRuntimeOverrides"])
        output.append(variant_payload)
    return output


def crop_target_source_kind(item: dict[str, Any], target_type: str) -> str | None:
    if target_type != "seal":
        return None
    if item.get("sourceKind"):
        return str(item.get("sourceKind"))
    flags = {str(flag) for flag in item.get("qualityFlags") or []}
    if {"generic_seal_region_crop", "missing_required_seal_region_crop"}.intersection(flags):
        return "generic_signature_region"
    if "seal_bbox_from_ocr_fragments" in flags or item.get("sealEvidenceLevel") == "fragment_roi_text":
        return "fragment_seal_bbox"
    if (
        float(item.get("visualConfidence") or 0.0) > 0.0
        or "visual_candidate_only" in flags
        or item.get("sealEvidenceLevel") in {"visual_candidate", "visual_plus_seal_crop", "visual_plus_seal_crop_ocr"}
    ):
        return "visual_seal_candidate"
    return "generic_signature_region"


def can_use_as_crop_target(item: dict[str, Any]) -> bool:
    flags = {str(flag) for flag in item.get("qualityFlags") or []}
    if item.get("coordinateSystem") != "rendered_pixels":
        return False
    if not item.get("pageNo"):
        return False
    if {"document_coordinate_unmapped", "coordinate_transform_unmapped", "external_coordinate_unverified"}.intersection(flags):
        return False
    status = item.get("coordinateTransformStatus")
    if status and status not in {"original", "mapped", "mapped_from_crop", "mapped_from_pdf_points"}:
        return False
    return bool(rect_from_bbox(item.get("bbox") or item.get("polygon")))


def short_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()[:8]


def original_variant_for_page(variants: list[dict[str, Any]], page_no: int) -> dict[str, Any] | None:
    return next(
        (
            variant
            for variant in variants
            if int(variant.get("pageNo") or 1) == page_no
            and str(variant.get("variantId") or "").endswith("_original")
            and variant.get("path")
        ),
        None,
    )


def crop_variant_image(source_path: Path, bbox: list[float], *, padding_ratio: float, purpose: str) -> dict[str, Any] | None:
    if not source_path.exists():
        return None
    try:
        from PIL import Image  # type: ignore

        with Image.open(str(source_path)) as image:
            width, height = image.size
            x0, y0, x1, y1 = bbox
            pad_x = max((x1 - x0) * padding_ratio, 8.0)
            pad_y = max((y1 - y0) * padding_ratio, 8.0)
            crop_box = (
                max(int(x0 - pad_x), 0),
                max(int(y0 - pad_y), 0),
                min(int(x1 + pad_x), width),
                min(int(y1 + pad_y), height),
            )
            if crop_box[2] <= crop_box[0] or crop_box[3] <= crop_box[1]:
                return None
            out_dir = Path(tempfile.gettempdir()) / "aicheck-ocr-remediation-crops"
            out_dir.mkdir(parents=True, exist_ok=True)
            source_hash = file_sha256(source_path)
            key = hashlib.sha256(
                f"{source_hash}:bbox={crop_box}:purpose={purpose}:transform=crop_remediation_v1".encode()
            ).hexdigest()[:20]
            target = out_dir / f"{source_path.stem}-{key}.png"
            if not target.exists():
                image.crop(crop_box).save(target)
            return {
                "path": target,
                "cropOffsetX": crop_box[0],
                "cropOffsetY": crop_box[1],
                "cropWidth": crop_box[2] - crop_box[0],
                "cropHeight": crop_box[3] - crop_box[1],
                "sourcePageWidth": width,
                "sourcePageHeight": height,
            }
    except Exception:
        return None


def safe_variant_token(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", value).strip("_")[:80] or "target"


def file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return f"sha256:{hasher.hexdigest()}"


def call_probe_page_quality(
    source_path: Path,
    *,
    profile: dict[str, Any],
    pages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    try:
        return probe_page_quality(source_path, profile=profile, pages=pages)
    except TypeError:
        # Backward-compatible for tests and older local extensions monkeypatching this hook.
        return probe_page_quality(source_path, profile=profile)


def call_generate_image_variants(
    source_path: Path,
    *,
    profile: dict[str, Any],
    page_quality: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    options: dict[str, Any],
) -> list[dict[str, Any]]:
    try:
        return generate_image_variants(
            source_path,
            profile=profile,
            page_quality=page_quality,
            pages=pages,
            options=options,
        )
    except TypeError:
        # Backward-compatible for tests and older local extensions monkeypatching this hook.
        return generate_image_variants(source_path, profile=profile, page_quality=page_quality, options=options)


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
                "engineScope": variant.get("engineScope") or "page",
                "cacheHit": bool(variant.get("cacheHit")),
                "coordinateTransformStatus": variant.get("coordinateTransformStatus"),
                "coordinateSystem": variant.get("coordinateSystem"),
                "sourceCoordinateSystem": variant.get("sourceCoordinateSystem"),
                "cropOffsetX": variant.get("cropOffsetX"),
                "cropOffsetY": variant.get("cropOffsetY"),
                "cropWidth": variant.get("cropWidth"),
                "cropHeight": variant.get("cropHeight"),
                "sourcePageWidth": variant.get("sourcePageWidth"),
                "sourcePageHeight": variant.get("sourcePageHeight"),
                "remediationTarget": variant.get("remediationTarget"),
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


def attach_variant_metadata(
    result: dict[str, Any],
    engine_name: str,
    variant: dict[str, Any],
    *,
    document_pages: list[dict[str, Any]] | None = None,
) -> None:
    variant_id = variant.get("variantId")
    chain = variant.get("preprocessChain") or []
    engine_scope = str(variant.get("engineScope") or (result.get("metadata") or {}).get("engineScope") or "page")
    document_level = engine_scope == "document" or bool((result.get("metadata") or {}).get("documentLevel"))
    page_no = int(variant.get("pageNo") or 1) if not document_level else None
    pages_by_no = {int(page.get("pageNo") or 0): page for page in document_pages or [] if isinstance(page, dict)}
    for key in ["fragments", "fields", "tables", "seals", "layoutBlocks"]:
        for item in result.get(key) or []:
            if not isinstance(item, dict):
                continue
            if not item.get("sourceEngine"):
                item["sourceEngine"] = engine_name
            item["variantId"] = variant_id
            item["selectedVariantId"] = variant_id
            item["preprocessChain"] = chain
            item["engineScope"] = engine_scope
            if page_no is not None:
                item["pageNo"] = page_no
            else:
                item.setdefault("pageNo", int(item.get("pageNo") or 1))
            normalize_item_coordinates(item, engine_name=engine_name, variant=variant, pages_by_no=pages_by_no)
            if variant_has_unmapped_coordinates(variant, item):
                flags = {str(flag) for flag in item.get("qualityFlags") or []}
                flags.add("coordinate_transform_unmapped")
                item["qualityFlags"] = sorted(flags)
                item["coordinateTransformStatus"] = variant.get("coordinateTransformStatus")
            normalize_nested_coordinates(
                item,
                engine_name=engine_name,
                variant=variant,
                pages_by_no=pages_by_no,
                parent_page_no=int(item.get("pageNo") or 1),
                parent_coordinate_system=str(item.get("coordinateSystem") or "rendered_pixels"),
                skip_self=True,
            )
            prefix_item_identity(item, key=key, variant_id=str(variant_id or "document_original"))
    result.setdefault("fields", []).extend(fields_from_field_crop_fragments(result, variant, engine_name))
    result.setdefault("seals", []).extend(seals_from_seal_crop_fragments(result, variant, engine_name))


def normalize_item_coordinates(
    item: dict[str, Any],
    *,
    engine_name: str,
    variant: dict[str, Any],
    pages_by_no: dict[int, dict[str, Any]],
) -> None:
    page_no = int(item.get("pageNo") or 1)
    page = pages_by_no.get(page_no) or {}
    if variant_is_remediation_crop(variant) and (item.get("bbox") or item.get("polygon")):
        map_crop_item_to_page(item, variant)
        return
    if engine_name == "pymupdf_text_layer" and item.get("bbox") and page.get("renderScaleX"):
        bbox = item.get("bbox")
        if isinstance(bbox, list) and len(bbox) == 4:
            matrix = page.get("pdfTextToPixelMatrix") or page.get("pdfRenderMatrix")
            if isinstance(matrix, list) and len(matrix) >= 6:
                pixmap_x = float(page.get("pdfPixmapX") or 0.0)
                pixmap_y = float(page.get("pdfPixmapY") or 0.0)
                item["bbox"] = offset_pdf_pixmap_bbox(
                    transform_pdf_bbox(bbox, matrix),
                    pixmap_x=pixmap_x,
                    pixmap_y=pixmap_y,
                )
                item["coordinateTransform"] = {
                    "matrix": [round(float(value), 6) for value in matrix[:6]],
                    "pixmapX": round(pixmap_x, 4),
                    "pixmapY": round(pixmap_y, 4),
                }
            else:
                scale_x = float(page.get("renderScaleX") or 1.0)
                scale_y = float(page.get("renderScaleY") or scale_x)
                item["bbox"] = [
                    round(float(bbox[0]) * scale_x, 4),
                    round(float(bbox[1]) * scale_y, 4),
                    round(float(bbox[2]) * scale_x, 4),
                    round(float(bbox[3]) * scale_y, 4),
                ]
                item["coordinateTransform"] = {"scaleX": round(scale_x, 6), "scaleY": round(scale_y, 6)}
            item["sourceCoordinateSystem"] = "pdf_points"
            item["coordinateSystem"] = "rendered_pixels"
            item["coordinateTransformStatus"] = "mapped_from_pdf_points"
            return
    if (
        engine_name == "paddleocr_vl_1_6"
        and str(variant.get("engineScope") or "") == "document"
        and item.get("bbox")
        and paddleocr_vl_bbox_matches_rendered_page(item, page)
    ):
        item["bbox"] = [round(float(value), 4) for value in rect_from_bbox(item.get("bbox")) or item["bbox"]]
        item["coordinateSystem"] = "rendered_pixels"
        item["sourceCoordinateSystem"] = "paddleocr_vl_document_pixels"
        item["coordinateTransformStatus"] = "vl_document_pixels_match_rendered_page"
        flags = {str(flag) for flag in item.get("qualityFlags") or []}
        flags.discard("document_coordinate_unmapped")
        flags.discard("coordinate_transform_unmapped")
        item["qualityFlags"] = sorted(flags)
        return
    if str(variant.get("engineScope") or "") == "document" and (item.get("bbox") or item.get("polygon")):
        item["coordinateSystem"] = f"{engine_name}_document"
        if variant.get("sourceCoordinateSystem"):
            item.setdefault("sourceCoordinateSystem", variant.get("sourceCoordinateSystem"))
        flags = {str(flag) for flag in item.get("qualityFlags") or []}
        flags.add("document_coordinate_unmapped")
        item["qualityFlags"] = sorted(flags)
        return
    if not item.get("coordinateSystem"):
        item["coordinateSystem"] = variant.get("coordinateSystem")
    if variant.get("sourceCoordinateSystem") and not item.get("sourceCoordinateSystem"):
        item["sourceCoordinateSystem"] = variant.get("sourceCoordinateSystem")
    if not item.get("coordinateTransformStatus"):
        item["coordinateTransformStatus"] = variant.get("coordinateTransformStatus")


def paddleocr_vl_bbox_matches_rendered_page(item: dict[str, Any], page: dict[str, Any]) -> bool:
    bbox = rect_from_bbox(item.get("bbox") or item.get("polygon"))
    if bbox is None:
        return False
    width = safe_float(page.get("width"))
    height = safe_float(page.get("height"))
    if not width or not height:
        return False
    x0, y0, x1, y1 = bbox
    if x1 <= x0 or y1 <= y0:
        return False
    margin_x = max(width * 0.02, 8.0)
    margin_y = max(height * 0.02, 8.0)
    return -margin_x <= x0 <= width + margin_x and -margin_y <= y0 <= height + margin_y and x1 <= width + margin_x and y1 <= height + margin_y


def fields_from_field_crop_fragments(
    result: dict[str, Any],
    variant: dict[str, Any],
    engine_name: str,
) -> list[dict[str, Any]]:
    target = variant.get("remediationTarget") if isinstance(variant.get("remediationTarget"), dict) else {}
    if target.get("type") != "field":
        return []
    field_code = normalize_field_key(target.get("fieldCode") or target.get("id") or "")
    if not field_code:
        return []
    fragments = [fragment for fragment in result.get("fragments") or [] if isinstance(fragment, dict) and str(fragment.get("text") or "").strip()]
    if not fragments:
        return []
    labels = FIELD_LABEL_ALIASES.get(field_code, [field_code])
    candidates = []
    for fragment in fragments:
        raw_text = str(fragment.get("text") or "")
        value = clean_field_crop_value(raw_text, labels)
        if not value:
            continue
        valid, _ = validate_business_field_value(field_code, value)
        candidates.append((valid, float(fragment.get("confidence") or 0.0), value, fragment))
    if not candidates:
        return []
    valid_candidates = [candidate for candidate in candidates if candidate[0]]
    selected = max(valid_candidates or candidates, key=lambda item: (item[0], item[1], len(item[2])))
    valid, confidence, value, fragment = selected
    bbox = rect_from_bbox(fragment.get("bbox") or fragment.get("polygon")) or rect_from_bbox(variant.get("cropSourceBbox"))
    if not bbox:
        return []
    reason_set = {str(item) for item in target.get("reasons") or [] if str(item).strip()}
    if target.get("reason"):
        reason_set.add(str(target.get("reason")))
    source_flags = {str(flag) for flag in target.get("sourceQualityFlags") or []} | {
        str(flag) for flag in fragment.get("qualityFlags") or []
    }
    label_proximity = "missing_field_label_crop" in source_flags
    has_strong_validator = field_code in FIELD_CODES_WITH_STRONG_VALIDATORS
    formal_candidate = field_crop_candidate_is_formal(
        field_code=field_code,
        valid=valid,
        confidence=confidence,
        has_strong_validator=has_strong_validator,
        label_proximity=label_proximity,
        reasons=reason_set,
    )
    flags = {*map(str, fragment.get("qualityFlags") or []), "remediation_field_crop"}
    if not formal_candidate:
        flags.update({"remediation_field_crop_candidate", "needs_field_review"})
        if confidence < 0.78:
            flags.add("field_crop_low_confidence")
    return [
        {
            "fieldCode": field_code,
            "fieldName": str(target.get("fieldName") or field_code),
            "fieldValue": value,
            "pageNo": page_no_from(fragment) or int(variant.get("pageNo") or 1),
            "bbox": bbox,
            "coordinateSystem": "rendered_pixels",
            "sourceCoordinateSystem": fragment.get("sourceCoordinateSystem") or "crop_pixels",
            "coordinateTransform": fragment.get("coordinateTransform"),
            "coordinateTransformStatus": fragment.get("coordinateTransformStatus") or "mapped_from_crop",
            "confidence": round(confidence, 4),
            "sourceEngine": engine_name,
            "variantId": variant.get("variantId"),
            "selectedVariantId": variant.get("variantId"),
            "extractionMethod": "remediation_field_crop_ocr",
            "remediationCandidateOnly": not formal_candidate,
            "qualityFlags": sorted(flags),
            "remediationTarget": deepcopy(target),
        }
    ]


def field_crop_candidate_is_formal(
    *,
    field_code: str,
    valid: bool,
    confidence: float,
    has_strong_validator: bool,
    label_proximity: bool,
    reasons: set[str],
) -> bool:
    if "FIELD_FORMAT_INVALID" in reasons:
        return has_strong_validator and valid
    if "FIELD_VALUE_CONFLICT" in reasons:
        return False
    if "REQUIRED_FIELD_MISSING" in reasons:
        return (has_strong_validator and valid) or label_proximity or confidence >= 0.78
    if has_strong_validator:
        return valid and confidence >= 0.5
    return confidence >= 0.78


def clean_field_crop_value(text: str, labels: list[str]) -> str:
    value = str(text or "").strip()
    for label in sorted({str(label) for label in labels if str(label).strip()}, key=len, reverse=True):
        value = re.sub(re.escape(label), "", value, flags=re.IGNORECASE)
    return value.strip(" ：:：,，;；|/-")


def seals_from_seal_crop_fragments(
    result: dict[str, Any],
    variant: dict[str, Any],
    engine_name: str,
) -> list[dict[str, Any]]:
    if engine_name not in SEAL_CROP_TEXT_ENGINES:
        return []
    target = variant.get("remediationTarget") if isinstance(variant.get("remediationTarget"), dict) else {}
    if target.get("type") != "seal" or str(variant.get("purpose") or "") != "seal":
        return []
    fragments = [
        fragment
        for fragment in result.get("fragments") or []
        if isinstance(fragment, dict) and str(fragment.get("text") or "").strip()
    ]
    if not fragments:
        return []
    raw_text = " ".join(str(fragment.get("text") or "") for fragment in fragments)
    has_visual_source = seal_crop_has_visual_source(target)
    seal_type = infer_seal_type_from_text(raw_text) or str(target.get("sourceSealType") or "unknown")
    if seal_type == "unknown" and target.get("sourceSealType"):
        seal_type = str(target.get("sourceSealType"))
    evidence_fragments = seal_crop_evidence_fragments(fragments, seal_type)
    evidence_text = " ".join(str(fragment.get("text") or "") for fragment in evidence_fragments)
    text = compact_seal_crop_text(evidence_text)
    if not text:
        text = compact_seal_crop_text(raw_text)
        evidence_fragments = fragments
        evidence_text = raw_text
    if not text:
        return []
    confidence = average_confidence(evidence_fragments) or average_confidence(fragments) or 0.0
    boxes = [rect_from_bbox(fragment.get("bbox") or fragment.get("polygon")) for fragment in evidence_fragments]
    bbox = union_rectangles([box for box in boxes if box]) or rect_from_bbox(variant.get("cropSourceBbox"))
    if not bbox:
        return []
    formal = has_visual_source and confidence >= 0.65 and seal_type != "unknown"
    flags = {"seal_crop_ocr"}
    if evidence_fragments != fragments:
        flags.add("seal_crop_adjacent_text_removed")
    if confidence < 0.65:
        flags.add("seal_crop_ocr_low_confidence")
    if not has_visual_source:
        flags.add("seal_crop_ocr_without_visual_evidence")
    return [
        {
            "sealId": f"{variant.get('variantId')}_ocr_seal",
            "pageNo": int(variant.get("pageNo") or page_no_from(fragments[0])),
            "sealType": seal_type,
            "sealName": text,
            "bbox": bbox,
            "coordinateSystem": "rendered_pixels",
            "sourceCoordinateSystem": "crop_pixels",
            "coordinateTransformStatus": "mapped_from_crop",
            "ocrConfidence": round(confidence, 4),
            "visualConfidence": 0.0,
            "sourceEngine": engine_name,
            "variantId": variant.get("variantId"),
            "selectedVariantId": variant.get("variantId"),
            "sealEvidenceLevel": "visual_plus_seal_crop_ocr" if has_visual_source else "generic_region_seal_crop_ocr",
            "candidateOnly": not formal,
            "canSatisfyRequiredSeal": formal,
            "cropOcrText": " ".join(str(evidence_text or "").split())[:500],
            "cropOcrRawText": " ".join(str(raw_text or "").split())[:800],
            "cropBbox": variant.get("cropSourceBbox"),
            "cropConfidence": round(confidence, 4),
            "sealCropEvidence": {
                "variantId": variant.get("variantId"),
                "cropSourceTargetId": variant.get("cropSourceTargetId"),
                "cropBbox": variant.get("cropSourceBbox"),
                "cropOffsetX": variant.get("cropOffsetX"),
                "cropOffsetY": variant.get("cropOffsetY"),
                "cropWidth": variant.get("cropWidth"),
                "cropHeight": variant.get("cropHeight"),
                "sourceEngine": engine_name,
                "confidence": round(confidence, 4),
                "text": " ".join(str(evidence_text or "").split())[:500],
                "rawText": " ".join(str(raw_text or "").split())[:800],
            },
            "fields": seal_crop_fields_from_text(
                evidence_text,
                evidence_fragments,
                bbox,
                confidence,
                seal_type=seal_type,
                engine_name=engine_name,
                variant=variant,
            ),
            "qualityFlags": sorted(flags),
            "remediationTarget": deepcopy(target),
        }
    ]


def seal_crop_evidence_fragments(fragments: list[dict[str, Any]], seal_type: str) -> list[dict[str, Any]]:
    clean = [fragment for fragment in fragments if not seal_crop_fragment_is_adjacent_noise(fragment)]
    if not clean:
        return fragments
    return clean


def seal_crop_fragment_is_adjacent_noise(fragment: dict[str, Any]) -> bool:
    text = " ".join(str(fragment.get("text") or "").split())
    if not text:
        return True
    compact = re.sub(r"\s+", "", text)
    if re.search(r"QX\d{6,}[A-Z0-9-]+", compact, flags=re.IGNORECASE):
        return True
    if compact.isdigit() and len(compact) <= 2:
        return True
    drawing_terms = [
        "工艺图纸目录",
        "工艺设计说明书",
        "带控制点流程图",
        "设备表一览表",
        "平面布置图",
        "配管平面图",
        "管道安装材料表",
        "管道特性表",
        "油漆保温一览表",
        "综合材料表",
    ]
    if any(term in compact for term in drawing_terms) and "压力管道" not in compact:
        return True
    return False


def seal_crop_has_visual_source(target: dict[str, Any]) -> bool:
    flags = {str(flag) for flag in target.get("sourceQualityFlags") or []}
    return (
        target.get("sourceKind") == "visual_seal_candidate"
        or target.get("sourceKind") == "fragment_seal_bbox"
        or "seal_bbox_from_ocr_fragments" in flags
        or "visual_candidate_only" in flags
        or float(target.get("sourceVisualConfidence") or 0.0) > 0.0
        or target.get("sourceSealEvidenceLevel") in {"visual_candidate", "visual_plus_seal_crop", "visual_plus_seal_crop_ocr", "fragment_roi_text"}
    )


def compact_seal_crop_text(text: str) -> str:
    value = " ".join(str(text or "").split())
    value = re.sub(r"^[：:;；,，\s]+|[：:;；,，\s]+$", "", value)
    return value[:160]


def infer_seal_type_from_text(text: str) -> str:
    value = str(text or "")
    if "检测" in value or "检验" in value:
        return "inspection_testing_seal"
    if "质量" in value or "质检" in value:
        return "quality_seal"
    if "设计" in value and ("许可" in value or "压力管道" in value):
        return "design_license_seal"
    if "审图" in value or "施工图审查" in value or "出图" in value or "资质证书编号" in value:
        return "drawing_approval_seal"
    return "unknown"


def seal_crop_fields_from_text(
    text: str,
    fragments: list[dict[str, Any]],
    bbox: list[float],
    confidence: float,
    *,
    seal_type: str,
    engine_name: str,
    variant: dict[str, Any],
) -> list[dict[str, Any]]:
    spatial = {
        "pageNo": int(variant.get("pageNo") or page_no_from(fragments[0] if fragments else {})),
        "bbox": bbox,
        "coordinateSystem": "rendered_pixels",
        "sourceCoordinateSystem": "crop_pixels",
        "coordinateTransformStatus": "mapped_from_crop",
        "sourceEngine": engine_name,
        "variantId": variant.get("variantId"),
        "selectedVariantId": variant.get("variantId"),
    }
    fields = [
        {
            **spatial,
            "fieldName": "seal_text",
            "fieldCode": "seal_text",
            "fieldValue": compact_seal_crop_text(text),
            "confidence": round(confidence, 4),
            "extractionMethod": "seal_crop_ocr_field",
            "sourcePriority": "crop_ocr",
        }
    ]
    license_match = re.search(r"TS\s*[A-Z0-9-]+", text, flags=re.IGNORECASE)
    if license_match:
        fields.append(
            {
                **spatial,
                "fieldName": "license_no",
                "fieldCode": "license_no",
                "fieldValue": license_match.group(0).replace(" ", ""),
                "confidence": round(confidence, 4),
                "extractionMethod": "seal_crop_ocr_field",
                "sourcePriority": "crop_ocr",
            }
        )
    blue_certificate_match = re.search(r"\bA\s*\d{6,12}\b", text, flags=re.IGNORECASE)
    if seal_type == "drawing_approval_seal" and blue_certificate_match:
        fields.append(
            {
                **spatial,
                "fieldName": "资质证书编号",
                "fieldCode": "blue_seal_license_no",
                "fieldValue": blue_certificate_match.group(0).replace(" ", ""),
                "confidence": round(confidence, 4),
                "extractionMethod": "seal_crop_ocr_field",
                "sourcePriority": "crop_ocr",
            }
        )
    blue_expiry = extract_blue_seal_expiry(text)
    if seal_type == "drawing_approval_seal" and blue_expiry:
        fields.append(
            {
                **spatial,
                "fieldName": "蓝章有效期至",
                "fieldCode": "blue_seal_expiry",
                "fieldValue": blue_expiry,
                "confidence": round(confidence, 4),
                "extractionMethod": "seal_crop_ocr_field",
                "sourcePriority": "crop_ocr",
            }
        )
    red_date = extract_red_seal_date(text)
    if seal_type == "design_license_seal" and red_date:
        fields.append(
            {
                **spatial,
                "fieldName": "红章日期",
                "fieldCode": "red_seal_date",
                "fieldValue": red_date,
                "confidence": round(confidence, 4),
                "extractionMethod": "seal_crop_ocr_field",
                "sourcePriority": "crop_ocr",
            }
        )
    scope = next((str(fragment.get("text") or "") for fragment in fragments if "管道" in str(fragment.get("text") or "")), "")
    if scope:
        fields.append(
            {
                **spatial,
                "fieldName": "license_scope",
                "fieldCode": "license_scope",
                "fieldValue": scope,
                "confidence": round(confidence, 4),
                "extractionMethod": "seal_crop_ocr_field",
                "sourcePriority": "crop_ocr",
            }
        )
    return fields


def extract_blue_seal_expiry(text: str) -> str | None:
    patterns = [
        re.compile(r"有效期(?:限)?至\s*[:：]?\s*(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)"),
        re.compile(r"有效期(?:限)?\s*[:：]?\s*(?:至|到)\s*(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)"),
    ]
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return re.sub(r"\s+", "", match.group(1))
    return None


def extract_red_seal_date(text: str) -> str | None:
    if "有效期" in text:
        return None
    match = re.search(r"(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)", text)
    return re.sub(r"\s+", "", match.group(1)) if match else None


def union_rectangles(boxes: list[list[float]]) -> list[float] | None:
    if not boxes:
        return None
    return [
        round(min(float(box[0]) for box in boxes), 4),
        round(min(float(box[1]) for box in boxes), 4),
        round(max(float(box[2]) for box in boxes), 4),
        round(max(float(box[3]) for box in boxes), 4),
    ]


def variant_is_remediation_crop(variant: dict[str, Any]) -> bool:
    return str(variant.get("source") or "") == "remediation_crop" or str(variant.get("engineScope") or "") == "crop"


def map_crop_item_to_page(item: dict[str, Any], variant: dict[str, Any]) -> None:
    offset_x = float(variant.get("cropOffsetX") or 0.0)
    offset_y = float(variant.get("cropOffsetY") or 0.0)
    bbox = item.get("bbox")
    polygon = item.get("polygon")
    if is_numeric_rect(bbox):
        item["bbox"] = map_crop_bbox_to_page(bbox, offset_x=offset_x, offset_y=offset_y)
    elif is_polygon(bbox):
        mapped_polygon = map_crop_polygon_to_page(bbox, offset_x=offset_x, offset_y=offset_y)
        item["polygon"] = mapped_polygon
        item["bbox"] = rect_from_polygon(mapped_polygon)
    if is_polygon(polygon):
        mapped_polygon = map_crop_polygon_to_page(polygon, offset_x=offset_x, offset_y=offset_y)
        item["polygon"] = mapped_polygon
        if not is_numeric_rect(item.get("bbox")):
            item["bbox"] = rect_from_polygon(mapped_polygon)
    item["pageNo"] = int(variant.get("pageNo") or item.get("pageNo") or 1)
    item["coordinateSystem"] = "rendered_pixels"
    item["sourceCoordinateSystem"] = "crop_pixels"
    item["coordinateTransformStatus"] = "mapped_from_crop"
    item["coordinateTransform"] = {"offsetX": offset_x, "offsetY": offset_y}
    item["cropSourceVariantId"] = variant.get("cropSourceVariantId")
    item["cropSourceBbox"] = variant.get("cropSourceBbox")


def map_crop_bbox_to_page(bbox: list[Any], *, offset_x: float, offset_y: float) -> list[float]:
    x0, y0, x1, y1 = [float(value) for value in bbox[:4]]
    return [round(x0 + offset_x, 4), round(y0 + offset_y, 4), round(x1 + offset_x, 4), round(y1 + offset_y, 4)]


def is_numeric_rect(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 4
        and all(isinstance(item, (int, float)) for item in value)
    )


def is_polygon(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(
            isinstance(point, (list, tuple))
            and len(point) >= 2
            and isinstance(point[0], (int, float))
            and isinstance(point[1], (int, float))
            for point in value
        )
    )


def rect_from_polygon(polygon: list[Any]) -> list[float] | None:
    points = [(float(point[0]), float(point[1])) for point in polygon if isinstance(point, (list, tuple)) and len(point) >= 2]
    if not points:
        return None
    return [
        round(min(x for x, _ in points), 4),
        round(min(y for _, y in points), 4),
        round(max(x for x, _ in points), 4),
        round(max(y for _, y in points), 4),
    ]


def transform_pdf_bbox(bbox: list[Any], matrix: list[Any]) -> list[float]:
    x0, y0, x1, y1 = [float(value) for value in bbox[:4]]
    points = [
        transform_pdf_point(x0, y0, matrix),
        transform_pdf_point(x1, y0, matrix),
        transform_pdf_point(x1, y1, matrix),
        transform_pdf_point(x0, y1, matrix),
    ]
    return [
        round(min(point[0] for point in points), 4),
        round(min(point[1] for point in points), 4),
        round(max(point[0] for point in points), 4),
        round(max(point[1] for point in points), 4),
    ]


def offset_pdf_pixmap_bbox(bbox: list[float], *, pixmap_x: float, pixmap_y: float) -> list[float]:
    return [
        round(float(bbox[0]) - pixmap_x, 4),
        round(float(bbox[1]) - pixmap_y, 4),
        round(float(bbox[2]) - pixmap_x, 4),
        round(float(bbox[3]) - pixmap_y, 4),
    ]


def transform_pdf_point(x: float, y: float, matrix: list[Any]) -> tuple[float, float]:
    a, b, c, d, e, f = [float(value) for value in matrix[:6]]
    return a * x + c * y + e, b * x + d * y + f


def map_crop_polygon_to_page(polygon: list[Any], *, offset_x: float, offset_y: float) -> list[Any]:
    output = []
    for point in polygon:
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            try:
                output.append([round(float(point[0]) + offset_x, 4), round(float(point[1]) + offset_y, 4)])
            except (TypeError, ValueError):
                output.append(point)
        else:
            output.append(point)
    return output


def variant_has_unmapped_coordinates(variant: dict[str, Any], item: dict[str, Any]) -> bool:
    status = str(variant.get("coordinateTransformStatus") or "")
    if not status or status in {"identity", "original", "mapped", "mapped_from_crop", "mapped_from_pdf_points"}:
        return False
    item_status = str(item.get("coordinateTransformStatus") or "")
    if item_status in {"original", "mapped", "mapped_from_crop", "mapped_from_pdf_points"}:
        return False
    return True


def normalize_nested_coordinates(
    obj: Any,
    *,
    engine_name: str,
    variant: dict[str, Any],
    pages_by_no: dict[int, dict[str, Any]],
    parent_page_no: int,
    parent_coordinate_system: str,
    skip_self: bool = False,
) -> None:
    if isinstance(obj, dict):
        is_spatial = has_spatial_shape(obj)
        if not skip_self and is_spatial:
            if not obj.get("pageNo"):
                obj["pageNo"] = parent_page_no
            if not obj.get("coordinateSystem"):
                obj["coordinateSystem"] = parent_coordinate_system
            if not obj.get("sourceEngine"):
                obj["sourceEngine"] = engine_name
            if not obj.get("variantId"):
                obj["variantId"] = variant.get("variantId")
            if not obj.get("selectedVariantId"):
                obj["selectedVariantId"] = variant.get("variantId")
            normalize_item_coordinates(obj, engine_name=engine_name, variant=variant, pages_by_no=pages_by_no)
            if variant_has_unmapped_coordinates(variant, obj):
                flags = {str(flag) for flag in obj.get("qualityFlags") or []}
                flags.add("coordinate_transform_unmapped")
                obj["qualityFlags"] = sorted(flags)
                obj["coordinateTransformStatus"] = variant.get("coordinateTransformStatus")
        child_page_no = int(obj.get("pageNo") or parent_page_no)
        child_coordinate_system = str(obj.get("coordinateSystem") or parent_coordinate_system)
        for key, value in obj.items():
            if key in NON_SPATIAL_RECURSION_KEYS:
                continue
            normalize_nested_coordinates(
                value,
                engine_name=engine_name,
                variant=variant,
                pages_by_no=pages_by_no,
                parent_page_no=child_page_no,
                parent_coordinate_system=child_coordinate_system,
            )
        return
    if not isinstance(obj, list):
        return
    for item in obj:
        if isinstance(item, dict):
            normalize_nested_coordinates(
                item,
                engine_name=engine_name,
                variant=variant,
                pages_by_no=pages_by_no,
                parent_page_no=int(item.get("pageNo") or parent_page_no),
                parent_coordinate_system=str(item.get("coordinateSystem") or parent_coordinate_system),
            )


NON_SPATIAL_RECURSION_KEYS = {
    "coordinateTransform",
    "remediationTarget",
    "metadata",
    "quality",
    "diagnostics",
    "modelManifest",
    "engineRuns",
}


def has_spatial_shape(obj: dict[str, Any]) -> bool:
    return bool(obj.get("bbox") or obj.get("polygon"))


def prefix_item_identity(item: dict[str, Any], *, key: str, variant_id: str) -> None:
    page_no = int(item.get("pageNo") or 1)
    if key == "tables":
        raw_id = str(item.get("tableId") or "table")
        if not raw_id.startswith("page_") and not raw_id.startswith("document_"):
            item["tableId"] = f"page_{page_no}_{variant_id}_{raw_id}"
    elif key == "seals":
        raw_id = str(item.get("sealId") or "seal")
        if not raw_id.startswith("page_") and not raw_id.startswith("document_"):
            item["sealId"] = f"page_{page_no}_{variant_id}_{raw_id}"


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
    profile = route_profile_after_ocr(enriched, profile)
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


def route_profile_after_ocr(result: dict[str, Any], requested_profile: dict[str, Any]) -> dict[str, Any]:
    route = detect_engineering_drawing_profile(result, requested_profile)
    if route is None:
        route = detect_scan_business_document_profile(result, requested_profile)
    if route is None:
        result.setdefault("metadata", {}).setdefault(
            "requestedProfileId",
            requested_profile.get("profileId"),
        )
        return requested_profile
    detected_profile = route["profile"]
    metadata = result.setdefault("metadata", {})
    metadata["requestedProfileId"] = requested_profile.get("profileId")
    metadata["detectedProfileId"] = detected_profile.get("profileId")
    metadata["profileRouteReason"] = route["reason"]
    metadata["profileRoutingVersion"] = "ocr-profile-router-v3"
    result.setdefault("diagnostics", []).append(
        diagnostic(
            "PROFILE_ROUTED_BY_OCR_TEXT",
            "已根据 OCR 文本将资料从请求 Profile 自动切换到更匹配的专用 Profile。",
            level="info",
            requestedProfileId=requested_profile.get("profileId"),
            detectedProfileId=detected_profile.get("profileId"),
            routeReason=route["reason"],
        )
    )
    return detected_profile


def generic_profile_requested(requested_profile: dict[str, Any]) -> bool:
    requested_profile_id = str(requested_profile.get("profileId") or "")
    requested_document_type = str(requested_profile.get("documentType") or "")
    return requested_profile_id in GENERIC_PROFILE_IDS or requested_document_type in GENERIC_DOCUMENT_TYPES


def detect_engineering_drawing_profile(
    result: dict[str, Any],
    requested_profile: dict[str, Any],
) -> dict[str, Any] | None:
    requested_profile_id = str(requested_profile.get("profileId") or result.get("profileId") or "")
    requested_document_type = str(requested_profile.get("documentType") or result.get("documentType") or "")
    requested_is_generic = generic_profile_requested(requested_profile)
    if (
        requested_profile_id not in ENGINEERING_DRAWING_PROFILE_IDS
        and requested_document_type not in ENGINEERING_DRAWING_DOCUMENT_TYPES
        and not requested_is_generic
    ):
        return None
    fragments = [item for item in result.get("fragments") or [] if isinstance(item, dict)]
    joined = "\n".join(str(item.get("text") or item.get("fullText") or "") for item in fragments)
    normalized = re.sub(r"\s+", "", joined).upper()
    if not normalized:
        return None
    strong_drawing_list = "工艺图纸目录" in joined or "DRAWINGLIST" in normalized
    if strong_drawing_list:
        if requested_profile_id == "engineering_drawing_list_v1":
            return None
        return {"profile": profile_for("engineering_drawing_list_v1"), "reason": "drawing_list_title"}
    if requested_profile_id == "piping_characteristic_list_v1" and (
        "管道特性表" in joined or "PIPINGCHARACTERISTIC" in normalized
    ):
        return None
    route_specs = [
        (
            "engineering_drawing_list_v1",
            "drawing_list_title",
            ["工艺图纸目录"],
            ["DRAWINGLIST"],
        ),
        (
            "piping_characteristic_list_v1",
            "piping_characteristic_title",
            ["管道特性表"],
            ["PIPINGCHARACTERISTIC"],
        ),
        (
            "drawing_material_list_v1",
            "drawing_material_list_title",
            ["管道安装材料表", "安装材料表"],
            ["MATERIALLIST"],
        ),
        (
            "process_flow_diagram_v1",
            "process_flow_diagram_title",
            ["管道及仪表流程图", "带控制点流程图", "流程图"],
            ["PIPINGANDINSTRUMENTDIAGRAM", "P&ID", "PID"],
        ),
        (
            "strength_calculation_v1",
            "strength_calculation_title",
            ["压力管道强度计算书", "强度计算", "壁厚计算"],
            ["STRENGTHCALCULATION"],
        ),
        (
            "design_specification_v1",
            "design_specification_title",
            ["工艺设计说明书", "工艺设计说明", "设计说明"],
            ["DESIGNSPECIFICATION"],
        ),
        (
            "equipment_list_v1",
            "equipment_list_title",
            ["设备表一览表", "设备一览表", "设备表"],
            ["EQUIPMENTLIST"],
        ),
        (
            "paint_insulation_list_v1",
            "paint_insulation_list_title",
            ["油漆保温一览表", "油漆保温"],
            ["PAINTINSULATION"],
        ),
        (
            "comprehensive_material_list_v1",
            "comprehensive_material_list_title",
            ["综合材料表"],
            ["COMPREHENSIVEMATERIALLIST"],
        ),
        (
            "site_layout_drawing_v1",
            "site_layout_drawing_title",
            ["总平面图", "平面布置图", "设备布置图", "装置平面", "总图", "布置图"],
            ["SITELAYOUT", "PLOTPLAN", "LAYOUTDRAWING", "GENERALARRANGEMENT"],
        ),
    ]
    for profile_id, reason, cn_keywords, normalized_keywords in route_specs:
        if profile_id == requested_profile_id:
            continue
        if any(keyword in joined for keyword in cn_keywords) or any(keyword in normalized for keyword in normalized_keywords):
            return {"profile": profile_for(profile_id), "reason": reason}
    drawing_numbers = {match.group(0).upper() for match in DRAWING_LIST_SEQUENCE_RE.finditer(joined)}
    title_block_signal = any(token in joined for token in ["项目名称", "图纸编号", "设计阶段"]) or any(
        token in normalized for token in ["PROJECT", "DWG", "DRAWINGNO"]
    )
    table_header_signal = any(token in joined for token in ["序号", "图纸名称", "图纸编号"])
    if requested_profile_id != "engineering_drawing_list_v1" and len(drawing_numbers) >= 3 and table_header_signal:
        return {
            "profile": profile_for("engineering_drawing_list_v1"),
            "reason": "drawing_list_numbered_rows",
        }
    if requested_profile_id != "site_layout_drawing_v1" and site_layout_signal(joined, normalized):
        return {
            "profile": profile_for("site_layout_drawing_v1"),
            "reason": "site_layout_spatial_tokens",
        }
    if not title_block_signal:
        return None
    return None


def detect_scan_business_document_profile(
    result: dict[str, Any],
    requested_profile: dict[str, Any],
) -> dict[str, Any] | None:
    if not generic_profile_requested(requested_profile):
        return None
    fragments = [item for item in result.get("fragments") or [] if isinstance(item, dict)]
    joined = "\n".join(str(item.get("text") or item.get("fullText") or "") for item in fragments)
    if not joined.strip():
        return None
    normalized = normalize_route_text(joined)
    specs = [
        {
            "profileId": "quality_certificate_v1",
            "reason": "quality_certificate_text",
            "threshold": 5,
            "signals": [
                (4, ["质量证明书", "产品质量证明书", "产品质量", "质量证明", "合格证"]),
                (2, ["化学成分", "化学成份"]),
                (2, ["力学性能", "机械性能", "抗拉强度", "屈服强度"]),
                (2, ["执行标准", "标准号", "GB/T", "HG/T"]),
                (1, ["炉批号", "批号", "材质", "规格"]),
                (2, ["质检专用章", "检验合格", "检验结论"]),
            ],
            "negative": ["射线检测", "超声检测", "焊接工艺评定", "施工方案"],
        },
        {
            "profileId": "ndt_rt_report_v1",
            "reason": "ndt_rt_report_text",
            "threshold": 5,
            "signals": [
                (4, ["射线检测报告", "射线检测", "RT报告", "RADIOGRAPHIC"]),
                (2, ["底片", "评片", "像质计"]),
                (2, ["评定级别", "合格级别", "质量等级"]),
                (1, ["焊口编号", "焊口号", "检件名", "检件编号"]),
                (1, ["检测比例", "报告编号", "委托单位"]),
            ],
            "negative": ["质量证明", "产品质量", "特种设备生产许可证"],
        },
        {
            "profileId": "ndt_ut_report_v1",
            "reason": "ndt_ut_report_text",
            "threshold": 5,
            "signals": [
                (4, ["超声检测报告", "超声检测", "UT报告", "ULTRASONIC"]),
                (2, ["探头", "耦合剂", "DAC", "检测灵敏度"]),
                (2, ["评定级别", "合格级别", "质量等级"]),
                (1, ["焊口编号", "焊口号", "检件名", "检件编号"]),
                (1, ["检测比例", "报告编号", "委托单位"]),
            ],
            "negative": ["射线检测", "质量证明", "产品质量", "特种设备生产许可证"],
        },
        {
            "profileId": "qualification_certificate_v1",
            "reason": "qualification_certificate_text",
            "threshold": 5,
            "signals": [
                (4, ["特种设备生产许可证", "中华人民共和国特种设备生产许可证", "生产许可证"]),
                (2, ["许可证编号", "证书编号", "编号TS"]),
                (2, ["许可项目", "许可范围", "业务范围"]),
                (2, ["有效期至", "有效期限至", "发证机关"]),
                (1, ["压力管道元件", "压力管道安装", "压力管道设计", "制造"]),
            ],
            "negative": ["出图专用章", "射线检测", "质量证明书"],
        },
        {
            "profileId": "welding_procedure_qualification_v1",
            "reason": "welding_procedure_qualification_text",
            "threshold": 5,
            "signals": [
                (4, ["焊接工艺评定", "焊接工艺评定报告", "焊评报告", "PQR"]),
                (2, ["WPS", "焊接工艺规程", "工艺评定编号", "评定报告编号"]),
                (1, ["母材", "焊材", "厚度范围", "适用范围"]),
                (1, ["焊接方法", "试件", "评定日期", "报告日期"]),
            ],
            "negative": ["射线检测", "质量证明书"],
        },
        {
            "profileId": "welding_record_v1",
            "reason": "welding_record_text",
            "threshold": 5,
            "signals": [
                (4, ["焊接记录", "焊接施工记录", "焊口记录"]),
                (2, ["焊口编号", "焊缝编号", "焊工"]),
                (1, ["焊接日期", "焊工证号", "资格证号", "施焊人"]),
            ],
            "negative": ["焊接工艺评定", "焊接工艺评定报告", "PQR", "射线检测", "质量证明书"],
        },
        {
            "profileId": "construction_plan_v1",
            "reason": "construction_plan_text",
            "threshold": 5,
            "signals": [
                (4, ["施工组织设计", "施工方案", "专项施工方案", "管道施工方案"]),
                (2, ["施工单位", "编制单位", "承包单位"]),
                (1, ["编制依据", "施工方法", "质量保证措施", "安全技术措施"]),
                (1, ["项目名称", "工程名称", "审批", "审核", "编制"]),
            ],
            "negative": ["施工记录", "焊接工艺评定", "射线检测", "质量证明书", "特种设备生产许可证"],
        },
        {
            "profileId": "welder_certificate_v1",
            "reason": "welder_certificate_text",
            "threshold": 5,
            "signals": [
                (4, ["特种设备焊接作业人员证", "焊接作业人员证", "焊工合格证"]),
                (2, ["作业项目", "合格项目", "项目代号"]),
                (2, ["焊工档案编号", "档案编号", "身份证号"]),
                (1, ["有效期", "批准日期", "考试机构"]),
            ],
            "negative": ["焊接工艺评定", "射线检测报告"],
        },
    ]
    scored_routes = []
    for spec in specs:
        score = profile_route_score(joined, normalized, spec)
        if score >= int(spec["threshold"]):
            scored_routes.append((score, spec))
    if not scored_routes:
        return None
    scored_routes.sort(key=lambda item: item[0], reverse=True)
    best_score, best_spec = scored_routes[0]
    if len(scored_routes) > 1 and best_score == scored_routes[1][0]:
        return None
    return {
        "profile": profile_for(str(best_spec["profileId"])),
        "reason": str(best_spec["reason"]),
        "score": best_score,
    }


def normalize_route_text(value: str) -> str:
    return re.sub(r"[\s:：,，。./_-]+", "", str(value or "")).upper()


def profile_route_score(joined: str, normalized: str, spec: dict[str, Any]) -> int:
    score = 0
    for points, terms in spec.get("signals") or []:
        if any(route_term_hit(joined, normalized, term) for term in terms):
            score += int(points)
    for term in spec.get("negative") or []:
        if route_term_hit(joined, normalized, term):
            score -= 4
    return score


def route_term_hit(joined: str, normalized: str, term: str) -> bool:
    if not term:
        return False
    return term in joined or normalize_route_text(term) in normalized


def site_layout_signal(joined: str, normalized: str) -> bool:
    tank_count = len(re.findall(r"\bTK\s*\d{3,4}", joined, flags=re.IGNORECASE))
    road_or_area = any(token in joined for token in ["消防道路", "装车站", "泵区", "罐区", "防火堤", "临海路"])
    spatial_terms = any(token in joined for token in ["总平面", "布置图", "平面布置", "总图", "方位图"])
    normalized_spatial = any(token in normalized for token in ["SITELAYOUT", "PLOTPLAN", "GENERALARRANGEMENT", "LAYOUT"])
    return bool(spatial_terms or normalized_spatial or (tank_count >= 2 and road_or_area))


def detect_engineering_drawing_list_profile(
    result: dict[str, Any],
    requested_profile: dict[str, Any],
) -> dict[str, Any] | None:
    route = detect_engineering_drawing_profile(result, requested_profile)
    if route is not None and route["profile"].get("profileId") == "engineering_drawing_list_v1":
        return route
    return None


def apply_profile_postprocessing(result: dict[str, Any], profile: dict[str, Any]) -> None:
    if is_engineering_drawing_profile(result, profile):
        title_block_tables = infer_engineering_drawing_title_block_tables(result.get("fragments") or [])
        if title_block_tables:
            existing_tables = result.setdefault("tables", [])
            appended_title_blocks = []
            for table in title_block_tables:
                if should_keep_engineering_title_block_table(table, existing_tables):
                    existing_tables.append(table)
                    appended_title_blocks.append(table)
            if appended_title_blocks:
                result.setdefault("diagnostics", []).append(
                    diagnostic(
                        "ENGINEERING_DRAWING_TITLE_BLOCK_INFERRED",
                        "已根据 OCR 文本位置识别工程图纸标题栏/签审栏表格候选，避免只保留下方明细表。",
                        level="info",
                        tableIds=[table["tableId"] for table in appended_title_blocks],
                    )
                )
    if is_engineering_drawing_list_profile(result, profile):
        tag_engineering_drawing_list_tables(result)
        extract_engineering_drawing_list_fields(result, profile)
        add_profile_quality_diagnostics(result, profile)
        return

    if is_piping_characteristic_profile(result, profile):
        inferred_tables = infer_piping_tables(result.get("fragments") or [])
        aligned_tables = []
        for page_no, page_inferred_tables in group_tables_by_page(inferred_tables).items():
            grid_table = best_opencv_grid_table(result.get("tables") or [], page_no=page_no)
            if grid_table:
                aligned_tables.append(align_piping_text_table_with_grid(page_inferred_tables[0], grid_table))
        if aligned_tables:
            result.setdefault("tables", []).extend(aligned_tables)
            for aligned_table in aligned_tables:
                result.setdefault("diagnostics", []).append(
                    diagnostic(
                        "OPENCV_GRID_TABLE_ALIGNED",
                        "已用本地 OpenCV 表格网格结构对齐同页 OCR 文本行，作为 PP-StructureV3 缺失时的本地结构化表格结果。",
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
        extract_piping_fields(result, profile)
        extract_piping_requirement_fields(result)
        add_profile_quality_diagnostics(result, profile)
        return

    if is_engineering_drawing_profile(result, profile):
        tag_engineering_drawing_common_tables(result)
        extract_engineering_drawing_common_fields(result, profile)
        add_profile_quality_diagnostics(result, profile)
        return

    align_grid_tables_with_fragments(result)
    if is_quality_certificate_profile(result, profile):
        tag_quality_certificate_tables(result)
        append_quality_certificate_summary_tables(result)
        extract_quality_certificate_fields(result)
        add_profile_quality_diagnostics(result, profile)
        return
    if is_ndt_rt_report_profile(result, profile):
        tag_ndt_rt_report_tables(result)
        append_ndt_rt_report_summary_table(result)
        extract_ndt_rt_report_fields(result)
        add_profile_quality_diagnostics(result, profile)
        return
    if is_qualification_certificate_profile(result, profile):
        extract_qualification_certificate_fields(result)
        add_profile_quality_diagnostics(result, profile)
        return
    if is_construction_plan_profile(result, profile):
        extract_construction_plan_fields(result)
        add_profile_quality_diagnostics(result, profile)
        return
    if is_welding_procedure_qualification_profile(result, profile):
        tag_welding_procedure_qualification_tables(result)
        extract_welding_procedure_qualification_fields(result)
        add_profile_quality_diagnostics(result, profile)
        return
    if is_welding_record_profile(result, profile):
        tag_welding_record_tables(result)
        extract_welding_record_fields(result)
        add_profile_quality_diagnostics(result, profile)
        return
    if is_welder_certificate_profile(result, profile):
        extract_welder_certificate_fields_and_tables(result)
        add_profile_quality_diagnostics(result, profile)
        return
    if str(profile.get("profileId") or "") in R24_R34_BUSINESS_PROFILE_IDS:
        extract_r24_r34_labeled_business_fields(result, profile)
        add_profile_quality_diagnostics(result, profile)
        return


def group_tables_by_page(tables: list[Any]) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for table in tables:
        if isinstance(table, dict):
            grouped.setdefault(page_no_from(table), []).append(table)
    return grouped


def align_grid_tables_with_fragments(result: dict[str, Any]) -> None:
    tables = result.get("tables") or []
    fragments = result.get("fragments") or []
    if not isinstance(tables, list) or not isinstance(fragments, list) or not tables or not fragments:
        return

    updated_tables: list[Any] = []
    aligned_tables: list[dict[str, Any]] = []
    replaced_table_ids: list[str] = []
    for table in tables:
        if not isinstance(table, dict) or str(table.get("sourceEngine") or "") != "opencv_table_grid_subprocess":
            updated_tables.append(table)
            continue
        derived_tables = align_opencv_grid_table_with_fragments(table, fragments)
        if not derived_tables:
            updated_tables.append(table)
            continue
        if opencv_grid_table_has_cell_text(table):
            updated_tables.append(table)
        else:
            replaced_table_ids.append(str(table.get("tableId") or "opencv_grid_table"))
        updated_tables.extend(derived_tables)
        aligned_tables.extend(derived_tables)

    if not aligned_tables:
        return
    result["tables"] = updated_tables
    result.setdefault("diagnostics", []).append(
        diagnostic(
            "OPENCV_GRID_TEXT_ALIGNED",
            "已按 OpenCV 表格网格线与 OCR 文本坐标对齐单元格，替换空网格表并输出可读表格区域。",
            level="info",
            tableIds=[table["tableId"] for table in aligned_tables],
            replacedTableIds=replaced_table_ids,
        )
    )


def opencv_grid_table_has_cell_text(table: dict[str, Any]) -> bool:
    return any(
        isinstance(cell, dict) and str(cell.get("text") or "").strip()
        for cell in table.get("cells") or []
    )


def align_opencv_grid_table_with_fragments(
    grid_table: dict[str, Any],
    fragments: list[Any],
) -> list[dict[str, Any]]:
    grid_xs = numeric_grid_lines(grid_table.get("gridLineXs"))
    grid_ys = numeric_grid_lines(grid_table.get("gridLineYs"))
    if len(grid_xs) < 2 or len(grid_ys) < 2:
        return []
    page_no = page_no_from(grid_table)
    page_fragments = table_text_fragments_for_page(fragments, page_no)
    if len(page_fragments) < 6:
        return []

    cell_map: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for fragment in page_fragments:
        bbox = fragment["bbox"]
        center_x = (bbox[0] + bbox[2]) / 2
        center_y = (bbox[1] + bbox[3]) / 2
        col = grid_interval_index(grid_xs, center_x)
        row = grid_interval_index(grid_ys, center_y)
        if row is None or col is None:
            continue
        cell_map.setdefault((row, col), []).append(fragment)
    if not cell_map:
        return []

    segments = select_grid_text_segments(cell_map, grid_xs, grid_ys)
    if not segments:
        return []
    return [
        build_text_aligned_grid_table(
            grid_table,
            cell_map,
            grid_xs,
            grid_ys,
            segment,
            segment_index=index,
        )
        for index, segment in enumerate(segments, start=1)
    ]


def numeric_grid_lines(raw_lines: Any) -> list[float]:
    values: list[float] = []
    if not isinstance(raw_lines, list):
        return values
    for value in raw_lines:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if not values or all(abs(numeric - existing) > 1.0 for existing in values):
            values.append(numeric)
    return sorted(values)


def table_text_fragments_for_page(fragments: list[Any], page_no: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for fragment in fragments:
        if not isinstance(fragment, dict) or page_no_from(fragment) != page_no:
            continue
        text = str(fragment.get("text") or fragment.get("fullText") or "").strip()
        bbox = rect_from_bbox(fragment.get("bbox"))
        if not text or bbox is None:
            continue
        if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
            continue
        items.append(
            {
                "text": text,
                "bbox": bbox,
                "confidence": float(first_present(fragment, "confidence", "score", default=0.0) or 0.0),
                "sourceEngine": fragment.get("sourceEngine"),
                "fragmentId": fragment.get("fragmentId") or fragment.get("id"),
            }
        )
    return items


def grid_interval_index(lines: list[float], value: float, *, margin: float = 3.0) -> int | None:
    for index in range(len(lines) - 1):
        if lines[index] - margin <= value <= lines[index + 1] + margin:
            return index
    return None


def select_grid_text_segment(
    cell_map: dict[tuple[int, int], list[dict[str, Any]]],
    grid_xs: list[float],
    grid_ys: list[float],
) -> dict[str, Any] | None:
    segments = select_grid_text_segments(cell_map, grid_xs, grid_ys, max_segments=1)
    return segments[0] if segments else None


def select_grid_text_segments(
    cell_map: dict[tuple[int, int], list[dict[str, Any]]],
    grid_xs: list[float],
    grid_ys: list[float],
    *,
    max_segments: int = 6,
) -> list[dict[str, Any]]:
    row_stats = grid_row_stats(cell_map, grid_xs)
    candidates: list[dict[str, Any]] = []
    for row_index, stats in row_stats.items():
        distinct_cols = len(stats["cols"])
        if distinct_cols < 3 or stats["fragmentCount"] < 3:
            continue
        following_rows = following_dense_grid_rows(row_stats, row_index, distinct_cols)
        if len(following_rows) < 2:
            continue
        score = (
            distinct_cols * 100
            + min(int(stats["fragmentCount"]), 30) * 4
            + min(len(following_rows), 20) * 8
            + min(float(stats["spanX"]) / 120.0, 20.0)
            - row_index * 0.01
        )
        candidates.append(
            {
                "headerRow": row_index,
                "dataRows": following_rows,
                "score": score,
                "headerCols": set(stats["cols"]),
            }
        )
    if not candidates:
        return []

    selected_segments: list[dict[str, Any]] = []
    selected_rows: set[int] = set()
    for candidate in sorted(candidates, key=lambda item: item["score"], reverse=True):
        segment_rows = [int(candidate["headerRow"]), *[int(row) for row in candidate["dataRows"]]]
        row_set = set(segment_rows)
        if not row_set:
            continue
        if len(row_set & selected_rows) / len(row_set) > 0.35:
            continue
        used_cols = grid_segment_columns(row_stats, segment_rows, set(candidate["headerCols"]))
        if len(used_cols) < 2:
            continue
        selected_segments.append(
            {
                "headerRow": int(candidate["headerRow"]),
                "rows": segment_rows,
                "cols": used_cols,
                "score": float(candidate["score"]),
            }
        )
        selected_rows.update(row_set)
        if len(selected_segments) >= max_segments:
            break

    return sorted(
        selected_segments,
        key=lambda item: (min(item["rows"]), min(item["cols"]), -float(item["score"])),
    )


def grid_segment_columns(
    row_stats: dict[int, dict[str, Any]],
    segment_rows: list[int],
    header_cols: set[int],
) -> list[int]:
    col_counts: dict[int, int] = {}
    for row_index in segment_rows:
        for col_index in row_stats.get(row_index, {}).get("cols", set()):
            col_counts[int(col_index)] = col_counts.get(int(col_index), 0) + 1
    min_repeated_col_count = max(2, min(4, len(segment_rows) // 3))
    return sorted(
        col_index
        for col_index, count in col_counts.items()
        if col_index in header_cols or count >= min_repeated_col_count
    )


def grid_row_stats(
    cell_map: dict[tuple[int, int], list[dict[str, Any]]],
    grid_xs: list[float],
) -> dict[int, dict[str, Any]]:
    row_stats: dict[int, dict[str, Any]] = {}
    for (row_index, col_index), fragments in cell_map.items():
        stats = row_stats.setdefault(row_index, {"cols": set(), "fragmentCount": 0, "spanX": 0.0})
        stats["cols"].add(col_index)
        stats["fragmentCount"] += len(fragments)
    for stats in row_stats.values():
        cols = sorted(stats["cols"])
        if cols:
            stats["spanX"] = grid_xs[min(max(cols), len(grid_xs) - 2) + 1] - grid_xs[max(min(cols), 0)]
    return row_stats


def following_dense_grid_rows(
    row_stats: dict[int, dict[str, Any]],
    header_row: int,
    header_col_count: int,
) -> list[int]:
    dense_rows: list[int] = []
    min_cols = max(2, min(3, header_col_count // 2))
    for row_index in range(header_row + 1, max(row_stats.keys(), default=header_row) + 1):
        stats = row_stats.get(row_index)
        if not stats or len(stats["cols"]) < min_cols:
            break
        dense_rows.append(row_index)
    return dense_rows


def build_text_aligned_grid_table(
    grid_table: dict[str, Any],
    cell_map: dict[tuple[int, int], list[dict[str, Any]]],
    grid_xs: list[float],
    grid_ys: list[float],
    segment: dict[str, Any],
    *,
    segment_index: int = 1,
) -> dict[str, Any]:
    source_table_id = str(grid_table.get("tableId") or "opencv_grid_table")
    page_no = page_no_from(grid_table)
    segment_rows = [int(row) for row in segment["rows"]]
    used_cols = [int(col) for col in segment["cols"]]
    header_row = int(segment["headerRow"])
    cells: list[dict[str, Any]] = []
    normalized_rows: list[dict[str, str]] = []
    header_labels: dict[int, str] = {}

    for output_row, grid_row in enumerate(segment_rows):
        row_values: dict[str, str] = {}
        for output_col, grid_col in enumerate(used_cols):
            fragments = sorted(
                cell_map.get((grid_row, grid_col), []),
                key=lambda item: (item["bbox"][1], item["bbox"][0]),
            )
            text = join_grid_cell_fragments(fragments, is_header=grid_row == header_row)
            confidence = average_confidence([item.get("confidence") for item in fragments])
            cell_bbox = fragment_union_bbox(fragments) or [
                grid_xs[grid_col],
                grid_ys[grid_row],
                grid_xs[grid_col + 1],
                grid_ys[grid_row + 1],
            ]
            if grid_row == header_row:
                header_labels[grid_col] = normalize_grid_header_label(text) or f"列{output_col + 1}"
            elif text:
                row_values[header_labels.get(grid_col) or f"列{output_col + 1}"] = text
            cells.append(
                {
                    "cellId": f"cell_{output_row + 1}_{output_col + 1}",
                    "row": output_row,
                    "col": output_col,
                    "rowspan": 1,
                    "colspan": 1,
                    "text": text,
                    "bbox": cell_bbox,
                    "confidence": confidence,
                    "isHeader": grid_row == header_row,
                    "sourceGridRow": grid_row,
                    "sourceGridCol": grid_col,
                }
            )
        if grid_row != header_row and any(value.strip() for value in row_values.values()):
            normalized_rows.append(row_values)

    rows = len(segment_rows)
    columns = len(used_cols)
    text_cell_count = len([cell for cell in cells if str(cell.get("text") or "").strip()])
    coverage = text_cell_count / max(rows * columns, 1)
    structure_confidence = min(
        0.97,
        max(
            float(grid_table.get("structureConfidence") or 0.0),
            0.55 + coverage * 0.24 + min(max(rows - 1, 0), 12) * 0.012 + min(columns, 10) * 0.012,
        ),
    )
    return {
        "tableId": f"{source_table_id}_text_aligned_{segment_index}",
        "pageNo": page_no,
        "bbox": [
            grid_xs[min(used_cols)],
            grid_ys[min(segment_rows)],
            grid_xs[max(used_cols) + 1],
            grid_ys[max(segment_rows) + 1],
        ],
        "rows": rows,
        "columns": columns,
        "structureConfidence": round(structure_confidence, 4),
        "textCellCount": text_cell_count,
        "cellTextCoverage": round(coverage, 4),
        "cells": cells,
        "normalizedRows": normalized_rows,
        "sourceEngine": "opencv_grid_text_aligned",
        "qualityFlags": ["opencv_grid_structure", "ocr_text_aligned"],
        "gridEvidence": {
            "tableId": grid_table.get("tableId"),
            "rows": grid_table.get("rows"),
            "columns": grid_table.get("columns"),
            "gridCellCount": grid_table.get("gridCellCount"),
            "gridLineXs": grid_table.get("gridLineXs"),
            "gridLineYs": grid_table.get("gridLineYs"),
            "structureConfidence": grid_table.get("structureConfidence"),
            "selectedHeaderRow": header_row,
            "selectedRows": segment_rows,
            "selectedColumns": used_cols,
        },
    }


def join_grid_cell_fragments(fragments: list[dict[str, Any]], *, is_header: bool) -> str:
    texts = [str(item.get("text") or "").strip() for item in fragments if str(item.get("text") or "").strip()]
    if not texts:
        return ""
    separator = "\n" if is_header and len(texts) > 1 else " "
    return separator.join(texts)


def average_confidence(values: list[Any]) -> float | None:
    numbers = []
    for value in values:
        if isinstance(value, dict):
            value = value.get("confidence") if value.get("confidence") is not None else value.get("ocrConfidence")
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            numbers.append(number)
    if not numbers:
        return None
    return round(sum(numbers) / len(numbers), 4)


def fragment_union_bbox(fragments: list[dict[str, Any]]) -> list[float] | None:
    bboxes = [rect_from_bbox(item.get("bbox")) for item in fragments]
    bboxes = [bbox for bbox in bboxes if bbox is not None]
    if not bboxes:
        return None
    return [
        min(bbox[0] for bbox in bboxes),
        min(bbox[1] for bbox in bboxes),
        max(bbox[2] for bbox in bboxes),
        max(bbox[3] for bbox in bboxes),
    ]


def normalize_grid_header_label(text: Any) -> str:
    return re.sub(r"\s+", " / ", str(text or "").strip()).strip(" /")


def best_opencv_grid_table(tables: list[Any], *, page_no: int | None = None) -> dict[str, Any] | None:
    candidates = [
        table
        for table in tables
        if isinstance(table, dict) and str(table.get("sourceEngine") or "") == "opencv_table_grid_subprocess"
        and (page_no is None or page_no_from(table) == page_no)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda table: (int(table.get("gridCellCount") or 0), float(table.get("structureConfidence") or 0.0)))


def align_piping_text_table_with_grid(text_table: dict[str, Any], grid_table: dict[str, Any]) -> dict[str, Any]:
    aligned = deepcopy(text_table)
    page_no = page_no_from(aligned)
    aligned["tableId"] = f"page_{page_no}_piping_characteristic_table_1"
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
    return profile_id == "piping_characteristic_list_v1" or document_type in {
        "engineering_table_photo",
        "piping_characteristic_list",
    }


TITLE_BLOCK_KEYWORDS = {
    "职责",
    "姓名",
    "日期",
    "项目名称",
    "装置名称",
    "图纸编号",
    "设计阶段",
    "版次",
    "工艺图纸目录",
    "DRAWING LIST",
    "PROJECT",
    "DUTY",
    "NAME",
    "DATE",
    "DWG",
    "DESIGN",
    "REV",
}


def infer_engineering_drawing_title_block_tables(fragments: list[Any]) -> list[dict[str, Any]]:
    candidates = []
    for fragment in fragments:
        if not isinstance(fragment, dict):
            continue
        text = str(fragment.get("text") or fragment.get("fullText") or "").strip()
        bbox = rect_from_bbox(fragment.get("bbox"))
        if not text or bbox is None:
            continue
        candidates.append(
            {
                "text": text,
                "bbox": bbox,
                "pageNo": page_no_from(fragment),
                "confidence": float(first_present(fragment, "confidence", "score", default=0.0) or 0.0),
                "sourceEngine": fragment.get("sourceEngine"),
                "coordinateSystem": fragment.get("coordinateSystem"),
                "sourceCoordinateSystem": fragment.get("sourceCoordinateSystem"),
                "coordinateTransform": fragment.get("coordinateTransform"),
                "coordinateTransformStatus": fragment.get("coordinateTransformStatus"),
                "qualityFlags": list(fragment.get("qualityFlags") or []),
                "variantId": fragment.get("variantId"),
                "selectedVariantId": fragment.get("selectedVariantId"),
            }
        )
    tables: list[dict[str, Any]] = []
    for page_no in sorted({int(item["pageNo"]) for item in candidates}):
        page_items = [item for item in candidates if int(item["pageNo"]) == page_no]
        table = infer_engineering_drawing_title_block_for_page(page_items, page_no)
        if table:
            tables.append(table)
    return tables


def infer_engineering_drawing_title_block_for_page(items: list[dict[str, Any]], page_no: int) -> dict[str, Any] | None:
    keyword_hits = [item for item in items if title_block_keyword_hit(item["text"])]
    if len(keyword_hits) < 5:
        return None
    page_top = min(item["bbox"][1] for item in items)
    page_bottom = max(item["bbox"][3] for item in items)
    page_height = max(page_bottom - page_top, 1.0)
    median_height = sorted(max(1.0, item["bbox"][3] - item["bbox"][1]) for item in items)[len(items) // 2]
    top_band_limit = page_top + page_height * 0.45
    top_hits = [item for item in keyword_hits if item["bbox"][1] <= top_band_limit]
    if len(top_hits) < 5:
        return None
    y0 = max(page_top, min(item["bbox"][1] for item in top_hits) - median_height * 1.8)
    y1 = min(page_bottom, max(item["bbox"][3] for item in top_hits) + median_height * 1.8)
    x0 = min(item["bbox"][0] for item in top_hits)
    x1 = max(item["bbox"][2] for item in top_hits)
    band_items = [
        item
        for item in items
        if item["bbox"][1] <= y1
        and item["bbox"][3] >= y0
        and (title_block_keyword_hit(item["text"]) or text_box_overlap_ratio(item["bbox"], [x0, y0, x1, y1]) > 0)
    ]
    if len(band_items) < 8:
        return None
    x0 = min(item["bbox"][0] for item in band_items)
    y0 = min(item["bbox"][1] for item in band_items)
    x1 = max(item["bbox"][2] for item in band_items)
    y1 = max(item["bbox"][3] for item in band_items)
    evidence_source = next((item for item in band_items if item.get("coordinateSystem")), band_items[0])
    rows = group_text_items_into_rows(band_items)
    cells = []
    normalized_rows = []
    for row_index, row in enumerate(rows):
        row_texts = []
        for col_index, cell in enumerate(sorted(row, key=lambda value: value["bbox"][0])):
            row_texts.append(cell["text"])
            cells.append(
                {
                    "cellId": f"cell_{row_index + 1}_{col_index + 1}",
                    "row": row_index,
                    "col": col_index,
                    "rowspan": 1,
                    "colspan": 1,
                    "text": cell["text"],
                    "pageNo": page_no,
                    "bbox": cell["bbox"],
                    "confidence": cell["confidence"],
                    "isHeader": row_index <= 1 or title_block_keyword_hit(cell["text"]),
                    "coordinateSystem": cell.get("coordinateSystem"),
                    "sourceCoordinateSystem": cell.get("sourceCoordinateSystem"),
                    "coordinateTransform": cell.get("coordinateTransform"),
                    "coordinateTransformStatus": cell.get("coordinateTransformStatus"),
                    "qualityFlags": list(cell.get("qualityFlags") or []),
                    "variantId": cell.get("variantId"),
                    "selectedVariantId": cell.get("selectedVariantId"),
                }
            )
        if row_texts:
            normalized_rows.append({"rowText": " ".join(row_texts), "sourceRowIndex": row_index})
    return {
        "tableId": f"page_{page_no}_engineering_drawing_title_block_1",
        "pageNo": page_no,
        "bbox": [x0, y0, x1, y1],
        "coordinateSystem": evidence_source.get("coordinateSystem"),
        "sourceCoordinateSystem": evidence_source.get("sourceCoordinateSystem"),
        "coordinateTransform": evidence_source.get("coordinateTransform"),
        "coordinateTransformStatus": evidence_source.get("coordinateTransformStatus"),
        "variantId": evidence_source.get("variantId"),
        "selectedVariantId": evidence_source.get("selectedVariantId"),
        "rows": len(rows),
        "columns": max((len(row) for row in rows), default=0),
        "structureConfidence": round(min(0.92, 0.76 + min(len(top_hits), 12) * 0.012), 4),
        "cells": cells,
        "normalizedRows": normalized_rows,
        "businessSchema": "engineering_drawing_title_block_v1",
        "tableType": "engineering_drawing_title_block",
        "auxiliaryTable": True,
        "sourceEngine": "fragment_title_block_detector",
        "qualityFlags": ["title_block_region", "ocr_text_aligned"],
    }


def title_block_keyword_hit(text: Any) -> bool:
    value = str(text or "").strip()
    compact = re.sub(r"[\s:：./_-]+", "", value).upper()
    for keyword in TITLE_BLOCK_KEYWORDS:
        normalized = re.sub(r"[\s:：./_-]+", "", keyword).upper()
        if normalized and normalized in compact:
            return True
    return False


def group_text_items_into_rows(items: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    if not items:
        return []
    heights = [max(1.0, item["bbox"][3] - item["bbox"][1]) for item in items]
    tolerance = max(10.0, sorted(heights)[len(heights) // 2] * 0.75)
    rows: list[list[dict[str, Any]]] = []
    for item in sorted(items, key=lambda value: ((value["bbox"][1] + value["bbox"][3]) / 2, value["bbox"][0])):
        center_y = (item["bbox"][1] + item["bbox"][3]) / 2
        for row in rows:
            row_center = sum((cell["bbox"][1] + cell["bbox"][3]) / 2 for cell in row) / len(row)
            if abs(center_y - row_center) <= tolerance:
                row.append(item)
                break
        else:
            rows.append([item])
    return [sorted(row, key=lambda value: value["bbox"][0]) for row in rows]


def tables_spatially_overlap(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if page_no_from(left) != page_no_from(right):
        return False
    left_box = rect_from_bbox(left.get("bbox") or left.get("polygon"))
    right_box = rect_from_bbox(right.get("bbox") or right.get("polygon"))
    if left_box is None or right_box is None:
        return False
    return max(text_box_overlap_ratio(left_box, right_box), text_box_overlap_ratio(right_box, left_box)) >= 0.72


def should_keep_engineering_title_block_table(candidate: dict[str, Any], existing_tables: list[Any]) -> bool:
    candidate_box = rect_from_bbox(candidate.get("bbox") or candidate.get("polygon"))
    if candidate_box is None:
        return False
    for existing in existing_tables:
        if not isinstance(existing, dict) or page_no_from(existing) != page_no_from(candidate):
            continue
        existing_schema = str(existing.get("businessSchema") or existing.get("tableType") or "")
        if existing_schema == "engineering_drawing_title_block_v1" and tables_spatially_overlap(candidate, existing):
            return False
        existing_box = rect_from_bbox(existing.get("bbox") or existing.get("polygon"))
        if existing_box is None:
            continue
        if existing.get("sourceEngine") == candidate.get("sourceEngine") and candidate_box == existing_box:
            return False
    return True


def text_box_overlap_ratio(left: list[float], right: list[float]) -> float:
    x0 = max(float(left[0]), float(right[0]))
    y0 = max(float(left[1]), float(right[1]))
    x1 = min(float(left[2]), float(right[2]))
    y1 = min(float(left[3]), float(right[3]))
    if x1 <= x0 or y1 <= y0:
        return 0.0
    intersection = (x1 - x0) * (y1 - y0)
    left_area = max((float(left[2]) - float(left[0])) * (float(left[3]) - float(left[1])), 1.0)
    return intersection / left_area


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
        if len(ordered) >= 4 and span >= 400 or table_rows and (PIPE_CODE_RE.search(row_text) or len(ordered) >= 3):
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
            "tableId": f"page_{page_no}_piping_characteristic_table_1",
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


def extract_piping_fields(result: dict[str, Any], profile: dict[str, Any] | None = None) -> None:
    fragments = [item for item in result.get("fragments") or [] if isinstance(item, dict)]
    text_items = [(str(item.get("text") or "").strip(), item) for item in fragments if str(item.get("text") or "").strip()]
    joined = "\n".join(text for text, _ in text_items)
    add_field_if_missing(
        result,
        "document_title",
        "文件标题",
        find_text_fragment(text_items, ["管道特性表", "PIPING CHARACTERISTIC LIST"]),
    )
    organization_aliases = [str(item) for item in ((profile or {}).get("organizationAliases") or []) if str(item).strip()]
    if organization_aliases:
        add_field_if_missing(result, "company_name", "公司名称", find_text_fragment(text_items, organization_aliases))
    else:
        add_field_if_missing(result, "company_name", "公司名称", find_organization_fragment(text_items))
    project_fragment = find_project_fragment(text_items)
    add_field_if_missing(result, "project_name", "项目名称", project_fragment)
    add_field_if_missing(result, "drawing_no", "图纸编号", drawing_no_candidate(text_items))
    phase_match = DESIGN_PHASE_RE.search(joined)
    if phase_match:
        add_field_if_missing(result, "design_phase", "设计阶段", match_to_fragment(text_items, phase_match.group(0)))
    pipe_values = []
    pipe_bbox = None
    pipe_fragment = None
    for text, fragment in text_items:
        for match in PIPE_CODE_RE.finditer(text):
            value = match.group(0).upper()
            if value not in pipe_values:
                pipe_values.append(value)
                if pipe_bbox is None:
                    pipe_bbox = rect_from_bbox(fragment.get("bbox"))
                    pipe_fragment = fragment
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
        fragment_evidence = {
            "bbox": pipe_bbox,
            "pageNo": page_no_from(pipe_fragment or {}),
            "confidence": 0.74 if pipe_bbox else 0.52,
            "sourceEngine": "profile_regex",
        }
        if isinstance(pipe_fragment, dict):
            fragment_evidence.update(
                {
                    "coordinateSystem": pipe_fragment.get("coordinateSystem"),
                    "sourceCoordinateSystem": pipe_fragment.get("sourceCoordinateSystem"),
                    "coordinateTransformStatus": pipe_fragment.get("coordinateTransformStatus"),
                    "qualityFlags": list(pipe_fragment.get("qualityFlags") or []),
                    "variantId": pipe_fragment.get("variantId"),
                    "selectedVariantId": pipe_fragment.get("selectedVariantId"),
                }
            )
        add_field_if_missing(
            result,
            "pipe_no",
            "管道代号",
            {
                "text": ",".join(pipe_values[:20]),
                "fragment": fragment_evidence,
            },
        )


def extract_piping_requirement_fields(result: dict[str, Any]) -> None:
    fragments = [item for item in result.get("fragments") or [] if isinstance(item, dict)]
    text_items = [(str(item.get("text") or "").strip(), item) for item in fragments if str(item.get("text") or "").strip()]
    joined = "\n".join(text for text, _ in text_items)
    row_values = collect_piping_requirement_values(result)

    requirement_specs = [
        (
            "pressure_pipe_level",
            "压力管道级别",
            ["pressureLevel"],
            re.compile(r"\bGC\s*[123]\b", re.IGNORECASE),
            lambda value: re.sub(r"\s+", "", value).upper(),
        ),
        (
            "weld_detection_method",
            "焊缝检测方法",
            ["weldDetectionMethod"],
            re.compile(r"\b(?:RT|UT|MT|PT)\b", re.IGNORECASE),
            lambda value: value.upper(),
        ),
        (
            "weld_detection_ratio",
            "焊缝检测比例",
            ["weldDetectionScale"],
            re.compile(r"\b\d{1,3}\s*%\b"),
            lambda value: re.sub(r"\s+", "", value),
        ),
        (
            "weld_acceptance_level",
            "焊缝合格级别",
            ["eligibleLevel"],
            re.compile(r"\b(?:I|II|III|IV|Ⅰ|Ⅱ|Ⅲ|Ⅳ)\b", re.IGNORECASE),
            normalize_roman_level,
        ),
        (
            "weld_tech_level",
            "焊缝检测技术等级",
            ["ranking"],
            re.compile(r"\b(?:A|B|C|AB)\b", re.IGNORECASE),
            lambda value: value.upper(),
        ),
        (
            "strength_test_medium",
            "强度试验介质",
            ["strengthTestMedium"],
            re.compile(r"(?:强度试验|强度).*?(水|空气)", re.DOTALL),
            lambda value: value,
        ),
        (
            "strength_test_pressure",
            "强度试验压力",
            ["strengthTestPressure"],
            re.compile(r"(?:强度试验|强度).*?(\d+(?:\.\d+)?)\s*MPA?", re.IGNORECASE | re.DOTALL),
            lambda value: value,
        ),
        (
            "tightness_test_medium",
            "严密性试验介质",
            ["tightnessTestMedium"],
            re.compile(r"(?:严密性试验|严密).*?(水|空气)", re.DOTALL),
            lambda value: value,
        ),
        (
            "tightness_test_pressure",
            "严密性试验压力",
            ["tightnessTestPressure"],
            re.compile(r"(?:严密性试验|严密).*?(\d+(?:\.\d+)?)\s*MPA?", re.IGNORECASE | re.DOTALL),
            lambda value: value,
        ),
    ]

    for field_code, field_name, row_keys, pattern, normalizer in requirement_specs:
        value = first_row_requirement_value(row_values, row_keys)
        candidate = None
        row_candidate = piping_detection_row_candidate(text_items, field_code)
        if row_candidate is not None:
            candidate = row_candidate
        if value:
            normalized_value = normalizer(str(value))
            candidate = match_to_fragment(text_items, str(value)) or match_to_fragment(text_items, normalized_value)
            if candidate:
                candidate["text"] = normalized_value
        if candidate is None:
            match = pattern.search(joined)
            if match:
                raw_value = match.group(1) if match.lastindex else match.group(0)
                normalized_value = normalizer(raw_value)
                candidate = match_to_fragment(text_items, raw_value) or match_to_fragment(text_items, normalized_value)
                if candidate:
                    candidate["text"] = normalized_value
        add_field_if_missing(result, field_code, field_name, candidate)


def collect_piping_requirement_values(result: dict[str, Any]) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for table in result.get("tables") or []:
        if not isinstance(table, dict):
            continue
        for row in table.get("businessRows") or table.get("normalizedRows") or []:
            if isinstance(row, dict):
                values.append(row)
    return values


def first_row_requirement_value(rows: list[dict[str, Any]], keys: list[str]) -> str | None:
    for row in rows:
        for key in keys:
            value = str(row.get(key) or "").strip()
            if value:
                return value
    return None


def piping_detection_row_candidate(text_items: list[tuple[str, dict[str, Any]]], field_code: str) -> dict[str, Any] | None:
    rows = ocr_rows_by_method_fragment(text_items)
    for row in rows:
        method_text, method_fragment = row["method"]
        if field_code == "weld_detection_method":
            return {"text": method_text.upper(), "fragment": method_fragment}
        right_items = row["rightItems"]
        if field_code == "weld_detection_ratio":
            match = first_row_text_candidate(right_items, re.compile(r"^\d{1,3}\s*[％%]$"))
            if match:
                text, fragment = match
                return {"text": text.replace("％", "%").replace(" ", ""), "fragment": fragment}
        if field_code == "weld_acceptance_level":
            match = first_row_text_candidate(right_items, re.compile(r"^(?:I|II|III|IV|Ⅰ|Ⅱ|Ⅲ|Ⅳ)$", re.IGNORECASE))
            if match:
                text, fragment = match
                return {"text": normalize_roman_level(text), "fragment": fragment}
        if field_code == "weld_tech_level":
            match = first_row_text_candidate(right_items, re.compile(r"^(?:AB|A|B|C)$", re.IGNORECASE), prefer_longest=True)
            if match:
                text, fragment = match
                return {"text": text.upper(), "fragment": fragment}
    return None


def ocr_rows_by_method_fragment(text_items: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    rows = []
    indexed = []
    for text, fragment in text_items:
        bbox = rect_from_bbox(fragment.get("bbox"))
        if not bbox:
            continue
        indexed.append((text.strip(), fragment, bbox))
    for text, fragment, bbox in indexed:
        upper = text.upper().strip()
        if upper not in {"RT", "UT", "MT", "PT"}:
            continue
        x0, y0, x1, y1 = bbox
        center_y = (y0 + y1) / 2
        tolerance = max((y1 - y0) * 1.5, 18.0)
        right_items = []
        for other_text, other_fragment, other_bbox in indexed:
            ox0, oy0, ox1, oy1 = other_bbox
            other_center_y = (oy0 + oy1) / 2
            if other_fragment is fragment:
                continue
            if ox0 < x0 - 5:
                continue
            if abs(other_center_y - center_y) > tolerance:
                continue
            right_items.append((other_text, other_fragment, other_bbox))
        right_items.sort(key=lambda item: (item[2][0], item[2][1]))
        rows.append({"method": (upper, fragment), "rightItems": [(text, fragment) for text, fragment, _ in right_items]})
    return rows


def first_row_text_candidate(
    items: list[tuple[str, dict[str, Any]]],
    pattern: re.Pattern[str],
    *,
    prefer_longest: bool = False,
) -> tuple[str, dict[str, Any]] | None:
    matches = [(text.strip(), fragment) for text, fragment in items if pattern.fullmatch(text.strip())]
    if not matches:
        return None
    if prefer_longest:
        matches.sort(key=lambda item: len(item[0]), reverse=True)
    return matches[0]


def normalize_roman_level(value: str) -> str:
    normalized = str(value or "").upper()
    return normalized.replace("Ⅰ", "I").replace("Ⅱ", "II").replace("Ⅲ", "III").replace("Ⅳ", "IV")


def is_engineering_drawing_profile(result: dict[str, Any], profile: dict[str, Any]) -> bool:
    profile_id = str(profile.get("profileId") or result.get("profileId") or "")
    document_type = str(profile.get("documentType") or result.get("documentType") or "")
    return profile_id in ENGINEERING_DRAWING_PROFILE_IDS or document_type in ENGINEERING_DRAWING_DOCUMENT_TYPES


def is_engineering_drawing_list_profile(result: dict[str, Any], profile: dict[str, Any]) -> bool:
    profile_id = str(profile.get("profileId") or result.get("profileId") or "")
    document_type = str(profile.get("documentType") or result.get("documentType") or "")
    return profile_id in {"engineering_drawing_list_v1", "engineering_drawing_list"} or document_type == "engineering_drawing_list"


def extract_engineering_drawing_common_fields(result: dict[str, Any], profile: dict[str, Any] | None = None) -> None:
    fragments = [item for item in result.get("fragments") or [] if isinstance(item, dict)]
    text_items = [(str(item.get("text") or "").strip(), item) for item in fragments if str(item.get("text") or "").strip()]
    joined = "\n".join(text for text, _ in text_items)
    add_field_if_missing(result, "document_title", "文件标题", find_engineering_document_title_fragment(text_items, profile))
    organization_aliases = [str(item) for item in ((profile or {}).get("organizationAliases") or []) if str(item).strip()]
    if organization_aliases:
        add_field_if_missing(result, "company_name", "公司名称", find_text_fragment(text_items, organization_aliases))
    else:
        add_field_if_missing(result, "company_name", "公司名称", find_organization_fragment(text_items))
    add_field_if_missing(result, "project_name", "项目名称", find_project_fragment(text_items))
    add_field_if_missing(result, "drawing_no", "图纸编号", drawing_no_candidate(text_items))
    phase_match = DESIGN_PHASE_RE.search(joined)
    if phase_match:
        add_field_if_missing(result, "design_phase", "设计阶段", match_to_fragment(text_items, phase_match.group(0)))


def find_engineering_document_title_fragment(
    text_items: list[tuple[str, dict[str, Any]]],
    profile: dict[str, Any] | None,
) -> dict[str, Any] | None:
    profile_id = str((profile or {}).get("profileId") or "")
    keywords_by_profile = {
        "drawing_material_list_v1": ["管道安装材料表", "安装材料表", "MATERIAL LIST"],
        "process_flow_diagram_v1": ["管道及仪表流程图", "带控制点流程图", "流程图", "P&ID", "PID"],
        "strength_calculation_v1": ["压力管道强度计算书", "强度计算", "壁厚计算"],
        "design_specification_v1": ["工艺设计说明书", "工艺设计说明", "设计说明", "DESIGN SPECIFICATION"],
        "equipment_list_v1": ["设备表一览表", "设备一览表", "设备表", "EQUIPMENT LIST"],
        "paint_insulation_list_v1": ["油漆保温一览表", "油漆保温"],
        "comprehensive_material_list_v1": ["综合材料表", "COMPREHENSIVE MATERIAL LIST"],
        "site_layout_drawing_v1": ["总平面图", "平面布置图", "设备布置图", "布置图", "总图"],
    }
    direct = find_text_fragment(text_items, keywords_by_profile.get(profile_id, []))
    if direct:
        return direct
    generic_keywords = [
        "管道安装材料表",
        "管道及仪表流程图",
        "带控制点流程图",
        "压力管道强度计算书",
        "工艺设计说明书",
        "设备表一览表",
        "油漆保温一览表",
        "综合材料表",
        "总平面图",
        "平面布置图",
        "设备布置图",
    ]
    return find_text_fragment(text_items, generic_keywords)


def tag_engineering_drawing_common_tables(result: dict[str, Any]) -> None:
    for table in result.get("tables") or []:
        if not isinstance(table, dict):
            continue
        text = table_text(table)
        compact = re.sub(r"\s+", "", text).upper()
        if not (
            ("项目名称" in text and ("图纸编号" in text or "设计阶段" in text))
            or ("PROJECT" in compact and ("DWG" in compact or "DRAWING" in compact))
        ):
            continue
        schemas = set(str(item) for item in table.get("businessSchemas") or [] if item)
        schemas.add("engineering_drawing_title_block_v1")
        table["businessSchemas"] = sorted(schemas)
        table.setdefault("businessSchema", "engineering_drawing_title_block_v1")
        flags = {str(flag) for flag in table.get("qualityFlags") or []}
        flags.add("engineering_drawing_title_block_schema_match")
        table["qualityFlags"] = sorted(flags)


def extract_engineering_drawing_list_fields(result: dict[str, Any], profile: dict[str, Any] | None = None) -> None:
    fragments = [item for item in result.get("fragments") or [] if isinstance(item, dict)]
    text_items = [(str(item.get("text") or "").strip(), item) for item in fragments if str(item.get("text") or "").strip()]
    joined = "\n".join(text for text, _ in text_items)
    add_field_if_missing(
        result,
        "document_title",
        "文件标题",
        find_text_fragment(text_items, ["工艺图纸目录", "DRAWING LIST"]),
    )
    organization_aliases = [str(item) for item in ((profile or {}).get("organizationAliases") or []) if str(item).strip()]
    if organization_aliases:
        add_field_if_missing(result, "company_name", "公司名称", find_text_fragment(text_items, organization_aliases))
    else:
        add_field_if_missing(result, "company_name", "公司名称", find_organization_fragment(text_items))
    add_field_if_missing(result, "project_name", "项目名称", find_project_fragment(text_items))
    add_field_if_missing(result, "drawing_no", "图纸编号", drawing_no_candidate(text_items))
    phase_match = DESIGN_PHASE_RE.search(joined)
    if phase_match:
        add_field_if_missing(result, "design_phase", "设计阶段", match_to_fragment(text_items, phase_match.group(0)))
    add_field_if_missing(result, "total_sheets", "总张数", find_total_sheets_fragment(text_items))
    append_engineering_drawing_list_rows(result, text_items)


def find_total_sheets_fragment(text_items: list[tuple[str, dict[str, Any]]]) -> dict[str, Any] | None:
    patterns = [
        re.compile(r"共\s*(\d{1,4})\s*张"),
        re.compile(r"总\s*张\s*数\s*[:：]?\s*(\d{1,4})"),
        re.compile(r"TOTAL\s*SHEETS?\s*[:：]?\s*(\d{1,4})", flags=re.IGNORECASE),
        re.compile(r"SHEET\s+\d{1,4}\s+OF\s+(\d{1,4})", flags=re.IGNORECASE),
    ]
    for text, fragment in text_items:
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                return {"text": match.group(1), "fragment": fragment}
    return None


def tag_engineering_drawing_list_tables(result: dict[str, Any]) -> None:
    for table in result.get("tables") or []:
        if not isinstance(table, dict):
            continue
        text = table_text(table)
        compact = re.sub(r"\s+", "", text).upper()
        if not (
            "工艺图纸目录" in text
            or "DRAWINGLIST" in compact
            or ("图纸编号" in text and "项目名称" in text)
            or ("DWG" in compact and "PROJECT" in compact)
        ):
            continue
        schemas = set(str(item) for item in table.get("businessSchemas") or [] if item)
        schemas.add("engineering_drawing_title_block_v1")
        table["businessSchemas"] = sorted(schemas)
        table.setdefault("businessSchema", "engineering_drawing_title_block_v1")
        flags = {str(flag) for flag in table.get("qualityFlags") or []}
        flags.add("engineering_drawing_list_schema_match")
        table["qualityFlags"] = sorted(flags)


def append_engineering_drawing_list_rows(result: dict[str, Any], text_items: list[tuple[str, dict[str, Any]]]) -> None:
    rows = infer_engineering_drawing_list_rows(text_items)
    if not rows:
        return
    result.setdefault("metadata", {})["drawingListRows"] = rows
    append_structured_field_if_missing(
        result,
        "drawing_list_rows",
        "图纸目录行",
        rows,
        row_evidence_summary(rows),
    )
    table = drawing_list_rows_table(rows)
    if table and not any(
        isinstance(item, dict) and item.get("tableId") == table["tableId"]
        for item in result.get("tables") or []
    ):
        result.setdefault("tables", []).append(table)


def infer_engineering_drawing_list_rows(text_items: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for text, fragment in text_items:
        bbox = rect_from_bbox(fragment.get("bbox") or fragment.get("polygon"))
        if not text or bbox is None:
            continue
        candidates.append(
            {
                "text": text,
                "fragment": fragment,
                "bbox": bbox,
                "centerY": (bbox[1] + bbox[3]) / 2,
                "centerX": (bbox[0] + bbox[2]) / 2,
            }
        )
    drawing_items = []
    for item in candidates:
        match = DRAWING_LIST_SEQUENCE_RE.search(item["text"])
        if match:
            drawing_items.append({**item, "drawingNo": match.group(0)})
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in sorted(drawing_items, key=lambda value: (value["bbox"][1], value["bbox"][0])):
        drawing_no = item["drawingNo"]
        if drawing_no in seen:
            continue
        seen.add(drawing_no)
        row_items = same_text_row_items(candidates, item)
        name_item = drawing_name_item_for_row(row_items, item)
        seq_item = drawing_sequence_item_for_row(row_items, item)
        evidence_items = [candidate for candidate in [seq_item, name_item, item] if candidate]
        bbox = fragment_union_bbox([candidate["fragment"] for candidate in evidence_items])
        rows.append(
            {
                "rowIndex": len(rows) + 1,
                "pageNo": page_no_from(item["fragment"]),
                "sequenceNo": seq_item["text"] if seq_item else None,
                "drawingName": name_item["text"] if name_item else None,
                "drawingNo": drawing_no,
                "bbox": bbox,
                "coordinateSystem": item["fragment"].get("coordinateSystem"),
                "coordinateTransformStatus": item["fragment"].get("coordinateTransformStatus"),
                "confidence": round(
                    sum(safe_float(candidate["fragment"].get("confidence")) for candidate in evidence_items)
                    / max(len(evidence_items), 1),
                    4,
                ),
                "evidence": [
                    {
                        "text": candidate["text"],
                        "bbox": rect_from_bbox(candidate["fragment"].get("bbox") or candidate["fragment"].get("polygon")),
                        "sourceEngine": candidate["fragment"].get("sourceEngine"),
                        "confidence": candidate["fragment"].get("confidence"),
                    }
                    for candidate in evidence_items
                ],
            }
        )
    return rows


def same_text_row_items(items: list[dict[str, Any]], anchor: dict[str, Any]) -> list[dict[str, Any]]:
    anchor_height = max(anchor["bbox"][3] - anchor["bbox"][1], 1.0)
    tolerance = max(anchor_height * 0.85, 12.0)
    return [
        item
        for item in items
        if page_no_from(item["fragment"]) == page_no_from(anchor["fragment"])
        and abs(float(item["centerY"]) - float(anchor["centerY"])) <= tolerance
    ]


def drawing_name_item_for_row(row_items: list[dict[str, Any]], drawing_item: dict[str, Any]) -> dict[str, Any] | None:
    left_items = [
        item
        for item in row_items
        if item["bbox"][2] <= drawing_item["bbox"][0] + 8
        and item["text"] != drawing_item["text"]
        and not re.fullmatch(r"\d{1,4}", item["text"].strip())
        and not DRAWING_LIST_SEQUENCE_RE.search(item["text"])
        and not any(token in item["text"].upper() for token in ["DRAWING", "DWG", "PROJECT", "REV"])
    ]
    if not left_items:
        return None
    return max(left_items, key=lambda item: (len(item["text"]), item["bbox"][0]))


def drawing_sequence_item_for_row(row_items: list[dict[str, Any]], drawing_item: dict[str, Any]) -> dict[str, Any] | None:
    seq_items = [
        item
        for item in row_items
        if item["bbox"][2] <= drawing_item["bbox"][0] + 8
        and re.fullmatch(r"\d{1,4}", item["text"].strip())
    ]
    if not seq_items:
        return None
    return max(seq_items, key=lambda item: item["bbox"][0])


def row_evidence_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    bboxes = [row.get("bbox") for row in rows if isinstance(row.get("bbox"), list)]
    bbox = union_rectangles([box for box in bboxes if box]) if bboxes else None
    confidence = sum(float(row.get("confidence") or 0.0) for row in rows) / max(len(rows), 1)
    first = rows[0] if rows else {}
    return {
        "bbox": bbox,
        "pageNo": first.get("pageNo") or 1,
        "coordinateSystem": first.get("coordinateSystem"),
        "coordinateTransformStatus": first.get("coordinateTransformStatus"),
        "confidence": round(confidence, 4),
        "sourceEngine": "fragment_drawing_list_row_detector",
    }


def append_structured_field_if_missing(
    result: dict[str, Any],
    field_code: str,
    field_name: str,
    value: Any,
    evidence: dict[str, Any],
) -> None:
    fields = result.setdefault("fields", [])
    if any(isinstance(item, dict) and item.get("fieldCode") == field_code for item in fields):
        return
    fields.append(
        {
            "fieldCode": field_code,
            "fieldName": field_name,
            "fieldValue": value,
            "pageNo": evidence.get("pageNo"),
            "bbox": evidence.get("bbox"),
            "coordinateSystem": evidence.get("coordinateSystem"),
            "coordinateTransformStatus": evidence.get("coordinateTransformStatus"),
            "confidence": evidence.get("confidence"),
            "extractionMethod": "profile_structured_rows",
            "sourceEngine": evidence.get("sourceEngine"),
        }
    )


def drawing_list_rows_table(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    bbox = union_rectangles([row["bbox"] for row in rows if isinstance(row.get("bbox"), list)])
    if not bbox:
        return None
    page_no = int(rows[0].get("pageNo") or 1)
    cells = []
    normalized_rows = []
    for index, row in enumerate(rows, start=1):
        normalized_rows.append(
            {
                "序号": str(row.get("sequenceNo") or index),
                "名称": str(row.get("drawingName") or ""),
                "图号": str(row.get("drawingNo") or ""),
            }
        )
        for col, key in enumerate(["sequenceNo", "drawingName", "drawingNo"]):
            value = str(row.get(key) or "")
            if not value:
                continue
            cells.append(
                {
                    "cellId": f"cell_{index}_{col + 1}",
                    "row": index - 1,
                    "col": col,
                    "rowspan": 1,
                    "colspan": 1,
                    "text": value,
                    "bbox": row.get("bbox"),
                    "pageNo": page_no,
                    "coordinateSystem": row.get("coordinateSystem"),
                    "coordinateTransformStatus": row.get("coordinateTransformStatus"),
                    "confidence": row.get("confidence"),
                    "isHeader": False,
                }
            )
    return {
        "tableId": f"page_{page_no}_engineering_drawing_list_rows_1",
        "pageNo": page_no,
        "bbox": bbox,
        "coordinateSystem": rows[0].get("coordinateSystem"),
        "coordinateTransformStatus": rows[0].get("coordinateTransformStatus"),
        "rows": len(rows),
        "columns": 3,
        "structureConfidence": round(min(0.96, 0.76 + min(len(rows), 20) * 0.01), 4),
        "cells": cells,
        "normalizedRows": normalized_rows,
        "businessSchema": "engineering_drawing_list_rows_v1",
        "tableType": "engineering_drawing_list_rows",
        "sourceEngine": "fragment_drawing_list_row_detector",
        "qualityFlags": ["drawing_list_rows", "ocr_text_aligned"],
    }


def is_quality_certificate_profile(result: dict[str, Any], profile: dict[str, Any]) -> bool:
    return str(profile.get("profileId") or result.get("profileId") or "") == "quality_certificate_v1"


def is_ndt_rt_report_profile(result: dict[str, Any], profile: dict[str, Any]) -> bool:
    return str(profile.get("profileId") or result.get("profileId") or "") == "ndt_rt_report_v1"


def is_qualification_certificate_profile(result: dict[str, Any], profile: dict[str, Any]) -> bool:
    return str(profile.get("profileId") or result.get("profileId") or "") == "qualification_certificate_v1"


def is_welding_record_profile(result: dict[str, Any], profile: dict[str, Any]) -> bool:
    return str(profile.get("profileId") or result.get("profileId") or "") == "welding_record_v1"


def is_welding_procedure_qualification_profile(result: dict[str, Any], profile: dict[str, Any]) -> bool:
    profile_id = str(profile.get("profileId") or result.get("profileId") or "")
    document_type = str(profile.get("documentType") or result.get("documentType") or "")
    return profile_id == "welding_procedure_qualification_v1" or document_type == "welding_procedure_qualification"


def is_construction_plan_profile(result: dict[str, Any], profile: dict[str, Any]) -> bool:
    profile_id = str(profile.get("profileId") or result.get("profileId") or "")
    document_type = str(profile.get("documentType") or result.get("documentType") or "")
    return profile_id == "construction_plan_v1" or document_type == "construction_plan"


def is_welder_certificate_profile(result: dict[str, Any], profile: dict[str, Any]) -> bool:
    profile_id = str(profile.get("profileId") or result.get("profileId") or "")
    document_type = str(profile.get("documentType") or result.get("documentType") or "")
    return profile_id == "welder_certificate_v1" or document_type == "welder_certificate"


def extract_r24_r34_labeled_business_fields(result: dict[str, Any], profile: dict[str, Any]) -> None:
    fragments = [item for item in result.get("fragments") or [] if isinstance(item, dict)]
    text_items = [(str(item.get("text") or "").strip(), item) for item in fragments if str(item.get("text") or "").strip()]
    for field_code, configured_labels in dict(profile.get("fieldLabels") or {}).items():
        labels = configured_labels if isinstance(configured_labels, list) else [str(configured_labels)]
        candidate = value_from_labeled_text(text_items, labels, max_steps=6, max_length=160)
        add_field_if_missing(result, str(field_code), labels[0], candidate)


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
    add_field_if_missing(
        result,
        "chemical_composition_summary",
        "化学成分摘要",
        find_text_fragment(text_items, ["化学成分", "C", "Si", "Mn", "P", "S"]),
    )
    add_field_if_missing(
        result,
        "mechanical_property_summary",
        "力学性能摘要",
        find_text_fragment(text_items, ["力学性能", "屈服", "抗拉", "延伸率", "硬度"]),
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


def append_quality_certificate_summary_tables(result: dict[str, Any]) -> None:
    fragments = [item for item in result.get("fragments") or [] if isinstance(item, dict)]
    if not fragments:
        return
    joined = "\n".join(str(item.get("text") or "") for item in fragments)
    existing_schemas = {
        str(schema)
        for table in result.get("tables") or []
        if isinstance(table, dict)
        for schema in [table.get("businessSchema"), *(table.get("businessSchemas") or [])]
        if schema
    }
    if "material_chemical_composition_table" not in existing_schemas and quality_table_has_chemical_composition(joined):
        table = fragments_summary_table(
            fragments,
            table_id="quality_certificate_chemical_composition_from_fragments",
            schema="material_chemical_composition_table",
            keywords=["化学成分", "C", "Si", "Mn", "P", "S", "碳", "硅", "锰", "磷", "硫"],
            quality_flag="quality_certificate_chemical_summary_from_fragments",
        )
        if table:
            result.setdefault("tables", []).append(table)
    if "mechanical_property_table" not in existing_schemas and quality_table_has_mechanical_property(joined):
        table = fragments_summary_table(
            fragments,
            table_id="quality_certificate_mechanical_property_from_fragments",
            schema="mechanical_property_table",
            keywords=["力学性能", "屈服", "抗拉", "延伸", "硬度", "冲击"],
            quality_flag="quality_certificate_mechanical_summary_from_fragments",
        )
        if table:
            result.setdefault("tables", []).append(table)


def fragments_summary_table(
    fragments: list[dict[str, Any]],
    *,
    table_id: str,
    schema: str,
    keywords: list[str],
    quality_flag: str,
) -> dict[str, Any] | None:
    selected = []
    for fragment in fragments:
        text = str(fragment.get("text") or "")
        if any(keyword.lower() in text.lower() for keyword in keywords):
            selected.append(fragment)
    if not selected:
        return None
    selected = sorted(selected, key=lambda item: (page_no_from(item), rect_from_bbox(item.get("bbox")) or [0, 0, 0, 0]))
    cells = []
    for index, fragment in enumerate(selected[:80]):
        cells.append(
            {
                "cellId": f"cell_{index + 1}_1",
                "row": index,
                "col": 0,
                "text": str(fragment.get("text") or ""),
                "bbox": rect_from_bbox(fragment.get("bbox")),
                "pageNo": page_no_from(fragment),
                "coordinateSystem": fragment.get("coordinateSystem"),
                "coordinateTransformStatus": fragment.get("coordinateTransformStatus"),
                "confidence": first_present(fragment, "confidence", default=0.0),
                "isHeader": index == 0,
            }
        )
    bbox = fragment_union_bbox(selected)
    page_no = page_no_from(selected[0])
    return {
        "tableId": f"page_{page_no}_{table_id}",
        "pageNo": page_no,
        "bbox": bbox,
        "rows": len(cells),
        "columns": 1,
        "structureConfidence": 0.72,
        "cells": cells,
        "businessSchema": schema,
        "businessSchemas": [schema],
        "sourceEngine": "heuristic_table_from_ocr_fragments",
        "qualityFlags": [quality_flag, "ocr_text_aligned"],
    }


def quality_table_has_chemical_composition(text: str) -> bool:
    compact = text.lower().replace(" ", "")
    return "化学成分" in compact or sum(token in compact for token in ["碳c", "锰mn", "硅si", "硫s", "磷p"]) >= 3


def quality_table_has_mechanical_property(text: str) -> bool:
    compact = text.lower().replace(" ", "")
    return any(token in compact for token in ["屈服点", "抗拉强度", "延伸率", "力学性能", "硬度"])


def tag_ndt_rt_report_tables(result: dict[str, Any]) -> None:
    tables = [table for table in result.get("tables") or [] if isinstance(table, dict)]
    for table in tables:
        text = table_text(table)
        compact = text.replace(" ", "").upper()
        if not any(token in compact for token in ["射线", "RT", "焊口", "检测比例", "评定级别", "报告编号"]):
            continue
        schemas = set(str(item) for item in table.get("businessSchemas") or [] if item)
        schemas.add("weld_detection_result_table")
        table["businessSchemas"] = sorted(schemas)
        if not table.get("businessSchema"):
            table["businessSchema"] = "weld_detection_result_table"
        flags = {str(flag) for flag in table.get("qualityFlags") or []}
        flags.add("ndt_rt_report_schema_match")
        table["qualityFlags"] = sorted(flags)


def append_ndt_rt_report_summary_table(result: dict[str, Any]) -> None:
    existing_schemas = {
        str(schema)
        for table in result.get("tables") or []
        if isinstance(table, dict)
        for schema in [table.get("businessSchema"), *(table.get("businessSchemas") or [])]
        if schema
    }
    if "weld_detection_result_table" in existing_schemas:
        return
    fragments = [item for item in result.get("fragments") or [] if isinstance(item, dict)]
    joined = "\n".join(str(item.get("text") or "") for item in fragments)
    if not any(token in joined for token in ["射线检测", "RT", "焊口", "底片", "评定级别", "合格级别"]):
        return
    table = fragments_summary_table(
        fragments,
        table_id="ndt_rt_result_from_fragments",
        schema="weld_detection_result_table",
        keywords=["射线", "RT", "焊口", "检测比例", "评定级别", "合格级别", "底片", "报告编号", "结论"],
        quality_flag="ndt_rt_result_summary_from_fragments",
    )
    if table:
        result.setdefault("tables", []).append(table)


def extract_ndt_rt_report_fields(result: dict[str, Any]) -> None:
    fragments = [item for item in result.get("fragments") or [] if isinstance(item, dict)]
    text_items = [(str(item.get("text") or "").strip(), item) for item in fragments if str(item.get("text") or "").strip()]
    joined = "\n".join(text for text, _ in text_items)
    if not any(token in joined for token in ["射线检测", "RT", "焊口", "底片", "评定级别", "检测报告"]):
        return
    add_field_if_missing(result, "report_no", "报告编号", ndt_report_no_candidate(text_items))
    add_field_if_missing(result, "project_name", "工程名称", ndt_project_candidate(text_items))
    add_field_if_missing(result, "detection_method", "检测方法", ndt_detection_method_candidate(text_items))
    add_field_if_missing(result, "weld_no", "焊口编号", ndt_weld_no_candidate(text_items))
    add_field_if_missing(result, "detection_date", "检测日期", ndt_detection_date_candidate(text_items))
    add_field_if_missing(result, "evaluation_level", "评定级别", ndt_evaluation_level_candidate(text_items))
    add_field_if_missing(result, "conclusion", "检测结论", ndt_conclusion_candidate(text_items))
    add_field_if_missing(result, "inspection_unit", "检测单位", ndt_inspection_unit_candidate(text_items))


def ndt_report_no_candidate(text_items: list[tuple[str, dict[str, Any]]]) -> dict[str, Any] | None:
    candidate = next_value_after_label(text_items, ["报告编号", "报告号", "编号"], max_steps=5)
    if candidate:
        return candidate
    pattern = re.compile(r"\b(?:RT|UT)?[A-Z0-9-]*\d{4}[A-Z0-9-]*(?:RTBG|BG)?[-A-Z0-9]*\b", re.IGNORECASE)
    return regex_field_candidate(text_items, pattern)


def ndt_project_candidate(text_items: list[tuple[str, dict[str, Any]]]) -> dict[str, Any] | None:
    return next_value_after_label(text_items, ["工程名称", "工程名", "项目名称"], max_steps=8) or find_project_fragment(text_items)


def ndt_detection_method_candidate(text_items: list[tuple[str, dict[str, Any]]]) -> dict[str, Any] | None:
    for text, fragment in text_items:
        upper = text.upper()
        if "射线" in text or "RT" in upper:
            return {"text": "RT", "fragment": fragment}
    return None


def ndt_weld_no_candidate(text_items: list[tuple[str, dict[str, Any]]]) -> dict[str, Any] | None:
    return next_value_after_label(text_items, ["焊口编号", "焊口号", "检件编号", "检件名"], max_steps=8)


def ndt_detection_date_candidate(text_items: list[tuple[str, dict[str, Any]]]) -> dict[str, Any] | None:
    direct = regex_field_candidate(text_items, DATE_CN_RE)
    if direct:
        return direct
    chinese_month = re.compile(r"二\s*[零〇○]\s*(?:二\s*)?(?:一\s*)?年?\s*([一二三四五六七八九十]{1,3})\s*月")
    report_year = ndt_report_year(text_items)
    for text, fragment in text_items:
        match = chinese_month.search(text)
        if match:
            month = chinese_month_to_number(match.group(1))
            if month and report_year:
                return {"text": f"{report_year}年{month}月", "fragment": fragment}
    return next_value_after_label(text_items, ["检测日期", "报告日期", "日期"], max_steps=4)


def ndt_report_year(text_items: list[tuple[str, dict[str, Any]]]) -> str | None:
    for text, _ in text_items:
        match = re.search(r"(20\d{2})", text)
        if match:
            return match.group(1)
    return None


def chinese_month_to_number(value: str) -> int | None:
    digits = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    text = str(value or "").strip()
    if text == "十":
        return 10
    if text.startswith("十") and len(text) == 2:
        return 10 + digits.get(text[1], 0)
    if text.endswith("十") and len(text) == 2:
        return digits.get(text[0], 0) * 10
    if len(text) == 1:
        return digits.get(text)
    if len(text) == 2 and text[0] in digits and text[1] in digits:
        return digits[text[0]] * 10 + digits[text[1]]
    return None


def ndt_evaluation_level_candidate(text_items: list[tuple[str, dict[str, Any]]]) -> dict[str, Any] | None:
    candidate = next_value_after_label(text_items, ["评定级别", "合格级别", "质量等级"], max_steps=6)
    if candidate:
        candidate["text"] = normalize_roman_level(str(candidate.get("text") or "")).replace("级", "")
        return candidate
    pattern = re.compile(r"\b(?:I|II|III|IV|Ⅰ|Ⅱ|Ⅲ|Ⅳ)\s*级?\b", re.IGNORECASE)
    match = regex_field_candidate(text_items, pattern)
    if match:
        match["text"] = normalize_roman_level(str(match["text"])).replace("级", "")
    return match


def ndt_conclusion_candidate(text_items: list[tuple[str, dict[str, Any]]]) -> dict[str, Any] | None:
    for text, fragment in text_items:
        if "合格" in text:
            return {"text": "合格", "fragment": fragment}
    return next_value_after_label(text_items, ["结论", "检测结论", "评定结果"], max_steps=6)


def ndt_inspection_unit_candidate(text_items: list[tuple[str, dict[str, Any]]]) -> dict[str, Any] | None:
    for text, fragment in text_items:
        cleaned = text.strip(" ：:")
        if "检测" in cleaned and "有限公司" in cleaned:
            return {"text": cleaned, "fragment": fragment}
    return next_value_after_label(text_items, ["检测单位", "检验单位"], max_steps=6)


def extract_qualification_certificate_fields(result: dict[str, Any]) -> None:
    fragments = [item for item in result.get("fragments") or [] if isinstance(item, dict)]
    text_items = [(str(item.get("text") or "").strip(), item) for item in fragments if str(item.get("text") or "").strip()]
    joined = "\n".join(text for text, _ in text_items)
    if not qualification_certificate_evidence_text(joined):
        return
    add_field_if_missing(result, "certificate_no", "许可证编号", qualification_certificate_no_candidate(text_items))
    add_field_if_missing(result, "organization_name", "单位名称", qualification_organization_candidate(text_items))
    add_field_if_missing(result, "license_scope", "许可范围", qualification_scope_candidate(text_items))
    add_field_if_missing(result, "valid_until", "有效期至", qualification_valid_until_candidate(text_items))
    add_field_if_missing(result, "issuer", "发证机关", qualification_issuer_candidate(text_items))
    add_field_if_missing(result, "issue_date", "发证日期", qualification_issue_date_candidate(text_items))


def qualification_certificate_evidence_text(joined: str) -> str:
    if any(token in joined for token in ["特种设备生产许可证", "生产许可证", "许可证编号", "许可项目", "许可范围"]):
        return joined
    if re.search(r"\bTS\s*\d{6,12}(?:-\d{4})?\b", joined, flags=re.IGNORECASE) and "有效期" in joined:
        return joined
    return ""


def qualification_certificate_no_candidate(text_items: list[tuple[str, dict[str, Any]]]) -> dict[str, Any] | None:
    labeled = value_from_labeled_text(text_items, ["许可证编号", "证书编号", "编号"], LICENSE_NO_RE)
    if labeled:
        return labeled
    return regex_field_candidate(text_items, LICENSE_NO_RE)


def qualification_organization_candidate(text_items: list[tuple[str, dict[str, Any]]]) -> dict[str, Any] | None:
    return value_from_labeled_text(
        text_items,
        ["单位名称", "获证单位", "制造单位", "施工单位", "申请单位", "单位"],
        max_length=80,
    ) or find_organization_fragment(text_items)


def qualification_scope_candidate(text_items: list[tuple[str, dict[str, Any]]]) -> dict[str, Any] | None:
    return value_from_labeled_text(
        text_items,
        ["许可范围", "许可项目", "业务范围", "获准从事"],
        max_steps=10,
        max_length=180,
    ) or find_license_scope_fragment(text_items)


def qualification_valid_until_candidate(text_items: list[tuple[str, dict[str, Any]]]) -> dict[str, Any] | None:
    labeled = value_from_labeled_text(text_items, ["有效期至", "有效期限至", "有效期"], DATE_CN_RE)
    if labeled:
        return labeled
    for text, fragment in text_items:
        if "有效期" not in text:
            continue
        match = DATE_CN_RE.search(text)
        if match:
            return {"text": re.sub(r"\s+", "", match.group(0)), "fragment": fragment}
    return None


def qualification_issuer_candidate(text_items: list[tuple[str, dict[str, Any]]]) -> dict[str, Any] | None:
    return value_from_labeled_text(text_items, ["发证机关", "签发机构", "批准机关", "发证单位"], max_steps=5, max_length=80)


def qualification_issue_date_candidate(text_items: list[tuple[str, dict[str, Any]]]) -> dict[str, Any] | None:
    return value_from_labeled_text(text_items, ["发证日期", "签发日期", "批准日期"], DATE_CN_RE, max_steps=5)


def find_license_scope_fragment(text_items: list[tuple[str, dict[str, Any]]]) -> dict[str, Any] | None:
    scope_terms = ["压力管道安装", "压力管道元件", "压力管道设计", "管件制造", "钢管制造", "工业管道"]
    for text, fragment in text_items:
        if any(term in text for term in scope_terms):
            return {"text": text.strip(" ：:"), "fragment": fragment}
    return None


def extract_construction_plan_fields(result: dict[str, Any]) -> None:
    fragments = [item for item in result.get("fragments") or [] if isinstance(item, dict)]
    text_items = [(str(item.get("text") or "").strip(), item) for item in fragments if str(item.get("text") or "").strip()]
    joined = "\n".join(text for text, _ in text_items)
    if not construction_plan_evidence_text(joined):
        return
    add_field_if_missing(
        result,
        "document_title",
        "文件标题",
        find_text_fragment(text_items, ["施工组织设计", "专项施工方案", "管道施工方案", "施工方案"]),
    )
    add_field_if_missing(
        result,
        "project_name",
        "项目名称",
        next_value_after_label(text_items, ["项目名称", "工程名称"], max_steps=8) or find_project_fragment(text_items),
    )
    add_field_if_missing(
        result,
        "construction_unit",
        "施工单位",
        value_from_labeled_text(text_items, ["施工单位", "编制单位", "承包单位"], max_steps=8, max_length=90)
        or construction_unit_candidate(text_items),
    )
    add_field_if_missing(
        result,
        "issue_date",
        "编制日期",
        value_from_labeled_text(text_items, ["编制日期", "日期", "报审日期"], DATE_CN_RE, max_steps=5)
        or regex_field_candidate(text_items, DATE_CN_RE),
    )


def construction_plan_evidence_text(joined: str) -> str:
    if any(token in joined for token in ["施工组织设计", "施工方案", "专项施工方案", "管道施工方案"]):
        return joined
    if "编制依据" in joined and "施工方法" in joined and any(token in joined for token in ["施工单位", "项目名称", "工程名称"]):
        return joined
    return ""


def construction_unit_candidate(text_items: list[tuple[str, dict[str, Any]]]) -> dict[str, Any] | None:
    for text, fragment in text_items:
        cleaned = text.strip(" ：:")
        if any(suffix in cleaned for suffix in ["建设有限公司", "工程有限公司", "安装有限公司", "施工有限公司"]):
            return {"text": cleaned, "fragment": fragment}
    return find_organization_fragment(text_items)


def extract_welding_procedure_qualification_fields(result: dict[str, Any]) -> None:
    fragments = [item for item in result.get("fragments") or [] if isinstance(item, dict)]
    text_items = [(str(item.get("text") or "").strip(), item) for item in fragments if str(item.get("text") or "").strip()]
    joined = "\n".join(text for text, _ in text_items)
    if not welding_procedure_qualification_evidence_text(joined):
        return
    add_field_if_missing(
        result,
        "report_no",
        "评定报告编号",
        value_from_labeled_text(text_items, ["评定报告编号", "报告编号", "报告号", "编号"], PQR_WPS_NO_RE, max_steps=6)
        or regex_field_candidate(text_items, PQR_WPS_NO_RE),
    )
    add_field_if_missing(
        result,
        "project_name",
        "项目名称",
        next_value_after_label(text_items, ["项目名称", "工程名称"], max_steps=8) or find_project_fragment(text_items),
    )
    add_field_if_missing(
        result,
        "procedure_no",
        "WPS/PQR编号",
        value_from_labeled_text(
            text_items,
            ["WPS编号", "PQR编号", "焊接工艺规程编号", "工艺评定编号", "工艺编号"],
            PQR_WPS_NO_RE,
            max_steps=6,
        )
        or regex_field_candidate(text_items, PQR_WPS_NO_RE),
    )
    add_field_if_missing(
        result,
        "welding_method",
        "焊接方法",
        welding_method_candidate(text_items)
        or value_from_labeled_text(text_items, ["焊接方法"], max_steps=6, max_length=80),
    )
    add_field_if_missing(
        result,
        "base_material",
        "母材",
        value_from_labeled_text(text_items, ["母材", "母材牌号", "材料牌号", "钢号"], max_steps=8, max_length=100),
    )
    add_field_if_missing(
        result,
        "thickness_range",
        "适用厚度范围",
        value_from_labeled_text(text_items, ["厚度范围", "适用厚度", "适用范围", "母材厚度"], max_steps=8, max_length=100)
        or thickness_range_candidate(text_items),
    )
    add_field_if_missing(
        result,
        "qualification_date",
        "评定日期",
        value_from_labeled_text(text_items, ["评定日期", "报告日期", "批准日期", "日期"], DATE_CN_RE, max_steps=6)
        or regex_field_candidate(text_items, DATE_CN_RE),
    )
    for field_code, label, labels in (
        ("wps_no", "WPS编号", ["WPS编号", "焊接工艺规程编号"]),
        ("pqr_no", "PQR编号", ["PQR编号", "焊接工艺评定编号", "评定报告编号"]),
        ("current_range", "电流范围", ["电流范围", "焊接电流"]),
        ("voltage_range", "电压范围", ["电压范围", "电弧电压"]),
        ("welding_speed_range", "焊接速度范围", ["焊接速度范围", "焊接速度"]),
        ("interpass_temperature_range", "层间温度范围", ["层间温度范围", "层间温度"]),
        ("approved_by", "批准人员", ["批准", "批准人", "审批"]),
    ):
        add_field_if_missing(result, field_code, label, value_from_labeled_text(text_items, labels, max_steps=6, max_length=120))


PQR_WPS_NO_RE = re.compile(r"\b(?:PQR|WPS)[A-Z0-9_./-]*\b", re.IGNORECASE)


def welding_procedure_qualification_evidence_text(joined: str) -> str:
    if any(token in joined for token in ["焊接工艺评定", "焊评报告", "焊接工艺评定报告"]):
        return joined
    if re.search(r"\bPQR\b|\bWPS\b", joined, flags=re.IGNORECASE) and any(token in joined for token in ["母材", "焊接方法", "厚度范围", "适用范围"]):
        return joined
    return ""


def welding_method_candidate(text_items: list[tuple[str, dict[str, Any]]]) -> dict[str, Any] | None:
    patterns = [
        re.compile(r"\b(?:GTAW|SMAW|GMAW|SAW|FCAW|PAW)(?:\s*[+/]\s*(?:GTAW|SMAW|GMAW|SAW|FCAW|PAW))*\b", re.IGNORECASE),
        re.compile(r"(?:钨极氩弧焊|焊条电弧焊|气体保护焊|埋弧焊|手工电弧焊)"),
    ]
    for text, fragment in text_items:
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                return {"text": match.group(0).upper() if match.group(0).isascii() else match.group(0), "fragment": fragment}
    return None


def thickness_range_candidate(text_items: list[tuple[str, dict[str, Any]]]) -> dict[str, Any] | None:
    pattern = re.compile(r"(?:厚度|适用).*?(\d+(?:\.\d+)?\s*(?:[-~～至]\s*)?\d*(?:\.\d+)?\s*mm)", re.IGNORECASE)
    for text, fragment in text_items:
        match = pattern.search(text)
        if match:
            return {"text": re.sub(r"\s+", "", match.group(1)), "fragment": fragment}
    return None


def tag_welding_procedure_qualification_tables(result: dict[str, Any]) -> None:
    tables = [table for table in result.get("tables") or [] if isinstance(table, dict)]
    for table in tables:
        text = table_text(table)
        compact = text.replace(" ", "").upper()
        if not any(token in compact for token in ["PQR", "WPS", "焊接工艺评定", "焊接方法", "母材", "厚度范围", "适用范围"]):
            continue
        schemas = set(str(item) for item in table.get("businessSchemas") or [] if item)
        schemas.add("welding_procedure_qualification_table")
        table["businessSchemas"] = sorted(schemas)
        if not table.get("businessSchema"):
            table["businessSchema"] = "welding_procedure_qualification_table"
        flags = {str(flag) for flag in table.get("qualityFlags") or []}
        flags.add("welding_procedure_qualification_schema_match")
        table["qualityFlags"] = sorted(flags)


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


def extract_welder_certificate_fields_and_tables(result: dict[str, Any]) -> None:
    extraction = extract_welder_certificate_from_ocr_result(result)
    result.setdefault("metadata", {})[
        "welderCertificateExtraction"
    ] = welder_certificate_extraction_metadata(extraction)
    for field in welder_certificate_ocr_fields(extraction):
        append_field_if_code_missing(result, field)
    existing_schemas = {
        str(schema)
        for table in result.get("tables") or []
        if isinstance(table, dict)
        for schema in [table.get("businessSchema"), *(table.get("businessSchemas") or [])]
        if schema
    }
    for table in welder_certificate_ocr_tables(extraction):
        schema = str(table.get("businessSchema") or "")
        if schema and schema in existing_schemas:
            continue
        result.setdefault("tables", []).append(table)
    result.setdefault("diagnostics", []).append(
        diagnostic(
            "WELDER_CERTIFICATE_TOOL_APPLIED",
            "已使用焊工资格证专用工具提取证件编号、档案编号、"
            "发证机关和作业项目有效期。",
            level="info",
            verificationSignals=(extraction.get("verificationSignals") or {}),
        )
    )
    for item in extraction.get("diagnostics") or []:
        if isinstance(item, dict):
            result.setdefault("diagnostics", []).append(item)


def append_field_if_code_missing(result: dict[str, Any], field: dict[str, Any]) -> None:
    field_code = str(field.get("fieldCode") or "")
    if not field_code:
        return
    fields = result.setdefault("fields", [])
    if any(
        isinstance(item, dict) and str(item.get("fieldCode") or "") == field_code
        for item in fields
    ):
        return
    fields.append(field)


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
        if re.search(r"\b(?:WN|DN|NPS)\s*\d+", text, flags=re.IGNORECASE) or PIPE_SIZE_RE.search(text) or "S=" in normalized:
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


def value_from_labeled_text(
    text_items: list[tuple[str, dict[str, Any]]],
    labels: list[str],
    value_pattern: re.Pattern[str] | None = None,
    *,
    max_steps: int = 5,
    max_length: int = 120,
) -> dict[str, Any] | None:
    for index, (text, fragment) in enumerate(text_items):
        raw = str(text or "").strip()
        if not raw:
            continue
        for label in labels:
            if label not in raw:
                continue
            suffix = raw.split(label, 1)[1].strip(" ：:，,")
            candidate = value_from_text_suffix(suffix, value_pattern, max_length=max_length)
            if candidate:
                return {"text": candidate, "fragment": fragment}
            next_candidate = next_value_after_label(text_items[index : index + max_steps + 1], labels, max_steps=max_steps)
            if next_candidate:
                if value_pattern:
                    matched = value_pattern.search(str(next_candidate.get("text") or ""))
                    if not matched:
                        continue
                    next_candidate["text"] = re.sub(r"\s+", "", matched.group(0))
                return next_candidate
    return None


def value_from_text_suffix(
    suffix: str,
    value_pattern: re.Pattern[str] | None,
    *,
    max_length: int,
) -> str | None:
    value = str(suffix or "").strip(" ：:，,")
    if value_pattern:
        match = value_pattern.search(value)
        return re.sub(r"\s+", "", match.group(0)) if match else None
    if not value:
        return None
    if len(value) > max_length:
        value = value[:max_length].rstrip(" ：:，,")
    return value or None


def regex_field_candidate(text_items: list[tuple[str, dict[str, Any]]], pattern: re.Pattern[str]) -> dict[str, Any] | None:
    for text, fragment in text_items:
        match = pattern.search(text)
        if match:
            return {"text": match.group(0).replace(" ", ""), "fragment": fragment}
    return None


def add_profile_quality_diagnostics(result: dict[str, Any], profile: dict[str, Any]) -> None:
    diagnostics = result.setdefault("diagnostics", [])
    if parse_bool((profile.get("sealRules") or {}).get("required"), False) is True and not result.get("seals"):
        diagnostics.append(diagnostic("SEAL_NOT_FOUND", "当前 Profile 要求印章，但未检测到印章候选。", level="warning"))
    required_fields = profile.get("requiredFields") or []
    field_codes = {
        normalize_field_key(item.get("fieldCode") or item.get("fieldName") or "")
        for item in result.get("fields") or []
        if isinstance(item, dict)
    }
    missing_fields = [
        field
        for field in required_fields
        if field != "seal" and normalize_field_key(field) not in field_codes
    ]
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
    inherited_flags = [str(flag) for flag in fragment.get("qualityFlags") or []]
    fields.append(
        {
            "fieldCode": field_code,
            "fieldName": field_name,
            "fieldValue": str(text),
            "pageNo": page_no_from(fragment),
            "bbox": rect_from_bbox(fragment.get("bbox")),
            "coordinateSystem": fragment.get("coordinateSystem"),
            "sourceCoordinateSystem": fragment.get("sourceCoordinateSystem"),
            "coordinateTransform": fragment.get("coordinateTransform"),
            "coordinateTransformStatus": fragment.get("coordinateTransformStatus"),
            "qualityFlags": inherited_flags,
            "variantId": fragment.get("variantId"),
            "selectedVariantId": fragment.get("selectedVariantId"),
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


def find_organization_fragment(text_items: list[tuple[str, dict[str, Any]]]) -> dict[str, Any] | None:
    suffixes = ("有限公司", "设计院", "研究院", "工程公司", "检测有限公司", "集团公司")
    for text, fragment in text_items:
        cleaned = text.strip(" ：:")
        if any(suffix in cleaned for suffix in suffixes) and "项目名称" not in cleaned:
            return {"text": cleaned, "fragment": fragment}
    return None


def find_project_fragment(text_items: list[tuple[str, dict[str, Any]]]) -> dict[str, Any] | None:
    for index, (text, fragment) in enumerate(text_items):
        if "项目名称" in text or "PROJECT" in text.upper():
            cleaned = text.replace("项目名称", "").replace("PROJECT", "").strip(" ：:")
            if cleaned:
                return {"text": cleaned, "fragment": fragment}
            combined = project_fragments_after_label(text_items[index + 1 : index + 8])
            if combined:
                return combined
    for text, fragment in text_items:
        if "有限公司" in text and ("项目" in text or "新增" in text):
            return {"text": text, "fragment": fragment}
    return None


def drawing_no_candidate(text_items: list[tuple[str, dict[str, Any]]]) -> dict[str, Any] | None:
    for pattern in [ENGINEERING_DRAWING_NO_RE, DRAWING_LIST_SEQUENCE_RE]:
        for text, fragment in text_items:
            for match in pattern.finditer(text):
                value = normalize_drawing_no(match.group(0))
                if valid_engineering_drawing_no(value):
                    return {"text": value, "fragment": fragment}
    for text, fragment in text_items:
        for match in DRAWING_NO_RE.finditer(text):
            value = normalize_drawing_no(match.group(0))
            if valid_engineering_drawing_no(value):
                return {"text": value, "fragment": fragment}
    return None


def normalize_drawing_no(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).upper()


def valid_engineering_drawing_no(value: str) -> bool:
    normalized = normalize_drawing_no(value)
    if not normalized:
        return False
    if LICENSE_NO_RE.fullmatch(normalized):
        return False
    if re.fullmatch(r"A\d{6,12}", normalized):
        return False
    if re.fullmatch(r"TS\d{6,12}(?:-\d{4})?", normalized):
        return False
    if re.match(r"^(?:PL|VT)\d", normalized):
        return False
    if re.fullmatch(r"T\d+(?:\.\d+)?-\d{4}", normalized):
        return False
    if re.fullmatch(r"(?:GB|HG|NB|JB|SH|SY|TSG)[A-Z0-9.-]+", normalized):
        return False
    return bool(ENGINEERING_DRAWING_NO_RE.fullmatch(normalized) or DRAWING_LIST_SEQUENCE_RE.fullmatch(normalized))


def project_fragments_after_label(text_items: list[tuple[str, dict[str, Any]]]) -> dict[str, Any] | None:
    pieces: list[str] = []
    fragments: list[dict[str, Any]] = []
    stop_keywords = {"职责", "姓名", "日期", "装置名称", "编制", "设计", "审核", "校核", "DUTY", "NAME", "DATE"}
    keep_keywords = {"有限公司", "项目", "新增", "改造", "系统", "装车站", "卸车", "工程"}
    for text, fragment in text_items:
        cleaned = text.replace("PROJECT", "").strip(" ：:")
        if not cleaned or not CHINESE_TEXT_RE.search(cleaned):
            continue
        if any(keyword in cleaned.upper() for keyword in stop_keywords) and not any(keyword in cleaned for keyword in keep_keywords):
            continue
        if not any(keyword in cleaned for keyword in keep_keywords):
            continue
        pieces.append(cleaned)
        fragments.append(fragment)
        if "项目" in cleaned and len(pieces) >= 2:
            break
    if not pieces or not fragments:
        return None
    combined_fragment = deepcopy(fragments[0])
    combined_fragment["bbox"] = fragment_union_bbox(fragments)
    confidences = [safe_float(fragment.get("confidence")) for fragment in fragments]
    confidences = [value for value in confidences if value is not None]
    if confidences:
        combined_fragment["confidence"] = round(sum(confidences) / len(confidences), 6)
    return {"text": "".join(pieces), "fragment": combined_fragment}


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


def drop_none_fields(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if value is not None}


def page_no_from(raw: dict[str, Any]) -> int:
    if raw.get("pageNo") is not None:
        return int(raw["pageNo"])
    if raw.get("page_no") is not None:
        return int(raw["page_no"])
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


def apply_fast_first_default_options(options: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    if not fast_first_profile_enabled(profile, options):
        return options
    adjusted = deepcopy(options)
    adjusted["fastFirstMode"] = True
    adjusted.setdefault("quickMode", True)
    adjusted.setdefault("disableRemediation", True)
    adjusted.setdefault("enableFallback", False)
    adjusted.setdefault("maxPages", 1)
    adjusted.setdefault("maxLongSide", int(os.getenv("AICHECK_FAST_FIRST_MAX_LONG_SIDE", "1800")))
    adjusted.setdefault("engineBudgetSeconds", float(os.getenv("AICHECK_FAST_FIRST_ENGINE_BUDGET_SECONDS", "240")))
    if "variants" not in adjusted:
        adjusted["variants"] = ["original", "gray_clahe", "seal_color_mask"]
    return adjusted


def fast_first_profile_enabled(profile: dict[str, Any], options: dict[str, Any]) -> bool:
    if parse_bool(options.get("fastFirstMode"), False) is True:
        return True
    if parse_bool(options.get("disableFastFirst"), False) is True or parse_bool(options.get("fullOcr"), False) is True:
        return False
    if not env_bool("AICHECK_FAST_FIRST_ENGINEERING_PHOTO", True):
        return False
    profile_id = str(profile.get("profileId") or "")
    document_type = str(profile.get("documentType") or "")
    return profile_id in FAST_FIRST_PROFILE_IDS or document_type in FAST_FIRST_DOCUMENT_TYPES


def request_budget_exceeded(options: dict[str, Any], started_ms: int) -> bool:
    raw_budget = options.get("engineBudgetSeconds")
    if raw_budget is None:
        return False
    try:
        budget_ms = max(float(raw_budget), 0.0) * 1000
    except (TypeError, ValueError):
        return False
    if budget_ms <= 0:
        return False
    return monotonic_ms() - started_ms >= budget_ms


def engine_allowlist(options: dict[str, Any]) -> set[str] | None:
    raw = options.get("engineAllowlist")
    if raw is None:
        return None
    if isinstance(raw, str):
        values = [item.strip() for item in raw.split(",")]
    elif isinstance(raw, (list, tuple, set)):
        values = [str(item).strip() for item in raw]
    else:
        values = []
    return {value for value in values if value}


def tesseract_fallback_satisfied(
    result: dict[str, Any],
    *,
    profile: dict[str, Any],
    options: dict[str, Any],
) -> bool:
    policy = str(options.get("tesseractPolicy") or os.getenv("AICHECK_TESSERACT_POLICY") or "fallback_only").strip().lower()
    if policy not in {"fallback", "fallback_only"}:
        return False
    allowed = engine_allowlist(options)
    if allowed is not None and "tesseract_cli" in allowed and "paddle_ocr_subprocess" not in allowed:
        return False
    return ocr_text_content_sufficient(result, profile=profile)


def attach_engine_execution_metadata(result: dict[str, Any]) -> None:
    for run in result.get("engineRuns") or []:
        if not isinstance(run, dict):
            continue
        status = str(run.get("status") or "")
        attempted = status in {"success", "failed"}
        run["engineAttempted"] = attempted
        run["engineExecuted"] = bool(
            attempted
            and (
                int(run.get("durationMs") or 0) > 0
                or parse_bool(run.get("engineCacheHit"), False) is True
            )
        )
        if status == "skipped":
            run["skipReason"] = str(run.get("reason") or "no_routed_variant")


def should_defer_heavy_engine(
    engine_name: str,
    result: dict[str, Any],
    *,
    profile: dict[str, Any],
    options: dict[str, Any],
) -> bool:
    if parse_bool(options.get("fastFirstMode"), False) is not True:
        return False
    if engine_name not in FAST_FIRST_DEFERRED_ENGINES:
        return False
    if parse_bool(options.get("forceHeavyEngines"), False) is True:
        return False
    return ocr_text_content_sufficient(result, profile=profile)


def ocr_text_content_sufficient(result: dict[str, Any], *, profile: dict[str, Any]) -> bool:
    fragments = [
        item
        for item in result.get("fragments") or []
        if isinstance(item, dict)
        and str(item.get("text") or "").strip()
        and str(item.get("sourceEngine") or "") in {"paddle_ocr_subprocess", "paddle_ocr_v6", "tesseract_cli", "pymupdf_text_layer"}
    ]
    if not fragments:
        return False
    total_chars = sum(len(str(item.get("text") or "").strip()) for item in fragments)
    try:
        min_fragments = int(os.getenv("AICHECK_FAST_FIRST_MIN_FRAGMENTS", "8"))
    except (TypeError, ValueError):
        min_fragments = 8
    try:
        min_chars = int(os.getenv("AICHECK_FAST_FIRST_MIN_CHARS", "80"))
    except (TypeError, ValueError):
        min_chars = 80
    if len(fragments) >= max(min_fragments, 1) or total_chars >= max(min_chars, 1):
        return True
    required_fields = {str(item) for item in profile.get("requiredFields") or []}
    if required_fields.intersection({"drawing_no", "project_name", "design_phase"}):
        joined = "\n".join(str(item.get("text") or "") for item in fragments)
        return bool(DRAWING_NO_RE.search(joined) and DESIGN_PHASE_RE.search(joined))
    return False


def apply_parse_options_to_profile(profile: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
    adjusted = deepcopy(profile)
    policy = adjusted.setdefault("preprocessPolicy", {})
    quick_mode = parse_bool(options.get("quickMode"), False) is True
    if quick_mode:
        policy["renderDpi"] = min(int(policy.get("renderDpi") or 300), 180)
        policy["maxLongSide"] = min(int(policy.get("maxLongSide") or 2600), 1600)
        ocr_policy = policy.setdefault("ocr", {})
        ocr_policy["textDetLimitSideLen"] = min(int(ocr_policy.get("textDetLimitSideLen") or 2400), 1600)
        ocr_policy["useDocOrientationClassify"] = False
        ocr_policy["useDocUnwarping"] = False
        ocr_policy["useTextlineOrientation"] = False
    if options.get("maxPages") is not None:
        try:
            policy["maxPages"] = max(1, min(int(options["maxPages"]), 30))
        except (TypeError, ValueError):
            pass
    if options.get("maxLongSide") is not None:
        try:
            policy["maxLongSide"] = max(800, min(int(options["maxLongSide"]), 4096))
        except (TypeError, ValueError):
            pass
    if options.get("renderDpi") is not None:
        try:
            policy["renderDpi"] = max(150, min(int(options["renderDpi"]), 400))
        except (TypeError, ValueError):
            pass
    if options.get("textDetLimitSideLen") is not None:
        try:
            det_limit = max(800, min(int(options["textDetLimitSideLen"]), 4096))
            policy["textDetLimitSideLen"] = det_limit
            policy.setdefault("ocr", {})["textDetLimitSideLen"] = det_limit
        except (TypeError, ValueError):
            pass
    if isinstance(options.get("variants"), list) and options["variants"]:
        policy["variants"] = [str(item) for item in options["variants"] if str(item)]
    if parse_bool(options.get("enableTables"), True) is False:
        adjusted["requiredTables"] = []
    if parse_bool(options.get("enableSeals"), True) is False:
        adjusted.setdefault("sealRules", {})["required"] = False
        adjusted["sealRules"]["expectedSealTypes"] = []
        seal_policy = policy.setdefault("seal", {})
        seal_policy["enableColorCandidate"] = False
        seal_policy["enablePaddlexSeal"] = False
        seal_policy["enableAgentdesignSeal"] = False
        seal_policy["enableSealTextRecognition"] = False
    else:
        seal_policy = policy.setdefault("seal", {})
        for key in [
            "enableColorCandidate",
            "enablePaddlexSeal",
            "enableAgentdesignSeal",
            "enableSealTextRecognition",
        ]:
            if key in options:
                seal_policy[key] = parse_bool(options.get(key), parse_bool(seal_policy.get(key), False))
    if parse_bool(options.get("enableFallback"), True) is False:
        policy.setdefault("fallback", {})["enableVlmWhen"] = []
    try:
        max_long_side_cap = max(800, int(os.getenv("AICHECK_OCR_MAX_LONG_SIDE", "1920")))
    except (TypeError, ValueError):
        max_long_side_cap = 1920
    policy["maxLongSide"] = min(int(policy.get("maxLongSide") or max_long_side_cap), max_long_side_cap)
    policy["textDetLimitSideLen"] = min(
        int(policy.get("textDetLimitSideLen") or max_long_side_cap),
        max_long_side_cap,
    )
    ocr_policy = policy.setdefault("ocr", {})
    ocr_policy["textDetLimitSideLen"] = min(
        int(ocr_policy.get("textDetLimitSideLen") or policy["textDetLimitSideLen"]),
        max_long_side_cap,
    )
    return adjusted


def directory_fingerprint(path: Path) -> str:
    hasher = hashlib.sha256()
    files = sorted(item for item in path.rglob("*") if item.is_file())[:200]
    for item in files:
        stat = item.stat()
        hasher.update(str(item.relative_to(path)).encode("utf-8"))
        hasher.update(str(stat.st_size).encode("ascii"))
        hasher.update(str(int(stat.st_mtime)).encode("ascii"))
    return f"sha256:{hasher.hexdigest()}"
