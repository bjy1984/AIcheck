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


def test_备用供应商是DeepSeek且模型名显式覆盖(tmp_path: pathlib.Path):
    """通义故障时切 DeepSeek；模型名不覆盖的话备胎会拿通义默认值去打 DeepSeek，直接 400。"""
    env = _build(
        tmp_path,
        {
            "AICHECK_POSTGRES_PASSWORD": "pw",
            "DEEPSEEK_API_KEY": "sk-deepseek",
            "AICHECK_LLM_VISION_API_KEY": "sk-dashscope",
        },
    )
    assert env["AICHECK_LLM_FALLBACK_API_BASE"] == "https://api.deepseek.com"
    assert env["AICHECK_LLM_FALLBACK_API_KEY"] == "sk-deepseek"
    assert env["AICHECK_LLM_FALLBACK_MODEL_REVIEW"] == "deepseek-v4-pro"
    assert env["AICHECK_LLM_FALLBACK_MODEL_PROJECT_REVIEW"] == "deepseek-v4-pro"
    assert env["AICHECK_LLM_FALLBACK_MODEL_COMPARE_FAST"] == "deepseek-v4-flash"
    # 主供应商已是 DashScope，一键分析角色不再需要单独的地址密钥
    assert "AICHECK_LLM_PROJECT_REVIEW_API_BASE" not in env

    without_key = _build(tmp_path, {"AICHECK_POSTGRES_PASSWORD": "pw", "AICHECK_LLM_VISION_API_KEY": "sk-d"})
    assert "AICHECK_LLM_FALLBACK_API_BASE" not in without_key
