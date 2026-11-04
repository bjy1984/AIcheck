#!/usr/bin/env python3
"""aicheck-feedback：AI（Claude Code / Codex）领取平台已批准的改进任务、回报修改（2026-11-04）。

服务器接口见 backend/apps/api/improvement_routes.py。要平台管理员授权（web 授权，口令只在浏览器里输）。
令牌存在 ~/.config/aicheck-feedback/session.json，和审计 skill 的登录分开。

命令（输出都是 {"ok": true, "data": …} 或 {"ok": false, "error": …}）：
  login [--no-browser] [--timeout 秒]   网页授权登录（借用 aicheck-node-audit 的 login --web）
  list [--status approved]              列任务；默认只列「待开发」
  show <任务号>                          任务包：任务描述、验收标准、脱敏的反馈原文、规则
  claim <任务号> [--agent 名字]           领取并锁定 4 小时
  release <任务号> [--note 原因]          放弃，退回待开发
  done <任务号> --pr URL --tests 结果 [--commit SHA] [--note 说明]   回报，进入待审核合并
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

SKILL_DIR = Path(__file__).resolve().parents[1]
NODE_AUDIT = SKILL_DIR.parent / "aicheck-node-audit" / "scripts" / "node_audit.py"
DEFAULT_BASE = "http://39.108.65.148:8081"


class ClientError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def session_path() -> Path:
    return Path(os.getenv("AICHECK_FEEDBACK_SESSION_FILE") or Path.home() / ".config/aicheck-feedback/session.json").expanduser()


def claims_path() -> Path:
    return session_path().with_name("claims.json")


def remember_claim(task_id: str, claim_id: str | None) -> None:
    path = claims_path()
    try:
        claims = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        claims = {}
    if claim_id:
        claims[task_id] = claim_id
    else:
        claims.pop(task_id, None)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(claims), encoding="utf-8")
    path.chmod(0o600)


def recall_claim(task_id: str) -> str:
    try:
        return str(json.loads(claims_path().read_text(encoding="utf-8")).get(task_id) or "")
    except (OSError, ValueError):
        return ""


def base_url() -> str:
    session = load_session()
    session_base = str(session.get("baseUrl") or "").rstrip("/")
    env_base = str(os.getenv("AICHECK_BASE_URL") or "").rstrip("/")
    # 令牌只发给登录时的那台服务器（2026-11-04 审计）：环境变量指向别处时拒绝，免得把平台管理员令牌发出去
    if session_base and env_base and env_base != session_base:
        raise ClientError("baseUrlMismatch", f"登录的是 {session_base}，现在要连 {env_base}；换服务器请先重新 login。")
    base = (session_base or env_base or DEFAULT_BASE).rstrip("/")
    parts = urllib.parse.urlparse(base)
    loopback = parts.hostname in {"127.0.0.1", "localhost", "::1"}
    if parts.scheme == "http" and not loopback and os.getenv("AICHECK_ALLOW_HTTP", "").lower() not in {"1", "true", "yes"}:
        raise ClientError("insecureTransport", "远程地址是明文 HTTP，令牌会明文传输；确认可接受后设置 AICHECK_ALLOW_HTTP=1。")
    return base


def load_session() -> dict[str, Any]:
    try:
        return json.loads(session_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def call(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    token = load_session().get("token")
    if not token:
        raise ClientError("loginRequired", "还没登录：先运行 login，请用户用平台管理员账号在浏览器里授权。")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if method != "GET":
        headers["Idempotency-Key"] = f"feedback-skill-{uuid.uuid4().hex}"
    request = urllib.request.Request(base_url() + path, method=method, headers=headers,
                                     data=json.dumps(body).encode("utf-8") if body is not None else None)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read() or b"{}")
        except ValueError:
            payload = {}
        if exc.code == 401:
            raise ClientError("loginRequired", "令牌过期或无效：重新 login。") from None
        if exc.code == 403:
            raise ClientError("forbidden", "要平台管理员授权：请用户用平台院的管理员账号重新 login。") from None
        raise ClientError(f"HTTP_{exc.code}", str(payload.get("message") or exc.reason)) from None
    except ValueError:
        raise ClientError("badResponse", "服务器返回的不是 JSON：检查 AICHECK_BASE_URL 是否指向 AIcheck。") from None
    except urllib.error.URLError as exc:
        raise ClientError("unreachable", f"连不上服务器：{exc.reason}") from None
    if payload.get("code") == 401:
        raise ClientError("loginRequired", "令牌过期或无效：重新 login。")
    if payload.get("code") not in (0, None):
        message = str(payload.get("message") or "")
        if payload.get("code") == 403 or "平台管理员" in message:
            raise ClientError("forbidden", "要平台管理员授权：请用户用平台院的管理员账号重新 login。")
        raise ClientError("refused", message or "服务器拒绝了这个操作。")
    return payload.get("data")


def cmd_login(args: argparse.Namespace) -> Any:
    if not NODE_AUDIT.exists():
        raise ClientError("missingDependency", f"网页授权借用 aicheck-node-audit：没找到 {NODE_AUDIT}")
    session_path().parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "AICHECK_SESSION_FILE": str(session_path()), "AICHECK_BASE_URL": os.getenv("AICHECK_BASE_URL") or DEFAULT_BASE}
    command = [sys.executable, str(NODE_AUDIT), "login", "--web", "--timeout", str(args.timeout)]
    if args.no_browser:
        command.append("--no-browser")
    done = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
    sys.stderr.write(done.stderr)
    try:
        result = json.loads(done.stdout or "{}")
    except ValueError:
        raise ClientError("loginFailed", (done.stdout or done.stderr or "登录失败").strip()[-300:]) from None
    if not result.get("ok"):
        error = result.get("error") or {}
        raise ClientError(str(error.get("code") or "loginFailed"), str(error.get("message") or "登录失败"))
    data = result.get("data") or {}
    return {"loggedIn": True, "user": data.get("user") or data.get("username"), "sessionFile": str(session_path()),
            "note": "要平台管理员：list 报 forbidden 就是授权的不是平台管理员账号。"}


def cmd_list(args: argparse.Namespace) -> Any:
    data = call("GET", "/api/platform/improvement-tasks" + (f"?status={urllib.parse.quote(args.status)}" if args.status else ""))
    return {"items": [{key: row.get(key) for key in ("id", "status", "statusLabel", "priority", "scope", "title",
                                                     "sourceInstitutes", "sourceCount", "claim", "updatedAt")}
                      for row in data.get("items") or []],
            "statusCounts": data.get("statusCounts")}


def cmd_show(args: argparse.Namespace) -> Any:
    return call("GET", f"/api/platform/improvement-tasks/{urllib.parse.quote(args.task_id)}")["packet"]


def _act(task_id: str, verb: str, body: dict[str, Any]) -> Any:
    task = call("POST", f"/api/platform/improvement-tasks/{urllib.parse.quote(task_id)}/{verb}", body)["task"]
    return {key: task.get(key) for key in ("id", "status", "statusLabel", "claim", "result")}


def cmd_claim(args: argparse.Namespace) -> Any:
    result = _act(args.task_id, "claim", {"agent": args.agent})
    remember_claim(args.task_id, (result.get("claim") or {}).get("id"))
    return result


def cmd_release(args: argparse.Namespace) -> Any:
    result = _act(args.task_id, "release", {"note": args.note or "", "claimId": recall_claim(args.task_id)})
    remember_claim(args.task_id, None)
    return result


def cmd_done(args: argparse.Namespace) -> Any:
    result = _act(args.task_id, "submit", {"prUrl": args.pr, "tests": args.tests, "commit": args.commit or "",
                                           "note": args.note or "", "claimId": recall_claim(args.task_id)})
    remember_claim(args.task_id, None)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AIcheck 改进任务（AI 领取与回报）")
    sub = parser.add_subparsers(dest="command", required=True)
    login = sub.add_parser("login")
    login.add_argument("--no-browser", action="store_true")
    login.add_argument("--timeout", type=int, default=300)
    listing = sub.add_parser("list")
    listing.add_argument("--status", default="approved")
    for name in ("show", "claim", "release", "done"):
        command = sub.add_parser(name)
        command.add_argument("task_id")
        if name == "claim":
            command.add_argument("--agent", default=os.getenv("AICHECK_AGENT_NAME") or "agent")
        if name in {"release", "done"}:
            command.add_argument("--note")
        if name == "done":
            command.add_argument("--pr", required=True)
            command.add_argument("--tests", required=True)
            command.add_argument("--commit")
    args = parser.parse_args(argv)
    handlers = {"login": cmd_login, "list": cmd_list, "show": cmd_show, "claim": cmd_claim, "release": cmd_release,
                "done": cmd_done}
    try:
        print(json.dumps({"ok": True, "data": handlers[args.command](args)}, ensure_ascii=False, indent=2))
        return 0
    except ClientError as exc:
        print(json.dumps({"ok": False, "error": {"code": exc.code, "message": exc.message}}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
