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
    env = _build(tmp_path, {"AICHECK_POSTGRES_PASSWORD": "pw", "DEEPSEEK_API_KEY": "sk-deepseek"})
    assert env["AICHECK_QWEN_CALL_MODE"] == "official_api"
    assert env["AICHECK_LLM_API_BASE"] == "https://api.deepseek.com"
    # 模型名必须显式写死：配置文件默认是 qwen3.7-plus，DeepSeek 不认
    assert env["AICHECK_LLM_MODEL_REVIEW"].startswith("deepseek-")
    assert env["AICHECK_LLM_MODEL_COMPARE_FAST"].startswith("deepseek-")


def test_模型密钥沿用凭证文件里的那一份(tmp_path: pathlib.Path):
    """不在凭证文件里复制第二份——轮换时漏改的那份不会报错，只会静默降级。"""
    env = _build(tmp_path, {"AICHECK_POSTGRES_PASSWORD": "pw", "DEEPSEEK_API_KEY": "sk-real"})
    assert env["AICHECK_LLM_API_KEY"] == "sk-real"


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
