"""视觉角色可以走另一家供应商。

## 起因（2026-08-15 线上）

印章读字第一次实跑，模型返回 HTTP 400：

    unknown variant `image_url`, expected `text`

生产主模型是 DeepSeek，它的 chat.completions **不接受图片**。而配置里
`AICHECK_LLM_MODEL_VISION` 写着 `deepseek-v4-pro`——声明了一个不存在的能力。

这类配置的危害在于失败点离成因很远：报错出现在印章读字那行，看起来像
新功能自己坏了，而真正的问题是「这台机器上根本没有视觉模型」。

## 判据

- 视觉角色在两项都配齐时走独立地址与密钥
- 只配一半退回主供应商——不能拼出「新地址 + 旧密钥」这种组合
- 非视觉角色一律不受影响
"""

from __future__ import annotations

from libs import qwen_runtime


def test_两项都配齐才切供应商(monkeypatch):
    monkeypatch.setenv("AICHECK_LLM_VISION_API_BASE", "https://dashscope.example/v1")
    monkeypatch.setenv("AICHECK_LLM_VISION_API_KEY", "sk-vision")
    base, key = qwen_runtime.vision_override("qwen-vision-review")
    assert base == "https://dashscope.example/v1"
    assert key == "sk-vision"


def test_只配地址不生效(monkeypatch):
    monkeypatch.setenv("AICHECK_LLM_VISION_API_BASE", "https://dashscope.example/v1")
    monkeypatch.delenv("AICHECK_LLM_VISION_API_KEY", raising=False)
    assert qwen_runtime.vision_override("qwen-vision-review") == ("", "")


def test_只配密钥不生效(monkeypatch):
    monkeypatch.delenv("AICHECK_LLM_VISION_API_BASE", raising=False)
    monkeypatch.setenv("AICHECK_LLM_VISION_API_KEY", "sk-vision")
    assert qwen_runtime.vision_override("qwen-vision-review") == ("", "")


def test_其它角色不受影响(monkeypatch):
    monkeypatch.setenv("AICHECK_LLM_VISION_API_BASE", "https://dashscope.example/v1")
    monkeypatch.setenv("AICHECK_LLM_VISION_API_KEY", "sk-vision")
    for role in ("review-chat", "default-chat", "compare-fast", "review"):
        assert qwen_runtime.vision_override(role) == ("", ""), role


def test_别名也认(monkeypatch):
    """调用处用的是别名 qwen-vision-review，配置里的角色名是 visionReview。"""
    monkeypatch.setenv("AICHECK_LLM_VISION_API_BASE", "https://dashscope.example/v1")
    monkeypatch.setenv("AICHECK_LLM_VISION_API_KEY", "sk-vision")
    assert qwen_runtime.vision_override("visionReview")[0]
    assert qwen_runtime.vision_override("qwen-vision-review")[0]


def test_部署配置不再把视觉指向不支持图片的模型():
    source = open(
        "deploy/build_runtime_env.py", encoding="utf-8"
    ).read()
    line = next(
        item for item in source.splitlines() if "AICHECK_LLM_MODEL_VISION" in item and ":" in item
    )
    assert "deepseek" not in line.lower(), "视觉模型又指回了不接受图片的供应商"
