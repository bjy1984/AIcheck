"""ruff 棘轮：冻结存量告警，新增即失败（P0 护栏）。

pyproject.toml 里配了 [tool.ruff]，但 ruff 既没进 CI 也没人本地跑——
存量 290+ 条告警让「直接开严格模式」不现实，一次性清完又会制造巨型 diff
淹没真实改动。棘轮是中间态：

    python -m scripts.ruff_baseline            # 校验：新增 (文件, 规则) 或计数上升 → 退出码 1
    python -m scripts.ruff_baseline --update   # 清掉一批存量后重新冻结基线

基线按 {文件: {规则: 数量}} 存储。行号不参与比较——挪动代码不该触发棘轮；
但同一文件同一规则的数量上升会被抓住。基线只许缩，不许涨。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = BACKEND_ROOT / "ruff-baseline.json"
CHECK_TARGETS = ["apps", "libs", "scripts", "tests"]


def current_findings() -> dict[str, dict[str, int]]:
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", *CHECK_TARGETS, "--output-format=json", "--exit-zero"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 and not result.stdout.strip():
        print(result.stderr, file=sys.stderr)
        raise SystemExit(f"ruff 本身运行失败（退出码 {result.returncode}）")
    findings: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for item in json.loads(result.stdout or "[]"):
        file_path = str(Path(item["filename"]).resolve().relative_to(BACKEND_ROOT))
        findings[file_path][str(item["code"])] += 1
    return {file: dict(rules) for file, rules in sorted(findings.items())}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true", help="重新冻结基线（清完一批存量后用）")
    args = parser.parse_args()

    findings = current_findings()
    total = sum(sum(rules.values()) for rules in findings.values())

    if args.update:
        BASELINE_PATH.write_text(
            json.dumps(findings, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"基线已更新：{total} 条存量告警，{len(findings)} 个文件。")
        return 0

    if not BASELINE_PATH.exists():
        print(f"缺少基线文件 {BASELINE_PATH.name}，先跑 --update 生成。", file=sys.stderr)
        return 2

    baseline: dict[str, dict[str, int]] = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    regressions: list[str] = []
    for file_path, rules in findings.items():
        for rule, count in rules.items():
            allowed = int(baseline.get(file_path, {}).get(rule, 0))
            if count > allowed:
                regressions.append(f"  {file_path}: {rule} {allowed} → {count}")

    baseline_total = sum(sum(rules.values()) for rules in baseline.values())
    print(f"当前 {total} 条 / 基线 {baseline_total} 条。")
    if regressions:
        print("\nruff 棘轮触发——以下文件的告警比基线多（新代码不许带新告警）：", file=sys.stderr)
        for line in regressions:
            print(line, file=sys.stderr)
        print("\n修掉新增告警；确属误报再在行内 noqa 并说明原因。", file=sys.stderr)
        return 1
    if total < baseline_total:
        print(f"存量少了 {baseline_total - total} 条——记得跑 --update 收紧基线，别让余量被吃掉。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
