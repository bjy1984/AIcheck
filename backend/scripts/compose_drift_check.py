#!/usr/bin/env python3
"""生产拓扑漂移检查：让 docker-compose.deploy.yml 真的说了算（issue #12 A-5）。

## 问题不是「13 个 compose 文件」，是没人校验

审计记的是「14 个 compose 文件，生产权威口径不唯一」。今天实测发现更糟：

- `scripts/deploy_to_server.sh` **一次都没引用过任何 compose 文件**——它直接
  docker build + docker run；
- 名为 deploy 的那份声明了 15 个服务，而线上实跑 11 个；
- 线上跑着的 `aicheck-web`（nginx）和 `aicheck-onlyoffice` **压根不在这份文件里**。

也就是说，一个看起来像「部署权威」的文件，既不驱动部署，也不描述现状。
任何人照它去理解生产环境，得到的都是错的图。

这和这轮反复撞见的是同一类问题：**看起来正常的东西其实是空的**。

## 加服务不能解决问题，加校验才能

往 deploy.yml 里补两个服务只是让这份谎言更详细。让它开始有意义的唯一办法，
是有东西定期比对它和现实——漂移出现时说出来。这个脚本就干这件事，
并接进部署后验证。

## 用法

    python -m scripts.compose_drift_check --running aicheck-api,aicheck-web,...

容器清单由调用方给（部署脚本从 docker ps 取），脚本本身不连 docker：
这样它在任何机器上都能跑，也能被单测直接喂数据。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
AUTHORITATIVE_COMPOSE = BACKEND_ROOT / "docker-compose.deploy.yml"

# compose 服务名 → 线上容器名。两套命名不一致是历史遗留：compose 用
# `<角色>-service`，而手工 docker run 用 `aicheck-<角色>`。映射写在这里，
# 而不是靠猜——猜错会把「漂移」和「命名差异」混为一谈，那比不检查更吵。
SERVICE_TO_CONTAINER = {
    "api-service": "aicheck-api",
    "postgres": "aicheck-postgres",
    "redis": "aicheck-redis",
    "minio": "aicheck-minio",
    "temporal-service": "aicheck-temporal",
    "worker-service": "aicheck-worker",
    "business-light-worker-service": "aicheck-worker-business",
    "cpu-heavy-worker-service": "aicheck-worker-cpu-heavy",
    "llm-remote-worker-service": "aicheck-worker-llm",
    "ocr-remote-worker-service": "aicheck-worker-ocr-remote",
    "review-worker-service": "aicheck-review-worker",
    "ocr-service": "aicheck-ocr",
    "embedding-service": "aicheck-embedding",
    "litellm-service": "aicheck-litellm",
    "temporal-ui": "aicheck-temporal-ui",
}

# 声明了但当前部署有意不跑的服务。写在这里是为了区分「有意不跑」和「漂移」——
# 不区分的话每次都报一堆已知差异，报久了就没人看了。
#
# ⚠️ 这份名单的每条理由都必须是**核对过的事实**，不是推断。
#
# 反面教材（2026-08-13 我自己写的）：
#
#     "litellm-service": "镜像不可达，模型直连供应商"
#
# 前半句对——ghcr.io 的镜像境内确实拉不到。后半句是我顺手补的推断，从没验证：
# qwen_runtime.yaml 里 `defaultMode: server`、`allowFallbackToServer: false`，
# 根本没有直连供应商的路径。于是这条理由把一个真警报按掉了，线上四天无模型可用
# 而漂移检查一片安静。**免检名单上一条错误的理由，比不写这份名单更危险。**
INTENTIONALLY_ABSENT = {
    "temporal-ui": "调试用界面，生产不暴露",
    "ocr-service": "OCR 走远端 API，本地不起",
    "embedding-service": "向量化走远端 API，本地不起",
    "worker-service": "已按队列拆成 business/cpu-heavy/llm/ocr 四个专用 worker",
    "review-worker-service": "编排当前是 inline 模式，未启用独立审查 worker",
}

# 已知但**尚未决定怎么办**的漂移。与 INTENTIONALLY_ABSENT 的区别是态度：
# 那份是「就这么定了」，这份是「还没定，先别装作没事」。
#
# 按本仓既有的棘轮做法（ruff_baseline / monolith_baseline）：这份名单只能缩不能涨。
# 新出现的漂移会立刻变红；名单里的项要消失，必须有人真的做了决定并删掉这一条。
#
# 放这里而不是塞回豁免表，是因为豁免表意味着「不用管了」——正是那个态度让
# litellm 缺失静默了四天。
UNRESOLVED_DRIFT = {
    "litellm-service": (
        "生产无模型网关：镜像 ghcr.io/berriai/litellm 境内拉不到，容器从未创建。"
        "而历史上真正跑通的 4 次模型调用走的是 official_api 直连 DashScope"
        "（2026-07-21 至 08-10），说明 compose 声明的拓扑与实际意图本就不一致。"
        "待定：恢复 official_api 直连（需 QWEN_API_KEY），或换可达镜像把网关立起来。"
        "在决定之前，模型相关功能一律降级，降级文案见 libs/review_conversation_fallback。"
    ),
}


def declared_services(compose_path: Path | None = None) -> dict[str, Any]:
    import yaml

    path = compose_path or AUTHORITATIVE_COMPOSE
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return document.get("services") or {}


def drift(running: set[str], services: dict[str, Any]) -> dict[str, list[str]]:
    """比对声明与现实，返回四类差异。

    `missing` 与 `unresolved` 都是「声明了却没跑」，分开是因为处置不同：
    missing 是新问题，要当场查；unresolved 是已登记、等人决定的老问题。
    合成一类的话，老问题会一直盖着新问题。
    """
    exempt = set(INTENTIONALLY_ABSENT) | set(UNRESOLVED_DRIFT)
    expected = {
        SERVICE_TO_CONTAINER.get(name, f"aicheck-{name}")
        for name in services
        if name not in exempt
    }
    declared_all = {SERVICE_TO_CONTAINER.get(name, f"aicheck-{name}") for name in services}
    unresolved = {
        SERVICE_TO_CONTAINER.get(name, f"aicheck-{name}")
        for name in UNRESOLVED_DRIFT
        if name in services
    }
    return {
        # 声明了、也该跑，但没跑——最需要注意的一类
        "missing": sorted(expected - running),
        # 在跑但任何 compose 都没声明——照文件理解生产就会漏掉它们
        "undeclared": sorted(running - declared_all),
        "intentionallyAbsent": sorted(INTENTIONALLY_ABSENT),
        # 已知未决：不当作通过，但也不淹没新问题
        "unresolved": sorted(unresolved - running),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--running", default="", help="逗号分隔的在跑容器名")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="发现任何漂移即退出码 1（默认只报告未声明项，不失败）",
    )
    args = parser.parse_args()

    running = {item.strip() for item in args.running.split(",") if item.strip()}
    if not running:
        print("未提供在跑容器清单（--running），无法比对", file=sys.stderr)
        return 2

    report = drift(running, declared_services())
    print(f"生产拓扑漂移检查 · 在跑 {len(running)} 个容器")
    if report["missing"]:
        print(f"  ✗ 声明了却没在跑：{'、'.join(report['missing'])}")
    if report["undeclared"]:
        print(f"  ! 在跑却没被任何 compose 声明：{'、'.join(report['undeclared'])}")
        print("    照 docker-compose.deploy.yml 理解生产环境会漏掉它们。")
    for name, note in UNRESOLVED_DRIFT.items():
        container = SERVICE_TO_CONTAINER.get(name, f"aicheck-{name}")
        if container in report["unresolved"]:
            print(f"  ⏳ 已知未决：{container}")
            print(f"     {note}")
    if not report["missing"] and not report["undeclared"]:
        print("  ✓ 声明与现实一致（已知未决项除外）")
    return 1 if (args.strict and (report["missing"] or report["undeclared"])) else 0


if __name__ == "__main__":
    raise SystemExit(main())
