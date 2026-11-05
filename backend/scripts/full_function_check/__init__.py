"""AIcheck 全功能验收：用例清单＋可执行脚本。入口见 __main__.py。"""

from __future__ import annotations

import importlib

CASE_MODULES = (
    "cases_system",
    "cases_auth",
    "cases_inspection",
    "cases_contractor",
    "cases_ndt",
    "cases_owner",
    "cases_flow",
    "cases_auto",
    "cases_messages",
    "cases_feedback",
    "cases_rules",
    "cases_admin",
    "cases_platform",
    "cases_knowledge",
    "cases_fde",
    "cases_skill",
    "cases_archive",
    "cases_ui",
)


def load_cases() -> list:
    from scripts.full_function_check.base import MODULES, REGISTRY

    for name in CASE_MODULES:
        importlib.import_module(f"scripts.full_function_check.{name}")
    order = list(MODULES)
    # 文档和执行都按模块顺序；同一模块内保持登记顺序（执行依赖这个顺序）。
    return sorted(REGISTRY, key=lambda case: order.index(case.prefix))
