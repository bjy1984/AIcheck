from __future__ import annotations

import os
from typing import Any

EMBEDDING_DEFAULT_ALIAS = "embedding-default"
EMBEDDING_DEFAULT_MODEL_ID = "Qwen/Qwen3-Embedding-0.6B"
EMBEDDING_FALLBACK_MODEL_ID = "BAAI/bge-m3"

EMBEDDING_MODEL_REGISTRY: dict[str, dict[str, Any]] = {
    "Qwen/Qwen3-Embedding-0.6B": {
        "modelId": "Qwen/Qwen3-Embedding-0.6B",
        "label": "Qwen3 Embedding 0.6B",
        "provider": "Infinity",
        "role": "recommended_default",
        "dimensions": 1024,
        "contextLength": 32768,
        "parameters": "0.6B",
        "localOnly": True,
        "license": "Apache-2.0",
        "indexVersion": "knowledge-index-qwen3-0.6b@1024",
        "strengths": ["中文工程资料", "长文本检索", "指令化查询", "1024维低迁移成本"],
        "tradeoffs": ["需要重建旧 BGE-M3 索引", "首次切换需要下载新模型缓存"],
    },
    "BAAI/bge-m3": {
        "modelId": "BAAI/bge-m3",
        "label": "BGE-M3",
        "provider": "Infinity",
        "role": "stable_fallback",
        "dimensions": 1024,
        "contextLength": 8192,
        "parameters": "0.57B",
        "localOnly": True,
        "license": "MIT",
        "indexVersion": "knowledge-index-bge-m3@1024",
        "strengths": ["稳定基线", "中文/多语言", "dense/sparse/multi-vector 模型能力", "现有索引兼容"],
        "tradeoffs": ["当前 OpenAI-compatible embedding 链路主要使用 dense 向量", "长文本能力弱于 Qwen3 32K"],
    },
    "Qwen/Qwen3-Embedding-4B": {
        "modelId": "Qwen/Qwen3-Embedding-4B",
        "label": "Qwen3 Embedding 4B",
        "provider": "Infinity/TEI/vLLM",
        "role": "accuracy_candidate",
        "dimensions": 2560,
        "contextLength": 32768,
        "parameters": "4B",
        "localOnly": True,
        "license": "Apache-2.0",
        "indexVersion": "knowledge-index-qwen3-4b@2560",
        "strengths": ["更高召回潜力", "中文和跨语言能力强"],
        "tradeoffs": ["显存/延迟成本高", "维度变化，必须新建索引"],
    },
    "Qwen/Qwen3-Embedding-8B": {
        "modelId": "Qwen/Qwen3-Embedding-8B",
        "label": "Qwen3 Embedding 8B",
        "provider": "Infinity/TEI/vLLM",
        "role": "sota_candidate",
        "dimensions": 4096,
        "contextLength": 32768,
        "parameters": "8B",
        "localOnly": True,
        "license": "Apache-2.0",
        "indexVersion": "knowledge-index-qwen3-8b@4096",
        "strengths": ["最高准确率候选", "复杂语义检索能力强"],
        "tradeoffs": ["资源要求最高", "维度变化，必须新建索引和评估门禁"],
    },
}


def embedding_model_spec(model_id: str | None = None) -> dict[str, Any]:
    selected = str(model_id or os.getenv("AICHECK_EMBEDDING_MODEL_ID") or EMBEDDING_DEFAULT_MODEL_ID).strip()
    spec = EMBEDDING_MODEL_REGISTRY.get(selected) or EMBEDDING_MODEL_REGISTRY[EMBEDDING_DEFAULT_MODEL_ID]
    return dict(spec)


def embedding_runtime_config(env: dict[str, str] | None = None) -> dict[str, Any]:
    source = env or os.environ
    model_id = str(source.get("AICHECK_EMBEDDING_MODEL_ID") or EMBEDDING_DEFAULT_MODEL_ID).strip()
    served_model_name = str(source.get("AICHECK_EMBEDDING_SERVED_MODEL_NAME") or EMBEDDING_DEFAULT_ALIAS).strip()
    engine = str(source.get("AICHECK_EMBEDDING_ENGINE") or "torch").strip()
    spec = embedding_model_spec(model_id)
    return {
        **spec,
        "alias": EMBEDDING_DEFAULT_ALIAS,
        "modelId": model_id,
        "servedModelName": served_model_name,
        "litellmModel": f"infinity/{served_model_name}",
        "engine": engine,
        "apiBase": "http://embedding-service:7997",
        "hotSwappable": True,
        "fallbackModelId": EMBEDDING_FALLBACK_MODEL_ID,
        "switchControl": "AICHECK_EMBEDDING_MODEL_ID + AICHECK_EMBEDDING_SERVED_MODEL_NAME",
        "switchRequires": "重启 embedding-service 并为新模型重建独立索引；业务调用方继续使用 embedding-default",
    }


def embedding_registry_payload() -> list[dict[str, Any]]:
    return [dict(item) for item in EMBEDDING_MODEL_REGISTRY.values()]


def allowed_embedding_model_ids() -> set[str]:
    return set(EMBEDDING_MODEL_REGISTRY)
