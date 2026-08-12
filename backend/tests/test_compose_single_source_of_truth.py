"""compose 口径一致性（issue #12 的 A-5）。

14 个 compose 文件里同一个服务常在多处定义。多处定义本身不是问题——dev 与 prod
本来就该用不同镜像、不同端口，那是正当的环境差异。问题是**同一口径内部的漂移**：
谁也不会去 diff 两个 YAML，漂移的那一份要等到用它跑起来才暴露。

这里只钉两条能明确判对错的规则，不追求把 14 个文件合成 base + overlay ——
那是结构性重构，收益不在「防漂移」而在「少读几个文件」，风险与收益不匹配。
"""

from __future__ import annotations

import pathlib

import yaml

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]

# docker-compose.yml 是本地开发口径（api/worker/review-worker 一律 Dockerfile）；
# docker-compose.deploy.yml 是生产口径（一律 Dockerfile.server，部署脚本也用它）。
# 两者用不同镜像是设计，不是漂移——按文件区分，不做全局比较。
DEV_COMPOSE = "docker-compose.yml"
PRODUCTION_COMPOSE = "docker-compose.deploy.yml"
PRODUCTION_DOCKERFILE = "Dockerfile.server"
BACKEND_RUNTIME_SERVICES = {
    "api-service",
    "review-worker-service",
    "worker-service",
    # 迁移跑的是同一份后端代码，镜像不一致等于用另一套依赖改生产库
    "workflow-migrate",
}


def load(path: pathlib.Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def services_of(file_name: str) -> dict:
    return load(BACKEND_ROOT / file_name).get("services") or {}


def dockerfile_of(service: dict) -> str | None:
    build = service.get("build")
    return str(build.get("dockerfile")) if isinstance(build, dict) and build.get("dockerfile") else None


def test_all_compose_files_parse() -> None:
    """先保证都能解析——否则后面的规则会因为读不到而假通过。"""
    files = sorted(BACKEND_ROOT.glob("docker-compose*.yml"))
    assert files, "没找到任何 compose 文件，路径大概变了"
    for path in files:
        assert isinstance(load(path), dict), f"{path.name} 解析结果不是映射"


def test_production_compose_builds_every_backend_service_from_the_server_image() -> None:
    """生产 compose 里的后端服务必须全部用 Dockerfile.server。

    混进一个 Dockerfile 就意味着那个服务跑在与其他服务不同的依赖集上，
    而且不会有任何症状——直到某个只在生产镜像里装的依赖缺失。
    """
    offenders = [
        f"{name} 用 {dockerfile_of(service)}"
        for name, service in services_of(PRODUCTION_COMPOSE).items()
        if name in BACKEND_RUNTIME_SERVICES
        and dockerfile_of(service)
        and dockerfile_of(service) != PRODUCTION_DOCKERFILE
    ]
    assert not offenders, (
        f"{PRODUCTION_COMPOSE} 中以下服务未用 {PRODUCTION_DOCKERFILE}：" + "、".join(offenders)
    )


def test_each_compose_file_is_internally_consistent_about_its_backend_image() -> None:
    """单个文件内部不能一半 Dockerfile、一半 Dockerfile.server。

    跨文件的差异是环境差异（正当），同一文件内的差异没有正当解释——
    要么是复制粘贴时漏改，要么是有人只改了一处。
    """
    inconsistent = []
    for path in sorted(BACKEND_ROOT.glob("docker-compose*.yml")):
        used = {
            dockerfile_of(service)
            for name, service in (load(path).get("services") or {}).items()
            if name in BACKEND_RUNTIME_SERVICES and dockerfile_of(service)
        }
        if len(used) > 1:
            inconsistent.append(f"{path.name} 混用了 {sorted(used)}")
    assert not inconsistent, "以下文件内部后端镜像口径不一致：" + "；".join(inconsistent)


def test_every_routed_queue_has_a_consumer_in_the_production_compose() -> None:
    """路由表里的每个队列，生产部署都必须有 worker 消费。

    没有消费者的队列不会报错——任务投进去，Redis 里堆着，永远不执行。
    调用方拿到的是「已排队」，用户看到的是「一直在处理中」。这是最贵的一类
    失败：既没有异常，也没有日志，只有一个永远不完成的任务。

    实测发现 business.light / cpu.heavy / llm.remote 三个队列在
    docker-compose.deploy.yml 里无人消费，涉及 OCR 证据融合、印章识别、
    知识切片与向量化、AI 复核、对话式审查等 12 个任务。
    """
    import re

    routes_source = (BACKEND_ROOT / "apps/worker/celery_app.py").read_text(encoding="utf-8")
    routed: dict[str, list[str]] = {}
    for match in re.finditer(r'"(apps\.worker\.tasks\.[\w_]+)":\s*\{"queue":\s*"([\w.]+)"', routes_source):
        routed.setdefault(match.group(2), []).append(match.group(1).rsplit(".", 1)[-1])
    assert routed, "没解析出任何路由——celery_app.py 的写法大概变了，规则要跟着改"

    consumed: set[str] = set()
    for service in services_of(PRODUCTION_COMPOSE).values():
        queues = re.search(r"-Q\s+([\w.,]+)", str(service.get("command") or ""))
        if queues:
            consumed |= set(queues.group(1).split(","))

    orphaned = {queue: tasks for queue, tasks in routed.items() if queue not in consumed}
    detail = "；".join(f"{queue} ← {'、'.join(tasks)}" for queue, tasks in sorted(orphaned.items()))
    assert not orphaned, f"以下队列在 {PRODUCTION_COMPOSE} 里无人消费，任务会静默堆积：{detail}"
