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

import torch
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from PIL import Image
from transformers import AutoModelForImageTextToText, AutoProcessor, StoppingCriteria, StoppingCriteriaList


MODEL_PATH = os.environ["NUEXTRACT_MODEL_PATH"]
API_KEY = os.getenv("DOCUMENT_AI_API_KEY", "")
MAX_PAGES = 6
MAX_NEW_TOKENS = min(int(os.getenv("NUEXTRACT_MAX_NEW_TOKENS", "2048")), 2048)
REQUEST_TIMEOUT_SECONDS = min(float(os.getenv("NUEXTRACT_REQUEST_TIMEOUT_SECONDS", "180")), 180.0)

app = FastAPI(title="AIcheck NuExtract3 Shadow", version="2")
lock = asyncio.Semaphore(1)
processor = None
model = None
loaded_at = None
last_inference = None
last_error = None


class DeadlineStoppingCriteria(StoppingCriteria):
    def __init__(self, deadline: float, cancelled: threading.Event):
        self.deadline = deadline
        self.cancelled = cancelled

    def __call__(self, input_ids, scores, **kwargs):
        return self.cancelled.is_set() or time.monotonic() >= self.deadline


def require_auth(request: Request) -> None:
    if not API_KEY:
        raise HTTPException(503, detail={"code": "DOCUMENT_AI_API_KEY_MISSING"})
    if not secrets.compare_digest(request.headers.get("authorization", ""), f"Bearer {API_KEY}"):
        raise HTTPException(401, detail={"code": "DOCUMENT_AI_AUTH_REQUIRED"})


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@app.on_event("startup")
def load_model():
    global processor, model, loaded_at, last_error
    try:
        processor = AutoProcessor.from_pretrained(MODEL_PATH, trust_remote_code=True, local_files_only=True)
        model = AutoModelForImageTextToText.from_pretrained(
            MODEL_PATH,
            dtype=torch.bfloat16,
            device_map="auto",
            trust_remote_code=True,
            local_files_only=True,
        ).eval()
        loaded_at = utcnow()
        last_error = None
    except Exception as exc:
        last_error = f"{type(exc).__name__}: {exc}"
        raise


def run_extract(images, template, instructions, evidence_prior, enable_thinking, cancelled):
    global last_inference, last_error
    content = [{"type": "image", "image": image} for image in images]
    if evidence_prior:
        content.append(
            {
                "type": "text",
                "text": "EvidencePrior (cite candidate IDs when used):\n"
                + json.dumps(evidence_prior, ensure_ascii=False),
            }
        )
    messages = [{"role": "user", "content": content}]
    kwargs = {"enable_thinking": enable_thinking}
    if template is not None:
        kwargs["template"] = json.dumps(template, ensure_ascii=False, indent=2)
    else:
        kwargs["mode"] = "content"
    if instructions:
        kwargs["instructions"] = instructions
    started = time.monotonic()
    deadline = started + REQUEST_TIMEOUT_SECONDS
    inputs = processor.apply_chat_template(
        messages,
        add_generation_prompt=True,
        tokenize=True,
        return_dict=True,
        return_tensors="pt",
        **kwargs,
    ).to(model.device)
    with torch.inference_mode():
        generated = model.generate(
            **inputs,
            max_new_tokens=MAX_NEW_TOKENS,
            do_sample=False,
            stopping_criteria=StoppingCriteriaList([DeadlineStoppingCriteria(deadline, cancelled)]),
        )
    if cancelled.is_set():
        raise InterruptedError("request cancelled")
    generated = generated[:, inputs.input_ids.shape[1] :]
    raw = processor.batch_decode(
        generated,
        skip_special_tokens=True,
        clean_up_tokenization_spaces=False,
    )[0].strip()
    elapsed = time.monotonic() - started
    if elapsed >= REQUEST_TIMEOUT_SECONDS:
        raise TimeoutError("generation deadline exceeded")
    last_inference = utcnow()
    last_error = None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None
    return raw, parsed, elapsed


@app.get("/healthz")
def healthz(request: Request):
    require_auth(request)
    return {
        "status": "ok" if model is not None else "starting",
        "model": "numind/NuExtract3",
        "revision": "2e9fca82ee641e6bb6e1f5d905241e994be27a07",
        "dtype": "bfloat16",
        "loadedAt": loaded_at,
        "lastSuccessfulInferenceAt": last_inference,
        "lastError": last_error,
    }


@app.get("/readyz")
def readyz(request: Request):
    require_auth(request)
    if model is None or processor is None or last_inference is None:
        raise HTTPException(503, detail={"ready": False, "error": last_error})
    return {"ready": True, "warmedUp": True}


@app.post("/v1/extract")
async def extract(
    request: Request,
    files: list[UploadFile] = File(...),
    template: str | None = Form(None),
    instructions: str | None = Form(None),
    evidence_prior: str | None = Form(None),
    enable_thinking: bool = Form(False),
):
    require_auth(request)
    if not 1 <= len(files) <= MAX_PAGES:
        raise HTTPException(400, detail={"code": "PAGE_LIMIT"})
    try:
        template_obj = json.loads(template) if template else None
        prior_obj = json.loads(evidence_prior) if evidence_prior else None
    except json.JSONDecodeError as exc:
        raise HTTPException(400, detail={"code": "INVALID_JSON"}) from exc
    images = []
    try:
        for upload in files:
            with tempfile.NamedTemporaryFile(suffix=Path(upload.filename or "page.png").suffix) as tmp:
                tmp.write(await upload.read())
                tmp.flush()
                images.append(Image.open(tmp.name).convert("RGB").copy())
    except Exception as exc:
        raise HTTPException(400, detail={"code": "INVALID_IMAGE"}) from exc
    cancelled = threading.Event()
    async with lock:
        inference = asyncio.create_task(
            asyncio.to_thread(
                run_extract,
                images,
                template_obj,
                instructions,
                prior_obj,
                enable_thinking,
                cancelled,
            )
        )
        while not inference.done():
            if await request.is_disconnected():
                cancelled.set()
                try:
                    await inference
                except Exception:
                    pass
                raise HTTPException(499, detail={"code": "CLIENT_DISCONNECTED"})
            await asyncio.sleep(0.1)
        try:
            raw, parsed, elapsed = await inference
        except InterruptedError as exc:
            raise HTTPException(499, detail={"code": "CLIENT_DISCONNECTED"}) from exc
        except TimeoutError as exc:
            raise HTTPException(504, detail={"code": "NUEXTRACT_DEADLINE"}) from exc
        except Exception as exc:
            global last_error
            last_error = f"{type(exc).__name__}: {exc}"
            raise HTTPException(500, detail={"code": "NUEXTRACT_FAILED"}) from exc
    return {
        "model": "numind/NuExtract3",
        "revision": "2e9fca82ee641e6bb6e1f5d905241e994be27a07",
        "parsed": parsed,
        "raw": raw,
        "jsonValid": parsed is not None,
        "elapsedSeconds": round(elapsed, 3),
        "pageCount": len(images),
        "enableThinking": enable_thinking,
    }
