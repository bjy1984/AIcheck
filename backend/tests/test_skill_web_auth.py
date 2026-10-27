"""skill 网页授权：浏览器里已登录的监检/管理员授权 → 一次性授权码回调本机 → skill 凭 PKCE 校验码换令牌。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api import main
from libs.db.repository import repo
from libs.security import skill_auth
from libs.security.skill_auth import loopback_redirect_uri, pkce_challenge, skill_auth_codes

client = TestClient(main.app)
AUTHORIZE, TOKEN = "/api/auth/skill/authorize", "/api/auth/skill/token"
REDIRECT = "http://127.0.0.1:54321/callback"
VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"  # RFC 7636 附录 B 的示例
CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    repo.reset()
    skill_auth_codes.reset_for_tests()
    monkeypatch.setattr(repo, "postgres_enabled", False)
    monkeypatch.setattr(repo, "sync_postgres", None)
    monkeypatch.setattr(repo, "postgres_dsn", None)
    monkeypatch.setattr(repo, "sqlite_enabled", False)
    monkeypatch.setattr(repo, "sqlite_path", None)
    monkeypatch.setenv("AICHECK_REQUIRE_AUTH", "true")
    monkeypatch.setenv("AICHECK_ALLOW_DEV_TOKENS", "true")
    monkeypatch.setenv("AICHECK_ENABLE_DEMO_USERS", "true")


def bearer(role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer dev-token-{role}"}


def authorize(role: str = "inspection", **overrides):
    body = {"redirectUri": REDIRECT, "codeChallenge": CHALLENGE, "codeChallengeMethod": "S256", **overrides}
    return client.post(AUTHORIZE, headers=bearer(role), json=body)


def exchange(code: str, verifier: str = VERIFIER, redirect: str = REDIRECT):
    return client.post(TOKEN, json={"code": code, "codeVerifier": verifier, "redirectUri": redirect})


def code_of(response) -> str:
    assert response.status_code == 200 and response.json()["code"] == 0, response.text
    return response.json()["data"]["code"]


def test_pkce_uses_the_rfc_7636_s256_transform():
    assert pkce_challenge(VERIFIER) == CHALLENGE


def test_only_a_loopback_callback_on_this_machine_is_accepted():
    for good in ("http://127.0.0.1:54321/callback", "http://localhost:8765/callback", "http://[::1]:9000/callback"):
        assert loopback_redirect_uri(good) == good, good
    for bad in (
        "https://127.0.0.1:54321/callback",           # 本机回调不用 https，这里只认 http
        "http://evil.example:54321/callback",          # 别的主机：授权码会被送走
        "http://127.0.0.1.evil.example:54321/callback",
        "http://user@127.0.0.1:54321/callback",        # 带账号
        "http://127.0.0.1:54321/callback?x=1",         # 带查询串
        "http://127.0.0.1:54321/callback#x",
        "http://127.0.0.1:54321/other",                # 路径不对
        "http://127.0.0.1/callback",                   # 没端口
        "http://127.0.0.1:80/callback",                # 特权端口
        "http://127.0.0.1:99999/callback",             # 端口非法
        None, 42, "http://127.0.0.1:54321/callback" + "x" * 100,
    ):
        assert loopback_redirect_uri(bad) is None, bad


def test_an_inspector_authorizes_and_the_skill_gets_a_working_token_without_any_password():
    before = {k: len(v) for k, v in repo.state.items() if isinstance(v, list) and k != "audit_logs"}
    granted = authorize()
    data = granted.json()["data"]
    assert data["expiresIn"] == skill_auth.CODE_TTL_SECONDS and data["client"] == skill_auth.CLIENT_NAME
    issued = exchange(code_of(granted))  # 换令牌不带 Authorization：这一步是公开的
    assert issued.status_code == 200 and issued.json()["code"] == 0, issued.text
    token, user = issued.json()["data"]["token"], issued.json()["data"]["user"]
    assert user["username"] == "inspection" and user["role"] == "inspection"
    assert "password" not in user and "passwordHash" not in user
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200 and me.json()["data"]["username"] == "inspection", me.text
    after = {k: len(v) for k, v in repo.state.items() if isinstance(v, list) and k != "audit_logs"}
    assert after == before  # 除了审计记录，什么状态都不写
    actions = [entry.get("action") for entry in repo.state.get("audit_logs", [])]
    assert "授权 skill 访问" in actions and "skill 网页授权换取令牌" in actions


def test_an_admin_can_authorize_too():
    issued = exchange(code_of(authorize("admin")))
    assert issued.json()["code"] == 0 and issued.json()["data"]["user"]["role"] == "admin", issued.text


def test_the_code_works_once_and_dies_on_the_first_wrong_attempt():
    code = code_of(authorize())
    assert exchange(code).json()["code"] == 0
    again = exchange(code)
    assert again.status_code == 400 and "已用过" in again.json()["message"]
    other = code_of(authorize())
    wrong = exchange(other, verifier="x" * 43)  # 截获授权码的人没有校验码
    assert wrong.status_code == 400
    assert exchange(other).status_code == 400  # 试错一次就作废，不能接着猜


def test_the_code_only_goes_back_to_the_callback_it_was_issued_for():
    code = code_of(authorize())
    assert exchange(code, redirect="http://127.0.0.1:60000/callback").status_code == 400


def test_an_expired_code_is_rejected(monkeypatch):
    code = code_of(authorize())
    real_time = skill_auth.time.time
    monkeypatch.setattr(skill_auth.time, "time", lambda: real_time() + skill_auth.CODE_TTL_SECONDS + 1)
    assert exchange(code).status_code == 400


def test_authorizing_needs_a_login_and_an_inspector_or_admin_account():
    anonymous = client.post(AUTHORIZE, json={"redirectUri": REDIRECT, "codeChallenge": CHALLENGE, "codeChallengeMethod": "S256"})
    assert anonymous.json()["data"]["reason"] == "AUTH_REQUIRED" and "code" not in anonymous.json()["data"]
    contractor = authorize("contractor")
    assert contractor.status_code == 403 and "监检或管理员" in contractor.json()["message"]


def test_a_bad_callback_or_missing_pkce_is_refused_before_any_code_is_issued():
    assert authorize(redirectUri="http://evil.example:54321/callback").status_code == 400
    assert authorize(codeChallengeMethod="plain").status_code == 400
    assert authorize(codeChallenge="short").status_code == 400
    assert skill_auth_codes._memory == {}  # 一个码都没发


def test_the_token_endpoint_rejects_malformed_requests_without_touching_codes():
    code = code_of(authorize())
    assert client.post(TOKEN, json={"code": code}).status_code == 400
    assert client.post(TOKEN, json={"code": code, "codeVerifier": VERIFIER, "redirectUri": "http://evil.example:1/callback"}).status_code == 400
    assert exchange(code).json()["code"] == 0  # 格式不对的请求不消耗授权码


def test_a_disabled_account_cannot_redeem_a_code_issued_before(monkeypatch):
    code = code_of(authorize())
    from apps.api import skill_auth_routes

    monkeypatch.setattr(skill_auth_routes, "user_record_by_username", lambda *a, **k: None)
    refused = exchange(code)
    assert refused.status_code == 403 and "停用" in refused.json()["message"]
