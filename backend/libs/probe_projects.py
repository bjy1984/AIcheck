"""巡检探针建的项目：从项目列表和计数里隐藏（2026-11-04 用户：「写操作审计-勿动-…」能不能删）。

服务器每天 04:10 的写操作巡检（scripts/write_ops_audit.py）建一个临时项目，把六个角色的主线写操作
真做一遍，收尾删除——但项目里有了业务数据，删除按防误删设计退化成归档，于是每天多一个已归档项目
（2026-11-04 生产 81 个项目里 67 个是它）。不硬删：它们的审计记录在平台院的哈希链里，删了会断链。
只是不让它们出现在任何人的项目列表里；按项目 id 直接访问（探针自己要用）不受影响。
"""

from __future__ import annotations

from typing import Any

PROBE_PROJECT_PREFIX = "写操作审计-勿动-"


def is_probe_project(project: dict[str, Any] | None) -> bool:
    if not isinstance(project, dict):
        return False
    return bool(project.get("probe")) or str(project.get("name") or "").startswith(PROBE_PROJECT_PREFIX)
