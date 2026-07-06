from __future__ import annotations

import os
import threading
import time
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field


MODEL_ID = os.getenv("AICHECK_EMBEDDING_MODEL_ID", "Qwen/Qwen3-Embedding-0.6B")
SERVED_MODEL_NAME = os.getenv("AICHECK_EMBEDDING_SERVED_MODEL_NAME", "embedding-default")
API_KEY = os.getenv("INFINITY_API_KEY", "")
HF_HOME = os.getenv("HF_HOME") or os.getenv("TRANSFORMERS_CACHE") or "/app/.cache"
DEVICE = os.getenv("AICHECK_EMBEDDING_DEVICE", "cpu")
NORMALIZE = os.getenv("AICHECK_EMBEDDING_NORMALIZE", "true").lower() != "false"
PRELOAD = os.getenv("AICHECK_EMBEDDING_PRELOAD", "false").lower() == "true"

app = FastAPI(title="AIcheck Local Embedding Service")

_model: Any | None = None
_model_lock = threading.Lock()
_model_error: str | None = None


class EmbeddingRequest(BaseModel):
    model: str = Field(default=SERVED_MODEL_NAME)
    input: str | list[str]


def _authorize(authorization: str | None) -> None:
    if not API_KEY:
        return
    expected = f"Bearer {API_KEY}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="invalid embedding service api key")


def _load_model() -> Any:
    global _model, _model_error
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:
            return _model
        try:
            from sentence_transformers import SentenceTransformer

            _model = SentenceTransformer(MODEL_ID, cache_folder=HF_HOME, device=DEVICE)
            _model_error = None
            return _model
        except Exception as exc:  # pragma: no cover - surfaced through HTTP for ops.
            _model_error = f"{exc.__class__.__name__}: {exc}"
            raise


@app.on_event("startup")
def _startup() -> None:
    if PRELOAD:
        _load_model()


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "model": MODEL_ID,
        "servedModelName": SERVED_MODEL_NAME,
        "modelLoaded": _model is not None,
        "lastModelError": _model_error,
    }


@app.post("/v1/embeddings")
@app.post("/embeddings")
def embeddings(payload: EmbeddingRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    _authorize(authorization)
    inputs = [payload.input] if isinstance(payload.input, str) else payload.input
    if not inputs:
        raise HTTPException(status_code=400, detail="input is required")

    started = time.time()
    try:
        model = _load_model()
        vectors = model.encode(inputs, normalize_embeddings=NORMALIZE, convert_to_numpy=True)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"embedding model unavailable: {exc}") from exc

    data = []
    for index, vector in enumerate(vectors):
        data.append(
            {
                "object": "embedding",
                "index": index,
                "embedding": vector.astype(float).tolist(),
            }
        )
    return {
        "object": "list",
        "data": data,
        "model": payload.model or SERVED_MODEL_NAME,
        "usage": {
            "prompt_tokens": sum(len(item) for item in inputs),
            "total_tokens": sum(len(item) for item in inputs),
        },
        "metadata": {"elapsedSeconds": round(time.time() - started, 3)},
    }
