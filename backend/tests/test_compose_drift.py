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
    UNRESOLVED_DRIFT,
    declared_services,
    drift,
    gateway_exemption,
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


def test_模型网关豁免是查出来的不是写死的() -> None:
    """这条 2026-08-14 走过一整圈：一句没验证的手写理由按掉真警报，静默四天。

    修好之后如果再写一句「已改直连，故不需要网关」，仍然是会过期的手写理由——
    有人把模式改回 server，那句话立刻变成谎言，而检查依旧安静。
    所以豁免要去查生产配置的实际声明。
    """
    from pathlib import Path as _Path
    from tempfile import TemporaryDirectory

    # 当前生产声明为直连 → 网关可以合法缺席
    assert "official_api" in gateway_exemption()
    assert "deepseek" in gateway_exemption()

    with TemporaryDirectory() as tmp:
        # 改回网关模式 → 豁免立刻失效
        gateway = _Path(tmp) / "builder.py"
        gateway.write_text('"AICHECK_QWEN_CALL_MODE": "server",\n', encoding="utf-8")
        assert gateway_exemption(gateway) == ""

        # 声明成直连却把地址指回网关：配置自相矛盾，不给豁免
        contradictory = _Path(tmp) / "c.py"
        contradictory.write_text(
            '"AICHECK_QWEN_CALL_MODE": "official_api",\n'
            '"AICHECK_LLM_API_BASE": "http://litellm-service:4000",\n',
            encoding="utf-8",
        )
        assert gateway_exemption(contradictory) == ""

        # 声明了模式却没有地址，也不算配好
        no_base = _Path(tmp) / "n.py"
        no_base.write_text('"AICHECK_QWEN_CALL_MODE": "official_api",\n', encoding="utf-8")
        assert gateway_exemption(no_base) == ""


def test_unresolved_drift_only_shrinks() -> None:
    """未决漂移是棘轮：只能删，不能加。

    照本仓 ruff_baseline / monolith_baseline 的做法。往这份名单里添东西，
    等于把「暂时不管」变成常态——litellm 缺失静默四天，正是因为它当时被写进了
    「有意不跑」的豁免表，还配了一条我没验证过的理由。
    """
    assert set(UNRESOLVED_DRIFT) == set(), (
        "未决漂移清单变了。删除条目=问题已解决，欢迎；"
        "新增条目=请先确认这真的没法当场解决，再连同决定选项一起写进理由。"
    )
    for name, note in UNRESOLVED_DRIFT.items():
        assert name in declared_services(), f"{name} 不在 compose 里，不该出现在未决表"
        # 未决项必须写明「待定什么」，否则名单本身就成了新的静默处
        assert "待定" in note, f"{name} 没写清楚待谁决定什么：{note}"
        assert len(note) >= 40, f"{name} 的说明太短，读的人无法据此决策"


def test_网关缺席不再报成漂移() -> None:
    """决定已经做出并在线上验证：official_api 直连 DeepSeek。"""
    report = drift(PRODUCTION_CONTAINERS, declared_services())
    assert "aicheck-litellm" not in report["missing"]
    assert "aicheck-litellm" not in report["unresolved"]
    # 但不能靠塞进「有意不跑」的手写名单来实现——那正是当初出事的做法
    assert "litellm-service" not in INTENTIONALLY_ABSENT


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
