from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


PACKAGE_CHECKS = {
    "cv2": "opencv-python-headless",
    "numpy": "numpy",
    "fitz": "PyMuPDF",
    "paddleocr": "paddleocr",
    "paddlex": "paddlex[ocr]",
    "docling": "docling",
    "transformers": "transformers",
}
SUBPROCESS_REQUIRED_PACKAGES = ("cv2", "numpy", "paddleocr")
SUBPROCESS_PROBED_PACKAGES = tuple(PACKAGE_CHECKS)


def build_runtime_doctor(
    *,
    engine_status: list[dict[str, Any]],
    model_manifest: dict[str, Any],
    offline_only: bool,
    network_disabled: bool,
    placeholder_allowed: bool,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    discovered = discover_runtime_candidates()
    subprocess_check = subprocess_python_check(discovered.get("subprocessPythonCandidates") or [])
    package_checks = [
        package_check(
            module,
            package_name,
            subprocess_packages=(subprocess_check.get("data") or {}).get("packages") or {},
        )
        for module, package_name in PACKAGE_CHECKS.items()
    ]
    checks.extend(package_checks)
    checks.append(subprocess_check)
    checks.extend(model_dir_checks(model_manifest))
    checks.extend(engine_checks(engine_status))
    checks.extend(policy_checks(offline_only, network_disabled, placeholder_allowed))
    checks.append(preprocess_dependency_check(package_checks, checks))

    summary = {
        "pass": len([item for item in checks if item["status"] == "pass"]),
        "warn": len([item for item in checks if item["status"] == "warn"]),
        "fail": len([item for item in checks if item["status"] == "fail"]),
        "total": len(checks),
    }
    return {
        "schemaVersion": "aicheck-ocr-runtime-doctor-v1",
        "ok": summary["fail"] == 0,
        "summary": summary,
        "checks": checks,
        "subprocessPython": os.getenv("AICHECK_OCR_SUBPROCESS_PYTHON"),
        "discovered": discovered,
        "recommendedEnv": recommended_env(discovered),
    }


def package_check(
    module_name: str,
    package_name: str,
    *,
    subprocess_packages: dict[str, bool] | None = None,
) -> dict[str, Any]:
    available = importlib.util.find_spec(module_name) is not None
    subprocess_packages = subprocess_packages or {}
    subprocess_covers_core = module_name in SUBPROCESS_REQUIRED_PACKAGES and bool(subprocess_packages.get(module_name))
    optional_runtime_package = module_name in {"fitz", "paddlex", "docling", "transformers"}
    status = "pass" if available else "warn" if subprocess_covers_core or optional_runtime_package else "fail"
    if available:
        message = f"{package_name} is importable."
        fix = None
    elif subprocess_covers_core:
        message = f"{package_name} is not importable in this runtime, but OCR subprocess provides {module_name}."
        fix = f"Install {package_name} in the OCR image to enable in-process fallback, or keep AICHECK_OCR_SUBPROCESS_PYTHON configured."
    elif optional_runtime_package:
        message = f"{package_name} is not importable in this runtime; related adapter is optional or gated by engine availability."
        fix = f"Install {package_name} if this adapter is required for the target OCR profile."
    else:
        message = f"{package_name} is not importable in this runtime."
        fix = f"Install {package_name} in the OCR image or point AICHECK_OCR_SUBPROCESS_PYTHON to an OCR venv."
    return {
        "name": f"package.{module_name}",
        "status": status,
        "message": message,
        "fix": fix,
        "data": {
            "module": module_name,
            "package": package_name,
            "subprocessCovered": subprocess_covers_core,
        },
    }


def subprocess_python_check(candidates: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    candidates = candidates or []
    python_bin = os.getenv("AICHECK_OCR_SUBPROCESS_PYTHON")
    if not python_bin:
        usable = next((item for item in candidates if item.get("usable")), None)
        candidate_fix = (
            f"Set AICHECK_OCR_SUBPROCESS_PYTHON={usable['path']}"
            if usable
            else "Set AICHECK_OCR_SUBPROCESS_PYTHON to a local OCR Python with cv2, numpy, and paddleocr installed."
        )
        return {
            "name": "subprocess.python",
            "status": "warn",
            "message": "AICHECK_OCR_SUBPROCESS_PYTHON is not configured.",
            "fix": candidate_fix,
            "data": {"python": None, "packages": {}, "candidates": candidates},
        }
    path = Path(python_bin)
    if not path.exists():
        return {
            "name": "subprocess.python",
            "status": "fail",
            "message": f"AICHECK_OCR_SUBPROCESS_PYTHON does not exist: {path}",
            "fix": "Fix AICHECK_OCR_SUBPROCESS_PYTHON or install the OCR venv.",
            "data": {"python": str(path), "packages": {}},
        }
    package_status = check_subprocess_packages(path, SUBPROCESS_PROBED_PACKAGES)
    missing = sorted(name for name in SUBPROCESS_REQUIRED_PACKAGES if not package_status.get(name))
    return {
        "name": "subprocess.python",
        "status": "pass" if not missing else "fail",
        "message": "OCR subprocess Python is usable." if not missing else f"OCR subprocess Python is missing packages: {', '.join(missing)}",
        "fix": None if not missing else "Install missing packages into the OCR subprocess Python environment.",
        "data": {"python": str(path), "packages": package_status, "candidates": candidates},
    }


def check_subprocess_packages(python_bin: Path, packages: tuple[str, ...]) -> dict[str, bool]:
    script = (
        "import importlib.util,json,sys;"
        "mods=sys.argv[1:];"
        "print(json.dumps({name: importlib.util.find_spec(name) is not None for name in mods}))"
    )
    try:
        completed = subprocess.run(
            [str(python_bin), "-c", script, *packages],
            check=False,
            capture_output=True,
            encoding="utf-8",
            timeout=10,
        )
    except Exception:
        return {name: False for name in packages}
    if completed.returncode != 0:
        return {name: False for name in packages}
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        return {name: False for name in packages}
    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError:
        return {name: False for name in packages}
    return {name: bool(payload.get(name)) for name in packages}


def model_dir_checks(model_manifest: dict[str, Any]) -> list[dict[str, Any]]:
    model_dirs = model_manifest.get("modelDirs") if isinstance(model_manifest, dict) else {}
    if not isinstance(model_dirs, dict) or not model_dirs:
        return [
            {
                "name": "models.manifest",
                "status": "fail",
                "message": "OCR model manifest has no modelDirs.",
                "fix": "Set AICHECK_OCR_MODELS_HOST_PATH and explicit OCR model directory environment variables.",
                "data": {},
            }
        ]
    checks = []
    for env_key, item in sorted(model_dirs.items()):
        item = item if isinstance(item, dict) else {}
        exists = bool(item.get("exists"))
        required = bool(item.get("required"))
        category = str(item.get("category") or "model")
        status = "pass" if exists else "fail" if required else "warn"
        fix_prefix = "Mount the required local model directory" if required else "Mount this local model directory to enable the related optional OCR capability"
        checks.append(
            {
                "name": f"models.{env_key}",
                "status": status,
                "message": f"{env_key} exists." if exists else f"{env_key} is missing: {item.get('path')}",
                "fix": None if exists else f"{fix_prefix} for {env_key} before starting ocr-service.",
                "data": {
                    "path": item.get("path"),
                    "hash": item.get("hash"),
                    "required": required,
                    "category": category,
                },
            }
        )
    return checks


def engine_checks(engine_status: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checks = []
    for engine in engine_status:
        name = str(engine.get("engine") or "unknown")
        available = bool(engine.get("available"))
        required = name in {"paddle_ocr_subprocess", "pp_structure_v3", "visual_seal_candidate_subprocess"}
        status = "pass" if available else "fail" if required else "warn"
        checks.append(
            {
                "name": f"engine.{name}",
                "status": status,
                "message": f"{name} is available." if available else f"{name} is unavailable.",
                "fix": None if available else engine_fix(engine),
                "data": engine,
            }
        )
    return checks


def engine_fix(engine: dict[str, Any]) -> str:
    name = str(engine.get("engine") or "")
    if name == "paddle_ocr_subprocess":
        return "Set AICHECK_OCR_SUBPROCESS_PYTHON plus text det/rec model dirs."
    if name == "pp_structure_v3":
        return "Mount PP-StructureV3 layout/table/text model directories."
    if name == "visual_seal_candidate_subprocess":
        return "Set AICHECK_OCR_SUBPROCESS_PYTHON to a Python with cv2/numpy."
    if engine.get("missingModelDirs"):
        return "Mount missing local model directories: " + ", ".join(str(item) for item in engine.get("missingModelDirs") or [])
    if engine.get("package"):
        return f"Install OCR package {engine['package']}."
    return "Check OCR runtime package and model configuration."


def policy_checks(offline_only: bool, network_disabled: bool, placeholder_allowed: bool) -> list[dict[str, Any]]:
    return [
        {
            "name": "policy.offline-only",
            "status": "pass" if offline_only else "fail",
            "message": "OCR is local-only." if offline_only else "OCR offline-only mode is disabled.",
            "fix": None if offline_only else "Set AICHECK_OCR_OFFLINE_ONLY=true.",
            "data": {"offlineOnly": offline_only},
        },
        {
            "name": "policy.network-disabled",
            "status": "pass" if network_disabled else "fail",
            "message": "Runtime model downloads are disabled." if network_disabled else "OCR network disable flag is off.",
            "fix": None if network_disabled else "Set AICHECK_OCR_DISABLE_NETWORK=true.",
            "data": {"networkDisabled": network_disabled},
        },
        {
            "name": "policy.placeholder-disabled",
            "status": "pass" if not placeholder_allowed else "fail",
            "message": "Placeholder OCR is disabled." if not placeholder_allowed else "Placeholder OCR is enabled.",
            "fix": None if not placeholder_allowed else "Set AICHECK_OCR_ALLOW_PLACEHOLDER=false in production.",
            "data": {"placeholderAllowed": placeholder_allowed},
        },
    ]


def preprocess_dependency_check(
    package_checks: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> dict[str, Any]:
    current_runtime_cv2 = next((item for item in package_checks if item["name"] == "package.cv2"), {})
    subprocess_check = next((item for item in checks if item["name"] == "subprocess.python"), {})
    subprocess_packages = ((subprocess_check.get("data") or {}).get("packages") or {}) if isinstance(subprocess_check, dict) else {}
    ready = current_runtime_cv2.get("status") == "pass" or bool(subprocess_packages.get("cv2") and subprocess_packages.get("numpy"))
    candidates = (subprocess_check.get("data") or {}).get("candidates") or {}
    usable_candidate = next((item for item in candidates if isinstance(item, dict) and item.get("usable")), None)
    fix = None
    if not ready:
        if usable_candidate:
            fix = f"Set AICHECK_OCR_SUBPROCESS_PYTHON={usable_candidate['path']} to enable preprocess variants."
        else:
            fix = "Install opencv-python-headless or configure AICHECK_OCR_SUBPROCESS_PYTHON with cv2/numpy."
    return {
        "name": "preprocess.variants",
        "status": "pass" if ready else "fail",
        "message": "Preprocess variants can be generated." if ready else "Only original images can be used; preprocess variants are unavailable.",
        "fix": fix,
        "data": {"currentRuntimeCv2": current_runtime_cv2.get("status"), "subprocessPackages": subprocess_packages},
    }


def discover_runtime_candidates() -> dict[str, Any]:
    roots = candidate_agentdesign_roots()
    python_candidates = discover_subprocess_python_candidates(roots)
    model_caches = discover_model_caches(roots)
    docling_artifacts = discover_docling_artifacts(roots)
    return {
        "agentdesignRoots": [str(root) for root in roots],
        "subprocessPythonCandidates": python_candidates,
        "modelCaches": model_caches,
        "doclingArtifacts": docling_artifacts,
    }


def candidate_agentdesign_roots() -> list[Path]:
    candidates: list[Path] = []
    for value in [
        os.getenv("AICHECK_AGENTDESIGN_HOST_PATH"),
        os.getenv("AICHECK_AGENTDESIGN_ROOT"),
        str(Path(os.getenv("AICHECK_AGENTDESIGN_BACKEND", "")).parents[2])
        if os.getenv("AICHECK_AGENTDESIGN_BACKEND") and len(Path(os.getenv("AICHECK_AGENTDESIGN_BACKEND", "")).parents) >= 3
        else None,
        "/Volumes/Volume/project/agentdesign",
        "/opt/agentdesign",
    ]:
        if not value:
            continue
        path = Path(value).expanduser()
        if path.exists() and path not in candidates:
            candidates.append(path)
    return candidates


def discover_subprocess_python_candidates(roots: list[Path]) -> list[dict[str, Any]]:
    paths: list[Path] = []
    env_python = os.getenv("AICHECK_OCR_SUBPROCESS_PYTHON")
    if env_python:
        paths.append(Path(env_python).expanduser())
    for root in roots:
        for relative in [
            ".venv-ocr311/bin/python",
            ".venv-ocr/bin/python",
            ".venv/bin/python",
            "venv/bin/python",
        ]:
            paths.append(root / relative)
    deduped: list[Path] = []
    for path in paths:
        if path.exists() and path not in deduped:
            deduped.append(path)
    candidates = []
    for path in deduped[:8]:
        packages = check_subprocess_packages(path, SUBPROCESS_PROBED_PACKAGES)
        missing = sorted(name for name in SUBPROCESS_REQUIRED_PACKAGES if not packages.get(name))
        candidates.append(
            {
                "path": str(path),
                "usable": not missing,
                "packages": packages,
                "missingPackages": missing,
            }
        )
    return candidates


def discover_model_caches(roots: list[Path]) -> list[dict[str, Any]]:
    paths: list[Path] = []
    for value in [os.getenv("AICHECK_PADDLEX_MODEL_CACHE"), os.getenv("PADDLE_PDX_MODEL_SOURCE")]:
        if value:
            paths.append(Path(value).expanduser())
    if os.getenv("PADDLEOCR_VL_MODEL_DIR"):
        paths.append(Path(os.environ["PADDLEOCR_VL_MODEL_DIR"]).expanduser())
    for root in roots:
        paths.append(root / ".paddlex-cache" / "official_models")
    deduped: list[Path] = []
    for path in paths:
        if path.exists() and path not in deduped:
            deduped.append(path)
    caches = []
    for path in deduped[:6]:
        models = sorted(item.name for item in path.iterdir() if item.is_dir())[:80]
        caches.append({"path": str(path), "models": models, "modelCount": len(models)})
    return caches


def discover_docling_artifacts(roots: list[Path]) -> list[dict[str, Any]]:
    paths: list[Path] = []
    if os.getenv("DOCLING_ARTIFACTS_PATH"):
        paths.append(Path(os.environ["DOCLING_ARTIFACTS_PATH"]).expanduser())
    for root in roots:
        paths.extend([root / "docling", root / ".cache" / "docling" / "models"])
    artifacts = []
    seen: set[Path] = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        if not path.exists() or not path.is_dir():
            continue
        file_count = sum(1 for item in path.rglob("*") if item.is_file())
        if file_count:
            artifacts.append({"path": str(path), "fileCount": file_count})
    return artifacts[:6]


def recommended_env(discovered: dict[str, Any]) -> dict[str, str]:
    env: dict[str, str] = {}
    usable_python = next(
        (item for item in discovered.get("subprocessPythonCandidates") or [] if item.get("usable")),
        None,
    )
    if usable_python:
        env["AICHECK_OCR_SUBPROCESS_PYTHON"] = str(usable_python["path"])
    cache = next((item for item in discovered.get("modelCaches") or [] if item.get("models")), None)
    if cache:
        base = Path(str(cache["path"]))
        env["AICHECK_PADDLEX_MODEL_CACHE"] = str(base)
        mappings: dict[str, str | tuple[str, ...]] = {
            "AICHECK_PADDLEOCR_DET_MODEL_DIR": "PP-OCRv6_medium_det",
            "AICHECK_PADDLEOCR_REC_MODEL_DIR": "PP-OCRv6_medium_rec",
            "AICHECK_SEAL_DET_MODEL_DIR": "PP-OCRv4_server_seal_det",
            "AICHECK_SEAL_REC_MODEL_DIR": "PP-OCRv4_server_rec",
            "AICHECK_PPSTRUCTURE_LAYOUT_MODEL_DIR": "PP-DocLayout-L",
            "AICHECK_PPSTRUCTURE_WIRED_TABLE_STRUCTURE_MODEL_DIR": "SLANeXt_wired",
            "AICHECK_PPSTRUCTURE_WIRED_TABLE_CELLS_MODEL_DIR": "RT-DETR-L_wired_table_cell_det",
            "AICHECK_PPSTRUCTURE_WIRELESS_TABLE_STRUCTURE_MODEL_DIR": "SLANeXt_wireless",
            "AICHECK_PPSTRUCTURE_WIRELESS_TABLE_CELLS_MODEL_DIR": "RT-DETR-L_wireless_table_cell_det",
            "AICHECK_PADDLEOCR_VL_LAYOUT_MODEL_DIR": "PP-DocLayoutV3",
            "AICHECK_PADDLEOCR_VL_REC_MODEL_DIR": ("PaddleOCR-VL-1.6-0.9B", "PaddleOCR-VL-1.6"),
            "AICHECK_PADDLEOCR_VL_DOC_ORI_MODEL_DIR": "PP-LCNet_x1_0_doc_ori",
            "AICHECK_PADDLEOCR_VL_DOC_UNWARP_MODEL_DIR": "UVDoc",
        }
        for key, model_names in mappings.items():
            for model_name in (model_names if isinstance(model_names, tuple) else (model_names,)):
                path = base / model_name
                if path.exists():
                    env[key] = str(path)
                    break
        if (base / "PP-OCRv4_server_seal_det").exists() and (base / "PP-OCRv4_server_rec").exists():
            env["AICHECK_ENABLE_PADDLEX_SEAL_PIPELINE"] = "true"
    docling_artifact = next((item for item in discovered.get("doclingArtifacts") or [] if item.get("path")), None)
    if docling_artifact:
        env["DOCLING_ARTIFACTS_PATH"] = str(docling_artifact["path"])
    return env


def summary_text(report: dict[str, Any]) -> str:
    summary = report.get("summary") or {}
    return f"pass={summary.get('pass', 0)} warn={summary.get('warn', 0)} fail={summary.get('fail', 0)} total={summary.get('total', 0)}"


def main() -> int:
    from apps.ocr_service.service import ocr_service

    strict = "--strict-production" in sys.argv
    json_output = "--json" in sys.argv
    report = ocr_service.runtime_doctor_payload()
    if json_output:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(summary_text(report))
        for check in report["checks"]:
            print(f"{check['status'].upper()} {check['name']}: {check['message']}")
            if check.get("fix") and check["status"] != "pass":
                print(f"  fix: {check['fix']}")
    return 1 if strict and not report.get("ok") else 0


if __name__ == "__main__":
    raise SystemExit(main())
