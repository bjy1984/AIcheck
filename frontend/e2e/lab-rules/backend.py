"""Local-only HTTP bridge to real API routes with isolated in-memory seed data."""
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

for key, value in {
    "AICHECK_REQUIRE_AUTH": "false", "AICHECK_REQUIRE_IF_MATCH": "false",
    "AICHECK_ENABLE_DEMO_DATA": "true", "AICHECK_ENABLE_COMPATIBILITY_MOCKS": "true",
    "AICHECK_ALLOW_DEV_TOKENS": "true", "AICHECK_WORKSTATIONS_ENABLED": "true",
}.items():
    os.environ[key] = value

from fastapi.testclient import TestClient

from apps.api.main import app
from libs.db.repository import repo

repo.reset()
repo.postgres_enabled = False
repo.sqlite_enabled = False
client = TestClient(app)


class Handler(BaseHTTPRequestHandler):
    def forward(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        response = client.request(self.command, self.path, content=body,
            headers={"Content-Type": "application/json", "X-Role": "inspection", "X-User-Id": "USER-INSPECTION-001",
                     **{key: value for key, value in self.headers.items() if key.lower() in {"if-match", "idempotency-key"}}})
        self.send_response(response.status_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(response.content)

    do_GET = forward
    do_POST = forward
    do_PATCH = forward


HTTPServer(("127.0.0.1", 4174), Handler).serve_forever()
