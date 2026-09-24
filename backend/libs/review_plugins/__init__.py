"""審查插件登記表：核心流程只經這裡呼叫插件，不直接 import 插件實作。

插件只做加強（提示、事實核對、表格行分類、文件歸屬候選），不產生、也不改寫結論。
每個插件宣告它擁有的流程步驟，以及可選的鉤子：
- steps：{步驟鍵: fn(state, review_run, context) -> 步驟結果}
- on_run_created(record, state)：建立審查時補插件自己的欄位（只在選用時呼叫）
- suggestion_fields(review_run) -> dict：節點建議卡上的提示
- prompt_requirements(review_run) -> list[str]、prompt_payload(review_run) -> dict：撰寫發現時的說明

插件實作延遲載入：沒有任何審查選用時，插件模組根本不會被 import。
"""
from __future__ import annotations

from typing import Any

from libs.review_plugins.settings import run_plugin_enabled

# 各插件擁有的步驟鍵（沿用原有鍵名，歷史審查與進行中的工作流不受影響）。
PLUGIN_STEPS = {
    "classify_ocr_tables": "jev",
    "qwen_compose_jev_questions": "jev",
    "jev_decision": "jev",
}


def _plugin(plugin_id: str) -> Any:
    if plugin_id == "jev":
        from libs.review_plugins import jev

        return jev
    raise KeyError(plugin_id)


def _enabled(review_run: dict[str, Any]) -> list[Any]:
    return [_plugin(plugin_id) for plugin_id in sorted(set(PLUGIN_STEPS.values()))
            if run_plugin_enabled(review_run, plugin_id)]


def run_plugin_step(step_key: str, state: dict[str, Any], review_run: dict[str, Any],
                    context: dict[str, Any]) -> dict[str, Any]:
    """流程走到插件的步驟：沒選用就略過，規則結果原樣往下走。"""
    plugin_id = PLUGIN_STEPS[step_key]
    if not run_plugin_enabled(review_run, plugin_id):
        return {"status": "skipped", "reason": "review_plugin_not_enabled", "plugin": plugin_id}
    return _plugin(plugin_id).STEPS[step_key](state, review_run, context)


def on_run_created(record: dict[str, Any], state: dict[str, Any]) -> None:
    for plugin in _enabled(record):
        hook = getattr(plugin, "on_run_created", None)
        if hook:
            hook(record, state)


def suggestion_fields(review_run: dict[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for plugin in _enabled(review_run):
        fields.update(plugin.suggestion_fields(review_run))
    return fields


def prompt_requirements(review_run: dict[str, Any]) -> list[str]:
    return [line for plugin in _enabled(review_run) for line in plugin.prompt_requirements(review_run)]


def prompt_payload(review_run: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for plugin in _enabled(review_run):
        payload.update(plugin.prompt_payload(review_run))
    return payload


def plugin_catalog() -> list[dict[str, Any]]:
    """給工程設定頁：有哪些插件、部署上能不能用（不含任何金鑰或內部設定值）。"""
    from libs.review_plugins.settings import PLUGIN_IDS, PLUGIN_LABELS

    return [{"id": plugin_id, "label": PLUGIN_LABELS[plugin_id],
             "deploymentAvailable": bool(_plugin(plugin_id).deployment_available())}
            for plugin_id in PLUGIN_IDS]
