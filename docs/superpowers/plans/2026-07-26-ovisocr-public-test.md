# OvisOCR2 Public Test Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy the real OvisOCR2 Q6 model on the Linux target and expose a public, streaming single-image test page at `http://39.108.128.107:8081/ocr-test/`, with an entry from the FDE OCR workbench.

**Architecture:** A CPU-only llama.cpp container and a Python OvisOCR Web container share a private Docker network. The existing AIcheck frontend Nginx serves a separate Vite page at `/ocr-test/` and proxies `/ocr-api/` to the private Web container; the FDE workbench opens that same page. Work is based on `origin/main` in an isolated worktree so the user's dirty checkout remains untouched.

**Tech Stack:** Python 3.12, FastAPI/Gradio, llama.cpp server, Docker Compose, Vue 3, TypeScript, Vite multi-page build, Nginx, Playwright.

## Global Constraints

- Run the real `OvisOCR2-Q6_K.gguf` and `mmproj-F16.gguf`; never enable test mode in deployment.
- Target hardware is Linux x86_64 with 4 logical CPUs, 30 GiB RAM, no GPU, and limited disk.
- Accept one JPG, JPEG, PNG, or WebP image, at most 20 MiB and 16,000,000 pixels.
- Permit one active inference at a time.
- Keep llama.cpp private; expose only `/ocr-test/` and `/ocr-api/` through port 8081.
- The public page requires no login.
- Preserve the user's existing uncommitted `frontend/src/views/AIReviewB/ConversationalReviewWorkbenchB.vue`.

---

### Task 1: Isolate the Current Upstream Source

**Files:**
- Use worktree: `/Volumes/Volume/project/AIcheck/.worktrees/ovisocr-public-test`
- Preserve: `/Volumes/Volume/project/AIcheck/frontend/src/views/AIReviewB/ConversationalReviewWorkbenchB.vue`

**Interfaces:**
- Consumes: `origin/main`, design commit `091c387`
- Produces: clean branch `feat/ovisocr-public-test`

- [ ] **Step 1: Invoke the worktree skill and verify repository state**

Run:

```bash
git fetch origin
git status --short --branch
git rev-parse origin/main
```

Expected: the existing checkout still shows only the user's work plus the two documentation commits.

- [ ] **Step 2: Create the isolated branch from current upstream**

Follow `superpowers:using-git-worktrees`, using:

```bash
git worktree add .worktrees/ovisocr-public-test -b feat/ovisocr-public-test origin/main
```

- [ ] **Step 3: Bring the approved documentation into the isolated branch**

Run:

```bash
git cherry-pick 091c387
```

After the implementation-plan commit exists, cherry-pick that commit as well.

- [ ] **Step 4: Verify isolation**

Run:

```bash
git -C .worktrees/ovisocr-public-test status --short --branch
git status --short --branch
```

Expected: the worktree is clean and the original checkout still contains the user's untouched modification.

---

### Task 2: Add a Public Streaming OCR Endpoint

**Files:**
- Create: `/Volumes/Volume/project/ocr/src/ovisocr_web/public_api.py`
- Modify: `/Volumes/Volume/project/ocr/src/ovisocr_web/app.py`
- Modify: `/Volumes/Volume/project/ocr/src/ovisocr_web/config.py`
- Modify: `/Volumes/Volume/project/ocr/pyproject.toml`
- Test: `/Volumes/Volume/project/ocr/tests/test_public_api.py`
- Test: `/Volumes/Volume/project/ocr/tests/test_config.py`

**Interfaces:**
- Consumes: `run_ocr({"path": image_path}) -> Iterator[dict[str, Any]]`
- Produces: `POST /api/ocr` with an image request body and `application/x-ndjson` response
- Produces: `GET /healthz` reporting llama.cpp readiness
- Produces: `encode_ndjson(payload: dict[str, Any]) -> bytes`

- [ ] **Step 1: Write failing configuration and NDJSON tests**

Add tests proving:

```python
def test_allows_container_bind_only_with_explicit_opt_in():
    settings = Settings.from_env(
        {
            "OVISOCR_WEB_HOST": "0.0.0.0",
            "OVISOCR_ALLOW_NON_LOOPBACK": "1",
        }
    )
    assert settings.web_host == "0.0.0.0"


def test_ndjson_encoder_emits_one_compact_line():
    assert encode_ndjson({"event": "stream", "markdown": "文字"}) == (
        b'{"event":"stream","markdown":"\\u6587\\u5b57"}\n'
    )
```

Add endpoint tests using `fastapi.testclient.TestClient` that:

- upload a PNG as the raw request body with `Content-Type: image/png`;
- receive `page_start`, `stream`, `page_complete`, and `complete` lines in order;
- reject an unsupported content type with HTTP 415;
- reject a body larger than `OVISOCR_MAX_UPLOAD_BYTES` with HTTP 413;
- convert iterator failure into an `error` NDJSON event.

- [ ] **Step 2: Run the focused tests and confirm RED**

Run:

```bash
cd /Volumes/Volume/project/ocr
.venv/bin/pytest -q tests/test_config.py tests/test_public_api.py
```

Expected: failures because the opt-in setting, encoder, and endpoint do not exist.

- [ ] **Step 3: Implement container binding and streaming helpers**

Add `allow_non_loopback: bool` to `Settings`. Continue rejecting non-loopback hosts unless
`OVISOCR_ALLOW_NON_LOOPBACK` is one of `1`, `true`, or `yes`.

In `public_api.py`, implement:

```python
def encode_ndjson(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
```

Implement a bounded request-body writer that streams chunks to a named temporary file,
raises HTTP 413 before exceeding `settings.max_upload_bytes`, and always removes the file.
Accept only `image/jpeg`, `image/png`, and `image/webp`.

- [ ] **Step 4: Register the endpoint**

In `app.py`, register `POST /api/ocr` on the existing server. Return a
`StreamingResponse(..., media_type="application/x-ndjson")` whose iterator emits the
existing `run_ocr` payloads. Convert operational exceptions into:

```json
{"event":"error","code":"OCR_INFERENCE_FAILED","message":"识别失败，请稍后重试。"}
```

Set `Cache-Control: no-store` and `X-Accel-Buffering: no`.

Extend `/healthz` to call `client.health()` and report `llama_ready`; a failed health
probe must produce HTTP 503 without leaking the API key.

- [ ] **Step 5: Run focused and full OCR tests**

Run:

```bash
.venv/bin/pytest -q tests/test_config.py tests/test_public_api.py
.venv/bin/python -m compileall -q src
.venv/bin/pytest -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit the OCR source changes if the OCR directory is version-controlled**

If it is not a Git repository, record the exact file manifest and hashes for deployment
instead of creating a synthetic repository.

---

### Task 3: Add Linux CPU Deployment Artifacts

**Files:**
- Create: `/Volumes/Volume/project/ocr/Dockerfile.web`
- Create: `/Volumes/Volume/project/ocr/docker-compose.linux.yml`
- Create: `/Volumes/Volume/project/ocr/.env.server.example`
- Create: `/Volumes/Volume/project/ocr/scripts/server-healthcheck.sh`
- Modify: `/Volumes/Volume/project/ocr/README.md`
- Test: `/Volumes/Volume/project/ocr/tests/test_linux_deployment.py`

**Interfaces:**
- Consumes: model files in `./models`
- Consumes: external Docker network `aicheck_default`
- Produces: containers `ovisocr-llama` and `ovisocr-web`
- Produces: internal DNS endpoint `http://ovisocr-web:7860`

- [ ] **Step 1: Write failing deployment contract tests**

Parse the Compose YAML as text and assert:

```python
assert "OVISOCR_TEST_MODE" not in compose
assert "OvisOCR2-Q6_K.gguf" in compose
assert "mmproj-F16.gguf" in compose
assert "--parallel" in compose and "\"1\"" in compose
assert "aicheck_default" in compose
assert "ports:" not in compose
assert "unless-stopped" in compose
```

Also assert the Web image uses Python 3.12 and the health-check script probes both
`/healthz` and the llama.cpp health endpoint.

- [ ] **Step 2: Run the test and confirm RED**

Run:

```bash
.venv/bin/pytest -q tests/test_linux_deployment.py
```

Expected: missing deployment files.

- [ ] **Step 3: Add the Web image**

`Dockerfile.web` must:

- use `python:3.12-slim`;
- create an unprivileged runtime user;
- install the local package without test dependencies;
- copy `src` and the vendored frontend assets;
- bind `0.0.0.0:7860` with `OVISOCR_ALLOW_NON_LOOPBACK=1`;
- define a health check against `/healthz`.

- [ ] **Step 4: Add the Compose stack**

Use `ghcr.io/ggml-org/llama.cpp:server` for `ovisocr-llama`, mount the two model files
read-only, pass:

```text
--model /models/OvisOCR2-Q6_K.gguf
--mmproj /models/mmproj-F16.gguf
--host 0.0.0.0
--port 8081
--parallel 1
--threads 3
--ctx-size 16384
--image-min-tokens 1024
--api-key ${OVISOCR_LLAMA_API_KEY}
```

Configure `ovisocr-web` with `OVISOCR_LLAMA_BASE_URL=http://ovisocr-llama:8081`,
the same API key, a 900-second timeout, `depends_on` health, `unless-stopped`, and only
the external `aicheck_default` network. Do not publish container ports.

- [ ] **Step 5: Add health and operator documentation**

Document:

```bash
openssl rand -hex 32
docker compose --env-file .env.server -f docker-compose.linux.yml up -d
./scripts/server-healthcheck.sh
docker compose --env-file .env.server -f docker-compose.linux.yml logs --tail=100
```

- [ ] **Step 6: Run deployment contract and full OCR tests**

Run:

```bash
.venv/bin/pytest -q tests/test_linux_deployment.py
.venv/bin/pytest -q
```

Expected: all tests pass.

---

### Task 4: Build the Public Vue Test Page and FDE Entry

**Files:**
- Create: `frontend/ocr-test.html`
- Create: `frontend/src/ocr-test/main.ts`
- Create: `frontend/src/ocr-test/OcrPublicTest.vue`
- Create: `frontend/src/ocr-test/ocrStream.ts`
- Modify: `frontend/vite.config.ts`
- Modify: `frontend/nginx.aicheck.conf`
- Modify: `frontend/src/views/AICheck/FdeConsole.vue`
- Test: `frontend/e2e/ocr-public-test.spec.ts`
- Test: `frontend/scripts/test-ocr-stream.mts`
- Modify: `frontend/package.json`

**Interfaces:**
- Consumes: `POST /ocr-api/api/ocr` NDJSON stream
- Produces: Vite output `dist-pro/ocr-test.html`
- Produces: public URL `/ocr-test/`
- Produces: `parseNdjsonStream(response: Response, onEvent: (event) => void)`

- [ ] **Step 1: Write the failing stream parser test**

Add `test-ocr-stream.mts` with fragmented UTF-8 and line chunks:

```ts
const chunks = [
  encoder.encode('{"event":"stream","markdown":"文'),
  encoder.encode('字"}\\n{"event":"complete","markdown":"文字"}\\n')
]
```

Assert that `parseNdjsonStream` emits exactly two parsed events and preserves `文字`.
Add `test:ocr-stream` to `package.json`.

- [ ] **Step 2: Run the parser test and confirm RED**

Run:

```bash
cd frontend
pnpm test:ocr-stream
```

Expected: module or exported function does not exist.

- [ ] **Step 3: Implement the stream client**

`ocrStream.ts` must:

- send the raw `File` body with its MIME type and `X-File-Name`;
- reject non-2xx responses with a user-facing message;
- decode arbitrary byte boundaries with `TextDecoder(..., { stream: true })`;
- buffer incomplete lines;
- dispatch typed `page_start`, `stream`, `page_complete`, `complete`, and `error` events;
- support `AbortSignal`.

- [ ] **Step 4: Implement the standalone public page**

Create a separate Vite entry rather than adding the page to the authenticated hash router.
The Vue page must include:

- drag/drop and file input;
- JPG/JPEG/PNG/WebP, 20 MiB client validation;
- object-URL preview with cleanup;
- start, cancel/reset, and copy Markdown actions;
- queued/inference/completed/error states;
- streaming Markdown source and rendered output;
- CPU performance and single-image notices;
- responsive two-column desktop and one-column mobile layout;
- accessible labels, keyboard focus, and visible error text.

Use the existing Element Plus setup only where necessary; sanitize rendered Markdown with the
project's existing safe rendering approach and never assign unsanitized model HTML directly.

- [ ] **Step 5: Configure the Vite multi-page build**

Set Rollup inputs to:

```ts
input: {
  main: resolve(root, 'index.html'),
  ocrTest: resolve(root, 'ocr-test.html')
}
```

Keep the current main SPA output unchanged.

- [ ] **Step 6: Configure Nginx**

Add:

```nginx
location = /ocr-test {
  return 301 /ocr-test/;
}

location /ocr-test/ {
  try_files /ocr-test.html =404;
}

location /ocr-api/ {
  client_max_body_size 20m;
  proxy_pass http://ovisocr-web:7860/;
  proxy_buffering off;
  proxy_request_buffering off;
  proxy_read_timeout 900s;
  proxy_send_timeout 900s;
  proxy_set_header Host $host;
  proxy_set_header X-Real-IP $remote_addr;
  proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

- [ ] **Step 7: Add the FDE entry**

Add an `open-public-ovisocr-test` action to the `ocr-quality` page metadata with label
`OvisOCR2 在线测试`. Handle it with:

```ts
window.open('/ocr-test/', '_blank', 'noopener,noreferrer')
```

Reuse the existing `fde:ocr-quality:view` permission.

- [ ] **Step 8: Add and run the browser test**

The Playwright test routes `**/ocr-api/api/ocr`, responds with delayed NDJSON, and verifies:

- `/ocr-test/` loads without a login redirect;
- selecting a fixture enables recognition;
- incremental and final text render;
- copy/reset controls become available;
- an error event displays a visible retry message.

Run:

```bash
pnpm test:ocr-stream
pnpm ts:check
pnpm build:pro
pnpm playwright test e2e/ocr-public-test.spec.ts
```

Expected: all commands pass.

- [ ] **Step 9: Commit the AIcheck implementation**

Run:

```bash
git add frontend/ocr-test.html frontend/src/ocr-test frontend/vite.config.ts \
  frontend/nginx.aicheck.conf frontend/src/views/AICheck/FdeConsole.vue \
  frontend/e2e/ocr-public-test.spec.ts frontend/scripts/test-ocr-stream.mts \
  frontend/package.json
git commit -m "feat: add public OvisOCR test page"
```

---

### Task 5: Deploy Through the Jump Host

**Files:**
- Deploy OCR to: `/home/dev-bjy/ovisocr`
- Deploy frontend build to: `/home/dev-bjy/AIcheck/frontend/dist-pro`
- Deploy Nginx config to: `/home/dev-bjy/AIcheck/frontend/nginx.aicheck.conf`
- Backup to: `/home/dev-bjy/AIcheck/.deploy-backups/ovisocr-public-<timestamp>`

**Interfaces:**
- Consumes: local verified OCR source/model files and `frontend/dist-pro`
- Produces: `ovisocr-llama`, `ovisocr-web`, and updated `aicheck-frontend`

- [ ] **Step 1: Capture pre-deployment evidence**

Through `47.120.63.210`, record:

```bash
docker ps
docker inspect aicheck-frontend
docker network inspect aicheck_default
curl -fsS http://127.0.0.1:18080/healthz
df -h /home/dev-bjy
```

Stop if free space is below 3 GiB after accounting for the uploaded model and image layers.

- [ ] **Step 2: Create recoverable backups**

Copy the current `dist-pro` and `nginx.aicheck.conf` to the timestamped backup directory.
Do not remove earlier backups.

- [ ] **Step 3: Transfer OCR artifacts without the macOS virtual environment**

Use tar over SSH or rsync through the configured jump host. Include:

```text
src/
vendor/
scripts/
models/OvisOCR2-Q6_K.gguf
models/mmproj-F16.gguf
pyproject.toml
Dockerfile.web
docker-compose.linux.yml
.env.server
```

Exclude `.venv`, `.pytest_cache`, `__pycache__`, and local logs. Verify SHA-256 hashes of
both GGUF files on local and target.

- [ ] **Step 4: Transfer the built frontend atomically**

Upload to a staging directory, verify `ocr-test.html` exists, then rename the current
`dist-pro` to a backup name and move the staging build into place. Upload the Nginx config
only after `nginx -t` succeeds in a disposable Nginx container attached to
`aicheck_default`.

- [ ] **Step 5: Start OCR services**

Run:

```bash
cd /home/dev-bjy/ovisocr
docker compose --env-file .env.server -f docker-compose.linux.yml pull
docker compose --env-file .env.server -f docker-compose.linux.yml build ovisocr-web
docker compose --env-file .env.server -f docker-compose.linux.yml up -d
docker compose --env-file .env.server -f docker-compose.linux.yml ps
```

Wait for both health checks before continuing.

- [ ] **Step 6: Reload the frontend proxy**

Run:

```bash
docker exec aicheck-frontend nginx -t
docker exec aicheck-frontend nginx -s reload
```

If the bind-mounted directory inode changed, recreate only `aicheck-frontend` using its
captured network, mounts, and restart policy; do not restart backend, database, or workers.

- [ ] **Step 7: Roll back on any failed gate**

Restore the saved `dist-pro` and Nginx config, reload Nginx, and stop the new OCR Compose
stack. Preserve logs and the failed staging directory for diagnosis.

---

### Task 6: Verify Real Inference and Production Regression

**Files:**
- Record evidence in: `docs/test-results/2026-07-26-ovisocr-public-production.md`

**Interfaces:**
- Verifies: public page, proxy, real model, FDE entry, private model port, restart recovery

- [ ] **Step 1: Run service and proxy health checks**

Run on the target:

```bash
docker compose --env-file /home/dev-bjy/ovisocr/.env.server \
  -f /home/dev-bjy/ovisocr/docker-compose.linux.yml ps
curl -fsS http://127.0.0.1:18080/ocr-api/healthz
curl -fsSI http://127.0.0.1:18080/ocr-test/
curl -fsS http://127.0.0.1:18080/healthz
```

Expected: OCR and AIcheck health are successful, and the public page returns HTML.

- [ ] **Step 2: Run a real Q6 inference**

POST a real PNG or JPEG:

```bash
curl --no-buffer --fail-with-body \
  -H 'Content-Type: image/png' \
  -H 'X-File-Name: smoke.png' \
  --data-binary @smoke.png \
  http://127.0.0.1:18080/ocr-api/api/ocr
```

Expected: ordered NDJSON ending in `complete`, `backend` equals `llama.cpp`, and final
Markdown is non-empty. Record wall-clock duration.

- [ ] **Step 3: Verify from the public network**

Open `http://39.108.128.107:8081/ocr-test/` without an authenticated session and repeat
the upload. Confirm incremental output, final output, copy, and reset.

- [ ] **Step 4: Verify FDE entry and regressions**

Log in as FDE, open OCR Quality, click `OvisOCR2 在线测试`, and confirm the same public page
opens. Check the existing dashboard, OCR Quality page, and `/healthz`.

- [ ] **Step 5: Verify llama.cpp remains private**

From outside the target, probe ports 8081 and 7860 on `39.108.128.107`. Port 8081 must
remain the AIcheck gateway; 7860 and the internal llama port must not be reachable.

- [ ] **Step 6: Verify restart recovery**

Restart only the OCR Compose stack, wait for health, and repeat `/ocr-api/healthz`. Do not
restart AIcheck stateful services.

- [ ] **Step 7: Run final local verification**

Run fresh:

```bash
cd /Volumes/Volume/project/ocr
.venv/bin/python -m compileall -q src
.venv/bin/pytest -q

cd /Volumes/Volume/project/AIcheck/.worktrees/ovisocr-public-test/frontend
pnpm test:ocr-stream
pnpm ts:check
pnpm build:pro
```

Expected: every command exits 0.

- [ ] **Step 8: Commit production evidence**

Run:

```bash
git add docs/test-results/2026-07-26-ovisocr-public-production.md
git commit -m "docs: record OvisOCR production verification"
```

