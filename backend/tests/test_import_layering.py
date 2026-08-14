"""导入拓扑护栏（issue #12 的 A-3）。

修复前：单独 `import libs.review_tools` 直接 ImportError。

    libs.review_tools.r13_tools
      → from libs.review_orchestrator.deterministic_tools import check
        → 先执行 libs/review_orchestrator/__init__.py（导入子模块会先跑包 __init__）
          → dispatcher → execution → runtime_tools
            → from libs.review_tools import BUSINESS_TOOL_DESCRIPTORS  ← 它还没初始化完

调用方必须先 import libs.review_orchestrator 才能用 libs.review_tools——一个没有
任何提示的隐式顺序依赖。三个测试文件里为此写过 `# 先初始化，规避循环导入` 的
规避行，已随本次修复删除。

这类问题不会在整包跑测试时暴露（总有别的模块先把 orchestrator 导进来），
只在「单独导入」时炸——所以必须用子进程逐个真导一遍。
"""

from __future__ import annotations

import subprocess
import sys

import pytest

# 会被独立导入的业务库：脚本、worker、测试都可能只 import 其中一个
STANDALONE_IMPORTABLE = [
    "libs.review_tools",
    "libs.review_orchestrator",
    "libs.review_orchestrator.deterministic_tools",
    "libs.review_orchestrator.runtime_tools",
    "libs.ocr_readiness",
    "libs.business_pack",
    "libs.business_pack.clause_store",
    "libs.db.repository",
    "libs.audit_context",
]


@pytest.mark.parametrize("module", STANDALONE_IMPORTABLE)
def test_module_imports_standalone_in_a_fresh_interpreter(module: str) -> None:
    """每个模块都要能在干净解释器里单独导入。

    用子进程而不是 importlib.reload：同进程里 sys.modules 已被其他测试填满，
    循环导入根本复现不出来——那正是这个 bug 长期存活的原因。
    """
    completed = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert completed.returncode == 0, (
        f"{module} 无法单独导入：\n{completed.stderr[-1500:]}"
    )


def test_orchestrator_package_api_survives_lazy_export() -> None:
    """惰性导出不能改变包的公开 API。"""
    import libs.review_orchestrator as orchestrator

    missing = [name for name in orchestrator.__all__ if not hasattr(orchestrator, name)]
    assert not missing, f"__all__ 里这些名字取不到：{missing}"
    assert callable(orchestrator.dispatch_review_run)
    assert orchestrator.REVIEW_GRAPH_STEPS


def test_unknown_attribute_still_raises_attribute_error() -> None:
    """惰性 __getattr__ 不能把拼错的名字变成静默的 None。"""
    import libs.review_orchestrator as orchestrator

    with pytest.raises(AttributeError):
        orchestrator.this_name_does_not_exist


# ---- 分层方向：libs 不该依赖 apps ----

# libs 是业务库，apps 是入口（HTTP 路由、worker、OCR 服务）。libs → apps 的依赖
# 意味着「业务规则装载即绑定到某个入口」，既没法单独复用，也容易绕出循环导入。
#
# 原有 6 处全部指向 apps.ocr_service。已下沉 utils / profiles /
# welder_certificate_tool 到 libs.ocr（issue #12 A-3），消掉其中 4 处。
#
# 剩下 2 处都在 libs/mineru_ocr.py，卡在体量上：engines.py 3418 行、service.py
# 7207 行且自身有 15 处跨模块依赖，整体搬迁是独立课题，不该塞进这次改动里
# 顺手做——改动越大越难验，而这两个文件是 OCR 主链路。
#
# 棘轮冻住剩余项：**只许减，不许增**。新代码一律不得新增 libs → apps 的模块级导入。
LIBS_TO_APPS_BASELINE = {
    "libs/mineru_ocr.py": {
        "apps.ocr_service.engines",
        "apps.ocr_service.service",
    },
}


def _module_level_libs_to_apps() -> dict[str, set[str]]:
    import ast
    import pathlib

    backend_root = pathlib.Path(__file__).resolve().parents[1]
    found: dict[str, set[str]] = {}
    for path in sorted((backend_root / "libs").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        # 只看模块级：函数内导入是延迟绑定，属于规避环路的既有手法，另行处理
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("apps."):
                key = str(path.relative_to(backend_root))
                found.setdefault(key, set()).add(node.module)
    return found


def test_libs_does_not_gain_new_dependencies_on_apps() -> None:
    """棘轮：libs → apps 的模块级依赖只许减少。"""
    current = _module_level_libs_to_apps()
    added = []
    for file_name, modules in current.items():
        new_modules = modules - LIBS_TO_APPS_BASELINE.get(file_name, set())
        if new_modules:
            added.append(f"{file_name} → {'、'.join(sorted(new_modules))}")
    assert not added, (
        "libs 新增了对 apps 的模块级依赖（业务库不该反向依赖入口层）：" + "；".join(added)
    )


def test_libs_to_apps_baseline_is_not_stale() -> None:
    """清掉一处就要同步收紧基线，否则棘轮会停在虚高的水位上。"""
    current = _module_level_libs_to_apps()
    stale = []
    for file_name, modules in LIBS_TO_APPS_BASELINE.items():
        gone = modules - current.get(file_name, set())
        if gone:
            stale.append(f"{file_name} 已不再依赖 {'、'.join(sorted(gone))}")
    assert not stale, "基线该收紧了：" + "；".join(stale)


def test_business_rule_tooling_does_not_import_http_routes() -> None:
    """审查规则工具不得依赖 API 路由模块——这条是硬规则，不进棘轮。

    修复前 runtime_tools.py 在模块级 import 了 apps.api.cnse_routes 与
    apps.api.std_samr_routes，只为拿四个纯查询函数（无路由装饰器、不碰
    Request/Response）。那些函数已下沉到 libs/integrations/external_registry_queries.py。
    """
    offenders = [
        f"{file_name} → {module}"
        for file_name, modules in _module_level_libs_to_apps().items()
        for module in modules
        if module.startswith("apps.api")
    ]
    assert not offenders, "业务库依赖了 API 路由模块：" + "、".join(offenders)
