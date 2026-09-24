#!/usr/bin/env python3
"""Portable AIcheck client. Python 3.10+, standard library only; no model credentials."""
from __future__ import annotations

import argparse
import getpass
import hashlib
import ipaddress
import json
import os
import re
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any
from urllib import error, parse, request


class ClientError(Exception):
    """Safe error suitable for CLI and MCP output."""

    def __init__(self, code: str, message: str, **details: Any):
        self.code = code
        self.message = message
        self.details = details
        super().__init__(message)


def schema(properties: dict, required: tuple = ()) -> dict:
    return {"type": "object", "properties": properties, "required": list(required),
            "additionalProperties": False}


TEXT = {"type": "string", "minLength": 1, "maxLength": 1000}
NODE = {"type": "integer", "minimum": 1}
DATE = {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$", "minLength": 10, "maxLength": 10}
STRINGS = {"type": "array", "items": TEXT, "maxItems": 100}
PAGING = {"page": {"type": "integer", "minimum": 1},
          "pageSize": {"type": "integer", "minimum": 1, "maximum": 200}}
CERTIFICATE = schema({"certificateNo": TEXT, "holder": TEXT, "validFrom": DATE,
                      "validUntil": DATE, "scopes": STRINGS})


def action(description: str, properties: dict, required: tuple = (), read_only: bool = True) -> dict:
    return {"description": description, "inputSchema": schema(properties, required), "readOnly": read_only}


ACTIONS = {
    "connection": action("检查标准、规则和证件审查服务的可用性与处理留存说明。", {}),
    "standards": action("检索公共标准依据，保留来源与版本；不读取工程资料，不证明标准现行性。",
                        {"query": TEXT, **PAGING}, ("query",)),
    "standard_content": action("读取标准规范化原文及来源，供核对条款；不能以标准列表摘要代替原文。",
                               {"fileId": TEXT, "pageNo": NODE, "section": TEXT}, ("fileId",)),
    "standard_status": action("通过标准公共服务核验指定标准在审查日期的有效状态，不上传工程资料。",
                              {"standardRef": TEXT, "reviewDate": DATE}, ("standardRef",)),
    "rules": action("读取本地v3规则；source=server读取服务器公共审查规则及版本。无需工程身份或资料编号。",
                    {"nodeId": NODE, "source": {"type": "string", "enum": ["local", "server"]}}),
    "certificate_validity": action("对用户本地资料提取的证件字段核验有效期、主体与范围；不存储资料，不代表证件真伪或官方登记已核验。必须提供referenceDate或完整periodStart+periodEnd，日期为YYYY-MM-DD。",
                                   {"certificates": {"type": "array", "items": CERTIFICATE, "maxItems": 100},
                                    "expectedHolder": TEXT, "requiredScopes": STRINGS,
                                    "periodStart": DATE, "periodEnd": DATE, "referenceDate": DATE},
                                   ("certificates",)),
    "certificate_registry": action("明确获用户授权后，将最少的证件标识发送官方登记查询；不存储查询结果，第三方留存依其政策；查不到或服务失败不能判为假证。",
                                   {"kind": {"type": "string", "enum": ["person", "organization_license"]},
                                    "identifier": TEXT, "allowExternalQuery": {"type": "boolean", "enum": [True]}},
                                   ("kind", "identifier", "allowExternalQuery")),
}


def _validate(value: Any, spec: dict, path: str = "arguments") -> None:
    kind = spec.get("type")
    if kind == "object":
        if not isinstance(value, dict):
            raise ClientError("invalidArguments", f"{path} 必须是JSON对象。")
        if set(value) - spec.get("properties", {}).keys():
            raise ClientError("invalidArguments", f"{path} 含未支持字段。")
        if set(spec.get("required", [])) - value.keys():
            raise ClientError("invalidArguments", f"{path} 缺少必填字段。")
        for key, item in value.items():
            _validate(item, spec["properties"][key], f"{path}.{key}")
    elif kind == "string":
        if not isinstance(value, str) or (spec.get("minLength") and not value.strip()) or "\x00" in value or len(value) > spec.get("maxLength", 1000000):
            raise ClientError("invalidArguments", f"{path} 必须是非空字符串。")
        if "pattern" in spec and not re.fullmatch(spec["pattern"], value):
            raise ClientError("invalidArguments", f"{path} 格式无效。")
    elif kind == "boolean":
        if type(value) is not bool:
            raise ClientError("invalidArguments", f"{path} 必须是布尔值。")
    elif kind == "integer":
        if type(value) is not int or value < spec.get("minimum", value) or value > spec.get("maximum", value):
            raise ClientError("invalidArguments", f"{path} 整数范围无效。")
    elif kind == "array":
        if not isinstance(value, list) or not spec.get("minItems", 0) <= len(value) <= spec.get("maxItems", 10000):
            raise ClientError("invalidArguments", f"{path} 列表长度无效。")
        if spec.get("uniqueItems") and len({json.dumps(item, sort_keys=True) for item in value}) != len(value):
            raise ClientError("invalidArguments", f"{path} 不得重复。")
        for item in value:
            _validate(item, spec["items"], path)
    if "enum" in spec and value not in spec["enum"]:
        raise ClientError("invalidArguments", f"{path} 值不受支持。")


def _origin(url: str) -> tuple:
    parsed = parse.urlsplit(url)
    return parsed.scheme.lower(), (parsed.hostname or "").lower(), parsed.port or (443 if parsed.scheme == "https" else 80)


def _allowed_url(url: str) -> str:
    try:
        parsed = parse.urlsplit(url)
        _origin(url)  # also validate port
    except ValueError as exc:
        raise ClientError("invalidUrl", "服务器地址格式无效。") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ClientError("invalidUrl", "仅支持不带用户名、密码、片段的HTTP(S)地址。")
    try:
        loopback = ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        loopback = parsed.hostname.lower() == "localhost"
    if parsed.scheme == "http" and not loopback and os.getenv("AICHECK_ALLOW_HTTP", "").lower() not in {"1", "true", "yes"}:
        raise ClientError("insecureTransport", "远程服务器必须使用HTTPS；可信私网HTTP需显式设置AICHECK_ALLOW_HTTP=1。")
    return url


# Match the public sources actually emitted by backend std_samr_client.py.
# This is output presentation only; it neither fetches a URL nor changes API transport policy.
PUBLIC_STANDARD_PATHS = frozenset({"/", "/search/stdPage", "/gb/search/gbDetailed",
                                   "/hb/search/stdHBDetailed", "/db/search/stdDBDetailed"})


def _public_standard_source(url: str, redactions: list[str]) -> bool:
    try:
        if any(secret and secret in parse.unquote(url) for secret in redactions):
            return False
        parts = parse.urlsplit(url)
        query = parse.parse_qsl(parts.query, keep_blank_values=True, strict_parsing=True)
        return (parts.scheme.lower() == "https" and parts.hostname == "std.samr.gov.cn"
                and parts.port in (None, 443) and parts.username is None and parts.password is None
                and not parts.fragment and (parts.path or "/") in PUBLIC_STANDARD_PATHS
                and all(key == "id" and re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value) for key, value in query)
                and len(query) <= 1)
    except ValueError:
        return False


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self, *, require_token: bool = True):
        raw_base = os.getenv("AICHECK_BASE_URL", "").strip().rstrip("/")
        if not raw_base:
            raise ClientError("notConfigured", "请设置AICHECK_BASE_URL为后台服务地址。")
        self.base = _allowed_url(raw_base)
        if parse.urlsplit(self.base).query:
            raise ClientError("invalidUrl", "AICHECK_BASE_URL不能包含查询参数。")
        if not self.base.endswith("/api"):
            self.base += "/api"
        self.token = os.getenv("AICHECK_TOKEN", "").strip() if require_token else ""
        if require_token and not self.token and os.getenv("AICHECK_TOKEN_FILE"):
            try:
                self.token = Path(os.environ["AICHECK_TOKEN_FILE"]).expanduser().read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise ClientError("tokenUnavailable", "无法读取AICHECK_TOKEN_FILE。") from exc
        self.token = self.token.removeprefix("Bearer ").strip()
        if require_token and not self.token:
            raise ClientError("notAuthenticated", "请提供AICHECK_TOKEN_FILE或AICHECK_TOKEN，或运行login。")
        if "\n" in self.token or "\r" in self.token:
            raise ClientError("invalidToken", "令牌文件格式无效。")
        self.redactions = [self.token] if self.token else []
        try:
            self.timeout = max(1.0, min(float(os.getenv("AICHECK_TIMEOUT", "60")), 300.0))
        except ValueError as exc:
            raise ClientError("invalidConfiguration", "AICHECK_TIMEOUT须为秒数。") from exc
        self.opener = request.build_opener(_NoRedirect())

    def safe(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: ("[redacted]" if any(word in key.lower() for word in ("token", "authorization", "password", "secret", "contentbase64"))
                          else self.safe(item)) for key, item in value.items()}
        if isinstance(value, list):
            return [self.safe(item) for item in value]
        if isinstance(value, str):
            text = value
            for secret in self.redactions:
                if secret:
                    text = text.replace(secret, "[redacted]")
            # Preserve narrowly allowlisted public standard citations, never signed/storage URLs.
            return re.sub(r"https?://[^\s\"'<>]+",
                          lambda match: match.group(0) if _public_standard_source(match.group(0), self.redactions) else "[server URL redacted]",
                          text, flags=re.IGNORECASE)
        return value

    def url(self, path: str, query: dict | None = None) -> str:
        url = self.base + "/" + path.lstrip("/")
        return url + ("?" + parse.urlencode(query) if query else "")

    def open(self, method: str, url: str, *, body: Any = None, headers: dict | None = None,
             authenticate: bool = True):
        _allowed_url(url)
        outgoing = dict(headers or {})
        # Never trust a returned signed URL's headers to forward API identity.
        for key in list(outgoing):
            if key.lower() in {"authorization", "cookie", "proxy-authorization"}:
                del outgoing[key]
        if authenticate and self.token and _origin(url) == _origin(self.base):
            outgoing["Authorization"] = "Bearer " + self.token
        outgoing.setdefault("User-Agent", "AIcheck-Inspection-Skill/2.0")
        req = request.Request(url, data=body, headers=outgoing, method=method)
        try:
            return self.opener.open(req, timeout=self.timeout)
        except error.HTTPError as exc:
            return exc
        except (error.URLError, TimeoutError, OSError) as exc:
            raise ClientError("networkError", "无法连接审查服务或请求超时。未自动重试；确认服务状态后可重新发起请求。") from exc

    def decode(self, response, *, capability: bool = False) -> Any:
        status = response.status
        raw = response.read(32 * 1024 * 1024 + 1)
        if len(raw) > 32 * 1024 * 1024:
            raise ClientError("responseTooLarge", "服务器响应过大，请缩小查询范围。")
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            payload = None
        if 300 <= status < 400:
            raise ClientError("redirectRejected", "API重定向已拒绝；请将AICHECK_BASE_URL设置为最终API地址。", httpStatus=status)
        if capability and status == 404:
            raise ClientError("capabilityUnavailable", "服务器尚未部署对应的无存储审查服务。可继续按本地skill审查用户提供的资料；不会回退到工程资料上传接口。", httpStatus=status, capabilityUnavailable=True)
        if status >= 400 or not isinstance(payload, dict) or payload.get("code") != 0:
            if isinstance(payload, dict) and "code" in payload:
                business_data = payload.get("data")
                raise ClientError(str(payload.get("code")), self.safe(str(payload.get("message") or "服务器业务请求失败。")),
                                  httpStatus=status, operationId=self.safe(payload.get("operationId")),
                                  reason=self.safe(business_data.get("reason") if isinstance(business_data, dict) else None))
            raise ClientError("httpError" if status >= 400 else "invalidResponse", "后台未返回有效成功响应。", httpStatus=status)
        return payload.get("data")

    def api(self, method: str, path: str, *, query: dict | None = None, body: dict | None = None,
            capability: bool = False) -> Any:
        headers = {"Accept": "application/json"}
        encoded = None
        if body is not None:
            encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        with self.open(method, self.url(path, query), body=encoded, headers=headers) as response:
            return self.decode(response, capability=capability)


def _segment(value: Any) -> str:
    return parse.quote(str(value), safe="")


def _local_rules(arguments: dict) -> dict:
    path = Path(__file__).resolve().parents[1] / "references" / "business-nodes-v3.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ClientError("rulesUnavailable", "skill缺少references/business-nodes-v3.md，请完整安装skill目录。") from exc
    rows = [{"nodeId": int(match[1]), "code": f"R{int(match[1]):02d}", "name": match[2].strip(), "content": match[3].strip()}
            for match in re.finditer(r"^## R(\d+)｜([^\n]+)\n(.*?)(?=^## R|\Z)", text, re.MULTILINE | re.DOTALL)]
    if "nodeId" in arguments:
        rows = [row for row in rows if row["nodeId"] == arguments["nodeId"]]
    if not rows:
        raise ClientError("rulesUnavailable", "本地v3文档没有该节点规则。")
    return {"source": "local", "reference": "references/business-nodes-v3.md",
            "version": hashlib.sha256(text.encode()).hexdigest(), "nodes": rows}


def _validate_certificate_dates(arguments: dict) -> None:
    start, end = arguments.get("periodStart"), arguments.get("periodEnd")
    if bool(start) != bool(end):
        raise ClientError("invalidArguments", "施工期间须同时提供periodStart和periodEnd。")
    if not arguments.get("referenceDate") and not (start and end):
        raise ClientError("invalidArguments", "请明确业务核验日期referenceDate或完整施工期间periodStart+periodEnd，不能自动按今天判断。")
    values = [arguments[key] for key in ("periodStart", "periodEnd", "referenceDate") if key in arguments]
    values.extend(row[key] for row in arguments["certificates"] for key in ("validFrom", "validUntil") if key in row)
    try:
        for value in values:
            date.fromisoformat(value)
    except ValueError as exc:
        raise ClientError("invalidArguments", "证件日期及核验日期必须是有效的YYYY-MM-DD日期。") from exc
    if start and end and start > end:
        raise ClientError("invalidArguments", "periodStart不得晚于periodEnd。")
    for certificate in arguments["certificates"]:
        if certificate.get("validFrom") and certificate.get("validUntil") and certificate["validFrom"] > certificate["validUntil"]:
            raise ClientError("invalidArguments", "证件validFrom不得晚于validUntil。")


def invoke(action_name: str, arguments: dict) -> dict:
    """Return JSON-safe result; never print secrets, including in business errors."""
    client = None
    try:
        if action_name not in ACTIONS:
            raise ClientError("unknownAction", "未知动作。此客户端仅提供审查服务，不提供工程资料管理或后台审查任务。")
        _validate(arguments, ACTIONS[action_name]["inputSchema"])
        if action_name == "rules" and arguments.get("source", "local") == "local":
            return {"ok": True, "data": _local_rules(arguments)}
        if action_name == "certificate_validity":
            _validate_certificate_dates(arguments)
        client = Client()
        if action_name == "connection":
            result = client.api("GET", "inspection-services/capabilities", capability=True)
        elif action_name == "standards":
            result = client.api("GET", "knowledge/clauses", query={"keyword": arguments["query"],
                                "page": arguments.get("page", 1), "pageSize": arguments.get("pageSize", 20)})
            result["warnings"] = ["当前total仅为检索截断后的匹配条目数，不代表标准库完整总量；未命中不证明不存在相应标准。"]
        elif action_name == "standard_content":
            query = {"includeBlocks": "true", "includeHistory": "false"}
            for key in ("pageNo", "section"):
                if key in arguments:
                    query[key] = arguments[key]
            try:
                result = client.api("GET", "knowledge/files/" + _segment(arguments["fileId"]) + "/canonical", query=query)
            except ClientError as exc:
                if exc.code == "40404" or exc.details.get("httpStatus") == 404:
                    raise ClientError("standardEvidenceUnavailable", "标准原文尚不可用或无权访问，不能据摘要确定条款或数值要求。") from exc
                raise
        elif action_name == "standard_status":
            result = client.api("POST", "std-samr/standards/verify", body=arguments)
        elif action_name == "rules":
            result = client.api("GET", "inspection-services/rules",
                                query={"nodeId": arguments["nodeId"]} if "nodeId" in arguments else None, capability=True)
        elif action_name == "certificate_validity":
            result = client.api("POST", "inspection-services/certificate-validity", body=arguments, capability=True)
        elif action_name == "certificate_registry":
            result = client.api("POST", "inspection-services/certificate-registry", body=arguments, capability=True)
        return {"ok": True, "data": client.safe(result)}
    except ClientError as exc:
        payload = {"code": exc.code, "message": exc.message, **exc.details}
        return {"ok": False, "error": client.safe(payload) if client else payload}
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return {"ok": False, "error": {"code": "clientError", "message": "本地文件或服务器响应无效；未自动重试。", "errorType": type(exc).__name__}}


def login(username: str | None, token_file: str | None, tenant_id: str | None) -> dict:
    raw_path = token_file or os.getenv("AICHECK_TOKEN_FILE")
    if not raw_path:
        raise ClientError("invalidConfiguration", "请通过--token-file或AICHECK_TOKEN_FILE指定令牌保存位置。")
    client = Client(require_token=False)
    name = username or input("AIcheck username: ").strip()
    password = getpass.getpass("AIcheck password: ")
    if not name or not password:
        raise ClientError("invalidCredentials", "账号和密码不能为空。")
    client.redactions.append(password)
    body = {"username": name, "password": password}
    if tenant_id:
        body["tenantId"] = tenant_id
    data = client.api("POST", "auth/login", body=body)
    token = str(data.get("token") or "").removeprefix("Bearer ").strip()
    if not token or "\n" in token or "\r" in token:
        raise ClientError("invalidResponse", "登录响应未提供有效令牌。")
    path = Path(raw_path).expanduser().absolute()
    if path.is_symlink():
        raise ClientError("invalidPath", "令牌目标不能是符号链接。")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".aicheck-token-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            os.chmod(temporary, 0o600)
            stream.write(token + "\n")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return {"ok": True, "data": {"tokenFile": str(path), "message": "登录成功，令牌已安全写入文件；请设置AICHECK_TOKEN_FILE。"}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=[*ACTIONS, "login"])
    parser.add_argument("--json", default="{}", dest="arguments", help="JSON object arguments")
    parser.add_argument("--username")
    parser.add_argument("--token-file")
    parser.add_argument("--tenant-id")
    args = parser.parse_args()
    try:
        result = (login(args.username, args.token_file, args.tenant_id) if args.action == "login"
                  else invoke(args.action, json.loads(args.arguments)))
    except ClientError as exc:
        result = {"ok": False, "error": {"code": exc.code, "message": exc.message, **exc.details}}
    except (ValueError, OSError, EOFError):
        result = {"ok": False, "error": {"code": "clientError", "message": "参数格式或本地文件操作失败。"}}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
