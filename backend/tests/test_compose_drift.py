"""生产拓扑漂移检查（issue #12 A-5）。

审计记的是「14 个 compose 文件，生产权威口径不唯一」。实测发现更糟：
deploy_to_server.sh 一次都没引用过任何 compose 文件，而名为 deploy 的那份
既不驱动部署、也不描述现状——线上跑着的 aicheck-web（对外唯一入口）和
aicheck-onlyoffice 压根不在里面。

一个看起来像「部署权威」的文件，照它去理解生产环境得到的是错的图。
往里补服务只是让谎言更详细；让它开始有意义的唯一办法是有东西校验它。
"""

from __future__ import annotations

from scripts.compose_drift_check import (
    INTENTIONALLY_ABSENT,
    SERVICE_TO_CONTAINER,
    declared_services,
    drift,
)

# 2026-08-13 线上实测的容器清单
PRODUCTION_CONTAINERS = {
    "aicheck-api",
    "aicheck-web",
    "aicheck-onlyoffice",
    "aicheck-postgres",
    "aicheck-redis",
    "aicheck-minio",
    "aicheck-temporal",
    "aicheck-worker-business",
    "aicheck-worker-cpu-heavy",
    "aicheck-worker-llm",
    "aicheck-worker-ocr-remote",
}


def test_authoritative_compose_matches_production() -> None:
    """声明与现实必须一致。

    这条红了只有两种情况：线上起了新东西没登记，或者声明的服务挂了。
    两种都该有人知道——而在此之前，两种都没人会发现。
    """
    report = drift(PRODUCTION_CONTAINERS, declared_services())
    assert report["missing"] == [], f"声明了却没在跑：{report['missing']}"
    assert report["undeclared"] == [], f"在跑却没声明：{report['undeclared']}"


def test_gateway_and_office_are_declared() -> None:
    """具体钉住这两个——它们正是审计时缺失的。

    aicheck-web 是浏览器唯一入口，缺了它，读文件的人会以为前端直连 api-service。
    """
    services = declared_services()
    assert "web" in services
    assert services["web"]["container_name"] == "aicheck-web"
    assert "onlyoffice" in services


def test_absent_services_are_explained_not_just_listed() -> None:
    """「有意不跑」要写明理由。

    不区分「有意不跑」和「漂移」，检查每次都会报一堆已知差异——报久了没人看，
    真正的漂移就淹在里面了。
    """
    for name, reason in INTENTIONALLY_ABSENT.items():
        assert name in declared_services(), f"{name} 不在 compose 里，不该出现在豁免表"
        assert len(reason) >= 6, f"{name} 的豁免理由太含糊：{reason}"


def test_service_name_mapping_covers_every_declared_service() -> None:
    """每个服务都要有确定的容器名映射。

    compose 用 `<角色>-service`、线上手工 run 用 `aicheck-<角色>`，两套命名不一致
    是历史遗留。靠猜会把「命名差异」误报成「漂移」，那比不检查更吵。
    """
    services = declared_services()
    unmapped = [
        name
        for name in services
        if name not in SERVICE_TO_CONTAINER
        and (services[name].get("container_name") or "") != f"aicheck-{name}"
    ]
    assert unmapped == [], f"这些服务的容器名靠猜：{unmapped}"
