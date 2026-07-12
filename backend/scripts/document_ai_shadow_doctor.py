from __future__ import annotations

import argparse
import json
from typing import Any

from libs.document_ai_shadow import document_ai_mode, document_ai_profile_allowlist
from libs.integrations.document_ai_client import DocumentAiClient


def build_document_ai_shadow_doctor(client: DocumentAiClient | None = None) -> dict[str, Any]:
    mode = document_ai_mode()
    client = client or DocumentAiClient()
    report: dict[str, Any] = {
        "schemaVersion": "DocumentAiShadowDoctor@1",
        "mode": mode,
        "advisoryOnly": True,
        "formalEvidenceReady": False,
        "client": client.public_config(),
        "profileAllowlist": sorted(document_ai_profile_allowlist()),
        "checks": [],
    }
    if mode == "off":
        report.update({"status": "disabled", "ok": True, "blockers": []})
        return report
    blockers = []
    if not client.enabled:
        blockers.append("DOCUMENT_AI_CLIENT_NOT_CONFIGURED")
    probes = []
    if client.enabled:
        for name, operation in [("health", client.health), ("ready", client.ready), ("doctor", client.doctor)]:
            try:
                payload = operation()
                ready = payload.get("ready") is not False and payload.get("status") not in {"failed", "degraded"}
                probes.append({"name": name, "passed": ready, "payload": payload})
                if not ready:
                    blockers.append(f"DOCUMENT_AI_{name.upper()}_FAILED")
            except Exception as exc:
                probes.append({"name": name, "passed": False, "reason": exc.__class__.__name__})
                blockers.append(f"DOCUMENT_AI_{name.upper()}_FAILED")
    report["checks"] = probes
    report["blockers"] = sorted(set(blockers))
    report["ok"] = not blockers
    report["status"] = "ready" if report["ok"] else "blocked"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only readiness doctor for the remote Document AI Shadow service.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = build_document_ai_shadow_doctor()
    print(json.dumps(report, ensure_ascii=False, indent=None if args.json else 2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
