from __future__ import annotations

from pathlib import Path

from apps.ocr_service import engines as engines_module
from apps.ocr_service import service as service_module


class FakeEngine:
    name = "paddle_ocr_subprocess"

    def __init__(self, *, available: bool = True, execution_mode: str = "subprocess") -> None:
        self._available = available
        self._execution_mode = execution_mode

    def available(self) -> bool:
        return self._available

    def status(self) -> dict:
        return {
            "engine": self.name,
            "available": self._available,
            "executionMode": self._execution_mode,
        }

    def parse(self, source_path: Path, **_kwargs) -> dict:
        return {
            "status": "success",
            "fragments": [{"text": "AIcheck OCR 2026", "bbox": [1, 1, 100, 20]}],
            "fields": [],
            "tables": [],
            "seals": [],
        }


def build_service(monkeypatch, *, available_mb: float = 8192) -> service_module.OcrService:
    monkeypatch.setattr(service_module, "local_engines", lambda: [FakeEngine()])
    monkeypatch.setattr(
        service_module,
        "memory_headroom_payload",
        lambda: {"source": "test", "availableBytes": int(available_mb * 1024 * 1024), "availableMb": available_mb},
    )
    return service_module.OcrService()


def test_readiness_distinguishes_executable_warmup_and_capacity(monkeypatch) -> None:
    service = build_service(monkeypatch)

    health = service.health_payload()

    assert health["executable"] is True
    assert health["warmedUp"] is False
    assert health["capacityReady"] is True
    assert health["lastSuccessfulInferenceAt"] is None


def test_deep_readiness_fails_until_real_probe_succeeds(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_OCR_DEEP_READY_PROBE", "true")
    monkeypatch.setenv("AICHECK_OCR_OFFLINE_ONLY", "false")
    service = build_service(monkeypatch)

    before = service.readiness_payload()
    probe = service.run_readiness_probe()
    after = service.readiness_payload()

    assert before["ready"] is False
    assert "OCR deep readiness probe has not succeeded." in before["readinessFailures"]
    assert probe["inferenceStatus"] == "success"
    assert after["ready"] is True
    assert after["lastSuccessfulInferenceAt"]


def test_readiness_fails_when_memory_headroom_is_below_minimum(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_OCR_OFFLINE_ONLY", "false")
    service = build_service(monkeypatch, available_mb=1024)

    readiness = service.readiness_payload()

    assert readiness["capacityReady"] is False
    assert readiness["ready"] is False
    assert "OCR memory headroom is below the configured minimum." in readiness["readinessFailures"]


def test_readiness_fails_when_cache_directory_is_not_writable(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AICHECK_OCR_OFFLINE_ONLY", "false")
    monkeypatch.setenv("AICHECK_OCR_PREPROCESS_CACHE_DIR", str(tmp_path / "preprocess"))
    monkeypatch.setenv("AICHECK_OCR_RESULT_CACHE_DIR", str(tmp_path / "results"))
    monkeypatch.setenv("AICHECK_OCR_ENGINE_RESULT_CACHE_DIR", str(tmp_path / "engines"))
    service = build_service(monkeypatch)
    real_named_temporary_file = service_module.tempfile.NamedTemporaryFile

    def fail_for_cache(*args, **kwargs):
        if kwargs.get("dir"):
            raise PermissionError("cache is read-only")
        return real_named_temporary_file(*args, **kwargs)

    monkeypatch.setattr(service_module.tempfile, "NamedTemporaryFile", fail_for_cache)

    readiness = service.readiness_payload()

    assert readiness["cacheWritable"] is False
    assert readiness["ready"] is False
    assert "OCR cache directories are not writable." in readiness["readinessFailures"]


def test_paddleocr_vl_is_not_available_without_transformers(monkeypatch, tmp_path) -> None:
    layout = tmp_path / "layout"
    recognition = tmp_path / "recognition"
    layout.mkdir()
    recognition.mkdir()
    monkeypatch.setenv("AICHECK_ENABLE_PADDLEOCR_VL", "true")
    monkeypatch.setattr(
        engines_module,
        "paddleocr_vl_model_dirs",
        lambda: {"layout": layout, "vl_rec": recognition},
    )
    engine = engines_module.PaddleOcrVlEngine()
    monkeypatch.setattr(engine, "package_available", lambda: True)
    monkeypatch.setattr(engine, "transformers_available", lambda: False)

    assert engine.available() is False
    assert engine.status()["available"] is False


def test_paddleocr_vl_uses_bounded_subprocess_by_default(monkeypatch, tmp_path) -> None:
    layout = tmp_path / "layout"
    recognition = tmp_path / "recognition"
    layout.mkdir()
    recognition.mkdir()
    monkeypatch.setenv("AICHECK_ENABLE_PADDLEOCR_VL", "true")
    monkeypatch.setenv("AICHECK_PADDLEOCR_VL_MEMORY_LIMIT_MB", "12288")
    monkeypatch.setattr(
        engines_module,
        "paddleocr_vl_model_dirs",
        lambda: {"layout": layout, "vl_rec": recognition},
    )
    monkeypatch.setattr(engines_module, "subprocess_package_available", lambda _name: True)
    engine = engines_module.PaddleOcrVlEngine()

    assert engine.status()["executionMode"] == "subprocess"


def test_paddleocr_vl_fails_closed_when_memory_limit_is_unproven(monkeypatch, tmp_path) -> None:
    layout = tmp_path / "layout"
    recognition = tmp_path / "recognition"
    layout.mkdir()
    recognition.mkdir()
    monkeypatch.setenv("AICHECK_ENABLE_PADDLEOCR_VL", "true")
    monkeypatch.setenv("AICHECK_PADDLEOCR_VL_MEMORY_LIMIT_MB", "8192")
    monkeypatch.setenv("AICHECK_PADDLEOCR_VL_MIN_MEMORY_MB", "10240")
    monkeypatch.setattr(
        engines_module,
        "paddleocr_vl_model_dirs",
        lambda: {"layout": layout, "vl_rec": recognition},
    )
    monkeypatch.setattr(engines_module, "subprocess_package_available", lambda _name: True)
    engine = engines_module.PaddleOcrVlEngine()

    status = engine.status()
    assert status["available"] is False
    assert status["capacityReady"] is False
    assert status["executionMode"] == "unavailable"
