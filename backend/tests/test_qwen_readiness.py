"""模型链路就绪判定：不许再有恒真的健康检查。

背景见 libs/runtime_readiness.qwen_configuration_status 的文档串——
原实现在 server 模式下无条件返回 configured=True，线上四天没有模型可用，
生产就绪报告全程绿灯。
"""

from __future__ import annotations

import pytest

from libs.runtime_readiness import qwen_configuration_status


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch):
    for name in (
        "QWEN_API_KEY",
        "QWEN_API_BASE",
        "LITELLM_BASE_URL",
        "AICHECK_QWEN_SERVER_BASE_URL",
        "AICHECK_QWEN_ALLOW_SERVER_FALLBACK",
    ):
        monkeypatch.delenv(name, raising=False)


def test_server_模式没配地址时不算就绪(monkeypatch: pytest.MonkeyPatch):
    """这就是线上 2026-08-10~08-14 的真实状态。

    旧实现在这里返回 True。LiteLLMClient 的缺省地址 http://litellm-service:4000
    是 compose 内部主机名，生产用 docker run 起容器，必然解析失败。
    """
    status = qwen_configuration_status("server")
    assert status["configured"] is False
    assert status["ready"] is False
    assert "未配置模型网关地址" in status["reason"]


def test_server_模式配了地址才算就绪(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LITELLM_BASE_URL", "http://127.0.0.1:14001")
    status = qwen_configuration_status("server")
    assert status["configured"] is True
    assert status["ready"] is True
    assert status["reason"] == ""
    assert status["baseUrl"] == "http://127.0.0.1:14001"


def test_配置文件文档化的那个变量要真的生效(monkeypatch: pytest.MonkeyPatch):
    """qwen_runtime.yaml 写的是 AICHECK_QWEN_SERVER_BASE_URL。

    修复前它是死配置：写进配置字典、被上报，但没有代码路径读它。运维照文档
    设置后行为毫无变化，调用照旧打向 litellm-service。
    """
    monkeypatch.setenv("AICHECK_QWEN_SERVER_BASE_URL", "http://gateway.internal:4000")
    status = qwen_configuration_status("server")
    assert status["configured"] is True
    assert status["baseUrl"] == "http://gateway.internal:4000"


def test_official_模式看密钥(monkeypatch: pytest.MonkeyPatch):
    assert qwen_configuration_status("official_api")["configured"] is False
    monkeypatch.setenv("QWEN_API_KEY", "sk-test")
    status = qwen_configuration_status("official_api")
    assert status["configured"] is True
    assert status["ready"] is True


def test_显式给出_ready_键():
    """上游 production_runtime_status 用 get("ready", get("configured")) 取值。

    依赖「没有 ready 就读 configured」这条隐式规则，是当初漏检的一环——
    这里显式写出来，别让下一个人再推一遍。
    """
    assert "ready" in qwen_configuration_status("server")
    assert "ready" in qwen_configuration_status("official_api")


def test_地址要脱敏(monkeypatch: pytest.MonkeyPatch):
    """就绪信息会进接口响应，地址里的 query 可能带密钥。"""
    monkeypatch.setenv("LITELLM_BASE_URL", "http://gw:4000/v1?key=secret-value")
    assert "secret-value" not in qwen_configuration_status("server")["baseUrl"]


def test_生产就绪总状态会反映模型缺失(monkeypatch: pytest.MonkeyPatch):
    """严格模式下，模型没配好必须让 serviceReadiness 反映出来。"""
    from libs.runtime_readiness import audit_service_configuration_status

    services = audit_service_configuration_status()
    assert services["qwen"]["ready"] is False
