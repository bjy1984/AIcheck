from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.api.main import app
from apps.api.routes import mock_router, router

REQUEST_PATTERN = re.compile(
    r"request\.(get|post|put|patch|delete)(?:<[^>()]*>)?\s*\(\s*\{.*?url\s*:\s*([`'\"])(.*?)\2",
    re.DOTALL,
)
PARAM_PATTERN = re.compile(r"\$\{[^}]+}|{[^}/]+}")


@dataclass(frozen=True)
class EndpointRef:
    method: str
    path: str
    normalized_path: str
    source: str

    @property
    def key(self) -> tuple[str, str]:
        return self.method, self.normalized_path


@dataclass(frozen=True)
class AuditResult:
    frontend_count: int
    backend_count: int
    missing: list[EndpointRef]
    covered: list[EndpointRef]

    @property
    def ok(self) -> bool:
        return not self.missing


def parse_args() -> argparse.Namespace:
    default_root = Path(__file__).resolve().parents[2] / "frontend" / "src" / "api"
    parser = argparse.ArgumentParser(description="Audit frontend API client paths against FastAPI routes.")
    parser.add_argument("--frontend-api-root", default=str(default_root))
    parser.add_argument(
        "--include",
        action="append",
        default=["aicheck/**/*.ts", "login/**/*.ts"],
        help="Relative glob under frontend API root. Can be passed multiple times.",
    )
    parser.add_argument("--include-mock", action="store_true", help="Include /mock/* endpoints in coverage requirements.")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def normalize_path(path: str) -> str:
    path = path.split("?", 1)[0].strip()
    if not path.startswith("/"):
        path = f"/{path}"
    path = re.sub(r"/+", "/", path)
    if len(path) > 1:
        path = path.rstrip("/")
    return PARAM_PATTERN.sub("{}", path)


def iter_included_files(root: Path, patterns: Iterable[str]) -> list[Path]:
    files: dict[Path, None] = {}
    for pattern in patterns:
        for path in root.glob(pattern):
            if path.is_file() and path.suffix == ".ts" and not path.name.endswith(".d.ts"):
                files[path] = None
    return sorted(files)


def extract_frontend_endpoints(root: Path, patterns: Iterable[str], *, include_mock: bool = False) -> list[EndpointRef]:
    endpoints: list[EndpointRef] = []
    for path in iter_included_files(root, patterns):
        text = path.read_text(encoding="utf-8")
        for match in REQUEST_PATTERN.finditer(text):
            method = match.group(1).upper()
            raw_path = match.group(3)
            if not include_mock and raw_path.startswith("/mock/"):
                continue
            endpoints.append(
                EndpointRef(
                    method=method,
                    path=raw_path,
                    normalized_path=normalize_path(raw_path),
                    source=str(path.relative_to(root)),
                )
            )
    return sorted(set(endpoints), key=lambda item: (item.source, item.method, item.normalized_path))


def backend_route_keys() -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for route in app.routes:
        methods = getattr(route, "methods", set()) or set()
        path = getattr(route, "path", "")
        if not path:
            continue
        for method in methods:
            method = method.upper()
            if method in {"HEAD", "OPTIONS"}:
                continue
            keys.add((method, normalize_path(path)))
    for api_router, prefixes in ((router, ("", "/api")), (mock_router, ("", "/api"))):
        for route in expanded_routes(api_router):
            methods = getattr(route, "methods", set()) or set()
            path = getattr(route, "path", "")
            if not path:
                continue
            for prefix in prefixes:
                full_path = f"{prefix}{path}"
                for method in methods:
                    method = method.upper()
                    if method in {"HEAD", "OPTIONS"}:
                        continue
                    keys.add((method, normalize_path(full_path)))
    return keys


def route_matches(frontend_key: tuple[str, str], backend_keys: set[tuple[str, str]]) -> bool:
    method, frontend_path = frontend_key
    for backend_method, backend_path in backend_keys:
        if backend_method != method:
            continue
        if path_pattern_matches(backend_path, frontend_path):
            return True
    return False


def path_pattern_matches(backend_path: str, frontend_path: str) -> bool:
    backend_parts = backend_path.strip("/").split("/") if backend_path != "/" else []
    frontend_parts = frontend_path.strip("/").split("/") if frontend_path != "/" else []
    if len(backend_parts) != len(frontend_parts):
        return False
    return all(backend == "{}" or frontend == "{}" or backend == frontend for backend, frontend in zip(backend_parts, frontend_parts))


def expanded_routes(api_router: Any) -> list[Any]:
    """展开 include_router 挂进来的子路由。

    FastAPI 0.138 的 include_router 是惰性的：router.routes 里留下的是没有 .path
    的 _IncludedRouter 占位。原先这里 `if not path: continue` 会把它整段静默跳过——
    于是拆分出去的端点在契约审计眼里等于「后端没有」，前端调用被报成缺失。

    静默跳过比报错更贵：审计工具自己漏看了东西，却照常输出一份「已审计」的结论。
    """
    collected: list[Any] = []
    for route in getattr(api_router, "routes", []) or []:
        if getattr(route, "path", ""):
            collected.append(route)
            continue
        # FastAPI 0.138 的占位类把子路由挂在 original_router 上（不是 router）
        nested = getattr(route, "original_router", None) or getattr(route, "router", None)
        if nested is not None:
            collected.extend(expanded_routes(nested))
    return collected


def audit(frontend_root: Path, patterns: Iterable[str], *, include_mock: bool = False) -> AuditResult:
    frontend = extract_frontend_endpoints(frontend_root, patterns, include_mock=include_mock)
    backend = backend_route_keys()
    missing = [item for item in frontend if not route_matches(item.key, backend)]
    covered = [item for item in frontend if route_matches(item.key, backend)]
    return AuditResult(
        frontend_count=len(frontend),
        backend_count=len(backend),
        missing=missing,
        covered=covered,
    )


def print_result(result: AuditResult, *, as_json: bool) -> None:
    if as_json:
        print(
            json.dumps(
                {
                    "ok": result.ok,
                    "frontendCount": result.frontend_count,
                    "backendCount": result.backend_count,
                    "missing": [asdict(item) for item in result.missing],
                    "covered": [asdict(item) for item in result.covered],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    print(f"Frontend endpoints: {result.frontend_count}")
    print(f"Backend route keys: {result.backend_count}")
    if result.ok:
        print("Missing endpoints: 0")
        return
    print(f"Missing endpoints: {len(result.missing)}")
    for item in result.missing:
        print(f"- {item.method} {item.path} ({item.source})")


def main() -> int:
    args = parse_args()
    result = audit(Path(args.frontend_api_root), args.include, include_mock=args.include_mock)
    print_result(result, as_json=args.json)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
