"""巨石与直访棘轮：不许再长（issue #12 A-2 / F-2）。

## 为什么是棘轮而不是拆分

audit-reports 在 2026-08-07 记下 routes.py 30,490 行、repo.state 直写 82 处。
2026-08-13 复量：**32,226 行、直写 109 处**——六天里又长了 1,736 行、27 处直写，
其中相当一部分是这几天修 bug 时我自己加的。

一次性拆一个 32k 行、368 路由的文件是多日工程，而且会制造一个淹没所有真实改动
的巨型 diff。棘轮是中间态，和这个项目已经在用的 ruff 棘轮同一个思路：

    python -m scripts.monolith_baseline            # 校验：任一指标上升 → 退出码 1
    python -m scripts.monolith_baseline --update   # 拆走一部分后重新冻结

它不解决巨石，它只保证巨石不再变大。**止血先于治病**——不止血的话，等真的
排期去拆的时候，要拆的东西比今天更多。

## 为什么直写比行数更要紧

`repo.state["x"].append(...)` 绕过 repository 方法，也就绕过了 revision 递增、
审计留痕和字段校验。行数只是难读，直写是会出错。所以两个指标都冻，但直写这项
的阈值卡得更死。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
BASELINE_PATH = BACKEND_ROOT / "monolith-baseline.json"

# 直写 repo.state：绕过 repository 方法，也就绕过 revision / 审计 / 校验
DIRECT_WRITE_PATTERN = re.compile(
    r"""repo\.state\[[^\]]+\]\s*(?:
        \.(?:append|insert|extend|pop|remove|clear|update|setdefault)\b
        | =(?!=)
    )""",
    re.VERBOSE,
)
DIRECT_ACCESS_PATTERN = re.compile(r"repo\.state\[")

# 被盯住的文件。加新条目要有理由：棘轮盯太多东西就没人看了。
#
# FdeConsole.vue 是 2026-08-14 补进来的，理由是它当时 29,203 行——**比
# routes.py 还大**（script 10,875 / template 10,179 / style 8,147），
# 而全仓最大的那个文件此前完全不在任何护栏里。
#
# 被盯住不等于变好，只等于不再变坏。它现在还很大，往下拆要先把
# reactive 状态与纯整形分开，那是另一件事。
TRACKED_FILES = (
    "backend/apps/api/routes.py",
    "backend/libs/review_orchestrator/execution.py",
    "frontend/src/views/AICheck/Workbench.vue",
    "frontend/src/views/AICheck/FdeConsole.vue",
)


def measure_file(path: Path) -> dict[str, int]:
    """量一个文件。

    行数不含空行与纯注释行：ruff --fix 会把一行长导入拆成六行，那是格式化噪音，
    不是巨石长大。第一次冻基线后就被这种噪音误报过一次——棘轮报的必须是
    「代码变多了」，报格式变动只会让人学会忽略它。
    """
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    code_lines = [
        line
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith(("#", "//"))
    ]
    metrics = {"lines": len(code_lines)}
    if path.suffix == ".py":
        metrics["directStateAccess"] = len(DIRECT_ACCESS_PATTERN.findall(text))
        metrics["directStateWrite"] = len(DIRECT_WRITE_PATTERN.findall(text))
    return metrics


def current_metrics() -> dict[str, dict[str, int]]:
    return {
        relative: measure_file(REPO_ROOT / relative)
        for relative in TRACKED_FILES
        if (REPO_ROOT / relative).exists()
    }


def load_baseline() -> dict[str, dict[str, int]]:
    if not BASELINE_PATH.exists():
        print(f"缺少基线文件 {BASELINE_PATH.name}，先跑 --update 生成。", file=sys.stderr)
        raise SystemExit(2)
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def write_baseline(metrics: dict[str, dict[str, int]]) -> None:
    BASELINE_PATH.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true", help="重新冻结基线（只在指标下降后用）")
    args = parser.parse_args()

    metrics = current_metrics()
    if args.update:
        write_baseline(metrics)
        print(f"基线已更新 → {BASELINE_PATH.name}")
        for name, values in sorted(metrics.items()):
            print(f"  {name}: {values}")
        return 0

    baseline = load_baseline()
    grown: list[str] = []
    shrunk: list[str] = []
    for name, values in sorted(metrics.items()):
        for metric, value in sorted(values.items()):
            was = int((baseline.get(name) or {}).get(metric, value))
            if value > was:
                grown.append(f"  {name} · {metric}: {was} → {value}（+{value - was}）")
            elif value < was:
                shrunk.append(f"  {name} · {metric}: {was} → {value}（-{was - value}）")

    if shrunk:
        print("以下指标下降了，记得跑 --update 把成果冻进基线：")
        print("\n".join(shrunk))
    if grown:
        print("\n巨石棘轮触发——这些文件不许再长：", file=sys.stderr)
        print("\n".join(grown), file=sys.stderr)
        print(
            "\n新增业务代码请放进独立模块，并走 repository 方法而不是直接改 repo.state。\n"
            "直写会绕过 revision 递增、审计留痕和字段校验——那不是难读，是会出错。",
            file=sys.stderr,
        )
        return 1
    if not shrunk:
        print("巨石棘轮：无增长。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
