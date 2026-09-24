"""審查插件的開關：按工程設定，建立審查時凍結進任務。

插件（目前只有 Jev）只做加強，不改結論。要不要用、哪個工程用，是工程設定
`project["reviewPlugins"][插件]["enabled"]`；建立審查時凍結成
`reviewRun["reviewPluginSnapshot"]`，之後改設定不影響已建立的審查。

部署層仍有總開關（金鑰、出境批准、主機白名單、各階段開關），由插件自己檢查；
這裡只回答「這個工程／這次審查有沒有選用」。本模組不得 import 任何插件實作。

舊資料相容：沒有明確設定的工程，沿用原來的環境變數白名單
（AICHECK_JEV_PRIMARY_ALLOWED_PROJECTS 等）；沒有快照的舊審查同樣按白名單判斷。
明確設定一律優先。
"""
from __future__ import annotations

import os
from typing import Any

PLUGIN_IDS = ("jev",)
PLUGIN_LABELS = {"jev": "Jev 加强（外部模型，只做提示与事实核对，不改结论）"}
# 各插件在「沒有明確設定」時沿用的舊白名單。
_LEGACY_ALLOWLIST = {"jev": "AICHECK_JEV_PRIMARY_ALLOWED_PROJECTS"}


def _allowlisted(project_id: Any, env_name: str) -> bool:
    allowed = {item.strip() for item in os.getenv(env_name, "").split(",") if item.strip()}
    return bool(project_id) and str(project_id) in allowed


def explicit_project_setting(project: dict[str, Any] | None, plugin_id: str) -> bool | None:
    """工程上明確寫了開或關就回 True/False；沒寫回 None。"""
    settings = (project or {}).get("reviewPlugins")
    entry = settings.get(plugin_id) if isinstance(settings, dict) else None
    enabled = entry.get("enabled") if isinstance(entry, dict) else None
    return enabled if isinstance(enabled, bool) else None


def project_plugin_enabled(project: dict[str, Any] | None, plugin_id: str, *, legacy_env: str | None = None) -> bool:
    """這個工程現在有沒有選用插件（上傳時的文件歸屬等沒有審查任務的場合用）。"""
    explicit = explicit_project_setting(project, plugin_id)
    if explicit is not None:
        return explicit
    return _allowlisted((project or {}).get("id"), legacy_env or _LEGACY_ALLOWLIST[plugin_id])


def freeze_review_plugins(project: dict[str, Any] | None) -> dict[str, Any]:
    """建立審查時的插件快照：{插件: {"enabled": bool, "source": 來源}}。"""
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
    """這次審查有沒有選用插件：以凍結快照為準；沒有快照的舊審查按舊白名單。"""
    snapshot = (run or {}).get("reviewPluginSnapshot")
    if isinstance(snapshot, dict):
        entry = snapshot.get(plugin_id)
        return bool(isinstance(entry, dict) and entry.get("enabled") is True)
    return _allowlisted((run or {}).get("projectId"), legacy_env or _LEGACY_ALLOWLIST[plugin_id])


def any_plugin_enabled(snapshot: dict[str, Any] | None) -> bool:
    return isinstance(snapshot, dict) and any(
        isinstance(entry, dict) and entry.get("enabled") is True for entry in snapshot.values())


def validated_plugin_settings(value: Any) -> dict[str, Any]:
    """工程設定介面收到的 reviewPlugins：只收已知插件與布林 enabled，其餘一律拒絕。"""
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
