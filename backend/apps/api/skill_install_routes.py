"""一条提示词安装节点审计 skill 的三个接口（2026-11-04，逻辑在 libs/skill_distribution）。

- POST /skill-install/links：监检、管理员登录后取一句安装提示词（含 10 分钟有效的签名链接）
- GET  /skill-install/d/{token}/install.md：写给 AI 助手的安装说明（凭链接，不带令牌）
- GET  /skill-install/d/{token}/package.zip：安装包（凭链接，不带令牌）

下载两步不带令牌，是因为 AI 助手这时还没有平台令牌——装好之后网页授权才拿得到；
所以凭平台签发的短链接，链接本身就是凭证。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, PlainTextResponse

from libs import skill_distribution as sd
from libs.contracts import errors
from libs.contracts.responses import fail, ok

skill_install_router = APIRouter(tags=["skill install"])


@skill_install_router.post("/skill-install/links")
def create_skill_install_link(request: Request, payload: dict[str, Any]):
    from apps.api.routes import effective_role_for_request

    role, identity_error = effective_role_for_request(request)
    if identity_error:
        return identity_error
    if str(role or "") not in sd.INSTALLER_ROLES:
        return fail(errors.FORBIDDEN, request, message="只有监检人员和管理员能安装节点审计 skill。")
    claims = getattr(request.state, "auth", None) or {}
    user_id = str(claims.get("uid") or claims.get("sub") or "")
    try:
        origin = sd.normalize_origin(str((payload or {}).get("origin") or ""))
        info = sd.package_info()
        token, expires = sd.issue_install_token(user_id=user_id, role=str(role), origin=origin)
    except sd.SkillInstallError as exc:
        return fail(errors.VALIDATION_ERROR, request, message=str(exc))
    paths = sd.link_paths(token)
    return ok({
        "prompt": sd.install_prompt(origin, token, info),
        "guideUrl": f"{origin}{paths['guide']}",
        "packageUrl": f"{origin}{paths['package']}",
        "sha256": info["sha256"],
        "size": info.get("size"),
        "revision": info.get("revision"),
        "expiresAt": datetime.fromtimestamp(expires, UTC).isoformat(timespec="seconds"),
        "validSeconds": sd.INSTALL_LINK_SECONDS,
    }, request)


def _refused(exc: sd.SkillInstallError) -> PlainTextResponse:
    # 纯文本加 403：curl -f 会失败，AI 助手照说明停下，不会把错误页当安装包解压
    return PlainTextResponse(str(exc), status_code=403)


@skill_install_router.get("/skill-install/d/{token}/install.md")
def skill_install_guide(token: str):
    try:
        claims = sd.verify_install_token(token)
        info = sd.package_info()
    except sd.SkillInstallError as exc:
        return _refused(exc)
    return PlainTextResponse(sd.install_guide(claims, token, info), media_type="text/markdown; charset=utf-8")


@skill_install_router.get("/skill-install/d/{token}/package.zip")
def skill_install_package(token: str):
    try:
        sd.verify_install_token(token)
        info = sd.package_info()
    except sd.SkillInstallError as exc:
        return _refused(exc)
    return FileResponse(sd.package_path(info), media_type="application/zip", filename=str(info["fileName"]))
