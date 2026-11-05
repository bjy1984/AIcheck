"""节点审计 skill：一条提示词安装（签名链接、说明、安装包校验）、OCR 结果复用接口。"""

from __future__ import annotations

import hashlib
import re

from scripts.full_function_check.base import Context, api_case, check, skip


@api_case(
    "SKILL-01",
    "监检生成安装提示词",
    role="inspection",
    steps=["监检 POST /api/skill-install/links（origin=当前站点）"],
    expected="返回一句提示词，含 10 分钟有效的安装链接和安装包 SHA-256；有效期约 10 分钟",
    priority="P1",
)
def create_link(ctx: Context) -> None:
    data = ctx.session("inspection").ok(
        "POST", "/api/skill-install/links", json={"origin": "http://127.0.0.1:4000"}
    )
    prompt = str(data.get("prompt") or "")
    check(prompt, "没返回提示词")
    check(re.search(r"[0-9a-f]{64}", prompt), "提示词里没有安装包校验值")
    urls = re.findall(r"https?://\S+?/install\.md", prompt)
    check(urls, f"提示词里没有安装说明链接：{prompt[:200]}")
    ctx.store["skill_install_url"] = urls[0]
    ctx.store["skill_sha"] = re.search(r"[0-9a-f]{64}", prompt).group(0)


@api_case(
    "SKILL-02",
    "安装说明和安装包能按链接下载，校验值对得上",
    role="public",
    steps=["不登录 GET 安装说明链接", "GET 同一链接下的 package.zip", "算 SHA-256 与提示词比对"],
    expected="说明是 Markdown，含下载、校验、安装、授权步骤；安装包的 SHA-256 与提示词一致",
    priority="P1",
)
def download_package(ctx: Context) -> None:
    url = ctx.need("skill_install_url")
    path = "/" + url.split("://", 1)[1].split("/", 1)[1]
    guide = ctx.send("GET", path)
    check(guide.http == 200, f"安装说明应能下载，实际 {guide.brief()}")
    check("sha256" in guide.text.lower() or "校验" in guide.text, "安装说明里没有校验步骤")
    package = ctx.send("GET", path.replace("install.md", "package.zip"))
    check(
        package.http == 200 and package.content[:2] == b"PK",
        f"安装包应是 zip，实际 {package.brief()}",
    )
    check(
        hashlib.sha256(package.content).hexdigest() == ctx.need("skill_sha"),
        "安装包校验值与提示词不一致",
    )


@api_case(
    "SKILL-03",
    "伪造或改过的安装链接被拒",
    role="public",
    steps=["GET /api/skill-install/d/forged-token/install.md", "把真链接的令牌改一位再下载"],
    expected="都返回 403，提示链接无效或已过期",
    priority="P1",
)
def forged_link(ctx: Context) -> None:
    forged = ctx.send("GET", "/api/skill-install/d/forged-token/install.md")
    check(forged.http == 403, f"伪造链接应 403，实际 {forged.brief()}")
    url = ctx.store.get("skill_install_url")
    if url:
        path = "/" + url.split("://", 1)[1].split("/", 1)[1]
        token = path.split("/d/", 1)[1].split("/", 1)[0]
        tampered = path.replace(token, token[:-1] + ("A" if token[-1] != "A" else "B"))
        reply = ctx.send("GET", tampered)
        check(reply.http == 403, f"改过的链接应 403，实际 {reply.brief()}")


@api_case(
    "SKILL-04",
    "只有监检和管理员能生成安装链接",
    role="outside",
    steps=[
        "施工方、无损、建设方 POST /api/skill-install/links",
        "不登录 POST /api/skill-install/links",
    ],
    expected="对外角色被拒（403），未登录 401",
    priority="P1",
)
def link_roles(ctx: Context) -> None:
    for role in ("contractor", "ndt", "owner", "public"):
        ctx.session(role).denied(
            "POST", "/api/skill-install/links", json={"origin": "http://127.0.0.1:4000"}
        )


@api_case(
    "SKILL-05",
    "skill 复用平台已有的 OCR 结果",
    role="inspection",
    steps=[
        "取一份已识别资料的当前版本",
        "GET /api/projects/{项目}/documents/{资料}/versions/{版本}/ocr-result",
    ],
    expected="有识别结果时返回结果、识别引擎和 reusable 标志（只有 MinerU/千问的结果可复用）；"
    "还没有结果时 resultAvailable=false，skill 改为自己上传识别",
    priority="P1",
)
def ocr_result(ctx: Context) -> None:
    project = ctx.need("project")
    document = ctx.store.get("flow_document") or {}
    if not document:
        skip("没有本轮上传并识别完成的资料（FLOW-01 没跑）")
    data = ctx.session("inspection").ok_get(
        f"/api/projects/{project}/documents/{document['documentId']}/versions/{document['documentVersionId']}/ocr-result"
    )
    check(data.get("documentVersionId") == document["documentVersionId"], "返回的版本号不对")
    if not data.get("resultAvailable"):
        return
    check(
        "reusable" in data and "ocrProvider" in data, f"返回缺 reusable/ocrProvider：{list(data)}"
    )
    if str(data.get("ocrProvider") or "").lower() not in ("mineru", "qwen"):
        check(data.get("reusable") is False, "非 MinerU/千问的结果不该标成可复用")


@api_case(
    "SKILL-06",
    "对外角色读不到 OCR 结果接口",
    role="contractor",
    steps=["施工方 GET 同一个 …/ocr-result"],
    expected="被拒（只给监检、管理员、测试账号）",
    priority="P1",
)
def ocr_result_roles(ctx: Context) -> None:
    project = ctx.need("project")
    document = ctx.store.get("flow_document") or {}
    if not document:
        skip("没有本轮上传的资料")
    ctx.session("contractor").denied(
        "GET",
        f"/api/projects/{project}/documents/{document['documentId']}/versions/{document['documentVersionId']}/ocr-result",
        codes={401, 403, 40301, 40404},
    )
