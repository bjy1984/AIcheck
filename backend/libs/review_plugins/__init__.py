"""审查插件登记表：核心流程只经这里呼叫插件，不直接 import 插件实作。

插件只做加强（提示、事实核对、表格行分类、文件归属候选），不产生、也不改写结论。
每个插件宣告它拥有的流程步骤，以及可选的钩子：
- steps：{步骤键: fn(state, review_run, context) -> 步骤结果}
- on_run_created(record, state)：建立审查时补插件自己的栏位（只在选用时呼叫）
- suggestion_fields(review_run) -> dict：节点建议卡上的提示
- prompt_requirements(review_run) -> list[str]、prompt_payload(review_run) -> dict：撰写发现时的说明

插件实作延迟载入：没有任何审查选用时，插件模组根本不会被 import。
"""
from __future__ import annotations

from typing import Any

from libs.review_plugins.settings import run_plugin_enabled

# 各插件拥有的步骤键（沿用原有键名，历史审查与进行中的工作流不受影响）。
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
    """流程走到插件的步骤：没选用就略过，规则结果原样往下走。"""
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
    """给工程设定页：有哪些插件、部署上能不能用（不含任何金钥或内部设定值）。"""
    from libs.review_plugins.settings import PLUGIN_IDS, PLUGIN_LABELS

    return [{"id": plugin_id, "label": PLUGIN_LABELS[plugin_id],
             "deploymentAvailable": bool(_plugin(plugin_id).deployment_available())}
            for plugin_id in PLUGIN_IDS]
