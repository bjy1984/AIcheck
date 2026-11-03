"""审查插件的开关：按工程设定，建立审查时冻结进任务。

插件（目前只有 Jev）只做加强，不改结论。要不要用、哪个工程用，是工程设定
`project["reviewPlugins"][插件]["enabled"]`；建立审查时冻结成
`reviewRun["reviewPluginSnapshot"]`，之后改设定不影响已建立的审查。

部署层仍有总开关（金钥、出境批准、主机白名单、各阶段开关），由插件自己检查；
这里只回答「这个工程／这次审查有没有选用」。本模组不得 import 任何插件实作。

旧资料相容：没有明确设定的工程，沿用原来的环境变数白名单
（AICHECK_JEV_PRIMARY_ALLOWED_PROJECTS 等）；没有快照的旧审查同样按白名单判断。
明确设定一律优先。
"""
from __future__ import annotations

import os
from typing import Any

PLUGIN_IDS = ("jev",)
PLUGIN_LABELS = {"jev": "Jev 加强（外部模型，只做提示与事实核对，不改结论）"}
# 各插件在「没有明确设定」时沿用的旧白名单。
_LEGACY_ALLOWLIST = {"jev": "AICHECK_JEV_PRIMARY_ALLOWED_PROJECTS"}


def _allowlisted(project_id: Any, env_name: str) -> bool:
    allowed = {item.strip() for item in os.getenv(env_name, "").split(",") if item.strip()}
    return bool(project_id) and str(project_id) in allowed


def explicit_project_setting(project: dict[str, Any] | None, plugin_id: str) -> bool | None:
    """工程上明确写了开或关就回 True/False；没写回 None。"""
    settings = (project or {}).get("reviewPlugins")
    entry = settings.get(plugin_id) if isinstance(settings, dict) else None
    enabled = entry.get("enabled") if isinstance(entry, dict) else None
    return enabled if isinstance(enabled, bool) else None


def project_plugin_enabled(project: dict[str, Any] | None, plugin_id: str, *, legacy_env: str | None = None) -> bool:
    """这个工程现在有没有选用插件（上传时的文件归属等没有审查任务的场合用）。"""
    explicit = explicit_project_setting(project, plugin_id)
    if explicit is not None:
        return explicit
    return _allowlisted((project or {}).get("id"), legacy_env or _LEGACY_ALLOWLIST[plugin_id])


def freeze_review_plugins(project: dict[str, Any] | None) -> dict[str, Any]:
    """建立审查时的插件快照：{插件: {"enabled": bool, "source": 来源}}。"""
    snapshot: dict[str, Any] = {}
    for plugin_id in PLUGIN_IDS:
        explicit = explicit_project_setting(project, plugin_id)
        if explicit is not None:
            snapshot[plugin_id] = {"enabled": explicit, "source": "project_setting"}
        elif _allowlisted((project or {}).get("id"), _LEGACY_ALLOWLIST[plugin_id]):
            snapshot[plugin_id] = {"enabled": True, "source": "legacy_allowlist"}
        else:
            snapshot[plugin_id] = {"enabled": False, "source": "default_off"}
    return snapshot


def run_plugin_enabled(run: dict[str, Any] | None, plugin_id: str, *, legacy_env: str | None = None) -> bool:
    """这次审查有没有选用插件：以冻结快照为准；没有快照的旧审查按旧白名单。"""
    snapshot = (run or {}).get("reviewPluginSnapshot")
    if isinstance(snapshot, dict):
        entry = snapshot.get(plugin_id)
        return bool(isinstance(entry, dict) and entry.get("enabled") is True)
    return _allowlisted((run or {}).get("projectId"), legacy_env or _LEGACY_ALLOWLIST[plugin_id])


def any_plugin_enabled(snapshot: dict[str, Any] | None) -> bool:
    return isinstance(snapshot, dict) and any(
        isinstance(entry, dict) and entry.get("enabled") is True for entry in snapshot.values())


def validated_plugin_settings(value: Any) -> dict[str, Any]:
    """工程设定介面收到的 reviewPlugins：只收已知插件与布林 enabled，其余一律拒绝。"""
    if not isinstance(value, dict):
        raise ValueError("reviewPlugins 必须是对象")  # noqa: TRY004 -- 接口按 ValueError 回 400
    settings: dict[str, Any] = {}
    for plugin_id, entry in value.items():
        if plugin_id not in PLUGIN_IDS:
            raise ValueError(f"未知的审查插件：{plugin_id}")
        if not isinstance(entry, dict) or set(entry) - {"enabled"} or not isinstance(entry.get("enabled"), bool):
            raise ValueError(f"审查插件 {plugin_id} 只接受 {{\"enabled\": true|false}}")
        settings[plugin_id] = {"enabled": entry["enabled"]}
    return settings
