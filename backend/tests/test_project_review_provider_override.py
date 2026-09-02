"""一键分析角色可以单独走另一家供应商（role_provider_override）。

## 起因（2026-09-01 线上）

生产主模型 DeepSeek V4 Pro 在同一份一键分析提示词下几乎不写 evidenceRefs，
通过的节点直接回 `supported` + 空 findings；校验器按「零 finding 或全无效即
降级」把整个节点改成「证据不足」，监检工作台一条结果都看不到
（PARUN-4B22A0B9B5D34554：24 条 finding 23 条无效）。同一代码同一提示词，
qwen3.7-plus 那次 66 条里 40 条带原文引用。

本地经 litellm 把 project-review-large 映射到 DashScope 的 qwen3.7-plus，
生产没有 litellm，于是按视觉角色的先例给一键分析角色一组独立地址与密钥
（生产模型名取 qwen3.8-max）。

## 判据

- 两项都配齐时该角色走独立地址与密钥；只配一半退回主供应商
- 别名 project-review-large 与角色名 projectReview 都认
- 其它文本角色不受影响；视觉角色的既有行为不变
- 实际打到别家时 provider 标签按实际地址报，不沿用主供应商的名字
"""

from __future__ import annotations

import httpx

from libs import qwen_runtime


def _set_project_review(monkeypatch, base="https://dashscope.example/v1", key="sk-dashscope"):
    monkeypatch.setenv("AICHECK_LLM_PROJECT_REVIEW_API_BASE", base)
    monkeypatch.setenv("AICHECK_LLM_PROJECT_REVIEW_API_KEY", key)


def test_两项都配齐才切供应商(monkeypatch):
    _set_project_review(monkeypatch)
    assert qwen_runtime.role_provider_override("project-review-large") == (
        "https://dashscope.example/v1",
        "sk-dashscope",
    )
    assert qwen_runtime.role_provider_override("projectReview")[0]


def test_只配一半不生效(monkeypatch):
    monkeypatch.setenv("AICHECK_LLM_PROJECT_REVIEW_API_BASE", "https://dashscope.example/v1")
    monkeypatch.delenv("AICHECK_LLM_PROJECT_REVIEW_API_KEY", raising=False)
    assert qwen_runtime.role_provider_override("project-review-large") == ("", "")
    monkeypatch.delenv("AICHECK_LLM_PROJECT_REVIEW_API_BASE", raising=False)
    monkeypatch.setenv("AICHECK_LLM_PROJECT_REVIEW_API_KEY", "sk-dashscope")
    assert qwen_runtime.role_provider_override("project-review-large") == ("", "")


def test_其它角色不受影响(monkeypatch):
    _set_project_review(monkeypatch)
    for role in ("review-chat", "default-chat", "compare-fast", "review", "document-classifier"):
        assert qwen_runtime.role_provider_override(role) == ("", ""), role


def test_视觉角色的既有行为保持(monkeypatch):
    monkeypatch.setenv("AICHECK_LLM_VISION_API_BASE", "https://vision.example/v1")
    monkeypatch.setenv("AICHECK_LLM_VISION_API_KEY", "sk-vision")
    assert qwen_runtime.vision_override("qwen-vision-review") == ("https://vision.example/v1", "sk-vision")
    assert qwen_runtime.role_provider_override("qwen-vision-review") == ("https://vision.example/v1", "sk-vision")
    assert qwen_runtime.vision_override("project-review-large") == ("", "")


def test_一键分析实际打到DashScope且标签按实际地址报(monkeypatch):
    monkeypatch.setenv("AICHECK_QWEN_CALL_MODE", "official_api")
    monkeypatch.setenv("AICHECK_LLM_API_BASE", "https://api.deepseek.com")
    monkeypatch.setenv("AICHECK_LLM_API_KEY", "sk-deepseek")
    monkeypatch.setenv("AICHECK_LLM_MODEL_PROJECT_REVIEW", "qwen3.8-max")
    monkeypatch.setenv("AICHECK_LLM_MODEL_REVIEW", "deepseek-v4-pro")
    _set_project_review(monkeypatch, base="https://dashscope.aliyuncs.com/compatible-mode/v1")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "{}"}}], "usage": {}},
        )

    client = qwen_runtime.QwenRuntimeClient(transport=httpx.MockTransport(handler))
    project = client.chat_sync([{"role": "user", "content": "hi"}], model="project-review-large")
    review = client.chat_sync([{"role": "user", "content": "hi"}], model="review-chat")

    assert seen[0].url.host == "dashscope.aliyuncs.com"
    assert seen[0].headers["Authorization"] == "Bearer sk-dashscope"
    assert project["model"] == "qwen3.8-max"
    assert project["provider"] == "Model Studio / DashScope"
    assert seen[1].url.host == "api.deepseek.com"
    assert seen[1].headers["Authorization"] == "Bearer sk-deepseek"
    assert review["provider"] == "DeepSeek"
