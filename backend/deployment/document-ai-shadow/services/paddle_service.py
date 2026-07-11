from __future__ import annotations

import asyncio
import json
import os
import secrets
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from paddleocr import PaddleOCRVL


MODEL_PATH = os.environ["PADDLE_VL_MODEL_PATH"]
MODEL_ROOT = os.getenv("PADDLE_AUX_MODEL_ROOT", "/usrdata/aicheck-models/paddlex/official_models")
API_KEY = os.getenv("DOCUMENT_AI_API_KEY", "")
app = FastAPI(title="AIcheck PaddleOCR-VL 1.6 Shadow", version="2")
lock = asyncio.Semaphore(1)
pipeline = None
loaded_at = None
last_inference = None
last_error = None


def require_auth(request: Request) -> None:
    if not API_KEY:
        raise HTTPException(503, detail={"code": "DOCUMENT_AI_API_KEY_MISSING"})
    if not secrets.compare_digest(request.headers.get("authorization", ""), f"Bearer {API_KEY}"):
        raise HTTPException(401, detail={"code": "DOCUMENT_AI_AUTH_REQUIRED"})


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@app.on_event("startup")
def load_pipeline():
    global pipeline, loaded_at, last_error
    try:
        pipeline = PaddleOCRVL(
            vl_rec_model_dir=MODEL_PATH,
            pipeline_version="v1.6",
            layout_detection_model_dir=f"{MODEL_ROOT}/PP-DocLayoutV3",
            doc_orientation_classify_model_dir=f"{MODEL_ROOT}/PP-LCNet_x1_0_doc_ori",
            doc_unwarping_model_dir=f"{MODEL_ROOT}/UVDoc",
            use_doc_orientation_classify=True,
            use_doc_unwarping=False,
            use_chart_recognition=False,
            use_seal_recognition=True,
            device="gpu:0",
        )
        loaded_at = utcnow()
        last_error = None
    except TypeError:
        pipeline = PaddleOCRVL(vl_rec_model_dir=MODEL_PATH, device="gpu:0")
        loaded_at = utcnow()
        last_error = None
    except Exception as exc:
        last_error = f"{type(exc).__name__}: {exc}"
        raise


def serializable(value):
    if callable(value):
        value = value()
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    try:
        json.dumps(value)
        return value
    except TypeError:
        return json.loads(json.dumps(value, default=lambda obj: getattr(obj, "__dict__", str(obj))))


def result_payload(result):
    for name in ("json", "to_dict", "dict"):
        if hasattr(result, name):
            return serializable(getattr(result, name))
    return serializable(result)


def parse_file(path: Path):
    global last_inference, last_error
    started = time.monotonic()
    results = list(pipeline.predict(str(path)))
    if not results:
        raise ValueError("no parseable document content")
    payloads = [result_payload(item) for item in results]
    last_inference = utcnow()
    last_error = None
    return payloads, time.monotonic() - started


@app.get("/healthz")
def healthz(request: Request):
    require_auth(request)
    return {
        "status": "ok" if pipeline is not None else "starting",
        "model": "PaddlePaddle/PaddleOCR-VL-1.6",
        "revision": "66317acc4c9fc17bd154591ce650735cd2855f3e",
        "pipeline": "PaddleOCRVL full pipeline",
        "loadedAt": loaded_at,
        "lastSuccessfulInferenceAt": last_inference,
        "lastError": last_error,
    }


@app.get("/readyz")
def readyz(request: Request):
    require_auth(request)
    if pipeline is None or last_inference is None:
        raise HTTPException(503, detail={"ready": False, "error": last_error})
    return {"ready": True, "warmedUp": True}


@app.post("/v1/parse")
async def parse(request: Request, file: UploadFile = File(...)):
    require_auth(request)
    suffix = Path(file.filename or "document.png").suffix or ".png"
    with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp.flush()
        async with lock:
            inference = asyncio.create_task(asyncio.to_thread(parse_file, Path(tmp.name)))
            started = time.monotonic()
            while not inference.done():
                if await request.is_disconnected() or time.monotonic() - started >= 120:
                    # Paddle predict is not cooperatively cancellable. Terminate this worker so
                    # Supervisor can rebuild a clean single model instance without GPU overlap.
                    threading.Timer(0.05, lambda: os._exit(124)).start()
                    raise HTTPException(504, detail={"code": "PADDLE_DEADLINE_OR_DISCONNECT"})
                await asyncio.sleep(0.1)
            try:
                pages, elapsed = await inference
            except ValueError as exc:
                raise HTTPException(422, detail={"code": "NO_PARSEABLE_CONTENT"}) from exc
            except Exception as exc:
                global last_error
                last_error = f"{type(exc).__name__}: {exc}"
                raise HTTPException(500, detail={"code": "PADDLE_INFERENCE_FAILED"}) from exc
    return {
        "model": "PaddlePaddle/PaddleOCR-VL-1.6",
        "revision": "66317acc4c9fc17bd154591ce650735cd2855f3e",
        "pages": pages,
        "elapsedSeconds": round(elapsed, 3),
    }
