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
    status = qwen_configuration_status()
    assert status["configured"] is False
    assert status["ready"] is False
    assert "未配置模型网关地址" in status["reason"]


def test_server_模式配了地址才算就绪(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LITELLM_BASE_URL", "http://127.0.0.1:14001")
    status = qwen_configuration_status()
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
    status = qwen_configuration_status()
    assert status["configured"] is True
    assert status["baseUrl"] == "http://gateway.internal:4000"


def test_official_模式看密钥(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AICHECK_QWEN_CALL_MODE", "official_api")
    assert qwen_configuration_status()["configured"] is False
    monkeypatch.setenv("QWEN_API_KEY", "sk-test")
    status = qwen_configuration_status()
    assert status["configured"] is True
    assert status["ready"] is True


def test_显式给出_ready_键(monkeypatch: pytest.MonkeyPatch):
    """上游 production_runtime_status 用 get("ready", get("configured")) 取值。

    依赖「没有 ready 就读 configured」这条隐式规则，是当初漏检的一环——
    这里显式写出来，别让下一个人再推一遍。
    """
    assert "ready" in qwen_configuration_status()
    monkeypatch.setenv("AICHECK_QWEN_CALL_MODE", "official_api")
    assert "ready" in qwen_configuration_status()


def test_地址要脱敏(monkeypatch: pytest.MonkeyPatch):
    """就绪信息会进接口响应，地址里的 query 可能带密钥。"""
    monkeypatch.setenv("LITELLM_BASE_URL", "http://gw:4000/v1?key=secret-value")
    assert "secret-value" not in qwen_configuration_status()["baseUrl"]


def test_生产就绪总状态会反映模型缺失(monkeypatch: pytest.MonkeyPatch):
    """严格模式下，模型没配好必须让 serviceReadiness 反映出来。"""
    from libs.runtime_readiness import audit_service_configuration_status

    services = audit_service_configuration_status()
    assert services["qwen"]["ready"] is False


def test_通用密钥变量也算配好(monkeypatch: pytest.MonkeyPatch):
    """official_api 走的是 OpenAI 兼容协议，供应商不一定是通义。

    只认 QWEN_API_KEY 的话，用 AICHECK_LLM_API_KEY 配好的部署会被误判成没配——
    又是一个「检查说了假话」。
    """
    monkeypatch.setenv("AICHECK_QWEN_CALL_MODE", "official_api")
    monkeypatch.setenv("AICHECK_LLM_API_KEY", "sk-generic")
    status = qwen_configuration_status()
    assert status["configured"] is True


def test_供应商名按实际地址报而不是按模式(monkeypatch: pytest.MonkeyPatch):
    """provider 会写进 execution 记录，是事后追溯「谁生成了这条结论」的唯一线索。

    原实现只要 mode==official_api 就报 "Model Studio / DashScope"，
    哪怕地址指着 api.deepseek.com——记录会说谎。
    """
    from libs.qwen_runtime import provider_label_for

    assert provider_label_for("official_api", "https://api.deepseek.com/v1") == "DeepSeek"
    assert (
        provider_label_for("official_api", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        == "Model Studio / DashScope"
    )
    # 认不出的主机名原样报出，不编也不吞
    assert provider_label_for("official_api", "https://llm.internal:8443/v1") == "llm.internal"
    assert provider_label_for("server", "https://api.deepseek.com") == "server"
    assert "未配置" in provider_label_for("official_api", "")


def test_模型名可按环境覆盖(monkeypatch: pytest.MonkeyPatch):
    """换供应商必须能换模型名，否则要改仓库 yaml 再重建镜像。"""
    from libs.qwen_runtime import model_names_with_env_overrides

    base = {"review": "qwen3.7-plus", "default": "qwen3.7-plus", "compareFast": "qwen3.6-flash"}
    resolved = model_names_with_env_overrides(
        base, {"AICHECK_LLM_MODEL_REVIEW": "deepseek-v4-pro"}
    )
    assert resolved["review"] == "deepseek-v4-pro"
    assert resolved["default"] == "qwen3.7-plus"  # 没覆盖的保持原样
    assert base["review"] == "qwen3.7-plus", "不能就地改传入的字典"
    # 空值不算覆盖——env 里写个空串不该把模型名清掉
    assert model_names_with_env_overrides(base, {"AICHECK_LLM_MODEL_REVIEW": "  "})["review"] == "qwen3.7-plus"


def test_就绪检查与实际调用用同一份密钥解析(monkeypatch: pytest.MonkeyPatch):
    """两个来源必须给同一个答案。

    2026-08-14 栽过：qwen_runtime_config 按「通用变量优先」解析出了密钥，
    apiKeyConfigured=True、就绪检查报绿；而 _official_chat_sync 里照着
    apiKeyEnv 重读一遍 env，读到空，当场抛错。
    配置说配好了、调用说没配好——合起来就是错的。
    """
    from libs.qwen_runtime import official_api_key, qwen_runtime_config

    monkeypatch.setenv("AICHECK_QWEN_CALL_MODE", "official_api")
    monkeypatch.setenv("AICHECK_LLM_API_KEY", "sk-generic-only")
    config = qwen_runtime_config()
    assert config["apiKeyConfigured"] is True, "配置侧认为配好了"
    assert official_api_key(config) == "sk-generic-only", "调用侧必须拿到同一个"
    assert qwen_configuration_status()["ready"] is True

    # 旧变量单独存在时同样要两边一致
    monkeypatch.delenv("AICHECK_LLM_API_KEY")
    monkeypatch.setenv("QWEN_API_KEY", "sk-legacy")
    assert official_api_key() == "sk-legacy"
    assert qwen_configuration_status()["ready"] is True
