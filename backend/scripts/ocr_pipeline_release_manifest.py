from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from libs.contracts.responses import server_time


DEFAULT_COMPOSE_FILES = [
    BACKEND_ROOT / "docker-compose.yml",
    BACKEND_ROOT / "docker-compose.accuracy-pipeline.yml",
    BACKEND_ROOT / "docker-compose.ocr-validation.yml",
]
SCHEMA_FILES = [
    BACKEND_ROOT / "libs" / "db" / "repository.py",
    BACKEND_ROOT / "docker" / "postgres" / "init-databases.sh",
    BACKEND_ROOT / "scripts" / "setup_langgraph_checkpoint.py",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a traceable OCR pipeline deployment manifest.")
    parser.add_argument("--origin-commit")
    parser.add_argument("--bundle")
    parser.add_argument("--compose", action="append", default=[])
    parser.add_argument("--image-manifest", help="JSON object mapping image names to immutable digests.")
    parser.add_argument("--require-origin", action="store_true")
    parser.add_argument("--require-bundle", action="store_true")
    parser.add_argument("--require-images", action="store_true")
    parser.add_argument("--output")
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def aggregate_hash(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: str(item)):
        digest.update(str(path.relative_to(REPOSITORY_ROOT)).encode("utf-8"))
        digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


def git_revision(reference: str) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", reference],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def git_branch() -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def git_worktree_status() -> list[str]:
    result = subprocess.run(
        ["git", "status", "--short"],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.splitlines() if result.returncode == 0 else ["git_status_unavailable"]


def load_image_manifest(path: str | None) -> dict[str, str]:
    if not path:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("image manifest must be a JSON object")
    return {str(key): str(value) for key, value in payload.items()}


def build_manifest(args: argparse.Namespace) -> dict[str, Any]:
    head = git_revision("HEAD")
    origin = str(args.origin_commit or git_revision("origin/main") or "").strip() or None
    compose_paths = [Path(value).resolve() for value in args.compose] if args.compose else DEFAULT_COMPOSE_FILES
    missing = [str(path) for path in [*compose_paths, *SCHEMA_FILES] if not path.is_file()]
    if missing:
        raise FileNotFoundError(", ".join(missing))
    bundle_path = Path(args.bundle).resolve() if args.bundle else None
    images = load_image_manifest(args.image_manifest)
    worktree_status = git_worktree_status()
    blockers = []
    if not head:
        blockers.append({"code": "GIT_HEAD_UNAVAILABLE"})
    if not origin:
        blockers.append({"code": "ORIGIN_COMMIT_UNAVAILABLE"})
    elif head != origin:
        blockers.append({"code": "ORIGIN_COMMIT_MISMATCH", "head": head, "originCommit": origin})
    if bundle_path and not bundle_path.is_file():
        blockers.append({"code": "GIT_BUNDLE_MISSING", "path": str(bundle_path)})
    if args.require_bundle and (bundle_path is None or not bundle_path.is_file()):
        blockers.append({"code": "GIT_BUNDLE_REQUIRED"})
    if args.require_origin and (not origin or head != origin):
        blockers.append({"code": "ORIGIN_VISIBILITY_REQUIRED"})
    if args.require_origin and worktree_status:
        blockers.append({"code": "WORKTREE_NOT_CLEAN", "changedPathCount": len(worktree_status)})
    image_digests_complete = bool(images) and all("@sha256:" in value for value in images.values())
    if args.require_images and not image_digests_complete:
        blockers.append({"code": "IMMUTABLE_IMAGE_DIGESTS_REQUIRED"})
    return {
        "schemaVersion": "aicheck-ocr-pipeline-deployment-manifest@1",
        "generatedAt": server_time(),
        "passed": not blockers,
        "git": {
            "head": head,
            "originCommit": origin,
            "branch": git_branch(),
            "worktreeClean": not worktree_status,
            "changedPathCount": len(worktree_status),
        },
        "bundle": (
            {"path": str(bundle_path), "sha256": sha256_file(bundle_path)} if bundle_path and bundle_path.is_file() else None
        ),
        "compose": {
            "aggregateSha256": aggregate_hash(compose_paths),
            "files": [
                {
                    "path": str(path.relative_to(REPOSITORY_ROOT)),
                    "sha256": sha256_file(path),
                }
                for path in compose_paths
            ],
        },
        "databaseSchemaSha256": aggregate_hash(SCHEMA_FILES),
        "images": images,
        "imageDigestsComplete": image_digests_complete,
        "blockingReasons": blockers,
    }


def main() -> int:
    args = parse_args()
    report = build_manifest(args)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
