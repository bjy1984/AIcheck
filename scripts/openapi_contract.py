from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
OPENAPI_DIR = ROOT / "openapi"
ENTRYPOINT = OPENAPI_DIR / "aicheck.yaml"
INDEX_PATH = OPENAPI_DIR / "contract-index.json"
FRONTEND_OPERATION_MAP_PATH = (
    ROOT / "frontend" / "src" / "api" / "aicheck" / "generated" / "operation-map.ts"
)

REQUIRED_FILES = [
    "aicheck.yaml",
    "common.yaml",
    "schemas-project.yaml",
    "schemas-document.yaml",
    "schemas-review.yaml",
    "paths-workbench.yaml",
    "paths-documents.yaml",
    "paths-submissions.yaml",
    "paths-inspection.yaml",
    "paths-ndt-owner-report.yaml",
    "paths-knowledge-admin.yaml",
]
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
REQUIRED_RESPONSE_CODES = {"200", "400", "401", "403", "404", "409"}
OPERATION_ID_RE = re.compile(r"^[a-z][a-z0-9]*_[a-z][a-z0-9]*_[a-z0-9_]+$")


class OpenApiContractError(AssertionError):
    pass


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    if not isinstance(payload, dict):
        raise OpenApiContractError(f"{path} must contain a YAML object")
    return payload


def pointer_parts(pointer: str) -> list[str]:
    if not pointer:
        return []
    if not pointer.startswith("/"):
        raise OpenApiContractError(f"Invalid JSON pointer: {pointer}")
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]


def read_pointer(payload: Any, pointer: str) -> Any:
    current = payload
    for part in pointer_parts(pointer):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            raise OpenApiContractError(f"Cannot resolve pointer {pointer!r} at {part!r}")
    return current


def resolve_ref(ref: str, *, base_file: Path) -> Any:
    file_part, _, pointer = ref.partition("#")
    target_file = (base_file.parent / file_part).resolve() if file_part else base_file
    if not target_file.exists():
        raise OpenApiContractError(f"Missing $ref target file: {target_file}")
    return read_pointer(load_yaml(target_file), pointer)


def root_spec() -> dict[str, Any]:
    missing = [name for name in REQUIRED_FILES if not (OPENAPI_DIR / name).exists()]
    if missing:
        raise OpenApiContractError(f"Missing OpenAPI files: {', '.join(missing)}")
    spec = load_yaml(ENTRYPOINT)
    if spec.get("openapi") != "3.1.0":
        raise OpenApiContractError("openapi/aicheck.yaml must declare openapi: 3.1.0")
    return spec


def dereference_path_item(path_item: dict[str, Any]) -> dict[str, Any]:
    if "$ref" in path_item:
        resolved = resolve_ref(str(path_item["$ref"]), base_file=ENTRYPOINT)
        if not isinstance(resolved, dict):
            raise OpenApiContractError(f"Path $ref did not resolve to an object: {path_item['$ref']}")
        return resolved
    return path_item


def parameter_name(parameter: dict[str, Any]) -> str | None:
    if "$ref" in parameter:
        resolved = resolve_ref(str(parameter["$ref"]), base_file=ENTRYPOINT)
        return resolved.get("name") if isinstance(resolved, dict) else None
    return parameter.get("name")


def operation_parameters(operation: dict[str, Any]) -> set[str]:
    return {
        name
        for parameter in operation.get("parameters") or []
        if isinstance(parameter, dict)
        for name in [parameter_name(parameter)]
        if name
    }


def response_json_media(response: dict[str, Any]) -> dict[str, Any]:
    content = response.get("content") or {}
    media = content.get("application/json") or {}
    return media if isinstance(media, dict) else {}


def response_has_example(response: dict[str, Any]) -> bool:
    media = response_json_media(response)
    return "examples" in media or "example" in media


def response_has_schema(response: dict[str, Any]) -> bool:
    media = response_json_media(response)
    return isinstance(media.get("schema"), dict)


def request_body_has_schema(request_body: dict[str, Any]) -> bool:
    content = request_body.get("content") or {}
    media = content.get("application/json") or {}
    return isinstance(media, dict) and isinstance(media.get("schema"), dict)


def resolved_response(response: Any) -> dict[str, Any]:
    if isinstance(response, dict) and "$ref" in response:
        resolved = resolve_ref(str(response["$ref"]), base_file=ENTRYPOINT)
        if not isinstance(resolved, dict):
            raise OpenApiContractError(f"Response $ref did not resolve to object: {response['$ref']}")
        return resolved
    return response if isinstance(response, dict) else {}


def validate_operation(path: str, method: str, operation: dict[str, Any]) -> dict[str, Any]:
    label = f"{method.upper()} {path}"
    operation_id = operation.get("operationId")
    if not operation_id or not OPERATION_ID_RE.match(str(operation_id)):
        raise OpenApiContractError(f"{label} has invalid operationId: {operation_id!r}")
    if not operation.get("security"):
        raise OpenApiContractError(f"{label} must declare bearer security")

    params = operation_parameters(operation)
    for path_param in re.findall(r"{([^}]+)}", path):
        if path_param not in params:
            raise OpenApiContractError(f"{label} missing path parameter: {path_param}")
    if method in {"post", "put", "patch", "delete"} and "Idempotency-Key" not in params:
        raise OpenApiContractError(f"{label} mutation must declare Idempotency-Key")
    if method in {"put", "patch", "delete"} and "If-Match" not in params:
        raise OpenApiContractError(f"{label} update/delete must declare If-Match")
    if method in {"post", "put", "patch"}:
        request_body = operation.get("requestBody")
        if not isinstance(request_body, dict) or request_body.get("required") is not True:
            raise OpenApiContractError(f"{label} mutation must declare required requestBody")
        if not request_body_has_schema(request_body):
            raise OpenApiContractError(f"{label} requestBody must declare an application/json schema")

    responses = operation.get("responses")
    if not isinstance(responses, dict):
        raise OpenApiContractError(f"{label} must declare responses")
    missing_responses = REQUIRED_RESPONSE_CODES - set(map(str, responses.keys()))
    if missing_responses:
        raise OpenApiContractError(f"{label} missing responses: {sorted(missing_responses)}")
    success_response = resolved_response(responses["200"])
    if not response_has_schema(success_response):
        raise OpenApiContractError(f"{label} response 200 must include an application/json schema")
    if not response_has_example(success_response):
        raise OpenApiContractError(f"{label} response 200 must include a success example")
    for code in ["400", "401", "403", "404", "409"]:
        error_response = resolved_response(responses[code])
        if not response_has_schema(error_response):
            raise OpenApiContractError(f"{label} response {code} must include an application/json schema")
        if not response_has_example(error_response):
            raise OpenApiContractError(f"{label} response {code} must include an error example")

    return {
        "operationId": operation_id,
        "method": method.upper(),
        "path": path,
        "tags": operation.get("tags") or [],
    }


def build_contract_index() -> dict[str, Any]:
    spec = root_spec()
    operations: list[dict[str, Any]] = []
    seen_operation_ids: set[str] = set()
    paths = spec.get("paths")
    if not isinstance(paths, dict) or not paths:
        raise OpenApiContractError("openapi/aicheck.yaml must declare paths")

    for path, raw_path_item in sorted(paths.items()):
        if not isinstance(raw_path_item, dict):
            raise OpenApiContractError(f"Path item must be object: {path}")
        path_item = dereference_path_item(raw_path_item)
        for method, operation in sorted(path_item.items()):
            if method not in HTTP_METHODS:
                continue
            if not isinstance(operation, dict):
                raise OpenApiContractError(f"Operation must be object: {method.upper()} {path}")
            entry = validate_operation(path, method, operation)
            if entry["operationId"] in seen_operation_ids:
                raise OpenApiContractError(f"Duplicate operationId: {entry['operationId']}")
            seen_operation_ids.add(entry["operationId"])
            operations.append(entry)

    return {
        "entrypoint": "openapi/aicheck.yaml",
        "operationCount": len(operations),
        "operations": operations,
        "codegenTargets": [
            {
                "name": "frontend-aicheck-client",
                "source": "openapi/aicheck.yaml",
                "target": "frontend/src/api/aicheck/generated/operation-map.ts",
                "recommendedGenerator": "scripts/openapi_contract.py --write-frontend; orval/openapi-typescript can replace this map later",
            }
        ],
    }


def write_index(index: dict[str, Any]) -> None:
    INDEX_PATH.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def ts_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def render_frontend_operation_map(index: dict[str, Any]) -> str:
    entries = []
    for operation in index["operations"]:
        entries.append(
            "  "
            + ts_string(operation["operationId"])
            + ": { method: "
            + ts_string(operation["method"])
            + ", path: "
            + ts_string(operation["path"])
            + ", tags: "
            + json.dumps(operation["tags"], ensure_ascii=False)
            + " }"
        )
    return (
        "/* eslint-disable */\n"
        "// Generated by scripts/openapi_contract.py --write-frontend.\n"
        "// Do not edit by hand.\n\n"
        "export const aicheckOpenApiOperations = {\n"
        + ",\n".join(entries)
        + "\n} as const\n\n"
        "export type AicheckOpenApiOperationId = keyof typeof aicheckOpenApiOperations\n"
    )


def write_frontend_operation_map(index: dict[str, Any]) -> None:
    FRONTEND_OPERATION_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    FRONTEND_OPERATION_MAP_PATH.write_text(render_frontend_operation_map(index), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate AIcheck OpenAPI contract fragments.")
    parser.add_argument("--write-index", action="store_true", help="Write openapi/contract-index.json.")
    parser.add_argument(
        "--write-frontend",
        action="store_true",
        help="Write frontend/src/api/aicheck/generated/operation-map.ts.",
    )
    args = parser.parse_args()
    index = build_contract_index()
    if args.write_index:
        write_index(index)
    if args.write_frontend:
        write_frontend_operation_map(index)
    print(json.dumps({"ok": True, "operationCount": index["operationCount"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
