"""一条提示词安装节点审计 skill（2026-11-04）。

监检或管理员在平台账号菜单点「安装节点审计 skill」，拿到一句话发给自己电脑上的 AI 助手（Claude Code、Codex）。
那句话里有一个 10 分钟有效的签名链接：AI 助手先读链接给的安装说明（写给它看的 markdown），再按说明下载安装包、
核对 SHA-256、解压、装依赖、把 skill 挂进 skills 目录、自检，最后跑网页授权登录。

为什么是签名链接、不是公开下载：包里有审计规则和标准原文，只给登录过平台的监检和管理员。下载那一步 AI 助手
手里还没有平台令牌（令牌要装好之后网页授权才拿得到），所以用平台签发的短链接代替。链接在 10 分钟内可以用
不止一次——安装说明和安装包是两次请求。

平台现在走 HTTP（HTTPS 之后再上）：校验值同时写在提示词和安装说明里，对不上就停下；但能同时改掉页面和下载内容
的中间人，这一层挡不住，所以先只给内部试用。安装包本身由 scripts/build_skill_package.py 在部署时打好。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import time
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
INSTALL_LINK_SECONDS = 10 * 60
INSTALLER_ROLES = {"inspection", "admin", "test"}
_ORIGIN = re.compile(r"^https?://[A-Za-z0-9.\-]+(?::\d{1,5})?$")
_SIGN_CONTEXT = b"aicheck-skill-install|"


class SkillInstallError(ValueError):
    pass


def package_dir() -> Path:
    return Path(os.getenv("AICHECK_SKILL_PACKAGE_DIR") or BACKEND_ROOT / "skill_package")


def package_info(build_if_missing: bool = True) -> dict[str, Any]:
    """部署时打好的安装包；本机开发、测试时没有就用当前仓库现打一份。"""
    directory = package_dir()
    info_path = directory / "package.json"
    if not info_path.is_file() and build_if_missing:
        repo = BACKEND_ROOT.parent
        if (repo / "skills" / "aicheck-node-audit" / "SKILL.md").is_file():
            from scripts.build_skill_package import build

            build(repo, directory, "local")
    try:
        info = json.loads(info_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SkillInstallError("服务器上还没有 skill 安装包（部署时会打好）。") from exc
    if not (directory / str(info.get("fileName") or "")).is_file():
        raise SkillInstallError("服务器上的 skill 安装包不完整，请重新部署。")
    return info


def package_path(info: dict[str, Any]) -> Path:
    return package_dir() / str(info["fileName"])


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _secret() -> bytes:
    from libs.security.auth import jwt_secret

    return str(jwt_secret()).encode()


def _signature(payload: bytes) -> str:
    return _b64(hmac.new(_secret(), _SIGN_CONTEXT + payload, hashlib.sha256).digest()[:18])


def normalize_origin(origin: str) -> str:
    """提示词和安装说明里写的平台地址：只收 http(s)://主机[:端口]，免得往给 AI 助手的说明里塞别的东西。"""
    value = str(origin or "").strip().rstrip("/")
    if not _ORIGIN.fullmatch(value):
        raise SkillInstallError("平台地址格式不对。")
    return value


def issue_install_token(*, user_id: str, role: str, origin: str, now: float | None = None) -> tuple[str, int]:
    if role not in INSTALLER_ROLES:
        raise SkillInstallError("只有监检人员和管理员能安装节点审计 skill。")
    expires = int((now or time.time()) + INSTALL_LINK_SECONDS)
    payload = json.dumps({"u": user_id, "r": role, "o": normalize_origin(origin), "e": expires},
                         separators=(",", ":"), ensure_ascii=False).encode()
    return f"{_b64(payload)}.{_signature(payload)}", expires


def verify_install_token(token: str, now: float | None = None) -> dict[str, Any]:
    try:
        encoded, signature = str(token or "").split(".", 1)
        payload = _unb64(encoded)
    except (ValueError, TypeError) as exc:
        raise SkillInstallError("安装链接无效。") from exc
    if not hmac.compare_digest(signature, _signature(payload)):
        raise SkillInstallError("安装链接无效。")
    claims = json.loads(payload)
    if int(claims.get("e") or 0) < (now or time.time()):
        raise SkillInstallError("安装链接已过期：请回平台账号菜单重新点「安装节点审计 skill」。")
    return claims


def link_paths(token: str) -> dict[str, str]:
    base = f"/api/skill-install/d/{token}"
    return {"guide": f"{base}/install.md", "package": f"{base}/package.zip"}


def install_prompt(origin: str, token: str, info: dict[str, Any]) -> str:
    return (f"请按 {origin}{link_paths(token)['guide']} 这一页的步骤，在我的电脑上安装 AIcheck 节点审计 skill"
            f"（链接 10 分钟内有效）。安装包的 SHA-256 是 {info['sha256']}：下载后先核对，对不上就停下告诉我。")


def install_guide(claims: dict[str, Any], token: str, info: dict[str, Any]) -> str:
    origin = claims["o"]
    paths = link_paths(token)
    expires = time.strftime("%Y-%m-%d %H:%M", time.gmtime(int(claims["e"]) + 8 * 3600)) + "（北京时间）"
    size = f"{int(info.get('size') or 0) / 1048576:.0f} MB"
    revision = str(info.get("revision") or "")[:8] or "本机"
    http_note = ("平台现在用 HTTP：每一步只连这一个地址，不要改连别的；校验值对不上就停下，不要重下了再装。"
                 if origin.startswith("http://") else "")
    return f"""# 安装 AIcheck 节点审计 skill

这一页是写给 AI 助手的安装步骤。用户在 AIcheck 平台上点了「安装节点审计 skill」，让你照这一页装。
链接到 {expires} 失效。按顺序做；任何一步失败就停下，把命令和报错原样告诉用户，不要换别的办法绕过去。
{http_note}

- 版本：{revision}，安装包约 {size}
- SHA-256：`{info['sha256']}`

## 1. 检查环境

需要 Python 3.9 或更新、curl、unzip：`python3 --version && curl --version | head -1 && unzip -v | head -1`。
缺哪个就告诉用户先装上。Windows 请在 Git Bash 里执行下面的命令。

## 2. 下载并核对

```bash
ROOT="$HOME/.aicheck-node-audit/skill"
mkdir -p "$ROOT" && cd "$ROOT"
curl -fSL -o package.zip "{origin}{paths['package']}"
(shasum -a 256 package.zip 2>/dev/null || sha256sum package.zip)
```

算出来的值必须和上面的 SHA-256 一字不差，也和用户发给你的那句话里的一致。不一致就 `rm package.zip`，
停下告诉用户「安装包校验不通过」。

## 3. 解压（覆盖旧版本）

```bash
rm -rf "$ROOT/aicheck-node-audit-skill" && unzip -q package.zip -d "$ROOT" && rm package.zip
PKG="$ROOT/aicheck-node-audit-skill"
```

## 4. 装依赖

```bash
cd "$PKG" && python3 -m venv backend/.venv && backend/.venv/bin/pip install -q pymupdf pyyaml
```

下载慢可以在 pip install 后面加 `-i https://mirrors.aliyun.com/pypi/simple/`。

## 5. 让 AI 助手找到 skill

先把包根目录写进 SKILL.md（skill 里的命令都按包根目录写）：

```bash
sed -i.bak "s#__AICHECK_PACKAGE_ROOT__#$PKG#g" "$PKG/skills/aicheck-node-audit/SKILL.md" && rm -f "$PKG/skills/aicheck-node-audit/SKILL.md.bak"
```

再按你是哪个助手挂进 skills 目录：

- Claude Code：`mkdir -p ~/.claude/skills && ln -sfn "$PKG/skills/aicheck-node-audit" ~/.claude/skills/aicheck-node-audit`
- Codex：`mkdir -p ~/.agents/skills && ln -sfn "$PKG/skills/aicheck-node-audit" ~/.agents/skills/aicheck-node-audit`
- 其他助手：以后用之前先读 `$PKG/skills/aicheck-node-audit/SKILL.md`，照它做。

## 6. 自检

```bash
cd "$PKG" && backend/.venv/bin/python skills/aicheck-node-audit/scripts/node_audit.py rules --node 24
```

输出里有 `"ok": true` 才算装好。

## 7. 登录（网页授权）

```bash
cd "$PKG" && AICHECK_BASE_URL={origin} AICHECK_ALLOW_HTTP=1 backend/.venv/bin/python skills/aicheck-node-audit/scripts/node_audit.py login --web
```

浏览器会打开平台的授权页：请用户核对登录的是自己的监检或管理员账号，再点「授权」。浏览器没自动打开时，
把命令输出里的链接发给用户。用户的口令只在浏览器里输，不要向用户要口令。

## 8. 告诉用户

告诉用户装好了、装在 `$PKG`，以后说「审计 P-xxx 节点 N」或「用 aicheck-node-audit 审一下这个节点」就行；
新开的 Claude Code、Codex 会话会自动认出这个 skill。登录 12 小时后过期，到时再授权一次。
"""
