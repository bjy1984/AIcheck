from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.ocr_eval_set import write_text_file


OCR_100_PADDLEX_MODELS = [
    "PP-OCRv6_medium_det",
    "PP-OCRv6_medium_rec",
    "PP-DocLayout-L",
    "PP-DocLayoutV3",
    "SLANeXt_wired",
    "RT-DETR-L_wired_table_cell_det",
    "SLANeXt_wireless",
    "RT-DETR-L_wireless_table_cell_det",
    "PP-OCRv4_server_seal_det",
    "PP-OCRv4_server_rec",
    "PP-LCNet_x1_0_doc_ori",
    "UVDoc",
    "PaddleOCR-VL-1.6-0.9B",
]

VLM_TRANSFORMERS_MODELS = {
    "PP-Chart2Table",
    "PaddleOCR-VL-0.9B",
    "PaddleOCR-VL-1.5-0.9B",
    "PaddleOCR-VL-1.6-0.9B",
}

PREFETCH_MODEL_ALIASES = {
    "PaddleOCR-VL-1.6-0.9B": ("PaddleOCR-VL-1.6",),
}

MODEL_REQUIRED_FILES = {
    "PaddleOCR-VL-1.6-0.9B": ("config.json", "model.safetensors", "processor_config.json"),
    "PaddleOCR-VL-1.6": ("config.json", "model.safetensors", "processor_config.json"),
}

DOCLING_DEFAULT_MODELS = [
    "layout",
    "tableformer",
    "code_formula",
    "picture_classifier",
    "rapidocr",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Prefetch local OCR model artifacts for AIcheck OCR 100 readiness.")
    parser.add_argument("--python", default=os.getenv("AICHECK_OCR_SUBPROCESS_PYTHON") or sys.executable, help="Python interpreter with paddlex installed.")
    parser.add_argument("--cache-home", default=os.getenv("PADDLE_PDX_CACHE_HOME") or os.getenv("AICHECK_PADDLEX_CACHE_HOME") or "", help="PaddleX cache home. official_models will be stored below this path.")
    parser.add_argument("--model", action="append", default=[], help="Specific PaddleX official model name. Repeatable.")
    parser.add_argument("--ocr-100", action="store_true", help="Prefetch the AIcheck OCR 100 PaddleX model set.")
    parser.add_argument("--docling", action="store_true", help="Prefetch Docling offline artifacts too. Enabled automatically by --ocr-100 unless --no-docling is set.")
    parser.add_argument("--no-docling", action="store_true", help="Skip Docling artifact prefetch even when --ocr-100 is set.")
    parser.add_argument("--docling-output-dir", default=os.getenv("DOCLING_ARTIFACTS_PATH") or "", help="Docling offline artifact directory. Defaults to <cache-home-parent>/docling when --docling/--ocr-100 is used.")
    parser.add_argument("--docling-model", action="append", default=[], help=f"Docling model family to download. Defaults: {', '.join(DOCLING_DEFAULT_MODELS)}. Repeatable.")
    parser.add_argument("--clean-incomplete", action="store_true", help="Move incomplete model cache directories aside before retrying a download.")
    parser.add_argument("--vl-download-method", choices=["auto", "hf-snapshot", "paddlex"], default=os.getenv("AICHECK_OCR_VL_DOWNLOAD_METHOD", "auto"), help="Download method for PaddleOCR-VL artifacts.")
    parser.add_argument("--download-retries", type=int, default=int(os.getenv("AICHECK_OCR_PREFETCH_RETRIES", "2")), help="Retry count for resumable large model downloads.")
    parser.add_argument("--verify-only", action="store_true", help="Only verify that model directories already exist.")
    parser.add_argument("--timeout-seconds", type=float, default=float(os.getenv("AICHECK_OCR_PREFETCH_TIMEOUT", "900")), help="Per-model prefetch timeout. Large VLM models may require 3600+ seconds.")
    parser.add_argument("--disable-hf-xet", action="store_true", default=os.getenv("AICHECK_OCR_PREFETCH_DISABLE_HF_XET", "").lower() in {"1", "true", "yes", "on"}, help="Set HF_HUB_DISABLE_XET=1 for slow or unstable Xet-backed model downloads.")
    parser.add_argument("--output", help="Optional JSON report path.")
    args = parser.parse_args()

    cache_home = resolve_cache_home(args.cache_home)
    models = unique([*args.model, *(OCR_100_PADDLEX_MODELS if args.ocr_100 or not args.model else [])])
    report = prefetch_report(
        python_bin=Path(args.python),
        cache_home=cache_home,
        models=models,
        include_docling=bool((args.docling or args.ocr_100) and not args.no_docling),
        docling_output_dir=resolve_docling_artifacts_dir(args.docling_output_dir, cache_home),
        docling_models=unique(args.docling_model or DOCLING_DEFAULT_MODELS),
        verify_only=bool(args.verify_only),
        timeout_seconds=float(args.timeout_seconds),
        disable_hf_xet=bool(args.disable_hf_xet),
        clean_incomplete=bool(args.clean_incomplete),
        vl_download_method=str(args.vl_download_method),
        download_retries=max(0, int(args.download_retries)),
    )
    if args.output:
        write_text_file(Path(args.output), json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def prefetch_report(
    *,
    python_bin: Path,
    cache_home: Path,
    models: list[str],
    include_docling: bool = False,
    docling_output_dir: Path | None = None,
    docling_models: list[str] | None = None,
    verify_only: bool,
    timeout_seconds: float | None = None,
    disable_hf_xet: bool = False,
    clean_incomplete: bool = False,
    vl_download_method: str = "auto",
    download_retries: int = 2,
) -> dict[str, Any]:
    results = []
    failures = []
    if not python_bin.exists():
        failures.append({"code": "OCR_PREFETCH_PYTHON_MISSING", "message": f"Python not found: {python_bin}"})
    cache_home.mkdir(parents=True, exist_ok=True)
    for model in models:
        model_dir = first_model_dir(cache_home, model) or primary_model_dir(cache_home, model)
        if verify_only:
            complete = model_artifacts_complete(model_dir, model)
            status = "present" if complete else "incomplete" if model_dir.exists() else "missing"
            if status == "missing":
                failures.append({"code": "OCR_PREFETCH_MODEL_MISSING", "message": f"Model is missing: {model}", "model": model})
            elif status == "incomplete":
                failures.append({"code": "OCR_PREFETCH_MODEL_INCOMPLETE", "message": f"Model cache is incomplete: {model}", "model": model, "path": str(model_dir)})
            results.append({"model": model, "status": status, "path": str(model_dir)})
            continue
        result = run_create_model(
            python_bin=python_bin,
            cache_home=cache_home,
            model=model,
            timeout_seconds=timeout_seconds,
            disable_hf_xet=disable_hf_xet,
            clean_incomplete=clean_incomplete,
            vl_download_method=vl_download_method,
            download_retries=download_retries,
        )
        results.append(result)
        if result["status"] != "present":
            failures.append({"code": "OCR_PREFETCH_MODEL_FAILED", "message": f"Model prefetch failed: {model}", "model": model, "detail": result.get("detail")})
    docling_report = None
    if include_docling:
        docling_report = prefetch_docling_report(
            python_bin=python_bin,
            output_dir=docling_output_dir or resolve_docling_artifacts_dir("", cache_home),
            models=docling_models or DOCLING_DEFAULT_MODELS,
            verify_only=verify_only,
            timeout_seconds=timeout_seconds,
            disable_hf_xet=disable_hf_xet,
        )
        if not docling_report["ok"]:
            failures.extend(docling_report["failures"])
    return {
        "schemaVersion": "aicheck-ocr-prefetch-report-v1",
        "ok": not failures,
        "cacheHome": str(cache_home),
        "python": str(python_bin),
        "timeoutSeconds": timeout_seconds,
        "disableHfXet": disable_hf_xet,
        "cleanIncomplete": clean_incomplete,
        "vlDownloadMethod": vl_download_method,
        "downloadRetries": download_retries,
        "models": results,
        "docling": docling_report,
        "failures": failures,
    }


def run_create_model(
    *,
    python_bin: Path,
    cache_home: Path,
    model: str,
    timeout_seconds: float | None = None,
    disable_hf_xet: bool = False,
    clean_incomplete: bool = False,
    vl_download_method: str = "auto",
    download_retries: int = 2,
) -> dict[str, Any]:
    if model in VLM_TRANSFORMERS_MODELS and vl_download_method in {"auto", "hf-snapshot"}:
        result = run_hf_snapshot_download(
            python_bin=python_bin,
            cache_home=cache_home,
            model=model,
            timeout_seconds=timeout_seconds,
            disable_hf_xet=disable_hf_xet,
            clean_incomplete=clean_incomplete,
            download_retries=download_retries,
        )
        if result["status"] == "present" or vl_download_method == "hf-snapshot":
            return result
    engine = prefetch_engine_for_model(model)
    script = (
        "from paddlex import create_model; import sys; "
        "engine = sys.argv[2] or None; "
        "create_model(sys.argv[1], engine=engine)"
    )
    env = os.environ.copy()
    env["PADDLE_PDX_CACHE_HOME"] = str(cache_home)
    env["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
    if disable_hf_xet:
        env["HF_HUB_DISABLE_XET"] = "1"
    cleaned = clean_incomplete_model_dirs(cache_home, model) if clean_incomplete else []
    try:
        completed = subprocess.run(
            [str(python_bin), "-c", script, model, engine or ""],
            check=False,
            capture_output=True,
            encoding="utf-8",
            env=env,
            timeout=float(timeout_seconds or os.getenv("AICHECK_OCR_PREFETCH_TIMEOUT", "900")),
        )
    except subprocess.TimeoutExpired:
        return {
            "model": model,
            "status": "timeout",
            "path": str(primary_model_dir(cache_home, model)),
            "timeoutSeconds": float(timeout_seconds or os.getenv("AICHECK_OCR_PREFETCH_TIMEOUT", "900")),
            "disableHfXet": disable_hf_xet,
            "engine": engine,
            "cleanedIncomplete": cleaned,
            "detail": "timeout",
        }
    model_dir = first_model_dir(cache_home, model) or primary_model_dir(cache_home, model)
    if completed.returncode == 0 and model_artifacts_complete(model_dir, model):
        return {"model": model, "status": "present", "path": str(model_dir), "engine": engine, "method": "paddlex", "cleanedIncomplete": cleaned}
    return {
        "model": model,
        "status": "incomplete" if completed.returncode == 0 and model_dir.exists() else "failed",
        "path": str(model_dir),
        "engine": engine,
        "method": "paddlex",
        "cleanedIncomplete": cleaned,
        "detail": (completed.stderr or completed.stdout or "")[-1200:],
    }


def run_hf_snapshot_download(
    *,
    python_bin: Path,
    cache_home: Path,
    model: str,
    timeout_seconds: float | None = None,
    disable_hf_xet: bool = False,
    clean_incomplete: bool = False,
    download_retries: int = 2,
) -> dict[str, Any]:
    repo_name = hf_repo_model_name(model)
    model_dir = primary_model_dir(cache_home, repo_name)
    cleaned = clean_incomplete_model_dirs(cache_home, model) if clean_incomplete else []
    script = """
import os
import sys
from huggingface_hub import snapshot_download

repo_id = sys.argv[1]
local_dir = sys.argv[2]
endpoint = os.getenv("PADDLE_PDX_HUGGING_FACE_ENDPOINT") or os.getenv("HF_ENDPOINT") or None
kwargs = {"repo_id": repo_id, "local_dir": local_dir}
if endpoint:
    kwargs["endpoint"] = endpoint
snapshot_download(**kwargs)
print(local_dir)
"""
    env = os.environ.copy()
    env["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
    if disable_hf_xet:
        env["HF_HUB_DISABLE_XET"] = "1"
    attempts: list[dict[str, Any]] = []
    for attempt in range(max(0, download_retries) + 1):
        try:
            completed = subprocess.run(
                [str(python_bin), "-c", script, f"PaddlePaddle/{repo_name}", str(model_dir)],
                check=False,
                capture_output=True,
                encoding="utf-8",
                env=env,
                timeout=float(timeout_seconds or os.getenv("AICHECK_OCR_PREFETCH_TIMEOUT", "900")),
            )
        except subprocess.TimeoutExpired:
            attempts.append({"attempt": attempt + 1, "status": "timeout", "detail": "timeout"})
            if model_artifacts_complete(model_dir, model):
                break
            continue
        attempts.append({"attempt": attempt + 1, "status": "ok" if completed.returncode == 0 else "failed", "detail": (completed.stderr or completed.stdout or "")[-600:]})
        if completed.returncode == 0 and model_artifacts_complete(model_dir, model):
            return {
                "model": model,
                "status": "present",
                "path": str(model_dir),
                "engine": "transformers",
                "method": "hf-snapshot",
                "cleanedIncomplete": cleaned,
                "attempts": attempts,
            }
    if model_artifacts_complete(model_dir, model):
        return {
            "model": model,
            "status": "present",
            "path": str(model_dir),
            "engine": "transformers",
            "method": "hf-snapshot",
            "cleanedIncomplete": cleaned,
            "attempts": attempts,
        }
    return {
        "model": model,
        "status": "incomplete" if model_dir.exists() else "failed",
        "path": str(model_dir),
        "engine": "transformers",
        "method": "hf-snapshot",
        "cleanedIncomplete": cleaned,
        "attempts": attempts,
        "detail": attempts[-1]["detail"] if attempts else "download did not run",
    }


def hf_repo_model_name(model: str) -> str:
    if model == "PaddleOCR-VL-1.6-0.9B":
        return "PaddleOCR-VL-1.6"
    if model == "PaddleOCR-VL-1.5-0.9B":
        return "PaddleOCR-VL-1.5"
    if model == "PaddleOCR-VL-0.9B":
        return "PaddleOCR-VL"
    return model


def prefetch_engine_for_model(model: str) -> str:
    return "transformers" if model in VLM_TRANSFORMERS_MODELS else ""


def primary_model_dir(cache_home: Path, model: str) -> Path:
    return cache_home / "official_models" / model


def model_dir_candidates(cache_home: Path, model: str) -> list[Path]:
    return [primary_model_dir(cache_home, name) for name in (model, *PREFETCH_MODEL_ALIASES.get(model, ()))]


def first_model_dir(cache_home: Path, model: str) -> Path | None:
    return next((path for path in model_dir_candidates(cache_home, model) if path.exists()), None)


def model_artifacts_complete(model_dir: Path, model: str) -> bool:
    if not model_dir.exists():
        return False
    required = MODEL_REQUIRED_FILES.get(model) or MODEL_REQUIRED_FILES.get(model_dir.name)
    if required:
        return all((model_dir / name).is_file() for name in required)
    return True


def clean_incomplete_model_dirs(cache_home: Path, model: str) -> list[dict[str, str]]:
    cleaned = []
    for model_dir in model_dir_candidates(cache_home, model):
        if not model_dir.exists() or model_artifacts_complete(model_dir, model):
            continue
        backup = model_dir.with_name(f"{model_dir.name}.incomplete-{int(time.time())}-{os.getpid()}")
        model_dir.rename(backup)
        cleaned.append({"from": str(model_dir), "to": str(backup)})
    return cleaned


def prefetch_docling_report(
    *,
    python_bin: Path,
    output_dir: Path,
    models: list[str],
    verify_only: bool,
    timeout_seconds: float | None,
    disable_hf_xet: bool,
) -> dict[str, Any]:
    if verify_only:
        status = "present" if docling_artifacts_complete(output_dir) else "missing"
        failures = [] if status == "present" else [{"code": "OCR_PREFETCH_DOCLING_MISSING", "message": f"Docling artifacts are missing or empty: {output_dir}"}]
        return {"ok": not failures, "status": status, "path": str(output_dir), "models": models, "failures": failures}
    output_dir.mkdir(parents=True, exist_ok=True)
    script = """
import sys
from pathlib import Path
from docling.utils.model_downloader import download_models

output_dir = Path(sys.argv[1])
models = set(sys.argv[2:])
download_models(
    output_dir=output_dir,
    progress=False,
    with_layout="layout" in models,
    with_tableformer="tableformer" in models,
    with_tableformer_v2="tableformerv2" in models,
    with_code_formula="code_formula" in models,
    with_picture_classifier="picture_classifier" in models,
    with_smolvlm="smolvlm" in models,
    with_granitedocling="granitedocling" in models,
    with_granitedocling_mlx="granitedocling_mlx" in models,
    with_granitedocling_2stage="granitedocling_2stage" in models,
    with_smoldocling="smoldocling" in models,
    with_smoldocling_mlx="smoldocling_mlx" in models,
    with_granite_vision="granite_vision" in models,
    with_granite_chart_extraction="granite_chart_extraction" in models,
    with_granite_chart_extraction_v4="granite_chart_extraction_v4" in models,
    with_rapidocr="rapidocr" in models,
    with_easyocr="easyocr" in models,
    with_nemotron_ocr="nemotron_ocr_v2" in models,
)
print(output_dir)
"""
    env = os.environ.copy()
    if disable_hf_xet:
        env["HF_HUB_DISABLE_XET"] = "1"
    try:
        completed = subprocess.run(
            [str(python_bin), "-c", script, str(output_dir), *models],
            check=False,
            capture_output=True,
            encoding="utf-8",
            env=env,
            timeout=float(timeout_seconds or os.getenv("AICHECK_OCR_PREFETCH_TIMEOUT", "900")),
        )
    except subprocess.TimeoutExpired:
        failure = {"code": "OCR_PREFETCH_DOCLING_TIMEOUT", "message": "Docling artifact prefetch timed out", "path": str(output_dir)}
        return {"ok": False, "status": "timeout", "path": str(output_dir), "models": models, "failures": [failure]}
    if completed.returncode == 0 and docling_artifacts_complete(output_dir):
        return {"ok": True, "status": "present", "path": str(output_dir), "models": models, "failures": []}
    failure = {
        "code": "OCR_PREFETCH_DOCLING_FAILED",
        "message": "Docling artifact prefetch failed",
        "path": str(output_dir),
        "detail": (completed.stderr or completed.stdout or "")[-1200:],
    }
    return {"ok": False, "status": "failed", "path": str(output_dir), "models": models, "failures": [failure]}


def docling_artifacts_complete(output_dir: Path) -> bool:
    return output_dir.exists() and output_dir.is_dir() and any(item.is_file() for item in output_dir.rglob("*"))


def resolve_docling_artifacts_dir(value: str, cache_home: Path) -> Path:
    if value:
        return Path(value).expanduser()
    return cache_home.parent / "docling"


def resolve_cache_home(value: str) -> Path:
    if value:
        path = Path(value).expanduser()
        return path.parent if path.name == "official_models" else path
    return Path.home() / ".paddlex"


def unique(values: list[str]) -> list[str]:
    seen: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.append(value)
    return seen


if __name__ == "__main__":
    raise SystemExit(main())
