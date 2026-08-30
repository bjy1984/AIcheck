"""本地上传文件（local:// 存储键）的根目录解析。

## 为什么需要显式判据

原实现散落各处、一律是 `Path(__file__).parents[N]`，靠目录层数倒推：
本地开发下 `backend/apps/api/routes.py` 往上三层正好是仓库根、`output/` 在其下；
但容器里代码在 `/app/apps/api/routes.py`，往上三层是 `/`，而文件在 `/app/output/`。

**少一层目录，所有 local:// 文件的路径就全部解析失败。**

这个 bug 在 routes.py 修过一次（当时 66 个线上文件预览地址失效），
但 `apps/worker/tasks.py` 漏修，继续用 `parents[3]`——于是 worker 侧
`WORKSPACE_ROOT = /`，13 份实际存在于 `/app/output/` 的资料被判成
「源文件已丢失」（2026-08-29 审计：差点据此让用户重新上传）。

同一个判据必须只有一份实现，两处共用。
"""

from __future__ import annotations

import os
from pathlib import Path


def resolve_workspace_root(start: Path | None = None) -> Path:
    """优先环境变量，其次「哪一层真的有 output/」，最后才回落层数推断。"""
    override = os.getenv("AICHECK_WORKSPACE_ROOT", "").strip()
    if override:
        return Path(override).resolve()
    here = (start or Path(__file__)).resolve()
    for candidate in here.parents:
        if (candidate / "output").is_dir():
            return candidate
    return here.parents[min(3, len(here.parents) - 1)]
