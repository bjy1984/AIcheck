"""删除只能停用时让出名字（2026-11-04 青岛特检院：qdns 删不掉、同名组织建不了、开通特检院报用户名已占用）。"""
from __future__ import annotations

from libs.name_release import release_org_name, release_username


def test_用户停用时改名并留原名_再次删除不重复改名():
    user = {"id": "USER-24536D0B", "username": "qdns", "status": "停用"}
    assert release_username(user) == "qdns"
    assert user == {"id": "USER-24536D0B", "username": "qdns~已删除-24536D0B", "status": "停用", "releasedUsername": "qdns"}
    assert release_username(user) is None and user["username"] == "qdns~已删除-24536D0B"


def test_组织改名时按名字和按id引用的都跟着改_别的组织不动():
    org = {"id": "ORG-8504904C", "name": "青岛特检院"}
    users = [{"orgId": "ORG-8504904C", "orgName": "青岛特检院"}, {"orgId": "ORG-OTHER", "orgName": "别的院"}]
    state = {"project_members": [{"orgId": None, "orgName": "青岛特检院"}],
             "projects": [{"inspectionOrgName": "青岛特检院", "ownerOrgName": "业主"}]}
    assert release_org_name(state, users, org) == "青岛特检院"
    new = "青岛特检院（已删除-8504904C）"
    assert org["name"] == new and org["releasedName"] == "青岛特检院"
    assert users[0]["orgName"] == new and users[1]["orgName"] == "别的院"
    assert state["project_members"][0]["orgName"] == new
    assert state["projects"][0] == {"inspectionOrgName": new, "ownerOrgName": "业主"}


def test_被项目引用的用户删除后用户名可以再建():
    from fastapi.testclient import TestClient

    from apps.api.main import app
    from libs.db.repository import repo

    client = TestClient(app)
    org_id = repo.state["admin_config"]["orgUnits"][0]["id"] if repo.state["admin_config"].get("orgUnits") else None
    body = {"username": "qdns_release_case", "name": "牛帅", "role": "admin", "password": "Release!2026"}
    if org_id:
        body["orgId"] = org_id
    created = client.post("/admin/users", json=body).json()["data"]["user"]
    repo.state["project_members"].append({"id": "PM-RELEASE", "projectId": "P-2026-HDCP-001", "userId": created["id"], "status": "启用"})
    deleted = client.delete(f"/admin/users/{created['id']}", headers={"If-Match": created["etag"]}).json()["data"]
    assert deleted["deleted"] is False and deleted["user"]["username"].startswith("qdns_release_case~已删除-")
    again = client.post("/admin/users", json=body).json()
    assert again.get("data", {}).get("user", {}).get("username") == "qdns_release_case", again
