from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "aicheck-release-manifest-v1"
IGNORED_NAMES = {".DS_Store", "__pycache__"}


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def git_archive_hash(repo_root: Path, git_sha: str) -> str:
    """Hash a Git archive without materializing multi-gigabyte LFS exports."""
    digest = hashlib.sha256()
    process = subprocess.Popen(
        ["git", "archive", "--format=tar", git_sha],
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdout is not None
    for chunk in iter(lambda: process.stdout.read(1024 * 1024), b""):
        digest.update(chunk)
    stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
    return_code = process.wait()
    if return_code:
        raise RuntimeError(f"git archive failed with exit {return_code}: {stderr.strip()}")
    return "sha256:" + digest.hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def git(repo_root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo_root, text=True).strip()


def tree_manifest(root: Path) -> dict[str, Any]:
    if not root.exists():
        return {"exists": False, "aggregateHash": None, "files": {}}
    files: dict[str, str] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if any(part in IGNORED_NAMES for part in path.parts):
            continue
        files[path.relative_to(root).as_posix()] = sha256_file(path)
    return {
        "exists": True,
        "aggregateHash": sha256_bytes(canonical_bytes(files)),
        "files": files,
    }


def optional_file(path: Path) -> dict[str, Any]:
    return {
        "path": path.as_posix(),
        "exists": path.is_file(),
        "sha256": sha256_file(path) if path.is_file() else None,
    }


def command_version(command: list[str]) -> str | None:
    try:
        return subprocess.check_output(command, text=True, stderr=subprocess.STDOUT).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def load_json_file(path: str | None) -> Any:
    if not path:
        return None
    return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))


def build_manifest(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(args.repo_root).expanduser().resolve()
    git_sha = git(repo_root, "rev-parse", "HEAD")
    dirty_lines = [line for line in git(repo_root, "status", "--porcelain").splitlines() if line]
    if args.require_clean and dirty_lines:
        raise RuntimeError("release manifest requires a clean worktree")
    frontend_dist = Path(args.frontend_dist).expanduser().resolve() if args.frontend_dist else repo_root / "frontend/dist-pro"
    business_pack_root = repo_root / "backend/business_packs"
    rules_root = repo_root / "rules"
    material_mapping = repo_root / "backend/config/material_review_points.json"
    compose_paths = [
        repo_root / "backend/docker-compose.yml",
        repo_root / "backend/docker-compose.deploy.yml",
        repo_root / "backend/docker-compose.production-data.yml",
        repo_root / "backend/docker-compose.backup.yml",
    ]
    if args.compose_config:
        compose_paths.append(Path(args.compose_config).expanduser().resolve())

    rollback = load_json_file(args.rollback_manifest)
    rollback_hash = rollback.get("manifestHash") if isinstance(rollback, dict) else None
    services = load_json_file(args.service_digests) or {}
    release_id = args.release_id or git_sha
    document: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "releaseId": release_id,
        "generatedAt": datetime.now(UTC).isoformat(),
        "source": {
            "gitSha": git_sha,
            "dirty": bool(dirty_lines),
            "dirtyPaths": dirty_lines,
            "archiveHash": git_archive_hash(repo_root, git_sha),
        },
        "backend": {
            "imageDigest": args.backend_image_digest or None,
            "services": services,
            "businessPacks": tree_manifest(business_pack_root),
            "materialMapping": optional_file(material_mapping),
            "migrations": tree_manifest(repo_root / "backend/db/migrations"),
        },
        "frontend": {
            "dist": tree_manifest(frontend_dist),
            "entry": optional_file(frontend_dist / "index.html"),
        },
        "rules": tree_manifest(rules_root),
        "dependencies": {
            "pnpmLock": optional_file(repo_root / "frontend/pnpm-lock.yaml"),
            "backendRequirements": optional_file(repo_root / "backend/requirements.txt"),
            "ocrRequirements": optional_file(repo_root / "backend/requirements-ocr-core.txt"),
        },
        "deployment": {
            "composeFiles": [optional_file(path) for path in dict.fromkeys(compose_paths)],
            "tlsCertificateFingerprint": args.tls_certificate_fingerprint or None,
        },
        "buildEnvironment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "node": command_version(["node", "--version"]),
            "pnpm": command_version(["pnpm", "--version"]),
        },
        "evidence": {
            "sbom": optional_file(Path(args.sbom).expanduser().resolve()) if args.sbom else None,
            "securityScan": optional_file(Path(args.security_scan).expanduser().resolve()) if args.security_scan else None,
        },
        "rollbackManifestHash": rollback_hash,
    }
    document["manifestHash"] = sha256_bytes(canonical_bytes(document))
    return document


def verify_manifest(document: dict[str, Any]) -> str:
    expected = str(document.get("manifestHash") or "")
    unsigned = {key: value for key, value in document.items() if key != "manifestHash"}
    actual = sha256_bytes(canonical_bytes(unsigned))
    if expected != actual:
        raise RuntimeError(f"release manifest hash mismatch: expected={expected}, actual={actual}")
    return actual


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an immutable AIcheck release manifest.")
    parser.add_argument("--repo-root", default=Path(__file__).resolve().parents[2])
    parser.add_argument("--release-id")
    parser.add_argument("--frontend-dist")
    parser.add_argument("--backend-image-digest", default=os.getenv("AICHECK_BACKEND_IMAGE_DIGEST"))
    parser.add_argument("--service-digests", help="JSON object containing immutable service image digests.")
    parser.add_argument("--compose-config", help="Rendered production Compose config to bind into the release.")
    parser.add_argument("--sbom")
    parser.add_argument("--security-scan")
    parser.add_argument("--tls-certificate-fingerprint")
    parser.add_argument("--rollback-manifest")
    parser.add_argument("--require-clean", action="store_true")
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = build_manifest(args)
    verify_manifest(manifest)
    target = Path(args.output).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(target), "releaseId": manifest["releaseId"], "manifestHash": manifest["manifestHash"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
