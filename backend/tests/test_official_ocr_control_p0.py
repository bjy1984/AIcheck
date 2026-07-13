from __future__ import annotations

import inspect
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from apps.worker import tasks as worker_tasks
from libs import official_ocr_control as control
from libs.runtime_readiness import production_runtime_status


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self._lock = threading.Lock()

    def get(self, key: str):
        with self._lock:
            return self.values.get(key)

    def set(self, key: str, value, *args, **kwargs):
        with self._lock:
            nx = kwargs.get("nx") or "NX" in args
            ex = kwargs.get("ex")
            if ex is None and "EX" in args:
                ex_index = args.index("EX")
                ex = int(args[ex_index + 1])
            if nx and key in self.values:
                return None
            self.values[key] = str(value)
            if ex is not None:
                self.ttls[key] = int(ex)
            return True

    def delete(self, *keys: str):
        with self._lock:
            count = 0
            for key in keys:
                count += int(key in self.values)
                self.values.pop(key, None)
                self.ttls.pop(key, None)
            return count

    def ttl(self, key: str):
        with self._lock:
            return self.ttls.get(key, -1) if key in self.values else -2

    def incr(self, key: str):
        with self._lock:
            value = int(float(self.values.get(key, "0"))) + 1
            self.values[key] = str(value)
            return value

    def expire(self, key: str, seconds: int):
        with self._lock:
            if key in self.values:
                self.ttls[key] = int(seconds)
                return 1
            return 0

    def eval(self, script: str, numkeys: int, *args):
        keys = list(args[:numkeys])
        argv = list(args[numkeys:])
        with self._lock:
            if "ocr-budget-reconcile" in script:
                current = float(self.values.get(keys[0], "0"))
                reserved = float(argv[0])
                actual = float(argv[1])
                limit = float(argv[2])
                updated = max(0.0, current - reserved + actual)
                self.values[keys[0]] = str(updated)
                self.ttls[keys[0]] = int(argv[3])
                if updated > limit:
                    self.values[keys[1]] = str(updated)
                    self.ttls[keys[1]] = int(argv[3])
                    return [0, str(updated), str(max(0.0, limit - updated))]
                return [1, str(updated), str(max(0.0, limit - updated))]
            if "ocr-circuit-before" in script:
                ttl = self.ttls.get(keys[1], -1) if keys[1] in self.values else -2
                generation = int(self.values.get(keys[2], "0"))
                if ttl > 0:
                    return [0, generation, ttl, 0]
                failures = int(self.values.get(keys[0], "0"))
                threshold = int(argv[0])
                if failures < threshold:
                    return [1, generation, 0, 0]
                if keys[3] not in self.values:
                    self.values[keys[3]] = str(argv[1])
                    self.ttls[keys[3]] = int(argv[2])
                    return [1, generation, 0, 1]
                return [0, generation, int(argv[2]), 1]
            if "ocr-circuit-failure" in script:
                generation = int(self.values.get(keys[2], "0")) + 1
                failures = int(self.values.get(keys[0], "0")) + 1
                self.values[keys[2]] = str(generation)
                self.values[keys[0]] = str(failures)
                self.values[keys[4]] = str(argv[0])
                ttl = int(argv[2])
                self.ttls[keys[0]] = ttl
                self.ttls[keys[2]] = ttl
                self.ttls[keys[4]] = ttl
                if argv[1] and self.values.get(keys[3]) == str(argv[1]):
                    self.values.pop(keys[3], None)
                    self.ttls.pop(keys[3], None)
                if failures >= int(argv[3]):
                    self.values[keys[1]] = str(generation)
                    self.ttls[keys[1]] = int(argv[4])
                return [generation, failures]
            if "ocr-circuit-success" in script:
                generation = int(self.values.get(keys[2], "0"))
                if generation != int(argv[0]):
                    return 0
                if keys[1] in self.values and self.ttls.get(keys[1], -1) > 0:
                    return 0
                if int(argv[2]) == 1 and self.values.get(keys[3]) != str(argv[1]):
                    return 0
                for key in (keys[0], keys[1], keys[3], keys[4]):
                    self.values.pop(key, None)
                    self.ttls.pop(key, None)
                return 1
            if "local current = tonumber(redis.call('get', KEYS[1]) or '0')" in script:
                current = float(self.values.get(keys[0], "0"))
                requested = float(argv[0])
                limit = float(argv[1])
                if current + requested > limit:
                    return [-1, str(current)]
                updated = current + requested
                self.values[keys[0]] = str(updated)
                self.ttls[keys[0]] = int(argv[2])
                return [1, str(updated)]
            raise AssertionError("unexpected script")


def configure_fake_redis(monkeypatch, fake: FakeRedis) -> None:
    monkeypatch.setenv("AICHECK_REDIS_URL", "redis://fake/0")
    monkeypatch.setenv("AICHECK_OCR_DISTRIBUTED_CONTROL", "true")
    monkeypatch.setattr(control, "_redis_client", lambda: fake)


def test_cost_reconcile_records_unavoidable_overrun_and_blocks_future_reserve(monkeypatch) -> None:
    fake = FakeRedis()
    configure_fake_redis(monkeypatch, fake)

    control.reserve_official_ocr_cost("DOC-1", 0.1, 1.0)
    result = control.reconcile_official_ocr_cost("DOC-1", reserved=0.1, actual=1.4, limit=1.0)

    assert result["withinLimit"] is False
    assert result["current"] == pytest.approx(1.4)
    assert result["remaining"] == 0
    with pytest.raises(control.OfficialOcrBudgetExceeded):
        control.reserve_official_ocr_cost("DOC-1", 0.01, 1.0)


def test_concurrent_cost_reservations_do_not_cross_hard_limit(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_OCR_DISTRIBUTED_CONTROL", "false")
    monkeypatch.setattr(control, "_LOCAL_BUDGETS", {})

    def reserve() -> bool:
        try:
            control.reserve_official_ocr_cost("DOC-CONCURRENT", 0.25, 1.0)
            return True
        except control.OfficialOcrBudgetExceeded:
            return False

    with ThreadPoolExecutor(max_workers=12) as executor:
        accepted = list(executor.map(lambda _: reserve(), range(12)))

    assert sum(accepted) == 4
    assert control._LOCAL_BUDGETS["DOC-CONCURRENT"] == pytest.approx(1.0)


def test_stale_success_cannot_close_new_circuit_generation(monkeypatch) -> None:
    fake = FakeRedis()
    configure_fake_redis(monkeypatch, fake)
    breaker = control.RedisOfficialOcrCircuitBreaker(1, 60)

    stale_lease = breaker.before_call()
    breaker.failure("HTTP_503", stale_lease)
    breaker.success(stale_lease)

    status = breaker.public_status()
    assert status["open"] is True
    assert status["generation"] == 1
    assert status["failureCount"] == 1


def test_only_one_half_open_probe_owns_the_lease(monkeypatch) -> None:
    fake = FakeRedis()
    configure_fake_redis(monkeypatch, fake)
    breaker = control.RedisOfficialOcrCircuitBreaker(1, 1)
    initial = breaker.before_call()
    breaker.failure("HTTP_503", initial)
    fake.values.pop(f"{breaker.prefix}:open", None)
    fake.ttls.pop(f"{breaker.prefix}:open", None)

    first_probe = breaker.before_call()
    assert first_probe.half_open is True
    with pytest.raises(control.OfficialOcrControlUnavailable):
        breaker.before_call()


def test_official_worker_retry_uses_runtime_max_attempts() -> None:
    source = inspect.getsource(worker_tasks.ocr_pipeline_official_extract.run)

    assert 'runtime["official"].get("maxAttempts")' in source
    assert "retry_index + 1 < max_attempts" in source


def test_strict_runtime_readiness_uses_ocr_ready_not_only_configured(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_STRICT_PRODUCTION", "true")
    monkeypatch.setattr(
        "libs.runtime_readiness.workflow_schema_status",
        lambda: {"ready": True, "required": False, "tableCount": 0, "missingTables": []},
    )
    monkeypatch.setattr(
        "libs.runtime_readiness.material_review_asset_status",
        lambda: {"ready": True, "version": "v1", "itemCount": 1, "sourceSha256": "sha256:x"},
    )
    monkeypatch.setattr(
        "libs.runtime_readiness.audit_service_configuration_status",
        lambda: {
            "ocr": {"configured": True, "ready": False},
            "qwen": {"configured": True},
            "embedding": {"configured": True},
            "temporal": {"configured": True},
        },
    )

    status = production_runtime_status()

    assert status["runtimeReady"] is False
