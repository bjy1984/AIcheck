from __future__ import annotations

import json
import subprocess
from argparse import Namespace
from pathlib import Path

import pytest

from scripts.build_release_manifest import build_manifest, verify_manifest


def manifest_args(repo_root: Path, **overrides) -> Namespace:
    values = {
        "repo_root": str(repo_root),
        "release_id": "release-test",
        "frontend_dist": None,
        "backend_image_digest": "sha256:" + "a" * 64,
        "service_digests": None,
        "compose_config": None,
        "sbom": None,
        "security_scan": None,
        "tls_certificate_fingerprint": None,
        "rollback_manifest": None,
        "require_clean": False,
    }
    values.update(overrides)
    return Namespace(**values)


def create_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "backend/business_packs/pack").mkdir(parents=True)
    (repo / "backend/config").mkdir(parents=True)
    (repo / "backend/db/migrations").mkdir(parents=True)
    (repo / "frontend/dist-pro/assets").mkdir(parents=True)
    (repo / "frontend").mkdir(exist_ok=True)
    (repo / "rules").mkdir()
    (repo / "backend/business_packs/pack/manifest.yaml").write_text("version: 1\n", encoding="utf-8")
    (repo / "backend/config/material_review_points.json").write_text("[]\n", encoding="utf-8")
    (repo / "backend/db/migrations/0001.sql").write_text("select 1;\n", encoding="utf-8")
    (repo / "frontend/dist-pro/index.html").write_text("<main>release</main>\n", encoding="utf-8")
    (repo / "frontend/dist-pro/assets/index.js").write_text("export default 1\n", encoding="utf-8")
    (repo / "frontend/pnpm-lock.yaml").write_text("lockfileVersion: 9\n", encoding="utf-8")
    (repo / "rules/rule.yaml").write_text("id: R1\n", encoding="utf-8")
    (repo / "backend/requirements.txt").write_text("httpx==1\n", encoding="utf-8")
    (repo / "backend/requirements-ocr-core.txt").write_text("pillow==1\n", encoding="utf-8")
    for compose in ("docker-compose.yml", "docker-compose.deploy.yml", "docker-compose.production-data.yml"):
        (repo / "backend" / compose).write_text("services: {}\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "release@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Release Test"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "fixture"], cwd=repo, check=True, capture_output=True)
    return repo


def test_release_manifest_binds_source_frontend_rules_and_business_pack(tmp_path: Path) -> None:
    repo = create_repo(tmp_path)
    manifest = build_manifest(manifest_args(repo))

    assert verify_manifest(manifest) == manifest["manifestHash"]
    assert manifest["schemaVersion"] == "aicheck-release-manifest-v1"
    assert manifest["source"]["dirty"] is False
    assert manifest["backend"]["imageDigest"].startswith("sha256:")
    assert manifest["backend"]["businessPacks"]["aggregateHash"].startswith("sha256:")
    assert manifest["frontend"]["dist"]["aggregateHash"].startswith("sha256:")
    assert manifest["rules"]["aggregateHash"].startswith("sha256:")


def test_release_manifest_detects_tampering(tmp_path: Path) -> None:
    repo = create_repo(tmp_path)
    manifest = build_manifest(manifest_args(repo))
    manifest["releaseId"] = "tampered"

    with pytest.raises(RuntimeError, match="hash mismatch"):
        verify_manifest(manifest)


def test_release_manifest_can_require_clean_worktree(tmp_path: Path) -> None:
    repo = create_repo(tmp_path)
    (repo / "rules/rule.yaml").write_text("id: changed\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="clean worktree"):
        build_manifest(manifest_args(repo, require_clean=True))
