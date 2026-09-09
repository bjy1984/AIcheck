# Lab rule editor browser integration

This local-only harness mounts the real Vue editor and calls real FastAPI routes through TestClient with isolated in-memory seed data. Only authentication transport is substituted with a seeded inspection member. It is not production-login acceptance or external-service verification.

Run from the repository root in separate terminals:

```sh
PYTHONPATH=backend backend/.venv/bin/python frontend/e2e/lab-rules/backend.py
```

```sh
cd frontend
./node_modules/.bin/vite --config e2e/lab-rules/vite.config.ts
```

```sh
cd frontend
node e2e/lab-rules/check.mjs
```

Requires installed Google Chrome. Uses a fresh temporary browser profile; does not access existing browser sessions. Servers bind loopback ports 4174 and 4393. Stop both servers after testing. Do not expose the test bridge to a network or deploy it.

The script checks platform read-only behavior, creating and saving a numeric condition, failing/passing/missing-evidence trials, clearing stale results, disabling trials for unsaved edits, and retaining unsaved text after canceling close. It fails on browser runtime errors. The screenshot is written to `docs/lab/verification/browser/rule-trial-pass.png`.
