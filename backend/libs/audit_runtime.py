from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "audit_runtime.yaml"
SUPPORTED_MODES = {"ocr_llm", "pure_llm"}


def load_audit_runtime_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    if not isinstance(loaded, dict):
        raise RuntimeError("Audit runtime config must be a mapping")
    return loaded


def normalize_audit_input_mode(value: str | None, config: dict[str, Any] | None = None) -> str:
    raw = str(value or "").strip().lower().replace("-", "_")
    if not raw:
        return ""
    aliases = (config or {}).get("aliases") if isinstance((config or {}).get("aliases"), dict) else {}
    normalized_aliases = {str(key).lower().replace("-", "_"): str(val) for key, val in aliases.items()}
    mode = normalized_aliases.get(raw, raw)
    if mode not in SUPPORTED_MODES:
        raise RuntimeError(f"Unsupported audit input mode: {value}")
    return mode


def audit_runtime_config(
    path: Path | None = None,
    env: dict[str, str] | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    source = env if env is not None else os.environ
    config = load_audit_runtime_config(path or CONFIG_PATH)
    mode_env = str(config.get("modeEnv") or "AICHECK_AUDIT_INPUT_MODE")
    configured_mode = normalize_audit_input_mode(mode, config)
    if not configured_mode:
        configured_mode = normalize_audit_input_mode(str(source.get(mode_env) or config.get("defaultMode") or "ocr_llm"), config)
    modes = config.get("modes") if isinstance(config.get("modes"), dict) else {}
    mode_config = modes.get(configured_mode) if isinstance(modes.get(configured_mode), dict) else {}
    if not mode_config:
        raise RuntimeError(f"Audit input mode is not configured: {configured_mode}")
    return {
        "schemaVersion": str(config.get("schemaVersion") or "aicheck-audit-runtime@1"),
        "mode": configured_mode,
        "modeEnv": mode_env,
        "label": str(mode_config.get("label") or configured_mode),
        "useOcrEvidence": bool(mode_config.get("useOcrEvidence", configured_mode == "ocr_llm")),
        "requireEvidenceRefs": bool(mode_config.get("requireEvidenceRefs", configured_mode == "ocr_llm")),
        "groundingPolicy": str(mode_config.get("groundingPolicy") or "evidence_only"),
        "evidenceValidationMode": str(mode_config.get("evidenceValidationMode") or "strict"),
    }


def audit_runtime_public_config(
    env: dict[str, str] | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    runtime = audit_runtime_config(env=env, mode=mode)
    return {
        "schemaVersion": runtime["schemaVersion"],
        "mode": runtime["mode"],
        "modeEnv": runtime["modeEnv"],
        "label": runtime["label"],
        "useOcrEvidence": runtime["useOcrEvidence"],
        "requireEvidenceRefs": runtime["requireEvidenceRefs"],
        "groundingPolicy": runtime["groundingPolicy"],
        "evidenceValidationMode": runtime["evidenceValidationMode"],
    }


def audit_runtime_for_run(run: dict[str, Any] | None) -> dict[str, Any]:
    run = run or {}
    audit_runtime = run.get("auditRuntime") if isinstance(run.get("auditRuntime"), dict) else {}
    explicit_mode = run.get("auditInputMode") or audit_runtime.get("mode")
    return audit_runtime_config(mode=str(explicit_mode or "") or None)
