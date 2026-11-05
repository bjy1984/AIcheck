"""一条提示词安装节点审计 skill（2026-11-04）：安装包、签名链接、写给 AI 助手的安装说明。"""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api import main
from libs import skill_distribution as sd
from libs.db.repository import repo
from libs.security.actions import required_action_for_request
from scripts.build_skill_package import PACKAGE_ROOT, ROOT_PLACEHOLDER, build

REPO = Path(__file__).resolve().parents[2]
client = TestClient(main.app)
ORIGIN = "http://39.108.65.148:8081"


@pytest.fixture(scope="module")
def package(tmp_path_factory):
    out = tmp_path_factory.mktemp("skill-package")
    info = build(REPO, out, "abc12345")
    return out, info


@pytest.fixture(autouse=True)
def isolated(monkeypatch, package):
    repo.reset()
    monkeypatch.setattr(repo, "postgres_enabled", False)
    monkeypatch.setattr(repo, "sync_postgres", None)
    monkeypatch.setattr(repo, "postgres_dsn", None)
    monkeypatch.setattr(repo, "sqlite_enabled", False)
    monkeypatch.setattr(repo, "sqlite_path", None)
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")
    monkeypatch.setenv("AICHECK_ALLOW_DEV_TOKENS", "true")
    monkeypatch.setenv("AICHECK_ENABLE_DEMO_USERS", "true")
    monkeypatch.setenv("AICHECK_SKILL_PACKAGE_DIR", str(package[0]))


def bearer(role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer dev-token-{role}"}


def test_package_has_the_skill_rules_and_standards_and_a_root_placeholder(package):
    out, info = package
    with zipfile.ZipFile(out / info["fileName"]) as archive:
        names = archive.namelist()
        skill_md = archive.read(f"{PACKAGE_ROOT}/skills/aicheck-node-audit/SKILL.md").decode("utf-8")
    assert f"{PACKAGE_ROOT}/README.md" in names
    assert f"{PACKAGE_ROOT}/skills/aicheck-node-audit/scripts/node_audit.py" in names
    assert f"{PACKAGE_ROOT}/backend/business_packs/engineering_inspection_v1/atomic_checks.yaml" in names
    assert sum(1 for name in names if name.startswith(f"{PACKAGE_ROOT}/rules/standards/")) == 14
    assert not [name for name in names if "__pycache__" in name or ".ruff_cache" in name]
    # 安装说明把占位符换成解压后的真实路径：在别的目录起会话也知道先 cd 到哪
    assert skill_md.count(ROOT_PLACEHOLDER) == 1 and skill_md.index(ROOT_PLACEHOLDER) < skill_md.index("## 准备")
    assert info["fileCount"] == len(names) and info["revision"] == "abc12345"


def test_same_tree_builds_the_same_bytes(package, tmp_path):
    """校验值写进提示词：同一个提交打两次必须一样，不然提示词里的值会和服务器上的包对不上。"""
    assert build(REPO, tmp_path, "abc12345")["sha256"] == package[1]["sha256"]


def test_links_are_signed_short_lived_and_only_for_inspection_and_admin():
    token, expires = sd.issue_install_token(user_id="U1", role="inspection", origin=ORIGIN, now=1_000_000)
    assert expires == 1_000_000 + sd.INSTALL_LINK_SECONDS
    assert sd.verify_install_token(token, now=1_000_100)["o"] == ORIGIN
    with pytest.raises(sd.SkillInstallError, match="已过期"):
        sd.verify_install_token(token, now=expires + 1)
    payload, signature = token.split(".")
    with pytest.raises(sd.SkillInstallError, match="无效"):
        sd.verify_install_token(f"{payload}.{signature[:-2]}AA", now=1_000_100)
    for role in ("contractor", "ndt", "owner"):
        with pytest.raises(sd.SkillInstallError):
            sd.issue_install_token(user_id="U2", role=role, origin=ORIGIN)
    for bad in ("javascript:alert(1)", "http://evil.example/path", "http://a b", ""):
        with pytest.raises(sd.SkillInstallError):
            sd.normalize_origin(bad)


def test_inspection_gets_a_prompt_with_the_guide_link_and_checksum(package):
    response = client.post("/api/skill-install/links", headers=bearer("inspection"), json={"origin": ORIGIN})
    assert response.json()["code"] == 0, response.text
    data = response.json()["data"]
    assert data["sha256"] == package[1]["sha256"] and data["validSeconds"] == 600
    assert data["guideUrl"].startswith(f"{ORIGIN}/api/skill-install/d/") and data["guideUrl"].endswith("/install.md")
    assert data["guideUrl"] in data["prompt"] and package[1]["sha256"] in data["prompt"]
    assert required_action_for_request("POST", "/api/skill-install/links") == "project:view"


def test_outside_roles_cannot_get_a_link():
    for role in ("contractor", "ndt", "owner"):
        body = client.post("/api/skill-install/links", headers=bearer(role), json={"origin": ORIGIN}).json()
        assert body["code"] == 403, role
    assert client.post("/api/skill-install/links", json={"origin": ORIGIN}).json()["code"] == 401


def test_guide_and_package_download_with_the_link_alone(package):
    data = client.post("/api/skill-install/links", headers=bearer("admin"), json={"origin": ORIGIN}).json()["data"]
    guide_path = data["guideUrl"].removeprefix(ORIGIN)
    guide = client.get(guide_path)  # 不带令牌：AI 助手这时还没登录
    assert guide.status_code == 200 and guide.headers["content-type"].startswith("text/markdown")
    text = guide.text
    assert package[1]["sha256"] in text and data["packageUrl"] in text
    assert "login --web" in text and f"AICHECK_BASE_URL={ORIGIN}" in text and "__AICHECK_PACKAGE_ROOT__" in text
    assert "HTTP" in text  # 平台走 HTTP 时提醒校验值对不上就停
    archive = client.get(data["packageUrl"].removeprefix(ORIGIN))
    assert archive.status_code == 200 and hashlib.sha256(archive.content).hexdigest() == package[1]["sha256"]


def test_bad_or_expired_links_are_refused_with_plain_text(monkeypatch):
    assert client.get("/api/skill-install/d/not-a-token/install.md").status_code == 403
    token, _ = sd.issue_install_token(user_id="U1", role="inspection", origin=ORIGIN, now=1_000_000)
    expired = client.get(f"/api/skill-install/d/{token}/package.zip")
    assert expired.status_code == 403 and "已过期" in expired.text
