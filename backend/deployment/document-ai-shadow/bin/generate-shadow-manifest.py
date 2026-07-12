from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


BASE = Path("/usrdata/aicheck-document-ai")
MODEL_ROOT = Path("/usrdata/aicheck-models/document-ai")
OUTPUT = BASE / "manifests" / "document-ai-shadow-manifest.json"


def sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def main() -> int:
    tracked = [
        BASE / "services" / "hybrid_service.py",
        BASE / "services" / "nuextract_service.py",
        BASE / "services" / "paddle_service.py",
        BASE / "config" / "supervisord.conf",
        BASE / "bin" / "start-all.sh",
        BASE / "bin" / "stop-all.sh",
        BASE / "bin" / "status.sh",
        BASE / "bin" / "generate-shadow-manifest.py",
        BASE / "manifests" / "requirements-control.lock",
        BASE / "manifests" / "requirements-nuextract3.lock",
        BASE / "manifests" / "requirements-paddle-vl16.lock",
    ]
    manifest = {
        "schemaVersion": "DocumentAiShadowDeploymentManifest@1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "advisoryOnly": True,
        "formalEvidenceReady": False,
        "network": {
            "bindHost": "127.0.0.1",
            "paddlePort": 18110,
            "nuExtractPort": 18220,
            "hybridPort": 18300,
            "bearerAuthRequired": True,
        },
        "limits": {
            "activeRequests": 1,
            "queuedRequests": 2,
            "maxPages": 6,
            "maxCandidates": 64,
            "maxPriorTokens": 12000,
            "maxOutputTokens": 2048,
            "deadlineSeconds": 180,
        },
        "models": {
            "paddleocrVl16": {
                "revision": "66317acc4c9fc17bd154591ce650735cd2855f3e",
                "path": str(MODEL_ROOT / "paddleocr-vl16" / "66317acc4c9fc17bd154591ce650735cd2855f3e"),
                "present": (MODEL_ROOT / "paddleocr-vl16" / "66317acc4c9fc17bd154591ce650735cd2855f3e").is_dir(),
            },
            "nuExtract3": {
                "revision": "2e9fca82ee641e6bb6e1f5d905241e994be27a07",
                "path": str(MODEL_ROOT / "nuextract3" / "2e9fca82ee641e6bb6e1f5d905241e994be27a07"),
                "present": (MODEL_ROOT / "nuextract3" / "2e9fca82ee641e6bb6e1f5d905241e994be27a07").is_dir(),
            },
        },
        "files": {str(path.relative_to(BASE)): sha256(path) for path in tracked},
        "secretFilesExcluded": ["config/document-ai.env"],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "modelsPresent": all(item["present"] for item in manifest["models"].values())}))
    return 0 if all(item["present"] for item in manifest["models"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
