#!/usr/bin/env python3
"""Portable stdio MCP adapter. Python 3.10+, no third-party dependencies."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from aicheck_client import ACTIONS, ClientError, invoke

VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
ROOT = Path(__file__).resolve().parents[1]
RESOURCES = {
    "aicheck://skill": ("监检工作方法", "SKILL.md"),
    "aicheck://business-nodes-v3": ("业务节点描述 v3", "references/business-nodes-v3.md"),
    "aicheck://review-contract": ("审查输出与判定", "references/review-contract.md"),
}


def validate(value, schema, path="arguments"):
    """Validate the deliberately small JSON Schema subset used by our public tools."""
    kind = schema.get("type")
    types = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool}
    if kind in types and (not isinstance(value, types[kind]) or kind == "integer" and isinstance(value, bool)):
        raise ValueError(f"{path}: expected {kind}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path}: unsupported value")
    if kind == "object":
        properties = schema.get("properties", {})
        if any(key not in value for key in schema.get("required", [])):
            raise ValueError(f"{path}: missing required field")
        if schema.get("additionalProperties") is False and set(value) - set(properties):
            raise ValueError(f"{path}: unexpected field")
        for key, item in value.items():
            if key in properties:
                validate(item, properties[key], f"{path}.{key}")
    elif kind == "array":
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", 10000):
            raise ValueError(f"{path}: invalid number of items")
        if schema.get("uniqueItems") and len({json.dumps(item, sort_keys=True) for item in value}) != len(value):
            raise ValueError(f"{path}: duplicate items")
        for item in value:
            validate(item, schema.get("items", {}), path + "[]")
    elif kind == "string":
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", 1000000):
            raise ValueError(f"{path}: invalid length")
    elif kind == "integer":
        if value < schema.get("minimum", -2**53) or value > schema.get("maximum", 2**53):
            raise ValueError(f"{path}: out of range")


class Server:
    def __init__(self):
        self.initialized = False

    def dispatch(self, request):
        if not isinstance(request, dict) or request.get("jsonrpc") != "2.0" or not isinstance(request.get("method"), str):
            return self.error(None, -32600, "Invalid Request")
        request_id = request.get("id")
        method = request["method"]
        params = request.get("params", {})
        # JSON-RPC notifications, including initialized/cancelled, never receive responses.
        if "id" not in request:
            return None
        if not isinstance(params, dict):
            return self.error(request_id, -32602, "Invalid params")
        try:
            result = self.handle(method, params)
        except ValueError as exc:
            return self.error(request_id, -32602, str(exc))
        except LookupError:
            return self.error(request_id, -32601, "Method not found")
        except Exception:  # noqa: BLE001 - protocol boundary must redact all implementation errors
            # Never serialize exception repr, which can include credentials or URLs.
            return self.error(request_id, -32603, "Internal error; consult local configuration")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def error(request_id, code, message):
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

    def handle(self, method, params):
        if method == "initialize":
            requested = params.get("protocolVersion")
            self.initialized = True
            return {
                "protocolVersion": requested if requested in VERSIONS else VERSIONS[0],
                "capabilities": {"tools": {}, "resources": {}},
                "serverInfo": {"name": "aicheck-inspection", "version": "2.0.0"},
                "instructions": "读取 aicheck://skill 获取监检方法。资料仅由用户本地提供，宿主AI平台先完成OCR和资料整理。工具仅提供标准、规则及证件核验，不接收工程原文件，不创建工程资料或审查任务。所有结果为辅助意见。",
            }
        if method == "ping":
            return {}
        if not self.initialized:
            raise ValueError("Initialize the MCP connection first")
        if method == "tools/list":
            return {"tools": [{
                "name": "aicheck_" + name,
                "description": spec["description"],
                "inputSchema": spec["inputSchema"],
                "annotations": {
                    "readOnlyHint": spec.get("readOnly", False),
                    "destructiveHint": False,
                    "idempotentHint": spec.get("readOnly", False),
                    "openWorldHint": True,
                },
            } for name, spec in ACTIONS.items()]}
        if method == "tools/call":
            name = params.get("name", "")
            action = name.removeprefix("aicheck_") if isinstance(name, str) else ""
            if not isinstance(name, str) or not name.startswith("aicheck_") or action not in ACTIONS:
                raise ValueError("Unknown tool")
            arguments = params.get("arguments", {})
            validate(arguments, ACTIONS[action]["inputSchema"])
            try:
                data = invoke(action, arguments)
                return {"isError": data.get("ok") is False,
                        "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}]}
            except ClientError as exc:
                return {"isError": True, "content": [{"type": "text", "text": str(exc)}]}
        if method == "resources/list":
            return {"resources": [{"uri": uri, "name": title, "mimeType": "text/markdown"}
                                  for uri, (title, _) in RESOURCES.items()]}
        if method == "resources/read":
            uri = params.get("uri")
            if uri not in RESOURCES:
                raise ValueError("Unknown resource")
            return {"contents": [{"uri": uri, "mimeType": "text/markdown",
                                   "text": (ROOT / RESOURCES[uri][1]).read_text(encoding="utf-8")}]}
        raise LookupError(method)


def main():
    server = Server()
    for raw in sys.stdin:
        try:
            request = json.loads(raw)
        except (ValueError, UnicodeError):
            response = server.error(None, -32700, "Parse error")
        else:
            response = server.dispatch(request)
        if response is not None:
            print(json.dumps(response, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
