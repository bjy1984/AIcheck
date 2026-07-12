# Document AI Shadow deployment

This bundle hardens the independent PaddleOCR-VL 1.6 and NuExtract3 deployment for preproduction Shadow use.

Properties:

- localhost-only services on ports `18110`, `18220`, and `18300`;
- unprivileged model/API programs under `aicheck-docai` (Supervisor remains the root control process so it can drop privileges reliably);
- bearer authentication sourced from `/usrdata/aicheck-document-ai/config/document-ai.env`;
- one active request, at most two queued requests, six selected pages, 64 prior candidates, 12K estimated prior tokens, 2048 output tokens, and a 180-second request deadline;
- PaddleOCR-VL is called only for difficult table/seal crops; NuExtract3 output remains advisory-only;
- no endpoint can write AIcheck OCR state, evidence, or audit conclusions.

Install on the GPU server as root:

```bash
bash backend/deployment/document-ai-shadow/bin/install-shadow.sh
/usrdata/aicheck-document-ai/bin/stop-all.sh || true
/usrdata/aicheck-document-ai/bin/start-all.sh
/usrdata/aicheck-document-ai/bin/status.sh
/usrdata/aicheck-document-ai/venv-control/bin/python /usrdata/aicheck-document-ai/bin/generate-shadow-manifest.py
```

Copy the generated API key to the preproduction worker secret store as `AICHECK_DOCUMENT_AI_API_KEY`. Do not put it in Git or command arguments. Reach `127.0.0.1:18300` only through a private SSH tunnel.

The `/readyz` endpoint intentionally remains not-ready until both model services have completed at least one real inference. This prevents process liveness from being reported as model readiness.
