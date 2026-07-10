from __future__ import annotations

import json

import httpx

from libs.embedding_models import embedding_model_spec, embedding_runtime_config
from libs.integrations.embedding_client import EmbeddingClient


def test_local_embedding_uses_infinity_native_paths(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_EMBEDDING_PROVIDER", "local")
    monkeypatch.setenv("AICHECK_EMBEDDING_API_BASE", "http://embedding-service:7997")
    monkeypatch.setenv("AICHECK_EMBEDDING_API_KEY", "local-key")
    monkeypatch.setenv("AICHECK_EMBEDDING_MODEL_ID", "Qwen/Qwen3-Embedding-0.6B")
    monkeypatch.setenv("AICHECK_EMBEDDING_SERVED_MODEL_NAME", "embedding-default")
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.0] * 1024}]})

    client = EmbeddingClient(transport=httpx.MockTransport(handler))

    assert client.health()["status"] == "ok"
    assert len(client.embed_sync(["test"])[0]["embedding"]) == 1024
    assert seen == ["/health", "/embeddings"]


def test_official_qwen_embedding_uses_openai_compatible_endpoint_and_batches(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_EMBEDDING_PROVIDER", "official_api")
    monkeypatch.setenv("AICHECK_EMBEDDING_API_BASE", "https://qwen.example/compatible-mode/v1")
    monkeypatch.setenv("AICHECK_EMBEDDING_API_KEY", "sk-test")
    monkeypatch.setenv("AICHECK_EMBEDDING_MODEL_ID", "text-embedding-v4")
    monkeypatch.setenv("AICHECK_EMBEDDING_SERVED_MODEL_NAME", "text-embedding-v4")
    monkeypatch.setenv("AICHECK_EMBEDDING_BATCH_SIZE", "2")
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read().decode("utf-8"))
        seen.append({"path": request.url.path, "auth": request.headers.get("authorization"), "body": body})
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": index, "embedding": [float(index + 1)] * 1024}
                    for index, _ in enumerate(body["input"])
                ]
            },
        )

    client = EmbeddingClient(transport=httpx.MockTransport(handler))
    vectors = client.embed_sync(["a", "b", "c"])

    assert [item["index"] for item in vectors] == [0, 1, 2]
    assert all(len(item["embedding"]) == 1024 for item in vectors)
    assert [item["path"] for item in seen] == [
        "/compatible-mode/v1/embeddings",
        "/compatible-mode/v1/embeddings",
    ]
    assert all(item["auth"] == "Bearer sk-test" for item in seen)
    assert all(item["body"]["model"] == "text-embedding-v4" for item in seen)
    assert all(item["body"]["dimensions"] == 1024 for item in seen)


def test_official_embedding_runtime_has_independent_index_version(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_EMBEDDING_PROVIDER", "official_api")
    monkeypatch.setenv("AICHECK_EMBEDDING_API_BASE", "https://qwen.example/compatible-mode/v1")
    monkeypatch.setenv("AICHECK_EMBEDDING_MODEL_ID", "text-embedding-v4")
    monkeypatch.setenv("AICHECK_EMBEDDING_SERVED_MODEL_NAME", "text-embedding-v4")

    spec = embedding_model_spec("text-embedding-v4")
    runtime = embedding_runtime_config()

    assert spec["dimensions"] == 1024
    assert spec["indexVersion"] == "knowledge-index-text-embedding-v4@1024"
    assert runtime["providerMode"] == "official_api"
    assert runtime["apiBase"] == "https://qwen.example/compatible-mode/v1"


def test_empty_runtime_environment_does_not_inherit_process_provider(monkeypatch) -> None:
    monkeypatch.setenv("AICHECK_EMBEDDING_PROVIDER", "official_api")
    monkeypatch.setenv("AICHECK_EMBEDDING_MODEL_ID", "text-embedding-v4")

    runtime = embedding_runtime_config({})

    assert runtime["providerMode"] == "local"
    assert runtime["modelId"] == "Qwen/Qwen3-Embedding-0.6B"
    assert runtime["litellmModel"] == "infinity/embedding-default"
