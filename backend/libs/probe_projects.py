"""巡检探针建的项目：从项目列表和计数里隐藏（2026-11-04 用户：「写操作审计-勿动-…」能不能删）。

服务器每天 04:10 的写操作巡检（scripts/write_ops_audit.py）建一个临时项目，把六个角色的主线写操作
真做一遍，收尾删除——但项目里有了业务数据，删除按防误删设计退化成归档，于是每天多一个已归档项目
（2026-11-04 生产 81 个项目里 67 个是它）。不硬删：它们的审计记录在平台院的哈希链里，删了会断链。
只是不让它们出现在任何人的项目列表里；按项目 id 直接访问（探针自己要用）不受影响。
"""

from __future__ import annotations

import re
from typing import Any

PROBE_PROJECT_PREFIX = "写操作审计-勿动-"
PROBE_REGIONS = {"审计专用", "审计专用-已改"}
# 探针建的名字是「前缀 + 8 位 UTC 时间（月日时分）」，地区「审计专用」，改项目那步改成「审计专用-已改」
# （scripts/write_ops_audit.py；2026-11-04 生产 67 个全是后者）。
# 只按前缀认的话，真实项目改成同样开头也会从所有人的列表里消失（2026-11-04 审计），所以名字格式和地区都要对上
_PROBE_NAME = re.compile(rf"^{re.escape(PROBE_PROJECT_PREFIX)}\d{{8}}$")


def is_probe_project(project: dict[str, Any] | None) -> bool:
    if not isinstance(project, dict):
        return False
    if project.get("probe"):
        return True
    return bool(_PROBE_NAME.match(str(project.get("name") or ""))) and project.get("region") in PROBE_REGIONS
