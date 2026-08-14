from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

GIB = 1024**3


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _usage_percent(total: int, free: int) -> float:
    return round(((total - free) / total) * 100, 2) if total > 0 else 100.0


def swap_capacity(path: Path = Path("/proc/swaps")) -> dict[str, Any]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[1:]
    except OSError:
        lines = []
    total_kib = 0
    devices: list[dict[str, Any]] = []
    for line in lines:
        columns = line.split()
        if len(columns) < 5:
            continue
        try:
            size_kib = int(columns[2])
            used_kib = int(columns[3])
        except ValueError:
            continue
        total_kib += size_kib
        devices.append(
            {
                "name": columns[0],
                "type": columns[1],
                "sizeBytes": size_kib * 1024,
                "usedBytes": used_kib * 1024,
                "priority": columns[4],
            }
        )
    return {"totalBytes": total_kib * 1024, "devices": devices}


def disk_capacity_status(path: str | Path | None = None) -> dict[str, Any]:
    target = Path(path or os.getenv("AICHECK_CAPACITY_GATE_PATH") or "/")
    usage = shutil.disk_usage(target)
    used_percent = _usage_percent(usage.total, usage.free)
    warning_percent = _env_float("AICHECK_DISK_WARNING_PERCENT", 80)
    pause_percent = _env_float("AICHECK_DISK_PAUSE_PERCENT", 88)
    fail_percent = _env_float("AICHECK_DISK_FAIL_PERCENT", 92)
    release_target_percent = _env_float("AICHECK_DISK_RELEASE_TARGET_PERCENT", 70)
    release_min_free_gib = _env_float("AICHECK_DISK_RELEASE_MIN_FREE_GIB", 25)
    operational_min_free_gib = _env_float("AICHECK_DISK_OPERATIONAL_MIN_FREE_GIB", 5)
    free_gib = round(usage.free / GIB, 2)
    readiness_ready = used_percent < fail_percent and free_gib >= operational_min_free_gib
    dispatch_allowed = used_percent < pause_percent and free_gib >= operational_min_free_gib
    if not readiness_ready:
        status = "failed"
    elif not dispatch_allowed:
        status = "paused"
    elif used_percent >= warning_percent:
        status = "warning"
    else:
        status = "ready"
    return {
        "path": str(target),
        "status": status,
        "totalBytes": usage.total,
        "usedBytes": usage.used,
        "freeBytes": usage.free,
        "freeGiB": free_gib,
        "usedPercent": used_percent,
        "dispatchAllowed": dispatch_allowed,
        "readinessReady": readiness_ready,
        "releaseTargetPassed": used_percent < release_target_percent and free_gib >= release_min_free_gib,
        "thresholds": {
            "warningPercent": warning_percent,
            "pausePercent": pause_percent,
            "failPercent": fail_percent,
            "releaseTargetPercent": release_target_percent,
            "releaseMinFreeGiB": release_min_free_gib,
            "operationalMinFreeGiB": operational_min_free_gib,
        },
    }


def cpu_heavy_dispatch_status() -> dict[str, Any]:
    enabled = str(os.getenv("AICHECK_CPU_HEAVY_DISK_GATE") or "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    capacity = disk_capacity_status()
    return {
        "enabled": enabled,
        "allowed": not enabled or bool(capacity["dispatchAllowed"]),
        "statusReason": "capacity_ready" if not enabled or capacity["dispatchAllowed"] else "disk_capacity_paused",
        "capacity": capacity,
    }

