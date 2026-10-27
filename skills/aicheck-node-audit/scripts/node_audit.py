#!/usr/bin/env python3
"""AIcheck node audit helper for AI coding assistants. Python 3.10+, standard library (PyYAML only for local rules).

Pulls one project node from the AIcheck server into a local bundle, exposes the server's
certificate/standard tools, and checks the assistant's audit.json before rendering audit.md.
Only an explicitly confirmed sync writes draft AI findings back to the server.
"""
from __future__ import annotations

import argparse
import base64
import functools
import getpass
import hashlib
import ipaddress
import json
import os
import re
import shutil
import sys
import time
import unicodedata
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib import error, parse, request

SKILL_DIR = Path(__file__).resolve().parents[1]
BUNDLE_SCHEMA = "aicheck-node-audit-bundle@1"
REPORT_SCHEMA = "aicheck-node-audit-report@1"
VERDICTS = {
    "passed": "符合",
    "failed": "不符合",
    "evidence_insufficient": "证据不足",
    "human_review_required": "需人工确认",
    "not_applicable": "不适用",
    "not_executed": "未执行",
}
NEEDS_SOURCE = {"passed", "failed"}
MAX_DOWNLOAD_BYTES = 300 * 1024 * 1024
MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 每页
MAX_IMAGE_PAGES = 16
GATEWAY_ERRORS = {"http502", "http503", "http504"}
GATEWAY_RETRY_SECONDS = 5
RULE_FIELDS = ("id", "sourceRuleId", "name", "nodeIds", "version", "status", "inspectionClass",
               "businessModule", "inspectionItem", "criteria", "checkMethod", "referencedStandards",
               "agentThinking", "toolchainThinking", "materialTypeCodes")


class ClientError(Exception):
    def __init__(self, code: str, message: str, **details: Any):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def audit_home() -> Path:
    return Path(os.getenv("AICHECK_AUDIT_HOME") or Path.home() / ".aicheck-node-audit").expanduser()


def session_path() -> Path:
    return Path(os.getenv("AICHECK_SESSION_FILE") or Path.home() / ".config/aicheck-node-audit/session.json").expanduser()


def repo_root() -> Path:
    return Path(os.getenv("AICHECK_REPO") or SKILL_DIR.parents[1]).expanduser()


def private_dir(path: Path) -> Path:
    """mkdir -p, then 0700 on the leaf and on every ancestor inside the audit home."""
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    home = audit_home().resolve()
    for current in (path.resolve(), *path.resolve().parents):
        if current != path.resolve() and home not in (current, *current.parents):
            break
        os.chmod(current, 0o700)
    return path


def write_private(path: Path, text: str) -> None:
    private_dir(path.parent)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.chmod(path, 0o600)


def dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- connection

def normalize_base(url: str) -> str:
    url = url.strip().rstrip("/")
    url = url[:-4] if url.endswith("/api") else url
    parts = parse.urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password \
            or parts.query or parts.fragment:
        raise ClientError("invalidUrl", "服务器地址须为不带账号、查询串或片段的 http(s) origin。")
    try:
        loopback = ipaddress.ip_address(parts.hostname).is_loopback
    except ValueError:
        loopback = parts.hostname.lower() == "localhost"
    if parts.scheme == "http" and not loopback and os.getenv("AICHECK_ALLOW_HTTP", "").lower() not in {"1", "true", "yes"}:
        raise ClientError("insecureTransport", "远程地址是明文 HTTP，口令和令牌会明文传输；确认可接受后设置 AICHECK_ALLOW_HTTP=1。")
    return url


def load_session() -> dict[str, Any]:
    try:
        return json.loads(session_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


class Api:
    def __init__(self, base_url: str | None = None):
        session = load_session()
        base = base_url or os.getenv("AICHECK_BASE_URL") or session.get("baseUrl")
        if not base:
            raise ClientError("baseUrlMissing", "未配置服务器地址：设置 AICHECK_BASE_URL 或先执行 login --base-url。")
        self.base = normalize_base(base)
        # 会话令牌只发给签发它的服务器；换地址必须重新登录。
        self.token = os.getenv("AICHECK_TOKEN") or (session.get("token") if session.get("baseUrl") == self.base else None)

    def _request(self, method: str, path: str, *, body: Any = None, auth: bool = False,
                 query: dict[str, Any] | None = None, headers: dict[str, str] | None = None,
                 content: bytes | None = None) -> request.Request:
        url = f"{self.base}/api{path}"
        if query:
            url += "?" + parse.urlencode({k: v for k, v in query.items() if v is not None})
        data = content if content is not None else json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        req = request.Request(url, data=data, method=method)
        req.add_header("Accept", "application/json")
        if data is not None and content is None:
            req.add_header("Content-Type", "application/json")
        for name, value in (headers or {}).items():
            req.add_header(name, value)
        if auth:
            if not self.token:
                raise ClientError("loginRequired", "该接口需要监检账号令牌：请用户在自己的终端执行 login。")
            # unredirected：跳转到对象存储时不带令牌。
            req.add_unredirected_header("Authorization", f"Bearer {self.token}")
        return req

    def call(self, method: str, path: str, *, body: Any = None, auth: bool = False,
             query: dict[str, Any] | None = None, timeout: float = 90, headers: dict[str, str] | None = None,
             content: bytes | None = None) -> Any:
        try:
            return self._call(method, path, body=body, auth=auth, query=query, timeout=timeout, headers=headers, content=content)
        except ClientError as exc:
            # 网关 502/504 多是服务器一时不可用（部署、重启），公示平台暂不可查询回 503，过几秒常常就好；只重试一次，登录不重试。
            if exc.code not in GATEWAY_ERRORS or path.startswith("/auth/"):
                raise
            time.sleep(GATEWAY_RETRY_SECONDS)
            return self._call(method, path, body=body, auth=auth, query=query, timeout=timeout, headers=headers, content=content)

    def upload(self, path: str, content: bytes, *, headers: dict[str, str]) -> Any:
        """原始字节上传（服务器 OCR）。网关重试靠调用方给的 Idempotency-Key 去重。"""
        return self.call("POST", path, auth=True, headers=headers, content=content, timeout=300)

    def _call(self, method: str, path: str, *, body: Any, auth: bool, query: dict[str, Any] | None, timeout: float,
              headers: dict[str, str] | None = None, content: bytes | None = None) -> Any:
        req = self._request(method, path, body=body, auth=auth, query=query, headers=headers, content=content)
        try:
            with request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read() or b"{}")
        except error.HTTPError as exc:
            raise http_error(exc, path) from None
        except (error.URLError, TimeoutError, OSError) as exc:
            raise ClientError("unreachable", f"服务器不可达：{getattr(exc, 'reason', exc)}", path=path) from None
        except ValueError:
            raise ClientError("badResponse", "服务器返回的不是 JSON。", path=path) from None
        if isinstance(payload, dict) and "code" in payload:
            if payload.get("code") not in (0, "0", "OK"):
                raise ClientError(str(payload.get("code")), str(payload.get("message") or "服务器拒绝请求。"), path=path)
            return payload.get("data")
        return payload

    def download(self, path: str, target: Path, *, query: dict[str, Any] | None = None) -> dict[str, Any]:
        req = self._request("GET", path, auth=True, query=query)
        digest, size = hashlib.sha256(), 0
        private_dir(target.parent)
        try:
            with request.urlopen(req, timeout=300) as resp, \
                    os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb") as handle:
                while chunk := resp.read(1 << 16):
                    size += len(chunk)
                    if size > MAX_DOWNLOAD_BYTES:
                        raise ClientError("fileTooLarge", "原件超过 300MB，未下载。", path=path)
                    digest.update(chunk)
                    handle.write(chunk)
                content_type = resp.headers.get("Content-Type", "")
        except error.HTTPError as exc:
            target.unlink(missing_ok=True)
            raise http_error(exc, path) from None
        except ClientError:
            target.unlink(missing_ok=True)
            raise
        except (error.URLError, TimeoutError, OSError) as exc:
            target.unlink(missing_ok=True)
            raise ClientError("unreachable", f"下载失败：{getattr(exc, 'reason', exc)}", path=path) from None
        return {"sha256": digest.hexdigest(), "bytes": size, "contentType": content_type}


def http_error(exc: error.HTTPError, path: str) -> ClientError:
    try:
        payload = json.loads(exc.read() or b"{}")
    except ValueError:
        payload = {}
    finally:
        exc.close()
    payload = payload if isinstance(payload, dict) else {}
    message = str(payload.get("message") or exc.reason or "请求失败")
    code = {401: "loginRequired", 403: "forbidden", 404: "notFound", 429: "rateLimited"}.get(exc.code, f"http{exc.code}")
    details: dict[str, Any] = {"status": exc.code, "path": path}
    if isinstance(payload.get("data"), dict) and "retryAfter" in payload["data"]:
        details["retryAfter"] = payload["data"]["retryAfter"]
    if exc.code == 401:
        message += "（令牌缺失或过期：请用户在自己的终端重新 login）"
    return ClientError(code, message, **details)


# ---------------------------------------------------------------- auth

def cmd_login(args: argparse.Namespace) -> Any:
    if not sys.stdin.isatty():
        raise ClientError("ttyRequired", "login 只能在用户自己的终端里运行：口令由 getpass 读取，不经过对话。")
    base = args.base_url or os.getenv("AICHECK_BASE_URL") or load_session().get("baseUrl")
    if not base:
        raise ClientError("baseUrlMissing", "未配置服务器地址：加 --base-url 或设置 AICHECK_BASE_URL。")
    base = normalize_base(base)
    api = Api(base)
    password = getpass.getpass(f"{args.username} @ {base} 口令（不回显）: ")
    body: dict[str, Any] = {"username": args.username, "password": password}
    if args.tenant_id:
        body["tenantId"] = args.tenant_id
    data = api.call("POST", "/auth/login", body=body)
    user = (data or {}).get("user") or {}
    write_private(session_path(), dump({"baseUrl": base, "token": data["token"], "username": args.username,
                                        "role": user.get("role"), "savedAt": now()}))
    role = user.get("role")
    result = {"baseUrl": base, "username": args.username, "role": role, "sessionFile": str(session_path())}
    if role not in {"inspection", "admin"}:
        result["warning"] = "节点审计工作区只对监检（inspection）或管理员开放，当前角色可能取不到节点资料。"
    return result


def cmd_logout(args: argparse.Namespace) -> Any:
    session = load_session()
    if session.get("token"):
        try:
            Api(session.get("baseUrl")).call("POST", "/auth/logout", auth=True, body={})
        except ClientError:
            pass
    session_path().unlink(missing_ok=True)
    return {"loggedOut": True}


def cmd_connection(args: argparse.Namespace) -> Any:
    api = Api(args.base_url)
    result: dict[str, Any] = {"baseUrl": api.base, "tokenPresent": bool(api.token)}
    for key, path in (("ready", "/readyz"), ("inspectionServices", "/inspection-services/capabilities")):
        try:
            result[key] = api.call("GET", path, timeout=30)
        except ClientError as exc:
            result[key] = {"error": exc.code, "message": exc.message}
    if api.token:
        try:
            me = api.call("GET", "/auth/me", auth=True, timeout=30) or {}
            user = me.get("user", me)
            result["user"] = {k: user.get(k) for k in ("username", "role", "displayName") if k in user}
        except ClientError as exc:
            result["user"] = {"error": exc.code, "message": exc.message}
    return result


# ---------------------------------------------------------------- rules (local business pack)

@functools.lru_cache(maxsize=None)
def load_yaml(path: Path) -> Any:
    try:
        import yaml  # type: ignore
    except ImportError:
        raise ClientError("pyyamlMissing", "读取业务包需要 PyYAML：python3 -m pip install pyyaml，或用 backend/.venv/bin/python 运行。") from None
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


PER_ITEM = re.compile(r"逐(焊口|焊缝|件|张|根|个|条|项|台|批|道|管线|份|人|名)")


# instruction 没写“逐”字、但实际要逐件核对的检查。
PER_ITEM_OVERRIDES = {"AC-R24-04": "逐焊口"}  # 厚度、外径、填充金属要按每道焊口的实际规格核


def check_role(instruction: str, check_id: str = "") -> dict[str, Any]:
    """Every rule has one traceability check; 14 checks (plus overrides) demand item-by-item coverage."""
    role: dict[str, Any] = {}
    if check_id in PER_ITEM_OVERRIDES:
        role["perItem"] = PER_ITEM_OVERRIDES[check_id]
    if "可追溯" in instruction and "不得判定为符合" in instruction:
        role["role"] = "traceability"
    match = PER_ITEM.search(instruction)
    if match and "perItem" not in role:
        role["perItem"] = match.group(0)
    return role


def rule_catalog(node_id: int) -> dict[str, Any]:
    pack = Path(os.getenv("AICHECK_BUSINESS_PACK") or repo_root() / "backend/business_packs/engineering_inspection_v1")
    if not (pack / "rules.yaml").exists():
        raise ClientError("businessPackMissing", f"找不到业务包：{pack}（可设置 AICHECK_REPO 或 AICHECK_BUSINESS_PACK）。")
    rule_id = f"R{node_id:02d}"
    rules = [r for r in load_yaml(pack / "rules.yaml")["ruleSets"]
             if node_id in (r.get("nodeIds") or []) and r.get("sourceRuleId") == rule_id]
    if not rules:
        raise ClientError("ruleNotFound", f"业务包里没有节点 {node_id} 的规则 {rule_id}。")
    node = next((n for n in load_yaml(pack / "nodes.yaml")["nodeTemplates"] if n.get("nodeId") == node_id), {})
    checks = [c for c in load_yaml(pack / "atomic_checks.yaml")["atomicChecks"] if c.get("sourceRuleId") == rule_id]
    bindings = {b["atomicCheckId"]: b for b in load_yaml(pack / "atomic_check_tool_bindings.yaml")["atomicCheckToolBindings"]
                if b.get("sourceRuleId") == rule_id}
    clauses = [c for c in load_yaml(pack / "standard_clause_bindings.yaml")["standardClauseBindings"]
               if c.get("sourceRuleId") == rule_id]
    return {
        "source": "local_business_pack",
        "businessPack": str(pack),
        "ruleId": rule_id,
        "node": {k: node.get(k) for k in ("nodeId", "name", "groupName", "inspectionType", "requiredMaterials")},
        "rule": {k: rules[0].get(k) for k in RULE_FIELDS},
        "atomicChecks": [
            {**{k: c.get(k) for k in ("id", "name", "checkType", "instruction", "evidenceRequired")},
             **check_role(str(c.get("instruction") or ""), c["id"]),
             "serverTools": (bindings.get(c["id"]) or {}).get("tools") or [],
             "requiredFacts": (bindings.get(c["id"]) or {}).get("requiredFacts") or [],
             "toolImplementationStatus": (bindings.get(c["id"]) or {}).get("implementationStatus")}
            for c in checks
        ],
        "standardClauses": [{k: c.get(k) for k in ("standardRef", "clauseNo", "bindingRole", "applicability",
                                                   "verificationStatus", "sourcePage", "knowledgeFileId")}
                            for c in clauses],
    }


def cmd_rules(args: argparse.Namespace) -> Any:
    return rule_catalog(args.node)


# ---------------------------------------------------------------- bundle helpers

def safe_name(name: str) -> str:
    name = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", name).strip(" .") or "file"
    return name[:120]


def bundle_dir(project: str, node: int, out: str | None) -> Path:
    if out:
        return Path(out).expanduser().resolve()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return audit_home() / safe_name(project) / f"node-{node:02d}" / stamp


def latest(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    key = lambda r: str(r.get("updatedAt") or r.get("completedAt") or r.get("createdAt") or "")
    return max(records, key=key) if records else None


def server_outcomes(review_run: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    run = (review_run or {}).get("run", review_run) or {}
    run_id = run.get("reviewRunId") or run.get("id")
    outcomes = {}
    for item in run.get("atomicCheckOutcomes") or []:
        if isinstance(item, dict) and item.get("atomicCheckId"):
            outcomes[item["atomicCheckId"]] = {"result": item.get("result") or item.get("status"),
                                               "decisionSource": item.get("decisionSource"),
                                               "reviewRunId": run_id}
    return outcomes


def field_value(field: dict[str, Any]) -> str:
    value = field.get("fieldValue", field.get("value"))
    return "" if value is None else str(value)


def cell(value: Any) -> str:
    return str("" if value is None else value).replace("|", "\\|").replace("\n", " ")


def flatten_workspace(payload: Any) -> dict[str, Any]:
    """服务器 audit-workspace 把 submission / ocr / evidence / aiReview 等放在 `content` 下；
    包里和后面各处都按顶层键读，所以这里摊平。已经是平铺的（本地 --workspace 模拟文件）原样返回。"""
    if not isinstance(payload, dict):
        return {}
    content = payload.get("content")
    if not isinstance(content, dict):
        return payload
    return {**{k: v for k, v in payload.items() if k != "content"}, **content}


def write_digest(root: Path, manifest: dict[str, Any], rules: dict[str, Any], workspace: dict[str, Any]) -> None:
    """A compact first read for the assistant; full JSON stays alongside."""
    rule = rules["rule"]
    outcomes = manifest.get("serverOutcomes") or {}
    lines = [f"# {manifest.get('projectId')} · 节点 {manifest['nodeId']:02d} · {rules['ruleId']} {rule.get('name')}", "",
             f"- 来源：{manifest['source']}；取数时间：{manifest['fetchedAt']}；服务器：{manifest.get('baseUrl') or '—'}"]
    lines += [f"- ⚠ {w}" for w in manifest.get("warnings") or []]
    lines += ["", "## 规则", "", f"**依据（criteria）**：{rule.get('criteria')}", "",
              f"**审查方法（checkMethod）**：{rule.get('checkMethod')}", "",
              "**参考标准**：" + "、".join(str(s.get("reference") or s) for s in rule.get("referencedStandards") or []), "",
              "**固定主条款**：" + "；".join(f"{c.get('standardRef')} {c.get('clauseNo')}（第{c.get('sourcePage')}页，{c.get('verificationStatus')}）"
                                     for c in rules.get("standardClauses") or []) or "—", "",
              "## 原子检查（每项都要出结论；audit.json 骨架已按这个顺序列好）", ""]
    for check in rules["atomicChecks"]:
        server = outcomes.get(check["id"], {})
        marks = [m for m in ("**证据追溯项**：节点内任一项证据不足/未执行就判证据不足，有冲突就判需人工确认" if check.get("role") == "traceability" else "",
                             f"**逐件核对项（{check['perItem']}）**：判符合要 coverage 且全部覆盖，没有逐件记录就判证据不足" if check.get("perItem") else "") if m]
        lines += [f"### {check['id']} {check['name']}", "", f"- 要做的事：{check.get('instruction')}"]
        lines += [f"- {m}" for m in marks]
        if manifest.get("source") == "server":
            lines.append(f"- 服务器结果：{server.get('result') or '—'}；服务器工具：{', '.join(check['serverTools']) or '—'}")
        lines.append("")
    lines += ["## 资料要求", ""]
    for req in (rules["node"].get("requiredMaterials") or []):
        lines.append(f"- `{req.get('id')}` {req.get('name')}（{req.get('requiredType')}）— {req.get('note') or ''}")
    lines += ["", "## 文件（files/ 下为原件，可直接读取）", "",
              "| 文件 | 资料名 | 挂载状态 | OCR | sha256 前 12 位 |", "|---|---|---|---|---|"]
    for item in manifest["files"]:
        lines.append(f"| `{item['path']}` | {item.get('requirementName') or item.get('fileName')} | "
                     f"{item.get('bindingStatus') or '—'} | {item.get('ocrStatus') or '—'} | {str(item.get('sha256') or '')[:12]} |")
    for item in manifest.get("skippedFiles") or []:
        lines.append(f"| （未收入）{item.get('fileName') or item.get('projectPath')} | — | — | — | {item.get('reason')} |")
    fields = ((workspace.get("ocr") or {}).get("extractedFields") or [])
    if fields:
        by_version = {f.get("documentVersionId"): f.get("path") for f in manifest["files"]}
        lines += ["", "## 服务器抽取字段（OCR 线索，关键值须对照原页）", "",
                  "| 文件 | 页 | 字段 | 值 | 置信度 | 状态 |", "|---|---|---|---|---|---|"]
        for field in fields[:400]:
            value = cell(field_value(field)[:120])
            lines.append(f"| {by_version.get(field.get('documentVersionId')) or field.get('documentVersionId')} | "
                         f"{field.get('pageNo') or '—'} | {field.get('fieldName')} | {value} | "
                         f"{field.get('confidence') if field.get('confidence') is not None else '—'} | {field.get('reviewStatus') or '—'} |")
        if len(fields) > 400:
            lines.append(f"\n（共 {len(fields)} 条，只列前 400 条；全部见 workspace.json → ocr.extractedFields）")
    readiness = (workspace.get("evidence") or {}).get("readiness") or {}
    if readiness:
        lines += ["", "## 服务器证据就绪度", "",
                  f"readyForAiFormal={readiness.get('readyForAiFormal')}，missing={readiness.get('missingCount')}，pending={readiness.get('pendingCount')}"]
        lines += [f"- {r.get('code')}: {r.get('message')}" for r in readiness.get("blockingReasons") or []]
    write_private(root / "digest.md", mask_ids("\n".join(lines) + "\n"))


def finish_bundle(root: Path, manifest: dict[str, Any], rules: dict[str, Any], workspace: dict[str, Any]) -> dict[str, Any]:
    manifest["atomicChecks"] = [c["id"] for c in rules["atomicChecks"]]
    write_private(root / "rules.json", dump(rules))
    write_private(root / "bundle.json", dump(manifest))
    write_digest(root, manifest, rules, workspace)
    return {"bundle": str(root), "digest": str(root / "digest.md"), "files": len(manifest["files"]),
            "skippedFiles": manifest.get("skippedFiles") or [], "atomicChecks": manifest["atomicChecks"],
            "serverOutcomes": len(manifest.get("serverOutcomes") or {}), "warnings": manifest.get("warnings") or []}


# ---------------------------------------------------------------- fetch from server

def cmd_fetch(args: argparse.Namespace) -> Any:
    api = Api(args.base_url)
    project, node = args.project, args.node
    node_path = f"/projects/{parse.quote(project, safe='')}/inspection/nodes/{node}"
    workspace = flatten_workspace(api.call("GET", f"{node_path}/audit-workspace", auth=True))
    root = bundle_dir(project, node, args.out)
    private_dir(root)
    write_private(root / "workspace.json", dump(workspace))
    warnings: list[str] = []
    if not any(key in workspace for key in ("submission", "ocr", "aiReview")):
        warnings.append("服务器 audit-workspace 的返回里没有 submission / ocr / aiReview（也不在 content 下），"
                        "接口结构可能变了：下面“没有挂载资料”“没有审查运行”可能是读不到而不是真没有，先看 workspace.json 再信。")
    parts = {"workspace": "workspace.json"}
    optional = (("serverRule", "rules/current-version", "server-rule.json"),
                ("standards", "standards", "standards.json"),
                ("evidenceChain", "evidence-chain", "evidence-chain.json"))
    fetched: dict[str, Any] = {}
    for key, path, filename in optional:
        try:
            fetched[key] = api.call("GET", f"{node_path}/{path}", auth=True)
            parts[key] = filename
            write_private(root / filename, dump(fetched[key]))
        except ClientError as exc:
            warnings.append(f"{key} 未取到：{exc.code} {exc.message}")

    rules = rule_catalog(node)
    server_rule = (fetched.get("serverRule") or {}).get("rule") or {}
    if server_rule and (node not in (server_rule.get("nodeIds") or []) or server_rule.get("sourceRuleId") != rules["ruleId"]):
        warnings.append(f"服务器规则与节点不一致：节点 {node} 拿到 {server_rule.get('sourceRuleId')}/{server_rule.get('nodeIds')}，"
                        f"审计以本地业务包 {rules['ruleId']} 为准，并在报告里写明。")

    review_run = None
    run_ref = latest(((workspace.get("aiReview") or {}).get("reviewRuns")) or [])
    if run_ref:
        run_id = run_ref.get("reviewRunId") or run_ref.get("id")
        try:
            review_run = api.call("GET", f"/review-runs/{parse.quote(str(run_id), safe='')}", auth=True)
            parts["reviewRun"] = "review-run.json"
            write_private(root / "review-run.json", dump(review_run))
        except ClientError as exc:
            warnings.append(f"最近一次审查运行 {run_id} 未取到：{exc.code} {exc.message}")
    else:
        warnings.append("该节点在服务器上没有审查运行，没有服务器结论可对照。")

    files, skipped = [], []
    documents = ((workspace.get("submission") or {}).get("documents")) or ((workspace.get("ocr") or {}).get("documents")) or []
    for index, doc in enumerate(documents, start=1):
        bindings = doc.get("bindings") or []
        binding = doc.get("primaryBinding") or (bindings[0] if bindings else {})
        version_id = binding.get("documentVersionId") or doc.get("currentVersionId")
        entry = {"documentId": doc.get("id"), "documentVersionId": version_id, "fileName": doc.get("fileName"),
                 "requirementName": binding.get("requirementName"), "bindingStatus": binding.get("bindingStatus"),
                 "materialTypeCode": doc.get("materialTypeCode"),
                 "ocrStatus": (doc.get("ocrReadiness") or {}).get("status")}
        if args.no_files:
            skipped.append({**entry, "reason": "--no-files"})
            continue
        relative = f"files/{index:02d}-{safe_name(str(doc.get('fileName') or doc.get('id')))}"
        try:
            meta = api.download(f"/projects/{parse.quote(project, safe='')}/documents/{parse.quote(str(doc.get('id')), safe='')}/original",
                                root / relative, query={"disposition": "attachment", "versionId": version_id})
            files.append({**entry, "path": relative, **meta})
        except ClientError as exc:
            skipped.append({**entry, "reason": f"{exc.code} {exc.message}"})
    if not documents:
        warnings.append("该节点没有已提交的挂载资料（工作区只给已提交的挂载）。")

    manifest = {"schemaVersion": BUNDLE_SCHEMA, "source": "server", "baseUrl": api.base, "projectId": project,
                "nodeId": node, "ruleId": rules["ruleId"], "fetchedAt": now(), "parts": parts,
                "files": files, "skippedFiles": skipped, "serverOutcomes": server_outcomes(review_run),
                "warnings": warnings}
    return finish_bundle(root, manifest, rules, workspace)


# ---------------------------------------------------------------- local test bundle

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(1 << 16):
            digest.update(chunk)
    return digest.hexdigest()


def skip_file(path: Path) -> bool:
    """Office lock files (~$x.docx), macOS metadata and hidden files are not project material."""
    return path.name.startswith(("~$", ".", "._")) or path.name in {"Thumbs.db", "desktop.ini"}


def cmd_local_init(args: argparse.Namespace) -> Any:
    project = args.project or "LOCAL-TEST"
    root = bundle_dir(project, args.node, args.out)
    if (root / "bundle.json").exists():
        raise ClientError("bundleExists", f"{root} 已有 bundle.json，换一个 --out。")
    sources = [Path(p).expanduser().resolve() for p in args.files or []]
    skipped: list[dict[str, Any]] = []
    project_dir = Path(args.project_dir).expanduser().resolve() if args.project_dir else None
    if project_dir:
        if not project_dir.is_dir():
            raise ClientError("fileNotFound", f"找不到项目目录：{project_dir}")
        found = sorted(p for p in project_dir.rglob("*") if p.is_file())
        hidden = lambda p: skip_file(p) or any(part.startswith(".") or part == "__MACOSX" for part in p.relative_to(project_dir).parts)
        sources += [p for p in found if not hidden(p)]
        skipped = [{"projectPath": str(p.relative_to(project_dir)), "reason": "锁文件、隐藏文件或系统元数据"} for p in found if hidden(p)]
    if not sources:
        raise ClientError("invalidArguments", "用 --project-dir 给整个项目目录（推荐），或用 --files 列文件。")
    missing = [str(p) for p in sources if not p.is_file()]
    if missing:
        raise ClientError("fileNotFound", "找不到文件：" + "、".join(missing))
    workspace: dict[str, Any] = {}
    if args.workspace:
        workspace = json.loads(Path(args.workspace).expanduser().read_text(encoding="utf-8"))
        workspace = flatten_workspace(workspace.get("data", workspace))
    private_dir(root)
    write_private(root / "workspace.json", dump(workspace))
    files = []
    for index, source in enumerate(sources, start=1):
        relative = f"files/{index:02d}-{safe_name(source.name)}"
        private_dir(root / "files")
        shutil.copyfile(source, root / relative)
        os.chmod(root / relative, 0o600)
        entry = {"path": relative, "fileName": source.name, "sha256": sha256_file(source),
                 "bytes": source.stat().st_size, "localSource": str(source)}
        if project_dir and project_dir in source.parents:
            entry["projectPath"] = str(source.relative_to(project_dir))
        files.append(entry)
    review_run = None
    if args.review_run:
        review_run = json.loads(Path(args.review_run).expanduser().read_text(encoding="utf-8"))
        review_run = review_run.get("data", review_run)
    rules = rule_catalog(args.node)
    manifest = {"schemaVersion": BUNDLE_SCHEMA, "source": "local", "baseUrl": None, "projectId": project,
                "nodeId": args.node, "ruleId": rules["ruleId"], "fetchedAt": now(),
                "parts": {"workspace": "workspace.json"}, "files": files, "skippedFiles": skipped,
                "serverOutcomes": server_outcomes(review_run),
                "warnings": ["本地测试资料：没有服务器挂载、OCR 与证据确认状态，资料是否齐备只能按文件本身判断。"]}
    return finish_bundle(root, manifest, rules, workspace)


# ---------------------------------------------------------------- page rendering (PDF too large to open whole)

def parse_pages(spec: str | None, count: int, limit: int = 20) -> list[int]:
    if not spec:
        pages = list(range(1, count + 1))
    else:
        pages = []
        for part in spec.split(","):
            start, _, end = part.strip().partition("-")
            first, last = int(start), int(end or start)
            if not 1 <= first <= last <= count:
                raise ClientError("pageOutOfRange", f"页码 {part} 超出 1–{count}。")
            pages.extend(range(first, last + 1))
    if len(pages) > limit:
        raise ClientError("tooManyPages", f"一次最多 {limit} 页。")
    return pages


def quiet_fitz() -> Any:
    """PyMuPDF prints xref repair messages to stdout, which would corrupt the JSON this CLI prints."""
    import fitz  # type: ignore  # PyMuPDF
    fitz.TOOLS.mupdf_display_errors(False)
    fitz.TOOLS.mupdf_display_warnings(False)
    return fitz


def find_bundle(path: Path) -> Path | None:
    for parent in list(path.parents)[:4]:
        if (parent / "bundle.json").exists():
            return parent
    return None


def pages_out_dir(args: argparse.Namespace, path: Path) -> Path:
    """页图只进资料包：渲染仓库里的标准原件时不加 --bundle 会写进 rules/，那是要提交的目录。"""
    if args.out:
        return Path(args.out).expanduser().resolve()
    if args.bundle:
        bundle = Path(args.bundle).expanduser().resolve()
        if not (bundle / "bundle.json").exists():
            raise ClientError("bundleMissing", f"{bundle} 不是资料包（没有 bundle.json）。")
        return bundle / "pages"
    bundle = find_bundle(path)
    if bundle is None:
        raise ClientError("outputMissing", f"{path.name} 不在资料包里：加 --bundle <资料包>（页图存进它的 pages/），或 --out <目录>。")
    return bundle / "pages"


def parse_clip(value: str | None) -> list[float] | None:
    if not value:
        return None
    try:
        box = [float(v) for v in value.split(",")]
    except ValueError:
        box = []
    if len(box) != 4 or not (0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1):
        raise ClientError("invalidArguments", "--clip 须为 x0,y0,x1,y1，取值 0–1 的页面比例。")
    return box


def render_png(fitz: Any, page: Any, target: Path, *, dpi: int, rotate: int = 0, clip: Any = None) -> Path:
    private_dir(target.parent)
    pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72).prerotate(rotate), clip=clip)
    pix.set_dpi(dpi, dpi)  # 用 matrix 渲染时 PNG 不记分辨率，补上，和 dpi= 渲染的一样
    pix.save(target)
    os.chmod(target, 0o600)
    return target


def clip_rect(fitz: Any, page: Any, box: list[float]) -> Any:
    r = page.rect
    return fitz.Rect(r.x0 + r.width * box[0], r.y0 + r.height * box[1], r.x0 + r.width * box[2], r.y0 + r.height * box[3])


def unrotate_box(box: list[float], rotate: int) -> list[float]:
    """--clip 按转正后的样子给比例坐标；换回未旋转页面上的比例（顺时针转 90/180/270）。"""
    u0, v0, u1, v1 = box
    if rotate == 90:
        return [v0, 1 - u1, v1, 1 - u0]
    if rotate == 180:
        return [1 - u1, 1 - v1, 1 - u0, 1 - v0]
    if rotate == 270:
        return [1 - v1, u0, 1 - v0, u1]
    return box


def resolve_input(args: argparse.Namespace) -> Path:
    """--file 可写资料包里的相对路径（如 files/13-焊工证.pdf），配 --bundle 时按资料包解析。"""
    path = Path(args.file).expanduser()
    if not path.is_absolute() and not path.exists() and getattr(args, "bundle", None):
        candidate = Path(args.bundle).expanduser() / path
        if candidate.exists():
            path = candidate
    return path.resolve()


def form_fields(page: Any) -> int:
    """图纸上的电子章、签名多是表单域，不在页面内容里；有几个就报几个，给“页面上有章”一个工具依据。"""
    try:
        return sum(1 for _ in page.widgets())
    except Exception:  # noqa: BLE001 -- 图片文档没有表单域
        return 0


def contact_sheets(fitz: Any, doc: Any, numbers: list[int], out_dir: Path, stem: str, cols: int, dpi: int) -> list[str]:
    """缩略拼图：每格一页、左上角标页码，每张最多 30 格；用来过目扫描件、找某张表在哪页。
    每格用 get_pixmap 连注释和表单域一起渲染再贴图：show_pdf_page 会漏掉表单域里的电子章。"""
    cell_w, cell_h, label_h, per_sheet = 200, 260, 14, 30
    scale = dpi / 72
    sheets = []
    for k in range(0, len(numbers), per_sheet):
        chunk = numbers[k:k + per_sheet]
        rows = -(-len(chunk) // cols)
        with fitz.open() as canvas:
            sheet = canvas.new_page(width=cols * cell_w, height=rows * (cell_h + label_h))
            for i, number in enumerate(chunk):
                x, y = (i % cols) * cell_w, (i // cols) * (cell_h + label_h)
                page = doc[number - 1]
                fields = form_fields(page)
                sheet.insert_text((x + 4, y + 11), f"p{number}" + (f" 表单域{fields}" if fields else ""), fontsize=9,
                                  fontname="china-s")
                zoom = min((cell_w - 4) / page.rect.width, (cell_h - 4) / page.rect.height) * scale
                thumb = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), annots=True)
                sheet.insert_image(fitz.Rect(x + 2, y + label_h, x + cell_w - 2, y + label_h + cell_h - 2), pixmap=thumb)
                sheet.draw_rect(fitz.Rect(x + 1, y + label_h - 1, x + cell_w - 1, y + label_h + cell_h - 1), color=(0.75, 0.75, 0.75), width=0.5)
            target = out_dir / f"{stem}-sheet-p{chunk[0]:03d}-{chunk[-1]:03d}.png"
            private_dir(target.parent)
            sheet.get_pixmap(dpi=dpi).save(target)
            os.chmod(target, 0o600)
            sheets.append(str(target))
    return sheets


def all_visual_sheets(fitz: Any, args: argparse.Namespace) -> Any:
    """一次给最近一次 search 标出的全部无文字层文件（和文字 PDF 里的扫描页）出缩略拼图。"""
    if not args.bundle:
        raise ClientError("invalidArguments", "--all-visual 要配 --bundle <资料包>。")
    bundle = Path(args.bundle).expanduser().resolve()
    search = latest_search(bundle)
    if not search:
        raise ClientError("searchMissing", "先跑 search，再用 --all-visual。")
    out_dir = Path(args.out).expanduser().resolve() if args.out else bundle / "pages"
    targets = [(path, None) for path in search.get("needsOcr", search.get("needsVisualReview")) or []]
    targets += [(path, pages) for path, pages in (search.get("needsOcrPages", search.get("needsVisualPages")) or {}).items()]
    results, skipped = [], []
    for relative, pages in targets:
        try:
            doc = fitz.open(bundle / relative)
        except Exception:  # noqa: BLE001 -- e.g. a .doc fitz cannot open
            skipped.append({"file": relative, "reason": "不是 PDF 或图片，用 text 转文字，或请用户给 PDF"})
            continue
        with doc:
            numbers = pages if pages and not isinstance(pages, str) else list(range(1, doc.page_count + 1))
            numbers = numbers[:300]
            results.append({"file": relative, "pageCount": doc.page_count,
                            "sheets": contact_sheets(fitz, doc, numbers, out_dir, safe_name(Path(relative).stem), args.cols, args.dpi or 72),
                            "formFieldPages": {n: c for n in numbers if (c := form_fields(doc[n - 1]))}})
    return {"bundle": str(bundle), "files": results, "skipped": skipped}


def cmd_pages(args: argparse.Namespace) -> Any:
    try:
        fitz = quiet_fitz()
    except ImportError:
        raise ClientError("pymupdfMissing", "需要 PyMuPDF：用 backend/.venv/bin/python 运行本命令，或 pip install pymupdf。") from None
    if args.all_visual:
        return all_visual_sheets(fitz, args)
    if not args.file:
        raise ClientError("invalidArguments", "给 --file，或用 --all-visual --bundle 一次过目全部无文字层文件。")
    path = resolve_input(args)
    if not path.is_file():
        raise ClientError("fileNotFound", f"找不到文件：{path}")
    out_dir = pages_out_dir(args, path)
    rotate = args.rotate or 0
    clip_box = parse_clip(args.clip)
    try:
        doc = fitz.open(path)  # PDF，或 png/jpg/tif 等图片（当作单页文档）
    except Exception:  # noqa: BLE001 -- unreadable or unsupported file
        raise ClientError("unsupportedFile", f"{path.name} 不是 PDF 或可识别的图片。") from None
    with doc:
        if not args.pages and not args.sheet:
            if doc.page_count != 1:
                raise ClientError("invalidArguments", f"{path.name} 有 {doc.page_count} 页：给 --pages（如 1-3,7），或用 --sheet 出缩略拼图。")
            args.pages = "1"  # 图片和单页 PDF 不必写 --pages
        stem = safe_name(path.stem)
        result: dict[str, Any] = {"file": str(path), "pageCount": doc.page_count, "outDir": str(out_dir)}
        if args.sheet:
            numbers = parse_pages(args.pages, doc.page_count, limit=300)
            result["sheets"] = contact_sheets(fitz, doc, numbers, out_dir, stem, args.cols, args.dpi or 72)
            result["formFieldPages"] = {n: c for n in numbers if (c := form_fields(doc[n - 1]))}
            return result
        result["pages"] = []
        for number in parse_pages(args.pages, doc.page_count):
            page = doc[number - 1]
            item: dict[str, Any] = {"page": number}
            if not args.text_only:
                clip = clip_rect(fitz, page, unrotate_box(clip_box, rotate)) if clip_box else None
                suffix = ("-clip" + "_".join(f"{v:g}" for v in clip_box)) if clip_box else ""
                suffix += f"-r{rotate}" if rotate else ""
                if clip_box:
                    item["clip"] = clip_box
                if rotate:
                    item["rotate"] = rotate
                target = render_png(fitz, page, out_dir / f"{stem}-p{number:03d}{suffix}.png",
                                    dpi=args.dpi or 150, rotate=rotate, clip=clip)
                item["image"] = str(target)
            text = page.get_text().strip()
            item["text"] = text[:6000]
            item["textLayer"] = bool(text)
            item["formFields"] = form_fields(page)
            result["pages"].append(item)
    return result


# ---------------------------------------------------------------- whole-bundle search

# 全项目资料里最容易漏的事实：工期、证书有效期、材质、人员、管道级别。
COMMON_TERMS = ("计划施工时间", "施工时间", "工期", "开工", "竣工", "有效期", "许可证")
# 原子检查 requiredFacts 里的字段名 → 原件里会写的词；字段缺了就要靠这些词去找。
REQUIRED_FACT_TERMS = {
    "changeClarification": ("设计变更", "变更单", "澄清"), "actualConstructionEnd": ("竣工",),
    "pipelineGrades": ("管道级别", "管道等级", "GC1", "GC2", "GCD"), "scopeCodes": ("许可项目", "许可范围"),
    "titleBlockOrganization": ("标题栏",), "designSealOrganization": ("出图专用章", "设计专用章", "许可印章"),
    "workDate": ("施焊日期", "焊接日期"), "workItems": ("焊口", "焊缝编号"), "qualificationCodes": ("合格项目", "项目代号"),
}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".gif", ".webp"}


# 拉丁补充、希腊字母、数学符号、带圈数字、罗马数字、几何形状：工程文本里的 Φ × ° ≤ Ⅱ ① 都在这里。
READABLE_RANGES = ((0x4E00, 0x9FFF), (0x3000, 0x303F), (0xFF00, 0xFFEF), (0x00A0, 0x03FF),
                   (0x2000, 0x22FF), (0x2150, 0x218F), (0x2460, 0x24FF), (0x25A0, 0x25FF))


def readable_ratio(text: str) -> float:
    if not text:
        return 0.0
    # \x07 是 Word 表格的单元格结束符，\x0b/\x0c 是换行换页。
    good = sum(1 for ch in text if ch.isspace() or ch in "\x07\x0b\x0c" or (ch.isascii() and ch.isprintable())
               or any(low <= ord(ch) <= high for low, high in READABLE_RANGES))
    return good / len(text)


def looks_like_text(text: str) -> bool:
    sample = text[:200000]
    return bool(sample.strip()) and sample.count("\x00") < len(sample) * 0.005 and readable_ratio(sample) >= 0.85


def word97_text(path: Path) -> str:
    """Word 97-2003 .doc text: OLE compound file → WordDocument/Table streams → piece table. Data only, nothing executed."""
    data = path.read_bytes()
    if data[:8] != bytes.fromhex("D0CF11E0A1B11AE1"):
        raise ValueError("not an OLE compound file")
    import struct
    sector_size, mini_size = 1 << struct.unpack_from("<H", data, 0x1E)[0], 1 << struct.unpack_from("<H", data, 0x20)[0]
    first_dir, mini_cutoff, first_minifat, first_difat, n_difat = (struct.unpack_from("<I", data, off)[0]
                                                                   for off in (0x30, 0x38, 0x3C, 0x44, 0x48))
    end = 0xFFFFFFFA
    sector = lambda i: data[(i + 1) * sector_size:(i + 2) * sector_size]
    difat = list(struct.unpack_from("<109I", data, 0x4C))
    nxt = first_difat
    for _ in range(n_difat):
        if nxt >= end:
            break
        values = struct.unpack(f"<{sector_size // 4}I", sector(nxt))
        difat.extend(values[:-1])
        nxt = values[-1]
    fat = [v for s in difat if s < end for v in struct.unpack(f"<{sector_size // 4}I", sector(s))]

    def chain(start: int, table: list[int], read) -> bytes:
        out, seen = [], set()
        while start < end and start not in seen and start < len(table):
            seen.add(start)
            out.append(read(start))
            start = table[start]
        return b"".join(out)

    directory = chain(first_dir, fat, sector)
    entries = []
    for off in range(0, len(directory) - 127, 128):
        entry = directory[off:off + 128]
        name_len = struct.unpack_from("<H", entry, 64)[0]
        entries.append((entry[:max(name_len - 2, 0)].decode("utf-16-le", "replace"), entry[66],
                        struct.unpack_from("<I", entry, 116)[0], struct.unpack_from("<I", entry, 120)[0]))
    ministream = chain(entries[0][2], fat, sector)
    minifat = list(struct.unpack(f"<{len(m) // 4}I", m)) if (m := chain(first_minifat, fat, sector)) else []

    def stream(name: str) -> bytes:
        for entry_name, kind, start, size in entries:
            if entry_name == name and kind == 2:
                if size < mini_cutoff:
                    return chain(start, minifat, lambda i: ministream[i * mini_size:(i + 1) * mini_size])[:size]
                return chain(start, fat, sector)[:size]
        raise ValueError(f"stream {name} missing")

    word = stream("WordDocument")
    table = stream("1Table" if struct.unpack_from("<H", word, 0x0A)[0] & 0x0200 else "0Table")
    fc_clx, lcb_clx = struct.unpack_from("<II", word, 0x1A2)  # FibRgFcLcb97.fcClx
    clx = table[fc_clx:fc_clx + lcb_clx]
    i = 0
    while i < len(clx) and clx[i] == 0x01:  # Prc 块跳过
        i += 3 + struct.unpack_from("<h", clx, i + 1)[0]
    if i >= len(clx) or clx[i] != 0x02:
        raise ValueError("piece table missing")
    lcb = struct.unpack_from("<I", clx, i + 1)[0]
    plc = clx[i + 5:i + 5 + lcb]
    count = (lcb - 4) // 12
    cps = struct.unpack_from(f"<{count + 1}I", plc, 0)
    parts = []
    for k in range(count):
        fc = struct.unpack_from("<I", plc, (count + 1) * 4 + k * 8 + 2)[0]
        chars = cps[k + 1] - cps[k]
        if fc & 0x40000000:
            start = (fc & ~0x40000000) // 2
            parts.append(word[start:start + chars].decode("cp1252", "replace"))
        else:
            parts.append(word[fc:fc + chars * 2].decode("utf-16-le", "replace"))
    text = "".join(parts)
    text = re.sub(r"\x13[^\x13\x14\x15]*\x14", "", text)  # 域代码只留结果
    text = re.sub(r"\x13[^\x13\x14\x15]*\x15", "", text)
    for old, new in (("\r", "\n"), ("\x07", "\t"), ("\x0b", "\n"), ("\x0c", "\n")):
        text = text.replace(old, new)
    return "".join(ch for ch in text if ch in "\n\t" or ord(ch) >= 32)


def office_xml_text(path: Path) -> str:
    import zipfile
    parts = {".docx": ("word/document.xml",), ".xlsx": ("xl/sharedStrings.xml",)}[path.suffix.lower()]
    with zipfile.ZipFile(path) as archive:
        xml = "\n".join(archive.read(name).decode("utf-8", "replace") for name in parts if name in archive.namelist())
    xml = re.sub(r"</w:p>|</si>|</w:tc>", "\n", xml)
    return re.sub(r"<[^>]+>", "", xml)


def file_text(path: Path) -> tuple[str, list[str]]:
    """(status, page texts). status: text | image | office_unreadable | unsupported | pymupdf_missing."""
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return "image", []
    if suffix == ".pdf":
        try:
            fitz = quiet_fitz()
        except ImportError:
            return "pymupdf_missing", []
        with fitz.open(path) as doc:
            return "text", [page.get_text() for page in doc]
    if suffix in {".txt", ".md", ".csv", ".json"}:
        return "text", [path.read_text(encoding="utf-8", errors="replace")]
    if suffix in {".docx", ".xlsx"}:
        try:
            return "text", [office_xml_text(path)]
        except Exception:  # noqa: BLE001 -- a damaged archive is reported, not fatal
            return "office_unreadable", []
    if suffix in {".doc", ".wps"}:
        try:
            text = word97_text(path)
            if looks_like_text(text):
                return "text", [text]
        except Exception:  # noqa: BLE001 -- not Word 97 (RTF/HTML saved as .doc, Word 6): try textutil
            pass
    if suffix in {".doc", ".xls", ".rtf", ".wps"} and shutil.which("textutil"):
        import subprocess
        try:
            out = subprocess.run(["textutil", "-convert", "txt", "-stdout", str(path)], capture_output=True, timeout=60)
        except subprocess.TimeoutExpired:
            return "office_unreadable", []
        text = out.stdout.decode("utf-8", "replace")
        # WPS 存的 .doc 经 textutil 常吐出整份二进制：可读字符太少或夹着大量 NUL 就当没读到。
        if out.returncode or not looks_like_text(text):
            return "office_unreadable", []
        return "text", [text]
    return "unsupported", []


# 按节点所属专业补的默认检索词；材质牌号决定焊工、焊材、元件能否覆盖，焊接和材料类节点必查。
MATERIAL_GRADES = ("材质", "牌号", "不锈钢", "碳钢", "合金钢", "异种钢", "S30408", "S31603", "Q235", "Q245R", "Q345R",
                   "20#", "15CrMo", "12Cr1MoV")
GROUP_TERMS = {
    "焊接": ("焊工", "钢印", "焊工号", "焊口", "施焊", "焊接记录", "焊材", "母材", "规格", *MATERIAL_GRADES),
    "热处理": ("热处理", "硬度", "曲线", "测温", "恒温"),
    "材料": ("质量证明", "炉批号", "复验", "规格", "数量", *MATERIAL_GRADES),
    "阀门": ("阀门", "壳体试验", "密封试验", "试压"),
    "无损检测": ("检测比例", "合格级别", "底片", "RT", "UT", "PT", "MT"),
    "设计": ("设计压力", "设计温度", "管道级别", "设计变更", "审批", "会审"),
    "资质": ("许可证", "许可项目", "许可范围", "有效期"),
    "耐压": ("试验压力", "保压", "压力表", "试验介质"),
    "泄漏": ("泄漏试验", "试验压力", "压力表"),
}


def text_out_path(args: argparse.Namespace, path: Path) -> Path:
    """转出的文字只进资料包：仓库里的标准原件不带 --bundle/--out 会写进 rules/ 旁边。"""
    name = f"{safe_name(path.stem)}.txt"
    if args.out:
        out = Path(args.out).expanduser().resolve()
        return out / name if out.is_dir() or args.out.endswith(("/", os.sep)) else out
    if args.bundle:
        bundle = Path(args.bundle).expanduser().resolve()
        if not (bundle / "bundle.json").exists():
            raise ClientError("bundleMissing", f"{bundle} 不是资料包（没有 bundle.json）。")
        return bundle / "text" / name
    bundle = find_bundle(path)
    if bundle is None:
        raise ClientError("outputMissing", f"{path.name} 不在资料包里：加 --bundle <资料包>（存进它的 text/），或 --out <文件或目录>。")
    return bundle / "text" / name


def cmd_text(args: argparse.Namespace) -> Any:
    path = resolve_input(args)
    if not path.is_file():
        raise ClientError("fileNotFound", f"找不到文件：{path}")
    bundle = Path(args.bundle).expanduser().resolve() if args.bundle else find_bundle(path)
    relative = bundle_relative(bundle, path) if bundle else None
    status, _, pages, used = page_texts(bundle, relative, path)
    ocr_hint = f"先跑 ocr --bundle <资料包>{'' if not relative or relative.startswith('files/') else ' --files ' + relative}（服务器 OCR），再用 text 读 OCR 文字。"
    if status not in {"text", "ocr"}:
        raise ClientError("noTextLayer", f"{path.name}：{status}，没有可取的文字——{ocr_hint}")
    empty = [n for n, text in enumerate(pages, start=1) if len(text.strip()) < 20]
    if pages and len(empty) == len(pages):
        raise ClientError("noTextLayer", f"{path.name} 没有文字层（扫描件）——{ocr_hint}")
    out = text_out_path(args, path)
    label = lambda n: f"--- 第 {n} 页{'（OCR）' if status == 'ocr' or n in used else ''} ---"
    body = "\n\n".join(f"{label(n)}\n{t}" if len(pages) > 1 or status == "ocr" else t for n, t in enumerate(pages, start=1))
    write_private(out, mask_ids(body))
    result = {"file": str(path), "status": status, "pages": len(pages), "chars": sum(len(t) for t in pages), "saved": str(out)}
    if status == "ocr" or used:
        result["ocrPages"] = page_ranges(range(1, len(pages) + 1)) if status == "ocr" else page_ranges(used)
        result["ocrNote"] = "标（OCR）的页是服务器识别的文字；[印章：…]、[签名：…] 是服务器识别的印章、签名，“服务器未读出章上的字”表示有章但没读出字，该事实交人工确认。"
    if empty and len(pages) > 1:
        result["pagesWithoutText"] = page_ranges(empty)  # 这些页文字层和 OCR 里都没有字：跑 ocr；跑过仍是空白的页，相关事实交人工确认
    return result


def captioned_image_pages(path: Path, pages: list[str]) -> list[int]:
    """字很少（<50）又嵌着图片的页：多半是整页证书扫描配一行说明，检索看不到图里的内容。"""
    short = [n for n, text in enumerate(pages, start=1) if 20 <= len(text.strip()) < 50]
    if not short:
        return []
    fitz = quiet_fitz()
    with fitz.open(path) as doc:
        return [n for n in short if doc[n - 1].get_images()]


def default_terms(bundle: Path) -> list[str]:
    rules = json.loads((bundle / "rules.json").read_text(encoding="utf-8"))
    terms = list(COMMON_TERMS)
    group = f"{rules['node'].get('groupName') or ''}{rules['rule'].get('businessModule') or ''}"
    for key, extra in GROUP_TERMS.items():
        if key in group:
            terms += [t for t in extra if t not in terms]
    facts = " ".join(f for check in rules["atomicChecks"] for f in check.get("requiredFacts") or [])
    for key, extra in REQUIRED_FACT_TERMS.items():
        if key in facts:
            terms += [t for t in extra if t not in terms]
    for requirement in rules["node"].get("requiredMaterials") or []:
        for part in re.split(r"[、及和与/（）()\s]+", str(requirement.get("name") or "")):
            if len(part) >= 2 and part not in terms:
                terms.append(part)
    return terms


def cmd_search(args: argparse.Namespace) -> Any:
    bundle = Path(args.bundle).expanduser().resolve()
    manifest = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))
    terms = list(args.terms or []) if args.only else [*default_terms(bundle), *(args.terms or [])]
    terms = list(dict.fromkeys(t for t in terms if t.strip()))
    files, visual, visual_pages, id_files = [], [], {}, {}
    scanned_files, scanned_pages = [], {}
    for item in manifest.get("files") or []:
        path = bundle / item["path"]
        status, layer, pages, used = page_texts(bundle, item["path"], path)
        for text in pages:
            for match in ID_CANDIDATE.finditer(text):
                if is_id_number(match.group(1)):
                    id_files.setdefault(mask_ids(match.group(1)), set()).add(item["path"])
        record: dict[str, Any] = {"path": item["path"], "status": status, "pages": len(pages),
                                  "textChars": sum(len(t.strip()) for t in pages), "hits": []}
        # 扫描页按原件文字层算（报告据此要求这一页有 OCR 文字）；还缺字的页按补过 OCR 的文字算（要先跑 ocr）。
        raw_empty = [n for n, text in enumerate(layer, start=1) if len(text.strip()) < 20]
        if status == "text" and item["path"].lower().endswith(".pdf"):
            raw_empty = sorted(set(raw_empty) | set(captioned_image_pages(path, layer)))
        if status not in {"text"} or (layer and len(raw_empty) == len(layer)):
            scanned_files.append(item["path"])
        elif raw_empty:
            scanned_pages[item["path"]] = raw_empty
        empty = [n for n, text in enumerate(pages, start=1) if len(text.strip()) < 20 and n not in used]
        if status == "text" and item["path"].lower().endswith(".pdf"):
            empty = sorted(set(empty) | (set(captioned_image_pages(path, layer)) - used))
        if used:
            record["ocrPages"] = page_ranges(used)
        if empty and len(pages) > 1:
            record["pagesWithoutText"] = empty if len(empty) <= 30 else f"{len(empty)} 页"
        if status not in {"text", "ocr"} or (pages and len(empty) == len(pages)):
            visual.append(item["path"])
        elif empty and len(pages) > 1:
            visual_pages[item["path"]] = empty  # 部分页是扫描件、也还没 OCR：检索看不到这些页
        per_term: dict[str, int] = {}
        for page_no, text in enumerate(pages, start=1):
            flat = re.sub(r"\s+", " ", text)
            for term in terms:
                for match in re.finditer(re.escape(term), flat):
                    if per_term.get(term, 0) >= args.max_per_term:
                        break
                    per_term[term] = per_term.get(term, 0) + 1
                    record["hits"].append({"page": page_no, "term": term,
                                           "snippet": flat[max(0, match.start() - 40): match.end() + 60]})
        files.append(record)
    # 文字层里有的身份证号可直接用脱敏号查 cert-registry；不在这里的只在图片上，要照原件读。
    id_numbers = {masked: sorted(paths) for masked, paths in sorted(id_files.items())}
    target = bundle / "search" / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    write_private(target, dump_masked({"at": now(), "bundle": str(bundle), "terms": terms, "files": files,
                                        "needsOcr": visual, "needsOcrPages": visual_pages,
                                        "scannedFiles": scanned_files, "scannedPages": scanned_pages,
                                        "idNumbersInText": id_numbers}))
    files.sort(key=lambda f: -len(f["hits"]))
    term_files = {t: sorted({f["path"] for f in files for h in f["hits"] if h["term"] == t}) for t in terms}
    zero_hit = [t for t, paths in term_files.items() if not paths]
    # 输出只给摘要，一行一份文件、按词列命中页；逐条命中和片段在 saved 的 JSON 里。
    return {
        "bundle": str(bundle),
        "saved": str(target),
        "termHitFiles": "、".join(f"{t} {len(paths)}" for t, paths in term_files.items() if paths),
        "zeroHitTerms": "、".join(zero_hit),
        **({"zeroHitNote": zero_hit_note(len(visual), len(visual_pages))} if zero_hit and (visual or visual_pages) else {}),
        "filesWithHits": [{"path": f["path"], "hitCount": len(f["hits"]),
                           "termPages": "、".join(f"{t} p{page_ranges(p)}" for t, p in term_pages(f["hits"]).items()),
                           **({"ocrPages": f["ocrPages"]} if f.get("ocrPages") else {}),
                           "sample": [f"p{h['page']} [{h['term']}] {h['snippet']}" for h in f["hits"][:args.sample]]}
                          for f in files if f["hits"]],
        "filesWithoutHits": [f["path"] for f in files if not f["hits"] and f["path"] not in visual],
        "needsOcr": visual,
        "needsOcrPages": {path: page_ranges(pages) for path, pages in visual_pages.items()},
        "idNumbersInText": {masked: "、".join(paths) for masked, paths in list(id_numbers.items())[:30]},
    }


def zero_hit_note(scanned_files: int, partly_scanned: int) -> str:
    """零命中只对有文字（文字层或 OCR）的文件成立；还没 OCR 的扫描件没被检索到，不能凭零命中说“没有”。"""
    parts = [f"{scanned_files} 份图片或扫描件（needsOcr）" if scanned_files else "",
             f"{partly_scanned} 份文件的部分扫描页（needsOcrPages）" if partly_scanned else ""]
    return ("零命中只对有文字的文件有效；" + "、".join(p for p in parts if p)
            + "还没 OCR，没有被检索到，这些词可能在那里。要说“没有”，先跑 ocr 再检索。")


def term_pages(hits: list[dict[str, Any]]) -> dict[str, set[int]]:
    pages: dict[str, set[int]] = {}
    for hit in hits:
        pages.setdefault(hit["term"], set()).add(hit["page"])
    return dict(sorted(pages.items()))


def page_ranges(numbers: Any) -> str:
    """[1, 2, 3, 7] → "1-3,7"。"""
    ordered, parts = sorted(numbers), []
    for n in ordered:
        if parts and n == parts[-1][1] + 1:
            parts[-1][1] = n
        else:
            parts.append([n, n])
    return ",".join(str(a) if a == b else f"{a}-{b}" for a, b in parts)


# ---------------------------------------------------------------- OCR（经服务器：MinerU，排队超时自动改 qwen）
#
# 扫描件、图片不让助手自己看图：交给 AIcheck 服务器做 OCR。服务器用它自己配的 MinerU，MinerU 连续排队
# 超时会自动改用千问识别（qwen 兜底），本机不需要任何 OCR 密钥，用监检登录令牌即可。结果按页给出文字、
# 表格、印章、签名，助手读文字。2026-10-27 用 TSG Z6002 两页实测：MinerU 项目代号逐字全对、合并单元格
# 表格全对。服务器没有“对某一页问一个问题”的接口：OCR 后仍缺的事实交人工确认。

OCR_UPLOAD_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".doc", ".docx", ".ppt", ".pptx"}
OCR_MAX_BYTES = 100 * 1024 * 1024
OCR_ACTIVE = {"queued", "running"}
OCR_FAILED = {"failed", "canceled"}
OCR_POLL_SECONDS = 30  # 服务器查状态、取结果每次都整表加载 OCR 记录，别查太勤；它建议更久就听它的
OCR_FILL_BELOW = 50  # 文字层不到这么多字的页（扫描页、整页证书配一行说明）用 OCR 文字补
LATEX_SYMBOLS = {r"\geqslant": "≥", r"\leqslant": "≤", r"\geq": "≥", r"\leq": "≤", r"\ge": "≥", r"\le": "≤",
                 r"\sim": "~", r"\times": "×", r"\pm": "±", r"\varphi": "φ", r"\phi": "φ", r"\Phi": "Φ",
                 r"\circ": "°", r"\%": "%", r"\mu": "μ", r"\alpha": "α", r"\beta": "β", r"\delta": "δ",
                 r"\Delta": "Δ", r"\sigma": "σ", r"\cdot": "·", r"\approx": "≈", r"\neq": "≠", r"\infty": "∞"}
INLINE_MATH = re.compile(r"\$\$?([^$]{1,300}?)\$\$?")


def latex_plain(expr: str) -> str:
    """MinerU 把 14mm 写成 $14\\mathrm{mm}$、≥300 写成 $\\geqslant 300$：转回原件上的写法，检索才对得上。"""
    text = expr.replace("~", " ")  # LaTeX 里 ~ 是空格；\sim 才是波浪号，下面再换
    for _ in range(3):  # \mathrm{\mathbf{x}} 这类嵌套
        text = re.sub(r"\\(?:mathrm|text|textrm|mathbf|mathit|operatorname|rm|bf|it)\s*\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\^\s*\{?\s*\\circ\s*\}?", "°", text)
    for command in sorted(LATEX_SYMBOLS, key=len, reverse=True):
        text = re.sub(re.escape(command) + r"(?![A-Za-z])", LATEX_SYMBOLS[command], text)
    text = re.sub(r"[_^]\s*\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"[_^]\s*(\w)", r"\1", text)
    text = re.sub(r"\\[A-Za-z]+", "", text).replace("{", "").replace("}", "").replace("\\", "")
    text = re.sub(r"\s*([≥≤<>±~×=·])\s*", r"\1", text)
    text = re.sub(r"(?<=\d)\s+(?=[A-Za-z°%μ])", "", text)  # 14 mm → 14mm，和原件一致
    text = re.sub(r"([φΦ])\s+(?=\d)", r"\1", text)  # φ 89 → φ89
    return re.sub(r"\s+", " ", text).strip()


def plain_latex(text: str) -> str:
    return INLINE_MATH.sub(lambda m: latex_plain(m.group(1)), text)


class TableGrid(HTMLParser):
    """MinerU 的表格是带 rowspan/colspan 的 HTML。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[tuple[str, int, int]]] = []
        self.row: list[tuple[str, int, int]] | None = None
        self.cell: list[str] | None = None
        self.span = (1, 1)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self.row = []
        elif tag in ("td", "th"):
            values = dict(attrs)
            span = []
            for name in ("rowspan", "colspan"):
                try:
                    span.append(min(max(int(values.get(name) or 1), 1), 100))
                except ValueError:
                    span.append(1)
            self.cell, self.span = [], (span[0], span[1])
        elif tag == "br" and self.cell is not None:
            self.cell.append(" ")

    def handle_data(self, data: str) -> None:
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self.cell is not None:
            if self.row is None:
                self.row = []
            self.row.append((re.sub(r"\s+", " ", "".join(self.cell)).strip(), *self.span))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def table_text(html: str) -> str:
    """合并单元格按格展开：值在所跨的每一行、每一列都重复一次，逐行读就知道每一行的完整取值。"""
    grid = TableGrid()
    grid.feed(html)
    grid.close()
    cells: dict[tuple[int, int], str] = {}
    for r, row in enumerate(grid.rows):
        c = 0
        for text, rowspan, colspan in row:
            while (r, c) in cells:
                c += 1
            for dr in range(rowspan):
                for dc in range(colspan):
                    cells[(r + dr, c + dc)] = text
            c += colspan
    if not cells:
        return plain_latex(re.sub(r"<[^>]+>", " ", html))
    width = max(c for _, c in cells) + 1
    lines = []
    for r in range(max(r for r, _ in cells) + 1):
        values = [plain_latex(cells.get((r, c), "")) for c in range(width)]
        while values and not values[-1]:
            values.pop()
        lines.append(" | ".join(values))
    return "\n".join(lines)


def first_text(row: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def page_of(row: dict[str, Any]) -> int | None:
    try:
        number = int(row.get("pageNo"))
    except (TypeError, ValueError):
        return None
    return number if number >= 1 else None


def server_ocr_pages(result: dict[str, Any]) -> dict[int, str]:
    """服务器 OCR 结果 → {物理页: 文字}：文字块按阅读顺序排；表格用原 HTML 展开合并单元格；印章、签名各记一行。"""
    pages: dict[int, list[tuple[int, str]]] = {}
    for fragment in result.get("fragments") or []:
        if not isinstance(fragment, dict) or page_of(fragment) is None:
            continue
        html = fragment.get("tableHtml")
        text = table_text(html) if isinstance(html, str) and "<t" in html else plain_latex(first_text(fragment, ("text",)))
        if text:
            order = fragment.get("readingOrder") if isinstance(fragment.get("readingOrder"), int) else 10 ** 6
            pages.setdefault(page_of(fragment), []).append((order, text))
    tail = 10 ** 7  # 印章、签名排在本页文字后面
    for seal in result.get("seals") or []:
        if isinstance(seal, dict) and page_of(seal):
            text = first_text(seal, ("text", "sealText", "recognizedText", "ocrText", "content"))
            pages.setdefault(page_of(seal), []).append((tail, f"[印章：{text or '服务器未读出章上的字'}]"))
    for signature in result.get("signatures") or []:
        if isinstance(signature, dict) and page_of(signature):
            text = first_text(signature, ("text", "name", "recognizedText", "content"))
            pages.setdefault(page_of(signature), []).append((tail + 1, f"[签名：{text or '有手写签名'}]"))
    count = result.get("pageCount") if isinstance(result.get("pageCount"), int) else 0
    count = max([count, *pages]) if pages else count
    return {n: "\n".join(text for _, text in sorted(pages.get(n, []), key=lambda item: item[0])) for n in range(1, count + 1)}


def server_ocr_fields(result: dict[str, Any]) -> list[dict[str, Any]]:
    fields = []
    for row in [*(result.get("fields") or []), *(result.get("documentFields") or [])]:
        if isinstance(row, dict):
            name = first_text(row, ("fieldName", "name", "label", "key"))
            value = row.get("fieldValue", row.get("value", row.get("normalizedValue")))
            if name and value not in (None, ""):
                fields.append({"name": name, "value": str(value), "pageNo": page_of(row)})
    return fields


SHA_CACHE: dict[tuple[str, int, int], str] = {}


def cached_sha(path: Path) -> str:
    info = path.stat()
    key = (str(path), info.st_size, info.st_mtime_ns)
    if key not in SHA_CACHE:
        SHA_CACHE[key] = sha256_file(path)
    return SHA_CACHE[key]


def ocr_key(relative: str) -> str:
    return safe_name(relative.replace("/", "__").replace(":", "_"))


def ocr_record_path(bundle: Path, relative: str) -> Path:
    return bundle / "ocr" / f"{ocr_key(relative)}.json"


def ocr_text_path(bundle: Path, relative: str) -> Path:
    return bundle / "text" / f"{safe_name(Path(relative).stem)}.ocr.txt"


def load_ocr(bundle: Path | None, relative: str | None, path: Path) -> dict[str, Any] | None:
    """本包里这份原件的 OCR 记录；原件改过（sha256 不同）就当没有。"""
    if bundle is None or relative is None:
        return None
    try:
        record = json.loads(ocr_record_path(bundle, relative).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict) or record.get("sha256") != cached_sha(path):
        return None
    return record


def ocr_page_map(record: dict[str, Any]) -> dict[int, str]:
    pages = {}
    for item in record.get("pages") or []:
        try:
            pages[int(item["page"])] = str(item.get("text") or "")
        except (KeyError, TypeError, ValueError):
            continue
    return pages


def page_texts(bundle: Path | None, relative: str | None, path: Path) -> tuple[str, list[str], list[str], set[int]]:
    """(状态, 文字层每页, 用 OCR 补过的每页, 用了 OCR 的页)。没有 OCR 记录时后两份同文字层。
    状态 ocr 表示原件本身没有可取的文字，整份文字来自 OCR。"""
    status, layer = file_text(path)
    record = load_ocr(bundle, relative, path)
    if not record:
        return status, layer, layer, set()
    ocr = ocr_page_map(record)
    if status != "text" or not layer or all(len(t.strip()) < 20 for t in layer):
        count = max([*ocr, len(layer)]) if ocr else len(layer)
        return "ocr", layer, [ocr.get(n, "") for n in range(1, count + 1)], {n for n, t in ocr.items() if t.strip()}
    merged, used = list(layer), set()
    for number, text in ocr.items():
        if 1 <= number <= len(layer) and text.strip() and len(layer[number - 1].strip()) < OCR_FILL_BELOW:
            merged[number - 1] = f"{layer[number - 1].strip()}\n{text}".strip()
            used.add(number)
    return status, layer, merged, used


def bundle_relative(bundle: Path, path: Path) -> str | None:
    """资料包里的原件写 files/…；仓库里的标准原件写 standard:rules/…，和报告出处的写法一致。"""
    resolved = path.resolve()
    if resolved.is_relative_to(bundle.resolve()):
        return str(resolved.relative_to(bundle.resolve()))
    root = repo_root().resolve()
    if resolved.is_relative_to(root):
        return "standard:" + str(resolved.relative_to(root))
    return None


def ocr_reason(path: Path) -> str | None:
    """这份原件为什么要 OCR；不需要（文字层齐）或服务器收不了时返回 None。"""
    status, layer = file_text(path)
    if status == "pymupdf_missing":
        raise ClientError("pymupdfMissing", "需要 PyMuPDF：用 backend/.venv/bin/python 运行本命令，或 pip install pymupdf。")
    if status == "image":
        return "图片"
    if status == "office_unreadable" and path.suffix.lower() in OCR_UPLOAD_SUFFIXES:
        return "转不出文字的 Office 文件"
    if status == "text" and path.suffix.lower() == ".pdf":
        empty = sorted({n for n, t in enumerate(layer, start=1) if len(t.strip()) < 20} | set(captioned_image_pages(path, layer)))
        if empty:
            return "扫描件" if len(empty) == len(layer) else f"第 {page_ranges(empty)} 页是扫描页"
    return None


def upload_payload(path: Path, sha: str) -> tuple[str, bytes]:
    """上传名只用哈希：文件名里常有人名，没必要给出去。服务器不收的图片格式先转 PNG。"""
    suffix = path.suffix.lower()
    if suffix in OCR_UPLOAD_SUFFIXES:
        return f"{sha[:16]}{suffix}", path.read_bytes()
    if suffix not in IMAGE_SUFFIXES:
        raise ClientError("unsupportedFile", f"{path.name}：服务器 OCR 不收这种格式，请用户转成 PDF。")
    try:
        fitz = quiet_fitz()
        pix = fitz.Pixmap(str(path))
        if pix.alpha or pix.n > 3:
            pix = fitz.Pixmap(fitz.csRGB, pix)
        return f"{sha[:16]}.png", pix.tobytes("png")
    except Exception:  # noqa: BLE001 -- 转不了就跳过这份，不让整批失败
        raise ClientError("unsupportedFile", f"{path.name}：服务器 OCR 不收这种图片格式，也转不成 PNG。") from None


def check_egress(bundle: Path, manifest: dict[str, Any], allowed: bool) -> None:
    """服务器节点的资料本来就在服务器上、服务器自己做过 OCR；本地资料第一次上传要用户点头。"""
    marker = bundle / "ocr" / "egress-approved.json"
    if manifest.get("source") == "server" or marker.exists():
        return
    if not allowed:
        raise ClientError("egressNotApproved", "本地资料包：ocr 会把原件上传到 AIcheck 服务器（服务器会留存原件，并交 MinerU、千问识别），"
                                               "里面可能有身份证号等个人信息。先问用户是否同意；同意后加 --allow-egress（每个资料包只需一次）。")
    write_private(marker, dump({"approvedAt": now(), "note": "用户同意把本资料包的原件上传到 AIcheck 服务器做 OCR"}))


def ocr_text(record: dict[str, Any]) -> str:
    provider = "千问（MinerU 排队超时后服务器改用）" if record.get("provider") == "qwen" else "MinerU"
    head = (f"（服务器 OCR 文字，识别：{provider}；不是原件文字层。表格已按格展开：合并单元格的值在所跨的每一行重复；"
            "[印章：…]、[签名：…] 是服务器识别的印章、签名。）")
    body = "\n\n".join(f"--- 第 {p['page']} 页 ---\n{p['text']}" for p in record.get("pages") or [])
    fields = record.get("fields") or []
    if fields:
        body += "\n\n--- 服务器抽取的字段（只作线索，以上面的页文字为准） ---\n" + "\n".join(
            f"{f['name']}：{f['value']}" + (f"（第 {f['pageNo']} 页）" if f.get("pageNo") else "") for f in fields)
    return f"{head}\n\n{body}\n"


def store_ocr(bundle: Path, item: dict[str, Any], status: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    pages = server_ocr_pages(result)
    processing = result.get("processing") if isinstance(result.get("processing"), dict) else {}
    provider = str(processing.get("provider") or status.get("provider") or "mineru")
    record = {"file": item["file"], "sha256": item["sha256"], "engine": "aicheck-server", "provider": provider,
              "fallback": processing.get("fallback") or status.get("fallback"), "jobId": item["jobId"],
              "quality": result.get("quality"), "documentType": result.get("documentType"), "at": now(),
              "pages": [{"page": n, "text": t} for n, t in sorted(pages.items())], "fields": server_ocr_fields(result)}
    write_private(ocr_record_path(bundle, item["file"]), dump(record))  # 原文（含完整证号），只给脚本回查用
    target = ocr_text_path(bundle, item["file"])
    write_private(target, mask_ids(ocr_text(record)))
    blank = [n for n, t in pages.items() if not t.strip()]
    return {"file": item["file"], "pages": len(pages), "chars": sum(len(t) for t in pages.values()), "provider": provider,
            "saved": str(target), **({"blankPages": page_ranges(blank)} if blank else {})}


def ocr_targets(bundle: Path, manifest: dict[str, Any], files: list[str] | None) -> tuple[list[tuple[str, Path]], list[dict[str, Any]]]:
    skipped: list[dict[str, Any]] = []
    if not files:
        return [(item["path"], bundle / item["path"]) for item in manifest.get("files") or []
                if ocr_reason(bundle / item["path"])], skipped
    targets = []
    for name in files:
        path = repo_root() / name.removeprefix("standard:") if name.startswith("standard:") else bundle / name
        if not path.exists() and Path(name).expanduser().exists():
            path = Path(name).expanduser()
        relative = bundle_relative(bundle, path) if path.is_file() else None
        if relative is None:
            skipped.append({"file": name, "reason": "找不到，或不在资料包、仓库里"})
        else:
            targets.append((relative, path.resolve()))
    return targets, skipped


# 服务器暂时不可用：API 每约半小时被内存守卫重启一次（502/503/504 或连不上，约一分钟），不能因此中止整个 OCR。
OCR_TRANSIENT = GATEWAY_ERRORS | {"unreachable"}
OCR_RETRY_PAUSES = (10, 20, 30)  # 上传遇到上面的错误时的等待；轮询不重试，下一轮再查就是退避


def is_transient(exc: ClientError) -> bool:
    return exc.code in OCR_TRANSIENT


def with_server_retry(call: Any) -> Any:
    """服务器暂时不可用时按 OCR_RETRY_PAUSES 重试几次；仍不行就把最后一次的错误抛出去，由调用方决定怎么办。"""
    for pause in (*OCR_RETRY_PAUSES, None):
        try:
            return call()
        except ClientError as exc:
            if not is_transient(exc) or pause is None:
                raise
            time.sleep(pause)


def ocr_attempts_path(bundle: Path) -> Path:
    return bundle / "ocr" / "attempts.json"


def load_attempts(bundle: Path) -> dict[str, int]:
    """{原件哈希: 已经用掉的重试次数}。服务器的幂等记录不过期：同一个键永远拿回第一次建的任务，
    任务失败了也一样，所以重试必须换键。"""
    try:
        data = json.loads(ocr_attempts_path(bundle).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): v for k, v in data.items() if isinstance(v, int) and v > 0} if isinstance(data, dict) else {}


def save_attempts(bundle: Path, attempts: dict[str, int]) -> None:
    write_private(ocr_attempts_path(bundle), dump(attempts))


def idempotency_key(sha: str, attempt: int) -> str:
    base = f"aicheck-node-audit-{sha[:48]}"
    return base if attempt <= 0 else f"{base}-r{attempt}"


def record_failed_attempt(bundle: Path, attempts: dict[str, int], item: dict[str, Any]) -> None:
    """任务失败、取消或完成了却没有结果：下次上传换新键，才会建新任务，而不是拿回这个失败的。"""
    sha = item["sha256"]
    attempts[sha] = max(attempts.get(sha, 0), int(item.get("attempt") or 0) + 1)
    save_attempts(bundle, attempts)


def cmd_ocr(args: argparse.Namespace) -> Any:
    bundle = Path(args.bundle).expanduser().resolve()
    if not (bundle / "bundle.json").exists():
        raise ClientError("bundleMissing", f"{bundle} 不是资料包（没有 bundle.json）。")
    manifest = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))
    api = Api(args.base_url)
    if not api.token:
        raise ClientError("loginRequired", "OCR 由服务器做，要监检账号令牌：请用户在自己的终端执行 login。")
    targets, skipped = ocr_targets(bundle, manifest, args.files)
    if any(not relative.startswith("standard:") for relative, _ in targets):
        check_egress(bundle, manifest, args.allow_egress)
    state_path = bundle / "ocr" / "pending.json"
    try:
        pending = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pending = []
    waiting = {item["sha256"] for item in pending}
    attempts = load_attempts(bundle)
    cached, failed = [], []
    server_down = ""  # 上传时服务器一直不可用：后面的文件不再试，别一份份耗时间
    for relative, path in targets:
        finished = load_ocr(bundle, relative, path)
        if finished and not args.force:
            cached.append(relative)
            continue
        sha = cached_sha(path)
        if sha in waiting:
            continue  # 上次交了还没出结果：接着等，不重传
        if server_down:
            failed.append({"file": relative, "reason": server_down, "retryable": True})
            continue
        if path.stat().st_size > OCR_MAX_BYTES:
            skipped.append({"file": relative, "reason": "超过 100MB，服务器 OCR 不收"})
            continue
        try:
            name, content = upload_payload(path, sha)
        except ClientError as exc:
            skipped.append({"file": relative, "reason": exc.message})
            continue
        # 同一份原件同一个键：网关重试、重跑都拿回原来的任务，不会重复识别。要重做已完成的文件（--force）
        # 或上次失败了，就换键（r1、r2…）：服务器的幂等记录不过期，同键永远是第一次的那个任务。
        attempt = attempts.get(sha, 0) + (1 if finished else 0)
        metadata = base64.urlsafe_b64encode(json.dumps({"fileName": name, "options": {"language": "ch"}}).encode()).decode()
        headers = {"Content-Type": "application/octet-stream", "Idempotency-Key": idempotency_key(sha, attempt),
                   "X-AICheck-Ocr-Metadata-B64": metadata}
        try:
            data = with_server_retry(lambda body=content, hdrs=headers: api.upload("/internal/ocr/mineru/tasks/upload", body, headers=hdrs))
        except ClientError as exc:
            if not is_transient(exc):
                raise
            # 请求可能已经在服务器上建了任务：键没变，稍后重跑会拿回它，不会重复建，所以这里不动重试计数。
            server_down = f"服务器暂时不可用（{exc.code}），没有上传：稍后重跑同一条 ocr 命令，键不变，不会重复建任务。"
            failed.append({"file": relative, "reason": server_down, "retryable": True})
            continue
        job_id = str((data or {}).get("jobId") or "")
        if not job_id:
            raise ClientError("badResponse", "服务器没有返回 OCR 任务号。")
        if attempt != attempts.get(sha, 0):
            attempts[sha] = attempt
            save_attempts(bundle, attempts)
        pending.append({"file": relative, "sha256": sha, "jobId": job_id, "attempt": attempt, "submittedAt": now()})
        write_private(state_path, dump(pending))
    done = []
    deadline = time.monotonic() + (0 if server_down else max(args.timeout, 0))
    while pending:
        left, waits = [], []
        for item in pending:
            path = f"/internal/ocr/mineru/tasks/{parse.quote(item['jobId'], safe='')}"
            try:
                status = api.call("GET", path, auth=True) or {}
                state = str(status.get("status") or "")
                result = api.call("GET", f"{path}/result", auth=True) or {} if state == "success" else {}
            except ClientError as exc:
                if not is_transient(exc):
                    raise
                # 服务器重启中：不是识别失败。任务还在，记着，下一轮（或下次重跑）再查。
                left.append({**item, "state": "unreachable", "message": f"服务器暂时不可用（{exc.code}），稍后接着等"})
                continue
            if state == "success":
                if result.get("resultAvailable") is False:
                    failed.append({"file": item["file"], "reason": "服务器说识别完成，但没有结果"})
                    record_failed_attempt(bundle, attempts, item)
                else:
                    done.append(store_ocr(bundle, item, status, result))
            elif state in OCR_FAILED:
                codes = "、".join(str(d.get("code")) for d in status.get("diagnostics") or [] if isinstance(d, dict) and d.get("code"))
                failed.append({"file": item["file"], "reason": f"服务器 OCR {state}" + (f"：{codes}" if codes else "")})
                record_failed_attempt(bundle, attempts, item)
            else:
                left.append({**item, "state": state or "unknown", "provider": status.get("provider"),
                             "message": status.get("statusMessage")})
                if isinstance(status.get("recommendedPollSeconds"), int):
                    waits.append(status["recommendedPollSeconds"])
        pending = left
        if pending:
            write_private(state_path, dump(pending))
        else:
            state_path.unlink(missing_ok=True)
        pause = max([OCR_POLL_SECONDS, *waits])
        if not pending or time.monotonic() + pause > deadline:
            break
        time.sleep(pause)
    result: dict[str, Any] = {"bundle": str(bundle), "done": done, "cached": cached, "skipped": skipped, "failed": failed}
    steps = []
    if pending:
        result["pending"] = [{k: i.get(k) for k in ("file", "state", "provider", "message")} for i in pending]
        if any(i.get("state") == "unreachable" for i in pending):
            steps.append("服务器暂时不可用（API 每约半小时重启一次，约一分钟）：等一两分钟再跑同一条 ocr 命令接着等，任务还在，不会重新上传。")
        else:
            steps.append("服务器还在识别：过一两分钟再跑同一条 ocr 命令接着等，不会重新上传。")
    if any(not f.get("retryable") for f in failed):
        steps.append("失败的文件：再跑一次同一条 ocr 命令会换新任务重试一次（已记下重试次数）；仍失败就写进 limitations，相关事实交人工确认。")
    if any(f.get("retryable") for f in failed):
        steps.append(server_down or "服务器暂时不可用，没有上传的文件稍后重跑同一条 ocr 命令，不会重复建任务。")
    if not steps and (done or cached):
        steps.append("重跑 search，检索就带上 OCR 文字；读某份文件用 text --file（扫描页给的是 OCR 文字）。")
    if steps:
        result["nextStep"] = "；".join(steps)
    if not targets:
        result["note"] = "没有需要 OCR 的文件：包里的原件都有文字层。"
    return result


def ocr_coverage(bundle: Path, known: list[str]) -> dict[str, set[int]]:
    """每份原件哪些页有 OCR 文字；报告里确定结论引用的扫描页必须落在这里。"""
    pages: dict[str, set[int]] = {}
    for relative in known:
        path = bundle / relative
        record = load_ocr(bundle, relative, path) if path.is_file() else None
        if record:
            pages[relative] = {n for n, t in ocr_page_map(record).items() if t.strip()}
    return pages


# ---------------------------------------------------------------- server tools

def cmd_cert_registry(args: argparse.Namespace) -> Any:
    identifier = args.identifier.strip().upper()
    if args.kind == "person" and MASKED_ID.fullmatch(identifier):
        identifier = resolve_masked_id(identifier, args.bundle)
    pattern = r"\d{17}[\dX]" if args.kind == "person" else r"TS\d{7}-\d{4}"
    if args.kind != "person" and re.fullmatch(r"TS[0-9A-Z]{7}-\d{4}", identifier) and not re.fullmatch(pattern, identifier):
        # 有些许可证号中间带字母（如 TS2710A12-2030），服务器登记接口目前只收纯数字格式，发过去也会被拒。
        raise ClientError("unsupportedLicenceFormat",
                          "这个许可证号带字母，服务器的登记查询接口目前只支持 TS+7 位数字-4 位。登记核验这一维记为未完成："
                          "请监检人员在全国特种设备公示信息查询平台手工核验，并在报告 limitations 写明。")
    if not re.fullmatch(pattern, identifier):
        raise ClientError("invalidArguments", "person 需 18 位身份证号；organization_license 需 TS+7 位-4 位的许可证编号。")
    if args.kind == "person" and not is_id_number(identifier):
        # 从图片上照抄的号码最容易错一位：出生日期或校验位对不上就不去平台查。
        raise ClientError("idChecksumFailed", "身份证号的出生日期或校验位对不上，多半有一位读错了：放大原件（--clip、--dpi 400）重读再查。")
    return Api(args.base_url).call("POST", "/inspection-services/certificate-registry", timeout=120,
                                   body={"kind": args.kind, "identifier": identifier, "allowExternalQuery": True})


VALIDITY_FIELDS = ("certificates", "expectedHolder", "requiredScopes", "periodStart", "periodEnd", "referenceDate")
CERTIFICATE_FIELDS = ("certificateNo", "holder", "validFrom", "validUntil", "scopes")


def cmd_cert_validity(args: argparse.Namespace) -> Any:
    try:
        payload = json.loads(args.json)
    except ValueError as exc:
        raise ClientError("invalidArguments", f"--json 不是合法 JSON：{exc}") from None
    if not isinstance(payload, dict) or not payload.get("certificates"):
        raise ClientError("invalidArguments", "--json 须为含 certificates 的对象。")
    # 服务器只说“存在不支持的字段”，不说是哪个；在本地先点名。
    unknown = [k for k in payload if k not in VALIDITY_FIELDS]
    unknown += [f"certificates[].{k}" for c in payload["certificates"] if isinstance(c, dict) for k in c if k not in CERTIFICATE_FIELDS]
    if unknown:
        raise ClientError("invalidArguments", f"cert-validity 不接受这些字段：{'、'.join(dict.fromkeys(unknown))}。"
                                              f"顶层只收 {'、'.join(VALIDITY_FIELDS)}；certificates 里只收 {'、'.join(CERTIFICATE_FIELDS)}。")
    return Api(args.base_url).call("POST", "/inspection-services/certificate-validity", body=payload)


def cmd_cnse_org_search(args: argparse.Namespace) -> Any:
    return Api(args.base_url).call("POST", "/cnse/organizations/search", auth=True, body={"keyword": args.keyword}, timeout=120)


def trim_text(value: Any, limit: int = 300) -> Any:
    """检索命中里会夹整张表的 OCR 文字（实测一次 600 多 KB）：只留开头，原文用 standard-content 读。"""
    if isinstance(value, str) and len(value) > limit:
        return f"{value[:limit]}…（共 {len(value)} 字，原文用 standard-content 读）"
    if isinstance(value, list):
        return [trim_text(item, limit) for item in value]
    if isinstance(value, dict):
        return {key: trim_text(item, limit) for key, item in value.items()}
    return value


def cmd_standards(args: argparse.Namespace) -> Any:
    return trim_text(Api(args.base_url).call("GET", "/inspection-services/standards",
                                             query={"keyword": args.query, "page": args.page, "pageSize": args.page_size}))


def cmd_standard_content(args: argparse.Namespace) -> Any:
    return Api(args.base_url).call("GET", f"/inspection-services/standards/{parse.quote(args.file_id, safe='')}/canonical",
                                   query={"pageNo": args.page_no, "section": args.section})


def status_on_date(result: Any, day: str) -> dict[str, Any]:
    """服务器的 verdict 按今天算；给了 --date 就按实施日、废止日算出那一天的状态。"""
    result = result if isinstance(result, dict) else {}
    ref = next(iter(result.get("standardReferences") or []), {})
    detail = result.get("detail") or {}
    start = ref.get("effectiveFrom") or detail.get("effectiveDate")
    end = ref.get("withdrawnOn") or detail.get("withdrawnOn")
    out: dict[str, Any] = {"date": day, "effectiveFrom": start, "withdrawnOn": end}
    if not start:
        out.update(status="unknown", note="没有实施日期，判断不了那一天是否有效。")
    elif day < start:
        out.update(status="not_yet_effective", note=f"{day} 时还没实施（{start} 起实施）。")
    elif end and day >= end:
        out.update(status="withdrawn", note=f"{day} 时已废止（{end} 起）。")
    else:
        out.update(status="in_force", note=f"{day} 时有效（{start} 起实施" + (f"，{end} 废止）。" if end else "，未废止）。"))
    return out


def cmd_standard_status(args: argparse.Namespace) -> Any:
    if args.date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.date):
        raise ClientError("invalidArguments", "--date 写成 YYYY-MM-DD，如 2021-03-24。")
    body = {"standardRef": args.ref, **({"reviewDate": args.date} if args.date else {})}
    result = Api(args.base_url).call("POST", "/inspection-services/standard-status", body=body, timeout=120)
    if args.date and isinstance(result, dict) and result.get("status") == "COMPLETED":
        result["onDate"] = status_on_date(result, args.date)
    return result


def cmd_node_standards(args: argparse.Namespace) -> Any:
    return Api(args.base_url).call("GET", f"/projects/{parse.quote(args.project, safe='')}/inspection/nodes/{args.node}/standards", auth=True)


# ---------------------------------------------------------------- report

# 资料包里的派生文件不是出处：事实要指回原件或工具。
SOURCE_HINTS = (("text/", "转出的文字（含 OCR 文字）：file 写 files/ 下的原件，page 写页码，text/… 写进 locator"),
                ("ocr/", "OCR 存档：file 写 files/ 下的原件，page 写页码"),
                ("search/", "检索结果：file 写 tool:search，search/<时间>.json 和检索词写进 locator"),
                ("tool-results/", "工具结果：file 写 tool:<命令名>，存档路径写进 locator"),
                ("pages/", "页图：file 写 files/ 下的原件，page 写页码"))


def has_value(value: Any) -> bool:
    """Zero and False are facts, not missing values."""
    return value is not None and (bool(value.strip()) if isinstance(value, str)
                                  else bool(value) if isinstance(value, (list, dict)) else True)


def lexical_path(root: Path, relative: str) -> Path:
    """按字面路径（去掉 ..）判断在不在允许目录里，不跟符号链接：仓库里的 rules/、资料包里的原件都可能是链接。"""
    return Path(os.path.normpath(os.path.join(os.path.abspath(root), relative)))


def source_problem(bundle: Path, source: dict[str, Any], known_files: set[str], page_counts: dict[str, int]) -> str | None:
    """Check existing source fields and files, not whether the model read them correctly."""
    file, page, locator = source.get("file"), source.get("page"), str(source.get("locator") or "").strip()
    if not isinstance(file, str) or not file.strip() or (page is None and not locator):
        return "出处须有 file 及 page/locator"
    if page is not None and (type(page) is not int or page < 1):
        return "page 须为正整数物理页"
    base = bundle.resolve()
    if file.startswith("tool:"):
        command = file.removeprefix("tool:")
        matches = re.findall(r"(?<![\w./-])((?:tool-results|search)/[\w.-]+\.json)(?![\w./-])", locator)
        for relative in matches:
            archive = (base / relative).resolve()
            if not archive.is_relative_to(base) or not archive.is_file():
                continue
            try:
                record = json.loads(archive.read_text(encoding="utf-8"))
                if isinstance(record, dict) and (record.get("tool") == command or
                        (command == "search" and relative.startswith("search/") and "files" in record and "terms" in record)):
                    return None
            except (OSError, ValueError):
                pass
        return "工具出处的 locator 须指向本包内对应命令的实际 JSON 存档"
    if file.startswith("standard:"):
        base = Path(os.path.abspath(repo_root()))
        target = lexical_path(base, file.removeprefix("standard:"))
    elif file.startswith("server:"):
        target = lexical_path(base, file.removeprefix("server:"))
        if target.suffix != ".json":
            return "服务器出处须指向本包内已保存的 JSON"
    else:
        if file not in known_files:
            hint = next((h for prefix, h in SOURCE_HINTS if file.startswith(prefix)), "")
            return f"引用的 {file} 不在本资料包清单中" + (f"——{hint}" if hint else "")
        target = lexical_path(base, file)
    if not target.is_relative_to(base) or not target.is_file():
        return "引用来源不存在或越出允许目录"
    if target.suffix.lower() == ".pdf":
        if page is None:
            return "PDF 出处须写物理页 page"
        key = str(target)
        if key not in page_counts:
            try:
                with quiet_fitz().open(target) as document:
                    page_counts[key] = document.page_count
            except Exception:  # noqa: BLE001 -- 原件损坏或没装 PyMuPDF：数不了页，check_report 统一给警告
                page_counts[key] = 0
        if page_counts[key] and page > page_counts[key]:
            return "引用页超过原件页数"
    elif target.suffix.lower() in IMAGE_SUFFIXES and page not in (None, 1):
        return "单页图片的物理页只能为 1"
    return None


def check_report(bundle: Path) -> tuple[dict[str, Any], dict[str, Any], list[str], list[str]]:
    manifest = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))
    report_path = bundle / "audit.json"
    if not report_path.exists():
        raise ClientError("reportMissing", f"{report_path} 不存在：先按 references/report-format.md 写 audit.json。")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    errors_, warnings = [], []
    if report.get("schemaVersion") != REPORT_SCHEMA:
        errors_.append(f"schemaVersion 应为 {REPORT_SCHEMA}")
    expected = list(manifest.get("atomicChecks") or [])
    seen: dict[str, int] = {}
    known_files = {f["path"] for f in manifest.get("files") or []}
    outcomes = manifest.get("serverOutcomes") or {}
    page_counts: dict[str, int] = {}
    for check in report.get("checks") or []:
        cid = check.get("atomicCheckId")
        seen[cid] = seen.get(cid, 0) + 1
        verdict = check.get("verdict")
        if verdict not in VERDICTS:
            errors_.append(f"{cid}: 还没下结论" if not verdict else f"{cid}: verdict 必须是 {sorted(VERDICTS)} 之一")
            continue
        sourced = []
        for fact in check.get("facts") or []:
            if not isinstance(fact, dict) or not str(fact.get("name") or "").strip() or not has_value(fact.get("value")):
                errors_.append(f"{cid}: 每条已列事实须有非空 name 和 value；未知事实写入 reason/limitations")
                continue
            source = fact.get("source")
            problem = source_problem(bundle, source, known_files, page_counts) if isinstance(source, dict) else "事实缺 source"
            if problem:
                errors_.append(f"{cid}: {problem}")
            else:
                sourced.append(fact)
        if verdict in NEEDS_SOURCE and not sourced:
            errors_.append(f"{cid}: {VERDICTS[verdict]} 至少要一条带 file+page/locator 的事实")
        if verdict in NEEDS_SOURCE and not str(check.get("reasoning") or check.get("reason") or "").strip():
            errors_.append(f"{cid}: {VERDICTS[verdict]} 必须写 reasoning 或 reason 说明比较与判断")
        if verdict not in NEEDS_SOURCE and not str(check.get("reason") or "").strip():
            errors_.append(f"{cid}: {VERDICTS[verdict]} 必须写 reason")
        if verdict == "passed" and any(str(step).strip() for step in check.get("nextSteps") or []):
            warnings.append(f"{cid}: 符合项带着 nextSteps。这些若是本项结论依赖的待补材料或待人工核对的事项，改判证据不足或需人工确认"
                            "（audit-method「判符合前自检」）；与结论无关的跟进事项可保留，并在 reasoning 说明为什么不影响结论")
        for fact in check.get("facts") or []:
            if not isinstance(fact, dict):
                continue
            file = (fact.get("source") if isinstance(fact.get("source"), dict) else {}).get("file")
            if file and file not in known_files and not str(file).startswith(("server:", "tool:", "standard:")):
                hint = next((h for prefix, h in SOURCE_HINTS if str(file).startswith(prefix)), "")
                warnings.append(f"{cid}: 引用的 {file} 不在 bundle files 里" + (f"——{hint}" if hint else ""))
        if not outcomes:
            continue  # 本地资料没有服务器结论，不往 audit.json 里加空的对照字段
        server = (outcomes.get(cid) or {}).get("result")
        check["serverResult"] = server
        check["agreesWithServer"] = None if not server else server == verdict
        if server and server != verdict and not str(check.get("differenceNote") or "").strip():
            warnings.append(f"{cid}: 与服务器结论（{server}）不同，补 differenceNote 说明原因")
    missing = [cid for cid in expected if cid not in seen]
    extra = [cid for cid in seen if cid not in expected]
    dupes = [cid for cid, count in seen.items() if count > 1]
    if missing:
        errors_.append("缺少原子检查：" + "、".join(missing))
    if extra:
        errors_.append("不属于本节点的检查：" + "、".join(map(str, extra)))
    if dupes:
        errors_.append("重复的检查：" + "、".join(dupes))
    unreadable = sorted(Path(key).name for key, count in page_counts.items() if not count)
    if unreadable:
        warnings.append("这些 PDF 打不开（原件损坏，或没用装了 PyMuPDF 的 backend/.venv/bin/python 跑），没核对引用页是否超出页数："
                        + "、".join(unreadable))
    if contains_id_number(report_path.read_text(encoding="utf-8")):
        errors_.append("audit.json 里有完整的 18 位身份证号：一律写成前 4 位 + **** + 后 4 位")
    for flag in report.get("riskFlags") or []:
        if not isinstance(flag, dict) or flag.get("level") not in RISK_LEVELS or not str(flag.get("flag") or "").strip():
            errors_.append(f"riskFlags 每条须有 level（{'/'.join(RISK_LEVELS)}）和 flag：{flag}")
    rules = json.loads((bundle / "rules.json").read_text(encoding="utf-8"))
    roles = {c["id"]: c for c in rules["atomicChecks"]}
    check_strict_rules(report.get("checks") or [], roles, errors_)
    check_reading_coverage(bundle, manifest, report, errors_, warnings)
    check_primary_clauses(rules, report, warnings)
    return manifest, report, errors_, warnings


def clause_text(value: Any) -> str:
    """条款号比对用：全角括号变半角、去空白，D2.4.1（5）和 D2.4.1 (5) 都算 D2.4.1(5)。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)))


def check_primary_clauses(rules: dict[str, Any], report: dict[str, Any], warnings: list[str]) -> None:
    """总适用的固定主条款要么在某条事实里引用（excerpt 或 locator 写出条款号），要么在 limitations 里写明没取到。"""
    cited = clause_text([f.get("source") for c in report.get("checks") or [] for f in c.get("facts") or [] if isinstance(f, dict)])
    noted = clause_text(report.get("limitations") or [])
    for clause in rules.get("standardClauses") or []:
        number = clause_text(str(clause.get("clauseNo") or ""))
        if clause.get("bindingRole") != "primary" or clause.get("applicability") != "always" or not number:
            continue
        if number not in cited and number not in noted:
            ref = str(clause.get("standardRef") or "").removeprefix("STD-")
            warnings.append(f"固定主条款 {ref} {clause.get('clauseNo')}（物理页 {clause.get('sourcePage')}）没有在任何检查的 facts 里引用"
                            "（source 的 excerpt 或 locator 要写出条款号），也没有在 limitations 里写明没取到")


def check_strict_rules(checks: list[dict[str, Any]], roles: dict[str, dict[str, Any]], errors_: list[str]) -> None:
    valid = [c for c in checks if c.get("verdict") in VERDICTS]
    conflicted = [c["atomicCheckId"] for c in valid if c.get("conflicts")]
    for check in valid:
        cid, verdict = check["atomicCheckId"], check["verdict"]
        role = roles.get(cid) or {}
        if check.get("conflicts") and verdict == "passed":
            errors_.append(f"{cid}: 列了 conflicts 就不能判符合")
        if role.get("perItem") and verdict == "passed":
            coverage = check.get("coverage") or {}
            items, done = coverage.get("items"), coverage.get("checked")
            if not (isinstance(items, int) and items > 0 and done == items and str(coverage.get("source") or "").strip()):
                errors_.append(f"{cid}: 规则要求{role['perItem']}核对，判符合须给 coverage{{items, checked, source}} 且 checked = items；"
                               "没有逐件记录就判证据不足")
        if role.get("role") == "traceability" and verdict == "passed":
            short = [c["atomicCheckId"] for c in valid if c is not check and c["verdict"] in {"evidence_insufficient", "not_executed"}]
            if short or conflicted:
                expected = "需人工确认" if conflicted else "证据不足"
                errors_.append(f"{cid}: 证据追溯项不得判符合——"
                               + "；".join(x for x in (f"证据缺失：{'、'.join(short)}" if short else "",
                                                     f"存在冲突：{'、'.join(conflicted)}" if conflicted else "") if x)
                               + f"。应判{expected}")


# ocr：读了服务器 OCR 的文字。read/pages/thumbs 是助手自己看图的旧写法，仍收，
# 但扫描页上的确定结论只认 OCR 文字（见 check_reading_coverage）。
REVIEW_METHODS = {"ocr", "read", "pages", "thumbs", "search", "text", "textutil", "skipped"}
ID_CANDIDATE = re.compile(r"(?<![0-9A-Za-z])(\d{17}[\dXx])(?![0-9A-Za-z])")
ID_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)


def is_id_number(value: str) -> bool:
    """居民身份证号：出生日期合法且校验位正确（GB 11643）。全数字的统一社会信用代码过不了这两关。"""
    try:
        born = datetime.strptime(value[6:14], "%Y%m%d")
    except ValueError:
        return False
    if not 1900 <= born.year <= 2099:
        return False
    return value[17].upper() == "10X98765432"[sum(int(d) * w for d, w in zip(value[:17], ID_WEIGHTS)) % 11]


def contains_id_number(text: str) -> bool:
    return any(is_id_number(match.group(1)) for match in ID_CANDIDATE.finditer(text))


def mask_ids(text: str) -> str:
    """命令输出、检索结果、转出的文字、工具存档里的身份证号一律写成前 4 位 + ********** + 后 4 位。"""
    return ID_CANDIDATE.sub(lambda m: f"{m.group(1)[:4]}**********{m.group(1)[-4:]}" if is_id_number(m.group(1)) else m.group(0), text)


def mask_value(value: Any) -> Any:
    """递归遮蔽字符串值。必须在转 JSON 之前做：JSON 里换行写成 \\n，后面紧跟的号码前一个字符是字母 n，在转义后的文本上扫会漏掉。"""
    if isinstance(value, str):
        return mask_ids(value)
    if isinstance(value, dict):
        return {mask_value(k): mask_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [mask_value(v) for v in value]
    return value


def dump_masked(value: Any) -> str:
    return dump(mask_value(value))


MASKED_ID = re.compile(r"\d{4}\*{4,}\d{3}[\dX]")


def resolve_masked_id(masked: str, bundle_arg: str | None) -> str:
    """模型手里只有脱敏号：回资料包原件的文字层、OCR 原文（和服务器抽取字段）里找前后 4 位都对上的那一个完整号码。"""
    if not bundle_arg:
        raise ClientError("invalidArguments", "脱敏号码要配 --bundle <资料包>，从包里原件找回完整号码再查。")
    bundle = Path(bundle_arg).expanduser().resolve()
    manifest = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))
    texts = [text for item in manifest.get("files") or [] for text in page_texts(bundle, item["path"], bundle / item["path"])[2]]
    if (bundle / "workspace.json").exists():
        texts.append((bundle / "workspace.json").read_text(encoding="utf-8"))
    head, tail = masked[:4], masked[-4:]
    found = {m.group(1).upper() for text in texts for m in ID_CANDIDATE.finditer(text)
             if is_id_number(m.group(1)) and m.group(1).startswith(head) and m.group(1).upper().endswith(tail)}
    if len(found) == 1:
        return found.pop()
    if not found:
        raise ClientError("identifierNotFound", f"资料包的文字层和 OCR 文字里都没有与 {masked} 前后 4 位都对上的身份证号；"
                                                 "还没跑 ocr 就先跑；OCR 也没读出时，这张证的登记查询交人工，写进 limitations。")
    raise ClientError("identifierAmbiguous", f"资料包里有 {len(found)} 个身份证号与 {masked} 前后 4 位相同，分不出是哪个；这张证的登记查询交人工，写进 limitations。")


RISK_LEVELS = ("high", "medium")


def latest_search(bundle: Path) -> dict[str, Any] | None:
    runs = sorted((bundle / "search").glob("*.json")) if (bundle / "search").is_dir() else []
    return json.loads(runs[-1].read_text(encoding="utf-8")) if runs else None


def check_reading_coverage(bundle: Path, manifest: dict[str, Any], report: dict[str, Any],
                           errors_: list[str], warnings: list[str]) -> None:
    known = [f["path"] for f in manifest.get("files") or []]
    listed: dict[str, dict[str, Any]] = {}
    for entry in report.get("reviewedFiles") or []:
        path = entry.get("file") if isinstance(entry, dict) else None
        if path not in known:
            warnings.append(f"reviewedFiles 里的 {path} 不在资料包里")
            continue
        listed[path] = entry
        if entry.get("method") not in REVIEW_METHODS:
            errors_.append(f"reviewedFiles {path}: " + ("还没写怎么看的（method）" if not entry.get("method") else f"method 须为 {sorted(REVIEW_METHODS)} 之一"))
        elif entry["method"] == "skipped" and not str(entry.get("note") or "").strip():
            errors_.append(f"reviewedFiles {path}: skipped 要写 note 说明为什么不看")
    unlisted = [p for p in known if p not in listed]
    if unlisted:
        errors_.append(f"reviewedFiles 缺 {len(unlisted)} 份文件（每份都要写明怎么看的或为什么跳过）：" + "、".join(unlisted))
    search = latest_search(bundle)
    if not search:
        warnings.append("没有跑过 search：全包检索能找出没想到的文件里的工期、材质、人员等事实")
        search = {}
    unread = set(search.get("needsOcr", search.get("needsVisualReview")) or [])
    unread_pages = search.get("needsOcrPages", search.get("needsVisualPages")) or {}
    # 扫描件与扫描页按原件文字层算（旧存档没有 scannedFiles，退回“当时还缺字”的清单）。
    visual = set(search.get("scannedFiles") or []) | unread
    partial = {**unread_pages, **(search.get("scannedPages") or {})}
    ocr_pages = ocr_coverage(bundle, known)
    image_only: dict[tuple[str, int], bool] = {}
    for path, entry in listed.items():
        if path in unread and entry.get("method") == "search" and not ocr_pages.get(path):
            errors_.append(f"reviewedFiles {path}: 没有文字层也没 OCR，只检索等于没看——先跑 ocr 再读 OCR 文字（method 写 ocr），或标 skipped 写原因")
        elif path in unread_pages and entry.get("method") == "search" and not str(entry.get("note") or "").strip() \
                and not ocr_pages.get(path):
            errors_.append(f"reviewedFiles {path}: 第 {unread_pages[path]} 页没有文字层，检索看不到——跑 ocr 后在 pages 写明，或在 note 说明为何不看")
    for check in report.get("checks") or []:
        if check.get("verdict") not in NEEDS_SOURCE:
            continue
        for fact in check.get("facts") or []:
            if not isinstance(fact, dict):
                continue
            source = fact.get("source") if isinstance(fact.get("source"), dict) else {}
            path, page = source.get("file"), source.get("page")
            scanned = (path in visual or Path(str(path)).suffix.lower() in IMAGE_SUFFIXES
                       or (isinstance(partial.get(path), list) and page in partial[path]))
            # A missing/stale search archive must not exempt a cited image-only PDF page.
            target = (bundle / str(path)).resolve()
            if (not scanned and path in known and target.is_relative_to(bundle.resolve())
                    and target.suffix.lower() == ".pdf" and type(page) is int and page > 0):
                key = (path, page)
                if key not in image_only:
                    try:
                        with quiet_fitz().open(target) as document:
                            image_only[key] = not bool(document[page - 1].get_text().strip())
                    except Exception:  # noqa: BLE001 -- 打不开就核不了文字层：只警告，不让整份报告交不出去
                        image_only[key] = False
                        warnings.append(f"{check['atomicCheckId']}: {path} 第 {page} 页打不开，没核对它是不是扫描页、阅读记录够不够")
                scanned = image_only[key]
            number = page if type(page) is int and page > 0 else 1
            if scanned and path in known and number not in ocr_pages.get(path, set()):
                errors_.append(f"{check['atomicCheckId']}: 确定结论引用的扫描页 {path} 第 {number} 页没有 OCR 文字"
                               "——先跑 ocr；OCR 里仍没有这一处，本项判证据不足或需人工确认")


OUTCOME_LABELS = {"passed": "通过", "failed": "不通过", "pending": "暂不能判定通过"}


def node_outcome(checks: list[dict[str, Any]]) -> dict[str, Any]:
    """The node as a whole, from its atomic checks: any failed -> failed; everything passed (or not applicable) -> passed;
    otherwise pending, because something is still missing or needs a person, which is not the same as failing."""
    counts: dict[str, int] = {}
    for check in checks:
        counts[check["verdict"]] = counts.get(check["verdict"], 0) + 1
    if counts.get("failed"):
        key = "failed"
    elif counts and set(counts) <= {"passed", "not_applicable"} and counts.get("passed"):
        key = "passed"
    else:
        key = "pending"
    parts = "、".join(f"{VERDICTS[v]} {counts[v]}" for v in VERDICTS if counts.get(v))
    explain = {
        "failed": f"有 {counts.get('failed', 0)} 项不符合要求，需要整改。",
        "passed": "全部检查项都有原件证据支持，满足要求。",
        "pending": "没有发现明确不符合，但还有检查项缺证据或需要人工确认，补齐或确认后才能判通过。",
    }[key]
    return {"outcome": key, "label": OUTCOME_LABELS[key], "explain": explain, "counts": counts, "summary": f"{len(checks)} 项检查：{parts}。"}


TOOL_LABELS = {"cert-registry": "公示平台登记查询", "cert-validity": "有效期核验", "search": "全包检索",
               "standard-content": "标准原文", "standard-status": "标准有效性查询", "cnse-org-search": "公示平台单位查询"}


def short_file(path: Any) -> str:
    """How a source reads to a person: the original file's name, a standard's name, or what a tool did."""
    text = str(path or "")
    if text.startswith("tool:"):
        return TOOL_LABELS.get(text[5:], text[5:])
    if text.startswith("standard:"):
        return "标准 " + re.sub(r"\.pdf$", "", Path(text[9:]).name)
    return re.sub(r"^files/\d+-", "", text)


def fact_place(fact: dict[str, Any]) -> str:
    src = fact.get("source") or {}
    where = short_file(src.get("file"))
    if src.get("page"):
        where += f" 第{src['page']}页"
    elif src.get("locator") and not str(src.get("file") or "").startswith("tool:"):
        where += f"（{src['locator']}）"
    return where.strip()


VERDICT_MARK = {"passed": "✅", "failed": "❌", "evidence_insufficient": "❓", "human_review_required": "👤",
                "not_applicable": "➖", "not_executed": "⏸"}


def clip_text(text: str, limit: int) -> str:
    """Cut at the last clause break before the limit, so a table cell never ends in half a word."""
    if len(text) <= limit:
        return text
    head = text[: limit - 1]
    cut = max(head.rfind(mark) for mark in "，；、,;")
    return (head[:cut] if cut >= limit // 2 else head) + "…"


def first_sentence(text: Any, limit: int = 110) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    cut = re.split(r"(?<=[。！？])", text, maxsplit=1)[0] if text else ""  # 只在句号处断：分号前常是半句
    return clip_text(cut, limit)


def leading_sentences(text: Any, limit: int = 220) -> str:
    """The first sentences that fit in `limit` characters (always at least the first one, clipped if it is long)."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    sentences = [s for s in re.split(r"(?<=[。！？])", text) if s]
    out = ""
    for sentence in sentences:
        if out and len(out) + len(sentence) > limit:
            break
        out += sentence
    return clip_text(out, limit)


def short_time(value: Any) -> str:
    """2026-10-26T18:40:00-07:00 -> 2026-10-26 18:40 (no seconds, no offset: a person reads the date and the hour)."""
    match = re.match(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})", str(value or ""))
    return f"{match.group(1)} {match.group(2)}" if match else str(value or "—")


def check_title(check: dict[str, Any]) -> str:
    """Rule names prefix every check name (“规则名·检查名”); a person only needs the check part."""
    name = str(check.get("name") or "")
    return f"{check['atomicCheckId']} {name.split('·', 1)[-1]}".strip()


def check_reason(check: dict[str, Any]) -> str:
    if check["verdict"] in NEEDS_SOURCE:
        return first_sentence(check.get("reasoning") or check.get("reason"))
    return first_sentence(check.get("reason") or check.get("reasoning"))


def check_evidence(check: dict[str, Any], limit: int = 2) -> str:
    """Where the evidence is, grouped by file: `焊工证.pdf 第1、5页；施工方案.pdf 第3页 等 9 处`. Originals before standards and tools."""
    groups: dict[str, list[str]] = {}
    total = 0
    rank = lambda fact: (str((fact.get("source") or {}).get("file") or "").startswith(("tool:", "standard:", "server:")),)
    for fact in sorted(check.get("facts") or [], key=rank):
        src = fact.get("source") or {}
        name = short_file(src.get("file"))
        if not name:
            continue
        if src.get("page"):
            mark = str(src["page"])
        elif src.get("locator") and not str(src.get("file") or "").startswith("tool:"):
            mark = f"（{src['locator']}）"
        else:
            mark = ""
        pages = groups.setdefault(name, [])
        if mark not in pages:
            pages.append(mark)
            total += 1
    def label(name: str, marks: list[str]) -> str:
        numbers = sorted((m for m in marks if m.isdigit()), key=int)
        others = [m for m in marks if m and not m.isdigit()]
        parts = ([f"第{'、'.join(numbers)}页"] if numbers else []) + others
        return f"{name} {''.join(parts)}".strip()
    shown = "；".join(label(name, marks) for name, marks in list(groups.items())[:limit])
    return shown + (f" 等 {total} 处" if len(groups) > limit else "")


def priority_steps(checks: list[dict[str, Any]], cap: int = 6) -> tuple[list[str], int]:
    """The few things a person should do first: fix what failed, supply what is missing, then confirm what a person must decide.
    Inside each group the checks take turns (every check's first step before any check's second), so one check with many steps
    cannot fill the list. Steps that only point at another check (“补齐 AC-… 所列缺口”) go last."""
    seen, steps, pointers = set(), [], []
    for verdicts in (("failed",), ("evidence_insufficient", "not_executed"), ("human_review_required",)):
        queues = []
        for check in checks:
            if check["verdict"] in verdicts:
                queues.append([(check["atomicCheckId"], str(step).strip()) for step in check.get("nextSteps") or [] if str(step).strip()])
        for turn in range(max((len(q) for q in queues), default=0)):
            for queue in queues:
                if turn >= len(queue):
                    continue
                cid, step = queue[turn]
                key = re.sub(r"\s+", "", step)
                if key in seen:
                    continue
                seen.add(key)
                line = f"**{cid}**：{step}"
                (pointers if re.search(r"AC-[A-Z0-9]+-\d+", step) and len(step) < 60 else steps).append(line)
    steps += pointers
    return steps[:cap], max(len(steps) - cap, 0)


def render_markdown(manifest: dict[str, Any], report: dict[str, Any], warnings: list[str], rule_name: str = "") -> str:
    """User-facing first: the node's result, then why (per check, with where the evidence is), then the details."""
    checks = report.get("checks") or []
    outcome = node_outcome(checks)
    title = f"# 节点审计结果 · {manifest.get('projectId')} · 节点 {manifest['nodeId']:02d} {manifest['ruleId']}" + (f" {rule_name}" if rule_name else "")
    marks = "　".join(f"{VERDICT_MARK[v]} {VERDICTS[v]} {outcome['counts'][v]}" for v in VERDICTS if outcome["counts"].get(v))
    lines = [title, "",
             "> 本报告是 AI 助手的辅助审计意见，不代替监检人员的正式结论。是否同步到服务器由用户决定；同步后在服务器上是待人工复核的 AI 审查发现。", "",
             f"## 结论：{outcome['label']}", "", outcome["explain"], "", f"共 {len(checks)} 项检查：{marks}", "",
             f"- 资料来源：{manifest['source']}（{manifest.get('baseUrl') or '本地'}），取数 {short_time(manifest['fetchedAt'])}",
             f"- 审计时间：{short_time(report.get('auditedAt'))}；审计者：{report.get('auditor') or '—'}", "",
             "| 检查 | 结论 | 理由 | 主要依据 |", "|---|---|---|---|"]
    for check in checks:
        lines.append(f"| {cell(check_title(check))} | {VERDICT_MARK[check['verdict']]} {VERDICTS[check['verdict']]} | "
                     f"{cell(check_reason(check))} | {cell(check_evidence(check) or '—')} |")
    steps, more = priority_steps(checks)
    if steps:
        lines += ["", "## 最需要先做的事", ""] + [f"{n}. {step}" for n, step in enumerate(steps, 1)]
        if more:
            lines.append(f"\n另有 {more} 条建议，见下面各项的“建议”。")
    agree = [c for c in checks if c.get("agreesWithServer") is True]
    differ = [c for c in checks if c.get("agreesWithServer") is False]
    if agree or differ:
        lines += ["", f"与服务器结论一致 {len(agree)} 项，不一致 {len(differ)} 项。"]

    def section(heading: str, verdicts: set[str], lead: str) -> None:
        picked = [c for c in checks if c["verdict"] in verdicts]
        if not picked:
            return
        lines.extend(["", f"## {heading}", "", lead, ""])
        for check in picked:
            text = (check.get("reasoning") or check.get("reason")) if check["verdict"] in NEEDS_SOURCE else (check.get("reason") or check.get("reasoning"))
            text = str(text or "").strip()
            if check["verdict"] != "failed":  # 不符合的原因写全；其余只放开头，完整说明在逐项明细
                brief = leading_sentences(text)
                text = brief + f"（完整说明见下面“逐项明细”{check['atomicCheckId']}）" if brief != text else text
            lines.append(f"- **{check_title(check)}**：{text}")
            evidence = check_evidence(check, limit=4)
            if evidence:
                lines.append(f"  - 依据：{evidence}")
            for conflict in check.get("conflicts") or []:
                lines.append(f"  - 资料矛盾：{conflict}")
            for step in check.get("nextSteps") or []:
                lines.append(f"  - 建议：{step}")

    section("不通过的原因", {"failed"}, "原件明确显示不满足要求的项，需要受检单位整改：")
    section("需要人工确认", {"human_review_required"}, "要由人现场、对原件，或在互相矛盾的资料中确认的项（这些项本身的资料齐了，缺的资料见“证据不足”）：")
    section("证据不足", {"evidence_insufficient", "not_executed"}, "缺资料、读不清或没能核验，补齐后才能下结论的项：")
    if report.get("missingMaterials"):
        lines += ["", "## 需要补充的资料", ""] + [f"- {item}" for item in report["missingMaterials"]]
    section("通过项及证据", {"passed"}, "已有原件证据支持、满足要求的项：")
    if report.get("riskFlags"):
        lines += ["", "## 高风险提示", ""]
        for flag in report["riskFlags"]:
            label = "高" if flag.get("level") == "high" else "中"
            lines.append(f"- 【{label}】{flag.get('check') or ''} {flag.get('flag')}" + (f"（{flag['basis']}）" if flag.get("basis") else ""))
    if report.get("summary"):
        lines += ["", "## 总体意见", "", str(report["summary"])]
    lines += ["", "## 逐项明细"]
    for check in checks:
        lines += ["", f"### {check['atomicCheckId']} · {check.get('name') or ''}", "",
                  f"**结论：{VERDICTS[check['verdict']]}**" + (f"（服务器：{check['serverResult']}）" if check.get("serverResult") else "")]
        if check.get("requirement"):
            lines += ["", f"要求：{check['requirement']}"]
        if check.get("facts"):
            lines += ["", "| 事实 | 值 | 出处 |", "|---|---|---|"]
            for fact in check["facts"]:
                src = fact.get("source") or {}
                where = " ".join(str(x) for x in (src.get("file"), f"第{src['page']}页" if src.get("page") else "", src.get("locator")) if x)
                excerpt = f"「{src['excerpt']}」" if src.get("excerpt") else ""
                lines.append(f"| {cell(fact.get('name'))} | {cell(fact.get('value'))} | {cell(f'{where} {excerpt}')} |")
        cov = check.get("coverage") or {}
        if cov.get("items") is not None or cov.get("checked") is not None:  # 骨架里的 null 不是统计结果，不打印
            def count(value: Any) -> str:
                return "未知" if value is None else str(value)
            origin = f"（{cov['source']}）" if cov.get("source") else ""
            lines += ["", f"逐件覆盖：{count(cov.get('checked'))}/{count(cov.get('items'))}{origin}"]
        for label, key in (("判断", "reasoning"), ("原因", "reason"), ("与服务器差异", "differenceNote")):
            if check.get(key):
                lines += ["", f"{label}：{check[key]}"]
        for conflict in check.get("conflicts") or []:
            lines.append(f"- 冲突：{conflict}")
        for call in check.get("toolCalls") or []:
            if isinstance(call, dict):
                lines.append(f"- 工具 `{call.get('tool')}`（{call.get('at') or ''}）：{call.get('summary')}")
            else:
                lines.append(f"- 工具：{call}")
        for step in check.get("nextSteps") or []:
            lines.append(f"- 下一步：{step}")
    for heading, key in (("关联节点复核建议", "relatedNodeSuggestions"), ("局限与未覆盖", "limitations")):
        if report.get(key):
            lines += ["", f"## {heading}", ""] + [f"- {item}" for item in report[key]]
    if report.get("reviewedFiles"):
        method_label = {"read": "读原件", "pages": "看页图", "thumbs": "缩略图过目", "search": "文字层检索", "text": "转文字", "textutil": "转文字", "skipped": "未看"}
        lines += ["", "## 已阅读文件", "", "| 文件 | 方式 | 页 | 说明 |", "|---|---|---|---|"]
        for entry in report["reviewedFiles"]:
            lines.append(f"| {cell(entry.get('file'))} | {method_label.get(entry.get('method'), cell(entry.get('method')))} | "
                         f"{cell(entry.get('pages') or '—')} | {cell(entry.get('note') or '')} |")
    if manifest.get("warnings") or warnings:
        lines += ["", "## 取数与校验提示", ""] + [f"- {w}" for w in (manifest.get("warnings") or []) + warnings]
    return mask_value("\n".join(lines) + "\n")


def cmd_skeleton(args: argparse.Namespace) -> Any:
    """audit.json 骨架：每个原子检查、每份文件各占一格，只需填空；漏检查、漏文件、字段名写错的机会都没了。"""
    bundle = Path(args.bundle).expanduser().resolve()
    manifest = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))
    rules = json.loads((bundle / "rules.json").read_text(encoding="utf-8"))
    target = bundle / "audit.json"
    if target.exists() and not args.force:
        raise ClientError("reportExists", f"{target} 已存在；确认要重来再加 --force。")
    checks = []
    for check in rules["atomicChecks"]:
        item: dict[str, Any] = {"atomicCheckId": check["id"], "name": check.get("name"), "instruction": check.get("instruction"),
                                "verdict": "", "requirement": "", "facts": [], "reasoning": "", "reason": "",
                                "conflicts": [], "toolCalls": [], "nextSteps": []}
        if check.get("perItem"):
            item["coverage"] = {"items": None, "checked": None, "source": ""}
        checks.append(item)
    report = {"schemaVersion": REPORT_SCHEMA, "projectId": manifest.get("projectId"), "nodeId": manifest.get("nodeId"),
              "ruleId": manifest.get("ruleId"), "auditedAt": "", "auditor": "", "summary": "", "checks": checks,
              "riskFlags": [], "missingMaterials": [], "relatedNodeSuggestions": [], "limitations": [],
              "reviewedFiles": [{"file": f["path"], "method": "", "pages": "", "note": ""} for f in manifest.get("files") or []]}
    write_private(target, dump(report))
    return {"skeleton": str(target), "checks": len(checks), "files": len(report["reviewedFiles"]),
            "next": "逐项填 verdict/facts/reasoning 或 reason，逐份填 reviewedFiles 的 method；填完跑 report"}


def cmd_report(args: argparse.Namespace) -> Any:
    bundle = Path(args.bundle).expanduser().resolve()
    before = json.loads((bundle / "audit.json").read_text(encoding="utf-8")) if (bundle / "audit.json").exists() else None
    manifest, report, errors_, warnings = check_report(bundle)
    if errors_:
        raise ClientError("reportInvalid", "audit.json 未通过校验，修正后重跑 report。", errors=errors_, warnings=warnings)
    updated = report != before  # 只有补了服务器结论才改写 audit.json，免得之后编辑它时文件已变
    if updated:
        write_private(bundle / "audit.json", dump(report))
    rule = (json.loads((bundle / "rules.json").read_text(encoding="utf-8")).get("rule") or {}) if (bundle / "rules.json").exists() else {}
    full_report = render_markdown(manifest, report, warnings, rule.get("name") or "")
    write_private(bundle / "audit.md", full_report)
    outcome = node_outcome(report["checks"])
    counts = {VERDICTS[v]: n for v, n in outcome["counts"].items()}
    # fullReport 和 audit.md 一字不差：完整结果随输出给出，回复用户不必再去读文件。
    return {"markdown": str(bundle / "audit.md"), "outcome": outcome["label"], "outcomeExplain": outcome["explain"],
            "counts": counts, "warnings": warnings, "auditJsonUpdated": updated,
            "syncAvailable": manifest.get("source") == "server", "fullReport": full_report,
            "next": ("把 fullReport 里的完整逐项结果贴给用户（SKILL.md 第 10 步）；用户看过后运行 sync --bundle 预览，"
                     "用户确认该次内容后加 --confirm --preview-hash <摘要>"
                     if manifest.get("source") == "server" else
                     "把 fullReport 里的完整逐项结果贴给用户（SKILL.md 第 10 步）；本地资料包没有对应的服务器节点，不能同步")}


# ---------------------------------------------------------------- result image (rendered by the server)

IMAGE_PATH = "/inspection-services/audit-result-image"


def audit_image_body(manifest: dict[str, Any], report: dict[str, Any], rule_name: str = "") -> dict[str, Any]:
    """发给服务器画图的摘要：和 audit.md 同一套结论、理由、依据，只要摘要，不带全文。证号再脱敏一遍。"""
    checks = report["checks"]
    outcome = node_outcome(checks)
    steps, _ = priority_steps(checks, cap=6)
    flags = [{"level": f.get("level"), "flag": f.get("flag") or "", "basis": f.get("basis") or ""}
             for f in report.get("riskFlags") or [] if isinstance(f, dict) and f.get("flag")]
    body = {
        "nodeId": manifest["nodeId"], "nodeName": rule_name, "ruleId": manifest.get("ruleId") or "",
        "projectLabel": str(manifest.get("projectId") or ""), "outcome": outcome["outcome"], "outcomeExplain": outcome["explain"],
        "auditedAt": short_time(report.get("auditedAt")) if report.get("auditedAt") else "", "auditor": str(report.get("auditor") or ""),
        "source": "服务器资料包" if manifest.get("source") == "server" else "本地资料包",
        "checks": [{"atomicCheckId": c["atomicCheckId"], "title": str(c.get("name") or "").split("·", 1)[-1],
                    "verdict": c["verdict"], "reason": check_reason(c), "evidence": check_evidence(c, limit=3),
                    "differsFromServer": (not c["agreesWithServer"]) if isinstance(c.get("agreesWithServer"), bool) else None}
                   for c in checks],
        "nextSteps": [re.sub(r"\*\*(.+?)\*\*", r"\1", step) for step in steps],
        "missingMaterials": [str(m) for m in report.get("missingMaterials") or []][:10],
        "riskFlags": flags[:8], "summary": clip_text(str(report.get("summary") or ""), 600),
    }
    return json.loads(dump_masked(body))


def decode_image_pages(data: Any) -> list[bytes]:
    """服务器一次回所有页：{pages: [{pageNo, imageBase64}]}。每页必须是合法 base64 的 PNG，页数和大小有上限。"""
    pages = data.get("pages") if isinstance(data, dict) else None
    if not isinstance(pages, list) or not 1 <= len(pages) <= MAX_IMAGE_PAGES:
        raise ClientError("badResponse", "服务器返回的图片页数不对。", path=IMAGE_PATH)
    decoded = []
    for page in pages:
        try:
            raw = base64.b64decode(page["imageBase64"], validate=True)
        except (KeyError, TypeError, ValueError):
            raise ClientError("badResponse", "服务器返回的图片不是合法的 base64。", path=IMAGE_PATH) from None
        if not raw.startswith(b"\x89PNG") or len(raw) > MAX_IMAGE_BYTES:
            raise ClientError("badResponse", "服务器返回的不是 PNG，或单页超过 8MB。", path=IMAGE_PATH)
        decoded.append(raw)
    return decoded


def image_targets(base: Path, count: int) -> list[Path]:
    """一页就是 base 本身；多页在文件名后加页码：audit.png → audit-1.png、audit-2.png…"""
    if count == 1:
        return [base]
    return [base.with_name(f"{base.stem}-{number}{base.suffix}") for number in range(1, count + 1)]


def cmd_render(args: argparse.Namespace) -> Any:
    """把审计结果的摘要发给服务器，由它用 HTML 模板渲染成白底的图（内容多就分页），存进资料包。"""
    bundle = Path(args.bundle).expanduser().resolve()
    manifest, report, errors_, warnings = check_report(bundle)
    if errors_:
        raise ClientError("reportInvalid", "audit.json 未通过校验：先修正并跑 report，再生成结果图。", errors=errors_, warnings=warnings)
    api = Api(args.base_url)
    if not api.token:
        raise ClientError("loginRequired", "结果图由服务器渲染，要监检账号令牌：请用户在自己的终端执行 login。")
    rule = (json.loads((bundle / "rules.json").read_text(encoding="utf-8")).get("rule") or {}) if (bundle / "rules.json").exists() else {}
    try:
        data = api.call("POST", IMAGE_PATH, body=audit_image_body(manifest, report, rule.get("name") or ""), auth=True)
    except ClientError as exc:
        # 这个服务器的业务错误常是 HTTP 200 加 JSON，错误码是数字：401 没登录、403 无权。
        if exc.code == "notFound":
            raise ClientError("renderNotDeployed", "服务器还没有结果图片接口（要部署新版后端）：先用 audit.md，部署后再生成图片。") from None
        if exc.code == "401":
            raise ClientError("loginRequired", f"{exc.message}（令牌缺失或过期：请用户在自己的终端重新 login）", **exc.details) from None
        if exc.code == "403":
            raise ClientError("forbidden", exc.message, **exc.details) from None
        raise
    pages = decode_image_pages(data)
    base = Path(args.out).expanduser().resolve() if args.out else bundle / "audit.png"
    targets = image_targets(base, len(pages))
    private_dir(base.parent)
    if not args.out:  # 默认位置：上一次留下的 audit.png / audit-N.png 不能和这次的混在一起
        for old in bundle.iterdir():
            if re.fullmatch(r"audit(-\d+)?\.png", old.name) and old not in targets:
                old.unlink()
    for target, png in zip(targets, pages, strict=True):
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(png)
        os.chmod(target, 0o600)
    outcome = node_outcome(report["checks"])
    return {"images": [str(t) for t in targets], "pageCount": len(pages), "bytes": sum(len(p) for p in pages),
            "outcome": outcome["label"],
            "next": "把图片路径告诉用户；你所在的环境能显示图片就按页码顺序一并展示。图只是摘要，完整依据在 audit.md。"}


# ---------------------------------------------------------------- sync to server

SYNC_VERDICTS = {"failed", "human_review_required", "evidence_insufficient", "not_executed"}
FINDING_SEVERITY = {"failed": "high", "human_review_required": "medium", "evidence_insufficient": "medium", "not_executed": "low"}
# 服务器要求 AI 发现带 confidence。这里按结论类型取固定值，不是模型概率；说明里写明。
FINDING_CONFIDENCE = {"failed": 0.8, "human_review_required": 0.6, "evidence_insufficient": 0.5, "not_executed": 0.3}
FINDING_TYPE = "ai_node_audit"


def matching_evidence_links(fact: dict[str, Any], version: str, evidence_chain: dict[str, Any]) -> list[str]:
    """Require a locatable fact match, not just a confirmed document version."""
    source = fact.get("source") or {}
    def literal(value: Any) -> str:
        return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value if value is not None else "")))
    excerpt, name, value = literal(source.get("excerpt")), literal(fact.get("name")), literal(fact.get("value"))
    matches = set()
    for link in (evidence_chain or {}).get("links") or []:
        if (not version or link.get("documentVersionId") != version or not link.get("id")
                or str(link.get("manualStatus") or "").lower() != "confirmed"
                or link.get("formalEvidenceEligible", True) is False
                or type(link.get("pageNo")) is not int or link["pageNo"] < 1
                or link["pageNo"] != source.get("page")):
            continue
        box = link.get("bbox")
        try:
            located = isinstance(box, (list, tuple)) and len(box) >= 4 and float(box[2]) > float(box[0]) and float(box[3]) > float(box[1])
        except (ValueError, TypeError):
            located = False
        quote, field = literal(link.get("quotedText")), literal(link.get("fieldName"))
        if not located or not (quote or field):
            continue
        same_excerpt = bool(excerpt and quote and excerpt == quote)
        same_field_value = bool(name and field == name and value and quote
                                and re.search(r"(?<![A-Za-z0-9.])" + re.escape(value) + r"(?![A-Za-z0-9.])",
                                              unicodedata.normalize("NFKC", str(link.get("quotedText") or ""))))
        if same_excerpt or same_field_value:
            matches.add(str(link["id"]))
    # Same text in several regions is ambiguous without a finer source locator.
    return sorted(matches) if len(matches) == 1 else []


def finding_description(check: dict[str, Any], outcome: dict[str, Any], unmatched: list[str] | None = None) -> str:
    parts = [f"结论：{VERDICTS[check['verdict']]}（节点整体：{outcome['label']}）"]
    if check.get("requirement"):
        parts.append(f"要求：{check['requirement']}")
    reason = (check.get("reasoning") or check.get("reason")) if check["verdict"] in NEEDS_SOURCE else (check.get("reason") or check.get("reasoning"))
    if reason:
        parts.append(f"理由：{reason}")
    for fact in (check.get("facts") or [])[:6]:
        parts.append(f"事实：{fact.get('name')}＝{fact.get('value')}（{fact_place(fact)}）")
    parts += [f"资料矛盾：{c}" for c in check.get("conflicts") or []]
    parts += [f"建议：{n}" for n in check.get("nextSteps") or []]
    if unmatched:
        parts.append("没挂证据链接的事实（服务器上没有逐条对应的已确认证据，请按出处人工核）：" + "；".join(unmatched))
    parts.append(f"来源：aicheck-node-audit 本地 AI 辅助审计；confidence 按结论类型固定取 {FINDING_CONFIDENCE[check['verdict']]}，不是模型概率。")
    text = "\n".join(str(p) for p in parts)
    return mask_ids(text if len(text) <= 2000 else text[:1990] + "…（截断）")


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def sync_approval_snapshot(server: str, plan: dict[str, Any], evidence_chain: dict[str, Any]) -> dict[str, Any]:
    # Ignore array ordering, not changed evidence content or confirmation status.
    links = sorted(evidence_chain.get("links") or [], key=canonical_digest)
    return {"server": server, "projectId": plan["manifest"]["projectId"], "nodeId": plan["manifest"]["nodeId"],
            "auditSha256": plan["auditSha256"], "evidenceSha256": canonical_digest(links),
            "create": plan["create"], "skipped": plan["skipped"]}


def sync_plan(bundle: Path, evidence_chain: dict[str, Any]) -> dict[str, Any]:
    manifest, report, errors_, _ = check_report(bundle)
    if errors_:
        raise ClientError("reportInvalid", "audit.json 未通过校验，先跑 report 改到通过再同步。", errors=errors_)
    if manifest.get("source") != "server":
        raise ClientError("localBundle", "这是本地资料包，服务器上没有对应的项目节点，不能同步。")
    outcome = node_outcome(report["checks"])
    versions = {f["path"]: str(f.get("documentVersionId") or "") for f in manifest.get("files") or []}
    risk_high = {flag.get("check") for flag in report.get("riskFlags") or [] if flag.get("level") == "high"}
    digest = hashlib.sha256((bundle / "audit.json").read_bytes()).hexdigest()
    rules = json.loads((bundle / "rules.json").read_text(encoding="utf-8")) if (bundle / "rules.json").exists() else {}
    pack = Path(str(rules.get("businessPack") or "engineering_inspection_v1")).name
    create, skipped = [], []
    for check in report["checks"]:
        cid, verdict = check["atomicCheckId"], check["verdict"]
        if verdict not in SYNC_VERDICTS:
            continue
        link_ids: list[str] = []
        unmatched = []
        for fact in check.get("facts") or []:
            path = (fact.get("source") or {}).get("file")
            matched = matching_evidence_links(fact, versions.get(str(path), ""), evidence_chain)
            if path in versions and not matched:
                unmatched.append(mask_ids(f"{fact.get('name')}（{fact_place(fact)}）"))
            for link_id in matched:
                if link_id not in link_ids:
                    link_ids.append(link_id)
        # 只挂逐条对上的证据；对不上的事实写进说明，不借同文件别的链接，也不因此丢掉整条发现。
        if not link_ids:
            skipped.append({"check": cid, "verdict": VERDICTS[verdict],
                            "reason": "本项没有一条事实对上同版本、同页且摘录或字段和值对应的唯一已确认证据；不借用同文件其他证据。"
                                      "可先在服务器上确认对应证据再同步，或由监检人员处理，本地报告保留。",
                            "unmatchedFacts": unmatched})
            continue
        body = {"projectId": manifest["projectId"], "nodeId": manifest["nodeId"], "source": "ai", "findingType": FINDING_TYPE,
                "severity": "high" if cid in risk_high else FINDING_SEVERITY[verdict],
                "title": mask_ids(f"{cid} {check.get('name') or ''}：{VERDICTS[verdict]}")[:200],
                "description": finding_description(check, outcome, unmatched), "evidenceLinkIds": sorted(link_ids),
                "ruleRefs": [{"ruleCode": manifest["ruleId"], "atomicCheckId": cid, "ruleSetVersion": pack}],
                "confidence": FINDING_CONFIDENCE[verdict],
                "suggestedAction": "human_confirm", "agentId": "aicheck-node-audit-skill", "agentVersion": REPORT_SCHEMA}
        key = canonical_digest(body)
        create.append({"check": cid, "verdict": VERDICTS[verdict], "idempotencyKey": key, "body": body, "unmatchedFacts": unmatched})
    return {"manifest": manifest, "outcome": outcome, "create": create, "skipped": skipped, "auditSha256": digest}


def cmd_sync(args: argparse.Namespace) -> Any:
    """Preview, then (only with --confirm) write the audit's open items to the server as AI findings pending human review.
    Never changes the node's status and never writes a human review opinion."""
    bundle = Path(args.bundle).expanduser().resolve()
    manifest = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))
    if manifest.get("source") != "server":
        raise ClientError("localBundle", "这是本地资料包，服务器上没有对应的项目节点，不能同步。")
    api = Api(args.base_url or manifest.get("baseUrl"))
    if api.base != manifest.get("baseUrl"):
        raise ClientError("serverMismatch", f"资料包取自 {manifest.get('baseUrl')}，当前服务器是 {api.base}，不能同步到别的服务器。")
    node_path = f"/projects/{parse.quote(manifest['projectId'], safe='')}/inspection/nodes/{manifest['nodeId']}"
    evidence_chain = api.call("GET", f"{node_path}/evidence-chain", auth=True) or {}
    plan = sync_plan(bundle, evidence_chain)
    snapshot = sync_approval_snapshot(api.base, plan, evidence_chain)
    snapshot_hash = canonical_digest(snapshot)
    outcome = plan["outcome"]
    preview = [{"check": item["check"], "verdict": item["verdict"], "severity": item["body"]["severity"],
                "title": item["body"]["title"], "evidenceLinks": len(item["body"]["evidenceLinkIds"]),
                "unmatchedFacts": item["unmatchedFacts"]} for item in plan["create"]]
    if not args.confirm:
        target = bundle / "sync" / f"preview-{snapshot_hash}.json"
        if not target.exists():
            write_private(target, dump(snapshot))
        return {"preview": True, "previewHash": snapshot_hash, "savedTo": str(target.relative_to(bundle)),
                "server": api.base, "outcome": outcome["label"], "willCreate": preview, "skipped": plan["skipped"],
                "note": "同步内容：未判符合的检查项各写一条 AI 审查发现（草稿，待人工复核），不改节点状态，不写人工审查意见；符合项不同步。",
                "next": "给用户看 willCreate、skipped 及快照完整内容；明确同意后加 --confirm --preview-hash " + snapshot_hash if preview else "没有可同步的项"}
    approved_hash = getattr(args, "preview_hash", None)
    if not approved_hash or not re.fullmatch(r"[a-f0-9]{64}", approved_hash):
        raise ClientError("previewRequired", "须先预览并获用户同意，再用 --confirm --preview-hash <该次摘要>。")
    try:
        approved = json.loads((bundle / "sync" / f"preview-{approved_hash}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ClientError("previewRequired", "找不到可读的已批准预览；请重新预览。") from None
    if canonical_digest(approved) != approved_hash or snapshot_hash != approved_hash:
        raise ClientError("previewChanged", "报告、证据链或预览内容已变化；没有写服务器，请重新预览并确认。")
    results = []
    for item in plan["create"]:
        try:
            data = api.call("POST", "/review/findings", body=item["body"], auth=True, headers={"Idempotency-Key": item["idempotencyKey"]})
            finding = (data or {}).get("finding") or {}
            results.append({"check": item["check"], "ok": True, "findingId": finding.get("id"), "status": finding.get("status"),
                            "humanStatus": finding.get("humanStatus")})
        except ClientError as exc:
            results.append({"check": item["check"], "ok": False, "error": {"code": exc.code, "message": exc.message}})
    record = {"at": now(), "server": api.base, "projectId": manifest["projectId"], "nodeId": manifest["nodeId"],
              "auditSha256": plan["auditSha256"], "previewHash": snapshot_hash,
              "outcome": outcome["label"], "results": results, "skipped": plan["skipped"]}
    target = bundle / "sync" / f"{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.json"
    private_dir(target.parent)
    write_private(target, dump_masked(record))
    return {"synced": sum(r["ok"] for r in results), "failed": [r for r in results if not r["ok"]], "skipped": plan["skipped"],
            "results": results, "savedTo": str(target.relative_to(bundle)),
            "next": "告诉用户：已写入几条、哪些失败或跳过；这些发现在服务器“审查发现”里待人工接受或驳回"}


# ---------------------------------------------------------------- CLI

def save_tool_result(args: argparse.Namespace, data: Any, error: dict[str, Any] | None = None) -> str:
    """失败的查询也存档：报告引用 tool: 时要有文件可指，“平台不可用”本身就是事实。"""
    bundle = Path(args.bundle).expanduser().resolve()
    arguments = {k: v for k, v in vars(args).items() if k not in {"func", "saves", "bundle", "base_url", "command"}}
    target = bundle / "tool-results" / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{args.command}.json"
    record = {"tool": args.command, "at": now(), "ok": error is None, "arguments": arguments}
    record.update({"error": error} if error else {"result": data})
    write_private(target, dump_masked(record))
    return str(target.relative_to(bundle))

def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="AIcheck 节点审计（AI 本地辅助）")
    root.add_argument("--base-url", help="服务器 origin；默认 AICHECK_BASE_URL 或登录时保存的地址")
    sub = root.add_subparsers(dest="command", required=True)

    p = sub.add_parser("login", help="用户在自己的终端登录（getpass 读口令）")
    p.add_argument("--username", required=True)
    p.add_argument("--tenant-id")
    p.set_defaults(func=cmd_login)
    sub.add_parser("logout").set_defaults(func=cmd_logout)
    sub.add_parser("connection").set_defaults(func=cmd_connection)

    p = sub.add_parser("rules", help="本地业务包的节点规则与原子检查")
    p.add_argument("--node", type=int, required=True)
    p.set_defaults(func=cmd_rules)

    p = sub.add_parser("fetch", help="从服务器拉取节点资料包")
    p.add_argument("--project", required=True)
    p.add_argument("--node", type=int, required=True)
    p.add_argument("--out")
    p.add_argument("--no-files", action="store_true", help="只取元数据，不下载原件")
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("local-init", help="用本地测试文件建资料包")
    p.add_argument("--node", type=int, required=True)
    p.add_argument("--project-dir", help="整个项目目录：递归收入全部文件（推荐，合同、施工方案这类全项目资料不会漏）")
    p.add_argument("--files", nargs="+", help="只收这些文件；可与 --project-dir 同用")
    p.add_argument("--project")
    p.add_argument("--out")
    p.add_argument("--workspace", help="可选：模拟服务器 audit-workspace 的 JSON")
    p.add_argument("--review-run", help="可选：模拟服务器审查运行（含 atomicCheckOutcomes）的 JSON")
    p.set_defaults(func=cmd_local_init)

    p = sub.add_parser("pages", help="PDF 或图片渲染成 PNG 并取文字层；--clip 放大局部，--sheet 出缩略拼图")
    p.add_argument("--file")
    p.add_argument("--all-visual", action="store_true", help="配 --bundle：给最近一次 search 标出的全部无文字层文件出缩略拼图")
    p.add_argument("--pages", help="如 1-3,7；单页渲染一次最多 20 页；--sheet 时省略即全部页")
    p.add_argument("--dpi", type=int, help="默认 150；--sheet 默认 72")
    p.add_argument("--bundle", help="页图存进这个资料包的 pages/（文件不在资料包里时必须给，或给 --out）")
    p.add_argument("--out", help="输出目录；默认文件所在资料包的 pages/")
    p.add_argument("--text-only", action="store_true")
    p.add_argument("--clip", help="只渲染页面局部 x0,y0,x1,y1（0–1 比例），配合高 --dpi 看小字")
    p.add_argument("--rotate", type=int, choices=(0, 90, 180, 270), help="顺时针旋转页图（横放的表格、图纸转正）；--clip 按转正后的样子给")
    p.add_argument("--sheet", action="store_true", help="缩略拼图：每格一页并标页码，每张最多 30 格")
    p.add_argument("--cols", type=int, default=5, help="拼图列数，默认 5")
    p.set_defaults(func=cmd_pages)

    p = sub.add_parser("text", help="把 .doc/.docx/.xlsx/文字 PDF 转成文本存到资料包 text/，再读全文")
    p.add_argument("--file", required=True)
    p.add_argument("--bundle", help="存进这个资料包的 text/（文件不在资料包里时必须给，或给 --out）")
    p.add_argument("--out", help="输出文件或目录")
    p.set_defaults(func=cmd_text)

    p = sub.add_parser("ocr", help="没有文字层的原件交服务器 OCR（MinerU，排队超时自动改千问），逐页文字存进资料包 ocr/、text/（需登录）")
    p.add_argument("--bundle", required=True)
    p.add_argument("--files", nargs="+", help="只 OCR 这些（资料包相对路径，或 standard:rules/standards/…）；默认全部没有文字层的原件")
    p.add_argument("--force", action="store_true", help="已有 OCR 也重做")
    p.add_argument("--timeout", type=int, default=300, help="最多等几秒，默认 300；没等完再跑一次接着等，不重传")
    p.add_argument("--allow-egress", action="store_true", help="本地资料包：用户已同意把原件上传到服务器做 OCR（每个资料包一次）")
    p.set_defaults(func=cmd_ocr)

    p = sub.add_parser("search", help="在资料包全部文件的文字层和 OCR 文字里检索规则关键词与常见事实（需 PyMuPDF 读 PDF）")
    p.add_argument("--bundle", required=True)
    p.add_argument("--terms", nargs="+", help="追加的检索词")
    p.add_argument("--only", action="store_true", help="只用 --terms，不带默认词")
    p.add_argument("--max-per-term", type=int, default=5, help="每个词在每份文件里最多记几处")
    p.add_argument("--sample", type=int, default=1, help="每份文件在输出里展示几处命中（全部命中见 saved 指向的 JSON）")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("cert-registry", help="公示平台登记查询（经服务器）")
    p.add_argument("--kind", choices=["person", "organization_license"], required=True)
    p.add_argument("--identifier", required=True)
    p.set_defaults(func=cmd_cert_registry, saves=True)
    p = sub.add_parser("cert-validity", help="证件有效期/主体/范围字段核对（经服务器）")
    p.add_argument("--json", required=True)
    p.set_defaults(func=cmd_cert_validity, saves=True)
    p = sub.add_parser("cnse-org-search", help="按单位名称查公示平台（需登录）")
    p.add_argument("--keyword", required=True)
    p.set_defaults(func=cmd_cnse_org_search, saves=True)

    p = sub.add_parser("standards", help="检索公共标准库")
    p.add_argument("--query", required=True)
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--page-size", type=int, default=20)
    p.set_defaults(func=cmd_standards, saves=True)
    p = sub.add_parser("standard-content", help="读取标准规范化原文")
    p.add_argument("--file-id", required=True)
    p.add_argument("--page-no", type=int)
    p.add_argument("--section")
    p.set_defaults(func=cmd_standard_content, saves=True)
    p = sub.add_parser("standard-status", help="标准在某日的有效状态")
    p.add_argument("--ref", required=True)
    p.add_argument("--date")
    p.set_defaults(func=cmd_standard_status, saves=True)
    p = sub.add_parser("node-standards", help="项目节点的固定依据条款（需登录）")
    p.add_argument("--project", required=True)
    p.add_argument("--node", type=int, required=True)
    p.set_defaults(func=cmd_node_standards)

    for name, command in sub.choices.items():
        if command.get_default("saves"):
            command.add_argument("--bundle", help="把这次结果存进资料包 tool-results/，供报告引用")

    p = sub.add_parser("skeleton", help="生成 audit.json 骨架：原子检查与文件都已列好，只需填空")
    p.add_argument("--bundle", required=True)
    p.add_argument("--force", action="store_true", help="覆盖已有的 audit.json")
    p.set_defaults(func=cmd_skeleton)

    p = sub.add_parser("report", help="校验 audit.json 并生成 audit.md")
    p.add_argument("--bundle", required=True)
    p.set_defaults(func=cmd_report)
    p = sub.add_parser("render", help="把审计结果摘要发给服务器，用 HTML 模板渲染成白底的图 audit.png（内容多自动分页为 audit-1.png…；需登录）")
    p.add_argument("--bundle", required=True)
    p.add_argument("--out", help="图片保存路径；默认资料包里的 audit.png（多页加页码）")
    p.set_defaults(func=cmd_render)
    p = sub.add_parser("sync", help="把审计结果同步到服务器（先预览；用户同意后加 --confirm）")
    p.add_argument("--bundle", required=True)
    p.add_argument("--confirm", action="store_true", help="用户已明确同意同步")
    p.add_argument("--preview-hash", help="用户已确认的预览摘要；确认时必须与当前计划一致")
    p.set_defaults(func=cmd_sync)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        # 所有带 --bundle 的命令都先确认它是资料包：路径写错时给出错误 JSON，而不是读 bundle.json 时抛 Traceback。
        if getattr(args, "bundle", None) and not (Path(args.bundle).expanduser() / "bundle.json").exists():
            raise ClientError("bundleMissing", f"{args.bundle} 不是资料包（没有 bundle.json），未执行：检查路径，或先 fetch / local-init。")
        data = args.func(args)
        saved = save_tool_result(args, data) if getattr(args, "saves", False) and args.bundle else None
        print(dump_masked({"ok": True, "data": data, **({"savedTo": saved} if saved else {})}))
        return 0
    except ClientError as exc:
        error = {"code": exc.code, "message": exc.message, **exc.details}
        saved = None
        if getattr(args, "saves", False) and args.bundle and exc.code != "bundleMissing":
            saved = save_tool_result(args, None, error)
        print(dump_masked({"ok": False, "error": error, **({"savedTo": saved} if saved else {})}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
