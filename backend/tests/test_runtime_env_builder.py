"""部署时生成的 env 必须真的带上模型配置。

2026-08-14 踩过：手工往 /home/dev-bjy/aicheck-runtime.env 追加了模型配置，
下一次部署 build_runtime_env.py 重新生成，全丢。容器起来后 readyz 全绿、
登录正常、业务链探针全过——只有模型静默没接上。

生成器此前只存在于服务器上，改坏了也没有 diff 可看。纳入仓库的同时补这层校验。
"""

from __future__ import annotations

import pathlib
import runpy

BUILDER = pathlib.Path(__file__).resolve().parents[1] / "deploy" / "build_runtime_env.py"


def _build(tmp_path: pathlib.Path, secrets: dict[str, str]) -> dict[str, str]:
    """在临时目录里跑一遍生成器，返回它写出的键值。"""
    secret_file = tmp_path / "stack-secrets.env"
    secret_file.write_text("".join(f"{k}={v}\n" for k, v in secrets.items()), encoding="utf-8")
    target = tmp_path / "runtime.env"
    source = BUILDER.read_text(encoding="utf-8")
    source = source.replace(
        'SECRET_FILES = ["/home/dev-bjy/stack-secrets.env", "/home/dev-bjy/aicheck-secrets.env"]',
        f"SECRET_FILES = [{str(secret_file)!r}]",
    )
    source = source.replace(
        'TARGET = pathlib.Path("/home/dev-bjy/aicheck-runtime.env")',
        f"TARGET = pathlib.Path({str(target)!r})",
    )
    patched = tmp_path / "builder.py"
    patched.write_text(source, encoding="utf-8")
    runpy.run_path(str(patched), run_name="__main__")
    return dict(
        line.split("=", 1)
        for line in target.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )


def test_模型配置进得了生成结果(tmp_path: pathlib.Path):
    env = _build(tmp_path, {"AICHECK_POSTGRES_PASSWORD": "pw", "AICHECK_LLM_VISION_API_KEY": "sk-dashscope"})
    assert env["AICHECK_QWEN_CALL_MODE"] == "official_api"
    # 2026-09-03 起全部文本角色统一走通义（DashScope 兼容模式）
    assert env["AICHECK_LLM_API_BASE"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert env["AICHECK_LLM_MODEL_REVIEW"] == "qwen3.7-plus"
    assert env["AICHECK_LLM_MODEL_DEFAULT"] == "qwen3.7-plus"
    assert env["AICHECK_LLM_MODEL_COMPARE_FAST"] == "qwen3.6-flash"
    assert env["AICHECK_LLM_MODEL_PROJECT_REVIEW"] == "qwen3.8-max"
    assert env["AICHECK_LLM_MODEL_DOCUMENT_CLASSIFIER"] == "qwen3.8-max"
    # 角色清单必须和 libs/qwen_runtime.MODEL_ROLE_ENV 对齐（漏配角色曾让 run 卡死）
    for name in ("deepseek",):
        assert not any(name in str(v).lower() for k, v in env.items() if k.startswith("AICHECK_LLM_MODEL_"))


def test_主模型密钥沿用视觉那把DashScope密钥(tmp_path: pathlib.Path):
    """不在凭证文件里复制第二份——轮换时漏改的那份不会报错，只会静默降级。"""
    env = _build(tmp_path, {"AICHECK_POSTGRES_PASSWORD": "pw", "AICHECK_LLM_VISION_API_KEY": "sk-real"})
    assert env["AICHECK_LLM_API_KEY"] == "sk-real"
    assert env["AICHECK_EMBEDDING_API_KEY"] == "sk-real"


def test_没有密钥时不写出空密钥(tmp_path: pathlib.Path):
    """空字符串会让就绪检查以为「配了但是空的」，比干脆没有更难查。"""
    env = _build(tmp_path, {"AICHECK_POSTGRES_PASSWORD": "pw"})
    assert "AICHECK_LLM_API_KEY" not in env


def test_引导口令不进运行时env(tmp_path: pathlib.Path):
    """原有约定：AICHECK_BOOTSTRAP_PASSWORD_* 只用于初始化，不进容器。"""
    env = _build(
        tmp_path,
        {
            "AICHECK_POSTGRES_PASSWORD": "pw",
            "AICHECK_BOOTSTRAP_PASSWORD_ADMIN": "should-not-leak",
        },
    )
    assert not any(k.startswith("AICHECK_BOOTSTRAP_PASSWORD_") for k in env)


def test_部署脚本用的是仓库里的这份生成器():
    """否则改了仓库版本，线上跑的还是服务器上那份手改的副本。"""
    script = (BUILDER.parents[1] / "scripts" / "deploy_to_server.sh").read_text(encoding="utf-8")
    assert "cp deploy/build_runtime_env.py" in script


TOKEN_PLAN = "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
DASHSCOPE = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def test_有TokenPlan密钥时文本切到TokenPlan而视觉留在按量端点(tmp_path: pathlib.Path):
    """三种百炼密钥与端点互不通用；按量端点才有 qwen-vl-max，视觉不该跟着切。"""
    env = _build(tmp_path, {
        "AICHECK_POSTGRES_PASSWORD": "pw",
        "AICHECK_LLM_VISION_API_BASE": DASHSCOPE,
        "AICHECK_LLM_VISION_API_KEY": "sk-ws-payg",
        "AICHECK_TOKEN_PLAN_API_KEY": "sk-sp-token-plan",
    })
    assert env["AICHECK_LLM_API_BASE"] == TOKEN_PLAN
    assert env["AICHECK_LLM_API_KEY"] == "sk-sp-token-plan"
    # 视觉凭证齐备就留在按量端点，用专门的视觉模型
    assert env["AICHECK_LLM_VISION_API_BASE"] == DASHSCOPE
    assert env["AICHECK_LLM_VISION_API_KEY"] == "sk-ws-payg"
    assert env["AICHECK_LLM_MODEL_VISION"] == "qwen-vl-max"
    # 文本模型名不动——它们在 Token Plan 上就是这些名字
    assert env["AICHECK_LLM_MODEL_REVIEW"] == "qwen3.7-plus"
    assert env["AICHECK_LLM_MODEL_PROJECT_REVIEW"] == "qwen3.8-max"


def test_没有按量视觉凭证时视觉才退回TokenPlan(tmp_path: pathlib.Path):
    """只配一半（有密钥没地址）也算不齐，退回 Token Plan，不拼出错配的组合。"""
    env = _build(tmp_path, {
        "AICHECK_POSTGRES_PASSWORD": "pw",
        "AICHECK_LLM_VISION_API_KEY": "sk-ws-payg",
        "AICHECK_TOKEN_PLAN_API_KEY": "sk-sp-token-plan",
    })
    assert env["AICHECK_LLM_VISION_API_BASE"] == TOKEN_PLAN
    assert env["AICHECK_LLM_VISION_API_KEY"] == "sk-sp-token-plan"
    assert env["AICHECK_LLM_MODEL_VISION"] == "qwen3.7-plus"


def test_TokenPlan不接管embeddings(tmp_path: pathlib.Path):
    """Token Plan 没有 text-embedding-v4（404）；向量化必须留在按量端点。"""
    env = _build(tmp_path, {
        "AICHECK_POSTGRES_PASSWORD": "pw",
        "AICHECK_LLM_VISION_API_KEY": "sk-ws-payg",
        "AICHECK_TOKEN_PLAN_API_KEY": "sk-sp-token-plan",
    })
    assert env["AICHECK_EMBEDDING_API_BASE"] == DASHSCOPE
    assert env["AICHECK_EMBEDDING_API_KEY"] == "sk-ws-payg"
    assert env["AICHECK_EMBEDDING_API_KEY"] != env["AICHECK_LLM_API_KEY"]


def test_凭证里显式的embedding密钥优先(tmp_path: pathlib.Path):
    """按量密钥失效后新签一把只给 embeddings 用，不该被视觉那把盖掉。"""
    env = _build(tmp_path, {
        "AICHECK_POSTGRES_PASSWORD": "pw",
        "AICHECK_LLM_VISION_API_KEY": "sk-ws-payg",
        "AICHECK_TOKEN_PLAN_API_KEY": "sk-sp-token-plan",
        "AICHECK_EMBEDDING_API_KEY": "sk-new-payg",
    })
    assert env["AICHECK_EMBEDDING_API_KEY"] == "sk-new-payg"


def test_没有TokenPlan密钥时一切照旧(tmp_path: pathlib.Path):
    env = _build(tmp_path, {"AICHECK_POSTGRES_PASSWORD": "pw", "AICHECK_LLM_VISION_API_KEY": "sk-dashscope"})
    assert env["AICHECK_LLM_API_BASE"] == DASHSCOPE
    assert env["AICHECK_LLM_MODEL_VISION"] == "qwen-vl-max"
    assert "AICHECK_LLM_VISION_API_BASE" not in env


def test_生产开启工位模式(tmp_path: pathlib.Path):
    """没有它，新运行不冻结文件范围，验收 fixture 一份都导不出。"""
    env = _build(tmp_path, {"AICHECK_POSTGRES_PASSWORD": "pw", "AICHECK_LLM_VISION_API_KEY": "sk-dashscope"})
    assert env["AICHECK_WORKSTATIONS_ENABLED"] == "true"


def test_备用供应商是通义按量计费_不再用DeepSeek(tmp_path: pathlib.Path):
    """2026-09-24：Token Plan 限流 429 转 DeepSeek 又 402 欠费；用户要求只用通义。"""
    env = _build(tmp_path, {
        "AICHECK_POSTGRES_PASSWORD": "pw",
        "AICHECK_LLM_VISION_API_BASE": DASHSCOPE,
        "AICHECK_LLM_VISION_API_KEY": "sk-ws-payg",
        "AICHECK_TOKEN_PLAN_API_KEY": "sk-sp-token-plan",
        "DEEPSEEK_API_KEY": "sk-deepseek",
    })
    assert env["AICHECK_LLM_FALLBACK_API_BASE"] == DASHSCOPE
    assert env["AICHECK_LLM_FALLBACK_API_KEY"] == "sk-ws-payg"
    assert "sk-deepseek" not in env.values()
    # 逐角色与主供应商同名；视觉不走文本备胎
    for role in ("REVIEW", "DEFAULT", "PROJECT_REVIEW", "COMPARE_FAST", "DOCUMENT_CLASSIFIER"):
        assert env[f"AICHECK_LLM_FALLBACK_MODEL_{role}"] == env[f"AICHECK_LLM_MODEL_{role}"]
    assert "AICHECK_LLM_FALLBACK_MODEL_VISION" not in env


def test_主供应商已是按量或没有按量密钥时不配备胎(tmp_path: pathlib.Path):
    payg_primary = _build(tmp_path, {"AICHECK_POSTGRES_PASSWORD": "pw", "AICHECK_LLM_VISION_API_KEY": "sk-ws-payg",
                                     "DEEPSEEK_API_KEY": "sk-deepseek"})
    assert "AICHECK_LLM_FALLBACK_API_BASE" not in payg_primary
    token_plan_only = _build(tmp_path, {"AICHECK_POSTGRES_PASSWORD": "pw", "AICHECK_TOKEN_PLAN_API_KEY": "sk-sp-token-plan",
                                        "AICHECK_EMBEDDING_API_KEY": "sk-sp-wrong-kind"})
    assert "AICHECK_LLM_FALLBACK_API_BASE" not in token_plan_only


def test_有Jev密钥才开Jev_且只开走项目开关的阶段(tmp_path: pathlib.Path):
    """2026-09-25：用户批准 GDLNG/ECD202 出境做 Jev 评估。真正外发仍要项目级开关。"""
    base = {"AICHECK_POSTGRES_PASSWORD": "pw", "AICHECK_LLM_VISION_API_KEY": "sk-ws-payg"}
    off = _build(tmp_path, {**base, "AICHECK_JEV_ENABLED": "true", "AICHECK_JEV_DATA_EGRESS_APPROVED": "true"})
    assert not [key for key in off if key.startswith("AICHECK_JEV_")], "没有密钥时凭证里残留的开关也不许透传"
    on = _build(tmp_path, {**base, "AICHECK_JEV_API_KEY": "jev-key"})
    assert on["AICHECK_JEV_ENABLED"] == on["AICHECK_JEV_DATA_EGRESS_APPROVED"] == "true"
    assert on["AICHECK_JEV_PRIMARY_DECISION_ENABLED"] == on["AICHECK_JEV_FACT_CHECK_ENABLED"] == "true"
    for stage in ("DOCUMENT_ROUTING", "SECOND_OPINION", "CLAIM_SHADOW"):
        assert f"AICHECK_JEV_{stage}_ENABLED" not in on, "不走项目开关的阶段不开"
