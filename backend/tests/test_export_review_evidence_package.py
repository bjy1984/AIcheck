from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"


def _all_shard_text(package_root: Path) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(package_root.rglob("shard_*.json"))
    )


def test_exporter_cli_can_run_directly_from_backend() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/export_review_evidence_package.py", "--help"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--project-code" in result.stdout


def test_exported_test_package_contains_complete_design_license_ocr(tmp_path: Path) -> None:
    from scripts.export_review_evidence_package import export_project_review_package

    result = export_project_review_package(
        repo_root=REPO_ROOT,
        project_code="test",
        output_root=tmp_path,
        max_shard_estimated_tokens=1200,
    )

    payload = _all_shard_text(tmp_path / "evidence_shards" / "test")
    assert "TS1844171-2028" in payload
    assert "工业管道(GC1)" in payload
    assert "GC1级覆盖GC2级" in payload
    assert result["coveragePassed"] is True


def test_exported_packages_cover_every_linked_node_and_artifact(tmp_path: Path) -> None:
    from scripts.export_review_evidence_package import export_project_review_package

    test_result = export_project_review_package(
        repo_root=REPO_ROOT,
        project_code="test",
        output_root=tmp_path,
        max_shard_estimated_tokens=1200,
    )
    test2_result = export_project_review_package(
        repo_root=REPO_ROOT,
        project_code="test2",
        output_root=tmp_path,
        max_shard_estimated_tokens=1200,
    )

    assert test_result["includedNodeCount"] == 42
    assert test2_result["includedNodeCount"] == 42
    assert test_result["coveragePassed"] is True
    assert test2_result["coveragePassed"] is True
    for code, result in (("test", test_result), ("test2", test2_result)):
        manifest_path = tmp_path / "evidence_shards" / code / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert len(manifest["nodes"]) == result["includedNodeCount"]
        assert all(node["coverage"]["coveragePassed"] for node in manifest["nodes"])
        assert all(node["coverage"]["missingArtifactIds"] == [] for node in manifest["nodes"])


def test_entry_prompt_references_shards_instead_of_embedding_excerpt_summaries(
    tmp_path: Path,
) -> None:
    from scripts.export_review_evidence_package import export_project_review_package

    export_project_review_package(
        repo_root=REPO_ROOT,
        project_code="test",
        output_root=tmp_path,
        max_shard_estimated_tokens=1200,
    )

    prompt = (tmp_path / "ai_full_review_prompt_test.md").read_text(encoding="utf-8")
    assert "evidence_shards/test/manifest.json" in prompt
    assert "evidenceExcerpts" not in prompt
    assert "一次只处理一个业务节点的一个 EvidenceShard" in prompt
    assert "全部当前有效历史挂接资料" in prompt
